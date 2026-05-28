#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 全局配置（统一版）
moutai_automation.py (5000端口) 共用
"""

import os

# ===================== 路径配置 =====================
BASEDIR = os.path.abspath(os.path.dirname(__file__))
QRCODE_FOLDER = os.path.join(BASEDIR, 'static', 'qrcodes')
UPLOAD_FOLDER = os.path.join(BASEDIR, 'uploads')
DATA_FOLDER = os.path.join(BASEDIR, 'data')
BUILDS_DIR = os.path.join(BASEDIR, 'builds')
STATIC_DIR = os.path.join(BASEDIR, 'static')
TEMPLATES_DIR = os.path.join(BASEDIR, 'templates')

# 确保必要目录存在
for d in [QRCODE_FOLDER, UPLOAD_FOLDER, DATA_FOLDER, BUILDS_DIR]:
    os.makedirs(d, exist_ok=True)


# ===================== 安全配置 =====================
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'main-bridge-secret-key-5000'
    
    # MySQL 数据库配置
    MYSQL_HOST = 'ipla.top'
    MYSQL_PORT = 3306
    MYSQL_USER = 'maomama'
    MYSQL_PASSWORD = 'aQ9SnwTx6i4QzRhx'
    MYSQL_DATABASE = 'maomama'
    SQLALCHEMY_DATABASE_URI = (
        f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@'
        f'{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
    )
    
    # 服务配置
    MAX_THREADS = 20
    HOST = '0.0.0.0'
    BRIDGE_PORT = 5000   # 桥接/管理端口（原8000已合并到5000）
    CLIENT_PORT = 5000    # 客户端通信端口 (moutai_automation.py)
    
    # API鉴权
    API_TOKEN = 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd'
    
    # 桥接配置
    BRIDGE_BASE_URL = 'http://127.0.0.1:5000'
    
    # 默认抢购时间
    DEFAULT_RUSH_HOUR = 19
    DEFAULT_RUSH_MINUTE = 59
    DEFAULT_RUSH_SECOND = 59
    
    # 库存监控
    INVENTORY_MONITORING_END_HOUR = 21
    INVENTORY_CHECK_INTERVAL = 60
    
    # 客户端心跳超时（秒）
    CLIENT_HEARTBEAT_TIMEOUT = 30
    
    # 滑块验证模块端口
    SLIDER_API_PORT = 8887    # Express app_api_rounddv.js
    OCR_SERVER_PORT = 9898    # Flask ocr_server.py
    SLIDER_API_URL = f'http://127.0.0.1:{SLIDER_API_PORT}'
    OCR_SERVER_URL = f'http://127.0.0.1:{OCR_SERVER_PORT}'


# ===================== 茅台 API 常量 =====================
# App API 基础URL
BASE_URL = "https://app.moutai519.com.cn"
H5_BASE_URL = "https://h5.moutai519.com.cn"
STATIC_URL = "https://static.moutai519.com.cn"
RESOURCE_URL = "https://resource.moutai519.com.cn"
PAYAPI_URL = "https://payapi.moutai519.com.cn"
FE_URL = "https://fe.moutai519.com.cn"

# App 版本
APP_VERSION = "1.9.7"
SDK_VERSION = "3.4.0.202109291244"
BUNDLE_ID = "com.moutai.mall"


# ===================== 服务器 IP 白名单（从 HAR 提取）=====================
WHITELIST_IPS = [
    # === 茅台核心 ===
    "175.43.199.112",   # app.moutai519.com.cn + fk1 + payapi
    "123.6.84.25",      # static.moutai519.com.cn + fe
    "123.6.84.248",     # static.moutai519.com.cn + fe
    "123.6.85.83",      # static.moutai519.com.cn + fe
    "180.76.199.131",   # dc.moutai519.com.cn (事件上报，可选)
    "122.195.144.16",   # resource.moutai519.com.cn (CDN，可选)
    "101.69.146.238",   # resource.moutai519.com.cn (CDN，可选)
    "27.222.17.238",    # resource.moutai519.com.cn (CDN，可选)
    "119.188.72.61",    # h5.moutai519.com.cn
    "123.155.252.136",  # h5.moutai519.com.cn
    "123.155.252.138",  # h5.moutai519.com.cn
    # === 百度风控 ===
    "163.177.18.227",   # haotian.baidu.com + mshield.baidu.com
    # === 网易易盾验证码 ===
    "221.204.66.38",    # cstaticdun.126.net
    "220.197.32.185",   # c.dun.163.com
    "220.197.32.187",   # ir-sdk.dun.163.com
    "180.130.99.140",   # necaptcha.nosdn.127.net
    # === 支付宝 ===
    "203.209.250.8",    # mobilegw.alipay.com
    "203.209.243.27",   # mobilegw.alipay.com
]
