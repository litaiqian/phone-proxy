import threading
import json
import os
from datetime import datetime
from models import db, PhoneRecord
from external_api import send_verification_code, submit_verification_code, query_balance
from config import Config

if not os.path.exists(Config.DATA_FOLDER):
    os.makedirs(Config.DATA_FOLDER)

running_tasks = set()
lock = threading.Lock()

def save_phone_data(phone, data):
    filepath = os.path.join(Config.DATA_FOLDER, f"{phone}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_code_task(phone, app):
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
    with lock:
        if phone in running_tasks:
            return False
        running_tasks.add(phone)
    t = threading.Thread(target=send_code_task, args=(phone, app))
    t.daemon = True
    t.start()
    return True

def start_submit_code(phone, code, app):
    with lock:
        if phone in running_tasks:
            return False
        running_tasks.add(phone)
    t = threading.Thread(target=submit_code_task, args=(phone, code, app))
    t.daemon = True
    t.start()
    return True