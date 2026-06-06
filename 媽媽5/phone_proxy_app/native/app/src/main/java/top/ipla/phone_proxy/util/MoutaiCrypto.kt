package top.ipla.phone_proxy.util

import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec
import kotlin.random.Random

/**
 * i茅台 加密/签名完整链 — 纯 Kotlin 实现，零第三方依赖
 *
 * 对应 Python crypto.py + demo.py 中的全部加密逻辑：
 *   - MurmurHash3 x64 128-bit
 *   - SM4-CBC / SM4-ECB（国密，手搓）
 *   - AES-CBC / PKCS7Padding
 *   - MD5（标准 + 不补零 APP 版本）
 *   - XOR 流加密（MtCrypUtil）
 *   - MT-V / MT-K 签名对
 *   - actParam 加密（AES → Base64）
 *   - Content-Web-Bb / Content-Hh-Bb / Sdk-Ver-Bb（瑞数 BotShield H5）
 *   - H5 did / startId / _bs_device_id / _d_u cookie
 *   - Bangcle Content-Info-Bb
 *
 * 使用方式（单例）:
 *   val crypto = MoutaiCrypto
 *   val headers = crypto.buildRushHeaders(body, did, startId, userId, deviceId, userAgent, mtR)
 */
object MoutaiCrypto {

    // ============================================================
    // 常量
    // ============================================================

    const val APP_VERSION = "1.9.7"
    private const val SDK_VERSION = "V3.5.0_20260403.1_imaotai"
    private const val DEFAULT_APP_KEY = "10001"
    // WASM 签名版本 (从浏览器 localStorage __wasm_sign_version__ 提取)
    // 瑞数CDN解密Content-Web-Bb时校验字段"140"(wasm_version), 若为空返回429
    const val WASM_VERSION = "38df6fbb539f079c4c82c64aaae89869"
    const val MT_INFO = "a3f9c2b8471de05f9b6c4e1287d5a9c1"

    private val AES_KEY = "3a79d\$e4c2169a#fbd24c583ae71c0b9".toByteArray().copyOf(32)
    private val AES_IV = "7392645081974362".toByteArray()

    // randC 字符集 (librand.so 0x55e0, 37 chars)
    private val RAND_CHARSET = "01234567890abcdefghijklmnopqrstuvwxyz".toCharArray()

    // ============================================================
    // Hex / Bytes 工具
    // ============================================================

    private fun hexToBytes(s: String): ByteArray {
        val len = s.length
        val data = ByteArray(len / 2)
        var i = 0
        while (i < len) {
            data[i / 2] = ((s[i].digitToIntOrNull(16) ?: 0 shl 4) +
                    (s[i + 1].digitToIntOrNull(16) ?: 0)).toByte()
            i += 2
        }
        return data
    }

    private fun bytesToHex(bytes: ByteArray): String {
        return bytes.joinToString("") { "%02x".format(it) }
    }

    private fun intToBytesBE(value: Int, buf: ByteArray, offset: Int) {
        buf[offset] = (value shr 24).toByte()
        buf[offset + 1] = (value shr 16).toByte()
        buf[offset + 2] = (value shr 8).toByte()
        buf[offset + 3] = value.toByte()
    }

    private fun bytesToIntBE(buf: ByteArray, offset: Int): Int {
        return ((buf[offset].toInt() and 0xFF) shl 24) or
                ((buf[offset + 1].toInt() and 0xFF) shl 16) or
                ((buf[offset + 2].toInt() and 0xFF) shl 8) or
                (buf[offset + 3].toInt() and 0xFF)
    }

    private fun Byte.toUnsigned(): Int = this.toInt() and 0xFF

    // ============================================================
    // 1. SM4 国密算法（手搓，对应 crypto.py SM4 实现）
    // ============================================================

    private val SM4_SBOX = intArrayOf(
        214, 144, 233, 254, 204, 225, 61, 183, 22, 182, 20, 194, 40, 251, 44, 5,
        43, 103, 154, 118, 42, 190, 4, 195, 170, 68, 19, 38, 73, 134, 6, 153,
        156, 66, 80, 244, 145, 239, 152, 122, 51, 84, 11, 67, 237, 207, 172, 98,
        228, 179, 28, 169, 201, 8, 232, 149, 128, 223, 148, 250, 117, 143, 63, 166,
        71, 7, 167, 252, 243, 115, 23, 186, 131, 89, 60, 25, 230, 133, 79, 168,
        104, 107, 129, 178, 113, 100, 218, 139, 248, 235, 15, 75, 112, 86, 157, 53,
        30, 36, 14, 94, 99, 88, 209, 162, 37, 34, 124, 59, 1, 33, 120, 135,
        212, 0, 70, 87, 159, 211, 39, 82, 76, 54, 2, 231, 160, 196, 200, 158,
        234, 191, 138, 210, 64, 199, 56, 181, 163, 247, 242, 206, 249, 97, 21, 161,
        224, 174, 93, 164, 155, 52, 26, 85, 173, 147, 50, 48, 245, 140, 177, 227,
        29, 246, 226, 46, 130, 102, 202, 96, 192, 41, 35, 171, 13, 83, 78, 111,
        213, 219, 55, 69, 222, 253, 142, 47, 3, 255, 106, 114, 109, 108, 91, 81,
        141, 27, 175, 146, 187, 221, 188, 127, 17, 217, 92, 65, 31, 16, 90, 216,
        10, 193, 49, 136, 165, 205, 123, 189, 45, 116, 208, 18, 184, 229, 180, 176,
        137, 105, 151, 74, 12, 150, 119, 126, 101, 185, 241, 9, 197, 110, 198, 132,
        24, 240, 125, 236, 58, 220, 77, 32, 121, 238, 95, 62, 215, 203, 57, 72
    )

    private val SM4_CK = intArrayOf(
        462357, 472066609, 943670861, 1415275113, 1886879365, 2358483617.toInt(),
        2830087869.toInt(), 3301692121.toInt(), 3773296373.toInt(), 4228057617.toInt(),
        404694573, 876298825,
        1347903077, 1819507329, 2291111581.toInt(), 2762715833.toInt(), 3234320085.toInt(), 3705924337.toInt(),
        4177462797.toInt(), 337322537, 808926789, 1280531041, 1752135293, 2223739545.toInt(),
        2695343797.toInt(), 3166948049.toInt(), 3638552301.toInt(), 4110090761.toInt(),
        269950501, 741554753,
        1213159005, 1684763257
    )

    private val SM4_FK = intArrayOf(
        0xA3B1BAC6.toInt(), 0x56AA3350.toInt(), 0x677D9197.toInt(), 0xB27022DC.toInt()
    )

    private fun sm4Rotl(x: Int, n: Int): Int =
        ((x shl (n and 31)) or (x ushr (32 - (n and 31))))

    private fun sm4SboxTransform(x: Int): Int =
        (((SM4_SBOX[(x shr 24) and 0xFF]) shl 24) or
         ((SM4_SBOX[(x shr 16) and 0xFF]) shl 16) or
         ((SM4_SBOX[(x shr 8) and 0xFF]) shl 8) or
         (SM4_SBOX[x and 0xFF]))

    private fun sm4TTransform(x: Int): Int {
        val b = sm4SboxTransform(x)
        return b xor sm4Rotl(b, 2) xor sm4Rotl(b, 10) xor sm4Rotl(b, 18) xor sm4Rotl(b, 24)
    }

    private fun sm4TPrime(x: Int): Int {
        val b = sm4SboxTransform(x)
        return b xor sm4Rotl(b, 13) xor sm4Rotl(b, 23)
    }

    private fun sm4RoundKeys(keyBytes: ByteArray, isEncrypt: Boolean): IntArray {
        val mk = IntArray(4)
        for (i in 0 until 4) {
            mk[i] = bytesToIntBE(keyBytes, 4 * i)
        }
        val k = IntArray(4) { mk[it] xor SM4_FK[it] }
        val rk = IntArray(32)
        for (i in 0 until 32 step 4) {
            var tmp = k[1] xor k[2] xor k[3] xor SM4_CK[i]
            rk[i] = k[0] xor sm4TPrime(tmp); k[0] = rk[i]
            tmp = k[2] xor k[3] xor k[0] xor SM4_CK[i + 1]
            rk[i + 1] = k[1] xor sm4TPrime(tmp); k[1] = rk[i + 1]
            tmp = k[3] xor k[0] xor k[1] xor SM4_CK[i + 2]
            rk[i + 2] = k[2] xor sm4TPrime(tmp); k[2] = rk[i + 2]
            tmp = k[0] xor k[1] xor k[2] xor SM4_CK[i + 3]
            rk[i + 3] = k[3] xor sm4TPrime(tmp); k[3] = rk[i + 3]
        }
        if (!isEncrypt) {
            for (i in 0 until 16) {
                val t = rk[i]; rk[i] = rk[31 - i]; rk[31 - i] = t
            }
        }
        return rk
    }

    private fun sm4OneBlock(block: ByteArray, blockOff: Int, out: ByteArray, outOff: Int, rk: IntArray) {
        val x = IntArray(4)
        for (i in 0 until 4) {
            x[i] = bytesToIntBE(block, blockOff + 4 * i)
        }
        for (i in 0 until 32 step 4) {
            x[0] = x[0] xor sm4TTransform(x[1] xor x[2] xor x[3] xor rk[i])
            x[1] = x[1] xor sm4TTransform(x[2] xor x[3] xor x[0] xor rk[i + 1])
            x[2] = x[2] xor sm4TTransform(x[3] xor x[0] xor x[1] xor rk[i + 2])
            x[3] = x[3] xor sm4TTransform(x[0] xor x[1] xor x[2] xor rk[i + 3])
        }
        for (i in 0 until 4) {
            intToBytesBE(x[3 - i], out, outOff + 4 * i)
        }
    }

    /** SM4-CBC 加密，PKCS#7 填充，返回 hex 字符串 */
    fun sm4EncryptCbc(plaintext: String, keyHex: String, ivHex: String): String {
        val keyBytes = hexToBytes(keyHex)
        val ivBytes = hexToBytes(ivHex)
        val data = plaintext.toByteArray(Charsets.UTF_8)

        // PKCS#7 padding
        val padLen = 16 - (data.size % 16)
        val padded = data + ByteArray(padLen) { padLen.toByte() }

        val rk = sm4RoundKeys(keyBytes, true)
        val result = ByteArray(padded.size)
        var prevBlock = ivBytes.copyOf()

        for (offset in padded.indices step 16) {
            val xored = ByteArray(16) { (padded[offset + it].toInt() xor prevBlock[it].toInt()).toByte() }
            sm4OneBlock(xored, 0, result, offset, rk)
            prevBlock = result.copyOfRange(offset, offset + 16)
        }
        return bytesToHex(result)
    }

    /** SM4-CBC 解密 */
    fun sm4DecryptCbc(ciphertextHex: String, keyHex: String, ivHex: String): String {
        val keyBytes = hexToBytes(keyHex)
        val ivBytes = hexToBytes(ivHex)
        val data = hexToBytes(ciphertextHex)
        val rk = sm4RoundKeys(keyBytes, false)

        val decrypted = ByteArray(data.size)
        var prevBlock = ivBytes.copyOf()

        for (offset in data.indices step 16) {
            val outBlock = ByteArray(16)
            sm4OneBlock(data, offset, outBlock, 0, rk)
            for (i in 0 until 16) {
                decrypted[offset + i] = (outBlock[i].toInt() xor prevBlock[i].toInt()).toByte()
            }
            prevBlock = data.copyOfRange(offset, offset + 16)
        }

        // PKCS#7 unpadding
        val padLen = decrypted.last().toInt() and 0xFF
        return if (padLen in 1..16) {
            decrypted.copyOf(decrypted.size - padLen).toString(Charsets.UTF_8)
        } else {
            decrypted.toString(Charsets.UTF_8)
        }
    }

    /** SM4-ECB 加密（支付用），PKCS#7 填充，返回 Base64 */
    fun sm4EncryptEcb(plaintext: String, key: String): String {
        val keyBytes = key.toByteArray(Charsets.UTF_8)
        val data = plaintext.toByteArray(Charsets.UTF_8)

        val padLen = 16 - (data.size % 16)
        val padded = data + ByteArray(padLen) { padLen.toByte() }

        val rk = sm4RoundKeys(keyBytes, true)
        val result = ByteArray(padded.size)

        for (offset in padded.indices step 16) {
            sm4OneBlock(padded, offset, result, offset, rk)
        }
        return Base64.encodeToString(result, Base64.NO_WRAP)
    }

    // ============================================================
    // 2. MurmurHash3 x64 128-bit（对应 crypto.py murmur_hash3_x64_128）
    // ============================================================

    private data class U64(val lo: Int, val hi: Int)

    private fun u64Add(a: U64, b: U64): U64 {
        var lo = (a.lo.toLong() and 0xFFFFFFFFL) + (b.lo.toLong() and 0xFFFFFFFFL)
        var hi = (a.hi.toLong() and 0xFFFFFFFFL) + (b.hi.toLong() and 0xFFFFFFFFL) + (lo shr 32)
        return U64(lo.toInt(), hi.toInt())
    }

    private fun u64Mul(a: U64, b: U64): U64 {
        val alo = a.lo.toLong() and 0xFFFFFFFFL
        val ahi = a.hi.toLong() and 0xFFFFFFFFL
        val blo = b.lo.toLong() and 0xFFFFFFFFL
        val bhi = b.hi.toLong() and 0xFFFFFFFFL
        val lo = alo * blo
        val hi = ahi * blo + alo * bhi + (lo shr 32)
        return U64(lo.toInt(), hi.toInt())
    }

    private fun u64Rotl(a: U64, n: Int): U64 {
        val shift = n and 63
        return if (shift == 32) U64(a.hi, a.lo)
        else if (shift < 32) {
            val lo = ((a.lo.toLong() and 0xFFFFFFFFL) shl shift).toInt() or
                    ((a.hi.toLong() and 0xFFFFFFFFL) ushr (32 - shift)).toInt()
            val hi = ((a.hi.toLong() and 0xFFFFFFFFL) shl shift).toInt() or
                    ((a.lo.toLong() and 0xFFFFFFFFL) ushr (32 - shift)).toInt()
            U64(lo, hi)
        } else {
            val s2 = shift - 32
            val lo = ((a.hi.toLong() and 0xFFFFFFFFL) shl s2).toInt() or
                    ((a.lo.toLong() and 0xFFFFFFFFL) ushr (32 - s2)).toInt()
            val hi = ((a.lo.toLong() and 0xFFFFFFFFL) shl s2).toInt() or
                    ((a.hi.toLong() and 0xFFFFFFFFL) ushr (32 - s2)).toInt()
            U64(lo, hi)
        }
    }

    private fun u64Xor(a: U64, b: U64): U64 = U64(a.lo xor b.lo, a.hi xor b.hi)

    private fun u64LeftShift(a: U64, b: Int): U64 = when {
        b == 0 -> a
        b < 32 -> U64(((a.hi.toLong() and 0xFFFFFFFFL) shl b ushr 32).toInt(),
                       ((a.hi.toLong() and 0xFFFFFFFFL) shl b).toInt())
        else -> U64(((a.hi.toLong() and 0xFFFFFFFFL) shl (b - 32)).toInt(), 0)
    }

    private fun u64Fmix(a: U64): U64 {
        var v = u64Xor(a, U64(0, a.lo ushr 1))
        v = u64Mul(v, U64(0xED558CCD.toInt(), 0xFF51AFD7.toInt()))
        v = u64Xor(v, U64(0, v.lo ushr 1))
        v = u64Mul(v, U64(0x1A85EC53.toInt(), 0xC4CEB9FE.toInt()))
        v = u64Xor(v, U64(0, v.lo ushr 1))
        return v
    }

    fun murmurHash3x64(data: String, seed: Int = 0, maxLen: Int = -1, salt: String = ""): String {
        val raw = if (maxLen > 0) data.take(maxLen) + salt else data + salt
        val bytes = raw.toByteArray(Charsets.UTF_8)
        val len = bytes.size
        val remainder = len % 16
        val bytesLen = len - remainder

        val c1 = U64(0x114253D5.toInt(), 0x87C37B91.toInt())
        val c2 = U64(0x2745937F.toInt(), 0x4CF5AD43.toInt())

        var h1 = U64(seed, 0)
        var h2 = U64(seed, 0)

        var d = 0
        while (d < bytesLen) {
            var k1 = U64(
                (bytes[d].toUnsigned() or (bytes[d + 1].toUnsigned() shl 8) or
                 (bytes[d + 2].toUnsigned() shl 16) or (bytes[d + 3].toUnsigned() shl 24)),
                (bytes[d + 4].toUnsigned() or (bytes[d + 5].toUnsigned() shl 8) or
                 (bytes[d + 6].toUnsigned() shl 16) or (bytes[d + 7].toUnsigned() shl 24))
            )
            var k2 = U64(
                (bytes[d + 8].toUnsigned() or (bytes[d + 9].toUnsigned() shl 8) or
                 (bytes[d + 10].toUnsigned() shl 16) or (bytes[d + 11].toUnsigned() shl 24)),
                (bytes[d + 12].toUnsigned() or (bytes[d + 13].toUnsigned() shl 8) or
                 (bytes[d + 14].toUnsigned() shl 16) or (bytes[d + 15].toUnsigned() shl 24))
            )

            k1 = u64Mul(k1, c1)
            k1 = u64Rotl(k1, 31)
            k1 = u64Mul(k1, c2)
            h1 = u64Xor(h1, k1)
            h1 = u64Rotl(h1, 27)
            h1 = u64Add(h1, h2)
            h1 = u64Add(u64Mul(h1, U64(5, 0)), U64(0x52DCE729.toInt(), 0))

            k2 = u64Mul(k2, c2)
            k2 = u64Rotl(k2, 33)
            k2 = u64Mul(k2, c1)
            h2 = u64Xor(h2, k2)
            h2 = u64Rotl(h2, 31)
            h2 = u64Add(h2, h1)
            h2 = u64Add(u64Mul(h2, U64(5, 0)), U64(0x38495AB5.toInt(), 0))

            d += 16
        }

        var k1 = U64(0, 0)
        var k2 = U64(0, 0)

        // Remainder handling (same fall-through pattern as Python)
        val rem = remainder
        val base = bytesLen
        if (rem >= 15) k2 = u64Xor(k2, u64LeftShift(U64(bytes[base + 14].toUnsigned(), 0), 48))
        if (rem >= 14) k2 = u64Xor(k2, u64LeftShift(U64(bytes[base + 13].toUnsigned(), 0), 40))
        if (rem >= 13) k2 = u64Xor(k2, u64LeftShift(U64(bytes[base + 12].toUnsigned(), 0), 32))
        if (rem >= 12) k2 = u64Xor(k2, u64LeftShift(U64(bytes[base + 11].toUnsigned(), 0), 24))
        if (rem >= 11) k2 = u64Xor(k2, u64LeftShift(U64(bytes[base + 10].toUnsigned(), 0), 16))
        if (rem >= 10) k2 = u64Xor(k2, u64LeftShift(U64(bytes[base + 9].toUnsigned(), 0), 8))
        if (rem >= 9) {
            k2 = u64Xor(k2, U64(bytes[base + 8].toUnsigned(), 0))
            k2 = u64Mul(k2, c2); k2 = u64Rotl(k2, 33); k2 = u64Mul(k2, c1)
            h2 = u64Xor(h2, k2)
        }

        if (rem >= 8) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 7].toUnsigned(), 0), 56))
        if (rem >= 7) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 6].toUnsigned(), 0), 48))
        if (rem >= 6) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 5].toUnsigned(), 0), 40))
        if (rem >= 5) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 4].toUnsigned(), 0), 32))
        if (rem >= 4) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 3].toUnsigned(), 0), 24))
        if (rem >= 3) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 2].toUnsigned(), 0), 16))
        if (rem >= 2) k1 = u64Xor(k1, u64LeftShift(U64(bytes[base + 1].toUnsigned(), 0), 8))
        if (rem >= 1) {
            k1 = u64Xor(k1, U64(bytes[base].toUnsigned(), 0))
            k1 = u64Mul(k1, c1); k1 = u64Rotl(k1, 31); k1 = u64Mul(k1, c2)
            h1 = u64Xor(h1, k1)
        }

        h1 = u64Xor(h1, U64(len, 0))
        h2 = u64Xor(h2, U64(len, 0))
        h1 = u64Add(h1, h2)
        h2 = u64Add(h2, h1)
        h1 = u64Fmix(h1)
        h2 = u64Fmix(h2)
        h1 = u64Add(h1, h2)
        h2 = u64Add(h2, h1)

        return String.format(
            "%08x%08x%08x%08x",
            h1.hi, h1.lo, h2.hi, h2.lo
        )
    }

    // ============================================================
    // 3. MD5
    // ============================================================

    fun md5Hex(text: String): String {
        val digest = MessageDigest.getInstance("MD5").digest(text.toByteArray(Charsets.UTF_8))
        return bytesToHex(digest)
    }

    /** MD5 不补零版本（APP 内部 MiscUtil.a） */
    fun md5HexNoPad(text: String): String {
        val digest = MessageDigest.getInstance("MD5").digest(text.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { (it.toInt() and 0xFF).toString(16) }
    }

    // ============================================================
    // 4. AES-CBC / PKCS7
    // ============================================================

    fun aesEncrypt(plaintext: String): String {
        val cipher = Cipher.getInstance("AES/CBC/PKCS7Padding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(AES_KEY, "AES"), IvParameterSpec(AES_IV))
        return Base64.encodeToString(cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }

    fun aesDecrypt(ciphertextB64: String): String {
        val cipher = Cipher.getInstance("AES/CBC/PKCS7Padding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(AES_KEY, "AES"), IvParameterSpec(AES_IV))
        return String(cipher.doFinal(Base64.decode(ciphertextB64, Base64.NO_WRAP)), Charsets.UTF_8)
    }

    // ============================================================
    // 5. XOR 流加密 (MtCrypUtil.b)
    // ============================================================

    fun xorEncrypt(text: String, initKey: Int = 72): String {
        var key = initKey
        return buildString {
            for (c in text) {
                key = key xor c.code
                append(key.toChar())
            }
        }
    }

    // ============================================================
    // 6. GUID / Base36 / Random ID
    // ============================================================

    fun generateGuid(): String {
        val ts = System.currentTimeMillis()
        val template = "xxxxxxxx-xxxx-xxxx-yxxx-xxxxxxxxxxxx"
        var t = ts
        val sb = StringBuilder()
        for (ch in template) {
            when (ch) {
                '-' -> sb.append('-')
                'x' -> {
                    val r = ((t + Random.nextInt(16)) % 16).toInt()
                    t /= 16
                    sb.append(Integer.toHexString(r))
                }
                'y' -> {
                    val r = ((t + Random.nextInt(16)) % 16).toInt()
                    t /= 16
                    sb.append(Integer.toHexString((r and 0x3) or 0x8))
                }
                else -> sb.append(ch)
            }
        }
        return sb.toString()
    }

    private fun intToBase36(n: Long): String = n.toString(36)

    fun getRandomId(): String {
        val parts = buildString {
            repeat(3) { append(System.currentTimeMillis().toString()) }
        }
        val template = parts.replace(".", "x").take(32).padEnd(32, 'x')
        var ts = System.currentTimeMillis()
        val sb = StringBuilder()
        for (ch in template) {
            val r = ((ts + Random.nextInt(16)) % 16).toInt()
            ts /= 16
            sb.append(if (ch == 'x') Integer.toHexString(r) else Integer.toHexString((r and 0x3) or 0x8))
        }
        return sb.toString()
    }

    // ============================================================
    // 7. 设备标识：MT-Device-ID / MT-R / MT-SN
    // ============================================================

    fun generateDeviceIdRaw(androidId: String = ""): String {
        val deviceStr = androidId.ifEmpty { java.util.UUID.randomUUID().toString() }
        return md5HexNoPad(deviceStr)
    }

    fun generateMtDeviceId(rawDeviceId: String): String {
        val xored = xorEncrypt(rawDeviceId, 72)
        return "clips_" + Base64.encodeToString(xored.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
    }

    fun generateMtR(isRooted: Boolean = false, isDebug: Boolean = false,
                    hasProxy: Boolean = false, isInjected: Boolean = false): String {
        val plaintext = "root/${if (isRooted) 1 else 0}" +
                ";debug/${if (isDebug) 1 else 0}" +
                ";proxy/${if (hasProxy) 1 else 0}" +
                ";inject/${if (isInjected) 1 else 0}"
        val xored = xorEncrypt(plaintext, 72)
        return "clips_" + Base64.encodeToString(xored.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
    }

    fun generateMtSn(): String {
        val signatureMd5 = "2f5ae2348f427a666876d7da3563a7d2"
        val xored = xorEncrypt(signatureMd5, 72)
        return "clips_" + Base64.encodeToString(xored.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
    }

    // ============================================================
    // 8. MT-V / MT-K 签名对（对应 crypto.py generate_mt_k_and_v / generate_mt_v）
    // ============================================================

    private fun generateMtV(timestamp: String, deviceId: String, extra: String = "",
                            version: String = APP_VERSION, platform: String = "android"): String {
        val combined = if (platform.lowercase() == "ios") {
            "iOS$timestamp$deviceId$extra$version"
        } else {
            "android$timestamp$deviceId$extra$version"
        }
        // 冒泡排序（与 native 层一致）
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

    data class MtKv(val mtK: String, val mtV: String)

    fun generateMtKAndV(deviceId: String, version: String = APP_VERSION): MtKv {
        val mtK = System.currentTimeMillis().toString()
        val mtV = generateMtV(mtK, deviceId, "", version)
        return MtKv(mtK, mtV)
    }

    // ============================================================
    // 9. actParam（AES 加密请求体）
    // ============================================================

    fun generateActParam(data: JSONObject): String {
        return aesEncrypt(data.toString())
    }

    fun generateActParam(data: Map<String, Any>): String {
        return aesEncrypt(JSONObject(data).toString())
    }

    /** 构建抢购 actParam
     * ★ itemCode 参数语义: HAR真机验证 actParam 的 itemCode 字段 = skuId (如"741")
     *   不是 purchaseInfoMap key (如"1001017")
     *   调用方应传 spuId (=defaultSkuId) 而非 itemCodeRush (=purchaseInfoMap key)
     */
    fun buildRushActParam(
        itemCode: String,  // ★ 传skuId, 调用方传spuId
        itemPriorityActId: String, deviceId: String,
        amount: String = "1", appUserAgent: String = "", mtr: String = ""
    ): String {
        val data = mapOf(
            "amount" to amount,
            "itemCode" to itemCode,
            "itemPriorityActId" to itemPriorityActId,
            "userInfoBaseContext" to mapOf(
                "addressLat" to "", "addressLng" to "",
                "appUserAgent" to appUserAgent, "deviceId" to deviceId, "mtr" to mtr
            ),
            "ydLogId" to "", "ydToken" to ""
        )
        return generateActParam(data)
    }

    // ============================================================
    // 10. JSON 序列化 / objectToArray / urlParamsConcat（对应 crypto.py）
    // ============================================================

    private fun jsonSerialize(obj: Any?, depth: Int = 0): String {
        val d = depth + 1
        return when (obj) {
            null -> "|-|-|"
            is String -> obj
            is Boolean -> obj.toString()
            is Number -> if (d == 1 && obj is Double && obj.isNaN()) "" else obj.toString()
            is JSONArray -> {
                if (d > 10) return "[]"
                val items = (0 until obj.length()).map { i ->
                    jsonSerialize(obj.opt(i), d)
                }.filter { it != "|-|-|" }
                JSONArray(items).toString()
            }
            is JSONObject -> {
                val keys = obj.keys().asSequence().toList().sorted()
                val parts = keys.mapNotNull { k ->
                    val v = jsonSerialize(obj.opt(k), d)
                    if (v != "|-|-|") v else null
                }
                if (parts.isEmpty()) "" else JSONArray(parts).toString()
            }
            else -> obj.toString()
        }
    }

    private fun jsonSerialize(data: String): String {
        return try {
            jsonSerialize(JSONObject(data))
        } catch (_: Exception) {
            data
        }
    }

    private fun urlParamsConcat(query: String): String {
        if (query.isEmpty()) return ""
        val pairs = query.split("&").map { part ->
            val idx = part.indexOf('=')
            if (idx > -1) part.substring(0, idx) to part.substring(idx + 1)
            else part to ""
        }.sortedBy { it.first }
        return pairs.joinToString("&") { "${it.first}=${it.second}" }
    }

    private fun objectToArray(obj: JSONObject): JSONArray {
        val keys = obj.keys().asSequence().toList().sortedBy { it.toIntOrNull() ?: it.toIntOrNull() ?: 0 }
        val arr = JSONArray()
        for (key in keys) {
            if (key == "\$1") continue
            val value = obj.opt(key)
            when (value) {
                null -> arr.put(JSONObject.NULL)
                is JSONObject -> arr.put(objectToArray(value))
                is JSONArray -> {
                    val sub = JSONArray()
                    for (i in 0 until value.length()) {
                        val item = value.opt(i)
                        sub.put(if (item is JSONObject) objectToArray(item) else item)
                    }
                    arr.put(sub)
                }
                else -> arr.put(value)
            }
        }
        return arr
    }

    // ============================================================
    // 11. SM4 密钥派生（对应 crypto.py derive_sm4_key）
    // ============================================================

    private fun deriveSm4Key(smk: String): String {
        val result = murmurHash3x64(smk + "_bsdk_", seed = 27)
        return result.lowercase().ifEmpty { "9eqaw+jthssyswpl9eqaw+jthssyswpl" }
    }

    // ============================================================
    // 12. processData（SM4 加密 Content-Web-Bb）
    // ============================================================

    data class ProcessDataResult(val encrypted: String, val smk: String, val smk1: String, val smi: String)

    private fun processData(data: Any, smkIn: String? = null, smk1In: String? = null, smiIn: String? = null): ProcessDataResult {
        val smk = smkIn ?: getRandomId()
        val smk1 = smk1In ?: deriveSm4Key(smk)
        val smi = smiIn ?: smk.map { c -> (1 xor c.digitToIntOrNull(16)!!).toString(16) }.joinToString("")

        val plaintext = when (data) {
            is String -> data
            is JSONArray -> data.toString()
            else -> data.toString()
        }
        val encrypted = sm4EncryptCbc(plaintext, smk1, smk1)
        return ProcessDataResult(smi + encrypted, smk, smk1, smi)
    }

    // ============================================================
    // 13. Content-Web-Bb / Content-Hh-Bb / Sdk-Ver-Bb 生成
    // ============================================================

    data class BotShieldHeaders(
        val contentWebBb: String,
        val sdkVerBb: String = SDK_VERSION,
        val contentHhBb: String,
        val debug: Map<String, Any> = emptyMap()
    )

    /**
     * 生成瑞数 H5 防护头（对应 crypto.py generate_content_web_bb）
     *
     * @param requestData 序列化后的请求数据 (POST: jsonSerialize, GET: urlParamsConcat)
     * @param did         设备 ID
     * @param startId     会话 ID
     * @param userId      用户 ID
     * @param isRush      是否抢购（抢购才需要 WASM 签名，这里暂留空）
     */
    fun generateContentWebBb(
        requestData: String, did: String, startId: String, userId: String = "",
        appKey: String = DEFAULT_APP_KEY, uaInfo: String = "", deviceFp: String = "0",
        hp: String = "0", wasmVersion: String = "", wasmSign: String = "",
        isRushPurchase: Boolean = false
    ): BotShieldHeaders {
        val randomId = getRandomId()
        val sign = murmurHash3x64(requestData, seed = 27, maxLen = 4096, salt = randomId)
        val timestamp = System.currentTimeMillis()  // Long, NOT toInt() — 否则1.78万亿截断为垃圾值

        val h = JSONObject().apply {
            put("101", appKey)
            put("103", did)
            put("104", startId)
            put("105", uaInfo)
            put("106", deviceFp)
            put("108", hp)
            put("109", randomId)
            put("110", sign)
            put("111", timestamp)
            put("120", JSONObject())
            put("130", userId)
            put("140", wasmVersion)
            put("141", wasmSign)
        }

        val arr = objectToArray(h)
        val processed = processData(arr)

        return BotShieldHeaders(
            contentWebBb = processed.encrypted,
            contentHhBb = sign,
            debug = mapOf(
                "smk" to processed.smk, "smk1" to processed.smk1, "smi" to processed.smi,
                "random_id" to randomId, "sign" to sign
            )
        )
    }

    /** 为 GET 请求生成 BotShield 头 */
    fun generateHeadersForGet(url: String, did: String, startId: String, userId: String = "",
                              appKey: String = DEFAULT_APP_KEY): BotShieldHeaders {
        val query = if ("?" in url) url.substringAfter("?") else ""
        val serialized = urlParamsConcat(query)
        return generateContentWebBb(serialized, did, startId, userId, appKey)
    }

    /** 为 POST 请求生成 BotShield 头 */
    fun generateHeadersForPost(body: Any, did: String, startId: String, userId: String = "",
                               appKey: String = DEFAULT_APP_KEY, isRushPurchase: Boolean = false,
                               wasmSign: String = "", wasmVersion: String = ""): BotShieldHeaders {
        val effectiveWasmVersion = if (isRushPurchase && wasmVersion.isEmpty()) WASM_VERSION else wasmVersion
        val serialized = when (body) {
            is JSONObject -> jsonSerialize(body)
            is Map<*, *> -> jsonSerialize(JSONObject(body as Map<String, Any>))
            is String -> jsonSerialize(body)
            else -> body.toString()
        }
        return generateContentWebBb(serialized, did, startId, userId, appKey,
            isRushPurchase = isRushPurchase, wasmSign = wasmSign, wasmVersion = effectiveWasmVersion)
    }

    // ============================================================
    // 14. H5 设备指纹：did / startId / _bs_device_id / _d_u
    // ============================================================

    /**
     * 生成 H5 设备 ID (did)
     * 对应 crypto.py generate_h5_did()
     *
     * 参数使用 Android 真机特征，伪装度最高
     */
    fun generateH5Did(
        userAgent: String = "",
        colorDepth: Int = 24,
        deviceMemory: Int = 8,
        pixelRatio: Float = 3.0f,
        hardwareConcurrency: Int = 8,
        platform: String = "Linux armv8l",
        timezoneOffset: Int = -480,
        webglRenderer: String = "Adreno (TM) 730",
        webglVendorRenderer: String = "Qualcomm~Adreno (TM) 730"
    ): String {
        val ua = userAgent.ifEmpty {
            "mozilla/5.0 (linux; android 14; 22081212c build/ukq1.230917.001; wv) " +
                    "applewebkit/537.36 (khtml, like gecko) version/4.0 " +
                    "chrome/122.0.6261.64 mobile safari/537.36"
        }

        // UA 去网络标识
        val uaLower = ua.lowercase()
        val uaClean = listOf("nett", "nt:", "wifi", "4g", "5g").fold(uaLower) { acc, marker ->
            if (marker in acc) {
                val idx = acc.indexOf(marker)
                acc.substring(0, idx).trimEnd()
            } else acc
        }

        val canvasFp = murmurHash3x64(Random.nextDouble().toString() + System.currentTimeMillis().toString(), seed = 27).take(16)
        val canvasTextFp = murmurHash3x64(Random.nextDouble().toString() + System.currentTimeMillis().toString() + "text", seed = 27).take(16)
        val webglFp = murmurHash3x64(Random.nextDouble().toString() + System.currentTimeMillis().toString() + "webgl", seed = 27).take(16)

        val features = listOf(
            uaClean, "", colorDepth.toString(), deviceMemory.toString(), pixelRatio.toString(),
            hardwareConcurrency.toString(), "", platform, timezoneOffset.toString(), "",
            "3;true;true", "1", "1", "0", "1", "0", "0", "0", "",
            canvasFp, canvasTextFp, "", webglFp, "", webglRenderer, webglVendorRenderer,
            "37", "20030107", "", "", "0", "0", "0", "srgb"
        ).joinToString("_")

        val guidPart = generateGuid().substring(25)
        val fpHash = murmurHash3x64(features, seed = 27)
        val fpPart = fpHash.substring(3, 19)
        val didBase = "h$guidPart$fpPart"
        val checksum = murmurHash3x64(didBase, seed = 27).substring(6, 10)
        return didBase + checksum
    }

    fun generateH5StartId(): String {
        val tsB36 = intToBase36(System.currentTimeMillis())
        val randB36 = intToBase36((Random.nextDouble() * Math.pow(36.0, 10.0)).toLong()).substring(2)
        return "${tsB36}_${randB36}_4"
    }

    fun generateBsDeviceId(did: String): String {
        val tsReversed = System.currentTimeMillis().toString().reversed()
        val didTail = if (did.length >= 4) did.takeLast(4) else did
        val guidPart = generateGuid().substring(9, 13)
        return "bid-${tsReversed}-${didTail}-${guidPart}"
    }

    /**
     * 生成 _d_u cookie（对应 crypto.py generate_d_u_cookie）
     */
    fun generateDuCookie(did: String, startId: String, userAgent: String = "",
                         domain: String = "h5.moutai519.com.cn", hp: String = "",
                         appKey: String = DEFAULT_APP_KEY): String {
        val uaShort = if (")" in userAgent) userAgent.substringBefore(")") else userAgent.take(50)
        val hpVal = hp.ifEmpty {
            murmurHash3x64(did + System.currentTimeMillis().toString(), seed = 27).take(16)
        }
        val obj = JSONObject().apply {
            put("101", appKey)
            put("103", did)
            put("105", startId)
            put("107", uaShort)
            put("109", domain)
            put("111", hpVal)
            put("113", System.currentTimeMillis())  // Long, NOT toInt()
        }
        val arr = objectToArray(obj)
        return processData(arr).encrypted
    }

    // ============================================================
    // 15. Bangcle Content-Info-Bb（邦盛设备验证）
    // ============================================================

    fun generateBangcleContentInfo(deviceId: String = ""): String {
        val raw = deviceId.ifEmpty { java.util.UUID.randomUUID().toString().replace("-", "").take(16) }
        val ts = System.currentTimeMillis().toString()
        val seed = raw + ts + Random.nextInt(10000, 99999).toString()
        val h1 = murmurHash3x64(seed, seed = 27)
        val h2 = md5Hex(seed.reversed() + raw)
        return h1 + h2
    }

    // ============================================================
    // 16. 高层封装：构建完整抢购请求
    // ============================================================

    data class RushRequest(
        val headers: Map<String, String>,
        val cookies: Map<String, String>,
        val body: Map<String, String>
    )

    /**
     * 构建完整抢购请求（含 APP 签名 + 瑞数 H5 防护）
     *
     * 对应 crypto.py build_rush_request
     */
    fun buildRushRequest(
        itemCode: String, itemPriorityActId: String, deviceId: String, cookie: String,
        amount: String = "1", appVersion: String = APP_VERSION, userAgent: String = "",
        h5Did: String = "", h5StartId: String = "", h5UserId: String = "",
        wasmVersion: String = "", sourceId: String = ""
    ): RushRequest {
        val rawDeviceId = generateDeviceIdRaw()
        val mtKv = generateMtKAndV(rawDeviceId, appVersion)
        val mtDevice = generateMtDeviceId(rawDeviceId)
        val mtR = generateMtR()
        val mtSn = generateMtSn()
        val actParam = buildRushActParam(itemCode, itemPriorityActId, mtDevice, amount, userAgent, mtR)

        val body = mapOf("actParam" to actParam)

        val did = h5Did.ifEmpty { generateH5Did() }
        val startId = h5StartId.ifEmpty { generateH5StartId() }

        val bb = generateHeadersForPost(body, did, startId, h5UserId, isRushPurchase = true)
        val duCookie = generateDuCookie(did, startId, userAgent)
        val bsDeviceId = generateBsDeviceId(did)

        // Referer 根据 itemCode 确定（对应 Python _h5_headers referer）
        val referer = getRushReferer(itemCode, sourceId)

        // Cookie 合并为单个字符串（对应 Python _h5_headers cookie_str）
        // 注意: Cookie 顺序必须与真实浏览器一致 (瑞数 CDN 可能校验顺序)
        val cookieStr = "MT-Token-Wap=$cookie; MT-Device-ID-Wap=$deviceId; " +
                "_sdk_v_=$SDK_VERSION; _bs_device_id=$bsDeviceId; _d_u=$duCookie"

        val headers = mutableMapOf(
            "Host" to "h5.moutai519.com.cn",
            "Connection" to "keep-alive",
            "x-csrf-token" to "",
            "MT-V" to mtKv.mtV,
            "MT-Device-ID" to mtDevice,
            "Content-Web-Bb" to bb.contentWebBb,
            "MT-APP-Version" to appVersion,
            "Sdk-Ver-Bb" to bb.sdkVerBb,
            "User-Agent" to userAgent,
            "content-type" to "application/json",
            "Accept" to "application/json, text/javascript, */*; q=0.01",
            "Content-Hh-Bb" to bb.contentHhBb,
            "X-Requested-With" to "XMLHttpRequest",
            "MT-Info" to MT_INFO,
            "MT-K" to mtKv.mtK,
            "Origin" to H5_BASE_URL,
            "Sec-Fetch-Site" to "same-origin",
            "Sec-Fetch-Mode" to "cors",
            "Sec-Fetch-Dest" to "empty",
            "Referer" to referer,
            "Accept-Encoding" to "gzip, deflate",
            "Accept-Language" to "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie" to cookieStr
        )

        val cookies = mapOf(
            "MT-Token-Wap" to cookie,
            "MT-Device-ID-Wap" to deviceId,
            "_sdk_v_" to SDK_VERSION,
            "_bs_device_id" to bsDeviceId,
            "_d_u" to duCookie
        )

        return RushRequest(headers, cookies, body)
    }

    // ============================================================
    // 17. Rush URL 路由 + Referer 表（对应 demo.py rush_purchase）
    // ============================================================

    private val ITEM_BRANCH_MAP = mapOf(
        // sku_id → branch
        "741" to "one", "11947" to "two", "11945" to "two",
        "11942" to "two", "1741" to "three",
        // SPU 码 → branch（手机抢购下发的是 SPU 码，比 itemCode 更稳定）
        "IMTP1000313" to "one",    // 蛇茅 500ml
        "IMTP1000006" to "one",    // 蛇茅 (xft页面)
        "IMTP1000314" to "two",    // 500ml×2
        "IMTP1000315" to "two",    // 375ml×2
        "IMTP1000316" to "three",  // 精品茅台
        "IMTP1000003" to "one",    // 蛇茅(旧SPU)
        // API 返回的 purchaseInfoMap key → branch
        "1001017" to "one",   // 蛇茅 itemCode
        "1000139" to "one"    // 蛇茅 itemCode (variant)
    )

    private val ITEM_REFERER_MAP = mapOf(
        // sku_id → Referer
        "741" to "https://h5.moutai519.com.cn/mt/item/smsp-detail?appConfig=2_1_2",
        "483" to "https://h5.moutai519.com.cn/mt/item/1000ml-detail?appConfig=2_1_2",
        "10193" to "https://h5.moutai519.com.cn/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006",
        "11335" to "https://h5.moutai519.com.cn/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006",
        "11947" to "https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2",
        "11945" to "https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2",
        "11942" to "https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2",
        "1741" to "https://h5.moutai519.com.cn/mt/item/jpmt-detail?appConfig=2_1_2",
        "10220" to "https://h5.moutai519.com.cn/mt/item/grad-detail?appConfig=2_1_2",
        // SPU 码 → Referer
        "IMTP1000313" to "https://h5.moutai519.com.cn/mt/item/smsp-detail?appConfig=2_1_2",
        "IMTP1000006" to "https://h5.moutai519.com.cn/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006",
        "IMTP1000314" to "https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2",
        "IMTP1000315" to "https://h5.moutai519.com.cn/mt/item/mm-485-detail-group?appConfig=2_1_2",
        "IMTP1000316" to "https://h5.moutai519.com.cn/mt/item/jpmt-detail?appConfig=2_1_2",
        // API purchaseInfoMap key → Referer
        "1001017" to "https://h5.moutai519.com.cn/mt/item/smsp-detail?appConfig=2_1_2",
        "1000139" to "https://h5.moutai519.com.cn/mt/item/xft-detail?appConfig=2_1_2&sourceId=IMTP1000006"
    )

    fun getRushUrl(itemCode: String, spuCode: String = ""): String {
        // SPU码更稳定（API返回的itemCode格式可能变化），优先用SPU码查找
        val lookupKey = spuCode.ifEmpty { itemCode }
        val branch = ITEM_BRANCH_MAP[lookupKey] ?: ITEM_BRANCH_MAP[itemCode]
        return if (branch != null) {
            "https://h5.moutai519.com.cn/xhr/front/trade/priority/rushPurchase/hot/branch/$branch"
        } else {
            "https://h5.moutai519.com.cn/xhr/front/trade/priority/rushPurchase"
        }
    }

    fun getRushReferer(itemCode: String, sourceId: String = "", spuCode: String = ""): String {
        val lookupKey = spuCode.ifEmpty { itemCode }
        val ref = ITEM_REFERER_MAP[lookupKey] ?: ITEM_REFERER_MAP[itemCode]
            ?: "https://h5.moutai519.com.cn/mt/item/smsp-detail?appConfig=2_1_2"
        // 对应 Python demo.py: spu_code 拼接 sourceId
        return if (sourceId.isNotEmpty()) {
            ref + "&sourceId=$sourceId"
        } else if (spuCode.isNotEmpty() && ITEM_REFERER_MAP[spuCode] == null) {
            ref + "&sourceId=$spuCode"
        } else {
            ref
        }
    }

    // ============================================================
    // 18. 支付签名：SM4-ECB + securityID（对应 demo.py pay_order + request_pay）
    // ============================================================

    /** SM4-ECB + Base64（支付用 cipherText） */
    fun paySm4Encrypt(plaintext: String, key: String): String {
        return sm4EncryptEcb(plaintext, key)
    }

    /** 支付 securityID = MD5(tn + timestamp + appSecret) */
    fun paySecurityId(channelTradeSn: String, timestamp: String, appSecret: String): String {
        return md5Hex(channelTradeSn + timestamp + appSecret)
    }

    const val MTPAY_APP_ID = "MT519ANDROID"
    const val MTPAY_APP_SECRET = "8C79446361034bd2aE98b27E153a2eA8"
    const val MTPAY_SM4_KEY = "e881E52D7932Cf00"
    const val BASE_URL = "https://app.moutai519.com.cn"
    const val H5_BASE_URL = "https://h5.moutai519.com.cn"
    const val PAY_API_URL = "https://payapi.moutai519.com.cn"
    const val BANGCLE_URL = "https://fk1.moutai519.com.cn/bangcle/api/v1/1/2"
}
