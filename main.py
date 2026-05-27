#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 桥接/管理服务入口 (8000端口)
精简版：模块化架构，所有路由从 routes/ 加载
"""
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect as sa_inspect

# 确保工作目录正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, BASEDIR, TEMPLATES_DIR, STATIC_DIR
from core.database import engine, SessionLocal, init_db
from services.keepalive import start_background_tasks
from routes import db_unavailable_middleware

# ===================== FastAPI 应用 =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化数据库
    init_db()
    # 启动后台任务
    start_background_tasks()
    yield

app = FastAPI(title="猫妈妈自动化系统 - 桥接服务", lifespan=lifespan)

# Session 中间件
app.add_middleware(SessionMiddleware, secret_key=Config.SECRET_KEY, session_cookie="main_session")

# 数据库不可用拦截中间件
@app.middleware("http")
async def db_check_middleware(request: Request, call_next):
    return await db_unavailable_middleware(request, call_next)

# 静态文件
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(BASEDIR, 'templates'), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Jinja2 模板
from jinja2 import Environment, FileSystemLoader, select_autoescape
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(['html', 'xml']),
    cache_size=0
)
templates = Jinja2Templates(env=jinja_env)
app.state.templates = templates  # 让路由模块可以访问模板引擎


# ===================== 注册路由 =====================
from routes.web_auth import router as auth_router
from routes.web_dashboard import router as dashboard_router
from routes.web_admin import router as admin_router
from routes.web_bind import router as bind_router
from routes.api_accounts import router as accounts_router
from routes.api_config import router as config_router
from routes.api_blackwhite import router as blackwhite_router
from routes.api_client import router as client_router
from routes.api_bridge import router as bridge_router
from routes.api_misc import router as misc_router
from routes.api_teams import router as teams_router
from routes.api_app import router as app_router

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(bind_router)
app.include_router(accounts_router)
app.include_router(config_router)
app.include_router(blackwhite_router)
app.include_router(client_router)
app.include_router(bridge_router)
app.include_router(misc_router)
app.include_router(teams_router)
app.include_router(app_router)


@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/login")


if __name__ == "__main__":
    import uvicorn
    import socket
    import subprocess
    import platform

    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def kill_port(port: int) -> bool:
        """杀掉占用指定端口的进程，返回是否清理过"""
        try:
            if platform.system() == 'Windows':
                r = subprocess.run(f'netstat -ano | findstr ":{port} "',
                                   shell=True, capture_output=True, text=True)
                lines = [l.strip() for l in r.stdout.split('\n') if l.strip()]
                pids = set()
                for line in lines:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        if pid not in pids:
                            pids.add(pid)
                if pids:
                    print(f"[main] 检测到端口 {port} 被占用 (PID: {', '.join(pids)})，正在清理...")
                    for pid in pids:
                        subprocess.run(f'taskkill /F /PID {pid}',
                                       shell=True, capture_output=True)
                    return True
            else:
                import signal
                r = subprocess.run(f'lsof -ti :{port}', shell=True, capture_output=True, text=True)
                pids = [p.strip() for p in r.stdout.split('\n') if p.strip()]
                if pids:
                    print(f"[main] 检测到端口 {port} 被占用 (PID: {', '.join(pids)})，正在清理...")
                    for pid in pids:
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                        except Exception:
                            pass
                    return True
        except Exception as e:
            print(f"[main] 端口 {port} 检查失败: {e}")
        return False

    # 启动前清理端口
    kill_port(8000)
    kill_port(5000)

    local_ip = get_local_ip()
    print(f"\n{'='*50}")
    print(f"桥接服务启动成功！(端口 {Config.BRIDGE_PORT})")
    print(f"本地访问: http://127.0.0.1:{Config.BRIDGE_PORT}")
    print(f"内网访问: http://{local_ip}:{Config.BRIDGE_PORT}")
    print(f"{'='*50}\n")

    # 自定义日志配置：完全抑制 h11 Invalid HTTP request 刷屏
    import logging
    import logging.config
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["loggers"]["uvicorn"]["level"] = "ERROR"
    log_config["loggers"]["uvicorn.error"]["level"] = "ERROR"
    log_config["loggers"]["uvicorn.access"]["level"] = "ERROR"
    # h11 协议库 WARNING
    logging.getLogger("h11").setLevel(logging.ERROR)
    # uvicorn.protocols 模块 WARNING
    logging.getLogger("uvicorn.protocols").setLevel(logging.ERROR)

    # 自定义 asyncio 异常处理器：吞掉 h11 协议错误 traceback
    import asyncio
    _orig_handler = asyncio.get_event_loop().get_exception_handler()
    def _quiet_exception_handler(loop, context):
        exc = context.get('exception')
        if exc and 'LocalProtocolError' in type(exc).__name__:
            return  # 不打印 h11 协议错误 traceback
        if _orig_handler:
            _orig_handler(loop, context)
        else:
            loop.default_exception_handler(context)
    asyncio.get_event_loop().set_exception_handler(_quiet_exception_handler)

    uvicorn.run(app, host="0.0.0.0", port=Config.BRIDGE_PORT, log_config=log_config)
