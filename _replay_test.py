#!/usr/bin/env python3
"""
重放 HAR 中抓到的 haotian/mshield 原始请求
关键修正：HAR postData encoding=base64, text 需要先 decode 再发送
策略：逐条用 httpx + curl_cffi 各试一次
"""
import json, time, sys, base64
import httpx
import urllib3
urllib3.disable_warnings()

REPLAY_FILE = r"D:\采购管理\_haotian_mshield_replay.json"

with open(REPLAY_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

def replay_request(r, label=""):
    """重放单条请求，返回结果"""
    url = r['url']
    method = r['method']
    body = r['body']
    headers = {k: v for k, v in r['headers'].items()
               if k.lower() not in ('host', 'connection', 'content-length')}

    # ===== 关键修正：HAR postData encoding=base64，需要先 decode =====
    raw_body = body
    decoded_body = b''
    if body:
        try:
            decoded_body = base64.b64decode(body)
            print(f"  Body: HAR base64({len(body)}b) → decode({len(decoded_body)}b)")
        except:
            decoded_body = body.encode()  # fallback
            print(f"  Body: RAW text({len(body)}b), not base64")

    # 检查 decoded body 是不是 gzip
    if decoded_body[:2] == b'\x1f\x8b':
        print(f"  Body: IS GZIP compressed!")

    print(f"  Body hex[:40]: {decoded_body[:20].hex()}")
    expected_status = r['status']
    expected_body = r.get('resp_body', '')[:200]
    har_time = r.get('startedDateTime', '')[:19]

    print(f"\n{'─'*60}")
    print(f"[{label}] {method} {r['har_file'][:35]} #{r['idx']}")
    print(f"  HAR时间: {har_time} | 期望: {expected_status}")
    url_short = url[:150]
    print(f"  URL: {url_short}")

    results = {}

    # ---- 方式1: httpx (标准Python) ----
    try:
        with httpx.Client(timeout=10, verify=False, follow_redirects=False) as client:
            if method == 'POST':
                # body 在 HAR 里已经是 base64 字符串，Content-Type 是 x-www-form-urlencoded
                # HAR的postData.text就是发送的body原文
                resp = client.post(url, headers=headers, content=decoded_body)
            else:
                resp = client.get(url, headers=headers)

            results['httpx'] = {
                'status': resp.status_code,
                'body': resp.text[:300],
                'headers': {k: v for k, v in resp.headers.items()},
            }
            match = "✓" if resp.status_code == expected_status else "✗"
            print(f"  [httpx] {resp.status_code} {match} | resp: {resp.text[:150]}")
    except Exception as e:
        results['httpx'] = {'error': str(e)[:200]}
        print(f"  [httpx] ERROR: {e}")

    # ---- 方式2: 尝试 curl_cffi (如果有) ----
    try:
        from curl_cffi import requests as curl_requests
        if method == 'POST':
            resp2 = curl_requests.post(url, headers=headers, data=decoded_body,
                                       timeout=10, verify=False, impersonate="chrome110")
        else:
            resp2 = curl_requests.get(url, headers=headers,
                                      timeout=10, verify=False, impersonate="chrome110")
        results['curl_cffi'] = {
            'status': resp2.status_code,
            'body': resp2.text[:300],
        }
        match = "✓" if resp2.status_code == expected_status else "✗"
        print(f"  [curl_cffi] {resp2.status_code} {match} | resp: {resp2.text[:150]}")
    except ImportError:
        results['curl_cffi'] = {'error': 'curl_cffi not installed'}
        print(f"  [curl_cffi] 未安装，跳过")
    except Exception as e:
        results['curl_cffi'] = {'error': str(e)[:200]}
        print(f"  [curl_cffi] ERROR: {e}")

    return results

# ============ 先试 mshield ============
print("=" * 70)
print("MSHIELD 重放测试 (先试最简单的 p/1/r)")
print("=" * 70)

# 选2条 mshield: 一条 p/1/r，一条 s/5/aio
mshield_samples = []
for r in data['mshield']:
    if '/p/1/r/' in r['url']:
        mshield_samples.append(('mshield:p/1/r', r))
        break
for r in data['mshield']:
    if '/s/5/aio/' in r['url']:
        mshield_samples.append(('mshield:s/5/aio', r))
        break

for label, req in mshield_samples:
    replay_request(req, label)

# ============ 再试 haotian ============
print(f"\n{'='*70}")
print("HAOTIAN 重放测试 (选3条: p/5/aio, p/1/r, r/5/c)")
print("=" * 70)

haotian_samples = []
for path in ['/p/5/aio/', '/p/1/r/', '/r/5/c/']:
    for r in data['haotian']:
        if path in r['url']:
            label = f"haotian:{path.rsplit('/', 2)[0].rsplit('/', 1)[0]}"
            haotian_samples.append((label, r))
            break

for label, req in haotian_samples:
    replay_request(req, label)

print(f"\n{'='*70}")
print("重放完成")
print("=" * 70)
