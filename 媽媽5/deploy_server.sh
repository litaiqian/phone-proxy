#!/bin/bash
# ============================================================
# 茅台抢购服务端 — 阿里云一键部署
# 用法: curl -sL http://ipla.top:6789/FuWuduan_3987/deploy_server.sh | bash
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

BASE_URL="http://ipla.top:6789/FuWuduan_3987"
INSTALL_DIR="/opt/moutai"
SERVICE_NAME="moutai-server"
PORT=5000

echo ""
echo -e "${CYAN}========================================"
echo "  茅台抢购服务端 一键部署"
echo "  安装目录: ${INSTALL_DIR}"
echo "  端口: ${PORT}"
echo -e "========================================${NC}"
echo ""

# ===== 1. 停止旧服务 =====
echo -e "${YELLOW}[1/5] 停止旧服务...${NC}"
systemctl stop ${SERVICE_NAME} 2>/dev/null || true
pkill -f "moutai_automation.py" 2>/dev/null || true
sleep 2
echo -e "${GREEN}  旧服务已停止${NC}"

# ===== 2. 系统依赖 =====
echo -e "${YELLOW}[2/5] 检查系统依赖...${NC}"
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq wget curl python3 python3-pip python3-venv libcurl4-openssl-dev libssl-dev 2>/dev/null
elif command -v yum &>/dev/null; then
    yum install -y -q wget curl python3 python3-pip python3-venv curl-devel openssl-devel 2>/dev/null
fi
echo -e "${GREEN}  系统依赖就绪${NC}"

# ===== 3. 下载文件 =====
echo -e "${YELLOW}[3/5] 从网盘下载源码...${NC}"
mkdir -p ${INSTALL_DIR}
cd ${INSTALL_DIR}

# 核心文件
for f in moutai_automation.py demo.py crypto.py requirements.txt; do
    echo -n "  ${f} ... "
    curl -fsSL --connect-timeout 10 --max-time 30 "${BASE_URL}/${f}" -o "${f}" && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
done

# routes/
mkdir -p routes
for f in __init__.py api_accounts.py api_app.py api_blackwhite.py api_bridge.py api_client.py api_config.py api_misc.py api_teams.py web_admin.py web_auth.py web_bind.py web_dashboard.py; do
    curl -fsSL --connect-timeout 10 --max-time 15 "${BASE_URL}/routes/${f}" -o "routes/${f}" 2>/dev/null
done
echo -e "  routes/ ${GREEN}✓ (13个文件)${NC}"

# templates/
mkdir -p templates
for f in admin_users.html base.html bind_account.html dashboard.html login.html register.html style.css team_dashboard.html team_login.html; do
    curl -fsSL --connect-timeout 10 --max-time 15 "${BASE_URL}/templates/${f}" -o "templates/${f}" 2>/dev/null
done
echo -e "  templates/ ${GREEN}✓ (9个文件)${NC}"

# slider/
mkdir -p slider
for f in __init__.py app_api_rounddv.js crypto_module.js fp.js ocr_server.py slider_client.py ua_generator.js; do
    curl -fsSL --connect-timeout 10 --max-time 15 "${BASE_URL}/slider/${f}" -o "slider/${f}" 2>/dev/null
done
echo -e "  slider/ ${GREEN}✓ (7个文件)${NC}"

echo -e "${GREEN}  下载完成${NC}"

# ===== 4. Python 虚拟环境 & 依赖 =====
echo -e "${YELLOW}[4/5] 配置 Python 环境 & 安装依赖...${NC}"

# 创建/复用 venv
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 国内镜像加速
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ 2>/dev/null || true
pip install --upgrade pip -q 2>/dev/null || true

# 核心依赖（分步安装，失败不中断）
PACKAGES=(
    "fastapi"
    "uvicorn[standard]"
    "sqlalchemy"
    "pymysql"
    "pandas"
    "werkzeug"
    "python-multipart"
    "httpx"
    "pycryptodome"
    "gmssl"
    "tls_client"
    "curl_cffi"
    "itsdangerous"
    "aiofiles"
    "jinja2"
    "wasmtime"
    "requests"
)

for pkg in "${PACKAGES[@]}"; do
    echo -n "  ${pkg} ... "
    pip install "${pkg}" -q 2>/dev/null && echo -e "${GREEN}✓${NC}" || {
        # 阿里云镜像失败则尝试清华源
        pip install "${pkg}" -i https://pypi.tuna.tsinghua.edu.cn/simple -q 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
    }
done

echo -e "${GREEN}  依赖安装完成${NC}"

# ===== 5. systemd 服务 & 启动 =====
echo -e "${YELLOW}[5/5] 配置 systemd 开机自启...${NC}"

cat > /etc/systemd/system/${SERVICE_NAME}.service << SYSTEMDEOF
[Unit]
Description=茅台抢购服务端 (端口${PORT})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/moutai_automation.py
Restart=always
RestartSec=5
StandardOutput=append:${INSTALL_DIR}/server.log
StandardError=append:${INSTALL_DIR}/server.log

[Install]
WantedBy=multi-user.target
SYSTEMDEOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

sleep 3

# 检查状态
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo ""
    echo -e "${GREEN}========================================"
    echo "  部署成功！"
    echo -e "========================================${NC}"
    echo -e "  服务名:   ${CYAN}${SERVICE_NAME}${NC}"
    echo -e "  端口:     ${CYAN}${PORT}${NC}"
    echo -e "  Web 管理: ${CYAN}http://ipla.top:${PORT}${NC}"
    echo ""
    echo "  管理命令:"
    echo "    查看状态:  systemctl status ${SERVICE_NAME}"
    echo "    重启:      systemctl restart ${SERVICE_NAME}"
    echo "    停止:      systemctl stop ${SERVICE_NAME}"
    echo "    查看日志:  tail -f ${INSTALL_DIR}/server.log"
    echo ""
else
    echo ""
    echo -e "${RED}========================================"
    echo "  启动失败！查看错误日志："
    echo -e "========================================${NC}"
    tail -20 ${INSTALL_DIR}/server.log
fi
