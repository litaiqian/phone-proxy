#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Android 前台服务
保持后台常驻不被杀，系统杀死后自动重启
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import run_tunnel

if __name__ == '__main__':
    threading.Thread(target=run_tunnel, daemon=True).start()
    import time
    while True:
        time.sleep(60)
