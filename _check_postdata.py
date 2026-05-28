#!/usr/bin/env python3
"""检查 HAR postData 结构"""
import json, base64

har_path = r"C:\Users\Administrator\Desktop\111\新建文件夹\2026-1539.har"
with open(har_path, 'r', encoding='utf-8') as f:
    d = json.load(f)

for e in d['log']['entries']:
    url = e['request']['url']
    if 'haotian' in url or 'mshield' in url:
        pd = e['request'].get('postData', {})
        print(f"\nURL: {url[:130]}")
        print(f"  mimeType: {pd.get('mimeType', 'N/A')}")
        print(f"  params: {pd.get('params', [])}")
        print(f"  encoding: {pd.get('encoding', 'N/A')}")
        print(f"  comment: {pd.get('comment', 'N/A')}")
        text = pd.get('text', '')
        if text:
            print(f"  text length: {len(text)}")
            print(f"  text[:60]: {text[:60]}")
            # Try base64 decode
            try:
                decoded = base64.b64decode(text)
                print(f"  ✓ base64 decode OK: {len(decoded)} bytes, hex[:40]: {decoded[:20].hex()}")
                # Check if decoded looks like gzip
                if decoded[:2] == b'\x1f\x8b':
                    print(f"  >>> IS GZIP!")
                    import gzip
                    try:
                        inner = gzip.decompress(decoded)
                        print(f"  gzip inner: {len(inner)} bytes, hex[:40]: {inner[:20].hex()}")
                    except:
                        print(f"  gzip decompress failed")
                # Check if it's protobuf or other binary
            except Exception as e1:
                print(f"  ✗ base64 decode failed: {e1}")
                try:
                    # try with padding
                    padded = text + '=' * (4 - len(text) % 4)
                    decoded = base64.b64decode(padded)
                    print(f"  ✓ base64+padded decode OK: {len(decoded)} bytes")
                except:
                    print(f"  ✗ also failed with padding")
        # Only check first 5
        if sum(1 for x in d['log']['entries'] if 'haotian' in x['request']['url'] or 'mshield' in x['request']['url']) > 5:
            break
