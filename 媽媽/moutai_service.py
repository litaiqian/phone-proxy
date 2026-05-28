import json
import os
from datetime import datetime
from typing import Optional, Dict, Any
from models import db, PhoneRecord
from demo import MoutaiClient

# 存放每个手机号对应的客户端实例（内存缓存，避免重复构建）
_client_cache = {}


class MoutaiService:
    """茅台接口服务，负责管理每个手机号的客户端和登录状态"""

    @staticmethod
    def _build_client(phone: str) -> MoutaiClient:
        """从数据库记录中恢复设备指纹，构建 MoutaiClient 实例"""
        record = PhoneRecord.query.get(phone)
        if not record:
            raise ValueError(f"手机号 {phone} 不存在")

        # 如果有保存的设备指纹，则复用
        if record.raw_device_id:
            client = MoutaiClient(
                android_id=record.raw_device_id[:16] if len(record.raw_device_id) >= 16 else "",
                bs_dvid=record.mt_device_id.replace("clips_", "") if record.mt_device_id else ""
            )
            # 手动注入已保存的登录信息
            client.token = record.token or ""
            client.cookie = record.cookie or ""
            client.user_id = record.user_id_ext or ""
            client.mt_device_id = record.mt_device_id or ""
            client.raw_device_id = record.raw_device_id or ""
        else:
            # 首次使用，随机生成客户端
            client = MoutaiClient()
            # 保存生成的设备指纹到数据库
            record.raw_device_id = client.raw_device_id
            record.mt_device_id = client.mt_device_id
            db.session.commit()

        _client_cache[phone] = client
        return client

    @staticmethod
    def send_verification_code(phone: str) -> bool:
        """发送验证码"""
        client = _client_cache.get(phone)
        if not client:
            client = MoutaiService._build_client(phone)

        result = client.send_vcode(phone)
        if result.get("code") == 2000:
            # 更新数据库中的发送状态
            record = PhoneRecord.query.get(phone)
            if record:
                record.code_sent = True
                record.last_updated = datetime.utcnow()
                db.session.commit()
            return True
        else:
            return False

    @staticmethod
    def submit_verification_code(phone: str, code: str) -> Optional[str]:
        """提交验证码完成登录，返回 token"""
        client = _client_cache.get(phone)
        if not client:
            client = MoutaiService._build_client(phone)

        result = client.login(phone, code)
        if result.get("code") == 2000:
            # 保存登录凭证到数据库
            record = PhoneRecord.query.get(phone)
            if record:
                record.token = client.token
                record.cookie = client.cookie
                record.user_id_ext = client.user_id
                record.logged_in = True
                record.last_updated = datetime.utcnow()
                db.session.commit()
            return client.token
        else:
            # 登录失败，清除本地缓存
            _client_cache.pop(phone, None)
            return None

    @staticmethod
    def query_balance(phone: str) -> str:
        """查询账户余额（模拟，实际可从茅台用户信息接口获取）"""
        record = PhoneRecord.query.get(phone)
        if not record or not record.token:
            return "0"

        # 这里可以调用真正的茅台用户信息接口，例如使用 client 的 get_user_info 方法
        # 为简化演示，返回一个固定字符串
        # 真实场景可扩展 MoutaiClient.get_balance()
        return "999.00"