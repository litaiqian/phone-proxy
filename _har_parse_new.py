#!/usr/bin/env python3
"""批量解析HAR文件，提取关键信息并分类"""

import os, json, glob
from urllib.parse import urlparse

har_dir = r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹'
files = glob.glob(os.path.join(har_dir, '*.har'))

print(f'共找到 {len(files)} 个HAR文件\n')
print('='*100)

all_hosts = {}
all_endpoints = {}

for fpath in sorted(files):
    fname = os.path.basename(fpath)
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        entries = data.get('log', {}).get('entries', [])
        
        urls = set()
        methods = {}
        hosts_set = set()
        response_codes = {}
        
        for e in entries:
            req = e.get('request', {})
            url = req.get('url', '')
            method = req.get('method', '')
            parsed = urlparse(url)
            host = parsed.netloc
            path = parsed.path[:120]
            resp = e.get('response', {})
            code = resp.get('status', 0)
            
            urls.add((method, host, path))
            methods[method] = methods.get(method, 0) + 1
            hosts_set.add(host)
            response_codes[code] = response_codes.get(code, 0) + 1
            
            if host not in all_hosts:
                all_hosts[host] = 0
            all_hosts[host] += 1
            
            # Extract key headers
            headers = req.get('headers', [])
            header_dict = {}
            for h in headers:
                header_dict[h.get('name', '')] = h.get('value', '')
        
        print(f'\n[{fname}] ({len(entries)} requests)')
        
        for host in sorted(hosts_set):
            print(f'  Domain: {host}')
        for method, count in sorted(methods.items()):
            print(f'  Method: {method} x{count}')
        print(f'  Response codes: {response_codes}')
        
        for method, host, path in sorted(urls):
            print(f'    {method} https://{host}{path}')
            
            key = f'{method} {host}{path}'
            if key not in all_endpoints:
                all_endpoints[key] = 0
            all_endpoints[key] += 1
            
    except Exception as ex:
        print(f'\n[{fname}] - FAILED: {ex}')

print('\n' + '='*100)
print('\n=== SUMMARY ===\n')

# Categorize by domain type
categories = {}
for host, count in all_hosts.items():
    if 'moutai519.com.cn' in host:
        cat = '茅台业务API'
    elif 'bugly.qq.com' in host:
        cat = 'Bugly崩溃上报'
    elif 'google' in host or '142.250' in host:
        cat = 'Google服务'
    else:
        cat = f'其他 ({host})'
    if cat not in categories:
        categories[cat] = {'hosts': set(), 'count': 0}
    categories[cat]['hosts'].add(host)
    categories[cat]['count'] += count

for cat, info in sorted(categories.items()):
    print(f'\n### {cat} ({info["count"]} requests)')
    for h in sorted(info['hosts']):
        print(f'  - {h}')

print(f'\nTotal unique endpoints: {len(all_endpoints)}')
print(f'Total requests across all files: {sum(all_hosts.values())}')

# ===== DEEP DIVE: Business API analysis =====
print('\n' + '='*100)
print('=== KEY BUSINESS API ANALYSIS ===')
print('='*100)

# Key files for deep analysis
key_files = [
    r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\app.moutai519.com.cn_2026_05_25_14_46_49.har',
    r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\app.moutai519.com.cn_2026_05_25_14_48_12.har',
    r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\dc.moutai519.com.cn_2026_05_25_14_41_54.har',
    r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\fk1.moutai519.com.cn_2026_05_25_14_50_28.har',
]

for fpath in key_files:
    fname = os.path.basename(fpath)
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        entries = data.get('log', {}).get('entries', [])
        
        print(f'\n[{fname}] ({len(entries)} requests)')
        
        xhr_calls = []
        for e in entries:
            req = e.get('request', {})
            url = req.get('url', '')
            method = req.get('method', '')
            parsed = urlparse(url)
            host = parsed.netloc
            path = parsed.path
            qs = parsed.query
            resp = e.get('response', {})
            code = resp.get('status', 0)
            
            # Get content from response
            content = resp.get('content', {})
            text = content.get('text', '')[:300] if content else ''
            
            headers = {h['name']: h['value'][:80] for h in req.get('headers', []) if h.get('name')}
            has_mt_token = 'mt-token' in headers
            has_mt_device_id = 'mt-device-id' in headers
            has_mt_r = 'mt-r' in headers
            has_mt_sn = 'mt-sn' in headers
            
            if 'moutai519.com.cn' in host and ('/xhr/' in path or '/upload/' in path):
                xhr_calls.append({
                    'method': method, 'host': host, 'path': path, 'qs': qs,
                    'code': code, 'has_token': has_mt_token,
                    'has_device_id': has_mt_device_id,
                    'has_mt_r': has_mt_r, 'has_mt_sn': has_mt_sn,
                    'resp_preview': text[:120] if text else ''
                })
        
        for x in xhr_calls:
            flags = []
            if x['has_token']: flags.append('TOKEN')
            if x['has_device_id']: flags.append('DEVICE-ID')
            if x['has_mt_r']: flags.append('MT-R')
            if x['has_mt_sn']: flags.append('MT-SN')
            flag_str = ','.join(flags) if flags else 'NO-AUTH'
            qs_str = f'?{x["qs"]}' if x['qs'] else ''
            print(f'  [{x["code"]}] {x["method"]:4} {x["host"]}{x["path"]}{qs_str}')
            print(f'       Auth: {flag_str}')
            if x['resp_preview']:
                print(f'       Resp: {x["resp_preview"]}')
                
    except Exception as ex:
        print(f'  FAILED: {ex}')
