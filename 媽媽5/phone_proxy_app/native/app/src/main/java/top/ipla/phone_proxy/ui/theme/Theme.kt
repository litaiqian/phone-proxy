package top.ipla.phone_proxy.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Accent = Color(0xFF03A9F4)       // 水蓝主色
val Blue = Color(0xFF1976D2)         // 支付宝蓝
val Green = Color(0xFF26A69A)        // 青绿（成功/在线）
val Red = Color(0xFFFF5252)          // 红（错误/退出）
val Gold = Color(0xFFFFA726)         // 琥珀（警告/提醒）
val White = Color.White
val Grey = Color(0xFF90A4AE)         // 蓝灰（次要文字）
val DarkGrey = Color(0xFF37474F)     // 深蓝灰（主文字）
val CardBg = Color(0xFFFFFFFF)       // 白卡
val Bg = Color(0xFFF5F9FC)           // 冰白底

private val LightColorScheme = lightColorScheme(
    primary = Accent,
    secondary = Green,
    tertiary = Gold,
    background = Bg,
    surface = CardBg,
    onBackground = DarkGrey,
    onSurface = DarkGrey,
    error = Red,
)

@Composable
fun PhoneProxyTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LightColorScheme,
        typography = Typography(),
        content = content
    )
}
