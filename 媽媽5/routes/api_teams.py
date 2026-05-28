#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 团队管理 API（8000端口）
"""
import os
import datetime
import asyncio
import random
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash, check_password_hash

from routes import get_db, get_current_user
from models import User, PhoneRecord, Team, TeamAccount
from config import Config, BASEDIR

router = APIRouter(tags=["团队管理"])


# ---------- 团队 CRUD ----------
@router.get("/api/teams")
async def list_teams(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出当前用户或管理员的团队"""
    if user.id == 1 or user.username.lower() == "admin":
        teams = db.query(Team).all()
    else:
        teams = db.query(Team).filter(Team.owner_user_id == user.id).all()
    return JSONResponse(content={
        'status': 'success',
        'teams': [{
            'id': t.id, 'name': t.name, 'login_username': t.login_username,
            'payment_method': t.payment_method or '',
            'owner_user_id': t.owner_user_id,
            'created_at': t.created_at.isoformat() if t.created_at else '',
            'account_count': db.query(TeamAccount).filter(TeamAccount.team_id == t.id).count()
        } for t in teams]
    })


@router.post("/api/teams")
async def create_team(request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    data = await request.json()
    name = data.get('name', '').strip()
    login_username = data.get('login_username', '').strip()
    password = data.get('password', '').strip()
    if not name or not login_username or not password:
        return JSONResponse(content={'status': 'error', 'message': '团队名称、登录账号、密码不能为空'}, status_code=400)
    if db.query(Team).filter(Team.login_username == login_username).first():
        return JSONResponse(content={'status': 'error', 'message': '登录账号已存在'}, status_code=400)
    team = Team(name=name, login_username=login_username,
                password_hash=generate_password_hash(password),
                owner_user_id=user.id)
    db.add(team)
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'团队「{name}」创建成功', 'team_id': team.id})


@router.put("/api/teams/{team_id}")
async def update_team(team_id: int, request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    data = await request.json()
    if 'name' in data and data['name'].strip():
        team.name = data['name'].strip()
    if 'login_username' in data and data['login_username'].strip():
        new_uname = data['login_username'].strip()
        existing = db.query(Team).filter(Team.login_username == new_uname, Team.id != team_id).first()
        if existing:
            return JSONResponse(content={'status': 'error', 'message': '登录账号已存在'}, status_code=400)
        team.login_username = new_uname
    if 'password' in data and data['password'].strip():
        team.password_hash = generate_password_hash(data['password'].strip())
    if 'payment_method' in data:
        team.payment_method = data['payment_method'].strip()
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'团队「{team.name}」已更新'})


@router.delete("/api/teams/{team_id}")
async def delete_team(team_id: int, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    db.query(TeamAccount).filter(TeamAccount.team_id == team_id).delete()
    db.delete(team)
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'团队「{team.name}」已删除'})


# ---------- 团队账号分配 ----------
@router.get("/api/teams/{team_id}/accounts")
async def get_team_accounts(team_id: int, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    mappings = db.query(TeamAccount).filter(TeamAccount.team_id == team_id).all()
    phones = [m.phone for m in mappings]
    records = []
    if phones:
        records = db.query(PhoneRecord).filter(PhoneRecord.phone.in_(phones)).all()
    return JSONResponse(content={
        'status': 'success',
        'accounts': [{
            'phone': r.phone, 'team_name': r.team or '',
            'logged_in': r.logged_in,
            'login_status': 'success' if r.logged_in else ('offline' if (r.token or r.cookie) else 'never'),
            'account_type': r.account_type or '',
            'bid_result': r.bid_result or '',
            'pay_url': r.pay_url or '',
            'pay_status': r.pay_status or '',
            'balance': r.balance or ''
        } for r in records]
    })


@router.post("/api/teams/{team_id}/assign")
async def assign_accounts_to_team(team_id: int, request: Request,
                                  user: User = Depends(get_current_user),
                                  db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    data = await request.json()
    phones = data.get('phones', [])
    if not phones:
        return JSONResponse(content={'status': 'error', 'message': '请选择要分配的账号'}, status_code=400)
    assigned = 0
    for phone in phones:
        if user.id != 1 and user.username.lower() != "admin":
            rec = db.query(PhoneRecord).filter(PhoneRecord.phone == phone,
                                               PhoneRecord.user_id == user.id).first()
            if not rec: continue
        existing = db.query(TeamAccount).filter(TeamAccount.team_id == team_id,
                                                TeamAccount.phone == phone).first()
        if existing: continue
        ta = TeamAccount(team_id=team_id, phone=phone, owner_user_id=team.owner_user_id)
        db.add(ta)
        assigned += 1
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'已将 {assigned} 个账号分配给「{team.name}」'})


@router.post("/api/teams/{team_id}/unassign")
async def unassign_accounts_from_team(team_id: int, request: Request,
                                      user: User = Depends(get_current_user),
                                      db: Session = Depends(get_db)):
    if user.id == 1 or user.username.lower() == "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    data = await request.json()
    phones = data.get('phones', [])
    if not phones:
        return JSONResponse(content={'status': 'error', 'message': '请选择要移除的账号'}, status_code=400)
    deleted = db.query(TeamAccount).filter(
        TeamAccount.team_id == team_id, TeamAccount.phone.in_(phones)
    ).delete(synchronize_session=False)
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': f'已从「{team.name}」移除 {deleted} 个账号'})
