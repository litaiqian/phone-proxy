import requests
requests.packages.urllib3.disable_warnings()

# Try wide range of IDs for whiteList-addition
print('=== Scanning whiteList-addition (wide range) ===')
ranges = [(1,50), (50,100), (100,200), (200,500), (500,1000),
          (1000,2000), (2000,3000), (5000,6000), (8000,9000),
          (9000,9200), (9200,9400), (9400,9500), (9500,9700),
          (9700,9800), (9800,9900), (10000,10100), (15000,15100),
          (20000,20100), (50000,50100)]

for start, end in ranges:
    for pid in range(start, end):
        try:
            r = requests.get(
                f'https://api.jikip.com/whiteList-addition?id={pid}&ip=175.155.107.147&key=egt8hjcnpbm38k8',
                timeout=3, verify=False)
            data = r.json()
            msg = data.get('message', '')
            if '套餐不存在' not in msg:
                print(f'  ★ id={pid}: code={data.get("code")} msg={msg}')
        except:
            pass
    print(f'  range {start}-{end}: done')

print('\n=== Also test whiteList-get ===')
for uid in [18610808598, 9044, 1, 2]:
    for pid in [9044]:
        try:
            r = requests.get(f'https://api.jikip.com/whiteList-get?id={pid}&userId={uid}', timeout=5, verify=False)
            print(f'  whiteList-get id={pid} userId={uid}: {r.text[:200]}')
        except Exception as e:
            print(f'  error: {e}')