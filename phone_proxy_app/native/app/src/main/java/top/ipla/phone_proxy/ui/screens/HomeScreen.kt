package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import top.ipla.phone_proxy.PhoneProxyApp
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.data.CatFoodResponse

@Composable
fun HomeScreen() {
    var catFood by remember { mutableStateOf(0.0) }
    var onlineSeconds by remember { mutableStateOf(0L) }
    var connected by remember { mutableStateOf(false) }
    var userId by remember { mutableStateOf("") }
    var totalFood by remember { mutableStateOf(0.0) }

    LaunchedEffect(Unit) {
        while (true) {
            try {
                val r = ApiClient.service.getCatFood()
                if (r.ok != false) {
                    catFood = r.catFood
                    onlineSeconds = r.onlineToday
                    connected = r.proxyConnected
                    userId = r.userId
                    totalFood = r.totalFood
                }
            } catch (_: Exception) {}
            delay(3000)
        }
    }

    val h = onlineSeconds / 3600
    val m = (onlineSeconds % 3600) / 60

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(modifier = Modifier.height(20.dp))

        Text(
            if (connected) "🐱 猫咪正在觅食中…" else "🐱 猫咪睡着了，正在唤醒…",
            fontSize = 18.sp,
            color = if (connected) Green else Gold,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(12.dp))

        Text(
            "🍚 猫粮: ${"%.3f".format(catFood)} 颗",
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold,
            color = Green
        )
        Spacer(modifier = Modifier.height(8.dp))

        Text(
            "⏱ 今日觅食: ${h}时${m}分",
            fontSize = 14.sp,
            color = Grey
        )
        Spacer(modifier = Modifier.height(8.dp))

        Text(
            "用户ID: $userId\n🐾 累计猫粮: ${"%.3f".format(totalFood)}",
            fontSize = 12.sp,
            color = Grey,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(20.dp))

        Button(
            onClick = { /* 换 IP */ },
            modifier = Modifier.fillMaxWidth().height(44.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
        ) { Text("🚶 换条街逛逛") }

        Spacer(modifier = Modifier.height(8.dp))

        Button(
            onClick = { /* 看广告 */ },
            modifier = Modifier.fillMaxWidth().height(44.dp)
        ) { Text("🎬 看视频 +0.5猫粮") }
    }
}
