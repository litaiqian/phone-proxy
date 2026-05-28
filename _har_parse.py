import json

f = open(r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\新建文件夹\android.bugly.qq.com_2026_05_25_14_39_51.har', 'r', encoding='utf-8')
data = json.load(f)
entries = data['log']['entries']

print("=== rushPurchase 请求 ===")
for i, e in enumerate(entries):
    if 'rushPurchase' in e['request']['url']:
        ref = e['request']['headers']
        referer = ''
        for h in ref:
            if h['name'].lower() == 'referer':
                referer = h['value']
        print(f"#{i}: {e['request']['url']}")
        print(f"   Referer: {referer}")
        print(f"   actParam前50: {e['request']['postData']['text'][:50]}...")

print("\n=== purchaseInfoV2 响应 ===")
for i, e in enumerate(entries):
    if 'purchaseInfoV2' in e['request']['url']:
        text = e['response']['content'].get('text', '')
        if text:
            try:
                resp = json.loads(text)
                d = resp.get('data', {})
                print(f"#{i}: itemId={d.get('itemId')}")
                for k, v in d.get('purchaseInfoMap', {}).items():
                    pi = v.get('purchaseInfo', {})
                    print(f"   itemCode={k}  skuId={pi.get('skuId')}  actId={pi.get('itemPriorityActId')}  inventory={pi.get('inventory')}")
                    st = pi.get('startTimeList', [])
                    if st:
                        from datetime import datetime
                        print(f"   抢购时间戳: {[datetime.fromtimestamp(x/1000).strftime('%H:%M:%S') for x in st]}")
                print(f"   full: {text[:500]}")
            except:
                print(f"#{i}: {text[:300]}")

print("\n=== detailV2 响应 (找商品名称) ===")
for i, e in enumerate(entries):
    url = e['request']['url']
    if 'detailV2' in url:
        text = e['response']['content'].get('text', '')
        if not text:
            continue
        try:
            resp = json.loads(text)
            item = resp.get('data', {}).get('item', {})
            title = item.get('title', '') or item.get('name', '')
            spu_id = resp.get('data', {}).get('spuId', '')
            print(f"#{i}: spuId={spu_id}  title={title}")
            if 'IMTP1000313' in url or spu_id == 'IMTP1000313':
                print(f"   >>> 这就是抢购商品! title={title}")
                print(f"   full: {text[:800]}")
        except:
            pass

print("\n=== 浏览过的页面 (jpmt/smsp) ===")
for i, e in enumerate(entries):
    url = e['request']['url']
    if 'jpmt-detail' in url or 'smsp-detail' in url:
        ref = e['request'].get('headers', [])
        print(f"#{i}: {url}")

f.close()
