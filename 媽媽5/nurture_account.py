#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i茅台 养号模块 v1.0 — 智能模拟真机用户行为
============================================
功能:
  1. 非快抢时段自动养号，模拟真机浏览行为
  2. 基于 HAR 抓包学习的请求序列模拟
  3. 账号-机型绑定（不可更换）
  4. CDN 节点健康检测（2000=OK, 429=限流）
  5. 周期性抢购商品4030检测（判断账号健康状态）
  6. 预设多款主流 Android 机型真实参数模板
  7. 增量 HAR 训练，持续优化行为模拟
  8. 所有日志带 [HH:MM:SS.mmm] 时间前缀

集成方式:
  由 moutai_client_worker.py 在非快抢时段调用本模块的 run_nurture_cycle()
  传入: tasks 列表, clients 列表, proxy_cache, account_cdn_mode
  返回: 本轮养号结果汇总
"""

import json, time, os, sys, uuid, random, threading, hashlib, requests, base64, re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

# 导入现有 MoutaiClient（复用所有设备指纹/加密/请求逻辑）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo import MoutaiClient, _WEBVIEW_UA_POOL, H5_BASE_URL, BASE_URL, _post, _get
from _security_bodies import HAOTIAN_BODIES, MSHIELD_BODIES
STATIC_URL = "https://static.moutai519.com.cn"
APP_VERSION = "1.9.7"  # 与 crypto.py 保持同步

# 服务端 API 配置（由 moutai_client_worker.py 注入）
_SERVER_BASE_URL = ""
_API_TOKEN = ""
_UPLOADER_ID = 0

# ===================== 日志系统 =====================
_nurture_log_lock = threading.Lock()

def nurture_log(msg: str):
    """养号专用日志，自动带 [HH:MM:SS.mmm] 前缀，并尝试附加模式标签"""
    # 尝试从客户端获取当前线程的代理模式标签（延迟导入避免循环依赖）
    try:
        from moutai_client_worker import _thread_mode_tag
        tag = _thread_mode_tag()
        if tag:
            msg = msg + tag
    except Exception:
        pass
    now = datetime.now()
    ts = now.strftime('%H:%M:%S.') + f'{now.microsecond // 1000:03d}'
    line = f'[{ts}] [养号] {msg}'
    print(line)


def set_server_config(server_url: str, api_token: str, uploader_id: int = 0):
    """设置服务端 API 配置（由 moutai_client_worker.py 启动时调用）"""
    global _SERVER_BASE_URL, _API_TOKEN, _UPLOADER_ID
    _SERVER_BASE_URL = server_url
    _API_TOKEN = api_token
    _UPLOADER_ID = uploader_id


def _server_post(path: str, data: dict = None, timeout: int = 8) -> dict:
    """调用服务端 API"""
    if not _SERVER_BASE_URL:
        return {'status': 'error', 'message': '服务端未配置'}
    try:
        headers = {'X-API-TOKEN': _API_TOKEN, 'Content-Type': 'application/json'}
        r = requests.post(f'{_SERVER_BASE_URL}{path}', json=data or {}, headers=headers, timeout=timeout)
        return r.json()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def _server_get(path: str, timeout: int = 8) -> dict:
    """调用服务端 GET API"""
    if not _SERVER_BASE_URL:
        return {'status': 'error', 'message': '服务端未配置'}
    try:
        headers = {'X-API-TOKEN': _API_TOKEN}
        r = requests.get(f'{_SERVER_BASE_URL}{path}', headers=headers, timeout=timeout)
        return r.json()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

# ===================== 常量配置 =====================
# 养号数据目录
NURTURE_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'nurture')
os.makedirs(NURTURE_DATA_DIR, exist_ok=True)

# 账号-机型绑定文件
BINDING_FILE = os.path.join(NURTURE_DATA_DIR, 'account_device_bindings.json')

# HAR 学习数据目录
HAR_LEARN_DIR = os.path.join(NURTURE_DATA_DIR, 'har_learned')
os.makedirs(HAR_LEARN_DIR, exist_ok=True)

# 养号行为间隔范围（秒）
PAGE_STAY_MIN = 3.0    # 页面最短停留
PAGE_STAY_MAX = 10.0   # 页面最长停留
RUSH_CHECK_MIN = 1.0   # 抢购检查最短停留
RUSH_CHECK_MAX = 5.0   # 抢购检查最长停留
CYCLE_INTERVAL_MIN = 30.0  # 养号周期间隔最短
CYCLE_INTERVAL_MAX = 120.0 # 养号周期间隔最长

# 每个养号周期最多操作的账号数（避免单轮太久）
MAX_ACCOUNTS_PER_CYCLE = 10

# 4030 检测间隔（每 N 轮养号做一次）
RUSH_CHECK_INTERVAL = 5

# ==================== 机型参数模板库 ====================
# 预设 30 款主流 Android 真机参数
# 每个机型包含: 厂商, 型号, Build ID, Android SDK, 屏幕, Chrome版本, 
#             设备池索引, 厂商UA名, APP型号名
DEVICE_TEMPLATES: Dict[str, Dict] = {
    # === Xiaomi 系列 ===
    "xiaomi_13": {
        "brand": "Xiaomi", "model": "2211133C", "build_id": "UKQ1.230705.002",
        "sdk": 14, "screen": "1080*2400", "chrome": "128.0.6613.127",
        "manufacturer": "Xiaomi", "app_model": "fuxi", "pool_index": 0,
        "cpu": "Qualcomm Snapdragon 8 Gen 2", "ram": "8GB", "storage": "256GB",
    },
    "xiaomi_14": {
        "brand": "Xiaomi", "model": "23127PN0CC", "build_id": "UKQ1.230804.001",
        "sdk": 14, "screen": "1220*2712", "chrome": "127.0.6533.64",
        "manufacturer": "Xiaomi", "app_model": "shennong", "pool_index": 19,
        "cpu": "Qualcomm Snapdragon 8 Gen 3", "ram": "12GB", "storage": "256GB",
    },
    "xiaomi_15_pro": {
        "brand": "Xiaomi", "model": "2410DPN6CC", "build_id": "OS2.0.6.0.VOBCNXM",
        "sdk": 15, "screen": "1440*3200", "chrome": "131.0.6778.81",
        "manufacturer": "Xiaomi", "app_model": "dada", "pool_index": 12,
        "cpu": "Qualcomm Snapdragon 8 Elite", "ram": "16GB", "storage": "512GB",
    },
    "xiaomi_12s_ultra": {
        "brand": "Xiaomi", "model": "22081212C", "build_id": "UKQ1.230917.001",
        "sdk": 14, "screen": "1440*3200", "chrome": "122.0.6261.64",
        "manufacturer": "Xiaomi", "app_model": "cupid", "pool_index": 3,
        "cpu": "Qualcomm Snapdragon 8+ Gen 1", "ram": "8GB", "storage": "256GB",
    },
    "redmi_note_13_pro": {
        "brand": "Redmi", "model": "23090RA98G", "build_id": "UKQ1.231108.001",
        "sdk": 14, "screen": "1220*2712", "chrome": "126.0.6478.110",
        "manufacturer": "Redmi", "app_model": "ruby", "pool_index": 7,
        "cpu": "Qualcomm Snapdragon 7s Gen 2", "ram": "8GB", "storage": "128GB",
    },
    "redmi_note_12_turbo": {
        "brand": "Redmi", "model": "23053RN02A", "build_id": "UKQ1.230804.001",
        "sdk": 14, "screen": "1080*2460", "chrome": "126.0.6478.122",
        "manufacturer": "Redmi", "app_model": "pearl", "pool_index": 18,
        "cpu": "Qualcomm Snapdragon 7+ Gen 2", "ram": "8GB", "storage": "256GB",
    },

    # === Samsung 系列 ===
    "samsung_s21": {
        "brand": "samsung", "model": "SM-G991B", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1080*2340", "chrome": "124.0.6367.179",
        "manufacturer": "samsung", "app_model": "o1q", "pool_index": 1,
        "cpu": "Exynos 2100", "ram": "8GB", "storage": "128GB",
    },
    "samsung_s24_ultra": {
        "brand": "samsung", "model": "SM-S928B", "build_id": "AP1A.240405.002",
        "sdk": 15, "screen": "1440*3120", "chrome": "130.0.6723.86",
        "manufacturer": "samsung", "app_model": "e1q", "pool_index": 5,
        "cpu": "Qualcomm Snapdragon 8 Gen 3", "ram": "12GB", "storage": "256GB",
    },
    "samsung_s23_ultra": {
        "brand": "samsung", "model": "SM-S9180", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1440*3088", "chrome": "125.0.6422.165",
        "manufacturer": "samsung", "app_model": "dm1q", "pool_index": 23,
        "cpu": "Qualcomm Snapdragon 8 Gen 2", "ram": "12GB", "storage": "256GB",
    },
    "samsung_z_fold5": {
        "brand": "samsung", "model": "SM-F946B", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1812*2176", "chrome": "125.0.6422.146",
        "manufacturer": "samsung", "app_model": "q5q", "pool_index": 13,
        "cpu": "Qualcomm Snapdragon 8 Gen 2", "ram": "12GB", "storage": "512GB",
    },
    "samsung_a54": {
        "brand": "samsung", "model": "SM-A5460", "build_id": "TP1A.220624.014",
        "sdk": 13, "screen": "1080*2340", "chrome": "122.0.6261.119",
        "manufacturer": "samsung", "app_model": "a54x", "pool_index": 17,
        "cpu": "Exynos 1380", "ram": "6GB", "storage": "128GB",
    },

    # === HUAWEI 系列 ===
    "huawei_mate60": {
        "brand": "HUAWEI", "model": "ALN-AL80", "build_id": "ALN-AL80 4.0.0.120",
        "sdk": 13, "screen": "1212*2616", "chrome": "118.0.5993.80",
        "manufacturer": "HUAWEI", "app_model": "aln-al80", "pool_index": 11,
        "cpu": "Kirin 9000S", "ram": "12GB", "storage": "256GB",
    },
    "huawei_p60_pro": {
        "brand": "HUAWEI", "model": "MNA-AL00", "build_id": "MNA-AL00 3.1.0.156",
        "sdk": 13, "screen": "1220*2700", "chrome": "120.0.6099.210",
        "manufacturer": "HUAWEI", "app_model": "mna-al00", "pool_index": -1,
        "cpu": "Qualcomm Snapdragon 8+ Gen 1", "ram": "8GB", "storage": "256GB",
    },

    # === OPPO 系列 ===
    "oppo_find_x7": {
        "brand": "OPPO", "model": "PJZ110", "build_id": "UKQ1.230804.001",
        "sdk": 14, "screen": "1264*2780", "chrome": "125.0.6422.165",
        "manufacturer": "OPPO", "app_model": "pjz110", "pool_index": 10,
        "cpu": "MediaTek Dimensity 9300", "ram": "12GB", "storage": "256GB",
    },
    "oppo_reno12": {
        "brand": "OPPO", "model": "PKM110", "build_id": "AP3A.240617.008",
        "sdk": 15, "screen": "1080*2412", "chrome": "130.0.6723.58",
        "manufacturer": "OPPO", "app_model": "pkm110", "pool_index": 22,
        "cpu": "MediaTek Dimensity 8250", "ram": "12GB", "storage": "256GB",
    },
    "oppo_a78": {
        "brand": "OPPO", "model": "CPH2487", "build_id": "TP1A.220905.001",
        "sdk": 13, "screen": "1080*2412", "chrome": "118.0.5993.65",
        "manufacturer": "OPPO", "app_model": "cph2487", "pool_index": 20,
        "cpu": "Qualcomm Snapdragon 680", "ram": "8GB", "storage": "128GB",
    },

    # === vivo 系列 ===
    "vivo_x90": {
        "brand": "vivo", "model": "V2254A", "build_id": "TP1A.220624.014",
        "sdk": 13, "screen": "1080*2376", "chrome": "119.0.6045.193",
        "manufacturer": "vivo", "app_model": "v2254a", "pool_index": 4,
        "cpu": "MediaTek Dimensity 9200", "ram": "8GB", "storage": "128GB",
    },
    "vivo_x100": {
        "brand": "vivo", "model": "V2361A", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1260*2800", "chrome": "126.0.6478.122",
        "manufacturer": "vivo", "app_model": "v2361a", "pool_index": 9,
        "cpu": "MediaTek Dimensity 9300", "ram": "12GB", "storage": "256GB",
    },
    "vivo_x100_pro": {
        "brand": "vivo", "model": "V2318A", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1260*2800", "chrome": "124.0.6367.243",
        "manufacturer": "vivo", "app_model": "v2318a", "pool_index": 21,
        "cpu": "MediaTek Dimensity 9300", "ram": "16GB", "storage": "512GB",
    },

    # === OnePlus 系列 ===
    "oneplus_12": {
        "brand": "OnePlus", "model": "PHN110", "build_id": "UKQ1.230928.001",
        "sdk": 14, "screen": "1264*2780", "chrome": "124.0.6367.113",
        "manufacturer": "OnePlus", "app_model": "phn110", "pool_index": 15,
        "cpu": "Qualcomm Snapdragon 8 Gen 3", "ram": "12GB", "storage": "256GB",
    },
    "oneplus_10_pro": {
        "brand": "OnePlus", "model": "OPH2201", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1080*2412", "chrome": "123.0.6312.118",
        "manufacturer": "OnePlus", "app_model": "oph2201", "pool_index": 25,
        "cpu": "Qualcomm Snapdragon 8 Gen 1", "ram": "8GB", "storage": "128GB",
    },
    "oneplus_9_pro": {
        "brand": "OnePlus", "model": "LE2120", "build_id": "UKQ1.230928.001",
        "sdk": 14, "screen": "1080*2400", "chrome": "125.0.6422.147",
        "manufacturer": "OnePlus", "app_model": "lemonade", "pool_index": 16,
        "cpu": "Qualcomm Snapdragon 888", "ram": "8GB", "storage": "128GB",
    },

    # === Google Pixel 系列 ===
    "google_pixel7": {
        "brand": "google", "model": "Pixel 7", "build_id": "TQ3A.230901.001",
        "sdk": 13, "screen": "1080*2400", "chrome": "120.0.6099.230",
        "manufacturer": "google", "app_model": "pixel7", "pool_index": 2,
        "cpu": "Google Tensor G2", "ram": "8GB", "storage": "128GB",
    },
    "google_pixel9_pro": {
        "brand": "google", "model": "Pixel 9 Pro", "build_id": "AP3A.240905.015",
        "sdk": 15, "screen": "1280*2856", "chrome": "132.0.6834.79",
        "manufacturer": "google", "app_model": "caiman", "pool_index": 8,
        "cpu": "Google Tensor G4", "ram": "16GB", "storage": "256GB",
    },

    # === 其他品牌 ===
    "realme_gt5": {
        "brand": "realme", "model": "RMX3700", "build_id": "TP1A.220905.001",
        "sdk": 13, "screen": "1080*2412", "chrome": "120.0.6099.144",
        "manufacturer": "realme", "app_model": "rmx3700", "pool_index": 14,
        "cpu": "Qualcomm Snapdragon 8 Gen 2", "ram": "12GB", "storage": "256GB",
    },
    "nubia_z60_ultra": {
        "brand": "nubia", "model": "NX769J", "build_id": "UP1A.231005.007",
        "sdk": 14, "screen": "1116*2480", "chrome": "126.0.6478.71",
        "manufacturer": "nubia", "app_model": "nx769j", "pool_index": 24,
        "cpu": "Qualcomm Snapdragon 8 Gen 3", "ram": "12GB", "storage": "256GB",
    },
}

# 按品牌分组
DEVICE_BY_BRAND = defaultdict(list)
for _key, _dev in DEVICE_TEMPLATES.items():
    DEVICE_BY_BRAND[_dev['brand']].append(_key)

# 设备key → WebView UA池索引映射（确保同一设备始终用同一个 UA 模板）
DEVICE_KEY_TO_POOL_INDEX: Dict[str, int] = {}
for _key, _dev in DEVICE_TEMPLATES.items():
    _pi = _dev.get('pool_index', -1)
    if _pi >= 0:
        DEVICE_KEY_TO_POOL_INDEX[_key] = _pi

# 反向映射：pool_index → device_key (1对1)
POOL_INDEX_TO_DEVICE_KEY: Dict[int, str] = {}
for _key, _pi in DEVICE_KEY_TO_POOL_INDEX.items():
    if _pi not in POOL_INDEX_TO_DEVICE_KEY:
        POOL_INDEX_TO_DEVICE_KEY[_pi] = _key


def get_device_index_for_phone(phone: str) -> int:
    """根据手机号获取对应的设备池索引（优先使用绑定机型，否则哈希兜底）
    保证同一手机号永远返回相同的 device_index"""
    mgr = get_nurture_manager()
    dk = mgr.get_account_device_key(phone) if mgr else None
    if dk and dk in DEVICE_KEY_TO_POOL_INDEX:
        return DEVICE_KEY_TO_POOL_INDEX[dk]
    # 未绑定时用手机号哈希兜底（与 moutai_client_worker 中 hash(phone) % 25 一致）
    return abs(hash(phone)) % len(_WEBVIEW_UA_POOL)


def get_device_key_for_pool_index(pool_index: int) -> Optional[str]:
    """根据设备池索引获取对应的 device_key"""
    return POOL_INDEX_TO_DEVICE_KEY.get(pool_index)


def match_device_from_ua(user_agent: str) -> Optional[str]:
    """从 user-agent 解析设备型号并精确匹配 DEVICE_TEMPLATES
    格式: "android;{sdk};{brand};{app_model}"
    返回: 匹配到的 device_key，无匹配返回 None"""
    if not user_agent:
        return None
    parts = user_agent.split(';')
    if len(parts) < 4:
        return None
    brand = parts[2].strip()
    app_model = parts[3].strip()
    app_model_lower = app_model.lower()
    brand_lower = brand.lower()

    # 1. 精确匹配 app_model（大小写不敏感）
    for key, dev in DEVICE_TEMPLATES.items():
        if dev.get('app_model', '').lower() == app_model_lower:
            return key

    # 2. 匹配 model 字段
    for key, dev in DEVICE_TEMPLATES.items():
        if dev.get('model', '').lower() == app_model_lower:
            return key

    # 3. 同品牌前缀匹配
    for key, dev in DEVICE_TEMPLATES.items():
        if dev.get('brand', '').lower() == brand_lower:
            if dev.get('app_model', '').lower().startswith(app_model_lower[:3]):
                return key

    # 4. 同品牌任意机型兜底
    brand_devices = DEVICE_BY_BRAND.get(brand, [])
    if brand_devices:
        return brand_devices[0]

    return None


# ==================== 账号-机型绑定管理 ====================
class AccountDeviceBinding:
    """账号(手机号)与机型的绑定管理
    - 优先使用服务端数据库持久化（绑定后不可更换）
    - 本地 JSON 文件作为缓存/离线兜底
    - 启动时自动从服务端同步已有绑定
    """

    def __init__(self, binding_file: str = BINDING_FILE):
        self._file = binding_file
        self._bindings: Dict[str, str] = {}      # phone -> device_key
        self._device_keys: Dict[str, str] = {}   # device_key -> phone (反向)
        self._lock = threading.Lock()
        self._synced_from_server = False
        self._load()

    def _load(self):
        """从本地 JSON 加载缓存"""
        if os.path.exists(self._file):
            try:
                with open(self._file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._bindings = data.get('bindings', {})
                self._device_keys = data.get('device_keys', {})
                nurture_log(f'[绑定] 加载 {len(self._bindings)} 条本地缓存')
            except Exception as e:
                nurture_log(f'[绑定] 加载本地缓存失败: {e}')

    def _save(self):
        """保存到本地 JSON 缓存"""
        try:
            with open(self._file, 'w', encoding='utf-8') as f:
                json.dump({
                    'bindings': self._bindings,
                    'device_keys': self._device_keys,
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            nurture_log(f'[绑定] 保存本地缓存失败: {e}')

    def sync_from_server(self) -> int:
        """从服务端同步已有绑定关系
        如果本地有绑定但服务端没有，则推送到服务端
        返回: 同步到的绑定数量"""
        if not _SERVER_BASE_URL:
            nurture_log('[绑定] 服务端未配置，跳过同步')
            return 0

        resp = _server_get('/api/client/get_device_bindings')
        if resp.get('status') != 'success':
            nurture_log(f'[绑定] 服务端同步失败: status={resp.get("status")} msg="{resp.get("message", "")}" raw={str(resp)[:200]}')
            return 0

        server_bindings = resp.get('bindings', {})

        with self._lock:
            local_bindings = dict(self._bindings)

        if not server_bindings:
            # 服务端无记录 → 如果本地有缓存，推送到服务端
            if local_bindings:
                pushed = 0
                for phone, dk in local_bindings.items():
                    if self._bind_via_api(phone, dk):
                        pushed += 1
                nurture_log(f'[绑定] 服务端无记录，已推送本地 {pushed}/{len(local_bindings)} 条到服务端')
            else:
                nurture_log('[绑定] 服务端无绑定记录')
            self._synced_from_server = True
            return 0

        # 服务端有记录 → 合并到本地
        with self._lock:
            new_count = 0
            for phone, device_key in server_bindings.items():
                if phone not in self._bindings:
                    self._bindings[phone] = device_key
                    self._device_keys[device_key] = phone
                    new_count += 1
            self._save()
            self._synced_from_server = True

        nurture_log(f'[绑定] 从服务端同步 {new_count} 条新绑定 (总计 {len(self._bindings)} 条)')
        return new_count

    def _bind_via_api(self, phone: str, device_key: str) -> bool:
        """通过服务端 API 持久化绑定"""
        if not _SERVER_BASE_URL:
            return False
        resp = _server_post('/api/client/bind_device', {
            'phone': phone,
            'device_key': device_key,
        })
        if resp.get('status') == 'success':
            return True
        nurture_log(f'[绑定] API绑定失败 {phone}: {resp.get("message", "")}')
        return False

    def bind(self, phone: str, device_key: str = None, user_agent: str = None) -> str:
        """
        绑定账号到机型（或自动分配），绑定后不可更换
        - 优先从 accounts.json 的 user_agent 匹配真实机型
        - 优先从服务端获取已有绑定
        - 新绑定通过 API 持久化到服务端数据库
        - 本地 JSON 作为缓存
        返回: 分配的 device_key
        """
        with self._lock:
            # 已有本地缓存绑定 → 直接返回
            if phone in self._bindings:
                return self._bindings[phone]

        # 尝试从服务端获取已有绑定
        if _SERVER_BASE_URL and not self._synced_from_server:
            self.sync_from_server()
            with self._lock:
                if phone in self._bindings:
                    return self._bindings[phone]

        # 新绑定：确定 device_key
        if not (device_key and device_key in DEVICE_TEMPLATES):
            all_keys = sorted(DEVICE_TEMPLATES.keys())  # 提前定义，避免 UA 匹配成功后下方代码访问不到
            # 1. 优先从 user_agent 匹配真实设备
            if user_agent:
                matched = match_device_from_ua(user_agent)
                if matched:
                    device_key = matched
                    nurture_log(f'[绑定] {phone} UA匹配 → {device_key} ({DEVICE_TEMPLATES.get(device_key, {}).get("brand","")} {DEVICE_TEMPLATES.get(device_key, {}).get("model","")})')
            # 2. 自动分配：根据手机号哈希选择机型
            if not (device_key and device_key in DEVICE_TEMPLATES):
                phone_hash = int(hashlib.md5(phone.encode()).hexdigest(), 16)
                with self._lock:
                    used_keys = set(self._device_keys.keys())
                available = [k for k in all_keys if k not in used_keys]
                if available:
                    idx = phone_hash % len(available)
                    device_key = available[idx]
                else:
                    idx = phone_hash % len(all_keys)
                    device_key = all_keys[idx]

        # 持久化：优先服务端 API，本地 JSON 兜底
        api_ok = self._bind_via_api(phone, device_key)

        with self._lock:
            self._bindings[phone] = device_key
            self._device_keys[device_key] = phone
            self._save()

        persistence = 'DB' if api_ok else '本地'
        dev_info = DEVICE_TEMPLATES.get(device_key, {})
        nurture_log(f'[绑定] {phone} → {device_key} ({dev_info.get("brand","")} {dev_info.get("model","")}) [{persistence}]')
        return device_key

    def get_device(self, phone: str) -> Optional[Dict]:
        """获取账号绑定的机型参数，未绑定返回 None"""
        with self._lock:
            dk = self._bindings.get(phone)
            if dk:
                return DEVICE_TEMPLATES.get(dk)
        return None

    def get_device_key(self, phone: str) -> Optional[str]:
        """获取账号绑定的 device_key"""
        with self._lock:
            return self._bindings.get(phone)

    def get_all_bindings(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._bindings)

    def get_pool_index(self, phone: str) -> int:
        """获取账号绑定的 WebView UA 池索引"""
        dk = self.get_device_key(phone)
        if dk and dk in DEVICE_KEY_TO_POOL_INDEX:
            return DEVICE_KEY_TO_POOL_INDEX[dk]
        return abs(hash(phone)) % len(_WEBVIEW_UA_POOL)


# ==================== HAR 解析与行为学习 ====================
class HARBehaviorLearner:
    """
    从 HAR 抓包文件中学习真机请求序列和行为模式

    HAR 格式: Chrome DevTools Network export
    提取内容:
      - 请求序列 (URL, method, headers, body)
      - 设备指纹参数 (mt-r, mt-sn, User-Agent, 友盟等)
      - 时间间隔模式
      - CDN 节点分布
    """

    def __init__(self, learn_dir: str = HAR_LEARN_DIR):
        self._learn_dir = learn_dir
        self._sequences: List[Dict] = []           # 学习到的行为序列
        self._device_fingerprints: Dict[str, Dict] = {}  # device_key -> 指纹参数
        self._timing_patterns: List[float] = []     # 请求间隔模式
        self._cdn_nodes: Dict[str, set] = defaultdict(set)  # 域名 -> IP集合
        self._lock = threading.Lock()
        self._load_learned()

    def _learned_file(self) -> str:
        return os.path.join(self._learn_dir, 'learned_behaviors.json')

    def _load_learned(self):
        fpath = self._learned_file()
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._sequences = data.get('sequences', [])
                self._timing_patterns = data.get('timings', [])
                self._cdn_nodes = defaultdict(set, {k: set(v) for k, v in data.get('cdn_nodes', {}).items()})
                nurture_log(f'[HAR学习] 加载 {len(self._sequences)} 条行为序列, '
                           f'{len(self._timing_patterns)} 个时间模式')
            except Exception as e:
                nurture_log(f'[HAR学习] 加载失败: {e}')

    def _save_learned(self):
        fpath = self._learned_file()
        try:
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump({
                    'sequences': self._sequences[-500:],  # 最多保留500条
                    'timings': self._timing_patterns[-1000:],
                    'cdn_nodes': {k: list(v) for k, v in self._cdn_nodes.items()},
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            nurture_log(f'[HAR学习] 保存失败: {e}')

    def parse_har(self, har_path: str, device_key: str = None) -> Dict:
        """
        解析 HAR 文件，提取行为序列和设备指纹

        返回: {
            'entries': [...],           # 解析后的请求条目
            'device_fingerprint': {...}, # 提取的设备指纹
            'cdn_nodes': {...},         # CDN节点分布
            'behavior_sequence': [...],  # 行为序列
            'entry_count': int,         # 总请求数
        }
        """
        try:
            with open(har_path, 'r', encoding='utf-8') as f:
                har_data = json.load(f)
        except Exception as e:
            nurture_log(f'[HAR解析] 文件读取失败 {har_path}: {e}')
            return {'error': str(e)}

        entries = har_data.get('log', {}).get('entries', [])
        if not entries:
            nurture_log(f'[HAR解析] 空 HAR 文件: {har_path}')
            return {'error': 'empty HAR'}

        parsed_entries = []
        device_fp = {}
        cdn_nodes = defaultdict(set)
        behavior_sequence = []
        last_time = None
        timings = []

        for i, entry in enumerate(entries):
            req = entry.get('request', {})
            resp = entry.get('response', {})
            url = req.get('url', '')
            method = req.get('method', '')
            server_ip = entry.get('serverIPAddress', '')
            started = entry.get('startedDateTime', '')

            # 时间解析
            try:
                req_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
            except Exception:
                req_time = None

            # 提取域名和CDN
            from urllib.parse import urlparse
            try:
                parsed = urlparse(url)
                domain = parsed.netloc
                path = parsed.path
            except Exception:
                domain, path = '', url

            if server_ip:
                cdn_nodes[domain].add(server_ip)

            # 提取请求头中的设备指纹
            req_headers = {}
            for h in req.get('headers', []):
                name = h.get('name', '').lower()
                value = h.get('value', '')
                req_headers[name] = value

            # 提取关键设备指纹
            fp_extracted = {}
            for fp_key in ['mt-r', 'mt-sn', 'mt-device-id', 'mt-token', 'user-agent',
                          'bs-dvid', 'x-requested-with', 'content-info-bb',
                          'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform']:
                if fp_key in req_headers:
                    fp_extracted[fp_key] = req_headers[fp_key]

            # 提取 Cookie 中的指纹
            cookie_str = req_headers.get('cookie', '')
            for cookie_key in ['_bs_device_id', '_d_u', 'MT-Token-Wap', 'MT-Device-ID-Wap']:
                if cookie_key in cookie_str:
                    # 简单提取（不做完整解析）
                    start = cookie_str.find(cookie_key + '=')
                    if start >= 0:
                        end = cookie_str.find(';', start)
                        if end < 0:
                            end = len(cookie_str)
                        fp_extracted[f'cookie_{cookie_key}'] = cookie_str[start+len(cookie_key)+1:end]

            if fp_extracted and device_key:
                if device_key not in self._device_fingerprints:
                    self._device_fingerprints[device_key] = fp_extracted
                else:
                    # 合并新发现的指纹字段
                    self._device_fingerprints[device_key].update(fp_extracted)

            # 时间间隔
            if req_time:
                if last_time:
                    delta = (req_time - last_time).total_seconds()
                    if 0 < delta < 60:  # 合理范围
                        timings.append(delta)
                last_time = req_time

            # 行为序列记录
            entry_info = {
                'index': i,
                'url': f'{domain}{path}',
                'method': method,
                'status': resp.get('status', 0),
                'server_ip': server_ip,
                'fingerprint_keys': list(fp_extracted.keys()),
            }
            parsed_entries.append(entry_info)

            # 识别关键行为
            if '/rushPurchase' in url:
                behavior_sequence.append({'action': 'rush_purchase', 'time': started, 'url': url})
            elif '/item/detail' in url:
                behavior_sequence.append({'action': 'view_product', 'time': started, 'url': url})
            elif '/purchaseInfo' in url:
                behavior_sequence.append({'action': 'check_purchase', 'time': started, 'url': url})
            elif '/resource/get' in url:
                behavior_sequence.append({'action': 'homepage', 'time': started, 'url': url})
            elif '/category' in url.lower():
                behavior_sequence.append({'action': 'browse_category', 'time': started, 'url': url})
            elif '/order/list' in url:
                behavior_sequence.append({'action': 'check_orders', 'time': started, 'url': url})
            elif '/address' in url:
                behavior_sequence.append({'action': 'check_address', 'time': started, 'url': url})
            elif '/bangcle' in url:
                behavior_sequence.append({'action': 'anti_fraud', 'time': started, 'url': url})

        # 更新学习数据
        with self._lock:
            self._sequences.append({
                'source': os.path.basename(har_path),
                'device_key': device_key,
                'entry_count': len(entries),
                'behavior_sequence': behavior_sequence,
                'timings': timings,
                'parsed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })
            self._timing_patterns.extend(timings)
            for domain, ips in cdn_nodes.items():
                self._cdn_nodes[domain].update(ips)
            self._save_learned()

        nurture_log(f'[HAR解析] {har_path}: {len(entries)}请求, '
                   f'{len(behavior_sequence)}关键行为, {len(timings)}时间间隔, '
                   f'设备={device_key or "未指定"}')

        return {
            'entries': parsed_entries,
            'device_fingerprint': device_fp or self._device_fingerprints.get(device_key, {}),
            'cdn_nodes': {k: list(v) for k, v in cdn_nodes.items()},
            'behavior_sequence': behavior_sequence,
            'entry_count': len(entries),
            'device_key': device_key,
        }

    def get_behavior_template(self) -> List[Dict]:
        """获取推荐的行为模板（基于学习数据）"""
        with self._lock:
            if not self._sequences:
                return self._default_template()
            # 取最近的一条序列作为模板
            latest = self._sequences[-1]
            return latest.get('behavior_sequence', self._default_template())

    def _default_template(self) -> List[Dict]:
        """默认行为模板（基于常见真机行为）"""
        return [
            {'action': 'anti_fraud', 'desc': '邦盛设备验证'},
            {'action': 'homepage', 'desc': '浏览首页'},
            {'action': 'view_product', 'desc': '浏览商品详情'},
            {'action': 'check_purchase', 'desc': '查看购买信息'},
            {'action': 'browse_category', 'desc': '浏览分类'},
            {'action': 'check_orders', 'desc': '查看订单'},
            {'action': 'check_address', 'desc': '查看收货地址'},
        ]

    def get_timing_stats(self) -> Dict:
        """获取时间间隔统计"""
        with self._lock:
            if not self._timing_patterns:
                return {'min': 1.0, 'max': 10.0, 'avg': 5.0, 'median': 5.0}
            sorted_t = sorted(self._timing_patterns)
            n = len(sorted_t)
            return {
                'min': sorted_t[0],
                'max': sorted_t[-1],
                'avg': sum(sorted_t) / n,
                'median': sorted_t[n // 2],
                'count': n,
            }

    def get_cdn_nodes(self, domain: str = None) -> Dict:
        """获取已知CDN节点"""
        with self._lock:
            if domain:
                return {domain: list(self._cdn_nodes.get(domain, set()))}
            return {k: list(v) for k, v in self._cdn_nodes.items()}


# ==================== 养号行为状态机 ====================
class NurtureStateMachine:
    """
    养号行为状态机 — 模拟真机用户浏览链路

    状态流转:
      IDLE → WARMUP → HOME → CATEGORY → PRODUCT_DETAIL →
      PURCHASE_INFO → CART → ORDERS → RUSH_CHECK → IDLE

    每个状态随机停留 3-10 秒，模拟真人浏览节奏
    """

    STATES = [
        'IDLE',
        'WARMUP',           # 启动预热（邦盛验证）
        'SECURITY_PING',    # 安全SDK上报（haotian/mshield/bangcle_upload/sp_exist/event_track）
        'HOME',             # 浏览首页
        'COIN_CHECK',       # 查看小茅运/耐力值（必须在haotian/mshield之后）
        'CATEGORY',         # 浏览分类
        'PRODUCT_DETAIL',   # 浏览商品详情
        'PURCHASE_INFO',    # 查看购买信息
        'GAME_CHECK',       # 小茅运游戏互动
        'RESERVATION',      # 查看预约列表
        'ORDERS',           # 查看订单列表
        'RUSH_CHECK',       # 抢购商品4030检测
    ]

    def __init__(self, learner: HARBehaviorLearner = None):
        self._learner = learner
        self._state = 'IDLE'
        self._cycle_count = 0
        # 基于学习数据的行为模板
        self._template = learner.get_behavior_template() if learner else None

    def next_state(self, rush_check_needed: bool = False) -> str:
        """获取下一个养号状态"""
        if self._state == 'IDLE':
            self._state = 'WARMUP'
            return self._state

        # 按真机浏览顺序流转：安全SDK→首页→小茅运→分类→商品→购买→游戏→预约→订单
        state_order = [
            'WARMUP', 'SECURITY_PING', 'HOME', 'COIN_CHECK',
            'CATEGORY', 'PRODUCT_DETAIL', 'PURCHASE_INFO',
            'GAME_CHECK', 'RESERVATION', 'ORDERS'
        ]

        try:
            idx = state_order.index(self._state)
            if idx < len(state_order) - 1:
                self._state = state_order[idx + 1]
            else:
                # 周期性加入抢购检测
                if rush_check_needed:
                    self._state = 'RUSH_CHECK'
                else:
                    self._state = 'HOME'  # 重新循环
        except ValueError:
            self._state = 'HOME'

        self._cycle_count += 1
        return self._state

    @property
    def state(self) -> str:
        return self._state

    def get_stay_duration(self) -> float:
        """获取当前状态的随机停留时间（秒）"""
        if self._state == 'RUSH_CHECK':
            return random.uniform(RUSH_CHECK_MIN, RUSH_CHECK_MAX)
        # 使用学习数据优化停留时间
        if self._learner:
            stats = self._learner.get_timing_stats()
            avg = stats.get('avg', 5.0)
            return random.uniform(max(2.0, avg - 2), min(15.0, avg + 3))
        return random.uniform(PAGE_STAY_MIN, PAGE_STAY_MAX)


# ==================== CDN健康检测器 ====================
class CDNHealthChecker:
    """CDN节点健康检测：2000=可用, 429=限流"""

    def __init__(self):
        self._health: Dict[str, Dict] = {}  # cdn_node -> {status, last_check, fail_count}
        self._lock = threading.Lock()

    def record_response(self, cdn_node: str, http_status: int, code: int) -> str:
        """
        记录CDN节点响应，返回状态标签

        返回: 'ok' | 'throttled' | 'error' | 'unknown'
        """
        now = time.time()
        with self._lock:
            if cdn_node not in self._health:
                self._health[cdn_node] = {'status': 'unknown', 'last_check': now,
                                          'fail_count': 0, 'success_count': 0}

            h = self._health[cdn_node]
            h['last_check'] = now

            if code == 2000:
                h['status'] = 'ok'
                h['success_count'] += 1
                h['fail_count'] = 0
                return 'ok'
            elif http_status == 429 or code == 429:
                h['status'] = 'throttled'
                h['fail_count'] += 1
                return 'throttled'
            else:
                h['fail_count'] += 1
                if h['fail_count'] >= 3:
                    h['status'] = 'error'
                return 'error'

    def is_healthy(self, cdn_node: str) -> bool:
        with self._lock:
            h = self._health.get(cdn_node, {})
            return h.get('status') == 'ok'

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                node: {
                    'status': info['status'],
                    'success': info['success_count'],
                    'fail': info['fail_count'],
                }
                for node, info in self._health.items()
            }


# ==================== 养号会话管理器 ====================
class NurtureSessionManager:
    """
    养号会话管理器 — 协调多账号养号流程

    使用方式（在 moutai_client_worker.py 的 async_main 中调用）:
      from nurture_account import NurtureSessionManager
      nurture_mgr = NurtureSessionManager()
      # 在非快抢分支:
      result = await loop.run_in_executor(None,
          nurture_mgr.run_cycle, tasks, clients, proxy_cache, account_cdn_mode, round_num)
    """

    def __init__(self):
        self._binding = AccountDeviceBinding()
        self._learner = HARBehaviorLearner()
        self._state_machines: Dict[str, NurtureStateMachine] = {}  # phone -> state_machine
        self._cdn_health = CDNHealthChecker()
        self._round_count = 0
        self._rush_check_phones: Dict[str, float] = {}  # phone -> last_check_time
        self._last_nurture_ping: Dict[str, float] = {}  # phone -> last nurture ping timestamp
        self._last_pre_rush_ping: Dict[str, str] = {}   # phone -> last rush window key (HH:MM)
        self._account_stats: Dict[str, Dict] = defaultdict(lambda: {
            'nurture_cycles': 0,
            'cdn_ok': 0,
            'cdn_429': 0,
            'rush_4030': 0,
            'rush_2000': 0,
            'errors': 0,
        })
        # 养号浏览的多商品池（从HAR文件提取）
        # 真机抓包发现的所有SPU，模拟正常用户逛多种商品的行为
        self._browse_products = [
            # 已确认商品
            {'spu': 'IMTP1000313', 'sku': '741', 'name': '飞天53%vol 500ml', 'price': 1539},
            {'spu': 'IMTP1000006', 'sku': '10193', 'name': '299元商品', 'price': 299},
            {'spu': 'IMTP1000151', 'sku': '1000061', 'name': '大曲188', 'price': 188},
            {'spu': 'IMTP1000117', 'sku': '10170', 'name': '1639商品', 'price': 1639},
            # HAR新发现：dc.moutai519.com.cn 云商列表商品
            {'spu': 'IMTP1000196', 'sku': '', 'name': '云商商品0196', 'price': 0},
            {'spu': 'IMTP1000296', 'sku': '', 'name': '云商商品0296', 'price': 0},
            {'spu': 'IMTP1000329', 'sku': '', 'name': '云商商品0329', 'price': 0},
            {'spu': 'IMTP1000330', 'sku': '', 'name': '云商商品0330', 'price': 0},
            {'spu': 'IMTP1000331', 'sku': '', 'name': '云商商品0331', 'price': 0},
            {'spu': 'IMTP1000332', 'sku': '', 'name': '云商商品0332', 'price': 0},
            {'spu': 'IMTP1000333', 'sku': '', 'name': '云商商品0333', 'price': 0},
            {'spu': 'IMTP1000334', 'sku': '', 'name': '云商商品0334', 'price': 0},
        ]

    def sync_bindings_from_server(self) -> int:
        """启动时从服务端同步所有设备绑定
        返回: 同步到的绑定数量"""
        return self._binding.sync_from_server()

    def parse_har_file(self, har_path: str, device_key: str = None) -> Dict:
        """解析HAR文件并增量学习"""
        return self._learner.parse_har(har_path, device_key)

    def bind_account(self, phone: str, device_key: str = None, user_agent: str = None) -> str:
        """绑定账号到机型（不可更换）"""
        return self._binding.bind(phone, device_key, user_agent)

    def get_account_device(self, phone: str) -> Optional[Dict]:
        """获取账号绑定的机型参数"""
        return self._binding.get_device(phone)

    def get_account_device_key(self, phone: str) -> Optional[str]:
        """获取账号绑定的 device_key"""
        return self._binding.get_device_key(phone)

    def get_all_bindings(self) -> Dict[str, str]:
        return self._binding.get_all_bindings()

    def run_cycle(self, tasks: List[Dict], clients: List[MoutaiClient],
                  proxy_cache: Dict, account_cdn_mode: Dict,
                  round_num: int) -> Dict:
        """
        执行一轮养号（同步方法，在 executor 中运行）

        参数:
          tasks:           账号任务列表
          clients:         MoutaiClient 实例列表（与 tasks 一一对应）
          proxy_cache:     代理配置 {'enabled': bool, 'url': str}
          account_cdn_mode: CDN锁定模式 {phone: 'direct'|proxy_ip}
          round_num:       当前轮次

        返回: {
          'accounts_processed': int,
          'behaviors': [...],
          'cdn_health': {...},
          'rush_checks': [...],
          'errors': [...],
        }
        """
        self._round_count += 1
        round_start = time.time()

        # 限制每轮处理账号数
        active = list(enumerate(zip(tasks, clients)))
        if len(active) > MAX_ACCOUNTS_PER_CYCLE:
            # 轮转选择
            start_idx = (self._round_count * MAX_ACCOUNTS_PER_CYCLE) % len(active)
            active = (active[start_idx:] + active[:start_idx])[:MAX_ACCOUNTS_PER_CYCLE]

        behavior_log = []
        rush_check_results = []
        errors = []

        # 是否需要在本次做抢购4030检测
        need_rush_check = (self._round_count % RUSH_CHECK_INTERVAL == 0)

        # === 20:00-21:00 快抢高峰：停止养号，每轮只进入商品页面一次 ===
        now_hour = datetime.now().hour
        if now_hour == 20:
            for idx, (task, client) in active:
                phone = task.get('phone', '')
                if not phone:
                    continue
                saved_proxy = client.proxy
                # 根据CDN锁定模式决定代理
                locked_mode = account_cdn_mode.get(phone)
                if locked_mode is not None:
                    client.proxy = None if locked_mode == 'direct' else locked_mode
                elif not proxy_cache.get('enabled'):
                    client.proxy = None
                try:
                    product = random.choice(self._browse_products)
                    detail = client.get_item_detail_v2(product['spu'])
                    if detail:
                        nurture_log(f'[{phone}] 商品页(20点) ✓ '
                                   f'{detail.get("title", product["name"])} '
                                   f'¥{detail.get("price","?")} sku={detail.get("default_sku_id","?")}')
                        behavior_log.append({
                            'phone': phone, 'state': 'PRODUCT_DETAIL', 'stay': 0,
                            'device': task.get('device_key', ''),
                            'result': {'action': 'PRODUCT_DETAIL', 'http_status': 200,
                                       'code': 2000, 'cdn_status': 'ok'},
                        })
                    else:
                        nurture_log(f'[{phone}] 商品页(20点) ✗ 空数据')
                        errors.append({'phone': phone, 'state': 'PRODUCT_DETAIL', 'error': '空数据'})
                except Exception as e:
                    nurture_log(f'[{phone}] 商品页(20点) ✗: {e}')
                    errors.append({'phone': phone, 'state': 'PRODUCT_DETAIL', 'error': str(e)[:100]})
                finally:
                    client.proxy = saved_proxy
                time.sleep(random.uniform(0.3, 1.0))
            elapsed = time.time() - round_start
            summary = {
                'round': round_num,
                'accounts_processed': len(active),
                'behaviors': behavior_log,
                'cdn_health': self._cdn_health.get_stats(),
                'rush_checks': rush_check_results,
                'errors': errors,
                'elapsed': round(elapsed, 1),
                'rush_hour_skip': True,
            }
            nurture_log(f'[第{round_num}轮·20点简化] {len(active)}账号 | 仅商品页 | '
                       f'成功={len(behavior_log)} 失败={len(errors)} | 耗时={elapsed:.1f}s')
            return summary

        for idx, (task, client) in active:
            phone = task.get('phone', '')
            if not phone:
                continue

            # 获取或创建状态机
            if phone not in self._state_machines:
                self._state_machines[phone] = NurtureStateMachine(self._learner)
            sm = self._state_machines[phone]

            # 确保账号已绑定机型（优先使用服务端下发的 device_key，否则自动绑定并上报）
            device_key = task.get('device_key', '') or self._binding.get_device_key(phone)
            if not device_key:
                device_key = self._binding.bind(phone, user_agent=task.get('user_agent', ''))
            elif device_key and phone not in [k for k in self._binding.get_all_bindings()]:
                # 服务端有绑定但本地无缓存 → 自动加载
                self._binding.bind(phone, device_key, task.get('user_agent', ''))

            # 检查是否需要做抢购检测
            do_rush_check = need_rush_check
            if not do_rush_check:
                last_check = self._rush_check_phones.get(phone, 0)
                if time.time() - last_check > 600:  # 至少10分钟做一次
                    do_rush_check = True

            # 获取下一个行为状态
            state = sm.next_state(rush_check_needed=do_rush_check)
            stay = sm.get_stay_duration()

            # 保存原始代理设置
            saved_proxy = client.proxy
            proxy_enabled = proxy_cache.get('enabled', False)

            try:
                result = self._execute_behavior(
                    phone, client, state, stay, proxy_cache, account_cdn_mode)
                behavior_log.append({
                    'phone': phone, 'state': state, 'stay': round(stay, 1),
                    'device': device_key, 'result': result,
                })

                # 更新账号统计
                stats = self._account_stats[phone]
                stats['nurture_cycles'] += 1
                if result.get('cdn_status') == 'ok':
                    stats['cdn_ok'] += 1
                elif result.get('cdn_status') == 'throttled':
                    stats['cdn_429'] += 1

                if state == 'RUSH_CHECK':
                    rush_check_results.append({
                        'phone': phone, 'result': result,
                    })
                    self._rush_check_phones[phone] = time.time()
                    if result.get('code') == 4030:
                        stats['rush_4030'] += 1
                    elif result.get('code') == 2000:
                        stats['rush_2000'] += 1

                if result.get('error'):
                    stats['errors'] += 1

            except Exception as e:
                errors.append({'phone': phone, 'state': state, 'error': str(e)})
                self._account_stats[phone]['errors'] += 1
            finally:
                client.proxy = saved_proxy

            # 行为间短暂间隔（模拟真人节奏）
            time.sleep(random.uniform(0.5, 2.0))

        elapsed = time.time() - round_start
        summary = {
            'round': round_num,
            'accounts_processed': len(active),
            'behaviors': behavior_log,
            'cdn_health': self._cdn_health.get_stats(),
            'rush_checks': rush_check_results,
            'errors': errors,
            'elapsed': round(elapsed, 1),
        }

        # 汇总日志
        state_counts = defaultdict(int)
        for b in behavior_log:
            state_counts[b['state']] += 1
        state_str = ' | '.join(f'{k}:{v}' for k, v in sorted(state_counts.items()))
        cdn_ok = sum(1 for b in behavior_log if b['result'].get('cdn_status') == 'ok')
        cdn_429 = sum(1 for b in behavior_log if b['result'].get('cdn_status') == 'throttled')
        rush_4030 = sum(1 for r in rush_check_results if r['result'].get('code') == 4030)
        nurture_log(f'[第{round_num}轮] {len(active)}账号 | {state_str} | '
                    f'CDN:OK={cdn_ok}/429={cdn_429} | 4030={rush_4030} | '
                    f'错误={len(errors)} | 耗时={elapsed:.1f}s')

        return summary

    def _send_umeng(self, client: MoutaiClient, phone: str) -> bool:
        """友盟启动日志 (cnlogs.umeng.com/unify_logs)"""
        try:
            umeng_url = "https://cnlogs.umeng.com/unify_logs"
            umeng_headers = {
                "X-Umeng-UTC": str(int(time.time() * 1000)),
                "X-Umeng-Sdk": f"i/1.2.0 {APP_VERSION}/Android fc80117c334ae2991ee6ab5a686e3bd",
                "Content-Type": "ut/i",
                "Msg-Type": "envelope/json",
                "X-Umeng-Pro-Ver": "1.0.0",
                "SM-IMP": "1",
                "User-Agent": "Dalvik/2.1.0 (Linux; U; Android )",
            }
            _post(umeng_url, headers=umeng_headers, data=b'',
                  proxy=client.proxy, timeout=5)
            return True
        except Exception as e:
            nurture_log(f'[{phone}] 友盟日志 ✗: {e}')
            return False

    def _send_sp_exist(self, client: MoutaiClient, phone: str) -> bool:
        """安全SDK存在性检测 (POST /moutai/sdk/v1/sp/exist)"""
        try:
            sp_url = f"{BASE_URL}/moutai/sdk/v1/sp/exist"
            sp_headers = {
                "MT-Token": client.token or "",
                "MT-Device-ID": client.mt_device_id,
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "okhttp/4.9.2",
            }
            _post(sp_url, headers=sp_headers, json={},
                  proxy=client.proxy, timeout=5)
            return True
        except Exception as e:
            nurture_log(f'[{phone}] SDK检测 ✗: {e}')
            return False

    def _send_event_track(self, client: MoutaiClient, phone: str) -> bool:
        """数据中心事件追踪 (dc.moutai519.com.cn/upload/mt-mall/event-tracking/app/v1)"""
        try:
            event_url = "https://dc.moutai519.com.cn/upload/mt-mall/event-tracking/app/v1"
            event_headers = {
                "charset": "UTF-8",
                "level": "INFO",
                "Content-Type": "application/json",
                "User-Agent": client.webview_ua,
            }
            event_body = {
                "OS_V": "android14",
                "YXS_v": "4",
                "model_Id": "Xiaomi 2211133C",
                "net_type": "wifi",
                "resolution": client.screen or "1080*2166",
                "uid": client.user_id or "",
                "uuid": client.mt_device_id[:32] if client.mt_device_id else "",
                "timestamp_s": int(time.time() * 1000),
                "frequency": "10000",
                "events": [{
                    "app_v": f"MT {APP_VERSION}/197",
                    "event_action": "special",
                    "event_name": "special_default_cdndecrypt",
                    "locpage": "moutaiapp://launchpage",
                    "log_source": "mtapp",
                    "page_name": "default",
                    "parameters": {"code": 0, "sequen": 36},
                    "sessionid": f"{client.mt_device_id[:32] if client.mt_device_id else ''}{int(time.time()*1000)}",
                    "timestamp_a": int(time.time() * 1000),
                }],
            }
            _post(event_url, headers=event_headers, json=event_body,
                  proxy=client.proxy, timeout=5)
            return True
        except Exception as e:
            nurture_log(f'[{phone}] 事件追踪 ✗: {e}')
            return False

    def _simulate_security_ping(self, client: MoutaiClient, phone: str,
                               for_rush: bool = False) -> Dict:
        """
        模拟真机安全SDK上报链（必须在敏感接口前执行）

        Args:
            for_rush: True=抢购前调用(无频率限制), False=养号调用(最多5次/小时)

        2026-05-25 最终方案: haotian/mshield 固定 body 重放
        ┌──────────────────────────────────────────────────────────┐
        │ ✓ HAR抓包提取 → body无时效性验证 → 固定重放可行        │
        │   haotian: 4条路径 (p/5/aio→p/1/r→r/5/c→c/11/z)       │
        │   mshield: 2条路径 (p/1/r→s/5/aio)                     │
        │   所有账号共用同一套加密body（服务器不校验绑定关系）     │
        │   养号频率限制: 每12分钟最多1次 (≤5次/小时)            │
        │   抢前调用: 无限制（每次快抢前1-2分钟调用1次）          │
        └──────────────────────────────────────────────────────────┘

        安全链调用顺序（按 HAR 真机时序）:
        0. haotian   (p/5/aio→p/1/r→r/5/c→c/11/z) — 固定body重放
        0. mshield   (p/1/r→s/5/aio) — 固定body重放
        1. umeng     (cnlogs.umeng.com) — 友盟启动日志
        2. sp/exist  (/moutai/sdk/v1/sp/exist) — 安全SDK存在性检测
        3. event_track (dc.moutai519.com.cn) — 事件追踪
        """
        results = {}

        # 养号频率限制: 每12分钟最多1次 (≤5次/小时)
        now_ts = time.time()
        if not for_rush:
            last = self._last_nurture_ping.get(phone, 0)
            if now_ts - last < 720:  # 12分钟冷却
                results['haotian'] = 'throttled'
                results['mshield'] = 'throttled'
                # 轻量接口照常发送（无频率限制）
                results['umeng'] = self._send_umeng(client, phone)
                results['sp_exist'] = self._send_sp_exist(client, phone)
                results['event_track'] = self._send_event_track(client, phone)
                ok_count = sum(1 for v in results.values() if v is True)
                nurture_log(f'[{phone}] 安全链 {ok_count}/{len(results)} HTTP ✓ '
                            f'(haotian=节流 mshield=节流)')
                return results
            self._last_nurture_ping[phone] = now_ts

        # 0a. haotian 百度设备指纹SDK — 4条固定body重放
        haotian_ok = 0
        for entry in HAOTIAN_BODIES:
            try:
                body = base64.b64decode(entry['body_b64'])
                _post(entry['url'], headers=entry['headers'], data=body,
                      proxy=client.proxy, timeout=5)
                haotian_ok += 1
            except Exception:
                pass
        results['haotian'] = (haotian_ok == len(HAOTIAN_BODIES))

        # 0b. mshield 百度盾SDK — 2条固定body重放
        mshield_ok = 0
        for entry in MSHIELD_BODIES:
            try:
                body = base64.b64decode(entry['body_b64'])
                _post(entry['url'], headers=entry['headers'], data=body,
                      proxy=client.proxy, timeout=5)
                mshield_ok += 1
            except Exception:
                pass
        results['mshield'] = (mshield_ok == len(MSHIELD_BODIES))

        results['umeng'] = self._send_umeng(client, phone)
        results['sp_exist'] = self._send_sp_exist(client, phone)
        results['event_track'] = self._send_event_track(client, phone)

        ok_count = sum(1 for v in results.values() if v is True)
        hao = f"{haotian_ok}/{len(HAOTIAN_BODIES)}" if results['haotian'] else f"{haotian_ok}/{len(HAOTIAN_BODIES)}✗"
        ms = f"{mshield_ok}/{len(MSHIELD_BODIES)}" if results['mshield'] else f"{mshield_ok}/{len(MSHIELD_BODIES)}✗"
        nurture_log(f'[{phone}] 安全链 {ok_count}/{len(results)} HTTP ✓ '
                    f'(haotian={hao} mshield={ms})')
        return results

    def pre_rush_security_ping(self, tasks: List[Dict], clients: List[MoutaiClient],
                               proxy_cache: Dict, account_cdn_mode: Dict) -> bool:
        """
        抢购前安全链上报（1-2分钟前调用一次）

        每个快抢窗口（如 20:00）只调用一次，每个账号独立。
        与养号节流独立——抢前调用不受频率限制。

        返回: True=已执行, False=本窗口已执行过（跳过）
        """
        now = datetime.now()
        window_key = f"{now.hour:02d}:{now.minute // 5 * 5:02d}"  # 五分钟窗口标识

        # 检查是否已为本窗口执行过
        executed = False
        for task, client in zip(tasks, clients):
            phone = task.get('phone', '')
            if not phone:
                continue
            last_key = self._last_pre_rush_ping.get(phone, '')
            if last_key == window_key:
                continue  # 本窗口已执行

            executed = True
            self._last_pre_rush_ping[phone] = window_key

            # 保存原始代理
            saved_proxy = client.proxy
            try:
                locked_mode = account_cdn_mode.get(phone)
                if locked_mode is not None:
                    if locked_mode == 'direct':
                        client.proxy = None
                    else:
                        client.proxy = locked_mode
                elif not proxy_cache.get('enabled'):
                    client.proxy = None

                nurture_log(f'[{phone}] 抢前安全链上报...')
                self._simulate_security_ping(client, phone, for_rush=True)
            except Exception as e:
                nurture_log(f'[{phone}] 抢前安全链 ✗: {e}')
            finally:
                client.proxy = saved_proxy

        if executed:
            nurture_log(f'[抢前安全链] 窗口={window_key} 已上报')
        return executed

    def _execute_behavior(self, phone: str, client: MoutaiClient, state: str,
                          stay: float, proxy_cache: Dict,
                          account_cdn_mode: Dict) -> Dict:
        """
        执行具体的养号行为

        返回: {action, http_status, code, cdn_status, server_ip, error}
        """
        result = {
            'action': state,
            'http_status': 0,
            'code': -1,
            'cdn_status': 'unknown',
            'server_ip': '',
            'error': '',
        }

        # 随机选择一个商品用于浏览（模拟真机逛不同商品）
        product = random.choice(self._browse_products)
        browse_spu = product['spu']
        browse_sku = product['sku']
        browse_name = product['name']

        # 根据CDN锁定模式决定代理
        locked_mode = account_cdn_mode.get(phone)
        if locked_mode is not None:
            if locked_mode == 'direct':
                client.proxy = None
            else:
                client.proxy = locked_mode
        elif not proxy_cache.get('enabled'):
            client.proxy = None

        try:
            if state == 'WARMUP':
                # 邦盛设备验证（预热）
                ok = client.bangcle_verify(force=True)
                result['code'] = 2000 if ok else -1
                result['http_status'] = 200 if ok else -1
                result['cdn_status'] = 'ok' if ok else 'error'
                nurture_log(f'[{phone}] 预热{"✓" if ok else "✗"}')
                time.sleep(min(stay, 3.0))  # 预热不需要太长

            elif state == 'SECURITY_PING':
                # 安全SDK上报链（haotian→mshield→umeng→sp_exist→event_track）
                try:
                    sec_result = self._simulate_security_ping(client, phone)
                    http_ok = all(v is True for k, v in sec_result.items()
                                  if k not in ('haotian', 'mshield'))
                    result['code'] = 2000 if http_ok else -1
                    result['http_status'] = 200 if http_ok else -1
                    result['cdn_status'] = 'ok' if http_ok else 'error'
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 安全SDK链 ✗: {e}')
                time.sleep(min(stay, 3.0))

            elif state == 'HOME':
                # 浏览首页 — resource/get (真机首页请求)
                try:
                    home_url = f"https://static.moutai519.com.cn/mt-backend/xhr/front/mall/resource/get"
                    home_headers = {"User-Agent": client.user_agent, "Accept": "*/*"}
                    resp = _get(home_url, headers=home_headers,
                               proxy=client.proxy, timeout=8)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('code') == 2000:
                            home_data = data.get('data', {})
                            # 首页通常返回banner/推荐商品列表
                            banners = home_data.get('bannerList', home_data.get('banners', []))
                            items = home_data.get('itemList', home_data.get('items', []))
                            result['http_status'] = 200
                            result['code'] = 2000
                            result['cdn_status'] = 'ok'
                            # 提取实际内容用于日志
                            banner_names = []
                            for b in (banners if isinstance(banners, list) else []):
                                name = b.get('title', b.get('name', '')) if isinstance(b, dict) else ''
                                if name:
                                    banner_names.append(str(name)[:18])
                            item_names = []
                            for it in (items if isinstance(items, list) else []):
                                name = it.get('title', it.get('name', it.get('itemName', ''))) if isinstance(it, dict) else ''
                                if name:
                                    item_names.append(str(name)[:15])
                            b_str = ', '.join(banner_names[:3]) if banner_names else '-'
                            i_str = ', '.join(item_names[:4]) if item_names else '-'
                            nurture_log(f'[{phone}] 首页浏览 ✓ '
                                       f'(banner: {b_str} | 商品: {i_str}, 停留{stay:.1f}s)')
                        else:
                            result['http_status'] = resp.status_code
                            result['code'] = data.get('code', -1)
                            result['cdn_status'] = 'error'
                            nurture_log(f'[{phone}] 首页浏览 code={data.get("code")} raw={str(data)[:100]}')
                    else:
                        result['http_status'] = resp.status_code
                        result['cdn_status'] = 'error'
                        nurture_log(f'[{phone}] 首页浏览 HTTP {resp.status_code}')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 首页浏览 ✗: {e}')
                time.sleep(stay)

            elif state == 'COIN_CHECK':
                # 查看小茅运/耐力值
                # HAR证实: GET .../xmy/user/coin?scene=0 → {"xmyNum":20.99,"energy":50}
                # 注意: HAR中coin调用在sp/exist之前就已成功(code=2000)，安全链并非硬依赖
                try:
                    coin_url = f"{BASE_URL}/xhr/front/mall/index/xmy/user/coin"
                    coin_headers = client._app_headers()
                    resp = _get(coin_url, headers=coin_headers, params={"scene": 0},
                               proxy=client.proxy, timeout=8)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('code') == 2000:
                            coin_data = data.get('data', {})
                            xmy = coin_data.get("xmyNum", "?")
                            energy = coin_data.get("energy", "?")
                            result['http_status'] = 200
                            result['code'] = 2000
                            result['cdn_status'] = 'ok'
                            nurture_log(f'[{phone}] 小茅运 ✓ '
                                       f'(xmyNum={xmy}, energy={energy}, 停留{stay:.1f}s)')
                        else:
                            result['http_status'] = resp.status_code
                            result['code'] = data.get('code', -1)
                            result['cdn_status'] = 'error'
                            nurture_log(f'[{phone}] 小茅运 code={data.get("code")}')
                    else:
                        result['http_status'] = resp.status_code
                        result['cdn_status'] = 'error'
                        nurture_log(f'[{phone}] 小茅运 HTTP {resp.status_code}')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 小茅运 ✗: {e}')
                time.sleep(stay)

            elif state == 'CATEGORY':
                # 浏览分类 — 随机商品详情（模拟逛分类页后点进商品）
                try:
                    product2 = random.choice(self._browse_products)
                    detail = client.get_item_detail_v2(product2['spu'])
                    if detail:
                        result['http_status'] = 200
                        result['code'] = 2000
                        result['cdn_status'] = 'ok'
                        nurture_log(f'[{phone}] 分类浏览 ✓ '
                                   f'(商品={detail.get("title", product2["name"])} '
                                   f'¥{detail.get("price","?")} sku={detail.get("default_sku_id","?")}, '
                                   f'停留{stay:.1f}s)')
                    else:
                        result['http_status'] = 200
                        result['code'] = -1
                        result['cdn_status'] = 'error'
                        nurture_log(f'[{phone}] 分类浏览 ✗ (无数据), 停留{stay:.1f}s)')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 分类浏览 ✗: {e}')
                time.sleep(stay)

            elif state == 'PRODUCT_DETAIL':
                # 浏览商品详情
                try:
                    detail = client.get_item_detail_v2(browse_spu)
                    if detail:
                        result['http_status'] = 200
                        result['code'] = 2000
                        result['cdn_status'] = 'ok'
                        nurture_log(f'[{phone}] 商品详情 ✓ '
                                   f'(标题={detail.get("title", browse_name)} '
                                   f'¥{detail.get("price","?")} sku={detail.get("default_sku_id","?")}, '
                                   f'停留{stay:.1f}s)')
                    else:
                        result['http_status'] = 200
                        result['code'] = -1
                        result['cdn_status'] = 'error'
                        nurture_log(f'[{phone}] 商品详情 ✗ (空数据), 停留{stay:.1f}s)')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 商品详情 ✗: {e}')
                time.sleep(stay)

            elif state == 'PURCHASE_INFO':
                # 查看购买信息（库存/价格/活动ID）
                try:
                    purchase = client.get_purchase_info_v2(browse_spu)
                    if purchase:
                        result['http_status'] = 200
                        result['code'] = 2000
                        result['cdn_status'] = 'ok'
                        pinfo_map = purchase.get('purchaseInfoMap', {})
                        # 提取库存摘要
                        inventory_info = ''
                        for sku_key, sku_info in list(pinfo_map.items())[:2]:
                            pi = sku_info.get('purchaseInfo', {})
                            inv = pi.get('inventory', '?')
                            act = pi.get('itemPriorityActId', '?')
                            inventory_info += f' sku:{sku_key}=库存{inv}/活动{act}'
                        nurture_log(f'[{phone}] 购买信息 ✓ '
                                   f'({browse_name}{inventory_info}, 停留{stay:.1f}s)')
                    else:
                        result['http_status'] = 200
                        result['code'] = -1
                        result['cdn_status'] = 'error'
                        nurture_log(f'[{phone}] 购买信息 ✗ (空数据), 停留{stay:.1f}s)')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 购买信息 ✗: {e}')
                time.sleep(stay)

            elif state == 'GAME_CHECK':
                # 小茅运游戏互动 — 浏览游戏H5页面
                try:
                    game_url = "https://h5.moutai519.com.cn/game"
                    game_headers = {"User-Agent": client.webview_ua}
                    resp = _get(game_url, headers=game_headers,
                               proxy=client.proxy, timeout=8)
                    result['http_status'] = resp.status_code
                    result['code'] = 2000
                    result['cdn_status'] = 'ok'
                    # 提取页面标题/内容摘要
                    page_info = '-'
                    try:
                        html = resp.text[:3000] if hasattr(resp, 'text') else ''
                        m = re.search(r'<title>(.*?)</title>', html, re.I)
                        if m:
                            page_info = m.group(1).strip()[:30]
                        elif '{"code"' in html:
                            # JSON 响应
                            j = json.loads(html)
                            page_info = f'code={j.get("code","?")}'
                    except:
                        pass
                    nurture_log(f'[{phone}] 游戏互动 ✓ (页面={page_info}, 停留{stay:.1f}s)')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 游戏互动 ✗: {e}')
                time.sleep(stay)

            elif state == 'RESERVATION':
                # 查看预约列表
                try:
                    reserve_url = f"{BASE_URL}/xhr/front/mall/reservation/list"
                    reserve_params = {"pageNum": 1, "pageSize": 10}
                    reserve_headers = client._app_headers()
                    resp = _get(reserve_url, headers=reserve_headers,
                               params=reserve_params, proxy=client.proxy, timeout=8)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('code') == 2000:
                            result['http_status'] = 200
                            result['code'] = 2000
                            result['cdn_status'] = 'ok'
                            reserve_list = data.get('data', {}).get('list', [])
                            # 提取预约项目名
                            reserve_names = []
                            for item in (reserve_list if isinstance(reserve_list, list) else []):
                                name = str(item.get('itemName', item.get('title', '?')) if isinstance(item, dict) else '?')[:15]
                                reserve_names.append(name)
                            r_str = ', '.join(reserve_names[:3]) if reserve_names else '-'
                            nurture_log(f'[{phone}] 预约列表 ✓ ({len(reserve_list)}条: {r_str}, 停留{stay:.1f}s)')
                        else:
                            result['http_status'] = resp.status_code
                            result['code'] = data.get('code', -1)
                            result['cdn_status'] = 'error'
                            nurture_log(f'[{phone}] 预约列表 code={data.get("code")}')
                    else:
                        result['http_status'] = resp.status_code
                        result['cdn_status'] = 'error'
                        nurture_log(f'[{phone}] 预约列表 HTTP {resp.status_code}')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 预约列表 ✗: {e}')
                time.sleep(stay)

            elif state == 'ORDERS':
                # 查看订单列表
                try:
                    if client.token and client.cookie:
                        orders = client.query_order_list(status_filter=0, page_size=5)
                        result['http_status'] = 200
                        result['code'] = 2000
                        result['cdn_status'] = 'ok'
                        # 提取订单摘要
                        order_summary = []
                        for o in (orders if isinstance(orders, list) else []):
                            name = str(o.get('itemName', o.get('title', '?')) if isinstance(o, dict) else '?')[:12]
                            price = o.get('realPrice', '?') if isinstance(o, dict) else '?'
                            order_summary.append(f'{name}¥{price}')
                        o_str = ', '.join(order_summary[:3]) if order_summary else '-'
                        nurture_log(f'[{phone}] 订单列表 ✓ ({len(orders)}条: {o_str}, 停留{stay:.1f}s)')
                    else:
                        nurture_log(f'[{phone}] 订单列表 ⊘ (未登录)')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 订单列表 ✗: {e}')
                time.sleep(stay)

            elif state == 'RUSH_CHECK':
                # 抢购商品4030检测 — 使用 CDN 穿透参数发起轻量抢购
                try:
                    # 使用固定的过期参数发起请求，检测返回码
                    r = client.rush_purchase(
                        item_code='1001017',
                        sku_id='741',
                        item_priority_act_id='82319',
                        amount='1',
                        timeout=8,
                    )
                    code = r.get('code', -1)
                    http_status = r.get('_http_status', 0)
                    msg = r.get('message', '')
                    srv_time = r.get('_server_time', '')

                    result['http_status'] = http_status
                    result['code'] = code
                    result['server_ip'] = getattr(r, '_server_ip', '')

                    if code == 4030 or '商品信息不存在' in msg:
                        result['cdn_status'] = 'ok'
                        health = self._cdn_health.record_response(
                            phone, http_status, code)
                        nurture_log(f'[{phone}] 4030检测 ✓ (CDN穿透正常, srv={srv_time}, 停留{stay:.1f}s)')
                    elif http_status == 429 or code == 429:
                        result['cdn_status'] = 'throttled'
                        self._cdn_health.record_response(phone, http_status, code)
                        nurture_log(f'[{phone}] 4030检测 ⚠ 429限流!')
                    else:
                        result['cdn_status'] = 'ok'
                        nurture_log(f'[{phone}] 4030检测 code={code} msg={msg[:60]} srv={srv_time}')
                except Exception as e:
                    result['error'] = str(e)[:100]
                    result['cdn_status'] = 'error'
                    nurture_log(f'[{phone}] 4030检测 ✗: {e}')
                time.sleep(stay)

        except Exception as e:
            result['error'] = str(e)[:200]
            result['cdn_status'] = 'error'
            nurture_log(f'[{phone}] {state} 异常: {e}')

        return result

    def get_account_health_report(self, phone: str = None) -> Dict:
        """获取账号健康报告"""
        if phone:
            stats = self._account_stats.get(phone, {})
            device = self._binding.get_device(phone)
            return {
                'phone': phone,
                'device': device,
                'stats': dict(stats),
            }

        report = []
        for phone, stats in self._account_stats.items():
            device = self._binding.get_device(phone)
            report.append({
                'phone': phone,
                'device_key': self._binding.get_device_key(phone),
                'device': device.get('model', '') if device else '',
                'cycles': stats['nurture_cycles'],
                'cdn_ok': stats['cdn_ok'],
                'cdn_429': stats['cdn_429'],
                'rush_4030': stats['rush_4030'],
                'errors': stats['errors'],
            })
        return {'accounts': report, 'total': len(report)}

    def get_device_templates(self, brand: str = None) -> Dict:
        """获取机型模板列表，brand 不区分大小写"""
        if brand:
            brand_lower = brand.lower()
            matched = {}
            for key, dev in DEVICE_TEMPLATES.items():
                if dev['brand'].lower() == brand_lower:
                    matched[key] = dev
            return matched
        return DEVICE_TEMPLATES

    def get_behavior_templates(self) -> List[Dict]:
        """获取行为模板"""
        return self._learner.get_behavior_template()

    def get_cdn_summary(self) -> Dict:
        """获取CDN节点汇总"""
        return {
            'health': self._cdn_health.get_stats(),
            'nodes': self._learner.get_cdn_nodes(),
        }


# ==================== 便捷入口 ====================
# 全局单例
_nurture_manager: Optional[NurtureSessionManager] = None
_manager_lock = threading.Lock()


def get_nurture_manager() -> NurtureSessionManager:
    """获取养号管理器单例"""
    global _nurture_manager
    if _nurture_manager is None:
        with _manager_lock:
            if _nurture_manager is None:
                _nurture_manager = NurtureSessionManager()
    return _nurture_manager


def run_nurture_cycle(tasks: List[Dict], clients: List[MoutaiClient],
                      proxy_cache: Dict, account_cdn_mode: Dict,
                      round_num: int) -> Dict:
    """
    便捷函数 — 执行一轮养号

    由 moutai_client_worker.py 在非快抢分支中调用
    """
    # 设置线程上下文，使 nurture_log 自动附加模式标签
    if tasks:
        proxy_ip = tasks[0].get('proxy_ip', '') if proxy_cache.get('enabled') else ''
        try:
            from moutai_client_worker import set_thread_ctx
            set_thread_ctx(phone=tasks[0].get('phone', ''), proxy_ip=proxy_ip)
        except Exception:
            pass
    mgr = get_nurture_manager()
    return mgr.run_cycle(tasks, clients, proxy_cache, account_cdn_mode, round_num)


def parse_har_and_learn(har_path: str, device_key: str = None) -> Dict:
    """便捷函数 — 解析HAR并学习"""
    mgr = get_nurture_manager()
    return mgr.parse_har_file(har_path, device_key)


def bind_account_device(phone: str, device_key: str = None) -> str:
    """便捷函数 — 绑定账号到机型"""
    mgr = get_nurture_manager()
    return mgr.bind_account(phone, device_key)


def sync_bindings_from_server() -> int:
    """便捷函数 — 从服务端同步设备绑定"""
    mgr = get_nurture_manager()
    return mgr.sync_bindings_from_server()


def batch_parse_har_files(har_paths: List[str], device_key: str = None) -> Dict:
    """批量解析多个 HAR 文件，合并行为学习结果
    
    返回: {total_entries, files_processed, behaviors_learned}
    """
    mgr = get_nurture_manager()
    total_entries = 0
    files_processed = 0
    errors = []

    for har_path in har_paths:
        if not os.path.exists(har_path):
            errors.append({'path': har_path, 'error': '文件不存在'})
            continue
        result = mgr.parse_har_file(har_path, device_key)
        if 'error' in result:
            errors.append({'path': har_path, 'error': result['error']})
        else:
            total_entries += result.get('entry_count', 0)
            files_processed += 1

    nurture_log(f'[批量HAR] {files_processed}/{len(har_paths)} 文件成功, '
               f'{total_entries} 条请求, {len(errors)} 个错误')

    return {
        'total_entries': total_entries,
        'files_processed': files_processed,
        'total_files': len(har_paths),
        'errors': errors,
    }


# ==================== 独立测试入口 ====================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='i茅台 养号模块')
    parser.add_argument('--parse-har', type=str, help='解析HAR文件路径')
    parser.add_argument('--batch-har', type=str, help='批量解析HAR文件目录')
    parser.add_argument('--device-key', type=str, help='指定设备key（用于HAR解析）')
    parser.add_argument('--bind', type=str, help='绑定手机号到机型')
    parser.add_argument('--sync-bindings', action='store_true', help='从服务端同步设备绑定')
    parser.add_argument('--server', type=str, default='', help='服务端URL（用于同步/绑定）')
    parser.add_argument('--api-token', type=str, default='', help='API Token')
    parser.add_argument('--uploader-id', type=int, default=0, help='上传者ID')
    parser.add_argument('--report', action='store_true', help='输出账号健康报告')
    parser.add_argument('--templates', type=str, help='列出机型模板 (all/xiaomi/samsung/huawei/oppo/vivo)')
    parser.add_argument('--behaviors', action='store_true', help='列出行为模板')
    parser.add_argument('--cdn', action='store_true', help='列出CDN节点')

    args = parser.parse_args()

    # 配置服务端
    if args.server:
        set_server_config(args.server, args.api_token or 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd', args.uploader_id)

    mgr = get_nurture_manager()

    if args.sync_bindings:
        count = mgr.sync_bindings_from_server()
        nurture_log(f'同步完成: {count} 条绑定')

    if args.parse_har:
        result = mgr.parse_har_file(args.parse_har, args.device_key)
        nurture_log(f'HAR解析完成: {result.get("entry_count", 0)} 条请求')
        if 'behavior_sequence' in result:
            nurture_log(f'行为序列: {len(result["behavior_sequence"])} 个关键步骤')
            for b in result['behavior_sequence']:
                nurture_log(f'  → {b["action"]}: {b["url"][:80]}')

    if args.batch_har:
        har_dir = args.batch_har
        har_files = []
        if os.path.isdir(har_dir):
            for f in os.listdir(har_dir):
                if f.endswith('.har'):
                    har_files.append(os.path.join(har_dir, f))
        elif os.path.isfile(har_dir):
            har_files = [har_dir]
        if har_files:
            result = batch_parse_har_files(har_files, args.device_key)
            nurture_log(f'批量解析: {result["files_processed"]}/{result["total_files"]} 成功, '
                       f'{result["total_entries"]} 条请求')

    if args.bind:
        device_key = mgr.bind_account(args.bind, args.device_key)
        nurture_log(f'绑定完成: {args.bind} → {device_key}')

    if args.report:
        report = mgr.get_account_health_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.templates:
        if args.templates == 'all':
            templates = mgr.get_device_templates()
        else:
            templates = mgr.get_device_templates(args.templates)
        for k, v in sorted(templates.items()):
            print(f'{k}: {v["brand"]} {v["model"]} (SDK{v["sdk"]}, {v["screen"]}, {v["cpu"]})')

    if args.behaviors:
        behaviors = mgr.get_behavior_templates()
        for b in behaviors:
            print(f'  {b.get("action")}: {b.get("desc", b.get("url", ""))}')

    if args.cdn:
        cdn = mgr.get_cdn_summary()
        print(json.dumps(cdn, ensure_ascii=False, indent=2))
