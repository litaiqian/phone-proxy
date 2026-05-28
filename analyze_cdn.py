import json
from urllib.parse import urlparse

with open(r'C:\Users\Administrator\Desktop\111\新建文件夹\从头0-1到尾.har', 'r', encoding='utf-8') as f:
    data = json.load(f)
entries = data['log']['entries']

print('=== 关键请求头/CDN分析 (moutai域名) ===')
for i, e in enumerate(entries):
    url = e['request']['url']
    time = e['startedDateTime']
    
    if 'moutai519' not in url:
        continue
    
    resp_headers = {h['name'].lower(): h['value'] for h in e['response']['headers']}
    cdn_via = resp_headers.get('x-via', '')
    server = resp_headers.get('server', '')
    
    method = e['request']['method']
    status = e['response']['status']
    server_ip = e.get('serverIPAddress', 'N/A')
    
    parsed = urlparse(url)
    short = f'{parsed.netloc}{parsed.path}'
    
    if cdn_via or server:
        print(f'[{i+1:3d}] {time[11:23]} {method:7s} {status} IP={server_ip}')
        print(f'    URL: {short}')
        if cdn_via: print(f'    CDN-Via: {cdn_via}')
        if server: print(f'    Server: {server}')
        print()
