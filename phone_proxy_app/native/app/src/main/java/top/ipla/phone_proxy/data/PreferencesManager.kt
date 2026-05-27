package top.ipla.phone_proxy.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "app_prefs")

class PreferencesManager(private val context: Context) {

    companion object {
        private val KEY_TOKEN = stringPreferencesKey("token")
        private val KEY_USERNAME = stringPreferencesKey("username")
        private val KEY_USER_ID = stringPreferencesKey("user_id")
        private val KEY_DEVICE_ID = stringPreferencesKey("device_id")
    }

    val token: Flow<String?> = context.dataStore.data.map { it[KEY_TOKEN] }
    val username: Flow<String?> = context.dataStore.data.map { it[KEY_USERNAME] }
    val userId: Flow<String?> = context.dataStore.data.map { it[KEY_USER_ID] }
    val deviceId: Flow<String?> = context.dataStore.data.map { it[KEY_DEVICE_ID] }

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

    suspend fun getTokenOnce(): String? {
        var token: String? = null
        context.dataStore.data.collect { prefs ->
            token = prefs[KEY_TOKEN]
        }
        return token
    }
}
