#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i茅台分布式抢购客户端
从服务端拉取指定上传者的账号，执行完整抢购->下单->支付->转链，并将结果回传。
支持服务端离线等待、时间同步、断线重连、循环运行。
"""

import os
import sys
import time
import json
import requests
import threading
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

# 导入 demo 中的核心类与函数
from demo import MoutaiClient, _post, _get, generate_h5_did, generate_h5_start_id, generate_bs_device_id

# ===================== 配置 =====================
SERVER_BASE_URL = "http://192.168.1.3:5000"  # 修改为实际地址
API_TOKEN = "your-secure-token-change-me"  # 必须与服务端 Config.API_TOKEN 一致
UPLOADER_ID = 1  # 上传者（用户）ID，抢购该用户下的所有账号

# 抢购循环次数（针对每个账号，持续尝试直到成功或达到最大次数）
MAX_RUSH_ATTEMPTS = 100000
RUSH_INTERVAL = 0.8  # 秒

# 服务端连接配置
MIN_RETRY_INTERVAL = 5   # 最小重试间隔（秒）
MAX_RETRY_INTERVAL = 20  # 最大重试间隔（秒）
SERVER_TIMEOUT = 5       # 请求超时时间（秒）

# 每日抢购配置
DAILY_RUSH_HOUR = 8      # 每天抢购时间 - 小时
DAILY_RUSH_MINUTE = 50   # 每天抢购时间 - 分钟


# ===================== 辅助函数 =====================

def wait_for_server() -> bool:
    """
    等待服务端上线，随机间隔5-20秒重试，直到连接成功
    返回: True-连接成功, False-用户中断
    """
    print(f"[服务端] 正在连接服务端: {SERVER_BASE_URL}")
    retry_count = 0
    
    while True:
        try:
            resp = requests.get(
                f"{SERVER_BASE_URL}/api/client/get_config",
                headers={'X-API-TOKEN': API_TOKEN},
                timeout=SERVER_TIMEOUT
            )
            if resp.status_code == 200:
                print(f"[服务端] ✅ 服务端已上线！")
                return True
            else:
                print(f"[服务端] ⚠️ 服务端响应异常: HTTP {resp.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"[服务端] ❌ 服务端未响应 (尝试 {retry_count + 1})")
        except requests.exceptions.Timeout:
            print(f"[服务端] ⏱️ 连接超时 (尝试 {retry_count + 1})")
        except Exception as e:
            print(f"[服务端] ⚠️ 连接异常: {e}")
        
        retry_count += 1
        # 随机等待5-20秒
        wait_time = random.randint(MIN_RETRY_INTERVAL, MAX_RETRY_INTERVAL)
        print(f"[服务端] ⏳ {wait_time} 秒后重试... (按 Ctrl+C 退出)")
        
        try:
            time.sleep(wait_time)
        except KeyboardInterrupt:
            print("\n[客户端] 用户中断退出")
            return False


def fetch_rush_time() -> Optional[Tuple[int, int]]:
    """
    从服务端获取抢购时间配置
    返回: (hour, minute) 元组，失败返回 None
    """
    url = f"{SERVER_BASE_URL}/api/client/get_config"
    headers = {'X-API-TOKEN': API_TOKEN}
    
    try:
        resp = requests.get(url, headers=headers, timeout=SERVER_TIMEOUT)
        if resp.status_code != 200:
            print(f"[配置] 获取失败: HTTP {resp.status_code}")
            return None
        
        data = resp.json()
        rush_hour = data.get('rush_hour')
        rush_minute = data.get('rush_minute')
        
        if rush_hour is not None and rush_minute is not None:
            print(f"[配置] ✅ 抢购时间: {rush_hour:02d}:{rush_minute:02d}")
            return (int(rush_hour), int(rush_minute))
        else:
            print(f"[配置] ⚠️ 服务端未返回抢购时间")
            return None
            
    except Exception as e:
        print(f"[配置] 获取异常: {e}")
        return None


def calculate_wait_seconds(target_hour: int, target_minute: int) -> int:
    """
    计算距离目标时间的等待秒数
    如果当前时间已过今天的目标时间，则计算到明天的时间
    """
    now = datetime.now()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    
    # 如果当前时间已超过今天的抢购时间，目标设为明天
    if now >= target:
        target += timedelta(days=1)
        print(f"[时间] 今天的抢购时间已过，将等待至明天 {target_hour:02d}:{target_minute:02d}")
    
    wait_seconds = int((target - now).total_seconds())
    return wait_seconds


def countdown_timer(wait_seconds: int, label: str = "抢购"):
    """
    显示倒计时
    """
    print(f"\n[倒计时] 距离{label}还有 {wait_seconds} 秒 ({wait_seconds // 3600}小时 {(wait_seconds % 3600) // 60}分 {wait_seconds % 60}秒)")
    
    while wait_seconds > 0:
        hours = wait_seconds // 3600
        minutes = (wait_seconds % 3600) // 60
        seconds = wait_seconds % 60
        
        if hours > 0:
            print(f"[倒计时] ⏰ {hours:02d}:{minutes:02d}:{seconds:02d}", end='\r')
        else:
            print(f"[倒计时] ⏰ {minutes:02d}:{seconds:02d}", end='\r')
        
        # 最后60秒每秒更新，否则每10秒更新
        if wait_seconds <= 60:
            time.sleep(1)
        else:
            time.sleep(10)
        
        wait_seconds -= 1
    
    print(f"\n[倒计时] 🚀 {label}开始！\n")


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
        h5_url = h5_result["h5_url"]
        print(f"[{phone}] 获取到支付链接: {h5_url[:80]}...")
    except Exception as e:
        report_result(phone, success=False, error=f"转链异常: {e}")
        return

    # 8. 上报最终成功结果
    report_result(phone, success=True, order_id=order_id, h5_url=h5_url)


def fetch_tasks() -> List[dict]:
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


def fetch_config() -> Tuple[str, str, Optional[Tuple[int, int]]]:
    """
    获取抢购商品配置和抢购时间
    返回: (item_code, act_id, (rush_hour, rush_minute))
    """
    url = f"{SERVER_BASE_URL}/api/client/get_config"
    headers = {'X-API-TOKEN': API_TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        item_code = data.get('item_code', '741')
        act_id = data.get('act_id', '76145')
        rush_hour = data.get('rush_hour')
        rush_minute = data.get('rush_minute')
        
        rush_time = None
        if rush_hour is not None and rush_minute is not None:
            rush_time = (int(rush_hour), int(rush_minute))
        
        return item_code, act_id, rush_time
    except Exception as e:
        print(f"获取配置失败: {e}，使用默认值")
        return '741', '76145', None


def execute_rush_cycle():
    """
    执行一次完整的抢购周期
    返回: True-执行成功, False-需要重新连接服务端
    """
    print("\n" + "=" * 60)
    print("=== 开始新一轮抢购周期 ===")
    print("=" * 60)
    
    # 1. 获取商品配置和抢购时间
    item_code, act_id, rush_time = fetch_config()
    print(f"[配置] 目标商品: {item_code}, 活动ID: {act_id}")
    
    # 2. 如果有抢购时间，进行倒计时等待
    if rush_time:
        rush_hour, rush_minute = rush_time
        wait_seconds = calculate_wait_seconds(rush_hour, rush_minute)
        
        if wait_seconds > 0:
            print(f"\n[计划] 将在 {rush_hour:02d}:{rush_minute:02d} 开始抢购")
            countdown_timer(wait_seconds, "抢购")
        else:
            print(f"\n[计划] 立即开始抢购！")
    else:
        print(f"\n[警告] 未获取到抢购时间，立即开始抢购")
    
    # 3. 拉取任务
    tasks = fetch_tasks()
    if not tasks:
        print("没有需要执行的任务")
        return True  # 继续下一轮

    print(f"共获取到 {len(tasks)} 个账号，开始并发抢购...\n")

    # 4. 并发执行（每个账号一个线程）
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

    print("\n✅ 所有账号抢购流程结束")
    return True


def main():
    print("=" * 60)
    print("=== i茅台分布式抢购客户端启动 ===")
    print("=" * 60)
    
    # 主循环：持续运行，每天执行一次抢购
    while True:
        try:
            # 1. 等待服务端上线（随机5-20秒重试）
            if not wait_for_server():
                print("[客户端] 用户中断，退出")
                return
            
            # 2. 执行抢购周期
            execute_rush_cycle()
            
            # 3. 抢购完成后，等待到第二天8:50
            print("\n" + "=" * 60)
            print("=== 本轮抢购完成，等待下一轮 ===")
            print("=" * 60)
            
            # 计算到明天8:50的等待时间
            tomorrow_rush = calculate_wait_seconds(DAILY_RUSH_HOUR, DAILY_RUSH_MINUTE)
            
            if tomorrow_rush > 0:
                print(f"\n[计划] 将在明天 {DAILY_RUSH_HOUR:02d}:{DAILY_RUSH_MINUTE:02d} 继续抢购")
                print(f"[提示] 期间会随机每5-20秒检查服务端状态\n")
                
                # 在等待期间，随机每5-20秒检查一次服务端
                elapsed = 0
                while elapsed < tomorrow_rush:
                    # 随机等待5-20秒
                    check_interval = random.randint(MIN_RETRY_INTERVAL, MAX_RETRY_INTERVAL)
                    
                    # 确保不会超过总等待时间
                    if elapsed + check_interval > tomorrow_rush:
                        check_interval = tomorrow_rush - elapsed
                    
                    remaining = tomorrow_rush - elapsed
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    seconds = remaining % 60
                    
                    print(f"[等待] 下次检查: {check_interval}秒 | 距离抢购: {hours:02d}:{minutes:02d}:{seconds:02d}", end='\r')
                    
                    try:
                        time.sleep(check_interval)
                    except KeyboardInterrupt:
                        print("\n[客户端] 用户中断，退出")
                        return
                    
                    elapsed += check_interval
                    
                    # 尝试连接服务端（不阻塞，仅检查）
                    try:
                        resp = requests.get(
                            f"{SERVER_BASE_URL}/api/client/get_config",
                            headers={'X-API-TOKEN': API_TOKEN},
                            timeout=2
                        )
                        if resp.status_code == 200:
                            print(f"\n[检查] ✅ 服务端在线")
                        else:
                            print(f"\n[检查] ⚠️ 服务端异常: HTTP {resp.status_code}")
                    except:
                        print(f"\n[检查] ❌ 服务端离线")
                
                print(f"\n[提示] 已到达预定时间，开始新一轮抢购\n")
            else:
                # 如果时间计算异常，等待一段时间后继续
                print("\n[警告] 时间计算异常，1小时后重试")
                time.sleep(3600)
                
        except KeyboardInterrupt:
            print("\n\n[客户端] 用户中断，退出")
            return
        except Exception as e:
            print(f"\n[错误] 发生异常: {e}")
            import traceback
            traceback.print_exc()
            print("\n[提示] 30秒后重试...\n")
            time.sleep(30)


if __name__ == "__main__":
    main()