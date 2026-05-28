# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

# 创建 SQLAlchemy 实例
db = SQLAlchemy()

# 网站用户表
class User(UserMixin, db.Model):
    # 用户 ID，主键，自增
    id = db.Column(db.Integer, primary_key=True)
    # 用户名，唯一且不能为空
    username = db.Column(db.String(80), unique=True, nullable=False)
    # 密码哈希值，不能为空
    password_hash = db.Column(db.String(120), nullable=False)
    # 创建时间，默认当前时间
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# 手机号操作记录表（每个手机号是独立实体）
class PhoneRecord(db.Model):
    # 第1列：团队
    team = db.Column(db.String(100), default='')
    # 第2列：手机号（主键）
    phone = db.Column(db.String(20), primary_key=True)
    # 第3列：所属用户 ID
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    # 第4列：上传者 ID
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    # 第5列：验证码发送状态
    code_sent = db.Column(db.Boolean, default=False)
    # 第6列：登录状态
    logged_in = db.Column(db.Boolean, default=False)
    # 第7列：中标结果
    bid_result = db.Column(db.String(200), default='')
    # 第8列：账户余额
    balance = db.Column(db.String(50), default='')
    # 第9列：最后更新时间
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)