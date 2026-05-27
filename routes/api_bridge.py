#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 桥接 API（供 moutai_automation.py 和客户端调用）
"""
import json
import hashlib
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from config import Config
from demo import (
    MoutaiClient, _get, _post,
    generate_bs_device_id, BASE_URL
)

router = APIRouter(tags=["桥接"])


def _bridge_build_client(data: dict) -> MoutaiClient:
    """根据桥接请求数据重建 MoutaiClient（持久化设备标识 + 确定性设备索引）"""
    and_id = (data.get('raw_device_id', '') or '')[:16]
    bs_dvid = (data.get('mt_device_id', '') or '').replace('clips_', '')
    raw_did = data.get('raw_device_id', '') or ''
    if raw_did:
        dev_idx = hashlib.md5(raw_did.encode()).digest()[0] % 25
    else:
        dev_idx = -1
    client = MoutaiClient(android_id=and_id, bs_dvid=bs_dvid, device_index=dev_idx)
    client.phone = data.get('phone', '')
    client.token = data.get('token', '') or ''
    client.cookie = data.get('cookie', '') or ''
    client.user_id = data.get('user_id_ext', '') or data.get('user_id', '') or ''
    client.mt_device_id = data.get('mt_device_id', '') or ''
    client.raw_device_id = data.get('raw_device_id', '') or ''
    if data.get('h5_did'):
        client.h5_did = data['h5_did']
    if data.get('h5_start_id'):
        client.h5_start_id = data['h5_start_id']
    if data.get('bs_device_id'):
        client.bs_device_id = data['bs_device_id']
    else:
        client.bs_device_id = generate_bs_device_id(client.h5_did)
    if data.get('user_agent'):
        client.user_agent = data['user_agent']
    if data.get('webview_ua'):
        client.webview_ua = data['webview_ua']
    if data.get('mt_r'):
        client.mt_r = data['mt_r']
    if data.get('mt_sn'):
        client.mt_sn = data['mt_sn']
    return client


def _check_token(request: Request):
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)


@router.post("/api/bridge/check_login")
async def bridge_check_login(request: Request):
    _check_token(request)
    data = await request.json()
    try:
        client = _bridge_build_client(data)
        # 支持代理
        proxy_url = data.get('proxy_url', '')
        if proxy_url:
            client.proxy = proxy_url
        headers = client._app_headers(need_sign=False)
        resp = _get(f"{BASE_URL}/xhr/front/user/info", headers=headers, proxy=client.proxy)
        result = resp.json()
        valid = result.get("code") == 2000
        return JSONResponse(content={'valid': valid, 'message': result.get('message', '')})
    except Exception as e:
        return JSONResponse(content={'valid': False, 'message': str(e)})


@router.post("/api/bridge/send_vcode")
async def bridge_send_vcode(request: Request):
    _check_token(request)
    data = await request.json()
    phone = data.get('phone', '')
    try:
        client = _bridge_build_client(data.get('credentials', {}))
        result = client.send_vcode(phone)
        success = result.get("code") == 2000
        return JSONResponse(content={'success': success, 'message': result.get('message', ''), 'data': result})
    except Exception as e:
        return JSONResponse(content={'success': False, 'message': str(e)})


@router.post("/api/bridge/login")
async def bridge_login(request: Request):
    _check_token(request)
    data = await request.json()
    phone = data.get('phone', '')
    vcode = data.get('vcode', '')
    try:
        creds = data.get('credentials', {})
        and_id = (creds.get('raw_device_id', '') or '')[:16]
        bs_dvid = (creds.get('mt_device_id', '') or '').replace('clips_', '')
        client = MoutaiClient(android_id=and_id, bs_dvid=bs_dvid)
        client.phone = phone
        if creds.get('h5_did'): client.h5_did = creds['h5_did']
        if creds.get('h5_start_id'): client.h5_start_id = creds['h5_start_id']
        if creds.get('bs_device_id'): client.bs_device_id = creds['bs_device_id']
        if creds.get('user_agent'): client.user_agent = creds['user_agent']
        if creds.get('webview_ua'): client.webview_ua = creds['webview_ua']
        if creds.get('mt_r'): client.mt_r = creds['mt_r']
        if creds.get('mt_sn'): client.mt_sn = creds['mt_sn']
        result = client.login(phone, vcode)
        if result.get("code") == 2000:
            return JSONResponse(content={'success': True, 'message': '登录成功',
                'credentials': {
                    'token': client.token, 'cookie': client.cookie,
                    'user_id_ext': client.user_id,
                    'mt_device_id': client.mt_device_id, 'raw_device_id': client.raw_device_id,
                    'h5_did': client.h5_did, 'h5_start_id': client.h5_start_id,
                    'bs_device_id': client.bs_device_id, 'user_agent': client.user_agent,
                    'webview_ua': client.webview_ua, 'mt_r': client.mt_r, 'mt_sn': client.mt_sn,
                }})
        return JSONResponse(content={'success': False, 'message': result.get('message', '')})
    except Exception as e:
        return JSONResponse(content={'success': False, 'message': str(e)})


@router.post("/api/bridge/check_inventory")
async def bridge_check_inventory(request: Request):
    _check_token(request)
    data = await request.json()
    phone = data.get('phone', '')
    item_code = data.get('item_code', '741')
    spu_id = data.get('spu_id', '')
    api_spu_id = spu_id or item_code
    try:
        client = _bridge_build_client(data.get('credentials', {}))
        purchase_data = client.get_purchase_info_v2(api_spu_id)
        available = 0
        raw_detail = {}
        if purchase_data:
            purchase_info_map = purchase_data.get("purchaseInfoMap", {})
            for sku_id_key, sku_info in purchase_info_map.items():
                pinfo = sku_info.get("purchaseInfo", {})
                raw_detail[str(sku_id_key)] = {
                    'disable': pinfo.get('disable', None),
                    'inventory': pinfo.get('inventory', 0),
                    'act_id': pinfo.get('itemPriorityActId', '')
                }
                if not pinfo.get("disable", False):
                    available += pinfo.get("inventory", 0)
        return JSONResponse(content={'available': available, 'code': 2000 if purchase_data else -1})
    except Exception as e:
        return JSONResponse(content={'available': -1, 'message': str(e)})


@router.post("/api/bridge/execute")
async def bridge_execute(request: Request):
    """通用桥接执行端点：调用 MoutaiClient 的任意方法"""
    _check_token(request)
    data = await request.json()
    method = data.get('method')
    params = data.get('params', {})
    creds = data.get('credentials', {})
    if not method:
        return JSONResponse(content={'success': False, 'error': '缺少 method 参数'})
    try:
        client = _bridge_build_client(creds)
        # 如果 params 中包含 proxy_url，设置代理
        proxy_url = data.get('proxy_url', '') or params.pop('_proxy_url', '')
        if proxy_url:
            client.proxy = proxy_url
        # 设置手机号用于日志
        if data.get('phone'):
            client.phone = data['phone']
        fn = getattr(client, method, None)
        if not fn:
            return JSONResponse(content={'success': False, 'error': f'未知方法: {method}'})
        result = fn(**params)
        return JSONResponse(content={'success': True, 'result': result})
    except Exception as e:
        return JSONResponse(content={'success': False, 'error': str(e)})


@router.post("/api/bridge/test_proxy")
async def bridge_test_proxy(request: Request):
    """
    测试代理IP是否可用 — 通过代理发起轻量HTTPS请求到i茅台
    用于代理池净化、IP预检测、实时切换等场景
    """
    _check_token(request)
    data = await request.json()
    proxy_url = data.get('proxy_url', '')
    timeout = data.get('timeout', 10)

    if not proxy_url:
        return JSONResponse(content={'ok': False, 'reason': '缺少 proxy_url'})

    import time as _time
    t0 = _time.time()
    try:
        # 使用 curl_cffi 模拟真实浏览器TLS指纹，避免被CDN识别为脚本
        from curl_cffi import requests as cffi_requests
        sess = cffi_requests.Session(impersonate="chrome124")
        resp = sess.get(
            f"{BASE_URL}/xhr/front/user/info",
            headers={
                'User-Agent': 'Mozilla/5.0 (Linux; Android 14; 2211133C) AppleWebKit/537.36',
                'Accept': 'application/json',
            },
            proxy=proxy_url,
            timeout=timeout,
        )
        elapsed = round((_time.time() - t0) * 1000)
        if resp.status_code == 429:
            return JSONResponse(content={'ok': False, 'reason': f'CDN限流(429)', 'elapsed_ms': elapsed})
        elif resp.status_code == 403:
            return JSONResponse(content={'ok': False, 'reason': f'HTTP禁止(403)', 'elapsed_ms': elapsed})
        elif 200 <= resp.status_code < 500:
            return JSONResponse(content={'ok': True, 'reason': f'HTTP {resp.status_code}', 'elapsed_ms': elapsed})
        else:
            return JSONResponse(content={'ok': False, 'reason': f'HTTP {resp.status_code}', 'elapsed_ms': elapsed})
    except Exception as e:
        err = str(e)[:120]
        elapsed = round((_time.time() - t0) * 1000)
        return JSONResponse(content={'ok': False, 'reason': f'连接失败: {err}', 'elapsed_ms': elapsed})
