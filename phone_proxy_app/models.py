#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 数据模型（重构版）
所有表通过 user_id 实现严格多用户隔离
"""

import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ===================== 用户表 =====================
class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=True)    # 注册手机号（可选，可用手机号或用户名登录）
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # 登录安全
    failed_logins = Column(Integer, default=0)                # 连续错误次数（登录成功归零）
    frozen_until = Column(DateTime, nullable=True)            # 冻结截止时间
    daily_failed = Column(Integer, default=0)                 # 当日累计错误次数
    last_failed_date = Column(DateTime, nullable=True)        # 最近一次错误日期（用于跨天重置）


# ===================== 设置表（每用户独立配置）=====================
class UserConfig(Base):
    """替代原 GlobalConfig，每个用户一行，user_id 唯一"""
    __tablename__ = 'user_config'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), unique=True, nullable=False, index=True)
    # 抢购时间
    rush_hour = Column(Integer, default=8)
    rush_minute = Column(Integer, default=58)
    rush_second = Column(Integer, default=0)
    rush_millisecond = Column(Integer, default=500)
    # 抢购参数
    task_frequency = Column(Integer, default=1)          # 抢购频率（毫秒）
    rush_attempts = Column(Integer, default=10000)       # 窗口抢购总数（安全上限）
    rush_count = Column(Integer, default=100)            # 单次抢购次数
    # 多开
    multi_open_count = Column(Integer, default=1)        # 多开数
    multi_open_enabled = Column(Boolean, default=False)  # 继续分配开关
    # 库存监控
    inventory_monitoring = Column(Integer, default=0)
    # 批量发送间隔
    min_delay = Column(Integer, default=10)
    max_delay = Column(Integer, default=20)
    # 暂停
    rush_paused = Column(Integer, default=0)             # 0=运行中 1=已暂停
    # 间隔模式
    interval_mode = Column(Integer, default=0)             # 0=连续抢购(一直抢) 1=每5分钟间隔
    # 客户端窗口数（Linux 进程数）
    client_windows = Column(Integer, default=10)         # 网站设置的 Linux 窗口数
    # 排除规则
    excluded_teams = Column(String(500), default='')      # 排除的团队，逗号分隔
    excluded_uploaders = Column(String(500), default='')   # 排除的上传者，逗号分隔


# ===================== 导入数据表（手机号/凭证）=====================
class PhoneRecord(Base):
    __tablename__ = 'phone_record'
    team = Column(String(100), default='')
    phone = Column(String(20), primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), index=True, nullable=False)
    uploaded_by = Column(Integer)                        # 上传者 user_id
    uploader_name = Column(String(50), default='')       # 上传者用户名（冗余用于快速显示）
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
    task_role = Column(String(10), default='both')       # both=监控+抢购, monitor=仅监控, rush=仅抢购
    account_type = Column(String(10), default='')        # ''=未判断, white=白号, black=黑号
    proxy_ip = Column(String(50), default='')             # 绑定的代理IP socks5://ip:port
    device_key = Column(String(50), default='')           # 绑定的设备机型key (如 xiaomi_13, samsung_s24_ultra)


# ===================== IP 代理表（每用户独立）=====================
class UserProxy(Base):
    __tablename__ = 'user_proxy'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), unique=True, nullable=False, index=True)
    proxy_enabled = Column(Boolean, default=False)       # 代理开关
    proxy_url = Column(String(300), default='')           # 代理地址
    # 防封策略（从原 GlobalConfig 迁移）
    anti_ban_429_retry = Column(Integer, default=5)
    anti_ban_429_delay = Column(Integer, default=3)
    anti_ban_bangcle_ttl = Column(Integer, default=300)
    anti_ban_account_cooldown = Column(Integer, default=200)


# ===================== 任务分配表 =====================
class TaskAssignment(Base):
    """记录多窗口/多批次的任务分配历史"""
    __tablename__ = 'task_assignment'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'), index=True, nullable=False)
    phone = Column(String(20), ForeignKey('phone_record.phone'), nullable=False)
    client_uuid = Column(String(64), default='')
    batch = Column(Integer, default=0)
    status = Column(String(20), default='assigned')       # assigned / completed / failed
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_task_user_phone', 'user_id', 'phone'),
        Index('idx_task_batch', 'batch'),
    )


# ===================== 团队管理表 =====================
class Team(Base):
    """团队表：主站用户创建的团队，拥有独立登录凭据"""
    __tablename__ = 'team'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    login_username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    owner_user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    payment_method = Column(String(50), default='')


class TeamAccount(Base):
    """团队-账号映射表"""
    __tablename__ = 'team_account'
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey('team.id'), nullable=False, index=True)
    phone = Column(String(20), ForeignKey('phone_record.phone'), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)


# ===================== 保留旧的 GlobalConfig 用于兼容（迁移后废弃）=====================
class GlobalConfig(Base):
    """已废弃：迁移到 UserConfig + UserProxy。保留定义以兼容旧表。"""
    __tablename__ = 'global_config'
    id = Column(Integer, primary_key=True)
    rush_hour = Column(Integer, default=8)
    rush_minute = Column(Integer, default=58)
    rush_second = Column(Integer, default=0)
    default_item_code = Column(String(20), default='741')
    default_act_id = Column(String(20), default='76145')
    multi_open_count = Column(Integer, default=1)
    multi_open_enabled = Column(Boolean, default=False)
    task_frequency = Column(Integer, default=1)
    rush_attempts = Column(Integer, default=10000)
    rush_count = Column(Integer, default=100)
    inventory_monitoring = Column(Integer, default=0)
    min_delay = Column(Integer, default=10)
    max_delay = Column(Integer, default=20)
    anti_ban_429_retry = Column(Integer, default=5)
    anti_ban_429_delay = Column(Integer, default=3)
    anti_ban_bangcle_ttl = Column(Integer, default=300)
    anti_ban_account_cooldown = Column(Integer, default=200)
    anti_ban_proxy_enabled = Column(Boolean, default=False)
    anti_ban_proxy_url = Column(String(300), default='')
    rush_paused = Column(Integer, default=0)


# ===================== 设备与窗口密钥注册系统 =====================
class DeviceKey(Base):
    """设备注册表：每台物理机一个唯一密钥
    machine_id = 系统 UUID (dmidecode -s system-uuid)，用于重启后识别同一设备
    密钥不足时自动生成新密钥（uuid4），不会阻塞新设备注册"""
    __tablename__ = 'device_keys'
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_key = Column(String(64), unique=True, nullable=False, index=True)  # 下发给客户端的密钥
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    machine_id = Column(String(128), nullable=False, index=True)        # dmidecode 系统 UUID
    hostname = Column(String(128), default='')
    last_ip = Column(String(45), default='')
    status = Column(String(16), default='active')   # active / inactive
    max_windows = Column(Integer, default=8)         # 该设备允许的最大窗口数
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index('idx_device_machine', 'user_id', 'machine_id', unique=True),  # 同用户同机器唯一
    )


class WindowKey(Base):
    """窗口注册表：每台设备下每个窗口一个唯一密钥
    按 (device_key, window_index) 唯一约束，重启后复用原窗口编号"""
    __tablename__ = 'window_keys'
    id = Column(Integer, primary_key=True, autoincrement=True)
    window_key = Column(String(64), unique=True, nullable=False, index=True)  # 下发给窗口的密钥
    device_key = Column(String(64), ForeignKey('device_keys.device_key'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    window_index = Column(Integer, nullable=False, default=0)      # 设备内窗口编号 0,1,2...
    status = Column(String(16), default='active')   # active / inactive
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    client_uuid = Column(String(64), default='')     # 窗口运行时 UUID（用于心跳匹配）

    __table_args__ = (
        Index('idx_window_device', 'device_key', 'window_index', unique=True),  # 同设备同编号唯一
    )


# ===================== 手机代理表 =====================
class PhoneProxy(Base):
    """手机端 SOCKS5 代理注册表
    手机通过 Tailscale 组网，运行 phone_proxy.py 后注册到此表
    服务端分配任务时可优先使用本表IP（手机蜂窝IP，CDN信任度高）"""
    __tablename__ = 'phone_proxy'
    id = Column(Integer, primary_key=True, autoincrement=True)
    proxy_addr = Column(String(200), nullable=False)             # socks5://tailscale_ip:10808
    name = Column(String(100), default='')                       # 手机名称
    tailscale_ip = Column(String(45), default='')                # Tailscale IP (100.x.x.x)
    port = Column(Integer, default=10808)                        # SOCKS5 端口
    status = Column(String(16), default='online')                # online / offline
    last_heartbeat = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ===================== 预生成密钥种子（可选，用于 UUID 可追溯性） =====================
class KeySeed(Base):
    """预生成密钥池：可提前批量生成一批密钥，分配时从池中取用
    池中密钥不足时，register 端点自动生成新密钥追加到池中"""
    __tablename__ = 'key_seeds'
    id = Column(Integer, primary_key=True, autoincrement=True)
    seed_key = Column(String(64), unique=True, nullable=False, index=True)
    key_type = Column(String(16), default='window')  # 'device' / 'window'
    assigned = Column(Boolean, default=False)         # 是否已分配
    assigned_to = Column(String(64), default='')      # 分配给哪个 device_key/window_key
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
