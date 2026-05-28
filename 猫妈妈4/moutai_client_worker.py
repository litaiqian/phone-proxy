#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈分布式抢购客户端
从服务端拉取指定子账号的账号列表，按照服务端配置的抢购时间执行银联支付
支持服务端断线重连、循环拉取配置
"""

import os
import sys
import time
import json
import requests
import threading
from datetime import datetime
from typing import Dict, Any, List

from demo import MoutaiClient, _post, _get

# ===================== 配置 =====================
SERVER_BASE_URL = "http://192.168.1.3:5000"   # 修改为实际服务端地址
API_TOKEN = "your-secure-token-change-me"    # 必须与服务端 Config.API_TOKEN 一致
SUBUSER_ID = 2                               # 子账号ID（从服务端获取）

# 抢购循环参数
MAX_RUSH_ATTEMPTS = 10000
RUSH_INTERVAL = 0.8
POLL_INTERVAL_MIN = 5     # 服务端不可用时重试间隔（秒）
POLL_INTERVAL_MAX = 20

# ===================== 辅助函数 =====================
def build_client_from_task(task: dict) -> MoutaiClient:
    android_id = task['raw_device_id'][:16] if len(task['raw_device_id']) >= 16 else ""
    client = MoutaiClient(android_id=android_id, bs_dvid=task.get('bs_device_id', ''))
    client.token = task['token']
    client.cookie = task['cookie']
    client.user_id = task['user_id']
    client.mt_device_id = task['mt_device_id']
    client.raw_device_id = task['raw_device_id']
    client.h5_did = task.get('h5_did', '')
    client.h5_start_id = task.get('h5_start_id', '')
    client.bs_device_id = task.get('bs_device_id', '')
    if task.get('user_agent'):
        client.user_agent = task['user_agent']
    if task.get('webview_ua'):
        client.webview_ua = task['webview_ua']
    if task.get('mt_r'):
        client.mt_r = task['mt_r']
    if task.get('mt_sn'):
        client.mt_sn = task['mt_sn']
    return client

def report_result(phone: str, success: bool, order_id: str = "", pay_link: str = "", error: str = ""):
    """上报结果到服务端"""
    url = f"{SERVER_BASE_URL}/api/worker/report_result"
    headers = {'X-API-TOKEN': API_TOKEN, 'Content-Type': 'application/json'}
    payload = {
        'phone': phone,
        'success': success,
        'order_id': order_id,
        'pay_link': pay_link,
        'error': error
    }
    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"[上报失败] {phone}: {e}")

def fetch_config():
    """获取抢购配置（商品编码、活动ID、抢购时间）"""
    url = f"{SERVER_BASE_URL}/api/worker/get_config"
    headers = {'X-API-TOKEN': API_TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        return data
    except:
        return None

def fetch_tasks():
    """拉取分配给当前子账号的已登录账号列表"""
    url = f"{SERVER_BASE_URL}/api/worker/get_tasks"
    headers = {'X-API-TOKEN': API_TOKEN, 'Content-Type': 'application/json'}
    payload = {'subuser_id': SUBUSER_ID}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        return data.get('tasks', [])
    except:
        return []

def rush_and_pay(client: MoutaiClient, phone: str, item_code: str, act_id: str):
    """抢购+下单+银联支付全流程"""
    # 1. 抢购循环
    rush_result = None
    for attempt in range(1, MAX_RUSH_ATTEMPTS + 1):
        print(f"[{phone}] 第 {attempt} 次抢购尝试")
        try:
            rush_result = client.rush_purchase(item_code, act_id, amount="1")
            if rush_result.get("code") == 2000:
                print(f"[{phone}] 抢购成功")
                break
        except Exception as e:
            print(f"[{phone}] 抢购异常: {e}")
        time.sleep(RUSH_INTERVAL)
    else:
        report_result(phone, success=False, error="抢购超时")
        return

    # 2. 获取收货地址
    try:
        addresses = client.get_addresses()
        if not addresses:
            report_result(phone, success=False, error="无收货地址")
            return
        default_addr = next((addr for addr in addresses if addr.get("dft")), addresses[0])
    except Exception as e:
        report_result(phone, success=False, error=f"地址错误: {e}")
        return

    record_id = rush_result.get("data", {}).get("priorityRecordId", 0)
    if not record_id:
        report_result(phone, success=False, error="无priorityRecordId")
        return

    # 3. 组单
    try:
        compose_res = client.compose_order(
            spu_id=item_code, count=1, priority_record_id=record_id, address=default_addr
        )
        if compose_res.get("code") != 2000:
            report_result(phone, success=False, error=f"组单失败: {compose_res}")
            return
    except Exception as e:
        report_result(phone, success=False, error=f"组单异常: {e}")
        return

    # 4. 提交订单
    try:
        submit_res = client.submit_order(
            spu_id=item_code, count=1, priority_record_id=record_id, address=default_addr
        )
        if submit_res.get("code") != 2000:
            report_result(phone, success=False, error=f"下单失败: {submit_res}")
            return
        order_id = submit_res.get("data", {}).get("orderId")
        if not order_id:
            report_result(phone, success=False, error="无订单号")
            return
        print(f"[{phone}] 下单成功，订单号 {order_id}")
    except Exception as e:
        report_result(phone, success=False, error=f"下单异常: {e}")
        return

    # 5. 支付（银联）
    try:
        pay_res = client.pay_order(order_id)
        if pay_res.get("code") != 2000:
            report_result(phone, success=False, error=f"支付请求失败: {pay_res}")
            return
        channel_trade_sn = pay_res.get("data", {}).get("channelTradeSn")
        if not channel_trade_sn:
            report_result(phone, success=False, error="无TN")
            return
    except Exception as e:
        report_result(phone, success=False, error=f"支付异常: {e}")
        return

    # 请求支付网关（银联 pay_channel=20）
    try:
        gw_result = client.request_pay(channel_trade_sn, pay_channel="20")
        code = gw_result.get("code")
        if isinstance(code, str):
            code = int(code)
        if code not in (200, 2000):
            report_result(phone, success=False, error=f"支付网关失败: {gw_result}")
            return
        # 银联返回的 pay_link 通常在 data 中直接为URL
        pay_link = gw_result.get("data")
        if not pay_link:
            pay_link = gw_result.get("payInfo") or gw_result.get("orderInfo")
        if not pay_link:
            report_result(phone, success=False, error="未获取到银联支付链接")
            return
        print(f"[{phone}] 获取到银联支付链接: {pay_link[:80]}...")
    except Exception as e:
        report_result(phone, success=False, error=f"支付网关异常: {e}")
        return

    # 上报成功（包含支付链接）
    report_result(phone, success=True, order_id=order_id, pay_link=pay_link)

def worker_loop():
    """主循环：持续拉取配置，到达抢购时间后执行"""
    print("=== 猫妈妈抢购客户端启动 ===")
    last_rush_date = None
    while True:
        # 拉取配置
        config = fetch_config()
        if not config:
            print("无法连接服务端，等待重试...")
            time.sleep(random.uniform(POLL_INTERVAL_MIN, POLL_INTERVAL_MAX))
            continue

        rush_hour = config.get("rush_hour", 8)
        rush_minute = config.get("rush_minute", 58)
        item_code = config.get("item_code", "741")
        act_id = config.get("act_id", "76145")
        print(f"当前配置: 抢购时间 {rush_hour:02d}:{rush_minute:02d}, 商品 {item_code}, 活动 {act_id}")

        # 计算下次抢购时间
        now = datetime.now()
        target = now.replace(hour=rush_hour, minute=rush_minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)

        # 如果日期变化，重置标记
        if last_rush_date != target.date():
            last_rush_date = target.date()
            # 提前60秒开始准备
            wait_seconds = (target - now).total_seconds() - 60
            if wait_seconds > 0:
                print(f"距离下次抢购 {wait_seconds/60:.1f} 分钟，进入等待...")
                time.sleep(wait_seconds)

            # 等待精确到秒
            while datetime.now() < target:
                time.sleep(0.1)

            # 抢购开始
            print(f"抢购时间到！开始执行...")
            tasks = fetch_tasks()
            if not tasks:
                print("没有可用的账号任务")
            else:
                # 串行或并发执行（这里简单串行）
                for task in tasks:
                    client = build_client_from_task(task)
                    rush_and_pay(client, task['phone'], item_code, act_id)
                    time.sleep(1)  # 错开间隔
        else:
            # 未到抢购日，先睡眠一段时间再重新拉取配置
            time.sleep(30)

if __name__ == "__main__":
    from datetime import timedelta
    import random
    worker_loop()