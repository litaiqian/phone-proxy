#!/usr/bin/env python3
"""测试 coin 接口是否正常返回 — 使用真机账号token + 设备指纹"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from demo import MoutaiClient, _get, BASE_URL, APP_VERSION

ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'iplala_accounts.json')

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"❌ 账号文件不存在: {ACCOUNTS_FILE}")
        return []
    with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def test_coin_for_account(acc):
    """对单个账号测试 coin 接口"""
    phone = acc.get('mobile', '')
    print(f"\n{'='*60}")
    print(f"📱 测试账号: {phone}")
    print(f"   Token过期: {acc.get('token','')[:50]}...")

    # 创建客户端并注入设备指纹
    client = MoutaiClient()
    client.token = acc.get('token', '')
    client.cookie = acc.get('cookie', '')
    client.user_id = str(acc.get('userid', ''))
    client.phone = phone

    if acc.get('device-id'):
        client.raw_device_id = acc['device-id']
    if acc.get('mt-device-id'):
        client.mt_device_id = acc['mt-device-id']
    if acc.get('mt-r'):
        client.mt_r = acc['mt-r']
    if acc.get('mt-sn'):
        client.mt_sn = acc['mt-sn']
    if acc.get('webview-ua'):
        client.webview_ua = acc['webview-ua']
    if acc.get('user-agent'):
        client.user_agent = acc['user-agent']

    print(f"   MT-Device-ID: {client.mt_device_id[:40]}...")

    # 测试 coin 接口
    coin_url = f"{BASE_URL}/xhr/front/mall/index/xmy/user/coin"
    print(f"\n   🔍 请求: GET {coin_url}?scene=0")

    try:
        headers = client._app_headers()
        resp = _get(coin_url, headers=headers, params={"scene": 0},
                    proxy=None, timeout=10)

        print(f"   HTTP状态: {resp.status_code}")
        data = resp.json()
        code = data.get('code')
        print(f"   业务码: {code}")

        if code == 2000:
            coin_data = data.get('data', {})
            xmy = coin_data.get('xmyNum', '?')
            energy = coin_data.get('energy', '?')
            print(f"   ✅ 小茅运(xmyNum): {xmy}")
            print(f"   ✅ 耐力值(energy): {energy}")
            print(f"   完整响应: {json.dumps(data, ensure_ascii=False)}")
            return True
        elif code == 401 or code == 2001:
            print(f"   ⚠️ Token已过期或未登录: {data.get('message', data.get('msg', ''))}")
            return False
        else:
            print(f"   ❌ 异常返回: {data.get('message', data.get('msg', ''))}")
            print(f"   完整响应: {json.dumps(data, ensure_ascii=False)[:500]}")
            return False

    except Exception as e:
        print(f"   ❌ 请求异常: {e}")
        return False

def main():
    # 同时输出到文件（解决PSReadLine终端bug）
    result_file = r"C:\coin_test_result.json"
    results = []

    accounts = load_accounts()
    if not accounts:
        return

    log_lines = []
    def log(msg):
        log_lines.append(msg)
        print(msg)

    log("=" * 60)
    log("💰 i茅台 Coin 接口真机测试")
    log(f"   测试账号数: {len(accounts)}")
    log(f"   BASE_URL: {BASE_URL}")
    log(f"   APP_VERSION: {APP_VERSION}")
    log("=" * 60)

    success = 0
    expired = 0
    for acc in accounts:
        if acc.get('token') and acc.get('cookie'):
            ok = test_coin_for_account(acc)
            if ok:
                success += 1
            else:
                expired += 1
        else:
            log(f"\n   ⚠️ 跳过 {acc.get('mobile','?')}: 无token/cookie")

    summary = f"\n{'='*60}\n📊 汇总: 成功={success}, Token过期={expired}\n{'='*60}"
    log(summary)

    # 写入文件
    try:
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(log_lines))
        print(f"\n结果已写入: {result_file}")
    except Exception as e:
        print(f"\n写入文件失败: {e}")
        # 尝试当前目录
        try:
            alt = r"coin_test_result.txt"
            with open(alt, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_lines))
            print(f"结果已写入(alt): {os.path.abspath(alt)}")
        except Exception as e2:
            print(f"备选写入也失败: {e2}")

if __name__ == '__main__':
    main()
