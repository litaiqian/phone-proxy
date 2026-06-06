package top.ipla.phone_proxy.util

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.text.SimpleDateFormat
import java.util.*

/**
 * 全局日志缓冲区 — App 内所有模块的日志统一汇聚到此。
 * UI 层通过 [logs] StateFlow 订阅，实现实时日志窗口。
 *
 * 日志过滤策略：
 *   - 白名单标签 [HTTP/HB/INIT/CONFIG] → 全部显示
 *   - STATUS → 仅启动/已开启/错误
 *   - WS     → 仅连接/注册/错误/重要指令
 *   - RUSH   → 仅错误 + 中签/全流程成功/429触发
 *   - 其他   → 仅错误/警告
 */
object LogBuffer {
    private val dateFormat = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)
    private val _logs = MutableStateFlow<List<String>>(emptyList())
    val logs: StateFlow<List<String>> = _logs

    private const val MAX_LOGS = 3000

    // ── 白名单：这些标签全部消息都显示 ──
    private val alwaysShowTags = setOf("HTTP", "HB", "INIT", "CONFIG")

    /** 判断是否为错误/警告消息 */
    private fun isError(msg: String): Boolean {
        return msg.contains("\u274C") || msg.contains("\u26A0\uFE0F") ||
               msg.contains("失败") || msg.contains("异常") ||
               msg.contains("错误") || msg.contains("\uD83D\uDCA5") ||
               msg.contains("\u26AB")
    }

    /** STATUS 标签：仅显示启动/已开启/错误，抑制 已关闭/恢复 等常态消息 */
    private fun statusShouldShow(msg: String): Boolean {
        if (isError(msg)) return true
        if (msg.contains("状态轮询已启动")) return true
        if (msg.contains("手机抢购已开启")) return true
        return false
    }

    /** WS 标签：仅显示连接/注册/错误/重要指令，抑制普通消息推送 */
    private fun wsShouldShow(msg: String): Boolean {
        if (isError(msg)) return true
        if (msg.contains("已连接")) return true
        if (msg.contains("注册:")) return true
        if (msg.contains("\uD83D\uDE80")) return true       // 服务端直接触发抢购
        if (msg.contains("\uD83D\uDD04")) return true       // 切IP指令
        return false
    }

    /** RUSH 标签：仅错误/警告 + 关键里程碑（中签/全流程成功/429触发动作） */
    private fun rushShouldShow(msg: String): Boolean {
        if (isError(msg)) return true
        if (msg.contains("\uD83C\uDFAF") && msg.contains("抢购成功")) return true  // 中签
        if (msg.contains("\u2705") && msg.contains("全流程成功")) return true
        if (msg.contains("\u26A1") && msg.contains("429")) return true       // 429触发切IP
        if (msg.contains("\u23F9") && msg.contains("提前退出")) return true   // 异常退出
        return false
    }

    /** IP 标签：仅错误/警告 */
    private fun ipShouldShow(msg: String): Boolean {
        return isError(msg)
    }

    /** 非白名单标签：仅错误/警告放行，特定标签有额外规则 */
    private fun shouldLog(tag: String, msg: String): Boolean {
        if (tag in alwaysShowTags) return true
        if (isError(msg)) return true
        return when (tag) {
            "STATUS" -> statusShouldShow(msg)
            "WS"     -> wsShouldShow(msg)
            "RUSH"   -> rushShouldShow(msg)
            "IP"     -> ipShouldShow(msg)
            else     -> false
        }
    }

    @Synchronized
    fun append(tag: String, msg: String) {
        if (!shouldLog(tag, msg)) return
        val ts = dateFormat.format(Date())
        val line = "[$ts][$tag] $msg"
        val current = _logs.value.toMutableList()
        current.add(line)
        if (current.size > MAX_LOGS) {
            current.removeAt(0)
        }
        _logs.value = current
    }

    @Synchronized
    fun clear() {
        _logs.value = emptyList()
    }
}