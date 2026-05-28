# app.py
import os

import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, send_from_directory
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from config import Config
from models import db, User, PhoneRecord
# tasks 模块导入正常（已不再引用 platform.py）
from tasks import start_send_code, start_submit_code


# import warnings
# # 屏蔽所有 Python 警告（可选）
# warnings.filterwarnings('ignore')


import logging
class NoRequestLogsFilter(logging.Filter):
    def filter(self, record):
        # 屏蔽包含 HTTP 方法的日志
        return not any(method in record.getMessage() for method in ['GET', 'POST', 'PUT', 'DELETE'])
log = logging.getLogger('werkzeug')
log.addFilter(NoRequestLogsFilter())


# 创建 Flask 应用，加载配置
app = Flask(__name__)
app.config.from_object(Config)

# 初始化数据库
db.init_app(app)

# 初始化登录管理器
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # 未登录用户自动跳转的视图

# 确保上传目录和数据目录存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['DATA_FOLDER']):
    os.makedirs(app.config['DATA_FOLDER'])

@login_manager.user_loader
def load_user(user_id):
    """根据用户 ID 加载 User 对象"""
    return User.query.get(int(user_id))

# ----- 注册 -----
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')

# ----- 登录 -----
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('登录成功')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误')
    return render_template('login.html')

# ----- 登出 -----
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----- 控制台 -----
@app.route('/dashboard')
@login_required
def dashboard():
    records = PhoneRecord.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', records=records)

# ----- 上传 Excel 导入手机号 -----
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_excel():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': '没有文件'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        # ① 使用 openpyxl 引擎，并确保读取所有列为文本（避免科学计数）
        df = pd.read_excel(filepath, header=None, dtype=str, engine='openpyxl')
        # 打印数据帧供调试（可选，生产环境可注释）
        print("=== 读取到的 Excel 内容 ===")
        print(df.head())

        imported = 0
        skipped = 0
        for _, row in df.iterrows():
            # ② 读取团队和手机号，处理 NaN
            team = str(row[0]).strip() if pd.notna(row[0]) else ''
            raw_phone = str(row[1]).strip() if pd.notna(row[1]) else ''

            # ③ 去除可能存在的 .0 后缀（数字被转成 '13800138000.0'）
            if '.' in raw_phone and raw_phone.endswith('.0'):
                raw_phone = raw_phone[:-2]
            # 去除空格、制表符、短横线等非法字符
            import re
            phone = re.sub(r'[\s\-\(\)]+', '', raw_phone)

            # ④ 基本验证：至少7位数字（支持国际号码可放宽）
            if not phone or not phone.isdigit() or len(phone) < 7:
                print(f"跳过无效号码: '{raw_phone}' -> '{phone}'")
                skipped += 1
                continue

            # ⑤ 使用 Session.get 方法查询是否已存在
            existing = db.session.get(PhoneRecord, phone)
            if not existing:
                rec = PhoneRecord(
                    team=team,
                    phone=phone,
                    user_id=current_user.id,
                    uploaded_by=current_user.id
                )
                db.session.add(rec)
                imported += 1
            else:
                # 如果希望同时更新已存在号码的团队，可取消下面注释
                # existing.team = team
                skipped += 1

        db.session.commit()
        msg = f'成功导入 {imported} 条新手机号'
        if skipped:
            msg += f'，跳过 {skipped} 条（已存在或格式错误）'
        print(msg)  # 控制台查看
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e:
        import traceback
        traceback.print_exc()  # 控制台打印完整错误堆栈
        return jsonify({'status': 'error', 'message': f'解析失败: {str(e)}'}), 400

# ----- 发送验证码 -----
@app.route('/api/send_code', methods=['POST'])
@login_required
def api_send_code():
    phone = request.json.get('phone', '').strip()
    if not phone:
        print("3333",jsonify({'status': 'error', 'message': '手机号为空'}), 400)
        return jsonify({'status': 'error', 'message': '手机号为空'}), 400
    record = PhoneRecord.query.get(phone)

    if not record or record.user_id != current_user.id:
        print("4444",jsonify({'status': 'error', 'message': '无权限操作此手机号'}), 403)
        return jsonify({'status': 'error', 'message': '无权限操作此手机号'}), 403
    started = start_send_code(phone, app)
    if not started:
        print("55555",jsonify({'status': 'error', 'message': '该手机号有操作正在进行，请稍后'}), 400)
        return jsonify({'status': 'error', 'message': '该手机号有操作正在进行，请稍后'}), 400
    print(record)
    print(started)
    print("6666",jsonify({'status': 'success', 'message': '验证码发送任务已启动'}))
    return jsonify({'status': 'success', 'message': '验证码发送任务已启动'})

# ----- 提交验证码 -----
@app.route('/api/submit_code', methods=['POST'])
@login_required
def api_submit_code():
    data = request.json
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    if not phone or not code:
        return jsonify({'status': 'error', 'message': '参数不完整'}), 400
    record = PhoneRecord.query.get(phone)
    if not record or record.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    started = start_submit_code(phone, code, app)
    if not started:
        return jsonify({'status': 'error', 'message': '该手机号有操作正在进行'}), 400
    return jsonify({'status': 'success', 'message': '登录任务已启动'})

# ----- 获取手机号最新状态（前端轮询） -----

@app.route('/api/phone_status/<phone>')
@login_required
def phone_status(phone):
    record = PhoneRecord.query.get(phone)
    if not record or record.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': '无权限'}), 404
    uploader = User.query.get(record.uploaded_by)
    return jsonify({
        'phone': record.phone,
        'team': record.team,
        'uploaded_by': uploader.username if uploader else '未知',
        'code_sent': record.code_sent,
        'logged_in': record.logged_in,
        'balance': record.balance,
        'bid_result': record.bid_result,
        'last_updated': record.last_updated.isoformat() if record.last_updated else ''
    })

# ----- 导出数据为 Excel -----
@app.route('/api/export')
@login_required
def export_data():
    records = PhoneRecord.query.filter_by(user_id=current_user.id).all()
    data = []
    for r in records:
        data.append({
            '手机号': r.phone,
            '验证码已发送': r.code_sent,
            '登录状态': '成功' if r.logged_in else '掉线',
            '中标结果': r.bid_result,
            '账户余额': r.balance,
            '最后更新': r.last_updated
        })
    df = pd.DataFrame(data)
    output = os.path.join(app.config['UPLOAD_FOLDER'], 'export.xlsx')
    df.to_excel(output, index=False)
    return send_from_directory(app.config['UPLOAD_FOLDER'], 'export.xlsx', as_attachment=True)

# app.py 新增 统计接口
@app.route('/api/stats')
@login_required
def stats():
    base_query = PhoneRecord.query.filter_by(user_id=current_user.id)
    total = base_query.count()
    success_login = base_query.filter_by(logged_in=True).count()
    offline = total - success_login
    bid_success = base_query.filter(PhoneRecord.bid_result.contains('成功')).count()
    return jsonify({
        'total': total,
        'success_login': success_login,
        'offline': offline,
        'bid_success': bid_success
    })
# app.py 新增 一键发送验证码（支持随机间隔
@app.route('/api/batch_send_code', methods=['POST'])
@login_required
def batch_send_code():
    data = request.json
    min_delay = int(data.get('min_delay', 10))
    max_delay = int(data.get('max_delay', 20))
    phones = [r.phone for r in PhoneRecord.query.filter_by(user_id=current_user.id).all()]
    if not phones:
        return jsonify({'status': 'error', 'message': '无号码'}), 400

    # 启动后台线程
    import threading, random, time
    def batch_task(app, phones, min_d, max_d):
        with app.app_context():
            from tasks import send_verification_code  # 直接调用发送函数，不另开线程
            for phone in phones:
                try:
                    send_verification_code(phone)   # 同步调用平台发送
                    # 在数据库中标记已发送
                    rec = PhoneRecord.query.get(phone)
                    if rec:
                        rec.code_sent = True
                        rec.last_updated = datetime.utcnow()
                        db.session.commit()
                except Exception as e:
                    print(f"批量发送 {phone} 失败: {e}")
                delay = random.randint(min_d, max_d)
                time.sleep(delay)
    t = threading.Thread(target=batch_task, args=(app, phones, min_delay, max_delay))
    t.daemon = True
    t.start()
    return jsonify({'status': 'success', 'message': f'批量发送已启动，共{len(phones)}个号码'})

# app.py 新增  接收手机端上传的验证码（供安卓 App 调用）
API_TOKEN = 'your-secure-token-change-me'

@app.route('/api/receive_sms', methods=['POST'])
def receive_sms():
    # 验证 API Token
    token = request.headers.get('X-API-TOKEN')
    if token != API_TOKEN:
        return jsonify({'status': 'error', 'message': '无权限'}), 403
    data = request.json
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    if not phone or not code:
        return jsonify({'status': 'error', 'message': '参数不完整'}), 400
    # 查找该手机号并自动提交验证码
    record = PhoneRecord.query.get(phone)
    if not record:
        return jsonify({'status': 'error', 'message': '手机号未在系统中'}), 404
    # 启动后台线程自动提交验证码登录（复用已有函数）
    from tasks import start_submit_code
    started = start_submit_code(phone, code, app)
    return jsonify({'status': 'success' if started else 'error', 'message': '任务已接收'})

# ----- 首页重定向 -----
@app.route('/')
def index():
    return redirect(url_for('login'))

# 启动服务（自动匹配 IP）
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host=Config.HOST, port=Config.PORT, threaded=True, debug=True)