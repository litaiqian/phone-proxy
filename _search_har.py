#!/usr/bin/env python3
"""搜索所有HAR文件中的 haotian/mshield/coin/sp_exist/event 请求"""
import json, os
from urllib.parse import urlparse

dirs = [
    r'C:\Users\Administrator\Desktop\111',
    r'C:\Users\Administrator\Desktop\111\新建文件夹',
    r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹',
]

all_har = []
for d in dirs:
    for root, dirs2, files in os.walk(d):
        for f in files:
            if f.endswith('.har'):
                fp = os.path.join(root, f)
                sz = os.path.getsize(fp)
                if sz > 200 * 1024 * 1024:
                    continue
                all_har.append(fp)

print(f'Total HAR files: {len(all_har)}')
results = {'haotian': [], 'mshield': [], 'coin': [], 'sp_exist': [], 'event_track': [], 'all_hosts': {}}

for hp in all_har:
    fname = os.path.basename(hp)
    try:
        with open(hp, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except:
        continue
    entries = data.get('log', {}).get('entries', [])
    for i, e in enumerate(entries):
        url = e.get('request', {}).get('url', '')
        host = urlparse(url).hostname or ''
        results['all_hosts'][host] = results['all_hosts'].get(host, 0) + 1
        for kw in ['haotian', 'mshield']:
            if kw in url.lower():
                results[kw].append({
                    'file': fname, 'idx': i, 'url': url,
                    'method': e['request']['method'],
                    'headers': {h['name']: h['value'][:200] for h in e['request'].get('headers', [])},
                    'status': e['response']['status'],
                    'resp': e['response'].get('content', {}).get('text', '')[:500],
                })
        if 'coin' in url.lower() or 'xmy' in url.lower():
            results['coin'].append({
                'file': fname, 'idx': i, 'url': url,
                'method': e['request']['method'],
                'headers': {h['name']: h['value'][:200] for h in e['request'].get('headers', [])},
                'status': e['response']['status'],
                'resp': e['response'].get('content', {}).get('text', '')[:500],
            })
        if 'sp/exist' in url or 'sdk/v1/sp' in url:
            results['sp_exist'].append({
                'file': fname, 'idx': i, 'url': url,
                'method': e['request']['method'],
                'headers': {h['name']: h['value'][:200] for h in e['request'].get('headers', [])},
                'postData': e['request'].get('postData', {}).get('text', '')[:500],
                'status': e['response']['status'],
                'resp': e['response'].get('content', {}).get('text', '')[:500],
            })
        if 'event/track' in url or 'event-tracking' in url:
            results['event_track'].append({
                'file': fname, 'idx': i, 'url': url,
                'method': e['request']['method'],
                'headers': {h['name']: h['value'][:200] for h in e['request'].get('headers', [])},
                'postData': e['request'].get('postData', {}).get('text', '')[:1000],
                'status': e['response']['status'],
                'resp': e['response'].get('content', {}).get('text', '')[:500],
            })

print(f'\n=== RESULTS ===')
print(f'haotian: {len(results["haotian"])}')
print(f'mshield: {len(results["mshield"])}')
print(f'coin: {len(results["coin"])}')
print(f'sp_exist: {len(results["sp_exist"])}')
print(f'event_track: {len(results["event_track"])}')

if results['haotian']:
    print(f'\n=== HAOTIAN ===')
    for r in results['haotian']:
        print(f'\n  [{r["file"][:50]}] #{r["idx"]} {r["method"]} {r["status"]}')
        print(f'  URL: {r["url"]}')
        for k, v in r['headers'].items():
            print(f'    {k}: {v[:150]}')
        if r.get('resp'):
            print(f'  RESP: {r["resp"][:400]}')

if results['mshield']:
    print(f'\n=== MSHIELD ===')
    for r in results['mshield']:
        print(f'\n  [{r["file"][:50]}] #{r["idx"]} {r["method"]} {r["status"]}')
        print(f'  URL: {r["url"]}')
        for k, v in r['headers'].items():
            print(f'    {k}: {v[:150]}')
        if r.get('resp'):
            print(f'  RESP: {r["resp"][:400]}')

if results['coin']:
    print(f'\n=== COIN ===')
    for r in results['coin'][:10]:
        print(f'\n  [{r["file"][:50]}] #{r["idx"]} {r["method"]} {r["status"]}')
        print(f'  URL: {r["url"]}')
        for k, v in r['headers'].items():
            print(f'    {k}: {v[:150]}')
        if r.get('resp'):
            try:
                rj = json.loads(r['resp'])
                code = rj.get('code')
                d = rj.get('data', {})
                print(f'  RESP: code={code} xmyNum={d.get("xmyNum","?")} energy={d.get("energy","?")}')
            except:
                print(f'  RESP: {r["resp"][:300]}')

if results['sp_exist']:
    print(f'\n=== SP/EXIST ===')
    for r in results['sp_exist']:
        print(f'\n  [{r["file"][:50]}] #{r["idx"]} {r["method"]} {r["status"]}')
        print(f'  URL: {r["url"]}')
        for k, v in r['headers'].items():
            print(f'    {k}: {v[:150]}')
        if r.get('postData'):
            print(f'  BODY: {r["postData"][:400]}')
        if r.get('resp'):
            print(f'  RESP: {r["resp"][:300]}')

if results['event_track']:
    print(f'\n=== EVENT TRACK ===')
    for r in results['event_track'][:5]:
        print(f'\n  [{r["file"][:50]}] #{r["idx"]} {r["method"]} {r["status"]}')
        print(f'  URL: {r["url"]}')
        for k, v in r['headers'].items():
            print(f'    {k}: {v[:150]}')
        if r.get('postData'):
            try:
                pd = json.loads(r['postData'])
                print(f'  BODY keys: {list(pd.keys()) if isinstance(pd, dict) else "raw"}')
                print(f'  BODY: {r["postData"][:500]}')
            except:
                print(f'  BODY: {r["postData"][:500]}')

print(f'\n=== KEY HOSTS ===')
for h, c in sorted(results['all_hosts'].items()):
    if any(kw in h for kw in ['moutai', 'baidu', 'haotian', 'mshield', 'umeng', 'bangcle']):
        print(f'  {h}: {c} requests')

# Write summary JSON
out_path = r'D:\采购管理\_har_summary.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({k: v for k, v in results.items() if k != 'all_hosts'},
              f, ensure_ascii=False, indent=2)
print(f'\nSummary written to: {out_path}')
