package top.ipla.phone_proxy.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Accent = Color(0xFFFF6B35)
val Green = Color(0xFF4CDD7F)
val Red = Color(0xFFFF4D4D)
val Gold = Color(0xFFFFCC1A)
val White = Color.White
val Grey = Color(0xFF80808C)
val DarkGrey = Color(0xFF404047)
val CardBg = Color(0xFF26262E)
val Bg = Color(0xFF1A1A1F)

private val DarkColorScheme = darkColorScheme(
    primary = Accent,
    secondary = Green,
    tertiary = Gold,
    background = Bg,
    surface = CardBg,
    onBackground = White,
    onSurface = White,
    error = Red,
)

@Composable
fun PhoneProxyTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content
    )
}
