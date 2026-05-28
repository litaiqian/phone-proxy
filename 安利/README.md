project/
├── app.py                 # 主程序入口，包含路由、前端页面、API
├── config.py              # 配置文件（数据库、平台接口等）
├── models.py              # 数据库模型定义
├── external_api.py        # 第三方平台 API 封装（发送验证码、登录、查余额）
├── tasks.py               # 后台多线程任务调度
├── templates/
│   ├── base.html          # 基础模板（含导航）
│   ├── login.html         # 登录页
│   ├── register.html      # 注册页
│   └── dashboard.html     # 导入/数据列表操作页
├── static/
│   └── style.css          # 样式
├── uploads/               # Excel 上传临时目录
├── data/                  # 每个手机号独立存放的 JSON 数据
├── requirements.txt
└── README.md