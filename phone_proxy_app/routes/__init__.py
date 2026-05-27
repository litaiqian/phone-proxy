#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由层 — 共享依赖（认证 / DB会话）
"""
from fastapi import Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.database import SessionLocal, get_user_config, get_user_proxy  # noqa: F401
from models import User


# 数据库不可用标志，启动时 init_db 失败会设为 True
_db_unavailable = False


def set_db_unavailable():
    global _db_unavailable
    _db_unavailable = True


def is_db_unavailable():
    return _db_unavailable


def get_db():
    """FastAPI 依赖：获取数据库会话"""
    global _db_unavailable
    if _db_unavailable:
        # 尝试重连：如果数据库恢复了，恢复服务
        try:
            db = SessionLocal()
            _db_unavailable = False
            print("[DB] 数据库连接恢复")
        except Exception:
            yield None
            return
    else:
        try:
            db = SessionLocal()
        except OperationalError:
            _db_unavailable = True
            print("[DB] 数据库连接失败，后续请求将跳过数据库操作")
            yield None
            return
        except Exception:
            yield None
            return
    try:
        yield db
    finally:
        db.close()


async def db_unavailable_middleware(request: Request, call_next):
    """中间件：数据库不可用时拦截请求，返回友好提示"""
    global _db_unavailable
    if _db_unavailable:
        # 尝试重连：如果数据库恢复了，放行请求
        try:
            test_db = SessionLocal()
            test_db.close()
            _db_unavailable = False
            print("[DB] 数据库连接恢复")
        except Exception:
            pass
    if _db_unavailable and request.url.path not in ('/login', '/register', '/static', '/'):
        # API 请求返回 JSON 错误
        if request.url.path.startswith('/api/'):
            return JSONResponse(status_code=503, content={'status': 'error', 'message': '数据库连接失败，请检查 MySQL 服务'})
        # 页面请求返回 HTML 提示
        if request.headers.get('accept', '').startswith('text/html'):
            return HTMLResponse(content='<html><body><h3>数据库连接失败</h3><p>请检查 MySQL 服务是否正常运行，然后刷新页面重试。</p></body></html>', status_code=503)
    return await call_next(request)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """FastAPI 依赖：获取当前登录用户，未登录则跳转 /login"""
    if db is None:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    try:
        user = db.query(User).filter(User.id == user_id).first()
    except OperationalError:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return user


def login_user(request: Request, user: User):
    """手动登录（写入 session）"""
    request.session["user_id"] = user.id
    request.session["permanent"] = True


def logout_user(request: Request):
    """手动登出（清除 session）"""
    request.session.clear()
