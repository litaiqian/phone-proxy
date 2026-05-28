import os

BASEDIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASEDIR, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASEDIR, 'uploads')
    DATA_FOLDER = os.path.join(BASEDIR, 'data')



    MAX_THREADS = 10
    HOST = '0.0.0.0'
    PORT = 5000

    # 短信接收 API 的 Token
    API_TOKEN = 'your-secure-token-change-me'