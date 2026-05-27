#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 白号/黑号检测 API
"""
import asyncio
import random
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from routes import get_db, get_current_user
from models import User, PhoneRecord
from demo import MoutaiClient, generate_h5_did, generate_h5_start_id, generate_bs_device_id

router = APIRouter(tags=["白号/黑号"])


def _build_client(phone: str, db: Session) -> MoutaiClient:
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


def _detect_account_type(phone: str, db: Session) -> dict:
    """检测单个账号白号/黑号"""
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record or not record.logged_in:
        return {'account_type': '', 'message': '未登录'}
    client = _build_client(phone, db)
    item_code = record.item_code or 'IMTP1000313'
    spu_id = record.item_name or item_code
    detail = client.auto_fetch_item_details(item_code=item_code, spu_id=spu_id)
    sku_id = detail.get('default_sku_id', '741')
    item_code_rush = detail.get('item_code_from_api', '1001017')
    act_id = detail.get('activity_id', '82107')
    result = client.rush_purchase(item_code=item_code_rush, sku_id=sku_id,
                                  item_priority_act_id=act_id, amount='1')
    code = result.get('code')
    msg = result.get('message', '')
    if code == 2000:
        return {'account_type': record.account_type or '', 'message': '抢购成功，跳过判断'}
    elif '人数多' in msg or '库存不足' in msg or code in (4031, 4099):
        record.account_type = 'black'
        return {'account_type': 'black', 'message': msg}
    elif '活动未开始' in msg or '未开始' in msg:
        record.account_type = 'white'
        return {'account_type': 'white', 'message': msg}
    return {'account_type': record.account_type or '', 'message': msg}


@router.post("/api/check_account_type")
async def check_account_type_main(request: Request, user: User = Depends(get_current_user),
                                  db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        records = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    else:
        records = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True, PhoneRecord.user_id == user.id).all()
    if not records:
        return JSONResponse(content={'status': 'success', 'message': '无已登录账号', 'results': {}})

    results = {}
    for i, rec in enumerate(records):
        if i > 0:
            await asyncio.sleep(random.uniform(0.05, 0.5))
        try:
            r = _detect_account_type(rec.phone, db)
            results[rec.phone] = r
        except Exception as e:
            results[rec.phone] = {'account_type': rec.account_type or '', 'message': f'异常: {str(e)[:50]}'}

    db.commit()
    white_count = sum(1 for v in results.values() if v['account_type'] == 'white')
    black_count = sum(1 for v in results.values() if v['account_type'] == 'black')
    return JSONResponse(content={
        'status': 'success', 'message': f'检测完成: 白号{white_count}个, 黑号{black_count}个',
        'results': results
    })


@router.post("/api/check_account_type_single")
async def check_account_type_single(request: Request, user: User = Depends(get_current_user),
                                    db: Session = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    if not phone:
        return JSONResponse(content={'status': 'error', 'message': '缺少手机号'}, status_code=400)
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '账号不存在'}, status_code=404)
    if not record.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '账号未登录，无法判断'}, status_code=400)
    try:
        r = _detect_account_type(phone, db)
        db.commit()
        return JSONResponse(content={'status': 'success', **r})
    except Exception as e:
        return JSONResponse(content={'status': 'error', 'message': f'异常: {str(e)}'}, status_code=500)


@router.post("/api/clear_black_accounts")
async def clear_black_accounts(user: User = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        black_records = db.query(PhoneRecord).filter(PhoneRecord.account_type == 'black').all()
    else:
        black_records = db.query(PhoneRecord).filter(
            PhoneRecord.account_type == 'black', PhoneRecord.user_id == user.id).all()
    deleted_phones = []
    for rec in black_records:
        deleted_phones.append(rec.phone)
        db.delete(rec)
    db.commit()
    return JSONResponse(content={
        'status': 'success', 'message': f'已清除 {len(deleted_phones)} 个黑号',
        'deleted_count': len(deleted_phones), 'deleted_phones': deleted_phones
    })
