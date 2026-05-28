#!/usr/bin/env python3
"""从HAR提取安全SDK请求 - 只搜索茅台域名相关的HAR文件，跳过>100MB"""
import json, os

TARGET_KW = ['haotian', 'mshield', 'bangcle', 'bbprbdata', '/sp/exist', 'event/track', 'xmy/user/coin', 'baidu.com']

# 只搜索含 moutai 字样且 <100MB 的 HAR
har_dirs = [
    r'C:\Users\Administrator\Desktop\111',
    r'C:\Users\Administrator\Desktop\111\新建文件夹',
    r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹',
]

har_files = []
for d in har_dirs:
    if not os.path.isdir(d):
        continue
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.endswith('.har'):
                full = os.path.join(root, f)
                sz = os.path.getsize(full)
                if sz > 100 * 1024 * 1024:  # skip >100MB
                    continue
                har_files.append(full)

output_lines = []
output_lines.append(f"找到 {len(har_files)} 个HAR文件\n")

for har_path in har_files:
    fname = os.path.basename(har_path)
    fsize = os.path.getsize(har_path) / 1024
    try:
        with open(har_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        output_lines.append(f"\n[跳过] {fname} ({fsize:.0f}KB) - {e}")
        continue
    
    entries = data.get('log', {}).get('entries', [])
    if not entries:
        continue
    
    matched = []
    for entry in entries:
        url = entry.get('request', {}).get('url', '')
        for kw in TARGET_KW:
            if kw in url.lower():
                matched.append(entry)
                break
    
    if not matched:
        continue
    
    output_lines.append(f"\n{'='*80}")
    output_lines.append(f"文件: {fname} ({len(entries)}请求, 匹配{len(matched)}条, {fsize:.0f}KB)")
    output_lines.append(f"{'='*80}")
    
    for entry in matched:
        req = entry.get('request', {})
        resp = entry.get('response', {})
        url = req.get('url', '')
        method = req.get('method', '')
        status = resp.get('status', 0)
        
        output_lines.append(f"\n{'─'*60}")
        output_lines.append(f"[{method}] {url}")
        output_lines.append(f"  HTTP: {status}")
        
        # 请求头
        headers = {}
        for h in req.get('headers', []):
            headers[h.get('name', '').lower()] = h.get('value', '')
            
        for k, v in headers.items():
            if len(v) > 200:
                v = v[:200] + '...'
            output_lines.append(f"  {k}: {v}")
        
        # 请求体
        pd = req.get('postData', {})
        if pd and pd.get('text'):
            txt = pd['text']
            if len(txt) > 2000:
                txt = txt[:2000] + '...'
            output_lines.append(f"\n  [BODY]")
            try:
                output_lines.append(f"  {json.dumps(json.loads(txt), indent=2, ensure_ascii=False)}")
            except:
                output_lines.append(f"  {txt}")
        
        # 响应
        ct = resp.get('content', {})
        rt = ct.get('text', '')
        if rt:
            if len(rt) > 1500:
                rt = rt[:1500] + '...'
            output_lines.append(f"\n  [RESPONSE]")
            try:
                output_lines.append(f"  {json.dumps(json.loads(rt), indent=2, ensure_ascii=False)}")
            except:
                output_lines.append(f"  {rt[:800]}")

out_path = r'D:\采购管理\_security_extract.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))
print(f'DONE: {len(output_lines)} lines -> {out_path}')
