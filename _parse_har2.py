import json, sys

f = open(r'C:\Users\Administrator\Desktop\111\新建文件夹\新建文件夹\新建文件夹\android.bugly.qq.com_2026_05_25_14_39_51.har', 'r', encoding='utf-8')
data = json.load(f)
entries = data['log']['entries']
out = open(r'D:\采购管理\_har_result.txt', 'w', encoding='utf-8')

out.write("=== rushPurchase 请求 ===\n")
for i, e in enumerate(entries):
    url = e['request']['url']
    if 'rushPurchase' in url:
        ref_hdrs = e['request'].get('headers', [])
        referer = ''
        for h in ref_hdrs:
            if h['name'].lower() == 'referer':
                referer = h['value']
        out.write(f"#{i}: {url}\n")
        out.write(f"   Referer: {referer}\n")
        pd = e['request'].get('postData', {}).get('text', '')
        out.write(f"   actParam前50: {pd[:50]}\n")

out.write("\n=== purchaseInfoV2 响应 ===\n")
for i, e in enumerate(entries):
    if 'purchaseInfoV2' in e['request']['url']:
        text = e['response']['content'].get('text', '')
        if text:
            resp = json.loads(text)
            d = resp.get('data', {})
            item_id = d.get('itemId', '')
            out.write(f"#{i}: itemId={item_id}\n")
            out.write(f"   spuId请求: {e['request'].get('postData',{}).get('text','')[:200]}\n")
            for k, v in d.get('purchaseInfoMap', {}).items():
                pi = v.get('purchaseInfo', {})
                out.write(f"   itemCode={k}  skuId={pi.get('skuId')}  actId={pi.get('itemPriorityActId')}  inventory={pi.get('inventory')}\n")
                st = pi.get('startTimeList', [])
                if st:
                    from datetime import datetime
                    times = [datetime.fromtimestamp(x/1000).strftime('%H:%M:%S') for x in st]
                    out.write(f"   抢购时间: {times}\n")

out.write("\n=== detailV2 响应 (找商品名) ===\n")
for i, e in enumerate(entries):
    url = e['request']['url']
    if 'detailV2' in url:
        text = e['response']['content'].get('text', '')
        if not text:
            continue
        resp = json.loads(text)
        item = resp.get('data', {}).get('item', {})
        spu_id = resp.get('data', {}).get('spuId', '')
        title = item.get('title', '') or item.get('name', '')
        out.write(f"#{i}: {url}\n  spuId={spu_id}  title={title}\n")

out.write("\n=== 浏览的商品页 (jpmt/smsp) ===\n")
for i, e in enumerate(entries):
    url = e['request']['url']
    if 'jpmt-detail' in url or 'smsp-detail' in url:
        out.write(f"#{i}: {url}\n")

out.close()
f.close()
print('DONE - wrote _har_result.txt')
