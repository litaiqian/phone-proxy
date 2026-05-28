import json

with open(r'C:\Users\Administrator\Desktop\111\新建文件夹\从头0-1到尾.har', 'r', encoding='utf-8') as f:
    har = json.load(f)

entries = har['log']['entries']
keywords = ['compose', 'submit', 'rushPurchase', 'verify/code']

for i, e in enumerate(entries):
    url = e['request']['url']
    if any(k in url for k in keywords):
        print(f'=== Entry #{i} ===')
        print(f'Method: {e["request"]["method"]}')
        print(f'URL: {url}')
        print(f'Time: {e["startedDateTime"]}')
        if 'postData' in e['request']:
            text = e['request']['postData'].get('text', '')
            print(f'RequestBody: {text[:2000]}')
        resp_text = e['response']['content'].get('text', '')
        print(f'Response: {resp_text[:2000]}')
        print()
