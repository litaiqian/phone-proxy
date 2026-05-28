#!/usr/bin/env python3
import json
d = json.load(open(r'D:\采购管理\_har_summary.json', 'r', encoding='utf-8'))

print('=== COIN ===')
for c in d['coin'][:10]:
    print(f"\n[{c['file'][:50]}] #{c['idx']} {c['method']} {c['status']}")
    print(f"  URL: {c['url'][:200]}")
    print(f"  Headers:")
    for k, v in c['headers'].items():
        if v and len(str(v)) > 3:
            print(f"    {k}: {str(v)[:150]}")
    if c.get('resp'):
        print(f"  RESP: {c['resp'][:400]}")

print('\n=== MSHIELD ===')
for c in d['mshield'][:10]:
    print(f"\n[{c['file'][:50]}] #{c['idx']} {c['method']} {c['status']}")
    print(f"  URL: {c['url'][:200]}")
    for k, v in c['headers'].items():
        print(f"    {k}: {str(v)[:150]}")
    if c.get('resp'):
        print(f"  RESP: {c['resp'][:400]}")

print('\n=== SP/EXIST ===')
for c in d['sp_exist'][:5]:
    print(f"\n[{c['file'][:50]}] #{c['idx']} {c['method']} {c['status']}")
    print(f"  URL: {c['url'][:200]}")
    for k, v in c['headers'].items():
        print(f"    {k}: {str(v)[:150]}")
    if c.get('postData'):
        print(f"  BODY: {c['postData'][:300]}")
    if c.get('resp'):
        print(f"  RESP: {c['resp'][:300]}")
