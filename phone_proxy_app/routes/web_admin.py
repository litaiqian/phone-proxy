#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 管理员用户管理
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from routes import get_db, get_current_user
from models import User, PhoneRecord

router = APIRouter(tags=["管理员"])


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    if user.username != "admin":
        raise HTTPException(status_code=403, detail="无权访问")

    all_users = db.query(User).all()
    users_data = []
    for u in all_users:
        total_accounts = db.query(PhoneRecord).filter(PhoneRecord.user_id == u.id).count()
        logged_in_count = db.query(PhoneRecord).filter(
            PhoneRecord.user_id == u.id, PhoneRecord.logged_in == True).count()
        offline_count = db.query(PhoneRecord).filter(
            PhoneRecord.user_id == u.id, PhoneRecord.logged_in == False,
            (PhoneRecord.token != '') | (PhoneRecord.cookie != '')).count()
        never_login_count = db.query(PhoneRecord).filter(
            PhoneRecord.user_id == u.id, PhoneRecord.logged_in == False,
            PhoneRecord.token == '', PhoneRecord.cookie == '').count()
        bid_success_count = db.query(PhoneRecord).filter(
            PhoneRecord.user_id == u.id, PhoneRecord.bid_result.contains('成功')).count()

        users_data.append({
            'user': u, 'total_accounts': total_accounts,
            'logged_in_count': logged_in_count, 'offline_count': offline_count,
            'never_login_count': never_login_count, 'bid_success_count': bid_success_count,
            'created_at': u.created_at.strftime('%Y-%m-%d %H:%M:%S') if u.created_at else '未知'
        })

    flash_messages = request.session.pop("_flash", [])
    return request.app.state.templates.TemplateResponse(request, "admin_users.html", {
        "user": user, "users_data": users_data, "flash_messages": flash_messages
    })
