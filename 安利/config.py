# config.py
import os

# 基础目录，用于生成绝对路径
BASEDIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Flask 密钥
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
    # 数据库 URI
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASEDIR, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 上传文件夹
    UPLOAD_FOLDER = os.path.join(BASEDIR, 'uploads')
    # 独立数据保存目录
    DATA_FOLDER = os.path.join(BASEDIR, 'data')
    # 第三方平台 API 地址（需替换为真实地址）
    PLATFORM_BASE_URL = 'https://api.example-platform.com'
    # 最大并发线程数
    MAX_THREADS = 10
    # 监听所有网络接口，自动匹配本机 IP
    HOST = '0.0.0.0'
    # 监听端口
    PORT = 5000