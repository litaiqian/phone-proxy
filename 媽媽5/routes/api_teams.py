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
from models import User, PhoneRecord, Team, TeamMember, TeamAccount
from config import Config, BASEDIR

router = APIRouter(tags=["团队管理"])


# ---------- 团队 CRUD ----------
@router.get("/api/teams")
async def list_teams(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出当前用户或管理员的团队（含成员信息）"""
    if user.id == 1 or user.username.lower() == "admin":
        teams = db.query(Team).all()
    else:
        teams = db.query(Team).filter(Team.owner_user_id == user.id).all()
    return JSONResponse(content={
        'status': 'success',
        'teams': [{
            'id': t.id, 'name': t.name,
            'owner_user_id': t.owner_user_id,
            'created_at': t.created_at.isoformat() if t.created_at else '',
            'account_count': db.query(TeamAccount).filter(TeamAccount.team_id == t.id).count(),
            'members': [{
                'user_id': m.user_id,
                'username': (db.query(User).filter(User.id == m.user_id).first().username if db.query(User).filter(User.id == m.user_id).first() else str(m.user_id))
            } for m in db.query(TeamMember).filter(TeamMember.team_id == t.id).all()]
        } for t in teams]
    })


@router.post("/api/teams")
async def create_team(request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """创建团队（可选添加成员用户ID）"""
    data = await request.json()
    name = data.get('name', '').strip()
    member_ids = data.get('member_ids', [])  # 要添加的成员用户ID列表
    if not name:
        return JSONResponse(content={'status': 'error', 'message': '团队名称不能为空'}, status_code=400)
    team = Team(name=name, owner_user_id=user.id)
    db.add(team)
    db.flush()  # 获取 team.id
    # 添加成员
    added_members = []
    for uid in member_ids:
        try:
            uid = int(uid)
            if uid == user.id:
                continue
            target = db.query(User).filter(User.id == uid).first()
            if not target:
                continue
            existing = db.query(TeamMember).filter(
                TeamMember.team_id == team.id, TeamMember.user_id == uid
            ).first()
            if existing:
                continue
            db.add(TeamMember(team_id=team.id, user_id=uid))
            added_members.append(target.username)
        except (ValueError, TypeError):
            continue
    db.commit()
    msg = f'团队「{name}」创建成功'
    if added_members:
        msg += f'，成员: {", ".join(added_members)}'
    return JSONResponse(content={'status': 'success', 'message': msg, 'team_id': team.id})


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
    db.query(TeamMember).filter(TeamMember.team_id == team_id).delete()
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


# ---------- 团队成员管理 ----------
@router.post("/api/teams/{team_id}/members")
async def add_team_members(team_id: int, request: Request,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """添加团队成员（仅 team owner 可操作）"""
    if user.id != 1 and user.username.lower() != "admin":
        team = db.query(Team).filter(Team.id == team_id, Team.owner_user_id == user.id).first()
    else:
        team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
    data = await request.json()
    member_ids = data.get('member_ids', [])
    if not member_ids:
        return JSONResponse(content={'status': 'error', 'message': '请提供要添加的成员用户ID'}, status_code=400)
    added = []
    for uid in member_ids:
        try:
            uid = int(uid)
            if uid == user.id:
                continue
            target = db.query(User).filter(User.id == uid).first()
            if not target:
                continue
            existing = db.query(TeamMember).filter(
                TeamMember.team_id == team_id, TeamMember.user_id == uid
            ).first()
            if existing:
                continue
            db.add(TeamMember(team_id=team_id, user_id=uid))
            added.append(target.username)
        except (ValueError, TypeError):
            continue
    db.commit()
    if added:
        return JSONResponse(content={'status': 'success', 'message': f'已添加成员: {", ".join(added)}'})
    return JSONResponse(content={'status': 'error', 'message': '未添加任何成员'}, status_code=400)


@router.delete("/api/teams/{team_id}/members/{member_user_id}")
async def remove_team_member(team_id: int, member_user_id: int,
                              user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """移除团队成员（team owner 或成员自己可以退出）"""
    if user.id != 1 and user.username.lower() != "admin":
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            return JSONResponse(content={'status': 'error', 'message': '团队不存在'}, status_code=404)
        # owner 可以移除任何人，成员只能移除自己
        if team.owner_user_id != user.id and member_user_id != user.id:
            return JSONResponse(content={'status': 'error', 'message': '无权限'}, status_code=403)
    deleted = db.query(TeamMember).filter(
        TeamMember.team_id == team_id, TeamMember.user_id == member_user_id
    ).delete()
    db.commit()
    if deleted:
        return JSONResponse(content={'status': 'success', 'message': '已移除成员'})
    return JSONResponse(content={'status': 'error', 'message': '未找到该成员'}, status_code=404)
