#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i茅台 1.9.6 Demo - 登录 + 黄小西抢购 + 下单 + 支付
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
import tls_client
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
)

BASE_URL = "https://app.moutai519.com.cn"
H5_BASE_URL = "https://h5.moutai519.com.cn"
PAY_API_URL = "https://payapi.moutai519.com.cn"
VCODE_SALT = "2af72f100c356273d46284f6fd1dfc08"

# 茅台支付 SDK 常量 (来自 PaySdkConfig / p458l9.C8324b.m31095a)
MTPAY_APP_ID = "MT519ANDROID"
MTPAY_APP_SECRET = "8C79446361034bd2aE98b27E153a2eA8"  # securityID = MD5(tn+ts+secret)
MTPAY_SM4_KEY = "e881E52D7932Cf00"                      # cipherText = SM4_ECB(ts, key)

# TLS 指纹伪装: okhttp 4.x JA3 指纹
TLS_IDENTIFIER = "okhttp4_android_13"

# tls_client session (全局复用)
_tls_session = tls_client.Session(client_identifier=TLS_IDENTIFIER, random_tls_extension_order=True)


def _post(url, headers=None, json=None, data=None, **kwargs):
    """统一 POST，使用 tls_client 伪装 TLS 指纹"""
    kwargs.pop('impersonate', None)
    return _tls_session.post(url, headers=headers, json=json, data=data, timeout_seconds=15, **kwargs)


def _get(url, headers=None, params=None, **kwargs):
    """统一 GET"""
    kwargs.pop('impersonate', None)
    return _tls_session.get(url, headers=headers, params=params, timeout_seconds=15, **kwargs)


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
# 每个元素: (Android 版本, 设备型号, Build ID, Chrome 版本)
_WEBVIEW_UA_POOL = [
    (14, "SM-G991B", "UP1A.231005.007", "124.0.6367.179"),   # Samsung S21
    (13, "Pixel 7",  "TQ3A.230901.001", "120.0.6099.230"),   # Google Pixel 7
    (14, "22081212C","UKQ1.230917.001", "122.0.6261.64"),     # Xiaomi 12S Ultra
    (13, "V2254A",   "TP1A.220624.014", "119.0.6045.193"),   # vivo X90
    (14, "OPH2201",  "UP1A.231005.007", "123.0.6312.118"),   # OnePlus 10 Pro
]


class MoutaiClient:
    """i茅台客户端"""

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
        """
        if not android_id:
            android_id = uuid.uuid4().hex[:16]

        # 从设备池随机选取一个设备配置 (保证 APP UA 和 WebView UA 一致)
        device_idx = random.randint(0, len(_WEBVIEW_UA_POOL) - 1)
        dv_android, dv_model, dv_build, dv_chrome = _WEBVIEW_UA_POOL[device_idx]

        # APP 层设备参数 (可覆盖, 不传则随机)
        _sdk = sdk_int or dv_android
        _mfr = manufacturer or ["samsung", "google", "xiaomi", "vivo", "oneplus"][device_idx]
        _mdl = model or ["o1q", "pixel7", "cupid", "v2254a", "oph2201"][device_idx]
        _screen = screen or random.choice(["1080*2340", "1080*2400", "1080*2176", "1440*3200"])

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

        # _d_u cookie (瑞数设备上报, 每 ~10 秒刷新)
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
            "Referer": referer or f"{H5_BASE_URL}/mt/item/hxx-detail?appConfig=2_1_2",
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

        print(f"[验证码] 手机号: {mobile}, 时间戳: {timestamp}")
        print(f"[验证码] 请求头:")
        for k, v in headers.items():
            print(f"  {k}: {v}")
        print(f"[验证码] 请求体: {json.dumps(body, ensure_ascii=False)}")
        resp = _post(f"{BASE_URL}/xhr/front/user/register/vcode", headers=headers, json=body)
        print(f"[验证码] HTTP {resp.status_code}, length={len(resp.content)}")
        if resp.status_code != 200 or not resp.text:
            print(f"[验证码] 响应头: {dict(resp.headers)}")
            print(f"[验证码] 响应体: {resp.text[:500] if resp.text else '(empty)'}")
            return {"code": resp.status_code, "message": "HTTP error"}
        result = resp.json()
        print(f"[验证码] 响应: {result}")
        return result

    def login(self, mobile: str, vcode: str) -> dict:
        """登录"""
        headers = self._app_headers(need_sign=True)
        body = {"vCode": vcode, "mobile": mobile, "ydToken": "", "ydLogId": ""}

        print(f"[登录] 手机号: {mobile}, MT-V: {headers['MT-V']}")
        resp = _post(f"{BASE_URL}/xhr/front/user/register/login", headers=headers, json=body)
        result = resp.json()

        if result.get("code") == 2000:
            data = result["data"]
            self.token = data.get("token", "")
            self.cookie = data.get("cookie", "")
            self.user_id = str(data.get("userId", ""))
            print(f"[登录] 成功! userId={self.user_id}")
            print(f"[登录] token:  {self.token[:50]}...")
            print(f"[登录] cookie: {self.cookie[:50] if self.cookie else '(empty)'}...")
            print(f"[登录] token==cookie: {self.token == self.cookie}")
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

    # ==================== 抢购 ====================

    def rush_purchase(self, item_code: str, item_priority_act_id: str,
                      amount: str = "1", source_id: str = "") -> dict:
        """
        黄小西抢购 (含瑞数防护 + WASM 签名)

        POST /xhr/front/trade/priority/rushPurchase
        Host: h5.moutai519.com.cn
        """
        data = {
            "amount": amount,
            "itemCode": item_code,
            "itemPriorityActId": item_priority_act_id,
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
        act_param = generate_act_param(data)
        body = {"actParam": act_param}

        item_branch_map = {'741': 'one', '11947': 'two', '11945': 'two', '11942': 'two','1741': 'three'}
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

        headers = self._h5_headers(body, referer=referer, is_rush_purchase=True)

        print(f"[抢购] itemCode={item_code}, actId={item_priority_act_id}, amount={amount}")
        print(f"[抢购] MT-K: {headers['MT-K']}")
        print(f"[抢购] Content-Hh-Bb: {headers['Content-Hh-Bb']}")

        resp = _post(
            f"{rush_url}",
            headers=headers,
            json=body,
        )
        try:
            result = resp.json()
        except Exception:
            result = {"code": resp.status_code, "raw": resp.text}
        print(f"[抢购] 响应: {result}")
        return result

    # ==================== 下单 ====================

    def compose_order(self, spu_id: str, count: int, priority_record_id: int,
                      address: dict, deliver_method: int = 1,
                      store_id: str = "0", shop_id: str = "",
                      inventory_source: int = 0) -> dict:
        """
        组单 (compose)

        POST /xhr/front/trade/priority/composeOrder
        Host: h5.moutai519.com.cn

        actParam 明文:
        {
            "deliverMethod": 1,
            "itemList": [{"storeId": "0", "spuId": "11679", "count": 24}],
            "addressInfo": {"shipAddressId": 37664847},
            "userPriorityInfo": {"priorityRecordId": 17642587, "shopId": "", "inventorySource": 0},
            "selfLatitude": "",
            "selfLongitude": ""
        }
        """
        data = {
            "deliverMethod": deliver_method,
            "itemList": [
                {"storeId": store_id, "spuId": spu_id, "count": count}
            ],
            "addressInfo": {"shipAddressId": address.get("shipAddressId", 0)},
            "userPriorityInfo": {
                "priorityRecordId": priority_record_id,
                "shopId": shop_id,
                "inventorySource": inventory_source,
            },
            "selfLatitude": "",
            "selfLongitude": "",
        }
        act_param = generate_act_param(data)
        body = {"actParam": act_param}
        headers = self._h5_headers(body)

        print(f"[组单] spuId={spu_id}, count={count}, addressId={address.get('shipAddressId')}")
        resp = _post(
            f"{BASE_URL}/xhr/front/trade/order/standard/compose/v2",
            headers=headers,
            json=body,
        )
        result = resp.json()
        print(f"[组单] 响应: code={result.get('code')}")
        return result

    def submit_order(self, spu_id: str, count: int, priority_record_id: int,
                     address: dict, deliver_method: int = 1,
                     store_id: str = "0", shop_id: str = "",
                     inventory_source: int = 0) -> dict:
        """
        提交订单 (submit)

        POST /xhr/front/trade/priority/submitOrder
        Host: h5.moutai519.com.cn

        actParam 明文:
        {
            "transactionId": "{userId}_{recordId}_compose",
            "deliverMethod": 1,
            "itemList": [{"storeId": "0", "spuId": "11679", "count": 24}],
            "addressInfo": { ...完整地址信息... },
            "userPriorityInfo": {"priorityRecordId": 17642587, "shopId": "", "inventorySource": 0},
            "selfLatitude": "",
            "selfLongitude": ""
        }
        """
        transaction_id = f"{self.user_id}_{priority_record_id}_compose"
        data = {
            "transactionId": transaction_id,
            "deliverMethod": deliver_method,
            "itemList": [
                {"storeId": store_id, "spuId": spu_id, "count": count}
            ],
            "addressInfo": {
                "address": address.get("address", ""),
                "cityId": address.get("cityId", ""),
                "cityName": address.get("cityName", ""),
                "dft": address.get("dft", False),
                "districtId": address.get("districtId", ""),
                "districtName": address.get("districtName", ""),
                "fullAddress": address.get("fullAddress", ""),
                "mobile": address.get("mobile", ""),
                "name": address.get("name", ""),
                "provinceId": address.get("provinceId", ""),
                "provinceName": address.get("provinceName", ""),
                "shipAddressId": address.get("shipAddressId", 0),
                "townId": address.get("townId", ""),
                "townName": address.get("townName", ""),
                "userId": int(self.user_id) if self.user_id else 0,
            },
            "userPriorityInfo": {
                "priorityRecordId": priority_record_id,
                "shopId": shop_id,
                "inventorySource": inventory_source,
            },
            "selfLatitude": "",
            "selfLongitude": "",
        }
        act_param = generate_act_param(data)
        body = {"actParam": act_param}
        headers = self._h5_headers(body)

        print(f"[下单] transactionId={transaction_id}")
        resp = _post(
            f"{BASE_URL}/xhr/front/trade/order/standard/submit/v2",
            headers=headers,
            json=body,
        )
        result = resp.json()
        print(f"[下单] 响应: {result}")
        return result

    # ==================== 支付 ====================

    def pay_order(self, order_id: str, pay_method: int = 0) -> dict:
        """
        支付订单 (第一步: 获取 TN)

        POST /xhr/front/trade/order/pay
        Host: app.moutai519.com.cn
        body: {"orderId": "619118778", "payMethod": 0}

        payMethod: 0=茅台支付(支付宝)
        返回 data 中包含 tn (交易号)
        {
            "code": 2000,
            "data": {
                "outTradeNo": "623895218",
                "channelTradeSn": "177631074300120260416177630990399362389521810",
                "totalAmount": 13794.00,
                "payResultQueryTimeout": 10,
                "extInfo": "{\"COUNTDOWN_SECOND\":840,\"MSG_429\":\"网络拥堵，请稍后重试\",\"PUB\":\"001\"}"
            }
        }
        """
        headers = self._app_headers(need_sign=False)
        body = {"orderId": order_id, "payMethod": pay_method}

        print(f"[支付] orderId={order_id}, payMethod={pay_method}")
        resp = _post(
            f"{H5_BASE_URL}/xhr/front/trade/order/pay",
            headers=headers,
            json=body,
        )
        result = resp.json()
        print(f"[支付] 响应: code={result.get('code')}")
        return result

    def request_pay(self, channel_trade_sn: str, pay_channel: str = "70") -> dict:
        """
        请求支付网关 (第二步: 获取支付宝 SDK 串)

        POST /settle-api-server/anon/pay/requestPay
        Host: payapi.moutai519.com.cn
        Content-Type: application/x-www-form-urlencoded

        来源: MtPayActivity.zfbAppPay
        参数:
          inJson    = {"PAY_CHANNEL":"70","TN":"xxx"}
          cipherText = SM4_ECB(timestamp, sm4Key) → Base64
          appId     = "MT519ANDROID"
          securityID = MD5(tn + timestamp + appSecret)

        pay_channel: "70"=支付宝, "10"=微信, "20"=银联
        """
        from urllib.parse import urlencode
        timestamp = str(int(time.time() * 1000))

        # inJson
        in_json = json.dumps({"PAY_CHANNEL": pay_channel, "TN": channel_trade_sn}, separators=(',', ':'))

        # cipherText = SM4_ECB(timestamp, sm4Key) → Base64
        cipher_text = sm4_encrypt(timestamp, MTPAY_SM4_KEY)

        # securityID = MD5(tn + timestamp + appSecret)
        security_id = md5_hex(channel_trade_sn + timestamp + MTPAY_APP_SECRET)

        body = urlencode({
            "inJson": in_json,
            "cipherText": cipher_text,
            "appId": MTPAY_APP_ID,
            "securityID": security_id,
        })

        print(f"[支付网关] TN={channel_trade_sn[:30]}...")
        print(f"[支付网关] securityID={security_id}")

        resp = _post(
            f"{PAY_API_URL}/settle-api-server/anon/pay/requestPay",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "okhttp/4.9.2",
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
            },
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
            resp = std_requests.post(
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
    from app import secure_filename
    import app
    accounts_path = os.path.join(os.path.dirname(__file__), 'accounts.json')
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
        from app import api_send_code
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

    # 3. 抢购
    print("\n" + "=" * 50)
    item_code = input("商品编码 (如 11679): ").strip()
    act_id = input("活动ID (如 76145): ").strip()
    amount = input("数量 (如 24): ").strip() or "1"

    print()
    rush_result = None
    for attempt in range(1, 100001):
        print(f"--- 第 {attempt}/100000 次抢购 ---")
        rush_result = client.rush_purchase(
            item_code=item_code,
            item_priority_act_id=act_id,
            amount=amount,
        )
        if isinstance(rush_result, dict) and rush_result.get("code") == 2000:
            break
        time.sleep(0.8)

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
