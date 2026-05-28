#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 数据库引擎 & 会话管理
"""
import os
import time as _time
import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from config import Config, BASEDIR, QRCODE_FOLDER, DATA_FOLDER

# ===================== 引擎 =====================
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False,
    connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ===================== 导入所有模型，确保 create_all 能建表 =====================
from models import User, UserConfig, PhoneRecord, UserProxy, TaskAssignment, GlobalConfig, Base  # noqa: F401


def init_db():
    """建表 + 字段迁移"""
    from sqlalchemy import inspect as sa_inspect

    try:
        inspector = sa_inspect(engine)
    except Exception as e:
        print(f"[启动] ⚠️ 数据库连接失败: {e}")
        print(f"[启动] 服务将以无数据库模式启动，相关功能不可用")
        # 通知路由层数据库不可用
        try:
            from routes import set_db_unavailable
            set_db_unavailable()
        except Exception:
            pass
        return

    try:
        Base.metadata.create_all(bind=engine)
        print("[启动] 数据库表结构检查完成")
    except Exception as e:
        print(f"[启动] ⚠️ 数据库连接失败: {e}")
        return

    # 推断已有列
    need_fix = {'user': [], 'phone_record': [], 'user_config': []}
    try:
        for col in inspector.get_columns('user'):
            need_fix['user'].append(col['name'])
    except Exception:
        pass
    try:
        for col in inspector.get_columns('phone_record'):
            need_fix['phone_record'].append(col['name'])
    except Exception:
        pass
    try:
        for col in inspector.get_columns('user_config'):
            need_fix['user_config'].append(col['name'])
    except Exception:
        pass

    with engine.connect() as conn:
        conn.execute(text('SET SESSION lock_wait_timeout = 1'))
        conn.execute(text('SET SESSION innodb_lock_wait_timeout = 1'))

        # user 表字段迁移
        user_config_fields = [
            ('rush_hour', 'INTEGER DEFAULT 8'),
            ('rush_minute', 'INTEGER DEFAULT 58'),
            ('rush_second', 'INTEGER DEFAULT 0'),
            ('task_window_count', 'INTEGER DEFAULT 1'),
            ('distribution_mode', 'BOOLEAN DEFAULT 0'),
            ('task_frequency', 'INTEGER DEFAULT 1'),
            ('rush_attempts', 'INTEGER DEFAULT 10000'),
        ]
        for fn, ft in user_config_fields:
            if fn not in need_fix['user']:
                try:
                    conn.execute(text(f'ALTER TABLE `user` ADD COLUMN `{fn}` {ft}'))
                    print(f"[DB] 为用户表添加字段: {fn}")
                except Exception:
                    pass

        # phone_record 表字段迁移
        pr_alter_list = [
            ('user_agent', 'ALTER TABLE phone_record ADD COLUMN user_agent VARCHAR(200) DEFAULT ""'),
            ('webview_ua', 'ALTER TABLE phone_record ADD COLUMN webview_ua VARCHAR(300) DEFAULT ""'),
            ('mt_r', 'ALTER TABLE phone_record ADD COLUMN mt_r VARCHAR(80) DEFAULT ""'),
            ('mt_sn', 'ALTER TABLE phone_record ADD COLUMN mt_sn VARCHAR(80) DEFAULT ""'),
            ('item_name', 'ALTER TABLE phone_record ADD COLUMN item_name VARCHAR(100) DEFAULT ""'),
            ('item_code', 'ALTER TABLE phone_record ADD COLUMN item_code VARCHAR(20) DEFAULT "IMTP1000313"'),
            ('amount', 'ALTER TABLE phone_record ADD COLUMN amount INTEGER DEFAULT 1'),
            ('activity_id', 'ALTER TABLE phone_record ADD COLUMN activity_id VARCHAR(20) DEFAULT ""'),
            ('sku_id', 'ALTER TABLE phone_record ADD COLUMN sku_id VARCHAR(20) DEFAULT ""'),
            ('login_time', 'ALTER TABLE phone_record ADD COLUMN login_time DATETIME'),
            ('uploader_name', 'ALTER TABLE phone_record ADD COLUMN uploader_name VARCHAR(50) DEFAULT ""'),
            ('account_type', 'ALTER TABLE phone_record ADD COLUMN account_type VARCHAR(10) DEFAULT ""'),
            ('proxy_ip', 'ALTER TABLE phone_record ADD COLUMN proxy_ip VARCHAR(50) DEFAULT ""'),
            ('pay_url_wechat', 'ALTER TABLE phone_record ADD COLUMN pay_url_wechat VARCHAR(500) DEFAULT ""'),
            ('pay_url_alipay', 'ALTER TABLE phone_record ADD COLUMN pay_url_alipay VARCHAR(500) DEFAULT ""'),
        ]
        for cn, alter_sql in pr_alter_list:
            if cn not in need_fix['phone_record']:
                try:
                    conn.execute(text(alter_sql))
                except Exception:
                    pass
        # 删除废弃字段
        try:
            conn.execute(text('ALTER TABLE phone_record DROP COLUMN auto_mode'))
        except Exception:
            pass

        # user_config 表字段迁移
        uc_alter_list = [
            ('excluded_teams', 'ALTER TABLE user_config ADD COLUMN excluded_teams VARCHAR(500) DEFAULT ""'),
            ('excluded_uploaders', 'ALTER TABLE user_config ADD COLUMN excluded_uploaders VARCHAR(500) DEFAULT ""'),
            ('client_windows', 'ALTER TABLE user_config ADD COLUMN client_windows INTEGER DEFAULT 10'),
            ('phone_multi_open_count', 'ALTER TABLE user_config ADD COLUMN phone_multi_open_count INTEGER DEFAULT 3'),
        ]
        for cn, alter_sql in uc_alter_list:
            if cn not in need_fix['user_config']:
                try:
                    conn.execute(text(alter_sql))
                    print(f"[DB] 为user_config表添加字段: {cn}")
                except Exception:
                    pass

        try:
            conn.commit()
        except Exception:
            pass


def get_user_config(user_id: int, db):
    """获取用户专属配置（不存在则自动创建）"""
    try:
        db.execute(text('SET SESSION lock_wait_timeout = 1'))
        db.execute(text('SET SESSION innodb_lock_wait_timeout = 1'))
    except Exception:
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
                _time.sleep(0.3)
            else:
                db.rollback()
                return UserConfig(user_id=user_id)
    return UserConfig(user_id=user_id)


def get_user_proxy(user_id: int, db):
    """获取用户专属代理配置（不存在则自动创建）"""
    try:
        up = db.query(UserProxy).filter(UserProxy.user_id == user_id).first()
        if not up:
            up = UserProxy(user_id=user_id)
            db.add(up)
            db.commit()
        return up
    except Exception:
        return UserProxy(user_id=user_id)
