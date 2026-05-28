#!/usr/bin/env python3
"""从 HAR 文件中提取 haotian/mshield 的完整请求（含请求体），用于重放"""
import json, os, sys
from urllib.parse import urlparse

# 目标 HAR 文件
har_paths = [
    r"C:\Users\Administrator\Desktop\111\新建文件夹\2026-1539.har",
    r"C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\android.bugly.qq.com_2026_05_25_14_39_51.har",
    r"C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\android.bugly.qq.com_2026_05_25_14_44_01.har",
    r"C:\Users\Administrator\Desktop\111\新建文件夹\从头0-1到尾.har",
]

results = {'haotian': [], 'mshield': []}

for har_path in har_paths:
    if not os.path.exists(har_path):
        print(f"SKIP: {har_path}")
        continue
    fname = os.path.basename(har_path)
    sz_mb = os.path.getsize(har_path) / (1024*1024)
    if sz_mb > 200:
        print(f"SKIP: {fname} ({sz_mb:.0f}MB too large)")
        continue
    print(f"Parsing: {fname} ({sz_mb:.1f}MB)...")
    with open(har_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    entries = data['log']['entries']
    for i, e in enumerate(entries):
        url = e['request']['url']
        method = e['request']['method']

        if 'haotian.baidu.com' in url:
            headers = {h['name']: h['value'] for h in e['request'].get('headers', [])}
            pd = e['request'].get('postData', {})
            body_text = pd.get('text', '') if pd else ''
            # 如果有 params，也提取
            params = []
            for p in pd.get('params', []) if pd else []:
                params.append({'name': p.get('name',''), 'value': p.get('value','')})

            results['haotian'].append({
                'har_file': fname,
                'idx': i,
                'url': url,
                'method': method,
                'headers': headers,
                'body': body_text,
                'params': params,
                'status': e['response']['status'],
                'resp_headers': {h['name']: h['value'] for h in e['response'].get('headers', [])},
                'resp_body': e['response'].get('content', {}).get('text', '')[:500],
                'startedDateTime': e.get('startedDateTime', ''),
            })

        if 'mshield.baidu.com' in url:
            headers = {h['name']: h['value'] for h in e['request'].get('headers', [])}
            pd = e['request'].get('postData', {})
            body_text = pd.get('text', '') if pd else ''
            params = []
            for p in pd.get('params', []) if pd else []:
                params.append({'name': p.get('name',''), 'value': p.get('value','')})

            results['mshield'].append({
                'har_file': fname,
                'idx': i,
                'url': url,
                'method': method,
                'headers': headers,
                'body': body_text,
                'params': params,
                'status': e['response']['status'],
                'resp_headers': {h['name']: h['value'] for h in e['response'].get('headers', [])},
                'resp_body': e['response'].get('content', {}).get('text', '')[:500],
                'startedDateTime': e.get('startedDateTime', ''),
            })

# 打印结果
print(f"\n{'='*80}")
print(f"haotian: {len(results['haotian'])} 条完整请求")
print(f"mshield: {len(results['mshield'])} 条完整请求")

# ---- 打印 mshield 前几条的详细信息 ----
if results['mshield']:
    print(f"\n{'='*80}")
    print("MSHIELD 完整请求详情 (前5条):")
    print(f"{'='*80}")
    for r in results['mshield'][:5]:
        print(f"\n[{r['har_file'][:40]}] #{r['idx']} {r['method']} {r['status']}")
        print(f"  Time: {r['startedDateTime']}")
        print(f"  URL: {r['url'][:200]}")
        print(f"  Headers:")
        for k, v in r['headers'].items():
            print(f"    {k}: {v[:200]}")
        if r['body']:
            print(f"  BODY (raw, {len(r['body'])} bytes):")
            print(f"    {r['body'][:500]}")
        if r['resp_body']:
            print(f"  RESPONSE:")
            print(f"    {r['resp_body'][:500]}")

# ---- 打印 haotian 前几条的详细信息 ----
if results['haotian']:
    print(f"\n{'='*80}")
    print("HAOTIAN 完整请求详情 (前5条):")
    print(f"{'='*80}")
    for r in results['haotian'][:5]:
        print(f"\n[{r['har_file'][:40]}] #{r['idx']} {r['method']} {r['status']}")
        print(f"  Time: {r['startedDateTime']}")
        print(f"  URL: {r['url'][:200]}")
        print(f"  Headers:")
        for k, v in r['headers'].items():
            if k not in ('content-length', 'connection', 'host', 'accept-encoding', 'accept-language'):
                print(f"    {k}: {v[:200]}")
        if r['body']:
            print(f"  BODY (raw, {len(r['body'])} bytes):")
            print(f"    {r['body'][:500]}")
        if r['resp_body']:
            print(f"  RESPONSE:")
            print(f"    {r['resp_body'][:500]}")

# 保存到 JSON 用于后续重放脚本
out_path = r"D:\采购管理\_haotian_mshield_replay.json"
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n完整数据已保存到: {out_path}")
print(f"  haotian 条目: {len(results['haotian'])}")
print(f"  mshield 条目: {len(results['mshield'])}")
