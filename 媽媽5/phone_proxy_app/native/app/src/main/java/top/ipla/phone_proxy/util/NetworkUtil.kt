package top.ipla.phone_proxy.util

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

object NetworkUtil {

    /** 强制 App 流量走蜂窝数据（4G/5G），绕过 WiFi */
    fun bindCellular(context: Context): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

        // 先找已有的蜂窝网络
        if (findAndBindCellular(cm)) {
            return true
        }

        // 尝试用反射开启蜂窝（需要系统权限/root）
        try {
            enableMobileData(context)
            // 等待网络注册
            Thread.sleep(3000)
            return findAndBindCellular(cm)
        } catch (e: Exception) {
            return false
        }
    }

    private fun findAndBindCellular(cm: ConnectivityManager): Boolean {
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network)
            if (caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true) {
                cm.bindProcessToNetwork(network)
                return true
            }
        }
        return false
    }

    private fun enableMobileData(context: Context) {
        try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val method = cm.javaClass.getDeclaredMethod("setMobileDataEnabled", Boolean::class.javaPrimitiveType)
            method.isAccessible = true
            method.invoke(cm, true)
        } catch (e: Exception) {
            // 回退：root 方式
            try {
                Runtime.getRuntime().exec(arrayOf("su", "-c", "svc data enable"))
            } catch (_: Exception) {}
        }
    }

    /** 切换 IP（多级降级，每级等待进程完成+验证 IP 确实变化）
     *  @return true=IP 已切换，false=所有方案均失败 */
    fun changeIp(context: Context, onLog: ((String) -> Unit)? = null): Boolean {
        fun log(msg: String) { onLog?.invoke(msg); android.util.Log.d("NetworkUtil", msg) }

        val oldIp = getPublicIp()
        log("切IP开始，当前IP: $oldIp")

        // === 第一梯队：飞行模式（最可靠，强制基站重连） ===

        // 方案1: Settings.Global 直写（需要 WRITE_SECURE_SETTINGS 权限）
        try {
            if (toggleAirplaneViaSettings(context)) {
                if (waitForIpChange(oldIp, onLog)) return true
            }
        } catch (e: Exception) { log("方案1 Settings.Global飞行模式: 失败 → ${e.message?.take(60)}") }

        // 方案2: cmd connectivity airplane-mode（Android 10+）
        try {
            val ok = execAndWait(arrayOf("cmd", "connectivity", "airplane-mode", "enable"), 8000)
            if (ok) {
                Thread.sleep(4000)
                execAndWait(arrayOf("cmd", "connectivity", "airplane-mode", "disable"), 8000)
                Thread.sleep(5000)
                if (waitForIpChange(oldIp, onLog)) return true
            }
        } catch (e: Exception) { log("方案2 cmd connectivity: 失败 → ${e.message?.take(60)}") }

        // 方案3: settings + am broadcast 飞行模式
        try {
            execAndWait(arrayOf("settings", "put", "global", "airplane_mode_on", "1"), 5000)
            execAndWait(arrayOf("am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true"), 5000)
            Thread.sleep(4000)
            execAndWait(arrayOf("settings", "put", "global", "airplane_mode_on", "0"), 5000)
            execAndWait(arrayOf("am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "false"), 5000)
            Thread.sleep(5000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案3 settings飞行模式: 失败 → ${e.message?.take(60)}") }

        // 方案4: Root 飞行模式
        try {
            execAndWait(arrayOf("su", "-c", "settings put global airplane_mode_on 1; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true; sleep 4; settings put global airplane_mode_on 0; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"), 15000)
            Thread.sleep(6000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案4 su飞行模式: 失败 → ${e.message?.take(60)}") }

        // === 第二梯队：直接开关蜂窝数据 ===

        // 方案5: svc data（部分 OEM 免 Root）
        try {
            execAndWait(arrayOf("svc", "data", "disable"), 5000)
            Thread.sleep(4000)
            execAndWait(arrayOf("svc", "data", "enable"), 5000)
            Thread.sleep(5000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案5 svc data: 失败 → ${e.message?.take(60)}") }

        // 方案6: Root svc data
        try {
            execAndWait(arrayOf("su", "-c", "svc data disable; sleep 4; svc data enable"), 15000)
            Thread.sleep(5000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案6 su svc data: 失败 → ${e.message?.take(60)}") }

        // === 第三梯队：网络制式切换（LTE→3G→LTE，强制换基站） ===
        try {
            forceNetworkTypeSwitch(context, onLog)
            Thread.sleep(5000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案7 网络制式切换: 失败 → ${e.message?.take(60)}") }

        // === 第四梯队：WiFi 开关（如果有WiFi连接，开关WiFi可触发蜂窝重连） ===
        try {
            execAndWait(arrayOf("cmd", "wifi", "set-wifi-enabled", "disabled"), 5000)
            Thread.sleep(2000)
            execAndWait(arrayOf("cmd", "wifi", "set-wifi-enabled", "enabled"), 5000)
            Thread.sleep(5000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案8 cmd wifi: 失败 → ${e.message?.take(60)}") }

        try {
            execAndWait(arrayOf("svc", "wifi", "disable"), 5000)
            Thread.sleep(2000)
            execAndWait(arrayOf("svc", "wifi", "enable"), 5000)
            Thread.sleep(5000)
            if (waitForIpChange(oldIp, onLog)) return true
        } catch (e: Exception) { log("方案9 svc wifi: 失败 → ${e.message?.take(60)}") }

        log("⚠️ 所有切IP方案均失败，IP未变化: $oldIp")
        return false
    }

    /** 执行命令并等待完成，返回是否成功（退出码==0） */
    private fun execAndWait(cmd: Array<String>, timeoutMs: Long): Boolean {
        return try {
            val proc = Runtime.getRuntime().exec(cmd)
            val finished = proc.waitFor(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS)
            if (!finished) {
                proc.destroyForcibly()
                false
            } else {
                proc.exitValue() == 0
            }
        } catch (e: Exception) {
            false
        }
    }

    /** 获取当前公网IP */
    private fun getPublicIp(): String {
        return try {
            val conn = java.net.URL("http://api.ipify.org").openConnection() as java.net.HttpURLConnection; conn.connectTimeout = 4000; conn.readTimeout = 4000; conn.inputStream.bufferedReader().readText().trim()
        } catch (_: Exception) { "unknown" }
    }

    /** 等待IP变化，最多等15秒 */
    private fun waitForIpChange(oldIp: String, onLog: ((String) -> Unit)?): Boolean {
        for (i in 1..6) {
            Thread.sleep(2500)
            val newIp = getPublicIp()
            if (newIp != "unknown" && newIp != oldIp) {
                onLog?.invoke("✅ IP切换成功: $oldIp → $newIp")
                return true
            }
            if (newIp != "unknown") {
                onLog?.invoke("轮询${i}/6: IP仍为 $newIp，继续等待...")
            }
        }
        return false
    }

    /** 通过 Settings.Global API 直写飞行模式（需要 WRITE_SECURE_SETTINGS） */
    private fun toggleAirplaneViaSettings(context: Context): Boolean {
        return try {
            // 开启飞行模式
            Settings.Global.putInt(context.contentResolver, Settings.Global.AIRPLANE_MODE_ON, 1)
            // 发送广播通知系统
            val intent = Intent(Intent.ACTION_AIRPLANE_MODE_CHANGED)
            intent.putExtra("state", true)
            context.sendBroadcast(intent)
            Thread.sleep(4000)

            // 关闭飞行模式
            Settings.Global.putInt(context.contentResolver, Settings.Global.AIRPLANE_MODE_ON, 0)
            val intentOff = Intent(Intent.ACTION_AIRPLANE_MODE_CHANGED)
            intentOff.putExtra("state", false)
            context.sendBroadcast(intentOff)
            true
        } catch (e: Exception) {
            false
        }
    }

    /** 网络制式切换（LTE → WCDMA/3G → LTE）无需 Root */
    private fun forceNetworkTypeSwitch(context: Context, onLog: ((String) -> Unit)?) {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as android.telephony.TelephonyManager
        try {
            // 获取当前网络制式
            val getNetType = tm.javaClass.getDeclaredMethod("getNetworkType")
            getNetType.isAccessible = true
            val currentType = getNetType.invoke(tm) as Int

            // 保存首选网络制式
            val getPreferred = tm.javaClass.getDeclaredMethod("getPreferredNetworkType", Int::class.javaPrimitiveType)
            getPreferred.isAccessible = true
            val subId = tm.javaClass.getDeclaredMethod("getSubId").invoke(tm) as? IntArray
            val prefType = try {
                getPreferred.invoke(tm, subId?.firstOrNull() ?: -1) as? Int ?: currentType
            } catch (_: Exception) { currentType }

            // 切到 3G (NETWORK_TYPE_WCDMA = 3 或 NETWORK_TYPE_UMTS = 3)
            val setPreferred = tm.javaClass.getDeclaredMethod("setPreferredNetworkType",
                Int::class.javaPrimitiveType, Int::class.javaPrimitiveType)
            setPreferred.isAccessible = true

            val threeG = 3  // NETWORK_TYPE_UMTS
            setPreferred.invoke(tm, subId?.firstOrNull() ?: 0, threeG)
            Thread.sleep(2500)

            // 切回 LTE (NETWORK_TYPE_LTE = 13 或 14)
            val lte = 13  // NETWORK_TYPE_LTE
            // 如果之前是 NR(20) 即 5G，优先切回 5G
            val target = if (prefType == 20) prefType else lte
            setPreferred.invoke(tm, subId?.firstOrNull() ?: 0, target)
            Thread.sleep(2500)
        } catch (_: Exception) {
            // 简化版: 用 setNetworkSelectionMode 触发重新搜网
            try {
                val setMode = tm.javaClass.getDeclaredMethod("setNetworkSelectionModeAutomatic", Int::class.javaPrimitiveType)
                setMode.isAccessible = true
                setMode.invoke(tm, (tm.javaClass.getDeclaredMethod("getSubId").invoke(tm) as? IntArray)?.firstOrNull() ?: 0)
                Thread.sleep(4000)
            } catch (_: Exception) { throw Exception("制式切换不可用") }
        }
    }

    /** 请求忽略电池优化 */
    fun requestBatteryOptimization(context: Context) {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(context.packageName)) return

        try {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = Uri.parse("package:${context.packageName}")
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        } catch (_: Exception) {}
    }

    // ============================================================
    // 网络变化监听：蜂窝断网→解绑，蜂窝恢复→重新绑定
    //   解决 bindProcessToNetwork 绑定到旧 Network 对象导致的永断网问题
    // ============================================================

    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    fun startNetworkMonitoring(context: Context) {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

        // 先做一次初始绑定
        bindCellular(context)

        // 注册回调，监听蜂窝网络变化
        networkCallback?.let { try { cm.unregisterNetworkCallback(it) } catch (_: Exception) {} }

        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                // 蜂窝网络恢复 → 重新绑定进程到新 Network
                try {
                    cm.bindProcessToNetwork(network)
                    android.util.Log.d("NetworkUtil", "蜂窝恢复 → 已重新绑定进程网络")
                } catch (e: Exception) {
                    android.util.Log.e("NetworkUtil", "重新绑定失败: ${e.message}")
                }
            }

            override fun onLost(network: Network) {
                // 蜂窝网络丢失 → 解除进程级绑定，让系统自动走默认路由
                try {
                    cm.bindProcessToNetwork(null)
                    android.util.Log.d("NetworkUtil", "蜂窝断网 → 已解除进程网络绑定")
                } catch (e: Exception) {
                    android.util.Log.e("NetworkUtil", "解绑失败: ${e.message}")
                }
            }
        }

        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
            .build()

        cm.registerNetworkCallback(request, callback)
        networkCallback = callback
    }

    fun stopNetworkMonitoring(context: Context) {
        networkCallback?.let {
            try {
                val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                cm.unregisterNetworkCallback(it)
            } catch (_: Exception) {}
        }
        networkCallback = null
    }
}
