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
BAKED_USER_ID = 0
if BAKED_USER_ID > 0:
    UPLOADER_ID = BAKED_USER_ID
    SERVER_BASE_URL = "http://ipla.top:5000"

    API_TOKEN = "your-secure-token-change-me"
else:
    import argparse
    def parse_args():
        p = argparse.ArgumentParser(description='抢购客户端 v4')
        p.add_argument('--user-id', type=int, default=2)
        p.add_argument('--server', type=str, default='http://ipla.top:5000')

        p.add_argument('--token', type=str, default='m9Xk2vLp7Qr4Wn8YbT1cFh6Jd')
        return p.parse_args()
    _a = parse_args()
    UPLOADER_ID, SERVER_BASE_URL, API_TOKEN = _a.user_id, _a.server, _a.token

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

# ===================== 代理IP本地池（从服务端获取，不存DB） =====================
_proxy_cache = {'enabled': False, 'url': ''}
_proxy_pool = []  # 本地缓存的代理IP列表
_proxy_pool_lock = Lock()
_last_proxy_fetch = 0.0  # 上次获取代理IP的时间戳


def _fetch_proxies_from_server(count=20):
    """从服务端获取代理IP列表，存入本地池"""
    global _proxy_pool, _last_proxy_fetch
    if not _proxy_cache.get('enabled'):
        log('[代理] 代理未开启，跳过获取')
        return []
    try:
        r = _post(f'{SERVER_BASE_URL}/api/client/get_proxies', {
            'uploader_id': UPLOADER_ID,
            'count': count
        })
        if r.get('status') == 'success':
            proxies = r.get('proxies', [])
            with _proxy_pool_lock:
                _proxy_pool = proxies
            _last_proxy_fetch = time.time()
            log(f'[代理] 从服务端获取到 {len(proxies)} 个IP')
            return proxies
        else:
            err_msg = r.get('message', '未知')
            log(f'[代理] 服务端获取失败: {err_msg}')
            return []
    except Exception as e:
        log(f'[代理] 获取异常: {e}')
        return []


def _assign_proxies_to_tasks(tasks):
    """将本地代理IP池分配给任务列表（轮询分配）"""
    global _proxy_pool
    with _proxy_pool_lock:
        pool = list(_proxy_pool)
    if not _proxy_cache.get('enabled') or not pool:
        for t in tasks:
            t['proxy_ip'] = ''
        return
    ip_count = len(pool)
    for i, t in enumerate(tasks):
        t['proxy_ip'] = pool[i % ip_count]


def _proxy_prefetch(tasks):
    """抢购前预取代理IP并分配给任务"""
    if not _proxy_cache.get('enabled'):
        for t in tasks:
            t['proxy_ip'] = ''
        return
    _fetch_proxies_from_server(len(tasks))
    _assign_proxies_to_tasks(tasks)


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
    proxy_ip = task.get('proxy_ip', '')  # 当前账号绑定的代理IP（服务端下发）
    # 代理彻底关闭时清空代理IP
    if not _proxy_cache.get('enabled') and proxy_ip:
        task['proxy_ip'] = ''
        client.proxy = None
        with _client_pool_lock:
            if phone in _client_pool:
                _client_pool[phone].proxy = None
        proxy_ip = ''
    # 本轮代理/直连切换
    _saved_proxy = client.proxy
    if not use_proxy and proxy_ip:
        client.proxy = None
    elif use_proxy and proxy_ip and not client.proxy:
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
                item_code=params['item_code'],       # skuId（API动态获取）
                item_priority_act_id=params['act_id'],  # itemPriorityActId（API动态获取）
                amount=rush_amount,     # 抢购数量（从数据库读取，每个账号可不同）
                timeout=_rush_timeout,   # 统一4秒超时
                spu_code=ITEM_CODE)       # SPU码（用于分链路路由）
            code = r.get('code', -1)        # 业务码：2000=成功 4030=过期 429=限流
            msg = r.get('message', '')      # 业务消息
            http_status = r.get('_http_status', '?')  # HTTP状态码（200/429/480等）
            raw_text = r.get('_raw_text', '')  # 原始响应体（截取500字符）
            server_time = r.get('_server_time', '')  # 服务器时间（RTT/2补偿毫秒）
            send_str = datetime.fromtimestamp(send_ts).strftime('%H:%M:%S.%f')[:-3]  # 客户端发送时间
            # log(f'[{phone}] send={send_str} | target={current_window_target()} | HTTP={http_status} | code={code} | msg={msg} | srv={server_time} | raw={raw_text[:200]}')  # 打印完整返回供分析

            if code == 2000:  # ✅ 抢购接口返回成功
                # 🎯 抢购成功
                report_rush_success(phone, task)  # 通知服务端：此号已中
                result = complete_order_flow(task, client, r)  # 走完下单→支付全流程
                if result and result.get('success'):
                    return result  # 全流程完成，线程结束
                # 下单支付失败不算成功，继续重试
                log(f'[{phone}] 下单/支付失败，继续抢购...')
                continue

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
            log(f'[{phone}] 异常: {str(e)[:100]}')
            continue

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
    # 从服务端获取代理IP并分配给任务
    _proxy_prefetch(tasks)

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
    _cached_offset: float = 0.0
    _last_time_sync: float = 0.0
    TIME_SYNC_INTERVAL = 300  # 5分钟同步一次

    def get_server_ts() -> float:
        """获取当前估计的服务器时间戳(秒)"""
        nonlocal _cached_offset, _last_time_sync
        now = time.time()
        if now - _last_time_sync > TIME_SYNC_INTERVAL:
            if clients:
                try:
                    _cached_offset = clients[0].sync_server_time()
                    set_server_time_offset(_cached_offset)
                except Exception:
                    pass
            _last_time_sync = now
        return now - _cached_offset

    # 启动时立即同步一次
    if clients:
        try:
            _cached_offset = await loop.run_in_executor(None, clients[0].sync_server_time)
            _last_time_sync = time.time()
            set_server_time_offset(_cached_offset)  # 写入全局变量，供 in_rush_window() 使用
            log(f'[时间同步] 偏差={_cached_offset:+.3f}s (本地{"快" if _cached_offset>0 else "慢"}于服务器)')
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
                    rush_count = new_cfg.get('rush_count', 100)
            except Exception:
                pass
            try:
                new_tasks = await loop.run_in_executor(None, fetch_tasks, CLIENT_BATCH)
                if new_tasks:
                    _proxy_prefetch(new_tasks)
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

        # === 代理IP预刷新：抢购模式开启时提前2分钟获取，关闭模式随时获取 ===
        if _proxy_cache.get('enabled'):
            dist = seconds_to_rush_window()
            need_refresh = False
            if _rush_mode == 0:
                # 抢购模式关闭：每120秒刷新一次
                if time.time() - _last_proxy_fetch > 120:
                    need_refresh = True
            elif _rush_mode == 1 and (dist <= 120 or in_rush_window()):
                # 抢购模式开启：距抢购≤2分钟或在窗口内，每30秒刷新
                if time.time() - _last_proxy_fetch > 30:
                    need_refresh = True
            if need_refresh:
                log(f'[代理] 预刷新代理IP（距抢购{dist:.0f}秒）')
                _proxy_prefetch(tasks)

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

            lock_parts = []
            for _, t in active:
                pip = t.get('proxy_ip', '')
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

            # 提前提交线程到线程池（线程内部用 window_start_ts 做精确时间同步）
            futures = [pool.submit(rush_single_account, task, clients[idx], rush_count, stop_flag,
                                   i, task_frequency,
                                   _use_proxy_this_round, window_start_ts)
                       for i, (idx, task) in enumerate(active)]

            # 等到窗口时刻再打日志（调试模式跳过等待）
            remaining = window_start_ts - time.time()
            if remaining > 0.01 and _rush_mode != 0:
                await asyncio.sleep(remaining + 0.002)
            # log(f'🔥快抢 | 目标={current_window_target()} | {" | ".join(lock_parts)}')

            deadline = t0 + safety_window + 5
            results = []
            for f in futures:
                try:
                    results.append(f.result(timeout=max(0, deadline - time.time())))
                except Exception:
                    results.append(None)
            stop_flag.set()

            success_count = 0
            for i, (idx, task) in enumerate(active):
                if i < len(results) and results[i] and results[i].get('success'):
                    succeeded_phones.add(task['phone'])
                    success_count += 1
            log(f'抢购结果: {success_count}/{len(active)}成功 | 累计{len(succeeded_phones)} | {time.time()-t0:.1f}s')

            # 等待当前窗口彻底结束（调试模式不等待）
            if _rush_mode != 0:
                while in_rush_window():
                    await asyncio.sleep(0.3)

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
