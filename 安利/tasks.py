# tasks.py
import threading
import json
import os
from datetime import datetime
from models import db, PhoneRecord
# 修改为从 external_api 导入
from external_api import send_verification_code, submit_verification_code, query_balance
from config import Config

# 确保数据保存目录存在
if not os.path.exists(Config.DATA_FOLDER):
    os.makedirs(Config.DATA_FOLDER)

# 记录正在运行的任务，避免重复操作同一个手机号
running_tasks = set()
# 线程锁，保证并发安全
lock = threading.Lock()

def save_phone_data(phone, data):
    """
    将手机号相关数据独立保存到本地 JSON 文件
    :param phone: 手机号（作为文件名）
    :param data: 要保存的字典数据
    """
    filepath = os.path.join(Config.DATA_FOLDER, f"{phone}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_code_task(phone, app):
    """
    后台线程：发送验证码，并更新数据库状态
    :param phone: 手机号
    :param app: Flask 应用实例，用于创建数据库上下文
    """
    with app.app_context():
        success = send_verification_code(phone)
        record = PhoneRecord.query.get(phone)
        if record:
            record.code_sent = success
            record.last_updated = datetime.utcnow()
            db.session.commit()
            save_phone_data(phone, {
                'phone': phone,
                'code_sent': success,
                'logged_in': record.logged_in,
                'balance': record.balance,
                'bid_result': record.bid_result,
                'last_updated': str(record.last_updated)
            })
    with lock:
        running_tasks.discard(phone)

def submit_code_task(phone, code, app):
    """
    后台线程：提交验证码，登录平台，查询余额，更新数据库和本地文件
    """
    with app.app_context():
        token = submit_verification_code(phone, code)
        record = PhoneRecord.query.get(phone)
        if record:
            if token:
                record.logged_in = True
                balance = query_balance(phone, token)
                record.balance = balance
            else:
                record.logged_in = False
            record.last_updated = datetime.utcnow()
            db.session.commit()
            save_phone_data(phone, {
                'phone': phone,
                'code_sent': record.code_sent,
                'logged_in': record.logged_in,
                'balance': record.balance,
                'bid_result': record.bid_result,
                'last_updated': str(record.last_updated)
            })
    with lock:
        running_tasks.discard(phone)

def start_send_code(phone, app):
    """
    启动发送验证码线程（非阻塞）
    """
    with lock:
        if phone in running_tasks:
            return False
        running_tasks.add(phone)
    t = threading.Thread(target=send_code_task, args=(phone, app))
    t.daemon = True
    t.start()
    return True

def start_submit_code(phone, code, app):
    """
    启动提交验证码线程（非阻塞）
    """
    with lock:
        if phone in running_tasks:
            return False
        running_tasks.add(phone)
    t = threading.Thread(target=submit_code_task, args=(phone, code, app))
    t.daemon = True
    t.start()
    return True