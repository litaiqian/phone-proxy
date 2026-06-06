package top.ipla.phone_proxy

import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.navigation.compose.rememberNavController
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.service.ProxyForegroundService
import top.ipla.phone_proxy.service.MoutaiRushService
import top.ipla.phone_proxy.ui.navigation.AppNavGraph
import top.ipla.phone_proxy.ui.theme.PhoneProxyTheme
import kotlinx.coroutines.*

class MainActivity : ComponentActivity() {

    /** 自动登录是否已完成检查（true=已检查，值=是否已登录） */
    val autoLoginReady = mutableStateOf(false)
    val autoLoginSuccess = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 启动保活+心跳服务（无需登录）
        startProxyService()

        // 启动手机抢购服务（心跳拉配置+WebSocket）
        startRushService()

        // 尝试自动登录（验证/恢复 token）→ 持久化登录，重启免重新登录
        checkAutoLogin()

        setContent {
            PhoneProxyTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val navController = rememberNavController()
                    AppNavGraph(
                        navController = navController,
                        autoLoginReady = autoLoginReady,
                        autoLoginSuccess = autoLoginSuccess
                    )
                }
            }
        }
    }

    private fun checkAutoLogin() {
        CoroutineScope(Dispatchers.IO).launch {
            val token = PhoneProxyApp.instance.prefs.getTokenOnce()
            if (!token.isNullOrEmpty()) {
                ApiClient.token = token
                try {
                    // 验证 token 是否有效（用 bind_status）
                    val r = ApiClient.service.getBindStatus()
                    if (r.ok == false) {
                        // Token 已失效
                        PhoneProxyApp.instance.prefs.clearAuth()
                        ApiClient.token = ""
                        autoLoginSuccess.value = false
                    } else {
                        autoLoginSuccess.value = true
                    }
                } catch (_: Exception) {
                    // 网络不通但 token 还在 → 允许进入主页（离线模式）
                    autoLoginSuccess.value = true
                }
            } else {
                autoLoginSuccess.value = false
            }
            autoLoginReady.value = true
        }
    }

    fun startProxyService() {
        val intent = Intent(this, ProxyForegroundService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    fun startRushService() {
        val intent = Intent(this, MoutaiRushService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
}
