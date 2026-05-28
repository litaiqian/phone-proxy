#!/usr/bin/env python3
"""从所有HAR文件中提取 haotian/mshield/bangcle/coin 真实请求详情"""
import json, os, sys

HAR_DIR = r"C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹"
OUT_FILE = r"D:\采购管理\security_extract.json"

security_keywords = [
    'haotian', 'mshield', 'bangcle', 'bbprbdata',
    'sp/exist', 'sp_exist', 'sdk/v1/sp',
]
coin_keywords = ['xmy/user/coin', 'user/coin']
event_keywords = ['dc.moutai', 'event/track', 'event-tracking']

all_results = {
    'haotian_mshield': [],
    'bangcle': [],
    'sp_exist': [],
    'coin': [],
    'event_track': [],
    'all_hosts': {},
}

har_files = [f for f in os.listdir(HAR_DIR) if f.endswith('.har')]
print(f"找到 {len(har_files)} 个HAR文件")

for har_name in sorted(har_files):
    har_path = os.path.join(HAR_DIR, har_name)
    file_size_mb = os.path.getsize(har_path) / (1024*1024)
    
    # 跳过超大的bugly文件
    if file_size_mb > 100:
        print(f"  跳过 {har_name} ({file_size_mb:.1f}MB - 太大)")
        continue
    
    print(f"  解析 {har_name} ({file_size_mb:.1f}MB)...")
    try:
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)
    except Exception as e:
        print(f"    错误: {e}")
        continue
    
    entries = har['log']['entries']
    
    for i, entry in enumerate(entries):
        req = entry['request']
        url = req['url']
        method = req['method']
        
        # 收集所有host
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        if host and host not in all_results['all_hosts']:
            all_results['all_hosts'][host] = url
        
        # ---- haotian / mshield ----
        if any(k in url.lower() for k in ['haotian', 'mshield']):
            detail = {
                'har_file': har_name,
                'index': i,
                'method': method,
                'url': url,
                'headers': {h['name']: h['value'] for h in req['headers']},
                'postData': req.get('postData', {}).get('text', ''),
                'queryString': req.get('queryString', []),
                'status': entry['response']['status'],
                'resp_headers': {h['name']: h['value'] for h in entry['response'].get('headers', [])},
                'resp_body': entry['response'].get('content', {}).get('text', '')[:2000],
            }
            all_results['haotian_mshield'].append(detail)
            print(f"    ✓ haotian/mshield: {method} {url[:150]}")
        
        # ---- bangcle ----
        if any(k in url.lower() for k in ['bangcle', 'bbprbdata']):
            detail = {
                'har_file': har_name,
                'index': i,
                'method': method,
                'url': url,
                'headers': {h['name']: h['value'] for h in req['headers']},
                'postData': req.get('postData', {}).get('text', ''),
                'status': entry['response']['status'],
                'resp_body': entry['response'].get('content', {}).get('text', '')[:2000],
            }
            all_results['bangcle'].append(detail)
            print(f"    ✓ bangcle: {method} {url[:150]}")
        
        # ---- sp/exist ----
        if 'sp/exist' in url or 'sdk/v1/sp' in url:
            detail = {
                'har_file': har_name,
                'index': i,
                'method': method,
                'url': url,
                'headers': {h['name']: h['value'] for h in req['headers']},
                'queryString': req.get('queryString', []),
                'status': entry['response']['status'],
                'resp_body': entry['response'].get('content', {}).get('text', '')[:2000],
            }
            all_results['sp_exist'].append(detail)
            print(f"    ✓ sp/exist: {method} {url[:150]}")
        
        # ---- coin ----
        if any(k in url.lower() for k in ['user/coin', 'xmy/user/coin']):
            detail = {
                'har_file': har_name,
                'index': i,
                'method': method,
                'url': url,
                'headers': {h['name']: h['value'] for h in req['headers']},
                'queryString': req.get('queryString', []),
                'status': entry['response']['status'],
                'resp_body': entry['response'].get('content', {}).get('text', '')[:3000],
            }
            all_results['coin'].append(detail)
            print(f"    ✓ coin: {method} {url[:150]}")
        
        # ---- dc event track ----
        if 'dc.moutai' in url.lower():
            detail = {
                'har_file': har_name,
                'index': i,
                'method': method,
                'url': url,
                'headers': {h['name']: h['value'] for h in req['headers']},
                'postData': req.get('postData', {}).get('text', ''),
                'status': entry['response']['status'],
                'resp_body': entry['response'].get('content', {}).get('text', '')[:2000],
            }
            all_results['event_track'].append(detail)
            print(f"    ✓ event_track: {method} {url[:150]}")

# 输出汇总
print()
print("=" * 80)
print("提取结果汇总:")
print(f"  haotian/mshield: {len(all_results['haotian_mshield'])} 条")
print(f"  bangcle:         {len(all_results['bangcle'])} 条")
print(f"  sp/exist:        {len(all_results['sp_exist'])} 条")
print(f"  coin:            {len(all_results['coin'])} 条")
print(f"  event_track:     {len(all_results['event_track'])} 条")
print(f"  唯一host:        {len(all_results['all_hosts'])} 个")

# 显示所有host
print()
print("所有请求HOST列表:")
for host in sorted(all_results['all_hosts'].keys()):
    print(f"  {host}")

# 写文件
try:
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已写入: {OUT_FILE}")
except Exception as e:
    print(f"\n写入文件失败: {e}")

# 重点: 打印 haotian/mshield 的详细信息
if all_results['haotian_mshield']:
    print("\n" + "=" * 80)
    print("haotian/mshield 真实请求详情:")
    print("=" * 80)
    for d in all_results['haotian_mshield']:
        print(f"\n  URL: {d['url']}")
        print(f"  Method: {d['method']}")
        print(f"  Status: {d['status']}")
        print(f"  Headers:")
        for k, v in d['headers'].items():
            print(f"    {k}: {v[:200]}")
        if d.get('postData'):
            print(f"  Body: {d['postData'][:500]}")
        if d.get('resp_body'):
            print(f"  Response: {d['resp_body'][:500]}")

# 重点: 打印 coin 的详细信息
if all_results['coin']:
    print("\n" + "=" * 80)
    print("coin 接口真实请求详情:")
    print("=" * 80)
    for d in all_results['coin']:
        print(f"\n  URL: {d['url']}")
        print(f"  Method: {d['method']}")
        print(f"  Status: {d['status']}")
        print(f"  Headers:")
        for k, v in d['headers'].items():
            print(f"    {k}: {v[:200]}")
        if d.get('resp_body'):
            print(f"  Response: {d['resp_body'][:1000]}")
else:
    print("\n⚠️ 未找到 coin 接口请求! 列出所有 coin 相关URL:")
    # 在所有HAR中再次搜索coin相关
    for har_name in sorted(har_files):
        har_path = os.path.join(HAR_DIR, har_name)
        if os.path.getsize(har_path) > 100*1024*1024:
            continue
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)
        for i, entry in enumerate(har['log']['entries']):
            u = entry['request']['url']
            if 'coin' in u.lower() or 'xmy' in u.lower():
                print(f"  [{har_name[:30]}] #{i} {entry['request']['method']} {u[:200]}")

print("\nDone.")
