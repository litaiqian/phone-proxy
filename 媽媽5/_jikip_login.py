import requests, json
requests.packages.urllib3.disable_warnings()
s = requests.Session()
s.headers.update({
    'User-Agent': 'Mozilla/5.0',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
})

# Try JSON-based login APIs
login_data = {'phone': '18610808598', 'password': 'a123aaaa'}
endpoints = [
    'https://www.jikip.com/api/user/login',
    'https://www.jikip.com/api/login',
    'https://api.jikip.com/user/login',
    'https://api.jikip.com/login',
    'https://www.jikip.com/user/doLogin',
    'https://www.jikip.com/login/doLogin',
]

for ep in endpoints:
    try:
        r = s.post(ep, json=login_data, verify=False, timeout=10)
        print(f'POST {ep}: status={r.status_code}')
        print(f'  Response: {r.text[:300]}')
        if r.status_code == 200 and r.json().get('code') in (0, 200, 1):
            print('=== LOGIN SUCCESS ===')
            # Now try to get package list
            for pkg_ep in ['https://www.jikip.com/api/user/product', 'https://api.jikip.com/user/product', 'https://www.jikip.com/api/product/list']:
                try:
                    r2 = s.get(pkg_ep, verify=False, timeout=10)
                    print(f'  GET {pkg_ep}: {r2.text[:500]}')
                except Exception as e2:
                    print(f'  GET {pkg_ep}: error={e2}')
            break
    except Exception as e:
        print(f'POST {ep}: error={e}')

# Also try whiteList-addition without id (just key and ip)
print('\n=== Test whiteList-addition without id ===')
r3 = requests.get('https://api.jikip.com/whiteList-addition?ip=8.137.86.132&key=egt8hjcnpbm38k8', timeout=10, verify=False)
print(f'No id: status={r3.status_code} response={r3.text}')

# Try whiteList-addition with empty id
r4 = requests.get('https://api.jikip.com/whiteList-addition?id=&ip=8.137.86.132&key=egt8hjcnpbm38k8', timeout=10, verify=False)
print(f'Empty id: status={r4.status_code} response={r4.text}')