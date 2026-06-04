import requests
requests.packages.urllib3.disable_warnings()

# Scan whiteList-addition for valid package IDs
print('=== Scanning whiteList-addition for valid package IDs ===')
for pid in range(1, 101):
    try:
        r = requests.get(f'https://api.jikip.com/whiteList-addition?id={pid}&ip=175.155.107.147&key=egt8hjcnpbm38k8', timeout=5, verify=False)
        data = r.json()
        msg = data.get('message', '')
        if '套餐不存在' not in msg:
            print(f'  id={pid}: code={data.get("code")} msg={msg}')
    except:
        pass

for pid in range(10000, 10100):
    try:
        r = requests.get(f'https://api.jikip.com/whiteList-addition?id={pid}&ip=175.155.107.147&key=egt8hjcnpbm38k8', timeout=5, verify=False)
        data = r.json()
        msg = data.get('message', '')
        if '套餐不存在' not in msg:
            print(f'  id={pid}: code={data.get("code")} msg={msg}')
    except:
        pass

# Try find-balance with different userId values and key as id
print('\n=== Testing find-balance ===')
for uid in [1, 2, 100, 1000, 18610808598]:
    try:
        r = requests.get(f'https://api.jikip.com/find-balance?id=egt8hjcnpbm38k8&userId={uid}', timeout=5, verify=False)
        print(f'  userId={uid}: status={r.status_code} response={r.text[:200]}')
    except Exception as e:
        print(f'  userId={uid}: error={e}')