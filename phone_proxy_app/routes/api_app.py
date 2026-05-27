#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 养猫 App API（Bearer Token 认证）
"""

import uuid
import datetime
import os
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash, check_password_hash

from routes import get_db
from models import User, PhoneRecord

router = APIRouter(tags=["养猫App"])
security = HTTPBearer(auto_error=False)

# 简易内存 token 存储: token -> user_id （服务重启后丢失，后续可迁移到 DB）
_token_store: dict = {}


def get_app_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Bearer Token 认证依赖"""
    if not credentials:
        raise HTTPException(status_code=401, detail="未提供令牌")
    token = credentials.credentials
    user_id = _token_store.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def _issue_token(user_id: int) -> str:
    """签发 token"""
    token = uuid.uuid4().hex
    _token_store[token] = user_id
    return token


# ===================== 注册 =====================
@router.post("/api/app/register")
async def app_register(request: Request, db: Session = Depends(get_db)):
    """App 注册：手机号/用户名（二选一）+ 密码 → 写入 User 表，返回 token
    自动识别：全数字11位 → 手机号注册；否则 → 用户名注册
    密码要求：必须包含字母（大写或小写）+ 数字"""
    import re
    data = await request.json()
    login_id = (data.get('login_id') or '').strip()
    password = (data.get('password') or '').strip()
    ref_code = (data.get('ref_code') or '').strip()

    if not login_id or not password:
        return JSONResponse(content={'ok': False, 'error': '用户名/手机号和密码不能为空'})
    if len(password) < 6:
        return JSONResponse(content={'ok': False, 'error': '密码至少6位'})

    # 密码必须包含字母+数字
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not has_letter or not has_digit:
        return JSONResponse(content={'ok': False, 'error': '密码必须包含字母和数字'})

    # 自动识别：全数字 = 手机号；否则 = 用户名
    is_phone = login_id.isdigit() and len(login_id) >= 8

    if is_phone:
        # 手机号注册
        if len(login_id) != 11:
            return JSONResponse(content={'ok': False, 'error': '手机号格式不正确（需11位）'})
        if db.query(User).filter(User.phone == login_id).first():
            return JSONResponse(content={'ok': False, 'error': '手机号已注册'})
        # 检查是否已有相同数字作为用户名
        if db.query(User).filter(User.username == login_id).first():
            return JSONResponse(content={'ok': False, 'error': '该号码已注册'})
        username = login_id  # 手机号注册时用户名也用手机号
        phone = login_id
    else:
        # 用户名注册
        if len(login_id) < 2:
            return JSONResponse(content={'ok': False, 'error': '用户名至少2位'})
        if db.query(User).filter(User.username == login_id).first():
            return JSONResponse(content={'ok': False, 'error': '用户名已存在'})
        username = login_id
        phone = None

    user = User(
        username=username,
        phone=phone,
        password_hash=generate_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = _issue_token(user.id)
    return JSONResponse(content={
        'ok': True, 'token': token,
        'user_id': str(user.id), 'username': user.username,
        'phone': user.phone
    })


# ===================== 登录 =====================
@router.post("/api/app/login")
async def app_login(request: Request, db: Session = Depends(get_db)):
    """App 登录：手机号或用户名 + 密码 → 返回 token
    错误限制：连续3次错 → 冻结1小时；当日累计5次错 → 冻结12小时"""
    import datetime as dt
    data = await request.json()
    login_id = (data.get('username') or '').strip()  # 可以是用户名或手机号
    password = (data.get('password') or '').strip()

    if not login_id or not password:
        return JSONResponse(content={'ok': False, 'error': '请输入账号和密码'})

    # 支持手机号或用户名登录
    user = db.query(User).filter(
        (User.username == login_id) | (User.phone == login_id)
    ).first()

    if not user:
        return JSONResponse(content={'ok': False, 'error': '账号不存在'})

    now = dt.datetime.utcnow()

    # 检查是否冻结
    if user.frozen_until and now < user.frozen_until:
        remain = int((user.frozen_until - now).total_seconds() // 60)
        remain_h = remain // 60
        remain_m = remain % 60
        if remain_h > 0:
            msg = f'账号已冻结，剩余 {remain_h}小时{remain_m}分钟'
        else:
            msg = f'账号已冻结，剩余 {remain_m}分钟'
        return JSONResponse(content={'ok': False, 'error': msg})

    # 验证密码
    if not check_password_hash(user.password_hash, password):
        # 跨天重置每日计数
        today = now.date()
        if user.last_failed_date and user.last_failed_date.date() != today:
            user.daily_failed = 0

        user.failed_logins += 1
        user.daily_failed += 1
        user.last_failed_date = now

        freeze_msg = ''
        # 规则1: 连续3次错误 → 冻结1小时
        if user.failed_logins >= 3:
            user.frozen_until = now + dt.timedelta(hours=1)
            user.failed_logins = 0  # 冻结后重置连续计数
            freeze_msg = '，已冻结1小时'
        # 规则2: 当天累计5次错误 → 冻结12小时
        elif user.daily_failed >= 5:
            user.frozen_until = now + dt.timedelta(hours=12)
            user.failed_logins = 0
            user.daily_failed = 0
            freeze_msg = '，已冻结12小时'

        db.commit()
        remaining = ''
        if user.failed_logins < 3:
            remaining = f'（连续错误{user.failed_logins}/3次）'
        return JSONResponse(content={
            'ok': False,
            'error': f'密码错误{freeze_msg}{remaining}'
        })

    # 密码正确 → 清除所有错误计数
    user.failed_logins = 0
    user.daily_failed = 0
    user.frozen_until = None
    user.last_failed_date = None
    db.commit()

    token = _issue_token(user.id)
    return JSONResponse(content={
        'ok': True, 'token': token,
        'user_id': str(user.id), 'username': user.username
    })


# ===================== 发送短信验证码 =====================
@router.post("/api/app/send_sms")
async def app_send_sms(
    request: Request,
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """向目标站手机号发送验证码（绑定用）"""
    data = await request.json()
    phone = (data.get('phone') or '').strip()
    if len(phone) != 11:
        return JSONResponse(content={'ok': False, 'error': '手机号格式无效'})

    # 复用 web_bind 的发送逻辑
    from routes.web_bind import send_verification_code_impl
    success = send_verification_code_impl(phone, db)
    if success:
        return JSONResponse(content={'ok': True, 'message': '验证码已发送'})
    return JSONResponse(content={'ok': False, 'error': '发送失败，请稍后重试'})


# ===================== 绑定账号 =====================
@router.post("/api/app/bind_account")
async def app_bind_account(
    request: Request,
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """提交验证码完成绑定 → 写入 PhoneRecord 表"""
    data = await request.json()
    phone = (data.get('account_phone') or '').strip()
    code = (data.get('code') or '').strip()

    if len(phone) != 11 or not code:
        return JSONResponse(content={'ok': False, 'error': '手机号和验证码不能为空'})

    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and record.logged_in:
        return JSONResponse(content={'ok': False, 'error': '该手机号已登录'})

    # 如果记录已存在但属于其他用户 → 拒绝
    if record and record.user_id != user.id:
        return JSONResponse(content={'ok': False, 'error': '该手机号已被其他用户绑定'})

    from routes.web_bind import build_client_from_record
    from services.keepalive import save_account_to_json
    from config import BASEDIR
    import datetime as dt

    # 创建或更新 PhoneRecord
    if not record:
        record = PhoneRecord(
            phone=phone, user_id=user.id, uploaded_by=user.id,
            uploader_name=user.username, item_code='IMTP1000313', amount=1
        )
        db.add(record)
        db.commit()

    try:
        client = build_client_from_record(phone, db)
    except ValueError:
        # 记录不存在时 build_client_from_record 会抛异常，这里手动创建
        from demo import MoutaiClient
        client = MoutaiClient()
        record.raw_device_id = client.raw_device_id
        record.mt_device_id = client.mt_device_id
        record.h5_did = client.h5_did
        record.h5_start_id = client.h5_start_id
        record.bs_device_id = client.bs_device_id

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
        record.last_updated = dt.datetime.utcnow()
        record.login_time = dt.datetime.now()
        db.commit()
        save_account_to_json(phone, client)
        return JSONResponse(content={'ok': True, 'message': '绑定成功'})
    else:
        return JSONResponse(content={
            'ok': False,
            'error': f'登录失败: {result.get("message", "未知错误")}'
        })


# ===================== 绑定状态 =====================
@router.get("/api/app/bind_status")
async def app_bind_status(
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """获取当前用户所有已绑定账号的登录状态"""
    records = (
        db.query(PhoneRecord)
        .filter(PhoneRecord.user_id == user.id)
        .all()
    )
    accounts = []
    for r in records:
        if r.logged_in:
            login_status = 'success'
        elif r.token or r.cookie:
            login_status = 'offline'
        else:
            login_status = 'never'
        accounts.append({
            'phone': r.phone,
            'login_status': login_status,
            'account_type': r.account_type or '',
        })
    return JSONResponse(content={'ok': True, 'accounts': accounts})


# ===================== 刷新绑定登录 =====================
@router.post("/api/app/refresh_bind_login")
async def app_refresh_bind_login(
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """触发服务端重新检测所有绑定账号的登录状态"""
    import asyncio, random, os, json
    from demo import MoutaiClient, _get, _load_accounts, _load_account_to_client, BASE_URL

    records = (
        db.query(PhoneRecord)
        .filter(PhoneRecord.user_id == user.id)
        .all()
    )

    accounts_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iplala_accounts.json',
    )
    try:
        accounts = _load_accounts(accounts_file)
    except Exception:
        accounts = []

    for i, record in enumerate(records):
        if i > 0:
            await asyncio.sleep(random.uniform(0.05, 0.3))
        try:
            acc = next(
                (a for a in accounts if a.get("mobile") == record.phone), None
            )
            if not acc:
                record.logged_in = False
                record.last_updated = datetime.datetime.utcnow()
                db.commit()
                continue

            client = MoutaiClient(bs_dvid=acc.get('bs-dvid', ''))
            _load_account_to_client(acc, client)
            headers = client._app_headers(need_sign=False)
            resp = _get(
                f"{BASE_URL}/xhr/front/user/info",
                headers=headers,
                proxy='',
            )
            data = resp.json()
            if data.get("code") == 2000:
                record.logged_in = True
                record.token = acc.get('token', '')
                record.cookie = acc.get('cookie', '')
                record.user_id_ext = acc.get('userid', '')
                record.last_updated = datetime.datetime.utcnow()
            else:
                record.logged_in = False
                record.last_updated = datetime.datetime.utcnow()
            db.commit()
        except Exception:
            record.logged_in = False
            record.last_updated = datetime.datetime.utcnow()
            db.commit()

    # 返回刷新后的状态
    return await app_bind_status(user=user, db=db)


# ===================== 中签推送 =====================
@router.post("/api/app/notify_won")
async def app_notify_won(request: Request, db: Session = Depends(get_db)):
    """抢购成功后通知手机 App 弹窗提示
    调用方：抢购系统检测到中签后调用此接口
    参数：phone（手机号）、item（商品名，可选）、order_id（可选）"""
    data = await request.json()
    phone = (data.get('phone') or '').strip()
    item = (data.get('item') or '茅台').strip()
    order_id = (data.get('order_id') or '').strip()

    if not phone:
        return JSONResponse(content={'ok': False, 'error': '手机号不能为空'})

    # 更新 PhoneRecord 状态
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record:
        record.bid_result = f'成功-订单{order_id}' if order_id else '中签'
        record.last_updated = datetime.datetime.utcnow()
        db.commit()

    # 通过手机隧道广播中签消息到所有在线 App
    from services.phone_tunnel import tunnel_manager
    masked = phone[:3] + '****' + phone[-4:]
    tunnel_manager.broadcast_to_all({
        'type': 'won',
        'phone': phone,
        'masked': masked,
        'item': item,
        'order_id': order_id,
    })

    print(f'[中签推送] 📱 {masked} | {item} | 已广播到 {tunnel_manager.tunnel_count} 台手机')
    return JSONResponse(content={'ok': True, 'message': f'已推送至 {masked}'})
