[app]

# 包名
title = 养猫
package.name = phone_proxy
package.domain = top.ipla

# 入口
source.dir = .
main.py = main.py

# 版本
version = 1.0.0
version.code = 1

# Colab 必须开启
android.accept_root = True
android.accept_sdk_license = True

# 依赖
requirements = python3,kivy,requests,websocket-client,android

# Android 权限
android.permissions = INTERNET,FOREGROUND_SERVICE,FOREGROUND_SERVICE_DATA_SYNC,WAKE_LOCK,ACCESS_NETWORK_STATE,CHANGE_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_STATE,RECEIVE_BOOT_COMPLETED,POST_NOTIFICATIONS

# 固定版本
android.api = 34
android.minapi = 26
android.ndk = 25c

# 架构
android.archs = arm64-v8a

# 前台服务（main.py 已通过 jnius startForeground 自行处理，无需 p4a 服务声明）
# android.services = proxy_service:proxy_service.py

# 功能配置
android.allow_backup = False
android.presplash_color = #FF6B35
android.statusbar_color = #E85D28

# 签名（发布时取消注释，并确保 release.keystore 已生成）
p4a.bootstrap = sdl2
# android.release = True
# android.sign = release
# android.keystore = release.keystore
# android.keyalias = phone_proxy
# android.keystore_password = changeme
# android.keyalias_password = changeme

# 图标
icon.filename = %(source.dir)s/icon.png

# 方向
orientation = portrait

# 日志
android.logcat_filters = *:S python:D

# 广告配置
android.meta_data = \
    com.google.android.gms.ads.APPLICATION_ID=ca-app-pub-3940256099942544~3347511713

# 必须开启
android.enable_androidx = True

[buildozer]
build_dir = .buildozer
log_level = 2