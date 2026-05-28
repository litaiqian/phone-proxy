#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i猫妈妈多账号自动化管理系统 - FastAPI 版本
整合：Web管理端 + 并发任务调度 + 自动登录保鲜 + 错峰抢购 + App回调接口
"""

import os
import sys
import json
import time
import threading
import random
import datetime
import logging
from typing import Dict, Optional, Any, List
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import timedelta

import qrcode
import io
import pandas as pd
from werkzeug.utils import secure_filename

# 导入猫妈妈协议的完整实现
from demo import (
    MoutaiClient, _load_accounts, _load_account_to_client, BASE_URL, H5_BASE_URL,
    generate_mt_k_and_v, generate_mt_device_id, generate_device_id_raw,
    generate_act_param, md5_hex, APP_VERSION, SDK_VERSION,
    generate_h5_did, generate_h5_start_id, generate_d_u_cookie,
    generate_bs_device_id, generate_headers_for_post, generate_wasm_sign,
    VCODE_SALT, _post, _get
)

# ===================== 配置日志 =====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('server.log', encoding='utf-8')
    ]
)
logger = logging.getLogger("MoutaiServer")


# ===================== 配置 =====================
BASEDIR = Path(__file__).parent.resolve()
QRCODE_FOLDER = BASEDIR / 'static' / 'qrcodes'
QRCODE_FOLDER.mkdir(parents=True, exist_ok=True)

UPLOAD_FOLDER = BASEDIR / 'uploads'
UPLOAD_FOLDER.mkdir(exist_ok=True)

DATA_FOLDER = BASEDIR / 'data'
DATA_FOLDER.mkdir(exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

    DATABASE_URL = f'sqlite:///{BASEDIR / "app.db"}'

    MAX_THREADS = 20
    HOST = '0.0.0.0'  # 监听所有网络接口（包括内网、外网）
    PORT = 5000
    API_TOKEN = 'your-secure-token-change-me'

    DEFAULT_RUSH_HOUR = 8
    DEFAULT_RUSH_MINUTE = 58
    AUTO_MODE_DEFAULT = False
    AUTO_START_TIME = "08:00"


config = Config()

# ===================== 数据库模型 =====================
engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)
    return encoded_jwt


def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


class User(Base):
    __tablename__ = 'user'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    phone_records = relationship("PhoneRecord", back_populates="uploader", foreign_keys="PhoneRecord.uploaded_by")


class PhoneRecord(Base):
    __tablename__ = 'phonerecord'

    phone = Column(String(20), primary_key=True, index=True)
    team = Column(String(100), default='')
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    uploaded_by = Column(Integer, ForeignKey('user.id'))
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

    auto_mode = Column(Boolean, default=False)
    rush_time_offset = Column(Integer, default=0)

    user_agent = Column(String(200), default='')
    webview_ua = Column(String(300), default='')
    mt_r = Column(String(80), default='')
    mt_sn = Column(String(80), default='')

    uploader = relationship("User", back_populates="phone_records", foreign_keys=[uploaded_by])

class GlobalConfig(Base):
    __tablename__ = 'globalconfig'

    id = Column(Integer, primary_key=True)
    rush_hour = Column(Integer, default=config.DEFAULT_RUSH_HOUR)
    rush_minute = Column(Integer, default=config.DEFAULT_RUSH_MINUTE)
    auto_mode_enabled = Column(Boolean, default=config.AUTO_MODE_DEFAULT)
    auto_start_time = Column(String(5), default=config.AUTO_START_TIME)


Base.metadata.create_all(bind=engine)


# ===================== Pydantic 模型 =====================
class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class SendCodeRequest(BaseModel):
    phone: str


class SubmitCodeRequest(BaseModel):
    phone: str
    code: str


class BatchSendRequest(BaseModel):
    min_delay: int = 10
    max_delay: int = 20


class ConfigUpdate(BaseModel):
    rush_hour: Optional[int] = None
    rush_minute: Optional[int] = None
    auto_mode_enabled: Optional[bool] = None
    auto_start_time: Optional[str] = None


class SMSReceiveRequest(BaseModel):
    phone: str
    code: str


class ClientTaskRequest(BaseModel):
    uploader_id: int


class ResultReport(BaseModel):
    phone: str
    success: bool
    order_id: str = ""
    h5_url: str = ""
    error: str = ""
    bid_result_str: str = ""


# ===================== FastAPI 应用初始化 =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 60)
    logger.info("🚀 开始启动后台任务...")
    
    try:
        threading.Thread(target=login_keepalive_worker, daemon=True).start()
        logger.info("✅ 登录保鲜任务已启动")
        
        threading.Thread(target=auto_mode_processor, daemon=True).start()
        logger.info("✅ 自动模式处理任务已启动")
        
        threading.Thread(target=rush_scheduler, daemon=True).start()
        logger.info("✅ 抢购调度器已启动")
        
        logger.info("✅ 所有后台任务启动成功")
    except Exception as e:
        logger.error(f"❌ 后台任务启动失败: {e}", exc_info=True)
    
    logger.info("=" * 60)
    yield
    logger.info("🛑 应用关闭")

app = FastAPI(title="i猫妈妈自动化管理系统", version="2.0.0", lifespan=lifespan)

# 添加请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有HTTP请求"""
    start_time = time.time()
    
    # 记录请求信息
    client_host = request.client.host if request.client else "unknown"
    method = request.method
    url = str(request.url)
    
    logger.info(f"📥 请求: {method} {url} (来自: {client_host})")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"📤 响应: {method} {url} - 状态码: {response.status_code} - 耗时: {process_time:.3f}s")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"❌ 错误: {method} {url} - 异常: {e} - 耗时: {process_time:.3f}s", exc_info=True)
        raise

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 修复：完全重新初始化 Jinja2Templates
templates_dir = str(BASEDIR / 'templates')
logger.info(f"📁 模板目录: {templates_dir}")

# 检查目录是否存在
import os
if not os.path.exists(templates_dir):
    logger.error(f"❌ 模板目录不存在: {templates_dir}")
    sys.exit(1)

# 列出所有模板文件
template_files = [f for f in os.listdir(templates_dir) if f.endswith('.html')]
logger.info(f"📄 找到 {len(template_files)} 个模板文件: {template_files}")

# 使用新的方式创建 templates
from starlette.templating import Jinja2Templates as StarletteJinja2Templates
templates = StarletteJinja2Templates(directory=templates_dir)

# 关键修复：清除并重新配置 Jinja2 环境
templates.env.cache = None  # 禁用缓存
templates.env.auto_reload = True  # 启用自动重载

logger.info("✅ Jinja2Templates 初始化成功")

# 挂载静态文件
try:
    static_dir = str(BASEDIR / 'static')
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info(f"✅ 静态文件目录挂载成功: {static_dir}")
except Exception as e:
    logger.error(f"❌ 静态文件目录挂载失败: {e}")


# ===================== 辅助函数 =====================
def get_global_config(db: Session):
    cfg = db.query(GlobalConfig).first()
    if not cfg:
        cfg = GlobalConfig(
            rush_hour=config.DEFAULT_RUSH_HOUR,
            rush_minute=config.DEFAULT_RUSH_MINUTE,
            auto_mode_enabled=config.AUTO_MODE_DEFAULT,
            auto_start_time=config.AUTO_START_TIME
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def build_client_from_record(phone: str, db: Session) -> MoutaiClient:
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        raise ValueError(f"手机号 {phone} 不存在")

    if record.raw_device_id:
        client = MoutaiClient(
            android_id=record.raw_device_id[:16] if len(record.raw_device_id) >= 16 else "",
            bs_dvid=record.mt_device_id.replace("clips_", "") if record.mt_device_id else ""
        )
        client.token = record.token or ""
        client.cookie = record.cookie or ""
        client.user_id = record.user_id_ext or ""
        client.mt_device_id = record.mt_device_id or ""
        client.raw_device_id = record.raw_device_id or ""
        client.h5_did = record.h5_did or generate_h5_did()
        client.h5_start_id = record.h5_start_id or generate_h5_start_id()
        client.bs_device_id = record.bs_device_id or generate_bs_device_id(client.h5_did)
    else:
        client = MoutaiClient()
        record.raw_device_id = client.raw_device_id
        record.mt_device_id = client.mt_device_id
        record.h5_did = client.h5_did
        record.h5_start_id = client.h5_start_id
        record.bs_device_id = client.bs_device_id
        db.commit()
    return client


def check_login_validity(phone: str, db: Session) -> bool:
    accounts_file = BASEDIR / 'iplala_accounts.json'
    try:
        accounts = _load_accounts(str(accounts_file))
    except Exception as e:
        print(f"[检查登录] 加载 iplala_accounts.json 失败: {e}")
        return False

    acc = next((a for a in accounts if a.get("mobile") == phone), None)
    if not acc:
        print(f"[检查登录] {phone} 未在 iplala_accounts.json 中找到")
        return False

    try:
        client = MoutaiClient(bs_dvid=acc.get('bs-dvid', ''))
        _load_account_to_client(acc, client)

        headers = client._app_headers(need_sign=False)
        resp = _get(f"{BASE_URL}/xhr/front/user/info", headers=headers)
        data = resp.json()
        is_valid = (data.get("code") == 2000)
        print(f"[检查登录] {phone} 结果: {'有效' if is_valid else '无效'}")
        return is_valid
    except Exception as e:
        print(f"[检查登录] {phone} 异常: {e}")
        return False


def update_login_status(phone: str, is_valid: bool, db: Session):
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record:
        if is_valid:
            record.logged_in = True
        else:
            record.logged_in = False
            record.token = ""
            record.cookie = ""
            record.user_id_ext = ""
        record.last_updated = datetime.datetime.utcnow()
        db.commit()


def save_account_to_json(phone: str, client: MoutaiClient):
    accounts_file = BASEDIR / 'iplala_accounts.json'
    accounts = []
    if accounts_file.exists():
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)

    idx = next((i for i, acc in enumerate(accounts) if acc.get("mobile") == phone), -1)
    acc_data = {
        "mobile": phone,
        "userid": client.user_id,
        "token": client.token,
        "cookie": client.cookie,
        "mt-device-id": client.mt_device_id,
        "device-id": client.raw_device_id,
        "user-agent": client.user_agent,
        "webview-ua": client.webview_ua,
        "mt-r": client.mt_r,
        "mt-sn": client.mt_sn,
        "h5-did": client.h5_did,
        "h5-start-id": client.h5_start_id,
        "bs-device-id": client.bs_device_id,
        "loginTime": datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    }

    if idx >= 0:
        accounts[idx] = {**accounts[idx], **acc_data}
    else:
        accounts.append(acc_data)

    with open(accounts_file, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def send_verification_code_impl(phone: str, db: Session) -> bool:
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if record and record.logged_in:
        print(f"[发送验证码] {phone} 已登录，跳过")
        return False

    client = build_client_from_record(phone, db)
    result = client.send_vcode(phone)
    success = result.get("code") == 2000
    if success and record:
        record.code_sent = True
        record.last_updated = datetime.datetime.utcnow()
        db.commit()
    return success


# ===================== 后台任务 =====================
rush_job_started = False


def login_keepalive_worker():
    """登录保鲜后台任务"""
    while True:
        db = SessionLocal()
        try:
            now = datetime.datetime.now()
            current_hour = now.hour

            if current_hour >= 22 or current_hour < 6:
                next_refresh = now.replace(hour=6, minute=0, second=0, microsecond=0)
                if now.hour >= 22:
                    next_refresh += datetime.timedelta(days=1)
                sleep_seconds = (next_refresh - now).total_seconds()
                print(f"[保鲜] 夜间休息，睡眠 {sleep_seconds / 3600:.1f} 小时")
                time.sleep(sleep_seconds)
                continue

            sleep_seconds = random.randint(600, 2900)
            time.sleep(sleep_seconds)

            records = db.query(PhoneRecord).all()
            for rec in records:
                if not rec.logged_in:
                    continue
                valid = check_login_validity(rec.phone, db)
                if not valid:
                    print(f"[保鲜] {rec.phone} 登录失效")
                    update_login_status(rec.phone, False, db)
                else:
                    rec.last_updated = datetime.datetime.utcnow()
                    db.commit()
        finally:
            db.close()


def auto_mode_processor():
    """自动模式批量处理"""
    while True:
        db = SessionLocal()
        try:
            cfg = get_global_config(db)
            if not cfg.auto_mode_enabled:
                time.sleep(30)
                continue

            target_time = cfg.auto_start_time
            now = datetime.datetime.now()
            current = now.strftime("%H:%M")

            if current == target_time:
                print(f"[自动模式] 到达时间 {target_time}，开始处理")
                records = db.query(PhoneRecord).filter(PhoneRecord.auto_mode == True).all()
                for rec in records:
                    if rec.logged_in:
                        continue
                    for attempt in range(2):
                        success = send_verification_code_impl(rec.phone, db)
                        if success:
                            print(f"[自动模式] {rec.phone} 验证码已发送")
                            break
                        else:
                            print(f"[自动模式] {rec.phone} 发送失败，重试")
                            time.sleep(2)
                time.sleep(60)
            else:
                time.sleep(30)
        finally:
            db.close()


def rush_scheduler():
    """抢购调度器"""
    global rush_job_started
    while True:
        db = SessionLocal()
        try:
            cfg = get_global_config(db)
            rush_hour = cfg.rush_hour
            rush_minute = cfg.rush_minute
            now = datetime.datetime.now()
            target = now.replace(hour=rush_hour, minute=rush_minute, second=0, microsecond=0)

            if now >= target:
                target += datetime.timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            if wait_seconds > 0:
                time.sleep(wait_seconds - 60)
                while datetime.datetime.now() < target:
                    time.sleep(0.1)

                if not rush_job_started:
                    rush_job_started = True
                    start_rush_for_all_accounts()
                    rush_job_started = False
            else:
                time.sleep(60)
        finally:
            db.close()


def start_rush_for_all_accounts():
    """启动所有账号的抢购"""
    db = SessionLocal()
    try:
        records = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
        if not records:
            print("[抢购] 没有已登录账号")
            return

        total = len(records)
        batch_size = total // 3
        batches = [
            records[:batch_size],
            records[batch_size:2 * batch_size],
            records[2 * batch_size:]
        ]
        delays = [0, 60, 59.5]

        for batch, delay in zip(batches, delays):
            if not batch:
                continue
            timer = threading.Timer(delay, lambda b=batch: run_rush_for_batch(b))
            timer.daemon = True
            timer.start()
    finally:
        db.close()


def run_rush_for_batch(records: List[PhoneRecord]):
    """执行一批账号的抢购"""
    item_code = "741"
    act_id = "76145"
    amount = "1"

    for rec in records:
        try:
            db = SessionLocal()
            client = build_client_from_record(rec.phone, db)
            result = client.rush_purchase(item_code, act_id, amount)
            if result.get("code") == 2000:
                complete_order_and_pay(rec, item_code, act_id, amount, result, db)
            else:
                print(f"[抢购] {rec.phone} 失败: {result}")
        except Exception as e:
            print(f"[抢购] {rec.phone} 异常: {e}")
        finally:
            db.close()


def complete_order_and_pay(rec: PhoneRecord, item_code: str, act_id: str, amount: str, rush_result: dict, db: Session):
    """抢购成功后自动下单、支付、生成二维码"""
    try:
        client = build_client_from_record(rec.phone, db)

        addresses = client.get_addresses()
        if not addresses:
            print(f"[下单] {rec.phone} 无收货地址")
            return
        default_addr = next((addr for addr in addresses if addr.get("dft")), addresses[0])

        record_id = rush_result.get("data", {}).get("priorityRecordId", 0)
        if not record_id:
            print(f"[下单] {rec.phone} 未获取到 priorityRecordId")
            return

        compose_res = client.compose_order(
            spu_id=item_code,
            count=int(amount),
            priority_record_id=record_id,
            address=default_addr
        )
        if compose_res.get("code") != 2000:
            print(f"[组单] {rec.phone} 失败")
            return

        submit_res = client.submit_order(
            spu_id=item_code,
            count=int(amount),
            priority_record_id=record_id,
            address=default_addr
        )
        if submit_res.get("code") != 2000:
            print(f"[下单] {rec.phone} 失败")
            return

        order_id = submit_res.get("data", {}).get("orderId")
        print(f"[下单] {rec.phone} 成功，订单号 {order_id}")

        pay_res = client.pay_order(order_id)
        if pay_res.get("code") != 2000:
            print(f"[支付] {rec.phone} 失败")
            return

        channel_trade_sn = pay_res.get("data", {}).get("channelTradeSn")
        if not channel_trade_sn:
            print(f"[支付] {rec.phone} 未获取到 TN")
            return

        gw_result = client.request_pay(channel_trade_sn, pay_channel="70")
        code = gw_result.get("code")
        if isinstance(code, str):
            code = int(code)
        if code not in (200, 2000):
            print(f"[支付网关] {rec.phone} 失败")
            return

        p_data = gw_result.get("data")
        sdk_str = p_data if isinstance(p_data, str) else (
                p_data.get("payInfo") or p_data.get("alipay_sdk")
                or p_data.get("orderInfo") or p_data.get("AUTH_CODE", "")
        ) if isinstance(p_data, dict) else ""

        if not sdk_str:
            print(f"[支付网关] {rec.phone} 未返回 SDK 串")
            return

        h5_result = client.convert_to_h5(sdk_str)
        if not h5_result.get("success"):
            print(f"[转链] {rec.phone} 失败")
            return

        h5_url = h5_result["h5Url"]
        print(f"[支付] {rec.phone} H5 链接生成成功")

        qrcode_path = QRCODE_FOLDER / f"{rec.phone}.png"
        img = qrcode.make(h5_url)
        img.save(str(qrcode_path))
        print(f"[二维码] {rec.phone} 已保存")

        rec.bid_result = f"成功-订单{order_id}"
        rec.balance = "待支付"
        rec.last_updated = datetime.datetime.utcnow()
        db.commit()

    except Exception as e:
        print(f"[下单支付] {rec.phone} 异常: {e}")
        import traceback
        traceback.print_exc()


# ===================== 启动后台任务 =====================

# ===================== API 路由 =====================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """根路径重定向到登录页"""
    logger.info("🔄 根路径访问，重定向到登录页")
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    logger.info("📄 渲染登录页面")
    try:
        return templates.TemplateResponse(
            name="login.html",
            context={"request": request}
        )
    except Exception as e:
        logger.error(f"❌ 登录页面渲染失败: {e}", exc_info=True)
        raise


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """注册页面"""
    logger.info("📄 渲染注册页面")
    try:
        return templates.TemplateResponse(
            name="register.html",
            context={"request": request}
        )
    except Exception as e:
        logger.error(f"❌ 注册页面渲染失败: {e}", exc_info=True)
        raise


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(get_current_user)):
    """控制台页面"""
    logger.info(f"📊 控制台访问: 用户={current_user.username}")
    db = SessionLocal()
    try:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
        logger.info(f"📋 查询到 {len(records)} 条记录")
        return templates.TemplateResponse(
            name="dashboard.html",
            context={
                "request": request,
                "records": records,
                "current_user": current_user
            }
        )
    except Exception as e:
        logger.error(f"❌ 控制台页面渲染失败: {e}", exc_info=True)
        raise
    finally:
        db.close()


@app.post("/api/upload")
async def upload_excel(
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user)
):
    """上传Excel文件"""
    db = SessionLocal()
    try:
        filename = secure_filename(file.filename)
        filepath = UPLOAD_FOLDER / filename

        contents = await file.read()
        with open(filepath, "wb") as f:
            f.write(contents)

        df = pd.read_excel(filepath, header=None, dtype=str, engine='openpyxl')
        imported = 0
        skipped = 0

        cfg = get_global_config(db)

        for _, row in df.iterrows():
            team = str(row[0]).strip() if pd.notna(row[0]) else ''
            raw_phone = str(row[1]).strip() if pd.notna(row[1]) else ''

            if '.' in raw_phone and raw_phone.endswith('.0'):
                raw_phone = raw_phone[:-2]

            import re
            phone = re.sub(r'[\s\-\(\)]+', '', raw_phone)

            if not phone or not phone.isdigit() or len(phone) < 7:
                skipped += 1
                continue

            existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
            if not existing:
                rec = PhoneRecord(
                    team=team,
                    phone=phone,
                    user_id=current_user.id,
                    uploaded_by=current_user.id,
                    auto_mode=cfg.auto_mode_enabled
                )
                db.add(rec)
                imported += 1
            else:
                skipped += 1

        db.commit()

        msg = f'成功导入 {imported} 条新手机号'
        if skipped:
            msg += f'，跳过 {skipped} 条（已存在或格式错误）'

        return JSONResponse(content={'status': 'success', 'message': msg})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'解析失败: {str(e)}')
    finally:
        db.close()


@app.post("/api/send_code")
async def api_send_code(
        req: SendCodeRequest,
        current_user: User = Depends(get_current_user)
):
    """发送验证码"""
    db = SessionLocal()
    try:
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == req.phone).first()
        if not record or record.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无权限")

        if record.logged_in:
            raise HTTPException(status_code=400, detail="账号已登录，无需发送验证码")

        success = send_verification_code_impl(req.phone, db)
        if success:
            return JSONResponse(content={'status': 'success', 'message': '验证码已发送'})
        else:
            raise HTTPException(status_code=400, detail="发送失败，请检查手机号或稍后重试")
    finally:
        db.close()


@app.post("/api/submit_code")
async def api_submit_code(
        req: SubmitCodeRequest,
        current_user: User = Depends(get_current_user)
):
    """提交验证码"""
    db = SessionLocal()
    try:
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == req.phone).first()
        if not record or record.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无权限")

        if record.logged_in:
            raise HTTPException(status_code=400, detail="账号已登录，无需重复提交")

        client = build_client_from_record(req.phone, db)
        result = client.login(req.phone, req.code)

        record.user_agent = client.user_agent
        record.webview_ua = client.webview_ua
        record.mt_r = client.mt_r
        record.mt_sn = client.mt_sn

        if result.get("code") == 2000:
            record.token = client.token
            record.cookie = client.cookie
            record.user_id_ext = client.user_id
            record.logged_in = True
            record.last_updated = datetime.datetime.utcnow()
            db.commit()

            save_account_to_json(req.phone, client)
            return JSONResponse(content={'status': 'success', 'message': '登录成功'})
        else:
            raise HTTPException(status_code=400, detail=f"登录失败: {result.get('message')}")
    finally:
        db.close()


@app.post("/api/receive_sms")
async def receive_sms(req: SMSReceiveRequest):
    """App回调接收验证码"""
    db = SessionLocal()
    try:
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == req.phone).first()
        if not record:
            raise HTTPException(status_code=404, detail="手机号未在系统中")

        if record.logged_in:
            return JSONResponse(content={'status': 'success', 'message': '账号已登录，忽略验证码'})

        client = build_client_from_record(req.phone, db)

        record.user_agent = client.user_agent
        record.webview_ua = client.webview_ua
        record.mt_r = client.mt_r
        record.mt_sn = client.mt_sn

        result = client.login(req.phone, req.code)
        if result.get("code") == 2000:
            record.token = client.token
            record.cookie = client.cookie
            record.user_id_ext = client.user_id
            record.logged_in = True
            record.last_updated = datetime.datetime.utcnow()
            db.commit()

            save_account_to_json(req.phone, client)
            return JSONResponse(content={'status': 'success', 'message': '自动登录成功'})
        else:
            raise HTTPException(status_code=400, detail=f"登录失败: {result.get('message')}")
    finally:
        db.close()


@app.get("/api/phone_status/{phone}")
async def phone_status(
        phone: str,
        current_user: User = Depends(get_current_user)
):
    """查询单个手机号状态"""
    db = SessionLocal()
    try:
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        if not record or record.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="无权限")

        uploader = db.query(User).filter(User.id == record.uploaded_by).first()
        return JSONResponse(content={
            'phone': record.phone,
            'team': record.team,
            'uploaded_by': uploader.username if uploader else '未知',
            'code_sent': record.code_sent,
            'logged_in': record.logged_in,
            'balance': record.balance,
            'bid_result': record.bid_result,
            'last_updated': record.last_updated.isoformat() if record.last_updated else ''
        })
    finally:
        db.close()


@app.get("/api/export")
async def export_data(current_user: User = Depends(get_current_user)):
    """导出数据"""
    db = SessionLocal()
    try:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
        data = []
        for r in records:
            data.append({
                '手机号': r.phone,
                '验证码已发送': r.code_sent,
                '登录状态': '成功' if r.logged_in else '掉线',
                '中标结果': r.bid_result,
                '账户余额': r.balance,
                '最后更新': r.last_updated
            })

        df = pd.DataFrame(data)
        output = UPLOAD_FOLDER / 'export.xlsx'
        df.to_excel(output, index=False)

        return FileResponse(
            path=output,
            filename='export.xlsx',
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    finally:
        db.close()


@app.get("/api/stats")
async def stats(current_user: User = Depends(get_current_user)):
    """统计接口"""
    db = SessionLocal()
    try:
        base_query = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id)
        total = base_query.count()
        success_login = base_query.filter(PhoneRecord.logged_in == True).count()

        offline = base_query.filter(
            PhoneRecord.logged_in == False,
            (PhoneRecord.token != '') | (PhoneRecord.cookie != '')
        ).count()

        never_login = base_query.filter(
            PhoneRecord.logged_in == False,
            PhoneRecord.token == '',
            PhoneRecord.cookie == ''
        ).count()

        qrcode_count = 0
        for rec in base_query.all():
            qrcode_path = QRCODE_FOLDER / f"{rec.phone}.png"
            if qrcode_path.exists():
                qrcode_count += 1

        from sqlalchemy import or_
        bid_success = base_query.filter(PhoneRecord.bid_result.contains('成功')).count()

        return JSONResponse(content={
            'total': total,
            'success_login': success_login,
            'offline': offline,
            'never_login': never_login,
            'bid_success': bid_success,
            'qrcode_count': qrcode_count
        })
    finally:
        db.close()


@app.post("/api/batch_send_code")
async def batch_send_code(
        req: BatchSendRequest,
        current_user: User = Depends(get_current_user)
):
    """批量发送验证码"""
    db = SessionLocal()
    try:
        user_id = current_user.id
        phones = [r.phone for r in db.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all()]

        if not phones:
            raise HTTPException(status_code=400, detail="无号码")

        def batch_task():
            with SessionLocal() as task_db:
                all_records = task_db.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all()
                pending_phones = [rec.phone for rec in all_records if not rec.logged_in]

                if not pending_phones:
                    print("[批量发送] 没有需要发送验证码的账号")
                    return

                for phone in pending_phones:
                    send_verification_code_impl(phone, task_db)
                    delay = random.randint(req.min_delay, req.max_delay)
                    time.sleep(delay)

                print(f"[批量发送] 已完成，共发送 {len(pending_phones)} 个账号")

        threading.Thread(target=batch_task, daemon=True).start()

        pending_count = sum(
            1 for r in db.query(PhoneRecord).filter(PhoneRecord.user_id == user_id).all() if not r.logged_in)

        return JSONResponse(content={
            'status': 'success',
            'message': f'批量发送已启动，共{len(phones)}个账号，其中{pending_count}个需要发送，{len(phones) - pending_count}个已登录自动跳过'
        })
    finally:
        db.close()


@app.post("/api/clear_all_records")
async def clear_all_records(current_user: User = Depends(get_current_user)):
    """清空所有账号"""
    db = SessionLocal()
    try:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
        for rec in records:
            qrcode_path = QRCODE_FOLDER / f"{rec.phone}.png"
            if qrcode_path.exists():
                qrcode_path.unlink()

        db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).delete()
        db.commit()

        return JSONResponse(content={'status': 'success', 'message': '已清空所有账号及二维码'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/api/get_config")
async def get_config(current_user: User = Depends(get_current_user)):
    """获取全局配置"""
    db = SessionLocal()
    try:
        cfg = get_global_config(db)
        return JSONResponse(content={
            'rush_hour': cfg.rush_hour,
            'rush_minute': cfg.rush_minute,
            'auto_mode_enabled': cfg.auto_mode_enabled,
            'auto_start_time': cfg.auto_start_time
        })
    finally:
        db.close()


@app.post("/api/set_config")
async def set_config(
        cfg_update: ConfigUpdate,
        current_user: User = Depends(get_current_user)
):
    """更新全局配置"""
    db = SessionLocal()
    try:
        cfg = get_global_config(db)
        if cfg_update.rush_hour is not None:
            cfg.rush_hour = cfg_update.rush_hour
        if cfg_update.rush_minute is not None:
            cfg.rush_minute = cfg_update.rush_minute
        if cfg_update.auto_mode_enabled is not None:
            cfg.auto_mode_enabled = cfg_update.auto_mode_enabled
        if cfg_update.auto_start_time is not None:
            cfg.auto_start_time = cfg_update.auto_start_time
        db.commit()

        return JSONResponse(content={'status': 'success'})
    finally:
        db.close()


@app.post("/api/refresh_login")
async def refresh_login(current_user: User = Depends(get_current_user)):
    """刷新登录状态"""
    db = SessionLocal()
    try:
        phones = [r.phone for r in db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()]
        results = {}

        for phone in phones:
            try:
                valid = check_login_validity(phone, db)
                update_login_status(phone, valid, db)

                record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
                if valid:
                    status_desc = 'success'
                elif record and (record.token or record.cookie):
                    status_desc = 'offline'
                else:
                    status_desc = 'never'

                results[phone] = {'valid': valid, 'status_desc': status_desc}
            except Exception as e:
                print(f"Refresh login error for {phone}: {e}")
                results[phone] = {'valid': False, 'status_desc': 'never'}

        return JSONResponse(content={'status': 'success', 'results': results})
    finally:
        db.close()


@app.post("/api/query_bid_results")
async def query_bid_results(current_user: User = Depends(get_current_user)):
    """查询所有中标结果"""
    db = SessionLocal()
    try:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
        results = {}

        for rec in records:
            if not rec.logged_in or not rec.token:
                results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
                continue

            try:
                client = build_client_from_record(rec.phone, db)
                orders = client.query_order_list()
                winning = [o for o in orders if o.get("status") in (1, 2, 3)]

                if winning:
                    bid_str = f"中奖-{winning[0].get('itemName', '商品')}"
                    rec.bid_result = bid_str
                    rec.balance = winning[0].get("totalAmount", "")
                else:
                    rec.bid_result = "未中奖"

                db.commit()
                results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
            except Exception as e:
                print(f"[中标查询] {rec.phone} 失败: {e}")
                results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}

        return JSONResponse(content={'status': 'success', 'results': results})
    finally:
        db.close()


@app.get("/qrcode/{phone}")
async def get_qrcode(phone: str, current_user: User = Depends(get_current_user)):
    """获取支付二维码图片"""
    qrcode_file = QRCODE_FOLDER / f"{phone}.png"
    if qrcode_file.exists():
        return FileResponse(path=qrcode_file, media_type="image/png")
    else:
        raise HTTPException(status_code=404, detail="二维码不存在")


@app.get("/api/sample_products")
async def sample_products(current_user: User = Depends(get_current_user)):
    """示例商品列表"""
    products = [
        {"name": "猫妈妈飞天53度 500ml", "price": "1499元"},
        {"name": "猫妈妈生肖酒 虎年", "price": "2499元"},
        {"name": "猫妈妈王子酒 酱香经典", "price": "398元"},
        {"name": "猫妈妈迎宾酒 中国红", "price": "168元"},
    ]
    return JSONResponse(content=products)


# ===================== 客户端 API 接口 =====================

@app.get("/api/client/get_config")
async def client_get_config(request: Request):
    """客户端获取抢购配置"""
    token = request.headers.get('X-API-TOKEN')
    if token != config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    db = SessionLocal()
    try:
        cfg = get_global_config(db)
        default_item_code = getattr(cfg, 'default_item_code', '741')
        default_act_id = getattr(cfg, 'default_act_id', '76145')

        return JSONResponse(content={
            'rush_hour': cfg.rush_hour,
            'rush_minute': cfg.rush_minute,
            'item_code': default_item_code,
            'act_id': default_act_id
        })
    finally:
        db.close()


@app.post("/api/client/get_tasks")
async def client_get_tasks(
        req: ClientTaskRequest,
        request: Request
):
    """客户端获取任务列表"""
    token = request.headers.get('X-API-TOKEN')
    if token != config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    db = SessionLocal()
    try:
        uploader_id = req.uploader_id
        records = db.query(PhoneRecord).filter(
            PhoneRecord.uploaded_by == uploader_id,
            PhoneRecord.logged_in == True
        ).all()

        tasks = []
        for rec in records:
            tasks.append({
                'phone': rec.phone,
                'token': rec.token,
                'cookie': rec.cookie,
                'user_id': rec.user_id_ext,
                'mt_device_id': rec.mt_device_id,
                'raw_device_id': rec.raw_device_id,
                'h5_did': rec.h5_did,
                'h5_start_id': rec.h5_start_id,
                'bs_device_id': rec.bs_device_id,
                'user_agent': rec.user_agent,
                'webview_ua': rec.webview_ua,
                'mt_r': rec.mt_r,
                'mt_sn': rec.mt_sn,
                'rush_time_offset': rec.rush_time_offset
            })

        return JSONResponse(content={'status': 'success', 'tasks': tasks})
    finally:
        db.close()


@app.post("/api/client/report_result")
async def client_report_result(
        report: ResultReport,
        request: Request
):
    """客户端上报抢购结果"""
    token = request.headers.get('X-API-TOKEN')
    if token != config.API_TOKEN:
        raise HTTPException(status_code=403, detail="无权限")

    db = SessionLocal()
    try:
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == report.phone).first()
        if record:
            if report.success:
                record.bid_result = f"成功-订单{report.order_id}"
                record.balance = "待支付"
            else:
                record.bid_result = f"失败-{report.error[:50]}"

            record.last_updated = datetime.datetime.utcnow()
            db.commit()

        return JSONResponse(content={'status': 'success'})
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 60)
    logger.info("🔧 正在初始化服务器...")
    
    # 获取本机内网IP
    import socket
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        logger.info(f"✅ 检测到内网IP: {local_ip}")
    except Exception as e:
        logger.warning(f"⚠️ 无法检测内网IP: {e}，使用默认值 127.0.0.1")
    
    # 检查端口是否被占用
    import socket as sock_check
    sock = sock_check.socket(sock_check.AF_INET, sock_check.SOCK_STREAM)
    port_available = True
    try:
        sock.bind(('0.0.0.0', config.PORT))
        logger.info(f"✅ 端口 {config.PORT} 可用")
    except OSError as e:
        port_available = False
        logger.error(f"❌ 端口 {config.PORT} 已被占用: {e}")
        logger.error(f"💡 请检查是否有其他程序在使用此端口")
    finally:
        sock.close()
    
    if not port_available:
        logger.error("🛑 服务器启动失败：端口被占用")
        sys.exit(1)
    
    logger.info("\n" + "=" * 60)
    logger.info("=== i猫妈妈自动化管理系统启动 ===")
    logger.info("=" * 60)
    logger.info(f"\n📍 服务端配置:")
    logger.info(f"   监听地址: {config.HOST}:{config.PORT}")
    logger.info(f"   数据库: {config.DATABASE_URL}")
    logger.info(f"   API Token: {config.API_TOKEN[:10]}...")
    logger.info(f"\n📍 可通过以下地址访问：")
    logger.info(f"   1. 本地访问:     http://127.0.0.1:{config.PORT}")
    logger.info(f"   2. 本地访问:     http://localhost:{config.PORT}")
    logger.info(f"   3. 内网访问:     http://{local_ip}:{config.PORT}")
    logger.info(f"   4. 外网访问:     http://你的外网IP:{config.PORT} (需端口映射)")
    logger.info(f"\n💡 提示:")
    logger.info(f"   - Web管理端:   浏览器打开上述任一地址")
    logger.info(f"   - 客户端连接:  配置 SERVER_ADDRESSES 为上述地址")
    logger.info(f"   - API文档:     http://{local_ip}:{config.PORT}/docs")
    logger.info(f"   - 日志文件:    server.log")
    logger.info(f"\n{'=' * 60}\n")
    
    # 启动Uvicorn服务器
    try:
        logger.info(f"🚀 正在启动 Uvicorn 服务器...")
        uvicorn.run(
            app, 
            host=config.HOST, 
            port=config.PORT,
            log_level="info",
            access_log=True
        )
    except Exception as e:
        logger.error(f"❌ 服务器启动失败: {e}", exc_info=True)
        sys.exit(1)
