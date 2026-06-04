#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 杂项 API（刷新登录 / 查询结果 / 健康检查 / 暂停恢复 / 代理开关）
"""
import os
import json
import asyncio
import random
import datetime
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

router = APIRouter(tags=["杂项"])

from routes import get_db, get_current_user  # noqa: E402
from moutai_automation import User, PhoneRecord, get_user_config, get_user_proxy, Config, BASEDIR, build_credentials_from_db, check_login_validity_async, update_login_status, _get_login_status_desc  # noqa: E402
from demo import MoutaiClient  # noqa: E402
from demo import generate_h5_did, generate_h5_start_id, generate_bs_device_id  # noqa: E402


def build_client_from_record(phone: str, db: Session) -> MoutaiClient:
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


def sync_login_time_from_json(phone: str, db: Session):
    accounts_file = os.path.join(BASEDIR, 'iplala_accounts.json')
    if not os.path.exists(accounts_file):
        return
    try:
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
        acc = next((a for a in accounts if a.get("mobile") == phone), None)
        if not acc or not acc.get("loginTime"):
            return
        login_time_str = acc["loginTime"]
        login_time = datetime.datetime.strptime(login_time_str, "%Y/%m/%d %H:%M:%S")
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        if record:
            record.login_time = login_time
            db.commit()
    except Exception as e:
        pass


@router.post("/api/refresh_login")
async def refresh_login(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        records = db.query(PhoneRecord).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()

    up = get_user_proxy(user.id, db)
    proxy_enabled = up.proxy_enabled if up else False
    proxy_api_url = up.proxy_url if up else ''

    phones = [r.phone for r in records]
    results = {}
    accounts_file = os.path.join(BASEDIR, 'iplala_accounts.json')
    try:
        accounts = _load_accounts(accounts_file)
    except Exception:
        accounts = []

    for i, phone in enumerate(phones):
        if i > 0:
            await asyncio.sleep(random.uniform(0.05, 0.5))
        try:
            record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
            acc = next((a for a in accounts if a.get("mobile") == phone), None)

            if not acc:
                status_desc = 'never'
                valid = False
                if record:
                    record.logged_in = False
                    record.last_updated = datetime.datetime.utcnow()
                    db.commit()
            else:
                current_proxy = ''
                if proxy_enabled:
                    from moutai_automation import _alloc_proxy_for_client
                    current_proxy = await _alloc_proxy_for_client(proxy_api_url)

                try:
                    client = MoutaiClient(bs_dvid=acc.get('bs-dvid', ''))
                    client.proxy = current_proxy
                    _load_account_to_client(acc, client)
                    headers = client._app_headers(need_sign=False)
                    resp = _get(f"{BASE_URL}/xhr/front/user/info", headers=headers, proxy=current_proxy)
                    data = resp.json()

                    if data.get("code") == 2000:
                        status_desc = 'success'
                        valid = True
                        if record:
                            record.logged_in = True
                            record.token = acc.get('token', '')
                            record.cookie = acc.get('cookie', '')
                            record.user_id_ext = acc.get('userid', '')
                            record.last_updated = datetime.datetime.utcnow()
                            db.commit()
                    else:
                        status_desc = 'offline'
                        valid = False
                        if record:
                            record.logged_in = False
                            record.last_updated = datetime.datetime.utcnow()
                            db.commit()
                except Exception as e:
                    status_desc = 'offline'
                    valid = False
                    if record:
                        record.logged_in = False
                        record.last_updated = datetime.datetime.utcnow()
                        db.commit()

            sync_login_time_from_json(phone, db)
        except Exception as e:
            valid = False
            status_desc = 'never'

        results[phone] = {
            'valid': valid, 'status_desc': status_desc,
            'account_type': record.account_type if record else '',
            'proxy_ip': current_proxy if 'current_proxy' in dir() else ''
        }

    return JSONResponse(content={'status': 'success', 'results': results})


@router.post("/api/query_bid_results")
async def query_bid_results(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    results = {}
    for rec in records:
        if not rec.logged_in or not rec.token:
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
            continue
        try:
            client = build_client_from_record(rec.phone, db)
            orders = client.query_order_list()
            winning = [o for o in orders if o.get("status") in (1, 2, 3)]
            if winning:
                bid_str = f"中奖-{winning[0].get('itemName', '商品')}"
                rec.bid_result = bid_str
                rec.balance = winning[0].get("totalAmount", "")
            else:
                rec.bid_result = "未中奖"
            db.commit()
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
        except Exception:
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
    return JSONResponse(content={'status': 'success', 'results': results})


@router.get("/api/health")
async def health_check():
    return {"status": "ok", "time": datetime.datetime.now().isoformat()}


@router.post("/api/pause_rush")
async def pause_rush(request: Request, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    cfg.rush_paused = 1
    db.commit()
    return JSONResponse(content={'status': 'success', 'rush_paused': 1})


@router.post("/api/resume_rush")
async def resume_rush(request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    cfg.rush_paused = 0
    db.commit()
    return JSONResponse(content={'status': 'success', 'rush_paused': 0})


@router.get("/api/rush_status")
async def rush_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    up = get_user_proxy(user.id, db)
    paused = getattr(cfg, 'rush_paused', 0)
    return JSONResponse(content={'rush_paused': paused, 'proxy_enabled': up.proxy_enabled})


@router.post("/api/toggle_proxy")
async def toggle_proxy(request: Request, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    data = await request.json()
    enabled = bool(data.get('enabled', False))
    up = get_user_proxy(user.id, db)
    up.proxy_enabled = enabled
    db.commit()
    return JSONResponse(content={'status': 'success', 'proxy_enabled': enabled})
