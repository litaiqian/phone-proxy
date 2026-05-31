#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手机代理 WS 隧道管理器（服务端）
- 管理手机 WebSocket 连接
- 为每台手机创建本地 SOCKS5 端口
- 客户端通过 socks5://服务器IP:本地端口 → WS → 手机 → 目标
"""

import asyncio
import socket
import struct
import threading
import time
import json
import uuid

# 手机隧道端口范围
TUNNEL_PORT_START = 10810
TUNNEL_PORT_END = 10900


class PhoneTunnel:
    """单个手机的隧道"""
    def __init__(self, tunnel_id: str, ws, name: str = ''):
        self.tunnel_id = tunnel_id
        self.ws = ws                          # WebSocket 连接
        self.name = name
        self.local_port = 0                    # 服务端本地 SOCKS5 端口
        self.status = 'connecting'
        self.last_heartbeat = time.time()
        self.active_connections = 0
        self._server_sock = None
        self._running = False
        self._pending = {}                     # {tunnel_id: asyncio.Event}
        self._resp_data = {}                   # {tunnel_id: bytes}

    def start_socks5(self, port: int):
        """在服务端启动本地 SOCKS5 代理，流量通过 WS 隧道转发到手机"""
        self.local_port = port
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', port))
        sock.listen(64)
        sock.settimeout(1)
        self._server_sock = sock

        def _accept_loop():
            while self._running:
                try:
                    client, addr = sock.accept()
                    self.active_connections += 1
                    t = threading.Thread(target=self._handle_socks5,
                                         args=(client, addr), daemon=True)
                    t.start()
                except socket.timeout:
                    continue
                except Exception:
                    if self._running:
                        break
            try:
                sock.close()
            except Exception:
                pass

        t = threading.Thread(target=_accept_loop, daemon=True)
        t.start()

    def stop(self):
        self._running = False
        try:
            self._server_sock.close()
        except Exception:
            pass

    def _handle_socks5(self, client, addr):
        """处理 SOCKS5 请求 → WS 隧道 → 手机"""
        remote_sock = None
        try:
            client.settimeout(30)
            # SOCKS5 握手
            ver, nmethods = struct.unpack('!BB', _recv_exact(client, 2))
            if ver != 5:
                client.close()
                return
            _recv_exact(client, nmethods)
            client.sendall(b'\x05\x00')

            # SOCKS5 请求
            data = _recv_exact(client, 4)
            ver, cmd, rsv, atyp = struct.unpack('!BBBB', data)
            if ver != 5 or cmd != 1:
                client.sendall(b'\x05\x07\x00\x01' + b'\x00' * 6)
                client.close()
                return

            if atyp == 1:  # IPv4
                dst_addr = socket.inet_ntoa(_recv_exact(client, 4))
            elif atyp == 3:  # 域名
                length = _recv_exact(client, 1)[0]
                dst_addr = _recv_exact(client, length).decode()
            elif atyp == 4:  # IPv6
                dst_addr = socket.inet_ntop(socket.AF_INET6, _recv_exact(client, 16))
            else:
                client.sendall(b'\x05\x08\x00\x01' + b'\x00' * 6)
                client.close()
                return

            dst_port = struct.unpack('!H', _recv_exact(client, 2))[0]

            # === 通过 WS 隧道让手机连接目标 ===
            tid = uuid.uuid4().hex[:12]
            event = asyncio.Event()
            self._pending[tid] = event

            # 发送连接请求到手机
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                self.ws.send_json({
                    'type': 'connect',
                    'tunnel_id': tid,
                    'host': dst_addr,
                    'port': dst_port,
                }), loop
            )

            # 等待手机确认连接（超时 8 秒）
            if not event.wait(8):
                client.sendall(b'\x05\x04\x00\x01' + b'\x00' * 6)
                client.close()
                return

            # 连接成功，回复客户端
            client.sendall(b'\x05\x00\x00\x01' + b'\x00' * 4 + struct.pack('!H', 0))

            # 双向转发：客户端 ↔ WS ↔ 手机
            self._relay_socks5(client, tid)

        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass
            self.active_connections = max(0, self.active_connections - 1)

    def _relay_socks5(self, client, tid):
        """客户端 ↔ WS 双向转发"""
        running = {'v': True}

        def _client_to_ws():
            """客户端 → WS → 手机"""
            try:
                while running['v']:
                    data = client.recv(8192)
                    if not data:
                        break
                    loop = asyncio.get_event_loop()
                    asyncio.run_coroutine_threadsafe(
                        self.ws.send_bytes(b'T' + tid.encode() + data),
                        loop
                    )
            except Exception:
                pass
            running['v'] = False

        t = threading.Thread(target=_client_to_ws, daemon=True)
        t.start()

        # 主线程：等待 WS 响应数据
        try:
            while running['v']:
                # WS 数据由 on_message 回调写入 _resp_data
                time.sleep(0.05)
                key = tid
                if key in self._resp_data:
                    data = self._resp_data.pop(key)
                    if data == b'__CLOSE__':
                        break
                    client.sendall(data)
        except Exception:
            pass
        running['v'] = False

    def on_ws_data(self, raw: bytes):
        """处理来自手机 WS 的数据（tunnel_id + data）"""
        if len(raw) < 13:
            # 心跳/控制消息
            try:
                msg = json.loads(raw.decode())
                if msg.get('type') == 'pong':
                    self.last_heartbeat = time.time()
                elif msg.get('type') == 'connected':
                    tid = msg.get('tunnel_id', '')
                    if tid in self._pending:
                        self._pending[tid].set()
                elif msg.get('type') == 'error':
                    tid = msg.get('tunnel_id', '')
                    if tid in self._pending:
                        self._pending[tid].set()  # 也触发（错误也解除等待）
            except Exception:
                pass
            return

        # 数据帧：T{tunnel_id:12}{data}
        try:
            tid = raw[1:13].decode()
            data = raw[13:]
            if data == b'__CLOSE__':
                self._resp_data[tid] = b'__CLOSE__'
            else:
                self._resp_data[tid] = data
        except Exception:
            pass


class PhoneTunnelManager:
    """管理所有手机隧道"""
    def __init__(self):
        self._tunnels = {}          # {tunnel_id: PhoneTunnel}
        self._port_alloc = {}       # {port: tunnel_id}
        self._next_port = TUNNEL_PORT_START
        self._lock = threading.Lock()

    def add_tunnel(self, ws, name: str = '') -> PhoneTunnel:
        """新手机连接，分配端口"""
        tid = uuid.uuid4().hex[:16]
        tunnel = PhoneTunnel(tid, ws, name)

        with self._lock:
            # 分配端口
            port = self._alloc_port()
            tunnel.start_socks5(port)
            self._tunnels[tid] = tunnel
            self._port_alloc[port] = tid

        print(f'[手机隧道] {name or tid[:8]} 已连接 | 端口={port} | socks5://服务器IP:{port}')
        return tunnel

    def remove_tunnel(self, tunnel_id: str):
        """手机断开"""
        with self._lock:
            tunnel = self._tunnels.pop(tunnel_id, None)
            if tunnel:
                tunnel.stop()
                port = tunnel.local_port
                self._port_alloc.pop(port, None)
                print(f'[手机隧道] {tunnel.name or tunnel_id[:8]} 已断开 | 端口={port} 释放')

    def get_tunnel_by_id(self, tunnel_id: str) -> PhoneTunnel:
        return self._tunnels.get(tunnel_id)

    def get_all_online(self) -> list:
        """获取所有在线手机隧道"""
        now = time.time()
        with self._lock:
            return [
                {
                    'tunnel_id': t.tunnel_id,
                    'name': t.name,
                    'local_port': t.local_port,
                    'proxy_addr': f'socks5://服务器IP:{t.local_port}',
                    'active_connections': t.active_connections,
                    'status': t.status,
                }
                for t in self._tunnels.values()
                if now - t.last_heartbeat < 90
            ]

    def pick_best_tunnel(self) -> PhoneTunnel:
        """选取最优手机隧道（最少连接数）"""
        online = []
        now = time.time()
        with self._lock:
            for t in self._tunnels.values():
                if now - t.last_heartbeat < 90:
                    online.append(t)
        if not online:
            return None
        # 选连接数最少的
        online.sort(key=lambda t: t.active_connections)
        return online[0]

    def broadcast_to_all(self, msg: dict):
        """向所有在线手机隧道广播消息（如中签通知）"""
        import asyncio
        now = time.time()
        loop = asyncio.get_event_loop()
        with self._lock:
            for t in self._tunnels.values():
                if now - t.last_heartbeat < 90 and t.ws:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            t.ws.send_json(msg), loop
                        )
                    except Exception:
                        pass

    def _alloc_port(self) -> int:
        """分配一个可用端口"""
        port = self._next_port
        while port in self._port_alloc:
            port += 1
            if port > TUNNEL_PORT_END:
                port = TUNNEL_PORT_START
        self._next_port = port + 1
        if self._next_port > TUNNEL_PORT_END:
            self._next_port = TUNNEL_PORT_START
        return port

    @property
    def tunnel_count(self) -> int:
        return len(self._tunnels)


def _recv_exact(sock, n):
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError('连接断开')
        data += chunk
    return data


# 全局单例
tunnel_manager = PhoneTunnelManager()
