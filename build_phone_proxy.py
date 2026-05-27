#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手机代理客户端打包工具
支持两种模式:
  1. AES 加密 Termux 模式 → phone_proxy_aes.zip
  2. APK 项目导出模式 → phone_proxy_apk_project.zip (传到 Linux 编译 APK)

用法:
  python build_phone_proxy.py --mode aes
  python build_phone_proxy.py --mode apk --server http://ipla.top:5000
"""

import os, sys, tempfile, zipfile, shutil, time

BASEDIR = os.path.dirname(os.path.abspath(__file__))
BUILDS_DIR = os.path.join(BASEDIR, 'builds')
SOURCE_FILE = os.path.join(BASEDIR, 'phone_proxy.py')
APK_APP_DIR = os.path.join(BASEDIR, 'phone_proxy_app')


def build_aes(server_url='http://ipla.top:5000',
              token='m9Xk2vLp7Qr4Wn8YbT1cFh6Jd',
              proxy_port=10808) -> str:
    """AES-256-GCM 加密 phone_proxy.py，返回 zip 路径"""

    os.makedirs(BUILDS_DIR, exist_ok=True)
    zip_path = os.path.join(BUILDS_DIR, 'phone_proxy_aes.zip')

    if not os.path.exists(SOURCE_FILE):
        print(f'[错误] 源文件不存在: {SOURCE_FILE}')
        return ''

    build_dir = tempfile.mkdtemp(prefix='phone_proxy_build_')

    try:
        # 1. 读取源码并注入配置
        with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
            source = f.read()
        source = source.replace(
            'SERVER_URL = os.environ.get(\'MT_SERVER\', \'http://ipla.top:5000\')',
            f'SERVER_URL = os.environ.get(\'MT_SERVER\', \'{server_url}\')')
        source = source.replace(
            'API_TOKEN = os.environ.get(\'MT_TOKEN\', \'m9Xk2vLp7Qr4Wn8YbT1cFh6Jd\')',
            f'API_TOKEN = os.environ.get(\'MT_TOKEN\', \'{token}\')')
        source = source.replace(
            'PROXY_PORT = int(os.environ.get(\'MT_PROXY_PORT\', \'10808\'))',
            f'PROXY_PORT = int(os.environ.get(\'MT_PROXY_PORT\', \'{proxy_port}\'))')

        src_path = os.path.join(build_dir, 'phone_proxy.py')
        with open(src_path, 'w', encoding='utf-8') as f:
            f.write(source)
        print(f'[AES] 配置已注入 (server={server_url})')

        # 2. 生成随机 AES-256 密钥
        key = os.urandom(32)
        key_hex = key.hex()

        # 3. 加密为 proxy.enc
        from Crypto.Cipher import AES as AESCipher
        with open(src_path, 'rb') as f:
            plain = f.read()
        cipher = AESCipher.new(key, AESCipher.MODE_GCM)
        ciphertext, tag = cipher.encrypt_and_digest(plain)
        enc_path = os.path.join(build_dir, 'proxy.enc')
        with open(enc_path, 'wb') as f:
            f.write(cipher.nonce)   # 12 bytes
            f.write(tag)            # 16 bytes
            f.write(ciphertext)
        os.remove(src_path)  # 删除明文
        print('[AES] phone_proxy.py → proxy.enc 已加密')

        # 4. 生成 run.py 启动器（hex 密钥嵌入）
        run_py = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AES 加密启动器 — 运行时解密并执行手机代理"""
import sys, os, types

_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_HEX = "{key_hex}"

def _key():
    return bytes.fromhex(_KEY_HEX)

def _load():
    from Crypto.Cipher import AES
    with open(f'{{_DIR}}/proxy.enc', 'rb') as f:
        nonce, tag, ct = f.read(12), f.read(16), f.read()
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    plain = cipher.decrypt_and_verify(ct, tag)
    code = compile(plain, '<phone_proxy>', 'exec')
    mod = types.ModuleType('phone_proxy')
    sys.modules['phone_proxy'] = mod
    exec(code, mod.__dict__)
    return mod

phone_proxy = _load()

if __name__ == '__main__' and hasattr(phone_proxy, 'main'):
    phone_proxy.main()
'''
        run_path = os.path.join(build_dir, 'run.py')
        with open(run_path, 'w', encoding='utf-8') as f:
            f.write(run_py)
        print('[AES] run.py 启动器已生成（密钥嵌入）')

        # 5. ZIP 打包
        print('[AES] ZIP打包中...')
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fname in ['run.py', 'proxy.enc']:
                fpath = os.path.join(build_dir, fname)
                if os.path.exists(fpath):
                    zf.write(fpath, fname)
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f'[AES] 成功: phone_proxy_aes.zip ({zip_mb:.1f}MB)')

        return zip_path

    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def build_apk_project(server_url='http://ipla.top:5000',
                     token='m9Xk2vLp7Qr4Wn8YbT1cFh6Jd',
                     proxy_port=10808) -> str:
    """导出 APK 编译项目 ZIP，上传到 Linux 后运行 build_apk.sh 编译 APK"""

    os.makedirs(BUILDS_DIR, exist_ok=True)
    zip_path = os.path.join(BUILDS_DIR, 'phone_proxy_apk_project.zip')

    if not os.path.isdir(APK_APP_DIR):
        print(f'[错误] APK 项目目录不存在: {APK_APP_DIR}')
        return ''

    build_dir = tempfile.mkdtemp(prefix='phone_proxy_apk_')

    try:
        # 1. 复制 APK 项目文件
        shutil.copytree(APK_APP_DIR, build_dir, dirs_exist_ok=True)

        # 2. 注入服务端配置到 main.py
        main_py = os.path.join(build_dir, 'main.py')
        with open(main_py, 'r', encoding='utf-8') as f:
            source = f.read()

        # 注入配置（硬编码进 APK，无需环境变量）
        source = source.replace(
            "SERVER_HOST = 'ipla.top'",
            f"SERVER_HOST = '{server_url.replace('http://', '').split(':')[0]}'")  # 提取域名
        source = source.replace(
            "SERVER_PORT = 5000",
            f"SERVER_PORT = {server_url.split(':')[-1] if ':' in server_url.replace('http://', '') else 5000}")  # 提取端口

        with open(main_py, 'w', encoding='utf-8') as f:
            f.write(source)
        print(f'[APK] 配置已注入 (server={server_url})')

        # 3. 同步注入 build_apk.sh（使一键编译无需再配环境变量）
        build_sh = os.path.join(build_dir, 'build_apk.sh')
        if os.path.exists(build_sh):
            with open(build_sh, 'r', encoding='utf-8') as f:
                sh = f.read()
            sh = sh.replace(
                'SERVER="${MT_SERVER:-http://ipla.top:5000}"',
                f'SERVER="{server_url}"')
            sh = sh.replace(
                'TOKEN="${MT_TOKEN:-m9Xk2vLp7Qr4Wn8YbT1cFh6Jd}"',
                f'TOKEN="{token}"')
            sh = sh.replace(
                'PORT="${MT_PROXY_PORT:-10808}"',
                f'PORT="{proxy_port}"')
            with open(build_sh, 'w', encoding='utf-8') as f:
                f.write(sh)
            print('[APK] build_apk.sh 配置已注入')

        # 4. ZIP 打包
        print('[APK] ZIP打包中...')
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(build_dir):
                # 跳过 .buildozer 目录（如果有残留）
                dirs[:] = [d for d in dirs if d != '.buildozer']
                for fname in files:
                    full = os.path.join(root, fname)
                    arcname = os.path.relpath(full, build_dir)
                    zf.write(full, arcname)
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f'[APK] 成功: phone_proxy_apk_project.zip ({zip_mb:.1f}MB)')

        return zip_path

    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='手机代理客户端打包工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
模式说明:
  aes   → AES-256-GCM 加密，产出 phone_proxy_aes.zip
          手机用 Termux 运行 (python run.py)

  apk   → 导出 APK 编译项目，产出 phone_proxy_apk_project.zip
          上传到 Linux 服务器后运行 build_apk.sh 编译 APK
          手机安装 APK 即用，无需任何配置

示例:
  python build_phone_proxy.py --mode aes
  python build_phone_proxy.py --mode apk --server http://ipla.top:5000
        '''
    )
    parser.add_argument('--mode', default='aes', choices=['aes', 'apk'], help='打包模式')
    parser.add_argument('--server', default='http://ipla.top:5000', help='服务端地址')
    parser.add_argument('--token', default='m9Xk2vLp7Qr4Wn8YbT1cFh6Jd', help='API Token')
    parser.add_argument('--port', type=int, default=10808, help='SOCKS5 代理端口')
    args = parser.parse_args()

    if args.mode == 'apk':
        path = build_apk_project(args.server, args.token, args.port)
        if path:
            print(f'\n[OK] APK 项目: {path}')
            print(f'')
            print(f'下一步 → 在 Linux 上编译 APK:')
            print(f'  1. 上传 phone_proxy_apk_project.zip 到 Linux 服务器')
            print(f'  2. unzip phone_proxy_apk_project.zip && cd phone_proxy_apk_project')
            print(f'  3. chmod +x build_apk.sh && ./build_apk.sh')
            print(f'  4. 获取 bin/*.apk，安装到所有手机')
        else:
            print('\n[FAIL] APK 项目导出失败')
            sys.exit(1)
    else:
        path = build_aes(args.server, args.token, args.port)
        if path:
            print(f'\n[OK] 产物: {path}')
            print(f'部署到手机 (Termux):')
            print(f'  1. 解压 phone_proxy_aes.zip 到 Termux')
            print(f'  2. pip install pycryptodome requests')
            print(f'  3. python run.py')
        else:
            print('\n[FAIL] 打包失败')
            sys.exit(1)
