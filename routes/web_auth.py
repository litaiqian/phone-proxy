#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 登录 / 注册 / 登出
"""
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash, check_password_hash

from routes import get_db, get_current_user, login_user, logout_user
from models import User

router = APIRouter(tags=["认证"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    flash_messages = request.session.pop("_flash", [])
    return request.app.state.templates.TemplateResponse(request, "login.html", {"flash_messages": flash_messages})


@router.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...),
                     db: Session = Depends(get_db)):
    if db is None:
        flash_messages = request.session.get("_flash", [])
        flash_messages.append(("error", "数据库连接失败，请稍后重试"))
        request.session["_flash"] = flash_messages
        return RedirectResponse(url="/login", status_code=303)
    user = db.query(User).filter(User.username == username).first()
    if user and check_password_hash(user.password_hash, password):
        # 8000端口仅admin可登录
        if user.id != 1 and user.username != "admin":
            flash_messages = request.session.get("_flash", [])
            flash_messages.append(("error", "8000端口仅限管理员登录，请使用5000端口"))
            request.session["_flash"] = flash_messages
            return RedirectResponse(url="/login", status_code=303)
        login_user(request, user)
        flash_messages = request.session.get("_flash", [])
        flash_messages.append(("success", "登录成功"))
        request.session["_flash"] = flash_messages
        return RedirectResponse(url="/dashboard", status_code=303)
    flash_messages = request.session.get("_flash", [])
    flash_messages.append(("error", "用户名或密码错误"))
    request.session["_flash"] = flash_messages
    return RedirectResponse(url="/login", status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    flash_messages = request.session.pop("_flash", [])
    return request.app.state.templates.TemplateResponse(request, "register.html", {"flash_messages": flash_messages})


@router.post("/register", response_class=HTMLResponse)
async def register_post(request: Request, username: str = Form(...), password: str = Form(...),
                        db: Session = Depends(get_db)):
    if db is None:
        flash_messages = request.session.get("_flash", [])
        flash_messages.append(("error", "数据库连接失败，请稍后重试"))
        request.session["_flash"] = flash_messages
        return RedirectResponse(url="/register", status_code=303)
    if db.query(User).filter(User.username == username).first():
        flash_messages = request.session.get("_flash", [])
        flash_messages.append(("error", "用户名已存在"))
        request.session["_flash"] = flash_messages
        return RedirectResponse(url="/register", status_code=303)
    user = User(username=username, password_hash=generate_password_hash(password))
    db.add(user)
    db.commit()
    flash_messages = request.session.get("_flash", [])
    flash_messages.append(("success", "注册成功，请登录"))
    request.session["_flash"] = flash_messages
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse(url="/login")
