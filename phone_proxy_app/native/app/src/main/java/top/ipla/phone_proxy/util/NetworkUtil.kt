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

    /** 切换 IP（开关蜂窝数据） */
    fun changeIp(context: Context) {
        try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val method = cm.javaClass.getDeclaredMethod("setMobileDataEnabled", Boolean::class.javaPrimitiveType)
            method.isAccessible = true
            method.invoke(cm, false)
            Thread.sleep(3000)
            method.invoke(cm, true)
        } catch (e: Exception) {
            try {
                Runtime.getRuntime().exec(arrayOf("su", "-c", "svc data disable && sleep 3 && svc data enable"))
            } catch (_: Exception) {}
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
}
