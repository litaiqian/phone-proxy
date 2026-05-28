#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 绑定账号（公开访问 + 上传者参数）
"""
import os
import datetime
import re
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from routes import get_db, get_current_user
from models import User, PhoneRecord
from core.database import SessionLocal
from config import BASEDIR

router = APIRouter(tags=["绑定账号"])

# 从 demo.py 导入
from demo import MoutaiClient
from services.keepalive import save_account_to_json


def build_client_from_record(phone: str, db: Session) -> MoutaiClient:
    """从数据库记录重建 MoutaiClient"""
    from demo import generate_h5_did, generate_h5_start_id, generate_bs_device_id
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
    """发送验证码实现"""
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


@router.get("/bind_account", response_class=HTMLResponse)
async def bind_account_page(request: Request, uploader: str = ""):
    flash_messages = request.session.pop("_flash", [])
    user = None
    user_id = request.session.get("user_id")
    if user_id:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()
    return request.app.state.templates.TemplateResponse(request, "bind_account.html", {
        "user": user, "uploader": uploader, "flash_messages": flash_messages
    })


@router.post("/api/bind_account/send_code")
async def bind_account_send_code(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    uploader = data.get('uploader', '').strip()
    if not phone or len(phone) != 11:
        return JSONResponse(content={'status': 'error', 'message': '手机号格式无效'}, status_code=400)

    uploader_user = db.query(User).filter(User.username == uploader).first() if uploader else None
    if not uploader_user:
        uploader_user = db.query(User).filter(User.username == "admin").first()
    uploader_id = uploader_user.id if uploader_user else 1

    existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if existing and existing.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '该手机号已被绑定'}, status_code=400)
    if existing and existing.user_id != uploader_id:
        return JSONResponse(content={'status': 'error', 'message': '该手机号已被其他用户绑定'}, status_code=403)

    success = send_verification_code_impl(phone, db)
    if success:
        return JSONResponse(content={'status': 'success', 'message': '验证码已发送'})
    return JSONResponse(content={'status': 'error', 'message': '发送失败，请稍后重试'}, status_code=400)


@router.post("/api/bind_account/submit_code")
async def bind_account_submit_code(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    item_code = data.get('item_code', 'IMTP1000313')
    amount = data.get('amount', 2)
    uploader = data.get('uploader', '').strip()

    if not phone or len(phone) != 11:
        return JSONResponse(content={'status': 'error', 'message': '手机号格式无效'}, status_code=400)
    if not code:
        return JSONResponse(content={'status': 'error', 'message': '验证码不能为空'}, status_code=400)

    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and record.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '该手机号已登录'}, status_code=400)

    uploader_user = db.query(User).filter(User.username == uploader).first() if uploader else None
    if not uploader_user:
        uploader_user = db.query(User).filter(User.username == "admin").first()
    owner_id = uploader_user.id if uploader_user else 1

    if record and record.user_id != owner_id:
        return JSONResponse(content={'status': 'error', 'message': '该手机号已被其他用户绑定'}, status_code=403)

    if not record:
        record = PhoneRecord(team='', phone=phone, user_id=owner_id, uploaded_by=owner_id,
                             uploader_name=uploader, item_code=item_code, amount=amount)
        db.add(record)
        db.commit()
    else:
        record.item_code = item_code
        record.amount = amount
        record.uploader_name = uploader
        record.uploaded_by = owner_id
        db.commit()

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

        account_type_msg = ''
        try:
            item_code_spu = record.item_code or 'IMTP1000313'
            detail = client.auto_fetch_item_details(item_code=item_code_spu, spu_id=item_code_spu)
            sku_id = detail.get('default_sku_id', '741')
            item_code_rush = detail.get('item_code_from_api', '1001017')
            act_id = detail.get('activity_id', '82107')
            rush_result = client.rush_purchase(item_code=item_code_rush, sku_id=sku_id,
                                               item_priority_act_id=act_id, amount='1')
            r_code = rush_result.get('code')
            r_msg = rush_result.get('message', '')
            if '人数多' in r_msg or '库存不足' in r_msg or r_code in (4031, 4099):
                record.account_type = 'black'
                account_type_msg = '（黑号）'
            elif '活动未开始' in r_msg or '未开始' in r_msg:
                record.account_type = 'white'
                account_type_msg = '（白号）'
            db.commit()
        except Exception as e:
            print(f'[绑定检测] {phone} 白号/黑号检测失败: {e}')

        return JSONResponse(content={
            'status': 'success', 'message': f'绑定成功{account_type_msg}',
            'account_type': record.account_type
        })
    else:
        return JSONResponse(content={
            'status': 'error', 'message': f'登录失败: {result.get("message", "未知错误")}'
        }, status_code=400)


@router.get("/api/bind_account/list")
async def bind_account_list(db: Session = Depends(get_db)):
    records = db.query(PhoneRecord).order_by(PhoneRecord.last_updated.desc()).limit(100).all()
    record_list = []
    for rec in records:
        login_time_str = rec.login_time.strftime('%Y-%m-%d %H:%M:%S') if rec.login_time else None
        record_list.append({
            'phone': rec.phone, 'logged_in': rec.logged_in, 'token': bool(rec.token),
            'item_code': rec.item_code or 'IMTP1000313', 'sku_id': rec.sku_id or '741',
            'activity_id': rec.activity_id or '82143', 'amount': rec.amount or 2,
            'login_time': login_time_str, 'uploader': rec.uploader_name or ''
        })
    return JSONResponse(content={'records': record_list})
