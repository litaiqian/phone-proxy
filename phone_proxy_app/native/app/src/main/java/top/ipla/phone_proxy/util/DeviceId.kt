package top.ipla.phone_proxy.util

import android.content.Context
import java.util.UUID

object DeviceId {
    private const val PREFS_NAME = "device_prefs"
    private const val KEY_ID = "device_id"

    fun get(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        var id = prefs.getString(KEY_ID, null)
        if (id == null) {
            id = UUID.randomUUID().toString().replace("-", "").substring(0, 16)
            prefs.edit().putString(KEY_ID, id).apply()
        }
        return id
    }
}
