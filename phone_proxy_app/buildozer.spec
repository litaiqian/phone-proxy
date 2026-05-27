[app]

# 包名和标题
title = 养猫
package.name = phone_proxy
package.domain = top.ipla

# 版本（升级时递增）
version = 1.0.2
version.code = 3

# 入口
source.dir = .
main.py = main.py

# ==================== Android 基础 ====================
android.accept_root = True
android.accept_sdk_license = True
android.api = 34
android.minapi = 21
android.ndk = 25c

# p4a develop 分支（含最新 SDL2 修复，解决 HyperOS 闪退）
p4a.branch = develop

# 支持多架构（适配各种手机）
android.archs = arm64-v8a,armeabi-v7a

# ==================== 依赖 ====================
# 注意: 不加 android 包，华为/荣耀无 GMS 会崩溃
# 所有 Android API 通过 jnius 直接调用
requirements = python3,kivy,requests,websocket-client

# ==================== 必要权限 ====================
android.permissions = \
    INTERNET,\
    FOREGROUND_SERVICE,\
    FOREGROUND_SERVICE_DATA_SYNC,\
    FOREGROUND_SERVICE_SPECIAL_USE,\
    WAKE_LOCK,\
    ACCESS_NETWORK_STATE,\
    CHANGE_NETWORK_STATE,\
    ACCESS_WIFI_STATE,\
    CHANGE_WIFI_STATE,\
    RECEIVE_BOOT_COMPLETED,\
    POST_NOTIFICATIONS,\
    REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,\
    SYSTEM_ALERT_WINDOW,\
    QUERY_ALL_PACKAGES,\
    READ_PHONE_STATE,\
    ACCESS_FINE_LOCATION

# ==================== UI 配置 ====================
orientation = portrait
icon.filename = %(source.dir)s/icon.png
android.presplash_color = #FF6B35
android.statusbar_color = #E85D28

# ==================== 签名（需先生成 release.keystore）====================
p4a.bootstrap = sdl2
# android.release = True
# android.sign = release
# android.keystore = release.keystore
# android.keyalias = phone_proxy
# android.keystore_password = phone_proxy_2024
# android.keyalias_password = phone_proxy_2024

android.allow_backup = False
android.enable_androidx = True

# ==================== 日志 ====================
android.logcat_filters = *:S python:D

# ==================== 广告 ====================
android.meta_data = \
    com.google.android.gms.ads.APPLICATION_ID=ca-app-pub-3940256099942544~3347511713

# ==================== Build 配置 ====================
[buildozer]
build_dir = .buildozer
log_level = 2
