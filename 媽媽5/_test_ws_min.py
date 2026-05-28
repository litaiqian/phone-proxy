"""最小 WebSocket 测试"""
from fastapi import FastAPI
from fastapi.websockets import WebSocket
import uvicorn

app = FastAPI()

@app.websocket("/ws")
async def test_ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)
