import json
har_path = r'C:\Users\Administrator\Desktop\111\新建文件夹\0-1.har'
data = json.load(open(har_path, 'r', encoding='utf-8'))
entries = data['log']['entries']

keys = ['purchaseInfoV2', 'item/detail', 'itemDetail', 'rushPurchase']
for e in entries:
    url = e['request']['url']
    method = e['request']['method']
    if method == 'OPTIONS':
        continue
    if any(k in url for k in keys):
        print(f'=== {method} {url}')
        pd = e['request'].get('postData', {})
        if pd and 'text' in pd:
            print(f'REQ: {pd["text"][:800]}')
        resp = e.get('response', {})
        ct = resp.get('content', {}).get('text', '')
        if ct:
            # Try to extract key fields from response
            try:
                rj = json.loads(ct)
                code = rj.get('code')
                d = rj.get('data', {})
                # Extract spuId, skuId, itemCode mappings
                pim = d.get('purchaseInfoMap', {})
                if pim:
                    for sku_id, info in pim.items():
                        pi = info.get('purchaseInfo', {})
                        print(f'  skuId={sku_id}, actId={pi.get("itemPriorityActId")}, inv={pi.get("inventory")}, disable={pi.get("disable")}')
                ii = d.get('itemInfo', {})
                if ii:
                    print(f'  itemInfo: title={ii.get("title")}, spuId={ii.get("spuId")}, price={ii.get("price")}')
                # For rushPurchase response
                rd = d if isinstance(d, dict) else {}
                if rd.get('priorityRecordId'):
                    print(f'  priorityRecordId={rd["priorityRecordId"]}, hasGain={rd.get("hasGain")}, userVerifyStatus={rd.get("userVerifyStatus")}')
                print(f'RESP({resp["status"]}): code={code}, keys={list(d.keys())[:10] if isinstance(d,dict) else type(d).__name__}')
            except:
                print(f'RESP({resp["status"]}): {ct[:500]}')
        print()
