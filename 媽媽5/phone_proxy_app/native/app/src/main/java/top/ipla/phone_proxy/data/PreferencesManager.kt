package top.ipla.phone_proxy.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "app_prefs")

class PreferencesManager(private val context: Context) {

    companion object {
        private val KEY_TOKEN = stringPreferencesKey("token")
        private val KEY_USERNAME = stringPreferencesKey("username")
        private val KEY_USER_ID = stringPreferencesKey("user_id")
        private val KEY_DEVICE_ID = stringPreferencesKey("device_id")
        private val KEY_WINDOW_INDEX = intPreferencesKey("window_index")
        private val KEY_WINDOW_DEVICE_TAG = stringPreferencesKey("window_device_tag")
    }

    val token: Flow<String?> = context.dataStore.data.map { it[KEY_TOKEN] }
    val username: Flow<String?> = context.dataStore.data.map { it[KEY_USERNAME] }
    val userId: Flow<String?> = context.dataStore.data.map { it[KEY_USER_ID] }
    val deviceId: Flow<String?> = context.dataStore.data.map { it[KEY_DEVICE_ID] }
    val windowIndex: Flow<Int?> = context.dataStore.data.map { it[KEY_WINDOW_INDEX] }

    suspend fun saveAuth(token: String, username: String, userId: String) {
        context.dataStore.edit {
            it[KEY_TOKEN] = token
            it[KEY_USERNAME] = username
            it[KEY_USER_ID] = userId
        }
    }

    suspend fun saveDeviceId(id: String) {
        context.dataStore.edit { it[KEY_DEVICE_ID] = id }
    }

    suspend fun clearAuth() {
        context.dataStore.edit {
            it.remove(KEY_TOKEN)
            it.remove(KEY_USERNAME)
            it.remove(KEY_USER_ID)
        }
    }

    /** 一次性读取 token（不阻塞，取第一个值即返回） */
    suspend fun getTokenOnce(): String? {
        return context.dataStore.data.first()[KEY_TOKEN]
    }

    /** 一次性读取 username */
    suspend fun getUsernameOnce(): String? {
        return context.dataStore.data.first()[KEY_USERNAME]
    }

    /** 一次性读取 user_id（即 uploader_id，用于抢购 API 鉴权） */
    suspend fun getUserIdOnce(): String? {
        return context.dataStore.data.first()[KEY_USER_ID]
    }

    /** 保存窗口编号（batch），-1 表示尚未分配 */
    suspend fun saveWindowIndex(index: Int) {
        context.dataStore.edit { it[KEY_WINDOW_INDEX] = index }
    }

    /** 一次性读取窗口编号，未分配返回 -1 */
    suspend fun getWindowIndexOnce(): Int {
        return context.dataStore.data.first()[KEY_WINDOW_INDEX] ?: -1
    }

    /** 保存窗口编号 + 设备标签（ANDROID_ID），用于检测镜像克隆 */
    suspend fun saveWindowIndexWithTag(index: Int, deviceTag: String) {
        context.dataStore.edit {
            it[KEY_WINDOW_INDEX] = index
            it[KEY_WINDOW_DEVICE_TAG] = deviceTag
        }
    }

    /** 一次性读取保存窗口号时的设备标签，无记录返回 null */
    suspend fun getWindowDeviceTagOnce(): String? {
        return context.dataStore.data.first()[KEY_WINDOW_DEVICE_TAG]
    }

    /** 检查是否已保存登录信息 */
    suspend fun hasAuth(): Boolean {
        return !getTokenOnce().isNullOrEmpty()
    }
}
