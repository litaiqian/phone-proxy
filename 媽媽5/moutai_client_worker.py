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
from services.local_ip_pool import local_ip_pool

# 直连猫猫：导入 demo.py 的 MoutaiClient
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo import MoutaiClient

# 养号模块
from nurture_account import run_nurture_cycle, get_nurture_manager, \
    set_server_config, sync_bindings_from_server, get_device_index_for_phone

# ===================== 日志系统 =====================
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
_log_lock = threading.Lock()
_log_buffer = []  # 内存缓冲，抢购中不写文件
_rushing = False   # 抢购进行中标志

_STARTUP_TIME = datetime.now().strftime('%d')
_STARTUP_PUBLIC_IP = ''  # 启动时获取一次

# 启动时立即获取公网IP，用于日志文件名
try:
    for _url in ['http://api.ipify.org', 'http://ifconfig.me', 'http://icanhazip.com']:
        try:
            _STARTUP_PUBLIC_IP = requests.get(_url, timeout=4).text.strip()
            if _STARTUP_PUBLIC_IP:
                break
        except Exception:
            continue
except Exception:
    _STARTUP_PUBLIC_IP = 'unknown'

def _log_prefix():
    """日志文件前缀: 日_公网IP_UUID"""
    return f'{_STARTUP_TIME}_{_STARTUP_PUBLIC_IP}_{CLIENT_UUID}'

def _log_file():
    """日志文件路径: logs/日_公网IP_UUID.txt"""
    prefix = _log_prefix()
    return os.path.join(LOG_DIR, f'{prefix}.txt')

def _log_flush():
    """将缓冲区日志一次性写入文件"""
    if not _log_buffer:
        return
    log_file = _log_file()
    with _log_lock:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.writelines(_log_buffer)
        except:
            pass
    _log_buffer.clear()

def log(msg, srv_time=''):
    """打印日志，抢购中缓冲、非抢购时立即写文件。
    自动附加当前线程的模式标签：[代理]IP / [直连]
    srv_time: CDN/目标站返回时间 (HH:MM:SS.ms)"""
    # 附加模式标签
    tag = _thread_mode_tag()
    if tag:
        msg = msg + tag
    if srv_time:
        msg = msg + f' | srv={srv_time}'
    now = datetime.now()
    ts = now.strftime('%H:%M:%S.') + f'{now.microsecond // 1000:03d}'
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    if _rushing:
        _log_buffer.append(line + '\n')
    else:
        with _log_lock:
            try:
                with open(_log_file(), 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except:
                pass

# ===================== 线程日志上下文（自动附加模式标签）=====================
_thread_ctx = {}  # {thread_id: {'phone': '', 'proxy_ip': ''}}
_thread_ctx_lock = threading.Lock()

def set_thread_ctx(phone='', proxy_ip=''):
    """设置当前线程的日志上下文（抢购线程调用）"""
    with _thread_ctx_lock:
        _thread_ctx[threading.current_thread().ident] = {'phone': phone, 'proxy_ip': proxy_ip}

def _proxy_label(proxy_ip):
    """根据代理IP返回标签：[代理]IP / [直连]"""
    if not proxy_ip:
        return '[直连]'
    return f'[代理]{proxy_ip}'

def _thread_mode_tag():
    """获取当前线程的模式标签"""
    tid = threading.current_thread().ident
    with _thread_ctx_lock:
        ctx = _thread_ctx.get(tid, {})
    proxy = ctx.get('proxy_ip', '')
    if proxy:
        return f' [代理]{proxy}'
    if ctx.get('phone'):
        return ' [直连]'
    return ''

def log_rush_start():
    """标记抢购开始，日志只缓冲不写文件"""
    global _rushing
    _rushing = True

def log_rush_end():
    """标记抢购结束，一次性刷出缓冲区到文件"""
    global _rushing
    _rushing = False
    _log_flush()

# ===================== 配置 =====================
BAKED_USER_ID = 0
if BAKED_USER_ID > 0:
    UPLOADER_ID = BAKED_USER_ID
    SERVER_BASE_URL = "http://ipla.top:5000"
    BRIDGE_BASE_URL = "http://ipla.top:5000"
    API_TOKEN = "your-secure-token-change-me"
else:
    import argparse
    def parse_args():
        p = argparse.ArgumentParser(description='抢购客户端 v4')
        p.add_argument('--user-id', type=int, default=2)
        p.add_argument('--server', type=str, default='http://ipla.top:5000')
        p.add_argument('--bridge', type=str, default='http://ipla.top:5000')
        p.add_argument('--token', type=str, default='m9Xk2vLp7Qr4Wn8YbT1cFh6Jd')
        return p.parse_args()
    _a = parse_args()
    UPLOADER_ID, SERVER_BASE_URL, BRIDGE_BASE_URL, API_TOKEN = _a.user_id, _a.server, _a.bridge, _a.token

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
log(f'[启动] 主机={HOSTNAME} | UUID={CLIENT_UUID} | 日志目录={LOG_DIR}')

ITEM_CODE = "IMTP1000313"

# ===================== 商品信息查询（独立测试函数，不用可删） =====================
def print_product_info(spu_code="IMTP1000313", phone=None):
    """
    打印商品完整信息：名称、价格、skuId、itemCode、actId、库存、收货地址等。
    自动加载本地已登录账号的 token/cookie 来获取完整购买信息。

    参数:
        spu_code: 商品 SPU 编码，如 "IMTP1000313"
        phone:    手机号，如 "18628877222"。传入则精确匹配该账号；
                  不传则使用第一个已登录账号。
    """
    import json as _json, os as _os
    from demo import MoutaiClient

    # 尝试从本地账号文件加载登录态
    client = MoutaiClient()
    account_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'iplala_accounts.json')
    found_phone = None
    if _os.path.exists(account_file):
        try:
            accounts = _json.load(open(account_file, 'r', encoding='utf-8'))
            # 如果指定了手机号，先精确匹配；否则取第一个已登录账号
            for acc in accounts:
                acc_phone = acc.get('mobile', acc.get('phone', ''))
                if phone:
                    if acc_phone == phone and acc.get('token') and acc.get('cookie'):
                        found_phone = acc_phone
                else:
                    if acc.get('token') and acc.get('cookie'):
                        found_phone = acc_phone
                if found_phone:
                    client.token = acc['token']
                    client.cookie = acc['cookie']
                    client.user_id = str(acc.get('userid', ''))
                    client.phone = acc_phone
                    # 恢复设备指纹，否则 H5 接口会因设备不匹配被拒
                    if acc.get('device-id'):
                        client.raw_device_id = acc['device-id']
                    if acc.get('mt-device-id'):
                        client.mt_device_id = acc['mt-device-id']
                    if acc.get('h5-did'):
                        client.h5_did = acc['h5-did']
                    if acc.get('h5-start-id'):
                        client.h5_start_id = acc['h5-start-id']
                    if acc.get('bs-device-id'):
                        client.bs_device_id = acc['bs-device-id']
                    if acc.get('mt-r'):
                        client.mt_r = acc['mt-r']
                    if acc.get('mt-sn'):
                        client.mt_sn = acc['mt-sn']
                    if acc.get('user-agent'):
                        client.user_agent = acc['user-agent']
                    if acc.get('webview-ua'):
                        client.webview_ua = acc['webview-ua']
                    break
        except Exception:
            pass
    if phone and not found_phone:
        print(f"\n  ⚠️  未找到手机号 {phone} 的已登录账号！\n")

    detail = client.get_item_detail_v2(spu_code)
    purchase = client.get_purchase_info_v2(spu_code)
    full = client.auto_fetch_item_details(spu_code)
    addresses = client.get_addresses() if client.token else []

    print(f"\n{'='*60}")
    print(f"  商品编号(SPU): {spu_code}")
    if client.token:
        print(f"  登录账号: {client.phone or '(已登录)'}")
    print(f"{'='*60}")

    # 基础信息 (detailV2)
    if detail:
        print(f"  📦 商品名称: {detail.get('title', '未知')}")
        print(f"  💰 价格: ¥{detail.get('price', 0)}")
        print(f"  🔢 默认规格ID(skuId): {detail.get('default_sku_id', '未知')}")
    else:
        print(f"  ⚠️  基础信息获取失败")

    # 抢购三参数 (auto_fetch_item_details) — 带登录态能拿到完整数据
    sku_id = full.get('default_sku_id', '') or full.get('sku_id', '')
    item_code_rush = full.get('item_code_from_api', '')
    act_id = full.get('activity_id', '')
    print(f"\n  {'─'*50}")
    print(f"  🎯 抢购参数 (API实时):")
    print(f"  {'─'*50}")
    print(f"  skuId       = {sku_id or '未获取到'}")
    print(f"  itemCode    = {item_code_rush or '未获取到'}")
    print(f"  actId(活动)  = {act_id or '未获取到'}")
    if full.get('inventory'):
        print(f"  inventory   = {full['inventory']}")

    # 购买信息 (purchaseInfoV2) — 包含库存、活动、规格等
    if purchase:
        item_info = purchase.get('itemInfo', {})
        if item_info:
            print(f"  🏷️  分类: {item_info.get('categoryName', '')} / {item_info.get('brandName', '')}")
            spec_list = item_info.get('specList', [])
            for spec in spec_list:
                print(f"  📏 {spec.get('specName', '')}: {spec.get('specValue', '')}")

        purchase_info_map = purchase.get('purchaseInfoMap', {})
        print(f"\n  {'─'*50}")
        print(f"  📊 可购规格 & 库存:")
        print(f"  {'─'*50}")
        for sku_key, sku_data in purchase_info_map.items():
            pinfo = sku_data.get('purchaseInfo', {})
            disabled = pinfo.get('disable', False)
            inventory = pinfo.get('inventory', 0)
            p_act_id = pinfo.get('itemPriorityActId', '')
            status = '❌ 已禁用' if disabled else f'✅ 库存 {inventory}'
            print(f"  itemCode={sku_key} | actId={p_act_id} | {status}")

        # 可购总量
        total_available = sum(
            si.get('purchaseInfo', {}).get('inventory', 0)
            for si in purchase_info_map.values()
            if not si.get('purchaseInfo', {}).get('disable', False)
        )
        print(f"  {'─'*50}")
        print(f"  🎯 可购总库存: {total_available}")
    else:
        print(f"  ⚠️  购买信息(库存/活动详情)获取失败（需登录态）")

    # 收货地址 (get_addresses)
    if addresses:
        print(f"\n  {'─'*50}")
        print(f"  📍 收货地址:")
        print(f"  {'─'*50}")
        for i, addr in enumerate(addresses):
            dft = " ⭐默认" if addr.get('dft') else ""
            print(f"  [{i}] id={addr.get('shipAddressId')}")
            print(f"      {addr.get('provinceName','')}{addr.get('cityName','')}"
                  f"{addr.get('districtName','')} {addr.get('address','')}")
            print(f"      收件人: {addr.get('name','')}  电话: {addr.get('mobile','')}{dft}")
    else:
        print(f"\n  ⚠️  未获取到收货地址（需登录态）")

    print(f"{'='*60}\n")


# 抢购轮次间隔（每轮抢购后等待的秒数）
RUSH_ROUND_INTERVAL = 5

# ===================== HTTP 工具 =====================
_HEADERS = {'X-API-TOKEN': API_TOKEN, 'Content-Type': 'application/json'}
_session_local = threading.local()

def _get_session():
    if not hasattr(_session_local, 'session'):
        s = requests.Session()
        s.headers.update(_HEADERS)
        from requests.adapters import HTTPAdapter
        s.mount('http://', HTTPAdapter(pool_connections=50, pool_maxsize=200, max_retries=0))
        s.mount('https://', HTTPAdapter(pool_connections=50, pool_maxsize=200, max_retries=0))
        _session_local.session = s
    return _session_local.session

def _get(url, timeout=5):
    try: return _get_session().get(url, timeout=timeout).json()
    except: return {'status': 'error'}

def _post(url, data=None, timeout=10):
    try:
        resp = _get_session().post(url, json=data or {}, timeout=timeout)
        return resp.json()
    except Exception as e:
        log(f'[HTTP] POST {url} 失败: {e}')
        return {'status': 'error'}

# ===================== 桥接 =====================
_proxy_cache = {'enabled': False, 'url': ''}

def bridge_call(method, params=None, credentials=None, proxy_ip=''):
    payload = {'method': method, 'params': params or {}, 'credentials': credentials or {}}
    # 优先使用账号绑定的代理IP(socks5://ip:port)，其次使用全局代理
    # 账号级IP用于IP多样性，全局开关不影响已分配IP的使用
    if proxy_ip:
        payload['proxy_url'] = proxy_ip
    elif _proxy_cache.get('enabled') and _proxy_cache.get('url'):
        payload['proxy_url'] = _proxy_cache['url']
    try:
        r = _get_session().post(f'{BRIDGE_BASE_URL}/api/bridge/execute', json=payload, timeout=12)
        return r.json()
    except:
        return {'success': False, 'error': 'bridge unreachable'}

# ===================== 滑块验证（服务端集中求解） =====================

def slider_solve(captcha_id, bg_url, fg_url, timeout=35):
    """
    调用服务端滑块求解 API
    返回: (success:bool, validate:str|None)
    """
    try:
        r = _get_session().post(
            f'{SERVER_BASE_URL}/api/client/slider_solve',
            json={'captchaId': captcha_id, 'bgUrl': bg_url, 'fgUrl': fg_url},
            timeout=timeout
        ).json()
        if r.get('success') and r.get('validate'):
            return True, r['validate']
        return False, r.get('error', '未知错误')
    except Exception as e:
        return False, str(e)


# ===================== 参数缓存（直连） =====================
_item_cache_lock, _item_cache = Lock(), {'data': None, 'ts': 0}
CACHE_TTL = 7200  # 2小时缓存

def get_item_params(client):
    """直连猫猫API获取商品参数，不走桥接。
    全部参数从 API 实时获取，不使用任何硬编码兜底值。
    API 失败时重试最多 3 次，全部失败返回 None。"""
    now = time.time()
    with _item_cache_lock:
        if _item_cache['data'] and (now - _item_cache['ts']) < CACHE_TTL:
            return _item_cache['data']
    for attempt in range(3):
        try:
            # 清除客户端缓存确保每次重试都真正请求 API（auto_fetch_item_details 会缓存不完整结果）
            if attempt > 0:
                client._item_detail_cache.clear()
            r = client.auto_fetch_item_details(ITEM_CODE)
            sku_id = r.get('default_sku_id', '') or ''
            item_code_rush = r.get('item_code_from_api', '') or ''
            act_id = r.get('activity_id', '') or ''
            if sku_id and item_code_rush and act_id:
                data = {'sku_id': sku_id, 'item_code_rush': item_code_rush, 'act_id': act_id}
                with _item_cache_lock:
                    _item_cache['data'], _item_cache['ts'] = data, now
                log(f'[参数] API获取成功 | skuId={sku_id} | itemCode={item_code_rush} | actId={act_id}')
                return data
            else:
                log(f'[参数] API返回数据不完整(第{attempt+1}次): sku_id={sku_id}, item_code={item_code_rush}, act_id={act_id}')
        except Exception as e:
            log(f'[参数] API调用异常(第{attempt+1}次): {e}')
        if attempt < 2:
            time.sleep(0.005)
    log(f'[参数] ❌ 3次重试均失败，无法获取商品参数！')
    return None

# ===================== CDN穿透探测 =====================
_account_cdn_mode = {}  # phone -> 'direct' 或 proxy_ip字符串
_account_cdn_mode_lock = Lock()
_account_429_blocked = {}  # phone -> True（CDN探测到429限流，本轮跳过）
_account_429_blocked_lock = Lock()
_probe_use_proxy_alt = False  # 慢速探测时直连/代理交替

def preload_local_ip_pool(target=100):
    """预加载IP到本地内存池（慢速期后台调用，仅代理开启时有效）
    返回就绪IP数量"""
    if not _proxy_cache.get('enabled') or not _proxy_cache.get('url'):
        return 0
    return local_ip_pool.preload(
        target_count=target,
        fetch_url=_proxy_cache['url'],
        bridge_base_url=BRIDGE_BASE_URL
    )

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

# 抢购请求提前发送量（秒）= 预估网络延迟
# 请求在配置时间前 NETWORK_ADVANCE 秒发出，到达目标站 ≈ 配置的抢购时间，调时间..李李
NETWORK_ADVANCE = 0.3

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
# 抢购截止时间（Unix秒），从 startTimeList 最后一个时间点提取
_rush_deadline = 0.0

def seconds_to_rush_prestart():
    """返回到快窗口前 RUSH_PRESTART 秒的秒数。已进入预启动区返回0"""
    dist = seconds_to_rush_window()
    return max(0, dist - RUSH_PRESTART)

# ===================== 服务端API =====================
def fetch_config():
    global _rush_mode
    r = _get(f'{SERVER_BASE_URL}/api/client/get_config?uploader_id={UPLOADER_ID}')
    if r.get('rush_paused') is not None:
        _rush_mode = r.get('rush_mode', 0)
        return r
    _rush_mode = 0
    return {'rush_paused': 0, 'proxy_enabled': False, 'proxy_url': '', 'multi_open_count': 1, 'multi_open_enabled': False}

def get_pause_status():
    global _proxy_cache
    r = _get(f'{SERVER_BASE_URL}/api/client/get_pause_status?uploader_id={UPLOADER_ID}')
    if r.get('paused') is not None:
        _proxy_cache = {
            'enabled': r.get('proxy_enabled', False),
            'url': r.get('proxy_url', ''),
        }
        return r
    return {'paused': 0, 'proxy_enabled': False, 'proxy_url': ''}

def register_client():
    global CLIENT_BATCH
    r = _post(f'{SERVER_BASE_URL}/api/client/register', {'client_uuid': CLIENT_UUID, 'uploader_id': UPLOADER_ID, 'hostname': HOSTNAME})
    if r.get('status') == 'success':
        CLIENT_BATCH = r.get('batch', 0)
        log(f'[注册] 窗口={CLIENT_BATCH+1}, UUID={CLIENT_UUID}, 任务={len(r.get("tasks",[]))}')
    else:
        log(f'[注册] 失败! 状态={r.get("status")} URL={SERVER_BASE_URL}/api/client/register')
    return r

def fetch_tasks(batch=0):
    r = _post(f'{SERVER_BASE_URL}/api/client/get_tasks', {'uploader_id': UPLOADER_ID, 'batch': batch})
    if r.get('status') == 'success':
        return r.get('tasks', [])
    log(f'[任务] 获取失败! 状态={r.get("status")}')
    return []

def request_replacement_tasks(succeeded_phones, request_count=1):
    r = _post(f'{SERVER_BASE_URL}/api/client/request_replacement_tasks', {
        'client_uuid': CLIENT_UUID, 'succeeded_phones': succeeded_phones,
        'request_count': request_count, 'uploader_id': UPLOADER_ID})
    tasks = r.get('tasks', []) if r.get('status') == 'success' else []
    if tasks: log(f'[继续分配] +{len(tasks)}账号')
    return tasks

def report_result(phone, success, order_id='', h5_url='', error='', ip_blocked=False, account_black=False):
    _post(f'{SERVER_BASE_URL}/api/client/report_result', {
        'phone': phone, 'success': success, 'order_id': order_id,
        'h5_url': h5_url, 'error': error,
        'ip_blocked': ip_blocked, 'account_black': account_black})

def report_ip_blocked_and_replace(phone, blocked_ip, uploader_id=0):
    """实时IP切换：上报被封IP给服务端，获取并测试新IP
    返回 (new_ip, client) 或 (None, None) 如果无可用IP"""
    # 全局代理关闭时不进行IP切换
    if not _proxy_cache.get('enabled'):
        log(f'[{phone}] 全局代理已关闭，跳过IP切换')
        return None, None
    try:
        r = _post(f'{SERVER_BASE_URL}/api/client/report_ip_blocked', {
            'phone': phone, 'blocked_ip': blocked_ip, 'uploader_id': uploader_id
        }, timeout=6)
        if r.get('status') == 'success' and r.get('new_ip'):
            new_ip = r['new_ip']
            log(f'[{phone}] IP切换: {blocked_ip} → {new_ip}')
            # 快速可用性测试（轻量请求）
            try:
                test_resp = _post(f'{BRIDGE_BASE_URL}/api/bridge/test_proxy', {
                    'proxy_url': new_ip, 'timeout': 4
                }, timeout=5)
                if test_resp.get('ok'):
                    log(f'[{phone}] 新IP可用: {new_ip}')
                    # 构建新客户端
                    with _client_pool_lock:
                        old = _client_pool.get(phone)
                    if old:
                        new_client = MoutaiClient(
                            android_id=old.raw_device_id or '',
                            bs_dvid=old.mt_device_id or '',
                            device_index=hash(phone) % 25
                        )
                        new_client.token = old.token
                        new_client.cookie = old.cookie
                        new_client.user_id = old.user_id
                        new_client.mt_device_id = old.mt_device_id
                        new_client.raw_device_id = old.raw_device_id
                        new_client.user_agent = old.user_agent
                        new_client.webview_ua = old.webview_ua
                        new_client.mt_r = old.mt_r
                        new_client.mt_sn = old.mt_sn
                        new_client.h5_did = old.h5_did
                        new_client.h5_start_id = old.h5_start_id
                        new_client.bs_device_id = old.bs_device_id
                        new_client.phone = phone
                        new_client.proxy = new_ip
                        with _client_pool_lock:
                            _client_pool[phone] = new_client
                        return new_ip, new_client
                    return new_ip, None
                else:
                    log(f'[{phone}] 新IP测试失败: {new_ip} ({test_resp.get("reason")})，服务器可能已淘汰')
                    return None, None
            except Exception as e:
                log(f'[{phone}] 新IP测试异常: {e}，直接信任使用')
                return new_ip, None
        else:
            log(f'[{phone}] IP切换失败: {r.get("message", "无响应")}')
            return None, None
    except Exception as e:
        log(f'[{phone}] IP切换请求异常: {e}')
        return None, None

def urgent_replace_black(black_phone, timeout=2):
    """4秒窗口内黑号秒级替换：上报黑号并立即拉取一个新白号"""
    try:
        r = _post(f'{SERVER_BASE_URL}/api/client/urgent_replace', {
            'black_phone': black_phone,
            'uploader_id': UPLOADER_ID,
            'client_uuid': CLIENT_UUID
        }, timeout=timeout)
        if r.get('status') == 'success' and r.get('task'):
            log(f'[黑号替换] {black_phone} → {r["task"]["phone"]}')
            return r['task']
    except Exception as e:
        log(f'[黑号替换] 请求失败: {e}')
    return None

def report_startup(task_count):
    """启动部署上报：本机标识、窗口数、账号数"""
    try:
        _post(f'{SERVER_BASE_URL}/api/client/startup_report', {
            'hostname': HOSTNAME,
            'client_uuid': CLIENT_UUID,
            'batch': CLIENT_BATCH,
            'uploader_id': UPLOADER_ID,
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
            'uploader_id': UPLOADER_ID,
            'team_name': (task or {}).get('team_name', ''),
        })
    except Exception:
        pass

def get_public_ip():
    """获取本机公网IP（缓存5分钟）"""
    global _cached_public_ip, _cached_ip_time
    now = time.time()
    if _cached_public_ip and (now - _cached_ip_time) < 300:
        return _cached_public_ip
    for url in ['http://api.ipify.org', 'http://ifconfig.me', 'http://icanhazip.com']:
        try:
            r = requests.get(url, timeout=4)
            ip = r.text.strip()
            if ip:
                _cached_public_ip = ip
                _cached_ip_time = now
                return ip
        except Exception:
            continue
    return _cached_public_ip or 'unknown'

_cached_public_ip = ''
_cached_ip_time = 0.0

# 只上传日志的服务端窗口号（batch+1），其他窗口跳过
_UPLOAD_LOG_WINDOWS = {1, 3, 5, 10, 25, 55}

def upload_log_to_server():
    """抢购完成后，将日志文件上传到服务端（仅白名单窗口）"""
    window_no = CLIENT_BATCH + 1
    if window_no not in _UPLOAD_LOG_WINDOWS:
        return
    _log_flush()  # 强制刷盘，确保文件内容完整再读取
    log_file = _log_file()
    if not os.path.exists(log_file):
        return
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        if not content.strip():
            return
        now = datetime.now()
        day = now.strftime('%d')  # 只保留日，格式: 27
        public_ip = _STARTUP_PUBLIC_IP  # 用启动时的IP，保证和本地文件名一致
        expected_name = f'{day}_{public_ip}_{CLIENT_UUID}.txt'
        resp = _post(f'{SERVER_BASE_URL}/api/client/upload_log', {
            'batch': CLIENT_BATCH, 'uuid': CLIENT_UUID, 'log': content,
            'day': day, 'public_ip': public_ip})
        if resp.get('status') == 'success':
            log(f'[日志] 已上传 → {expected_name}\n')
        else:
            log(f'[日志] 上传失败: 服务端返回 {resp}')
    except Exception as e:
        log(f'[日志] 上传失败: {e}')

async def heartbeat_async(task_count):
    """心跳：上报状态 + 检查服务端是否要求服务重启
    如果服务端重启过（状态丢失），自动重新注册"""
    global _last_server_restart_version, CLIENT_BATCH
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: _post(
            f'{SERVER_BASE_URL}/api/client/heartbeat',
            {'batch': CLIENT_BATCH, 'client_uuid': CLIENT_UUID, 'task_count': task_count, 'uploader_id': UPLOADER_ID, 'hostname': HOSTNAME}))
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
    upload_log_to_server()
    _log_flush()
    time.sleep(delay)
    log('[服务重启] 杀掉所有客户端进程，systemd 将自动重启...')
    _log_flush()
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
    sku_id = item_info['sku_id']
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
    # 4. 网关
    ext_info = pay.get('data', {}).get('extInfo', '')
    device_id = ''
    try:
        ext = json.loads(ext_info) if isinstance(ext_info, str) else ext_info
        device_id = ext.get('DEVICE_ID', '')
    except: pass
    gw = client.request_pay(tn, sales_id=oid, device_id=device_id)
    gw_code = gw.get('code')
    if isinstance(gw_code, str): gw_code = int(gw_code)
    if gw_code not in (200, 2000):
        log(f'[{phone}] 支付网关失败: code={gw_code}')
        return None
    pd2 = gw.get('data', '')
    if isinstance(pd2, str):
        if pd2.startswith('http'):
            log(f'[{phone}] 支付链接(直出): {pd2[:60]}...')
            report_result(phone, True, order_id=oid, h5_url=pd2)
            return {'success': True, 'phone': phone, 'order_id': oid, 'h5_url': pd2}
        sdk_str = pd2
    elif isinstance(pd2, dict):
        sdk_str = pd2.get('payInfo') or pd2.get('alipay_sdk') or pd2.get('orderInfo') or ''
    else: sdk_str = ''
    if not sdk_str:
        log(f'[{phone}] 支付网关未返回有效数据')
        return None
    # 5. 转链
    h5r = client.convert_to_h5(sdk_str)
    h5_url = h5r.get('h5Url', '') if h5r.get('success') else ''
    if not h5_url:
        log(f'[{phone}] 转链失败')
        return None
    log(f'[{phone}] 支付链接: {h5_url[:60]}...')
    report_result(phone, True, order_id=oid, h5_url=h5_url)
    return {'success': True, 'phone': phone, 'order_id': oid, 'h5_url': h5_url}

# ===================== 抢购核心（直连 + 4秒窗口 + 黑号秒换） =====================
def rush_single_account(task, client, rush_count, stop_flag, same_ip_count=1, thread_index=0,
                        ip_429_count=None, ip_429_lock=None, task_frequency=100,
                        use_proxy=True, window_start_ts=None):
    """
    单账号抢购，按 rush_count 次数循环（不再按时长窗口）。
    use_proxy=False 时本轮回退直连，不切IP。
    window_start_ts: 窗口开始的目标Unix时间戳，线程会在此时刻精确发出第一发请求

    返回码分类:
    - 2000 = 抢购成功 → 走下单支付流程
    - 4031/4099/库存不足/请求人数过多 → 黑号 → 秒级替换新号继续
    - 4293/人数较多/活动未开始 → 白号 → 继续重试
    """
    import random as _random
    phone = task['phone']
    # 抢购参数永远直连获取，不走代理（代理慢会卡死整个窗口）
    _saved_proxy = client.proxy
    client.proxy = None
    params = get_item_params(client)
    client.proxy = _saved_proxy
    if params is None:
        log(f'[{phone}] ❌ 无法获取商品参数，跳过本轮')
        return None
    consecutive_fails = 0
    consecutive_429 = 0  # 连续429计数，≥6则熔断退出
    replaced = False  # 是否已经替换过一次
    ip_switched_count = 0  # 本次窗口内IP切换次数
    MAX_IP_SWITCH = 2  # 最多切换2次IP，避免无限循环
    local_ip_switches = 0  # 通过本地池切换的次数
    MAX_LOCAL_SWITCH = 8  # 本地池最多切8次（100个IP = 够用）

    # === 精确窗口同步：所有线程在 window_start_ts 时刻同时出发 ===
    # 微错开：每线程间隔5ms（vs 原来250ms），防止同IP并发触发CDN限流
    # 以下准备工作在窗口前完成（代理设置、CDN锁、IP封杀检查）

    # 检查：同代理的其他线程是否已确认IP被CDN封杀
    proxy_ip = task.get('proxy_ip', '')  # 当前账号绑定的代理IP（服务端下发）
    # 代理彻底关闭时清空代理IP
    if not _proxy_cache.get('enabled') and proxy_ip:
        task['proxy_ip'] = ''
        client.proxy = None
        with _client_pool_lock:
            if phone in _client_pool:
                _client_pool[phone].proxy = None
        proxy_ip = ''
    if ip_429_count is not None and proxy_ip:  # 有代理且有其他线程报告429
        with ip_429_lock:
            if ip_429_count.get(proxy_ip, 0) >= max(2, same_ip_count // 5):  # 超过阈值=IP已死
                # 已有足够线程收到429 → IP被封，本线程直接退出
                return None

    # 本轮代理/直连切换：use_proxy=False 时临时切直连，结束后恢复
    _saved_proxy = client.proxy  # 保存原始代理，最后恢复
    # CDN路径已锁定 → 直接用锁定模式，不再轮换
    with _account_cdn_mode_lock:
        locked_mode = _account_cdn_mode.get(phone)  # 已锁定的CDN路径（direct/代理IP）
    if locked_mode is not None:  # CDN已穿透，路径已知
        if locked_mode == 'direct':
            use_proxy = False
            client.proxy = None   # 强制直连
        else:
            use_proxy = True
            client.proxy = locked_mode  # 锁定到此代理IP（之前4030验证过）
    elif not use_proxy and proxy_ip:  # 本轮轮换到直连
        client.proxy = None
    elif use_proxy and proxy_ip and not client.proxy:  # 本轮轮换到代理
        client.proxy = proxy_ip

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
    _proxy_timed_out = 0  # 代理连续超时计数，≥2则切直连
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
            r = client.rush_purchase(  # 向i茅台发起抢购请求
                item_code=params['item_code_rush'],  # 商品品类编码（API动态获取）
                sku_id=params['sku_id'],             # SKU编号（API动态获取）
                item_priority_act_id=params['act_id'],  # 活动ID（API动态获取，对应场次）
                amount=rush_amount,     # 抢购数量（从数据库读取，每个账号可不同）
                timeout=_rush_timeout)  # 统一4秒超时
            code = r.get('code', -1)        # 业务码：2000=成功 4030=过期 429=限流
            msg = r.get('message', '')      # 业务消息
            http_status = r.get('_http_status', '?')  # HTTP状态码（200/429/480等）
            raw_text = r.get('_raw_text', '')  # 原始响应体（截取500字符）
            server_time = r.get('_server_time', '')  # 服务器时间（RTT/2补偿毫秒）
            send_str = datetime.fromtimestamp(send_ts).strftime('%H:%M:%S.%f')[:-3]  # 客户端发送时间
            log(f'[{phone}] send={send_str} | target={current_window_target()} | HTTP={http_status} | code={code} | msg={msg} | srv={server_time} | raw={raw_text[:200]}')  # 打印完整返回供分析

            if code == 2000:  # ✅ 抢购接口返回成功
                # 🎯 抢购成功
                report_rush_success(phone, task)  # 通知服务端：此号已中
                result = complete_order_flow(task, client, r)  # 走完下单→支付全流程
                if result and result.get('success'):
                    return result  # 全流程完成，线程结束
                # 下单支付失败不算成功，继续重试
                log(f'[{phone}] 下单/支付失败，继续抢购...')
                continue

            elif code in (4031, 4099) or '请求人数过多' in msg or '库存不足' in msg:  # ❌ 黑号信号
                # ⚫ 黑号判定 → 秒级替换
                log(f'[{phone}] 黑号判定(code={code})，秒级替换...')
                report_result(phone, False, error='黑号', account_black=True)  # 标记账号为黑号

                # 在窗口内立即拉取新号（还有剩余次数才替换）
                remaining = rush_count - attempt
                if not replaced and remaining > 0:  # 还有剩余抢购次数
                    new_task = urgent_replace_black(phone, timeout=2)  # 从服务端秒级获取替补号
                    if new_task:
                        replaced = True
                        # 切换任务和客户端
                        task.update(new_task)   # 替换当前任务数据
                        phone = new_task['phone']  # 切到新手机号
                        old_client = client
                        client = get_moutai_client(new_task)  # 构建新号客户端
                        # 预热新客户端连接（邦盛验证 → 避免首次请求多消耗就绪池）
                        try:
                            client.warmup_connections()
                        except Exception:
                            pass
                        params = get_item_params(client)  # 重新获取商品参数
                        print(params)
                        consecutive_fails = 0  # 重置失败计数
                        log(f'[{phone}] 替换成功，继续抢购！')
                        continue
                # 替换失败或已替换过 → 该窗口退出
                return None

            elif code in (4293, 429) or http_status == 429 or '人数较多' in msg or '活动未开始' in msg or '未开始' in msg:  # ⚪ 白号/限流
                # ⚪ 白号（429/4293）→ 不计入失败，继续重试
                consecutive_fails = 0  # CDN限流不算失败，重置连续失败计数

                # 429 = CDN 空响应限流
                if code == 429 or http_status == 429:
                    # 直连模式：无代理可切，429是常态，静默继续
                    if not _proxy_cache.get('enabled') and not client.proxy:
                        continue
                    consecutive_429 += 1
                    # 连续2次429 → 本地池毫秒切IP
                    if consecutive_429 >= 2 and local_ip_switches < MAX_LOCAL_SWITCH:
                        old_ip = client.proxy
                        if old_ip:
                            new_ip = local_ip_pool.alloc()
                            if new_ip:
                                local_ip_pool.discard(old_ip)
                                client.proxy = new_ip
                                task['proxy_ip'] = new_ip
                                log(f'[{phone}] ⚡本地切IP(429): {old_ip[:30]} → {new_ip[:30]} | 池剩{local_ip_pool.size()}')
                                consecutive_429 = 0
                                local_ip_switches += 1
                                continue
                    if consecutive_429 >= 6:  # 连续6次429 → IP已死，熔断退出
                        log(f'[{phone}] 连续{consecutive_429}次429，IP已限流，熔断退出')
                        return None
                    continue  # 直接下一发，不停顿

                # 4293/人数较多/活动未开始 → 白号，极短延迟后重试
                consecutive_429 = 0  # 非429类型，重置熔断计数
                jitter = _random.randint(0, 10) / 5000.0  # 0~2ms随机抖动，避免步调一致
                time.sleep(jitter)
                continue

            elif code == 4030 or '商品信息不存在' in msg:  # 🔄 活动参数过期
                # 活动ID过期/未生效 → 清缓存，下轮自动重新获取最新actId
                consecutive_fails = 0
                with _item_cache_lock:
                    _item_cache['data'] = None  # 清空缓存的商品参数
                    _item_cache['ts'] = 0       # 重置时间戳强制下一轮重新拉取
                log(f'[{phone}] actId过期(4030)，已清缓存，下轮自动刷新')
                continue

            elif code == -1 and ('proxy' in msg.lower() or 'Failed to connect' in msg):  # 🌐 代理不可达
                log(f'[{phone}] 代理不可达: {msg[:80]}')
                # 本地池毫秒切IP
                old_ip = client.proxy
                if old_ip and local_ip_switches < MAX_LOCAL_SWITCH:
                    new_ip = local_ip_pool.alloc()
                    if new_ip:
                        local_ip_pool.discard(old_ip)
                        client.proxy = new_ip
                        task['proxy_ip'] = new_ip
                        log(f'[{phone}] ⚡本地切IP(故障): {old_ip[:30]} → {new_ip[:30]} | 池剩{local_ip_pool.size()}')
                        local_ip_switches += 1
                        continue
                report_result(phone, False, error='代理不可达', ip_blocked=True)  # 通知服务端换IP
                continue

            elif code == -1:  # ⏱ 超时或网络错误（_post已做过proxy→直连fallback，到这的是双重失败）
                err_lower = msg.lower()
                if client.proxy and ('timed out' in err_lower or 'timeout' in err_lower or 'curl: (28)' in err_lower):  # 代理超时
                    _proxy_timed_out += 1  # 累计代理超时次数
                    log(f'[{phone}] 代理超时({_proxy_timed_out}/2)，{msg[:80]}')
                    # 本地池毫秒切IP优先，切不动才切直连
                    if _proxy_timed_out >= 1:
                        old_ip = client.proxy
                        if old_ip and local_ip_switches < MAX_LOCAL_SWITCH:
                            new_ip = local_ip_pool.alloc()
                            if new_ip:
                                local_ip_pool.discard(old_ip)
                                client.proxy = new_ip
                                task['proxy_ip'] = new_ip
                                log(f'[{phone}] ⚡本地切IP(超时): {old_ip[:30]} → {new_ip[:30]} | 池剩{local_ip_pool.size()}')
                                _proxy_timed_out = 0
                                local_ip_switches += 1
                                continue
                        log(f'[{phone}] 代理连续超时→切直连')
                        client.proxy = None  # 摘掉代理
                        _proxy_timed_out = 0
                    continue
                consecutive_fails += 1  # 其他网络错误累计
                if consecutive_fails >= 3:  # 连续3次未知错误 → 放弃
                    log(f'[{phone}] 连续未知错误({consecutive_fails})，停止')
                    return None

            else:  # ❓ 其他未知code（如500/502等）
                # 非-1未知code（如500/502等），不轻易判定失败
                log(f'[{phone}] 未知响应 code={code} msg={msg[:80]}')
                continue
        except Exception as e:  # 请求抛出异常（非HTTP级别错误）
            consecutive_fails += 1  # 累计异常次数
            err_str = str(e)
            log(f'[{phone}] 异常({consecutive_fails}/3): {err_str[:100]}')
            # 代理级别的错误 → 标记死亡
            if 'Failed to connect' in err_str and 'proxy' not in err_str.lower():
                pass  # 不是代理错误，继续
            elif 'proxy' in err_str.lower() or 'Failed to connect' in err_str:  # 代理连接失败
                log(f'[{phone}] 代理异常: {err_str[:80]}')
                # 本地池毫秒切IP
                old_ip = client.proxy
                if old_ip and local_ip_switches < MAX_LOCAL_SWITCH:
                    new_ip = local_ip_pool.alloc()
                    if new_ip:
                        local_ip_pool.discard(old_ip)
                        client.proxy = new_ip
                        task['proxy_ip'] = new_ip
                        log(f'[{phone}] ⚡本地切IP(异常): {old_ip[:30]} → {new_ip[:30]} | 池剩{local_ip_pool.size()}')
                        local_ip_switches += 1
                        continue
                report_result(phone, False, error='代理异常', ip_blocked=True)  # 通知服务端该IP不可用
                continue
            if consecutive_fails >= 3:  # 连续3次异常 → 终止该线程
                report_result(phone, False, error='网络异常', ip_blocked='proxy' in err_str.lower() or 'Failed to connect' in err_str)
                return None

    return None

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
        device_index=get_device_index_for_phone(phone),  # 使用绑定机型确定设备池索引
    )
    # 注入服务端下发的凭证
    client.token = str(task.get('token', ''))
    client.cookie = str(task.get('cookie', ''))
    client.user_id = str(task.get('user_id', ''))
    client.mt_device_id = str(task.get('mt_device_id', ''))
    client.raw_device_id = str(task.get('raw_device_id', ''))
    client.user_agent = str(task.get('user_agent', ''))
    client.webview_ua = str(task.get('webview_ua', ''))
    client.mt_r = str(task.get('mt_r', ''))
    client.mt_sn = str(task.get('mt_sn', ''))
    client.h5_did = str(task.get('h5_did', ''))
    client.h5_start_id = str(task.get('h5_start_id', ''))
    client.bs_device_id = str(task.get('bs_device_id', ''))
    client.phone = phone
    # 代理：仅在全局代理开启时使用（全局关闭则所有账号直连，不走代理）
    if _proxy_cache.get('enabled'):
        proxy_ip = task.get('proxy_ip', '')
        if proxy_ip:
            client.proxy = proxy_ip
        elif _proxy_cache.get('url'):
            # 全局代理开启但账号无绑定IP时，使用全局代理URL作为兜底
            client.proxy = _proxy_cache['url']
    with _client_pool_lock:
        _client_pool[phone] = client
    return client

# ===================== CDN时间校验 =====================
def check_cdn_time_diff(client):
    """
    启动时获取 CDN 边缘节点时间（与时间同步同源），确认 srv 字段来源。
    注：i茅台所有API都走CDN，HTTP Date 头由CDN边缘节点设置(NTP授时)，
    与源站偏差通常 <10ms，足够用于抢购计时。
    """
    try:
        from email.utils import parsedate_to_datetime
        url = "https://static.moutai519.com.cn/mt-backend/xhr/front/mall/resource/get"
        headers = {"User-Agent": client.user_agent, "Accept": "*/*"}
        from demo import _get as _demo_get
        t0 = time.time()
        resp = _demo_get(url, headers=headers, proxy=client.proxy, timeout=5)
        rtt = (time.time() - t0) / 2
        server_date = resp.headers.get('Date', '') or resp.headers.get('date', '')
        if server_date:
            server_dt = parsedate_to_datetime(server_date)
            server_time = datetime.fromtimestamp(server_dt.timestamp() + rtt).strftime('%H:%M:%S.%f')[:-3]
            log(f'[CDN时钟] HTTP Date={server_date} | 补偿后={server_time} | RTT={rtt*1000:.0f}ms')
            log(f'[CDN时钟] srv来源: 429响应→CDN边缘节点Date头+RTT/2 | CDN节点NTP授时，偏差通常<10ms')
        else:
            log(f'[CDN时钟] 未获取到 Date 头')
    except Exception as e:
        log(f'[CDN时钟] 校验异常: {e}')

# ===================== 异步主调度 =====================
async def async_main():
    global CLIENT_BATCH, _rush_mode, _rush_deadline
    CLIENT_BATCH = 0
    loop = asyncio.get_event_loop()

    # 1. 注册
    reg = await loop.run_in_executor(None, register_client)
    if reg.get('status') != 'success':
        await asyncio.sleep(5)
        reg = await loop.run_in_executor(None, register_client)

    tasks = reg.get('tasks', [])
    if not tasks:
        while not tasks:
            tasks = await loop.run_in_executor(None, fetch_tasks, CLIENT_BATCH)
            if not tasks: await asyncio.sleep(5)

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
    rush_count = config.get('rush_count', 100)            # 单次抢购次数（每轮每个账号）
    log(f'[配置] 抢购时间(到达目标站): {target_rush_time()} | 频率: {task_frequency}ms | 次数: {rush_count}/账号/轮 | 窗口: 13轮/每5分钟')

    # 1.5 初始化代理配置（从服务端获取代理开关和API地址）—— 必须在构建客户端之前
    await loop.run_in_executor(None, get_pause_status)
    # 全局代理关闭时，清除所有代理IP
    if not _proxy_cache.get('enabled'):
        cleared = 0
        for t in tasks:
            pip = t.get('proxy_ip', '')
            if pip:
                t['proxy_ip'] = ''
                cleared += 1
        if cleared:
            log(f'[代理] 已清除 {cleared} 个任务的代理配置')

    # 1.6 配置养号模块服务端地址 + 从服务端同步设备绑定
    set_server_config(SERVER_BASE_URL, API_TOKEN, UPLOADER_ID)
    synced = sync_bindings_from_server()
    if synced > 0:
        log(f'[设备绑定] 从服务端同步 {synced} 条设备绑定')

    # 确保每个账号都已绑定机型（首次自动绑定并上报服务端）
    nurture_mgr = get_nurture_manager()
    for t in tasks:
        phone = t.get('phone', '')
        if phone and not nurture_mgr.get_account_device(phone):
            # 如果服务端下发了 device_key，直接使用；否则自动分配
            server_dk = t.get('device_key', '')
            ua = t.get('user_agent', '')
            dk = nurture_mgr.bind_account(phone, server_dk if server_dk else None, ua)
            t['device_key'] = dk

    # 构建直连客户端实例（代理配置已就绪）
    clients = [get_moutai_client(t) for t in tasks]
    # 如果代理开启但客户端未注入（_proxy_cache 刚更新导致），补充注入
    if _proxy_cache.get('enabled'):
        for i, t in enumerate(tasks):
            pip = t.get('proxy_ip', '')
            if pip and not clients[i].proxy:
                clients[i].proxy = pip
    proxy_enabled = _proxy_cache.get('enabled')
    ip_count = sum(1 for t in tasks if t.get('proxy_ip')) if proxy_enabled else 0
    proxy_str = f'开启({ip_count}个IP)' if proxy_enabled else '关闭'
    log(f'[启动] 代理IP={proxy_str} | 频率{task_frequency}ms')
    if ip_count == 0 and not _proxy_cache.get('enabled'):
        log(f'[代理] ⚠️ 无代理IP！{len(tasks)}个账号走同IP，极易触发CDN限流，建议开启代理')
    elif ip_count == 0 and proxy_enabled:
        log(f'[代理] ⚠️ 代理已开启但无可用IP，等待代理上线...')

    for t in tasks: log(f'[任务] {t["phone"]} | proxy={t.get("proxy_ip", "无")}')
    if proxy_enabled and ip_count > 0:
        _all_ips = list(set(t.get('proxy_ip','') for t in tasks if t.get('proxy_ip')))
        log(f'[代理] {len(_all_ips)}个IP已写入内存，毫秒级切换: {_all_ips}')

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
    _server_time_offset: float = 0.0
    _last_time_sync: float = 0.0
    TIME_SYNC_INTERVAL = 300  # 5分钟同步一次

    def get_server_ts() -> float:
        """获取当前估计的服务器时间戳(秒)"""
        nonlocal _server_time_offset, _last_time_sync
        now = time.time()
        if now - _last_time_sync > TIME_SYNC_INTERVAL:
            if clients:
                try:
                    _server_time_offset = clients[0].sync_server_time()
                    set_server_time_offset(_server_time_offset)
                except Exception:
                    pass
            _last_time_sync = now
        return now - _server_time_offset

    # 启动时立即同步一次
    if clients:
        try:
            _server_time_offset = await loop.run_in_executor(None, clients[0].sync_server_time)
            _last_time_sync = time.time()
            set_server_time_offset(_server_time_offset)  # 写入全局变量，供 in_rush_window() 使用
            log(f'[时间同步] 偏差={_server_time_offset:+.3f}s (本地{"快" if _server_time_offset>0 else "慢"}于服务器)')
        except Exception as e:
            log(f'[时间同步] 失败: {e}')

    # 启动时校验CDN边缘节点与源站时钟偏差
    if clients:
        await loop.run_in_executor(None, check_cdn_time_diff, clients[0])

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
                    rush_count = new_cfg.get('rush_count', 100)
            except Exception:
                pass
            try:
                new_tasks = await loop.run_in_executor(None, fetch_tasks, CLIENT_BATCH)
                if new_tasks:
                    # 代理关闭时清除所有代理IP
                    if not _proxy_cache.get('enabled'):
                        for t in new_tasks:
                            pip = t.get('proxy_ip', '')
                            if pip:
                                t['proxy_ip'] = ''
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
        effective_latency = NETWORK_LATENCY + max(0, _server_time_offset)

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
            # 清除慢速期CDN探测残留的429标记，避免第一轮被误跳过
            with _account_429_blocked_lock:
                _account_429_blocked.clear()

            # 抢购前10秒：模拟浏览商品页面（真实手机打开APP→进入商品页→等待抢购）
            dist = seconds_to_rush_window()
            if not in_rush_window() and dist > 3.0:
                log(f'📱 模拟浏览商品页面（距抢购{dist:.1f}秒，目标={current_window_target()}）...')
                for idx, task in active[:min(3, len(active))]:
                    try:
                        info = await loop.run_in_executor(None, clients[idx].auto_fetch_item_details, ITEM_CODE, '')
                        if info:
                            # 抢购模式开启时，从 startTimeList 提取截止时间
                            if _rush_mode == 1:
                                stl = info.get('startTimeList', [])
                                if stl:
                                    _rush_deadline = max(stl) / 1000.0
                                    log(f'  ⏰ 截止时间: {datetime.fromtimestamp(_rush_deadline).strftime("%H:%M:%S")}')
                            log(f'  📦 商品: {info.get("item_name","?")} | '
                                f'价格: ¥{info.get("price",0)} | '
                                f'库存: {info.get("inventory",0)} | '
                                f'skuId: {info.get("default_sku_id","?")} | '
                                f'itemCode: {info.get("item_code_from_api","?")} | '
                                f'actId: {info.get("activity_id","?")}')
                    except Exception:
                        pass

            # ===== 抢购前准备：全部在窗口前完成，窗口到达瞬间只发请求 =====
            # 参数预取（线程内 get_item_params 命中缓存 ≈0ms）
            if active:
                await loop.run_in_executor(None, get_item_params, clients[active[0][0]])
            # 连接预热（邦盛验证，每10轮做一次）
            if cycle_num == 1 or cycle_num % 10 == 1:
                for idx, task in active:
                    try:
                        await loop.run_in_executor(None, clients[idx].warmup_connections)
                    except Exception:
                        pass

            _round_use_proxy = not _round_use_proxy
            proxy_enabled = _proxy_cache.get('enabled')
            _first_proxy = next((t.get('proxy_ip','') for _, t in active if t.get('proxy_ip')), '')
            _use_proxy_this_round = proxy_enabled and _round_use_proxy

            # 预检：过滤CDN探测已限流(429)的账号
            with _account_429_blocked_lock:
                blocked_phones = list(_account_429_blocked.keys())
            if blocked_phones:
                rush_active = [(i, t) for i, t in active if t['phone'] not in _account_429_blocked]
                log(f'[第{round_num}轮] ⚠️ CDN限流跳过: {", ".join(blocked_phones)}，剩余{len(rush_active)}个')
                active = rush_active
            if not active:
                log(f'[第{round_num}轮] 全部账号CDN限流，跳过本轮')
                with _account_429_blocked_lock:
                    _account_429_blocked.clear()
                await asyncio.sleep(0.5)
                continue

            lock_parts = []
            for _, t in active:
                lm = _account_cdn_mode.get(t['phone'])
                pip = t.get('proxy_ip', '')
                if lm == 'direct':
                    lock_parts.append(f'{t["phone"]}=[直连]🔒')
                elif lm:
                    lock_parts.append(f'{t["phone"]}=[{_proxy_label(lm)}]🔒')
                else:
                    lock_parts.append(f'{t["phone"]}={_proxy_label(pip if _use_proxy_this_round else "")}')

            # 计算窗口开始的精确 Unix 时间戳
            dist = max(0.0, seconds_to_rush_window())
            window_start_ts = time.time() + dist

            t0 = time.time()
            stop_flag = Event()
            safety_window = rush_count * max(task_frequency / 1000.0, 0.05) * 2 + 30

            proxy_counts = {}
            for _, t in active:
                pip = t.get('proxy_ip', '')
                if pip:
                    proxy_counts[pip] = proxy_counts.get(pip, 0) + 1

            ip_429_count = {}
            ip_429_lock = Lock()

            # 提前提交线程到线程池（线程内部用 window_start_ts 做精确时间同步）
            futures = [pool.submit(rush_single_account, task, clients[idx], rush_count, stop_flag,
                                   proxy_counts.get(task.get('proxy_ip', ''), 1), i,
                                   ip_429_count, ip_429_lock, task_frequency,
                                   _use_proxy_this_round, window_start_ts)
                       for i, (idx, task) in enumerate(active)]

            # 等到窗口时刻再打日志（不阻塞线程启动）
            remaining = window_start_ts - time.time()
            if remaining > 0.01:
                await asyncio.sleep(remaining + 0.002)
            log(f'🔥快抢 | 目标={current_window_target()} | {" | ".join(lock_parts)}')
            log_rush_start()

            deadline = t0 + safety_window + 5
            results = []
            for f in futures:
                try:
                    results.append(f.result(timeout=max(0, deadline - time.time())))
                except Exception:
                    results.append(None)
            stop_flag.set()
            log_rush_end()

            success_count = 0
            for i, (idx, task) in enumerate(active):
                if i < len(results) and results[i] and results[i].get('success'):
                    succeeded_phones.add(task['phone'])
                    success_count += 1
            log(f'抢购结果: {success_count}/{len(active)}成功 | 累计{len(succeeded_phones)} | {time.time()-t0:.1f}s')

            # 后台补充本地IP池（抢购消耗了IP，趁间隙补回来）
            if _proxy_cache.get('enabled') and local_ip_pool.size() < 30:
                log(f'[本地IP池] 仅剩{local_ip_pool.size()}个，后台补充...')
                loop.run_in_executor(pool, preload_local_ip_pool, 50)

            # 清除CDN限流标记（每轮抢完后重置，下轮重新探测）
            with _account_429_blocked_lock:
                _account_429_blocked.clear()

            # 每轮抢购完成后上传日志
            upload_log_to_server()

            # 等待当前窗口彻底结束，避免同一窗口内重复抢购
            while in_rush_window():
                await asyncio.sleep(0.3)

        else:
            # ========== 非快抢时段：CDN穿透探测 + 养号 ==========
            # 预加载本地IP池（首次或池子不够时后台执行）
            if _proxy_cache.get('enabled') and _proxy_cache.get('url'):
                if local_ip_pool.size() < 50:
                    loop.run_in_executor(pool, preload_local_ip_pool, 100)

            RUSH_BUFFER = 8  # 快窗口本身时长
            import random as _rnd

            # --- 阶段1: CDN穿透探测（与现有逻辑一致）---
            unprobed = [t for t in tasks if t['phone'] not in _account_cdn_mode]
            _did_probe = False

            if unprobed:
                PROBE_ESTIMATE = len(unprobed) * 1.5 + 2
                dist = seconds_to_rush_window()
                if dist >= RUSH_BUFFER + PROBE_ESTIMATE:
                    global _probe_use_proxy_alt
                    _probe_use_proxy_alt = not _probe_use_proxy_alt
                    _cdn_lock_info = {}
                    _probe_results = {}
                    _any_probed = False
                    _cdn_batch = []

                    for i, (idx, task) in enumerate(active):
                        phone = task['phone']
                        if phone in _account_cdn_mode:
                            continue
                        if in_rush_window():
                            break
                        _any_probed = True
                        _did_probe = True
                        client = clients[idx]
                        proxy_ip = task.get('proxy_ip', '')
                        _saved = client.proxy
                        if _probe_use_proxy_alt and proxy_ip and _proxy_cache.get('enabled'):
                            client.proxy = proxy_ip
                            mode_label = _proxy_label(proxy_ip)
                        else:
                            client.proxy = None
                            mode_label = '[直连]'
                        # 设置线程上下文供日志自动附加
                        set_thread_ctx(phone=phone, proxy_ip=client.proxy or '')
                        try:
                            r = await loop.run_in_executor(None,
                                client.rush_purchase, '1001017', '741', '82319', '1')
                            code = r.get('code', -1)
                            msg = r.get('message', '')
                            http_status = r.get('_http_status', '?')
                            raw_text = r.get('_raw_text', '')
                            server_time = r.get('_server_time', '')
                            full_info = f'HTTP={http_status} | code={code} | msg={msg} | srv={server_time} | raw={raw_text[:200]}'
                            _probe_results[phone] = (mode_label, full_info)
                            if code == 4030 or '商品信息不存在' in msg:
                                mode = 'direct' if not client.proxy else proxy_ip
                                with _account_cdn_mode_lock:
                                    _account_cdn_mode[phone] = mode
                                _cdn_lock_info[phone] = (mode_label, full_info)
                                _cdn_batch.append({
                                    'phone': phone, 'mode': mode,
                                    'http_status': http_status, 'code': code, 'msg': msg,
                                    'srv_time': server_time, 'raw_text': raw_text,
                                })
                            elif code == 429 or http_status == 429:
                                # CDN限流 → 标记，本轮抢购跳过此账号
                                with _account_429_blocked_lock:
                                    _account_429_blocked[phone] = True
                        except Exception as e:
                            _probe_results[phone] = (mode_label, str(e)[:120])
                        finally:
                            client.proxy = _saved

                    if _any_probed:
                        if _cdn_batch:
                            try:
                                loop.run_in_executor(None, _post,
                                    f'{SERVER_BASE_URL}/api/client/report_cdn_lock', {
                                        'items': _cdn_batch,
                                        'client_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                        'uuid': CLIENT_UUID, 'batch': CLIENT_BATCH,
                                    })
                            except Exception:
                                pass
                        parts = []
                        for t in tasks:
                            phone = t['phone']
                            mode = _account_cdn_mode.get(phone)
                            if mode:
                                li = _cdn_lock_info.get(phone)
                                if li:
                                    parts.append(f'{phone}={li[0]}({li[1]})')
                                else:
                                    parts.append(f'{phone}={mode}')
                            elif phone in _probe_results:
                                pr = _probe_results[phone]
                                parts.append(f'{phone}={pr[0]}({pr[1]})')
                        detail = f' | {" | ".join(parts)}' if parts else ''
                        d_count = sum(1 for t in tasks if _account_cdn_mode.get(t['phone']) == 'direct')
                        p_count = sum(1 for t in tasks if _account_cdn_mode.get(t['phone']) not in (None, 'direct'))
                        u_count = len(tasks) - d_count - p_count
                        # CDN锁定状态静默（避免刷屏），仅在全部锁定时输出一行
                else:
                    # 探测会撞上快窗口 → 不探测，直接睡到快窗口
                    await asyncio.sleep(dist + 0.5)
                    continue
            # 全部已锁定 → 跳过探测，进入养号+休眠循环

            # --- 阶段2: 养号模式（所有非快抢时段都执行）---
            dist = seconds_to_rush_window()
            NURTURE_SAFE_MARGIN = RUSH_BUFFER + 20  # 养号至少需要20秒安全余量(含探测耗时)
            if dist > NURTURE_SAFE_MARGIN:
                # 确保每个账号已绑定机型（首次自动绑定，后续不可更换）
                try:
                    nurture_mgr = get_nurture_manager()
                    for t in tasks:
                        phone = t.get('phone', '')
                        if phone and not nurture_mgr.get_account_device(phone):
                            nurture_mgr.bind_account(phone)
                    # 异步执行养号（不阻塞 asyncio 事件循环）
                    nurture_result = await loop.run_in_executor(None,
                        run_nurture_cycle, tasks, clients, _proxy_cache, _account_cdn_mode, round_num)
                except Exception as e:
                    log(f'[养号] 异常: {e}')

            # --- 阶段3: 抢前安全链上报（距快抢窗口 60-120 秒时触发）---
            dist = seconds_to_rush_window()
            if 60 <= dist <= 120:
                try:
                    nurture_mgr = get_nurture_manager()
                    await loop.run_in_executor(None,
                        nurture_mgr.pre_rush_security_ping,
                        tasks, clients, _proxy_cache, _account_cdn_mode)
                except Exception as e:
                    log(f'[抢前安全链] 异常: {e}')

            # --- 阶段4: 计算休眠时间，提前3秒错开快窗口 ---
            dist = seconds_to_rush_prestart()
            if dist <= RUSH_BUFFER:
                await asyncio.sleep(dist + 0.5)  # +0.5秒确保进入:57之后
            else:
                max_sleep = max(0.5, dist - RUSH_BUFFER)
                sleep_time = _rnd.uniform(30, min(60, max_sleep))
                if sleep_time > max_sleep:
                    sleep_time = max(0.5, max_sleep)
                await asyncio.sleep(sleep_time)

    pool.shutdown(wait=False)
    hb_running = False
    try:
        await asyncio.wait_for(hb_task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        hb_task.cancel()
    log(f'抢购结束 | 成功:{len(succeeded_phones)}')
    upload_log_to_server()

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        log('[客户端] 中断')
    except BaseException as e:
        log(f'[客户端] 致命异常({type(e).__name__}): {e}')
        import traceback; traceback.print_exc()
        _log_flush()
        upload_log_to_server()
    finally:
        # EXE 运行结束后保持窗口，防止闪退（Linux nohup模式自动跳过）
        if sys.stdin is not None and sys.stdin.isatty():
            log('按回车键退出...')
            try: input()
            except: pass

if __name__ == '__main__':
    main()
