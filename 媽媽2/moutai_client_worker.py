#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i茅台分布式抢购客户端
从服务端拉取指定上传者的账号，执行完整抢购->下单->支付->转链，并将结果回传。
"""

import os
import sys
import time
import json
import requests
import threading
import random
from datetime import datetime
from typing import Dict, Any, List

# 导入 demo 中的核心类与函数
from demo import MoutaiClient, _post, _get, generate_h5_did, generate_h5_start_id, generate_bs_device_id

# ===================== 配置 =====================
SERVER_BASE_URL = "http://192.168.1.3:5000"  # 修改为实际地址
API_TOKEN = "your-secure-token-change-me"  # 必须与服务端 Config.API_TOKEN 一致
UPLOADER_ID = 1  # 上传者（用户）ID，抢购该用户下的所有账号

# 抢购循环次数（针对每个账号，持续尝试直到成功或达到最大次数）
MAX_RUSH_ATTEMPTS = 100000
RUSH_INTERVAL = 0.8  # 秒


# ===================== 辅助函数 =====================

def build_client_from_task(task: dict) -> MoutaiClient:
    """根据服务端下发的任务数据重建 MoutaiClient 实例"""
    # 使用 raw_device_id 前16位作为 android_id，bs_dvid 可选
    android_id = task['raw_device_id'][:16] if len(task['raw_device_id']) >= 16 else ""
    client = MoutaiClient(android_id=android_id, bs_dvid=task.get('bs_device_id', ''))
    # 注入登录后的持久化数据
    client.token = task['token']
    client.cookie = task['cookie']
    client.user_id = task['user_id']
    client.mt_device_id = task['mt_device_id']
    client.raw_device_id = task['raw_device_id']
    client.h5_did = task.get('h5_did', generate_h5_did())
    client.h5_start_id = task.get('h5_start_id', generate_h5_start_id())
    client.bs_device_id = task.get('bs_device_id', generate_bs_device_id(client.h5_did))
    # 可选覆盖 UA 和风控字段（若服务端提供）
    if task.get('user_agent'):
        client.user_agent = task['user_agent']
    if task.get('webview_ua'):
        client.webview_ua = task['webview_ua']
    if task.get('mt_r'):
        client.mt_r = task['mt_r']
    if task.get('mt_sn'):
        client.mt_sn = task['mt_sn']
    return client


def report_result(phone: str, success: bool, order_id: str = "", h5_url: str = "", error: str = ""):
    """上报抢购结果到服务端"""
    url = f"{SERVER_BASE_URL}/api/client/report_result"
    headers = {'X-API-TOKEN': API_TOKEN, 'Content-Type': 'application/json'}
    payload = {
        'phone': phone,
        'success': success,
        'order_id': order_id,
        'h5_url': h5_url,
        'error': error,
        'bid_result_str': f"成功-{order_id}" if success else f"失败-{error[:50]}"
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        print(f"[上报失败] {phone}: {e}")
        return None


def rush_and_pay_for_account(task: dict, item_code: str, act_id: str):
    """对单个账号执行抢购+下单+支付+转链全流程"""
    phone = task['phone']
    client = build_client_from_task(task)

    # 错峰延迟（例如 rush_time_offset 秒）
    offset = task.get('rush_time_offset', 0)
    if offset:
        print(f"[{phone}] 延迟 {offset} 秒启动抢购")
        time.sleep(offset)

    # 1. 抢购循环
    rush_result = None
    for attempt in range(1, MAX_RUSH_ATTEMPTS + 1):
        print(f"[{phone}] 第 {attempt} 次抢购尝试...")
        try:
            rush_result = client.rush_purchase(item_code, act_id, amount="1")
            if rush_result.get("code") == 2000:
                print(f"[{phone}] 抢购成功！")
                break
            else:
                print(f"[{phone}] 抢购失败: {rush_result}")
        except Exception as e:
            print(f"[{phone}] 抢购异常: {e}")
        time.sleep(RUSH_INTERVAL)
    else:
        # 抢购超时失败
        report_result(phone, success=False, error="抢购超过最大尝试次数")
        return

    # 2. 获取收货地址（使用默认地址）
    try:
        addresses = client.get_addresses()
        if not addresses:
            report_result(phone, success=False, error="无收货地址")
            return
        default_addr = next((addr for addr in addresses if addr.get("dft")), addresses[0])
    except Exception as e:
        report_result(phone, success=False, error=f"获取地址失败: {e}")
        return

    record_id = rush_result.get("data", {}).get("priorityRecordId", 0)
    if not record_id:
        report_result(phone, success=False, error="未获取到 priorityRecordId")
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
            report_result(phone, success=False, error="未获取到 orderId")
            return
        print(f"[{phone}] 下单成功，订单号: {order_id}")
    except Exception as e:
        report_result(phone, success=False, error=f"下单异常: {e}")
        return

    # 5. 支付（获取 TN）
    try:
        pay_res = client.pay_order(order_id)
        if pay_res.get("code") != 2000:
            report_result(phone, success=False, error=f"支付请求失败: {pay_res}")
            return
        channel_trade_sn = pay_res.get("data", {}).get("channelTradeSn")
        if not channel_trade_sn:
            report_result(phone, success=False, error="未获取到 TN")
            return
    except Exception as e:
        report_result(phone, success=False, error=f"支付异常: {e}")
        return

    # 6. 请求支付网关（获取 SDK 串）
    try:
        gw_result = client.request_pay(channel_trade_sn, pay_channel="70")
        code = gw_result.get("code")
        if isinstance(code, str):
            code = int(code)
        if code not in (200, 2000):
            report_result(phone, success=False, error=f"支付网关失败: {gw_result}")
            return
        p_data = gw_result.get("data")
        sdk_str = p_data if isinstance(p_data, str) else (
                p_data.get("payInfo") or p_data.get("alipay_sdk")
                or p_data.get("orderInfo") or p_data.get("AUTH_CODE", "")
        ) if isinstance(p_data, dict) else ""
        if not sdk_str:
            report_result(phone, success=False, error="支付网关未返回 SDK 串")
            return
    except Exception as e:
        report_result(phone, success=False, error=f"支付网关异常: {e}")
        return

    # 7. 转链获取 H5 支付链接
    try:
        h5_result = client.convert_to_h5(sdk_str)
        if not h5_result.get("success"):
            report_result(phone, success=False, error=f"转链失败: {h5_result.get('message')}")
            return
        h5_url = h5_result["h5Url"]
        print(f"[{phone}] 获取到支付链接: {h5_url[:80]}...")
    except Exception as e:
        report_result(phone, success=False, error=f"转链异常: {e}")
        return

    # 8. 上报最终成功结果
    report_result(phone, success=True, order_id=order_id, h5_url=h5_url)


def fetch_tasks():
    """从服务端拉取任务列表"""
    url = f"{SERVER_BASE_URL}/api/client/get_tasks"
    headers = {'X-API-TOKEN': API_TOKEN, 'Content-Type': 'application/json'}
    payload = {'uploader_id': UPLOADER_ID}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get('status') == 'success':
            return data.get('tasks', [])
        else:
            print(f"拉取任务失败: {data.get('message')}")
            return []
    except Exception as e:
        print(f"拉取任务异常: {e}")
        return []


def fetch_config():
    """获取抢购商品配置"""
    url = f"{SERVER_BASE_URL}/api/client/get_config"
    headers = {'X-API-TOKEN': API_TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        return data.get('item_code', '741'), data.get('act_id', '76145')
    except Exception as e:
        print(f"获取配置失败: {e}，使用默认值")
        return '741', '76145'


def main():
    print("=== i茅台分布式抢购客户端启动 ===")
    # 1. 获取商品配置
    item_code, act_id = fetch_config()
    print(f"目标商品: {item_code}, 活动ID: {act_id}")

    # 2. 拉取任务
    tasks = fetch_tasks()
    if not tasks:
        print("没有需要执行的任务")
        return

    print(f"共获取到 {len(tasks)} 个账号，开始并发抢购...")

    # 3. 并发执行（每个账号一个线程）
    threads = []
    for task in tasks:
        t = threading.Thread(target=rush_and_pay_for_account, args=(task, item_code, act_id))
        t.daemon = True
        t.start()
        threads.append(t)
        # 避免同时启动太多，错开一点
        time.sleep(0.5)

    for t in threads:
        t.join()

    print("所有账号抢购流程结束")


if __name__ == "__main__":
    main()