#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地内存IP池 — 预加载100个IP到内存，抢购时毫秒级切换（不走网络）
- preload: 从代理API批量拉取 + 并行测试 → 存入就绪池
- alloc:   线程安全，O(1) 弹出下一个可用IP
- discard: 标记IP死亡
- return_ip: 回收仍可用的IP
"""

import threading
import time
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LocalIPPool:
    """本地IP池：预加载N个IP到内存，抢购中毫秒级切换"""

    def __init__(self):
        self._ready = []          # 就绪IP列表 ["socks5://ip:port", ...]
        self._dead = set()        # 已确认死亡的IP（不重复添加）
        self._lock = threading.Lock()
        self._total_fetched = 0   # 已从API拉取的IP总数（用于断流判断）

    # ---------- 基础操作（毫秒级） ----------

    def alloc(self):
        """分配一个就绪IP。O(1)，线程安全，毫秒级返回。池空返回''"""
        with self._lock:
            if self._ready:
                return self._ready.pop(0)
        return ''

    def discard(self, ip):
        """标记IP死亡，从就绪池移除"""
        if ip:
            with self._lock:
                self._dead.add(ip)
                self._ready = [p for p in self._ready if p != ip]

    def return_ip(self, ip):
        """回收一个仍可用的IP到池尾"""
        if ip and ip not in self._dead:
            with self._lock:
                if ip not in self._ready:
                    self._ready.append(ip)

    def size(self):
        with self._lock:
            return len(self._ready)

    def clear(self):
        with self._lock:
            self._ready.clear()
            self._dead.clear()
            self._total_fetched = 0

    def all_ready(self):
        """返回所有就绪IP的快照（调试用）"""
        with self._lock:
            return list(self._ready)

    # ---------- 预加载 ----------

    def _test_single(self, ip, bridge_base_url, timeout=4):
        """测试单个IP是否可用（通过桥接请求i茅台）"""
        try:
            resp = requests.post(
                f'{bridge_base_url}/api/bridge/test_proxy',
                json={'proxy_url': ip, 'timeout': timeout},
                timeout=timeout + 2,
                headers={'X-API-TOKEN': ''}
            )
            ok = resp.json().get('ok', False) if resp.status_code == 200 else False
            return ip, ok
        except Exception:
            return ip, False

    def preload(self, target_count=100, fetch_url='', bridge_base_url='', 
                batch_size=20, test_workers=10):
        """
        预加载指定数量的IP到内存池。
        - 从 fetch_url 批量拉取IP
        - 通过 bridge_base_url 并行测试可用性
        - 通过测试的IP直接写入就绪池
        返回实际加载的就绪IP数量
        """
        if not fetch_url:
            print('[本地IP池] 未配置代理API，跳过预加载')
            return 0

        start = time.time()
        print(f'[本地IP池] 开始预加载{target_count}个IP...')
        self._total_fetched = 0
        added = 0
        max_fetch = target_count * 3  # 最多拉取3倍目标数（考虑测试淘汰）

        while self.size() < target_count and self._total_fetched < max_fetch:
            # 1. 拉取一批IP
            try:
                sep = '&' if '?' in fetch_url else '?'
                url = f"{fetch_url}{sep}num={batch_size}"
                resp = requests.get(url, timeout=10, verify=False)
                data = resp.json()

                if data.get('code') != 200 or not data.get('data'):
                    msg = data.get('msg', '')
                    if 'LACK' in str(msg).upper() or 'POOL' in str(msg).upper():
                        print(f'[本地IP池] 上游暂无更多IP(已获取{self._total_fetched}个)，等待30秒...')
                        time.sleep(30)
                        continue
                    else:
                        print(f'[本地IP池] API异常: {msg}，停止拉取')
                        break

                # 2. 解析IP列表
                raw_ips = []
                for item in data['data']:
                    ip = item.get('ip', '')
                    port = item.get('port', '')
                    if ip and port:
                        proxy = f"socks5://{ip}:{port}"
                        with self._lock:
                            if proxy not in self._dead and proxy not in self._ready:
                                raw_ips.append(proxy)
                self._total_fetched += len(raw_ips)

                if not raw_ips:
                    continue

                # 3. 并行测试
                batch_tested = 0
                with ThreadPoolExecutor(max_workers=test_workers) as executor:
                    futures = {
                        executor.submit(self._test_single, ip, bridge_base_url): ip
                        for ip in raw_ips
                    }
                    for f in as_completed(futures):
                        ip, ok = f.result()
                        if ok:
                            with self._lock:
                                if ip not in self._ready:
                                    self._ready.append(ip)
                            added += 1
                            batch_tested += 1
                        else:
                            with self._lock:
                                self._dead.add(ip)

                elapsed = time.time() - start
                print(f'[本地IP池] 本批 {batch_tested}/{len(raw_ips)} 可用 | '
                      f'池中 {self.size()}/{target_count} | 耗时 {elapsed:.1f}s')

            except Exception as e:
                print(f'[本地IP池] 拉取失败: {e}')
                break

        elapsed = time.time() - start
        print(f'[本地IP池] ⚡预加载完成: {self.size()}个就绪IP (目标{target_count}) | '
              f'总耗时{elapsed:.1f}s | 淘汰{len(self._dead)}个')
        return self.size()


# 全局单例
local_ip_pool = LocalIPPool()
