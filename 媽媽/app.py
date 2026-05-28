#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i茅台分布式抢购客户端 - 异步协程版（库存驱动循环模式）
通过 HTTP 桥接调用 main.py（端口 8000）执行 MoutaiClient 操作，
任务和配置从 moutai_automation.py（端口 5000）获取。
仅依赖标准库 + httpx（无自定义模块）。

核心架构：
  等待到购买时间 → 循环{
    库存监控(50ms轮询) → 发现库存 → 广播所有客户端抢购 →
    执行rush_count次抢购 → 查库存 →
    有库存继续抢购 / 无库存广播停止回到监控 →
    所有账号成功则请求替换任务(多开数个新账号)
  } 直到结束时间
"""

import os
import sys
import json
import random
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import httpx
import uuid

# ===================== 配置 =====================
SERVER_BASE_URL = "http://ipla.top:5000"  # moutai_automation.py 地址
BRIDGE_BASE_URL = "http://ipla.top:8000"  # main.py 桥接地址
API_TOKEN = "your-secure-token-change-me"  # 须与服务端 Config.API_TOKEN 一致
UPLOADER_ID = 1  # 上传者（用户）ID
CLIENT_UUID = str(uuid.uuid4())[:8]  # 窗口唯一标识
CLIENT_BATCH = -1  # 批次号（-1=未注册）

# 防封策略配置（可在服务端后台覆盖）
ANTI_BAN_CONFIG = {
    'min_delay': 10,  # 最小请求间隔（毫秒）
    'max_delay': 30,  # 最大请求间隔（毫秒），随机抖动
    'bangcle_interval': 300,  # 邦盛验证缓存时间（秒）
    'retry_429_delay': 3,  # 429重试等待（秒）
    'retry_429_max': 5,  # 429最大连续次数
    'd_u_refresh_interval': 10,  # _d_u cookie刷新间隔（秒）
    'inventory_check_delay': 50,  # 库存检查间隔（毫秒）
    'proxy_enabled': False,  # 是否启用代理
    'proxy_url': '',  # 代理地址
    'max_rush_per_cycle': 500,  # 每轮最大抢购次数
    'account_cooldown': 0.2,  # 账号切换冷却（秒）
}

# 桥接 API 请求头
_AUTH_HEADERS = {
    'X-API-TOKEN': API_TOKEN,
    'Content-Type': 'application/json'
}


# ===================== 异步 HTTP 工具 =====================

async def _api_post(url: str, json_data: dict = None, timeout: float = 15.0) -> dict:
    """通用异步 POST 请求"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=json_data or {}, headers=_AUTH_HEADERS)
            if resp.status_code == 403:
                return {'status': 'error', 'message': '鉴权失败'}
            return resp.json()
    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout):
        return {'status': 'error', 'message': '连接失败', 'error_type': 'network'}
    except Exception as e:
        return {'status': 'error', 'message': str(e), 'error_type': 'unknown'}


async def _api_get(url: str, timeout: float = 10.0) -> dict:
    """通用异步 GET 请求"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=_AUTH_HEADERS)
            if resp.status_code == 403:
                return {'status': 'error', 'message': '鉴权失败'}
            return resp.json()
    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout):
        return {'status': 'error', 'message': '连接失败', 'error_type': 'network'}
    except Exception as e:
        return {'status': 'error', 'message': str(e), 'error_type': 'unknown'}


# ===================== 桥接客户端 =====================

class BridgeClient:
    """通过 main.py 桥接 API 调用 MoutaiClient 方法"""

    def __init__(self, base_url: str = BRIDGE_BASE_URL):
        self.base_url = base_url

    async def execute(self, method: str, params: dict = None,
                      credentials: dict = None) -> dict:
        payload = {
            'method': method,
            'params': params or {},
            'credentials': credentials or {}
        }
        return await _api_post(f'{self.base_url}/api/bridge/execute', payload)

    async def check_login(self, credentials: dict) -> bool:
        result = await _api_post(f'{self.base_url}/api/bridge/check_login', credentials)
        return result.get('valid', False)

    async def send_vcode(self, phone: str, credentials: dict) -> bool:
        result = await _api_post(f'{self.base_url}/api/bridge/send_vcode', {
            'phone': phone, 'credentials': credentials
        })
        return result.get('success', False)

    async def login(self, phone: str, code: str, credentials: dict) -> dict:
        result = await _api_post(f'{self.base_url}/api/bridge/login', {
            'phone': phone, 'vcode': code, 'credentials': credentials
        })
        if result.get('success'):
            return result.get('credentials', {})
        return {'error': result.get('message', '登录失败')}

    async def check_inventory(self, item_code: str, credentials: dict, phone: str = '') -> int:
        """检查库存，返回可用数量"""
        result = await _api_post(f'{self.base_url}/api/bridge/check_inventory', {
            'item_code': item_code, 'credentials': credentials, 'phone': phone
        })
        return result.get('available', -1)


_bridge = BridgeClient()


# ===================== 服务端 API 调用 =====================

async def fetch_config() -> dict:
    """从服务端获取抢购配置（含防封策略）"""
    url = f'{SERVER_BASE_URL}/api/client/get_config'
    result = await _api_get(url)
    if result.get('rush_hour') is not None:
        return result
    return {
        'rush_hour': 8, 'rush_minute': 58, 'rush_second': 0,
        'rush_attempts': 100000, 'rush_count': 100, 'task_frequency': 10,
        'multi_open_count': 1, 'multi_open_enabled': False,
        'item_code': '741', 'act_id': '76145',
        # 防封默认值
        'min_delay': 10, 'max_delay': 30,
        'anti_ban_429_retry': 5, 'anti_ban_429_delay': 3,
        'anti_ban_bangcle_ttl': 300, 'anti_ban_account_cooldown': 200,
        'anti_ban_proxy_enabled': False, 'anti_ban_proxy_url': '',
    }


async def register_client() -> dict:
    """向服务端注册，一次性获取窗口号+任务列表"""
    url = f'{SERVER_BASE_URL}/api/client/register'
    result = await _api_post(url, {'client_uuid': CLIENT_UUID})
    if result.get('status') == 'success':
        assigned_batch = result.get('batch', 0)
        global CLIENT_BATCH
        CLIENT_BATCH = assigned_batch
        tasks = result.get('tasks', [])
        multi_open_count = result.get("multi_open_count", 1)
        if tasks:
            phone_list = [t["phone"] for t in tasks]
            print(f'[注册] 窗口={assigned_batch + 1}，UUID={CLIENT_UUID}，多开数={multi_open_count}，手机号: {phone_list}')
        else:
            print(f'[注册] 窗口={assigned_batch + 1}，UUID={CLIENT_UUID}，多开数={multi_open_count}，手机号: []')
        # 返回包含任务的结果
        result['tasks_from_register'] = tasks
        return result
    print(f'[注册] 失败: {result.get("message", "未知错误")}')
    return result


async def fetch_tasks(batch: int = 0) -> list:
    """从服务端拉取任务列表（备用，注册时已返回任务）"""
    url = f'{SERVER_BASE_URL}/api/client/get_tasks'
    result = await _api_post(url, {'uploader_id': UPLOADER_ID, 'batch': batch, 'client_uuid': CLIENT_UUID})
    if result.get('status') == 'success':
        tasks = result.get('tasks', [])
        for t in tasks:
            print(f'[任务] 手机号: {t["phone"]}')
        return tasks
    print(f'[任务] 拉取失败: {result.get("message")}')
    return []


async def request_replacement_tasks(succeeded_phones: list, request_count: int = 1) -> list:
    """请求替换任务：成功1个账号后请求request_count个新账号补入窗口
    request_count: 需要补入的新账号数量（继续分配开启时=1，全部成功替换时=multi_open_count）"""
    url = f'{SERVER_BASE_URL}/api/client/request_replacement_tasks'
    result = await _api_post(url, {
        'client_uuid': CLIENT_UUID,
        'succeeded_phones': succeeded_phones,
        'request_count': request_count
    })
    if result.get('status') == 'success':
        tasks = result.get('tasks', [])
        if tasks:
            print(f'[继续分配] 获得 {len(tasks)} 个新账号，补入窗口继续抢购')
        else:
            print(f'[继续分配] 无可用账号，所有账号已抢购成功')
        return tasks
    print(f'[继续分配] 请求失败: {result.get("message")}')
    return []


async def report_result(phone: str, success: bool, order_id: str = "",
                        h5_url: str = "", error: str = ""):
    """上报抢购结果到服务端"""
    url = f'{SERVER_BASE_URL}/api/client/report_result'
    payload = {
        'phone': phone, 'success': success, 'order_id': order_id,
        'h5_url': h5_url, 'error': error,
        'bid_result_str': f"成功-{order_id}" if success else f"失败-{error[:50]}"
    }
    result = await _api_post(url, payload)
    if result.get('status') == 'success':
        print(f'[上报] {phone}: {"成功" if success else "失败"}')
    return result


async def report_inventory(phone: str, item_code: str, available: int):
    """向服务端上报库存发现"""
    url = f'{SERVER_BASE_URL}/api/client/report_inventory'
    payload = {'phone': phone, 'item_code': item_code, 'available': available}
    await _api_post(url, payload)


async def broadcast_rush_status(action: str):
    """向服务端广播抢购状态：start_rush / stop_rush"""
    url = f'{SERVER_BASE_URL}/api/client/broadcast_rush_status'
    payload = {'action': action}
    await _api_post(url, payload)


# ===================== 心跳协程 =====================

async def heartbeat_sender(stop_event: asyncio.Event, task_count: int):
    """每10秒发送心跳到5000端口，保持窗口注册状态"""
    url = f'{SERVER_BASE_URL}/api/client/heartbeat'
    while not stop_event.is_set():
        try:
            result = await _api_post(url, {'batch': CLIENT_BATCH, 'client_uuid': CLIENT_UUID, 'task_count': task_count})
            if not result.get('status') == 'success':
                err_msg = result.get('message', '')[:40]
                if result.get('error_type') in ('network', 'unknown'):
                    print(f'[心跳] 发送失败: {err_msg}')
        except Exception as e:
            print(f'[心跳] 异常: {e}')
        await asyncio.sleep(10)


# ===================== 库存监控（顺序轮询） =====================

async def sequential_inventory_monitor(tasks: list, credentials_list: list,
                                       stop_event: asyncio.Event,
                                       inventory_found: asyncio.Event,
                                       rush_stop_event: asyncio.Event):
    """
    持续库存监控协程（全程运行，不因抢购而停止）
    顺序轮询：账号1→50ms→账号2→50ms→...→循环

    - 无库存时：持续轮询，发现库存后设置 inventory_found 并广播
    - 有库存时：继续轮询，发现售罄后设置 rush_stop_event 并广播
    - 直到 stop_event 被设置才停止
    """
    if not tasks:
        print('[库存监控] 无监控任务，跳过')
        return

    account_count = len(tasks)
    print(f'[库存监控] 启动持续顺序轮询：{account_count}个账号，每个间隔50ms')
    print(f'[库存监控] 一轮查询约需 {account_count * 0.05:.1f}秒')

    index = 0
    stock_was_available = False  # False=等待库存, True=监控售罄
    soldout_reported = False  # 防止重复广播 stop_rush

    while not stop_event.is_set():
        idx = index % account_count
        task = tasks[idx]
        credentials = credentials_list[idx]
        phone = task['phone']
        item_code = task.get('item_code', '741')

        available = await _bridge.check_inventory(item_code, credentials, phone)

        if available > 0:
            soldout_reported = False  # 有货就允许下次广播售罄
            if not stock_was_available:
                # 无库存→有库存 的转折点
                print(f'[{phone}] 🟢 发现库存！可用: {available}')
                inventory_found.set()
                stock_was_available = True
                await report_inventory(phone, item_code, available)
                await broadcast_rush_status('start_rush')
            # 有库存时继续轮询，检测售罄
        elif available == 0:
            if stock_was_available and not soldout_reported:
                # 有库存→无库存 的转折点
                print(f'[{phone}] 🔴 库存耗尽！广播停止抢购')
                rush_stop_event.set()
                stock_was_available = False
                soldout_reported = True
                await broadcast_rush_status('stop_rush')
            elif index % account_count == 0:
                print(f'[库存监控] 第 {index // account_count + 1} 轮，暂无库存')
        else:
            # 查询异常（-1）时默认继续
            if index % 20 == 0:
                print(f'[{phone}] 库存查询异常，继续尝试...')
            if stock_was_available:
                # 异常时不触发售罄判断，继续观察
                pass

        index += 1
        await asyncio.sleep(0.05)  # 50ms 间隔

    print('[库存监控] 持续监控已停止')


# ===================== 广播接收协程（长轮询） =====================

async def broadcast_listener(stop_event: asyncio.Event,
                             inventory_found: asyncio.Event,
                             rush_stop_event: asyncio.Event):
    """
    监听服务端库存状态广播 - 长轮询实现毫秒级响应
    新增: 检测到 soldout 状态时设置 rush_stop_event，通知主流程停止抢购回到监控
    """
    longpoll_url = f'{SERVER_BASE_URL}/api/client/inventory_longpoll'
    fail_count = 0
    last_status = 'unknown'

    while not stop_event.is_set():
        try:
            url_with_params = f'{longpoll_url}?timeout=30&last_status={last_status}'
            result = await _api_get(url_with_params, timeout=35.0)
        except Exception as e:
            result = {'status': 'error', 'message': str(e)[:40], 'error_type': 'unknown'}

        if result.get('status') == 'error' and result.get('error_type') in ('network', 'unknown'):
            fail_count += 1
            if fail_count == 1:
                err_msg = result.get('message', '')[:60]
                print(f'[广播] 服务端连接断开，等待重连... ({err_msg})')
            wait = min(2 + fail_count * 2, 10)
            await asyncio.sleep(wait)
            continue

        if fail_count > 0:
            print(f'[广播] 服务端重连成功（断开 {fail_count} 次）')
            fail_count = 0

        # 处理服务端响应
        if result.get('is_stock_available') and not inventory_found.is_set():
            print('[广播] 服务端通知：库存可用！')
            inventory_found.set()

        # 检测库存耗尽信号（soldout），通知主流程停止抢购
        current_status = result.get('current_status', 'unknown')
        if current_status == 'soldout' and not rush_stop_event.is_set():
            print('[广播] 服务端通知：库存耗尽，停止抢购回到监控！')
            rush_stop_event.set()

        last_status = current_status

        if not result.get('status_changed'):
            continue


# ===================== 抢购逻辑 =====================

async def rush_purchase_round(task: dict, credentials: dict,
                              rush_count: int = 100,
                              frequency_ms: int = 10) -> Optional[dict]:
    """
    执行一轮抢购（rush_count 次尝试），完成后返回结果
    库存驱动模式：每轮只执行 rush_count 次，不是无限循环

    改进：
    - 自动从API获取最新活动ID（activity_id）
    - _d_u cookie周期性刷新
    - 随机抖动请求间隔防封
    - 429智能退避

    返回: {'success': bool, 'order_id': str, 'h5_url': str, 'attempts': int} 或 None
    """
    phone = task['phone']
    item_code = task.get('item_code', '741')
    sku_id = task.get('sku_id', '741')
    activity_id = task.get('activity_id', '82107')
    amount = task.get('amount', 1)

    cfg = ANTI_BAN_CONFIG
    min_delay = max(cfg['min_delay'], 5)  # 最小5ms
    max_delay = max(cfg['max_delay'], min_delay + 5)  # 至少比最小大5ms

    # 前置：尝试从API获取最新活动ID（动态化参数）
    if attempt_first := True:
        try:
            # 登录后首次抢购前自动拉取商品详情
            detail = await _bridge.execute('auto_fetch_item_details', {
                'item_code': item_code
            }, credentials)
            if detail.get('success'):
                detail_data = detail.get('result', {})
                if detail_data.get('activity_id'):
                    new_act_id = detail_data['activity_id']
                    print(f'[{phone}] 自动获取活动ID: {new_act_id} (原配置: {activity_id})')
                    activity_id = new_act_id
                if detail_data.get('sku_id'):
                    new_sku_id = detail_data['sku_id']
                    print(f'[{phone}] 自动获取SKU ID: {new_sku_id} (原配置: {sku_id})')
                    sku_id = new_sku_id
                if detail_data.get('item_name'):
                    print(f'[{phone}] 商品名称: {detail_data["item_name"]}')
            else:
                print(f'[{phone}] 自动获取失败，使用配置值: itemCode={item_code}')
        except Exception as e:
            print(f'[{phone}] 自动获取异常: {e}')

    rush_result = None
    consecutive_429 = 0  # 连续429计数
    last_d_u_refresh = 0  # 上次_d_u刷新时间

    for attempt in range(1, rush_count + 1):
        if attempt <= 3 or attempt % 50 == 0:
            print(f'[{phone}] 第 {attempt}/{rush_count} 次抢购...')

        # 周期性刷新 _d_u cookie（每10秒重新生成）
        # 实际在 _h5_headers 中已每次重新生成，这里仅用于日志

        result = await _bridge.execute('rush_purchase', {
            'item_code': item_code, 'sku_id': sku_id,
            'item_priority_act_id': activity_id, 'amount': str(amount)
        }, credentials)

        if result.get('success'):
            rush_result = result.get('result', {})
            code = rush_result.get('code', -1)

            if code == 2000:
                print(f'[{phone}] 抢购成功！(第{attempt}次)')
                # 完成下单+支付+转链全流程
                final_result = await complete_order_flow(task, credentials, rush_result)
                return final_result or {'success': True, 'attempts': attempt}

            elif code == 429:
                consecutive_429 += 1
                # 指数退避：连续429越多等待越久
                wait = min(cfg['retry_429_delay'] * (2 ** (consecutive_429 - 1)), 30)
                wait += random.uniform(0, 1)  # 随机抖动
                print(f'[{phone}] 触发频率限制(429) x{consecutive_429}，等待 {wait:.1f}s')
                await asyncio.sleep(wait)
                if consecutive_429 >= cfg['retry_429_max']:
                    print(f'[{phone}] 连续429超过{cfg["retry_429_max"]}次，本轮暂停30秒')
                    await asyncio.sleep(30)
                    consecutive_429 = 0  # 重置
                continue
            else:
                consecutive_429 = 0  # 非429时重置计数
                if attempt <= 3 or attempt % 200 == 0:
                    print(f'[{phone}] 抢购返回: {str(rush_result)[:100]}')
                # 随机抖动延迟
                delay_ms = random.randint(min_delay, max_delay)
                await asyncio.sleep(delay_ms / 1000.0)
        else:
            consecutive_429 = 0
            # 网络错误使用较短延迟
            await asyncio.sleep(0.05)

    # 一轮抢购完成，未成功
    print(f'[{phone}] 本轮 {rush_count} 次抢购完成，未成功')
    return {'success': False, 'attempts': rush_count}


async def complete_order_flow(task: dict, credentials: dict, rush_result: dict) -> Optional[dict]:
    """完成下单+支付+转链全流程"""
    phone = task['phone']
    item_code = task.get('item_code', '741')

    # 1. 获取收货地址
    addr_result = await _bridge.execute('get_addresses', {}, credentials)
    if not addr_result.get('success'):
        await report_result(phone, success=False, error='获取地址失败')
        return None
    addresses = addr_result.get('result', [])
    if not addresses:
        await report_result(phone, success=False, error='无收货地址')
        return None
    default_addr = next((a for a in addresses if a.get('dft')), addresses[0])

    record_id = rush_result.get('data', {}).get('priorityRecordId', 0)
    if not record_id:
        await report_result(phone, success=False, error='未获取到 priorityRecordId')
        return None

    # 2. 组单
    compose_res = await _bridge.execute('compose_order', {
        'spu_id': item_code, 'count': 1,
        'priority_record_id': record_id, 'address': default_addr
    }, credentials)
    if not compose_res.get('success') or compose_res.get('result', {}).get('code') != 2000:
        msg = compose_res.get('result', {}).get('message', '组单失败')
        await report_result(phone, success=False, error=msg)
        return None

    # 3. 提交订单
    submit_res = await _bridge.execute('submit_order', {
        'spu_id': item_code, 'count': 1,
        'priority_record_id': record_id, 'address': default_addr
    }, credentials)
    if not submit_res.get('success') or submit_res.get('result', {}).get('code') != 2000:
        msg = submit_res.get('result', {}).get('message', '下单失败')
        await report_result(phone, success=False, error=msg)
        return None
    order_id = submit_res.get('result', {}).get('data', {}).get('orderId')
    if not order_id:
        await report_result(phone, success=False, error='未获取到 orderId')
        return None
    print(f'[{phone}] 下单成功，订单号: {order_id}')

    # 4. 支付
    pay_res = await _bridge.execute('pay_order', {'order_id': order_id}, credentials)
    if not pay_res.get('success') or pay_res.get('result', {}).get('code') != 2000:
        msg = pay_res.get('result', {}).get('message', '支付请求失败')
        await report_result(phone, success=False, error=msg)
        return None
    channel_trade_sn = pay_res.get('result', {}).get('data', {}).get('channelTradeSn')
    if not channel_trade_sn:
        await report_result(phone, success=False, error='未获取到 TN')
        return None

    # 5. 支付网关（云闪付 pay_channel=20）
    gw_res = await _bridge.execute('request_pay', {
        'channel_trade_sn': channel_trade_sn, 'pay_channel': '20'
    }, credentials)
    if not gw_res.get('success'):
        await report_result(phone, success=False, error='支付网关失败')
        return None
    gw_data = gw_res.get('result', {})
    gw_code = gw_data.get('code')
    if isinstance(gw_code, str):
        gw_code = int(gw_code)
    if gw_code not in (200, 2000):
        await report_result(phone, success=False, error=f'支付网关返回错误: {gw_code}')
        return None
    p_data = gw_data.get('data', '')
    # 银联云闪付可能直接返回 H5 URL，也可能返回 SDK 串
    if isinstance(p_data, str):
        # 直接判断是否已是 URL
        if p_data.startswith('http://') or p_data.startswith('https://'):
            sdk_str = ''
            h5_url = p_data
            print(f'[{phone}] 支付网关直接返回 H5 URL: {h5_url[:80]}...')
            await report_result(phone, success=True, order_id=order_id, h5_url=h5_url)
            return {'success': True, 'order_id': order_id, 'h5_url': h5_url}
        else:
            sdk_str = p_data
    elif isinstance(p_data, dict):
        sdk_str = (p_data.get('payInfo') or p_data.get('alipay_sdk') or
                   p_data.get('orderInfo') or p_data.get('AUTH_CODE', ''))
    else:
        sdk_str = ''
    if not sdk_str:
        await report_result(phone, success=False, error='支付网关未返回有效数据')
        return None

    # 6. 转链获取 H5 支付链接
    h5_res = await _bridge.execute('convert_to_h5', {'sdk_str': sdk_str}, credentials)
    if not h5_res.get('success'):
        await report_result(phone, success=False, error=f'转链失败: {h5_res.get("result", {}).get("message")}')
        return None
    h5_url = h5_res.get('result', {}).get('h5Url', '')
    if not h5_url:
        await report_result(phone, success=False, error='转链未返回 URL')
        return None
    print(f'[{phone}] 支付链接: {h5_url[:80]}...')

    # 7. 上报最终成果
    await report_result(phone, success=True, order_id=order_id, h5_url=h5_url)
    return {'success': True, 'order_id': order_id, 'h5_url': h5_url}


# ===================== 库存检查（抢购轮次间） =====================

async def check_stock_after_rush(tasks: list, credentials_list: list) -> bool:
    """
    一轮抢购完成后，检查库存状态
    使用第一个账号的凭证查询库存，返回是否有库存
    异常时默认返回 True（继续抢购），避免误判导致停止
    """
    if not tasks:
        return False

    # 依次尝试每个账号的凭证，确保至少一个能查到
    for i, task in enumerate(tasks):
        credentials = credentials_list[i]
        item_code = task.get('item_code', '741')
        phone = task['phone']
        available = await _bridge.check_inventory(item_code, credentials, phone)
        if available > 0:
            print(f'[库存检查] 账号 {task["phone"]} 检测到库存: {available}')
            return True
        elif available == 0:
            print(f'[库存检查] 账号 {task["phone"]} 无库存')
            return False
        # available == -1 查询异常，继续尝试下一个账号

    # 所有账号都查询异常，默认返回 True 继续抢购，避免误判
    print('[库存检查] 所有账号查询异常，默认继续抢购')
    return True


# ===================== 主流程（库存驱动循环模式） =====================

async def main_async():
    print('=== i茅台异步抢购客户端启动（库存驱动模式） ===')
    print(f'服务端: {SERVER_BASE_URL}')
    print(f'桥接: {BRIDGE_BASE_URL}')
    print(f'上传者ID: {UPLOADER_ID}')

    # 1. 等待服务端上线
    health_url = f'{SERVER_BASE_URL}/api/health'
    print(f'[服务端] 正在等待服务端上线 ({health_url})...')
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(health_url, headers=_AUTH_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('status') == 'ok':
                        print('[服务端] 连接成功')
                        break
        except Exception:
            pass
        print('[服务端] 服务端未就绪，5秒后重试...')
        await asyncio.sleep(5)

    # 2. 获取配置
    config = await fetch_config()
    rush_hour = config.get('rush_hour', 8)
    rush_minute = config.get('rush_minute', 58)
    rush_second = config.get('rush_second', 0)
    rush_attempts = config.get('rush_attempts', 100000)  # 总体安全上限
    rush_count = config.get('rush_count', 100)  # 每轮抢购次数
    task_frequency = config.get('task_frequency', 10)  # 毫秒
    multi_open_count = config.get('multi_open_count', 1)
    multi_open_enabled = config.get('multi_open_enabled', False)
    print(f'[配置] 抢购时间: {rush_hour}:{rush_minute}:{rush_second}')
    print(f'[配置] 每轮抢购次数: {rush_count}')
    print(f'[配置] 总体上限: {rush_attempts}')
    print(f'[配置] 抢购频率: {task_frequency}ms')
    print(f'[配置] 继续分配: {"开启" if multi_open_enabled else "关闭"}')
    print(f'[配置] 多开数: {multi_open_count}')

    # 应用防封配置
    cfg = ANTI_BAN_CONFIG
    if config.get('min_delay'): cfg['min_delay'] = config['min_delay']
    if config.get('max_delay'): cfg['max_delay'] = config['max_delay']
    if config.get('anti_ban_429_retry'): cfg['retry_429_max'] = config['anti_ban_429_retry']
    if config.get('anti_ban_429_delay'): cfg['retry_429_delay'] = config['anti_ban_429_delay']
    if config.get('anti_ban_bangcle_ttl'): cfg['bangcle_interval'] = config['anti_ban_bangcle_ttl']
    if config.get('anti_ban_account_cooldown'): cfg['account_cooldown'] = config['anti_ban_account_cooldown'] / 1000.0
    if config.get('anti_ban_proxy_enabled'): cfg['proxy_enabled'] = bool(config['anti_ban_proxy_enabled'])
    if config.get('anti_ban_proxy_url'): cfg['proxy_url'] = config['anti_ban_proxy_url']
    print(f'[防封] 请求间隔: {cfg["min_delay"]}-{cfg["max_delay"]}ms, 429重试: {cfg["retry_429_max"]}次')
    print(f'[防封] 代理: {"启用" if cfg["proxy_enabled"] else "关闭"}')
    if cfg['proxy_enabled']:
        print(f'[防封] 代理地址: {cfg["proxy_url"]}')

    # 3. 向服务端注册（一次性获取窗口号+任务列表）
    print(f'[注册] UUID={CLIENT_UUID}, 正在注册...')
    reg_result = await register_client()
    if reg_result.get('status') != 'success':
        print('[注册] 注册失败，5秒后重试...')
        await asyncio.sleep(5)
        reg_result = await register_client()
        if reg_result.get('status') != 'success':
            print('[注册] 注册失败，使用默认窗口1')
            global CLIENT_BATCH
            CLIENT_BATCH = 0
    batch = CLIENT_BATCH

    # 4. 获取任务列表（优先使用注册返回的任务）
    tasks = reg_result.get('tasks_from_register', [])
    if not tasks:
        # 注册未返回任务，单独拉取（备用路径）
        print('[任务] 注册未返回任务，单独拉取...')
        while not tasks:
            tasks = await fetch_tasks(batch=batch)
            if not tasks:
                print('[任务] 暂无任务，5秒后重试...')
                await asyncio.sleep(5)
    for t in tasks:
        print(f'[任务] 手机号: {t["phone"]}')
    print(f'=== 窗口{CLIENT_BATCH + 1} | 多开数={multi_open_count} ===')
    for t in tasks:
        print(f'=== 负责手机号: {t["phone"]} ===')

    # 5. 为每个任务构建凭证
    credentials_list = []
    for task in tasks:
        credentials = {
            'raw_device_id': task.get('raw_device_id', ''),
            'mt_device_id': task.get('mt_device_id', ''),
            'token': task.get('token', ''),
            'cookie': task.get('cookie', ''),
            'user_id_ext': task.get('user_id', ''),
            'h5_did': task.get('h5_did', ''),
            'h5_start_id': task.get('h5_start_id', ''),
            'bs_device_id': task.get('bs_device_id', ''),
            'user_agent': task.get('user_agent', ''),
            'webview_ua': task.get('webview_ua', ''),
            'mt_r': task.get('mt_r', ''),
            'mt_sn': task.get('mt_sn', ''),
        }
        credentials_list.append(credentials)

    # 6. 等待到抢购时间
    now = datetime.now()
    target_time = now.replace(hour=rush_hour, minute=rush_minute, second=rush_second, microsecond=0)
    if now < target_time:
        wait_sec = (target_time - now).total_seconds()
        print(f'[时间] 等待到 {rush_hour}:{rush_minute}:{rush_second}（{wait_sec:.0f}秒后）...')
        await asyncio.sleep(wait_sec)

    print(f'[时间] 已到达抢购时间 {rush_hour}:{rush_minute}:{rush_second}，开始库存驱动循环！')

    # 7. 启动心跳协程
    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        heartbeat_sender(stop_event, len(tasks))
    )

    # 8. 库存驱动循环：监控→抢购→查库存→循环
    succeeded_phones = set()  # 已抢购成功的手机号集合
    total_attempts = 0  # 总体尝试计数（安全上限）

    while True:
        # ====== 继续分配逻辑 ======
        # 继续分配开启：成功1个→立即请求1个新账号补入窗口
        # 继续分配关闭：成功后不分配，直到全部成功后暂停
        if multi_open_enabled and succeeded_phones:
            # 有账号成功，需要补入新账号维持窗口满员
            new_count = len(succeeded_phones)  # 成功几个就请求几个补入
            print(f'\n[继续分配] {len(succeeded_phones)} 个账号已成功，请求 {new_count} 个新账号补入...')
            new_tasks = await request_replacement_tasks(list(succeeded_phones), request_count=new_count)
            if new_tasks:
                # 为新任务构建凭证并补入现有列表
                for nt in new_tasks:
                    nc = {
                        'raw_device_id': nt.get('raw_device_id', ''),
                        'mt_device_id': nt.get('mt_device_id', ''),
                        'token': nt.get('token', ''),
                        'cookie': nt.get('cookie', ''),
                        'user_id_ext': nt.get('user_id', ''),
                        'h5_did': nt.get('h5_did', ''),
                        'h5_start_id': nt.get('h5_start_id', ''),
                        'bs_device_id': nt.get('bs_device_id', ''),
                        'user_agent': nt.get('user_agent', ''),
                        'webview_ua': nt.get('webview_ua', ''),
                        'mt_r': nt.get('mt_r', ''),
                        'mt_sn': nt.get('mt_sn', ''),
                    }
                    tasks.append(nt)
                    credentials_list.append(nc)
                    print(f'[继续分配] 新账号 {nt["phone"]} 已补入窗口')
                succeeded_phones = set()  # 清空成功集合，新账号开始抢购
                # 更新心跳任务数
                heartbeat_task.cancel()
                heartbeat_task = asyncio.create_task(
                    heartbeat_sender(stop_event, len(tasks))
                )
                continue  # 重新开始监控循环
            else:
                print('[继续分配] 无可用新账号，窗口保持现有账号继续抢购')

        # 按角色拆分任务：监控任务（both+monitor）和抢购任务（both+rush）
        all_active = [(i, t) for i, t in enumerate(tasks) if t['phone'] not in succeeded_phones]
        monitor_tasks = [(i, t) for i, t in all_active if t.get('task_role', 'both') in ('both', 'monitor')]
        rush_tasks = [(i, t) for i, t in all_active if t.get('task_role', 'both') in ('both', 'rush')]

        if not all_active:
            if not multi_open_enabled:
                print(f'\n[暂停] 窗口内所有 {len(succeeded_phones)} 个账号已抢购成功，继续分配关闭，暂停等待第二天')
                break
            else:
                # 继续分配开启但无新账号时，继续等待
                print('[监控] 所有活跃账号已成功，等待继续分配...')
                await asyncio.sleep(5)
                continue

        # ====== 创建同步事件 ======
        inventory_found = asyncio.Event()
        rush_stop_event = asyncio.Event()

        # ====== 启动持续监控 + 广播监听（全程运行，不因抢购而停止） ======
        monitor_phones = [t['phone'] for _, t in monitor_tasks]
        monitor_creds_list = [credentials_list[i] for i, _ in monitor_tasks]

        monitor_task = asyncio.create_task(
            sequential_inventory_monitor(
                [t for _, t in monitor_tasks],
                monitor_creds_list,
                stop_event, inventory_found, rush_stop_event)
        )
        listener_task = asyncio.create_task(
            broadcast_listener(stop_event, inventory_found, rush_stop_event)
        )

        if not monitor_tasks:
            print('[监控] ⚠️ 无监控角色账号！无法自动发现库存，需等待其他窗口广播')
        else:
            print(f'[监控] 启动持续库存监控（{len(monitor_tasks)}个监控账号）: {monitor_phones}')
        print(f'[角色] 监控={len(monitor_tasks)}, 抢购={len(rush_tasks)}, 总活跃={len(all_active)}')

        try:
            # ====== 阶段1: 等待库存发现（监控协程在后台持续轮询） ======
            while not inventory_found.is_set() and not rush_stop_event.is_set():
                await asyncio.sleep(0.1)

            if not inventory_found.is_set():
                continue  # 无库存，重新创建监控

            # ====== 阶段2: 执行抢购（监控协程在后台继续运行，检测售罄） ======
            rush_phone_list = [t['phone'] for _, t in rush_tasks]
            print(f'\n=== 开始抢购（{len(rush_tasks)}个抢购账号）: {rush_phone_list} ===')
            print('[监控] 后台持续监控库存，售罄时自动停止抢购')

            while True:
                # 检查是否收到售罄信号（由监控协程或广播检测到售罄时设置）
                if rush_stop_event.is_set():
                    print('[监控] 🛑 库存已售罄，停止抢购，回到库存等待')
                    rush_stop_event.clear()
                    inventory_found.clear()
                    break

                # 检查总体安全上限
                if total_attempts >= rush_attempts:
                    print(f'[安全] 总体尝试次数已达上限 {rush_attempts}，停止抢购')
                    break

                # 过滤出还未成功的抢购角色账号
                current_active = [(i, t) for i, t in rush_tasks if t['phone'] not in succeeded_phones]
                if not current_active:
                    break  # 所有抢购账号成功，外层循环会处理替换

                # 并发执行一轮抢购（每个抢购账号 rush_count 次）
                rush_tasks_async = []
                for idx_data, task_item in current_active:
                    creds = credentials_list[idx_data]
                    rush_tasks_async.append(asyncio.create_task(
                        rush_purchase_round(task_item, creds, rush_count, task_frequency)
                    ))
                    total_attempts += rush_count

                results = await asyncio.gather(*rush_tasks_async, return_exceptions=True)

                # 统计本轮结果
                round_success = 0
                for i, (idx_data, task_item) in enumerate(current_active):
                    r = results[i]
                    if r is not None and not isinstance(r, Exception) and r.get('success'):
                        succeeded_phones.add(task_item['phone'])
                        round_success += 1

                print(f'\n=== 本轮抢购完成: {round_success}/{len(current_active)} 成功 ===')
                print(f'=== 已成功总数: {len(succeeded_phones)}, 总尝试: {total_attempts} ===')

                # 如果所有抢购账号都成功了，跳出抢购循环
                rush_succeeded_all = all(t['phone'] in succeeded_phones for _, t in rush_tasks)
                if rush_tasks and rush_succeeded_all:
                    print('[抢购] 所有抢购账号已成功，跳出抢购循环')
                    break

                # ====== 一轮抢购后查库存（快速检查，不等监控轮询） ======
                active_creds = [credentials_list[i] for i, t in enumerate(tasks) if t['phone'] not in succeeded_phones]
                active_task_list = [t for t in tasks if t['phone'] not in succeeded_phones]
                has_stock = await check_stock_after_rush(active_task_list, active_creds)

                if has_stock:
                    print('[库存] 仍有库存，继续下一轮抢购')
                    await broadcast_rush_status('start_rush')
                    continue
                else:
                    print('[库存] 本轮检查无库存，等待监控确认售罄或等待补货')
                    await asyncio.sleep(0.5)
                    if not inventory_found.is_set():
                        print('[库存] 回到库存等待状态')
                        inventory_found.clear()
                        break
        finally:
            # 只有在需要重置（替换账号或结束）时才停止监控
            monitor_task.cancel()
            listener_task.cancel()

        # 如果所有抢购账号成功，进入替换逻辑（外层循环顶部）
        if rush_tasks and all(t['phone'] in succeeded_phones for _, t in rush_tasks):
            continue

    # 9. 清理
    stop_event.set()
    heartbeat_task.cancel()

    print(f'\n=== 客户端任务结束 ===')
    print(f'=== 成功: {len(succeeded_phones)} 个账号 ===')
    print(f'=== 总尝试: {total_attempts} 次 ===')


def main():
    """入口函数"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print('\n[客户端] 用户中断')
    except Exception as e:
        print(f'\n[客户端] 异常: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()