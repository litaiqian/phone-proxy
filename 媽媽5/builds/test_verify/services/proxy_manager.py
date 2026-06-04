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
    """代理池管理：获取、分配、回收、丢弃代理IP
    支持多代理服务商：豌豆代理(wandouip)、极客IP(jikip)、快代理、ipipgo 等
    ★ 三种认证模式自适应：
      1. 隧道模式(tunnel)：固定URL，所有账号共用，服务商自动轮换IP
      2. 账密模式(password)： socks5://user:pass@ip:port，任何客户端都能连
      3. 白名单模式(whitelist)：socks5://ip:port，只有白名单内客户端能连
    核心逻辑：每个账号绑定一个代理IP，从登录到抢购全程使用
    """
    def __init__(self):
        self._pool = []           # 可用代理IP列表 ["socks5://ip:port", ...]
        self._discarded = set()   # 已丢弃的IP（黑号导致）
        self._lock = threading.Lock()
        self._last_fetch_time = 0
        self._fetch_interval = 60  # 最小获取间隔60秒

    def fetch_proxies(self, api_url: str, count: int = 20) -> list:
        """从代理API获取代理IP，返回代理URL列表
        ★ 三种模式自适应：
          - 账密模式(jikip mode=2): socks5://user:pass@ip:port (任何客户端都能连)
          - 白名单模式(wandouip/jikip mode=1): socks5://ip:port (需白名单)
        兼容多代理服务商：豌豆、极客(jikip)、快代理、ipipgo 等"""
        if not api_url:
            print('[代理池] 未配置代理API地址')
            return []

        now = time.time()
        with self._lock:
            if now - self._last_fetch_time < self._fetch_interval and self._pool:
                return self._pool

        try:
            api_url = api_url.strip().rstrip('&')
            parsed = urllib.parse.urlparse(api_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            # 强制按实际需求数量提取，删除 URL 中原有的 num 参数
            clean_params = {k: v for k, v in query_params.items() if k != 'num'}
            clean_params['num'] = [str(count)]
            new_query = urllib.parse.urlencode(clean_params, doseq=True)
            url = urllib.parse.urlunparse(parsed._replace(query=new_query))
            resp = requests.get(url, timeout=10, verify=False)
            data = resp.json()
            # === 多代理服务商兼容解析 ===
            # ★ 三种认证模式：
            #   wandouip(豌豆): 所有模式都是IP白名单 → socks5://ip:port
            #   jikip mode=2(极客账密): 返回含username/password → socks5://user:pass@ip:port
            #   jikip mode=1(极客白名单): 返回不含认证 → socks5://ip:port
            # 响应格式兼容：
            #   豌豆:  code=200, data=[{ip,port}]           → data 直接是数组
            #   jikip: code=0,   data={list:[{ip,port,user,pass}]} → data 是字典包裹数组
            success_code = data.get('code')
            # 兼容多种成功码：200(豌豆/jikip)、0(部分)、1(部分)
            if success_code in (200, 0, 1) and data.get('data'):
                # 归一化 data['data']：豌豆直接是数组，jikip是字典含list/items/proxies等键
                raw_data = data['data']
                if isinstance(raw_data, list):
                    ip_list = raw_data
                elif isinstance(raw_data, dict):
                    for key in ('list', 'items', 'proxies', 'data', 'result'):
                        if isinstance(raw_data.get(key), list):
                            ip_list = raw_data[key]
                            break
                    else:
                        ip_list = next((v for v in raw_data.values() if isinstance(v, list)), [])
                else:
                    ip_list = []
                # 检测协议：从 URL 参数判断代理类型
                # 豌豆(wandouapp)用 xy=3 表示socks5, xy=1 表示http
                # jikip/快代理用 protocol=3 表示socks5, protocol=1 表示http
                protocol_param = (query_params.get('protocol', [''])[0].lower()
                                  or query_params.get('xy', [''])[0].lower())
                proxy_scheme = 'socks5'  # 默认 socks5
                if protocol_param in ('1', '2', 'http', 'https'):
                    proxy_scheme = 'http'
                elif protocol_param in ('3', 'socks5', '5'):
                    proxy_scheme = 'socks5'
                # ★ 提取 SOCKS5 认证凭据：部分代理服务商在API响应中返回 username/password
                #   wandouapp 住宅代理返回 {ip,port,username,password}
                #   也兼容 user/pass/auth_user/auth_pass 等字段名
                #   如果响应不含认证，则尝试从API URL参数提取
                #   如 &socks5_user=xxx&socks5_pass=xxx 或 &auth=username:password
                url_auth_user = (query_params.get('socks5_user', [''])[0]
                                or query_params.get('auth_user', [''])[0])
                url_auth_pass = (query_params.get('socks5_pass', [''])[0]
                                or query_params.get('auth_pass', [''])[0])
                auth_param = query_params.get('auth', [''])[0]
                if auth_param and ':' in auth_param and not url_auth_user:
                    url_auth_user, url_auth_pass = auth_param.split(':', 1)
                new_proxies = []
                for item in ip_list:
                    ip = item.get('ip', '') or item.get('host', '') or item.get('address', '').split(':')[0]
                    port = item.get('port', '') or item.get('p', '')
                    if isinstance(port, int):
                        port = str(port)
                    # ★ 提取认证凭据：优先从API响应条目中取
                    auth_user = (item.get('username', '') or item.get('user', '')
                                or item.get('auth_user', '') or url_auth_user)
                    auth_pass = (item.get('password', '') or item.get('pass', '')
                                or item.get('auth_pass', '') or url_auth_pass)
                    if ip and port:
                        if auth_user and auth_pass:
                            proxy = f"{proxy_scheme}://{auth_user}:{auth_pass}@{ip}:{port}"
                        else:
                            proxy = f"{proxy_scheme}://{ip}:{port}"
                        if proxy not in self._discarded:
                            new_proxies.append(proxy)
                with self._lock:
                    self._pool.extend(new_proxies)
                    self._pool = list(dict.fromkeys(self._pool))
                    self._last_fetch_time = now
                print(f"[代理池] 获取到 {len(new_proxies)} 个新代理({proxy_scheme})，当前池大小: {len(self._pool)}")
                auth_count = sum(1 for p in new_proxies if '@' in p)
                if auth_count:
                    print(f"[代理池] 含认证凭据的IP: {auth_count}/{len(new_proxies)}")
                return new_proxies
            else:
                # 兼容 msg / message 字段取错误消息
                msg = data.get('msg', '') or data.get('message', '') or '未知错误'
                if '白名单' in str(msg) or 'whitelist' in str(msg).lower():
                    print(f"[代理池] 白名单未配置({msg})，30秒后重试")
                    with self._lock:
                        self._last_fetch_time = now - self._fetch_interval + 30
                elif 'LACK' in str(msg).upper() or 'POOL' in str(msg).upper() or '暂无' in str(msg):
                    print(f"[代理池] 暂无可用IP({msg})，30秒后重试")
                    with self._lock:
                        self._last_fetch_time = now - self._fetch_interval + 30
                else:
                    print(f'[代理池] API返回异常 | code={success_code} | msg={msg}')
                return []
        except Exception as e:
            self._last_error = f'{type(e).__name__}: {e}'
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
