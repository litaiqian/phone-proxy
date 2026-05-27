package top.ipla.phone_proxy.service

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import org.json.JSONObject
import java.net.Socket
import java.util.concurrent.TimeUnit

class TunnelClient(
    private val onWon: (phone: String, masked: String, item: String, orderId: String) -> Unit = { _, _, _, _ -> },
    private val onStatusChange: (connected: Boolean, tunnelId: String, error: String) -> Unit = { _, _, _ -> }
) {
    companion object {
        private const val TAG = "TunnelClient"
        const val WS_URL = "ws://ipla.top:5000/api/phone_proxy/ws"
    }

    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS) // 无限读取
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var running = false
    private var tunnelId = ""
    private var reconnectDelay = 3L
    private var activeTunnels = 0

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun start(deviceId: String, deviceName: String) {
        if (running) return
        running = true
        scope.launch { connect(deviceId, deviceName) }
    }

    fun stop() {
        running = false
        webSocket?.close(1000, "stopped")
        webSocket = null
        scope.cancel()
    }

    private suspend fun connect(deviceId: String, deviceName: String) {
        while (running) {
            try {
                reconnect(deviceId, deviceName)
            } catch (e: Exception) {
                Log.e(TAG, "连接失败: ${e.message}")
                onStatusChange(false, "", e.message ?: "unknown")
            }
            delay(reconnectDelay * 1000)
            reconnectDelay = (reconnectDelay * 1.5).toLong().coerceAtMost(30)
        }
    }

    private suspend fun reconnect(deviceId: String, deviceName: String) {
        suspendCancellableCoroutine<Unit> { cont ->
            val request = Request.Builder().url(WS_URL).build()
            webSocket = client.newWebSocket(request, object : WebSocketListener() {
                override fun onOpen(ws: WebSocket, response: Response) {
                    Log.d(TAG, "WebSocket 已连接")
                    // 注册
                    val registerMsg = JSONObject().apply {
                        put("type", "register")
                        put("name", deviceName)
                        put("device_id", deviceId)
                    }
                    ws.send(registerMsg.toString())
                }

                override fun onMessage(ws: WebSocket, text: String) {
                    handleMessage(ws, text)
                }

                override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                    Log.e(TAG, "WebSocket 失败: ${t.message}")
                    onStatusChange(false, "", t.message ?: "error")
                    if (cont.isActive) cont.resume(Unit)
                }

                override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                    Log.d(TAG, "WebSocket 关闭: $code $reason")
                    onStatusChange(false, "", "closed")
                    if (cont.isActive) cont.resume(Unit)
                }
            })
        }
    }

    private fun handleMessage(ws: WebSocket, text: String) {
        try {
            val msg = JSONObject(text)
            when (msg.optString("type")) {
                "registered" -> {
                    tunnelId = msg.getString("tunnel_id")
                    reconnectDelay = 3
                    onStatusChange(true, tunnelId, "")
                    Log.d(TAG, "注册成功: $tunnelId")
                }
                "connect" -> {
                    val tid = msg.getString("tunnel_id")
                    val host = msg.getString("host")
                    val port = msg.getInt("port")
                    activeTunnels++
                    scope.launch { doConnect(ws, tid, host, port) }
                }
                "change_ip" -> {
                    // IP 切换由服务端触发，由 ForegroundService 处理
                }
                "won" -> {
                    onWon(
                        msg.optString("phone", ""),
                        msg.optString("masked", ""),
                        msg.optString("item", "茅台"),
                        msg.optString("order_id", "")
                    )
                }
                "ping" -> ws.send("""{"type":"pong"}""")
            }
        } catch (e: Exception) {
            Log.e(TAG, "消息处理异常: ${e.message}")
        }
    }

    private suspend fun doConnect(ws: WebSocket, tunnelId: String, host: String, port: Int) {
        try {
            val remote = withContext(Dispatchers.IO) {
                Socket(host, port).apply { soTimeout = 0 }
            }
            ws.send(JSONObject().apply {
                put("type", "connected")
                put("tunnel_id", tunnelId)
            }.toString())

            // TCP → WebSocket
            launch(Dispatchers.IO) {
                try {
                    val buffer = ByteArray(8192)
                    while (running) {
                        val n = remote.getInputStream().read(buffer)
                        if (n <= 0) break
                        val prefix = "T$tunnelId".toByteArray()
                        ws.send(okhttp3.internal.Util.EMPTY_BYTE_ARRAY).let { }
                        // 使用 BinaryMessage
                        val data = ByteArray(13 + n)
                        System.arraycopy("T".toByteArray(), 0, data, 0, 1)
                        System.arraycopy(tunnelId.toByteArray(), 0, data, 1, 12)
                        System.arraycopy(buffer, 0, data, 13, n)
                        ws.send(okio.ByteString.of(*data))
                    }
                } catch (_: Exception) {}
                try { remote.close() } catch (_: Exception) {}
                activeTunnels--
            }
        } catch (e: Exception) {
            ws.send(JSONObject().apply {
                put("type", "error")
                put("tunnel_id", tunnelId)
            }.toString())
            activeTunnels--
        }
    }

    fun isConnected(): Boolean = tunnelId.isNotEmpty()
    fun getActiveTunnels(): Int = activeTunnels
}
