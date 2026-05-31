#!/bin/bash
# ============================================================
# 猫妈妈服务端 Linux 一键安装/更新脚本
# 用法: bash install.sh              ← 首次安装
#       bash install.sh update       ← 更新（覆盖源码+重装依赖+重启）
# ============================================================
set -e

# ========== 配置 ==========
WEBDAV_BASE="http://ipla.top:3987"         # 网盘下载地址
INSTALL_DIR="/opt/moutai/3987"             # 安装目录
SERVICE_NAME="moutai-server-3987"          # systemd 服务名
PORT=5000

# Python3 路径
PYTHON="python3"
PIP="pip3"

# ========== 文件列表 ==========
FILES=(
    # 核心
    "moutai_automation.py"
    "demo.py"
    "crypto.py"
    "config.py"
    "models.py"
    # core 子模块
    "core/__init__.py"
    "core/database.py"
    # routes 路由
    "routes/__init__.py"
    "routes/api_app.py"
    "routes/api_bridge.py"
    "routes/api_client.py"
    "routes/api_teams.py"
    "routes/web_bind.py"
    # services 服务
    "services/__init__.py"
    "services/proxy_manager.py"
    "services/keepalive.py"
    # 前端模板
    "templates/base.html"
    "templates/dashboard.html"
    "templates/login.html"
    "templates/register.html"
    "templates/bind_account.html"
    "templates/team_dashboard.html"
    "templates/team_login.html"
    "templates/admin_users.html"
    # 静态资源
    "static/style.css"
    # WASM 签名文件 (瑞数 BotShield H5 抢购请求必需)
    "stub.wasm"
    "sign_wasm.bin"
)

# ===== 颜色 =====
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo ""
echo -e "${CYAN}========================================"
echo -e "  猫妈妈服务端 ${SERVICE_NAME}"
echo -e "  端口: ${PORT}"
echo -e "========================================${NC}"
echo ""

# ===== 检测系统 =====
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS="unknown"
fi

# ===== Step 1: 安装系统依赖 =====
echo -e "${YELLOW}[1/5] 安装系统依赖...${NC}"

install_system_deps() {
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y -qq wget curl python3 python3-pip python3-venv libcurl4-openssl-dev 2>/dev/null
    elif command -v yum &>/dev/null; then
        yum install -y -q wget curl python3 python3-pip 2>/dev/null
    elif command -v dnf &>/dev/null; then
        dnf install -y -q wget curl python3 python3-pip 2>/dev/null
    fi
}

install_system_deps
echo -e "${GREEN}  系统依赖已就绪${NC}"

# ===== Step 2: 创建虚拟环境 & 使用国内源配置 pip =====
echo -e "${YELLOW}[2/5] 配置 Python 虚拟环境...${NC}"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

if [ ! -d "venv" ]; then
    $PYTHON -m venv venv
fi
source venv/bin/activate

# 国内镜像源
MIRROR="https://mirrors.aliyun.com/pypi/simple/"
MIRROR_TSINGHUA="https://pypi.tuna.tsinghua.edu.cn/simple"
MIRROR_USTC="https://pypi.mirrors.ustc.edu.cn/simple/"

# 配置 pip 国内源
pip config set global.index-url $MIRROR 2>/dev/null || true

# 升级 pip
pip install --upgrade pip -q

# ===== Step 3: 下载源码文件 =====
echo -e "${YELLOW}[3/5] 从网盘拉取服务端文件...${NC}"

for FILE in "${FILES[@]}"; do
    URL="${WEBDAV_BASE}/${FILE}"
    LOCAL_PATH="${INSTALL_DIR}/${FILE}"
    LOCAL_DIR=$(dirname "$LOCAL_PATH")
    mkdir -p "$LOCAL_DIR"
    
    echo -n "  拉取 ${FILE} ... "
    if curl -fsSL --connect-timeout 5 --max-time 10 -o "$LOCAL_PATH" "$URL" 2>/dev/null; then
        echo -e "${GREEN}✓${NC}"
    else
        # 网盘下载失败，检查本地是否已有
        if [ -f "$LOCAL_PATH" ]; then
            echo -e "${YELLOW}网盘不可达，使用本地文件${NC}"
        else
            echo -e "${RED}失败! 文件不存在且网盘不可达${NC}"
        fi
    fi
done

echo -e "${GREEN}  文件拉取完成${NC}"

# ===== Step 4: 安装 Python 依赖 =====
echo -e "${YELLOW}[4/5] 安装 Python 依赖包（阿里云镜像源）...${NC}"

# 核心依赖（含国内源回退）
install_pkg() {
    local pkg=$1
    # 尝试多个国内源
    pip install "$pkg" -q 2>/dev/null && return 0
    pip install "$pkg" -i "$MIRROR_TSINGHUA" -q 2>/dev/null && return 0
    pip install "$pkg" -i "$MIRROR_USTC" -q 2>/dev/null && return 0
    echo -e "  ${RED}✗ $pkg 安装失败${NC}"
    return 1
}

PACKAGES=(
    "requests"
    "pillow"
    "fastapi"
    "uvicorn[standard]"
    "pymysql"
    "sqlalchemy"
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
    "wasmtime"     # WASM 运行时 (瑞数 BotShield H5 签名必需)
)

for pkg in "${PACKAGES[@]}"; do
    echo -n "  $pkg ... "
    install_pkg "$pkg" && echo -e "${GREEN}✓${NC}"
done

echo -e "${GREEN}  依赖安装完成${NC}"

# ===== Step 5: 创建 systemd 服务 =====
echo -e "${YELLOW}[5/5] 配置 systemd 服务...${NC}"

cat > /etc/systemd/system/${SERVICE_NAME}.service << SYSTEMDEOF
[Unit]
Description=猫妈妈服务端 (端口${PORT})
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

# 如果是更新，重启服务；否则启动
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo -e "  重启服务..."
    systemctl restart ${SERVICE_NAME}
else
    echo -e "  启动服务..."
    systemctl start ${SERVICE_NAME}
fi

sleep 2
systemctl status --no-pager -l ${SERVICE_NAME} 2>/dev/null || true

echo ""
echo -e "${GREEN}========================================"
echo -e "  部署完成!"
echo -e "========================================${NC}"
echo -e "  服务名:  ${CYAN}${SERVICE_NAME}${NC}"
echo -e "  端口:    ${CYAN}${PORT}${NC}"
echo -e "  状态:    ${CYAN}http://$(hostname -I | awk '{print $1}'):${PORT}${NC}"
echo ""
echo -e "  管理命令:"
echo -e "    查看状态:  systemctl status ${SERVICE_NAME}"
echo -e "    重启:      systemctl restart ${SERVICE_NAME}"
echo -e "    查看日志:  tail -f ${INSTALL_DIR}/server.log"
echo -e "    更新:      cd ${INSTALL_DIR} && bash install.sh update"
echo ""
