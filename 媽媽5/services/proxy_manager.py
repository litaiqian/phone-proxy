#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 代理池管理器
豌豆代理IP获取、分配、回收、丢弃
"""
import time
import threading
import requests
import urllib.parse
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ProxyManager:
    """豌豆代理池管理：获取、分配、回收、丢弃代理IP
    核心逻辑：每个账号绑定一个代理IP，从登录到抢购全程使用
    """
    def __init__(self):
        self._pool = []           # 可用代理IP列表 ["socks5://ip:port", ...]
        self._discarded = set()   # 已丢弃的IP（黑号导致）
        self._lock = threading.Lock()
        self._last_fetch_time = 0
        self._fetch_interval = 60  # 最小获取间隔60秒

    def fetch_proxies(self, api_url: str, count: int = 20) -> list:
        """从豌豆API获取代理IP，返回 socks5://ip:port 列表"""
        if not api_url:
            print('[代理池] 未配置代理API地址')
            return []

        now = time.time()
        with self._lock:
            if now - self._last_fetch_time < self._fetch_interval and self._pool:
                return self._pool

        try:
            # 用户填的是完整URL，如果URL中已有num参数则不重复追加
            parsed = urllib.parse.urlparse(api_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            if 'num' in query_params:
                url = api_url  # URL中已有num参数，不重复追加
            else:
                sep = '&' if '?' in api_url else '?'
                url = f"{api_url}{sep}num={count}"
            resp = requests.get(url, timeout=10, verify=False)
            data = resp.json()
            if data.get('code') == 200 and data.get('data'):
                new_proxies = []
                for item in data['data']:
                    ip = item.get('ip', '')
                    port = item.get('port', '')
                    if ip and port:
                        proxy = f"socks5://{ip}:{port}"
                        if proxy not in self._discarded:
                            new_proxies.append(proxy)
                with self._lock:
                    self._pool.extend(new_proxies)
                    self._pool = list(dict.fromkeys(self._pool))
                    self._last_fetch_time = now
                print(f"[代理池] 获取到 {len(new_proxies)} 个新代理，当前池大小: {len(self._pool)}")
                return new_proxies
            else:
                # IP_POOL_LACK 表示代理池暂无可用IP，不是错误，缩短重试间隔
                msg = data.get('msg', '未知错误')
                if 'LACK' in str(msg).upper() or 'POOL' in str(msg).upper():
                    print(f"[代理池] 暂无可用IP({msg})，30秒后重试")
                    with self._lock:
                        self._last_fetch_time = now - self._fetch_interval + 30  # 30秒后允许重试
                else:
                    print(f'[代理池] API返回异常: {msg}')
                return []
        except Exception as e:
            print(f"[代理池] 获取代理失败: {e}")
            return []

    def get_proxy(self, api_url: str = '') -> str:
        """分配一个代理IP，池空时自动获取"""
        with self._lock:
            if self._pool:
                return self._pool.pop(0)
        # 池空，尝试获取
        self.fetch_proxies(api_url, 20)
        with self._lock:
            if self._pool:
                return self._pool.pop(0)
        return ''

    def return_proxy(self, proxy: str):
        """回收一个仍可用的代理IP"""
        if proxy and proxy not in self._discarded:
            with self._lock:
                self._pool.append(proxy)

    def discard_proxy(self, proxy: str):
        """丢弃一个IP（因被封或3次黑号）"""
        if proxy:
            with self._lock:
                self._discarded.add(proxy)
                self._pool = [p for p in self._pool if p != proxy]

    def pool_size(self) -> int:
        with self._lock:
            return len(self._pool)

    def all_proxies(self) -> list:
        """返回池中所有代理（含已分配但记录在DB中的）"""
        with self._lock:
            return list(self._pool)

    def all_discarded(self) -> set:
        with self._lock:
            return set(self._discarded)


# 全局代理管理器实例
proxy_manager = ProxyManager()
