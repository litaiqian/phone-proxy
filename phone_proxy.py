#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手机端 SOCKS5 代理服务器 (Termux 常驻)
- 监听 0.0.0.0:10808 提供 SOCKS5 代理
- 通过 Tailscale 组网，外网 C/S 均可直连此端口
- 自动获取 Tailscale IP 并注册到服务端
- 每 30 秒发送心跳保持在线

依赖（仅标准库 + requests）:
  pip install requests
"""

import socket
import struct
import threading
import time
import json
import os
import sys
import subprocess
import requests

# ==================== 配置 ====================
SERVER_URL = os.environ.get('MT_SERVER', 'http://ipla.top:5000')
API_TOKEN = os.environ.get('MT_TOKEN', 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd')
PROXY_PORT = int(os.environ.get('MT_PROXY_PORT', '10808'))
BIND_HOST = '0.0.0.0'
HEARTBEAT_INTERVAL = 30  # 秒

# 手机标识
PHONE_NAME = os.environ.get('MT_NAME', '') or socket.gethostname()


def log(msg):
    ts = time.strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def get_tailscale_ip():
    """获取本机 Tailscale IP (100.x.x.x)"""
    try:
        r = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=5)
        ip = r.stdout.strip()
        if ip:
            return ip
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f'[Tailscale] 获取IP失败: {e}')

    # 备用：通过 ifconfig/ip 查找 tailscale0 接口
    try:
        r = subprocess.run(['ip', '-4', 'addr', 'show', 'tailscale0'], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split('\n'):
            if 'inet ' in line:
                ip = line.strip().split()[1].split('/')[0]
                if ip.startswith('100.'):
                    return ip
    except Exception:
        pass

    return ''


def register_with_server(tailscale_ip, port):
    """向服务端注册手机代理"""
    try:
        proxy_addr = 'socks5://{}:{}'.format(tailscale_ip, port)
        resp = requests.post(
            '{}/api/phone_proxy/register'.format(SERVER_URL),
            headers={'X-API-TOKEN': API_TOKEN},
            json={
                'proxy_addr': proxy_addr,
                'name': PHONE_NAME,
                'tailscale_ip': tailscale_ip,
                'port': port,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get('status') == 'success':
            proxy_id = data.get('proxy_id', 0)
            log('[注册] 服务端已记录 | ID={} | {}'.format(proxy_id, proxy_addr))
            return proxy_id
        else:
            log('[注册] 服务端拒绝: {}'.format(data.get('message', resp.text[:100])))
            return 0
    except Exception as e:
        log('[注册] 连接失败: {}'.format(e))
        return 0


def heartbeat(proxy_id):
    """发送心跳"""
    try:
        resp = requests.post(
            '{}/api/phone_proxy/heartbeat'.format(SERVER_URL),
            headers={'X-API-TOKEN': API_TOKEN},
            json={'proxy_id': proxy_id},
            timeout=5,
        )
    except Exception:
        pass


class SOCKS5Proxy:
    """极简 SOCKS5 代理服务器（仅 CONNECT，无认证）"""

    def __init__(self, host='0.0.0.0', port=10808):
        self.host = host
        self.port = port
        self._running = False

    def start(self):
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(256)
        sock.settimeout(1)
        log('[SOCKS5] 监听 {}:{}'.format(self.host, self.port))
        while self._running:
            try:
                client, addr = sock.accept()
                t = threading.Thread(target=self._handle, args=(client, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log('[SOCKS5] accept 异常: {}'.format(e))
        sock.close()

    def stop(self):
        self._running = False

    def _handle(self, client, addr):
        try:
            client.settimeout(30)
            # 握手: 读取支持的认证方式
            ver, nmethods = struct.unpack('!BB', self._recv_exact(client, 2))
            if ver != 5:
                client.close()
                return
            methods = self._recv_exact(client, nmethods)
            # 选择无认证 (0x00)
            client.sendall(b'\x05\x00')

            # 请求: 读取目标地址
            data = self._recv_exact(client, 4)
            ver, cmd, rsv, atyp = struct.unpack('!BBBB', data)
            if ver != 5 or cmd != 1:  # 仅支持 CONNECT
                client.sendall(b'\x05\x07\x00\x01' + b'\x00' * 6)
                client.close()
                return

            # 解析目标地址
            if atyp == 1:  # IPv4
                dst_addr = socket.inet_ntoa(self._recv_exact(client, 4))
            elif atyp == 3:  # 域名
                length = self._recv_exact(client, 1)[0]
                dst_addr = self._recv_exact(client, length).decode()
            elif atyp == 4:  # IPv6
                dst_addr = socket.inet_ntop(socket.AF_INET6, self._recv_exact(client, 16))
            else:
                client.sendall(b'\x05\x08\x00\x01' + b'\x00' * 6)
                client.close()
                return

            dst_port = struct.unpack('!H', self._recv_exact(client, 2))[0]

            # 连接目标
            try:
                remote = socket.create_connection((dst_addr, dst_port), timeout=10)
            except Exception:
                client.sendall(b'\x05\x04\x00\x01' + b'\x00' * 6)
                client.close()
                return

            # 回复成功
            bind_addr = b'\x00' * 4
            bind_port = struct.pack('!H', 0)
            client.sendall(b'\x05\x00\x00\x01' + bind_addr + bind_port)

            # 双向转发
            self._relay(client, remote)

        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _recv_exact(sock, n):
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError('连接断开')
            data += chunk
        return data

    @staticmethod
    def _relay(a, b):
        """双向转发"""
        def _pipe(src, dst):
            try:
                while True:
                    data = src.recv(8192)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
        t1 = threading.Thread(target=_pipe, args=(a, b), daemon=True)
        t2 = threading.Thread(target=_pipe, args=(b, a), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)


def main():
    log('=' * 50)
    log('手机代理服务器启动中...')
    log('服务端: {}'.format(SERVER_URL))
    log('代理端口: {}'.format(PROXY_PORT))
    log('=' * 50)

    # 获取 Tailscale IP
    tailscale_ip = get_tailscale_ip()
    if not tailscale_ip:
        log('[错误] 未检测到 Tailscale IP！请先安装并启动 Tailscale')
        log('  安装: curl -fsSL https://tailscale.com/install.sh | sh')
        log('  启动: tailscale up')
        sys.exit(1)
    log('[Tailscale] 本机IP: {}'.format(tailscale_ip))

    # 注册到服务端
    proxy_id = register_with_server(tailscale_ip, PROXY_PORT)
    if not proxy_id:
        log('[警告] 注册失败，重试中...')
        for i in range(3):
            time.sleep(5)
            proxy_id = register_with_server(tailscale_ip, PROXY_PORT)
            if proxy_id:
                break
    if not proxy_id:
        log('[错误] 无法注册到服务端，退出')
        sys.exit(1)

    # 启动 SOCKS5 代理
    proxy = SOCKS5Proxy(BIND_HOST, PROXY_PORT)
    proxy_thread = threading.Thread(target=proxy.start, daemon=True)
    proxy_thread.start()

    # 心跳循环
    log('[心跳] 已启动，每30秒上报')
    try:
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            heartbeat(proxy_id)
    except KeyboardInterrupt:
        log('[退出] 收到中断信号')
        proxy.stop()
        sys.exit(0)


if __name__ == '__main__':
    main()
