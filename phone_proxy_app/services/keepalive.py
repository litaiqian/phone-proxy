#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 登录保鲜后台任务
异步协程 + 线程混合，支持代理IP轮换
"""
import os
import json
import time
import random
import datetime
import asyncio
import threading

from config import BASEDIR, Config
from core.database import SessionLocal, get_user_proxy
from models import User, UserConfig, PhoneRecord
from services.proxy_manager import proxy_manager

# 导入 MoutaiClient 和工具函数（从 demo.py）
from demo import (
    MoutaiClient, _get, _post, _load_accounts, _load_account_to_client,
    BASE_URL
)


def check_login_validity(phone: str) -> bool:
    """检查单一账号登录有效性"""
    accounts_file = os.path.join(BASEDIR, 'iplala_accounts.json')
    try:
        accounts = _load_accounts(accounts_file)
    except Exception:
        return False
    acc = next((a for a in accounts if a.get("mobile") == phone), None)
    if not acc:
        return False
    try:
        client = MoutaiClient(bs_dvid=acc.get('bs-dvid', ''))
        _load_account_to_client(acc, client)
        headers = client._app_headers(need_sign=False)
        resp = _get(f"{BASE_URL}/xhr/front/user/info", headers=headers)
        data = resp.json()
        return data.get("code") == 2000
    except Exception:
        return False


def update_login_status(phone: str, is_valid: bool, db):
    """更新数据库登录状态"""
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record:
        if is_valid:
            record.logged_in = True
        else:
            record.logged_in = False
            record.token = ""
            record.cookie = ""
            record.user_id_ext = ""
        record.last_updated = datetime.datetime.utcnow()
        db.commit()


def save_account_to_json(phone: str, client: MoutaiClient):
    """保存账号凭证到 iplala_accounts.json"""
    accounts_file = os.path.join(BASEDIR, 'iplala_accounts.json')
    accounts = []
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
    idx = next((i for i, acc in enumerate(accounts) if acc.get("mobile") == phone), -1)
    acc_data = {
        "mobile": phone,
        "userid": client.user_id,
        "token": client.token,
        "cookie": client.cookie,
        "mt-device-id": client.mt_device_id,
        "device-id": client.raw_device_id,
        "user-agent": client.user_agent,
        "webview-ua": client.webview_ua,
        "mt-r": client.mt_r,
        "mt-sn": client.mt_sn,
        "h5-did": client.h5_did,
        "h5-start-id": client.h5_start_id,
        "bs-device-id": client.bs_device_id,
        "loginTime": datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    }
    if idx >= 0:
        accounts[idx] = {**accounts[idx], **acc_data}
    else:
        accounts.append(acc_data)
    with open(accounts_file, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def login_keepalive_worker():
    """后台保鲜线程：每10-50分钟随机检查一次所有已登录账号"""
    while True:
        with SessionLocal() as db:
            now = datetime.datetime.now()
            current_hour = now.hour
            if current_hour >= 22 or current_hour < 6:
                next_refresh = now.replace(hour=6, minute=0, second=0, microsecond=0)
                if now.hour >= 22:
                    next_refresh += datetime.timedelta(days=1)
                sleep_seconds = (next_refresh - now).total_seconds()
                print(f"[保鲜] 夜间休息，睡眠 {sleep_seconds/3600:.1f} 小时")
                time.sleep(sleep_seconds)
                continue
            sleep_seconds = random.randint(600, 2900)
            time.sleep(sleep_seconds)
            records = db.query(PhoneRecord).all()
            for rec in records:
                if not rec.logged_in:
                    continue
                valid = check_login_validity(rec.phone)
                if not valid:
                    print(f"[保鲜] {rec.phone} 登录失效")
                    update_login_status(rec.phone, False, db)
                else:
                    rec.last_updated = datetime.datetime.utcnow()


def start_background_tasks():
    """启动所有后台任务线程"""
    t1 = threading.Thread(target=login_keepalive_worker, daemon=True)
    t1.start()
