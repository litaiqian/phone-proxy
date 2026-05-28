'''




#!/bin/bash
# i茅台自动化服务端一键部署脚本（Ubuntu/Debian）

set -e

echo "=== 安装依赖 ==="
apt update
apt install -y python3 python3-pip sqlite3

echo "=== 下载代码 ==="
wget -O moutai_automation.py https://your-server.com/moutai_automation.py   # 实际部署时替换为真实URL
wget -O demo.py https://your-server.com/demo.py   # 需要将demo.py也上传到服务器

echo "=== 安装Python库 ==="
pip3 install flask flask-sqlalchemy flask-login pandas openpyxl werkzeug tls-client pycryptodome gmssl

echo "=== 初始化数据库 ==="
python3 -c "from moutai_automation import app, db; app.app_context().push(); db.create_all()"

echo "=== 启动服务 ==="
nohup python3 moutai_automation.py > moutai.log 2>&1 &
echo "服务已启动，端口5000"















'''