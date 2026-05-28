
# !/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版服务器 - 用于诊断启动问题
"""

import sys
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('debug.log', encoding='utf-8')
    ]
)
logger = logging.getLogger("DebugServer")

logger.info("=" * 60)
logger.info("开始诊断...")
logger.info("=" * 60)

# 测试1: 检查Python版本
logger.info(f"\n[测试1] Python版本: {sys.version}")

# 测试2: 检查必要库
try:
    import fastapi

    logger.info(f"[测试2] ✅ FastAPI 已安装: {fastapi.__version__}")
except ImportError as e:
    logger.error(f"[测试2] ❌ FastAPI 未安装: {e}")
    sys.exit(1)

try:
    import uvicorn

    logger.info(f"[测试3] ✅ Uvicorn 已安装: {uvicorn.__version__}")
except ImportError as e:
    logger.error(f"[测试3] ❌ Uvicorn 未安装: {e}")
    sys.exit(1)

try:
    import sqlalchemy

    logger.info(f"[测试4] ✅ SQLAlchemy 已安装: {sqlalchemy.__version__}")
except ImportError as e:
    logger.error(f"[测试4] ❌ SQLAlchemy 未安装: {e}")
    sys.exit(1)

try:
    import jinja2

    logger.info(f"[测试5] ✅ Jinja2 已安装: {jinja2.__version__}")
except ImportError as e:
    logger.error(f"[测试5] ❌ Jinja2 未安装: {e}")
    sys.exit(1)

try:
    import pandas

    logger.info(f"[测试6] ✅ Pandas 已安装")
except ImportError as e:
    logger.error(f"[测试6] ❌ Pandas 未安装: {e}")
    sys.exit(1)

# 测试7: 检查demo模块
BASEDIR = Path(__file__).parent.resolve()
logger.info(f"\n[测试7] 项目目录: {BASEDIR}")

demo_path = BASEDIR / 'demo'
if demo_path.exists():
    logger.info(f"[测试7] ✅ demo 目录存在: {demo_path}")

    # 检查demo/__init__.py
    init_file = demo_path / '__init__.py'
    if init_file.exists():
        logger.info(f"[测试7] ✅ demo/__init__.py 存在")
    else:
        logger.error(f"[测试7] ❌ demo/__init__.py 不存在")
else:
    logger.error(f"[测试7] ❌ demo 目录不存在")

# 尝试导入demo
try:
    logger.info("[测试8] 尝试导入 demo 模块...")
    from demo import MoutaiClient

    logger.info("[测试8] ✅ demo 模块导入成功")
except Exception as e:
    logger.error(f"[测试8] ❌ demo 模块导入失败: {e}")
    import traceback

    logger.error(traceback.format_exc())
    logger.info("\n💡 这可能是因为 demo 模块有语法错误或依赖缺失")

# 测试9: 检查templates目录
templates_path = BASEDIR / 'templates'
if templates_path.exists():
    logger.info(f"[测试9] ✅ templates 目录存在")
    html_files = list(templates_path.glob('*.html'))
    logger.info(f"[测试9] 找到 {len(html_files)} 个HTML文件:")
    for f in html_files:
        logger.info(f"      - {f.name}")
else:
    logger.error(f"[测试9] ❌ templates 目录不存在")

# 测试10: 创建最简单的FastAPI应用
logger.info("\n[测试10] 创建最简单的FastAPI应用...")
try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="Test Server")


    @app.get("/")
    async def root():
        return {"message": "Hello World"}


    @app.get("/test")
    async def test_page():
        return HTMLResponse(content="<h1>测试页面</h1>")


    logger.info("[测试10] ✅ FastAPI应用创建成功")

    # 启动服务器
    logger.info("\n" + "=" * 60)
    logger.info("🚀 启动测试服务器...")
    logger.info("=" * 60)
    logger.info("请在浏览器访问: http://127.0.0.1:8000")
    logger.info("按 Ctrl+C 停止服务器\n")

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

except Exception as e:
    logger.error(f"[测试10] ❌ 启动失败: {e}")
    import traceback

    logger.error(traceback.format_exc())
