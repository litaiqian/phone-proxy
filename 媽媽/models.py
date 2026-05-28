from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PhoneRecord(db.Model):
    team = db.Column(db.String(100), default='')
    phone = db.Column(db.String(20), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    code_sent = db.Column(db.Boolean, default=False)
    logged_in = db.Column(db.Boolean, default=False)
    bid_result = db.Column(db.String(200), default='')
    balance = db.Column(db.String(50), default='')
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    # 新增字段：保存茅台登录凭证和设备指纹
    token = db.Column(db.String(500), default='')  # MT-Token
    cookie = db.Column(db.String(500), default='')  # MT-Token-Wap
    user_id_ext = db.Column(db.String(50), default='')  # 茅台 userId
    mt_device_id = db.Column(db.String(200), default='')  # MT-Device-ID
    raw_device_id = db.Column(db.String(100), default='')  # 原始设备ID