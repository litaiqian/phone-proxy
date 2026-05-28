#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫妈妈自动化系统 — 滑块验证桥接服务
将滑块验证请求转发到本地 Express.js (port 8887) 和 OCR Server (port 9898)
"""

import httpx
from config import Config

SLIDER_API_URL = Config.SLIDER_API_URL      # http://127.0.0.1:8887
OCR_SERVER_URL = Config.OCR_SERVER_URL      # http://127.0.0.1:9898


async def verify_slider_captcha(
    captcha_id: str = "",
    bg_url: str = "",
    fg_url: str = "",
    verify_type: str = "slide",
    **kwargs
) -> dict:
    """
    调用 Express 滑块验证 API 完成滑块验证
    返回: {"success": bool, "result": {...}, "error": str}
    """
    try:
        payload = {
            "captchaId": captcha_id,
            "bgUrl": bg_url,
            "fgUrl": fg_url,
            "verifyType": verify_type,
            **kwargs
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{SLIDER_API_URL}/api/verify",
                json=payload
            )
            if resp.status_code == 200:
                return {"success": True, "result": resp.json()}
            return {"success": False, "error": f"滑块服务返回 {resp.status_code}"}
    except httpx.ConnectError:
        return {"success": False, "error": "滑块服务不可用 (port 8887)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def ocr_recognize(image_data: bytes, img_type: str = "slide") -> dict:
    """调用 OCR 服务识别验证码图片"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            files = {"image": ("captcha.png", image_data, "image/png")}
            resp = await client.post(
                f"{OCR_SERVER_URL}/ocr/{img_type}",
                files=files
            )
            if resp.status_code == 200:
                return {"success": True, "result": resp.json()}
            return {"success": False, "error": f"OCR服务返回 {resp.status_code}"}
    except httpx.ConnectError:
        return {"success": False, "error": "OCR服务不可用 (port 9898)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def ocr_slide_match(
    bg_bytes: bytes,
    fg_bytes: bytes,
    algo_type: str = "match"
) -> dict:
    """调用 OCR 滑块匹配服务，计算滑块偏移量"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            files = {
                "bg": ("bg.png", bg_bytes, "image/png"),
                "fg": ("fg.png", fg_bytes, "image/png"),
            }
            resp = await client.post(
                f"{OCR_SERVER_URL}/slide/{algo_type}/match",
                files=files
            )
            if resp.status_code == 200:
                return {"success": True, "result": resp.json()}
            return {"success": False, "error": f"滑块匹配返回 {resp.status_code}"}
    except httpx.ConnectError:
        return {"success": False, "error": "OCR服务不可用 (port 9898)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_slider_services() -> dict:
    """同步检查滑块服务是否可用（启动时调用）"""
    import requests
    status = {"slider_api": False, "ocr_server": False}
    try:
        r = requests.get(f"{SLIDER_API_URL}/health", timeout=3)
        status["slider_api"] = r.status_code == 200
    except Exception:
        pass
    try:
        r = requests.get(f"{OCR_SERVER_URL}/health", timeout=3)
        status["ocr_server"] = r.status_code == 200
    except Exception:
        pass
    return status
