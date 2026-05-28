#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矮猫多账号自动化管理系统 - FastAPI 独立版本
完全兼容原有的 Flask 版本的所有功能，可独立运行在任何服务器上，无需依赖 main.py
"""

import os
import sys
import json
import time
import random
import datetime
import re
import uuid as _uuid
from typing import Dict, Optional, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, File, UploadFile, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session as SQLSession
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
import qrcode
import asyncio
import httpx

# ========== 全局时间戳打印：所有 print() 自动追加 [HH:MM:SS.mmm] 前缀 ==========
class _TsWriter:
    """包装 sys.stdout，每行自动加时间戳前缀"""
    def __init__(self, orig):
        self._orig = orig
        self._buf = ''
    def write(self, s):
        if s == '\n':
            if self._buf:
                now = datetime.datetime.now()
                ts = now.strftime('%H:%M:%S.') + f'{now.microsecond // 1000:03d}'
                self._orig.write(f'[{ts}] {self._buf}\n')
                self._buf = ''
            else:
                self._orig.write('\n')
        else:
            self._buf += s
    def flush(self):
        if self._buf:
            self._orig.write(self._buf)
            self._buf = ''
        self._orig.flush()
    def isatty(self):
        return self._orig.isatty()
sys.stdout = _TsWriter(sys.stdout)
# ========================================================================

# 不直接导入 demo.py，MoutaiClient 操作通过 HTTP 桥接调用（本进程内端口 5000）
BRIDGE_BASE_URL = 'http://127.0.0.1:5000'


class BridgeClient:
    """通过 HTTP 桥接调用 MoutaiClient 操作（本进程内，端口 5000）"""
    
    def __init__(self, base_url: str = None, api_token: str = None):
        self.base_url = base_url or BRIDGE_BASE_URL
        self.api_token = api_token or Config.API_TOKEN
        self._headers = {'X-API-TOKEN': self.api_token, 'Content-Type': 'application/json'}
    
    async def _post(self, endpoint: str, data: dict) -> dict:
        """异步调用桥接 API"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f'{self.base_url}{endpoint}', json=data, headers=self._headers)
                if resp.status_code == 403:
                    return {'success': False, 'message': '桥接鉴权失败'}
                return resp.json()
        except httpx.ConnectError:
            print(f'[桥接] 连接失败 ({self.base_url})，桥接服务可能未启动')
            return {'success': False, 'message': '桥接服务不可用'}
        except Exception as e:
            print(f'[桥接] 请求异常: {e}')
            return {'success': False, 'message': str(e)}
    
    async def check_login(self, credentials: dict, proxy_url: str = '') -> Optional[bool]:
        """检查登录状态。返回 True=有效, False=无效, None=桥接不可达"""
        data = dict(credentials)
        if proxy_url:
            data['proxy_url'] = proxy_url
        result = await self._post('/api/bridge/check_login', data)
        if not result.get('success') and '桥接服务不可用' in result.get('message', ''):
            return None  # 桥接不可达，无法判断
        return result.get('valid', False)
    
    async def send_vcode(self, phone: str, credentials: dict) -> bool:
        """发送验证码"""
        result = await self._post('/api/bridge/send_vcode', {
            'phone': phone, 'credentials': credentials
        })
        return result.get('success', False)
    
    async def login(self, phone: str, code: str, credentials: dict) -> dict:
        """登录并返回更新后的凭证"""
        result = await self._post('/api/bridge/login', {
            'phone': phone, 'vcode': code, 'credentials': credentials
        })
        if result.get('success'):
            return result.get('credentials', {})
        return {'error': result.get('message', '登录失败')}
    
    async def check_inventory(self, phone: str, item_code: str, credentials: dict) -> int:
        """检查库存，返回可用数量（-1=错误）"""
        result = await self._post('/api/bridge/check_inventory', {
            'phone': phone, 'item_code': item_code, 'credentials': credentials
        })
        return result.get('available', -1)


# ===================== 配置 =====================
BASEDIR = os.path.abspath(os.path.dirname(__file__))
QRCODE_FOLDER = os.path.join(BASEDIR, 'static', 'qrcodes')
UPLOAD_FOLDER = os.path.join(BASEDIR, 'uploads')
DATA_FOLDER = os.path.join(BASEDIR, 'data')
os.makedirs(QRCODE_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)

# 库存监控全局变量
stock_monitoring_active = False
is_stock_available = False
active_monitors = {}
INVENTORY_MONITORING_END_HOUR = 21
INVENTORY_CHECK_INTERVAL = 60
rush_job_started = False

# 库存广播系统
inventory_broadcast_status: str = 'unknown'  # 'available' | 'soldout' | 'unknown'
broadcast_clients: dict = {}  # client_id -> callback_url
broadcast_tree_lock = asyncio.Lock()

# 客户端注册与心跳追踪系统
active_client_windows: dict = {}  # {client_id: {"batch": int, "last_heartbeat": float, "ip": str, "hostname": str, "task_count": int}}
CLIENT_HEARTBEAT_TIMEOUT = 30  # 秒，超时视为断开
assigned_phones: dict = {}  # {phone: client_uuid} 记录已分配给哪个窗口的手机号（追踪用，不限制跨窗口重复使用）
client_register_lock = asyncio.Lock()  # 注册与分配的原子锁，防止并发竞争

# 诊断去重字典（避免重复打印诊断日志）
_diag_logged: dict = {}
# 服务重启日志去重（避免心跳10秒刷屏）
_server_restart_logged: dict = {}

# 服务器远程重启标志（按客户端外网 IP 控制，收到指令后随机0~10秒执行服务重启）
# 客户端心跳检测到 server_restart_required 后 systemctl restart，systemd Restart=always 自动拉起
# {ip: {"flag": True, "version": int, "trigger_time": float}}
server_restart_flags: dict = {}
# 服务器列表：按外网 IP 聚合 {ip: {"hostname": str, "windows": int, "tasks": int, "last_seen": float}}
server_list: dict = {}
# 待处理重启：server_list 为空时用户触发了重启，等客户端上线后自动执行
_pending_server_restart: dict = {}  # {"version": int, "trigger_time": float}

# ===================== 代理模式 ====================
# 代理模式：控制代理开关
#   proxy_only = 使用外部代理（豌豆代理池）
#   off        = 完全不走代理
PHONE_PROXY_MODE = os.environ.get('PHONE_PROXY_MODE', 'proxy_only')

# 黑号判断：兼容 'black' / '成功|黑号' 等格式
def _is_black_account(account_type: str) -> bool:
    if not account_type:
        return False
    at = account_type.lower()
    return '黑号' in at or at == 'black'

# 排除团队/上传者过滤（不上号功能）
def _filter_excluded(records: list, cfg) -> list:
    """根据 UserConfig 中的 excluded_teams / excluded_uploaders 过滤记录"""
    excluded_teams = [t.strip() for t in (cfg.excluded_teams or '').split(',') if t.strip()] if cfg.excluded_teams else []
    excluded_uploaders = [u.strip() for u in (cfg.excluded_uploaders or '').split(',') if u.strip()] if cfg.excluded_uploaders else []
    if excluded_teams or excluded_uploaders:
        filtered = [r for r in records if r.team not in excluded_teams and r.uploader_name not in excluded_uploaders]
        if len(filtered) < len(records):
            print(f'[不上号] 排除 {len(records) - len(filtered)} 条 (团队={excluded_teams}, 上传者={excluded_uploaders})')
        return filtered
    return records

# 客户端构建与下载系统
build_jobs: dict = {}  # {build_id: {"status":"building|done|error", "exe_path":"...", "user_id":N, "started":float}}
BUILDS_DIR = os.path.join(BASEDIR, 'builds')
os.makedirs(BUILDS_DIR, exist_ok=True)
_build_lock = asyncio.Lock()  # 防止同一用户重复触发构建

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
    MYSQL_HOST = 'ipla.top'
    MYSQL_PORT = 3306
    MYSQL_USER = 'maomama'
    MYSQL_PASSWORD = 'aQ9SnwTx6i4QzRhx'
    MYSQL_DATABASE = 'maomama'
    SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
    UPLOAD_FOLDER = UPLOAD_FOLDER
    DATA_FOLDER = DATA_FOLDER
    MAX_THREADS = 20
    HOST = '0.0.0.0'
    PORT = 5000
    API_TOKEN = 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd'
    DEFAULT_RUSH_HOUR = 8
    DEFAULT_RUSH_MINUTE = 58
    AUTO_MODE_DEFAULT = False
    # 豌豆代理API配置
    # 豌豆代理API地址由用户在网页配置（UserProxy.proxy_url）


_bridge = BridgeClient()  # 全局单例（必须在 Config 类之后）

# ===================== iplala_accounts.json 导入函数 =====================
def import_accounts_from_json(db: SQLSession = None, default_username: str = "admin"):
    """
    将 {username}_accounts.json 中已登录的账号导入到 phone_record 表
    按用户名分文件存储，避免跨用户数据混淆
    只在凭证确实有变化时才更新，避免每次启动都无意义地写入数据库
    """
    accounts_file = os.path.join(BASEDIR, f'{default_username}_accounts.json')
    if not os.path.exists(accounts_file):
        # 兼容旧版 iplala_accounts.json 文件名，若新版文件不存在且用户是 admin 则回退
        if default_username == "admin":
            legacy_file = os.path.join(BASEDIR, 'iplala_accounts.json')
            if os.path.exists(legacy_file):
                accounts_file = legacy_file
            else:
                return 0
        else:
            return 0
    try:
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
    except Exception as e:
        print(f'[导入] 读取 accounts 文件失败: {e}')
        return 0
    if not accounts:
        return 0

    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    # 用用户名查真实 ID，不再硬编码 ID=1
    owner = db.query(User).filter(User.username == default_username).first()
    owner_id = owner.id if owner else 1
    if not owner:
        print(f'[导入] 警告: 用户 "{default_username}" 不存在，回退到 ID=1')

    imported = 0
    updated = 0
    unchanged = 0
    try:
        for acc in accounts:
            phone = acc.get('mobile', '')
            if not phone:
                continue
            existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
            if existing:
                # 只在凭证确实有变化时才更新
                changed = False
                credential_fields = {
                    'token': acc.get('token', ''),
                    'cookie': acc.get('cookie', ''),
                    'user_id_ext': str(acc.get('userid', '')),
                    'mt_device_id': acc.get('mt-device-id', ''),
                    'raw_device_id': acc.get('device-id', ''),
                    'user_agent': acc.get('user-agent', ''),
                    'webview_ua': acc.get('webview-ua', ''),
                    'mt_r': acc.get('mt-r', ''),
                    'mt_sn': acc.get('mt-sn', ''),
                    'h5_did': acc.get('h5-did', ''),
                    'h5_start_id': acc.get('h5-start-id', ''),
                    'bs_device_id': acc.get('bs-device-id', ''),
                }
                for field, new_val in credential_fields.items():
                    old_val = getattr(existing, field) or ''
                    if new_val and new_val != old_val:
                        setattr(existing, field, new_val)
                        changed = True
                # 修复 uploaded_by / user_id 和 uploader_name 不一致
                if existing.uploaded_by != owner_id or existing.user_id != owner_id:
                    existing.uploaded_by = owner_id
                    existing.user_id = owner_id
                    existing.uploader_name = default_username
                    changed = True
                # 修复 logged_in 状态不一致
                if not existing.logged_in and acc.get('token'):
                    existing.logged_in = True
                    changed = True
                if changed:
                    existing.last_updated = datetime.datetime.utcnow()
                    updated += 1
                else:
                    unchanged += 1
            else:
                # 新建记录
                login_time = None
                if acc.get('loginTime'):
                    try:
                        login_time = datetime.datetime.strptime(acc['loginTime'], '%Y/%m/%d %H:%M:%S')
                    except:
                        pass
                rec = PhoneRecord(
                    phone=phone,
                    team=acc.get('team', ''),
                    user_id=owner_id,
                    uploaded_by=owner_id,
                    uploader_name=default_username,
                    code_sent=True,
                    logged_in=True if acc.get('token') else False,
                    token=acc.get('token', ''),
                    cookie=acc.get('cookie', ''),
                    user_id_ext=str(acc.get('userid', '')),
                    mt_device_id=acc.get('mt-device-id', ''),
                    raw_device_id=acc.get('device-id', ''),
                    h5_did=acc.get('h5-did', ''),
                    h5_start_id=acc.get('h5-start-id', ''),
                    bs_device_id=acc.get('bs-device-id', ''),
                    user_agent=acc.get('user-agent', ''),
                    webview_ua=acc.get('webview-ua', ''),
                    mt_r=acc.get('mt-r', ''),
                    mt_sn=acc.get('mt-sn', ''),
                    login_time=login_time,
                    last_updated=datetime.datetime.utcnow(),
                )
                db.add(rec)
                imported += 1
        if imported > 0 or updated > 0:
            db.commit()
            print(f'[导入] {default_username}_accounts.json 导入完成 | 新增={imported} | 更新={updated} | 无变化={unchanged}')
        else:
            print(f'[导入] {default_username}_accounts.json 数据无变化 | 无变化={unchanged}条')
        return imported + updated + unchanged
    except Exception as e:
        db.rollback()
        print(f'[导入] 导入失败: {e}')
        return 0
    finally:
        if own_session:
            db.close()

# ===================== 数据库模型 =====================
Base = declarative_base()
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_size=10, max_overflow=20, pool_timeout=30, pool_recycle=1800,
    echo=False, connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    failed_logins = Column(Integer, default=0)
    frozen_until = Column(DateTime, nullable=True)
    daily_failed = Column(Integer, default=0)
    last_failed_date = Column(DateTime, nullable=True)

class PhoneRecord(Base):
    __tablename__ = 'phone_record'
    team = Column(String(100), default='')
    phone = Column(String(20), primary_key=True)
    user_id = Column(Integer)
    uploaded_by = Column(Integer)
    code_sent = Column(Boolean, default=False)
    logged_in = Column(Boolean, default=False)
    bid_result = Column(String(200), default='')
    balance = Column(String(50), default='')
    last_updated = Column(DateTime, default=datetime.datetime.utcnow)
    token = Column(String(500), default='')
    cookie = Column(String(500), default='')
    user_id_ext = Column(String(50), default='')
    mt_device_id = Column(String(200), default='')
    raw_device_id = Column(String(100), default='')
    h5_did = Column(String(64), default='')
    h5_start_id = Column(String(64), default='')
    bs_device_id = Column(String(64), default='')
    rush_time_offset = Column(Integer, default=0)
    user_agent = Column(String(200), default='')
    webview_ua = Column(String(300), default='')
    mt_r = Column(String(80), default='')
    mt_sn = Column(String(80), default='')
    pay_url = Column(String(500), default='')
    pay_url_wechat = Column(String(500), default='')     # 微信支付链接
    pay_url_alipay = Column(String(500), default='')     # 支付宝支付链接
    pay_status = Column(String(20), default='')
    item_name = Column(String(100), default='')
    item_code = Column(String(20), default='IMTP1000313')
    sku_id = Column(String(20), default='741')
    activity_id = Column(String(20), default='82107')
    amount = Column(Integer, default=1)
    login_time = Column(DateTime, nullable=True)
    uploader_name = Column(String(50), default='')
    task_role = Column(String(10), default='both')    # 任务角色: both=监控+抢购, monitor=仅监控, rush=仅抢购
    account_type = Column(String(10), default='')     # ''=未判断, white=白号, black=黑号
    proxy_ip = Column(String(50), default='')          # 绑定的代理IP socks5://ip:port
    device_key = Column(String(50), default='')        # 绑定的设备机型key (如 xiaomi_13, samsung_s24_ultra)

# ===================== 新模型：用户级隔离表 =====================
class UserConfig(Base):
    """替代 GlobalConfig，每个用户一行，user_id 唯一"""
    __tablename__ = 'user_config'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    rush_hour = Column(Integer, default=8)
    rush_minute = Column(Integer, default=58)
    rush_second = Column(Integer, default=0)
    rush_millisecond = Column(Integer, default=500)
    task_frequency = Column(Integer, default=1)
    rush_attempts = Column(Integer, default=10000)
    rush_count = Column(Integer, default=100)
    multi_open_count = Column(Integer, default=1)
    multi_open_enabled = Column(Boolean, default=False)
    inventory_monitoring = Column(Integer, default=0)
    min_delay = Column(Integer, default=10)
    max_delay = Column(Integer, default=20)
    rush_paused = Column(Integer, default=0)
    interval_mode = Column(Integer, default=0)             # 0=连续抢购 1=每5分钟间隔
    client_windows = Column(Integer, default=10)         # 客户端窗口数（Linux 进程数）
    excluded_teams = Column(String(500), default='')      # 排除的团队，逗号分隔
    excluded_uploaders = Column(String(500), default='')   # 排除的上传者，逗号分隔
    rush_mode = Column(Integer, default=0)                 # 抢购模式: 0=调试/关闭, 1=正式/开启
    phone_multi_open_count = Column(Integer, default=3)   # 手机多开数（只针对手机端）

class UserProxy(Base):
    """IP代理 + 防封策略，每用户独立"""
    __tablename__ = 'user_proxy'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    proxy_enabled = Column(Boolean, default=False)
    proxy_url = Column(String(300), default='')
    anti_ban_429_retry = Column(Integer, default=5)
    anti_ban_429_delay = Column(Integer, default=3)
    anti_ban_bangcle_ttl = Column(Integer, default=300)
    anti_ban_account_cooldown = Column(Integer, default=200)

class TaskAssignment(Base):
    """任务分配记录（持久化）"""
    __tablename__ = 'task_assignment'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    client_uuid = Column(String(64), default='')
    batch = Column(Integer, default=0)
    status = Column(String(20), default='assigned')
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

# ===================== 团队管理模型 =====================
class Team(Base):
    """团队表：主站用户创建的团队，通过 owner_user_id 管理成员"""
    __tablename__ = 'team'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    login_username = Column(String(80), unique=True, nullable=True)    # 可选（旧版兼容）
    password_hash = Column(String(256), nullable=True)                # 可选（旧版兼容）
    owner_user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # 支付方式预留字段
    payment_method = Column(String(50), default='')

class TeamAccount(Base):
    """团队-账号映射表：记录哪些账号分配给了哪个团队"""
    __tablename__ = 'team_account'
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, nullable=False, index=True)
    phone = Column(String(20), nullable=False, index=True)
    owner_user_id = Column(Integer, nullable=False, index=True)
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

# ===================== 设备与窗口密钥注册模型 =====================
class DeviceKey(Base):
    """设备注册表：每台物理机一个唯一密钥
    machine_id = 系统 UUID，重启后通过它识别同一设备"""
    __tablename__ = 'device_keys'
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_key = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(String(128), nullable=False, index=True)
    hostname = Column(String(128), default='')
    last_ip = Column(String(45), default='')
    status = Column(String(16), default='active')
    max_windows = Column(Integer, default=8)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)


class WindowKey(Base):
    """窗口注册表：每台设备下每个窗口一个唯一密钥
    按 (device_key, window_index) 唯一约束"""
    __tablename__ = 'window_keys'
    id = Column(Integer, primary_key=True, autoincrement=True)
    window_key = Column(String(64), unique=True, nullable=False, index=True)
    device_key = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    window_index = Column(Integer, nullable=False, default=0)
    status = Column(String(16), default='active')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    client_uuid = Column(String(64), default='')


class KeySeed(Base):
    """预生成密钥池"""
    __tablename__ = 'key_seeds'
    id = Column(Integer, primary_key=True, autoincrement=True)
    seed_key = Column(String(64), unique=True, nullable=False, index=True)
    key_type = Column(String(16), default='window')
    assigned = Column(Boolean, default=False)
    assigned_to = Column(String(64), default='')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ===================== FastAPI 应用初始化 =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
        print("[启动] 数据库表结构检查完成")
    except Exception as e:
        print(f"[启动] 数据库连接失败: {e}")
        print("[启动] 请检查 MySQL 服务器是否正常运行")
        yield
        return

    # 迁移 phone_record 字段
    try:
        inspector = inspect(engine)
        pr_columns = [col['name'] for col in inspector.get_columns('phone_record')]
        with engine.connect() as conn:
            conn.execute(text('SET SESSION lock_wait_timeout = 1'))
            conn.execute(text('SET SESSION innodb_lock_wait_timeout = 1'))
            phone_migrations = [
                ('user_agent', 'ALTER TABLE phone_record ADD COLUMN user_agent VARCHAR(200) DEFAULT ""'),
                ('webview_ua', 'ALTER TABLE phone_record ADD COLUMN webview_ua VARCHAR(300) DEFAULT ""'),
                ('mt_r', 'ALTER TABLE phone_record ADD COLUMN mt_r VARCHAR(80) DEFAULT ""'),
                ('mt_sn', 'ALTER TABLE phone_record ADD COLUMN mt_sn VARCHAR(80) DEFAULT ""'),
                ('pay_url', 'ALTER TABLE phone_record ADD COLUMN pay_url VARCHAR(500) DEFAULT ""'),
                ('pay_status', 'ALTER TABLE phone_record ADD COLUMN pay_status VARCHAR(20) DEFAULT ""'),
                ('item_code', 'ALTER TABLE phone_record ADD COLUMN item_code VARCHAR(20) DEFAULT "741"'),
                ('amount', 'ALTER TABLE phone_record ADD COLUMN amount INTEGER DEFAULT 1'),
                ('item_name', 'ALTER TABLE phone_record ADD COLUMN item_name VARCHAR(100) DEFAULT ""'),
                ('login_time', 'ALTER TABLE phone_record ADD COLUMN login_time DATETIME'),
                ('sku_id', 'ALTER TABLE phone_record ADD COLUMN sku_id VARCHAR(20) DEFAULT "741"'),
                ('activity_id', 'ALTER TABLE phone_record ADD COLUMN activity_id VARCHAR(20) DEFAULT "82107"'),
                ('uploader_name', 'ALTER TABLE phone_record ADD COLUMN uploader_name VARCHAR(50) DEFAULT ""'),
                ('task_role', 'ALTER TABLE phone_record ADD COLUMN task_role VARCHAR(10) DEFAULT "both"'),
                ('account_type', 'ALTER TABLE phone_record ADD COLUMN account_type VARCHAR(10) DEFAULT ""'),
                ('proxy_ip', 'ALTER TABLE phone_record ADD COLUMN proxy_ip VARCHAR(50) DEFAULT ""'),
                ('pay_url_wechat', 'ALTER TABLE phone_record ADD COLUMN pay_url_wechat VARCHAR(500) DEFAULT ""'),
                ('pay_url_alipay', 'ALTER TABLE phone_record ADD COLUMN pay_url_alipay VARCHAR(500) DEFAULT ""'),
                ('device_key', 'ALTER TABLE phone_record ADD COLUMN device_key VARCHAR(50) DEFAULT ""'),
            ]
            for col_name, alter_sql in phone_migrations:
                if col_name not in pr_columns:
                    try:
                        conn.execute(text(alter_sql))
                    except:
                        pass
    except:
        pass

    # 迁移 user 表字段（App 注册/登录需要）
    try:
        inspector = inspect(engine)
        user_columns = [col['name'] for col in inspector.get_columns('user')]
        with engine.connect() as conn:
            user_migrations = [
                ('phone', 'ALTER TABLE user ADD COLUMN phone VARCHAR(20) UNIQUE'),
                ('failed_logins', 'ALTER TABLE user ADD COLUMN failed_logins INTEGER DEFAULT 0'),
                ('frozen_until', 'ALTER TABLE user ADD COLUMN frozen_until DATETIME'),
                ('daily_failed', 'ALTER TABLE user ADD COLUMN daily_failed INTEGER DEFAULT 0'),
                ('last_failed_date', 'ALTER TABLE user ADD COLUMN last_failed_date DATETIME'),
            ]
            for col_name, alter_sql in user_migrations:
                if col_name not in user_columns:
                    try:
                        conn.execute(text(alter_sql))
                        print(f'[迁移] user 表添加 {col_name} 列')
                    except:
                        pass
    except:
        pass

    # 迁移 user_config 字段
    try:
        inspector = inspect(engine)
        uc_columns = [col['name'] for col in inspector.get_columns('user_config')]
        with engine.connect() as conn:
            uc_migrations = [
                ('excluded_teams', 'ALTER TABLE user_config ADD COLUMN excluded_teams VARCHAR(500) DEFAULT ""'),
                ('excluded_uploaders', 'ALTER TABLE user_config ADD COLUMN excluded_uploaders VARCHAR(500) DEFAULT ""'),
                ('client_windows', 'ALTER TABLE user_config ADD COLUMN client_windows INTEGER DEFAULT 10'),
                ('interval_mode', 'ALTER TABLE user_config ADD COLUMN interval_mode INTEGER DEFAULT 0'),
                ('rush_mode', 'ALTER TABLE user_config ADD COLUMN rush_mode INTEGER DEFAULT 0'),
                ('phone_multi_open_count', 'ALTER TABLE user_config ADD COLUMN phone_multi_open_count INTEGER DEFAULT 3'),
            ]
            for col_name, alter_sql in uc_migrations:
                if col_name not in uc_columns:
                    try:
                        conn.execute(text(alter_sql))
                    except:
                        pass
    except:
        pass

    # 迁移 team / team_account 表
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        with engine.connect() as conn:
            if 'team' not in existing_tables:
                conn.execute(text('''
                    CREATE TABLE team (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        login_username VARCHAR(80) UNIQUE,
                        password_hash VARCHAR(256),
                        owner_user_id INT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        payment_method VARCHAR(50) DEFAULT ""
                    )
                '''))
                conn.commit()
                print('[迁移] team 表创建完成')
            if 'team_account' not in existing_tables:
                conn.execute(text('''
                    CREATE TABLE team_account (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        team_id INT NOT NULL,
                        phone VARCHAR(20) NOT NULL,
                        owner_user_id INT NOT NULL,
                        assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_team_id (team_id),
                        INDEX idx_phone (phone),
                        INDEX idx_owner (owner_user_id)
                    )
                '''))
                conn.commit()
                print('[迁移] team_account 表创建完成')
            if 'team_member' not in existing_tables:
                conn.execute(text('''
                    CREATE TABLE team_member (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        team_id INT NOT NULL,
                        user_id INT NOT NULL,
                        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE INDEX idx_team_member (team_id, user_id)
                    )
                '''))
                conn.commit()
                print('[迁移] team_member 表创建完成')
    except:
        pass

    # 修复已有 team 表：login_username / password_hash 改为可选（新版团队只需名称+成员ID）
    try:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE team MODIFY login_username VARCHAR(80) UNIQUE NULL'))
            conn.execute(text('ALTER TABLE team MODIFY password_hash VARCHAR(256) NULL'))
            conn.commit()
            print('[迁移] team 表 login_username/password_hash 已改为可选')
    except:
        pass

    # 确保 pay_url / pay_url_wechat / pay_url_alipay 列存在
    try:
        with engine.connect() as conn:
            for col, col_type in [
                ('pay_url', 'VARCHAR(500) DEFAULT ""'),
                ('pay_url_wechat', 'VARCHAR(500) DEFAULT ""'),
                ('pay_url_alipay', 'VARCHAR(500) DEFAULT ""'),
                ('pay_status', 'VARCHAR(20) DEFAULT ""'),
            ]:
                try:
                    conn.execute(text(f'ALTER TABLE phone_record ADD COLUMN {col} {col_type}'))
                    conn.commit()
                    print(f'[迁移] phone_record.{col} 列已添加')
                except:
                    pass
    except:
        pass

    # 同步历史 TeamAccount → PhoneRecord.team（前端筛选依赖此字段）
    try:
        with SessionLocal() as sdb:
            all_teams = sdb.query(Team).all()
            sync_count = 0
            for t in all_teams:
                mappings = sdb.query(TeamAccount).filter(TeamAccount.team_id == t.id).all()
                for m in mappings:
                    rec = sdb.query(PhoneRecord).filter(PhoneRecord.phone == m.phone).first()
                    if rec and rec.team != t.name:
                        rec.team = t.name
                        sync_count += 1
            if sync_count > 0:
                sdb.commit()
                print(f'[迁移] 同步 {sync_count} 条 TeamAccount → PhoneRecord.team')
    except:
        pass

    start_background_tasks_async()
    # 启动时不再自动导入 iplala_accounts.json，改为网页手动触发
    # import_accounts_from_json(default_username="admin")
    yield

app = FastAPI(title="猫妈妈自动化系统-FastAPI", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=Config.SECRET_KEY, session_cookie="moutai_session")

# 注册养猫 App API 路由（/api/app/*）
from routes.api_app import router as api_app_router
app.include_router(api_app_router)

# 团队管理 API — 使用 routes/api_teams.py 中的新版路由（基于用户ID，无需登录账号密码）
from routes.api_teams import router as api_teams_router
app.include_router(api_teams_router)

# 注册桥接 API 路由（/api/bridge/*）— 同一进程内 HTTP 桥接，端口 5000
from routes.api_bridge import router as api_bridge_router
app.include_router(api_bridge_router)

# 注册客户端 API 路由（/api/client/* /api/phone/*）— 手机心跳/任务分配
from routes.api_client import router as api_client_router
app.include_router(api_client_router)

TEMPLATES_DIR = os.path.join(BASEDIR, "templates")
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=os.path.join(BASEDIR, "static")), name="static")
from jinja2 import Environment, FileSystemLoader, select_autoescape
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(['html', 'xml']),
    cache_size=0
)
templates = Jinja2Templates(env=jinja_env)

# ===================== 用户认证辅助 =====================
def get_current_user(request: Request, db: SQLSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return user

def login_user_fastapi(request: Request, user: User):
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["permanent"] = True

def logout_user_fastapi(request: Request):
    request.session.clear()
    # 确保 cookie 也被标记为过期，避免残留
    request.session["user_id"] = None
    request.session["username"] = None

# ===================== 辅助函数 =====================
def get_user_config(user_id: int, db: SQLSession):
    """获取用户专属配置（不存在则自动创建默认行）"""
    import time as _time
    try:
        db.execute(text('SET SESSION lock_wait_timeout = 1'))
        db.execute(text('SET SESSION innodb_lock_wait_timeout = 1'))
    except:
        pass
    max_retries = 10
    for attempt in range(max_retries):
        try:
            cfg = db.query(UserConfig).filter(UserConfig.user_id == user_id).first()
            if not cfg:
                cfg = UserConfig(user_id=user_id)
                db.add(cfg)
                db.commit()
            return cfg
        except OperationalError as e:
            if '1205' in str(e) and attempt < max_retries - 1:
                db.rollback()
                _time.sleep(0.1)
            else:
                db.rollback()
                return UserConfig(user_id=user_id)
    return UserConfig(user_id=user_id)


def get_user_proxy(user_id: int, db: SQLSession):
    """获取用户专属代理配置（不存在则自动创建）"""
    try:
        up = db.query(UserProxy).filter(UserProxy.user_id == user_id).first()
        if not up:
            up = UserProxy(user_id=user_id)
            db.add(up)
            db.commit()
        return up
    except:
        return UserProxy(user_id=user_id)


    # 已删除 get_global_config，统一使用 get_user_config(1, db)
# ===================== 代理池管理器 =====================
import threading as _threading
import requests as _requests
import urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ProxyManager:
    """豌豆代理池管理：获取、分配、回收、丢弃代理IP
    维护两个IP池：
    - _pool: 原始未测试IP池（从豌豆API获取后直接放入）
    - _ready_pool: 就绪池（已通过桥接测试确认可用的IP，直接下发无需再验证）
    """
    def __init__(self):
        self._pool = []           # 原始未测试IP池
        self._ready_pool = []     # 就绪池：已测试确认可用的IP
        self._discarded = set()
        self._lock = _threading.Lock()
        self._last_fetch_time = 0
        self._fetch_interval = 60
        self._ready_pool_min = 10  # 就绪池最低阈值（少于10个自动补充）

    def fetch_proxies(self, api_url: str, count: int = 20) -> list:
        """从豌豆API获取代理IP，api_url 为用户配置的完整API地址"""
        if not api_url:
            print('[代理池] 未配置代理API地址')
            return []
        now = time.time()
        with self._lock:
            if now - self._last_fetch_time < self._fetch_interval and self._pool:
                return self._pool
            self._last_fetch_time = now
        try:
            # 用户填的是完整URL，如果URL中已有num参数则不重复追加
            import urllib.parse
            parsed = urllib.parse.urlparse(api_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            if 'num' in query_params:
                url = api_url
            else:
                sep = '&' if '?' in api_url else '?'
                url = f"{api_url}{sep}num={count}"
            resp = _requests.get(url, timeout=10, verify=False)
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
                print(f'[代理池] 获取到 {len(new_proxies)} 个新代理 | 当前池大小: {len(self._pool)}')
                return new_proxies
            else:
                msg = data.get('msg', '未知错误')
                if 'LACK' in str(msg).upper() or 'POOL' in str(msg).upper():
                    print(f"[代理池] 暂无可用IP({msg})，30秒后重试")
                    with self._lock:
                        self._last_fetch_time = now - self._fetch_interval + 30
                else:
                    print(f'[代理池] API返回异常 | 错误: {msg}')
                return []
        except Exception as e:
            print(f"[代理池] 获取代理失败: {e}")
            return []

    def get_proxy(self, api_url: str = '') -> str:
        with self._lock:
            if self._pool:
                return self._pool.pop(0)
        self.fetch_proxies(api_url, 20)
        with self._lock:
            if self._pool:
                return self._pool.pop(0)
        return ''

    def return_proxy(self, proxy: str):
        if proxy and proxy not in self._discarded:
            with self._lock:
                self._pool.append(proxy)

    def discard_proxy(self, proxy: str):
        if proxy:
            with self._lock:
                self._discarded.add(proxy)
                self._pool = [p for p in self._pool if p != proxy]

    def pool_size(self) -> int:
        with self._lock:
            return len(self._pool)

    def all_discarded(self) -> set:
        """返回所有已丢弃的IP"""
        with self._lock:
            return set(self._discarded)

    def get_ready_proxy(self) -> str:
        """从就绪池取出一个已测试IP（无需再验证，立即返回）"""
        with self._lock:
            if self._ready_pool:
                ip = self._ready_pool.pop(0)
                self._pool = [p for p in self._pool if p != ip]
                return ip
        return ''

    def add_ready_proxy(self, proxy: str):
        """将已测试通过的IP加入就绪池"""
        if proxy and proxy not in self._discarded:
            with self._lock:
                if proxy not in self._ready_pool:
                    self._ready_pool.append(proxy)

    def ready_pool_size(self) -> int:
        with self._lock:
            return len(self._ready_pool)

    def ready_pool_need_refill(self) -> bool:
        """检查是否需要补充就绪池"""
        with self._lock:
            return len(self._ready_pool) < self._ready_pool_min

    def total_pool_size(self) -> int:
        """返回所有可用IP总数（原始池+就绪池）"""
        with self._lock:
            return len(self._pool) + len(self._ready_pool)

proxy_manager = ProxyManager()

def build_credentials_from_db(phone: str, db: SQLSession) -> dict:
    """
    从数据库构建凭证字典(替代 build_client_from_record)
    返回的 dict 可直接传给 BridgeClient 方法或 /api/bridge/execute
    """
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        raise ValueError(f"手机号 {phone} 不存在")
    return {
        'phone': phone,
        'raw_device_id': record.raw_device_id or '',
        'mt_device_id': record.mt_device_id or '',
        'token': record.token or '',
        'cookie': record.cookie or '',
        'user_id_ext': record.user_id_ext or '',
        'h5_did': record.h5_did or '',
        'h5_start_id': record.h5_start_id or '',
        'bs_device_id': record.bs_device_id or '',
        'user_agent': record.user_agent or '',
        'webview_ua': record.webview_ua or '',
        'mt_r': record.mt_r or '',
        'mt_sn': record.mt_sn or '',
    }

async def check_login_validity_async(phone: str, proxy_url: str = '') -> Optional[bool]:
    """通过桥接异步检查登录状态。返回 True=有效, False=无效, None=桥接不可达"""
    with SessionLocal() as db:
        try:
            creds = build_credentials_from_db(phone, db)
        except:
            return False
    return await _bridge.check_login(creds, proxy_url=proxy_url)

def update_login_status(phone: str, is_valid: bool, db: SQLSession):
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record:
        if is_valid:
            record.logged_in = True
        else:
            record.logged_in = False
            # 不删除 token/cookie/user_id_ext — 验证失败可能是暂时的（IP被封/限流/网络抖动），
            # 清空会导致下次又从 JSON 恢复 → 再次验证失败 → 再次清空的死循环
            # record.token = ""
            # record.cookie = ""
            # record.user_id_ext = ""
        record.last_updated = datetime.datetime.utcnow()
        db.commit()

async def send_verification_code_impl_async(phone: str, db: SQLSession) -> bool:
    """异步发送验证码（通过桥接）"""
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and record.logged_in:
        print(f"[发送验证码] {phone} 已登录，跳过发送")
        return False
    # 新号码（无凭证）使用空字典，main.py 的 demo 会自动生成设备信息
    try:
        creds = build_credentials_from_db(phone, db)
    except ValueError:
        creds = {}
    success = await _bridge.send_vcode(phone, creds)
    if success and record:
        record.code_sent = True
        record.last_updated = datetime.datetime.utcnow()
        db.commit()
    return success

def save_account_to_json_from_creds(phone: str, credentials: dict, uploader_name: str = "admin"):
    """将凭证保存到 {uploader_name}_accounts.json（按上传者分文件存储）"""
    accounts_file = os.path.join(BASEDIR, f'{uploader_name}_accounts.json')
    accounts = []
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
    idx = next((i for i, acc in enumerate(accounts) if acc.get("mobile") == phone), -1)
    acc_data = {
        "mobile": phone,
        "userid": credentials.get('user_id_ext', ''),
        "token": credentials.get('token', ''),
        "cookie": credentials.get('cookie', ''),
        "mt-device-id": credentials.get('mt_device_id', ''),
        "device-id": credentials.get('raw_device_id', ''),
        "user-agent": credentials.get('user_agent', ''),
        "webview-ua": credentials.get('webview_ua', ''),
        "mt-r": credentials.get('mt_r', ''),
        "mt-sn": credentials.get('mt_sn', ''),
        "h5-did": credentials.get('h5_did', ''),
        "h5-start-id": credentials.get('h5_start_id', ''),
        "bs-device-id": credentials.get('bs_device_id', ''),
        "loginTime": datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    }
    if idx >= 0:
        accounts[idx] = {**accounts[idx], **acc_data}
    else:
        accounts.append(acc_data)
    with open(accounts_file, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def sync_login_time_from_json(phone, db: SQLSession):
    """从数据库中读取 uploader_name，再定位对应的 {uploader}_accounts.json"""
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return
    uploader_name = record.uploader_name or "admin"
    accounts_file = os.path.join(BASEDIR, f'{uploader_name}_accounts.json')
    if not os.path.exists(accounts_file):
        # 兼容旧版
        legacy_file = os.path.join(BASEDIR, 'iplala_accounts.json')
        if os.path.exists(legacy_file):
            accounts_file = legacy_file
        else:
            return
    try:
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
        acc = next((a for a in accounts if a.get("mobile") == phone), None)
        if not acc or not acc.get("loginTime"):
            return
        login_time = datetime.datetime.strptime(acc["loginTime"], "%Y/%m/%d %H:%M:%S")
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        if record:
            record.login_time = login_time
            db.commit()
    except:
        pass

def _get_login_status_desc(phone: str, valid: bool, db: SQLSession) -> str:
    if valid:
        return 'success'
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and (record.token or record.cookie):
        return 'offline'
    uploader_name = record.uploader_name if record else "admin"
    accounts_file = os.path.join(BASEDIR, f'{uploader_name}_accounts.json')
    try:
        if os.path.exists(accounts_file):
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
            if any(a.get('mobile') == phone for a in accounts):
                return 'offline'
    except:
        pass
    # 兼容旧版 iplala_accounts.json
    legacy_file = os.path.join(BASEDIR, 'iplala_accounts.json')
    try:
        if os.path.exists(legacy_file):
            with open(legacy_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
            if any(a.get('mobile') == phone for a in accounts):
                return 'offline'
    except:
        pass
    return 'never'

# ===================== 代理IP自动测试与净化 =====================

async def _test_proxy_ip(proxy_url: str, timeout: float = 8.0) -> dict:
    """测试代理IP是否可用（通过桥接请求i茅台API）"""
    if not proxy_url:
        return {'ok': False, 'reason': '无代理'}
    result = await _bridge._post('/api/bridge/test_proxy', {
        'proxy_url': proxy_url, 'timeout': timeout
    })
    return result if isinstance(result, dict) else {'ok': False, 'reason': '桥接异常'}


async def _test_and_assign_ip(uploader_id: int, proxy_api_url: str, db: SQLSession,
                               max_retries: int = 5) -> str:
    """
    分配可用代理IP。优先从就绪池直取（已测试，无需再验证）。
    就绪池空时回退到现场测试逻辑。返回 socks5://... 或空字符串。
    """
    # 优先从就绪池取已测试IP（无需再验证，立即返回）
    ready_ip = proxy_manager.get_ready_proxy()
    if ready_ip:
        print(f'[IP分配] ⚡就绪池直取: {ready_ip} | 就绪池剩余: {proxy_manager.ready_pool_size()}')
        return ready_ip

    # 就绪池为空，回退到现场取IP+测试逻辑
    for attempt in range(max_retries):
        proxy_ip = proxy_manager.get_proxy(proxy_api_url)
        if not proxy_ip:
            proxy_manager.fetch_proxies(proxy_api_url, 20)
            proxy_ip = proxy_manager.get_proxy(proxy_api_url)
        if not proxy_ip:
            print(f'[IP分配] 代理池已空，无法分配IP')
            return ''
        test = await _test_proxy_ip(proxy_ip, timeout=6.0)
        if test.get('ok'):
            print(f'[IP分配] ✓ IP可用(现场测试): {proxy_ip}')
            return proxy_ip
        print(f'[IP分配] ✗ IP不可用: {proxy_ip}，丢弃重试({attempt+1}/{max_retries})')
        proxy_manager.discard_proxy(proxy_ip)
    return ''


async def _purge_all_dead_ips(db: SQLSession = None):
    """后台任务：遍历数据库中所有代理IP，逐个测试并淘汰不可用IP"""
    print('[代理净化] 开始扫描所有代理IP...')
    if db is None:
        db = SessionLocal()
        own_db = True
    else:
        own_db = False
    try:
        records = db.query(PhoneRecord).filter(
            PhoneRecord.proxy_ip != '',
            PhoneRecord.logged_in == True
        ).all()
        # 按IP去重（多个账号可能共用同一IP）
        seen_ips = set()
        dead_ips = set()
        alive_ips = set()
        for r in records:
            ip = r.proxy_ip
            if not ip or ip in seen_ips:
                continue
            seen_ips.add(ip)
            test = await _test_proxy_ip(ip, timeout=5.0)
            if test.get('ok'):
                alive_ips.add(ip)
            else:
                dead_ips.add(ip)
                print(f'[代理净化] 淘汰: {ip} ({test.get("reason")})')
            await asyncio.sleep(0.5)  # 请求间短暂间隔
        # 清理死IP：从数据库和代理池中移除
        if dead_ips:
            for ip in dead_ips:
                proxy_manager.discard_proxy(ip)
                # 清除对应记录的 proxy_ip
                db.query(PhoneRecord).filter(PhoneRecord.proxy_ip == ip).update(
                    {'proxy_ip': ''}, synchronize_session=False)
            db.commit()
            print(f'[代理净化] 完成: 淘汰{len(dead_ips)}个, 存活{len(alive_ips)}个, 总扫描{len(seen_ips)}个')
        else:
            print(f'[代理净化] 完成: 全部{len(seen_ips)}个IP正常')
    except Exception as e:
        print(f'[代理净化] 异常: {e}')
        if own_db:
            try:
                db.rollback()
            except:
                pass
    finally:
        if own_db:
            db.close()


async def _proxy_purge_scheduler():
    """代理净化后台调度器：每30分钟自动执行一次（代理关闭时跳过）"""
    await asyncio.sleep(120)  # 启动2分钟后首次执行
    while True:
        try:
            with SessionLocal() as db:
                up = get_user_proxy(1, db)
                if up and up.proxy_enabled:
                    await _purge_all_dead_ips()
        except Exception as e:
            print(f'[代理净化调度] 异常: {e}')
        await asyncio.sleep(1800)  # 每30分钟一次


async def _account_pre_detect_scheduler():
    """账号类型预检测调度器：每10分钟扫描未判定账号，自动测试判定白号/黑号"""
    await asyncio.sleep(60)  # 启动1分钟后首次执行
    while True:
        try:
            with SessionLocal() as db:
                # 扫描已登录但未判定类型的账号
                undetected = db.query(PhoneRecord).filter(
                    PhoneRecord.logged_in == True,
                    (PhoneRecord.account_type == '') | (PhoneRecord.account_type == None)
                ).limit(50).all()  # 每次最多处理50个
                if undetected:
                    print(f'[账号预检] 发现 {len(undetected)} 个未判定账号，开始检测...')
                    detected = 0
                    for rec in undetected:
                        try:
                            creds = build_credentials_from_db(rec.phone, db)
                            item_code = rec.item_code or 'IMTP1000313'
                            # 先获取商品详情
                            detail_result = await _bridge._post('/api/bridge/execute', {
                                'method': 'auto_fetch_item_details',
                                'params': {'item_code': item_code, 'spu_id': item_code},
                                'credentials': creds,
                                'proxy_url': rec.proxy_ip or ''
                            })
                            if detail_result.get('success'):
                                d = detail_result.get('result', {})
                                sku_id = d.get('default_sku_id', '741')
                                item_code_rush = d.get('item_code_from_api', '1001017')
                                act_id = d.get('activity_id', '82107')
                            else:
                                sku_id = '741'; item_code_rush = '1001017'; act_id = '82107'
                            # 测试下单判定黑白
                            rush_result = await _bridge._post('/api/bridge/execute', {
                                'method': 'rush_purchase',
                                'params': {'item_code': item_code_rush, 'sku_id': sku_id, 'item_priority_act_id': act_id, 'amount': '1'},
                                'credentials': creds,
                                'proxy_url': rec.proxy_ip or ''
                            })
                            if rush_result.get('success'):
                                rush_data = rush_result.get('result', {})
                                r_code = rush_data.get('code')
                                r_msg = rush_data.get('message', '')
                                if r_code in (4031, 4099) or '请求人数过多' in r_msg or '库存不足' in r_msg:
                                    rec.account_type = 'black'
                                    print(f'[账号预检] {rec.phone} → 黑号')
                                    detected += 1
                                elif r_code in (4293,) or '人数较多' in r_msg or '活动未开始' in r_msg or '未开始' in r_msg:
                                    rec.account_type = 'white'
                                    print(f'[账号预检] {rec.phone} → 白号')
                                    detected += 1
                            await asyncio.sleep(0.3)  # 请求间隔
                        except Exception as e:
                            print(f'[账号预检] {rec.phone} 检测异常: {e}')
                            await asyncio.sleep(0.5)
                    if detected > 0:
                        db.commit()
                        print(f'[账号预检] 本轮完成: 判定 {detected}/{len(undetected)} 个')
                else:
                    print(f'[账号预检] 无待判定账号')
        except Exception as e:
            print(f'[账号预检] 调度异常: {e}')
        await asyncio.sleep(600)  # 每10分钟一次


async def _ready_pool_refill(proxy_api_url: str):
    """
    就绪池补充：从原始池取未测试IP，通过桥接测试后移入就绪池。
    当原始池有IP时自动测试补充；原始池=0时输出无可用IP日志。
    """
    raw_count = proxy_manager.pool_size()
    if raw_count == 0:
        # 原始池为空，尝试从API拉取
        if proxy_api_url:
            proxy_manager.fetch_proxies(proxy_api_url, 20)
            raw_count = proxy_manager.pool_size()
        if raw_count == 0:
            print(f'[就绪池] 原始池和API均无可用IP！总池=0，无法补充')
            return 0

    ready_before = proxy_manager.ready_pool_size()
    need = max(0, proxy_manager._ready_pool_min - ready_before)
    # 每次最多测试 need+5 个（留余量）
    max_test = min(need + 5, raw_count)

    refilled = 0
    for i in range(max_test):
        raw_ip = proxy_manager.get_proxy(proxy_api_url)
        if not raw_ip:
            break
        test = await _test_proxy_ip(raw_ip, timeout=6.0)
        if test.get('ok'):
            proxy_manager.add_ready_proxy(raw_ip)
            refilled += 1
        else:
            proxy_manager.discard_proxy(raw_ip)
        await asyncio.sleep(0.3)

    ready_after = proxy_manager.ready_pool_size()
    if refilled > 0:
        print(f'[就绪池] 补充 {refilled} 个IP | 就绪池: {ready_before}→{ready_after} | 原始池剩余: {proxy_manager.pool_size()}')
    else:
        print(f'[就绪池] 本轮测试{max_test}个均不可用 | 就绪池: {ready_after} | 原始池: {proxy_manager.pool_size()}')
    return refilled


async def _ready_pool_refill_scheduler():
    """
    就绪池补充调度器：保持就绪池 >= 10 个已测试IP。
    每30秒检查一次，就绪池不足时自动补充。
    """
    await asyncio.sleep(25)  # 启动25秒后首次执行（让其他服务先初始化）
    while True:
        try:
            with SessionLocal() as db:
                up = get_user_proxy(1, db)  # admin用户代理配置
                proxy_enabled = up.proxy_enabled if up else False
                proxy_api_url = up.proxy_url if up else ''
            if not proxy_enabled:
                pass  # 代理关闭，跳过所有就绪池操作
            elif proxy_manager.ready_pool_need_refill():
                if proxy_api_url:
                    raw = proxy_manager.pool_size()
                    ready = proxy_manager.ready_pool_size()
                    print(f'[就绪池调度] 触发补充 | 就绪池: {ready} | 原始池: {raw}')
                    await _ready_pool_refill(proxy_api_url)
                else:
                    print(f'[就绪池调度] 未配置代理API，跳过补充')
        except Exception as e:
            print(f'[就绪池调度] 异常: {e}')
        await asyncio.sleep(30)  # 每30秒检查一次


# ===================== 异步后台任务 =====================
_background_tasks = []  # 存储 asyncio.Task 引用

async def async_login_keepalive_worker():
    """异步登录保鲜 - 通过桥接检查"""
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour >= 22 or now.hour < 6:
                next_refresh = now.replace(hour=6, minute=0, second=0, microsecond=0)
                if now.hour >= 22:
                    next_refresh += datetime.timedelta(days=1)
                sleep_seconds = (next_refresh - now).total_seconds()
                print(f"[保鲜] 夜间休息（22:00-6:00），睡眠 {sleep_seconds/3600:.1f} 小时")
                await asyncio.sleep(sleep_seconds)
                continue
            sleep_seconds = random.randint(600, 2900)
            await asyncio.sleep(sleep_seconds)
            with SessionLocal() as db:
                records = db.query(PhoneRecord).all()
                for rec in records:
                    if not rec.logged_in:
                        continue
                    valid = await check_login_validity_async(rec.phone)
                    if valid is None:
                        continue  # 桥接不可达，跳过
                    if not valid:
                        print(f"[保鲜] {rec.phone} 登录已失效")
                        update_login_status(rec.phone, False, db)
                    else:
                        rec.last_updated = datetime.datetime.utcnow()
                        db.commit()
        except:
            await asyncio.sleep(60)

async def async_inventory_monitoring_worker():
    """
    异步库存监控 - 50ms 轮询，每次只检查1个账号
    遵循需求：每50ms只选取1个账号去请求库存接口，轮询分配
    """
    global stock_monitoring_active, is_stock_available, inventory_broadcast_status
    account_index = 0
    while stock_monitoring_active:
        try:
            now = datetime.datetime.now()
            if now.hour >= INVENTORY_MONITORING_END_HOUR:
                stock_monitoring_active = False
                with SessionLocal() as db:
                    cfg = get_user_config(1, db)  # admin 的配置
                    if cfg:
                        cfg.inventory_monitoring = 0
                        db.commit()
                break
            with SessionLocal() as db:
                all_logged_in = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
                if not all_logged_in:
                    await asyncio.sleep(5)
                    continue
                num = len(all_logged_in)
                if num == 0:
                    await asyncio.sleep(5)
                    continue
                # 轮询分配：每次只检查1个账号，50ms间隔
                idx = account_index % num
                account_index += 1
                rec = all_logged_in[idx]
                creds = build_credentials_from_db(rec.phone, db)
                item_code = rec.item_code if rec.item_code else '741'
                available = await _bridge.check_inventory(rec.phone, item_code, creds)
                if available > 0:
                    is_stock_available = True
                    inventory_broadcast_status = 'available'
                    print(f'[库存监控] {rec.phone} 发现库存: {available}')
                    # 通知所有客户端
                    await broadcast_inventory_status('available')
            await asyncio.sleep(0.05)  # 50ms 间隔
        except:
            await asyncio.sleep(0.05)

async def broadcast_inventory_status(status: str):
    """树状广播库存状态到所有已注册客户端"""
    global inventory_broadcast_status
    inventory_broadcast_status = status
    async with broadcast_tree_lock:
        client_ids = list(broadcast_clients.keys())
    if not client_ids:
        return
    # 树状扩散：先通知10个，每个再通知10个...
    await _tree_broadcast(client_ids, status, 0, 10)

async def _tree_broadcast(client_ids: list, status: str, start_idx: int, fanout: int):
    """树状广播扩散"""
    end_idx = min(start_idx + fanout, len(client_ids))
    batch = client_ids[start_idx:end_idx]
    tasks = []
    for cid in batch:
        info = broadcast_clients.get(cid)
        if not info:
            continue
        url = info.get('callback_url', '')
        if url:
            tasks.append(_notify_single_client(url, status))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    # 递归通知下一层
    if end_idx < len(client_ids):
        await _tree_broadcast(client_ids, status, end_idx, fanout * 10)

async def _notify_single_client(url: str, status: str):
    """通知单个客户端"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={'status': status, 'type': 'inventory_broadcast'},
                headers={'X-API-TOKEN': Config.API_TOKEN})
    except:
        pass

def start_background_tasks_async():
    """启动所有异步后台任务"""
    global _background_tasks
    _background_tasks.append(asyncio.create_task(async_login_keepalive_worker()))
    _background_tasks.append(asyncio.create_task(_proxy_purge_scheduler()))
    _background_tasks.append(asyncio.create_task(_account_pre_detect_scheduler()))
    _background_tasks.append(asyncio.create_task(_ready_pool_refill_scheduler()))
    # 库存监控默认不启动，用户可在设置页面手动开启

# ===================== 健康检查 =====================
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "time": datetime.datetime.now().isoformat()}

# ===================== 页面路由 =====================
@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    flash_messages = request.session.pop("_flash", [])
    # 兼容 session 丢失，从 query 参数读取错误标记
    if request.query_params.get("error") == "1" and not flash_messages:
        flash_messages = [("error", "用户名或密码错误")]
    if request.query_params.get("conflict") == "1" and not flash_messages:
        expected = request.query_params.get("expected", "")
        flash_messages = [("error", f"检测到跨账号会话冲突：当前标签页属于「{expected}」，但 Session 已被其他标签页覆盖。请重新登录。")]
    user_id = request.session.get("user_id")
    user = None
    if user_id:
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse(request, "login.html", {
        "user": user, "flash_messages": flash_messages
    })

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request):
    form = await request.form()
    username = form.get('username', '').strip()
    password = form.get('password', '').strip()
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user_fastapi(request, user)
            return RedirectResponse(url=f"/dashboard?login=ok&user={user.username}", status_code=303)
        else:
            request.session["_flash"] = [("error", "用户名或密码错误")]
            return RedirectResponse(url="/login?error=1", status_code=303)

@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    flash_messages = request.session.pop("_flash", [])
    return templates.TemplateResponse(request, "register.html", {"flash_messages": flash_messages})

@app.post("/register", response_class=HTMLResponse)
async def register_post(request: Request):
    form = await request.form()
    username = form.get('username', '').strip()
    password = form.get('password', '').strip()
    if not username or not password:
        request.session["_flash"] = [("error", "用户名和密码不能为空")]
        return RedirectResponse(url="/register", status_code=302)
    with SessionLocal() as db:
        if db.query(User).filter(User.username == username).first():
            request.session["_flash"] = [("error", "用户名已存在")]
            return RedirectResponse(url="/register", status_code=302)
        user = User(username=username, password_hash=generate_password_hash(password))
        db.add(user)
        db.commit()
    request.session["_flash"] = [("success", "注册成功，请登录")]
    return RedirectResponse(url="/login", status_code=302)

@app.get("/logout")
async def logout(request: Request):
    logout_user_fastapi(request)
    return RedirectResponse(url="/login")

# ===================== 养猫 App API（Bearer Token 认证） =====================
_app_token_store: dict = {}  # token -> user_id

def _issue_app_token(user_id: int) -> str:
    token = _uuid.uuid4().hex
    _app_token_store[token] = user_id
    return token

def _get_app_user(
    request: Request,
    db: SQLSession = Depends(get_db),
):
    """Bearer Token 认证，用于 /api/app/* 接口"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供令牌")
    token = auth[7:]
    user_id = _app_token_store.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user

# ══════════════════════════════════════════════════════════
# /api/app/register 和 /api/app/login 已迁移至 routes/api_app.py
# 通过 app.include_router(api_app_router) 注册
# ══════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    # ===== 多用户会话隔离防护 =====
    # 同一个浏览器多标签页登录不同账号时，后登录的会覆盖前者的 Session Cookie，
    # 导致前者的页面刷新后读取到后者身份。此处比对 URL 中的 user 参数与
    # Session 中的 username，若不匹配则清除 Session 并强制重新登录。
    url_user = request.query_params.get('user', '').strip()
    session_user = request.session.get('username', '')
    if url_user and session_user and url_user != session_user:
        # Session 被其他标签页覆盖，清除并跳转到登录页
        request.session.clear()
        flash_msg = f"检测到跨账号会话冲突：URL 身份为「{url_user}」但 Session 已被「{session_user}」覆盖。请重新登录。"
        request.session["_flash"] = [("error", flash_msg)]
        return RedirectResponse(url="/login", status_code=303)
    # 若 Session 存在但 URL 未携带 user 参数，自动补充（兼容旧链接）
    if not url_user and session_user:
        return RedirectResponse(url=f"/dashboard?user={session_user}", status_code=303)
    # ===== 原有逻辑 =====
    if user.username.lower() == "admin":
        records = db.query(PhoneRecord).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    flash_messages = request.session.pop("_flash", [])
    # 兼容部分浏览器 session 丢失，优先从 query 参数生成 flash
    if request.query_params.get("login") == "ok" and not flash_messages:
        flash_messages = [("success", "登录成功")]
    records_with_uploaders = []
    for rec in records:
        uploader = db.query(User).filter(User.id == rec.uploaded_by).first()
        records_with_uploaders.append({
            'record': rec,
            'uploader_username': uploader.username if uploader else '未知'
        })
    # 获取当前用户的团队列表，供前端下拉选择
    if user.username.lower() == "admin":
        teams = db.query(Team).all()
    else:
        teams = db.query(Team).filter(Team.owner_user_id == user.id).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "records_with_uploaders": records_with_uploaders,
        "teams": teams,
        "User": User,
        "now": datetime.datetime.now,
        "flash_messages": flash_messages
    })

# ===================== API：当前用户身份（前端会话校验） =====================
@app.get("/api/whoami")
async def whoami(request: Request, db: SQLSession = Depends(get_db)):
    """返回当前 Session 中的用户身份，供前端定期校验 URL 与 Session 是否一致"""
    user_id = request.session.get("user_id")
    username = request.session.get("username", "")
    if not user_id:
        return JSONResponse(content={"logged_in": False, "username": ""})
    return JSONResponse(content={"logged_in": True, "user_id": user_id, "username": username})

# ===================== 绑定账号页面（公开） =====================
@app.get("/bind_account", response_class=HTMLResponse)
async def bind_account(request: Request, uploader: str = ""):
    flash_messages = request.session.pop("_flash", [])
    user = None
    user_id = request.session.get("user_id")
    if user_id:
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse(request, "bind_account.html", {
        "user": user, "uploader": uploader, "flash_messages": flash_messages
    })

# ===================== API：绑定账号（公开） =====================
@app.post("/api/bind_account/send_code")
async def bind_account_send_code(request: Request, db: SQLSession = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    uploader = data.get('uploader', '').strip()
    if not phone or len(phone) != 11:
        return JSONResponse(content={'status': 'error', 'message': '手机号格式无效'}, status_code=400)
    existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if existing and existing.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '该手机号已被绑定'}, status_code=400)
    # 根据上传者名称查找用户ID，找不到则归 admin
    uploader_user = db.query(User).filter(User.username == uploader).first() if uploader else None
    if not uploader_user:
        uploader_user = db.query(User).filter(User.username == "admin").first()
    uploader_id = uploader_user.id if uploader_user else 1
    # 新号码不存在时先创建记录，再发验证码
    if not existing:
        existing = PhoneRecord(team='', phone=phone, user_id=uploader_id, uploaded_by=uploader_id,
            uploader_name=uploader, item_name='茅台飞天53度 500ml', item_code='IMTP1000313', sku_id='741',
            activity_id='82143', amount=2)
        db.add(existing)
        db.commit()
        db.refresh(existing)
    success = await send_verification_code_impl_async(phone, db)
    if success:
        return JSONResponse(content={'status': 'success', 'message': '验证码已发送'})
    else:
        return JSONResponse(content={'status': 'error', 'message': '发送失败'}, status_code=400)

@app.post("/api/bind_account/submit_code")
async def bind_account_submit_code(request: Request, db: SQLSession = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    item_code = data.get('item_code', 'IMTP1000313')
    item_name = data.get('item_name', '茅台飞天53度 500ml')
    sku_id = data.get('sku_id', '741')
    activity_id = data.get('activity_id', '82143')
    amount = data.get('amount', 2)
    uploader = data.get('uploader', '').strip()
    if not phone or len(phone) != 11:
        return JSONResponse(content={'status': 'error', 'message': '手机号格式无效'}, status_code=400)
    if not code:
        return JSONResponse(content={'status': 'error', 'message': '验证码不能为空'}, status_code=400)
    # 根据上传者名称查找用户ID，找不到则归 admin
    uploader_user = db.query(User).filter(User.username == uploader).first() if uploader else None
    if not uploader_user:
        uploader_user = db.query(User).filter(User.username == "admin").first()
    uploader_id = uploader_user.id if uploader_user else 1
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and record.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '该手机号已登录'}, status_code=400)
    if not record:
        record = PhoneRecord(team='', phone=phone, user_id=uploader_id, uploaded_by=uploader_id,
            uploader_name=uploader, item_name=item_name, item_code=item_code, sku_id=sku_id,
            activity_id=activity_id, amount=amount)
        db.add(record)
        db.commit()
    else:
        record.item_name = item_name; record.item_code = item_code; record.sku_id = sku_id
        record.activity_id = activity_id; record.amount = amount
        record.uploader_name = uploader
        record.uploaded_by = uploader_id; record.user_id = uploader_id
        db.commit()
    creds = build_credentials_from_db(phone, db)
    login_result = await _bridge.login(phone, code, creds)
    if login_result.get('error'):
        return JSONResponse(content={'status': 'error', 'message': f'登录失败: {login_result["error"]}'}, status_code=400)
    record.token = login_result.get('token', ''); record.cookie = login_result.get('cookie', '')
    record.user_id_ext = login_result.get('user_id_ext', ''); record.logged_in = True
    record.last_updated = datetime.datetime.utcnow()
    record.login_time = datetime.datetime.now()
    db.commit()
    save_account_to_json_from_creds(phone, login_result, uploader or "admin")
    # 绑定成功后立即检测白号/黑号
    account_type_msg = ''
    try:
        creds = build_credentials_from_db(phone, db)
        item_code = record.item_code or 'IMTP1000313'
        detail_result = await _bridge._post('/api/bridge/execute', {
            'method': 'auto_fetch_item_details',
            'params': {'item_code': item_code, 'spu_id': item_code},
            'credentials': creds
        })
        if detail_result.get('success'):
            d = detail_result.get('result', {})
            sku_id = d.get('default_sku_id', '741')
            item_code_rush = d.get('item_code_from_api', '1001017')
            act_id = d.get('activity_id', '82107')
        else:
            sku_id = '741'; item_code_rush = '1001017'; act_id = '82107'
        rush_result = await _bridge._post('/api/bridge/execute', {
            'method': 'rush_purchase',
            'params': {'item_code': item_code_rush, 'sku_id': sku_id, 'item_priority_act_id': act_id, 'amount': '1'},
            'credentials': creds
        })
        if rush_result.get('success'):
            rush_data = rush_result.get('result', {})
            r_code = rush_data.get('code')
            r_msg = rush_data.get('message', '')
            if r_code == 2000:
                pass  # 抢购成功，不判断
            elif r_code in (4031, 4099) or '请求人数过多' in r_msg or '库存不足' in r_msg:
                record.account_type = 'black'
                account_type_msg = '（黑号）'
            elif r_code in (4293,) or '人数较多' in r_msg or '活动未开始' in r_msg or '未开始' in r_msg:
                record.account_type = 'white'
                account_type_msg = '（白号）'
            db.commit()
    except Exception as e:
        print(f'[绑定检测] {phone} 白号/黑号检测失败: {e}')
    return JSONResponse(content={'status': 'success', 'message': f'绑定成功{account_type_msg}', 'account_type': record.account_type})

@app.get("/api/bind_account/list")
async def bind_account_list(request: Request, db: SQLSession = Depends(get_db)):
    """获取指定上传者的账号列表（公开API，需通过uploader参数指定）"""
    uploader = request.query_params.get('uploader', '').strip()
    if not uploader:
        return JSONResponse(content={'records': []})
    uploader_user = db.query(User).filter(User.username == uploader).first()
    if not uploader_user:
        return JSONResponse(content={'records': []})
    records = db.query(PhoneRecord).filter(
        PhoneRecord.user_id == uploader_user.id
    ).order_by(PhoneRecord.last_updated.desc()).limit(100).all()
    record_list = []
    for rec in records:
        login_time_str = rec.login_time.strftime('%Y-%m-%d %H:%M:%S') if rec.login_time else None
        record_list.append({
            'phone': rec.phone, 'logged_in': rec.logged_in, 'token': bool(rec.token),
            'item_code': rec.item_code or 'IMTP1000313', 'sku_id': rec.sku_id or '741',
            'activity_id': rec.activity_id or '82143', 'amount': rec.amount or 2,
            'login_time': login_time_str, 'uploader': rec.uploader_name or ''
        })
    return JSONResponse(content={'records': record_list})

# ===================== API：库存监控 =====================
@app.get("/api/inventory_status")
async def inventory_status(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """获取库存监控状态（全局状态由admin控制，每用户可独立设置监控偏好）"""
    global stock_monitoring_active
    cfg = get_user_config(user.id, db)
    db_monitoring = cfg.inventory_monitoring
    return JSONResponse(content={
        'stock_monitoring_active': stock_monitoring_active,
        'is_stock_available': is_stock_available,
        'active_monitors_count': len(active_monitors),
        'inventory_monitoring_db': db_monitoring,
        'active_client_windows': get_active_client_count()
    })

@app.post("/api/start_inventory_monitoring")
async def start_inventory_monitoring(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """启动库存监控（仅管理员可控制全局监控任务）"""
    global stock_monitoring_active
    if user.id != 1 and user.username.lower() != "admin":
        # 非管理员用户：仅保存偏好，不控制全局监控
        cfg = get_user_config(user.id, db)
        cfg.inventory_monitoring = 1
        db.commit()
        return JSONResponse(content={'status': 'success', 'message': '监控偏好已保存（需管理员启动全局监控）'})
    stock_monitoring_active = True
    cfg = get_user_config(user.id, db)
    cfg.inventory_monitoring = 1
    db.commit()
    _background_tasks.append(asyncio.create_task(async_inventory_monitoring_worker()))
    return JSONResponse(content={'status': 'success', 'message': '库存监控已启动'})

@app.post("/api/stop_inventory_monitoring")
async def stop_inventory_monitoring(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """停止库存监控（仅管理员可控制全局监控任务）"""
    global stock_monitoring_active
    if user.id != 1 and user.username.lower() != "admin":
        # 非管理员用户：仅保存偏好，不控制全局监控
        cfg = get_user_config(user.id, db)
        cfg.inventory_monitoring = 0
        db.commit()
        return JSONResponse(content={'status': 'success', 'message': '监控偏好已保存（需管理员停止全局监控）'})
    stock_monitoring_active = False
    cfg = get_user_config(user.id, db)
    cfg.inventory_monitoring = 0
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': '库存监控已停止'})


# ===================== QR码、商品 =====================
@app.get("/qrcode/{phone}")
async def get_qrcode(phone: str, user: User = Depends(get_current_user)):
    qrcode_file = os.path.join(QRCODE_FOLDER, f"{phone}.png")
    if os.path.exists(qrcode_file):
        return FileResponse(qrcode_file)
    raise HTTPException(status_code=404)


@app.get("/api/sample_products")
async def sample_products(user: User = Depends(get_current_user)):
    return JSONResponse(content=[
        {"name": "茅台飞天53度 500ml", "price": "1499元"},
        {"name": "茅台生肖酒 虎年", "price": "2499元"},
        {"name": "茅台王子酒 酱香经典", "price": "398元"},
        {"name": "茅台迎宾酒 中国红", "price": "168元"},
    ])


# ===================== 上传Excel =====================
@app.post("/api/upload")
async def upload_excel(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    form = await request.form()
    if 'file' not in form:
        raise HTTPException(status_code=400, detail='没有文件')
    file = form['file']
    if not hasattr(file, 'filename') or not file.filename:
        raise HTTPException(status_code=400, detail='未选择文件')
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    content = await file.read()
    with open(filepath, 'wb') as f:
        f.write(content)
    try:
        df_with_header = pd.read_excel(filepath, header=0, dtype=str, engine='openpyxl')
        has_standard_headers = False
        if len(df_with_header.columns) >= 2:
            col_names = [str(col).strip().lower() for col in df_with_header.columns]
            if any(f in col_names for f in ['团队', '手机号', 'phone', 'team']):
                has_standard_headers = True
        imported = 0; skipped_exists = []; skipped_format = []
        if has_standard_headers:
            df = df_with_header
            column_mapping = {}
            for col in df.columns:
                cl = str(col).strip().lower()
                if cl in ['团队', 'team']: column_mapping[col] = 'team'
                elif cl in ['手机号', 'phone', '手机号码', '电话']: column_mapping[col] = 'phone'
                elif cl in ['商品名称', 'item_name']: column_mapping[col] = 'item_name'
                elif cl in ['商品编码', 'item_code', 'spu_id']: column_mapping[col] = 'item_code'
                elif cl in ['规格id', 'sku_id']: column_mapping[col] = 'sku_id'
                elif cl in ['活动id', 'activity_id']: column_mapping[col] = 'activity_id'
                elif cl in ['数量', 'amount', 'count', '采购数量']: column_mapping[col] = 'amount'
            if column_mapping:
                df = df.rename(columns=column_mapping)
            for index, row in df.iterrows():
                team = str(row.get('team', '')).strip() if pd.notna(row.get('team', '')) else ''
                raw_phone = str(row.get('phone', '')).strip() if pd.notna(row.get('phone', '')) else ''
                item_name = str(row.get('item_name', '')).strip() if pd.notna(row.get('item_name', '')) else ''
                item_code_raw = row.get('item_code', None)
                item_code = str(item_code_raw).strip() if pd.notna(item_code_raw) and item_code_raw != '' else 'IMTP1000313'
                sku_id_raw = row.get('sku_id', None)
                sku_id = str(sku_id_raw).strip() if pd.notna(sku_id_raw) and sku_id_raw != '' else '741'
                activity_id_raw = row.get('activity_id', None)
                activity_id = str(activity_id_raw).strip() if pd.notna(activity_id_raw) and activity_id_raw != '' else '82107'
                amount_raw = row.get('amount', None)
                amount_str = str(amount_raw).strip() if pd.notna(amount_raw) and amount_raw != '' else '1'
                if '.' in raw_phone and raw_phone.endswith('.0'): raw_phone = raw_phone[:-2]
                phone = re.sub(r'[\s\-\(\)]+', '', raw_phone)
                if not phone or not phone.isdigit() or len(phone) < 7:
                    skipped_format.append(f"第{index+2}行: '{raw_phone}'")
                    continue
                try: amount = int(amount_str)
                except: amount = 1
                if amount < 1: amount = 1
                existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
                if existing:
                    skipped_exists.append(phone)
                    continue
                rec = PhoneRecord(team=team, phone=phone, user_id=user.id, uploaded_by=user.id,
                    uploader_name=user.username, item_name=item_name, item_code=item_code, sku_id=sku_id, activity_id=activity_id, amount=amount)
                db.add(rec)
                imported += 1
        else:
            df_no_header = pd.read_excel(filepath, header=None, dtype=str, engine='openpyxl')
            for index, row in df_no_header.iterrows():
                team = str(row[0]).strip() if len(row) > 0 and pd.notna(row[0]) else ''
                raw_phone = str(row[1]).strip() if len(row) > 1 and pd.notna(row[1]) else ''
                item_name = str(row[2]).strip() if len(row) > 2 and pd.notna(row[2]) else ''
                sku_id = str(row[3]).strip() if len(row) > 3 and pd.notna(row[3]) else '741'
                activity_id = str(row[4]).strip() if len(row) > 4 and pd.notna(row[4]) else '82107'
                amount_str = str(row[5]).strip() if len(row) > 5 and pd.notna(row[5]) else '1'
                item_code = 'IMTP1000313'
                if '.' in raw_phone and raw_phone.endswith('.0'): raw_phone = raw_phone[:-2]
                phone = re.sub(r'[\s\-\(\)]+', '', raw_phone)
                if not phone or not phone.isdigit() or len(phone) < 7:
                    skipped_format.append(f"第{index+1}行: '{raw_phone}'")
                    continue
                try: amount = int(amount_str)
                except: amount = 1
                if amount < 1: amount = 1
                existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
                if existing:
                    skipped_exists.append(phone)
                    continue
                rec = PhoneRecord(team=team, phone=phone, user_id=user.id, uploaded_by=user.id,
                    uploader_name=user.username, item_name=item_name, item_code=item_code, sku_id=sku_id, activity_id=activity_id, amount=amount)
                db.add(rec)
                imported += 1
        db.commit()
        msg = f'成功导入 {imported} 条'
        if skipped_exists: msg += f'，跳过 {len(skipped_exists)} 条（已存在）'
        if skipped_format: msg += f'，失败 {len(skipped_format)} 条（格式错误）'
        return JSONResponse(content={'status': 'success', 'message': msg})
    except Exception as e:
        return JSONResponse(content={'status': 'error', 'message': f'解析失败: {str(e)}'}, status_code=400)


# ===================== 发送/提交验证码 =====================
@app.post("/api/send_code")
async def api_send_code(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record or record.user_id != user.id:
        raise HTTPException(status_code=403, detail='无权限')
    if record.logged_in:
        raise HTTPException(status_code=400, detail='账号已登录')
    success = await send_verification_code_impl_async(phone, db)
    if success:
        return JSONResponse(content={'status': 'success', 'message': '验证码已发送'})
    raise HTTPException(status_code=400, detail='发送失败')


@app.post("/api/submit_code")
async def api_submit_code(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record or record.user_id != user.id:
        raise HTTPException(status_code=403, detail='无权限')
    if record.logged_in:
        raise HTTPException(status_code=400, detail='账号已登录')
    creds = build_credentials_from_db(phone, db)
    login_result = await _bridge.login(phone, code, creds)
    if login_result.get('error'):
        raise HTTPException(status_code=400, detail=f'登录失败: {login_result["error"]}')
    record.token = login_result.get('token', ''); record.cookie = login_result.get('cookie', '')
    record.user_id_ext = login_result.get('user_id_ext', ''); record.logged_in = True
    record.last_updated = datetime.datetime.utcnow()
    record.login_time = datetime.datetime.now()
    db.commit(); save_account_to_json_from_creds(phone, login_result, record.uploader_name or "admin")
    return JSONResponse(content={'status': 'success', 'message': '登录成功'})


@app.post("/api/receive_sms")
async def receive_sms(request: Request, db: SQLSession = Depends(get_db)):
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail='无权限')
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    if not phone or not code:
        raise HTTPException(status_code=400, detail='参数不完整')
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        raise HTTPException(status_code=404, detail='手机号未在系统中')
    if record.logged_in:
        return JSONResponse(content={'status': 'success', 'message': '账号已登录'})
    creds = build_credentials_from_db(phone, db)
    login_result = await _bridge.login(phone, code, creds)
    if login_result.get('error'):
        raise HTTPException(status_code=400, detail=f'登录失败: {login_result["error"]}')
    record.token = login_result.get('token', ''); record.cookie = login_result.get('cookie', '')
    record.user_id_ext = login_result.get('user_id_ext', ''); record.logged_in = True
    record.last_updated = datetime.datetime.utcnow()
    record.login_time = datetime.datetime.now()
    db.commit(); save_account_to_json_from_creds(phone, login_result, record.uploader_name or "admin")
    return JSONResponse(content={'status': 'success', 'message': '自动登录成功'})


# ===================== 查询/导出/统计 =====================
@app.get("/api/phone_status/{phone}")
async def phone_status(phone: str, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record or record.user_id != user.id:
        raise HTTPException(status_code=404)
    uploader = db.query(User).filter(User.id == record.uploaded_by).first()
    return JSONResponse(content={
        'phone': record.phone, 'team': record.team,
        'uploaded_by': uploader.username if uploader else '未知',
        'code_sent': record.code_sent, 'logged_in': record.logged_in,
        'balance': record.balance, 'bid_result': record.bid_result,
        'last_updated': record.last_updated.isoformat() if record.last_updated else ''
    })


@app.get("/api/export")
async def export_data(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    data = [{'手机号': r.phone, '验证码已发送': r.code_sent, '登录状态': '成功' if r.logged_in else '掉线',
        '中标结果': r.bid_result, '账户余额': r.balance, '最后更新': r.last_updated} for r in records]
    df = pd.DataFrame(data)
    output = os.path.join(UPLOAD_FOLDER, 'export.xlsx')
    df.to_excel(output, index=False)
    return FileResponse(output, filename='export.xlsx')


@app.get("/api/stats")
async def stats(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    base = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id)
    total = base.count()
    success_login = base.filter(PhoneRecord.logged_in == True).count()
    offline = base.filter(PhoneRecord.logged_in == False, (PhoneRecord.token != '') | (PhoneRecord.cookie != '')).count()
    never_login = base.filter(PhoneRecord.logged_in == False, PhoneRecord.token == '', PhoneRecord.cookie == '').count()
    qrcode_count = sum(1 for rec in base.all() if os.path.exists(os.path.join(QRCODE_FOLDER, f"{rec.phone}.png")))
    bid_success = base.filter(PhoneRecord.bid_result.contains('成功')).count()
    # 白号/黑号计数
    all_records = base.all()
    white_count = sum(1 for r in all_records if r.account_type == 'white')
    black_count = sum(1 for r in all_records if r.account_type == 'black')
    logged_in_count = base.filter(PhoneRecord.logged_in == True).count()
    multi_open_count = cfg.multi_open_count or 1
    total_windows = (logged_in_count + multi_open_count - 1) // multi_open_count if logged_in_count > 0 else 0
    # 代理IP统计
    pool_count = proxy_manager.pool_size()
    # 统计数据库中已绑定IP的账号数（去重IP数）
    if user.username.lower() == 'admin':
        bound_records = db.query(PhoneRecord).filter(PhoneRecord.proxy_ip != '').all()
    else:
        bound_records = db.query(PhoneRecord).filter(PhoneRecord.proxy_ip != '', PhoneRecord.user_id == user.id).all()
    unique_ips = set(r.proxy_ip for r in bound_records if r.proxy_ip)
    ip_bound_count = len(bound_records)
    ip_unique_count = len(unique_ips)
    discarded_count = len(proxy_manager.all_discarded())
    # 团队统计
    teams = db.query(Team).filter(Team.owner_user_id == user.id).all()
    team_stats = []
    team_total_accounts = 0
    team_bid_success = 0
    team_paid_success = 0
    team_unpaid = 0
    # 筛选参数
    filter_team = request.query_params.get('team', '').strip()
    filter_uploader = request.query_params.get('uploader', '').strip()
    for t in teams:
        mappings = db.query(TeamAccount).filter(TeamAccount.team_id == t.id).all()
        t_phones = [m.phone for m in mappings]
        t_records = []
        if t_phones:
            t_records = db.query(PhoneRecord).filter(PhoneRecord.phone.in_(t_phones)).all()
        t_bid = sum(1 for r in t_records if r.bid_result and '成功' in r.bid_result)
        t_paid = sum(1 for r in t_records if r.pay_status == 'success')
        t_unpaid = sum(1 for r in t_records if r.pay_status == 'pending')
        team_stats.append({
            'id': t.id, 'name': t.name, 'account_count': len(t_phones),
            'bid_success': t_bid, 'paid_success': t_paid, 'unpaid': t_unpaid
        })
        team_total_accounts += len(t_phones)
        team_bid_success += t_bid
        team_paid_success += t_paid
        team_unpaid += t_unpaid
    return JSONResponse(content={
        'total': total, 'success_login': success_login, 'offline': offline,
        'never_login': never_login, 'bid_success': bid_success, 'qrcode_count': qrcode_count,
        'active_client_windows': get_active_client_count(),
        'server_count': len(server_list),
        'logged_in_count': logged_in_count, 'total_windows': total_windows,
        'white_count': white_count, 'black_count': black_count,
        'multi_open_count': multi_open_count, 'multi_open_enabled': cfg.multi_open_enabled,
        # IP统计
        'ip_pool_count': pool_count,
        'ip_ready_pool_count': proxy_manager.ready_pool_size(),
        'ip_bound_count': ip_bound_count,
        'ip_unique_count': ip_unique_count,
        'ip_discarded_count': discarded_count,
        # 团队统计
        'teams': team_stats,
        'team_total_accounts': team_total_accounts,
        'team_bid_success': team_bid_success,
        'team_paid_success': team_paid_success,
        'team_unpaid': team_unpaid
    })


@app.post("/api/batch_send_code")
async def batch_send_code(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    data = await request.json()
    min_delay = int(data.get('min_delay', 10))
    max_delay = int(data.get('max_delay', 20))
    user_id = user.id
    phones = [r.phone for r in db.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all()]
    if not phones:
        raise HTTPException(status_code=400, detail='无号码')
    async def batch_task():
        with SessionLocal() as sdb:
            pending = [r.phone for r in sdb.query(PhoneRecord).filter(PhoneRecord.user_id == user_id, PhoneRecord.logged_in == False).all()]
            for phone in pending:
                await send_verification_code_impl_async(phone, sdb)
                await asyncio.sleep(random.randint(min_delay, max_delay))
    _background_tasks.append(asyncio.create_task(batch_task()))
    pending_count = len([r for r in db.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all() if not r.logged_in])
    return JSONResponse(content={'status': 'success', 'message': f'共{len(phones)}个，{pending_count}个待发送'})


@app.post("/api/clear_all_records")
async def clear_all_records(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    try:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
        for rec in records:
            qrcode_path = os.path.join(QRCODE_FOLDER, f"{rec.phone}.png")
            if os.path.exists(qrcode_path): os.remove(qrcode_path)
        db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).delete()
        db.commit()
        return JSONResponse(content={'status': 'success', 'message': '已清空所有账号及二维码'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================== 配置管理 =====================
@app.get("/api/get_config")
async def get_config(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    up = get_user_proxy(user.id, db)
    return JSONResponse(content={
        'rush_hour': cfg.rush_hour, 'rush_minute': cfg.rush_minute, 'rush_second': cfg.rush_second,
        'rush_millisecond': getattr(cfg, 'rush_millisecond', 0),
        'multi_open_count': cfg.multi_open_count, 'multi_open_enabled': cfg.multi_open_enabled,
        'task_frequency': cfg.task_frequency, 'rush_attempts': cfg.rush_attempts,
        'rush_count': cfg.rush_count if hasattr(cfg, 'rush_count') else 100,
        'min_delay': cfg.min_delay, 'max_delay': cfg.max_delay,
        'anti_ban_proxy_enabled': up.proxy_enabled,
        'anti_ban_proxy_url': up.proxy_url,
        'client_windows': cfg.client_windows if hasattr(cfg, 'client_windows') else 10,
        'interval_mode': cfg.interval_mode if hasattr(cfg, 'interval_mode') else 0,
        'rush_paused': cfg.rush_paused if hasattr(cfg, 'rush_paused') else 0,
        'rush_mode': cfg.rush_mode if hasattr(cfg, 'rush_mode') else 0,
        'phone_multi_open_count': getattr(cfg, 'phone_multi_open_count', 3),
        'phone_rush_enabled': getattr(cfg, 'phone_rush_enabled', 0),
        'phone_deploy_info': getattr(cfg, 'phone_deploy_info', ''),
        'phone_device_assign': getattr(cfg, 'phone_device_assign', ''),
    })


# ===================== 手机抢购 WS 推送系统 =====================
from fastapi import WebSocket, WebSocketDisconnect

phone_ws_clients: dict = {}  # {device_id: WebSocket}
phone_ws_lock = asyncio.Lock()
phone_ws_uid_map: dict = {}  # {device_id: user_id}


async def broadcast_to_phone_device(device_id: str, message: dict):
    """向指定手机客户端推送消息"""
    async with phone_ws_lock:
        ws = phone_ws_clients.get(device_id)
    if ws:
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
            return True
        except Exception:
            async with phone_ws_lock:
                phone_ws_clients.pop(device_id, None)
                phone_ws_uid_map.pop(device_id, None)
    return False


async def broadcast_phone_status_to_user(user_id: int, status_data: dict):
    """向指定用户的所有手机设备推送状态变更"""
    async with phone_ws_lock:
        targets = [did for did, uid in phone_ws_uid_map.items() if uid == user_id]
    for did in targets:
        await broadcast_to_phone_device(did, {'type': 'status_change', **status_data})


@app.websocket("/api/phone_proxy/ws")
async def phone_proxy_websocket(websocket: WebSocket):
    await websocket.accept()
    device_id = None
    user_id = 0
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get('type', '')

            if msg_type == 'register':
                device_id = msg.get('device_id', '')
                mode = msg.get('mode', '')
                name = msg.get('name', '')

                if mode != 'rush_client':
                    await websocket.close(1008, "invalid mode")
                    return

                user_id = msg.get('user_id', 0)

                async with phone_ws_lock:
                    phone_ws_clients[device_id] = websocket
                    if user_id:
                        phone_ws_uid_map[device_id] = user_id

                # 查询当前用户的手机抢购状态，注册时一并下发
                status_data = {'phone_rush_enabled': 0, 'rush_paused': 0}
                if user_id:
                    try:
                        db2 = next(get_db())
                        cfg2 = get_user_config(user_id, db2)
                        status_data = {
                            'phone_rush_enabled': getattr(cfg2, 'phone_rush_enabled', 0),
                            'rush_paused': getattr(cfg2, 'rush_paused', 0),
                        }
                        db2.close()
                    except Exception:
                        pass

                await websocket.send_text(json.dumps({
                    'type': 'registered',
                    'tunnel_id': device_id,
                    'status': status_data,
                }, ensure_ascii=False))
                print(f'[手机WS] {name} 已注册 | device={device_id} | uid={user_id}')

            elif msg_type == 'rush_result':
                print(f'[手机WS] 抢购结果: {msg.get("round_id", "")} | {len(msg.get("results", []))}条')

            elif msg_type == 'rush_logs':
                print(f'[手机WS] 抢购日志: {msg.get("round_id", "")} | {len(msg.get("logs", ""))}字符')

            elif msg_type == 'ip_changed':
                print(f'[手机WS] IP变更: {msg.get("old_ip", "")} → {msg.get("new_ip", "")}')

            elif msg_type == 'pong':
                pass

            elif msg_type == 'ping':
                # 客户端心跳保活 → 回复pong
                await websocket.send_text(json.dumps({'type': 'pong'}, ensure_ascii=False))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f'[手机WS] 异常: {e}')
    finally:
        if device_id:
            async with phone_ws_lock:
                phone_ws_clients.pop(device_id, None)
                phone_ws_uid_map.pop(device_id, None)
            print(f'[手机WS] {device_id} 断开')


@app.post("/api/set_config")
async def set_config(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    data = await request.json()
    cfg = get_user_config(user.id, db)
    up = get_user_proxy(user.id, db)
    if 'rush_hour' in data: cfg.rush_hour = int(data['rush_hour'])
    if 'rush_minute' in data: cfg.rush_minute = int(data['rush_minute'])
    if 'rush_second' in data: cfg.rush_second = int(data['rush_second'])
    if 'rush_millisecond' in data: cfg.rush_millisecond = int(data['rush_millisecond'])
    if 'multi_open_count' in data: cfg.multi_open_count = int(data['multi_open_count'])
    elif 'task_window_count' in data: cfg.multi_open_count = int(data['task_window_count'])
    if 'multi_open_enabled' in data: cfg.multi_open_enabled = bool(data['multi_open_enabled'])
    elif 'distribution_mode' in data: cfg.multi_open_enabled = bool(data['distribution_mode'])
    if 'task_frequency' in data: cfg.task_frequency = int(data['task_frequency'])
    if 'rush_attempts' in data: cfg.rush_attempts = int(data['rush_attempts'])
    if 'rush_count' in data: cfg.rush_count = int(data['rush_count'])
    if 'min_delay' in data: cfg.min_delay = int(data['min_delay'])
    if 'max_delay' in data: cfg.max_delay = int(data['max_delay'])
    # 防封策略字段 → UserProxy
    if 'anti_ban_429_retry' in data: up.anti_ban_429_retry = int(data['anti_ban_429_retry'])
    if 'anti_ban_429_delay' in data: up.anti_ban_429_delay = int(data['anti_ban_429_delay'])
    if 'anti_ban_bangcle_ttl' in data: up.anti_ban_bangcle_ttl = int(data['anti_ban_bangcle_ttl'])
    if 'anti_ban_account_cooldown' in data: up.anti_ban_account_cooldown = int(data['anti_ban_account_cooldown'])
    if 'anti_ban_proxy_enabled' in data: up.proxy_enabled = bool(data['anti_ban_proxy_enabled'])
    if 'anti_ban_proxy_url' in data: up.proxy_url = str(data['anti_ban_proxy_url'])
    if 'client_windows' in data: cfg.client_windows = int(data['client_windows'])
    if 'interval_mode' in data: cfg.interval_mode = int(data['interval_mode'])
    if 'rush_mode' in data: cfg.rush_mode = int(data['rush_mode'])
    if 'phone_multi_open_count' in data: cfg.phone_multi_open_count = int(data['phone_multi_open_count'])
    if 'phone_rush_enabled' in data: cfg.phone_rush_enabled = int(data['phone_rush_enabled'])
    if 'phone_device_assign' in data: cfg.phone_device_assign = str(data['phone_device_assign'])
    db.commit()
    # === 实时推送：手机抢购状态变更 → 所有已连接手机设备 ===
    if 'phone_rush_enabled' in data or 'rush_paused' in data:
        asyncio.create_task(broadcast_phone_status_to_user(user.id, {
            'phone_rush_enabled': getattr(cfg, 'phone_rush_enabled', 0),
            'rush_paused': getattr(cfg, 'rush_paused', 0),
        }))
    return JSONResponse(content={'status': 'success'})


@app.post("/api/update_account_config")
async def update_account_config(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone', '').strip()
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record: raise HTTPException(status_code=404, detail='账号不存在')
    if user.id != 1 and record.user_id != user.id: raise HTTPException(status_code=403, detail='无权限')
    # 判断 item_name 是否为商品编号（SPU编码，如 IMTP1000313）
    item_name_val = str(data.get('item_name', '')).strip()
    record.item_name = item_name_val
    if item_name_val and re.match(r'^[A-Za-z]\w{4,}$', item_name_val):
        # 输入的是SPU商品编号，存入item_code，自动获取sku_id和act_id
        record.item_code = item_name_val
        # 异步自动获取 sku_id 和 activity_id
        try:
            creds = build_credentials_from_db(phone, db)
            detail_result = await _bridge._post('/api/bridge/execute', {
                'method': 'auto_fetch_item_details',
                'params': {'item_code': item_name_val, 'spu_id': item_name_val},
                'credentials': creds
            })
            if detail_result.get('success'):
                d = detail_result.get('result', {})
                record.sku_id = d.get('default_sku_id', '741')
                record.activity_id = d.get('activity_id', '82107')
                print(f'[配置] {phone} 商品编号={item_name_val} | 自动获取 sku_id={record.sku_id}, act_id={record.activity_id}')
            else:
                record.sku_id = '741'; record.activity_id = '82107'
                print(f'[配置] {phone} 商品详情获取失败，使用默认值')
        except Exception as e:
            print(f'[配置] {phone} 自动获取商品详情异常: {e}')
    elif not record.item_code:
        record.item_code = 'IMTP1000313'
    record.amount = int(data.get('amount', 1))
    if 'team' in data:
        new_team = str(data.get('team', ''))
        old_team = record.team or ''
        record.team = new_team
        # 同步维护 team_account 映射表（团队仪表盘依赖此表查询数据）
        if new_team != old_team:
            # 移除旧团队的映射
            if old_team:
                old_team_obj = db.query(Team).filter(Team.name == old_team).first()
                if old_team_obj:
                    db.query(TeamAccount).filter(
                        TeamAccount.team_id == old_team_obj.id,
                        TeamAccount.phone == phone
                    ).delete(synchronize_session=False)
            # 创建新团队的映射
            if new_team:
                new_team_obj = db.query(Team).filter(Team.name == new_team).first()
                if new_team_obj:
                    existing = db.query(TeamAccount).filter(
                        TeamAccount.team_id == new_team_obj.id,
                        TeamAccount.phone == phone
                    ).first()
                    if not existing:
                        ta = TeamAccount(team_id=new_team_obj.id, phone=phone, owner_user_id=new_team_obj.owner_user_id)
                        db.add(ta)
    if 'uploader_name' in data: record.uploader_name = str(data.get('uploader_name', ''))
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': '配置已保存'})


# ===================== 白号/黑号检测 API =====================
@app.post("/api/check_account_type")
async def check_account_type(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """检测白号/黑号：对已登录账号调用一次 rush_purchase，根据返回判定
    - 下单人数多（库存不足/人数过多类错误）→ 黑号
    - 活动未开始 → 白号
    - 其他情况不修改
    """
    # 获取当前用户的已登录账号
    if user.id == 1 or user.username.lower() == "admin":
        records = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    else:
        records = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True,
            PhoneRecord.user_id == user.id
        ).all()
    
    if not records:
        return JSONResponse(content={'status': 'success', 'message': '无已登录账号', 'results': {}})
    
    results = {}
    for i, rec in enumerate(records):
        if i > 0:
            await asyncio.sleep(random.uniform(0.05, 0.5))  # 50~500ms随机延迟，避免429
        try:
            creds = build_credentials_from_db(rec.phone, db)
            # 获取商品参数
            item_code = rec.item_code or 'IMTP1000313'
            detail_result = await _bridge._post('/api/bridge/execute', {
                'method': 'auto_fetch_item_details',
                'params': {'item_code': item_code, 'spu_id': item_code},
                'credentials': creds
            })
            if detail_result.get('success'):
                d = detail_result.get('result', {})
                sku_id = d.get('default_sku_id', '741')
                item_code_rush = d.get('item_code_from_api', '1001017')
                act_id = d.get('activity_id', '82107')
            else:
                sku_id = '741'
                item_code_rush = '1001017'
                act_id = '82107'
            
            # 调用一次 rush_purchase
            rush_result = await _bridge._post('/api/bridge/execute', {
                'method': 'rush_purchase',
                'params': {
                    'item_code': item_code_rush,
                    'sku_id': sku_id,
                    'item_priority_act_id': act_id,
                    'amount': '1'
                },
                'credentials': creds
            })
            
            if rush_result.get('success'):
                rush_data = rush_result.get('result', {})
                code = rush_data.get('code')
                msg = rush_data.get('message', '')
                
                if code == 2000:
                    # 抢购成功（意外情况），不修改 account_type
                    results[rec.phone] = {'account_type': rec.account_type or '', 'message': '抢购成功，跳过判断'}
                elif code in (4031, 4099) or '请求人数过多' in msg or '库存不足' in msg:
                    # 黑号：请求人数过多/库存不足
                    rec.account_type = 'black'
                    results[rec.phone] = {'account_type': 'black', 'message': msg}
                elif code in (4293,) or '人数较多' in msg or '活动未开始' in msg or '未开始' in msg:
                    # 白号：人数较多/活动未开始
                    rec.account_type = 'white'
                    results[rec.phone] = {'account_type': 'white', 'message': msg}
                else:
                    # 其他情况，不修改
                    results[rec.phone] = {'account_type': rec.account_type or '', 'message': msg}
            else:
                results[rec.phone] = {'account_type': rec.account_type or '', 'message': '桥接调用失败'}
        except Exception as e:
            results[rec.phone] = {'account_type': rec.account_type or '', 'message': f'异常: {str(e)[:50]}'}
    
    db.commit()
    white_count = sum(1 for v in results.values() if v['account_type'] == 'white')
    black_count = sum(1 for v in results.values() if v['account_type'] == 'black')
    return JSONResponse(content={
        'status': 'success',
        'message': f'检测完成: 白号{white_count}个, 黑号{black_count}个',
        'results': results
    })


@app.post("/api/check_account_type_single")
async def check_account_type_single(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """检测单个账号的白号/黑号"""
    data = await request.json()
    phone = data.get('phone', '').strip()
    if not phone:
        return JSONResponse(content={'status': 'error', 'message': '缺少手机号'}, status_code=400)
    
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '账号不存在'}, status_code=404)
    if not record.logged_in:
        return JSONResponse(content={'status': 'error', 'message': '账号未登录，无法判断'}, status_code=400)
    
    try:
        creds = build_credentials_from_db(phone, db)
        item_code = record.item_code or 'IMTP1000313'
        detail_result = await _bridge._post('/api/bridge/execute', {
            'method': 'auto_fetch_item_details',
            'params': {'item_code': item_code, 'spu_id': item_code},
            'credentials': creds
        })
        if detail_result.get('success'):
            d = detail_result.get('result', {})
            sku_id = d.get('default_sku_id', '741')
            item_code_rush = d.get('item_code_from_api', '1001017')
            act_id = d.get('activity_id', '82107')
        else:
            sku_id = '741'
            item_code_rush = '1001017'
            act_id = '82107'
        
        rush_result = await _bridge._post('/api/bridge/execute', {
            'method': 'rush_purchase',
            'params': {
                'item_code': item_code_rush,
                'sku_id': sku_id,
                'item_priority_act_id': act_id,
                'amount': '1'
            },
            'credentials': creds
        })
        
        if rush_result.get('success'):
            rush_data = rush_result.get('result', {})
            code = rush_data.get('code')
            msg = rush_data.get('message', '')
            
            if code == 2000:
                return JSONResponse(content={'status': 'success', 'account_type': record.account_type or '', 'message': '抢购成功，跳过判断'})
            elif code in (4031, 4099) or '请求人数过多' in msg or '库存不足' in msg:
                record.account_type = 'black'
                db.commit()
                return JSONResponse(content={'status': 'success', 'account_type': 'black', 'message': msg})
            elif code in (4293,) or '人数较多' in msg or '活动未开始' in msg or '未开始' in msg:
                record.account_type = 'white'
                db.commit()
                return JSONResponse(content={'status': 'success', 'account_type': 'white', 'message': msg})
            else:
                return JSONResponse(content={'status': 'success', 'account_type': record.account_type or '', 'message': msg})
        else:
            return JSONResponse(content={'status': 'error', 'message': '桥接调用失败'}, status_code=500)
    except Exception as e:
        return JSONResponse(content={'status': 'error', 'message': f'异常: {str(e)}'}, status_code=500)


@app.post("/api/clear_black_accounts")
async def clear_black_accounts(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """清除所有黑号账号（从数据库中删除）"""
    if user.id == 1 or user.username.lower() == "admin":
        black_records = db.query(PhoneRecord).filter(PhoneRecord.account_type == 'black').all()
    else:
        black_records = db.query(PhoneRecord).filter(PhoneRecord.account_type == 'black', PhoneRecord.user_id == user.id).all()
    
    deleted_phones = []
    for rec in black_records:
        deleted_phones.append(rec.phone)
        db.delete(rec)
    db.commit()
    
    print(f'[清除黑号] 用户 {user.username} 清除了 {len(deleted_phones)} 个黑号 | 手机号={deleted_phones}')
    return JSONResponse(content={
        'status': 'success',
        'message': f'已清除 {len(deleted_phones)} 个黑号',
        'deleted_count': len(deleted_phones),
        'deleted_phones': deleted_phones
    })


# ===================== 刷新登录状态 ======================
@app.post("/api/refresh_login")
async def refresh_login(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    records = db.query(PhoneRecord).all() if (user.id == 1 or user.username.lower() == "admin") else db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    
    # 加载当前用户的 iplala_accounts.json 备份
    accounts_file = os.path.join(BASEDIR, f'{user.username}_accounts.json')
    accounts_json = []
    try:
        if os.path.exists(accounts_file):
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts_json = json.load(f)
    except:
        pass
    # 兼容旧版 admin 用户的 iplala_accounts.json
    if not accounts_json and user.username == "admin":
        legacy_file = os.path.join(BASEDIR, 'iplala_accounts.json')
        try:
            if os.path.exists(legacy_file):
                with open(legacy_file, 'r', encoding='utf-8') as f:
                    accounts_json = json.load(f)
        except:
            pass
    
    results = {}
    # 检查代理开关和API地址
    up = get_user_proxy(user.id, db)
    proxy_enabled = up.proxy_enabled if up else False
    proxy_api_url = up.proxy_url if up else ''  # 豌豆代理API完整地址
    
    # 代理黑号计数器：IP -> 黑号数量（3次黑号则丢弃IP）
    ip_black_count = {}
    
    for i, phone in enumerate([r.phone for r in records]):
        if i > 0:
            await asyncio.sleep(random.uniform(0.05, 0.5))  # 50~500ms随机延迟，避免429
        try:
            print(f'[刷新登录] [{i+1}/{len(records)}] 开始处理: {phone}')
            # 1. 检查数据库是否有登录数据
            record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
            has_db_data = record and bool(record.token)
            print(f'[刷新登录] {phone} 数据库登录数据: {"有" if has_db_data else "无"}')
            
            # === 代理IP绑定逻辑 ===
            current_proxy = ''
            if proxy_enabled:
                # 如果账号已有绑定的代理IP且未被丢弃，复用
                if record and record.proxy_ip and record.proxy_ip not in proxy_manager._discarded:
                    current_proxy = record.proxy_ip
                else:
                    # 分配新代理IP（经就绪池/现场测试，确保IP可用）
                    current_proxy = await _test_and_assign_ip(user.id, proxy_api_url, db)
                    if record:
                        record.proxy_ip = current_proxy
                        db.commit()
                
                # 检查IP是否被3次黑号标记丢弃
                if current_proxy and ip_black_count.get(current_proxy, 0) >= 3:
                    print(f'[代理] IP {current_proxy} 已累积3次黑号，丢弃IP并删除关联黑号')
                    proxy_manager.discard_proxy(current_proxy)
                    black_with_ip = db.query(PhoneRecord).filter(
                        PhoneRecord.proxy_ip == current_proxy,
                        PhoneRecord.account_type == 'black'
                    ).all()
                    for bw in black_with_ip:
                        print(f'[代理] 删除黑号: {bw.phone}')
                        db.delete(bw)
                    db.commit()
                    current_proxy = await _test_and_assign_ip(user.id, proxy_api_url, db)
                    if record:
                        record.proxy_ip = current_proxy
                        db.commit()
            
            # 2. 如果数据库没有登录数据，尝试从 iplala_accounts.json 恢复
            if not has_db_data:
                acc = next((a for a in accounts_json if a.get('mobile') == phone), None)
                if acc and acc.get('token'):
                    print(f'[刷新登录] {phone} 数据库中无数据，从 {user.username}_accounts.json 恢复')
                    if record:
                        record.token = acc['token']
                        record.cookie = acc.get('cookie', '')
                        record.user_id_ext = str(acc.get('userid', ''))
                        record.mt_device_id = acc.get('mt-device-id', '')
                        record.raw_device_id = acc.get('device-id', '')
                        record.h5_did = acc.get('h5-did', '')
                        record.h5_start_id = acc.get('h5-start-id', '')
                        record.bs_device_id = acc.get('bs-device-id', '')
                        record.user_agent = acc.get('user-agent', '')
                        record.webview_ua = acc.get('webview-ua', '')
                        record.mt_r = acc.get('mt-r', '')
                        record.mt_sn = acc.get('mt-sn', '')
                        record.logged_in = True
                        record.last_updated = datetime.datetime.utcnow()
                        db.commit()
                        has_db_data = True
                        print(f'[刷新登录] {phone} 凭证恢复成功')
                else:
                    print(f'[刷新登录] {phone} 备份文件中也无数据，跳过')
            
            # 3. 如果有数据则检查登录状态
            if has_db_data:
                print(f'[刷新登录] {phone} 开始验证登录有效性...')
                valid = await check_login_validity_async(phone, proxy_url=current_proxy)
                if valid is None:
                    print(f'[刷新登录] {phone} 桥接不可达，跳过登录验证')
                    results[phone] = {'valid': None, 'status_desc': 'unknown', 'account_type': record.account_type if record else '', 'proxy_ip': record.proxy_ip if record else ''}
                    continue
                print(f'[刷新登录] {phone} 登录验证结果: {"有效" if valid else "无效/掉线"} | 代理={current_proxy or "无"}')
                # 代理场景：如果验证失败且使用代理，可能是IP被封
                if not valid and proxy_enabled and current_proxy:
                    print(f'[刷新登录] {phone} 登录验证失败，IP {current_proxy} 可能被封，丢弃换新IP')
                    proxy_manager.discard_proxy(current_proxy)
                    new_proxy = await _test_and_assign_ip(user.id, proxy_api_url, db)
                    if record:
                        record.proxy_ip = new_proxy
                        db.commit()
                    current_proxy = new_proxy
                    # 用新IP重试
                    print(f'[刷新登录] {phone} 用新IP {new_proxy} 重试验证...')
                    valid = await check_login_validity_async(phone, proxy_url=new_proxy)
                    if valid is None:
                        print(f'[刷新登录] {phone} 重试时桥接不可达，保留原数据')
                        results[phone] = {'valid': None, 'status_desc': 'unknown', 'account_type': record.account_type if record else '', 'proxy_ip': record.proxy_ip if record else ''}
                        continue
                    print(f'[刷新登录] {phone} 重试验证结果: {"有效" if valid else "无效/掉线"}')
                
                update_login_status(phone, valid, db)
                sync_login_time_from_json(phone, db)
                status_desc = _get_login_status_desc(phone, valid, db)
                # 获取 account_type
                rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
                account_type = rec.account_type if rec else ''
                # 登录成功且未判定白号/黑号，自动检测
                if valid and rec and not rec.account_type:
                    print(f'[刷新登录] {phone} 登录有效且未判定白号/黑号，开始测试下单检测...')
                    try:
                        creds = build_credentials_from_db(phone, db)
                        item_code = rec.item_code or 'IMTP1000313'
                        print(f'[刷新登录] {phone} 获取商品详情, item_code={item_code}')
                        detail_result = await _bridge._post('/api/bridge/execute', {
                            'method': 'auto_fetch_item_details',
                            'params': {'item_code': item_code, 'spu_id': item_code},
                            'credentials': creds,
                            'proxy_url': current_proxy
                        })
                        if detail_result.get('success'):
                            d = detail_result.get('result', {})
                            sku_id = d.get('default_sku_id', '741')
                            item_code_rush = d.get('item_code_from_api', '1001017')
                            act_id = d.get('activity_id', '82107')
                            print(f'[刷新登录] {phone} 商品详情成功 | sku_id={sku_id} | item_code_rush={item_code_rush} | act_id={act_id}')
                        else:
                            sku_id = '741'; item_code_rush = '1001017'; act_id = '82107'
                            print(f'[刷新登录] {phone} 商品详情失败，使用默认值 | sku_id={sku_id} | item_code_rush={item_code_rush} | act_id={act_id}')
                        print(f'[刷新登录] {phone} 发起测试下单(rush_purchase)...')
                        rush_result = await _bridge._post('/api/bridge/execute', {
                            'method': 'rush_purchase',
                            'params': {'item_code': item_code_rush, 'sku_id': sku_id, 'item_priority_act_id': act_id, 'amount': '1'},
                            'credentials': creds,
                            'proxy_url': current_proxy
                        })
                        if rush_result.get('success'):
                            rush_data = rush_result.get('result', {})
                            r_code = rush_data.get('code')
                            r_msg = rush_data.get('message', '')
                            print(f'[刷新登录] {phone} 下单返回 | code={r_code} | message={r_msg}')
                            if r_code == 2000:
                                print(f'[刷新登录] {phone} ⚠️ 测试下单成功(code=2000)，跳过判定')
                            elif r_code in (4031, 4099) or '请求人数过多' in r_msg or '库存不足' in r_msg:
                                rec.account_type = 'black'
                                print(f'[刷新登录] {phone} 判定为黑号(code={r_code})')
                                # 代理黑号计数+1
                                if current_proxy:
                                    ip_black_count[current_proxy] = ip_black_count.get(current_proxy, 0) + 1
                                    print(f'[刷新登录] IP {current_proxy} 黑号计数: {ip_black_count[current_proxy]}/3')
                            elif r_code in (4293,) or '人数较多' in r_msg or '活动未开始' in r_msg or '未开始' in r_msg:
                                rec.account_type = 'white'
                                print(f'[刷新登录] {phone} 判定为白号(人数较多/活动未开始)')
                            else:
                                print(f'[刷新登录] {phone} 未匹配已知判定规则，不修改account_type')
                            db.commit()
                        else:
                            print(f'[刷新登录] {phone} rush_purchase调用失败: {rush_result}')
                        account_type = rec.account_type
                    except Exception as e:
                        print(f'[刷新登录] {phone} 测试下单检测异常: {e}')
                elif valid and rec and rec.account_type:
                    print(f'[刷新登录] {phone} 登录有效，已有判定: {rec.account_type}，跳过测试下单')
                elif not valid:
                    print(f'[刷新登录] {phone} 登录无效/掉线，跳过测试下单')
                results[phone] = {'valid': valid, 'status_desc': status_desc, 'account_type': account_type, 'proxy_ip': record.proxy_ip if record else ''}
                print(f'[刷新登录] {phone} 处理完成 | 状态={status_desc} | 账号类型={account_type}')
            else:
                # 没有任何数据
                print(f'[刷新登录] {phone} 无任何登录数据，跳过')
                results[phone] = {'valid': False, 'status_desc': 'never', 'proxy_ip': ''}
        except Exception as e:
            print(f'[刷新登录] {phone} 处理异常: {e}')
            results[phone] = {'valid': False, 'status_desc': 'never'}
    return JSONResponse(content={'status': 'success', 'results': results})


# ===================== 单号刷新登录状态 ======================
@app.post("/api/refresh_login_single")
async def refresh_login_single(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """刷新单个号码的登录状态（在提交验证码后调用）"""
    data = await request.json()
    phone = str(data.get('phone', '')).strip()
    if not phone:
        return JSONResponse(content={'status': 'error', 'message': '手机号不能为空'})

    # 加载当前用户的 iplala_accounts.json 备份
    accounts_file = os.path.join(BASEDIR, f'{user.username}_accounts.json')
    accounts_json = []
    try:
        if os.path.exists(accounts_file):
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts_json = json.load(f)
    except:
        pass
    if not accounts_json and user.username == "admin":
        legacy_file = os.path.join(BASEDIR, 'iplala_accounts.json')
        try:
            if os.path.exists(legacy_file):
                with open(legacy_file, 'r', encoding='utf-8') as f:
                    accounts_json = json.load(f)
        except:
            pass

    # 检查代理配置
    up = get_user_proxy(user.id, db)
    proxy_enabled = up.proxy_enabled if up else False
    proxy_api_url = up.proxy_url if up else ''
    current_proxy = ''

    try:
        print(f'[单号刷新] 开始处理: {phone}')
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        if not record:
            return JSONResponse(content={'status': 'error', 'message': f'手机号 {phone} 不在数据库中'})

        has_db_data = record and bool(record.token)
        print(f'[单号刷新] {phone} 数据库登录数据: {"有" if has_db_data else "无"}')

        # 代理IP绑定 + 可用性测试
        ip_status = 'none'  # none/ok/dead/replaced
        if proxy_enabled:
            if record.proxy_ip and record.proxy_ip not in proxy_manager._discarded:
                # 先测试已有IP是否被CDN封禁
                ip_test = await _test_proxy_ip(record.proxy_ip, timeout=5.0)
                if ip_test.get('ok'):
                    current_proxy = record.proxy_ip
                    ip_status = 'ok'
                    print(f'[单号刷新] {phone} 复用IP且可用: {current_proxy}')
                else:
                    print(f'[单号刷新] {phone} 旧IP被封({ip_test.get("reason")})，丢弃换新IP')
                    proxy_manager.discard_proxy(record.proxy_ip)
                    current_proxy = await _test_and_assign_ip(user.id, proxy_api_url, db)
                    record.proxy_ip = current_proxy
                    db.commit()
                    ip_status = 'replaced' if current_proxy else 'dead'
                    print(f'[单号刷新] {phone} 新IP: {current_proxy or "无可用IP"}')
            else:
                if record.proxy_ip:
                    print(f'[单号刷新] {phone} 旧IP已丢弃({record.proxy_ip})，分配新IP')
                current_proxy = await _test_and_assign_ip(user.id, proxy_api_url, db)
                record.proxy_ip = current_proxy
                db.commit()
                ip_status = 'replaced' if current_proxy else 'dead'
                print(f'[单号刷新] {phone} 新绑定IP: {current_proxy or "无可用IP"}')

        # 尝试从 accounts.json 恢复
        if not has_db_data:
            acc = next((a for a in accounts_json if a.get('mobile') == phone), None)
            if acc and acc.get('token'):
                print(f'[单号刷新] {phone} 数据库中无数据，从 {user.username}_accounts.json 恢复')
                record.token = acc['token']
                record.cookie = acc.get('cookie', '')
                record.user_id_ext = str(acc.get('userid', ''))
                record.mt_device_id = acc.get('mt-device-id', '')
                record.raw_device_id = acc.get('device-id', '')
                record.h5_did = acc.get('h5-did', '')
                record.h5_start_id = acc.get('h5-start-id', '')
                record.bs_device_id = acc.get('bs-device-id', '')
                record.user_agent = acc.get('user-agent', '')
                record.webview_ua = acc.get('webview-ua', '')
                record.mt_r = acc.get('mt-r', '')
                record.mt_sn = acc.get('mt-sn', '')
                record.logged_in = True
                record.last_updated = datetime.datetime.utcnow()
                db.commit()
                has_db_data = True
                print(f'[单号刷新] {phone} 凭证恢复成功')
            else:
                print(f'[单号刷新] {phone} 备份文件中也无数据')
                return JSONResponse(content={
                    'status': 'success',
                    'results': {phone: {'valid': False, 'status_desc': 'never', 'account_type': '', 'proxy_ip': record.proxy_ip or '', 'ip_status': ip_status}}
                })

        # 验证登录有效性
        if has_db_data:
            print(f'[单号刷新] {phone} 开始验证登录有效性...')
            valid = await check_login_validity_async(phone, proxy_url=current_proxy)
            if valid is None:
                print(f'[单号刷新] {phone} 桥接不可达，跳过登录状态更新，保留现有数据')
                status_desc = _get_login_status_desc(phone, False, db)
                account_type = record.account_type or ''
                print(f'[单号刷新] {phone} 处理完成 | 状态={status_desc}(未验证) | 账号类型={account_type} | IP={record.proxy_ip or "无"} | IP状态={ip_status}')
                return JSONResponse(content={
                    'status': 'success',
                    'results': {phone: {'valid': None, 'status_desc': status_desc, 'account_type': account_type, 'proxy_ip': record.proxy_ip or '', 'ip_status': ip_status}}
                })
            print(f'[单号刷新] {phone} 登录验证结果: {"有效" if valid else "无效/掉线"}')

            if not valid and proxy_enabled and current_proxy:
                print(f'[单号刷新] {phone} 登录验证失败，IP {current_proxy} 可能被封，丢弃换新IP')
                proxy_manager.discard_proxy(current_proxy)
                new_proxy = await _test_and_assign_ip(user.id, proxy_api_url, db)
                record.proxy_ip = new_proxy
                db.commit()
                current_proxy = new_proxy
                if new_proxy:
                    print(f'[单号刷新] {phone} 用新IP {new_proxy} 重试验证...')
                    valid = await check_login_validity_async(phone, proxy_url=new_proxy)
                    if valid is None:
                        print(f'[单号刷新] {phone} 重试时桥接不可达，保留原数据')
                        status_desc = _get_login_status_desc(phone, False, db)
                        account_type = record.account_type or ''
                        return JSONResponse(content={
                            'status': 'success',
                            'results': {phone: {'valid': None, 'status_desc': status_desc, 'account_type': account_type, 'proxy_ip': record.proxy_ip or '', 'ip_status': ip_status}}
                        })
                    print(f'[单号刷新] {phone} 重试验证结果: {"有效" if valid else "无效/掉线"}')
                else:
                    print(f'[单号刷新] {phone} 无可用IP，跳过重试')

            update_login_status(phone, valid, db)
            sync_login_time_from_json(phone, db)
            status_desc = _get_login_status_desc(phone, valid, db)
            account_type = record.account_type or ''

            # 登录有效且未判定白号/黑号，自动检测
            if valid and record and not record.account_type:
                print(f'[单号刷新] {phone} 登录有效且未判定白号/黑号，开始测试下单检测...')
                try:
                    creds = build_credentials_from_db(phone, db)
                    item_code = record.item_code or 'IMTP1000313'
                    detail_result = await _bridge._post('/api/bridge/execute', {
                        'method': 'auto_fetch_item_details',
                        'params': {'item_code': item_code, 'spu_id': item_code},
                        'credentials': creds,
                        'proxy_url': current_proxy
                    })
                    if detail_result.get('success'):
                        d = detail_result.get('result', {})
                        sku_id = d.get('default_sku_id', '741')
                        item_code_rush = d.get('item_code_from_api', '1001017')
                        act_id = d.get('activity_id', '82107')
                    else:
                        sku_id = '741'; item_code_rush = '1001017'; act_id = '82107'
                    rush_result = await _bridge._post('/api/bridge/execute', {
                        'method': 'rush_purchase',
                        'params': {'item_code': item_code_rush, 'sku_id': sku_id, 'item_priority_act_id': act_id, 'amount': '1'},
                        'credentials': creds,
                        'proxy_url': current_proxy
                    })
                    if rush_result.get('success'):
                        rush_data = rush_result.get('result', {})
                        r_code = rush_data.get('code')
                        r_msg = rush_data.get('message', '')
                        print(f'[单号刷新] {phone} 下单返回 | code={r_code} | message={r_msg}')
                        if r_code == 2000:
                            print(f'[单号刷新] {phone} ⚠️ 测试下单成功(code=2000)，跳过判定')
                        elif r_code in (4031, 4099) or '请求人数过多' in r_msg or '库存不足' in r_msg:
                            record.account_type = 'black'
                            print(f'[单号刷新] {phone} 判定为黑号')
                        elif r_code in (4293,) or '人数较多' in r_msg or '活动未开始' in r_msg or '未开始' in r_msg:
                            record.account_type = 'white'
                            print(f'[单号刷新] {phone} 判定为白号')
                        db.commit()
                    account_type = record.account_type
                except Exception as e:
                    print(f'[单号刷新] {phone} 测试下单检测异常: {e}')
            elif valid and record and record.account_type:
                print(f'[单号刷新] {phone} 登录有效，已有判定: {record.account_type}，跳过测试下单')

            print(f'[单号刷新] {phone} 处理完成 | 状态={status_desc} | 账号类型={account_type} | IP={record.proxy_ip or "无"} | IP状态={ip_status}')
            return JSONResponse(content={
                'status': 'success',
                'results': {phone: {'valid': valid, 'status_desc': status_desc, 'account_type': account_type, 'proxy_ip': record.proxy_ip or '', 'ip_status': ip_status}}
            })
        else:
            return JSONResponse(content={
                'status': 'success',
                'results': {phone: {'valid': False, 'status_desc': 'never', 'account_type': '', 'proxy_ip': record.proxy_ip or '', 'ip_status': ip_status}}
            })
    except Exception as e:
        print(f'[单号刷新] {phone} 处理异常: {e}')
        return JSONResponse(content={'status': 'error', 'message': str(e)})


# ===================== 查询中标结果 =====================
@app.post("/api/query_bid_results")
async def query_bid_results(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    results = {}
    for rec in records:
        if not rec.logged_in or not rec.token:
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance, "pay_url": rec.pay_url, "pay_status": rec.pay_status}
            continue
        try:
            creds = build_credentials_from_db(rec.phone, db)
            bridge_result = await _bridge._post('/api/bridge/execute', {
                'method': 'query_order_list',
                'params': {},
                'credentials': creds
            })
            orders = bridge_result.get('result', []) if bridge_result.get('success') else []
            winning = [o for o in orders if o.get("status") in (1, 2, 3)]
            if winning:
                rec.bid_result = f"中奖-{winning[0].get('itemName', '商品')}"
                rec.balance = winning[0].get("totalAmount", "")
                st = winning[0].get("status")
                if st in (2, 3): rec.pay_status = "success"; rec.balance = "已支付"
                elif st == 1: rec.pay_status = "pending"; rec.balance = "待支付"
            else: rec.bid_result = "未中奖"
            db.commit()
        except: pass
        results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance, "pay_url": rec.pay_url, "pay_status": rec.pay_status}
    return JSONResponse(content={'status': 'success', 'results': results})


# ===================== 客户端 API =====================
@app.get("/api/client/inventory_status")
async def client_inventory_status(request: Request, db: SQLSession = Depends(get_db)):
    """客户端专用库存状态端点（X-API-TOKEN 认证，无需 session 登录）"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    global stock_monitoring_active, is_stock_available
    cfg = get_user_config(1, db)  # admin 的库存监控全局状态
    db_monitoring = cfg.inventory_monitoring if cfg else 0
    if db_monitoring == 1 and not stock_monitoring_active:
        stock_monitoring_active = True
    elif db_monitoring == 0 and stock_monitoring_active:
        stock_monitoring_active = False
    return JSONResponse(content={
        'stock_monitoring_active': stock_monitoring_active,
        'is_stock_available': is_stock_available,
        'active_monitors_count': len(active_monitors),
        'inventory_monitoring_db': db_monitoring,
        'active_client_windows': get_active_client_count()
    })


@app.get("/api/client/get_config")
async def client_get_config(request: Request, db: SQLSession = Depends(get_db)):
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    uploader_id_str = request.query_params.get('uploader_id', '0')
    try:
        uploader_id = int(uploader_id_str)
    except:
        uploader_id = 0
    try:
        if uploader_id > 0:
            cfg = get_user_config(uploader_id, db)
            up = get_user_proxy(uploader_id, db)
            logged_in_count = db.query(PhoneRecord).filter(
                PhoneRecord.logged_in == True,
                PhoneRecord.user_id == uploader_id
            ).count()
        else:
            cfg = get_user_config(1, db)
            up = get_user_proxy(1, db)
            logged_in_count = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).count()
    except Exception as e:
        print(f'[配置] 数据库查询异常: {e}')
        # MySQL不可达时返回默认配置
        return JSONResponse(content={
            'rush_hour': 8, 'rush_minute': 58, 'rush_second': 0,
            'rush_attempts': 100000, 'task_frequency': 10,
            'multi_open_count': 1, 'multi_open_enabled': False,
            'min_delay': 10, 'max_delay': 20,
            'item_code': '741', 'act_id': '76145',
            'logged_in_count': 0, 'total_windows': 0,
            'phone_multi_open_count': 3
        })
    multi_open_count = cfg.multi_open_count or 1
    # 计算需要多少个客户端窗口
    total_windows = (logged_in_count + multi_open_count - 1) // multi_open_count if logged_in_count > 0 else 0
    client_ip = request.client.host if request.client else 'unknown'
    rush_time_str = f"{cfg.rush_hour:02d}:{cfg.rush_minute:02d}:{cfg.rush_second:02d}.{getattr(cfg, 'rush_millisecond', 0):03d}"
    print(f'[取配置] → IP={client_ip} | 抢购时间={rush_time_str} | 频率={cfg.task_frequency}ms | 次数={getattr(cfg, "rush_count", 100)}/轮 | 多开数={multi_open_count} | 白号={logged_in_count} | 暂停={getattr(cfg, "rush_paused", 0)} | 代理={up.proxy_enabled}')
    return JSONResponse(content={
        'rush_hour': cfg.rush_hour, 'rush_minute': cfg.rush_minute, 'rush_second': cfg.rush_second,
        'rush_millisecond': getattr(cfg, 'rush_millisecond', 0),
        'rush_attempts': cfg.rush_attempts, 'task_frequency': cfg.task_frequency,
        'rush_count': cfg.rush_count if hasattr(cfg, 'rush_count') else 100,
        'multi_open_count': multi_open_count, 'multi_open_enabled': cfg.multi_open_enabled,
        'min_delay': cfg.min_delay, 'max_delay': cfg.max_delay,
        'item_code': 'IMTP1000313', 'act_id': '',
        'logged_in_count': logged_in_count, 'total_windows': total_windows,
        # 防封配置
        'anti_ban_429_retry': up.anti_ban_429_retry,
        'anti_ban_429_delay': up.anti_ban_429_delay,
        'anti_ban_bangcle_ttl': up.anti_ban_bangcle_ttl,
        'anti_ban_account_cooldown': up.anti_ban_account_cooldown,
        'rush_paused': cfg.rush_paused if hasattr(cfg, 'rush_paused') else 0,
        'proxy_enabled': up.proxy_enabled,
        'proxy_url': up.proxy_url,
        'anti_ban_proxy_enabled': up.proxy_enabled,
        'anti_ban_proxy_url': up.proxy_url,
        'client_windows': cfg.client_windows if hasattr(cfg, 'client_windows') else 10,
        'interval_mode': cfg.interval_mode if hasattr(cfg, 'interval_mode') else 0,
        'rush_mode': cfg.rush_mode if hasattr(cfg, 'rush_mode') else 0,
        'phone_multi_open_count': getattr(cfg, 'phone_multi_open_count', 3),
    })    


# ===================== 抢购模式开关 API =====================
@app.post("/api/toggle_rush_mode")
async def toggle_rush_mode(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """切换当前用户的抢购模式"""
    data = await request.json()
    enabled = int(data.get('rush_mode', 0))
    cfg = get_user_config(user.id, db)
    cfg.rush_mode = enabled
    db.commit()
    return JSONResponse(content={'status': 'success', 'rush_mode': enabled})

# ===================== 暂停/恢复/代理开关 API =====================
@app.post("/api/pause_rush")
async def pause_rush(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """暂停当前用户的抢购"""
    cfg = get_user_config(user.id, db)
    cfg.rush_paused = 1
    db.commit()
    return JSONResponse(content={'status': 'success', 'rush_paused': 1})

@app.post("/api/resume_rush")
async def resume_rush(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """恢复当前用户的抢购"""
    cfg = get_user_config(user.id, db)
    cfg.rush_paused = 0
    db.commit()
    return JSONResponse(content={'status': 'success', 'rush_paused': 0})

@app.get("/api/rush_status")
async def rush_status(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """获取当前用户抢购暂停状态和代理状态"""
    cfg = get_user_config(user.id, db)
    up = get_user_proxy(user.id, db)
    paused = cfg.rush_paused if hasattr(cfg, 'rush_paused') else 0
    proxy_enabled = up.proxy_enabled
    return JSONResponse(content={'rush_paused': paused, 'proxy_enabled': proxy_enabled})

@app.post("/api/toggle_proxy")
async def toggle_proxy(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """切换当前用户代理开关"""
    data = await request.json()
    enabled = bool(data.get('enabled', False))
    up = get_user_proxy(user.id, db)
    up.proxy_enabled = enabled
    db.commit()
    return JSONResponse(content={'status': 'success', 'proxy_enabled': enabled})

@app.get("/api/client/get_pause_status")
async def client_get_pause_status(request: Request, db: SQLSession = Depends(get_db)):
    """客户端查询暂停+代理状态（X-API-TOKEN 认证，支持 uploader_id）"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    uploader_id_str = request.query_params.get('uploader_id', '0')
    try:
        uploader_id = int(uploader_id_str)
    except:
        uploader_id = 0
    if uploader_id > 0:
        cfg = get_user_config(uploader_id, db)
        up = get_user_proxy(uploader_id, db)
    else:
        cfg = get_user_config(1, db)
        up = get_user_proxy(1, db)
    paused = cfg.rush_paused if hasattr(cfg, 'rush_paused') else 0
    # 代理模式下强制 proxy_enabled=True
    proxy_enabled = up.proxy_enabled or PHONE_PROXY_MODE == 'proxy_only'
    proxy_url = up.proxy_url if up.proxy_enabled else ''  # 仅外部代理开启时下发 proxy_url
    return JSONResponse(content={
        'paused': paused,
        'proxy_enabled': proxy_enabled,
        'proxy_url': proxy_url,
    })

# ===================== 设备密钥注册系统（基于数据库持久化） =====================
import uuid as _uuid

# 密钥分配锁：防止并发注册同一设备的设备/窗口密钥
_key_lock = asyncio.Lock()

def _gen_key() -> str:
    """生成密钥：优先从 key_seeds 池取未分配密钥，池空则自动生成"""
    return _uuid.uuid4().hex[:16]

def _fetch_or_create_key(db: SQLSession, key_type: str) -> str:
    """从密钥池取一个未分配的密钥，池空则自动生成并入库"""
    seed = db.query(KeySeed).filter(
        KeySeed.key_type == key_type, KeySeed.assigned == False
    ).first()
    if seed:
        return seed.seed_key
    # 池空：自动生成新密钥并入池
    new_key = _uuid.uuid4().hex[:16]
    try:
        db.add(KeySeed(seed_key=new_key, key_type=key_type, assigned=False))
        db.commit()
    except Exception:
        db.rollback()
    return new_key

@app.post("/api/client/register_device")
async def client_register_device(request: Request, db: SQLSession = Depends(get_db)):
    """设备注册端点：每台物理机在启动时调用一次
    上报 machine_id（系统 UUID，如 dmidecode -s system-uuid），
    服务端识别是否为新设备，分配或返回已有 device_key

    流程：
    1. 查 machine_id 是否已注册 → 是则返回已有 device_key，更新状态
    2. 否 → 分配新 device_key，创建 DeviceKey 记录
    3. 返回 device_key + max_windows"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    machine_id = (data.get('machine_id', '') or '').strip()
    user_id = data.get('uploader_id', 1)
    hostname = data.get('hostname', '')
    client_ip = request.client.host if request.client else 'unknown'

    if not machine_id:
        raise HTTPException(status_code=400, detail='缺少 machine_id')

    # 读多开配置
    try:
        cfg = get_user_config(user_id, db)
        max_windows = cfg.client_windows if cfg else 8
        multi_open_count = cfg.multi_open_count if cfg else 1
    except Exception:
        max_windows = 8
        multi_open_count = 1

    now = datetime.datetime.utcnow()

    async with _key_lock:
        existing = db.query(DeviceKey).filter(
            DeviceKey.user_id == user_id,
            DeviceKey.machine_id == machine_id
        ).first()

        if existing:
            # 同一设备重启：复用已有 device_key
            existing.status = 'active'
            existing.hostname = hostname
            existing.last_ip = client_ip
            existing.max_windows = max_windows
            existing.last_seen_at = now
            db.commit()
            device_key = existing.device_key
            print(f'[设备注册] 复用 {hostname} | machine={machine_id[:16]} | key={device_key}')
            # 重新激活该设备下的所有窗口
            db.query(WindowKey).filter(
                WindowKey.device_key == device_key
            ).update({'status': 'inactive'})
            db.commit()
        else:
            # 新设备
            device_key = _fetch_or_create_key(db, 'device')
            db.add(DeviceKey(
                device_key=device_key, user_id=user_id,
                machine_id=machine_id, hostname=hostname,
                last_ip=client_ip, max_windows=max_windows,
                status='active', last_seen_at=now
            ))
            # 标记密钥种子为已使用
            seed = db.query(KeySeed).filter(KeySeed.seed_key == device_key).first()
            if seed:
                seed.assigned = True
                seed.assigned_to = device_key
            db.commit()
            print(f'[设备注册] 新设备 {hostname} | machine={machine_id[:16]} | key={device_key}')

    # 返回已有窗口列表（重启后复用）
    existing_windows = db.query(WindowKey).filter(
        WindowKey.device_key == device_key
    ).order_by(WindowKey.window_index).all()
    window_list = [{
        'window_key': w.window_key,
        'window_index': w.window_index,
        'status': w.status
    } for w in existing_windows]

    return JSONResponse(content={
        'status': 'success',
        'device_key': device_key,
        'max_windows': max_windows,
        'multi_open_count': multi_open_count,
        'existing_windows': window_list
    })


@app.post("/api/client/register_window")
async def client_register_window(request: Request, db: SQLSession = Depends(get_db)):
    """窗口注册端点：每个客户端窗口启动时调用一次
    上报 device_key + client_uuid，服务端分配窗口编号和窗口密钥

    流程：
    1. 校验 device_key 是否有效
    2. 检查该设备下已有活跃窗口数 < max_windows
    3. 查找该设备下未使用的 window_index → 分配之
    4. 若无空闲位 → 达到上限，返回错误
    5. 分配窗口密钥，返回窗口编号 + 账号任务"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    device_key = (data.get('device_key', '') or '').strip()
    client_uuid = data.get('client_uuid', '')
    uploader_id = data.get('uploader_id', 1)
    client_ip = request.client.host if request.client else 'unknown'

    if not device_key:
        # 回退到旧版 register 逻辑
        return await client_register_legacy(request, db)
    if not client_uuid:
        raise HTTPException(status_code=400, detail='缺少 client_uuid')

    # 校验设备
    device = db.query(DeviceKey).filter(
        DeviceKey.device_key == device_key, DeviceKey.status == 'active'
    ).first()
    if not device:
        return JSONResponse(content={'status': 'error', 'message': '设备密钥无效或已过期'}, status_code=400)

    max_windows = device.max_windows
    # 读多开配置
    try:
        cfg = get_user_config(device.user_id, db)
        multi_open_count = cfg.multi_open_count if cfg else 1
    except Exception:
        multi_open_count = 1

    now_time = datetime.datetime.utcnow()

    async with _key_lock:
        # 清理该设备下超时的窗口（30秒无心跳）
        timeout_threshold = now_time - datetime.timedelta(seconds=CLIENT_HEARTBEAT_TIMEOUT)
        db.query(WindowKey).filter(
            WindowKey.device_key == device_key,
            WindowKey.status == 'active',
            WindowKey.last_seen_at < timeout_threshold
        ).update({'status': 'inactive'})
        db.commit()

        # 检查窗口数上限
        active_count = db.query(WindowKey).filter(
            WindowKey.device_key == device_key, WindowKey.status == 'active'
        ).count()

        # 如果该窗口之前已注册（重启后重新上线），复用原窗口
        existing_win = db.query(WindowKey).filter(
            WindowKey.device_key == device_key,
            WindowKey.client_uuid == client_uuid
        ).first()

        if existing_win:
            # 重启后复用原窗口密钥和编号
            window_key = existing_win.window_key
            window_index = existing_win.window_index
            existing_win.status = 'active'
            existing_win.last_seen_at = now_time
            db.commit()
            print(f'[窗口注册] 复用 设备={device_key[:8]} 窗口={window_index} key={window_key[:8]}')
        elif active_count < max_windows:
            # 分配新窗口：找最小未使用编号
            used_indices = set()
            for w in db.query(WindowKey).filter(
                WindowKey.device_key == device_key
            ).all():
                used_indices.add(w.window_index)
            window_index = 0
            while window_index in used_indices:
                window_index += 1

            window_key = _fetch_or_create_key(db, 'window')
            db.add(WindowKey(
                window_key=window_key, device_key=device_key,
                user_id=device.user_id, window_index=window_index,
                status='active', last_seen_at=now_time, client_uuid=client_uuid
            ))
            # 标记密钥种子
            seed = db.query(KeySeed).filter(KeySeed.seed_key == window_key).first()
            if seed:
                seed.assigned = True
                seed.assigned_to = window_key
            db.commit()
            print(f'[窗口注册] 新窗口 设备={device_key[:8]} 窗口={window_index} key={window_key[:8]}')
        else:
            return JSONResponse(content={
                'status': 'error',
                'message': f'设备窗口数已达上限 ({active_count}/{max_windows})，请增加窗口数配置或停止空闲窗口'
            }, status_code=409)

    # 分配账号任务
    all_logged_in = db.query(PhoneRecord).filter(
        PhoneRecord.logged_in == True,
        PhoneRecord.user_id == device.user_id
    ).all()
    all_logged_in = [r for r in all_logged_in if not _is_black_account(r.account_type)]
    all_logged_in = _filter_excluded(all_logged_in, cfg)
    window_records = allocate_tasks_for_window(all_logged_in, multi_open_count, window_index)

    # 更新设备最后活跃时间
    device.last_seen_at = now_time
    device.last_ip = client_ip
    db.commit()

    # 更新内存中的活跃窗口追踪
    active_client_windows[client_uuid] = {
        "batch": window_index,
        "client_uuid": client_uuid,
        "uploader_id": device.user_id,
        "last_heartbeat": time.time(),
        "ip": client_ip,
        "hostname": device.hostname or '',
        "task_count": len(window_records),
        "device_key": device_key,
        "window_key": window_key
    }

    # 更新 IP 聚合的服务器列表
    _update_server_list(client_ip, device.hostname or '', len(window_records))

    return JSONResponse(content={
        'status': 'success',
        'device_key': device_key,
        'window_key': window_key,
        'window_index': window_index,
        'batch': window_index,
        'multi_open_count': multi_open_count,
        'tasks': _build_task_response(window_records)
    })


@app.post("/api/client/bind_device")
async def client_bind_device(request: Request, db: SQLSession = Depends(get_db)):
    """客户端上报手机号与设备机型的绑定关系（绑定后不可更换）"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    data = await request.json()
    phone = data.get('phone', '')
    device_key = data.get('device_key', '')
    if not phone or not device_key:
        return JSONResponse(content={'status': 'error', 'message': '缺少phone或device_key'})

    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '手机号不存在'})

    if record.device_key:
        return JSONResponse(content={
            'status': 'success', 'device_key': record.device_key,
            'new_binding': False, 'message': f'已有绑定: {record.device_key}',
        })

    record.device_key = device_key
    db.commit()
    print(f'[设备绑定] {phone} → {device_key}')
    return JSONResponse(content={
        'status': 'success', 'device_key': device_key,
        'new_binding': True, 'message': f'绑定成功: {device_key}',
    })


@app.get("/api/client/get_device_bindings")
async def client_get_device_bindings(request: Request, db: SQLSession = Depends(get_db)):
    """获取所有手机号的设备绑定关系"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")
    uploader_id_str = request.query_params.get('uploader_id', '0')
    try:
        uploader_id = int(uploader_id_str)
    except Exception:
        uploader_id = 0

    if uploader_id:
        records = db.query(PhoneRecord).filter(
            PhoneRecord.device_key != '', PhoneRecord.user_id == uploader_id).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.device_key != '').all()

    bindings = {r.phone: r.device_key for r in records}
    print(f'[设备绑定] 查询返回 {len(bindings)} 条绑定 (uploader_id={uploader_id})')
    return JSONResponse(content={'status': 'success', 'bindings': bindings, 'count': len(bindings)})


async def client_register_legacy(request: Request, db: SQLSession):
    """旧版注册逻辑回退（无 device_key 时使用）"""
    # 直接调用原 client_register 逻辑
    # 这里需要原 register 代码...
    return JSONResponse(content={'status': 'error', 'message': '请先注册设备'}, status_code=400)


def _update_server_list(client_ip: str, hostname: str, task_count: int):
    """按外网 IP 更新服务器列表"""
    now = time.time()
    if client_ip not in server_list:
        server_list[client_ip] = {"hostname": hostname, "windows": 0, "tasks": 0, "last_seen": now}
    server_list[client_ip]["windows"] += 1
    server_list[client_ip]["tasks"] += task_count
    server_list[client_ip]["last_seen"] = now
    if hostname:
        server_list[client_ip]["hostname"] = hostname


# ===================== 客户端 API（旧版兼容） =====================
@app.post("/api/client/register")
async def client_register(request: Request, db: SQLSession = Depends(get_db)):
    """客户端注册端点 - 自动分配窗口号和账号
    注册时一次性完成：分配窗口号 + 分配账号 + 返回任务列表
    使用 asyncio.Lock 保证并发注册时窗口编号和账号分配的原子性
    新语义：多开数 = 每窗口持有手机号数，不限制每账号使用次数"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    client_uuid = data.get('client_uuid', '')
    if not client_uuid:
        raise HTTPException(status_code=400, detail='缺少 client_uuid')
    
    # 读取多开设置，按用户ID过滤账号
    try:
        uploader_id = data.get('uploader_id', 0)
        if uploader_id:
            cfg = get_user_config(uploader_id, db)
        else:
            cfg = get_user_config(1, db)
        multi_open_count = cfg.multi_open_count or 1
        if uploader_id:
            all_logged_in = db.query(PhoneRecord).filter(
                PhoneRecord.logged_in == True,
                PhoneRecord.user_id == uploader_id
            ).all()
        else:
            all_logged_in = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    except Exception as e:
        print(f'[注册] 数据库查询异常: {e}')
        multi_open_count = 1
        all_logged_in = []
    
    # 过滤黑号：仅分配白号或未判断的账号
    # 兼容多种 account_type 格式：'black' / '成功|黑号' 等都视为黑号
    all_logged_in = [r for r in all_logged_in if not _is_black_account(r.account_type)]
    all_logged_in = _filter_excluded(all_logged_in, cfg)

    client_ip = request.client.host if request.client else 'unknown'
    
    # 加锁保证注册、窗口分配、账号分配的原子性
    async with client_register_lock:
        # 如果该 UUID 已注册且心跳未超时，返回之前分配的窗口号和账号
        if client_uuid in active_client_windows:
            info = active_client_windows[client_uuid]
            if time.time() - info['last_heartbeat'] <= CLIENT_HEARTBEAT_TIMEOUT:
                info['last_heartbeat'] = time.time()
                assigned_batch = info['batch']
                # 新语义：多开数 = 每窗口持有手机号数，用公共分配函数
                window_records = allocate_tasks_for_window(all_logged_in, multi_open_count, assigned_batch)
                print(f'[注册] 窗口={assigned_batch + 1} | 多开数={multi_open_count} | 白号总数={len(all_logged_in)} | 负责手机号: {[r.phone for r in window_records]}')
                return JSONResponse(content={
                    'status': 'success', 'batch': assigned_batch,
                    'multi_open_count': multi_open_count,
                    'tasks': _build_task_response(window_records, db=db, uploader_id=uploader_id)
                })
        
        # 清理超时窗口
        now = time.time()
        expired_uuids = [cid for cid, info in active_client_windows.items()
                         if now - info['last_heartbeat'] > CLIENT_HEARTBEAT_TIMEOUT]
        for cid in expired_uuids:
            for phone, owner in list(assigned_phones.items()):
                if owner == cid:
                    del assigned_phones[phone]
            del active_client_windows[cid]
        
        # 收集已注册的活跃窗口号
        used_batches = set()
        for cid, info in active_client_windows.items():
            used_batches.add(info['batch'])
        
        # 找到最小的未被占用的窗口号
        assigned_batch = 0
        while assigned_batch in used_batches:
            assigned_batch += 1
        
        # 新语义：多开数 = 每窗口持有手机号数，用公共分配函数
        window_records = allocate_tasks_for_window(all_logged_in, multi_open_count, assigned_batch)

        # 标记这些账号为已分配（追踪用，不再限制重复分配）
        for rec in window_records:
            assigned_phones[rec.phone] = client_uuid

        phone_list = [r.phone for r in window_records]
        print(f'[注册] 窗口={assigned_batch + 1} | 多开数={multi_open_count} | 白号总数={len(all_logged_in)} | 负责手机号: {phone_list}')
        
        # 注册窗口
        active_client_windows[client_uuid] = {
            "batch": assigned_batch,
            "client_uuid": client_uuid,
            "uploader_id": uploader_id,
            "last_heartbeat": time.time(),
            "ip": client_ip,
            "hostname": data.get('hostname', ''),
            "task_count": len(window_records)
        }
        # 更新服务器列表（按 IP 聚合）
        if client_ip not in server_list:
            server_list[client_ip] = {"hostname": data.get('hostname', ''), "windows": 0, "tasks": 0, "last_seen": time.time()}
        server_list[client_ip]["windows"] += 1
        server_list[client_ip]["tasks"] += len(window_records)
        server_list[client_ip]["last_seen"] = time.time()
        if data.get('hostname', ''):
            server_list[client_ip]["hostname"] = data.get('hostname', '')
    
    return JSONResponse(content={
        'status': 'success', 'batch': assigned_batch,
        'multi_open_count': multi_open_count,
        'tasks': _build_task_response(window_records, db=db, uploader_id=uploader_id)
    })


def allocate_tasks_for_window(white_records: list, multi_open_count: int, window_index: int = 0) -> list:
    """
    新语义：为窗口分配恰好 multi_open_count 个任务（手机号）。
    multi_open_count = 每个窗口持有的手机号数量（不再是"每个账号最多N个窗口"）。

    规则：
    - 白号不足（n < M）：循环复用所有白号凑满 M 个
    - 白号充足（n >= M）：每个窗口 M 个号，由 accounts_per_window 个不同账号混合，
      每个账号重复 repeat_count 次，按窗口序号均匀分配不同账号组合
    """
    n = len(white_records)
    if n == 0:
        return []

    M = multi_open_count

    if n < M:
        # 白号不足：循环复用，凑满 M 个
        result = []
        offset = (window_index * M) % n  # 不同窗口从不同位置循环
        for i in range(M):
            result.append(white_records[(offset + i) % n])
        return result

    # 白号充足：确定每个窗口的账号组成
    if M <= 2:
        accounts_per_window = M
        repeat_count = 1
    elif M % 2 == 0:
        accounts_per_window = M // 2  # M=6→3, M=4→2, M=8→4, M=10→5
        repeat_count = 2
    elif M % 3 == 0:
        accounts_per_window = M // 3  # M=9→3
        repeat_count = 3
    else:
        accounts_per_window = M  # M=5,7 无法均匀分组，每个账号1份
        repeat_count = 1

    # 按窗口序号选不同的账号组合
    start_idx = (window_index * accounts_per_window) % n
    result = []
    for i in range(accounts_per_window):
        rec = white_records[(start_idx + i) % n]
        for _ in range(repeat_count):
            result.append(rec)

    return result


def _build_task_response(records: list, db=None, uploader_id=0) -> list:
    """构建任务响应列表。IP分配策略：手机代理(最优先) > 就绪池 > 原始池。
    独立IP优先，IP不足时共享（最多3账号/IP）。
    uploader_id: 用户ID，用于读取该用户的代理配置（开关+API地址）"""
    # 读取代理配置
    proxy_enabled = False
    proxy_api_url = ''
    MAX_SHARE_PER_IP = 3  # 共享阈值：同一IP最多分配给几个账号
    if db and uploader_id:
        try:
            up = get_user_proxy(uploader_id, db)
            if up:
                proxy_enabled = up.proxy_enabled
                proxy_api_url = up.proxy_url or ''
        except:
            pass

    def _get_best_ip():
        """获取最优IP，按代理模式控制来源
        proxy_only: 仅外部代理（就绪池 > 原始池）
        off:        不使用代理"""
        if PHONE_PROXY_MODE == 'off':
            return ''
        # 外部代理（proxy_only）
        if PHONE_PROXY_MODE == 'proxy_only':
            ip = proxy_manager.get_ready_proxy()
            if ip:
                return ip
            return proxy_manager.get_proxy(proxy_api_url)
        return ''

    tasks = []
    ip_usage_count = {}
    _assigned_new = False

    for r in records:
        proxy_ip = r.proxy_ip or ''

        # 判断是否需要代理
        _need_proxy = proxy_enabled or PHONE_PROXY_MODE == 'proxy_only'

        # 自动分配代理：需要代理且该记录无代理IP时，从池中获取
        if _need_proxy and not proxy_ip and proxy_api_url and db:
            proxy_ip = _get_best_ip()
            if proxy_ip:
                r.proxy_ip = proxy_ip
                _assigned_new = True
                try:
                    db.commit()
                except:
                    pass
        elif _need_proxy and proxy_ip:
            # 已有IP，检查是否超过共享阈值（同一IP给太多账号）
            if ip_usage_count.get(proxy_ip, 0) + 1 > MAX_SHARE_PER_IP:
                # 超过共享阈值，尝试分配独立IP（优先就绪池）
                new_ip = _get_best_ip()
                if new_ip and new_ip not in ip_usage_count:
                    proxy_manager.return_proxy(proxy_ip)
                    proxy_ip = new_ip
                    r.proxy_ip = proxy_ip
                    _assigned_new = True
                    try:
                        db.commit()
                    except:
                        pass
                    print(f'[IP分配] {r.phone} IP超共享阈值({MAX_SHARE_PER_IP})，切换为: {new_ip}')

        if proxy_ip:
            ip_usage_count[proxy_ip] = ip_usage_count.get(proxy_ip, 0) + 1

        tasks.append({
            'phone': r.phone, 'token': r.token, 'cookie': r.cookie, 'user_id': r.user_id_ext,
            'mt_device_id': r.mt_device_id, 'raw_device_id': r.raw_device_id, 'h5_did': r.h5_did,
            'h5_start_id': r.h5_start_id, 'bs_device_id': r.bs_device_id,
            'user_agent': r.user_agent, 'webview_ua': r.webview_ua, 'mt_r': r.mt_r, 'mt_sn': r.mt_sn,
            'rush_time_offset': r.rush_time_offset, 'item_code': r.item_code, 'sku_id': r.sku_id,
            'activity_id': r.activity_id, 'amount': r.amount, 'proxy_ip': proxy_ip,
        })

    # 仅在新分配IP时打印汇总，纯查询（fetch_tasks轮询）不刷屏
    if _assigned_new and _need_proxy and ip_usage_count:
        ip_dist = ', '.join(f'{ip}(x{c})' for ip, c in sorted(ip_usage_count.items(), key=lambda x: -x[1])[:10])
        print(f'[IP分配] 本轮分配完成: {len(tasks)}个账号, {len(ip_usage_count)}个IP | 就绪池: {proxy_manager.ready_pool_size()} | 分布: {ip_dist}')

    return tasks


@app.post("/api/client/get_tasks")
async def client_get_tasks(request: Request, db: SQLSession = Depends(get_db)):
    """客户端获取任务 - 按窗口号分配账号
    新语义：多开数 = 每窗口持有手机号数，不限制同一账号多窗口使用"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    uploader_id = data.get('uploader_id')
    if not uploader_id: raise HTTPException(status_code=400, detail='缺少 uploader_id')
    
    # 读取多开设置，按用户ID过滤账号
    try:
        uploader_id = data.get('uploader_id', 0)
        if uploader_id:
            cfg = get_user_config(uploader_id, db)
        else:
            cfg = get_user_config(1, db)
        multi_open_count = cfg.multi_open_count or 1
        if uploader_id:
            # 自己的账号 + 所在团队分配的账号
            from models import Team, TeamMember as TM, TeamAccount as TA
            member_team_ids = [
                mt.team_id for mt in db.query(TM).filter(TM.user_id == uploader_id).all()
            ]
            # 自己上传的 team 也包含（owner 也是成员）
            owned_team_ids = [
                t.id for t in db.query(Team).filter(Team.owner_user_id == uploader_id).all()
            ]
            all_team_ids = list(set(member_team_ids + owned_team_ids))
            # 所有团队的账号 phone 集合
            team_phones = set()
            if all_team_ids:
                mappings = db.query(TA).filter(TA.team_id.in_(all_team_ids)).all()
                team_phones = {m.phone for m in mappings}
            # 查询：自己的 + 团队账号
            if team_phones:
                all_logged_in = db.query(PhoneRecord).filter(
                    PhoneRecord.logged_in == True,
                    PhoneRecord.phone.in_(list(team_phones))
                ).all()
                # 也包含自己上传的账号（可能不在团队中）
                own_logged = db.query(PhoneRecord).filter(
                    PhoneRecord.logged_in == True,
                    PhoneRecord.user_id == uploader_id
                ).all()
                seen = {r.phone for r in all_logged_in}
                for r in own_logged:
                    if r.phone not in seen:
                        all_logged_in.append(r)
            else:
                all_logged_in = db.query(PhoneRecord).filter(
                    PhoneRecord.logged_in == True,
                    PhoneRecord.user_id == uploader_id
                ).all()
        else:
            all_logged_in = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    except Exception as e:
        print(f'[任务分发] 数据库查询异常: {e}')
        return JSONResponse(content={'status': 'error', 'message': f'数据库不可达: {str(e)[:60]}', 'tasks': []})
    
    # 过滤黑号：仅分配白号或未判断的账号
    # 兼容多种 account_type 格式：'black' / '成功|黑号' 等都视为黑号
    all_logged_in = [r for r in all_logged_in if not _is_black_account(r.account_type)]
    all_logged_in = _filter_excluded(all_logged_in, cfg)

    # 诊断：白号=0 时输出一次数据库实况（每个 uploader_id 只输出一次）
    if len(all_logged_in) == 0:
        diag_key = f"diag_baihao_{uploader_id}"
        if diag_key not in _diag_logged:
            _diag_logged[diag_key] = True
            total_all = db.query(PhoneRecord).count()
            total_logged = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).count()
            total_user_logged = db.query(PhoneRecord).filter(
                PhoneRecord.logged_in == True, PhoneRecord.phone.in_(list(team_phones) if team_phones else [])).count() if uploader_id and team_phones else (db.query(PhoneRecord).filter(
                PhoneRecord.logged_in == True, PhoneRecord.user_id == uploader_id).count() if uploader_id else total_logged)
            # 显示账号的用户分布
            from sqlalchemy import func
            user_dist = db.query(PhoneRecord.user_id, func.count(PhoneRecord.phone)).filter(
                PhoneRecord.logged_in == True).group_by(PhoneRecord.user_id).all()
            user_dist_str = ', '.join(f'user{u}={c}' for u, c in user_dist)
            # 显示 account_type 实际值
            type_samples = db.query(PhoneRecord.account_type, func.count(PhoneRecord.phone)).filter(
                PhoneRecord.logged_in == True).group_by(PhoneRecord.account_type).all()
            type_str = ', '.join(f'{t or "空"}={c}' for t, c in type_samples)
            print(f'[诊断] 白号为0！uploader_id={uploader_id} | 总账号={total_all} | 已登录(全库)={total_logged} | 已登录(本用户)={total_user_logged}')
            print(f'[诊断] user_id分布: {user_dist_str}')
            print(f'[诊断] account_type分布: {type_str}')
    
    batch = data.get('batch', 0)
    client_uuid = data.get('client_uuid', '')
    
    # 加锁保证分配的原子性
    async with client_register_lock:
        # batch=-1 表示自动分配：找到该 uploader_id 下最小的未使用窗口号
        if batch == -1:
            used_batches = set()
            for cid, info in active_client_windows.items():
                if info.get('uploader_id') == uploader_id:
                    used_batches.add(info.get('batch', 0))
            batch = 0
            while batch in used_batches:
                batch += 1
        
        # 新语义：使用公共分配函数
        assigned_tasks = allocate_tasks_for_window(all_logged_in, multi_open_count, batch)
        
        # 注册客户端窗口信息
        client_ip = request.client.host if request.client else 'unknown'
        # ⚠️ 去重：同一 IP+batch 只保留一条 active_client_windows 记录。
        #    旧客户端不调 register，只调 get_tasks（无 UUID）+ heartbeat（有 UUID），
        #    会产生 ip_batch 和 UUID 两条 key 的记录。先查找是否已有同 IP+batch 的条目。
        if not client_uuid:
            for existing_cid, existing_info in active_client_windows.items():
                if existing_info.get('ip') == client_ip and existing_info.get('batch') == batch:
                    client_uuid = existing_info.get('client_uuid', '')
                    client_id = existing_cid  # 复用已有 key
                    break
            else:
                client_id = f"{client_ip}_batch{batch}"
        else:
            client_id = client_uuid
        is_new = client_id not in active_client_windows
        active_client_windows[client_id] = {
            "batch": batch,
            "client_uuid": client_uuid,
            "uploader_id": uploader_id,
            "last_heartbeat": time.time(),
            "ip": client_ip,
            "task_count": len(assigned_tasks)
        }
        # 同步更新 server_list（IP 聚合）
        _update_server_list(client_ip, data.get('hostname', ''), len(assigned_tasks))
    
    # 每次请求都打印日志，方便追踪客户端获取了哪些任务
    phone_list = [r.phone for r in assigned_tasks]
    if is_new:
        print(f'[取任务] 🆕 新窗口{batch+1} | IP={client_ip} | 多开数={multi_open_count} | 白号总数={len(all_logged_in)} | UUID={client_uuid[:8] if client_uuid else "-"} | 下发账号: {phone_list}')
    else:
        print(f'[取任务] 🔄 窗口{batch+1} | IP={client_ip} | 下发账号: {phone_list}')
    
    return JSONResponse(content={'status': 'success', 'batch': batch, 'tasks': _build_task_response(assigned_tasks, db=db, uploader_id=uploader_id)})


@app.post("/api/client/heartbeat")
async def client_heartbeat(request: Request):
    """客户端心跳端点，每10秒调用一次，保持窗口注册状态"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    batch = data.get('batch', 0)
    client_uuid = data.get('client_uuid', '')
    client_ip = request.client.host if request.client else 'unknown'
    # 用 UUID 区分同机不同窗口，无 UUID 时降级为 ip_batch
    # ⚠️ 关键：如果 get_tasks 已为此窗口创建了 ip_batch 条目，心跳复用同一 key
    #    避免同一窗口产生两条 active_client_windows 记录
    ip_key = f"{client_ip}_batch{batch}"
    if client_uuid:
        client_id = client_uuid if ip_key not in active_client_windows else ip_key
    else:
        client_id = ip_key
    
    # 向后兼容：旧客户端不发 uploader_id，保留注册时存储的值不覆盖
    uploader_id = data.get('uploader_id', 0)
    existing = active_client_windows.get(client_id, {})
    if not uploader_id:
        uploader_id = existing.get('uploader_id', 0)
    is_new_hb = client_id not in active_client_windows
    
    active_client_windows[client_id] = {
        "batch": batch,
        "client_uuid": client_uuid,
        "uploader_id": uploader_id,
        "last_heartbeat": time.time(),
        "ip": client_ip,
        "hostname": data.get('hostname', existing.get('hostname', '')),
        "task_count": data.get('task_count', 0),
        "window_key": data.get('window_key', existing.get('window_key', '')),
        "device_key": data.get('device_key', existing.get('device_key', ''))
    }
    # 更新服务器列表（按 IP 聚合，基于 active_client_windows 实时计算，确保窗口数准确）
    now_ts = time.time()
    _hb_hostname = data.get('hostname', existing.get('hostname', ''))
    # 统计该 IP 下的活跃窗口数和任务数
    ip_win_count = sum(1 for cid, info in active_client_windows.items()
                       if info.get('ip') == client_ip and now_ts - info.get('last_heartbeat', 0) <= CLIENT_HEARTBEAT_TIMEOUT)
    ip_task_sum = sum(info.get('task_count', 0) for cid, info in active_client_windows.items()
                      if info.get('ip') == client_ip and now_ts - info.get('last_heartbeat', 0) <= CLIENT_HEARTBEAT_TIMEOUT)
    server_list[client_ip] = {
        "hostname": _hb_hostname or server_list.get(client_ip, {}).get('hostname', ''),
        "windows": ip_win_count,
        "tasks": ip_task_sum,
        "last_seen": now_ts
    }
    # 持久化：更新 WindowKey 最后心跳
    window_key = data.get('window_key', '')
    if window_key:
        try:
            db_local = SessionLocal()
            win = db_local.query(WindowKey).filter(WindowKey.window_key == window_key).first()
            if win:
                win.last_seen_at = datetime.datetime.utcnow()
                win.status = 'active'
                db_local.commit()
            db_local.close()
        except Exception:
            pass
    # 每次心跳顺便清理过期窗口和超时重启追踪
    get_active_client_count()
    # 统计该 uploader_id 名下有多少活跃设备
    now_ts = time.time()
    device_count = sum(1 for cid, info in active_client_windows.items()
                       if info.get('uploader_id') == uploader_id
                       and now_ts - info.get('last_heartbeat', 0) <= CLIENT_HEARTBEAT_TIMEOUT)
    # 仅首次心跳打印，后续静默避免刷屏
    if is_new_hb:
        window_no = batch + 1 if batch >= 0 else '?'
        print(f'[心跳] 🟢 窗口{window_no} 首次连接 | IP={client_ip} | 窗口={ip_win_count}个 | 任务={ip_task_sum}个 | 该用户设备总数={device_count}台')
    # 返回最新库存状态 + 服务重启指令
    # 检查待处理重启：用户点击按钮时 server_list 为空，等客户端上线后补发
    if _pending_server_restart and _pending_server_restart.get('version', 0) > 0:
        pending_ver = _pending_server_restart['version']
        if client_ip not in server_restart_flags or server_restart_flags[client_ip].get('version', 0) < pending_ver:
            server_restart_flags[client_ip] = {"flag": True, "version": pending_ver, "trigger_time": time.time()}
            print(f'[服务重启] 补发重启指令给新上线的 {client_ip} v={pending_ver}')
        # ⚠️ 补发后清除待处理标志（不立即清除，等所有已知IP都收到后再清）
        #    但这里简化：只要有一个客户端收到了，就认为补发完成
        _pending_server_restart.clear()
    # 清理过期的 server_restart_flags（超过120秒未执行的指令自动过期，防止重启后无限循环）
    RESTART_FLAG_TIMEOUT = 120
    expired_flags = [ip for ip, flag in server_restart_flags.items()
                     if now_ts - flag.get('trigger_time', 0) > RESTART_FLAG_TIMEOUT]
    for ip in expired_flags:
        del server_restart_flags[ip]
        _server_restart_logged.pop(ip, None)
    # 检查服务器级重启指令（按客户端IP匹配，而非hostname）
    client_ip_for_restart = data.get('ip', '') or client_ip
    restart_flag = server_restart_flags.get(client_ip_for_restart, {})
    server_restart_req = restart_flag.get('flag', False)
    server_restart_ver = restart_flag.get('version', 0)
    if server_restart_req and server_restart_ver > 0:
        if _server_restart_logged.get(client_id, 0) != server_restart_ver:
            _server_restart_logged[client_id] = server_restart_ver
            window_no = batch + 1 if batch >= 0 else '?'
            print(f'[服务重启] 窗口{window_no} 收到重启服务指令 v={server_restart_ver} | IP={client_ip_for_restart}')
    
    return JSONResponse(content={
        'status': 'success',
        'device_count': device_count,
        'is_stock_available': is_stock_available,
        'stock_monitoring_active': stock_monitoring_active,
        'server_restart_required': server_restart_req,
        'server_restart_version': server_restart_ver,
    })


def get_active_client_count() -> int:
    """返回活跃客户端窗口数量（心跳未超时）"""
    now = time.time()
    expired = [cid for cid, info in active_client_windows.items()
               if now - info['last_heartbeat'] > CLIENT_HEARTBEAT_TIMEOUT]
    for cid in expired:
        del active_client_windows[cid]
        _server_restart_logged.pop(cid, None)  # 同步清理去重记录
    return len(active_client_windows)


# ===================== 客户端运维上报端点 =====================
_startup_hosts: dict = {}  # {hostname: {"windows": int, "tasks": int}}

@app.post("/api/client/startup_report")
async def client_startup_report(request: Request):
    """启动部署上报：客户端启动完成后上报主机标识、窗口号、账号数"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    hostname = data.get('hostname', '?')
    batch = data.get('batch', 0)
    task_count = data.get('task_count', 0)
    client_uuid = data.get('client_uuid', '')
    window_no = batch + 1 if batch >= 0 else '?'
    
    # 按主机名累计
    if hostname not in _startup_hosts:
        _startup_hosts[hostname] = {"windows": 0, "tasks": 0}
    _startup_hosts[hostname]["windows"] += 1
    _startup_hosts[hostname]["tasks"] += task_count
    acc = _startup_hosts[hostname]
    
    print(f'[部署上线] 🖥 {hostname} | 窗口{window_no} UUID={client_uuid[:8]} | 账号={task_count} | 该主机累计={acc["windows"]}窗口/{acc["tasks"]}账号')
    return JSONResponse(content={'status': 'success'})


@app.post("/api/client/rush_success_report")
async def client_rush_success_report(request: Request):
    """抢购成功即时上报：任一账号抢购成功立即通知服务端"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    phone = data.get('phone', '?')
    hostname = data.get('hostname', '?')
    batch = data.get('batch', 0)
    team_name = data.get('team_name', '')
    window_no = batch + 1 if batch >= 0 else '?'
    
    team_info = f' | 团队={team_name}' if team_name else ''
    print(f'[抢购成功] 🎯 {phone} | 主机={hostname} | 窗口{window_no}{team_info}')
    return JSONResponse(content={'status': 'success'})


@app.get("/api/servers")
async def api_servers(request: Request):
    """网站仪表盘：返回服务器列表（hostname、IP、窗口数、状态）"""
    # 清理过期服务器（超过60秒无心跳则移除）
    now = time.time()
    SERVER_TIMEOUT = 60
    expired_hosts = [h for h, s in server_list.items()
                     if now - s.get('last_seen', 0) > SERVER_TIMEOUT]
    for h in expired_hosts:
        del server_list[h]
    
    # 重新计算每台服务器的活跃窗口数（按 IP 聚合）
    server_windows = {}
    server_tasks = {}
    for cid, info in active_client_windows.items():
        if now - info['last_heartbeat'] <= CLIENT_HEARTBEAT_TIMEOUT:
            ip = info.get('ip', 'unknown')
            if ip not in server_windows:
                server_windows[ip] = 0
                server_tasks[ip] = 0
            server_windows[ip] += 1
            server_tasks[ip] += info.get('task_count', 0)
    
    servers = []
    for ip, sinfo in server_list.items():
        win_count = server_windows.get(ip, 0)
        task_count = server_tasks.get(ip, 0)
        last_seen = sinfo.get('last_seen', 0)
        age = int(now - last_seen) if last_seen > 0 else 999
        restart_info = server_restart_flags.get(ip, {})
        servers.append({
            'hostname': sinfo.get('hostname', ip),
            'ip': ip,
            'windows': win_count,
            'tasks': task_count,
            'last_seen_age': age,
            'online': age < SERVER_TIMEOUT,
            'restarting': restart_info.get('flag', False),
        })
    servers.sort(key=lambda s: s['ip'])
    return JSONResponse(content={
        'server_count': len(servers),
        'total_windows': sum(s['windows'] for s in servers),
        'servers': servers
    })


@app.post("/api/client/restart_servers")
async def client_restart_servers(request: Request, user: User = Depends(get_current_user)):
    """网站按钮触发：通知指定 IP 或所有在线服务器执行服务重启（随机0~10秒延迟）
    按 IP 定位服务器，客户端心跳检测到 server_restart_required 后 systemctl restart，~5秒完成
    若 server_list 为空，自动从 active_client_windows 重建"""
    global server_restart_flags, server_list
    data = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    target_ip = data.get('ip', '').strip() or data.get('hostname', '').strip()  # 兼容旧字段名
    
    now = time.time()
    print(f'【诊断】restart_servers 被调用 | server_list={list(server_list.keys())} | active_windows={len(active_client_windows)} | server_restart_flags={list(server_restart_flags.keys())}')
    
    # 若 server_list 为空，从 active_client_windows 重建 IP 聚合数据
    if not server_list:
        for cid, info in active_client_windows.items():
            if now - info.get('last_heartbeat', 0) <= CLIENT_HEARTBEAT_TIMEOUT:
                ip = info.get('ip', '')
                if ip and ip != 'unknown':
                    if ip not in server_list:
                        server_list[ip] = {"hostname": info.get('hostname', ''), "windows": 0, "tasks": 0, "last_seen": now}
                    server_list[ip]["windows"] += 1
                    server_list[ip]["tasks"] += info.get('task_count', 0)
                    server_list[ip]["last_seen"] = max(server_list[ip]["last_seen"], info.get('last_heartbeat', 0))
        if server_list:
            print(f'【重启所有服务】 从 active_client_windows 重建了 {len(server_list)} 台服务器信息')
    
    triggered = []
    
    if target_ip:
        ver = server_restart_flags.get(target_ip, {}).get('version', 0) + 1
        server_restart_flags[target_ip] = {"flag": True, "version": ver, "trigger_time": now}
        triggered.append(target_ip)
        print(f'【重启所有服务】 用户 {user.username} 触发 IP={target_ip} 重启 v={ver}')
    else:
        for ip in list(server_list.keys()):
            if now - server_list[ip].get('last_seen', 0) <= CLIENT_HEARTBEAT_TIMEOUT * 4:
                ver = server_restart_flags.get(ip, {}).get('version', 0) + 1
                server_restart_flags[ip] = {"flag": True, "version": ver, "trigger_time": now}
                triggered.append(ip)
        if triggered:
            print(f'【重启所有服务】 用户 {user.username} 触发全部 {len(triggered)} 台服务器重启')
        else:
            # 无在线服务器：记录待处理重启，等客户端上线后心跳时补发
            _pending_server_restart['version'] = _pending_server_restart.get('version', 0) + 1
            _pending_server_restart['trigger_time'] = now
            print(f'【重启所有服务】 用户 {user.username} 触发重启（当前无在线服务器，已记录待处理 v={_pending_server_restart["version"]}，客户端上线后自动执行）')
    
    return JSONResponse(content={
        'status': 'success',
        'message': f'已触发 {len(triggered)} 台服务器重启' if triggered else f'当前无在线服务器，重启指令已记录，客户端上线后自动执行',
        'triggered': triggered
    })


@app.get("/api/client/active_windows")
async def client_active_windows(request: Request):
    """客户端活跃窗口详情端点"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    count = get_active_client_count()
    now = time.time()
    details = []
    for cid, info in active_client_windows.items():
        if now - info['last_heartbeat'] <= CLIENT_HEARTBEAT_TIMEOUT:
            details.append({
                'client_id': cid, 'batch': info['batch'], 'ip': info['ip'],
                'uploader_id': info.get('uploader_id', 0),
                'task_count': info['task_count'],
                'last_heartbeat_age': int(now - info['last_heartbeat'])
            })
    return JSONResponse(content={
        'active_client_windows': count, 'details': details
    })


@app.get("/api/client/inventory_longpoll")
async def client_inventory_longpoll(request: Request, db: SQLSession = Depends(get_db)):
    """客户端长轮询端点 - 库存状态变更时毫秒级响应
    客户端发送请求带上 last_status 参数，服务端挂起连接直到状态变更或超时
    """
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    global stock_monitoring_active, is_stock_available
    cfg = get_user_config(1, db)  # admin 的库存监控全局状态
    db_monitoring = cfg.inventory_monitoring if cfg else 0
    if db_monitoring == 1 and not stock_monitoring_active:
        stock_monitoring_active = True
    elif db_monitoring == 0 and stock_monitoring_active:
        stock_monitoring_active = False

    timeout_sec = min(float(request.query_params.get('timeout', '30')), 60)
    last_status = request.query_params.get('last_status', 'unknown')

    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        # 计算当前状态
        if is_stock_available:
            current_status = 'available'
        elif stock_monitoring_active:
            current_status = 'monitoring'
        else:
            current_status = 'unknown'

        # 状态发生变更，立即返回
        if current_status != last_status:
            return JSONResponse(content={
                'stock_monitoring_active': stock_monitoring_active,
                'is_stock_available': is_stock_available,
                'active_monitors_count': len(active_monitors),
                'inventory_monitoring_db': db_monitoring,
                'active_client_windows': get_active_client_count(),
                'status_changed': True,
                'current_status': current_status
            })
        # 每200ms检查一次状态变更
        await asyncio.sleep(0.2)

    # 超时，返回当前状态
    if is_stock_available:
        current_status = 'available'
    elif stock_monitoring_active:
        current_status = 'monitoring'
    else:
        current_status = 'unknown'
    return JSONResponse(content={
        'stock_monitoring_active': stock_monitoring_active,
        'is_stock_available': is_stock_available,
        'active_monitors_count': len(active_monitors),
        'inventory_monitoring_db': db_monitoring,
        'active_client_windows': get_active_client_count(),
        'status_changed': False,
        'current_status': current_status
    })


@app.post("/api/import_accounts_from_json")
async def api_import_accounts_from_json(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """
    手动触发：将 {username}_accounts.json 中的账号导入到 phone_record 表
    根据当前登录用户自动选择对应的备份文件（如 iplala → iplala_accounts.json）
    """
    total = import_accounts_from_json(db, default_username=user.username)
    return JSONResponse(content={'status': 'success', 'message': f'导入完成: {total} 个账号（文件: {user.username}_accounts.json）'})


@app.post("/api/client/request_replacement_tasks")
async def client_request_replacement_tasks(request: Request, db: SQLSession = Depends(get_db)):
    """客户端请求继续分配任务
    新语义：成功几个就补几个白号，保持窗口始终满多开数个手机号
    不限制同一账号多窗口使用"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    succeeded_phones = data.get('succeeded_phones', [])
    client_uuid = data.get('client_uuid', '')
    request_count = data.get('request_count', 1)  # 客户端指定请求几个新账号
    uploader_id = data.get('uploader_id', 0)
    
    try:
        if uploader_id:
            cfg = get_user_config(uploader_id, db)
        else:
            cfg = get_user_config(1, db)
        multi_open_count = cfg.multi_open_count or 1
        multi_open_enabled = cfg.multi_open_enabled
    except Exception as e:
        print(f'[继续分配] 数据库异常: {e}')
        return JSONResponse(content={'status': 'error', 'message': str(e)[:60], 'tasks': []})
    
    # 继续分配关闭时，返回空列表（客户端不再分配）
    if not multi_open_enabled:
        print(f'[继续分配] UUID={client_uuid}, 继续分配已关闭，不分配新账号')
        return JSONResponse(content={'status': 'success', 'tasks': []})
    
    # 查找所有白号（未黑号、已登录），排除已成功的，按用户ID过滤
    if uploader_id:
        all_white = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True,
            PhoneRecord.user_id == uploader_id,
            ~PhoneRecord.bid_result.contains('成功')
        ).all()
    else:
        all_white = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True,
            ~PhoneRecord.bid_result.contains('成功')
        ).all()
    # 过滤黑号
    all_white = [r for r in all_white if not _is_black_account(r.account_type)]
    all_white = _filter_excluded(all_white, cfg)

    # 过滤掉刚刚成功的号（这些号本窗口已经有了成功的记录）
    available = [r for r in all_white if r.phone not in succeeded_phones]
    
    # 新语义：不限制同一账号多窗口使用，凑满 request_count 个
    # 白号充足时取前 request_count 个；不足时循环复用
    n = len(available)
    if n == 0:
        print(f'[继续分配] UUID={client_uuid} | 已成功={len(succeeded_phones)} | 无可分配白号（所有白号均已成功或为黑号）')
        return JSONResponse(content={'status': 'success', 'tasks': []})
    
    assigned = []
    for i in range(request_count):
        assigned.append(available[i % n])
    
    print(f'[继续分配] UUID={client_uuid} | 已成功={len(succeeded_phones)} | 请求={request_count} | 可用白号={n} | 实际分配={len(assigned)}')
    
    return JSONResponse(content={'status': 'success', 'tasks': _build_task_response(assigned, db=db, uploader_id=uploader_id)})


@app.post("/api/client/broadcast_rush_status")
async def client_broadcast_rush_status(request: Request):
    """客户端广播抢购状态变更：start_rush / stop_rush
    服务端收到后更新库存广播状态，通知所有其他客户端"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    action = data.get('action', '')
    global inventory_broadcast_status, is_stock_available
    if action == 'start_rush':
        is_stock_available = True
        await broadcast_inventory_status('available')
        print(f'[广播] 客户端触发：开始抢购')
    elif action == 'stop_rush':
        is_stock_available = False
        await broadcast_inventory_status('soldout')
        print(f'[广播] 客户端触发：停止抢购，回到库存监控')
    return JSONResponse(content={'status': 'success', 'message': f'广播状态已更新: {action}'})


@app.post("/api/client/report_result")
async def client_report_result(request: Request, db: SQLSession = Depends(get_db)):
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN: raise HTTPException(status_code=403)
    data = await request.json()
    phone = data.get('phone'); success = data.get('success', False)
    order_id = data.get('order_id', ''); h5_url = data.get('h5_url', ''); error_msg = data.get('error', '')
    ip_blocked = data.get('ip_blocked', False)  # 客户端上报IP被封
    account_black = data.get('account_black', False)  # 客户端上报账号被黑
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record: raise HTTPException(status_code=404, detail='手机号不存在')
    
    # 获取该账号所属用户的代理API地址
    record_up = get_user_proxy(record.user_id or 1, db) if record.user_id else get_user_proxy(1, db)
    proxy_api_url = record_up.proxy_url if record_up else ''
    
    # === 抢购过程IP被封处理：立即测试并更换IP ===
    if ip_blocked and record.proxy_ip:
        print(f'[抢购] {phone} IP被封 | 旧IP={record.proxy_ip}，丢弃换新IP')
        proxy_manager.discard_proxy(record.proxy_ip)
        uid = record.user_id or 1
        new_proxy = await _test_and_assign_ip(uid, proxy_api_url, db)
        record.proxy_ip = new_proxy
        print(f'[抢购] {phone} 新IP: {new_proxy or "无可用IP"}')
    
    # === 账号被黑处理：立即下线，回收IP给其他账号用 ===
    if account_black:
        record.account_type = 'black'
        record.logged_in = False
        # 回收该黑号的代理IP，供其他白号复用
        if record.proxy_ip:
            proxy_manager.return_proxy(record.proxy_ip)
            print(f'[抢购] {phone} 账号被黑，回收IP: {record.proxy_ip}')
        record.proxy_ip = ''  # 清空绑定，让新账号分配时从池中取
        print(f'[抢购] {phone} 账号被黑，立即下线')
    
    if success:
        record.bid_result = f"成功-订单{order_id}"; record.balance = "待支付"
        record.pay_url_alipay = data.get('pay_url_alipay', '') or ''
        record.pay_url_wechat = data.get('pay_url_wechat', '') or ''
        record.pay_url = data.get('pay_url_unionpay', '') or ''  # 云闪付/银联 → pay_url
        record.pay_status = '待支付'
        if h5_url: qrcode.make(h5_url).save(os.path.join(QRCODE_FOLDER, f"{phone}.png"))
    else: record.bid_result = f"失败-{error_msg[:50]}"
    record.last_updated = datetime.datetime.utcnow(); db.commit()
    return JSONResponse(content={'status': 'success', 'new_proxy_ip': record.proxy_ip})


# ===================== 客户端日志上传 =====================
LOG_DIR_CLIENT = os.path.join(BASEDIR, 'client_logs')
os.makedirs(LOG_DIR_CLIENT, exist_ok=True)

CDN_LOG_DIR = os.path.join(BASEDIR, 'cdn_logs')
os.makedirs(CDN_LOG_DIR, exist_ok=True)


@app.post("/api/client/report_cdn_lock")
async def client_report_cdn_lock(request: Request):
    """接收客户端上报的CDN 4030锁定事件（一轮探测汇总），写入专用txt供分析"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    items = data.get('items', [])
    client_time = data.get('client_time', '')
    client_uuid = data.get('uuid', 'unknown')
    batch = data.get('batch', 0)
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    filename = f"cdn_{date_str}.txt"
    filepath = os.path.join(CDN_LOG_DIR, filename)
    if not items:
        return JSONResponse(content={'status': 'empty'})
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"[{client_time}] batch={batch} uuid={client_uuid}\n")
        for item in items:
            phone = item.get('phone', '?')
            mode = item.get('mode', '?')
            http_status = item.get('http_status', 0)
            code = item.get('code', '')
            msg = item.get('msg', '')
            srv_time = item.get('srv_time', '')
            f.write(f"  {phone} | mode={mode} | http={http_status} | code={code} | msg={msg} | srv_time={srv_time}\n")
        f.write('\n')
    return JSONResponse(content={'status': 'success'})


@app.post("/api/client/upload_log")
async def client_upload_log(request: Request):
    """接收客户端上传的日志文件，存储到 client_logs/ 目录
    文件名格式: 日_ip_uuid.txt"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    client_uuid = data.get('uuid', 'unknown')
    log_content = data.get('log', '')
    day = data.get('day', datetime.datetime.now().strftime('%d'))
    public_ip = data.get('public_ip', 'unknown')
    if not log_content:
        print(f'[日志上传] 收到空日志 uuid={client_uuid}')
        return JSONResponse(content={'status': 'empty'})
    filename = f"{day}_{public_ip}_{client_uuid}.txt"
    filepath = os.path.join(LOG_DIR_CLIENT, filename)
    print(f'[日志上传] 写入 {filepath} ({len(log_content)} 字节)')
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(log_content)
            if not log_content.endswith('\n'):
                f.write('\n')
            f.flush()
            os.fsync(f.fileno())  # 强制落盘
        print(f'[日志上传] 保存成功: {filename}')
    except Exception as e:
        print(f'[日志上传] 保存失败: {e}')
        return JSONResponse(content={'status': 'error', 'message': str(e)})
    return JSONResponse(content={'status': 'success', 'file': filename})


# ===================== 代理IP管理 API =====================

@app.get("/api/proxy/pool_size")
async def proxy_pool_size(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """获取代理池状态：池中可用IP数、已分配IP数、已淘汰IP数"""
    pool_count = proxy_manager.pool_size()
    # 统计数据库中已绑定IP的账号数
    if user.username.lower() == 'admin':
        bound_count = db.query(PhoneRecord).filter(PhoneRecord.proxy_ip != '').count()
        total_accounts = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).count()
    else:
        bound_count = db.query(PhoneRecord).filter(PhoneRecord.proxy_ip != '', PhoneRecord.user_id == user.id).count()
        total_accounts = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True, PhoneRecord.user_id == user.id).count()
    discarded_count = len(proxy_manager.all_discarded())
    return JSONResponse(content={
        'pool_count': pool_count,
        'bound_count': bound_count,
        'discarded_count': discarded_count,
        'total_accounts': total_accounts
    })


@app.post("/api/proxy/test")
async def proxy_test_ip(request: Request, user: User = Depends(get_current_user)):
    """手动测试单个代理IP是否可用"""
    data = await request.json()
    proxy_url = data.get('proxy_url', '').strip()
    if not proxy_url:
        return JSONResponse(content={'status': 'error', 'message': '缺少 proxy_url'})
    result = await _test_proxy_ip(proxy_url)
    return JSONResponse(content={'status': 'success', 'result': result})


@app.post("/api/proxy/purge")
async def proxy_purge_manual(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """手动触发代理IP净化（立即执行一次全量扫描）"""
    print(f'[代理净化] 用户 {user.username} 手动触发净化')
    await _purge_all_dead_ips(db)
    return JSONResponse(content={'status': 'success', 'message': '代理净化完成'})


@app.post("/api/proxy/replace")
async def proxy_replace_for_account(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """为指定账号替换代理IP（自动测试新IP可用性）"""
    data = await request.json()
    phone = str(data.get('phone', '')).strip()
    if not phone:
        return JSONResponse(content={'status': 'error', 'message': '手机号不能为空'})
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone, PhoneRecord.user_id == user.id).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '账号不存在'})
    # 丢弃旧IP
    old_ip = record.proxy_ip
    if old_ip:
        proxy_manager.discard_proxy(old_ip)
        print(f'[IP替换] {phone} 旧IP已丢弃: {old_ip}')
    # 获取用户代理配置
    up = get_user_proxy(user.id, db)
    proxy_api_url = up.proxy_url if up else ''
    if not proxy_api_url:
        return JSONResponse(content={'status': 'error', 'message': '未配置代理API'})
    # 分配并测试新IP
    new_ip = await _test_and_assign_ip(user.id, proxy_api_url, db)
    if new_ip:
        record.proxy_ip = new_ip
        db.commit()
        return JSONResponse(content={'status': 'success', 'new_ip': new_ip, 'old_ip': old_ip})
    else:
        return JSONResponse(content={'status': 'error', 'message': '无可用代理IP，请检查代理池'})


@app.post("/api/client/report_ip_blocked")
async def client_report_ip_blocked(request: Request, db: SQLSession = Depends(get_db)):
    """
    客户端上报IP被封（抢购过程中）→ 立即淘汰并分配新IP
    返回新IP地址供客户端即时切换
    """
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    phone = data.get('phone', '')
    blocked_ip = data.get('blocked_ip', '')
    uploader_id = data.get('uploader_id', 0)

    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return JSONResponse(content={'status': 'error', 'message': '账号不存在'})

    # 丢弃被封IP
    if blocked_ip:
        proxy_manager.discard_proxy(blocked_ip)
        print(f'[IP封禁] {phone} IP已淘汰: {blocked_ip}')

    # 获取代理配置
    uid = uploader_id or record.user_id or 1
    up = get_user_proxy(uid, db)
    proxy_api_url = up.proxy_url if up else ''

    # 分配新IP（自动测试可用性）
    new_ip = await _test_and_assign_ip(uid, proxy_api_url, db)
    if new_ip:
        record.proxy_ip = new_ip
        db.commit()
        print(f'[IP封禁] {phone} 新IP: {new_ip}')
        return JSONResponse(content={'status': 'success', 'new_ip': new_ip})
    else:
        record.proxy_ip = ''
        db.commit()
        return JSONResponse(content={'status': 'error', 'message': '无可用IP'})


@app.post("/api/client/urgent_replace")
async def client_urgent_replace(request: Request, db: SQLSession = Depends(get_db)):
    """
    4秒抢购窗口内的紧急黑号替换端点 — 极速返回一个白号

    客户端在抢购窗口中发现黑号时调用此端点：
    1. 即时标记该账号为黑号
    2. 不等待DB flush，立即返回一个可用白号

    超时策略：如果2秒内DB无响应，返回空（客户端不等待，继续抢购）
    """
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    black_phone = data.get('black_phone', '')
    uploader_id = data.get('uploader_id', 0)
    client_uuid = data.get('client_uuid', '')

    # 1. 异步标记黑号（不阻塞响应）
    if black_phone:
        try:
            rec = db.query(PhoneRecord).filter(PhoneRecord.phone == black_phone).first()
            if rec:
                rec.account_type = 'black'
                rec.logged_in = False
                db.commit()
        except Exception:
            db.rollback()

    # 2. 极速查找一个白号
    uid = uploader_id or 1
    cfg = get_user_config(uid, db)
    try:
        # 先用缓存回退
        actual_uid = uid
        white = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True,
            PhoneRecord.user_id == actual_uid
        ).all()
        white = [r for r in white if not _is_black_account(r.account_type)]
        white = _filter_excluded(white, cfg)

        if white:
            r = white[0]
            tasks = _build_task_response([r], db=db, uploader_id=uid)
            return JSONResponse(content={
                'status': 'success',
                'task': tasks[0] if tasks else {}
            })
    except Exception as e:
        print(f'[紧急替换] 查询异常: {e}')

    return JSONResponse(content={'status': 'empty', 'task': None})


@app.post("/api/client/report_inventory")
async def client_report_inventory(request: Request):
    """
    客户端上报库存发现
    服务端接收后立即更新库存状态，并通过树状广播通知所有其他客户端
    """
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    phone = data.get('phone', 'unknown')
    item_code = data.get('item_code', '')
    available = data.get('available', 0)
    print(f'[库存报告] 客户端 {phone} 上报库存 | 商品={item_code} | 可用={available}')
    global inventory_broadcast_status, is_stock_available
    if available > 0:
        is_stock_available = True
        await broadcast_inventory_status('available')
    else:
        is_stock_available = False
        await broadcast_inventory_status('soldout')
    return JSONResponse(content={'status': 'success', 'message': '库存状态已更新'})


@app.post("/api/client/broadcast_receive")
async def client_broadcast_receive(request: Request):
    """
    客户端接收广播的确认端点
    服务端树状广播时调用此端点通知客户端库存状态变更
    """
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    data = await request.json()
    status = data.get('status', 'unknown')
    msg_type = data.get('type', '')
    client_id = request.client.host if request.client else 'unknown'
    print(f'[广播] 客户端 {client_id} 确认收到通知 | 类型={msg_type} | 状态={status}')
    return JSONResponse(content={'status': 'success', 'message': '广播已确认'})


# ===================== 客户端打包下载 API =====================
def _run_build_sync(build_id: str, user_id: int):
    """同步执行打包（在独立线程中运行）"""
    try:
        from build_client import build_exe
        path = build_exe(user_id)
        if path:
            build_jobs[build_id]['status'] = 'done'
            build_jobs[build_id]['exe_path'] = path
        else:
            build_jobs[build_id]['status'] = 'error'
    except Exception as e:
        print(f'[打包] 构建异常: {e}')
        build_jobs[build_id]['status'] = 'error'


@app.get("/api/client/check_build")
async def check_client_build(request: Request, user: User = Depends(get_current_user)):
    """检查当前用户是否有已构建的客户端"""
    zip_name = f'moutai_client_u{user.id}.zip'
    zip_path = os.path.join(BUILDS_DIR, zip_name)
    
    # 检查是否正在构建
    for bid, job in build_jobs.items():
        if job.get('user_id') == user.id and job['status'] == 'building':
            elapsed = time.time() - job.get('started', time.time())
            return JSONResponse(content={
                'ready': False, 'status': 'building',
                'build_id': bid, 'elapsed_seconds': int(elapsed)
            })
    
    if os.path.exists(zip_path):
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        return JSONResponse(content={
            'ready': True, 'status': 'available',
            'download_url': f'/api/download_client',
            'size_mb': round(size_mb, 1)
        })
    
    return JSONResponse(content={'ready': False, 'status': 'not_built'})


@app.post("/api/build_client")
async def build_client_exe(request: Request, user: User = Depends(get_current_user)):
    """触发客户端EXE构建（后台执行）"""
    import uuid as _uuid
    
    async with _build_lock:
        # 检查是否已在构建中
        for bid, job in list(build_jobs.items()):
            if job.get('user_id') == user.id and job['status'] == 'building':
                elapsed = time.time() - job.get('started', time.time())
                if elapsed < 120:  # 2分钟内不重复构建
                    return JSONResponse(content={
                        'status': 'building', 'build_id': bid,
                        'message': f'正在构建中...（已等待{int(elapsed)}秒）'
                    })
                else:
                    build_jobs[bid]['status'] = 'timeout'
        
        # 检查是否已有构建好的客户端
        zip_name = f'moutai_client_u{user.id}.zip'
        zip_path = os.path.join(BUILDS_DIR, zip_name)
        if os.path.exists(zip_path):
            size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            return JSONResponse(content={
                'status': 'ready',
                'download_url': f'/api/download_client',
                'size_mb': round(size_mb, 1),
                'message': '客户端已就绪，可直接下载'
            })
        
        # 发起新构建
        build_id = _uuid.uuid4().hex[:12]
        build_jobs[build_id] = {
            'status': 'building', 'user_id': user.id,
            'started': time.time(), 'exe_path': None
        }
        
        # 在独立线程中运行打包（避免阻塞 async event loop）
        import threading
        t = threading.Thread(target=_run_build_sync, args=(build_id, user.id), daemon=True)
        t.start()
        
        return JSONResponse(content={
            'status': 'building', 'build_id': build_id,
            'message': '开始构建客户端，预计需要30-60秒...'
        })


@app.get("/api/build_status/{build_id}")
async def build_status(build_id: str, user: User = Depends(get_current_user)):
    """轮询构建状态"""
    job = build_jobs.get(build_id)
    if not job:
        return JSONResponse(content={'status': 'unknown', 'message': '构建任务不存在'})
    
    elapsed = time.time() - job.get('started', time.time())
    
    if job['status'] == 'done':
        exe_path = job.get('exe_path', '')
        size_mb = os.path.getsize(exe_path) / (1024 * 1024) if os.path.exists(exe_path) else 0
        return JSONResponse(content={
            'status': 'done', 'download_url': f'/api/download_client',
            'size_mb': round(size_mb, 1), 'elapsed_seconds': int(elapsed)
        })
    elif job['status'] == 'error':
        return JSONResponse(content={'status': 'error', 'message': '构建失败，请联系管理员'})
    else:
        return JSONResponse(content={
            'status': 'building', 'elapsed_seconds': int(elapsed),
            'message': f'正在打包...（已耗时{int(elapsed)}秒）'
        })


@app.get("/api/download_client")
async def download_client(user: User = Depends(get_current_user)):
    """下载当前用户的客户端(ZIP压缩包)"""
    zip_name = f'moutai_client_u{user.id}.zip'
    zip_path = os.path.join(BUILDS_DIR, zip_name)
    
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail='客户端尚未构建，请先点击构建按钮')
    
    return FileResponse(
        zip_path,
        filename=zip_name,
        media_type='application/zip'
    )


# ===================== 团队管理 API =====================

# ---------- 团队登录/仪表盘（独立站点）----------
@app.get("/team/login", response_class=HTMLResponse)
async def team_login_page(request: Request):
    flash_messages = request.session.pop("_team_flash", [])
    return templates.TemplateResponse(request, "team_login.html", {"flash_messages": flash_messages})

@app.post("/team/login", response_class=HTMLResponse)
async def team_login_post(request: Request, db: SQLSession = Depends(get_db)):
    form = await request.form()
    username = form.get('username', '').strip()
    password = form.get('password', '').strip()
    team = db.query(Team).filter(Team.login_username == username).first()
    if team and check_password_hash(team.password_hash, password):
        request.session["team_id"] = team.id
        request.session["team_name"] = team.name
        request.session["team_login_username"] = team.login_username
        return RedirectResponse(url="/team/dashboard", status_code=303)
    request.session["_team_flash"] = [("error", "团队账号或密码错误")]
    return RedirectResponse(url="/team/login", status_code=303)

@app.get("/team/logout")
async def team_logout(request: Request):
    request.session.pop("team_id", None)
    request.session.pop("team_name", None)
    request.session.pop("team_login_username", None)
    return RedirectResponse(url="/team/login")

def get_current_team(request: Request, db: SQLSession = Depends(get_db)):
    """获取当前登录的团队"""
    team_id = request.session.get("team_id")
    if not team_id:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/team/login"})
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/team/login"})
    return team

@app.get("/team/dashboard", response_class=HTMLResponse)
async def team_dashboard(request: Request, team: Team = Depends(get_current_team), db: SQLSession = Depends(get_db)):
    """团队独立仪表盘 - 手机端自适应"""
    # 获取团队名下的所有账号
    team_accounts = db.query(TeamAccount).filter(TeamAccount.team_id == team.id).all()
    phones = [ta.phone for ta in team_accounts]
    records = []
    if phones:
        records = db.query(PhoneRecord).filter(PhoneRecord.phone.in_(phones)).all()
    # 中奖成功的排在前面（排除"未中奖"）
    records.sort(key=lambda r: (0 if (r.bid_result and '中奖' in r.bid_result and '未中奖' not in r.bid_result) else 1, r.phone))
    return templates.TemplateResponse(request, "team_dashboard.html", {
        "team": team,
        "records": records,
        "now": datetime.datetime.now
    })

# ========== 团队 CRUD — 已迁移至 routes/api_teams.py ==========
# 团队成员通过 owner_user_id + TeamMember 表管理，无需单独的 login_username/password
# ========== 团队账号分配（保留 Assign/Unassign，包含 PhoneRecord.team 同步逻辑）==========
@app.get("/api/teams/{team_id}/accounts")
async def get_team_accounts(team_id: int, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """获取团队名下的账号列表"""
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    mappings = db.query(TeamAccount).filter(TeamAccount.team_id == team_id).all()
    phones = [m.phone for m in mappings]
    records = []
    if phones:
        records = db.query(PhoneRecord).filter(PhoneRecord.phone.in_(phones)).all()
    return JSONResponse(content={
        'status': 'success',
        'accounts': [{
            'phone': r.phone, 'team_name': r.team or '',
            'logged_in': r.logged_in,
            'login_status': 'success' if r.logged_in else ('offline' if (r.token or r.cookie) else 'never'),
            'account_type': r.account_type or '',
            'bid_result': r.bid_result or '',
            'pay_url': r.pay_url or '',
            'pay_status': r.pay_status or '',
            'balance': r.balance or ''
        } for r in records]
    })

@app.post("/api/teams/{team_id}/assign")
async def assign_accounts_to_team(team_id: int, request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """分配账号到团队"""
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    data = await request.json()
    phones = data.get('phones', [])
    if not phones:
        return JSONResponse(content={'status': 'error', 'message': '请选择要分配的账号'}, status_code=400)
    assigned = 0
    for phone in phones:
        # 查找 PhoneRecord（管理员可分配所有账号，普通用户只能分配自己的账号）
        if user.id == 1 or user.username.lower() == "admin":
            rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        else:
            rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone, PhoneRecord.user_id == user.id).first()
        if not rec:
            continue
        # 检查是否已分配
        existing = db.query(TeamAccount).filter(TeamAccount.team_id == team_id, TeamAccount.phone == phone).first()
        if existing:
            continue
        ta = TeamAccount(team_id=team_id, phone=phone, owner_user_id=user.id)
        db.add(ta)
        # 同步更新 PhoneRecord.team 字段（前端筛选依赖此字段）
        if rec.team != team.name:
            rec.team = team.name
        assigned += 1
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'已将 {assigned} 个账号分配给「{team.name}」'})

@app.post("/api/teams/{team_id}/unassign")
async def unassign_accounts_from_team(team_id: int, request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """从团队移除账号"""
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    data = await request.json()
    phones = data.get('phones', [])
    if not phones:
        return JSONResponse(content={'status': 'error', 'message': '请选择要移除的账号'}, status_code=400)
    deleted = db.query(TeamAccount).filter(
        TeamAccount.team_id == team_id,
        TeamAccount.phone.in_(phones)
    ).delete(synchronize_session=False)
    # 同步清除 PhoneRecord.team 字段（前端筛选依赖此字段）
    for phone in phones:
        if user.id == 1 or user.username.lower() == "admin":
            rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        else:
            rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone, PhoneRecord.user_id == user.id).first()
        if rec and rec.team == team.name:
            rec.team = ''
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'已从「{team.name}」移除 {deleted} 个账号'})

# ---------- 团队操作：刷新登录状态 ----------
@app.post("/api/team/refresh_login")
async def team_refresh_login(team: Team = Depends(get_current_team), db: SQLSession = Depends(get_db)):
    """团队端：刷新名下所有账号的登录状态"""
    mappings = db.query(TeamAccount).filter(TeamAccount.team_id == team.id).all()
    phones = [m.phone for m in mappings]
    if not phones:
        return JSONResponse(content={'status': 'success', 'message': '团队暂无分配账号', 'results': {},
                                     'success_count': 0, 'offline_count': 0, 'never_count': 0, 'black_count': 0})
    results = {}
    success_count = 0
    offline_count = 0
    never_count = 0
    black_count = 0
    for i, phone in enumerate(phones):
        if i > 0:
            await asyncio.sleep(random.uniform(0.05, 0.5))  # 50~500ms随机延迟
        try:
            record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
            if not record:
                results[phone] = {'status_desc': 'never', 'account_type': '', 'logged_in': False}
                never_count += 1
                continue
            # 黑号
            if record.account_type == 'black':
                results[phone] = {'status_desc': 'black', 'account_type': 'black', 'logged_in': record.logged_in}
                black_count += 1
                continue
            # 有凭证则检查有效性
            if record.token or record.cookie:
                valid = await check_login_validity_async(phone)
                if valid is None:
                    results[phone] = {'status_desc': 'unknown', 'account_type': record.account_type or '', 'logged_in': record.logged_in}
                    continue
                update_login_status(phone, valid, db)
                status_desc = _get_login_status_desc(phone, valid, db)
                rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
                account_type = rec.account_type if rec else ''
                results[phone] = {'status_desc': status_desc, 'account_type': account_type, 'logged_in': rec.logged_in if rec else False}
                if status_desc == 'success':
                    success_count += 1
                else:
                    offline_count += 1
            else:
                results[phone] = {'status_desc': 'never', 'account_type': '', 'logged_in': False}
                never_count += 1
        except Exception:
            results[phone] = {'status_desc': 'never', 'account_type': '', 'logged_in': False}
            never_count += 1
    return JSONResponse(content={
        'status': 'success',
        'message': f'刷新完成: 正常{success_count}, 掉线{offline_count}, 未登录{never_count}, 黑号{black_count}',
        'success_count': success_count, 'offline_count': offline_count,
        'never_count': never_count, 'black_count': black_count,
        'results': results
    })

# ---------- 团队操作：刷新抢购结果 ----------
@app.post("/api/team/refresh_bid")
async def team_refresh_bid(team: Team = Depends(get_current_team), db: SQLSession = Depends(get_db)):
    """刷新团队名下所有账号的抢购结果"""
    mappings = db.query(TeamAccount).filter(TeamAccount.team_id == team.id).all()
    phones = [m.phone for m in mappings]
    if not phones:
        return JSONResponse(content={'status': 'success', 'message': '团队暂无分配账号', 'bid_success': 0, 'paid_success': 0, 'unpaid': 0})
    records = db.query(PhoneRecord).filter(PhoneRecord.phone.in_(phones)).all()
    bid_success = 0
    paid_success = 0
    unpaid = 0
    results = {}
    for rec in records:
        if not rec.logged_in or not rec.token:
            results[rec.phone] = {'bid_result': rec.bid_result or '', 'balance': rec.balance or '',
                                   'pay_url': rec.pay_url or '', 'pay_url_wechat': rec.pay_url_wechat or '',
                                   'pay_url_alipay': rec.pay_url_alipay or '', 'pay_status': rec.pay_status or ''}
            continue
        try:
            creds = build_credentials_from_db(rec.phone, db)
            bridge_result = await _bridge._post('/api/bridge/execute', {
                'method': 'query_order_list',
                'params': {},
                'credentials': creds
            })
            orders = bridge_result.get('result', []) if bridge_result.get('success') else []
            winning = [o for o in orders if o.get("status") in (1, 2, 3)]
            if winning:
                rec.bid_result = f"中奖-{winning[0].get('itemName', '商品')}"
                rec.balance = winning[0].get("totalAmount", "")
                st = winning[0].get("status")
                if st in (2, 3):
                    rec.pay_status = "success"
                    rec.balance = "已支付"
                    paid_success += 1
                elif st == 1:
                    rec.pay_status = "pending"
                    rec.balance = "待支付"
                    unpaid += 1
                bid_success += 1
            else:
                rec.bid_result = "未中奖"
            rec.last_updated = datetime.datetime.utcnow()
            results[rec.phone] = {'bid_result': rec.bid_result, 'balance': rec.balance,
                                   'pay_url': rec.pay_url or '', 'pay_url_wechat': rec.pay_url_wechat or '',
                                   'pay_url_alipay': rec.pay_url_alipay or '', 'pay_status': rec.pay_status or ''}
        except Exception as e:
            results[rec.phone] = {'bid_result': rec.bid_result or '', 'balance': rec.balance or '',
                                   'pay_url': rec.pay_url or '', 'pay_url_wechat': rec.pay_url_wechat or '',
                                   'pay_url_alipay': rec.pay_url_alipay or '', 'pay_status': rec.pay_status or ''}
    db.commit()
    return JSONResponse(content={
        'status': 'success', 'message': f'刷新完成：抢购成功 {bid_success}，已付款 {paid_success}，待付款 {unpaid}',
        'bid_success': bid_success, 'paid_success': paid_success, 'unpaid': unpaid,
        'results': results
    })

# ---------- 每日凌晨清除支付链接和支付状态 ----------
@app.post("/api/team/clear_pay_info")
async def clear_team_pay_info(request: Request):
    """每日凌晨清除支付链接和支付状态（由定时任务调用）"""
    if request.headers.get('X-API-TOKEN') != Config.API_TOKEN:
        raise HTTPException(status_code=403)
    with SessionLocal() as db:
        db.query(PhoneRecord).update({
            'pay_url': '', 'pay_url_wechat': '', 'pay_url_alipay': '', 'pay_status': ''
        }, synchronize_session=False)
        db.commit()
    return JSONResponse(content={'status': 'success', 'message': '已清除所有支付链接和支付状态'})

# ===================== 滑块验证代理（服务端集中求解 → 客户端通过 API 调用） =====================

# 滑块服务地址（本机）
SLIDER_API_URL = "http://127.0.0.1:8887"   # Express.js app_api_rounddv.js
OCR_SERVER_URL = "http://127.0.0.1:9898"    # Flask ocr_server.py

import httpx

@app.post("/api/client/slider_solve")
async def slider_solve(request: Request):
    """
    滑块验证一站式求解（客户端调用）
    请求: {"captchaId":"...", "bgUrl":"...", "fgUrl":"..."}
    返回: {"success":true, "validate":"..."} 或 {"success":false, "error":"..."}
    """
    try:
        data = await request.json()
        captcha_id = data.get('captchaId', '')
        bg_url = data.get('bgUrl', '')
        fg_url = data.get('fgUrl', '')

        if not captcha_id or not bg_url or not fg_url:
            return JSONResponse(content={'success': False, 'error': '缺少 captchaId/bgUrl/fgUrl'})

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. 下载背景图和滑块图
            bg_resp = await client.get(bg_url)
            fg_resp = await client.get(fg_url)
            if bg_resp.status_code != 200 or fg_resp.status_code != 200:
                return JSONResponse(content={'success': False, 'error': '图片下载失败'})

            # 2. OCR 滑块匹配（Flask ocr_server.py）
            match_resp = await client.post(
                f"{OCR_SERVER_URL}/slide/match/match",
                files={
                    'bg': ('bg.png', bg_resp.content, 'image/png'),
                    'fg': ('fg.png', fg_resp.content, 'image/png'),
                },
                timeout=15.0
            )
            if match_resp.status_code != 200:
                return JSONResponse(content={'success': False, 'error': f'OCR匹配失败 HTTP {match_resp.status_code}'})
            match_data = match_resp.json()
            distance = match_data.get('distance', match_data.get('x', 0))

            # 3. 滑动验证（Express.js app_api_rounddv.js）
            verify_payload = {
                'captchaId': captcha_id,
                'bgUrl': bg_url,
                'fgUrl': fg_url,
                'verifyType': 'slide',
                'distance': distance,
            }
            verify_resp = await client.post(
                f"{SLIDER_API_URL}/api/verify",
                json=verify_payload,
                timeout=30.0
            )
            if verify_resp.status_code != 200:
                return JSONResponse(content={'success': False, 'error': f'验证失败 HTTP {verify_resp.status_code}'})
            verify_data = verify_resp.json()

            validate = verify_data.get('validate', verify_data.get('result', {}).get('validate', ''))
            if validate:
                return JSONResponse(content={'success': True, 'validate': validate})
            return JSONResponse(content={'success': False, 'error': '未获取到 validate token', 'raw': verify_data})

    except Exception as e:
        return JSONResponse(content={'success': False, 'error': str(e)})


@app.get("/api/client/slider_health")
async def slider_health():
    """检查滑块服务健康状态"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            slider_ok, ocr_ok = False, False
            try:
                r = await client.get(f"{SLIDER_API_URL}/health")
                slider_ok = r.status_code == 200
            except Exception:
                pass
            try:
                r = await client.get(f"{OCR_SERVER_URL}/health")
                ocr_ok = r.status_code == 200
            except Exception:
                pass
        return JSONResponse(content={'slider_api': slider_ok, 'ocr_server': ocr_ok})
    except Exception as e:
        return JSONResponse(content={'slider_api': False, 'ocr_server': False, 'error': str(e)})


# ===================== 手机设备管理（网站后台） =====================
@app.get("/api/phone/dashboard")
async def phone_dashboard(user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """网站后台查看手机设备：在线数/已布置/未布置 + 设备列表"""
    from routes.api_client import phone_devices
    cfg = get_user_config(user.id, db)
    phone_rush_enabled = getattr(cfg, 'phone_rush_enabled', 0)
    multi_open = getattr(cfg, 'phone_multi_open_count', 3)

    now = time.time()
    devices = []
    for device_id, info in list(phone_devices.items()):
        if now - info['last_heartbeat'] < 35:
            # 普通用户只看自己的设备，admin/root(user.id==1)看全部
            if user.id != 1 and info.get('uploader_id') != user.id:
                continue
            devices.append({
                'device_id': device_id[:16],
                'uploader_id': info['uploader_id'],
                'status': info.get('status', 'pending'),
                'account_count': info.get('account_count', 0),
                'last_heartbeat': info['last_heartbeat'],
                'device_info': info.get('device_info', {}),
            })

    online = len(devices)
    deployed = sum(1 for d in devices if d['status'] == 'deployed')

    # 已登录账号列表（用于分配）
    if user.id == 1:
        acc_records = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
    else:
        acc_records = db.query(PhoneRecord).filter(
            PhoneRecord.logged_in == True, PhoneRecord.user_id == user.id).all()
    account_list = [{'phone': r.phone, 'team': r.team or ''} for r in acc_records
                    if not (r.account_type and ('\u9ed1\u53f7' in r.account_type.lower() or r.account_type.lower() == 'black'))]

    # 已有分配
    assign_json = getattr(cfg, 'phone_device_assign', '') or '{}'
    try:
        assign_map = json.loads(assign_json)
    except Exception:
        assign_map = {}

    return JSONResponse(content={
        'phone_rush_enabled': phone_rush_enabled,
        'multi_open_count': multi_open,
        'devices': devices,
        'online_count': online,
        'deployed_count': deployed,
        'pending_count': online - deployed,
        'accounts': account_list,
        'assign_map': assign_map,
    })


@app.post("/api/phone/assign")
async def phone_dashboard_assign(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    """网站后台：分配/取消分配账号到设备"""
    data = await request.json()
    device_id = data.get('device_id', '') or ''
    phones = data.get('phones', [])

    if not device_id:
        return JSONResponse(content={'status': 'error', 'message': '缺少 device_id'})

    cfg = get_user_config(user.id, db)
    assign_json = getattr(cfg, 'phone_device_assign', '') or '{}'
    try:
        assign_map = json.loads(assign_json)
    except Exception:
        assign_map = {}

    if phones:
        assign_map[device_id] = phones
    else:
        assign_map.pop(device_id, None)

    cfg.phone_device_assign = json.dumps(assign_map, ensure_ascii=False)
    db.commit()
    print(f'[设备分配] device={device_id[:8]} → {len(phones)}个账号 | user={user.username}')
    return JSONResponse(content={
        'status': 'success',
        'message': f'已分配 {len(phones)} 个账号',
        'assign_map': assign_map,
    })


@app.post("/api/phone/reset")
async def phone_dashboard_reset(request: Request, user: User = Depends(get_current_user)):
    """网站后台：重置所有手机部署状态，所有设备下次心跳重新拉数据重新布置"""
    try:
        from routes.api_client import phone_devices
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={
            'status': 'error',
            'message': f'导入 phone_devices 失败: {e}',
        }, status_code=500)
    reset_count = 0
    for info in phone_devices.values():
        # 普通用户只重置自己的设备
        if user.id != 1 and info.get('uploader_id') != user.id:
            continue
        if info.get('status') == 'deployed':
            info['status'] = 'pending'
            info['account_count'] = 0
            reset_count += 1
    print(f'[手机重置] 🔄 user={user.username} 重置 {reset_count} 台设备')
    return JSONResponse(content={
        'status': 'success',
        'message': f'已重置 {reset_count} 台设备，所有手机下次心跳将重新拉取数据',
        'reset_count': reset_count,
    })


# ===================== 管理员页面 =====================
@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, user: User = Depends(get_current_user), db: SQLSession = Depends(get_db)):
    if user.username != "admin": return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request, "admin_users.html", {"user": user, "users": db.query(User).order_by(User.id).all()})


# ===================== 主入口 =====================
if __name__ == '__main__':
    import uvicorn
    import socket
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80)); ip = s.getsockname()[0]; s.close(); return ip
        except: return '127.0.0.1'
    lip = get_local_ip()
    print(f"\n{'='*50}")
    print(f" FastAPI 服务启动成功！")
    print(f" 本地访问: http://127.0.0.1:{Config.PORT}")
    print(f" 内网访问: http://{'ipla.top'}:{Config.PORT}")
    print(f" 文档地址: http://127.0.0.1:{Config.PORT}/docs")
    print(f"{'='*50}\n")
    # 打印代理模式
    mode_desc = {'proxy_only': '外部代理', 'off': '关闭'}
    print(f"  代理模式: {mode_desc.get(PHONE_PROXY_MODE, PHONE_PROXY_MODE)} (PHONE_PROXY_MODE={PHONE_PROXY_MODE})\n")
    # 自定义日志配置：完全抑制 h11 Invalid HTTP request 刷屏
    import logging
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["loggers"]["uvicorn"]["level"] = "ERROR"
    log_config["loggers"]["uvicorn.error"]["level"] = "ERROR"
    log_config["loggers"]["uvicorn.access"]["level"] = "ERROR"
    logging.getLogger("h11").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.protocols").setLevel(logging.ERROR)
    # 自定义 asyncio 异常处理器：吞掉 h11 协议错误 traceback
    _orig_handler = asyncio.get_event_loop().get_exception_handler()
    def _quiet_exception_handler(loop, context):
        exc = context.get('exception')
        if exc and 'LocalProtocolError' in type(exc).__name__:
            return
        if _orig_handler:
            _orig_handler(loop, context)
        else:
            loop.default_exception_handler(context)
    asyncio.get_event_loop().set_exception_handler(_quiet_exception_handler)
    uvicorn.run(app, host=Config.HOST, port=Config.PORT, log_config=log_config)

