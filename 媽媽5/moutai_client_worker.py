#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分布式抢购客户端 v4 — 异步调度 + 多线程暴力抢购
- asyncio 调度心跳/状态轮询
- ThreadPoolExecutor 并发抢购（最多200线程）
- IP秒级切换：检测到连接失败立即换IP
- 黑号秒级替换：黑号立即下线换新号
- 滑块验证集成点（需服务端部署 slider 服务）
"""
import json, time, uuid, requests, threading, asyncio, os, sys, socket
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Event

# ═══════════════════════════════════════════════════════
# 固定指向 iplala 账号，无需 Token 认证
# ═══════════════════════════════════════════════════════
USERNAME = 'iplala'
SERVER_BASE_URL = 'http://8.137.86.132:5000'

# 直连猫猫：导入 demo.py 的 MoutaiClient
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo import MoutaiClient

# ===================== 日志系统 =====================
def log(msg, srv_time=''):
    """打印日志（控制台输出）。
    自动附加当前线程的模式标签：[代理]IP / [直连]
    srv_time: CDN/目标站返回时间 (HH:MM:SS.ms)"""
    tag = _thread_mode_tag()
    if tag:
        msg = msg + tag
    if srv_time:
        msg = msg + f' | srv={srv_time}'
    now = datetime.now()
    ts = now.strftime('%H:%M:%S.') + f'{now.microsecond // 1000:03d}'
    line = f'[{ts}] {msg}'
    print(line, flush=True)

def _proxy_label(proxy_ip):
    """根据代理IP返回标签：[代理]IP / [直连]"""
    if not proxy_ip:
        return '[直连]'
    return f'[代理]{proxy_ip}'

def _thread_mode_tag():
    """获取当前线程的模式标签"""
    return ''

# ===================== 配置 =====================
# 固定指向 iplala 账号（在文件顶部已定义 USERNAME / SERVER_BASE_URL）

CLIENT_UUID = os.environ.get('CLIENT_UUID') or str(uuid.uuid4())[:8]
CLIENT_BATCH = -1
HOSTNAME = socket.gethostname()
# 服务重启版本号：从环境变量恢复，避免重启后反复触发
# 同时从文件恢复（systemd 重启时环境变量会丢失，文件持久化更可靠）
_last_server_restart_version = int(os.environ.get('LAST_SERVER_RESTART_VERSION', '0'))
if _last_server_restart_version == 0:
    try:
        ver_file = '/opt/moutai/last_server_restart_version'
        if os.path.exists(ver_file):
            with open(ver_file, 'r') as f:
                _last_server_restart_version = int(f.read().strip() or '0')
            if _last_server_restart_version > 0:
                log(f'[启动] 从文件恢复重启版本号 v={_last_server_restart_version}')
    except:
        pass
log(f'[启动] 主机={HOSTNAME} | UUID={CLIENT_UUID}')

ITEM_CODE = "IMTP1000313"


# 抢购轮次间隔（每轮抢购后等待的秒数）
RUSH_ROUND_INTERVAL = 5

# ===================== HTTP 工具 =====================
_HEADERS = {'Content-Type': 'application/json'}
_session_local = threading.local()

def _get_session():
    if not hasattr(_session_local, 'session'):
        _new_session()
    return _session_local.session

def _new_session():
    """新建 Session（丢弃旧连接，避免 RemoteDisconnected）"""
    s = requests.Session()
    s.headers.update(_HEADERS)
    from requests.adapters import HTTPAdapter
    s.mount('http://', HTTPAdapter(pool_connections=50, pool_maxsize=200, max_retries=0))
    s.mount('https://', HTTPAdapter(pool_connections=50, pool_maxsize=200, max_retries=0))
    _session_local.session = s

def _get(url, timeout=5):
    for attempt in range(2):
        try:
            return _get_session().get(url, timeout=timeout).json()
        except (requests.ConnectionError, requests.exceptions.ConnectionError):
            if attempt == 0:
                _new_session()  # 重建连接
                continue
        except Exception:
            pass
    return {'status': 'error'}

def _post(url, data=None, timeout=15):
    for attempt in range(2):
        try:
            resp = _get_session().post(url, json=data or {}, timeout=timeout)
            return resp.json()
        except (requests.ConnectionError, requests.exceptions.ConnectionError):
            if attempt == 0:
                _new_session()
                continue
        except Exception as e:
            if attempt == 0:
                _new_session()
                continue
            log(f'[HTTP] POST {url} 失败: {e}')
    return {'status': 'error'}

# ===================== 代理IP本地池（从服务端获取，不存DB） =====================
_proxy_cache = {'enabled': False, 'url': '', 'mode': 'whitelist'}  # mode: 'tunnel' / 'password' / 'whitelist'
_proxy_pool = []  # 本地缓存的代理IP列表（提取模式用）
_tunnel_url = ''    # 隧道代理URL（隧道模式用，所有账号共用）
_proxy_pool_lock = Lock()
_last_proxy_fetch = 0.0  # 上次获取代理IP的时间戳
_ips_per_account: int = 1   # 每号分配几个IP（从服务端配置读取）


def _get_proxy_session(proxy_url):
    """获取/创建 curl_cffi 代理 Session（支持 TLS 复用）
    同一个 proxy_url 复用同一个 Session，避免重复握手"""
    _key = f'_proxy_session_{hash(proxy_url)}'
    if not hasattr(_session_local, _key):
        from curl_cffi import requests as curl_requests
        s = curl_requests.Session()
        s.proxies = {'http': proxy_url, 'https': proxy_url}
        setattr(_session_local, _key, s)
    return getattr(_session_local, _key)


def _proxy_warmup(proxy_ips, stop_before_sec=0):
    """预热代理IP（二级验证：SOCKS5握手 + HTTP安全端点）。
    stop_before_sec>0: 每预热一个前检查距下一轮秒数，≤此值即停止预热（抢购优先）
    已预热的不参与下次预热；失败和未预热的认为不可用。
    返回 (成功IP列表, 失败+未预热IP列表)。"""
    if not proxy_ips:
        return [], []
    from urllib.parse import urlparse
    _SAFE_URL = "https://static.moutai519.com.cn/mt-backend/xhr/front/mall/resource/get"
    _SAFE_HEADERS = {"User-Agent": "android;34;Xiaomi;fuxi", "Accept": "*/*", "Accept-Encoding": "gzip"}

    warmed, failed = [], []
    for ip_url in proxy_ips:
        # ★ 抢购前停止预热：=0不检查，>0则每IP前判断
        if stop_before_sec > 0:
            dist = seconds_to_rush_window()
            if not in_rush_window() and dist <= stop_before_sec:
                remaining = proxy_ips[len(warmed) + len(failed):]
                log(f'[预热] 距下一轮{dist:.1f}s ≤ {stop_before_sec}s，停止预热 | 已{len(warmed)}/{len(proxy_ips)}个')
                failed.extend(remaining)
                break
        try:
            parsed = urlparse(ip_url)
            proxy_host = parsed.hostname
            proxy_port = parsed.port or (1080 if parsed.scheme and parsed.scheme.startswith('socks') else 8080)
            if not proxy_host:
                failed.append(ip_url)
                continue
            # ★ 日志脱敏：隐藏认证凭据
            display_url = ip_url
            if parsed.username:
                display_url = f"{parsed.scheme}://***:***@{proxy_host}:{proxy_port}"
            # ===== 第一层：SOCKS5 TCP连通 + 握手检测 =====
            has_auth = bool(parsed.username)
            t0 = time.time()
            sock = socket.create_connection((proxy_host, proxy_port), timeout=3)
            tcp_rtt = time.time() - t0

            sock_ok = False  # SOCKS5握手是否通过
            need_http_verify = False  # 是否需要HTTP层验证
            if parsed.scheme and parsed.scheme.startswith('socks'):
                if has_auth:
                    auth_methods = b'\x05\x02\x00\x02'  # NO_AUTH + USER/PASS
                else:
                    auth_methods = b'\x05\x01\x00'  # NO_AUTH only
                sock.sendall(auth_methods)
                resp = sock.recv(2)
                if len(resp) == 2 and resp[0] == 5:
                    if resp[1] == 0x00:          # NO AUTH → 通过
                        sock_ok = True
                    elif resp[1] == 0x02 and has_auth:  # 需认证且带密码 → 握手通过
                        sock_ok = True
                        need_http_verify = True  # ★ 但需HTTP验证凭据是否正确
                    # resp[1]==0x02 且无密码 → 不通过，但可能是IP白名单代理
                    # resp[1]==0xFF → 非标准实现，尝试HTTP测试
                # 非SOCKS5响应 → 尝试HTTP测试
            else:
                # HTTP代理 → TCP连通即可
                sock_ok = True
            sock.close()

            # ★ 非认证代理：SOCKS5握手通过即认为可用（不暴露IP到CDN）
            # ★ 认证代理：握手通过后需HTTP验证凭据正确
            if sock_ok and not need_http_verify:
                warmed.append(ip_url)
                log(f'[预热] {display_url} ✓ SOCKS5握手通过(tcp_rtt={tcp_rtt*1000:.0f}ms)')
                continue

            # ===== 第二层：HTTP验证 =====
            # ① SOCKS5握手不通过（0x02/0xFF） → 用HTTP测试连通性（IP白名单代理）
            # ② SOCKS5握手通过但需认证 → 用HTTP验证凭据是否正确
            # 都使用安全端点 static.moutai519.com.cn (APP启动配置资源)
            try:
                from curl_cffi import requests as curl_requests
                sess = curl_requests.Session(impersonate="chrome124")
                sess.proxies = {'http': ip_url, 'https': ip_url}
                resp = sess.get(_SAFE_URL, headers=_SAFE_HEADERS, timeout=5)
                # HTTP 200 = 正常, 304 = CDN缓存命中, 429 = 限流但连通
                if resp.status_code in (200, 304, 429) or (200 <= resp.status_code < 500):
                    warmed.append(ip_url)
                    if need_http_verify:
                        log(f'[预热] {display_url} ✓ 认证凭据验证通过(HTTP={resp.status_code})')
                    else:
                        log(f'[预热] {display_url} SOCKS5握手失败但HTTP连通(HTTP={resp.status_code})')
                else:
                    failed.append(ip_url)
                    log(f'[预热] {display_url} HTTP状态异常({resp.status_code})')
                sess.close()  # 预热Session不保留，抢购时用各自的持久Session
            except Exception as e:
                err_str = str(e)[:80]
                failed.append(ip_url)
                log(f'[预热] {display_url} SOCKS5+HTTP均失败: {err_str}')
        except Exception:
            failed.append(ip_url)
    if warmed:
        log(f'[预热] {len(warmed)}/{len(proxy_ips)} 个代理可用 | SOCKS5+HTTP二级验证(APP启动安全端点)')
    if failed:
        log(f'[预热] ⚠️ {len(failed)} 个代理不可用: {[f[:30] for f in failed]}')
    return warmed, failed


def _replace_failed_ips(failed_ips, tasks, ips_per):
    """连通性测试失败的 IP 从池中移除，重新拉取等量 IP 补充，确保每号 IP 数达标"""
    global _proxy_pool
    if not failed_ips or not _proxy_cache.get('enabled'):
        return
    # 从池中移除失败IP
    with _proxy_pool_lock:
        for fip in failed_ips:
            if fip in _proxy_pool:
                _proxy_pool.remove(fip)
        current_pool = list(_proxy_pool)
    # 计算还需多少IP
    total_needed = len(tasks) * ips_per
    shortage = max(0, total_needed - len(current_pool))
    if shortage > 0:
        log(f'[代理] 补充拉取 {shortage} 个IP（失败{len(failed_ips)}个，池余{len(current_pool)}，需{total_needed}）')
        r = _post(f'{SERVER_BASE_URL}/api/client/get_proxies', {
            'username': USERNAME,
            'count': shortage
        })
        if r.get('status') == 'success':
            new_ips = r.get('proxies', [])
            with _proxy_pool_lock:
                _proxy_pool.extend(new_ips)
            log(f'[代理] 补充获取 {len(new_ips)} 个IP')
            # 预热新IP
            if new_ips:
                warmed_new, failed_new = _proxy_warmup(new_ips)
                if failed_new:
                    # 递归替换再次失败的（最多2层防止死循环）
                    with _proxy_pool_lock:
                        for fip in failed_new:
                            if fip in _proxy_pool:
                                _proxy_pool.remove(fip)
    # 重新分配：确保每号独占 ips_per 个IP
    _assign_proxies_to_tasks(tasks)


def _fetch_proxies_from_server(count=20):
    """从服务端获取代理IP列表，存入本地池。
    ★ 三种模式自适应（服务端 proxy_mode 字段告知）：
      1. tunnel  = 隧道模式：服务端返回一个固定URL，所有账号共用，豌豆/极客后台自动轮换IP
      2. password = 账密模式：服务端返回 socks5://user:pass@ip:port，任何客户端都能连
                   不需要IP池管理（类似隧道），但每个IP是独立短效IP
      3. whitelist = 白名单模式：服务端返回 socks5://ip:port，需要IP池管理和分配
                   只有白名单内的客户端能连（≤5台适用）
    超时60秒（服务端需并发测试IP连通性）"""
    global _proxy_pool, _last_proxy_fetch, _tunnel_url
    if not _proxy_cache.get('enabled'):
        log('[代理] 代理未开启，跳过获取')
        return []
    try:
        s = _get_session()
        resp = s.post(f'{SERVER_BASE_URL}/api/client/get_proxies',
                      json={'username': USERNAME, 'count': count},
                      timeout=60)
        r = resp.json()
        proxy_mode = r.get('proxy_mode', 'whitelist')  # tunnel / password / whitelist
        _proxy_cache['mode'] = proxy_mode
        if r.get('status') == 'success':
            proxies = r.get('proxies', [])
            if proxy_mode == 'tunnel' and proxies:
                # ★ 隧道模式：只有一个URL，所有账号共用
                _tunnel_url = proxies[0]
                _display = _tunnel_url
                if '@' in _tunnel_url:
                    _display = _tunnel_url.split('@')[0] + '@***:***' + _tunnel_url.split('@')[1].split(':', 1)[0] if ':' in _tunnel_url.split('@')[1] else _tunnel_url.split('@')[0] + '@***'
                log(f'[代理] 隧道模式: {_display[:40]}... (所有账号共用，服务商自动轮换IP)')
                with _proxy_pool_lock:
                    _proxy_pool = proxies
                _last_proxy_fetch = time.time()
                return proxies
            elif proxy_mode == 'password' and proxies:
                # ★ 账密模式：IP自带认证凭据(socks5://user:pass@ip:port)
                # 任何客户端都能用，不需要白名单，100台客户端随便用
                auth_count = sum(1 for p in proxies if '@' in p)
                log(f'[代理] 账密模式: {len(proxies)} 个IP (含认证={auth_count}/{len(proxies)}), 任何客户端都能连')
                with _proxy_pool_lock:
                    _proxy_pool = proxies
                _last_proxy_fetch = time.time()
                return proxies
            else:
                # ★ 白名单模式：多个IP，需要分配和预热，只有白名单内客户端能连
                with _proxy_pool_lock:
                    _proxy_pool = proxies
                _last_proxy_fetch = time.time()
                log(f'[代理] 白名单模式: 从服务端获取到 {len(proxies)} 个IP')
                return proxies
        else:
            err_msg = r.get('message', '未知')
            log(f'[代理] 服务端获取失败: {err_msg}')
            return []
    except Exception as e:
        log(f'[代理] 获取异常: {e}')
        return []


def _assign_proxies_to_tasks(tasks):
    """将代理IP分配给任务列表。
    ★ 隧道模式(tunnel)：所有账号共用同一个隧道URL，服务商后台自动轮换IP
    ★ 账密模式(password)：每号独占 ips_per 个IP(含认证)，账号间不重叠
    ★ 白名单模式(whitelist)：每号独占 ips_per 个IP(无认证)，账号间不重叠"""
    global _proxy_pool, _ips_per_account
    # ★ 隧道模式 + 账密模式共用：所有账号共用同一个隧道URL
    # 隧道模式：1个固定URL，所有账号共用
    # 账密模式：也可所有账号共用同一组IP，但建议每号独占以避免同IP限流
    if _proxy_cache.get('mode') == 'tunnel' and _tunnel_url:
        for t in tasks:
            t['proxy_ip'] = _tunnel_url
            t['proxy_ips'] = [_tunnel_url]
        log(f'[分配] 隧道模式: {len(tasks)}号共用 {_tunnel_url[:30]}...')
        return
    # 提取模式：每号独占IP
    with _proxy_pool_lock:
        pool = list(_proxy_pool)
    if not _proxy_cache.get('enabled') or not pool:
        for t in tasks:
            t['proxy_ip'] = ''
            t['proxy_ips'] = []
        return
    ips_per = max(1, _ips_per_account)
    total_needed = len(tasks) * ips_per
    # IP不足时补拉（需要多少补多少）
    shortage = max(0, total_needed - len(pool))
    if shortage > 0:
        log(f'[分配] IP不足: 需{total_needed}个(={len(tasks)}号×{ips_per})，池仅{len(pool)}个，补拉{shortage}个')
        r = _post(f'{SERVER_BASE_URL}/api/client/get_proxies', {
            'username': USERNAME,
            'count': shortage
        })
        if r.get('status') == 'success':
            new_ips = r.get('proxies', [])
            with _proxy_pool_lock:
                _proxy_pool.extend(new_ips)
                pool = list(_proxy_pool)
            log(f'[分配] 补拉获取 {len(new_ips)} 个IP，池总量={len(pool)}')
    # 独占分配：每个账号连续取 ips_per 个IP，账号间不重叠
    ip_idx = 0
    for i, t in enumerate(tasks):
        start = ip_idx
        ips = []
        for j in range(ips_per):
            if start + j < len(pool):
                ips.append(pool[start + j])
        if ips:
            t['proxy_ips'] = ips
            t['proxy_ip'] = ips[0]
            ip_idx = start + len(ips)
        else:
            t['proxy_ip'] = ''
            t['proxy_ips'] = []
    assigned_count = sum(1 for t in tasks if t.get('proxy_ips'))
    total_ips = sum(len(t.get('proxy_ips', [])) for t in tasks)
    if ips_per > 1:
        log(f'[分配] 独占模式: {assigned_count}号×{ips_per}IP={total_ips}个IP | 池总量={len(pool)}')
    else:
        log(f'[分配] 独占模式: {assigned_count}号各1个IP | 池总量={len(pool)}')


def _proxy_prefetch(tasks):
    """抢购前预取代理IP + 分配。不测试，直接分。"""
    if not _proxy_cache.get('enabled'):
        for t in tasks:
            t['proxy_ip'] = ''
            t['proxy_ips'] = []
        return
    global _ips_per_account
    # 拉取代理
    _fetch_proxies_from_server(len(tasks) * max(1, _ips_per_account))
    # 分配（不测试，直接用）
    _assign_proxies_to_tasks(tasks)
    ip_count = sum(1 for t in tasks if t.get('proxy_ip'))
    total_ips = sum(len(t.get('proxy_ips', [])) for t in tasks)
    log(f'[代理] 获取完成: {ip_count}号 × {total_ips}个IP (不测试，直接分配)')


# ===================== 参数缓存（直连） =====================
_item_cache_lock, _item_cache = Lock(), {'data': None, 'ts': 0}
CACHE_TTL = 7200  # 2小时缓存

def get_item_params(client):
    """HAR方式获取商品参数：直连purchaseInfoV2获取skuId + itemPriorityActId。
    全部参数从 API 实时获取，不使用任何硬编码兜底值。
    API 失败时重试最多 3 次，全部失败返回 None。"""
    now = time.time()
    with _item_cache_lock:
        if _item_cache['data'] and (now - _item_cache['ts']) < CACHE_TTL:
            return _item_cache['data']
    for attempt in range(3):
        try:
            r = client.get_purchase_info_v2(ITEM_CODE)
            purchase_map = r.get('purchaseInfoMap', {})
            if purchase_map:
                sku_id = ''
                act_id = ''
                for sku_key, sku_info in purchase_map.items():
                    pinfo = sku_info.get('purchaseInfo', {})
                    sku_id = str(pinfo.get('skuId', ''))
                    act_id = str(pinfo.get('itemPriorityActId', ''))
                    print('+++++++++++++++++++',sku_id,act_id)
                    if sku_id and act_id:
                        # 优先取有库存且未禁用的sku
                        if pinfo.get('inventory', 0) > 0 and not pinfo.get('disable', False):
                            break
                if sku_id and act_id:
                    data = {'item_code': sku_id, 'act_id': act_id}
                    with _item_cache_lock:
                        _item_cache['data'], _item_cache['ts'] = data, now
                    log(f'[参数] HAR获取成功 | skuId(itemCode)={sku_id} | itemPriorityActId={act_id}')
                    return data
            log(f'[参数] purchaseInfoMap为空(第{attempt+1}次)')
        except Exception as e:
            log(f'[参数] API调用异常(第{attempt+1}次): {e}')
        if attempt < 2:
            time.sleep(0.005)
    log(f'[参数] ❌ 3次重试均失败，无法获取商品参数！')
    return None

# ===================== 抢购窗口定义（动态生成，基于网站配置的抢购时间） =====================
# 网站配置的抢购时间（从 fetch_config 读取并写入全局，供生成窗口使用）
_RUSH_HOUR: int = 20
_RUSH_MINUTE: int = 0
_RUSH_SECOND: int = 0
_RUSH_MILLISECOND: int = 0

def set_rush_time(hour: int, minute: int, second: int, millisecond: int = 0):
    """设置网站配置的抢购时间（到达目标站的时间），重建抢购窗口"""
    global _RUSH_HOUR, _RUSH_MINUTE, _RUSH_SECOND, _RUSH_MILLISECOND, _RUSH_WINDOWS
    _RUSH_HOUR, _RUSH_MINUTE, _RUSH_SECOND, _RUSH_MILLISECOND = hour, minute, second, millisecond
    _rebuild_rush_windows()

# 抢购请求提前发送量（秒）= 物理网络延迟 + 期望预到目标时间
# 请求在配置时间前 NETWORK_ADVANCE 秒发出，到达目标站 ≈ 配置的抢购时间 - PREADVANCE_MS 毫秒
# 直连默认 0.3s 物理延迟 + 300ms 预提前 = 0.6s，代理模式下物理延迟动态调整为实测 RTT/2
NETWORK_PREADVANCE_MS = 300  # 期望请求到达目标站早于配置时间多少毫秒
NETWORK_ADVANCE = 0.6  # 初始值 = 预估物理延迟 0.3s + 预提前 0.3s

def _rebuild_rush_windows():
    """多窗口：每5分钟1轮，共13轮。配置的抢购时间 = 请求到达目标站的时间
    示例: 配置19:59:59.500 → 第1轮19:59:59.500, 第2轮20:04:59.500, ..."""
    global _RUSH_WINDOWS
    rush_base = _RUSH_HOUR * 3600 + _RUSH_MINUTE * 60 + _RUSH_SECOND + _RUSH_MILLISECOND / 1000.0
    _RUSH_WINDOWS = []
    for i in range(13):
        offset_sec = i * 300  # 每5分钟一轮
        start = rush_base + offset_sec - NETWORK_ADVANCE  # 提前网络延迟量发出
        end   = rush_base + offset_sec + 4                # 窗口后延4秒兜底
        _RUSH_WINDOWS.append((start, end))

# 初始化为默认 20:00:00
_RUSH_WINDOWS: list = []
_rebuild_rush_windows()

# 全局服务器时间偏差（秒）：正数表示本地快于服务器
_server_time_offset: float = 0.0

def set_server_time_offset(offset: float):
    """设置服务器时间偏差，供抢购窗口判断使用"""
    global _server_time_offset
    _server_time_offset = offset

def _get_corrected_now():
    """返回校正后的当前时间（服务器时间）"""
    if _server_time_offset != 0.0:
        return datetime.fromtimestamp(time.time() - _server_time_offset)
    return datetime.now()

def in_rush_window():
    """检查当前是否在快抢窗口内（使用校正后的服务器时间，含毫秒精度）。"""
    now = _get_corrected_now()
    total = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1_000_000.0
    for start, end in _RUSH_WINDOWS:
        if start <= total <= end:
            return True
    return False

def seconds_to_rush_window():
    """返回到下一个快窗口开始的秒数（使用校正后的服务器时间，含毫秒精度）。在快窗口内返回0"""
    now = _get_corrected_now()
    total = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1_000_000.0
    for start, end in _RUSH_WINDOWS:
        if start <= total <= end:
            return 0.0
    for start, _end in _RUSH_WINDOWS:
        if total < start:
            return start - total
    tomorrow = now.replace(hour=19, minute=59, second=59, microsecond=0) + timedelta(days=1)
    return (tomorrow - now).total_seconds()

def target_rush_time():
    """返回网站配置的目标抢购时间（服务器时间），格式: 20:00:00.500"""
    return f"{_RUSH_HOUR:02d}:{_RUSH_MINUTE:02d}:{_RUSH_SECOND:02d}.{_RUSH_MILLISECOND:03d}"

def current_window_target():
    """返回当前所在窗口的目标抢购时间（含5分钟偏移），格式: 20:05:00.500
    若不在任何窗口内，返回最近一个未来窗口的目标时间"""
    now = _get_corrected_now()
    total = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1_000_000.0
    rush_base = _RUSH_HOUR * 3600 + _RUSH_MINUTE * 60 + _RUSH_SECOND + _RUSH_MILLISECOND / 1000.0
    for start, end in _RUSH_WINDOWS:
        if start <= total <= end:
            target_sec = start + NETWORK_ADVANCE  # 窗口开始 + 延迟 = 目标到达时间
            break
    else:
        # 不在窗口内，返回第一个未来窗口
        for start, _end in _RUSH_WINDOWS:
            if total < start:
                target_sec = start + NETWORK_ADVANCE
                break
        else:
            return target_rush_time()
    h = int(target_sec) // 3600 % 24
    m = (int(target_sec) % 3600) // 60
    s = int(target_sec) % 60
    ms = int(round((target_sec - int(target_sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

RUSH_PRESTART = 13.0  # 提前13秒进入（10秒浏览商品页面 + 3秒线程准备）

# 抢购模式: 0=调试/关闭 1=正式/开启（从服务端 fetch_config 读取）
_rush_mode = 0
_async_rush = False  # 异步抢购开关: True=每个IP独立并发抢购, False=IP轮询顺序抢购
# 抢购截止时间（Unix秒），从 startTimeList 最后一个时间点提取
_rush_deadline = 0.0

def seconds_to_rush_prestart():
    """返回到快窗口前 RUSH_PRESTART 秒的秒数。已进入预启动区返回0"""
    dist = seconds_to_rush_window()
    return max(0, dist - RUSH_PRESTART)

# ===================== 服务端API =====================
_last_config_log = {}
_last_pause_log = {}

def fetch_config():
    global _rush_mode, _ips_per_account, _async_rush, _last_config_log
    r = _get(f'{SERVER_BASE_URL}/api/client/get_config?username={USERNAME}')
    if r.get('rush_paused') is not None:
        _rush_mode = r.get('rush_mode', 0)
        _ips_per_account = max(1, r.get('ips_per_account', 1))
        _async_rush = r.get('async_rush', False) or False
        cfg_key = (r.get('proxy_enabled'), r.get('rush_count'), r.get('rush_paused'), _async_rush)
        if cfg_key != _last_config_log.get('key'):
            _last_config_log['key'] = cfg_key
            _async_label = '异步(IP并行)' if _async_rush else '轮询(IP顺序)'
            log(f'[配置] 代理={"开" if r.get("proxy_enabled") else "关"} | 次数={r.get("rush_count","?")}/轮 | 暂停={r.get("rush_paused")} | mode={_rush_mode} | 模式={_async_label}')
        return r
    _rush_mode = 0
    _ips_per_account = 1
    _async_rush = False
    log(f'[配置] fetch_config 失败，使用默认值')
    return {'rush_paused': 0, 'proxy_enabled': False, 'proxy_url': '', 'multi_open_count': 1}

def get_pause_status():
    global _proxy_cache, _last_pause_log
    r = _get(f'{SERVER_BASE_URL}/api/client/get_pause_status?username={USERNAME}')
    if r.get('paused') is not None:
        _proxy_cache = {
            'enabled': r.get('proxy_enabled', False),
            'url': r.get('proxy_url', ''),
        }
        p_key = (r.get('paused'), r.get('proxy_enabled'))
        if p_key != _last_pause_log.get('key'):
            _last_pause_log['key'] = p_key
            log(f'[状态] 暂停={r.get("paused")} | 代理={"开" if r.get("proxy_enabled") else "关"}')
        return r
    log(f'[状态] get_pause_status 失败')
    return {'paused': 0, 'proxy_enabled': False, 'proxy_url': ''}

def register_client():
    global CLIENT_BATCH
    r = _post(f'{SERVER_BASE_URL}/api/client/register', {'client_uuid': CLIENT_UUID, 'username': USERNAME, 'hostname': HOSTNAME})
    if r.get('status') == 'success':
        CLIENT_BATCH = r.get('batch', 0)
        log(f'[注册] 窗口={CLIENT_BATCH+1}, UUID={CLIENT_UUID}, 任务={len(r.get("tasks",[]))}')
    else:
        log(f'[注册] 失败! 状态={r.get("status")} URL={SERVER_BASE_URL}/api/client/register')
    return r

def fetch_tasks(batch=0):
    r = _post(f'{SERVER_BASE_URL}/api/client/get_tasks', {'username': USERNAME, 'batch': batch})
    if r.get('status') == 'success':
        return r.get('tasks', [])
    log(f'[任务] 获取失败! 状态={r.get("status")}')
    return []

def report_result(phone, success, order_id='', h5_url='', error='',
                  pay_url_alipay='', pay_url_wechat='', pay_url_unionpay=''):
    _post(f'{SERVER_BASE_URL}/api/client/report_result', {
        'phone': phone, 'success': success, 'order_id': order_id,
        'h5_url': h5_url, 'error': error,
        'pay_url_alipay': pay_url_alipay, 'pay_url_wechat': pay_url_wechat,
        'pay_url_unionpay': pay_url_unionpay})

def report_startup(task_count):
    """启动部署上报：本机标识、窗口数、账号数"""
    try:
        _post(f'{SERVER_BASE_URL}/api/client/startup_report', {
            'hostname': HOSTNAME,
            'client_uuid': CLIENT_UUID,
            'batch': CLIENT_BATCH,
            'username': USERNAME,
            'task_count': task_count
        })
    except Exception:
        pass

def report_rush_success(phone, task=None):
    """抢购成功即时上报"""
    try:
        _post(f'{SERVER_BASE_URL}/api/client/rush_success_report', {
            'phone': phone,
            'hostname': HOSTNAME,
            'client_uuid': CLIENT_UUID,
            'batch': CLIENT_BATCH,
            'username': USERNAME,
            'team_name': (task or {}).get('team_name', ''),
        })
    except Exception:
        pass

async def heartbeat_async(task_count):
    """心跳：上报状态 + 检查服务端是否要求服务重启
    如果服务端重启过（状态丢失），自动重新注册"""
    global _last_server_restart_version, CLIENT_BATCH
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: _post(
            f'{SERVER_BASE_URL}/api/client/heartbeat',
            {'batch': CLIENT_BATCH, 'client_uuid': CLIENT_UUID, 'task_count': task_count, 'username': USERNAME, 'hostname': HOSTNAME}))
        # 心跳失败（服务端重启/网络中断）：立即重新注册，恢复服务端内存状态
        if resp.get('status') != 'success':
            log('[心跳] 服务端无响应，尝试重新注册...')
            reg = await loop.run_in_executor(None, register_client)
            if reg.get('status') == 'success':
                log(f'[心跳] 重新注册成功，窗口={CLIENT_BATCH+1}')
            return
        # 检查服务级 restart 指令（杀所有进程，systemd 自动拉起，类似 Windows 注销）
        if resp.get('server_restart_required') and resp.get('server_restart_version', 0) != _last_server_restart_version:
            _last_server_restart_version = resp['server_restart_version']
            log(f'[服务重启] 收到 restart 指令 v={_last_server_restart_version}！随机延迟后执行...')
            do_server_restart()
    except Exception:
        pass


def do_server_restart():
    """服务重启（类似 Windows 注销）：杀所有客户端进程，systemd 自动重新拉起
    使用文件锁防止同一台机器的多个窗口同时执行，仅需 ~5 秒"""
    import random as _random
    lock_file = '/tmp/moutai_restart.lock'
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, f'{time.time()}\n'.encode())
        os.close(fd)
    except FileExistsError:
        log('[服务重启] 已有其他窗口在执行，跳过')
        return
    delay = _random.uniform(0, 10)
    log(f'[服务重启] 将在 {delay:.1f} 秒后重启所有窗口（systemd 自动拉起）...')
    # 保存版本号到文件，防止重启后再次触发
    try:
        ver_file = '/opt/moutai/last_server_restart_version'
        os.makedirs(os.path.dirname(ver_file), exist_ok=True)
        with open(ver_file, 'w') as f:
            f.write(str(_last_server_restart_version))
        log(f'[服务重启] 已保存版本号 v={_last_server_restart_version} 到文件')
    except Exception as e:
        log(f'[服务重启] 保存版本号失败: {e}')
    time.sleep(delay)
    log('[服务重启] 杀掉所有客户端进程，systemd 将自动重启...')
    # 先尝试 systemctl restart（最干净的方式）
    ret = os.system('systemctl restart moutai-client 2>/dev/null')
    if ret != 0:
        # 回退：直接杀进程，systemd Restart=always 会自动拉起
        os.system('pkill -9 -f moutai_client_worker 2>/dev/null')
    os._exit(0)


# ===================== 下单支付全流程（直连） =====================
def complete_order_flow(task, client, rush_result):
    """
    抢购成功后的下单支付全流程:
      1. 获取收货地址
      2. compose/v2 组单（3次尝试）
      3. submit/v2 提交订单
      4. pay_order → request_pay → convert_to_h5
    """
    phone = task['phone']
    rush_data = rush_result.get('data', {})
    rid = rush_data.get('priorityRecordId', 0)
    if not rid:
        log(f'[{phone}] 抢购成功但无 priorityRecordId')
        return None

    # 1. 地址
    addresses = client.get_addresses()

    if not addresses:
        log(f'[{phone}] 无收货地址，下单终止')
        return None
    addr = next((a for a in addresses if a.get('dft')), addresses[0])
    print(addr)
    # 2. 组单→提交
    item_info = get_item_params(client)

    if item_info is None:
        log(f'[{phone}] ❌ 无法获取商品参数，下单终止')
        return None
    sku_id = item_info['item_code']
    order_count = int(task.get('amount', 1))  # 从数据库读取每个账号的抢购数量
    log(f'[{phone}] 开始组单... spuId={sku_id} count={order_count}')
    compose = client.compose_order_v2(
        spu_id=sku_id, count=order_count, priority_record_id=rid,
        address_id=addr.get('shipAddressId', 0))
    if compose.get('code') != 2000:
        log(f'[{phone}] 组单失败: code={compose.get("code")}, msg={compose.get("message","")}')
        return None
    log(f'[{phone}] 组单成功，提交订单...')
    submit = client.submit_order(
        spu_id=sku_id, count=order_count, priority_record_id=rid, address=addr)
    if submit.get('code') != 2000:
        log(f'[{phone}] 提交订单失败: code={submit.get("code")}, msg={submit.get("message","")}')
        return None
    oid = submit.get('data', {}).get('orderId')
    if not oid:
        log(f'[{phone}] 提交成功但无 orderId')
        return None
    log(f'[{phone}] 下单成功! 订单号={oid}')
    # 3. 支付
    pay = client.pay_order(oid)
    if pay.get('code') != 2000:
        log(f'[{phone}] 支付失败: code={pay.get("code")}')
        return None
    tn = pay.get('data', {}).get('channelTradeSn')
    if not tn:
        log(f'[{phone}] 支付成功但无 TN')
        return None
    log(f'[{phone}] 获取支付TN成功')
    # 4. 网关 — 云闪付银联(20)优先，支付宝(70)/微信(10)备用
    ext_info = pay.get('data', {}).get('extInfo', '')
    device_id = ''
    try:
        ext = json.loads(ext_info) if isinstance(ext_info, str) else ext_info
        device_id = ext.get('DEVICE_ID', '')
    except: pass

    pay_urls = {'alipay': '', 'wechat': '', 'unionpay': ''}
    for ch_name, ch_code in [('unionpay', '20'), ('alipay', '70'), ('wechat', '10')]:
        try:
            gw = client.request_pay(tn, pay_channel=ch_code, sales_id=oid, device_id=device_id)
            gw_code = gw.get('code')
            if isinstance(gw_code, str): gw_code = int(gw_code)
            log(f'[{phone}] 📲 支付渠道 {ch_name}({ch_code}) 返回: code={gw_code} | data={str(gw.get("data",""))[:200]}')
            if gw_code not in (200, 2000):
                log(f'[{phone}] ❌ 支付渠道 {ch_name}({ch_code}) 失败: code={gw_code}')
                continue
            pd2 = gw.get('data', '')
            sdk_str = ''
            if isinstance(pd2, str):
                if pd2.startswith('http'):
                    pay_urls[ch_name] = pd2
                    log(f'[{phone}] ✅ {ch_name} 支付链接(直出): {pd2}')
                    continue
                sdk_str = pd2
            elif isinstance(pd2, dict):
                sdk_str = pd2.get('payInfo') or pd2.get('alipay_sdk') or pd2.get('orderInfo') or pd2.get('AUTH_CODE') or ''
                log(f'[{phone}] 📋 {ch_name} SDK原始数据: {str(pd2)[:300]}')
            if not sdk_str:
                log(f'[{phone}] ⚠️ 支付渠道 {ch_name} 未返回有效数据')
                continue
            if ch_code == '70':
                log(f'[{phone}] 🔄 支付宝 SDK→H5 转链中...')
                h5r = client.convert_to_h5(sdk_str)
                h5_url = h5r.get('h5Url', '') if h5r.get('success') else ''
                if h5_url:
                    pay_urls[ch_name] = h5_url
                    log(f'[{phone}] ✅ 支付宝转链成功: {h5_url}')
                else:
                    log(f'[{phone}] ❌ 支付宝转链失败 | 返回: {str(h5r)[:200]}')
            elif sdk_str.startswith('http'):
                pay_urls[ch_name] = sdk_str
                log(f'[{phone}] ✅ {ch_name} 支付链接: {sdk_str}')
            else:
                pay_urls[ch_name] = sdk_str
                log(f'[{phone}] 📦 {ch_name} 支付数据(长度={len(sdk_str)}): {sdk_str[:200]}')
        except Exception as e:
            log(f'[{phone}] 💥 支付渠道 {ch_name} 异常: {e}')

    # 汇总日志：打印所有3种支付链接
    log(f'[{phone}] 📊 支付链接汇总:')
    log(f'[{phone}]   支付宝: {"✅" if pay_urls["alipay"] else "❌ 无"} {pay_urls["alipay"]}')
    log(f'[{phone}]   微信:   {"✅" if pay_urls["wechat"] else "❌ 无"} {pay_urls["wechat"]}')
    log(f'[{phone}]   云闪付: {"✅" if pay_urls["unionpay"] else "❌ 无"} {pay_urls["unionpay"]}')

    # 取任意一个有效的作为主 h5_url，优先云闪付
    h5_url = pay_urls['unionpay'] or pay_urls['alipay'] or pay_urls['wechat']
    if not h5_url:
        log(f'[{phone}] 所有支付渠道均失败')
        return None
    report_result(phone, True, order_id=oid, h5_url=h5_url,
                  pay_url_alipay=pay_urls['alipay'], pay_url_wechat=pay_urls['wechat'],
                  pay_url_unionpay=pay_urls['unionpay'])
    return {'success': True, 'phone': phone, 'order_id': oid, 'h5_url': h5_url,
            'pay_url_alipay': pay_urls['alipay'], 'pay_url_wechat': pay_urls['wechat'],
            'pay_url_unionpay': pay_urls['unionpay']}

# ===================== 抢购核心（直连 + 4秒窗口 + 黑号秒换） =====================
def rush_single_account(task, client, rush_count, stop_flag, thread_index=0,
                        task_frequency=100, use_proxy=True, window_start_ts=None):
    """
    单账号抢购，按 rush_count 次数循环（不再按时长窗口）。
    use_proxy=False 时本轮回退直连，不切IP。
    window_start_ts: 窗口开始的目标Unix时间戳，线程会在此时刻精确发出第一发请求

    返回码分类:
    - 2000 = 抢购成功 → 走下单支付流程
    - 其他 → 记录日志并继续/退出
    """
    phone = task['phone']
    # 抢购参数永远直连获取，不走代理（代理慢会卡死整个窗口）
    _saved_proxy = client.proxy
    client.proxy = None
    params = get_item_params(client)
    client.proxy = _saved_proxy
    if params is None:
        # 兜底：非销售时段API返回空，使用数据库中预存的 sku_id 和 activity_id
        sku_id = task.get('sku_id', '')
        act_id = task.get('activity_id', '')
        if sku_id and act_id:
            params = {'item_code': str(sku_id), 'act_id': str(act_id)}
            log(f'[{phone}] ⚠️ API获取商品参数失败，使用预存参数 | skuId={sku_id} | actId={act_id}')
        else:
            log(f'[{phone}] ❌ 无法获取商品参数且无预存值，跳过本轮')
            return None


    # === 精确窗口同步：所有线程在 window_start_ts 时刻同时出发 ===
    # 微错开：每线程间隔5ms（vs 原来250ms），防止同IP并发触发CDN限流
    # 以下准备工作在窗口前完成（代理设置、CDN锁、IP封杀检查）

    # 检查：同代理的其他线程是否已确认IP被CDN封杀
    proxy_ip = task.get('proxy_ip', '')  # 当前账号绑定的代理IP（兼容旧格式）
    proxy_ips = task.get('proxy_ips', [])  # 新格式：每号N个IP列表
    # 向后兼容：旧任务只有 proxy_ip 没有 proxy_ips
    if not proxy_ips and proxy_ip:
        proxy_ips = [proxy_ip]
    # 代理彻底关闭时清空代理IP
    if not _proxy_cache.get('enabled'):
        task['proxy_ip'] = ''
        task['proxy_ips'] = []
        proxy_ips = []
        proxy_ip = ''
        client.proxy = None
        with _client_pool_lock:
            if phone in _client_pool:
                _client_pool[phone].proxy = None
    # === 多IP切换状态 ===
    # 目标站响应日志去重缓存（每次rush_single_account调用重建，避免刷屏）
    _rush_code_cache = {}  # {phone_code: count}
    ip_index = 0  # 当前活跃IP指针
    ip_429_count = {}  # {ip_str: 429次数}
    IP_SWITCH_THRESHOLD = 3  # 连续3次429后切换
    _last_switch_log = 0.0  # 防止刷屏
    if proxy_ips and len(proxy_ips) > 1:
        log(f'[{phone}] 🌐 {len(proxy_ips)}个IP就绪 | 首发: {proxy_ips[0][:30]}')
    # 本轮代理/直连切换
    _saved_proxy = client.proxy
    if not use_proxy:
        client.proxy = None
    elif use_proxy and proxy_ips:
        client.proxy = proxy_ips[0]
    elif use_proxy and proxy_ip:
        client.proxy = proxy_ip

    # ===== ★ 预构建首请求（WASM 签名 + AES 加密），窗口到达瞬间仅发 POST =====
    _first_amount = str(task.get('amount', 1))
    _prebuilt_first = None
    if window_start_ts is not None and params:
        try:
            _prebuilt_first = client.prepare_rush_purchase(
                params['item_code'], params['act_id'], _first_amount)
        except Exception:
            pass  # 失败则回退到常规构建

    # ===== 所有准备完成，精确等待窗口开始 =====
    if window_start_ts is not None:
        stagger_sec = thread_index * 0.005  # 5ms 错开
        target_ts = window_start_ts + stagger_sec
        now = time.time()
        if now < target_ts:
            # 高精度等待：先粗睡到目标前2ms，再自旋等待
            remaining = target_ts - now
            if remaining > 0.003:
                time.sleep(remaining - 0.002)
            while time.time() < target_ts and not stop_flag.is_set():
                pass  # 自旋等待，毫秒级精度

    attempts = 0  # 已发请求次数
    for attempt in range(1, rush_count + 1):  # 按次数循环，不再按时长
        if stop_flag.is_set():
            break
        attempts += 1
        # 频率控制：除首次请求立即发出外，后续都按 task_frequency（毫秒）间隔
        if attempts > 1 and task_frequency > 0:
            time.sleep(task_frequency / 1000.0)  # 快抢间隔（毫秒→秒，后台配置）
        try:
            rush_amount = str(task.get('amount', 1))  # 从数据库读取每个账号的抢购数量
            send_ts = time.time()  # 客户端发出时间（用于验证频率间隔）
            _rush_timeout = 4
            # ★ 首请求使用预构建（跳过 WASM 签名等耗时操作），后续请求常规构建
            _pre = _prebuilt_first if attempt == 1 and _prebuilt_first else None
            r = client.rush_purchase(  # 向i茅台发起抢购请求
                item_code=params['item_code'],       # skuId（API动态获取）
                item_priority_act_id=params['act_id'],  # itemPriorityActId（API动态获取）
                amount=rush_amount,     # 抢购数量（从数据库读取，每个账号可不同）
                timeout=_rush_timeout,   # 统一4秒超时，不传spu_code（IMTP1000313仅用于获取商品详情）
                prebuilt=_pre)
            code = r.get('code', -1)        # 业务码：2000=成功 4030=过期 429=限流
            msg = r.get('message', '')      # 业务消息
            http_status = r.get('_http_status', '?')  # HTTP状态码（200/429/480等）
            raw_text = r.get('_raw_text', '')  # 原始响应体（截取500字符）
            server_time = r.get('_server_time', '')  # 服务器时间（RTT/2补偿毫秒）
            send_str = datetime.fromtimestamp(send_ts).strftime('%H:%M:%S.%f')[:-3]  # 客户端发送时间
            # 打印目标站返回（首次code打印完整body，后续相同code按阈值打摘要）
            _rk = f'{phone}_{code}'
            _same_cnt = _rush_code_cache.get(_rk, 0)
            # 动态抑制阈值：rush_count<=20时每5次打印，否则每10次打印
            _log_threshold = 5 if rush_count <= 20 else 10
            if _same_cnt == 0:
                log(f'[{phone}] #{attempt} HTTP={http_status} code={code} msg={msg} {time.time()-send_ts:.1f}s srv={server_time} | body={raw_text[:200]}')
            elif _same_cnt % _log_threshold == 0:
                log(f'[{phone}] #{attempt} HTTP={http_status} code={code} msg={msg} {time.time()-send_ts:.1f}s (x{_same_cnt+1})')
            _rush_code_cache[_rk] = _same_cnt + 1

            if code == 2000:  # ✅ 抢购接口返回成功
                # 🎯 抢购成功
                report_rush_success(phone, task)  # 通知服务端：此号已中
                result = complete_order_flow(task, client, r)  # 走完下单→支付全流程
                if result and result.get('success'):
                    return result  # 全流程完成，线程结束
                # 下单支付失败不算成功，继续重试
                log(f'[{phone}] 下单/支付失败，继续抢购...')
                continue

            # === 429 IP切换：当前IP连续3次429 → 毫秒切下一个 ===
            if (http_status == 429 or code == 4293) and proxy_ips and len(proxy_ips) > 1:
                cur_ip = proxy_ips[ip_index]
                ip_429_count[cur_ip] = ip_429_count.get(cur_ip, 0) + 1
                cnt = ip_429_count[cur_ip]
                if cnt >= IP_SWITCH_THRESHOLD and ip_index < len(proxy_ips) - 1:
                    ip_index += 1
                    new_ip = proxy_ips[ip_index]
                    client.proxy = new_ip
                    # 新IP 429计数清零
                    ip_429_count[new_ip] = 0
                    if time.time() - _last_switch_log > 0.5:
                        _last_switch_log = time.time()
                        log(f'[{phone}] ⚡ 切IP{ip_index+1}/{len(proxy_ips)} | {cur_ip[:25]}→{new_ip[:25]} (429×{cnt})')
                elif cnt < IP_SWITCH_THRESHOLD:
                    pass  # 未达阈值，继续用当前IP
                # 降级IP：每5个间隔试探1次，看IP是否恢复
                if ip_index > 0 and attempt % 5 == 0:
                    recovered_ip = proxy_ips[ip_index - 1]
                    if ip_429_count.get(recovered_ip, 0) <= IP_SWITCH_THRESHOLD:
                        ip_index -= 1
                        client.proxy = proxy_ips[ip_index]
                        # log(f'[{phone}] ↩ 恢复IP{ip_index+1} {recovered_ip[:25]}')

            # elif code in (4031, 4099) or '请求人数过多' in msg or '库存不足' in msg:
            #     log(f'[{phone}] 黑号判定(code={code})')
            #     report_result(phone, False, error='黑号')
            #     return None
            #
            # elif code in (4293, 429) or http_status == 429 or '人数较多' in msg or '活动未开始' in msg or '未开始' in msg:
            #     log(f'[{phone}] 限流/白号 code={code} msg={msg}')
            #     continue
            #
            # elif code == 4030 or '商品信息不存在' in msg:
            #     log(f'[{phone}] 4030: code={code} msg={msg}')
            #     continue
            #
            # elif code == -1 and ('proxy' in msg.lower() or 'Failed to connect' in msg):
            #     log(f'[{phone}] 代理不可达: {msg[:80]}')
            #     report_result(phone, False, error='代理不可达')
            #     continue
            #
            # elif code == -1:
            #     log(f'[{phone}] 网络错误: {msg[:80]}')
            #     continue
            #
            # else:
            #     log(f'[{phone}] 未知响应 code={code} msg={msg[:80]}')
            #     continue
        except Exception as e:
            import traceback
            log(f'[{phone}] 异常: {e} | {traceback.format_exc().split(chr(10))[-2].strip()}')
            continue

    # 汇总日志：循环结束后打印总请求次数和响应码分布
    if attempts > 0:
        code_summary = ', '.join(f'{k.split("_",1)[1]}×{v}' for k, v in _rush_code_cache.items())
        log(f'[{phone}] 📊 本轮完成: {attempts}次请求 | 响应分布: {code_summary}')
    return {'success': False, 'attempts': attempts, 'phone': phone}

# ===================== 直连客户端实例池 =====================
_client_pool_lock = Lock()
_client_pool = {}  # phone -> MoutaiClient

def get_moutai_client(task):
    """从任务数据构建/复用 MoutaiClient 实例，直连茅台"""
    phone = task['phone']
    with _client_pool_lock:
        if phone in _client_pool:
            return _client_pool[phone]
    # 构建新客户端
    client = MoutaiClient(
        android_id=str(task.get('raw_device_id', ''))[:16] or '',
        bs_dvid=str(task.get('bs_dvid', '')),
        device_index=hash(phone) % 25,
    )
    # 注入服务端下发的凭证
    client.token = str(task.get('token', ''))
    client.cookie = str(task.get('cookie', ''))
    client.user_id = str(task.get('user_id', ''))
    client.mt_device_id = str(task.get('mt_device_id', ''))
    client.raw_device_id = str(task.get('raw_device_id', ''))
    client.user_agent = str(task.get('user_agent', ''))
    client.mt_r = str(task.get('mt_r', ''))
    client.mt_sn = str(task.get('mt_sn', ''))
    client.h5_did = str(task.get('h5_did', ''))
    client.h5_start_id = str(task.get('h5_start_id', ''))
    client.bs_device_id = str(task.get('bs_device_id', ''))
    client.phone = phone
    # ★ webview_ua 必须包含 BS-DVID（服务端下发的 UA 可能不含 BS-DVID，需要追加）
    # BS-DVID 是邦盛设备验证 ID，服务器通过 UA 中的 BS-DVID 校验链路合法性
    # 缺少 BS-DVID 会导致服务器返回"当前链路不支持购买该商品"(code=4030)
    webview_ua = str(task.get('webview_ua', ''))
    bs_dvid = str(task.get('bs_dvid', ''))
    if webview_ua and 'BS-DVID/' not in webview_ua:
        # 服务端下发的 UA 不含 BS-DVID → 需要追加
        if bs_dvid:
            webview_ua += f' BS-DVID/{bs_dvid}'
        else:
            # 服务端也没下发 bs_dvid → 从 mt_device_id 生成（去掉 clips_ 前缀，转 base64url）
            # 真机 BS-DVID 是邦盛 SDK 生成的 base64url 设备令牌
            mt_device = str(task.get('mt_device_id', ''))
            if mt_device.startswith('clips_'):
                # clips_ 后面是标准 base64，需要转换为 base64url（/→_  +→-  去尾部=）
                generated_dvid = mt_device[6:].replace('/', '_').replace('+', '-').rstrip('=')
            else:
                # 无 mt_device_id → 用 raw_device_id 生成
                import base64
                raw_id = str(task.get('raw_device_id', '')) or uuid.uuid4().hex[:16]
                generated_dvid = base64.urlsafe_b64encode(raw_id.encode()).decode().rstrip('=')
            webview_ua += f' BS-DVID/{generated_dvid}'
            bs_dvid = generated_dvid
    elif not webview_ua:
        # 服务端没下发 webview_ua → 使用构造器生成的 UA（已经含 BS-DVID）
        webview_ua = client.webview_ua  # ★ 保留构造器生成的 UA，不能覆盖为空
    client.webview_ua = webview_ua
    client.bs_dvid = bs_dvid
    # 代理：仅在全局代理开启时使用（全局关闭则所有账号直连，不走代理）
    if _proxy_cache.get('enabled'):
        proxy_ip = task.get('proxy_ip', '')
        if proxy_ip:
            client.proxy = proxy_ip
    with _client_pool_lock:
        _client_pool[phone] = client
    return client

# ===================== 异步主调度 =====================
async def async_main():
    global CLIENT_BATCH, _rush_mode, _rush_deadline, NETWORK_ADVANCE
    CLIENT_BATCH = 0
    loop = asyncio.get_event_loop()

    # 1. 注册
    reg = await loop.run_in_executor(None, register_client)
    if reg.get('status') != 'success':
        await asyncio.sleep(5)
        reg = await loop.run_in_executor(None, register_client)

    tasks = reg.get('tasks', [])
    if not tasks:
        log(f'[等待] 当前无可用账号任务，等待服务端分配（每5秒轮询）...')
        _no_task_logged = False
        while not tasks:
            tasks = await loop.run_in_executor(None, fetch_tasks, CLIENT_BATCH)
            if not tasks:
                if not _no_task_logged:
                    _no_task_logged = True
                    log(f'[等待] 持续轮询中，请在网站后台确保有已登录账号且分配到此窗口...')
                await asyncio.sleep(5)

    # 启动部署上报
    report_startup(len(tasks))

    config = await loop.run_in_executor(None, fetch_config)
    # 读取网站配置的抢购时间，动态生成抢购窗口
    rush_hour = config.get('rush_hour', 20)
    rush_minute = config.get('rush_minute', 0)
    rush_second = config.get('rush_second', 0)
    rush_millisecond = config.get('rush_millisecond', 0)
    set_rush_time(rush_hour, rush_minute, rush_second, rush_millisecond)
    task_frequency = config.get('task_frequency', 100)   # 请求频率（毫秒），每次请求间隔
    rush_count = config.get('rush_count', 5)            # 单次抢购次数（每轮每个账号），默认5防止断连时狂刷
    ips_info = f'每号{_ips_per_account}IP' if config.get('proxy_enabled') else '每号IP=直连'
    log(f'[配置] 抢购时间(到达目标站): {target_rush_time()} | 频率: {task_frequency}ms | 次数: {rush_count}/账号/轮 | 窗口: 13轮/每5分钟 | {ips_info}')

    # 1.5 初始化代理配置（从服务端获取代理开关和API地址）—— 必须在构建客户端之前
    await loop.run_in_executor(None, get_pause_status)
    _dist_to_rush = seconds_to_rush_window()
    _in_win = in_rush_window()
    if _proxy_cache.get('enabled'):
        if not _in_win:
            # 不在窗口内 → 立刻拉取IP并预热，抢购10秒前自动停止
            _proxy_prefetch(tasks)
            with _proxy_pool_lock:
                pool_snapshot = list(_proxy_pool)
            if pool_snapshot:
                log(f'[代理] 距抢购{_dist_to_rush:.0f}秒，立即预热IP池({len(pool_snapshot)}个)...')
                warmed, failed = _proxy_warmup(pool_snapshot, stop_before_sec=10)
                with _proxy_pool_lock:
                    for fip in failed:
                        if fip in _proxy_pool:
                            _proxy_pool.remove(fip)
                _assign_proxies_to_tasks(tasks)
                _proxy_window_ready = True
                log(f'[代理] 预热完成: {len(warmed)}个可用, {len(failed)}个丢弃 | 池余{len(_proxy_pool)}个')
            else:
                log(f'[代理] 启动拉取IP为空，等待补拉')
                _proxy_window_ready = False
        else:
            log(f'[代理] 已在窗口内启动，跳过预热直接抢购')
            _proxy_window_ready = False
    else:
        _proxy_window_ready = False

    # 构建直连客户端实例（代理配置已就绪）
    clients = [get_moutai_client(t) for t in tasks]
    # 如果代理开启但客户端未注入（_proxy_cache 刚更新导致），补充注入
    if _proxy_cache.get('enabled'):
        for i, t in enumerate(tasks):
            pip = t.get('proxy_ip', '')
            if pip and not clients[i].proxy:
                clients[i].proxy = pip
    proxy_enabled = _proxy_cache.get('enabled')
    ip_count = sum(1 for t in tasks if t.get('proxy_ips')) if proxy_enabled else 0
    total_ips = sum(len(t.get('proxy_ips', [])) for t in tasks) if proxy_enabled else 0
    ips_per = _ips_per_account
    proxy_str = f'开启(每号{ips_per}IP×{ip_count}号={total_ips}个)' if proxy_enabled and ips_per > 1 else f'开启({ip_count}个IP)' if proxy_enabled else '关闭'
    log(f'[启动] 代理IP={proxy_str} | 频率{task_frequency}ms')
    if ip_count == 0 and not _proxy_cache.get('enabled'):
        log(f'[代理] ⚠️ 无代理IP！{len(tasks)}个账号走同IP，极易触发CDN限流，建议开启代理')
    elif ip_count == 0 and proxy_enabled:
        log(f'[代理] ⚠️ 代理已开启但无可用IP，等待代理上线...')

    for t in tasks:
        ips = t.get('proxy_ips', [])
        ip_label = f'{len(ips)}个IP' if len(ips) > 1 else t.get('proxy_ip', '无')
        log(f'[任务] {t["phone"]} | proxy={ip_label}')
    if proxy_enabled and ip_count > 0:
        _all_ips = list(set(ip for t in tasks for ip in t.get('proxy_ips',[])))
        log(f'[代理] {len(_all_ips)}个唯一IP已写入内存，毫秒级切换: {_all_ips[:5]}{"..." if len(_all_ips)>5 else ""}')

    # 1.6 心跳协程
    hb_running = True
    async def hb_loop():
        while hb_running:
            now = datetime.now()
            # 整点前后10秒静默：xx:59:50 ~ xx:00:10 不心跳，避免干扰抢购
            in_silence = (now.minute == 59 and now.second >= 50) or (now.minute == 0 and now.second <= 10)
            if not in_silence:
                await heartbeat_async(len(tasks))
            await asyncio.sleep(10)
    hb_task = asyncio.create_task(hb_loop())
    log(f'[心跳] 已启动，每10秒上报状态')

    # === 初始时间同步（等待期间完成，不占抢购时间）===
    _cached_offset: float = 0.0
    _last_time_sync: float = 0.0
    TIME_SYNC_INTERVAL = 300  # 5分钟同步一次

    def get_server_ts() -> float:
        """获取当前估计的服务器时间戳(秒)，同时更新网络延迟测量"""
        global NETWORK_ADVANCE
        nonlocal _cached_offset, _last_time_sync, _measured_rtt_half
        now = time.time()
        if now - _last_time_sync > TIME_SYNC_INTERVAL:
            if clients:
                try:
                    _cached_offset = clients[0].sync_server_time()
                    set_server_time_offset(_cached_offset)
                    # ★ 同步更新网络延迟 → 代理切换后延迟变化自动补偿
                    new_rtt_half = getattr(clients[0], '_min_rtt_half', _measured_rtt_half) or _measured_rtt_half
                    if new_rtt_half != _measured_rtt_half:
                        old_advance = NETWORK_ADVANCE
                        NETWORK_ADVANCE = new_rtt_half + NETWORK_PREADVANCE_MS / 1000.0
                        _measured_rtt_half = new_rtt_half
                        if abs(NETWORK_ADVANCE - old_advance) > 0.01:
                            _rebuild_rush_windows()
                            log(f'[时间同步] 延迟变化: {old_advance*1000:.0f}ms → {NETWORK_ADVANCE*1000:.0f}ms，重建抢购窗口')
                except Exception:
                    pass
            _last_time_sync = now
        return now - _cached_offset

    # 启动时立即同步一次 + 测量网络延迟（含代理）
    _measured_rtt_half = 0.15  # 默认单向延迟 0.15s（RTT/2）
    if clients:
        try:
            _cached_offset = await loop.run_in_executor(None, clients[0].sync_server_time)
            _last_time_sync = time.time()
            set_server_time_offset(_cached_offset)  # 写入全局变量，供 in_rush_window() 使用
            # ★ 读取实测 RTT/2（通过代理或直连的单程延迟），动态调整 NETWORK_ADVANCE
            _measured_rtt_half = getattr(clients[0], '_min_rtt_half', 0.15) or 0.15
            old_advance = NETWORK_ADVANCE
            NETWORK_ADVANCE = _measured_rtt_half + NETWORK_PREADVANCE_MS / 1000.0  # 物理延迟 + 预提前量
            if NETWORK_ADVANCE != old_advance:
                _rebuild_rush_windows()
            _speed = "快" if _cached_offset > 0 else "慢"
            log(f'[时间同步] 偏差={_cached_offset:+.3f}s (本地{_speed}于服务器)')
            log(f'[网络延迟] 单程={_measured_rtt_half*1000:.0f}ms (RTT={_measured_rtt_half*2*1000:.0f}ms) → 提前量={NETWORK_ADVANCE*1000:.0f}ms | 旧={old_advance*1000:.0f}ms')
        except Exception as e:
            log(f'[时间同步] 失败: {e}')

    succeeded_phones = set()
    pool = ThreadPoolExecutor(max_workers=min(len(tasks) * 2, 200))

    NETWORK_LATENCY = 0.20   # 预估网络延迟（秒）
    # RUSH_WINDOW 不再用于循环时长，改为 rush_count 驱动；保留安全超时用于线程兜底
    round_num = 0

    cycle_num = 0
    _round_use_proxy = False  # 代理/直连交替：首轮走代理，not后变True
    while True:
        cycle_num += 1

        # 检查暂停
        status = await loop.run_in_executor(None, get_pause_status)
        if status.get('paused'):
            log('[暂停] 服务端暂停中，等待10秒...')
            await asyncio.sleep(10)
            continue

        # === 刷新配置+拉取新任务（首轮跳过）===
        if cycle_num > 1:
            try:
                new_cfg = await loop.run_in_executor(None, fetch_config)
                if new_cfg:
                    rh = new_cfg.get('rush_hour', 20)
                    rm = new_cfg.get('rush_minute', 0)
                    rs = new_cfg.get('rush_second', 0)
                    rms = new_cfg.get('rush_millisecond', 0)
                    set_rush_time(rh, rm, rs, rms)
                    task_frequency = new_cfg.get('task_frequency', 100)
                    rush_count = new_cfg.get('rush_count', 5)
            except Exception:
                pass
            try:
                new_tasks = await loop.run_in_executor(None, fetch_tasks, CLIENT_BATCH)
                if new_tasks:
                    _assign_proxies_to_tasks(new_tasks)
                    old_phones = {t['phone'] for t in tasks}
                    new_phones = {t['phone'] for t in new_tasks}
                    if old_phones != new_phones or len(tasks) != len(new_tasks):
                        log(f'[任务] 收到{len(new_tasks)}个新任务，刷新账号列表')
                        tasks = new_tasks
                        with _client_pool_lock:
                            _client_pool.clear()
                        clients = [get_moutai_client(t) for t in tasks]
                    else:
                        tasks = new_tasks
            except Exception:
                pass

        # 过滤已成功的账号（必须在任务刷新之后，否则 active 索引可能越界）
        active = [(i, t) for i, t in enumerate(tasks) if t['phone'] not in succeeded_phones]
        if not active:
            log('全部账号已成功，退出')
            break

        round_num += 1

        # === 时间同步 ===
        server_now = get_server_ts()
        effective_latency = NETWORK_LATENCY + max(0, _cached_offset)

        # === 代理IP补拉（正常情况由轮次结束后预热自动处理，此处仅应急）===
        if _proxy_cache.get('enabled'):
            dist = seconds_to_rush_window()
            in_win = in_rush_window()
            need_refresh = False
            refresh_reason = ''
            if _rush_mode == 0:
                if time.time() - _last_proxy_fetch > 120:
                    need_refresh = True
            elif _rush_mode == 1:
                # 池空 → 紧急补拉
                with _proxy_pool_lock:
                    pool_empty = not _proxy_pool
                if pool_empty and not _proxy_window_ready:
                    need_refresh = True
                    refresh_reason = '⚠️ 代理池为空，紧急补拉'
            if need_refresh:
                if refresh_reason:
                    log(f'[代理] {refresh_reason}')
                else:
                    log(f'[代理] 刷新代理IP（距抢购{dist:.0f}秒）')
                _proxy_prefetch(tasks)
                _proxy_window_ready = True
                # ★ 代理分配后：更新 clients 代理 + 强制重测延迟，确保 NETWORK_ADVANCE 使用真实代理延迟
                if clients and _proxy_cache.get('enabled'):
                    _need_resync = False
                    for i, t in enumerate(tasks):
                        if i < len(clients):
                            proxy_ip = t.get('proxy_ip', '')
                            if proxy_ip and clients[i].proxy != proxy_ip:
                                clients[i].proxy = proxy_ip
                                _need_resync = True
                    if _need_resync:
                        try:
                            new_offset = await loop.run_in_executor(None, clients[0].sync_server_time)
                            _cached_offset = new_offset
                            set_server_time_offset(_cached_offset)
                            new_rtt = getattr(clients[0], '_min_rtt_half', _measured_rtt_half) or _measured_rtt_half
                            if new_rtt != _measured_rtt_half:
                                old_advance = NETWORK_ADVANCE
                                _measured_rtt_half = new_rtt
                                NETWORK_ADVANCE = new_rtt + NETWORK_PREADVANCE_MS / 1000.0
                                _rebuild_rush_windows()
                                log(f'[代理延迟] 更新: 单程={new_rtt*1000:.0f}ms → 提前量={NETWORK_ADVANCE*1000:.0f}ms (旧={old_advance*1000:.0f}ms)')
                        except Exception as e:
                            log(f'[代理延迟] 测量失败: {e}')

        # ==================== 分支：快窗口 vs 慢探测 ====================
        # 抢购模式关闭(0): 强制进入快窗口，解除所有时间限制
        # 抢购模式开启(1): 按正常窗口判断 + 截止时间检查
        if _rush_mode == 0 or in_rush_window() or seconds_to_rush_window() <= RUSH_PRESTART:
            # 抢购模式开启时，先确保获取截止时间（只执行一次）
            if _rush_mode == 1 and _rush_deadline <= 0:
                log(f'[抢购模式] 获取截止时间...')
                for idx, task in active[:min(3, len(active))]:
                    try:
                        info = await loop.run_in_executor(None, clients[idx].auto_fetch_item_details, ITEM_CODE, '')
                        if info:
                            stl = info.get('startTimeList', [])
                            if stl:
                                _rush_deadline = max(stl) / 1000.0
                                log(f'  ⏰ 截止时间(API): {datetime.fromtimestamp(_rush_deadline).strftime("%H:%M:%S")} | '
                                    f'商品: {info.get("item_name","?")} | '
                                    f'库存: {info.get("inventory",0)} | '
                                    f'actId: {info.get("activity_id","?")}')
                                break
                    except Exception:
                        pass
                if _rush_deadline <= 0:
                    # startTimeList 为空时，用客户端窗口定义的最后窗口结束时间兜底
                    if _RUSH_WINDOWS:
                        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                        _rush_deadline = today_start.timestamp() + _RUSH_WINDOWS[-1][1]
                        log(f'  ⚠️ startTimeList 为空，兜底截止时间: {datetime.fromtimestamp(_rush_deadline).strftime("%H:%M:%S")} '
                            f'(来源: 客户端窗口定义第{len(_RUSH_WINDOWS)}轮结束)')
                    else:
                        log(f'  ⚠️ startTimeList 为空且无窗口定义，截止时间未设置')

            # 抢购模式开启时，检查截止时间
            if _rush_mode == 1 and _rush_deadline > 0 and time.time() > _rush_deadline:
                log(f'⏰ 已过截止时间 {datetime.fromtimestamp(_rush_deadline).strftime("%H:%M:%S")}，停止所有抢购')
                break

            # ========== 快窗口：抢购 ==========
            # 抢购前10秒：模拟浏览商品页面（真实手机打开APP→进入商品页→等待抢购）
            dist = seconds_to_rush_window()
            if not in_rush_window() and dist > 3.0:
                # log(f'📱 模拟浏览商品页面（距抢购{dist:.1f}秒，目标={current_window_target()}）...')
                for idx, task in active[:min(3, len(active))]:
                    try:
                        info = await loop.run_in_executor(None, clients[idx].auto_fetch_item_details, ITEM_CODE, '')
                        if info:
                            # 抢购模式开启时，从 startTimeList 提取截止时间
                            if _rush_mode == 1:
                                stl = info.get('startTimeList', [])
                                if stl:
                                    _rush_deadline = max(stl) / 1000.0
                            #         log(f'  ⏰ 截止时间: {datetime.fromtimestamp(_rush_deadline).strftime("%H:%M:%S")}')
                            # log(f'  📦 商品信息: {info.get("item_name","?")} | '
                            #     f'价格: ¥{info.get("price",0)} | '
                            #     f'库存: {info.get("inventory",0)} | '
                            #     f'skuId: {info.get("default_sku_id","?")} | '
                            #     f'itemCode: {info.get("item_code_from_api","?")} | '
                            #     f'actId: {info.get("activity_id","?")}')
                    except Exception:
                        pass

            # ===== 抢购前准备：全部在窗口前完成，窗口到达瞬间只发请求 =====
            # 参数预取（线程内 get_item_params 命中缓存 ≈0ms）
            if active:
                await loop.run_in_executor(None, get_item_params, clients[active[0][0]])
            # 连接预热（邦盛验证，每10轮做一次，距抢购<20秒则跳过避免错过窗口）
            if (cycle_num == 1 or cycle_num % 10 == 1) and seconds_to_rush_window() > 20:
                for idx, task in active:
                    try:
                        await loop.run_in_executor(None, clients[idx].warmup_connections)
                    except Exception:
                        pass

            _round_use_proxy = not _round_use_proxy
            proxy_enabled = _proxy_cache.get('enabled')
            _first_proxy = next((t.get('proxy_ips',[t.get('proxy_ip','')])[0] if t.get('proxy_ips') else t.get('proxy_ip','') for _, t in active if t.get('proxy_ip')), '')
            _use_proxy_this_round = proxy_enabled and _round_use_proxy

            lock_parts = []
            for _, t in active:
                ips = t.get('proxy_ips', [])
                pip = ips[0] if ips else t.get('proxy_ip', '')
                lock_parts.append(f'{t["phone"]}={_proxy_label(pip if _use_proxy_this_round else "")}')

            # 计算窗口开始的精确 Unix 时间戳
            # 调试模式(_rush_mode==0)：立即发请求，不等待真实窗口
            if _rush_mode == 0:
                dist = 0.0
                window_start_ts = time.time()
            else:
                dist = max(0.0, seconds_to_rush_window())
                window_start_ts = time.time() + dist

            t0 = time.time()
            stop_flag = Event()
            safety_window = rush_count * max(task_frequency / 1000.0, 0.05) * 2 + 30

            # ★ 异步抢购模式：每个IP独立线程并发抢购
            # 轮询模式：每账号1个线程，内部IP轮换
            # 异步模式：每账号N个线程（N=IP数），每个线程绑定1个IP，全部并发
            futures = []
            if _async_rush and proxy_enabled:
                # ★ 异步模式：每个IP一个独立线程
                for i, (idx, task) in enumerate(active):
                    proxy_ips = task.get('proxy_ips', [])
                    if not proxy_ips:
                        # 无代理IP → 单线程直连
                        futures.append((pool.submit(rush_single_account, task, clients[idx], rush_count, stop_flag,
                                                   i, task_frequency,
                                                   False, window_start_ts), task, None))
                    else:
                        for j, ip in enumerate(proxy_ips):
                            # 为每个IP创建独立的客户端实例（线程安全）
                            ip_task = dict(task)  # 浅拷贝任务，修改proxy字段
                            ip_task['proxy_ip'] = ip
                            ip_task['proxy_ips'] = [ip]  # 只绑定这一个IP
                            ip_client = get_moutai_client(ip_task)
                            ip_client.proxy = ip  # 固定此IP
                            futures.append((pool.submit(rush_single_account, ip_task, ip_client, rush_count, stop_flag,
                                                       i * len(proxy_ips) + j, task_frequency,
                                                       True, window_start_ts), task, ip))
                if futures:
                    _total_threads = len(futures)
                    _total_ips = sum(len(t.get('proxy_ips', [])) or 1 for _, t in active)
                    log(f'[异步抢购] {len(active)}个账号 × {_total_ips}个IP = {_total_threads}个线程并发 | 每线程{rush_count}次 | 总请求{_total_threads * rush_count}次')
            else:
                # ★ 轮询模式：每账号1个线程
                for i, (idx, task) in enumerate(active):
                    futures.append((pool.submit(rush_single_account, task, clients[idx], rush_count, stop_flag,
                                               i, task_frequency,
                                               _use_proxy_this_round, window_start_ts), task, None))

            # 等到窗口时刻再打日志（调试模式跳过等待）
            remaining = window_start_ts - time.time()
            if remaining > 0.01 and _rush_mode != 0:
                await asyncio.sleep(remaining + 0.002)

            deadline = t0 + safety_window + 5
            results = []
            for f, task, ip in futures:
                try:
                    results.append((f.result(timeout=max(0, deadline - time.time())), task, ip))
                except Exception:
                    results.append((None, task, ip))
            stop_flag.set()

            success_count = 0
            total_attempts = 0
            for result, task, ip in results:
                if result and result.get('success'):
                    succeeded_phones.add(task['phone'])
                    success_count += 1
                if result and isinstance(result, dict):
                    total_attempts += result.get('attempts', 0)
            t0_str = datetime.fromtimestamp(t0).strftime('%H:%M:%S.%f')[:-3]
            end_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            log(f'[请求:{t0_str}] 抢购结果: {success_count}/{len(active)}成功 | 总请求{total_attempts}次 | 累计{len(succeeded_phones)} | {time.time()-t0:.1f}s [服务器:{end_str}]')

            # 等待当前窗口彻底结束（调试模式不等待）
            if _rush_mode != 0:
                while in_rush_window():
                    await asyncio.sleep(0.3)
                # ★ 窗口结束后立即预热IP为下一轮准备，抢购10秒前自动停止
                if _proxy_cache.get('enabled'):
                    with _proxy_pool_lock:
                        pool_snapshot = list(_proxy_pool)
                    if pool_snapshot:
                        log(f'[代理] 本轮结束，立即预热IP池({len(pool_snapshot)}个)为下一轮准备...')
                        warmed, failed = _proxy_warmup(pool_snapshot, stop_before_sec=10)
                        # 剔除失败IP
                        with _proxy_pool_lock:
                            for fip in failed:
                                if fip in _proxy_pool:
                                    _proxy_pool.remove(fip)
                        # 重新分配预热好的IP
                        _assign_proxies_to_tasks(tasks)
                        _proxy_window_ready = True
                        if failed:
                            log(f'[代理] 预热: {len(warmed)}个可用, {len(failed)}个丢弃 | 池余{len(_proxy_pool)}个')
                        else:
                            log(f'[代理] 预热: {len(warmed)}个全部可用 | 池余{len(_proxy_pool)}个')

        else:
            dist = seconds_to_rush_prestart()
            if dist > 0:
                await asyncio.sleep(min(dist, 60))

    pool.shutdown(wait=False)
    hb_running = False
    try:
        await asyncio.wait_for(hb_task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        hb_task.cancel()
    log(f'抢购结束 | 成功:{len(succeeded_phones)}')

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        log('[客户端] 中断')
    except BaseException as e:
        log(f'[客户端] 致命异常({type(e).__name__}): {e}')
        import traceback; traceback.print_exc()
    finally:
        # EXE 运行结束后保持窗口，防止闪退（Linux nohup模式自动跳过）
        if sys.stdin is not None and sys.stdin.isatty():
            log('按回车键退出...')
            try: input()
            except: pass

if __name__ == '__main__':
    main()
