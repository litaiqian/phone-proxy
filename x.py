#!/usr/bin/env python3
"""测试 coin 接口 + 从特定 HAR 文件提取安全 SDK 请求"""
import json, os, sys

# 1. 先测HAR提取 - 只用已知存在的文件
har_path = r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\app.moutai519.com.cn_2026_05_25_14_46_49.har'
dc_path = r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\dc.moutai519.com.cn_2026_05_25_14_41_54.har'
fk_path = r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\fk1.moutai519.com.cn_2026_05_25_14_50_28.har'

lines = []

for path in [har_path, dc_path, fk_path]:
    lines.append(f'\n{"="*60}')
    lines.append(f'FILE: {os.path.basename(path)}')
    if not os.path.exists(path):
        lines.append(f'  NOT FOUND!')
        continue
    lines.append(f'  SIZE: {os.path.getsize(path)/1024:.0f}KB')
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        lines.append(f'  PARSE ERROR: {e}')
        continue
    
    entries = data.get('log', {}).get('entries', [])
    lines.append(f'  ENTRIES: {len(entries)}')
    
    # 搜索安全/coin相关
    targets = ['haotian', 'mshield', 'bangcle', 'bbprbdata', '/sp/exist', 'event/track', 'xmy/user/coin', 'baidu.com', 'bshield']
    for kw in targets:
        found = []
        for e in entries:
            if kw in e.get('request', {}).get('url', ''):
                found.append(e)
        if found:
            lines.append(f'\n  [{kw}] {len(found)} matches:')
            for en in found[:5]:
                rq = en['request']
                rp = en['response']
                lines.append(f'    {rq["method"]} {rq["url"]}')
                lines.append(f'    -> HTTP {rp["status"]}')
                # 关键请求头
                for h_name in ['user-agent', 'content-type', 'cookie', 'x-requested-with', 'referer', 'origin', 'content-info-bb']:
                    for h in rq.get('headers', []):
                        if h['name'].lower() == h_name:
                            v = h['value'][:200]
                            lines.append(f'      {h_name}: {v}')
                # body
                pd = rq.get('postData', {}).get('text', '')
                if pd:
                    lines.append(f'      BODY: {pd[:500]}')
                # response
                ct = rp.get('content', {}).get('text', '')
                if ct:
                    lines.append(f'      RESP: {ct[:500]}')

out = r'D:\采购管理\se.txt'
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'DONE: {len(lines)} lines')
