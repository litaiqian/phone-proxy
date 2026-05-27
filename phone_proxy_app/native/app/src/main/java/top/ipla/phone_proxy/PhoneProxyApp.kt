package top.ipla.phone_proxy

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.util.DeviceId

class PhoneProxyApp : Application() {

    lateinit var prefs: top.ipla.phone_proxy.data.PreferencesManager
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        prefs = top.ipla.phone_proxy.data.PreferencesManager(this)

        // 初始化 DeviceId
        ApiClient.deviceId = DeviceId.get(this)

        // 创建通知渠道（Android 8+ 必须）
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "养猫",
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply {
            description = "猫咪正在觅食中"
            setShowBadge(false)
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_ID = "yangmao_channel"
        lateinit var instance: PhoneProxyApp
            private set
    }
}
