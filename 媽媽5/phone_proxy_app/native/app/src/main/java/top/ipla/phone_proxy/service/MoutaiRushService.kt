package top.ipla.phone_proxy.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import android.content.pm.ServiceInfo
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import top.ipla.phone_proxy.PhoneProxyApp
import top.ipla.phone_proxy.R
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.data.GetTasksRequest
import top.ipla.phone_proxy.data.PhoneHeartbeatRequest
import top.ipla.phone_proxy.data.PhoneHeartbeatResponse
import top.ipla.phone_proxy.data.PhoneReadyRequest
import top.ipla.phone_proxy.data.PhoneReadyResponse
import top.ipla.phone_proxy.data.PhoneStatusResponse
import top.ipla.phone_proxy.data.PrebuiltPacket
import top.ipla.phone_proxy.data.PrebuiltPackets
import top.ipla.phone_proxy.data.RelayRequest
import top.ipla.phone_proxy.data.RushRelayResponse
import top.ipla.phone_proxy.data.UploadLogRequest
import top.ipla.phone_proxy.util.DeviceId
import top.ipla.phone_proxy.util.NetworkUtil
import top.ipla.phone_proxy.util.ShellCrypto
import top.ipla.phone_proxy.util.LogBuffer
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 手机端空壳抢购执行器 — ForegroundService
 *
 * 【空壳架构】：所有加密/业务逻辑（AES/SM4/MurmurHash/BotShield/Bangcle/actParam/组单/下单/支付）
 * 已移至服务端预构建。手机只负责：
 *   1. WebSocket 长连接 → 接收预构建请求包
 *   2. HTTP 心跳 → 同步状态（开关/暂停/部署）
 *   3. T-0 时刻 → 替换 MT-K/V 实时签名 → 直接 HTTP 发射预构建请求
 *   4. 响应回传 → 服务端组单/下单/支付 → 逐包下发 → 手机逐包发射
 *   5. IP 切换 → 飞行模式切换蜂窝 IP
 *   6. WakeLock + 前台通知 → 防止被系统杀死
 *
 * 状态机：IDLE → AWAIT_CONFIG → PRE_RUSH → RUSHING → POST_RUSH → IDLE
 */
class MoutaiRushService : Service() {

    companion object {
        private const val TAG = "MoutaiRush"
        private const val WS_URL = "ws://8.137.86.132:5000/api/phone_proxy/ws"
        private const val HB_MIN_MS = 15_000L
        private const val HB_MAX_MS = 30_000L
        private const val PRE_RUSH_STOP_HB_SEC = 15
        private const val NETWORK_ADVANCE_MS = 100L          // 提前100ms发出
        private const val ROUND_INTERVAL_MS = 5 * 60 * 1000L
        private const val MAX_ROUNDS = 12
        private const val STATUS_POLL_MIN_MS = 120_000L
        private const val STATUS_POLL_MAX_MS = 240_000L
        val isRushing = AtomicBoolean(false)
    }

    // ============================================================
    // 状态机
    // ============================================================
    private enum class State { IDLE, AWAIT_CONFIG, PRE_RUSH, RUSHING, POST_RUSH }
    private var state = State.IDLE

    // ============================================================
    // 核心组件
    // ============================================================
    private lateinit var wakeLock: PowerManager.WakeLock
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val okHttp = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(180, TimeUnit.SECONDS)
        .build()

    // 中继 HTTP 客户端（抢购/组单/下单/支付 请求发射用）
    private val relayHttpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .writeTimeout(8, TimeUnit.SECONDS)
        .callTimeout(10, TimeUnit.SECONDS)
        .followRedirects(false)
        .retryOnConnectionFailure(true)
        .build()

    private var webSocket: WebSocket? = null
    private var wsConnected = AtomicBoolean(false)
    private var reconnectDelay = 3L
    private var lastPongTime = 0L
    private var wsPingRunning = AtomicBoolean(false)

    // ============================================================
    // 抢购运行时数据
    // ============================================================
    private var roundId = ""
    private var rushTargetTimeMs = 0L
    private var rushFrequencyMs = 100
    private var rushCount = 100
    private var heartbeatRunning = AtomicBoolean(true)
    private var httpPollingStarted = AtomicBoolean(false)
    private var statusPollingStarted = AtomicBoolean(false)
    private var lastKnownPhoneRushEnabled = -1
    private var lastKnownPaused = -1
    private var lastConfigRushTime = ""
    private var rushPaused = false
    private var roundNumber = 0
    private var roundGeneration = 0
    private var firstHeartbeatDone = AtomicBoolean(false)
    private var initialDeployStarted = AtomicBoolean(false)
    var deviceCount = java.util.concurrent.atomic.AtomicInteger(0)
    private var windowIndex = -1

    // ★ 空壳核心：服务端预构建的请求包（WebSocket 下发，T-0 发射）
    private var prebuiltPackets: PrebuiltPackets? = null

    // ★ 本轮日志收集（用于上传）
    private val roundLogs = StringBuilder()

    // ============================================================
    // 时间格式化
    // ============================================================
    private fun fmtMs(ts: Long): String = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date(ts))
    private fun parseServerTime(serverTime: String): String {
        if (serverTime.isBlank()) return ""
        return try {
            val sdf = SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss zzz", Locale.US)
            sdf.timeZone = TimeZone.getTimeZone("GMT")
            val parsed = sdf.parse(serverTime) ?: return ""
            SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(parsed)
        } catch (_: Exception) { "" }
    }

    private fun parseRushTime(timeStr: String): Long {
        val parts = timeStr.split(":", ".")
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, parts[0].toInt())
        cal.set(Calendar.MINUTE, parts[1].toInt())
        cal.set(Calendar.SECOND, parts[2].toInt())
        cal.set(Calendar.MILLISECOND, if (parts.size > 3) parts[3].toInt() else 0)
        return cal.timeInMillis
    }

    // ============================================================
    // 身份 / 设备工具
    // ============================================================
    private fun md5(input: String): String {
        val digest = java.security.MessageDigest.getInstance("MD5")
        val hashBytes = digest.digest(input.toByteArray())
        return hashBytes.joinToString("") { "%02x".format(it) }
    }

    private suspend fun getUploaderId(): Int {
        val uid = PhoneProxyApp.instance.prefs.getUserIdOnce()
        return uid?.toIntOrNull() ?: 0
    }

    private suspend fun getPrimaryAccount(): String {
        return try {
            val username = PhoneProxyApp.instance.prefs.getUsernameOnce()
            if (!username.isNullOrBlank()) return username
            val prefs = getSharedPreferences("moutai_rush", MODE_PRIVATE)
            val saved = prefs.getString("primary_username", "") ?: ""
            saved.ifBlank { "unknown" }
        } catch (e: Exception) {
            Log.e(TAG, "getPrimaryAccount error: ${e.message}")
            "unknown"
        }
    }

    private suspend fun getBatch(): Int {
        if (windowIndex < 0) {
            windowIndex = PhoneProxyApp.instance.prefs.getWindowIndexOnce()
        }
        if (windowIndex >= 0) {
            val savedTag = PhoneProxyApp.instance.prefs.getWindowDeviceTagOnce()
            val currentAndroidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
            if (!savedTag.isNullOrEmpty() && !currentAndroidId.isNullOrEmpty() && savedTag != currentAndroidId) {
                Log.w(TAG, "⚠️ 检测到设备克隆! 清除窗口号 $windowIndex")
                windowIndex = -1
                PhoneProxyApp.instance.prefs.saveWindowIndex(-1)
            }
        }
        if (windowIndex < 0) {
            try {
                val resp = ApiClient.rushService.getRushTasks(
                    GetTasksRequest(uploaderId = getUploaderId(), batch = -1)
                )
                windowIndex = resp.batch
                val tag = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: ""
                PhoneProxyApp.instance.prefs.saveWindowIndexWithTag(windowIndex, tag)
                Log.d(TAG, "获得窗口编号: $windowIndex")
            } catch (e: Exception) {
                Log.w(TAG, "获取窗口编号失败，使用0: ${e.message}")
                windowIndex = 0
            }
        }
        return windowIndex
    }

    // ============================================================
    // Service 生命周期
    // ============================================================

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "Service onCreate")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground()
        connectWebSocket()
        startWakeLockRefresh()
        startHttpPolling()
        startStatusPolling()
        startInitialDeploy()
        NetworkUtil.requestBatteryOptimization(this)
        NetworkUtil.bindCellular(this)
        return START_STICKY
    }

    override fun onDestroy() {
        Log.d(TAG, "Service onDestroy")
        disconnectWebSocket()
        scope.cancel()
        releaseWakeLock()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ============================================================
    // 前台通知 + WakeLock
    // ============================================================

    private fun startForeground() {
        val notification = NotificationCompat.Builder(this, PhoneProxyApp.CHANNEL_ID)
            .setContentTitle("养猫")
            .setContentText("猫咪待命中…")
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
            .build()

        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notification)
        }

        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "YangMao:RushWakeLock")
        wakeLock.setReferenceCounted(false)
        wakeLock.acquire(30 * 60 * 1000L)
        Log.d(TAG, "WakeLock acquired")
    }

    private fun startWakeLockRefresh() {
        scope.launch {
            var tick = 0
            while (isActive) {
                delay(60_000)
                tick++
                if (tick % 15 == 0) refreshWakeLock()
            }
        }
    }

    private fun refreshWakeLock() {
        if (!::wakeLock.isInitialized) return
        try {
            if (wakeLock.isHeld) wakeLock.release()
            wakeLock.acquire(30 * 60 * 1000L)
        } catch (_: Exception) {}
    }

    private fun releaseWakeLock() {
        if (::wakeLock.isInitialized && wakeLock.isHeld) {
            try { wakeLock.release() } catch (_: Exception) {}
        }
    }

    private fun updateNotification(text: String) {
        try {
            val notification = NotificationCompat.Builder(this, PhoneProxyApp.CHANNEL_ID)
                .setContentTitle("养猫")
                .setContentText(text)
                .setSmallIcon(R.drawable.ic_notification)
                .setOngoing(true)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .build()
            val nm = getSystemService(NotificationManager::class.java)
            nm.notify(1, notification)
        } catch (_: Exception) {}
    }

    // ============================================================
    // WebSocket 连接管理
    // ============================================================

    private fun connectWebSocket() {
        scope.launch {
            while (isActive) {
                try { wsConnect() } catch (e: Exception) {
                    Log.e(TAG, "WS连接失败: ${e.message}")
                }
                delay(reconnectDelay * 1000)
                reconnectDelay = (reconnectDelay * 1.5).toLong().coerceAtMost(30)
            }
        }
    }

    private suspend fun wsConnect() {
        val deferred = CompletableDeferred<Unit>()
        val request = Request.Builder().url(WS_URL).build()
        val deviceId = ApiClient.deviceId.ifEmpty { DeviceId.get(this@MoutaiRushService) }
        val name = "${Build.MANUFACTURER}_${Build.MODEL}"
        val uploaderId = getUploaderId()
        webSocket = okHttp.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket 已连接")
                LogBuffer.append("WS", "✅ 已连接 → ${WS_URL}")
                wsConnected.set(true)
                reconnectDelay = 3
                lastPongTime = System.currentTimeMillis()
                startWsPing()
                val regMsg = JSONObject().apply {
                    put("type", "register")
                    put("mode", "rush_client")
                    put("device_id", deviceId)
                    put("name", name)
                    put("user_id", uploaderId)
                }.toString()
                ws.send(regMsg)
                LogBuffer.append("WS", "📤 注册: device=$deviceId name=$name uid=$uploaderId")
                updateNotification("猫咪待命中…")
            }

            override fun onMessage(ws: WebSocket, text: String) {
                lastPongTime = System.currentTimeMillis()
                LogBuffer.append("WS", "📥 ${text.take(300)}")
                handleWsMessage(ws, text)
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WS失败: ${t.message}")
                LogBuffer.append("WS", "❌ 连接失败: ${t.message}")
                wsConnected.set(false)
                heartbeatRunning.set(false)
                if (!deferred.isCompleted) deferred.complete(Unit)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WS关闭: $code $reason")
                LogBuffer.append("WS", "🔒 关闭: code=$code reason=$reason")
                wsConnected.set(false)
                heartbeatRunning.set(false)
                if (!deferred.isCompleted) deferred.complete(Unit)
            }
        })
        deferred.await()
    }

    private fun disconnectWebSocket() {
        wsConnected.set(false)
        wsPingRunning.set(false)
        webSocket?.close(1000, "service_stopped")
        webSocket = null
    }

    // ============================================================
    // WebSocket 保活 ping
    // ============================================================

    private fun startWsPing() {
        if (!wsPingRunning.compareAndSet(false, true)) return
        scope.launch {
            while (isActive && wsConnected.get()) {
                delay(45_000L)
                if (!wsConnected.get()) break
                val sinceLastPong = System.currentTimeMillis() - lastPongTime
                if (sinceLastPong > 120_000L) {
                    LogBuffer.append("WS", "⚠️ ${sinceLastPong/1000}s无pong → 强制重连")
                    try { webSocket?.close(1001, "ping_timeout") } catch (_: Exception) {}
                    wsConnected.set(false)
                    break
                }
                try {
                    webSocket?.send("""{"type":"ping"}""")
                } catch (e: Exception) {
                    LogBuffer.append("WS", "❌ ping发送失败: ${e.message?.take(60)}")
                    wsConnected.set(false)
                    break
                }
            }
            wsPingRunning.set(false)
        }
    }

    // ============================================================
    // HTTP 心跳轮询（拉状态 + 账号）
    // ============================================================

    private fun startInitialDeploy() {
        if (!initialDeployStarted.compareAndSet(false, true)) return
        scope.launch {
            delay(4_000)
            if (state != State.IDLE) return@launch
            LogBuffer.append("INIT", "🚀 主动拉取初始配置…")
            updateNotification("正在获取抢购配置…")
            try {
                val uid = getUploaderId()
                val username = getPrimaryAccount()
                val identity = md5("${username}_${uid}")
                val deviceInfo = mapOf(
                    "brand" to (Build.BRAND ?: ""),
                    "model" to (Build.MODEL ?: ""),
                    "sdk" to Build.VERSION.SDK_INT.toString()
                )
                val hbResp = ApiClient.rushService.phoneHeartbeat(
                    PhoneHeartbeatRequest(
                        identity = identity, uploaderId = uid,
                        deviceInfo = deviceInfo, deviceTag = ApiClient.deviceId,
                        forceDeploy = true
                    )
                )
                if (hbResp.hasData && hbResp.rushConfig != null) {
                    val cfg = hbResp.rushConfig
                    val rushTimeFmt = String.format("%02d:%02d:%02d.%03d",
                        cfg.rushHour, cfg.rushMinute, cfg.rushSecond, cfg.rushMillisecond)
                    val phoneList = hbResp.accounts.map { it.phone.ifEmpty { "***" } }
                    LogBuffer.append("INIT", "✅ 主动部署成功 | time=$rushTimeFmt | accounts=${hbResp.accounts.size} | 手机号=$phoneList")
                    updateNotification("收到${hbResp.accounts.size}个账号 | 抢购 $rushTimeFmt")
                    handleDeployConfig(hbResp)
                } else {
                    val enabled = hbResp.phoneRushEnabled
                    if (enabled == 0) {
                        LogBuffer.append("INIT", "⚠️ 手机抢购开关关闭")
                        updateNotification("手机抢购未开启")
                    } else {
                        LogBuffer.append("INIT", "⏳ 状态=${hbResp.status} | 等待心跳下发…")
                    }
                    lastKnownPhoneRushEnabled = enabled
                    lastKnownPaused = hbResp.rushPaused
                }
            } catch (e: Exception) {
                Log.e(TAG, "主动初始部署失败: ${e.message}")
                LogBuffer.append("INIT", "❌ 主动部署失败: ${e.message?.take(100)}")
            }
        }
    }

    private fun startHttpPolling() {
        if (!httpPollingStarted.compareAndSet(false, true)) return
        scope.launch {
            delay(1000 + (Math.random() * 4000).toLong())
            Log.d(TAG, "HTTP轮询已启动")
            LogBuffer.append("HB", "📱 手机心跳已启动 → /api/phone/heartbeat")

            while (isActive) {
                if (rushTargetTimeMs > 0) {
                    val dist = Math.abs(System.currentTimeMillis() - rushTargetTimeMs)
                    if (dist < 10_000) { delay(500); continue }
                }
                if (state == State.PRE_RUSH || state == State.RUSHING || state == State.POST_RUSH) {
                    delay(1000); continue
                }
                try {
                    val username = getPrimaryAccount()
                    val uid = getUploaderId()
                    val identity = md5("${username}_${uid}")
                    val deviceInfo = mapOf(
                        "brand" to (Build.BRAND ?: ""),
                        "model" to (Build.MODEL ?: ""),
                        "sdk" to Build.VERSION.SDK_INT.toString()
                    )
                    val isFirstHb = !firstHeartbeatDone.getAndSet(true)
                    val hbResp = ApiClient.rushService.phoneHeartbeat(
                        PhoneHeartbeatRequest(
                            identity = identity, uploaderId = uid,
                            deviceInfo = deviceInfo, deviceTag = ApiClient.deviceId,
                            forceDeploy = isFirstHb
                        )
                    )
                    if (isFirstHb) {
                        LogBuffer.append("HB", "📱 首次心跳 | force_deploy=true")
                    }

                    if (!hbResp.hasData) {
                        syncHeartbeatState(hbResp)
                        delay(HB_MIN_MS + (Math.random() * (HB_MAX_MS - HB_MIN_MS)).toLong())
                        continue
                    }

                    // hasData=true → 收到新配置
                    handleDeployConfig(hbResp)

                } catch (e: Exception) {
                    Log.e(TAG, "手机心跳失败: ${e.message}")
                    LogBuffer.append("HB", "❌ 心跳请求失败: ${e.message?.take(100)}")
                }
                delay(HB_MIN_MS + (Math.random() * (HB_MAX_MS - HB_MIN_MS)).toLong())
            }
        }
    }

    private fun syncHeartbeatState(hbResp: PhoneHeartbeatResponse) {
        val serverEnabled = hbResp.phoneRushEnabled
        if (serverEnabled != lastKnownPhoneRushEnabled) {
            lastKnownPhoneRushEnabled = serverEnabled
            if (serverEnabled == 0) {
                LogBuffer.append("HB", "📱 手机抢购已关闭")
                updateNotification("手机抢购未开启")
            } else {
                LogBuffer.append("HB", "✅ 手机抢购已开启")
                updateNotification("已就绪，等待抢购")
            }
        }
        val serverPaused = hbResp.rushPaused == 1
        if (serverPaused != rushPaused) {
            rushPaused = serverPaused
            lastKnownPaused = hbResp.rushPaused
            if (serverPaused) {
                LogBuffer.append("HB", "⚠️ 服务端暂停抢购")
                updateNotification("抢购已暂停")
            } else {
                LogBuffer.append("HB", "✅ 服务端恢复抢购")
                if (lastKnownPhoneRushEnabled == 1) updateNotification("已就绪，等待抢购")
            }
        }
    }

    /** 处理服务端下发的配置+账号（初始部署 or 心跳） */
    private fun handleDeployConfig(hbResp: PhoneHeartbeatResponse) {
        val cfg = hbResp.rushConfig ?: return
        val rushTimeFmt = String.format("%02d:%02d:%02d.%03d",
            cfg.rushHour, cfg.rushMinute, cfg.rushSecond, cfg.rushMillisecond)

        rushPaused = hbResp.rushPaused == 1
        rushFrequencyMs = cfg.taskFrequency
        rushCount = cfg.rushCount
        lastConfigRushTime = rushTimeFmt
        rushTargetTimeMs = parseRushTime(rushTimeFmt)
        roundId = "${cfg.rushHour}${cfg.rushMinute}${cfg.rushSecond}_${System.currentTimeMillis()}"
        roundNumber = 1
        roundGeneration++
        state = State.AWAIT_CONFIG

        val phoneList = hbResp.accounts.map { it.phone.ifEmpty { "***" } }
        LogBuffer.append("HB", "📋 收到配置: $rushTimeFmt | 频率=${cfg.taskFrequency}ms | 次数=${cfg.rushCount} | 账号=${hbResp.accounts.size} | 多开=${hbResp.multiOpenCount} | 手机号=$phoneList")
        LogBuffer.append("CONFIG", "🎯 开始布置 | time=$rushTimeFmt | accounts=${hbResp.accounts.size}")
        updateNotification("收到${hbResp.accounts.size}个账号 | 抢购 $rushTimeFmt")

        // 告知服务端「布置完毕」
        scope.launch {
            try {
                val username = getPrimaryAccount()
                val uid = getUploaderId()
                val identity = md5("${username}_${uid}")
                val readyResp = ApiClient.rushService.phoneReady(
                    PhoneReadyRequest(identity = identity, uploaderId = uid,
                        verifiedCount = hbResp.accounts.size, deploymentId = "")
                )
                LogBuffer.append("HB", "✅ 布置完毕 | 就绪=${readyResp.deployedCount}/${readyResp.onlineCount} | 手机号=$phoneList")
            } catch (_: Exception) {
                LogBuffer.append("HB", "⚠️ 布置回执发送失败")
            }
        }

        // 计算距离抢购时间，到时进入 PRE_RUSH
        val remainingMs = rushTargetTimeMs - System.currentTimeMillis()
        if (remainingMs > PRE_RUSH_STOP_HB_SEC * 1000) {
            scope.launch {
                val waitMs = remainingMs - PRE_RUSH_STOP_HB_SEC * 1000
                if (waitMs > 0) {
                    Log.d(TAG, "距预准备还有 ${waitMs / 1000}秒，静默等待…")
                    delay(waitMs)
                }
                requestPrebuiltAndRush()
            }
        } else if (remainingMs > 0) {
            scope.launch { requestPrebuiltAndRush() }
        } else {
            Log.d(TAG, "抢购时间已过，跳过")
        }
    }

    // ============================================================
    // 状态轮询
    // ============================================================

    private fun startStatusPolling() {
        if (!statusPollingStarted.compareAndSet(false, true)) return
        scope.launch {
            delay(10_000 + (Math.random() * 20_000).toLong())
            LogBuffer.append("STATUS", "📡 状态轮询已启动 → /api/phone/status (间隔120~240s)")

            while (isActive) {
                if (state == State.PRE_RUSH || state == State.RUSHING || state == State.POST_RUSH) {
                    delay(5000); continue
                }
                try {
                    val uid = getUploaderId()
                    val username = getPrimaryAccount()
                    val identity = md5("${username}_${uid}")
                    val resp = ApiClient.rushService.phoneStatus(identity, uid)
                    val enabled = resp.phoneRushEnabled
                    val paused = resp.rushPaused
                    if (enabled != lastKnownPhoneRushEnabled) {
                        val prev = lastKnownPhoneRushEnabled
                        lastKnownPhoneRushEnabled = enabled
                        if (prev >= 0) {
                            if (enabled == 1) {
                                LogBuffer.append("STATUS", "✅ 状态轮询: 手机抢购已开启")
                                updateNotification("手机抢购已开启")
                            } else {
                                LogBuffer.append("STATUS", "📱 状态轮询: 手机抢购已关闭")
                                updateNotification("手机抢购未开启")
                            }
                        } else {
                            LogBuffer.append("STATUS", if (enabled == 1) "✅ 状态轮询: 手机抢购已开启" else "📱 状态轮询: 手机抢购已关闭")
                        }
                    }
                    if (paused != lastKnownPaused) {
                        val prev = lastKnownPaused
                        lastKnownPaused = paused
                        if (prev >= 0) {
                            rushPaused = paused == 1
                            if (paused == 1) {
                                LogBuffer.append("STATUS", "⚠️ 状态轮询: 服务端暂停抢购")
                                updateNotification("抢购已暂停")
                            } else {
                                LogBuffer.append("STATUS", "✅ 状态轮询: 服务端恢复抢购")
                                updateNotification("已就绪，等待抢购")
                            }
                        } else {
                            lastKnownPaused = paused
                            rushPaused = paused == 1
                        }
                    }
                } catch (e: Exception) {
                    LogBuffer.append("STATUS", "❌ 状态轮询失败: ${e.message?.take(80)}")
                }
                delay(STATUS_POLL_MIN_MS + (Math.random() * (STATUS_POLL_MAX_MS - STATUS_POLL_MIN_MS)).toLong())
            }
        }
    }

    // ============================================================
    // WebSocket 消息处理（空壳版）
    // ============================================================

    private fun handleWsMessage(ws: WebSocket, text: String) {
        try {
            val msg = JSONObject(text)
            when (msg.optString("type")) {
                "registered" -> {
                    Log.d(TAG, "注册成功: ${msg.optString("tunnel_id", "")}")
                    LogBuffer.append("WS", "✅ 注册成功 | tunnel=${msg.optString("tunnel_id","").take(20)}")
                    state = State.AWAIT_CONFIG
                    isRushing.set(false)
                    heartbeatRunning.set(true)
                    updateNotification("已连接，等待抢购配置…")
                    if (msg.has("status")) {
                        val status = msg.getJSONObject("status")
                        val enabled = status.optInt("phone_rush_enabled", -1)
                        val paused = status.optInt("rush_paused", -1)
                        if (enabled >= 0) {
                            lastKnownPhoneRushEnabled = enabled
                            rushPaused = paused == 1
                            lastKnownPaused = paused
                            if (enabled == 0) {
                                LogBuffer.append("WS", "📱 注册状态: 手机抢购已关闭")
                                updateNotification("手机抢购未开启")
                            } else {
                                LogBuffer.append("WS", "✅ 注册状态: 手机抢购已开启")
                                if (paused == 1) updateNotification("抢购已暂停")
                            }
                        }
                    }
                }
                "status_change" -> {
                    val enabled = msg.optInt("phone_rush_enabled", -1)
                    val paused = msg.optInt("rush_paused", -1)
                    if (enabled >= 0 && enabled != lastKnownPhoneRushEnabled) {
                        lastKnownPhoneRushEnabled = enabled
                        if (enabled == 1) {
                            LogBuffer.append("WS", "✅ 服务端推送: 手机抢购已开启")
                            updateNotification("手机抢购已开启")
                        } else {
                            LogBuffer.append("WS", "📱 服务端推送: 手机抢购已关闭")
                            updateNotification("手机抢购未开启")
                        }
                    }
                    if (paused >= 0 && paused != lastKnownPaused) {
                        lastKnownPaused = paused
                        rushPaused = paused == 1
                        if (paused == 1) {
                            LogBuffer.append("WS", "⚠️ 服务端推送: 抢购已暂停")
                            updateNotification("抢购已暂停")
                        } else {
                            LogBuffer.append("WS", "✅ 服务端推送: 抢购已恢复")
                            updateNotification("已就绪，等待抢购")
                        }
                    }
                }
                // ★ 空壳核心：接收服务端预构建请求包
                "prebuilt_packets" -> {
                    LogBuffer.append("WS", "📦 收到预构建请求包")
                    handlePrebuiltPackets(msg)
                }
                // ★ 空壳核心：接收服务端后续请求（组单/下单/支付）
                "relay_request" -> {
                    LogBuffer.append("WS", "🔄 收到中继请求")
                    executeRelayRequest(msg)
                }
                "change_ip" -> {
                    Log.d(TAG, "收到切IP指令")
                    LogBuffer.append("WS", "🔄 收到切IP指令")
                    switchIpAndReport(ws)
                }
                "pong" -> lastPongTime = System.currentTimeMillis()
                "ping" -> { try { ws.send("""{"type":"pong"}""") } catch (_: Exception) {} }
            }
        } catch (e: Exception) {
            Log.e(TAG, "WS消息处理异常: ${e.message}")
        }
    }

    // ============================================================
    // ★ 空壳核心：预构建请求 → T-0 发射
    // ============================================================

    /** T-15秒：进入 PRE_RUSH，向服务端请求预构建包 */
    private suspend fun requestPrebuiltAndRush() {
        state = State.PRE_RUSH
        isRushing.set(true)
        heartbeatRunning.set(false)
        wsPingRunning.set(false)
        roundLogs.clear()
        updateNotification("抢购准备中…")
        LogBuffer.append("RUSH", "🔧 抢购前准备(T-15s) | 心跳/WS ping 已停止 | 请求预构建包…")

        try {
            val reqMsg = JSONObject().apply {
                put("type", "request_prebuilt")
                put("round_id", roundId)
            }.toString()
            webSocket?.send(reqMsg)
            LogBuffer.append("RUSH", "📤 已发送预构建请求 → 等待服务端下发…")
        } catch (e: Exception) {
            LogBuffer.append("RUSH", "❌ 发送预构建请求失败: ${e.message}")
            abortRush(); return
        }

        // 等待预构建包（最多10秒）
        var waited = 0L
        while (prebuiltPackets == null && waited < 10_000) { delay(200); waited += 200 }

        if (prebuiltPackets == null) {
            LogBuffer.append("RUSH", "❌ 等待预构建包超时(10s) → 中止本轮")
            abortRush(); return
        }

        val pkgs = prebuiltPackets!!
        LogBuffer.append("RUSH", "✅ 收到预构建包 | ${pkgs.packets.size}个请求 | 等待T=0…")
        updateNotification("预构建就绪，${pkgs.packets.size}个请求待发射")

        val adjustedTargetMs = rushTargetTimeMs - NETWORK_ADVANCE_MS
        val remainingMs = adjustedTargetMs - System.currentTimeMillis()
        if (remainingMs > 20) {
            delay(remainingMs - 20)
            while (System.currentTimeMillis() < adjustedTargetMs) { /* busy-wait */ }
        }
        executePrebuiltRush()
    }

    private fun handlePrebuiltPackets(msg: JSONObject) {
        try {
            val packets = mutableListOf<PrebuiltPacket>()
            val arr = msg.optJSONArray("packets")
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val p = arr.getJSONObject(i)
                    val headers = mutableMapOf<String, String>()
                    val headersObj = p.optJSONObject("headers")
                    if (headersObj != null) {
                        val keys = headersObj.keys()
                        while (keys.hasNext()) { val k = keys.next(); headers[k] = headersObj.optString(k, "") }
                    }
                    packets.add(PrebuiltPacket(
                        accountIndex = p.optInt("account_index", i),
                        phone = p.optString("phone", ""),
                        url = p.optString("url", ""),
                        method = p.optString("method", "POST"),
                        headers = headers,
                        body = p.optString("body", ""),
                        rawDeviceId = p.optString("raw_device_id", "")
                    ))
                }
            }
            prebuiltPackets = PrebuiltPackets(
                roundId = msg.optString("round_id", roundId),
                rushTime = msg.optString("rush_time", ""),
                frequencyMs = msg.optInt("frequency_ms", rushFrequencyMs),
                rushCount = msg.optInt("rush_count", rushCount),
                packets = packets
            )
            roundId = prebuiltPackets!!.roundId
            LogBuffer.append("CONFIG", "📦 预构建包解析完成 | ${packets.size}个请求")
        } catch (e: Exception) {
            LogBuffer.append("CONFIG", "❌ 预构建包解析失败: ${e.message}")
        }
    }

    /** T=0：并发发射所有预构建请求 */
    private suspend fun executePrebuiltRush() {
        state = State.RUSHING
        val pkgs = prebuiltPackets ?: run { abortRush(); return }
        val startTs = System.currentTimeMillis()

        LogBuffer.append("RUSH", "🔥 抢购开始 | round=$roundId | 请求数=${pkgs.packets.size}")
        updateNotification("抢购中…")
        appendLog("▶ 抢购 round=$roundId | 请求=${pkgs.packets.size} | 开始=${fmtMs(startTs)}")

        val jobs = pkgs.packets.map { pkg ->
            scope.async { fireSinglePacket(pkg, pkgs.frequencyMs, pkgs.rushCount) }
        }
        val results = jobs.map { try { it.await() } catch (e: Exception) {
            RushRelayResponse(accountIndex = -1, phone = "?", body = "异常: ${e.message}")
        }}

        val elapsed = System.currentTimeMillis() - startTs
        state = State.POST_RUSH
        val won = results.count { it.responseCode == 2000 }
        appendLog("◀ 结束=${fmtMs(System.currentTimeMillis())} | 总耗时=${elapsed}ms | $won/${results.size}中签")
        LogBuffer.append("RUSH", "🏁 抢购完成 | 成功=$won/${results.size} | 耗时=${elapsed}ms")
        updateNotification("抢购完成，${won}中签")

        // ★ 抢购结束后批量回传结果（抢购途中不发送任何WS消息，专心抢购）
        for (r in results) {
            relayResponse(r)
        }

        uploadLogs()

        state = State.AWAIT_CONFIG
        isRushing.set(false)
        heartbeatRunning.set(true)
        startWsPing()
        updateNotification("第${roundNumber}轮完成，等待下一轮…")

        val has429 = results.any { it.httpStatus == 429 || it.responseCode == 429 }
        if (has429) {
            appendLog("检测到429 → 切IP")
            LogBuffer.append("IP", "⚠️ 检测到429，本轮结束后切IP")
            scope.launch { try { switchIpAndReport(webSocket) } catch (_: Exception) {} }
        }

        prebuiltPackets = null
        if (!rushPaused && roundNumber < MAX_ROUNDS) {
            roundNumber++
            rushTargetTimeMs += ROUND_INTERVAL_MS
            val timeStr = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date(rushTargetTimeMs))
            val remainingS = (rushTargetTimeMs - System.currentTimeMillis()) / 1000
            Log.d(TAG, "第${roundNumber}轮 目标时间=$timeStr | 剩余=${remainingS}秒")
            updateNotification("第${roundNumber}轮 $timeStr")
            val remainingMs = rushTargetTimeMs - System.currentTimeMillis()
            if (remainingMs > PRE_RUSH_STOP_HB_SEC * 1000) {
                val gen = roundGeneration
                scope.launch {
                    delay(remainingMs - PRE_RUSH_STOP_HB_SEC * 1000)
                    if (roundGeneration != gen) return@launch
                    requestPrebuiltAndRush()
                }
            } else if (remainingMs > 0) {
                scope.launch { requestPrebuiltAndRush() }
            }
        } else if (roundNumber >= MAX_ROUNDS) {
            LogBuffer.append("RUSH", "✅ 已完成${MAX_ROUNDS}轮，自动停止")
            updateNotification("已完成${MAX_ROUNDS}轮")
            state = State.IDLE
        }
    }

    /** 发射单个预构建请求包（替换 MT-K/V 后直接 HTTP 请求） */
    private suspend fun fireSinglePacket(pkg: PrebuiltPacket, frequencyMs: Int, maxAttempts: Int): RushRelayResponse {
        val phone = pkg.phone.ifEmpty { "pkg_${pkg.accountIndex}" }
        val startMs = System.currentTimeMillis()

        for (attempt in 1..maxAttempts) {
            if (attempt > 1) {
                delay(frequencyMs.toLong())
                if (System.currentTimeMillis() - startMs > 90_000) {
                    appendLog("[$phone] ⏰ 单账号耗尽90秒")
                    return RushRelayResponse(roundId = roundId, accountIndex = pkg.accountIndex,
                        phone = phone, responseCode = -1, body = "超时90秒")
                }
            }

            val liveHeaders = pkg.headers.toMutableMap()
            val rawDeviceId = pkg.rawDeviceId.ifEmpty { "" }
            // ★ 替换 MT-K/V 为实时时间戳签名
            val mtKv = ShellCrypto.generateMtKAndV(rawDeviceId)
            liveHeaders["MT-K"] = mtKv.mtK
            liveHeaders["MT-V"] = mtKv.mtV
            liveHeaders.remove("__MTK__")
            liveHeaders["MT-DTIME"] = SimpleDateFormat("EEE MMM dd HH:mm:ss 'GMT+08:00' yyyy", Locale.US).format(Date())

            val sendTs = System.currentTimeMillis()
            val elapsed: Long
            val response: Response
            try {
                val body = pkg.body.ifEmpty { "" }
                val rb = if (body.isNotEmpty())
                    body.toRequestBody("application/json; charset=UTF-8".toMediaType())
                else "".toRequestBody(null)
                val builder = Request.Builder().url(pkg.url)
                if (pkg.method.equals("GET", ignoreCase = true)) builder.get() else builder.post(rb)
                liveHeaders.forEach { (k, v) -> builder.addHeader(k, v) }
                response = relayHttpClient.newCall(builder.build()).execute()
                elapsed = System.currentTimeMillis() - sendTs
            } catch (e: IOException) {
                val elapsed2 = System.currentTimeMillis() - sendTs
                LogBuffer.append("RUSH", "❌ [$phone] #${attempt} 网络错误 | ${elapsed2}ms | ${e.message?.take(60)}")
                return RushRelayResponse(roundId = roundId, accountIndex = pkg.accountIndex,
                    phone = phone, httpStatus = -1, responseCode = -1,
                    body = "网络错误: ${e.message}", elapsedMs = elapsed2)
            }

            val respBody = try { response.body?.string() ?: "" } catch (_: Exception) { "" }
            val serverTime = response.header("Date", "")
            val respJson = try { JSONObject(respBody) } catch (_: Exception) { JSONObject().apply { put("_raw", respBody) } }
            val code = respJson.optInt("code", response.code)
            val msg = respJson.optString("message", "").ifEmpty { respJson.optString("msg", "") }
            val sendTime = fmtMs(sendTs)
            val srvTime = parseServerTime(serverTime)
            val srvTimeStr = if (srvTime.isNotEmpty()) " 响应=$srvTime" else ""

            appendLog("[${phone}] #${attempt} 发送=${sendTime}${srvTimeStr} 耗时=${elapsed}ms code=$code${if (msg.isNotEmpty()) " | $msg" else ""}")

            when {
                code == 2000 -> {
                    appendLog("[${phone}] 🎯 抢购成功! code=2000")
                    LogBuffer.append("RUSH", "🎯 [$phone] 抢购成功! code=2000")
                    response.close()
                    return RushRelayResponse(roundId = roundId, accountIndex = pkg.accountIndex,
                        phone = phone, httpStatus = response.code, responseCode = code,
                        body = respBody, elapsedMs = elapsed)
                }
                code == 429 || response.code == 429 -> {
                    appendLog("[${phone}] ⚡ 429限流")
                }
                code == 4031 || code == 4099 -> {
                    LogBuffer.append("RUSH", "⚫ [$phone] 黑号(code=$code) → 退出")
                    response.close()
                    return RushRelayResponse(roundId = roundId, accountIndex = pkg.accountIndex,
                        phone = phone, httpStatus = response.code, responseCode = code,
                        body = respBody, elapsedMs = elapsed)
                }
                else -> {
                    if (attempt == 1 || attempt % 20 == 0) {
                        LogBuffer.append("RUSH", "[$phone] #${attempt} code=$code ${elapsed}ms")
                    }
                }
            }
            response.close()
        }
        appendLog("[${phone}] 达最大次数 → 退出")
        return RushRelayResponse(roundId = roundId, accountIndex = pkg.accountIndex,
            phone = phone, responseCode = -1, body = "已达最大次数")
    }

    private fun relayResponse(resp: RushRelayResponse) {
        try {
            val msg = JSONObject().apply {
                put("type", "rush_response")
                put("round_id", resp.roundId)
                put("account_index", resp.accountIndex)
                put("phone", resp.phone)
                put("http_status", resp.httpStatus)
                put("response_code", resp.responseCode)
                put("body", resp.body.take(10000))
                put("server_time", resp.serverTime)
                put("elapsed_ms", resp.elapsedMs)
            }.toString()
            webSocket?.send(msg)
        } catch (e: Exception) {
            LogBuffer.append("RUSH", "❌ 结果回传失败: ${e.message}")
        }
    }

    /** 执行服务端下发的后续请求（组单/下单/支付） */
    private fun executeRelayRequest(msg: JSONObject) {
        scope.launch {
            try {
                val accountIndex = msg.optInt("account_index", 0)
                val phone = msg.optString("phone", "")
                val url = msg.optString("url", "")
                val method = msg.optString("method", "POST")
                val body = msg.optString("body", "")
                val rawDeviceId = msg.optString("raw_device_id", "")
                val headers = mutableMapOf<String, String>()
                val headersObj = msg.optJSONObject("headers")
                if (headersObj != null) {
                    val keys = headersObj.keys()
                    while (keys.hasNext()) { val k = keys.next(); headers[k] = headersObj.optString(k, "") }
                }
                val mtKv = ShellCrypto.generateMtKAndV(rawDeviceId)
                headers["MT-K"] = mtKv.mtK
                headers["MT-V"] = mtKv.mtV
                headers["MT-DTIME"] = SimpleDateFormat("EEE MMM dd HH:mm:ss 'GMT+08:00' yyyy", Locale.US).format(Date())

                val startMs = System.currentTimeMillis()
                val rb = if (body.isNotEmpty())
                    body.toRequestBody("application/json; charset=UTF-8".toMediaType())
                else "".toRequestBody(null)
                val builder = Request.Builder().url(url)
                if (method.equals("GET", ignoreCase = true)) builder.get() else builder.post(rb)
                headers.forEach { (k, v) -> builder.addHeader(k, v) }

                val response = relayHttpClient.newCall(builder.build()).execute()
                val elapsed = System.currentTimeMillis() - startMs
                val respBody = try { response.body?.string() ?: "" } catch (_: Exception) { "" }
                val serverTime = response.header("Date", "")
                appendLog("[${phone}] 🔄 中继 ${method} ${url.take(60)} code=${response.code} ${elapsed}ms")
                LogBuffer.append("RUSH", "🔄 [$phone] 中继 ${response.code} ${elapsed}ms | ${respBody.take(200)}")
                relayResponse(RushRelayResponse(roundId = roundId, accountIndex = accountIndex,
                    phone = phone, httpStatus = response.code,
                    responseCode = try { JSONObject(respBody).optInt("code", response.code) } catch (_: Exception) { response.code },
                    body = respBody.take(5000), serverTime = serverTime, elapsedMs = elapsed))
                response.close()
            } catch (e: Exception) {
                LogBuffer.append("RUSH", "❌ 中继请求失败: ${e.message}")
            }
        }
    }

    private fun abortRush() {
        state = State.AWAIT_CONFIG
        isRushing.set(false)
        heartbeatRunning.set(true)
        startWsPing()
        prebuiltPackets = null
        updateNotification("猫咪待命中…")
    }

    private fun appendLog(line: String) {
        synchronized(roundLogs) { roundLogs.append(line).append("\n") }
        Log.d(TAG, line)
    }

    // ============================================================
    // IP 切换
    // ============================================================

    private fun getCurrentPublicIp(): String {
        return try {
            val client = OkHttpClient.Builder().connectTimeout(4, TimeUnit.SECONDS).readTimeout(4, TimeUnit.SECONDS).build()
            val resp = client.newCall(Request.Builder().url("http://api.ipify.org").build()).execute()
            resp.body?.string()?.trim() ?: "unknown"
        } catch (_: Exception) { "unknown" }
    }

    private fun toggleAirplaneMode() {
        try {
            Runtime.getRuntime().exec(arrayOf("sh", "-c",
                "cmd connectivity airplane-mode enable && sleep 3 && cmd connectivity airplane-mode disable"))
            return
        } catch (_: Exception) {}
        try {
            Runtime.getRuntime().exec(arrayOf("sh", "-c",
                "settings put global airplane_mode_on 1; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true; sleep 3; settings put global airplane_mode_on 0; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"))
            return
        } catch (_: Exception) {}
        try {
            Runtime.getRuntime().exec(arrayOf("su", "-c",
                "settings put global airplane_mode_on 1; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true; sleep 3; settings put global airplane_mode_on 0; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"))
        } catch (_: Exception) {}
    }

    private fun switchIpAndReport(ws: WebSocket?) {
        try {
            val oldIp = getCurrentPublicIp()
            LogBuffer.append("IP", "🔄 切换前IP: $oldIp")
            updateNotification("切换IP中…")
            NetworkUtil.changeIp(this) { msg -> appendLog(msg) }
            Thread.sleep(5000)
            NetworkUtil.bindCellular(this)
            Thread.sleep(2000)
            var newIp = getCurrentPublicIp()
            LogBuffer.append("IP", "切换后IP: $newIp")
            if (newIp == oldIp) {
                toggleAirplaneMode()
                Thread.sleep(8000)
                NetworkUtil.bindCellular(this)
                Thread.sleep(3000)
                newIp = getCurrentPublicIp()
            }
            ws?.send(JSONObject().apply {
                put("type", "ip_changed")
                put("old_ip", oldIp as Any)
                put("new_ip", newIp as Any)
            }.toString())
            updateNotification("IP已切换")
        } catch (e: Exception) {
            appendLog("IP切换异常: ${e.message}")
            updateNotification("IP切换失败")
        }
    }

    // ============================================================
    // 日志上传
    // ============================================================

    private fun uploadLogs() {
        try {
            val body = JSONObject().apply {
                put("type", "rush_logs")
                put("round_id", roundId)
                put("device_id", ApiClient.deviceId)
                put("logs", roundLogs.toString())
                put("timestamp", System.currentTimeMillis())
            }
            val sent = try { webSocket?.send(body.toString()); true } catch (_: Exception) { false }
            if (sent) {
                Log.d(TAG, "日志已上传(WS): ${roundLogs.length}字符")
            } else {
                uploadLogsHttp()
            }
        } catch (e: Exception) {
            Log.e(TAG, "日志上传失败: ${e.message}")
            uploadLogsHttp()
        }
    }

    private fun uploadLogsHttp() {
        try {
            val logContent = roundLogs.toString()
            if (logContent.isBlank()) return
            scope.launch {
                try {
                    val sdf = SimpleDateFormat("dd", Locale.getDefault())
                    val day = sdf.format(Date())
                    val publicIp = try { java.net.URL("http://api.ipify.org").readText().trim() } catch (_: Exception) { "unknown" }
                    ApiClient.rushService.uploadLog(UploadLogRequest(
                        uuid = ApiClient.deviceId, log = logContent, day = day, publicIp = publicIp))
                    Log.d(TAG, "日志已上传(HTTP): ${logContent.length}字符")
                } catch (e: Exception) {
                    Log.e(TAG, "HTTP日志上传失败: ${e.message}")
                }
            }
        } catch (_: Exception) {}
    }
}
