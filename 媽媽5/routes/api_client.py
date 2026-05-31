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

router = APIRouter(tags=["客户端API"])

from routes import get_db  # noqa: E402
from moutai_automation import PhoneRecord, User, UserConfig, get_user_config, get_user_proxy, Config  # noqa: E402
from moutai_automation import proxy_manager  # noqa: E402


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
            'sku_id': rec.sku_id or '',
            'activity_id': rec.activity_id or '',
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
        record.pay_url_alipay = data.get('pay_url_alipay', '') or ''
        record.pay_url_wechat = data.get('pay_url_wechat', '') or ''
        record.pay_url = data.get('pay_url_unionpay', '') or ''  # 云闪付/银联 → pay_url
        record.pay_status = '待支付'
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
            'sku_id': rec.sku_id or '',
            'activity_id': rec.activity_id or '',
        })
    return accounts


@router.post("/api/phone/heartbeat")
async def phone_heartbeat(request: Request, db: Session = Depends(get_db)):
    """手机客户端专用心跳
    已部署: 只返回状态标志（开关/暂停/是否需要重置）——几十字节
    未部署/被重置: 返回完整配置+账号——重新布置
    """
    import traceback as _tb
    try:
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

        cfg = get_user_config(matched_uid, db)
        up = get_user_proxy(matched_uid, db)

        phone_rush_enabled = getattr(cfg, 'phone_rush_enabled', 0) or 0
        rush_paused = getattr(cfg, 'rush_paused', 0) or 0
        multi_open = getattr(cfg, 'phone_multi_open_count', 3) or 3
        interval_mode = getattr(cfg, 'interval_mode', 0) or 0

        # 读取旧状态（若设备已存在则保留，否则初始 pending）
        prev_status = phone_devices.get(device_tag, {}).get('status', 'pending')

        # 客户端请求强制重新部署（App 每次启动时 force_deploy=true）
        force_deploy = data.get('force_deploy', False)
        if force_deploy and prev_status == 'deployed':
            prev_status = 'pending'
            print(f'[手机心跳] {matched_phone[:3]}*** | force_deploy → 强制重新部署')

        # 先计算本轮抢购时间字符串
        base_hour = getattr(cfg, 'rush_hour', 0) or 0
        base_min = getattr(cfg, 'rush_minute', 0) or 0
        base_sec = getattr(cfg, 'rush_second', 0) or 0
        base_ms = getattr(cfg, 'rush_millisecond', 0) or 0
        if interval_mode == 1:
            now_dt = datetime.datetime.now()
            base_time = now_dt.replace(hour=base_hour, minute=base_min, second=base_sec, microsecond=base_ms * 1000)
            if base_time <= now_dt:
                elapsed = (now_dt - base_time).total_seconds()
                intervals = int(elapsed // 300) + 1
                rush_time = base_time + datetime.timedelta(seconds=intervals * 300)
            else:
                rush_time = base_time
            rush_hour = rush_time.hour
            rush_minute = rush_time.minute
            rush_second = rush_time.second
            rush_millisecond = rush_time.microsecond // 1000
            rush_time_str = f"{rush_hour:02d}:{rush_minute:02d}:{rush_second:02d}.{rush_millisecond:03d}"
        else:
            rush_hour = base_hour
            rush_minute = base_min
            rush_second = base_sec
            rush_millisecond = base_ms
            rush_time_str = f"{rush_hour:02d}:{rush_minute:02d}:{rush_second:02d}"

        # 更新 device 信息（含 rush_time）
        phone_devices[device_tag] = {
            'uploader_id': matched_uid,
            'phone': matched_phone,
            'device_info': data.get('device_info', {}),
            'last_heartbeat': time.time(),
            'status': prev_status,
            'account_count': phone_devices.get(device_tag, {}).get('account_count', 0),
            'rush_time': rush_time_str,
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
        # 但以下情况重新下发完整数据：
        #   1. 设备从未收到账号（account_count==0，如服务器重启后设备重连）
        #   2. interval_mode=1 时抢购窗口变更
        if prev_status == 'deployed':
            stored_account_count = phone_devices[device_tag].get('account_count', 0)
            need_redeploy = (stored_account_count == 0)  # 服务器重启后丢失状态

            if interval_mode == 1:
                stored_rush = phone_devices[device_tag].get('rush_time', '')
                if rush_time_str != stored_rush:
                    need_redeploy = True
                    phone_devices[device_tag]['rush_time'] = rush_time_str
                    print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | interval模式窗口更新 {stored_rush}→{rush_time_str}，重新布置')

            if need_redeploy:
                phone_devices[device_tag]['status'] = 'pending'
                print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 重新布置 | 账号数={stored_account_count} | 窗口={rush_time_str}')
                # 不返回，继续往下走到完整数据下发
            else:
                tag = 'interval' if interval_mode == 1 else ''
                print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 已部署{tag} | 暂停={rush_paused} | 窗口={rush_time_str}')
                return JSONResponse(content={
                    'has_data': False,
                    'phone_rush_enabled': 1,
                    'rush_paused': rush_paused,
                    'status': 'deployed',
                })

        # === 未部署/被重置：返回完整数据（rush_time_str 已在上面计算）===
        device_assign = getattr(cfg, 'phone_device_assign', '')
        all_accounts = _get_phone_accounts(matched_uid, multi_open, db, device_assign)

        # 从第一个账号提取全局兜底的 item_code / act_id / sku_id
        first_account = all_accounts[0] if all_accounts else {}
        global_item_code = first_account.get('item_code', 'IMTP1000313')
        global_sku_id = first_account.get('sku_id', '741')
        global_act_id = first_account.get('activity_id', '82107')

        # === 多手机均分账号：每台手机分配不同账号子集 ===
        now = time.time()
        sibling_devices = sorted([
            d for d, info in phone_devices.items()
            if info.get('uploader_id') == matched_uid and now - info.get('last_heartbeat', 0) < 35
        ])
        phone_count = max(len(sibling_devices), 1)
        phone_index = sibling_devices.index(device_tag) if device_tag in sibling_devices else 0

        if all_accounts and phone_count > 1:
            chunk_size = max(1, len(all_accounts) // phone_count)
            start = phone_index * chunk_size
            end = start + chunk_size if phone_index < phone_count - 1 else len(all_accounts)
            accounts = all_accounts[start:end]
            print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 下发数据 | 时间={rush_time_str} | 频率={getattr(cfg, "task_frequency", 100)}ms | 次数={getattr(cfg, "rush_count", 100)} | 多开={multi_open} | 手机{phone_index+1}/{phone_count} | 账号={len(accounts)}/{len(all_accounts)}个 | 手机号={[a["phone"] for a in accounts]}')
        else:
            accounts = all_accounts
            print(f'[手机心跳] {matched_phone[:3]}*** | IP={client_ip} | 下发数据 | 时间={rush_time_str} | 频率={getattr(cfg, "task_frequency", 100)}ms | 次数={getattr(cfg, "rush_count", 100)} | 多开={multi_open} | 账号={len(accounts)}个')

        return JSONResponse(content={
            'has_data': True,
            'phone_rush_enabled': 1,
            'rush_paused': rush_paused,
            'status': 'pending',
            'rush_config': {
                'rush_hour': rush_hour,
                'rush_minute': rush_minute,
                'rush_second': rush_second,
                'rush_millisecond': rush_millisecond,
                'task_frequency': getattr(cfg, 'task_frequency', 100),
                'rush_count': getattr(cfg, 'rush_count', 100),
                'rush_attempts': getattr(cfg, 'rush_attempts', 10000),
                'multi_open_count': multi_open,
                'interval_mode': interval_mode,
                'rush_paused': rush_paused,
                'proxy_enabled': up.proxy_enabled,
                'proxy_url': up.proxy_url if up.proxy_enabled else '',
                'item_code': global_item_code,
                'act_id': global_act_id,
                'sku_id': global_sku_id,
            },
            'accounts': accounts,
            'multi_open_count': multi_open,
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f'[手机心跳异常] {type(e).__name__}: {e}')
        _tb.print_exc()
        return JSONResponse(
            content={'status': 'error', 'message': f'服务器内部错误: {type(e).__name__}: {e}'},
            status_code=500
        )


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


@router.post("/api/phone/wasm_sign")
async def phone_wasm_sign(request: Request):
    """为抢购请求生成 WASM 签名
    Android 端无法运行 wasmtime，由服务端代为生成
    输入: {did, sign}  输出: {wasm_sign}
    """
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    data = await request.json()
    did = data.get('did', '')
    sign = data.get('sign', '')

    if not did or not sign:
        return JSONResponse(content={'wasm_sign': None, 'error': '缺少 did 或 sign'})

    try:
        from crypto import generate_wasm_sign, WASM_VERSION
        ws = generate_wasm_sign(did, sign)
        return JSONResponse(content={'wasm_sign': ws, 'wasm_version': WASM_VERSION})
    except Exception as e:
        return JSONResponse(content={'wasm_sign': None, 'error': str(e)})


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
    cfg = get_user_config(matched_uid, db)
    up = get_user_proxy(matched_uid, db)

    phone_rush_enabled = getattr(cfg, 'phone_rush_enabled', 0) or 0
    paused = getattr(cfg, 'rush_paused', 0) or 0

    # 统计在线/已部署/未部署
    now = time.time()
    online_count = sum(1 for d in phone_devices.values() if now - d['last_heartbeat'] < 35)
    deployed_count = sum(1 for d in phone_devices.values() if d['status'] == 'deployed' and now - d['last_heartbeat'] < 35)
    pending_count = online_count - deployed_count

    return JSONResponse(content={
        'phone_rush_enabled': phone_rush_enabled,
        'rush_paused': paused,
        'proxy_enabled': up.proxy_enabled,
        'proxy_url': up.proxy_url if up.proxy_enabled else '',
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
