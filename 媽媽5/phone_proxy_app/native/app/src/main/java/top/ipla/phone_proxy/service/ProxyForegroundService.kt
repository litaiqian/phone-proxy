package top.ipla.phone_proxy.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.content.pm.ServiceInfo
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import top.ipla.phone_proxy.PhoneProxyApp
import top.ipla.phone_proxy.R
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.util.NetworkUtil
import kotlinx.coroutines.*

/**
 * 手机保活 + HTTP心跳服务（已移除隧道代理）
 *
 * 负责：
 *   1. WakeLock + 前台通知 → 防止被系统杀死
 *   2. HTTP 心跳（25~35s）→ 服务端记录在线时长 → 猫粮计算
 *   3. 蜂窝网络绑定 → 确保使用手机流量
 *
 * 注意：隧道代理已移除，手机直抢由 MoutaiRushService 独立负责
 */
class ProxyForegroundService : Service() {

    private lateinit var wakeLock: PowerManager.WakeLock
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    override fun onCreate() {
        super.onCreate()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground()
        NetworkUtil.startNetworkMonitoring(this)  // 持续监听蜂窝网络变化，自动重绑
        startHeartbeat()
        NetworkUtil.requestBatteryOptimization(this)
        return START_STICKY
    }

    private fun startForeground() {
        val notification = NotificationCompat.Builder(this, PhoneProxyApp.CHANNEL_ID)
            .setContentTitle("养猫")
            .setContentText("猫咪正在觅食中…")
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
            .build()

        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notification)
        }

        // WakeLock
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "YangMao:WakeLock"
        )
        wakeLock.setReferenceCounted(false)
        wakeLock.acquire(30 * 60 * 1000L)
    }

    private fun startHeartbeat() {
        scope.launch {
            var tick = 0
            // 首次随机延迟，避免所有手机同时启动就同时发心跳
            delay((25_000 + (Math.random() * 10_000)).toLong())
            while (isActive) {
                // 抢购期间暂停心跳，避免影响抢购网络
                if (MoutaiRushService.isRushing.get()) {
                    delay(1000)
                    continue
                }
                if (ApiClient.token.isNotEmpty()) {
                    try {
                        ApiClient.service.heartbeat()
                    } catch (_: Exception) {}
                }
                // 每约20分钟续期 WakeLock，防止锁屏后 CPU 进入深度休眠
                tick++
                if (tick % 40 == 0) {
                    refreshWakeLock()
                }
                // 随机间隔 30~120 秒，打散请求高峰（降频以减少服务器压力）
                delay((30_000 + (Math.random() * 90_000)).toLong())
            }
        }
    }

    private fun refreshWakeLock() {
        if (!::wakeLock.isInitialized) return
        try {
            if (wakeLock.isHeld) {
                wakeLock.release()
            }
            wakeLock.acquire(30 * 60 * 1000L)
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        scope.cancel()
        if (::wakeLock.isInitialized && wakeLock.isHeld) {
            wakeLock.release()
        }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
