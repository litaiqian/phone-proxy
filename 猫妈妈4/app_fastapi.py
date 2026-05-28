#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈多账号自动化管理系统 - FastAPI版
主账号/子账号体系 + 银联支付 + 分布式客户端调度
"""

import os
import json
import time
import random
import threading
import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, status, Request, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship, backref
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import qrcode
import jwt
from datetime import timedelta

# 导入茅台协议
from demo import (
    MoutaiClient, generate_mt_k_and_v, generate_mt_device_id, generate_device_id_raw,
    generate_act_param, md5_hex, APP_VERSION, SDK_VERSION, generate_h5_did,
    generate_h5_start_id, generate_d_u_cookie, generate_bs_device_id,
    generate_headers_for_post, VCODE_SALT, BASE_URL, H5_BASE_URL, _post, _get
)

# ===================== 配置 =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
QRCODE_DIR = os.path.join(STATIC_DIR, "qrcodes")
os.makedirs(QRCODE_DIR, exist_ok=True)

SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天
API_TOKEN = "your-secure-token-change-me"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ===================== 数据库模型 =====================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(120), nullable=False)
    role = Column(String(20), default="admin")
    parent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 关系
    children = relationship("User", backref=backref("parent", remote_side=[id]))
    uploaded_phones = relationship("PhoneRecord", foreign_keys="PhoneRecord.user_id", back_populates="uploader")
    assigned_phones = relationship("PhoneRecord", foreign_keys="PhoneRecord.assigned_to", back_populates="assigned_user")

class PhoneRecord(Base):
    __tablename__ = "phone_records"
    phone = Column(String(20), primary_key=True, index=True)
    team = Column(String(100), default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)      # 上传者（主账号）
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)  # 分配给哪个子账号
    uploaded_by = Column(Integer, ForeignKey("users.id"))                 # 原始上传者
    code_sent = Column(Boolean, default=False)
    logged_in = Column(Boolean, default=False)
    bid_result = Column(String(200), default="")
    balance = Column(String(50), default="")
    last_updated = Column(DateTime, default=datetime.datetime.utcnow)

    # 茅台凭证
    token = Column(String(500), default="")
    cookie = Column(String(500), default="")
    user_id_ext = Column(String(50), default="")
    mt_device_id = Column(String(200), default="")
    raw_device_id = Column(String(100), default="")
    h5_did = Column(String(64), default="")
    h5_start_id = Column(String(64), default="")
    bs_device_id = Column(String(64), default="")
    user_agent = Column(String(200), default="")
    webview_ua = Column(String(300), default="")
    mt_r = Column(String(80), default="")
    mt_sn = Column(String(80), default="")

    # 支付状态
    pay_status = Column(String(20), default="unpaid")
    pay_qrcode = Column(String(200), default="")
    pay_link = Column(String(500), default="")

    # 关系
    uploader = relationship("User", foreign_keys=[user_id], back_populates="uploaded_phones")
    assigned_user = relationship("User", foreign_keys=[assigned_to], back_populates="assigned_phones")

class GlobalConfig(Base):
    __tablename__ = "global_config"
    id = Column(Integer, primary_key=True)
    rush_hour = Column(Integer, default=8)
    rush_minute = Column(Integer, default=58)
    auto_mode_enabled = Column(Boolean, default=False)
    auto_start_time = Column(String(5), default="08:00")
    item_code = Column(String(20), default="741")
    act_id = Column(String(20), default="76145")

# 创建表
Base.metadata.create_all(bind=engine)

# ===================== 辅助函数 =====================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_password_hash(password):
    return generate_password_hash(password)

def verify_password(plain_password, hashed_password):
    return check_password_hash(hashed_password, plain_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def get_current_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user

def build_client_from_record(record: PhoneRecord) -> MoutaiClient:
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
    client.user_agent = record.user_agent or client.user_agent
    client.webview_ua = record.webview_ua or client.webview_ua
    client.mt_r = record.mt_r or client.mt_r
    client.mt_sn = record.mt_sn or client.mt_sn
    return client

def check_login_validity(record: PhoneRecord) -> bool:
    if not record.token:
        return False
    try:
        client = build_client_from_record(record)
        headers = client._app_headers(need_sign=False)
        resp = _get(f"{BASE_URL}/xhr/front/user/info", headers=headers)
        data = resp.json()
        return data.get("code") == 2000
    except:
        return False

# ===================== FastAPI 应用 =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动后台任务
    threading.Thread(target=login_keepalive_worker, daemon=True).start()
    threading.Thread(target=auto_mode_worker, daemon=True).start()
    yield
    # 关闭时清理（可选）

app = FastAPI(title="猫妈妈自动化系统", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 后台任务函数
def login_keepalive_worker():
    while True:
        now = datetime.datetime.now()
        if now.hour >= 22 or now.hour < 6:
            next_refresh = now.replace(hour=6, minute=0, second=0)
            if now.hour >= 22:
                next_refresh += datetime.timedelta(days=1)
            time.sleep((next_refresh - now).total_seconds())
        else:
            time.sleep(random.randint(600, 2900))
        db = SessionLocal()
        try:
            records = db.query(PhoneRecord).filter(PhoneRecord.logged_in == True).all()
            for rec in records:
                valid = check_login_validity(rec)
                if not valid:
                    rec.logged_in = False
                    rec.token = ""
                    rec.cookie = ""
                    rec.user_id_ext = ""
                    db.commit()
                    print(f"[保鲜] {rec.phone} 登录失效")
        finally:
            db.close()

def auto_mode_worker():
    while True:
        db = SessionLocal()
        try:
            cfg = db.query(GlobalConfig).first()
            if cfg and cfg.auto_mode_enabled:
                now_str = datetime.datetime.now().strftime("%H:%M")
                if now_str == cfg.auto_start_time:
                    records = db.query(PhoneRecord).filter(PhoneRecord.logged_in == False).all()
                    for rec in records:
                        client = build_client_from_record(rec)
                        result = client.send_vcode(rec.phone)
                        if result.get("code") == 2000:
                            rec.code_sent = True
                            db.commit()
                            print(f"[自动模式] 验证码已发送 {rec.phone}")
                        time.sleep(2)
                    time.sleep(60)
        finally:
            db.close()
        time.sleep(30)

# ===================== API 模型 =====================
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str

class SubUserCreate(BaseModel):
    username: str
    password: str

class AssignPhonesRequest(BaseModel):
    subuser_id: int
    phones: List[str]

class SendCodeRequest(BaseModel):
    phone: str

class SubmitCodeRequest(BaseModel):
    phone: str
    code: str

class BatchSendRequest(BaseModel):
    min_delay: int = 10
    max_delay: int = 20

class ConfigUpdateRequest(BaseModel):
    rush_hour: Optional[int] = None
    rush_minute: Optional[int] = None
    auto_mode_enabled: Optional[bool] = None
    auto_start_time: Optional[str] = None
    item_code: Optional[str] = None
    act_id: Optional[str] = None

# ===================== API 路由 =====================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/auth/register")
async def register(data: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(400, "用户名已存在")
    user = User(username=data.username, password_hash=get_password_hash(data.password), role="admin")
    db.add(user)
    db.commit()
    return {"status": "success"}

@app.post("/api/auth/login")
async def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"status": "success", "token": token, "role": user.role, "user_id": user.id}

@app.post("/api/admin/subuser")
async def create_subuser(data: SubUserCreate, current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(400, "用户名已存在")
    sub = User(username=data.username, password_hash=get_password_hash(data.password), role="subuser", parent_id=current_user.id)
    db.add(sub)
    db.commit()
    return {"status": "success", "subuser_id": sub.id}

@app.get("/api/admin/subusers")
async def list_subusers(current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    subs = db.query(User).filter(User.parent_id == current_user.id, User.role == "subuser").all()
    return [{"id": s.id, "username": s.username} for s in subs]

@app.post("/api/admin/assign")
async def assign_phones(data: AssignPhonesRequest, current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    subuser = db.query(User).filter(User.id == data.subuser_id, User.parent_id == current_user.id).first()
    if not subuser:
        raise HTTPException(404, "子账号不存在")
    for phone in data.phones:
        record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        if record and record.user_id == current_user.id:
            record.assigned_to = subuser.id
    db.commit()
    return {"status": "success"}

@app.post("/api/upload")
async def upload_excel(file: UploadFile = File(...), current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    temp_path = os.path.join(BASE_DIR, "temp.xlsx")
    with open(temp_path, "wb") as f:
        f.write(await file.read())
    df = pd.read_excel(temp_path, header=None, dtype=str)
    imported = 0
    for _, row in df.iterrows():
        team = row[0].strip() if pd.notna(row[0]) else ""
        phone = str(row[1]).strip().split('.')[0] if pd.notna(row[1]) else ""
        if not phone.isdigit():
            continue
        existing = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
        if not existing:
            rec = PhoneRecord(phone=phone, team=team, user_id=current_user.id, uploaded_by=current_user.id)
            db.add(rec)
            imported += 1
    db.commit()
    os.remove(temp_path)
    return {"status": "success", "imported": imported}

@app.post("/api/send_code")
async def send_code(data: SendCodeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == data.phone).first()
    if not record or record.user_id != current_user.id:
        raise HTTPException(403, "无权限")
    if record.logged_in:
        raise HTTPException(400, "已登录")
    client = build_client_from_record(record)
    result = client.send_vcode(data.phone)
    if result.get("code") == 2000:
        record.code_sent = True
        db.commit()
        return {"status": "success"}
    raise HTTPException(400, "发送失败")

@app.post("/api/submit_code")
async def submit_code(data: SubmitCodeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == data.phone).first()
    if not record or record.user_id != current_user.id:
        raise HTTPException(403, "无权限")
    if record.logged_in:
        raise HTTPException(400, "已登录")
    client = build_client_from_record(record)
    result = client.login(data.phone, data.code)
    if result.get("code") == 2000:
        record.token = client.token
        record.cookie = client.cookie
        record.user_id_ext = client.user_id
        record.logged_in = True
        record.user_agent = client.user_agent
        record.webview_ua = client.webview_ua
        record.mt_r = client.mt_r
        record.mt_sn = client.mt_sn
        db.commit()
        return {"status": "success"}
    raise HTTPException(400, f"登录失败: {result.get('message')}")

@app.post("/api/batch_send")
async def batch_send(data: BatchSendRequest, current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    def task():
        with SessionLocal() as session:
            records = session.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id, PhoneRecord.logged_in == False).all()
            for rec in records:
                client = build_client_from_record(rec)
                client.send_vcode(rec.phone)
                time.sleep(random.randint(data.min_delay, data.max_delay))
    threading.Thread(target=task).start()
    return {"status": "success", "message": "批量发送已启动"}

@app.get("/api/phones")
async def list_phones(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "admin":
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.assigned_to == current_user.id).all()
    result = []
    for rec in records:
        result.append({
            "phone": rec.phone,
            "team": rec.team,
            "logged_in": rec.logged_in,
            "bid_result": rec.bid_result,
            "balance": rec.balance,
            "pay_status": rec.pay_status,
            "pay_qrcode": f"/static/qrcodes/{rec.phone}.png" if rec.pay_qrcode else "",
            "pay_link": rec.pay_link,
            "last_updated": rec.last_updated.isoformat() if rec.last_updated else ""
        })
    return result

@app.get("/api/stats")
async def get_stats(current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    base = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id)
    total = base.count()
    success_login = base.filter(PhoneRecord.logged_in == True).count()
    offline = base.filter(PhoneRecord.logged_in == False, (PhoneRecord.token != "") | (PhoneRecord.cookie != "")).count()
    never_login = base.filter(PhoneRecord.logged_in == False, PhoneRecord.token == "", PhoneRecord.cookie == "").count()
    bid_success = base.filter(PhoneRecord.bid_result.contains("成功")).count()
    qrcode_count = len([f for f in os.listdir(QRCODE_DIR) if f.endswith(".png")])
    return {"total": total, "success_login": success_login, "offline": offline, "never_login": never_login, "bid_success": bid_success, "qrcode_count": qrcode_count}

@app.post("/api/refresh_login")
async def refresh_login(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "admin":
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.assigned_to == current_user.id).all()
    results = {}
    for rec in records:
        valid = check_login_validity(rec)
        if not valid and rec.logged_in:
            rec.logged_in = False
            rec.token = ""
            rec.cookie = ""
            db.commit()
        results[rec.phone] = {"valid": valid}
    return {"status": "success", "results": results}

@app.post("/api/query_bid")
async def query_bid(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "admin":
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == current_user.id).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.assigned_to == current_user.id).all()
    for rec in records:
        if rec.logged_in:
            client = build_client_from_record(rec)
            orders = client.query_order_list()
            for order in orders:
                if order.get("status") == 2:
                    rec.bid_result = f"已支付-{order.get('orderId','')}"
                    rec.pay_status = "paid"
                elif order.get("status") == 1:
                    rec.bid_result = f"待支付-{order.get('orderId','')}"
                    rec.pay_status = "unpaid"
            db.commit()
    return {"status": "success"}

@app.get("/api/config")
async def get_config(db: Session = Depends(get_db)):
    cfg = db.query(GlobalConfig).first()
    if not cfg:
        cfg = GlobalConfig()
        db.add(cfg)
        db.commit()
    return {"rush_hour": cfg.rush_hour, "rush_minute": cfg.rush_minute, "auto_mode_enabled": cfg.auto_mode_enabled, "auto_start_time": cfg.auto_start_time, "item_code": cfg.item_code, "act_id": cfg.act_id}

@app.post("/api/config")
async def update_config(data: ConfigUpdateRequest, current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    cfg = db.query(GlobalConfig).first()
    if not cfg:
        cfg = GlobalConfig()
        db.add(cfg)
    if data.rush_hour is not None: cfg.rush_hour = data.rush_hour
    if data.rush_minute is not None: cfg.rush_minute = data.rush_minute
    if data.auto_mode_enabled is not None: cfg.auto_mode_enabled = data.auto_mode_enabled
    if data.auto_start_time is not None: cfg.auto_start_time = data.auto_start_time
    if data.item_code is not None: cfg.item_code = data.item_code
    if data.act_id is not None: cfg.act_id = data.act_id
    db.commit()
    return {"status": "success"}

# ===================== 客户端专用 API =====================
@app.post("/api/worker/get_tasks")
async def worker_get_tasks(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("X-API-TOKEN")
    if token != API_TOKEN:
        raise HTTPException(403, "Invalid token")
    body = await request.json()
    subuser_id = body.get("subuser_id")
    if not subuser_id:
        raise HTTPException(400, "subuser_id required")
    records = db.query(PhoneRecord).filter(PhoneRecord.assigned_to == subuser_id, PhoneRecord.logged_in == True).all()
    tasks = []
    for rec in records:
        tasks.append({
            "phone": rec.phone, "token": rec.token, "cookie": rec.cookie, "user_id": rec.user_id_ext,
            "mt_device_id": rec.mt_device_id, "raw_device_id": rec.raw_device_id,
            "h5_did": rec.h5_did, "h5_start_id": rec.h5_start_id, "bs_device_id": rec.bs_device_id,
            "user_agent": rec.user_agent, "webview_ua": rec.webview_ua, "mt_r": rec.mt_r, "mt_sn": rec.mt_sn
        })
    return {"tasks": tasks}

@app.get("/api/worker/get_config")
async def worker_get_config(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("X-API-TOKEN")
    if token != API_TOKEN:
        raise HTTPException(403, "Invalid token")
    cfg = db.query(GlobalConfig).first()
    if not cfg:
        cfg = GlobalConfig()
        db.add(cfg)
        db.commit()
    return {"rush_hour": cfg.rush_hour, "rush_minute": cfg.rush_minute, "item_code": cfg.item_code, "act_id": cfg.act_id}

@app.post("/api/worker/report_result")
async def worker_report_result(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("X-API-TOKEN")
    if token != API_TOKEN:
        raise HTTPException(403, "Invalid token")
    data = await request.json()
    phone = data.get("phone")
    success = data.get("success", False)
    order_id = data.get("order_id", "")
    pay_link = data.get("pay_link", "")
    error = data.get("error", "")
    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        return {"status": "error", "message": "not found"}
    if success:
        record.bid_result = f"成功-订单{order_id}"
        record.pay_link = pay_link
        if pay_link:
            qr_path = os.path.join(QRCODE_DIR, f"{phone}.png")
            img = qrcode.make(pay_link)
            img.save(qr_path)
            record.pay_qrcode = f"/static/qrcodes/{phone}.png"
        record.pay_status = "unpaid"
    else:
        record.bid_result = f"失败-{error[:50]}"
    db.commit()
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    # 检查端口是否被占用，若被占用则使用 5001
    port = 5000
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.close()
    except OSError:
        port = 5001
        print(f"端口5000已被占用，将使用端口{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)