#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滑块验证模块 — 服务端桥接 + 客户端轻量调用
提供统一的滑块验证 API，服务端统一管理，客户端按需调用
"""
import base64
import httpx
from config import Config

SLIDER_API_URL = Config.SLIDER_API_URL      # Express.js: http://127.0.0.1:8887
OCR_SERVER_URL = Config.OCR_SERVER_URL      # Flask: http://127.0.0.1:9898


class SliderClient:
    """
    滑块验证客户端封装
    支持服务端（FastAPI）和客户端（moutai_client_worker）两种调用方式
    """
    def __init__(self, base_url: str = None):
        self.base_url = base_url or SLIDER_API_URL

    async def verify(self, captcha_id: str, bg_url: str = "", fg_url: str = "",
                     verify_type: str = "slide", **kwargs) -> dict:
        """通用滑块验证"""
        try:
            payload = {
                "captchaId": captcha_id,
                "bgUrl": bg_url,
                "fgUrl": fg_url,
                "verifyType": verify_type,
                **kwargs
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{self.base_url}/api/verify", json=payload)
                if resp.status_code == 200:
                    return {"success": True, "result": resp.json()}
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_sync(self, captcha_id: str, bg_url: str = "", fg_url: str = "",
                    verify_type: str = "slide", **kwargs) -> dict:
        """同步滑块验证（供客户端线程使用）"""
        import requests
        try:
            payload = {
                "captchaId": captcha_id,
                "bgUrl": bg_url,
                "fgUrl": fg_url,
                "verifyType": verify_type,
                **kwargs
            }
            resp = requests.post(f"{self.base_url}/api/verify", json=payload, timeout=30)
            if resp.status_code == 200:
                return {"success": True, "result": resp.json()}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def ocr(self, image_data: bytes, img_type: str = "slide") -> dict:
        """OCR识别"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                files = {"image": ("captcha.png", image_data, "image/png")}
                resp = await client.post(f"{OCR_SERVER_URL}/ocr/{img_type}", files=files)
                if resp.status_code == 200:
                    return {"success": True, "result": resp.json()}
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def slide_match(self, bg_bytes: bytes, fg_bytes: bytes,
                          algo_type: str = "match") -> dict:
        """滑块匹配"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                files = {
                    "bg": ("bg.png", bg_bytes, "image/png"),
                    "fg": ("fg.png", fg_bytes, "image/png"),
                }
                resp = await client.post(
                    f"{OCR_SERVER_URL}/slide/{algo_type}/match", files=files)
                if resp.status_code == 200:
                    return {"success": True, "result": resp.json()}
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# 全局单例
slider_client = SliderClient()


def check_services() -> dict:
    """检查滑块服务是否可用"""
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
