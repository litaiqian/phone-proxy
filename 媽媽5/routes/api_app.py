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

# 在线时长追踪: user_id -> {last_hb, session_start, accumulated_seconds}
_online_tracker: dict = {}
HEARTBEAT_TIMEOUT = 120  # 超过120秒无心跳视为离线


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


# ===================== 心跳 =====================
@router.post("/api/app/heartbeat")
async def app_heartbeat(user: User = Depends(get_app_user)):
    """App 心跳：验证 token 有效，记录在线时长
    客户端每30秒调用一次，服务端计算累计在线秒数"""
    now = datetime.datetime.utcnow()
    uid = user.id

    if uid not in _online_tracker:
        _online_tracker[uid] = {
            'last_hb': now,
            'session_start': now,
            'accumulated_seconds': 0.0,
        }
    else:
        info = _online_tracker[uid]
        gap = (now - info['last_hb']).total_seconds()
        if gap > HEARTBEAT_TIMEOUT:
            # 离线太久，开启新会话
            info['session_start'] = now
        else:
            info['accumulated_seconds'] += gap
        info['last_hb'] = now

    return JSONResponse(content={'ok': True})


# ===================== 首页猫粮 =====================
@router.get("/api/app/cat_food")
async def app_cat_food(
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """App 首页数据：猫粮余额（基于在线时长）、在线时长、代理状态
    猫粮 = 累计在线分钟数 × 1.0（每分钟1颗猫粮）"""
    import datetime as dt
    records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    bind_count = len(records)

    # 从在线追踪中获取累计在线秒数（含当前心跳间隔）
    uid = user.id
    now = dt.datetime.utcnow()
    total_online_seconds = 0.0
    if uid in _online_tracker:
        info = _online_tracker[uid]
        gap = (now - info['last_hb']).total_seconds()
        if gap <= HEARTBEAT_TIMEOUT:
            total_online_seconds = info['accumulated_seconds'] + gap
        else:
            total_online_seconds = info['accumulated_seconds']

    # 猫粮 = 在线分钟数 × 1.0（每分钟1颗）
    CAT_FOOD_RATE = 1.0
    cat_food = total_online_seconds / 60.0 * CAT_FOOD_RATE

    # 代理状态（由外部豌豆代理决定）
    proxy_connected = False

    return JSONResponse(content={
        'ok': True,
        'cat_food': round(cat_food, 3),
        'online_today': int(total_online_seconds),
        'proxy_connected': proxy_connected,
        'user_id': str(user.id),
        'total_food': round(cat_food, 3),
    })


# ===================== 推荐码 =====================
@router.get("/api/app/refer_code")
async def app_refer_code(user: User = Depends(get_app_user)):
    """获取用户的推荐码（用 user_id 生成固定码）"""
    import hashlib
    code = hashlib.md5(f"ref_{user.id}".encode()).hexdigest()[:8]
    return JSONResponse(content={'ok': True, 'code': code})


# ===================== 推荐列表 =====================
@router.get("/api/app/referrals")
async def app_referrals(
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """获取推荐用户列表及收益"""
    # 查询所有用户（不含自己）作为推荐列表
    all_users = db.query(User).filter(User.id != user.id).all()
    ref_list = []
    for u in all_users:
        user_records = db.query(PhoneRecord).filter(PhoneRecord.user_id == u.id).all()
        online = any(r.logged_in for r in user_records)
        won = any(r.bid_result and '成功' in str(r.bid_result) for r in user_records)
        ref_list.append({
            'phone': u.phone or u.username,
            'online': online,
            'online_hours': 0.0,
            'cat_food': len(user_records) * 10.0,
            'won': won,
        })
    return JSONResponse(content={
        'ok': True,
        'list': ref_list[:20],
        'earned_food': 0.0,
    })


# ===================== 订单列表 =====================
@router.get("/api/app/orders")
async def app_orders(
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """查询用户绑定账号的中签记录"""
    records = db.query(PhoneRecord).filter(
        PhoneRecord.user_id == user.id,
        PhoneRecord.bid_result != '',
    ).all()
    orders = []
    for r in records:
        orders.append({
            'date': r.last_updated.strftime('%m-%d %H:%M') if r.last_updated else '',
            'won': '成功' in str(r.bid_result) if r.bid_result else False,
            'item': r.item_name or 'i茅台',
        })
    return JSONResponse(content={'ok': True, 'orders': orders})


# ===================== 修改密码 =====================
@router.post("/api/app/change_password")
async def app_change_password(
    request: Request,
    user: User = Depends(get_app_user),
    db: Session = Depends(get_db),
):
    """修改登录密码"""
    import re
    data = await request.json()
    old_pw = (data.get('old_password') or '').strip()
    new_pw = (data.get('new_password') or '').strip()

    if not old_pw or not new_pw:
        return JSONResponse(content={'ok': False, 'error': '请输入新旧密码'})
    if not check_password_hash(user.password_hash, old_pw):
        return JSONResponse(content={'ok': False, 'error': '原密码错误'})
    if len(new_pw) < 6:
        return JSONResponse(content={'ok': False, 'error': '新密码至少6位'})
    has_letter = any(c.isalpha() for c in new_pw)
    has_digit = any(c.isdigit() for c in new_pw)
    if not has_letter or not has_digit:
        return JSONResponse(content={'ok': False, 'error': '新密码必须包含字母和数字'})

    user.password_hash = generate_password_hash(new_pw)
    db.commit()
    return JSONResponse(content={'ok': True, 'message': '密码修改成功'})


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

    # 广播中签通知到在线设备
    print(f'[中签推送] 📱 {masked} | {item} | order={order_id}')
    return JSONResponse(content={'ok': True, 'message': f'已推送至 {masked}'})
