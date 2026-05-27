#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 账号管理 API（上传 / 发码 / 登录 / 批量 / 清空）
"""
import os
import re
import time
import random
import datetime
import threading
from fastapi import APIRouter, Request, File, UploadFile, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from werkzeug.utils import secure_filename
import pandas as pd

from routes import get_db, get_current_user
from models import User, PhoneRecord
from config import UPLOAD_FOLDER, BASEDIR, Config

from demo import MoutaiClient, generate_h5_did, generate_h5_start_id, generate_bs_device_id
from services.keepalive import save_account_to_json

router = APIRouter(tags=["账号管理"])


def build_client_from_record(phone: str, db: Session) -> MoutaiClient:
    """从数据库记录重建 MoutaiClient"""
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        raise ValueError(f"手机号 {phone} 不存在")
    if record.raw_device_id:
        client = MoutaiClient(
            android_id=record.raw_device_id[:16] if len(record.raw_device_id) >= 16 else "",
            bs_dvid=record.mt_device_id.replace("clips_", "") if record.mt_device_id else ""
        )
        client.token = record.token or ""
        client.cookie = record.cookie or ""
        client.user_id = record.user_id_ext or ""
        client.mt_device_id = record.mt_device_id or ""
        client.raw_device_id = record.raw_device_id or ""
        client.h5_did = record.h5_did or generate_h5_did()
        client.h5_start_id = record.h5_start_id or generate_h5_start_id()
        client.bs_device_id = record.bs_device_id or generate_bs_device_id(client.h5_did)
    else:
        client = MoutaiClient()
        record.raw_device_id = client.raw_device_id
        record.mt_device_id = client.mt_device_id
        record.h5_did = client.h5_did
        record.h5_start_id = client.h5_start_id
        record.bs_device_id = client.bs_device_id
        db.commit()
    return client


def send_verification_code_impl(phone: str, db: Session) -> bool:
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and record.logged_in:
        return False
    client = build_client_from_record(phone, db)
    result = client.send_vcode(phone)
    success = result.get("code") == 2000
    if success and record:
        record.code_sent = True
        record.last_updated = datetime.datetime.utcnow()
        db.commit()
    return success


@router.get("/api/sample_products")
async def sample_products(user: User = Depends(get_current_user)):
    products = [
        {"name": "茅台飞天53度 500ml", "price": "1499元"},
        {"name": "茅台生肖酒 虎年", "price": "2499元"},
        {"name": "茅台王子酒 酱香经典", "price": "398元"},
        {"name": "茅台迎宾酒 中国红", "price": "168元"},
    ]
    return JSONResponse(content=products)


@router.post("/api/upload")
async def upload_excel(request: Request, file: UploadFile = File(...),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        return JSONResponse(content={'status': 'error', 'message': '文件格式错误，需要Excel文件'}, status_code=400)
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    content = await file.read()
    with open(filepath, 'wb') as f:
        f.write(content)
    try:
        df_with_header = pd.read_excel(filepath, header=0, dtype=str, engine='openpyxl')
        has_standard_headers = False
        if len(df_with_header.columns) >= 2:
            col_names = [str(col).strip().lower() for col in df_with_header.columns]
            if any(field in col_names for field in ['团队', '手机号', 'phone', 'team']):
                has_standard_headers = True
        imported = 0
        skipped = 0

        def _import_row(team, raw_phone, item_name, amount_str):
            if '.' in raw_phone and raw_phone.endswith('.0'):
                raw_phone = raw_phone[:-2]
            phone = re.sub(r'[\s\-\(\)]+', '', raw_phone)
            if not phone or not phone.isdigit() or len(phone) < 7:
                return 0, 1
            item_code_val = item_name if item_name and re.match(r'^[A-Za-z]\w{4,}$', item_name) else 'IMTP1000313'
            try:
                amount = int(amount_str)
                if amount < 1: amount = 1
            except Exception:
                amount = 1
            existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
            if not existing:
                rec = PhoneRecord(team=team, phone=phone, user_id=user.id, uploaded_by=user.id,
                                  item_name=item_name, item_code=item_code_val, amount=amount)
                db.add(rec)
                return 1, 0
            return 0, 1

        if has_standard_headers:
            df = df_with_header
            column_mapping = {}
            for col in df.columns:
                col_lower = str(col).strip().lower()
                if col_lower in ['团队', 'team']:
                    column_mapping[col] = 'team'
                elif col_lower in ['手机号', 'phone', '手机号码', '电话']:
                    column_mapping[col] = 'phone'
                elif col_lower in ['商品编码', '商品名称', 'item_name', '商品编号']:
                    column_mapping[col] = 'item_name'
                elif col_lower in ['商品id', 'item_code', 'spu_id']:
                    column_mapping[col] = 'item_code'
                elif col_lower in ['数量', 'amount', 'count', '采购数量']:
                    column_mapping[col] = 'amount'
            if column_mapping:
                df = df.rename(columns=column_mapping)
            for _, row in df.iterrows():
                team = str(row.get('team', '')).strip() if pd.notna(row.get('team', '')) else ''
                raw_phone = str(row.get('phone', '')).strip() if pd.notna(row.get('phone', '')) else ''
                item_name = str(row.get('item_name', '')).strip() if pd.notna(row.get('item_name', '')) else ''
                amount_str = str(row.get('amount', '1')).strip() if pd.notna(row.get('amount', '')) else '1'
                imp, sk = _import_row(team, raw_phone, item_name, amount_str)
                imported += imp
                skipped += sk
        else:
            df_no_header = pd.read_excel(filepath, header=None, dtype=str, engine='openpyxl')
            for _, row in df_no_header.iterrows():
                team = str(row[0]).strip() if len(row) > 0 and pd.notna(row[0]) else ''
                raw_phone = str(row[1]).strip() if len(row) > 1 and pd.notna(row[1]) else ''
                item_name = str(row[2]).strip() if len(row) > 2 and pd.notna(row[2]) else ''
                amount_str = str(row[3]).strip() if len(row) > 3 and pd.notna(row[3]) else '1'
                imp, sk = _import_row(team, raw_phone, item_name, amount_str)
                imported += imp
                skipped += sk

        db.commit()
        msg = f'成功导入 {imported} 条新手机号'
        if skipped:
            msg += f'，跳过 {skipped} 条'
        return JSONResponse(content={'status': 'success', 'message': msg})
    except Exception as e:
        return JSONResponse(content={'status': 'error', 'message': f'解析失败: {str(e)}'}, status_code=400)


@router.post("/api/send_code")
async def api_send_code(request: Request, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone,
                                          PhoneRecord.user_id == user.id).first()
    if not record:
        raise HTTPException(status_code=403, detail="无权限")
    if record.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '账号已登录'}, status_code=400)
    success = send_verification_code_impl(phone, db)
    if success:
        return JSONResponse(content={'status': 'success', 'message': '验证码已发送'})
    return JSONResponse(content={'status': 'error', 'message': '发送失败'}, status_code=400)


@router.post("/api/submit_code")
async def api_submit_code(request: Request, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone,
                                          PhoneRecord.user_id == user.id).first()
    if not record:
        raise HTTPException(status_code=403, detail="无权限")
    if record.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '账号已登录'}, status_code=400)
    client = build_client_from_record(phone, db)
    result = client.login(phone, code)
    record.user_agent = client.user_agent
    record.webview_ua = client.webview_ua
    record.mt_r = client.mt_r
    record.mt_sn = client.mt_sn
    if result.get("code") == 2000:
        record.token = client.token
        record.cookie = client.cookie
        record.user_id_ext = client.user_id
        record.logged_in = True
        record.last_updated = datetime.datetime.utcnow()
        record.login_time = datetime.datetime.now()
        db.commit()
        save_account_to_json(phone, client)
        return JSONResponse(content={'status': 'success', 'message': '登录成功'})
    return JSONResponse(content={'status': 'error',
                                  'message': f'登录失败: {result.get("message")}'}, status_code=400)


@router.post("/api/receive_sms")
async def receive_sms(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    if not phone or not code:
        raise HTTPException(status_code=400, detail="参数不完整")
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '手机号未在系统中'}, status_code=404)
    if record.logged_in:
        return JSONResponse(content={'status': 'success', 'message': '账号已登录'})
    client = build_client_from_record(phone, db)
    record.user_agent = client.user_agent
    record.webview_ua = client.webview_ua
    record.mt_r = client.mt_r
    record.mt_sn = client.mt_sn
    result = client.login(phone, code)
    if result.get("code") == 2000:
        record.token = client.token
        record.cookie = client.cookie
        record.user_id_ext = client.user_id
        record.logged_in = True
        record.last_updated = datetime.datetime.utcnow()
        record.login_time = datetime.datetime.now()
        db.commit()
        save_account_to_json(phone, client)
        return JSONResponse(content={'status': 'success', 'message': '自动登录成功'})
    return JSONResponse(content={'status': 'error',
                                  'message': f'登录失败: {result.get("message")}'}, status_code=400)


@router.get("/api/phone_status/{phone}")
async def phone_status(phone: str, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone,
                                          PhoneRecord.user_id == user.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="无权限")
    uploader = db.query(User).filter(User.id == record.uploaded_by).first()
    return JSONResponse(content={
        'phone': record.phone, 'team': record.team,
        'uploaded_by': uploader.username if uploader else '未知',
        'code_sent': record.code_sent, 'logged_in': record.logged_in,
        'balance': record.balance, 'bid_result': record.bid_result,
        'last_updated': record.last_updated.isoformat() if record.last_updated else ''
    })


@router.post("/api/batch_send_code")
async def batch_send_code(request: Request, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    data = await request.json()
    min_delay = int(data.get('min_delay', 10))
    max_delay = int(data.get('max_delay', 20))
    user_id = user.id
    phones = [r.phone for r in db.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all()]
    if not phones:
        return JSONResponse(content={'status': 'error', 'message': '无号码'}, status_code=400)

    def batch_task():
        from core.database import SessionLocal as SL
        with SL() as db2:
            all_records = db2.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all()
            pending_phones = [rec.phone for rec in all_records if not rec.logged_in]
            for phone in pending_phones:
                send_verification_code_impl(phone, db2)
                time.sleep(random.randint(min_delay, max_delay))

    threading.Thread(target=batch_task, daemon=True).start()
    pending_count = sum(1 for r in db.query(PhoneRecord).filter(
        PhoneRecord.user_id == user_id).all() if not r.logged_in)
    return JSONResponse(content={
        'status': 'success',
        'message': f'批量发送已启动，共{len(phones)}个账号，{pending_count}个需要发送'
    })


@router.post("/api/clear_all_records")
async def clear_all_records(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        from config import QRCODE_FOLDER as QF
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
        for rec in records:
            qrcode_path = os.path.join(QF, f"{rec.phone}.png")
            if os.path.exists(qrcode_path):
                os.remove(qrcode_path)
        db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).delete()
        db.commit()
        return JSONResponse(content={'status': 'success', 'message': '已清空所有账号及二维码'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
