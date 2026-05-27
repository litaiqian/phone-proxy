#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由 — 配置管理 API
"""
import re
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from routes import get_db, get_current_user
from models import User, PhoneRecord
from core.database import get_user_config, get_user_proxy

router = APIRouter(tags=["配置管理"])


@router.get("/api/get_config")
async def get_config_api(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    up = get_user_proxy(user.id, db)
    return JSONResponse(content={
        'rush_hour': cfg.rush_hour, 'rush_minute': cfg.rush_minute,
        'rush_second': cfg.rush_second, 'rush_millisecond': getattr(cfg, 'rush_millisecond', 0),
        'multi_open_count': cfg.multi_open_count,
        'multi_open_enabled': cfg.multi_open_enabled, 'task_frequency': cfg.task_frequency,
        'rush_attempts': cfg.rush_attempts,
        'rush_count': getattr(cfg, 'rush_count', 100),
        'rush_paused': getattr(cfg, 'rush_paused', 0),
        'interval_mode': getattr(cfg, 'interval_mode', 0),
        'client_windows': getattr(cfg, 'client_windows', 10),
        'anti_ban_proxy_enabled': up.proxy_enabled,
        'anti_ban_proxy_url': up.proxy_url,
    })


@router.post("/api/set_config")
async def set_config_api(request: Request, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    data = await request.json()
    cfg = get_user_config(user.id, db)
    up = get_user_proxy(user.id, db)
    if 'rush_hour' in data:
        cfg.rush_hour = int(data['rush_hour'])
    if 'rush_minute' in data:
        cfg.rush_minute = int(data['rush_minute'])
    if 'multi_open_count' in data:
        cfg.multi_open_count = int(data['multi_open_count'])
    elif 'task_window_count' in data:
        cfg.multi_open_count = int(data['task_window_count'])
    if 'multi_open_enabled' in data:
        cfg.multi_open_enabled = bool(data['multi_open_enabled'])
    elif 'distribution_mode' in data:
        cfg.multi_open_enabled = bool(data['distribution_mode'])
    if 'rush_attempts' in data:
        cfg.rush_attempts = int(data['rush_attempts'])
    if 'rush_count' in data:
        cfg.rush_count = int(data['rush_count'])
    if 'task_frequency' in data:
        cfg.task_frequency = int(data['task_frequency'])
    if 'rush_second' in data:
        cfg.rush_second = int(data['rush_second'])
    if 'rush_millisecond' in data:
        cfg.rush_millisecond = int(data['rush_millisecond'])
    if 'interval_mode' in data:
        cfg.interval_mode = int(data['interval_mode'])
    if 'client_windows' in data:
        cfg.client_windows = int(data['client_windows'])
    if 'anti_ban_proxy_enabled' in data:
        up.proxy_enabled = bool(data['anti_ban_proxy_enabled'])
    if 'anti_ban_proxy_url' in data:
        up.proxy_url = str(data['anti_ban_proxy_url'])
    db.commit()
    return JSONResponse(content={'status': 'success'})


@router.post("/api/update_account_config")
async def update_account_config(request: Request, user: User = Depends(get_current_user),
                                db: Session = Depends(get_db)):
    data = await request.json()
    phone = data.get('phone')
    item_name = data.get('item_name', '')
    amount = data.get('amount', 1)

    record = db.query(PhoneRecord).filter(PhoneRecord.phone == phone).first()
    if not record:
        raise HTTPException(status_code=404, detail="账号不存在")
    if user.id != 1 and record.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权限")

    record.item_name = str(item_name) if item_name else ''
    if item_name and re.match(r'^[A-Za-z]\w{4,}$', str(item_name).strip()):
        record.item_code = str(item_name).strip()
    elif not record.item_code:
        record.item_code = 'IMTP1000313'
    record.amount = int(amount)
    if 'team' in data:
        record.team = str(data['team']).strip()
    if 'uploader_name' in data:
        record.uploader_name = str(data['uploader_name']).strip()
    db.commit()
    return JSONResponse(content={'status': 'success', 'message': '配置已保存'})


@router.get("/api/get_exclude_config")
async def get_exclude_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = get_user_config(user.id, db)
    excluded_teams = [t.strip() for t in (cfg.excluded_teams or '').split(',') if t.strip()] if cfg.excluded_teams else []
    excluded_uploaders = [u.strip() for u in (cfg.excluded_uploaders or '').split(',') if u.strip()] if cfg.excluded_uploaders else []
    return JSONResponse(content={'excluded_teams': excluded_teams, 'excluded_uploaders': excluded_uploaders})


@router.post("/api/set_exclude_config")
async def set_exclude_config(request: Request, user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    try:
        data = await request.json()
        excluded_teams = data.get('excluded_teams', [])
        excluded_uploaders = data.get('excluded_uploaders', [])
        cfg = get_user_config(user.id, db)
        # 确保 cfg 在 session 中被追踪
        # get_user_config 在 DB 异常时会返回 detached 对象，必须 merge
        from sqlalchemy.orm import object_session
        if object_session(cfg) is None:
            cfg = db.merge(cfg)
        cfg.excluded_teams = ','.join(excluded_teams) if excluded_teams else ''
        cfg.excluded_uploaders = ','.join(excluded_uploaders) if excluded_uploaders else ''
        db.commit()
        print(f'[不上号] user={user.username}(id={user.id}) 保存成功: 团队={excluded_teams}, 上传者={excluded_uploaders}')
        return JSONResponse(content={'status': 'success',
                                      'message': f'已排除 {len(excluded_teams)} 个团队, {len(excluded_uploaders)} 个上传者'})
    except Exception as e:
        db.rollback()
        print(f'[不上号] 保存失败: {e}')
        return JSONResponse(content={'status': 'error', 'message': f'数据库保存失败: {str(e)[:80]}'})
