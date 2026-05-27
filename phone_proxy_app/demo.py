#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商城 1.9.6 Demo - 登录 + 抢购 + 下单 + 支付
所有请求参数动态生成, 含瑞数 BotShield H5 防护 + WASM 签名
"""

import time
import uuid
import random
import hashlib
import json
import base64
import re
import struct
from datetime import datetime
from urllib.parse import quote
from curl_cffi import requests as cffi_requests
from Crypto.Cipher import DES3
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5 as PKCS1_Cipher
from Crypto.Util.Padding import pad
from crypto import (
    generate_mt_k_and_v, generate_mt_device_id, generate_mt_r,
    generate_mt_sn, generate_device_id_raw, generate_act_param,
    generate_h5_did, generate_h5_start_id, generate_d_u_cookie,
    generate_bs_device_id,
    generate_headers_for_post, generate_wasm_sign,
    md5_hex, xor_encrypt,
    APP_VERSION, MT_INFO, DEFAULT_APP_KEY, SDK_VERSION,
    murmur_hash3_x64_128,
)

BASE_URL = "https://app.moutai519.com.cn"
H5_BASE_URL = "https://h5.moutai519.com.cn"
PAY_API_URL = "https://payapi.moutai519.com.cn"
VCODE_SALT = "2af72f100c356273d46284f6fd1dfc08"

# 支付 SDK 常量 (来自 PaySdkConfig / p458l9.C8324b.m31095a)
MTPAY_APP_ID = "MT519ANDROID"
MTPAY_APP_SECRET = "8C79446361034bd2aE98b27E153a2eA8"  # securityID = MD5(tn+ts+secret)
MTPAY_SM4_KEY = "e881E52D7932Cf00"                      # cipherText = SM4_ECB(ts, key)

# TLS 指纹伪装: 模拟 Chrome Android WebView (与真机H5请求一致)
IMPERSONATE = "chrome124"


def generate_bangcle_content_info(device_id: str = "") -> str:
    """
    生成 Bangcle Content-Info-Bb 头 (邦盛设备验证)
    使用设备 ID + 时间戳 + 随机因子生成一个 256 字符的 hex 签名
    """
    raw = device_id or str(uuid.uuid4().hex[:16])
    ts = str(int(time.time() * 1000))
    seed = raw + ts + str(random.randint(10000, 99999))
    # 使用 murmur hash 生成 128-bit + md5 生成另一段, 拼接成 256 hex chars
    h1 = murmur_hash3_x64_128(seed, seed=27)
    h2 = md5_hex(seed[::-1] + raw)
    return h1 + h2

# curl_cffi session (全局复用)
_tls_session = cffi_requests.Session(impersonate=IMPERSONATE)

# 代理 Session 池: 按 proxy URL 持久复用 TLS 连接，消除每次握手 ~500ms 延时
_proxy_sessions: dict = {}
_proxy_sessions_lock = __import__('threading').Lock()


def _get_proxy_session(proxy: str):
    """获取/创建代理持久 Session，每个代理 IP 复用一条 TLS 连接"""
    if proxy not in _proxy_sessions:
        with _proxy_sessions_lock:
            if proxy not in _proxy_sessions:
                sess = cffi_requests.Session(impersonate=IMPERSONATE)
                sess.proxies = {'https': proxy, 'http': proxy}
                _proxy_sessions[proxy] = sess
    return _proxy_sessions[proxy]


def _post(url, headers=None, json=None, data=None, proxy=None, **kwargs):
    """统一 POST，使用 curl_cffi 伪装 TLS 指纹，支持 SOCKS5 代理（连接复用）
    代理 TLS/连接失败时自动回退直连重试一次。"""
    kwargs.pop('impersonate', None)
    _timeout = kwargs.pop('timeout', 30)  # 允许调用方覆盖 timeout
    if proxy:
        try:
            return _get_proxy_session(proxy).post(url, headers=headers, json=json, data=data,
                                                  timeout=_timeout, **kwargs)
        except Exception as e:
            err_str = str(e)
            # TLS 错误(35) / 连接超时(28) / 连接拒绝(7) / 代理错误(5,97) → 回退直连
            if any(x in err_str for x in ('curl: (35)', 'curl: (28)', 'curl: (7)', 'curl: (5)', 'curl: (97)',
                                          'TLS connect error', 'Connection timed out',
                                          'Connection refused', 'Failed to connect')):
                return _tls_session.post(url, headers=headers, json=json, data=data,
                                         timeout=_timeout, **kwargs)
            raise
    return _tls_session.post(url, headers=headers, json=json, data=data, timeout=_timeout, **kwargs)


def _get(url, headers=None, params=None, proxy=None, **kwargs):
    """统一 GET，支持 SOCKS5 代理（连接复用）
    代理 TLS/连接失败时自动回退直连重试一次。"""
    kwargs.pop('impersonate', None)
    _timeout = kwargs.pop('timeout', 15)  # 允许调用方覆盖 timeout
    if proxy:
        try:
            return _get_proxy_session(proxy).get(url, headers=headers, params=params,
                                                 timeout=_timeout, **kwargs)
        except Exception as e:
            err_str = str(e)
            if any(x in err_str for x in ('curl: (35)', 'curl: (28)', 'curl: (7)', 'curl: (5)', 'curl: (97)',
                                          'TLS connect error', 'Connection timed out',
                                          'Connection refused', 'Failed to connect')):
                return _tls_session.get(url, headers=headers, params=params,
                                        timeout=_timeout, **kwargs)
            raise
    return _tls_session.get(url, headers=headers, params=params, timeout=_timeout, **kwargs)


def sm4_encrypt(plaintext: str, key: str) -> str:
    """
    SM4 ECB 加密 → Base64

    来源: je.C7891b.m29122a (SM4Utils.a)
    算法: SM4/ECB/PKCS7Padding → Base64(NO_WRAP)
    """
    from gmssl import sm4 as sm4_module
    cipher = sm4_module.CryptSM4()
    cipher.set_key(key.encode('utf-8'), sm4_module.SM4_ENCRYPT)
    ct = cipher.crypt_ecb(plaintext.encode('utf-8'))
    return base64.b64encode(ct).decode('utf-8')


# ---- WebView UA 设备池: 与 crypto._DEVICE_POOL 中的设备对应 ----
# 每个元素: (Android SDK, 显示型号, Build ID, Chrome 版本, 厂商名, APP型号名, 屏幕分辨率)
# 扩展至 25 款真机设备，保证每个客户端窗口使用不同的设备组合
_WEBVIEW_UA_POOL = [
    (14, "2211133C", "UKQ1.230705.002", "128.0.6613.127", "Xiaomi", "fuxi", "1080*2400"),      # Xiaomi 13 (HAR真机)
    (14, "SM-G991B", "UP1A.231005.007", "124.0.6367.179", "samsung", "o1q", "1080*2340"),       # Samsung S21
    (13, "Pixel 7",  "TQ3A.230901.001", "120.0.6099.230", "google", "pixel7", "1080*2400"),     # Google Pixel 7
    (14, "22081212C","UKQ1.230917.001", "122.0.6261.64", "Xiaomi", "cupid", "1440*3200"),       # Xiaomi 12S Ultra
    (13, "V2254A",   "TP1A.220624.014", "119.0.6045.193", "vivo", "v2254a", "1080*2376"),      # vivo X90
    (14, "OPH2201",  "UP1A.231005.007", "123.0.6312.118", "OnePlus", "oph2201", "1080*2412"),   # OnePlus 10 Pro
    (15, "SM-S928B", "AP1A.240405.002", "130.0.6723.86", "samsung", "e1q", "1440*3120"),        # Samsung S24 Ultra
    (14, "23090RA98G","UKQ1.231108.001", "126.0.6478.110", "Redmi", "ruby", "1220*2712"),      # Redmi Note 13 Pro
    (15, "Pixel 9 Pro","AP3A.240905.015", "132.0.6834.79", "google", "caiman", "1280*2856"),   # Google Pixel 9 Pro
    (14, "V2361A",   "UP1A.231005.007", "126.0.6478.122", "vivo", "v2361a", "1260*2800"),     # vivo X100
    (14, "PJZ110",   "UKQ1.230804.001", "125.0.6422.165", "OPPO", "pjz110", "1264*2780"),     # OPPO Find X7
    (13, "ALN-AL80", "ALN-AL80 4.0.0.120", "118.0.5993.80", "HUAWEI", "aln-al80", "1212*2616"), # HUAWEI Mate 60
    (15, "2410DPN6CC","OS2.0.6.0.VOBCNXM", "131.0.6778.81", "Xiaomi", "dada", "1440*3200"),   # Xiaomi 15 Pro
    (14, "SM-F946B", "UP1A.231005.007", "125.0.6422.146", "samsung", "q5q", "1812*2176"),     # Samsung Z Fold5
    (13, "RMX3700",  "TP1A.220905.001", "120.0.6099.144", "realme", "rmx3700", "1080*2412"),  # realme GT5
    (14, "PHN110",   "UKQ1.230928.001", "124.0.6367.113", "OnePlus", "phn110", "1264*2780"),  # OnePlus 12
    (14, "LE2120",   "UKQ1.230928.001", "125.0.6422.147", "OnePlus", "lemonade", "1080*2400"),# OnePlus 9 Pro
    (13, "SM-A5460", "TP1A.220624.014", "122.0.6261.119", "samsung", "a54x", "1080*2340"),    # Samsung A54
    (14, "23053RN02A","UKQ1.230804.001", "126.0.6478.122", "Redmi", "pearl", "1080*2460"),   # Redmi Note 12 Turbo
    (14, "23127PN0CC","UKQ1.230804.001", "127.0.6533.64", "Xiaomi", "shennong", "1220*2712"),# Xiaomi 14
    (13, "CPH2487",  "TP1A.220905.001", "118.0.5993.65", "OPPO", "cph2487", "1080*2412"),    # OPPO A78
    (14, "V2318A",   "UP1A.231005.007", "124.0.6367.243", "vivo", "v2318a", "1260*2800"),    # vivo X100 Pro
    (15, "PKM110",   "AP3A.240617.008", "130.0.6723.58", "OPPO", "pkm110", "1080*2412"),     # OPPO Reno12
    (14, "SM-S9180", "UP1A.231005.007", "125.0.6422.165", "samsung", "dm1q", "1440*3088"),    # Samsung S23 Ultra
    (14, "NX769J",   "UP1A.231005.007", "126.0.6478.71", "nubia", "nx769j", "1116*2480"),    # nubia Z60 Ultra
]

# 设备池全局轮转索引（保证每个客户端窗口使用不同设备）
_device_pool_index = 0
_device_pool_lock = __import__('threading').Lock()

def _get_next_device_index() -> int:
    """线程安全地获取下一个设备索引，实现窗口间设备轮转分配"""
    global _device_pool_index
    with _device_pool_lock:
        idx = _device_pool_index
        _device_pool_index = (_device_pool_index + 1) % len(_WEBVIEW_UA_POOL)
        return idx


class MoutaiClient:
    """商城客户端"""

    # 抢购 URL 列表 (与 bs_h5.js hookAjax 中的判断一致)
    RUSH_URLS = [
        "/xhr/front/trade/priority/rushPurchase/hot/branch/one",
        "/xhr/front/trade/priority/rushPurchase/hot/branch/two",
        "/xhr/front/trade/priority/rushPurchase/hot/branch/three",
        "/xhr/front/trade/priority/rushPurchase/hot/branch/four",
        "/xhr/front/trade/priority/rushPurchase",
    ]

    def __init__(
        self,
        android_id: str = "",
        sdk_int: int = None,
        manufacturer: str = "",
        model: str = "",
        screen: str = "",
        build_time: str = "",
        bs_dvid: str = "",
        wasm_version: str = "",
        device_index: int = -1,
    ):
        """
        初始化客户端, 自动生成所有设备标识

        Args:
            android_id:     Android ID (不传则随机生成)
            sdk_int:        Android SDK 版本 (不传则从设备池随机)
            manufacturer:   厂商 (不传则从设备池随机)
            model:          型号 (不传则从设备池随机)
            screen:         屏幕分辨率 (不传则随机)
            build_time:     构建时间 (不传则当前时间)
            bs_dvid:        BotShield 设备 ID (可选)
            wasm_version:   WASM 签名版本 (从浏览器 localStorage 获取)
            device_index:   设备池索引 (-1=自动轮转分配, 保证窗口唯一)
        """
        # 邦盛验证缓存 - 避免每次抢购都调用
        self._last_bangcle_time = 0
        self._bangcle_cache_valid = False
        self._bangcle_cache_ttl = 300  # 5分钟缓存

        # 商品详情缓存
        self._item_detail_cache = {}
        self._item_detail_cache_time = 0
        self._item_detail_cache_ttl = 7200  # 2小时缓存
        if not android_id:
            android_id = uuid.uuid4().hex[:16]

        # 从设备池选取设备配置 (默认轮转分配, 保证窗口唯一)
        if device_index >= 0 and device_index < len(_WEBVIEW_UA_POOL):
            self._device_idx = device_index
        else:
            self._device_idx = _get_next_device_index()
        dv_android, dv_model, dv_build, dv_chrome, dv_mfr, dv_app_model, dv_screen = _WEBVIEW_UA_POOL[self._device_idx]

        # APP 层设备参数 (可覆盖, 不传则使用设备池默认值)
        _sdk = sdk_int or dv_android
        _mfr = manufacturer or dv_mfr
        _mdl = model or dv_app_model
        _screen = screen or dv_screen

        self.raw_device_id = generate_device_id_raw(android_id=android_id)
        self.mt_device_id = generate_mt_device_id(self.raw_device_id)
        self.mt_r = generate_mt_r(is_rooted=False, is_debug=False, has_proxy=False)
        self.mt_sn = generate_mt_sn()

        # APP 原生接口 User-Agent: "android;{sdk};{manufacturer};{model}"
        self.user_agent = f"android;{_sdk};{_mfr};{_mdl}"

        # WebView User-Agent: 真实 Android WebView 格式
        # 格式来自 CheckRequestHeaderJsHandler 注入的 UA
        self.webview_ua = (
            f"Mozilla/5.0 (Linux; Android {_sdk}; {dv_model} Build/{dv_build}; wv) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
            f"Chrome/{dv_chrome} Mobile Safari/537.36 "
            f"moutaiapp/{APP_VERSION} device-id/{self.raw_device_id}"
        )
        if bs_dvid:
            self.webview_ua += f" BS-DVID/{bs_dvid}"

        self.screen = _screen
        self.bs_dvid = bs_dvid
        self.token = ""
        self.cookie = ""
        self.user_id = ""
        self.mt_dtime = build_time or datetime.now().strftime("%a %b %d %H:%M:%S GMT+08:00 %Y")

        # 瑞数 H5 指纹 (会话级持久化, 同一客户端实例内复用)
        self.h5_did = generate_h5_did()
        self.h5_start_id = generate_h5_start_id()
        self.bs_device_id = generate_bs_device_id(self.h5_did)  # _bs_device_id cookie
        self.wasm_version = wasm_version

        # 代理设置: 绑定到账号的 SOCKS5 代理 (socks5://ip:port)
        self.proxy = ""
        # 手机号 (由调用方设置，用于日志标识)
        self.phone = ""

    # ==================== 请求头构建 ====================

    def _app_headers(self, need_sign: bool = False) -> dict:
        """APP 原生接口请求头"""
        headers = {
            "MT-Token": self.token,
            "User-Agent": self.user_agent,
            "MT-Device-ID": self.mt_device_id,
            "MT-APP-Version": APP_VERSION,
            "MT-Request-ID": str(uuid.uuid4()),
            "MT-Network-Type": "4G",
            "MT-R": self.mt_r,
            "MT-Bundle-ID": "com.moutai.mall",
            "MT-USER-TAG": "0",
            "MT-SN": self.mt_sn,
            "MT-DTIME": self.mt_dtime,
            "MT-RS": self.screen,
            "BS-DVID": self.bs_dvid,
            "MT-DOUBLE": "0",
            "MT-SIM": "0",
            "MT-ACBE": "0",
            "MT-ACB": "0",
            "MT-ACBM": "0",
            "Content-Type": "application/json; charset=UTF-8",
            "Host": "app.moutai519.com.cn",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }
        if need_sign:
            mt_k, mt_v = generate_mt_k_and_v(self.raw_device_id)
            headers["MT-K"] = mt_k
            headers["MT-V"] = mt_v
        return headers

    def _h5_headers(self, body: dict, referer: str = "",
                    is_rush_purchase: bool = False) -> dict:
        """
        H5 WebView 抢购接口请求头 (含瑞数 BotShield 防护)

        -------- 生成的 Header --------
        Content-Web-Bb:  SM4-CBC 加密的 13 字段数组
        Sdk-Ver-Bb:      SDK 版本号
        Content-Hh-Bb:   MurmurHash3 请求签名

        -------- 生成的 Cookie --------
        _d_u:            SM4-CBC 加密的设备上报数据
        _bs_device_id:   浏览器指纹 cookie
        _sdk_v_:         SDK 版本 cookie
        """
        mt_k, mt_v = generate_mt_k_and_v(self.raw_device_id)

        # 瑞数 H5 防护头
        bb_headers = generate_headers_for_post(
            body,
            app_key=DEFAULT_APP_KEY,
            did=self.h5_did,
            start_id=self.h5_start_id,
            user_id=self.user_id,
            wasm_version=self.wasm_version,
            is_rush_purchase=is_rush_purchase,
        )

        # _d_u cookie (瑞数设备上报, 每 ~10 秒刷新, 每次调用重新生成)
        d_u = generate_d_u_cookie(self.h5_did, self.h5_start_id)

        # 完整 cookie: 包含 APP token + 瑞数防护 cookie
        cookie_str = (
            f"MT-Token-Wap={self.cookie}; "
            f"MT-Device-ID-Wap={self.mt_device_id}; "
            f"_d_u={d_u}; "
            f"_bs_device_id={self.bs_device_id}; "
            f"_sdk_v_={SDK_VERSION}"
        )

        return {
            "MT-V": mt_v,
            "MT-K": mt_k,
            "MT-Device-ID": self.mt_device_id,
            "MT-APP-Version": APP_VERSION,
            "MT-Info": MT_INFO,
            "Content-Web-Bb": bb_headers["Content-Web-Bb"],
            "Sdk-Ver-Bb": bb_headers["Sdk-Ver-Bb"],
            "Content-Hh-Bb": bb_headers["Content-Hh-Bb"],
            "User-Agent": self.webview_ua,
            "content-type": "application/json",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '"Chromium";v="118", "Android WebView";v="118", "Not=A?Brand";v="99"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "Origin": H5_BASE_URL,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": referer or f"{H5_BASE_URL}/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie": cookie_str,
        }

    # ==================== 登录 ====================

    def send_vcode(self, mobile: str) -> dict:
        """发送验证码"""
        timestamp = str(int(time.time() * 1000))
        md5 = md5_hex(VCODE_SALT + mobile + timestamp)
        headers = self._app_headers(need_sign=False)
        body = {"md5": md5, "mobile": mobile, "timestamp": timestamp}

        # print(f"[验证码] 手机号: {mobile}, 时间戳: {timestamp}")
        # print(f"[验证码] 请求头:")
        # for k, v in headers.items():
        #     print(f"  {k}: {v}")
        # print(f"[验证码] 请求体: {json.dumps(body, ensure_ascii=False)}")
        resp = _post(f"{BASE_URL}/xhr/front/user/register/vcode", headers=headers, json=body, proxy=self.proxy)
        # print(f"[验证码] HTTP {resp.status_code}, length={len(resp.content)}")
        if resp.status_code != 200 or not resp.text:
            # print(f"[验证码] 响应头: {dict(resp.headers)}")
            # print(f"[验证码] 响应体: {resp.text[:500] if resp.text else '(empty)'}")
            return {"code": resp.status_code, "message": "HTTP error"}
        result = resp.json()
        # print(f"[验证码] 响应: {result}")
        return result

    def login(self, mobile: str, vcode: str) -> dict:
        """登录"""
        headers = self._app_headers(need_sign=True)
        body = {"vCode": vcode, "mobile": mobile, "ydToken": "", "ydLogId": ""}

        # print(f"[登录] 手机号: {mobile}, MT-V: {headers['MT-V']}")
        resp = _post(f"{BASE_URL}/xhr/front/user/register/login", headers=headers, json=body, proxy=self.proxy)
        result = resp.json()

        if result.get("code") == 2000:
            data = result["data"]
            self.token = data.get("token", "")
            self.cookie = data.get("cookie", "")
            self.user_id = str(data.get("userId", ""))
            print(f"[登录] 成功! userId={self.user_id}")
            # print(f"[登录] token:  {self.token[:50]}...")
            # print(f"[登录] cookie: {self.cookie[:50] if self.cookie else '(empty)'}...")
            # print(f"[登录] token==cookie: {self.token == self.cookie}")
        else:
            print(f"[登录] 失败: {result}")
        return result

    # ==================== 地址查询 ====================

    def get_addresses(self, province_id: str = "", addr_type: int = 1) -> list:
        """
        获取收货地址列表

        GET /xhr/front/user/address/ship/query?provinceId=&type=1&addressType=1
        Host: app.moutai519.com.cn
        """
        headers = self._app_headers(need_sign=False)
        params = {"provinceId": province_id, "type": 1, "addressType": addr_type}

        resp = _get(
            f"{BASE_URL}/xhr/front/user/address/ship/query",
            headers=headers,
            params=params,
            proxy=self.proxy,
        )
        result = resp.json()

        if result.get("code") == 2000:
            data = result.get("data", [])
            # data 可能是列表，也可能是 {"list": [...]} 等嵌套结构
            if isinstance(data, dict):
                addresses = data.get("list", data.get("addresses", []))
                if not addresses:
                    print(f"[地址] data 结构: {list(data.keys())}")
                    print(f"[地址] data 内容: {json.dumps(data, ensure_ascii=False)[:500]}")
                    return []
            elif isinstance(data, list):
                addresses = data
            else:
                print(f"[地址] 未知 data 类型: {type(data)}")
                return []

            print(f"[地址] 共 {len(addresses)} 个收货地址:")
            for i, addr in enumerate(addresses):
                dft = " (默认)" if addr.get("dft") else ""
                print(f"  [{i}] id={addr.get('shipAddressId')} "
                      f"{addr.get('provinceName','')}{addr.get('cityName','')}"
                      f"{addr.get('districtName','')} {addr.get('address','')}"
                      f" {addr.get('name','')} {addr.get('mobile','')}{dft}")
            return addresses
        else:
            print(f"[地址] 查询失败: {result}")
            return []

    # ==================== 查询 ====================
    def query_order_list(self, status_filter: int = 0, page_size: int = 20):
        """
        查询订单列表，获取中奖/待支付订单 (与 查单.har 端点一致)

        GET h5.moutai519.com.cn/xhr/front/trade/order/list/get
        params: __timestamp, status, size

        返回 data 结构: {"orderList": [...], "hasMore": bool}
        status: 0=全部, 1=待付款, 2=待发货, 3=已完成, 4=已取消
        """
        import random as _random
        ts = str(int(time.time() * 1000) + _random.randint(0, 999))
        params = {"__timestamp": ts, "size": page_size}
        if status_filter:
            params["status"] = status_filter
        headers = self._h5_headers({})
        resp = _get(f"{H5_BASE_URL}/xhr/front/trade/order/list/get",
                    headers=headers, params=params, proxy=self.proxy)
        data = resp.json()
        if data.get("code") == 2000:
            return data.get("data", {}).get("orderList", [])
        return []

    def get_winning_bid_result(self):
        """获取中标结果字符串（例如中奖商品名称），若无则返回空字符串"""
        orders = self.query_order_list(status_filter=3)  # 查已完成(中奖)订单
        if orders:
            return orders[0].get("itemName", "中奖")
        # 也查待付款订单
        orders = self.query_order_list(status_filter=1)
        if orders:
            return orders[0].get("itemName", "待支付")
        return ""

    def sync_server_time(self) -> float:
        """
        同步茅台服务器时间，返回 本地时间 - 服务器时间 的偏差(秒)

        通过请求 resource/get 获取 Date 响应头
        GET static.moutai519.com.cn/mt-backend/xhr/front/mall/resource/get

        返回: offset > 0 表示本地比服务器快；< 0 表示本地比服务器慢
        """
        from email.utils import parsedate_to_datetime
        url = f"https://static.moutai519.com.cn/mt-backend/xhr/front/mall/resource/get"
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        try:
            t0 = time.time()
            resp = _get(url, headers=headers, proxy=self.proxy, timeout=5)
            rtt = (time.time() - t0) / 2  # 半 RTT 补偿
            server_date = resp.headers.get('Date', '') or resp.headers.get('date', '')
            if server_date:
                server_dt = parsedate_to_datetime(server_date)
                server_ts = server_dt.timestamp()
                local_ts = t0 + rtt
                offset = local_ts - server_ts
                return offset
        except Exception as e:
            pass
        return 0.0

    def warmup_connections(self):
        """
        抢购前预热所有关键连接，消除首次握手延迟
        - 邦盛设备验证
        - 商品详情
        - 购买信息
        """
        try:
            self.bangcle_verify()
        except Exception:
            pass

    # ==================== 抢购前置: 邦盛设备验证 ====================

    def bangcle_verify(self, force: bool = False) -> bool:
        """
        邦盛设备验证 (Bangcle Anti-Fraud)
        根据 HAR 包分析：抢购前必须调此接口获取设备验证
        结果缓存 5 分钟，避免每次抢购都重复调用

        GET https://fk1.moutai519.com.cn/bangcle/api/v1/1/2
        Headers: Content-Info-Bb, User-Agent, Origin, X-Requested-With
        """
        now = time.time()
        if not force and self._bangcle_cache_valid and (now - self._last_bangcle_time) < self._bangcle_cache_ttl:
            return True

        url = "https://fk1.moutai519.com.cn/bangcle/api/v1/1/2"
        headers = {
            "User-Agent": self.webview_ua,
            "Content-Info-Bb": generate_bangcle_content_info(self.raw_device_id),
            "Accept": "*/*",
            "Origin": H5_BASE_URL,
            "X-Requested-With": "com.moutai.mall",
            "Referer": f"{H5_BASE_URL}/",
        }
        try:
            resp = _get(url, headers=headers, proxy=self.proxy)
            if resp.status_code == 200:
                data = resp.json()
                # {"v":[{"v":"v1.0.8"}],"w":true}
                if data.get("w") is True:
                    # print(f"[邦盛] 设备验证通过")
                    self._last_bangcle_time = now
                    self._bangcle_cache_valid = True
                    return True
            # print(f"[邦盛] 验证返回: {resp.status_code}, {resp.text[:100]}")
            return False
        except Exception as e:
            # print(f"[邦盛] 验证异常: {e}")
            return False

    # ==================== 抢购前置: 购买信息查询 ====================

    def get_purchase_info_v2(self, spu_id: str) -> dict:
        """
        查询购买信息/库存状态 (与 HAR 包一致)

        POST https://h5.moutai519.com.cn/xhr/front/mall/item/purchaseInfoV2
        body: {"hot": true, "spuId": spu_id, "jt": "anonymous"}

        返回: {"code":2000, "data":{"purchaseInfoMap":{"skuId":{...inventory...,"itemPriorityActId":82128}}}}
        """
        body = {"hot": True, "spuId": spu_id, "jt": "anonymous"}
        headers = self._h5_headers(body)

        # print(f"[购买信息] spuId={spu_id}")
        resp = _post(f"{H5_BASE_URL}/xhr/front/mall/item/purchaseInfoV2", headers=headers, json=body, proxy=self.proxy)

        # 完整响应体日志（确认无2026后注释）:
        # print(f"[purchaseInfoV2] HTTP={resp.status_code} | spuId={spu_id}")
        # print(f"[purchaseInfoV2] 完整响应: {resp.text}")

        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 2000:
                return result.get("data", {})
            # print(f"[购买信息] 业务失败: {result}")
        else:
            # print(f"[购买信息] HTTP {resp.status_code}")
            pass
        return {}

    def get_item_detail_v2(self, spu_id: str) -> dict:
        """
        获取商品详情V2 (与 HAR 真机一致)

        GET https://static.moutai519.com.cn/mt-backend/xhr/front/mall/item/detailV2/{spuId}
        Host: static.moutai519.com.cn (CDN 无需签名)

        返回: {"default_sku_id": "741", "title": "xxx", "price": 1539.0, "spu_id": "IMTP1000313"}
        """
        url = f"https://static.moutai519.com.cn/mt-backend/xhr/front/mall/item/detailV2/{spu_id}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        try:
            t_send = time.time()
            resp = _get(url, headers=headers, proxy=self.proxy)
            t_recv = time.time()
            rtt_half = (t_recv - t_send) / 2

            # 完整响应体日志（确认无2026后注释）:
            # print(f"[detailV2] HTTP={resp.status_code} | spuId={spu_id}")
            # print(f"[detailV2] 完整响应: {resp.text}")

            if resp.status_code == 200:
                result = resp.json()
                # 提取服务器时间（HTTP Date 响应头 + RTT/2 补偿）
                try:
                    from email.utils import parsedate_to_datetime
                    server_dt = parsedate_to_datetime(resp.headers.get('Date', ''))
                    server_time = datetime.fromtimestamp(server_dt.timestamp() + rtt_half).strftime('%H:%M:%S.%f')[:-3]
                except Exception:
                    server_time = ''
                if result.get("code") == 2000:
                    item = result.get("data", {}).get("item", {})
                    return {
                        "spu_id": result.get("data", {}).get("spuId", spu_id),
                        "default_sku_id": str(item.get("defaultSkuId", "")),
                        "title": item.get("title", "") or item.get("name", ""),
                        "price": item.get("price", 0),
                        "_server_time": server_time,
                    }
                # print(f"[商品详情V2] 业务失败: code={result.get('code')}")
            else:
                # print(f"[商品详情V2] HTTP {resp.status_code}")
                pass
        except Exception as e:
            # print(f"[商品详情V2] 异常: {e}")
            pass
        return {}

    def auto_fetch_item_details(self, item_code: str, spu_id: str = "") -> dict:
        """
        只需传入 SPU 编码 (如 IMTP1000313)，自动从 API 获取全部参数：
        - default_sku_id: compose/submit 的 spuId + rush 的 skuId (如 741)
        - item_code_from_api: rushPurchase 的 itemCode (purchaseInfoMap key, 如 1001017)
        - activity_id: 活动ID (如 82178)
        - price / inventory / item_name

        spu_id 为空时用 item_code 兜底
        """
        api_spu_id = spu_id or item_code

        cache_key = f"detail_{api_spu_id}"
        now = time.time()
        if cache_key in self._item_detail_cache:
            if (now - self._item_detail_cache_time) < self._item_detail_cache_ttl:
                return self._item_detail_cache[cache_key]

        result = {
            "spu_id": api_spu_id,
            "default_sku_id": "",       # detailV2 defaultSkuId → compose/submit spuId
            "item_code_from_api": "",    # purchaseInfoMap key → rushPurchase itemCode
            "activity_id": "",
            "price": 0,
            "inventory": 0,
            "item_name": "",
            "sku_id": "",                # = default_sku_id (向后兼容)
            "startTimeList": [],          # 抢购时间点列表（毫秒时间戳）
        }

        # ① 获取商品详情 (detailV2) → defaultSkuId, price, title
        detail = self.get_item_detail_v2(api_spu_id)
        if detail:
            result["default_sku_id"] = detail.get("default_sku_id", "")
            result["sku_id"] = result["default_sku_id"]
            result["item_name"] = detail.get("title", "")
            result["price"] = detail.get("price", 0)

        # ② 获取购买信息 (purchaseInfoV2) → purchaseInfoMap key, actId, inventory
        purchase_data = self.get_purchase_info_v2(api_spu_id)
        if purchase_data:
            purchase_info_map = purchase_data.get("purchaseInfoMap", {})
            for sku_id_key, sku_info in purchase_info_map.items():
                pinfo = sku_info.get("purchaseInfo", {})
                # purchaseInfoMap 的 key 就是 rushPurchase 的 itemCode
                if not result["item_code_from_api"]:
                    result["item_code_from_api"] = str(sku_id_key)
                # 有库存且未禁用的sku优先取actId
                if pinfo.get("inventory", 0) > 0 and not pinfo.get("disable", False):
                    result["activity_id"] = str(pinfo.get("itemPriorityActId", ""))
                    result["inventory"] = pinfo.get("inventory", 0)
                if not result["activity_id"]:
                    result["activity_id"] = str(pinfo.get("itemPriorityActId", ""))
                # 提取 startTimeList（在 purchaseInfo 层级，非 data 层级）
                stl = pinfo.get("startTimeList", [])
                if stl:
                    result["startTimeList"] = stl
            if not result["item_name"]:
                item_info = purchase_data.get("itemInfo", {})
                result["item_name"] = item_info.get("title", "") or item_info.get("name", "")
            if not result["price"]:
                result["price"] = purchase_data.get("itemInfo", {}).get("price", 0)

        # ③ 缓存
        self._item_detail_cache[cache_key] = result
        self._item_detail_cache_time = now

        # print(f"[自动获取] SPU={api_spu_id}")
        # print(f"  商品名称: {result['item_name']}")
        # print(f"  defaultSkuId(compose/submit spuId): {result['default_sku_id']}")
        # print(f"  itemCode(rushPurchase): {result['item_code_from_api']}")
        # print(f"  活动ID: {result['activity_id']}")
        # print(f"  价格: {result['price']}")
        # print(f"  库存: {result['inventory']}")

        return result

    def fetch_item_activity_id(self, item_code: str) -> str:
        """
        从 purchaseInfoV2 获取当前有效活动ID
        用于在抢购前动态获取最新活动ID
        """
        purchase_data = self.get_purchase_info_v2(item_code)
        if purchase_data:
            purchase_info_map = purchase_data.get("purchaseInfoMap", {})
            for sku_id_key, sku_info in purchase_info_map.items():
                pinfo = sku_info.get("purchaseInfo", {})
                if not pinfo.get("disable", False):
                    act_id = pinfo.get("itemPriorityActId")
                    if act_id:
                        # print(f"[获取活动ID] itemCode={item_code}, actId={act_id}")
                        return str(act_id)
        return ""

    # ==================== 抢购 ====================

    def rush_purchase(self, item_code: str, sku_id: str, item_priority_act_id: str,
                      amount: str = "1", source_id: str = "", timeout: int = 30) -> dict:
        """
        抢购 (根据 HAR 包修正版)

        - 使用 H5 域名 h5.moutai519.com.cn
        - 使用瑞数 H5 防护头 (Content-Web-Bb / Content-Hh-Bb / Sdk-Ver-Bb)
        - actParam AES 加密
        - 前置邦盛设备验证
        - 热门商品走 /hot/branch/{branch} 分链路
        - 按 item_code 匹配正确的 Referer 页面

        POST https://h5.moutai519.com.cn/xhr/front/trade/priority/rushPurchase[/hot/branch/{branch}]
        body: {"actParam": "..."}
        """
        # 0. 前置：邦盛设备验证
        self.bangcle_verify()

        # 1. 构造请求体 (与 HAR 真机完全对齐)
        # HAR actParam 明文: {"amount":"1","itemCode":"10193","itemPriorityActId":82199,
        #   "userInfoBaseContext":{"addressLat":"","addressLng":"",
        #     "appUserAgent":"...","deviceId":"...","mtr":"..."},
        #   "ydLogId":"","ydToken":""}
        data = {
            "amount": str(amount),
            "itemCode": item_code,
            "itemPriorityActId": int(item_priority_act_id),
            "userInfoBaseContext": {
                "addressLat": "",
                "addressLng": "",
                "appUserAgent": self.user_agent,
                "deviceId": self.mt_device_id,
                "mtr": self.mt_r,
            },
            "ydLogId": "",
            "ydToken": "",
        }

        # 2. 生成 actParam (AES 加密)
        act_param = generate_act_param(data)
        body = {"actParam": act_param}

        # 3. 按 item_code 确定抢购 URL 和 Referer（热门商品走分支链路）
        item_branch_map = {'741': 'one', '11947': 'two', '11945': 'two', '11942': 'two', '1741': 'three'}
        branch = item_branch_map.get(str(item_code))
        base_rush_url = f"{H5_BASE_URL}/xhr/front/trade/priority/rushPurchase"
        rush_url = f"{base_rush_url}/hot/branch/{branch}" if branch else base_rush_url

        item_referer_map = {
            '741':   'https://h5.moutai519.com.cn/mt/item/smsp-detail?appConfig=2_1_2',
            '483':   'https://h5.moutai519.com.cn/mt/item/1000ml-detail?appConfig=2_1_2',
            '10193': 'https://h5.moutai519.com.cn/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006',
            '11335': 'https://h5.moutai519.com.cn/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006',
            '11947': 'https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2',
            '11945': 'https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2',
            '11942': 'https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2',
            '1741':  'https://h5.moutai519.com.cn/mt/item/jpmt-detail?appConfig=2_1_2',
            '10220': 'https://h5.moutai519.com.cn/mt/item/grad-detail?appConfig=2_1_2',
        }
        referer = item_referer_map.get(
            str(item_code),
            f'https://h5.moutai519.com.cn/mt/item/smsp-detail?appConfig=2_1_2'
        )
        if source_id:
            referer += f"&sourceId={source_id}"

        # 4. 使用 H5 Headers (Content-Web-Bb / Content-Hh-Bb / Sdk-Ver-Bb) - 与 HAR 一致
        headers = self._h5_headers(body, referer=referer, is_rush_purchase=True)

        # 5. 抢购 URL（热门商品走分支链路 /hot/branch/{branch}，普通商品直接走基础路径）
        url = rush_url

        _phone = self.phone or ''

        t_send = time.time()
        try:
            resp = _post(url, headers=headers, json=body, proxy=self.proxy, timeout=timeout)
        except Exception as e:
            return {"code": -1, "message": f"请求异常: {e}"}
        t_recv = time.time()
        rtt_half = (t_recv - t_send) / 2

        # 解析响应（所有HTTP状态码都尝试解析JSON获取真实code/msg）
        parsed_code = resp.status_code
        parsed_msg = resp.text[:200] if resp.text else ''
        raw_text = resp.text[:500] if resp.text else ''  # 完整原始响应（截取前500字符）
        try:
            result = resp.json()
            parsed_code = result.get("code", resp.status_code)
            parsed_msg = result.get("message", "")
        except Exception:
            result = None
            # HTTP 429/403 无 body 时给出语义化提示
            if resp.status_code == 429 and not resp.text:
                parsed_msg = 'HTTP限流(Too Many Requests)'
            elif resp.status_code == 403 and not resp.text:
                parsed_msg = 'HTTP禁止访问(Forbidden)'

        # 构建返回结果，始终携带原始响应信息
        if resp.status_code in (200, 480) and result is not None:
            ret = result
        elif result is not None:
            ret = {"code": parsed_code, "message": parsed_msg}
        else:
            ret = {"code": resp.status_code, "message": resp.text[:500] if resp.text else ''}
        ret['_http_status'] = resp.status_code
        ret['_raw_text'] = raw_text
        # 提取目标站服务器时间（HTTP Date 响应头 秒级 → RTT/2 补偿估算毫秒）
        try:
            from email.utils import parsedate_to_datetime
            from datetime import datetime
            server_dt = parsedate_to_datetime(resp.headers.get('Date', ''))
            server_ms = server_dt.timestamp() + rtt_half
            ret['_server_time'] = datetime.fromtimestamp(server_ms).strftime('%H:%M:%S.%f')[:-3]
        except Exception:
            ret['_server_time'] = ''
        return ret

    # ==================== 验证码校验 (网易易盾) ====================

    def verify_code(self, priority_record_id: int, captcha_id: str = "",
                    validate: str = "") -> dict:
        """
        抢购成功后的验证码校验步骤 (HAR 真机流程)

        在 rush_purchase 成功返回 userVerifyStatus=1 后，必须调用此方法
        完成网易易盾验证码校验，才能进行 compose/submit 操作。

        POST h5.moutai519.com.cn/xhr/front/trade/priority/verify/code
        body: {"captchaId": "...", "validate": "..."}

        注意：captchaId 和 validate 需要从网易易盾 SDK (c.dun.163.com) 获取。
        如果无法获取验证码参数，此步骤需要用户在真机或模拟器上手动完成。
        """
        body = {
            "captchaId": captcha_id,
            "validate": validate,
        }
        headers = self._h5_headers(body)

        # print(f"[验证码] priorityRecordId={priority_record_id}")
        resp = _post(
            f"{H5_BASE_URL}/xhr/front/trade/priority/verify/code",
            headers=headers,
            json=body,
            proxy=self.proxy,
        )
        result = resp.json()
        code = result.get("code")
        if code == 2000:
            data = result.get("data", {})
            # print(f"[验证码] 校验成功, id={data.get('id')}, itemCode={data.get('itemCode')}")
        else:
            # print(f"[验证码] 校验失败: code={code}, msg={result.get('message')}")
            pass
        return result

    # ==================== 直接下单（非抢购） ====================

    def get_item_detail(self, item_code: str) -> dict:
        """
        获取商品详情（包括活动ID）
        
        GET /xhr/front/v2/item/detail/{itemCode}
        """
        headers = self._app_headers(need_sign=False)
        # 尝试多个可能的 URL
        urls_to_try = [
            f"{H5_BASE_URL}/xhr/front/v2/item/detail/{item_code}",
            f"{BASE_URL}/xhr/front/v2/item/detail/{item_code}",
            f"{H5_BASE_URL}/xhr/front/item/detail/{item_code}",
        ]
        
        print(f"[获取商品详情] itemCode={item_code}")
        
        for url in urls_to_try:
            print(f"[尝试 URL] {url}")
            try:
                resp = _get(url, headers=headers)
                
                if resp.status_code != 200:
                    print(f"  [跳过] HTTP {resp.status_code}")
                    continue
                
                # 检查是否为 JSON
                content_type = resp.headers.get('Content-Type', '')
                if 'application/json' not in content_type and 'text/json' not in content_type:
                    print(f"  [跳过] Content-Type: {content_type}")
                    print(f"  [响应前100字符] {resp.text[:100]}")
                    continue
                
                result = resp.json()
                
                if result.get("code") == 2000:
                    item_info = result.get("data", {}).get("item", {})
                    act_info = result.get("data", {}).get("actInfo", {})
                    print(f"✓ [商品名称] {item_info.get('title', '')}")
                    print(f"✓ [活动ID] {act_info.get('actId', '')}")
                    return {
                        "item_name": item_info.get("title", ""),
                        "act_id": act_info.get("actId", ""),
                        "full_data": result
                    }
                else:
                    print(f"  [业务错误] code={result.get('code')}, msg={result.get('message', '')}")
            except Exception as e:
                print(f"  [异常] {e}")
                continue
        
        print("✗ 所有 URL 尝试失败")
        return {}

    def direct_submit_order(self, store_id: str, spu_id: str, count: int,
                           address: dict, deliver_method: int = -1) -> dict:
        """
        直接提交订单（模拟 App 真机下单 - 修正版）
        """
        # 1. 构造请求体
        data = {
            "deliverMethod": deliver_method,
            "addressInfo": {
                "shipAddressId": address.get("shipAddressId", 0),
                "name": address.get("name", ""),
                "mobile": address.get("mobile", ""),
                "fullAddress": address.get("fullAddress", ""),
                "provinceName": address.get("provinceName", ""),
                "cityName": address.get("cityName", ""),
                "districtName": address.get("districtName", "")
            },
            "itemList": [
                {
                    "storeId": store_id,
                    "spuId": spu_id,
                    "count": count
                }
            ]
        }
        
        # 2. 生成 actParam (AES 加密)
        act_param = generate_act_param(data)
        body = {"actParam": act_param}
        
        # 3. 生成 App 请求头
        headers = self._app_headers(need_sign=True)
        headers.update({
            "MT-Bundle-ID": "com.moutai.mall",
            "content-type": "application/json",
        })
        
        # 4. 使用 App 接口
        url = f"{BASE_URL}/xhr/front/trade/order/standard/submit/v2"
        
        print(f"[直接下单] storeId={store_id}, spuId={spu_id}, count={count}")
        print(f"[URL] {url}")
        
        resp = _post(url, headers=headers, json=body, proxy=self.proxy, timeout=timeout)
        
        print(f"[响应状态码] {resp.status_code}")
        if resp.status_code != 200:
            print(f"[错误] HTTP {resp.status_code}")
            print(f"[响应内容] {resp.text[:500]}")
            return {"code": resp.status_code, "message": f"HTTP {resp.status_code}"}
        
        try:
            result = resp.json()
            print(f"[直接下单] 响应: {result}")
            return result
        except Exception as e:
            print(f"[解析失败] {e}")
            return {"code": -1, "message": "响应解析失败"}

    # ==================== 下单 ====================

    def compose_order_v2(self, spu_id: str, count: int, priority_record_id: int,
                        address_id: int = 0, deliver_method: int = 1,
                        store_id: str = "0") -> dict:
        """
        组单 (compose/v2) — 根据 HAR 真机 1.9.7 协议重写

        POST app.moutai519.com.cn/xhr/front/trade/order/standard/compose/v2
        Host: app.moutai519.com.cn  (APP 原生接口 + actParam 加密)

        HAR 显示需要 3 次尝试：
          1. deliverMethod=-1, shipAddressId=0  (试探)
          2. deliverMethod=1, shipAddressId=0  (确认配送方式)
          3. deliverMethod=1, shipAddressId=真实地址ID  (最终提交)

        请求体 (仅包含必要字段，与 HAR 一致):
        {
            "deliverMethod": 1,
            "addressInfo": {"shipAddressId": 40556284},
            "itemList": [{"storeId": "0", "spuId": "10193", "count": 6}],
            "actParam": "..."
        }
        """
        # 3 次尝试，与 HAR 真机一致
        attempts = [
            (-1, 0),           # 试探
            (deliver_method, 0),    # 确认方式
            (deliver_method, address_id),  # 最终
        ]

        last_result = {}
        for attempt_num, (dm, addr_id) in enumerate(attempts, 1):
            data = {
                "deliverMethod": dm,
                "addressInfo": {"shipAddressId": addr_id},
                "itemList": [
                    {"storeId": store_id, "spuId": spu_id, "count": count}
                ],
            }
            act_param = generate_act_param(data)
            body = {"actParam": act_param}

            # 使用 APP 原生 headers (与 HAR 一致，走 app 域名)
            headers = self._app_headers(need_sign=True)
            headers["Content-Type"] = "application/json; charset=UTF-8"

            print(f"[组单v2] 第{attempt_num}次: spuId={spu_id}, count={count}, dm={dm}, addrId={addr_id}")
            resp = _post(
                f"{BASE_URL}/xhr/front/trade/order/standard/compose/v2",
                headers=headers,
                json=body,
                proxy=self.proxy,
            )
            result = resp.json()
            last_result = result
            code = result.get("code")
            if code == 2000:
                data_result = result.get("data", {})
                print(f"[组单v2] 成功! transactionId={data_result.get('transactionId')}, "
                      f"actualPrice={data_result.get('orderPrice', {}).get('showActualPrice')}")
                return result
            print(f"[组单v2] 第{attempt_num}次失败: code={code}, msg={result.get('message')}")

        return last_result

    # 保持旧方法兼容（内部调用新方法）
    def compose_order(self, spu_id: str, count: int, priority_record_id: int,
                      address: dict, deliver_method: int = 1,
                      store_id: str = "0", shop_id: str = "",
                      inventory_source: int = 0) -> dict:
        """组单 (兼容旧接口，内部使用 compose_order_v2)"""
        addr_id = address.get("shipAddressId", 0) if isinstance(address, dict) else 0
        return self.compose_order_v2(
            spu_id=spu_id, count=count, priority_record_id=priority_record_id,
            address_id=addr_id, deliver_method=deliver_method, store_id=store_id
        )

    def submit_order(self, spu_id: str, count: int, priority_record_id: int,
                     address: dict, deliver_method: int = 1,
                     store_id: str = "0", shop_id: str = "",
                     inventory_source: int = 0) -> dict:
        """
        提交订单 (standard/submit/v2) — 根据 HAR 真机 1.9.7 协议重写

        POST app.moutai519.com.cn/xhr/front/trade/order/standard/submit/v2
        Host: app.moutai519.com.cn  (APP 原生接口 + actParam 加密)

        HAR 真机请求体 (极其精简，不含 addressInfo 和 userPriorityInfo):
        {
            "transactionId": "1067251570_22267164_compose",
            "deliverMethod": 1,
            "itemList": [{"storeId": "0", "spuId": "10193", "count": 6}],
            "actParam": "..."
        }
        """
        transaction_id = f"{self.user_id}_{priority_record_id}_compose"
        data = {
            "transactionId": transaction_id,
            "deliverMethod": deliver_method,
            "itemList": [
                {"storeId": store_id, "spuId": spu_id, "count": count}
            ],
        }
        act_param = generate_act_param(data)
        body = {"actParam": act_param}

        # 使用 APP 原生 headers (与 HAR 一致，走 app 域名)
        headers = self._app_headers(need_sign=True)
        headers["Content-Type"] = "application/json; charset=UTF-8"

        print(f"[下单v2] transactionId={transaction_id}")
        resp = _post(
            f"{BASE_URL}/xhr/front/trade/order/standard/submit/v2",
            headers=headers,
            json=body,
            proxy=self.proxy,
        )
        result = resp.json()
        print(f"[下单v2] 响应: code={result.get('code')}, orderId={result.get('data', {}).get('orderId')}")
        return result

    # ==================== 支付 ====================

    def pay_order(self, order_id: str, pay_method: int = 0) -> dict:
        """
        支付订单 (第一步: 获取 TN) — HAR 真机走 APP 域名

        POST app.moutai519.com.cn/xhr/front/trade/order/pay
        Host: app.moutai519.com.cn
        body: {"orderId": "626976747", "payMethod": 0}

        payMethod: 0=支付宝, 1=微信(疑似), 2=银联
        返回 data.extInfo 包含 DEVICE_ID，后续 requestPay 需要用到
        {
            "code": 2000,
            "data": {
                "outTradeNo": "623895218",
                "channelTradeSn": "177631074300120260416177630990399362389521810",
                "totalAmount": 13794.00,
                "payResultQueryTimeout": 10,
                "extInfo": "{\"COUNTDOWN_SECOND\":900,\"MSG_429\":\"...\",\"PUB\":\"001\",\"DEVICE_ID\":\"aa542da9b565...\"}"
            }
        }
        """
        headers = self._app_headers(need_sign=False)
        body = {"orderId": order_id, "payMethod": pay_method}

        print(f"[支付] orderId={order_id}, payMethod={pay_method}")
        resp = _post(
            f"{BASE_URL}/xhr/front/trade/order/pay",
            headers=headers,
            json=body,
            proxy=self.proxy,
        )
        result = resp.json()
        print(f"[支付] 响应: code={result.get('code')}, tn={result.get('data', {}).get('channelTradeSn', '')[:40]}...")
        return result

    def request_pay(self, channel_trade_sn: str, pay_channel: str = "70",
                    sales_id: str = "", device_id: str = "") -> dict:
        """
        请求支付网关 (第二步: 获取 SDK 串 / AUTH_CODE) — HAR 真机 1.9.7 协议

        POST /settle-api-server/anon/pay/requestPay?salesId={orderId}&payChannel=70
        Host: payapi.moutai519.com.cn
        Content-Type: application/x-www-form-urlencoded

        来源: MtPayActivity.zfbAppPay
        参数 (URL 查询):
          salesId    = 订单ID (与 pay_order 的 orderId 相同)
          payChannel = "70"(支付宝), "80"(微信/银联扫码)
        参数 (表单):
          inJson     = {"PAY_CHANNEL":"70","TN":"xxx"}
          cipherText = SM4_ECB(timestamp, sm4Key) → Base64 URL-encoded
          appId      = "MT519ANDROID"
          securityID = MD5(tn + timestamp + appSecret)
          deviceId   = 从 pay_order extInfo 中提取的 DEVICE_ID
        """
        from urllib.parse import urlencode
        timestamp = str(int(time.time() * 1000))

        # inJson
        in_json = json.dumps({"PAY_CHANNEL": pay_channel, "TN": channel_trade_sn}, separators=(',', ':'))

        # cipherText = SM4_ECB(timestamp, sm4Key) → Base64
        cipher_text = sm4_encrypt(timestamp, MTPAY_SM4_KEY)

        # securityID = MD5(tn + timestamp + appSecret)
        security_id = md5_hex(channel_trade_sn + timestamp + MTPAY_APP_SECRET)

        form_data = {
            "inJson": in_json,
            "cipherText": cipher_text,
            "appId": MTPAY_APP_ID,
            "securityID": security_id,
        }
        if device_id:
            form_data["deviceId"] = device_id
        body = urlencode(form_data)

        # 构造 URL (含 salesId 和 payChannel 查询参数，与 HAR 一致)
        url = f"{PAY_API_URL}/settle-api-server/anon/pay/requestPay"
        query_params = []
        if sales_id:
            query_params.append(f"salesId={sales_id}")
        query_params.append(f"payChannel={pay_channel}")
        if query_params:
            url += "?" + "&".join(query_params)

        print(f"[支付网关] TN={channel_trade_sn[:30]}..., payChannel={pay_channel}")
        print(f"[支付网关] deviceId={'***' if device_id else '(无)'}")

        resp = _post(
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "okhttp/4.9.2",
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
            },
            proxy=self.proxy,
        )
        result = resp.json()
        print(f"[支付网关] 响应: {json.dumps(result, ensure_ascii=False)}")

        code = result.get("code")
        if isinstance(code, str):
            code = int(code)
        if code in (200, 2000):
            p_data = result.get("data")
            sdk_str = ""
            if isinstance(p_data, str):
                sdk_str = p_data
            elif isinstance(p_data, dict):
                sdk_str = (p_data.get("payInfo") or p_data.get("alipay_sdk")
                           or p_data.get("orderInfo") or p_data.get("AUTH_CODE", ""))
            if sdk_str:
                print(f"[支付网关] 获取 SDK 串成功 (长度={len(sdk_str)})")
                print(f"[支付网关] SDK 串前100字符: {sdk_str[:100]}...")
        return result

    def convert_to_h5(self, sdk_str: str) -> dict:
        """
        支付宝转链 (SDK 串 -> H5 支付链接)

        来源: test-direct-order.py convert_to_h5
        流程:
          1. 构造请求 JSON (含 sdk_str 作为 external_info)
          2. 3DES ECB 加密请求 JSON
          3. RSA 公钥加密 3DES 密钥
          4. 拼接 req_data 发送到支付宝网关 mcgw.alipay.com
          5. 3DES 解密响应，提取 H5 URL
        """
        import requests as std_requests

        ALIPAY_3DES_KEY = b'23h4fhdilenbs741kogue1tl'
        ALIPAY_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
                            MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDENksAVqDoz5SMCZq0bsZwE+I3
                            NjrANyTTwUVSf1+ec1PfPB4tiocEpYJFCYju9MIbawR8ivECbUWjpffZq5QllJg+
                            19CB7V5rYGcEnb/M7CS3lFF2sNcRFJUtXUUAqyR3/l7PmpxTwObZ4DLG258dhE2v
                            FlVGXjnuLs+FI2hg4QIDAQAB
                            -----END PUBLIC KEY-----"""

        print(f"[转链] 开始转链, sdk_str 长度={len(sdk_str)}")
        try:
            # 1. 构造请求 JSON
            json_request = (
                f'{{"tid":"qwertyuiopasdfghjklzxcvbnm",'
                f'"user_agent":"Msp/9.1.5 (Android 12;Linux 4.4.146;zh_CN;http;540*960;21.0;WIFI;'
                f'87699552;32617;1;000000000000000;000000000000000;8efce46e85;GOOGLE;H002;false;'
                f'00:00:00:00:00:00;-1.0;-1.0;sdk-and-lite;65r7u2pfruicqrn;r2agza5c56pzmev;'
                f'<unknown ssid>;02:00:00:00:00:00)",'
                f'"has_alipay":false,"has_msp_app":false,'
                f'"external_info":"{sdk_str}",'
                f'"app_key":"2021002145675770","utdid":"z1x2c3v4v5v6v78v9",'
                f'"new_client_key":"8efcf8b134",'
                f'"action":{{"type":"cashier","method":"main"}},"gzip":true}}'
            )

            # 2. 3DES ECB 加密
            cipher = DES3.new(ALIPAY_3DES_KEY, DES3.MODE_ECB)
            padded_data = pad(json_request.encode('utf-8'), DES3.block_size)
            encrypted_data = base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

            # 3. RSA 公钥加密 3DES 密钥
            rsa_key = RSA.import_key(ALIPAY_PUBLIC_KEY)
            rsa_cipher = PKCS1_Cipher.new(rsa_key)
            parameter1 = base64.b64encode(rsa_cipher.encrypt(ALIPAY_3DES_KEY)).decode('utf-8')

            # 4. 拼接 req_data
            parameter2 = format(len(parameter1), '08X')
            parameter3 = format(len(encrypted_data), '08X')
            req_data = parameter2 + parameter1 + parameter3 + encrypted_data

            gateway_payload = json.dumps({
                'data': {
                    'device': 'GOOGLE-H002',
                    'namespace': 'com.alipay.mobilecashier',
                    'api_name': 'com.alipay.mcpay',
                    'api_version': '4.0.2',
                    'params': {'req_data': req_data},
                }
            }, separators=(',', ':'))

            gateway_headers = {
                'Accept-Charset': 'UTF-8',
                'Connection': 'Keep-Alive',
                'Content-Type': 'application/octet-stream;binary/octet-stream',
                'Cookie': 'zone=RZ43A',
                'Cookie2': '$Version=1',
                'Host': 'mcgw.alipay.com',
                'Keep-Alive': 'timeout=180, max=100',
                'User-Agent': 'msp',
            }

            print("[转链] 请求支付宝网关 mcgw.alipay.com ...")
            with cffi_requests.Session(impersonate="chrome124") as pay_sess:
                resp = pay_sess.post(
                    'http://mcgw.alipay.com/gateway.do',
                    data=gateway_payload.encode('utf-8'),
                    headers=gateway_headers,
                    timeout=15,
                    verify=False,
                )
            response = resp.json()
            print(f"[转链] 网关响应: {json.dumps(response, ensure_ascii=False)[:200]}")

            # 5. 3DES 解密响应
            res_data = None
            if isinstance(response, dict):
                res_data = (response.get('data') or {}).get('params', {}).get('res_data')
            if not res_data:
                print("[转链] 网关响应无 res_data")
                return {'success': False, 'message': '网关响应无 res_data'}

            decipher = DES3.new(ALIPAY_3DES_KEY, DES3.MODE_ECB)
            decrypted_padded = decipher.decrypt(base64.b64decode(res_data))
            pad_len = decrypted_padded[-1]
            decrypted = decrypted_padded[:-pad_len].decode('utf-8')
            print(f"[转链] 解密响应: {decrypted[:300]}")

            json_data = json.loads(decrypted)
            onload_name = (json_data.get('form') or {}).get('onload', {}).get('name')
            if not onload_name:
                print("[转链] 解密响应中无 form.onload.name")
                return {'success': False, 'message': '解密响应中无 form.onload.name'}

            # 6. 提取 H5 URL
            match = re.search(r'https://[^\s\']+', onload_name)
            if match:
                h5_url = match.group(0)
                print(f"[转链] H5 支付链接: {h5_url}")
                return {'success': True, 'h5Url': h5_url}

            print("[转链] 未匹配到 H5 URL")
            return {'success': False, 'message': '未匹配到 H5 URL'}

        except Exception as e:
            print(f"[转链] 异常: {e}")
            return {'success': False, 'message': str(e)}


# ==================== 主流程 ====================

def _load_accounts(accounts_path: str) -> list:
    """从 iplala_accounts.json 加载账号列表"""
    import os
    if not os.path.exists(accounts_path):
        return []
    try:
        with open(accounts_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[账号] 读取 iplala_accounts.json 失败: {e}")
        return []


def _save_account(accounts_path: str, mobile: str, client) -> None:
    """登录成功后保存/更新账号到 iplala_accounts.json"""
    accounts = _load_accounts(accounts_path)
    record = {
        "mobile": mobile,
        "userid": client.user_id,
        "token": client.token,
        "cookie": client.cookie,
        "mt-device-id": client.mt_device_id,
        "bs-dvid": client.bs_dvid,
        "device-id": client.raw_device_id,
        "user-agent": client.user_agent,
        "webview-ua": client.webview_ua,
        "mt-r": client.mt_r,
        "mt-sn": client.mt_sn,
        "h5-did": client.h5_did,
        "h5-start-id": client.h5_start_id,
        "bs-device-id": client.bs_device_id,
        "loginTime": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }
    idx = next((i for i, u in enumerate(accounts) if u.get("mobile") == mobile), -1)
    if idx >= 0:
        accounts[idx] = {**accounts[idx], **record}
        print(f"\n💾 已更新账号 {mobile} 到 iplala_accounts.json")
    else:
        accounts.append(record)
        print(f"\n💾 已保存账号 {mobile} 到 iplala_accounts.json")
    with open(accounts_path, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def _load_account_to_client(acc: dict, client) -> None:
    """将账号数据注入 client，覆盖设备参数"""
    client.token        = acc.get("token", "")
    client.cookie       = acc.get("cookie", "")
    client.user_id      = str(acc.get("userid", ""))
    if acc.get("mt-device-id"):  client.mt_device_id  = acc["mt-device-id"]
    if acc.get("device-id"):     client.raw_device_id = acc["device-id"]
    if acc.get("bs-dvid"):       client.bs_dvid       = acc["bs-dvid"]
    if acc.get("mt-r"):          client.mt_r          = acc["mt-r"]
    if acc.get("mt-sn"):         client.mt_sn         = acc["mt-sn"]
    if acc.get("h5-did"):        client.h5_did        = acc["h5-did"]
    if acc.get("h5-start-id"):   client.h5_start_id   = acc["h5-start-id"]
    if acc.get("bs-device-id"):  client.bs_device_id  = acc["bs-device-id"]
    if acc.get("webview-ua"):    client.webview_ua    = acc["webview-ua"]
    if acc.get("user-agent"):    client.user_agent    = acc["user-agent"]


if __name__ == "__main__":
    import os
    accounts_path = os.path.join(os.path.dirname(__file__), 'iplala_accounts.json')
    accounts = _load_accounts(accounts_path)
    client = None

    # 1. 账号选择
    if accounts:
        print("\n📂 发现已保存的账号:")
        for i, u in enumerate(accounts):
            print(f"  [{i}] {u.get('mobile')}  userid={u.get('userid')}  登录时间: {u.get('loginTime', '-')}")

        choice = input("\n是否使用已有账号? (y=使用 / n=重新登录 / 直接回车=使用第一个): ").strip().lower()

        if choice != 'n':
            if len(accounts) == 1 or choice in ('y', ''):
                selected = accounts[0]
            else:
                idx = input(f"选择账号序号 [0-{len(accounts)-1}]: ").strip()
                selected = accounts[int(idx) if idx else 0]

            print(f"\n✅ 使用账号: {selected.get('mobile')} (userid={selected.get('userid')})")
            client = MoutaiClient(bs_dvid=selected.get('bs-dvid', ''))
            _load_account_to_client(selected, client)

    # 2. 需要重新登录
    if not client:
        client = MoutaiClient()
        print("=" * 50)
        print(f"Device-ID:  {client.mt_device_id}")
        print(f"Raw-ID:     {client.raw_device_id}")
        print(f"User-Agent: {client.user_agent}")
        print("=" * 50)

        mobile = input("\n请输入手机号: ").strip()
        if not mobile:
            print("手机号不能为空")
            exit(1)

        vcode_result = client.send_vcode(mobile)
        if vcode_result.get("code") != 2000:
            print(f"发送验证码失败: {vcode_result}")
            exit(1)

        vcode = input("\n请输入验证码: ").strip()
        login_result = client.login(mobile, vcode)
        if login_result.get("code") != 2000:
            exit(1)

        _save_account(accounts_path, mobile, client)

    # # 2. 获取收货地址
    # print("\n" + "=" * 50)
    # addresses = client.get_addresses()
    # if not addresses:
    #     print("没有收货地址，请先在 APP 中添加")
    #     exit(1)

    # if len(addresses) == 1:
    #     selected_addr = addresses[0]
    # else:
    #     idx = input(f"\n选择地址序号 [0-{len(addresses)-1}]: ").strip()
    #     selected_addr = addresses[int(idx) if idx else 0]
    # print(f"使用地址: id={selected_addr['shipAddressId']} {selected_addr.get('fullAddress','')}")

    # 3. 选择下单模式
    print("\n" + "=" * 50)
    mode = input("请选择下单模式 (1=抢购模式 / 2=直接购买模式): ").strip()
    
    if mode == "2":
        # === 直接购买模式（根据抓包数据） ===
        store_id = input("门店ID (如 IMT0000000099): ").strip()
        spu_id = input("商品ID (如 WC0050010002): ").strip()
        count = int(input("数量 (如 1): ").strip() or "1")
        
        # 获取地址
        addresses = client.get_addresses()
        if not addresses:
            print("未找到收货地址，请先添加地址")
            exit(0)
        
        print(f"\n可用地址:")
        for i, addr in enumerate(addresses):
            default_mark = " [默认]" if addr.get("dft") else ""
            print(f"  [{i}] {addr.get('fullAddress', '')} - {addr.get('name', '')} {addr.get('mobile', '')}{default_mark}")
        
        addr_idx = int(input(f"\n选择地址编号 (0-{len(addresses)-1}): ").strip() or "0")
        selected_addr = addresses[addr_idx]
        
        print(f"\n使用地址: {selected_addr.get('fullAddress', '')}")
        
        # 直接下单
        submit_result = client.direct_submit_order(
            store_id=store_id,
            spu_id=spu_id,
            count=count,
            address=selected_addr,
            deliver_method=-1  # -1 表示快递配送
        )
        
        if submit_result.get("code") != 2000:
            print(f"\n下单失败: {submit_result}")
            exit(0)
        
        order_id = str(submit_result.get("data", {}).get("orderId", ""))
        print(f"\n[下单成功] orderId={order_id}")
        
    else:
        # === 抢购模式（原有逻辑） ===
        item_code = "IMTP1000006" #input("商品编码 (如 IMTP1000313): ").strip()
        sku_id = "1000139" #input("规格ID (如 741): ").strip()
        act_id = "82164" #input("活动ID (如 82107): ").strip()
        amount = 1 #input("数量 (如 1): ").strip() or "1"

        if not item_code or not sku_id or not act_id:
            print("商品编码、规格ID和活动ID均不能为空")
            exit(1)

        print()
        rush_result = None
        for attempt in range(1, 100001):
            print(f"--- 第 {attempt}/100000 次抢购 ---")
            rush_result = client.rush_purchase(
                item_code=item_code,
                sku_id=sku_id,
                item_priority_act_id=act_id,
                amount=amount,
            )
            if isinstance(rush_result, dict) and rush_result.get("code") == 2000:
                break
            # 随机延迟，模拟真实操作，避免 429
            delay = random.uniform(2.0, 4.0)
            print(f"--- 等待 {delay:.2f} 秒后继续 ---")
            time.sleep(delay)

        # 4. 组单 + 下单
        if rush_result.get("code") != 2000:
            print(f"\n抢购未成功: {rush_result}")
            exit(0)

        record_id = rush_result.get("data", {}).get("priorityRecordId", 0)
        print(f"\n[抢购成功] priorityRecordId={record_id}")

        if input("\n是否下单? (y/n): ").strip().lower() != "y":
            exit(0)

        count = int(amount)
        # compose_result = client.compose_order(
        #     spu_id=item_code, count=count, priority_record_id=record_id, address=selected_addr,
        # )
        # if compose_result.get("code") != 2000:
        #     print(f"\n组单失败: {compose_result}")
        #     exit(0)

        # 先定义地址变量（空地址示例，你 later 可以改成真实地址）
        selected_addr = ""  # 这里是空字符串，不影响运行

        submit_result = client.submit_order(
            spu_id=item_code, count=count, priority_record_id=record_id, address=selected_addr,
        )
        if submit_result.get("code") != 2000:
            print(f"\n下单失败: {submit_result}")
            exit(0)

        order_id = str(submit_result.get("data", {}).get("orderId", ""))
        print(f"\n[下单成功] orderId={order_id}")

    if input("是否支付? (y/n): ").strip().lower() != "y" or not order_id:
        exit(0)

    pay_result = client.pay_order(order_id)
    if pay_result.get("code") != 2000:
        print(f"支付请求失败: {pay_result}")
        exit(0)

    pay_data = pay_result.get("data", {})
    channelTradeSn = pay_data.get("channelTradeSn") or pay_data.get("tn", "")
    if not channelTradeSn:
        print(f"未获取到 TN: {pay_data}")
        exit(0)

    gw_result = client.request_pay(channelTradeSn, pay_channel="70")
    code = gw_result.get("code")
    if isinstance(code, str):
        code = int(code)
    if code not in (200, 2000):
        print(f"支付网关失败: {gw_result}")
        exit(0)

    p_data = gw_result.get("data")
    sdk_str = p_data if isinstance(p_data, str) else (
        p_data.get("payInfo") or p_data.get("alipay_sdk")
        or p_data.get("orderInfo") or p_data.get("AUTH_CODE", "")
    ) if isinstance(p_data, dict) else ""

    if not sdk_str:
        print(f"支付网关未返回 SDK 串: {gw_result}")
        exit(0)

    h5_result = client.convert_to_h5(sdk_str)
    if h5_result.get("success"):
        print(f"\n[H5 支付链接] {h5_result['h5Url']}")
    else:
        print(f"转链失败: {h5_result.get('message')}")
        print(f"SDK 串: {sdk_str[:100]}...")
