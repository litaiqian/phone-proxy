package top.ipla.phone_proxy.util

import java.security.MessageDigest
import kotlin.random.Random

/**
 * 空壳加密 — 只保留手机端必须实时生成的部分：
 *   - MT-K / MT-V 签名对（MT-K = System.currentTimeMillis()，必须发送时刻生成）
 *   - MD5（生成 MT-V 和身份验证用）
 *
 * 其余全部加密逻辑（SM4 / AES / MurmurHash / BotShield / Bangcle / actParam）
 * 已移至服务端预构建，通过 WebSocket 下发预构建请求包。
 */
object ShellCrypto {

    const val APP_VERSION = "1.9.7"

    private val RAND_CHARSET = "01234567890abcdefghijklmnopqrstuvwxyz".toCharArray()

    // ============================================================
    // MD5
    // ============================================================

    fun md5Hex(text: String): String {
        val digest = MessageDigest.getInstance("MD5").digest(text.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    // ============================================================
    // MT-K / MT-V 签名对（必须手机端实时生成）
    // ============================================================

    data class MtKv(val mtK: String, val mtV: String)

    /** 生成 MT-K（当前毫秒时间戳）和 MT-V（冒泡排序 + MD5 + 随机后缀） */
    fun generateMtKAndV(deviceId: String, version: String = APP_VERSION): MtKv {
        val mtK = System.currentTimeMillis().toString()
        val mtV = generateMtV(mtK, deviceId, "", version)
        return MtKv(mtK, mtV)
    }

    private fun generateMtV(
        timestamp: String, deviceId: String, extra: String = "",
        version: String = APP_VERSION, platform: String = "android"
    ): String {
        val combined = if (platform.lowercase() == "ios") {
            "iOS$timestamp$deviceId$extra$version"
        } else {
            "android$timestamp$deviceId$extra$version"
        }
        // 冒泡排序（与 native 层 libmt signature 一致）
        val chars = combined.toCharArray()
        val n = chars.size
        for (i in 0 until n - 1) {
            for (j in 0 until n - 1 - i) {
                if (chars[j] > chars[j + 1]) {
                    val tmp = chars[j]; chars[j] = chars[j + 1]; chars[j + 1] = tmp
                }
            }
        }
        val sorted = String(chars)
        val suffix = RAND_CHARSET[Random.nextInt(37)].toString()
        val resultMd5 = md5Hex(sorted + suffix)
        return resultMd5.take(26) + suffix
    }
}
