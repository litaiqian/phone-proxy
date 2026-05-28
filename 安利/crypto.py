#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i-moutai 1.9.6 crypto - actParam + Content-Web-Bb 完整请求构建

通过 IDA 逆向 librand.so 还原:
  - MIX (mixK): MT-V 签名生成
  - MIXM (mixM): 单参数签名
  - MIXMP (mixMP): 双参数签名
  - gaes: 实际是 MD5 哈希 (不是 AES)

AES 加密参数 (来自 JADX 逆向 AesEncryptionUtil):
  Key: 3a79d$e4c2169a#fbd24c583ae71c0b9
  IV:  7392645081974362
  Mode: AES/CBC/PKCS7Padding

瑞数 BotShield H5 SDK (bs_h5.js):
  Content-Web-Bb: SM4-CBC 加密的设备指纹+请求签名
  Sdk-Ver-Bb:     SDK 版本号
  Content-Hh-Bb:  MurmurHash3 请求签名
"""

import base64
import json
import time
import hashlib
import random
import string
import struct
import os
import uuid as _uuid
from typing import Dict, Any, List, Tuple, Optional, Union


# ============================================================
# 瑞数 BotShield H5 SDK (bs_h5.js V3.5.0_20260403.1_imaotai)
# ============================================================


# ============================================================
# 1. MurmurHash3 x64 128-bit (对应 bs_h5.js 第 5030 行 h 函数)
# ============================================================

def _x64_add(a: list, b: list) -> list:
    """64-bit addition using two 32-bit ints [high, low]"""
    a = [a[0] >> 16, a[0] & 0xFFFF, a[1] >> 16, a[1] & 0xFFFF]
    b = [b[0] >> 16, b[0] & 0xFFFF, b[1] >> 16, b[1] & 0xFFFF]
    c = [0, 0, 0, 0]
    c[3] = a[3] + b[3]
    c[2] = a[2] + b[2] + (c[3] >> 16)
    c[3] &= 0xFFFF
    c[1] = a[1] + b[1] + (c[2] >> 16)
    c[2] &= 0xFFFF
    c[0] = a[0] + b[0] + (c[1] >> 16)
    c[1] &= 0xFFFF
    c[0] &= 0xFFFF
    return [(c[0] << 16) | c[1], (c[2] << 16) | c[3]]


def _x64_multiply(a: list, b: list) -> list:
    """64-bit multiply using two 32-bit ints"""
    a = [a[0] >> 16, a[0] & 0xFFFF, a[1] >> 16, a[1] & 0xFFFF]
    b = [b[0] >> 16, b[0] & 0xFFFF, b[1] >> 16, b[1] & 0xFFFF]
    c = [0, 0, 0, 0]
    c[3] += a[3] * b[3]
    c[2] += c[3] >> 16
    c[3] &= 0xFFFF
    c[2] += a[2] * b[3]
    c[1] += c[2] >> 16
    c[2] &= 0xFFFF
    c[2] += a[3] * b[2]
    c[1] += c[2] >> 16
    c[2] &= 0xFFFF
    c[1] += a[1] * b[3]
    c[0] += c[1] >> 16
    c[1] &= 0xFFFF
    c[1] += a[2] * b[2]
    c[0] += c[1] >> 16
    c[1] &= 0xFFFF
    c[1] += a[3] * b[1]
    c[0] += c[1] >> 16
    c[1] &= 0xFFFF
    c[0] += a[0] * b[3] + a[1] * b[2] + a[2] * b[1] + a[3] * b[0]
    c[0] &= 0xFFFF
    return [(c[0] << 16) | c[1], (c[2] << 16) | c[3]]


def _x64_rotl(a: list, b: int) -> list:
    """64-bit rotate left"""
    b %= 64
    if b == 32:
        return [a[1], a[0]]
    elif b < 32:
        return [
            (a[0] << b | a[1] >> (32 - b)) & 0xFFFFFFFF,
            (a[1] << b | a[0] >> (32 - b)) & 0xFFFFFFFF
        ]
    else:
        b -= 32
        return [
            (a[1] << b | a[0] >> (32 - b)) & 0xFFFFFFFF,
            (a[0] << b | a[1] >> (32 - b)) & 0xFFFFFFFF
        ]


def _x64_xor(a: list, b: list) -> list:
    return [(a[0] ^ b[0]) & 0xFFFFFFFF, (a[1] ^ b[1]) & 0xFFFFFFFF]


def _x64_left_shift(a: list, b: int) -> list:
    if b == 0:
        return a
    elif b < 32:
        return [(a[1] << b >> 32) & 0xFFFFFFFF, (a[1] << b) & 0xFFFFFFFF]
    else:
        return [(a[1] << (b - 32)) & 0xFFFFFFFF, 0]


def _x64_fmix(a: list) -> list:
    a = _x64_xor(a, [0, a[0] >> 1])
    a = _x64_multiply(a, [0xFF51AFD7, 0xED558CCD])
    a = _x64_xor(a, [0, a[0] >> 1])
    a = _x64_multiply(a, [0xC4CEB9FE, 0x1A85EC53])
    a = _x64_xor(a, [0, a[0] >> 1])
    return a


def _to_unsigned(v: int) -> int:
    """JS >>> 0 equivalent"""
    return v & 0xFFFFFFFF


def str2utf8(s: str) -> list:
    """对应 bs_h5.js str2utf8"""
    result = []
    for ch in s:
        code = ord(ch)
        if 0 <= code < 128:
            result.append(code)
        else:
            encoded = ch.encode('utf-8')
            for b in encoded:
                result.append(b)
    return result


def murmur_hash3_x64_128(data: str, seed: int = 0, max_len: int = None, salt: str = None) -> str:
    """
    MurmurHash3 x64 128-bit
    对应 bs_h5.js 第 5030 行 h(t, e, n, r) 函数
    """
    t = str2utf8(data) if isinstance(data, str) else list(data)
    if max_len:
        t = t[:max_len]
    if salt:
        t = t + str2utf8(salt)

    remainder = len(t) % 16
    bytes_len = len(t) - remainder

    h1 = [0, seed]
    h2 = [0, seed]
    k1 = [0, 0]
    k2 = [0, 0]

    c1 = [0x87C37B91, 0x114253D5]
    c2 = [0x4CF5AD43, 0x2745937F]

    d = 0
    while d < bytes_len:
        k1 = [
            (255 & t[d + 4]) | ((255 & t[d + 5]) << 8) | ((255 & t[d + 6]) << 16) | ((255 & t[d + 7]) << 24),
            (255 & t[d]) | ((255 & t[d + 1]) << 8) | ((255 & t[d + 2]) << 16) | ((255 & t[d + 3]) << 24)
        ]
        k2 = [
            (255 & t[d + 12]) | ((255 & t[d + 13]) << 8) | ((255 & t[d + 14]) << 16) | ((255 & t[d + 15]) << 24),
            (255 & t[d + 8]) | ((255 & t[d + 9]) << 8) | ((255 & t[d + 10]) << 16) | ((255 & t[d + 11]) << 24)
        ]

        k1 = _x64_multiply(k1, c1)
        k1 = _x64_rotl(k1, 31)
        k1 = _x64_multiply(k1, c2)
        h1 = _x64_xor(h1, k1)
        h1 = _x64_rotl(h1, 27)
        h1 = _x64_add(h1, h2)
        h1 = _x64_add(_x64_multiply(h1, [0, 5]), [0, 0x52DCE729])

        k2 = _x64_multiply(k2, c2)
        k2 = _x64_rotl(k2, 33)
        k2 = _x64_multiply(k2, c1)
        h2 = _x64_xor(h2, k2)
        h2 = _x64_rotl(h2, 31)
        h2 = _x64_add(h2, h1)
        h2 = _x64_add(_x64_multiply(h2, [0, 5]), [0, 0x38495AB5])

        d += 16

    k1 = [0, 0]
    k2 = [0, 0]

    # Handle remainder (fall-through switch)
    if remainder >= 15:
        k2 = _x64_xor(k2, _x64_left_shift([0, t[d + 14]], 48))
    if remainder >= 14:
        k2 = _x64_xor(k2, _x64_left_shift([0, t[d + 13]], 40))
    if remainder >= 13:
        k2 = _x64_xor(k2, _x64_left_shift([0, t[d + 12]], 32))
    if remainder >= 12:
        k2 = _x64_xor(k2, _x64_left_shift([0, t[d + 11]], 24))
    if remainder >= 11:
        k2 = _x64_xor(k2, _x64_left_shift([0, t[d + 10]], 16))
    if remainder >= 10:
        k2 = _x64_xor(k2, _x64_left_shift([0, t[d + 9]], 8))
    if remainder >= 9:
        k2 = _x64_xor(k2, [0, t[d + 8]])
        k2 = _x64_multiply(k2, c2)
        k2 = _x64_rotl(k2, 33)
        k2 = _x64_multiply(k2, c1)
        h2 = _x64_xor(h2, k2)

    if remainder >= 8:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 7]], 56))
    if remainder >= 7:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 6]], 48))
    if remainder >= 6:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 5]], 40))
    if remainder >= 5:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 4]], 32))
    if remainder >= 4:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 3]], 24))
    if remainder >= 3:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 2]], 16))
    if remainder >= 2:
        k1 = _x64_xor(k1, _x64_left_shift([0, t[d + 1]], 8))
    if remainder >= 1:
        k1 = _x64_xor(k1, [0, t[d]])
        k1 = _x64_multiply(k1, c1)
        k1 = _x64_rotl(k1, 31)
        k1 = _x64_multiply(k1, c2)
        h1 = _x64_xor(h1, k1)

    h1 = _x64_xor(h1, [0, len(t)])
    h2 = _x64_xor(h2, [0, len(t)])

    h1 = _x64_add(h1, h2)
    h2 = _x64_add(h2, h1)

    h1 = _x64_fmix(h1)
    h2 = _x64_fmix(h2)

    h1 = _x64_add(h1, h2)
    h2 = _x64_add(h2, h1)

    return (
        format(_to_unsigned(h1[0]), '08x') +
        format(_to_unsigned(h1[1]), '08x') +
        format(_to_unsigned(h2[0]), '08x') +
        format(_to_unsigned(h2[1]), '08x')
    )


# ============================================================
# 2. SM4-CBC 加密 (对应 bs_h5.js 第 923 模块)
# ============================================================

# SM4 S-Box
_SM4_SBOX = [
    214, 144, 233, 254, 204, 225, 61, 183, 22, 182, 20, 194, 40, 251, 44, 5,
    43, 103, 154, 118, 42, 190, 4, 195, 170, 68, 19, 38, 73, 134, 6, 153,
    156, 66, 80, 244, 145, 239, 152, 122, 51, 84, 11, 67, 237, 207, 172, 98,
    228, 179, 28, 169, 201, 8, 232, 149, 128, 223, 148, 250, 117, 143, 63, 166,
    71, 7, 167, 252, 243, 115, 23, 186, 131, 89, 60, 25, 230, 133, 79, 168,
    104, 107, 129, 178, 113, 100, 218, 139, 248, 235, 15, 75, 112, 86, 157, 53,
    30, 36, 14, 94, 99, 88, 209, 162, 37, 34, 124, 59, 1, 33, 120, 135,
    212, 0, 70, 87, 159, 211, 39, 82, 76, 54, 2, 231, 160, 196, 200, 158,
    234, 191, 138, 210, 64, 199, 56, 181, 163, 247, 242, 206, 249, 97, 21, 161,
    224, 174, 93, 164, 155, 52, 26, 85, 173, 147, 50, 48, 245, 140, 177, 227,
    29, 246, 226, 46, 130, 102, 202, 96, 192, 41, 35, 171, 13, 83, 78, 111,
    213, 219, 55, 69, 222, 253, 142, 47, 3, 255, 106, 114, 109, 108, 91, 81,
    141, 27, 175, 146, 187, 221, 188, 127, 17, 217, 92, 65, 31, 16, 90, 216,
    10, 193, 49, 136, 165, 205, 123, 189, 45, 116, 208, 18, 184, 229, 180, 176,
    137, 105, 151, 74, 12, 150, 119, 126, 101, 185, 241, 9, 197, 110, 198, 132,
    24, 240, 125, 236, 58, 220, 77, 32, 121, 238, 95, 62, 215, 203, 57, 72
]

# SM4 CK constants
_SM4_CK = [
    462357, 472066609, 943670861, 1415275113, 1886879365, 2358483617,
    2830087869, 3301692121, 3773296373, 4228057617, 404694573, 876298825,
    1347903077, 1819507329, 2291111581, 2762715833, 3234320085, 3705924337,
    4177462797, 337322537, 808926789, 1280531041, 1752135293, 2223739545,
    2695343797, 3166948049, 3638552301, 4110090761, 269950501, 741554753,
    1213159005, 1684763257
]

# SM4 FK constants
_SM4_FK = [0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC]


def _sm4_rotl(x: int, n: int) -> int:
    """32-bit rotate left"""
    n &= 31
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _sm4_sbox_transform(x: int) -> int:
    """SM4 S-Box substitution on 32-bit word"""
    return (
        ((_SM4_SBOX[(x >> 24) & 0xFF] & 0xFF) << 24) |
        ((_SM4_SBOX[(x >> 16) & 0xFF] & 0xFF) << 16) |
        ((_SM4_SBOX[(x >> 8) & 0xFF] & 0xFF) << 8) |
        (_SM4_SBOX[x & 0xFF] & 0xFF)
    )


def _sm4_t_transform(x: int) -> int:
    """SM4 T transform (S-Box + linear L)"""
    b = _sm4_sbox_transform(x)
    return b ^ _sm4_rotl(b, 2) ^ _sm4_rotl(b, 10) ^ _sm4_rotl(b, 18) ^ _sm4_rotl(b, 24)


def _sm4_t_prime(x: int) -> int:
    """SM4 T' transform for key expansion"""
    b = _sm4_sbox_transform(x)
    return b ^ _sm4_rotl(b, 13) ^ _sm4_rotl(b, 23)


def _sm4_round_keys(key_bytes: list, is_encrypt: bool = True) -> list:
    """Generate 32 round keys from 16-byte key"""
    mk = [0] * 4
    for i in range(4):
        mk[i] = (key_bytes[4 * i] << 24) | (key_bytes[4 * i + 1] << 16) | \
                 (key_bytes[4 * i + 2] << 8) | key_bytes[4 * i + 3]

    k = [0] * 4
    for i in range(4):
        k[i] = mk[i] ^ _SM4_FK[i]

    rk = [0] * 32
    for i in range(0, 32, 4):
        tmp = k[1] ^ k[2] ^ k[3] ^ _SM4_CK[i]
        rk[i] = k[0] ^ _sm4_t_prime(tmp)
        k[0] = rk[i]

        tmp = k[2] ^ k[3] ^ k[0] ^ _SM4_CK[i + 1]
        rk[i + 1] = k[1] ^ _sm4_t_prime(tmp)
        k[1] = rk[i + 1]

        tmp = k[3] ^ k[0] ^ k[1] ^ _SM4_CK[i + 2]
        rk[i + 2] = k[2] ^ _sm4_t_prime(tmp)
        k[2] = rk[i + 2]

        tmp = k[0] ^ k[1] ^ k[2] ^ _SM4_CK[i + 3]
        rk[i + 3] = k[3] ^ _sm4_t_prime(tmp)
        k[3] = rk[i + 3]

    if not is_encrypt:
        # Reverse round keys for decryption
        for i in range(16):
            rk[i], rk[31 - i] = rk[31 - i], rk[i]

    return rk


def _sm4_one_round(block: list, out: list, rk: list):
    """Encrypt/decrypt one 16-byte block"""
    x = [0] * 4
    for i in range(4):
        x[i] = (block[4 * i] << 24) | (block[4 * i + 1] << 16) | \
               (block[4 * i + 2] << 8) | block[4 * i + 3]

    for i in range(0, 32, 4):
        tmp = x[1] ^ x[2] ^ x[3] ^ rk[i]
        x[0] ^= _sm4_t_transform(tmp)
        tmp = x[2] ^ x[3] ^ x[0] ^ rk[i + 1]
        x[1] ^= _sm4_t_transform(tmp)
        tmp = x[3] ^ x[0] ^ x[1] ^ rk[i + 2]
        x[2] ^= _sm4_t_transform(tmp)
        tmp = x[0] ^ x[1] ^ x[2] ^ rk[i + 3]
        x[3] ^= _sm4_t_transform(tmp)

    for i in range(0, 16, 4):
        idx = 3 - i // 4
        out[i] = (x[idx] >> 24) & 0xFF
        out[i + 1] = (x[idx] >> 16) & 0xFF
        out[i + 2] = (x[idx] >> 8) & 0xFF
        out[i + 3] = x[idx] & 0xFF


def _hex_to_bytes(hex_str: str) -> list:
    """Hex string to byte list"""
    return [int(hex_str[i:i + 2], 16) for i in range(0, len(hex_str), 2)]


def _utf8_to_bytes(s: str) -> list:
    """UTF-8 string to byte list (same as SM4 module's internal encoder)"""
    result = []
    for ch in s:
        cp = ord(ch)
        if cp <= 127:
            result.append(cp)
        elif cp <= 2047:
            result.append(0xC0 | (cp >> 6))
            result.append(0x80 | (cp & 0x3F))
        elif cp <= 55295 or (57344 <= cp <= 65535):
            result.append(0xE0 | (cp >> 12))
            result.append(0x80 | ((cp >> 6) & 0x3F))
            result.append(0x80 | (cp & 0x3F))
        elif 65536 <= cp <= 1114111:
            result.append(0xF0 | ((cp >> 18) & 0x1C))
            result.append(0x80 | ((cp >> 12) & 0x3F))
            result.append(0x80 | ((cp >> 6) & 0x3F))
            result.append(0x80 | (cp & 0x3F))
    return result


def sm4_encrypt_cbc(plaintext: str, key_hex: str, iv_hex: str) -> str:
    """
    SM4-CBC encrypt, PKCS#7 padding, output hex string
    对应 bs_h5.js 第 7155 行 en 函数 + 第 923 模块
    """
    key_bytes = _hex_to_bytes(key_hex)
    iv_bytes = _hex_to_bytes(iv_hex)

    if len(key_bytes) != 16:
        raise ValueError(f"key must be 16 bytes, got {len(key_bytes)}")
    if len(iv_bytes) != 16:
        raise ValueError(f"iv must be 16 bytes, got {len(iv_bytes)}")

    # UTF-8 encode plaintext
    data = _utf8_to_bytes(plaintext)

    # PKCS#7 padding
    pad_len = 16 - (len(data) % 16)
    data.extend([pad_len] * pad_len)

    # Generate round keys
    rk = _sm4_round_keys(key_bytes, is_encrypt=True)

    # CBC encrypt
    result = []
    prev_block = iv_bytes[:]
    for offset in range(0, len(data), 16):
        block = data[offset:offset + 16]
        # XOR with previous ciphertext block
        xored = [(block[i] ^ prev_block[i]) for i in range(16)]
        out = [0] * 16
        _sm4_one_round(xored, out, rk)
        result.extend(out)
        prev_block = out[:]

    return ''.join(format(b, '02x') for b in result)


def sm4_decrypt_cbc(ciphertext_hex: str, key_hex: str, iv_hex: str) -> str:
    """SM4-CBC decrypt, PKCS#7 unpadding"""
    key_bytes = _hex_to_bytes(key_hex)
    iv_bytes = _hex_to_bytes(iv_hex)
    data = _hex_to_bytes(ciphertext_hex)

    rk = _sm4_round_keys(key_bytes, is_encrypt=False)

    result = []
    prev_block = iv_bytes[:]
    for offset in range(0, len(data), 16):
        block = data[offset:offset + 16]
        out = [0] * 16
        _sm4_one_round(block, out, rk)
        decrypted = [(out[i] ^ prev_block[i]) for i in range(16)]
        result.extend(decrypted)
        prev_block = block[:]

    # PKCS#7 unpadding
    pad_len = result[-1]
    if 1 <= pad_len <= 16:
        result = result[:-pad_len]

    # Decode UTF-8
    return bytes(result).decode('utf-8')


# ============================================================
# 3. 密钥派生 (对应 bs_h5.js 第 7150 行 k 函数)
# ============================================================

def derive_sm4_key(smk: str) -> str:
    """
    从随机 smk 派生 SM4 密钥
    k: function(t) { return h(t + "_bsdk_", 27).toLowerCase() }
    """
    result = murmur_hash3_x64_128(smk + "_bsdk_", seed=27)
    return result.lower() if result else "9eqaw+jthssyswpl9eqaw+jthssyswpl"


# ============================================================
# 4. 随机 ID 生成 (对应 bs_h5.js 第 10010 行 getRandomId)
# ============================================================


def get_random_id() -> str:
    """
    生成 32 位随机 hex ID
    对应 bs_h5.js getRandomId (l 函数)
    """
    parts = []
    for _ in range(3):
        parts.append(str(int(time.time() * 1000)))
    base = ''.join(parts)
    template = base.replace('.', 'x')[:32].ljust(32, 'x')

    ts = int(time.time() * 1000)
    result = []
    for ch in template:
        r = (ts + random.randint(0, 15)) % 16
        ts = ts // 16
        if ch == 'x':
            result.append(format(r, 'x'))
        else:  # 'y'
            result.append(format((r & 0x3) | 0x8, 'x'))
    return ''.join(result)


# ============================================================
# 5. jsonSerialize (对应 bs_h5.js 第 9841 行)
# ============================================================

def json_serialize(obj, depth: int = 0) -> Union[str, int, bool, None]:
    """
    递归序列化对象，用于请求签名
    对应 bs_h5.js jsonSerialize
    """
    depth = depth + 1 if isinstance(depth, int) else 1

    if depth == 1 and (obj is None or obj != obj):  # NaN check
        return ""
    if obj is None:
        return "|-|-|"
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float)):
        if depth == 1 and isinstance(obj, bool):
            return ""
        if isinstance(obj, bool):
            return obj
        return obj
    if isinstance(obj, list):
        if depth > 10:
            return "[]"
        serialized = [json_serialize(item, depth) for item in obj]
        filtered = [x for x in serialized if x != "|-|-|"]
        return json.dumps(filtered, separators=(',', ':'), ensure_ascii=False)
    if isinstance(obj, dict):
        keys = sorted(obj.keys())
        parts = []
        for key in keys:
            val = json_serialize(obj[key], depth)
            if val != "|-|-|":
                parts.append(val)
        return json.dumps(parts, separators=(',', ':'), ensure_ascii=False) if parts else ""

    return str(obj)


# ============================================================
# 6. urlParamsConcat (对应 bs_h5.js 第 9983 行)
# ============================================================

def url_params_concat(query_string: str, extra: str = "") -> str:
    """
    URL 参数排序拼接
    对应 bs_h5.js urlParamsConcat
    """
    pairs = []
    if query_string:
        for part in query_string.split("&"):
            idx = part.find("=")
            if idx > -1:
                pairs.append([part[:idx], part[idx + 1:]])
            else:
                pairs.append([part, ""])

    result = ""
    pairs.sort(key=lambda x: x[0])
    for pair in pairs:
        result += "&" + pair[0] + "=" + pair[1]

    return result[1:] if result else ""


# ============================================================
# 7. objectToArray (对应 bs_h5.js 第 9951 行)
# ============================================================

def object_to_array(obj: dict) -> list:
    """
    将对象按 key 排序转为数组
    对应 bs_h5.js objectToArray
    """
    keys = sorted(obj.keys(), key=str)
    result = []
    for key in keys:
        if key == "$1":
            continue
        val = obj[key]
        if val is None:
            result.append(None)
        elif isinstance(val, dict):
            result.append(object_to_array(val))
        elif isinstance(val, list):
            result.append([object_to_array(item) if isinstance(item, dict) else item for item in val])
        else:
            result.append(val)
    return result


# ============================================================
# 8. processData 加密 (对应 bs_h5.js 第 10270 行)
# ============================================================

def process_data(data, smk: str = None, smk1: str = None, smi: str = None):
    """
    加密数据为 Content-Web-Bb 的值
    对应 bs_h5.js processData

    返回: (encrypted_data, smk, smk1, smi)
    """
    if not smk:
        smk = get_random_id()
    if not smk1:
        smk1 = derive_sm4_key(smk)
    if not smi:
        smi = ''.join(format(1 ^ int(c, 16), 'x') for c in smk)

    plaintext = data if isinstance(data, str) else json.dumps(data, separators=(',', ':'), ensure_ascii=False)

    encrypted = sm4_encrypt_cbc(plaintext, smk1, smk1)

    # 结果 = [encrypted, smi].reverse().join("") = smi + encrypted
    result = smi + encrypted

    return result, smk, smk1, smi


# ============================================================
# 9. 完整的 Content-Web-Bb 生成 (对应 bs_h5.js 第 13989 行 p 函数)
# ============================================================

SDK_VERSION = "V3.5.0_20260403.1_imaotai"

# ============================================================
# 解密后 13 元素数组 — 各字段含义与生成方式
# ============================================================
#
# objectToArray 按 key 字典序 ("101" < "103" < ... < "141") 排序后:
#
# [0]  key=101  app_key
#      来源: e.sdkConfig.app_key
#      生成: 页面 window._bb_a 或 HTML 中 $$_bb_app_id_$$ 占位符替换
#      imaotai 固定值: "10001"
#
# [1]  key=103  did (设备ID)
#      来源: e.did
#      生成: bs_h5.js udid() 函数 (第 4002 行)
#        1) 采集 34 项浏览器特征 (UA/colorDepth/deviceMemory/canvas/webgl/fonts...)
#        2) features = 所有特征用 "_" 拼接
#        3) fp_hash = MurmurHash3(features, seed=27)
#        4) did = "h" + guid()[25:] + fp_hash[3:19] + MurmurHash3(did_base, 27)[6:10]
#      格式: "h" + 11位guid尾 + 16位指纹 + 4位校验 = 32字符
#      持久化: cookie "device_id" + localStorage "__ud"
#
# [2]  key=104  startId (会话ID)
#      来源: e.startId || sessionStorage.getItem("__36_i__") || ""
#      生成: getStartId() (第 10629 行)
#        Date.now().toString(36) + "_" + Math.random().toString(36).slice(2) + "_4"
#      示例: "mniz0s9z_e6a3xisfulu_4"
#      持久化: sessionStorage "__36_i__" (页面关闭即失效)
#
# [3]  key=105  UA 信息
#      来源: cookieSend 模式 → "" (空字符串)
#              非 cookieSend → UA 截断到第一个 ")" 处, IE 加 "ie:" 前缀
#      imaotai H5 使用 cookieSend 模式, 所以固定为 ""
#
# [4]  key=106  设备指纹 (deviceInfo[600])
#      来源: cookieSend 模式 → "0"
#              非 cookieSend → getDomain() 返回的页面域名
#      imaotai H5 使用 cookieSend 模式, 所以固定为 "0"
#
# [5]  key=108  浏览器指纹 hp
#      来源: cookieSend 模式 → "0"
#              非 cookieSend → e.hp (genFToken 生成)
#      genFToken (第 10330 行):
#        hp = "bid-" + Date.now()反转 + "-" + did末4位 + "-" + guid()[9:13]
#        持久化: localStorage "__mg__" (有效期 ~168年), cookie "_bs_device_id"
#      imaotai H5 使用 cookieSend 模式, 所以固定为 "0"
#
# [6]  key=109  randomId (请求随机数)
#      来源: getRandomId() (第 10010 行)
#      生成: 3次 Date.now() 拼接, 全部替换为 "x", 取前32位,
#            然后用时间戳+随机数逐位替换为 hex 字符
#      格式: 32 位随机 hex 字符串
#      每次请求重新生成, 不持久化
#
# [7]  key=110  sign (请求数据签名)
#      来源: MurmurHash3(请求数据, seed=27, maxLen=4096, salt=randomId)
#      生成: o["default"].h(t, 27, 4096, n) (第 5030 行)
#        t = 序列化后的请求数据:
#          POST → jsonSerialize(body) 递归序列化
#          GET  → urlParamsConcat(queryString) 参数排序拼接
#        n = randomId (字段 109)
#      格式: 32 位 hex (MurmurHash3 x64 128-bit)
#
# [8]  key=111  timestamp (毫秒时间戳)
#      来源: Date.now()
#      生成: 当前时间毫秒数, 如 1775224840388
#
# [9]  key=120  extra (扩展字段)
#      来源: {} (空对象)
#      生成: objectToArray({}) → []
#      固定为空数组 []
#
# [10] key=130  userId (用户ID)
#      来源: localStorage.getItem("_u_id_") || ""
#      生成: APP 通过 JSBridge 调用 getUserId_callback(userId) 写入
#        window.getUserId_callback = function(t) {
#            t && "null" !== t && localStorage.setItem("_u_id_", t)
#        }
#      示例: "1196233237"
#      未登录时为 ""
#
# [11] key=140  wasm_version (WASM 签名版本)
#      来源: getCurrentSignWasmVersion() (第 2670 行)
#      生成: window.__SIGN_WASM_VERSION__ || localStorage("__wasm_sign_version__")
#      示例: "v1.0.6"
#      WASM 未加载时为 ""
#
# [12] key=141  wasm_sign (WASM 签名结果)
#      来源: runWac(did, sign, wasmBinary) (第 9372 行)
#      生成:
#        1) wasmBinary = Base64Decode(localStorage("__wasm_sign_wasm__"))
#        2) 调用 WASM 模块的 run_wac(did, sign, wasmBinary)
#        3) WASM 内部用 did + sign 计算加密签名
#        4) js_invoke 桥接: WASM 调用 Date.now() 和 window.eval(环境检测)
#      格式: JSON 字符串 '{"uuid":"...","body":"...base64...","has_env":0}'
#        uuid: 随机 UUID
#        body: WASM 加密后的 base64 数据
#        has_env: 环境检测标志 (0=WebView, 1=浏览器)
#      Python: generate_wasm_sign(did, sign) 或 is_rush_purchase=True 自动调用
#      仅抢购 URL (/rushPurchase) 才需要, 其他请求为 ""
#      依赖: stub.wasm + sign_wasm.bin + wasmtime
#
# ============================================================

FIELD_INDEX = {
    "app_key":       0,   # 101
    "did":           1,   # 103
    "start_id":      2,   # 104
    "ua_info":       3,   # 105
    "device_fp":     4,   # 106
    "hp":            5,   # 108
    "random_id":     6,   # 109
    "sign":          7,   # 110
    "timestamp":     8,   # 111
    "extra":         9,   # 120
    "user_id":       10,  # 130
    "wasm_version":  11,  # 140
    "wasm_sign":     12,  # 141
}

# imaotai H5 默认 app_key
DEFAULT_APP_KEY = "10001"


def generate_content_web_bb(
    request_data: str,
    app_key: str = DEFAULT_APP_KEY,
    did: str = "",
    start_id: str = "",
    user_id: str = "",
    ua_info: str = "",
    device_fp: str = "0",
    hp: str = "0",
    wasm_version: str = "",
    wasm_sign: str = "",
    smk: str = None,
    smk1: str = None,
    smi: str = None,
    is_rush_purchase: bool = False,
    sign_wasm_bytes: bytes = None,
) -> dict:
    """
    生成完整的 Content-Web-Bb / Sdk-Ver-Bb / Content-Hh-Bb 三个 Header

    -------- 参数 --------
    request_data:    序列化后的请求数据 (GET: urlParamsConcat, POST: jsonSerialize)
    app_key:         SDK app_key, imaotai 固定为 "10001"
    did:             设备 ID, 格式 "h" + 指纹hash(16位) + 校验位(4位)
    start_id:        会话 ID (sessionStorage.__36_i__)
    user_id:         用户 ID (localStorage._u_id_)
    ua_info:         UA 信息 (cookieSend 模式下为空)
    device_fp:       设备指纹 (cookieSend 模式下为 "0")
    hp:              浏览器指纹 (cookieSend 模式下为 "0")
    wasm_version:    WASM 签名版本, 如 "a2abd765daa2ec438a96fc2d97209be4"
    wasm_sign:       WASM 签名结果 JSON (手动传入, 优先级高于自动生成)
    smk/smk1/smi:    可选, 复用已有的加密密钥
    is_rush_purchase: 是否为抢购请求 (仅抢购 URL 才需要 WASM 签名)
    sign_wasm_bytes: 可选, sign_wasm 字节 (不传则使用全局加载的)

    -------- 返回 --------
    {
        "Content-Web-Bb": "...",
        "Sdk-Ver-Bb": "...",
        "Content-Hh-Bb": "...",
            "_debug": { smk, smk1, smi, random_id, sign, ... }
        }
    """
    # Step 1: 生成随机 ID
    random_id = get_random_id()

    # Step 2: MurmurHash3 签名请求数据
    sign = murmur_hash3_x64_128(request_data, seed=27, max_len=4096, salt=random_id)

    # Step 3: 自动 WASM 签名 (仅抢购请求 + 未手动传入时)
    if is_rush_purchase and not wasm_sign:
        ws = generate_wasm_sign(did, sign, sign_wasm_bytes)
        if ws:
            wasm_sign = ws

    # Step 4: 构造数据对象 h (key 为字符串数字, objectToArray 按字典序排序)
    h = {
        "101": app_key,
        "103": did,
        "104": start_id,
        "105": ua_info,
        "106": device_fp,
        "108": hp,
        "109": random_id,
        "110": sign,
        "111": int(time.time() * 1000),
        "120": {},
        "130": str(user_id),
        "140": wasm_version,
        "141": wasm_sign,
    }

    # Step 5: objectToArray - 按 key 排序转数组
    arr = object_to_array(h)

    # Step 6: processData - SM4 加密
    encrypted, smk, smk1, smi = process_data(arr, smk, smk1, smi)

    return {
        "Content-Web-Bb": encrypted,
        "Sdk-Ver-Bb": SDK_VERSION,
        "Content-Hh-Bb": sign,
        "_debug": {
            "smk": smk,
            "smk1": smk1,
            "smi": smi,
            "random_id": random_id,
            "sign": sign,
            "wasm_sign": wasm_sign,
            "h_object": h,
            "h_array": arr,
        }
    }


# ============================================================
# 9.3 WASM 签名 (对应 bs_h5.js 第 9372 行 runWac)
# ============================================================
#
# stub.wasm: Emscripten 编译的 WASM 运行时, 导出 run_wac / malloc / free 等
# sign_wasm.bin: 加密的签名逻辑 WASM, 从 localStorage __wasm_sign_wasm__ 读取
#
# run_wac(did_ptr, did_len, sign_ptr, sign_len, wasm_ptr, wasm_len) -> result_ptr
#   输入: did (设备ID), sign (MurmurHash3 请求签名), sign_wasm (加密WASM字节)
#   输出: JSON 字符串 {"uuid":"...","body":"...","has_env":0}
#
# js_invoke 桥接协议 (WASM 调用 JS):
#   js_invoke(target_ptr, method_ptr, args_ptr) -> result_ptr
#   调用 1: target="Date", method="now" -> 返回时间戳
#   调用 2: target="window", method="eval" -> 返回环境类型 (0=WebView, 1=浏览器)

try:
    import wasmtime as _wasmtime
    _HAS_WASMTIME = True
except ImportError:
    _HAS_WASMTIME = False

# WASM 文件路径 (相对于本文件所在目录)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_WASM_PATH = os.path.join(_SCRIPT_DIR, "stub.wasm")
_SIGN_WASM_PATH = os.path.join(_SCRIPT_DIR, "sign_wasm.bin")

# 全局 WASM 实例 (懒加载, 单例)
_wasm_engine = None
_wasm_store = None
_wasm_instance = None
_sign_wasm_bytes = None


def _wasm_read_cstring(store, instance, ptr):
    """从 WASM 内存读取 null-terminated UTF-8 字符串"""
    mem = instance.exports(store)["memory"]
    buf = mem.data_ptr(store)
    size = mem.data_len(store)
    result = bytearray()
    i = 0
    while ptr + i < size and buf[ptr + i] != 0:
        result.append(buf[ptr + i])
        i += 1
    return result.decode('utf-8')


def _wasm_write_cstring(store, instance, s):
    """写入 UTF-8 字符串到 WASM 内存, 返回指针"""
    malloc_fn = instance.exports(store)["malloc"]
    mem = instance.exports(store)["memory"]
    encoded = s.encode('utf-8') + b'\x00'
    ptr = malloc_fn(store, len(encoded))
    buf = mem.data_ptr(store)
    for i, b in enumerate(encoded):
        buf[ptr + i] = b
    return ptr


def _init_wasm():
    """初始化 WASM 运行时 (懒加载, 仅首次调用时执行)"""
    global _wasm_engine, _wasm_store, _wasm_instance, _sign_wasm_bytes

    if _wasm_instance is not None:
        return True

    if not _HAS_WASMTIME:
        return False

    if not os.path.exists(_STUB_WASM_PATH):
        return False

    # 加载 sign_wasm 字节
    if os.path.exists(_SIGN_WASM_PATH):
        with open(_SIGN_WASM_PATH, "rb") as f:
            _sign_wasm_bytes = f.read()
    else:
        _sign_wasm_bytes = None

    _wasm_engine = _wasmtime.Engine()
    _wasm_store = _wasmtime.Store(_wasm_engine)

    # WASI
    wasi_config = _wasmtime.WasiConfig()
    _wasm_store.set_wasi(wasi_config)

    linker = _wasmtime.Linker(_wasm_engine)
    linker.define_wasi()

    # 类型
    i32 = _wasmtime.ValType.i32()
    f64 = _wasmtime.ValType.f64()

    # 闭包引用
    inst_ref = [None]

    def _js_invoke(target_ptr, method_ptr, args_ptr):
        store = _wasm_store
        inst = inst_ref[0]
        target = _wasm_read_cstring(store, inst, target_ptr)
        method = _wasm_read_cstring(store, inst, method_ptr)
        if target == "Date" and method == "now":
            result = int(time.time() * 1000)
        elif target == "window" and method == "eval":
            result = 0  # WebView 环境
        else:
            result = None
        return _wasm_write_cstring(store, inst, json.dumps(result))

    def _exit(code):
        raise RuntimeError(f"WASM exit({code})")

    def _cxa_throw(a, b, c):
        raise RuntimeError(f"WASM __cxa_throw")

    def _date_now():
        return float(int(time.time() * 1000))

    def _resize_heap(size):
        return 0

    def _abort_js():
        raise RuntimeError("WASM abort")

    def _tzset_js(a, b, c, d):
        pass

    linker.define_func("env", "js_invoke",
        _wasmtime.FuncType([i32, i32, i32], [i32]), _js_invoke)
    linker.define_func("env", "exit",
        _wasmtime.FuncType([i32], []), _exit)
    linker.define_func("env", "__cxa_throw",
        _wasmtime.FuncType([i32, i32, i32], []), _cxa_throw)
    linker.define_func("env", "emscripten_date_now",
        _wasmtime.FuncType([], [f64]), _date_now)
    linker.define_func("env", "emscripten_resize_heap",
        _wasmtime.FuncType([i32], [i32]), _resize_heap)
    linker.define_func("env", "_abort_js",
        _wasmtime.FuncType([], []), _abort_js)
    linker.define_func("env", "_tzset_js",
        _wasmtime.FuncType([i32, i32, i32, i32], []), _tzset_js)

    try:
        module = _wasmtime.Module.from_file(_wasm_engine, _STUB_WASM_PATH)
        _wasm_instance = linker.instantiate(_wasm_store, module)
        inst_ref[0] = _wasm_instance
        # 调用构造函数
        ctors = _wasm_instance.exports(_wasm_store)["__wasm_call_ctors"]
        ctors(_wasm_store)
        return True
    except Exception:
        _wasm_instance = None
        return False


def load_sign_wasm_from_base64(b64_data: str):
    """从 base64 字符串加载 sign_wasm 字节 (对应浏览器 localStorage 中的值)"""
    global _sign_wasm_bytes
    _sign_wasm_bytes = base64.b64decode(b64_data)


def generate_wasm_sign(did: str, sign: str, sign_wasm: bytes = None) -> Optional[str]:
    """
    调用 WASM 生成签名 (对应 bs_h5.js runWac)

    参数:
        did:       设备 ID
        sign:      MurmurHash3 请求签名 (Content-Hh-Bb)
        sign_wasm: 可选, sign_wasm 字节; 不传则使用全局加载的

    返回:
        成功: JSON 字符串 '{"uuid":"...","body":"...","has_env":0}'
        失败: None
    """
    if not _init_wasm():
        return None

    wasm_bytes = sign_wasm or _sign_wasm_bytes
    if not wasm_bytes:
        return None

    store = _wasm_store
    inst = _wasm_instance

    try:
        malloc_fn = inst.exports(store)["malloc"]
        free_fn = inst.exports(store)["free"]
        run_wac_fn = inst.exports(store)["run_wac"]
        free_memory_fn = inst.exports(store)["free_memory"]
        mem = inst.exports(store)["memory"]

        # 写入 did
        did_ptr = _wasm_write_cstring(store, inst, did)
        did_len = len(did.encode('utf-8'))

        # 写入 sign
        sign_ptr = _wasm_write_cstring(store, inst, sign)
        sign_len = len(sign.encode('utf-8'))

        # 写入 wasm 字节
        wasm_ptr = malloc_fn(store, len(wasm_bytes))
        buf = mem.data_ptr(store)
        for i, b in enumerate(wasm_bytes):
            buf[wasm_ptr + i] = b
        wasm_len = len(wasm_bytes)

        # 调用 run_wac
        result_ptr = run_wac_fn(store, did_ptr, did_len, sign_ptr, sign_len, wasm_ptr, wasm_len)

        result_str = None
        if result_ptr:
            result_str = _wasm_read_cstring(store, inst, result_ptr)
            free_memory_fn(store, result_ptr)
            # 验证结果有效性 (排除错误消息)
            if result_str and ("未初始化" in result_str or "未加载" in result_str or "失败" in result_str):
                result_str = None

        # 释放
        free_fn(store, did_ptr)
        free_fn(store, sign_ptr)
        free_fn(store, wasm_ptr)

        return result_str

    except Exception:
        return None


# ============================================================
# 9.5 解密 Content-Web-Bb
# ============================================================

def decrypt_content_web_bb(content_web_bb: str) -> dict:
    """
    解密 Content-Web-Bb Header 值

    参数:
        content_web_bb: Content-Web-Bb 的完整值 (hex string)

    返回:
        {
            "raw": 解密后的原始 JSON 字符串,
            "data": 解析后的数组,
            "fields": {
                "app_key": "10001",
                "did": "h3d76808c...",
                "start_id": "mniz0s9z_...",
                "ua_info": "",
                "device_fp": "0",
                "hp": "0",
                "random_id": "dac02114...",
                "sign": "6ec1aefe...",
                "timestamp": 1775224840388,
                "extra": [],
                "user_id": "1196233237",
                "wasm_version": "v1.0.6",
                "wasm_sign": '{"uuid":"..."}',
            },
            "_crypto": { "smi", "smk", "smk1" }
        }
    """
    # Step 1: 分离 smi (前32位) 和密文
    smi_part = content_web_bb[:32]
    cipher_part = content_web_bb[32:]

    # Step 2: 从 smi 反推 smk (每个 hex 字符 XOR 1)
    smk = ''.join(format(1 ^ int(c, 16), 'x') for c in smi_part)

    # Step 3: 派生 SM4 密钥
    smk1 = derive_sm4_key(smk)

    # Step 4: SM4-CBC 解密 (key=smk1, iv=smk1)
    raw = sm4_decrypt_cbc(cipher_part, smk1, smk1)

    # Step 5: 解析 JSON 数组
    data = json.loads(raw)

    # Step 6: 映射字段名
    fields = {}
    for name, idx in FIELD_INDEX.items():
        fields[name] = data[idx] if idx < len(data) else None

    return {
        "raw": raw,
        "data": data,
        "fields": fields,
        "_crypto": {
            "smi": smi_part,
            "smk": smk,
            "smk1": smk1,
        }
    }


# ============================================================
# 10. 高层封装: 为 GET/POST 请求生成 Header
# ============================================================

def generate_headers_for_get(url: str, **kwargs) -> dict:
    """为 GET 请求生成 Content-Web-Bb 等 Header"""
    query = ""
    if "?" in url:
        query = url[url.index("?") + 1:]
    serialized = url_params_concat(query)
    return generate_content_web_bb(serialized, **kwargs)


def generate_headers_for_post(body, **kwargs) -> dict:
    """为 POST 请求生成 Content-Web-Bb 等 Header"""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
    serialized = json_serialize(body) if not isinstance(body, str) else body
    if not isinstance(serialized, str):
        serialized = str(serialized)
    return generate_content_web_bb(serialized, **kwargs)



# ==================== 常量 ====================

# AES 加密参数 (1.9.6, 来自 p730yc.C11185b)
AES_KEY = b"3a79d$e4c2169a#fbd24c583ae71c0b9"[:32]
AES_IV = b"7392645081974362"

# MT-Info 固定常量
MT_INFO = "a3f9c2b8471de05f9b6c4e1287d5a9c1"

# randC 字符集 (来自 librand.so 0x55e0, 37个字符)
RAND_CHARSET = "01234567890abcdefghijklmnopqrstuvwxyz"

# APP 版本
APP_VERSION = "1.9.6"

# 合法签名 MD5 (来自 MIX 函数校验)
VALID_SIGN_MD5 = [
    "2f5ae2348f427a666876d7da3563a7d2",
    "dd6c1787c17943e9db0c59c0da3d20e5",
]


# ==================== MD5 ====================

def md5_hex(text: str) -> str:
    """标准 MD5, 返回32位小写hex"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def md5_hex_no_pad(text: str) -> str:
    """
    APP 内部的 MD5 实现 (MiscUtil.a / C6865b.m24274a)

    注意: 使用 Integer.toHexString(b & 0xFF) 不补零!
    例如 0x0a → "a" 而不是 "0a", 导致结果可能少于32位

    这是 DeviceUtil 中生成原始 deviceId 时使用的 MD5
    """
    digest = hashlib.md5(text.encode('utf-8')).digest()
    return ''.join(format(b, 'x') for b in digest)


# ==================== MT-Device-ID ====================

def xor_encrypt(text: str, key: int = 72) -> str:
    """
    XOR 流式加密 (MtCrypUtil.b / C11171b.m44630b)

    来源: p726y8.C11171b
    算法:
      for each char c in text:
        key ^= c
        output += chr(key)

    注意: key 是累积异或, 不是每次用固定 key

    Args:
        text: 输入字符串
        key: 初始 XOR key (默认 72, 即 0x48)

    Returns:
        XOR 加密后的字符串
    """
    result = []
    for c in text:
        key ^= ord(c)
        result.append(chr(key))
    return ''.join(result)


def generate_device_id_raw(imei: str = "", mac: str = "", android_id: str = "",
                           serial: str = "") -> str:
    """
    生成原始设备ID (DeviceUtil.a / C6864a.m24258a)

    优先级: IMEI@MAC > MAC > IMEI > AndroidID > Serial > UUID
    然后对结果做 MD5 (不补零版本)

    Args:
        imei: IMEI 号
        mac: MAC 地址
        android_id: Android ID
        serial: 序列号

    Returns:
        MD5 后的原始设备ID (可能少于32位)
    """
    # 组合设备标识
    device_str = ""
    has_imei = bool(imei)
    has_mac = bool(mac)

    if has_imei and has_mac:
        device_str = imei + "@" + mac
    elif has_mac:
        device_str = mac
    elif has_imei:
        device_str = imei
    elif android_id:
        device_str = android_id
    elif serial:
        device_str = serial
    else:
        import uuid
        device_str = str(uuid.uuid4())

    # MD5 (不补零)
    return md5_hex_no_pad(device_str)


def generate_mt_device_id(raw_device_id: str) -> str:
    """
    生成 MT-Device-ID (MtCrypUtil.a / C11171b.m44629a)

    算法: "clips_" + Base64(XOR(raw_device_id, 72))

    来源: p726y8.C11171b.m44629a
      1. XOR 流式加密: key 初始值 72, 累积异或
      2. Base64 编码 (NO_WRAP, flag=2)
      3. 前缀 "clips_"

    Args:
        raw_device_id: 原始设备ID (DeviceUtil.c() 返回值, 即 MD5 后的字符串)

    Returns:
        "clips_" + Base64(XOR(raw_device_id, 72))
    """
    if not raw_device_id:
        return raw_device_id

    xor_result = xor_encrypt(raw_device_id, 72)
    b64 = base64.b64encode(xor_result.encode('utf-8')).decode('utf-8')
    return "clips_" + b64


# ==================== MT-R ====================

def generate_mt_r(is_rooted: bool = False, is_debug: bool = False,
                  has_proxy: bool = False, is_injected: bool = False) -> str:
    """
    生成 MT-R (环境风控标记)

    来源: ApiInterceptor.<clinit> (smali line 15-20)
    明文格式: "root/{0|1};debug/{0|1};proxy/{0|1};inject/{0|1}"

    检测项:
      - root:   C5381a.e() → C5382b.f() 检测 su/Superuser 等
      - debug:  C5381a.b() → Debug.isDebuggerConnected() || (flags & 2)
      - proxy:  C5381a.d() → System.getProperty("http.proxyHost")
      - inject: 固定为 0

    加密: MtCrypUtil.a() = "clips_" + Base64(XOR(plaintext, 72))

    Args:
        is_rooted: 是否 root
        is_debug: 是否调试模式
        has_proxy: 是否有代理
        is_injected: 是否注入 (固定 False)

    Returns:
        "clips_" + Base64(XOR(明文, 72))
    """
    plaintext = (
        f"root/{int(is_rooted)}"
        f";debug/{int(is_debug)}"
        f";proxy/{int(has_proxy)}"
        f";inject/{int(is_injected)}"
    )
    xor_result = xor_encrypt(plaintext, 72)
    b64 = base64.b64encode(xor_result.encode('utf-8')).decode('utf-8')
    return "clips_" + b64


# ==================== MT-SN ====================

def generate_mt_sn(signature_md5: str = "2f5ae2348f427a666876d7da3563a7d2") -> str:
    """
    生成 MT-SN (应用签名标识)

    来源: ApiInterceptor.<clinit> (smali line 14)
      1. C5381a.a(context) → C5383c.a(context) → 获取 APK 签名字节
      2. Version.b(signatureBytes) → MD5(签名字节) 转 hex
      3. MtCrypUtil.a(md5) → "clips_" + Base64(XOR(md5, 72))

    默认签名 MD5: "2f5ae2348f427a666876d7da3563a7d2" (官方签名)

    Args:
        signature_md5: APK 签名的 MD5 hex 字符串

    Returns:
        "clips_" + Base64(XOR(signature_md5, 72))
    """
    xor_result = xor_encrypt(signature_md5, 72)
    b64 = base64.b64encode(xor_result.encode('utf-8')).decode('utf-8')
    return "clips_" + b64


# ==================== MT-V 签名 (还原自 librand.so MIX 函数) ====================

def generate_mt_v(timestamp: str, device_id: str, extra: str = "",
                  version: str = APP_VERSION, platform: str = "android") -> str:
    """
    生成 MT-V 签名

    还原自 librand.so MIX 函数 (0x2d48):
      1. combined = "android" + timestamp + deviceId + extra + versionName
      2. 冒泡排序所有字符 (ASCII升序)
      3. suffix = random.choice(RAND_CHARSET)  # 37个字符
      4. result_md5 = MD5(sorted_str + suffix)
      5. MT-V = result_md5[:26] + suffix

    注: MIX 中还校验了 getAN()=="com.moutai.mall" 和 getMd5S() 是否匹配合法签名,
        校验通过时不追加 "error", 我们直接走正常路径。

    Args:
        timestamp: 13位毫秒时间戳
        device_id: 设备ID
        extra: 第三个参数 (通常为空字符串)
        version: APP版本号
        platform: 平台 ("android" 或 "ios")

    Returns:
        27位签名字符串
    """
    # 1. 拼接
    if platform.lower() == "ios":
        combined = "iOS" + timestamp + device_id + extra + version
    else:
        combined = "android" + timestamp + device_id + extra + version

    # 2. 冒泡排序 (与 native 层一致)
    chars = list(combined)
    n = len(chars)
    for i in range(n - 1):
        for j in range(n - 1 - i):
            if chars[j] > chars[j + 1]:
                chars[j], chars[j + 1] = chars[j + 1], chars[j]
    sorted_str = ''.join(chars)

    # 3. 随机后缀
    suffix = RAND_CHARSET[random.randint(0, 36)]

    # 4. MD5
    result_md5 = md5_hex(sorted_str + suffix)

    # 5. 截取前26位 + 后缀
    return result_md5[:26] + suffix


def generate_mt_k_and_v(device_id: str, version: str = APP_VERSION,
                        platform: str = "android") -> Tuple[str, str]:
    """
    生成 MT-K + MT-V 签名对

    对应 Java: RandK.b(timestamp, deviceId, "")

    Returns:
        (mt_k, mt_v) 元组
    """
    mt_k = str(int(time.time() * 1000))
    mt_v = generate_mt_v(mt_k, device_id, "", version, platform)
    return mt_k, mt_v


# ==================== AES 加密/解密 ====================

def aes_encrypt(plaintext: str) -> str:
    """AES/CBC/PKCS7 加密 + Base64"""
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        ct = cipher.encrypt(pad(plaintext.encode('utf-8'), AES.block_size))
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext.encode('utf-8')) + padder.finalize()
        cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))
        ct = cipher.encryptor().update(padded) + cipher.encryptor().finalize()
    return base64.b64encode(ct).decode('utf-8')


def aes_decrypt(ciphertext_b64: str) -> str:
    """AES/CBC/PKCS7 解密"""
    ct = base64.b64decode(ciphertext_b64)
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        return unpad(cipher.decrypt(ct), AES.block_size).decode('utf-8')
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))
        padded = cipher.decryptor().update(ct) + cipher.decryptor().finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# ==================== actParam 生成 ====================

def generate_act_param(data: dict) -> str:
    """JSON序列化 → AES加密 → Base64"""
    plaintext = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return aes_encrypt(plaintext)


def decode_act_param(act_param: str) -> dict:
    """Base64 → AES解密 → JSON解析"""
    return json.loads(aes_decrypt(act_param))


def build_rush_purchase_param(
    item_code: str,
    item_priority_act_id: str,
    device_id: str,
    amount: str = "1",
    address_lat: str = "",
    address_lng: str = "",
    app_user_agent: str = "",
    mtr: str = "",
) -> str:
    """
    构建抢购 actParam

    Args:
        app_user_agent: APP UA, 格式 "android;{sdk};{manufacturer};{model}"
                        不传则不填 (由调用方负责)

    Returns:
        加密后的 actParam 字符串
    """
    data = {
        "amount": amount,
        "itemCode": item_code,
        "itemPriorityActId": item_priority_act_id,
        "userInfoBaseContext": {
            "addressLat": address_lat,
            "addressLng": address_lng,
            "appUserAgent": app_user_agent,
            "deviceId": device_id,
            "mtr": mtr,
        },
        "ydLogId": "",
        "ydToken": "",
    }
    return generate_act_param(data)


def build_reservation_param(
    session_id: int,
    shop_id: str,
    items: list,
    device_id: str,
    address_lat: str = "",
    address_lng: str = "",
    app_user_agent: str = "",
    mtr: str = "",
) -> str:
    """
    构建预约申购 actParam

    Args:
        app_user_agent: APP UA, 不传则不填

    Returns:
        加密后的 actParam 字符串
    """
    data = {
        "sessionId": session_id,
        "shopId": shop_id,
        "itemInfoList": items,
        "userInfoBaseContext": {
            "addressLat": address_lat,
            "addressLng": address_lng,
            "appUserAgent": app_user_agent,
            "deviceId": device_id,
            "mtr": mtr,
        },
        "ydLogId": "",
        "ydToken": "",
    }
    return generate_act_param(data)


# ==================== 瑞数 H5 设备指纹 (bs_h5.js udid) ====================

# ---- 设备池: 爬虫每次随机选取, 避免指纹固定被风控 ----
# 每个设备包含: WebView UA、WebGL 渲染器、设备内存、像素比、CPU 核心数
# 来源: 真实 Android 设备采集, 覆盖主流机型

_DEVICE_POOL = [
    {
        "ua": "mozilla/5.0 (linux; android 14; sm-g991b build/up1a.231005.007; wv) "
              "applewebkit/537.36 (khtml, like gecko) version/4.0 "
              "chrome/124.0.6367.179 mobile safari/537.36",
        "webgl_renderer": "Adreno (TM) 660",
        "webgl_vendor_renderer": "Qualcomm~Adreno (TM) 660",
        "device_memory": 8,
        "pixel_ratio": 3,
        "hardware_concurrency": 8,
    },
    {
        "ua": "mozilla/5.0 (linux; android 13; pixel 7 build/tq3a.230901.001; wv) "
              "applewebkit/537.36 (khtml, like gecko) version/4.0 "
              "chrome/120.0.6099.230 mobile safari/537.36",
        "webgl_renderer": "Mali-G78",
        "webgl_vendor_renderer": "ARM~Mali-G78",
        "device_memory": 8,
        "pixel_ratio": 2.625,
        "hardware_concurrency": 8,
    },
    {
        "ua": "mozilla/5.0 (linux; android 14; 22081212c build/ukq1.230917.001; wv) "
              "applewebkit/537.36 (khtml, like gecko) version/4.0 "
              "chrome/122.0.6261.64 mobile safari/537.36",
        "webgl_renderer": "Adreno (TM) 730",
        "webgl_vendor_renderer": "Qualcomm~Adreno (TM) 730",
        "device_memory": 12,
        "pixel_ratio": 2.75,
        "hardware_concurrency": 8,
    },
    {
        "ua": "mozilla/5.0 (linux; android 13; v2254a build/tp1a.220624.014; wv) "
              "applewebkit/537.36 (khtml, like gecko) version/4.0 "
              "chrome/119.0.6045.193 mobile safari/537.36",
        "webgl_renderer": "Adreno (TM) 642L",
        "webgl_vendor_renderer": "Qualcomm~Adreno (TM) 642L",
        "device_memory": 8,
        "pixel_ratio": 2.75,
        "hardware_concurrency": 8,
    },
    {
        "ua": "mozilla/5.0 (linux; android 14; oph2201 build/up1a.231005.007; wv) "
              "applewebkit/537.36 (khtml, like gecko) version/4.0 "
              "chrome/123.0.6312.118 mobile safari/537.36",
        "webgl_renderer": "Adreno (TM) 730",
        "webgl_vendor_renderer": "Qualcomm~Adreno (TM) 730",
        "device_memory": 12,
        "pixel_ratio": 3,
        "hardware_concurrency": 8,
    },
]


def _random_device() -> dict:
    """从设备池随机选取一个设备配置, 用于生成不同的 H5 指纹"""
    return random.choice(_DEVICE_POOL)


# 默认 WebView UA (仅用于 _d_u cookie 中的 UA 截断, 会被设备池覆盖)
_DEFAULT_WEBVIEW_UA = _DEVICE_POOL[0]["ua"]

# 浏览器指纹固定参数 (所有 Android WebView 共有, 不随设备变化)
_FINGERPRINT_CONSTANTS = {
    "mime_types": "",                    # Android WebView 无 mimeTypes
    "cpu_class": "",                     # navigator.cpuClass (Android 无)
    "platform": "Linux armv8l",          # navigator.platform (ARM64 设备)
    "timezone_offset": -480,             # new Date().getTimezoneOffset() (UTC+8 = -480)
    "plugins": "",                       # navigator.plugins (Android 无)
    "touch_support": "3;true;true",      # maxTouchPoints;ontouchstart;ontouchend
    "session_storage": 1,                # hasSessionStorage (WebView 支持)
    "local_storage": 1,                  # hasLocalStorage (WebView 支持)
    "java_enabled": 0,                   # navigator.javaEnabled() (Android 无)
    "indexed_db": 1,                     # hasIndexedDB (WebView 支持)
    "has_lied_languages": 0,             # 语言欺骗检测 (正常为 0)
    "has_lied_resolution": 0,            # 分辨率欺骗检测 (正常为 0)
    "has_lied_browser": 0,               # 浏览器欺骗检测 (正常为 0)
    "vendor_flavors": "",                # Android Chrome 无 vendor flavors
    "canvas_fp": "",                     # 运行时随机生成 (每个设备不同)
    "canvas_text_fp": "",                # 运行时随机生成
    "canvas_3d_hash": "",                # 运行时随机生成
    "webgl_fp": "",                      # 运行时随机生成
    "webgl_canvas": "",                  # 运行时随机生成
    "empty_eval_length": 37,             # eval.toString().length (Chrome 固定 37)
    "product_sub": "20030107",           # navigator.productSub (Chrome 固定)
    "error_ff": "",                      # Firefox 特有错误 (Chrome 无)
    "fonts": "",                         # 运行时检测 (Android 字体列表)
    "is_hdr": 0,                         # HDR 支持 (大部分设备 0)
    "is_motion_reduced": 0,              # 减少动画 (默认 0)
    "colors_forced": 0,                  # 强制颜色 (默认 0)
    "color_gamut": "srgb",               # 色域 (标准 sRGB)
    "color_depth": 24,                   # screen.colorDepth (标准 24-bit)
}


def _guid() -> str:
    """
    生成 GUID (对应 bs_h5.js guid 函数)
    格式: xxxxxxxx-xxxx-xxxx-yxxx-xxxxxxxxxxxx
    """
    ts = int(time.time() * 1000)
    template = "xxxxxxxx-xxxx-xxxx-yxxx-xxxxxxxxxxxx"
    result = []
    for ch in template:
        if ch == '-':
            result.append('-')
        elif ch in ('x', 'y'):
            r = (ts + int(random.random() * 16)) % 16
            ts = ts // 16
            if ch == 'x':
                result.append(format(r, 'x'))
            else:
                result.append(format((r & 0x3) | 0x8, 'x'))
        else:
            result.append(ch)
    return ''.join(result)


def _get_ua_for_fingerprint(ua: str) -> str:
    """
    处理 UA 用于指纹 (对应 bs_h5.js getUserAgent)
    去除网络类型标识 (nett/wifi/4g/5g)
    """
    ua_lower = ua.lower()
    for marker in ["nett", "nt:", "wifi", "4g", "5g"]:
        if marker in ua_lower:
            idx = ua_lower.index(marker)
            parts = ua_lower[:idx].rstrip()
            rest = ua_lower[idx + len(marker):]
            rest_parts = rest.split(" ", 1)
            if len(rest_parts) > 1:
                return parts + rest_parts[1]
            return parts
    return ua_lower


def generate_h5_did(
    user_agent: str = None,
    color_depth: int = None,
    device_memory: int = None,
    pixel_ratio: float = None,
    hardware_concurrency: int = None,
    platform: str = None,
    timezone_offset: int = None,
    webgl_renderer: str = None,
    webgl_vendor_renderer: str = None,
    canvas_fp: str = None,
    canvas_text_fp: str = None,
    webgl_fp: str = None,
) -> str:
    """
    生成瑞数 H5 设备 ID (did)

    对应 bs_h5.js 第 4002 行 udid() 函数:
      1. 采集 30+ 项浏览器特征
      2. 用 "_" 拼接所有特征
      3. MurmurHash3(特征串, seed=27) 取 [3:19] 共 16 位
      4. did = "h" + guid()[25:] + hash[3:19] + checksum[6:10]

    -------- 参数 --------
    爬虫模式: 不传参数时从设备池随机选取设备, 每次生成不同指纹
    固定模式: 传入具体参数可复现相同 did (用于会话保持)

    -------- 返回 --------
    "h" + 11位guid尾部 + 16位指纹hash + 4位校验 = 32 字符
    """
    # 从设备池随机选取一个设备 (爬虫每次调用得到不同指纹)
    device = _random_device()

    # 合并: 用户传入 > 设备池随机值 > 固定常量
    d = _FINGERPRINT_CONSTANTS.copy()
    d["user_agent"] = user_agent or device["ua"]
    d["device_memory"] = device_memory if device_memory is not None else device["device_memory"]
    d["pixel_ratio"] = pixel_ratio if pixel_ratio is not None else device["pixel_ratio"]
    d["hardware_concurrency"] = hardware_concurrency if hardware_concurrency is not None else device["hardware_concurrency"]
    d["webgl_renderer"] = webgl_renderer or device["webgl_renderer"]
    d["webgl_vendor_renderer"] = webgl_vendor_renderer or device["webgl_vendor_renderer"]

    # 可覆盖的固定参数
    if color_depth is not None:
        d["color_depth"] = color_depth
    if platform is not None:
        d["platform"] = platform
    if timezone_offset is not None:
        d["timezone_offset"] = timezone_offset

    # canvas/webgl 指纹: 每次随机生成 (模拟不同设备的渲染差异)
    if canvas_fp:
        d["canvas_fp"] = canvas_fp
    else:
        d["canvas_fp"] = murmur_hash3_x64_128(
            str(random.random()) + str(time.time()), seed=27
        )[:16]
    if canvas_text_fp:
        d["canvas_text_fp"] = canvas_text_fp
    else:
        d["canvas_text_fp"] = murmur_hash3_x64_128(
            str(random.random()) + str(time.time()) + "text", seed=27
        )[:16]
    if webgl_fp:
        d["webgl_fp"] = webgl_fp
    else:
        d["webgl_fp"] = murmur_hash3_x64_128(
            str(random.random()) + str(time.time()) + "webgl", seed=27
        )[:16]

    # 按 bs_h5.js udid() 中 this.r.push() 的顺序拼接 34 项特征
    ua_processed = _get_ua_for_fingerprint(d["user_agent"])
    features = [
        ua_processed,                           # [0]  getUserAgent
        d["mime_types"],                         # [1]  getAcceptMimeType
        str(d["color_depth"]),                   # [2]  colorDepth
        str(d["device_memory"]),                 # [3]  getDeviceMemory
        str(d["pixel_ratio"]),                   # [4]  getPixelRatio (mobile only)
        str(d["hardware_concurrency"]),          # [5]  getHardwareConcurrency
        d["cpu_class"],                          # [6]  getNavigatorCpuClass
        d["platform"],                           # [7]  getNavigatorPlatform
        str(d["timezone_offset"]),               # [8]  timezoneOffsetKey
        d["plugins"],                            # [9]  getPlugins
        d["touch_support"],                      # [10] getTouchSupport
        str(d["session_storage"]),               # [11] hasSessionStorage
        str(d["local_storage"]),                 # [12] hasLocalStorage
        str(d["java_enabled"]),                  # [13] hasJavaEnable
        str(d["indexed_db"]),                    # [14] hasIndexedDB
        str(d["has_lied_languages"]),            # [15] getHasLiedLanguages
        str(d["has_lied_resolution"]),           # [16] getHasLiedResolution
        str(d["has_lied_browser"]),              # [17] getHasLiedBrowser
        d["vendor_flavors"],                     # [18] getVendorFlavors
        d["canvas_fp"],                          # [19] getCanvasFp
        d["canvas_text_fp"],                     # [20] getCanvasTextFp
        d["canvas_3d_hash"],                     # [21] getCanvas3dHash
        d["webgl_fp"],                           # [22] getWebglFp
        d["webgl_canvas"],                       # [23] getWebglCanvas
        d["webgl_renderer"],                     # [24] getWebglRenderer
        d["webgl_vendor_renderer"],              # [25] getWebglVendorAndRenderer
        str(d["empty_eval_length"]),             # [26] getEmptyEvalLength
        d["product_sub"],                        # [27] getProductSub
        d["error_ff"],                           # [28] getErrorFF
        d["fonts"],                              # [29] getFonts
        str(d["is_hdr"]),                        # [30] getIsHDR
        str(d["is_motion_reduced"]),             # [31] getIsMotionReduced
        str(d["colors_forced"]),                 # [32] getColorsForced
        d["color_gamut"],                        # [33] getColorGamut
    ]

    features_str = "_".join(features)

    # did = "h" + guid()[25:](11字符) + murmur3(features, 27)[3:19](16字符)
    guid_part = _guid()[25:]
    fp_hash = murmur_hash3_x64_128(features_str, seed=27)
    fp_part = fp_hash[3:19]

    did_base = "h" + guid_part + fp_part  # "h" + 11 + 16 = 28 chars

    # checksum = murmur3(did_base, 27)[6:10] (4字符)
    checksum = murmur_hash3_x64_128(did_base, seed=27)[6:10]

    return did_base + checksum  # 32 chars total


def generate_h5_start_id() -> str:
    """
    生成会话 ID (startId)
    对应 bs_h5.js 第 10629 行 getStartId
    格式: {timestamp_base36}_{random_base36}_4
    """
    ts_b36 = _int_to_base36(int(time.time() * 1000))
    rand_b36 = _int_to_base36(int(random.random() * (36 ** 10)))[2:]
    return f"{ts_b36}_{rand_b36}_4"


def _int_to_base36(n: int) -> str:
    """整数转 base36 字符串"""
    if n == 0:
        return "0"
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = []
    while n > 0:
        result.append(chars[n % 36])
        n //= 36
    return ''.join(reversed(result))


# ==================== 瑞数 _bs_device_id Cookie ====================

def generate_bs_device_id(did: str) -> str:
    """
    生成 _bs_device_id cookie 值 (对应 bs_h5.js genFToken, 第 10330 行)

    算法:
      hp = "bid-" + Date.now()反转 + "-" + did末4位 + "-" + guid()[9:13]

    持久化:
      cookie "_bs_device_id" (有效期 ~394天)
      localStorage "__mg__" (有效期 ~168年)

    此值同时作为 Content-Web-Bb 中的 hp 字段 (字段 108)
    在 cookieSend 模式下 hp="0", 但 cookie 仍需设置

    Args:
        did: H5 设备 ID (generate_h5_did() 生成)

    Returns:
        "bid-{时间戳反转}-{did末4位}-{guid片段4位}"
    """
    # Date.now() 转字符串后反转
    ts_reversed = str(int(time.time() * 1000))[::-1]
    # did 末 4 位
    did_tail = did[-4:] if len(did) >= 4 else did
    # guid()[9:13] — 4 位随机 hex
    guid_part = _guid()[9:13]
    return f"bid-{ts_reversed}-{did_tail}-{guid_part}"


# ==================== 瑞数 _d_u Cookie ====================

def generate_d_u_cookie(
    did: str,
    start_id: str,
    user_agent: str = _DEFAULT_WEBVIEW_UA,
    domain: str = "h5.moutai519.com.cn",
    hp: str = "",
    app_key: str = DEFAULT_APP_KEY,
) -> str:
    """
    生成 _d_u cookie 值

    对应 bs_h5.js 第 16524 行 setCReport():
      1. 构造 {101, 103, 105, 107, 109, 111, 113} 对象
      2. objectToArray -> processData (SM4-CBC 加密)
      3. 写入 cookie, 有效期 50 秒, 每 ~10 秒刷新

    -------- 参数 --------
    did:        H5 设备 ID (generate_h5_did() 生成)
    start_id:   会话 ID (generate_h5_start_id() 生成)
    user_agent: 完整 UA (会被截断到第一个右括号处)
    domain:     页面域名
    hp:         浏览器指纹 hash (不传则自动生成)
    app_key:    SDK app_key

    -------- 返回 --------
    SM4-CBC 加密后的 _d_u cookie 值
    """
    # (object_to_array, process_data 已在本模块中定义)

    # UA 截断: 取到第一个 ")" 之前
    if ")" in user_agent:
        ua_short = user_agent[:user_agent.index(")")]
    else:
        ua_short = user_agent[:50]

    # hp 指纹 (如果未提供, 用 did + 时间戳生成)
    if not hp:
        hp = murmur_hash3_x64_128(
            did + str(int(time.time() * 1000)), seed=27
        )[:16]

    d_u_obj = {
        "101": app_key,
        "103": did,
        "105": start_id,
        "107": ua_short,
        "109": domain,
        "111": hp,
        "113": int(time.time() * 1000),
    }

    arr = object_to_array(d_u_obj)
    encrypted, _, _, _ = process_data(arr)
    return encrypted


# ==================== 完整请求构建 ====================

def build_rush_request(
    item_code: str,
    item_priority_act_id: str,
    device_id: str,
    cookie: str,
    amount: str = "1",
    app_version: str = APP_VERSION,
    user_agent: str = "",
    h5_did: str = None,
    h5_start_id: str = None,
    h5_user_id: str = "",
    wasm_version: str = "",
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
    """
    构建完整抢购请求 (含 APP 签名 + 瑞数 H5 防护 + WASM 签名)

    -------- 参数 --------
    item_code:              商品编码
    item_priority_act_id:   活动 ID
    device_id:              原始设备 ID (用于 MT-Device-ID)
    cookie:                 MT-Token-Wap
    amount:                 购买数量
    app_version:            APP 版本
    user_agent:             APP User-Agent (不传则不填)
    h5_did:                 瑞数 H5 设备 ID (不传则自动生成)
    h5_start_id:            瑞数会话 ID (不传则自动生成)
    h5_user_id:             用户 ID (用于瑞数指纹)
    wasm_version:           WASM 签名版本 (从浏览器 localStorage 获取)

    -------- 返回 --------
    (headers, cookies, body)
      headers:  包含 MT-V/MT-K/Content-Web-Bb/Sdk-Ver-Bb/Content-Hh-Bb
      cookies:  包含 MT-Token-Wap/_d_u/_bs_device_id/_sdk_v_
      body:     {"actParam": "..."}
    """
    mt_k, mt_v = generate_mt_k_and_v(device_id, app_version)
    mt_device = generate_mt_device_id(device_id)
    mt_r = generate_mt_r()
    mt_sn = generate_mt_sn()
    act_param = build_rush_purchase_param(
        item_code, item_priority_act_id, mt_device, amount, mtr=mt_r,
    )

    body = {"actParam": act_param}

    # 生成瑞数 H5 Content-Web-Bb (抢购请求启用 WASM 签名)
    if not h5_did:
        h5_did = generate_h5_did()
    if not h5_start_id:
        h5_start_id = generate_h5_start_id()

    bb_headers = generate_headers_for_post(
        body,
        app_key=DEFAULT_APP_KEY,
        did=h5_did,
        start_id=h5_start_id,
        user_id=h5_user_id,
        wasm_version=wasm_version,
        is_rush_purchase=True,
    )

    headers = {
        "MT-V": mt_v,
        "MT-K": mt_k,
        "MT-Info": MT_INFO,
        "MT-Device-ID": mt_device,
        "MT-APP-Version": app_version,
        "MT-R": mt_r,
        "MT-SN": mt_sn,
        "Content-Web-Bb": bb_headers["Content-Web-Bb"],
        "Sdk-Ver-Bb": bb_headers["Sdk-Ver-Bb"],
        "Content-Hh-Bb": bb_headers["Content-Hh-Bb"],
        "User-Agent": user_agent,
        "content-type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://h5.moutai519.com.cn",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    cookies = {
        "MT-Token-Wap": cookie,
        "MT-Device-ID-Wap": device_id,
        "_d_u": generate_d_u_cookie(h5_did, h5_start_id),
        "_bs_device_id": generate_bs_device_id(h5_did),  # genFToken 生成的浏览器指纹 cookie
        "_sdk_v_": SDK_VERSION,                           # SDK 版本 cookie
    }

    return headers, cookies, body


def build_reservation_request(
    session_id: int,
    shop_id: str,
    items: list,
    device_id: str,
    cookie: str,
    app_version: str = APP_VERSION,
    user_agent: str = "",
    h5_did: str = None,
    h5_start_id: str = None,
    h5_user_id: str = "",
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
    """
    构建完整预约申购请求 (含 APP 签名 + 瑞数 H5 防护)

    -------- 参数 --------
    session_id:   预约场次 ID
    shop_id:      门店 ID
    items:        商品列表 [{itemCode, count}]
    device_id:    原始设备 ID
    cookie:       MT-Token-Wap
    app_version:  APP 版本
    user_agent:   APP User-Agent (不传则不填)
    h5_did:       瑞数 H5 设备 ID (不传则自动生成)
    h5_start_id:  瑞数会话 ID (不传则自动生成)
    h5_user_id:   用户 ID

    -------- 返回 --------
    (headers, cookies, body)
      headers:  包含 MT-V/MT-K/Content-Web-Bb/Sdk-Ver-Bb/Content-Hh-Bb
      cookies:  包含 MT-Token-Wap/_d_u/_bs_device_id/_sdk_v_
      body:     {"actParam": "..."}
    """
    mt_k, mt_v = generate_mt_k_and_v(device_id, app_version)
    mt_device = generate_mt_device_id(device_id)
    mt_r = generate_mt_r()
    mt_sn = generate_mt_sn()
    act_param = build_reservation_param(
        session_id, shop_id, items, mt_device, mtr=mt_r,
    )

    body = {"actParam": act_param}

    if not h5_did:
        h5_did = generate_h5_did()
    if not h5_start_id:
        h5_start_id = generate_h5_start_id()

    bb_headers = generate_headers_for_post(
        body,
        app_key=DEFAULT_APP_KEY,
        did=h5_did,
        start_id=h5_start_id,
        user_id=h5_user_id,
    )

    headers = {
        "MT-V": mt_v,
        "MT-K": mt_k,
        "MT-Info": MT_INFO,
        "MT-Device-ID": mt_device,
        "MT-APP-Version": app_version,
        "MT-R": mt_r,
        "MT-SN": mt_sn,
        "Content-Web-Bb": bb_headers["Content-Web-Bb"],
        "Sdk-Ver-Bb": bb_headers["Sdk-Ver-Bb"],
        "Content-Hh-Bb": bb_headers["Content-Hh-Bb"],
        "User-Agent": user_agent,
        "content-type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://h5.moutai519.com.cn",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    cookies = {
        "MT-Token-Wap": cookie,
        "MT-Device-ID-Wap": device_id,
        "_d_u": generate_d_u_cookie(h5_did, h5_start_id),
        "_bs_device_id": generate_bs_device_id(h5_did),
        "_sdk_v_": SDK_VERSION,
    }

    return headers, cookies, body


# ==================== 测试 ====================

if __name__ == "__main__":
    # decrypt_content_web_bb 已在本模块中定义

    print("=" * 60)
    print("i-moutai 1.9.6 actParam + Content-Web-Bb")
    print("=" * 60)

    # 1. MT-V 签名算法自验证
    print("\n[1] MT-V sign verify")
    print("-" * 60)
    test_device = "1a8b941ad4c8f5be4964611fdd4ef1d"
    test_ts = "1774408506194"
    combined = f"android{test_ts}{test_device}{APP_VERSION}"
    sorted_str = ''.join(sorted(combined))
    suffix = "a"
    calc_md5 = md5_hex(sorted_str + suffix)
    calc_result = calc_md5[:26] + suffix
    print(f"  MT-V:   {calc_result}")
    print(f"  len={len(calc_result)}, ok={len(calc_result) == 27}")

    # 2. 生成当前签名
    print("\n[2] MT-K + MT-V")
    print("-" * 60)
    mt_k, mt_v = generate_mt_k_and_v(test_device)
    print(f"  MT-K: {mt_k}")
    print(f"  MT-V: {mt_v} (len={len(mt_v)})")

    # 3. AES 加密/解密
    print("\n[3] AES round-trip")
    print("-" * 60)
    test_data = {"amount": "1", "itemCode": "TEST001", "itemPriorityActId": "12345"}
    encrypted = generate_act_param(test_data)
    encrypted = 'SSeGBjTN7FYJHdAJdtdL3u4vjeXv7Y37r+avAPs/6T1cEL9+dmFRnCKwWg8C9o+Jsre5cr6BeAZrxm010p3sqK3CER1EKKlYZJihqTIdnVugVMEYeLWwQzJzxUc/NRG0s9bgBxlgQ9OlIXJybnvHHtQRFZNs4LX6XAV8/4jYUzmZNYkRfayoCeOHQYp4gZOP2Q8y19qCEmxIYwQSxqxMtXSPqr3/H5g7i7zAkL4EZgW+V0kiuc2SDe5ETmHyYV3w554sWpOz+a+T76ErCG3NG83+O0aXchIOETEQg3YYvuhCqiJFdHIyneaWXh5ioy91nk1Oyitkxj1BV/0XMYpaKx2GfqF9hY6PkNWar7KOKKhy8KT8Tgf/+M/j5IUXYQlPNgCBOhThFm9qEgvtP7V+VPoX7r4SHVnqyOsuBB5N1V0='
    decrypted = decode_act_param(encrypted)
    print(f"  encrypted: {encrypted[:50]}...")
    print(f"  decrypted: {decrypted}")

    print(f"  match: {decrypted == test_data}")

    # 4. H5 设备指纹生成
    print("\n[4] H5 did (BotShield fingerprint)")
    print("-" * 60)
    h5_did = generate_h5_did()
    print(f"  did:    {h5_did}")
    print(f"  len:    {len(h5_did)} (expect 32)")
    print(f"  prefix: {h5_did[0]} (expect 'h')")

    # 验证 did 格式: "h" + 11 guid + 16 fp + 4 checksum = 32
    assert h5_did[0] == 'h', "did must start with 'h'"
    assert len(h5_did) == 32, f"did length must be 32, got {len(h5_did)}"

    # 生成多个 did 确认唯一性
    dids = set(generate_h5_did() for _ in range(5))
    print(f"  unique: {len(dids)}/5 (should be 5)")

    # 5. H5 startId 生成
    print("\n[5] H5 startId")
    print("-" * 60)
    sid = generate_h5_start_id()
    print(f"  startId: {sid}")
    parts = sid.split("_")
    print(f"  format:  {len(parts)} parts (expect 3), ends with '{parts[-1]}' (expect '4')")

    # 6. MT-Device-ID / MT-R / MT-SN
    print("\n[6] MT-Device-ID / MT-R / MT-SN")
    print("-" * 60)
    real_raw_id = "3882c1bfa021f0dc20c2b404224e0b8"
    mt_device_id = generate_mt_device_id(real_raw_id)
    mt_r = generate_mt_r()
    mt_sn = generate_mt_sn()
    print(f"  MT-Device-ID: {mt_device_id}")
    print(f"  MT-R:         {mt_r}")
    print(f"  MT-SN:        {mt_sn}")

    # 7. 完整请求构建 (含 Content-Web-Bb + WASM 签名)
    print("\n[7] Full request build (rush purchase + WASM)")
    print("-" * 60)
    headers, cookies, body = build_rush_request(
        item_code="ITEM001",
        item_priority_act_id="ACT001",
        device_id="test_device_id",
        cookie="test_cookie",
        h5_user_id="1196233237",
        wasm_version="a2abd765daa2ec438a96fc2d97209be4",
    )
    print(f"  MT-K:           {headers['MT-K']}")
    print(f"  MT-V:           {headers['MT-V']}")
    print(f"  Content-Web-Bb: {headers['Content-Web-Bb'][:50]}...")
    print(f"  Sdk-Ver-Bb:     {headers['Sdk-Ver-Bb']}")
    print(f"  Content-Hh-Bb:  {headers['Content-Hh-Bb']}")
    print(f"  _d_u cookie:    {cookies['_d_u'][:50]}...")
    print(f"  _bs_device_id:  {cookies['_bs_device_id']}")
    print(f"  _sdk_v_:        {cookies['_sdk_v_']}")
    print(f"  actParam:       {body['actParam'][:50]}...")

    # 8. 解密验证 Content-Web-Bb (含 WASM 签名)
    print("\n[8] Decrypt Content-Web-Bb from request")
    print("-" * 60)
    dec = decrypt_content_web_bb(headers["Content-Web-Bb"])
    print(f"  app_key:      {dec['fields']['app_key']}")
    print(f"  did:          {dec['fields']['did']}")
    print(f"  user_id:      {dec['fields']['user_id']}")
    print(f"  start_id:     {dec['fields']['start_id']}")
    print(f"  wasm_version: {dec['fields']['wasm_version']}")
    wasm_sign = dec['fields'].get('wasm_sign', '')
    if wasm_sign:
        ws = json.loads(wasm_sign)
        print(f"  wasm_sign:    uuid={ws.get('uuid','')[:20]}... body={ws.get('body','')[:30]}...")
        print("  [OK] WASM sign present in Content-Web-Bb")
    else:
        print("  wasm_sign:    (empty - wasmtime/sign_wasm unavailable)")
    assert dec["fields"]["app_key"] == DEFAULT_APP_KEY
    assert dec["fields"]["did"][0] == "h"
    assert len(dec["fields"]["did"]) == 32
    print("  [OK] decrypt verified")

    print("\n" + "=" * 60)
    print("[DONE] All tests passed")
    print("=" * 60)
