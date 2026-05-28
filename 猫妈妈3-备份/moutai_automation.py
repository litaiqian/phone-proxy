#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i茅台多账号自动化管理系统
整合：Web管理端 + 并发任务调度 + 自动登录保鲜 + 错峰抢购 + App回调接口
"""

import os
import sys
import json
import time
import threading
import random
import datetime
from typing import Dict, Optional, Any, List
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, send_from_directory
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

import qrcode
from flask import send_from_directory
BASEDIR = os.path.abspath(os.path.dirname(__file__))
QRCODE_FOLDER = os.path.join(BASEDIR, 'static', 'qrcodes')
os.makedirs(QRCODE_FOLDER, exist_ok=True)
# 导入茅台协议的完整实现（demo.py 中的所有函数）
# 注意：demo.py 必须与当前文件放在同一目录，或已安装为模块
# 在原有导入下方添加
from demo import _load_accounts, _load_account_to_client, BASE_URL, _get
from demo import (
    MoutaiClient,
    generate_mt_k_and_v,
    generate_mt_device_id,
    generate_device_id_raw,
    generate_act_param,
    md5_hex,
    APP_VERSION,
    SDK_VERSION,
    generate_h5_did,
    generate_h5_start_id,
    generate_d_u_cookie,
    generate_bs_device_id,
    generate_headers_for_post,
    generate_wasm_sign,
    VCODE_SALT,
    BASE_URL,
    H5_BASE_URL,
    _post,
    _get
)

# ===================== 配置 =====================
BASEDIR = os.path.abspath(os.path.dirname(__file__))
from datetime import timedelta
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASEDIR, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASEDIR, 'uploads')
    DATA_FOLDER = os.path.join(BASEDIR, 'data')
    MAX_THREADS = 20
    HOST = '0.0.0.0'
    PORT = 5000
    API_TOKEN = 'your-secure-token-change-me'   # 与安卓App保持一致
    # 强制配置 Cookie 策略
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False  # 开发环境下不使用 HTTPS
    SESSION_COOKIE_DOMAIN = False  # 允许 127.0.0.1 和 localhost
    # 全局抢购配置（默认值）
    DEFAULT_RUSH_HOUR = 8
    DEFAULT_RUSH_MINUTE = 58
    AUTO_MODE_DEFAULT = False   # 默认关闭自动模式（手动输入验证码）
    AUTO_START_TIME = "08:00"   # 自动模式开始处理的时间（HH:MM）

    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 604800  # session 有效期
    REMEMBER_COOKIE_DURATION = 2592000  # 记住我 30 天
# ===================== 数据库模型 =====================
db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class PhoneRecord(db.Model):
    team = db.Column(db.String(100), default='')
    phone = db.Column(db.String(20), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))          # 系统用户ID
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    code_sent = db.Column(db.Boolean, default=False)
    logged_in = db.Column(db.Boolean, default=False)
    bid_result = db.Column(db.String(200), default='')
    balance = db.Column(db.String(50), default='')
    last_updated = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # 茅台登录凭证和设备指纹
    token = db.Column(db.String(500), default='')          # MT-Token
    cookie = db.Column(db.String(500), default='')         # MT-Token-Wap
    user_id_ext = db.Column(db.String(50), default='')     # 茅台 userId
    mt_device_id = db.Column(db.String(200), default='')   # MT-Device-ID
    raw_device_id = db.Column(db.String(100), default='')  # 原始设备ID
    h5_did = db.Column(db.String(64), default='')          # 瑞数H5设备指纹
    h5_start_id = db.Column(db.String(64), default='')     # 瑞数会话ID
    bs_device_id = db.Column(db.String(64), default='')    # _bs_device_id cookie

    # 扩展字段
    auto_mode = db.Column(db.Boolean, default=False)       # 是否自动接收验证码（依赖App推送）
    rush_time_offset = db.Column(db.Integer, default=0)    # 抢购偏移秒数（-120 ~ 120）

    #服务端 保存完整设备指纹和 UA
    user_agent = db.Column(db.String(200), default='')  # APP 原生 UA
    webview_ua = db.Column(db.String(300), default='')  # WebView UA
    mt_r = db.Column(db.String(80), default='')  # MT-R 风控串
    mt_sn = db.Column(db.String(80), default='')  # MT-SN 签名标识
class GlobalConfig(db.Model):
    """全局配置表（单行）"""
    id = db.Column(db.Integer, primary_key=True)
    rush_hour = db.Column(db.Integer, default=Config.DEFAULT_RUSH_HOUR)
    rush_minute = db.Column(db.Integer, default=Config.DEFAULT_RUSH_MINUTE)
    auto_mode_enabled = db.Column(db.Boolean, default=Config.AUTO_MODE_DEFAULT)
    auto_start_time = db.Column(db.String(5), default=Config.AUTO_START_TIME)  # "08:00"

# ===================== Flask 应用初始化 =====================
app = Flask(__name__)
app.config.from_object(Config)
app.config['SESSION_COOKIE_SECURE'] = False   # 明确允许 HTTP
app.permanent_session_lifetime = timedelta(days=7)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 创建目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===================== 辅助函数 =====================
def get_global_config():
    """获取全局配置（若不存在则创建默认）"""
    cfg = GlobalConfig.query.first()
    if not cfg:
        cfg = GlobalConfig(
            rush_hour=Config.DEFAULT_RUSH_HOUR,
            rush_minute=Config.DEFAULT_RUSH_MINUTE,
            auto_mode_enabled=Config.AUTO_MODE_DEFAULT,
            auto_start_time=Config.AUTO_START_TIME
        )
        db.session.add(cfg)
        db.session.commit()
    return cfg

def build_client_from_record(phone: str) -> MoutaiClient:
    """从数据库记录恢复 MoutaiClient 实例（复用设备指纹）"""
    record = PhoneRecord.query.get(phone)
    if not record:
        raise ValueError(f"手机号 {phone} 不存在")

    # 如果已有设备指纹，则复用；否则生成新的并保存
    if record.raw_device_id:
        client = MoutaiClient(
            android_id=record.raw_device_id[:16] if len(record.raw_device_id) >= 16 else "",
            bs_dvid=record.mt_device_id.replace("clips_", "") if record.mt_device_id else ""
        )
        # 手动注入保存的状态
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
        # 保存新生成的指纹
        record.raw_device_id = client.raw_device_id
        record.mt_device_id = client.mt_device_id
        record.h5_did = client.h5_did
        record.h5_start_id = client.h5_start_id
        record.bs_device_id = client.bs_device_id
        db.session.commit()
    return client

def check_login_validity(phone: str) -> bool:
    """从 iplala_accounts.json 加载账号信息并验证登录状态（与 demo.py 保持一致）"""
    accounts_file = os.path.join(BASEDIR, 'accounts.json')
    try:
        accounts = _load_accounts(accounts_file)
    except Exception as e:
        print(f"[检查登录] 加载 iplala_accounts.json 失败: {e}，视为无账号")
        return False

    acc = next((a for a in accounts if a.get("mobile") == phone), None)
    if not acc:
        print(f"[检查登录] {phone} 未在 iplala_accounts.json 中找到，视为掉线")
        return False

    try:
        # 创建客户端并恢复账号数据（完全复用 demo.py 的逻辑）
        client = MoutaiClient(bs_dvid=acc.get('bs-dvid', ''))
        _load_account_to_client(acc, client)

        # 使用一个需要登录的接口验证（例如获取用户信息）
        headers = client._app_headers(need_sign=False)
        resp = _get(f"{BASE_URL}/xhr/front/user/info", headers=headers)
        data = resp.json()
        is_valid = (data.get("code") == 2000)
        print(f"[检查登录] {phone} 结果: {'有效' if is_valid else '无效'} (code={data.get('code')})")
        return is_valid
    except Exception as e:
        print(f"[检查登录] {phone} 异常: {e}")
        return False

def update_login_status(phone: str, is_valid: bool):
    """更新数据库中的登录状态，若无效则清空凭证"""
    record = PhoneRecord.query.get(phone)
    if record:
        if is_valid:
            record.logged_in = True
        else:
            record.logged_in = False
            # 清空无效凭证
            record.token = ""
            record.cookie = ""
            record.user_id_ext = ""
        record.last_updated = datetime.datetime.utcnow()
        db.session.commit()

# ===================== 后台任务：登录保鲜（定期检查） =====================
import random

def login_keepalive_worker():
    """仅在白天（6:00-22:00）执行，随机间隔（10~48分钟）检查一次所有账号的登录状态"""
    with app.app_context():
        while True:
            now = datetime.datetime.now()
            current_hour = now.hour

            # 判断是否在夜间休息时段：22:00 到 次日 6:00
            if current_hour >= 22 or current_hour < 6:
                # 计算到下一个 6:00 的秒数
                next_refresh = now.replace(hour=6, minute=0, second=0, microsecond=0)
                if now.hour >= 22:
                    # 如果当前时间 >=22:00，下一个6:00是明天
                    next_refresh += datetime.timedelta(days=1)
                sleep_seconds = (next_refresh - now).total_seconds()
                print(f"[保鲜] 当前处于夜间休息时段（22:00-6:00），将睡眠 {sleep_seconds/3600:.1f} 小时，直到 {next_refresh.strftime('%Y-%m-%d %H:%M')}")
                time.sleep(sleep_seconds)
                continue  # 睡眠结束后重新进入循环，继续检查

            # 白天时段：随机睡眠 600 ~ 2900 秒（10~48分钟）
            sleep_seconds = random.randint(600, 2900)
            time.sleep(sleep_seconds)

            records = PhoneRecord.query.all()
            for rec in records:
                if not rec.logged_in:
                    continue
                valid = check_login_validity(rec.phone)
                if not valid:
                    print(f"[保鲜] {rec.phone} 登录已失效，标记为掉线")
                    update_login_status(rec.phone, False)
                else:
                    rec.last_updated = datetime.datetime.utcnow()
                    db.session.commit()

# ===================== 后台任务：自动模式批量处理（定时发送验证码） =====================
def auto_mode_processor():
    """
    当全局自动模式开启时，在设置的 auto_start_time 开始，批量向所有 auto_mode=True 的账号发送验证码，
    并等待 App 推送验证码完成登录。若发送失败则重试一次，最后放弃。
    """
    with app.app_context():
        cfg = get_global_config()
        if not cfg.auto_mode_enabled:
            return
        target_time = cfg.auto_start_time  # "08:00"
        while True:
            now = datetime.datetime.now()
            current = now.strftime("%H:%M")
            if current == target_time:
                print(f"[自动模式] 到达预定时间 {target_time}，开始处理所有自动账号")
                records = PhoneRecord.query.filter_by(auto_mode=True).all()
                for rec in records:
                    # 如果已经登录，跳过
                    if rec.logged_in:
                        continue
                    # 发送验证码（最多两次）
                    for attempt in range(2):
                        success = send_verification_code_impl(rec.phone)
                        if success:
                            print(f"[自动模式] {rec.phone} 验证码已发送，等待App回调")
                            break
                        else:
                            print(f"[自动模式] {rec.phone} 发送失败，重试({attempt+1}/2)")
                            time.sleep(2)
                    else:
                        print(f"[自动模式] {rec.phone} 两次发送均失败，放弃")
                # 等待一分钟后再次检查，避免重复触发
                time.sleep(60)
            else:
                time.sleep(30)

def send_verification_code_impl(phone: str) -> bool:
    """实际发送验证码（调用茅台接口）；若已登录则直接返回False"""
    record = PhoneRecord.query.get(phone)
    if record and record.logged_in:
        print(f"[发送验证码] {phone} 已登录，跳过发送")
        return False

    client = build_client_from_record(phone)
    result = client.send_vcode(phone)
    success = result.get("code") == 2000
    if success:
        if record:
            record.code_sent = True
            record.last_updated = datetime.datetime.utcnow()
            db.session.commit()
    return success

# ===================== 后台任务：抢购调度器 =====================
rush_job_started = False
def rush_scheduler():
    """根据全局抢购时间，错峰启动抢购任务"""
    global rush_job_started
    with app.app_context():
        while True:
            cfg = get_global_config()
            rush_hour = cfg.rush_hour
            rush_minute = cfg.rush_minute
            now = datetime.datetime.now()
            target = now.replace(hour=rush_hour, minute=rush_minute, second=0, microsecond=0)
            # 如果当前时间已经超过今天的抢购时间，则目标设为明天
            if now >= target:
                target += datetime.timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            if wait_seconds > 0:
                time.sleep(wait_seconds - 60)  # 提前60秒进入准备状态
                # 等待直到目标时间点
                while datetime.datetime.now() < target:
                    time.sleep(0.1)
                # 开始抢购
                if not rush_job_started:
                    rush_job_started = True
                    start_rush_for_all_accounts()
                    rush_job_started = False
            else:
                time.sleep(60)

def start_rush_for_all_accounts():
    """错峰启动所有账号的抢购"""
    with app.app_context():
        records = PhoneRecord.query.filter_by(logged_in=True).all()
        if not records:
            print("[抢购] 没有已登录账号")
            return
        total = len(records)
        # 分成三批
        batch_size = total // 3
        batches = [
            records[:batch_size],
            records[batch_size:2*batch_size],
            records[2*batch_size:]
        ]
        delays = [0, 60, 59.5]  # 秒数偏移：第一批立即，第二批延迟60秒，第三批延迟59.5秒（9点前500ms）
        for batch, delay in zip(batches, delays):
            if not batch:
                continue
            timer = threading.Timer(delay, lambda b=batch: run_rush_for_batch(b))
            timer.daemon = True
            timer.start()

def run_rush_for_batch(records: List[PhoneRecord]):
    """对一批账号执行抢购（需要从数据库读取商品编码、活动ID，目前使用示例）"""
    # 示例商品：黄小西（741）替换为实际ID
    item_code = "741"
    act_id = "76145"
    amount = "1"
    for rec in records:
        try:
            client = build_client_from_record(rec.phone)
            result = client.rush_purchase(item_code, act_id, amount)
            if result.get("code") == 2000:
                # 抢购成功，立即调用下单支付流程
                complete_order_and_pay(rec, item_code, act_id, amount, result)
            else:
                print(f"[抢购] {rec.phone} 失败: {result}")
        except Exception as e:
            print(f"[抢购] {rec.phone} 异常: {e}")


def complete_order_and_pay(rec: PhoneRecord, item_code: str, act_id: str, amount: str, rush_result: dict):
    """抢购成功后自动下单、支付、生成二维码"""
    try:
        client = build_client_from_record(rec.phone)
        # 获取收货地址（优先默认地址）
        addresses = client.get_addresses()
        if not addresses:
            print(f"[下单] {rec.phone} 无收货地址，跳过")
            return
        default_addr = next((addr for addr in addresses if addr.get("dft")), addresses[0])

        record_id = rush_result.get("data", {}).get("priorityRecordId", 0)
        if not record_id:
            print(f"[下单] {rec.phone} 未获取到 priorityRecordId")
            return

        # 组单
        compose_res = client.compose_order(
            spu_id=item_code,
            count=int(amount),
            priority_record_id=record_id,
            address=default_addr
        )
        if compose_res.get("code") != 2000:
            print(f"[组单] {rec.phone} 失败: {compose_res}")
            return

        # 提交订单
        submit_res = client.submit_order(
            spu_id=item_code,
            count=int(amount),
            priority_record_id=record_id,
            address=default_addr
        )
        if submit_res.get("code") != 2000:
            print(f"[下单] {rec.phone} 失败: {submit_res}")
            return
        order_id = submit_res.get("data", {}).get("orderId")
        print(f"[下单] {rec.phone} 成功，订单号 {order_id}")

        # 支付（获取支付宝 H5 链接）
        pay_res = client.pay_order(order_id)
        if pay_res.get("code") != 2000:
            print(f"[支付] {rec.phone} 失败: {pay_res}")
            return
        channel_trade_sn = pay_res.get("data", {}).get("channelTradeSn")
        if not channel_trade_sn:
            print(f"[支付] {rec.phone} 未获取到 TN")
            return

        # 请求支付网关获取 SDK 串
        gw_result = client.request_pay(channel_trade_sn, pay_channel="70")
        code = gw_result.get("code")
        if isinstance(code, str):
            code = int(code)
        if code not in (200, 2000):
            print(f"[支付网关] {rec.phone} 失败: {gw_result}")
            return

        p_data = gw_result.get("data")
        sdk_str = p_data if isinstance(p_data, str) else (
            p_data.get("payInfo") or p_data.get("alipay_sdk")
            or p_data.get("orderInfo") or p_data.get("AUTH_CODE", "")
        ) if isinstance(p_data, dict) else ""

        if not sdk_str:
            print(f"[支付网关] {rec.phone} 未返回 SDK 串")
            return

        # 转链获取 H5 支付链接
        h5_result = client.convert_to_h5(sdk_str)
        if not h5_result.get("success"):
            print(f"[转链] {rec.phone} 失败: {h5_result.get('message')}")
            return
        h5_url = h5_result["h5Url"]
        print(f"[支付] {rec.phone} H5 链接生成成功: {h5_url[:80]}...")

        # 生成二维码图片
        qrcode_path = os.path.join(QRCODE_FOLDER, f"{rec.phone}.png")
        img = qrcode.make(h5_url)
        img.save(qrcode_path)
        print(f"[二维码] {rec.phone} 已保存: {qrcode_path}")

        # 更新数据库中标结果（包含订单号和支付链接信息）
        rec.bid_result = f"成功-订单{order_id}"
        rec.balance = "待支付"  # 可根据实际情况更新
        rec.last_updated = datetime.datetime.utcnow()
        db.session.commit()

    except Exception as e:
        print(f"[下单支付] {rec.phone} 异常: {e}")
        import traceback
        traceback.print_exc()
# ===================== Flask 路由（原有 + 新增） =====================
@app.route('/qrcode/<phone>')
@login_required
def get_qrcode(phone):
    """返回指定手机号的支付二维码图片"""
    qrcode_file = os.path.join(QRCODE_FOLDER, f"{phone}.png")
    if os.path.exists(qrcode_file):
        return send_from_directory(QRCODE_FOLDER, f"{phone}.png")
    else:
        return "", 404

#商品列表预览  刷新登录状态”或单独“刷新列表”时，就会调用此接口。如果接口返回 200
@app.route('/api/sample_products', methods=['GET'])
@login_required
def sample_products():
    """
    示例商品列表接口（后续替换为真实商品地址）
    需要登录才能访问，用于验证登录有效性
    """
    # 模拟商品数据（实际可从此处调用真实的商品列表API）
    products = [
        {"name": "茅台飞天53度 500ml", "price": "1499元"},
        {"name": "茅台生肖酒 虎年", "price": "2499元"},
        {"name": "茅台王子酒 酱香经典", "price": "398元"},
        {"name": "茅台迎宾酒 中国红", "price": "168元"},
    ]
    return jsonify(products)

# 登录/注册（略，与原app.py相同，可复制）
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')


from flask import session   # 确保已导入 session
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.permanent = True          # 🔥 关键修复：使 session 长期有效
            login_user(user, remember=True, duration=timedelta(days=30))
            flash('登录成功')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    records = PhoneRecord.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', records=records, User=User)

# 导入Excel接口（同原版）
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_excel():
    # 与原代码相同，略
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': '没有文件'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    try:
        df = pd.read_excel(filepath, header=None, dtype=str, engine='openpyxl')
        imported = 0
        skipped = 0
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
            existing = db.session.get(PhoneRecord, phone)
            if not existing:
                rec = PhoneRecord(
                    team=team,
                    phone=phone,
                    user_id=current_user.id,
                    uploaded_by=current_user.id,
                    auto_mode=get_global_config().auto_mode_enabled   # 继承全局自动模式
                )
                db.session.add(rec)
                imported += 1
            else:
                skipped += 1
        db.session.commit()
        msg = f'成功导入 {imported} 条新手机号'
        if skipped:
            msg += f'，跳过 {skipped} 条（已存在或格式错误）'
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'解析失败: {str(e)}'}), 400

# 发送验证码（支持自动模式限制）
@app.route('/api/send_code', methods=['POST'])
@login_required
def api_send_code():
    data = request.json
    phone = data.get('phone', '').strip()
    record = PhoneRecord.query.get(phone)
    if not record or record.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    # 如果账号已登录，不允许再发送验证码（按钮应置灰）
    if record.logged_in:
        return jsonify({'status': 'error', 'message': '账号已登录，无需发送验证码'}), 400
    # 调用发送逻辑
    success = send_verification_code_impl(phone)
    if success:
        return jsonify({'status': 'success', 'message': '验证码已发送'})
    else:
        return jsonify({'status': 'error', 'message': '发送失败，请检查手机号或稍后重试'}), 400

# 提交验证码（手动输入）
@app.route('/api/submit_code', methods=['POST'])
@login_required
def api_submit_code():
    data = request.json
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    record = PhoneRecord.query.get(phone)


    if not record or record.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    if record.logged_in:
        return jsonify({'status': 'error', 'message': '账号已登录，无需重复提交'}), 400
    client = build_client_from_record(phone)
    result = client.login(phone, code)

    #服务端 在登录成功时保存这些字段
    record.user_agent = client.user_agent
    record.webview_ua = client.webview_ua
    record.mt_r = client.mt_r
    record.mt_sn = client.mt_sn

    if result.get("code") == 2000:
        # 保存登录信息
        record.token = client.token
        record.cookie = client.cookie
        record.user_id_ext = client.user_id
        record.logged_in = True
        record.last_updated = datetime.datetime.utcnow()
        db.session.commit()
        # 同时保存到 iplala_accounts.json（与demo.py兼容）
        save_account_to_json(phone, client)
        return jsonify({'status': 'success', 'message': '登录成功'})
    else:
        return jsonify({'status': 'error', 'message': f'登录失败: {result.get("message")}'}), 400

def save_account_to_json(phone, client):
    """将登录信息保存到 iplala_accounts.json（复用demo.py格式）"""
    accounts_file = os.path.join(BASEDIR, 'accounts.json')
    accounts = []
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
    # 查找是否已存在
    idx = next((i for i, acc in enumerate(accounts) if acc.get("mobile") == phone), -1)
    record = PhoneRecord.query.get(phone)
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

# App 回调接口（接收验证码）
@app.route('/api/receive_sms', methods=['POST'])
def receive_sms():
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    data = request.json
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    if not phone or not code:
        return jsonify({'status': 'error', 'message': '参数不完整'}), 400
    record = PhoneRecord.query.get(phone)
    if not record:
        return jsonify({'status': 'error', 'message': '手机号未在系统中'}), 404
    if record.logged_in:
        return jsonify({'status': 'success', 'message': '账号已登录，忽略验证码'})
    # 自动提交登录
    client = build_client_from_record(phone)

    #服务端 在登录成功时保存这些字段
    record.user_agent = client.user_agent
    record.webview_ua = client.webview_ua
    record.mt_r = client.mt_r
    record.mt_sn = client.mt_sn

    result = client.login(phone, code)
    if result.get("code") == 2000:
        record.token = client.token
        record.cookie = client.cookie
        record.user_id_ext = client.user_id
        record.logged_in = True
        record.last_updated = datetime.datetime.utcnow()
        db.session.commit()
        save_account_to_json(phone, client)
        return jsonify({'status': 'success', 'message': '自动登录成功'})
    else:
        return jsonify({'status': 'error', 'message': f'登录失败: {result.get("message")}'}), 400

# 查询单个手机号状态
@app.route('/api/phone_status/<phone>')
@login_required
def phone_status(phone):
    record = PhoneRecord.query.get(phone)
    if not record or record.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': '无权限'}), 404
    uploader = User.query.get(record.uploaded_by)
    return jsonify({
        'phone': record.phone,
        'team': record.team,
        'uploaded_by': uploader.username if uploader else '未知',
        'code_sent': record.code_sent,
        'logged_in': record.logged_in,
        'balance': record.balance,
        'bid_result': record.bid_result,
        'last_updated': record.last_updated.isoformat() if record.last_updated else ''
    })

# 导出数据
@app.route('/api/export')
@login_required
def export_data():
    records = PhoneRecord.query.filter_by(user_id=current_user.id).all()
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
    output = os.path.join(app.config['UPLOAD_FOLDER'], 'export.xlsx')
    df.to_excel(output, index=False)
    return send_from_directory(app.config['UPLOAD_FOLDER'], 'export.xlsx', as_attachment=True)

# 统计接口
@app.route('/api/stats')
@login_required
def stats():
    base_query = PhoneRecord.query.filter_by(user_id=current_user.id)
    total = base_query.count()
    success_login = base_query.filter_by(logged_in=True).count()

    # 掉线：有凭证但未登录
    offline = base_query.filter(PhoneRecord.logged_in == False,
                                (PhoneRecord.token != '') | (PhoneRecord.cookie != '')).count()
    # 未登录：无任何凭证
    never_login = base_query.filter(PhoneRecord.logged_in == False,
                                    PhoneRecord.token == '',
                                    PhoneRecord.cookie == '').count()

    # 二维码数量：遍历文件（注意性能，如果记录数很多可优化）
    qrcode_count = 0
    for rec in base_query.all():
        qrcode_path = os.path.join(QRCODE_FOLDER, f"{rec.phone}.png")
        if os.path.exists(qrcode_path):
            qrcode_count += 1

    bid_success = base_query.filter(PhoneRecord.bid_result.contains('成功')).count()

    return jsonify({
        'total': total,
        'success_login': success_login,
        'offline': offline,
        'never_login': never_login,
        'bid_success': bid_success,
        'qrcode_count': qrcode_count
    })

# 一键批量发送验证码（手动触发）
@app.route('/api/batch_send_code', methods=['POST'])
@login_required
def batch_send_code():
    data = request.json
    min_delay = int(data.get('min_delay', 10))
    max_delay = int(data.get('max_delay', 20))

    # ✅ 在主线程获取当前用户ID
    user_id = current_user.id

    # 获取所有手机号（仅用于统计总数）
    phones = [r.phone for r in PhoneRecord.query.filter_by(user_id=user_id).all()]
    if not phones:
        return jsonify({'status': 'error', 'message': '无号码'}), 400

    def batch_task():
        with app.app_context():
            # ✅ 使用传入的 user_id 进行查询
            all_records = PhoneRecord.query.filter_by(user_id=user_id).all()
            pending_phones = [rec.phone for rec in all_records if not rec.logged_in]

            if not pending_phones:
                print("[批量发送] 没有需要发送验证码的账号（所有账号均已登录）")
                return

            for phone in pending_phones:
                send_verification_code_impl(phone)
                delay = random.randint(min_delay, max_delay)
                time.sleep(delay)

            print(f"[批量发送] 已完成，共发送 {len(pending_phones)} 个账号")

    threading.Thread(target=batch_task, daemon=True).start()

    pending_count = sum(1 for r in PhoneRecord.query.filter_by(user_id=user_id).all() if not r.logged_in)
    return jsonify({
        'status': 'success',
        'message': f'批量发送已启动，共{len(phones)}个账号，其中{pending_count}个需要发送，{len(phones) - pending_count}个已登录自动跳过'
    })


#一键清空所有账号
@app.route('/api/clear_all_records', methods=['POST'])
@login_required
def clear_all_records():
    try:
        records = PhoneRecord.query.filter_by(user_id=current_user.id).all()
        for rec in records:
            qrcode_path = os.path.join(QRCODE_FOLDER, f"{rec.phone}.png")
            if os.path.exists(qrcode_path):
                os.remove(qrcode_path)
        PhoneRecord.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        return jsonify({'status': 'success', 'message': '已清空所有账号及二维码'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
# --------------------- 新增接口 ---------------------
# 获取全局配置
@app.route('/api/get_config', methods=['GET'])
@login_required
def get_config():
    cfg = get_global_config()
    return jsonify({
        'rush_hour': cfg.rush_hour,
        'rush_minute': cfg.rush_minute,
        'auto_mode_enabled': cfg.auto_mode_enabled,
        'auto_start_time': cfg.auto_start_time
    })

# 更新全局配置（抢购时间、自动模式等）
@app.route('/api/set_config', methods=['POST'])
@login_required
def set_config():
    data = request.json
    cfg = get_global_config()
    if 'rush_hour' in data:
        cfg.rush_hour = int(data['rush_hour'])
    if 'rush_minute' in data:
        cfg.rush_minute = int(data['rush_minute'])
    if 'auto_mode_enabled' in data:
        cfg.auto_mode_enabled = bool(data['auto_mode_enabled'])
    if 'auto_start_time' in data:
        cfg.auto_start_time = data['auto_start_time']
    db.session.commit()
    return jsonify({'status': 'success'})

# 刷新登录状态（前端点击按钮触发）
import sys
# 在 refresh_login 路由之前添加一个辅助函数（可选，直接写在路由里也可）
def _get_login_status_desc(phone: str, valid: bool) -> str:
    """根据验证结果和凭证存在性返回状态描述（安全版本）"""
    if valid:
        return 'success'
    record = PhoneRecord.query.get(phone)
    if record and (record.token or record.cookie):
        return 'offline'
    # 安全读取 iplala_accounts.json
    accounts_file = os.path.join(BASEDIR, 'accounts.json')
    try:
        if os.path.exists(accounts_file):
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
            if any(a.get('mobile') == phone for a in accounts):
                return 'offline'
    except Exception:
        pass  # 忽略读取错误，返回 never
    return 'never'
from flask import session as flask_session
@app.route('/api/refresh_login', methods=['POST'])
@login_required
def refresh_login():
    phones = [r.phone for r in PhoneRecord.query.filter_by(user_id=current_user.id).all()]
    results = {}
    for phone in phones:
        try:
            valid = check_login_validity(phone)
            update_login_status(phone, valid)
            status_desc = _get_login_status_desc(phone, valid)
        except Exception as e:
            app.logger.error(f"Refresh login error for {phone}: {e}")
            valid = False
            status_desc = 'never'   # 视为从未登录
        results[phone] = {'valid': valid, 'status_desc': status_desc}
    db.session.remove()
    return jsonify({'status': 'success', 'results': results})

# 查询所有中标结果（预留接口）
@app.route('/api/query_bid_results', methods=['POST'])
@login_required
def query_bid_results():
    """实时查询每个账号的中标结果，更新数据库并返回最新结果"""
    records = PhoneRecord.query.filter_by(user_id=current_user.id).all()
    results = {}
    for rec in records:
        if not rec.logged_in or not rec.token:
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
            continue
        try:
            client = build_client_from_record(rec.phone)
            # 调用订单查询接口获取中标信息
            orders = client.query_order_list()
            winning = [o for o in orders if o.get("status") in (1, 2, 3)]  # 待支付/已支付
            if winning:
                bid_str = f"中奖-{winning[0].get('itemName', '商品')}"
                # 更新数据库
                rec.bid_result = bid_str
                # 如果有余额字段，可另行获取
                rec.balance = winning[0].get("totalAmount", "")
            else:
                rec.bid_result = "未中奖"
            db.session.commit()
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
        except Exception as e:
            print(f"[中标查询] {rec.phone} 失败: {e}")
            results[rec.phone] = {"bid_result": rec.bid_result, "balance": rec.balance}
    return jsonify({'status': 'success', 'results': results})

# 客服端 客户端 API 接口
@app.route('/api/client/get_config', methods=['GET'])
def client_get_config():
    """客户端获取抢购配置（商品编码、活动ID、抢购时间）"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    
    cfg = get_global_config()
    
    # 可以从全局配置中读取，若不存在则提供默认硬编码
    default_item_code = getattr(cfg, 'default_item_code', '741')
    default_act_id = getattr(cfg, 'default_act_id', '76145')
    
    return jsonify({
        'rush_hour': cfg.rush_hour,
        'rush_minute': cfg.rush_minute,
        'item_code': default_item_code,
        'act_id': default_act_id
    })


@app.route('/api/client/get_tasks', methods=['POST'])
def client_get_tasks():
    """客户端拉取指定上传者的所有账号及完整凭证"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    data = request.json
    uploader_id = data.get('uploader_id')  # 系统用户的 id
    if not uploader_id:
        return jsonify({'status': 'error', 'message': '缺少 uploader_id'}), 400
    # 获取该上传者下的所有手机号记录
    records = PhoneRecord.query.filter_by(uploaded_by=uploader_id).all()
    tasks = []
    for rec in records:
        if not rec.logged_in:
            continue  # 只处理已登录账号
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
    return jsonify({'status': 'success', 'tasks': tasks})


@app.route('/api/client/report_result', methods=['POST'])
def client_report_result():
    """客户端上报抢购结果"""
    token = request.headers.get('X-API-TOKEN')
    if token != Config.API_TOKEN:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    data = request.json
    phone = data.get('phone')
    success = data.get('success', False)
    order_id = data.get('order_id', '')
    h5_url = data.get('h5_url', '')
    error_msg = data.get('error', '')
    bid_result_str = data.get('bid_result_str', '')

    record = PhoneRecord.query.get(phone)
    if not record:
        return jsonify({'status': 'error', 'message': '手机号不存在'}), 404

    if success:
        record.bid_result = f"成功-订单{order_id}"
        record.balance = "待支付"
        # 生成二维码并保存
        if h5_url:
            qrcode_path = os.path.join(QRCODE_FOLDER, f"{phone}.png")
            img = qrcode.make(h5_url)
            img.save(qrcode_path)
    else:
        record.bid_result = f"失败-{error_msg[:50]}"

    record.last_updated = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'status': 'success'})


# 首页重定向
@app.route('/')
def index():
    return redirect(url_for('login'))

# ===================== 启动后台线程 =====================
def start_background_tasks():
    # 登录保鲜线程
    t1 = threading.Thread(target=login_keepalive_worker, daemon=True)
    t1.start()
    # 抢购调度线程
    t2 = threading.Thread(target=rush_scheduler, daemon=True)
    t2.start()
    # 自动模式处理线程
    t3 = threading.Thread(target=auto_mode_processor, daemon=True)
    t3.start()

# ===================== 主入口 =====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # 确保全局配置存在
        get_global_config()

        # 检查并添加新增字段（兼容已有数据库）
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('phone_record')]
        with db.engine.connect() as conn:
            if 'user_agent' not in columns:
                conn.execute(text('ALTER TABLE phone_record ADD COLUMN user_agent VARCHAR(200) DEFAULT ""'))
            if 'webview_ua' not in columns:
                conn.execute(text('ALTER TABLE phone_record ADD COLUMN webview_ua VARCHAR(300) DEFAULT ""'))
            if 'mt_r' not in columns:
                conn.execute(text('ALTER TABLE phone_record ADD COLUMN mt_r VARCHAR(80) DEFAULT ""'))
            if 'mt_sn' not in columns:
                conn.execute(text('ALTER TABLE phone_record ADD COLUMN mt_sn VARCHAR(80) DEFAULT ""'))
            conn.commit()

    # 启动后台任务
    start_background_tasks()
    app.run(host=Config.HOST, port=Config.PORT, threaded=True, debug=False)