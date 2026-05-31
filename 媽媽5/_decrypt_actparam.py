import base64, json, sys
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

AES_KEY = b"3a79d$e4c2169a#fbd24c583ae71c0b9"[:32]
AES_IV = b"7392645081974362"

act_param = "SSeGBjTN7FYJHdAJdtdL3u4vjeXv7Y37r+avAPs/6T1cEL9+dmFRnCKwWg8C9o+J7nCGwzXeQHq8Fzklw6jD4PPweixANe8ZtAY2hYzHYe7r7FkI/QTZw6N+YUtLj42I9M1+j8h6hw0IVh4QB+xqdKhoFT+J0ve13Ql9Mnr8Tx4gcmNAcm1ybxjAxPIwVRyP5x8k7E4dT7/xGsR2T/b2Kji62PcexlkpPFzZRVX/17utPKTEh/hAH4ecVCs9xIXQi4XmS7wElMDuQ3b246AYLjhcD5KrSYuBv8FP1m9+tK+IufcBfYYNMqN+KH6zt/Pydn6czvMLpiRuBLf2SBweaYpwzdknRMHPgHYLFeKgCKiMsgCLyc4eqY12nl8yPUJn4C5pOhLRMxixjudtdg5KbQ=="

ciphertext = base64.b64decode(act_param)
cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
data = json.loads(plaintext)

out = []
out.append("=== 解密后的 actParam 明文 ===")
out.append(json.dumps(data, indent=2, ensure_ascii=False))

if "IMTP1000313" in json.dumps(data):
    out.append("\n>>> 包含 IMTP1000313！")
else:
    out.append("\n>>> 不包含 IMTP1000313")
    for k, v in data.items():
        if isinstance(v, str) and "IMTP" in v:
            out.append(f"  字段 {k} 包含: {v}")

result = "\n".join(out)
with open("D:/采购管理/媽媽5/_decrypt_result.txt", "w", encoding="utf-8") as f:
    f.write(result)
print(result)
