package top.ipla.phone_proxy.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import top.ipla.phone_proxy.PhoneProxyApp
import top.ipla.phone_proxy.R
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.util.DeviceId
import top.ipla.phone_proxy.util.NetworkUtil
import kotlinx.coroutines.*

class ProxyForegroundService : Service() {

    private lateinit var wakeLock: PowerManager.WakeLock
    private lateinit var tunnelClient: TunnelClient
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    override fun onCreate() {
        super.onCreate()
        tunnelClient = TunnelClient(
            onWon = { phone, masked, item, orderId ->
                showWonNotification(masked.ifEmpty { phone })
            },
            onStatusChange = { connected, _, _ ->
                if (connected) {
                    updateNotification("猫咪正在觅食中…")
                } else {
                    updateNotification("猫咪睡着了，正在唤醒…")
                }
            }
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground()
        startTunnel()
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

    private fun startTunnel() {
        NetworkUtil.bindCellular(this)
        val name = "${Build.MANUFACTURER}_${Build.MODEL}"
        tunnelClient.start(ApiClient.deviceId, name)
    }

    private fun startHeartbeat() {
        scope.launch {
            while (isActive) {
                if (ApiClient.token.isNotEmpty()) {
                    try {
                        ApiClient.service.heartbeat()
                    } catch (_: Exception) {}
                }
                delay(60_000)
            }
        }
    }

    private fun updateNotification(text: String) {
        val notification = NotificationCompat.Builder(this, PhoneProxyApp.CHANNEL_ID)
            .setContentTitle("养猫")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(1, notification)
    }

    private fun showWonNotification(phone: String) {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            val ch = NotificationChannel("won_channel", "中签通知", NotificationManager.IMPORTANCE_HIGH)
            nm.createNotificationChannel(ch)
        }
        val n = NotificationCompat.Builder(this, "won_channel")
            .setContentTitle("🎉 中签通知")
            .setContentText("$phone 已中签！")
            .setSmallIcon(R.drawable.ic_notification)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .build()
        nm.notify(100, n)
    }

    override fun onDestroy() {
        tunnelClient.stop()
        scope.cancel()
        if (::wakeLock.isInitialized && wakeLock.isHeld) {
            wakeLock.release()
        }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
