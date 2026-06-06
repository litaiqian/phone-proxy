package top.ipla.phone_proxy.util

import android.content.Context
import android.provider.Settings
import java.util.UUID

object DeviceId {
    private const val PREFS_NAME = "device_prefs"
    private const val KEY_ID = "device_id"

    /**
     * 获取设备唯一标识。优先使用系统 ANDROID_ID（云手机克隆镜像后每台不同），
     * 若不可用则降级为随机 UUID 并持久化。
     */
    fun get(context: Context): String {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        // ANDROID_ID 有效（非 null 且非 9774d56d682e549c 这个已知无效值）
        if (!androidId.isNullOrEmpty() && androidId != "9774d56d682e549c") {
            // 存储下来以便检测设备变更
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val savedAndroidId = prefs.getString("android_id", null)
            if (savedAndroidId != androidId) {
                // 设备已变更（镜像克隆或恢复出厂），清理旧数据
                prefs.edit()
                    .putString("android_id", androidId)
                    .remove(KEY_ID)  // 清除旧的随机 UUID
                    .apply()
            }
            return androidId.take(32)  // 取前32字符确保长度可控
        }
        // 降级：随机 UUID（仅在 ANDROID_ID 不可用时使用）
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        var id = prefs.getString(KEY_ID, null)
        if (id == null) {
            id = UUID.randomUUID().toString().replace("-", "").substring(0, 16)
            prefs.edit().putString(KEY_ID, id).apply()
        }
        return id
    }
}
