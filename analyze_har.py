import json

with open(r'C:\Users\Administrator\Desktop\111\新建文件夹\从头0-1到尾.har', 'r', encoding='utf-8') as f:
    data = json.load(f)

entries = data['log']['entries']
print(f'总请求数: {len(entries)}')
print()

# 收集所有唯一的域名和IP
domains = {}
for e in entries:
    url = e['request']['url']
    server_ip = e.get('serverIPAddress', 'N/A')
    # 提取域名
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain not in domains:
        domains[domain] = {'ips': set(), 'urls': []}
    domains[domain]['ips'].add(server_ip)
    domains[domain]['urls'].append(url.split('?')[0])

print('=== 域名与IP对应关系 ===')
for domain, info in sorted(domains.items()):
    ips = ', '.join(sorted(info['ips']))
    # 去重URL
    unique_urls = list(dict.fromkeys(info['urls']))
    print(f'\n域名: {domain}')
    print(f'  服务端IP: {ips}')
    print(f'  路径:')
    for u in unique_urls:
        parsed = urlparse(u)
        print(f'    {parsed.path}')

print('\n\n=== 所有请求时间线 ===')
for i, e in enumerate(entries):
    url = e['request']['url']
    method = e['request']['method']
    time = e['startedDateTime']
    server_ip = e.get('serverIPAddress', 'N/A')
    status = e['response']['status']
    from urllib.parse import urlparse
    parsed = urlparse(url)
    short = f'{parsed.netloc}{parsed.path}'
    print(f'[{i+1:3d}] {time[11:23]} {method:7s} {status} IP={server_ip:20s} {short}')
