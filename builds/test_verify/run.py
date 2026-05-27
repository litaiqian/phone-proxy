#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AES 加密启动器 — 运行时解密并执行"""
import sys, os, types

_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_HEX = "c6d5d7f760f05e4ab7cbdb5ddaf1482f62a65043801497bd16aabfbc82ef79d4"

def _key():
    return bytes.fromhex(_KEY_HEX)

def _load(mod_name, enc_name):
    from Crypto.Cipher import AES
    with open(f'{_DIR}/{enc_name}', 'rb') as f:
        nonce = f.read(12)          # AES-GCM recommended nonce length
        tag = f.read(16)            # GCM tag is always 16 bytes
        ct = f.read()
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    plain = cipher.decrypt_and_verify(ct, tag)
    code = compile(plain, f'<{mod_name}>', 'exec')
    mod = types.ModuleType(mod_name)
    mod.__file__ = f'{_DIR}/{enc_name}'
    sys.modules[mod_name] = mod
    exec(code, mod.__dict__)
    return mod

_ = _load('crypto', 'crypto.enc')
_ = _load('demo', 'demo.enc')
_ = _load('_security_bodies', 'security.enc')
_ = _load('nurture_account', 'nurture.enc')
worker = _load('moutai_client_worker', 'worker.enc')

if __name__ == '__main__' and hasattr(worker, 'main'):
    worker.main()
