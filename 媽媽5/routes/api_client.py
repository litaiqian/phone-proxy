#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 客户端 API（任务分配 / 上报 / 暂停 / 代理）
"""
import os
import hashlib
import datetime
import time
import json
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import hashlib
import time
import json

from routes import get_db
from models import PhoneRecord, User, UserConfig
from core.database import get_user_config, get_user_proxy
from config import Config, QRCODE_FOLDER
from services.proxy_manager import proxy_manager

router = APIRouter(tags=["客户端API"])


@router.get("/api/client/get_config")
async def client_get_config(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    uploader_id_str = request.query_params.get('uploader_id', '0')
    try:
        uploader_id = int(uploader_id_str)
    except Exception:
        uploader_id = 0
    if uploader_id > 0:
        cfg = get_user_config(uploader_id, db)
        up = get_user_proxy(uploader_id, db)
    else:
        cfg = get_user_config(1, db)
        up = get_user_proxy(1, db)
    client_ip = request.client.host if request.client else 'unknown'
    rush_time_str = f"{getattr(cfg, 'rush_hour', 0) or 0:02d}:{getattr(cfg, 'rush_minute', 0) or 0:02d}:{getattr(cfg, 'rush_second', 0) or 0:02d}"
    print(f'[取配置] → IP={client_ip} | 抢购时间={rush_time_str} | 频率={getattr(cfg, "task_frequency", 100)}ms | 次数={getattr(cfg, "rush_count", 100)}/轮 | 多开={cfg.multi_open_count or 1} | 暂停={getattr(cfg, "rush_paused", 0)}')
    return JSONResponse(content={
        'rush_hour': cfg.rush_hour, 'rush_minute': cfg.rush_minute,
        'rush_second': cfg.rush_second, 'item_code': 'IMTP1000313', 'act_id': '',
        'rush_count': getattr(cfg, 'rush_count', 100),
        'rush_attempts': getattr(cfg, 'rush_attempts', 10000),
        'task_frequency': getattr(cfg, 'task_frequency', 100),
        'rush_paused': getattr(cfg, 'rush_paused', 0),
        'interval_mode': getattr(cfg, 'interval_mode', 0),
        'proxy_enabled': up.proxy_enabled, 'proxy_url': up.proxy_url,
        'multi_open_count': cfg.multi_open_count or 1,
        'multi_open_enabled': cfg.multi_open_enabled or False,
        'client_windows': getattr(cfg, 'client_windows', 10),
        'phone_multi_open_count': getattr(cfg, 'phone_multi_open_count', 3),
    })


@router.post("/api/client/get_tasks")
async def client_get_tasks(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    uploader_id = data.get('uploader_id', 0)
    cfg = get_user_config(uploader_id, db) if uploader_id else get_user_config(1, db)
    multi_open_count = cfg.multi_open_count or 1
    multi_open_enabled = cfg.multi_open_enabled

    if uploader_id:
        all_logged_in = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True, PhoneRecord.user_id == uploader_id).all()
    else:
        all_logged_in = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    all_logged_in = [r for r in all_logged_in if not (r.account_type and ('黑号' in r.account_type.lower() or r.account_type.lower() == 'black'))]

    excluded_teams = [t.strip() for t in (cfg.excluded_teams or '').split(',') if t.strip()] if cfg.excluded_teams else []
    excluded_uploaders = [u.strip() for u in (cfg.excluded_uploaders or '').split(',') if u.strip()] if cfg.excluded_uploaders else []
    if excluded_teams or excluded_uploaders:
        all_logged_in = [r for r in all_logged_in
                         if r.team not in excluded_teams and r.uploader_name not in excluded_uploaders]

    assigned_tasks = []

    def _task_dict(rec):
        return {
            'phone': rec.phone, 'token': rec.token, 'cookie': rec.cookie,
            'user_id': rec.user_id_ext, 'mt_device_id': rec.mt_device_id,
            'raw_device_id': rec.raw_device_id, 'h5_did': rec.h5_did,
            'h5_start_id': rec.h5_start_id, 'bs_device_id': rec.bs_device_id,
            'user_agent': rec.user_agent, 'webview_ua': rec.webview_ua,
            'mt_r': rec.mt_r, 'mt_sn': rec.mt_sn, 'rush_time_offset': rec.rush_time_offset,
            'item_code': rec.item_code or 'IMTP1000313', 'item_name': rec.item_name or '',
            'amount': rec.amount or 1, 'task_type': 'rush', 'task_role': rec.task_role or 'both',
            'proxy_ip': rec.proxy_ip or '',
            'device_key': rec.device_key or '',
        }

    if multi_open_enabled:
        batch = data.get('batch', 0)
        start = batch * multi_open_count
        batch_records = all_logged_in[start:start + multi_open_count]
        for rec in batch_records:
            assigned_tasks.append(_task_dict(rec))
    else:
        for rec in all_logged_in:
            assigned_tasks.append(_task_dict(rec))

    client_ip = request.client.host if request.client else 'unknown'
    phone_list = [t['phone'] for t in assigned_tasks]
    batch = data.get('batch', 0)
    print(f'[取任务] → IP={client_ip} | 窗口={batch+1} | 多开数={multi_open_count} | 白号总数={len(all_logged_in)} | 下发账号: {phone_list}')
    return JSONResponse(content={'status': 'success', 'tasks': assigned_tasks})


@router.post("/api/client/report_result")
async def client_report_result(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    phone = data.get('phone')
    success = data.get('success', False)
    order_id = data.get('order_id', '')
    h5_url = data.get('h5_url', '')
    error_msg = data.get('error', '')
    ip_blocked = data.get('ip_blocked', False)
    account_black = data.get('account_black', False)
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        raise HTTPException(status_code=404, detail="手机号不存在")

    record_up = get_user_proxy(record.user_id or 1, db) if record.user_id else get_user_proxy(1, db)
    proxy_api_url = record_up.proxy_url if record_up else ''

    if ip_blocked and record.proxy_ip:
        print(f'[抢购] {phone} IP被封: {record.proxy_ip}，丢弃并换新IP')
        proxy_manager.discard_proxy(record.proxy_ip)
        new_proxy = proxy_manager.get_proxy(proxy_api_url)
        record.proxy_ip = new_proxy
        print(f'[抢购] {phone} 新IP: {new_proxy}')

    if account_black:
        record.account_type = 'black'
        record.logged_in = False
        print(f'[抢购] {phone} 账号被黑，立即下线')

    if success:
        record.bid_result = f"成功-订单{order_id}"
        record.balance = "待支付"
        if h5_url:
            qrcode_path = os.path.join(QRCODE_FOLDER, f"{phone}.png")
            try:
                import qrcode as qr
                img = qr.make(h5_url)
                img.save(qrcode_path)
            except Exception as e:
                print(f"[QR] 生成失败: {e}")
    else:
        record.bid_result = f"失败-{error_msg[:50]}"
    record.last_updated = datetime.datetime.utcnow()
    db.commit()
    return JSONResponse(content={'status': 'success', 'new_proxy_ip': record.proxy_ip})


@router.get("/api/client/get_pause_status")
async def client_get_pause_status(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    uploader_id_str = request.query_params.get('uploader_id', '0')
    try:
        uploader_id = int(uploader_id_str)
    except Exception:
        uploader_id = 0
    if uploader_id > 0:
        cfg = get_user_config(uploader_id, db)
        up = get_user_proxy(uploader_id, db)
    else:
        cfg = get_user_config(1, db)
        up = get_user_proxy(1, db)
    paused = getattr(cfg, 'rush_paused', 0)
    return JSONResponse(content={
        'paused': paused, 'proxy_enabled': up.proxy_enabled, 'proxy_url': up.proxy_url
    })


# ===================== 客户端日志上传 =====================
LOG_DIR_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'client_logs')
os.makedirs(LOG_DIR_SERVER, exist_ok=True)


# ===================== CDN 锁定日志 (4030) =====================
CDN_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cdn_logs')
os.makedirs(CDN_LOG_DIR, exist_ok=True)


@router.post("/api/client/report_cdn_lock")
async def client_report_cdn_lock(request: Request):
    """接收客户端上报的CDN 4030锁定事件（一轮探测汇总），写入专用txt供分析"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    items = data.get('items', [])  # 批量：[{phone, mode, http_status, code, msg, srv_time, raw_text}, ...]
    client_time = data.get('client_time', '')
    client_uuid = data.get('uuid', 'unknown')
    batch = data.get('batch', 0)

    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    filename = f"cdn_{date_str}.txt"
    filepath = os.path.join(CDN_LOG_DIR, filename)

    if not items:
        return JSONResponse(content={'status': 'empty'})

    lines = []
    for item in items:
        phone = item.get('phone', '')
        mode = item.get('mode', '')
        http_status = item.get('http_status', '')
        code = item.get('code', '')
        msg = item.get('msg', '')
        srv_time = item.get('srv_time', '')
        raw_text = item.get('raw_text', '')
        line = (
            f"{client_time}\t"
            f"{phone}\t"
            f"{mode}\t"
            f"HTTP={http_status}\t"
            f"code={code}\t"
            f"msg={msg}\t"
            f"srv={srv_time}\t"
            f"raw={raw_text[:300]}\t"
            f"uuid={client_uuid}\t"
            f"窗口={batch+1}\n"
        )
        lines.append(line)

    with open(filepath, 'a', encoding='utf-8') as f:
        f.writelines(lines)
    return JSONResponse(content={'status': 'success', 'count': len(items)})


@router.post("/api/client/upload_log")
async def client_upload_log(request: Request):
    """接收客户端上传的日志文件，存储到 client_logs/ 目录
    文件名格式: 日_ip_uuid.txt"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    client_uuid = data.get('uuid', 'unknown')
    log_content = data.get('log', '')
    day = data.get('day', datetime.datetime.now().strftime('%d'))
    public_ip = data.get('public_ip', 'unknown')
    if not log_content:
        return JSONResponse(content={'status': 'empty'})
    filename = f"{day}_{public_ip}_{client_uuid}.txt"
    filepath = os.path.join(LOG_DIR_SERVER, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(log_content)
        if not log_content.endswith('\n'):
            f.write('\n')
        f.flush()
        os.fsync(f.fileno())  # 强制落盘
    return JSONResponse(content={'status': 'success', 'file': filename})


# ===================== 设备绑定 API =====================
@router.post("/api/client/bind_device")
async def client_bind_device(request: Request, db: Session = Depends(get_db)):
    """客户端上报手机号与设备机型的绑定关系（绑定后不可更换）
    请求: {phone, device_key, device_info: {brand, model, build_id, sdk, screen, chrome, cpu, ram, storage}}
    响应: {status, device_key}"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    phone = data.get('phone', '')
    device_key = data.get('device_key', '')
    if not phone or not device_key:
        return JSONResponse(content={'status': 'error', 'message': '缺少phone或device_key'})

    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '手机号不存在'})

    # 已有绑定 → 返回已绑定的机型（不可更换）
    if record.device_key:
        return JSONResponse(content={
            'status': 'success',
            'device_key': record.device_key,
            'new_binding': False,
            'message': f'已有绑定: {record.device_key}',
        })

    # 新绑定
    record.device_key = device_key
    db.commit()
    print(f'[设备绑定] {phone} → {device_key}')
    return JSONResponse(content={
        'status': 'success',
        'device_key': device_key,
        'new_binding': True,
        'message': f'绑定成功: {device_key}',
    })


@router.get("/api/client/get_device_bindings")
async def client_get_device_bindings(request: Request, db: Session = Depends(get_db)):
    """获取所有手机号的设备绑定关系
    响应: {bindings: {phone: device_key, ...}}"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    uploader_id_str = request.query_params.get('uploader_id', '0')
    try:
        uploader_id = int(uploader_id_str)
    except Exception:
        uploader_id = 0

    if uploader_id:
        records = db.query(PhoneRecord).filter(
            PhoneRecord.device_key != '', PhoneRecord.user_id == uploader_id).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.device_key != '').all()

    bindings = {r.phone: r.device_key for r in records}
    return JSONResponse(content={'status': 'success', 'bindings': bindings, 'count': len(bindings)})


# ===================== 手机客户端专用 API（手机抢购） =====================
# 手机设备部署状态追踪
phone_devices: dict = {}  # {device_id: {"uploader_id": int, "device_info": {}, "status": "deployed"/"pending", "last_heartbeat": float, "account_count": int}}


def _verify_phone_identity(identity: str, db: Session):
    """验证手机客户端身份: identity = MD5(username + "_" + str(id))
    遍历数据库所有平台注册用户（User表），逐一计算 MD5 比对
    username 可能是手机号也可能是用户名
    返回 (user_id, username) 或 None"""
    if not identity:
        return None
    all_users = db.query(User).all()
    for u in all_users:
        expected = hashlib.md5(f"{u.username}_{u.id}".encode()).hexdigest()
        if identity == expected:
            return (u.id, u.username)
    return None


def _get_phone_accounts(uploader_id: int, phone_multi_open_count: int, db: Session, device_assign: str = '') -> list:
    """获取分配给手机的已登录账号
    若有 device_assign 配置，则只返回指定设备号的账号"""
    if uploader_id:
        all_logged_in = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True, PhoneRecord.user_id == uploader_id).all()
    else:
        all_logged_in = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    all_logged_in = [r for r in all_logged_in if not (
        r.account_type and ('\u9ed1\u53f7' in r.account_type.lower() or r.account_type.lower() == 'black'))]

    # 若有设备分配配置，按 device_assign 过滤
    if device_assign:
        try:
            assign_map = json.loads(device_assign)
            allowed_phones = set()
            for phones in assign_map.values():
                allowed_phones.update(phones)
            if allowed_phones:
                all_logged_in = [r for r in all_logged_in if r.phone in allowed_phones]
        except Exception:
            pass

    # 按手机多开数限制
    if phone_multi_open_count > 0 and len(all_logged_in) > phone_multi_open_count:
        all_logged_in = all_logged_in[:phone_multi_open_count]

    accounts = []
    for rec in all_logged_in:
        accounts.append({
            'phone': rec.phone, 'token': rec.token, 'cookie': rec.cookie,
            'user_id': rec.user_id_ext, 'mt_device_id': rec.mt_device_id,
            'raw_device_id': rec.raw_device_id, 'h5_did': rec.h5_did,
            'h5_start_id': rec.h5_start_id, 'bs_device_id': rec.bs_device_id,
            'user_agent': rec.user_agent, 'webview_ua': rec.webview_ua,
            'mt_r': rec.mt_r, 'mt_sn': rec.mt_sn, 'rush_time_offset': rec.rush_time_offset,
            'item_code': rec.item_code or 'IMTP1000313', 'item_name': rec.item_name or '',
            'amount': rec.amount or 1, 'task_type': 'rush', 'task_role': rec.task_role or 'both',
            'proxy_ip': rec.proxy_ip or '', 'device_key': rec.device_key or '',
        })
    return accounts


@router.post("/api/phone/heartbeat")
async def phone_heartbeat(request: Request, db: Session = Depends(get_db)):
    """手机客户端专用心跳
    已部署: 只返回状态标志（开关/暂停/是否需要重置）——几十字节
    未部署/被重置: 返回完整配置+账号——重新布置
    """
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    data = await request.json()
    identity = data.get('identity', '')
    matched = _verify_phone_identity(identity, db)
    if not matched:
        return JSONResponse(content={'status': 'error', 'message': '身份验证失败，未找到匹配账号'}, status_code=403)

    matched_uid, matched_phone = matched
    device_tag = request.headers.get('X-Device-Id', data.get('device_tag', 'unknown'))

    # phone_rush_enabled 是全局开关，始终从 admin(uid=1) 配置读取
    admin_cfg = get_user_config(1, db)
    cfg = get_user_config(matched_uid, db)
    up = get_user_proxy(matched_uid, db)

    phone_rush_enabled = getattr(admin_cfg, 'phone_rush_enabled', 0)
    rush_paused = getattr(cfg, 'rush_paused', 0)
    multi_open = getattr(cfg, 'phone_multi_open_count', 3)

    # 更新设备心跳时间
    prev_status = phone_devices.get(device_tag, {}).get('status', 'pending')
    phone_devices[device_tag] = {
        'uploader_id': matched_uid,
        'phone': matched_phone,
        'device_info': data.get('device_info', {}),
        'last_heartbeat': time.time(),
        'status': prev_status,
        'account_count': phone_devices.get(device_tag, {}).get('account_count', 0),
    }

    client_ip = request.client.host if request.client else 'unknown'

    # === 开关关闭：不做任何事，心跳只轮询 ===
    if not phone_rush_enabled:
        print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 开关=关')
        return JSONResponse(content={
            'has_data': False,
            'phone_rush_enabled': 0,
            'rush_paused': rush_paused,
            'status': prev_status,
        })

    # === 已部署：只返回状态标志，不返数据 ===
    if prev_status == 'deployed':
        print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 已部署 | 暂停={rush_paused}')
        return JSONResponse(content={
            'has_data': False,
            'phone_rush_enabled': 1,
            'rush_paused': rush_paused,
            'status': 'deployed',
        })

    # === 未部署/被重置：返回完整数据 ===
    rush_time_str = f"{getattr(cfg, 'rush_hour', 0) or 0:02d}:{getattr(cfg, 'rush_minute', 0) or 0:02d}:{getattr(cfg, 'rush_second', 0) or 0:02d}"
    device_assign = getattr(cfg, 'phone_device_assign', '')
    accounts = _get_phone_accounts(matched_uid, multi_open, db, device_assign)

    print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 下发数据 | 时间={rush_time_str} | 频率={getattr(cfg, "task_frequency", 100)}ms | 次数={getattr(cfg, "rush_count", 100)} | 多开={multi_open} | 账号={len(accounts)}个')

    return JSONResponse(content={
        'has_data': True,
        'phone_rush_enabled': 1,
        'rush_paused': rush_paused,
        'status': 'pending',
        'rush_config': {
            'rush_hour': cfg.rush_hour,
            'rush_minute': cfg.rush_minute,
            'rush_second': cfg.rush_second,
            'rush_millisecond': getattr(cfg, 'rush_millisecond', 0),
            'task_frequency': getattr(cfg, 'task_frequency', 100),
            'rush_count': getattr(cfg, 'rush_count', 100),
            'rush_attempts': getattr(cfg, 'rush_attempts', 10000),
            'multi_open_count': multi_open,
            'interval_mode': getattr(cfg, 'interval_mode', 0),
            'rush_paused': rush_paused,
            'proxy_enabled': up.proxy_enabled,
            'proxy_url': up.proxy_url,
        },
        'accounts': accounts,
        'multi_open_count': multi_open,
    })


@router.post("/api/phone/ready")
async def phone_ready(request: Request, db: Session = Depends(get_db)):
    """手机客户端确认部署完成
    客户端收到账号后验证登录信息 → 告知服务端「布置完毕」"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    data = await request.json()
    identity = data.get('identity', '')
    matched = _verify_phone_identity(identity, db)
    if not matched:
        return JSONResponse(content={'status': 'error', 'message': '身份验证失败'}, status_code=403)

    matched_uid, matched_phone = matched
    verified_count = data.get('verified_count', 0)
    device_tag = request.headers.get('X-Device-Id', data.get('device_tag', 'unknown'))

    # 更新设备状态为已部署
    if device_tag in phone_devices:
        phone_devices[device_tag]['status'] = 'deployed'
        phone_devices[device_tag]['account_count'] = verified_count

    print(f'[手机就绪] ✅ {matched_phone[:3]}*** | 验证通过={verified_count}个账号')
    return JSONResponse(content={
        'status': 'ready',
        'message': f'已就绪，{verified_count}个账号已布置',
        'deployed_count': sum(1 for d in phone_devices.values() if d['status'] == 'deployed'),
        'online_count': len(phone_devices),
    })


@router.get("/api/phone/status")
async def phone_status(request: Request, db: Session = Depends(get_db)):
    """手机客户端查询当前状态（是否有新配置/暂停变更/需要重置）"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    identity = request.query_params.get('identity', '')
    matched = _verify_phone_identity(identity, db)
    if not matched:
        return JSONResponse(content={'status': 'error', 'message': '身份验证失败'}, status_code=403)

    matched_uid, matched_phone = matched
    # phone_rush_enabled 是全局开关，始终从 admin(uid=1) 配置读取
    admin_cfg = get_user_config(1, db)
    cfg = get_user_config(matched_uid, db)
    up = get_user_proxy(matched_uid, db)

    phone_rush_enabled = getattr(admin_cfg, 'phone_rush_enabled', 0)
    paused = getattr(cfg, 'rush_paused', 0)

    # 统计在线/已部署/未部署
    now = time.time()
    online_count = sum(1 for d in phone_devices.values() if now - d['last_heartbeat'] < 35)
    deployed_count = sum(1 for d in phone_devices.values() if d['status'] == 'deployed' and now - d['last_heartbeat'] < 35)
    pending_count = online_count - deployed_count

    return JSONResponse(content={
        'phone_rush_enabled': phone_rush_enabled,
        'rush_paused': paused,
        'proxy_enabled': up.proxy_enabled,
        'proxy_url': up.proxy_url,
        'stats': {
            'online_count': online_count,
            'deployed_count': deployed_count,
            'pending_count': pending_count,
        },
    })


@router.get("/api/phone/devices")
async def phone_devices_list(request: Request, db: Session = Depends(get_db)):
    """获取在线手机设备列表（网站后台查看）"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    now = time.time()
    devices = []
    for device_id, info in list(phone_devices.items()):
        if now - info['last_heartbeat'] < 35:  # 35秒内有心跳=在线
            devices.append({
                'device_id': device_id,
                'uploader_id': info['uploader_id'],
                'status': info.get('status', 'pending'),
                'account_count': info.get('account_count', 0),
                'last_heartbeat': info['last_heartbeat'],
                'device_info': info.get('device_info', {}),
            })

    online_count = len(devices)
    deployed_count = sum(1 for d in devices if d['status'] == 'deployed')

    return JSONResponse(content={
        'devices': devices,
        'online_count': online_count,
        'deployed_count': deployed_count,
        'pending_count': online_count - deployed_count,
    })


# ⚠️ /api/phone/reset 和 /api/phone/assign 在 moutai_automation.py 中定义（网站后台用 session 认证）
