#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 仪表盘 + 二维码 + 数据导出
"""
import os
import datetime
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session
import pandas as pd

from routes import get_db, get_current_user
from models import User, PhoneRecord, Team, TeamAccount
from core.database import get_user_config
from config import QRCODE_FOLDER, UPLOAD_FOLDER

router = APIRouter(tags=["仪表盘"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        records = db.query(PhoneRecord).all()
    else:
        records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()

    flash_messages = request.session.pop("_flash", [])
    records_with_uploaders = []
    for rec in records:
        uploader = db.query(User).filter(User.id == rec.uploaded_by).first()
        records_with_uploaders.append({
            'record': rec,
            'uploader_username': uploader.username if uploader else '未知'
        })
    # 获取团队列表供前端下拉选择
    if user.id == 1 or user.username.lower() == "admin":
        teams = db.query(Team).all()
    else:
        teams = db.query(Team).filter(Team.owner_user_id == user.id).all()
    return request.app.state.templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "records_with_uploaders": records_with_uploaders,
        "teams": teams,
        "flash_messages": flash_messages,
        "is_admin": (user.id == 1 or user.username.lower() == "admin"),
        "now": datetime.datetime.now
    })


@router.get("/qrcode/{phone}")
async def get_qrcode(phone: str, user: User = Depends(get_current_user)):
    qrcode_file = os.path.join(QRCODE_FOLDER, f"{phone}.png")
    if os.path.exists(qrcode_file):
        return FileResponse(qrcode_file)
    raise HTTPException(status_code=404)


@router.get("/api/stats")
async def stats(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filter_uploader = request.query_params.get('uploader', '').strip()
    if user.id == 1 or user.username.lower() == "admin":
        base_query = db.query(PhoneRecord)
        if filter_uploader:
            base_query = base_query.filter(PhoneRecord.uploader_name == filter_uploader)
    else:
        base_query = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id)

    total = base_query.count()
    success_login = base_query.filter(PhoneRecord.logged_in == True).count()
    offline = base_query.filter(PhoneRecord.logged_in == False,
                                (PhoneRecord.token != '') | (PhoneRecord.cookie != '')).count()
    never_login = base_query.filter(PhoneRecord.logged_in == False,
                                    PhoneRecord.token == '', PhoneRecord.cookie == '').count()
    qrcode_count = 0
    for rec in base_query.all():
        if os.path.exists(os.path.join(QRCODE_FOLDER, f"{rec.phone}.png")):
            qrcode_count += 1
    bid_success = base_query.filter(PhoneRecord.bid_result.contains('成功')).count()

    all_records_for_type = base_query.all()
    white_count = sum(1 for r in all_records_for_type if r.account_type == 'white')
    black_count = sum(1 for r in all_records_for_type if r.account_type == 'black')

    cfg = get_user_config(user.id, db)
    logged_in_count = base_query.filter(PhoneRecord.logged_in == True).count()
    multi_open_count = cfg.multi_open_count or 1
    total_windows = (logged_in_count + multi_open_count - 1) // multi_open_count if logged_in_count > 0 else 0

    # 从5000端口异步获取活跃客户端窗口信息
    active_client_windows = 0
    try:
        import httpx
        from config import Config
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get('http://127.0.0.1:5000/api/client/active_windows',
                                    headers={'X-API-TOKEN': Config.API_TOKEN})
            if resp.status_code == 200:
                active_client_windows = resp.json().get('active_client_windows', 0)
    except Exception:
        pass

    # 团队统计
    if user.id == 1 or user.username.lower() == "admin":
        teams = db.query(Team).all()
    else:
        teams = db.query(Team).filter(Team.owner_user_id == user.id).all()
    team_stats = []
    team_total_accounts = 0
    team_bid_success = 0
    team_paid_success = 0
    team_unpaid = 0
    for t in teams:
        mappings = db.query(TeamAccount).filter(TeamAccount.team_id == t.id).all()
        t_phones = [m.phone for m in mappings]
        t_records = []
        if t_phones:
            t_records = db.query(PhoneRecord).filter(PhoneRecord.phone.in_(t_phones)).all()
        t_bid = sum(1 for r in t_records if r.bid_result and '成功' in r.bid_result)
        t_paid = sum(1 for r in t_records if r.pay_status == 'success')
        t_unpaid = sum(1 for r in t_records if r.pay_status == 'pending')
        team_stats.append({
            'id': t.id, 'name': t.name, 'account_count': len(t_phones),
            'bid_success': t_bid, 'paid_success': t_paid, 'unpaid': t_unpaid
        })
        team_total_accounts += len(t_phones)
        team_bid_success += t_bid
        team_paid_success += t_paid
        team_unpaid += t_unpaid

    return JSONResponse(content={
        'total': total, 'success_login': success_login, 'offline': offline,
        'never_login': never_login, 'bid_success': bid_success, 'qrcode_count': qrcode_count,
        'multi_open_count': cfg.multi_open_count, 'multi_open_enabled': cfg.multi_open_enabled,
        'active_client_windows': active_client_windows, 'logged_in_count': logged_in_count,
        'total_windows': total_windows, 'white_count': white_count, 'black_count': black_count,
        'phone_multi_open_count': getattr(cfg, 'phone_multi_open_count', 3),
        # 团队统计
        'teams': team_stats,
        'team_total_accounts': team_total_accounts,
        'team_bid_success': team_bid_success,
        'team_paid_success': team_paid_success,
        'team_unpaid': team_unpaid
    })


@router.get("/api/export")
async def export_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    records = db.query(PhoneRecord).filter(PhoneRecord.user_id == user.id).all()
    data = [{
        '手机号': r.phone, '验证码已发送': r.code_sent,
        '登录状态': '成功' if r.logged_in else '掉线',
        '中标结果': r.bid_result, '账户余额': r.balance,
        '最后更新': r.last_updated
    } for r in records]
    df = pd.DataFrame(data)
    output = os.path.join(UPLOAD_FOLDER, 'export.xlsx')
    df.to_excel(output, index=False)
    return FileResponse(output, filename='export.xlsx')
