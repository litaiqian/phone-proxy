package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.ipla.phone_proxy.data.*
import java.time.LocalTime

@Composable
fun TeamScreen() {
    var accounts by remember { mutableStateOf<List<BindAccount>>(emptyList()) }
    var statusMsg by remember { mutableStateOf("点击刷新查看绑定状态") }
    var loading by remember { mutableStateOf(false) }
    var phone by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var bindMsg by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    val timeStatus = remember {
        val now = LocalTime.now()
        val t = now.hour * 60 + now.minute
        when {
            t in 420..1194 -> "🐱 养号中…" to Green
            t in 1195..1259 -> "⚡ 抢购窗口" to Accent
            else -> "🌙 夜间休息中…" to Gold
        }
    }

    fun refreshStatus() {
        loading = true
        scope.launch {
            try {
                val r = ApiClient.service.getBindStatus()
                if (r.ok != false) {
                    accounts = r.accounts ?: emptyList()
                    val online = accounts.count { it.loginStatus == "success" }
                    statusMsg = "📱 已绑定 ${accounts.size} 个 | 🟢 在线 $online"
                } else statusMsg = "❌ 获取状态失败"
            } catch (_: Exception) { statusMsg = "❌ 网络错误" }
            loading = false
        }
    }

    LaunchedEffect(Unit) { refreshStatus() }

    Column(modifier = Modifier.fillMaxSize().padding(12.dp)) {
        // 标题 + 刷新
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("👨‍👩‍👧 绑定管理", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, modifier = Modifier.weight(1f))
            Button(onClick = { refreshStatus() }, enabled = !loading, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)) {
                Text(if (loading) "刷新中…" else "🔄 刷新")
            }
        }
        Text(timeStatus.first, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = timeStatus.second, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp))
        Text(statusMsg, fontSize = 11.sp, color = Grey)

        Spacer(modifier = Modifier.height(8.dp))

        // 已绑定列表
        LazyColumn(modifier = Modifier.weight(0.45f)) {
            items(accounts) { a ->
                Card(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                    Row(modifier = Modifier.padding(8.dp)) {
                        Text(a.phone ?: "***", fontSize = 12.sp, modifier = Modifier.weight(0.3f))
                        val (st, sc) = when (a.loginStatus) {
                            "success" -> "正常" to Green
                            "offline" -> "掉线" to Gold
                            else -> "未登录" to Red
                        }
                        Text(st, fontSize = 12.sp, color = sc, modifier = Modifier.weight(0.22f))
                        val (tt, tc) = when (a.accountType) {
                            "white" -> "白号" to Green
                            "black" -> "黑号" to Red
                            else -> "正常" to Grey
                        }
                        Text(tt, fontSize = 12.sp, color = tc, modifier = Modifier.weight(0.18f))
                        Text(timeStatus.first, fontSize = 12.sp, color = timeStatus.second, modifier = Modifier.weight(0.3f))
                    }
                }
            }
        }

        Divider(modifier = Modifier.padding(vertical = 8.dp))

        Text("─ 绑定新号码 ─", fontSize = 11.sp, color = DarkGrey, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp))

        OutlinedTextField(value = phone, onValueChange = { phone = it }, label = { Text("目标站手机号") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Spacer(modifier = Modifier.height(6.dp))
        Row(modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(value = code, onValueChange = { code = it }, label = { Text("验证码") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
            Spacer(modifier = Modifier.width(8.dp))
            Button(onClick = {
                if (phone.length != 11) { bindMsg = "请输入11位手机号"; return@Button }
                scope.launch {
                    try { ApiClient.service.sendSms(SmsRequest(phone)); bindMsg = "✅ 验证码已发送" }
                    catch (_: Exception) { bindMsg = "❌ 发送失败" }
                }
            }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)) { Text("获取") }
        }
        Spacer(modifier = Modifier.height(4.dp))
        Text(bindMsg, fontSize = 11.sp, color = Gold)
        Spacer(modifier = Modifier.height(8.dp))
        Button(onClick = {
            if (phone.isBlank() || code.isBlank()) { bindMsg = "请填写完整"; return@Button }
            scope.launch {
                try {
                    val r = ApiClient.service.bindAccount(BindRequest(phone, code))
                    bindMsg = if (r.ok != false) { phone = ""; code = ""; refreshStatus(); "🎉 绑定成功！" }
                    else r.error ?: "绑定失败"
                } catch (_: Exception) { bindMsg = "网络错误" }
            }
        }, modifier = Modifier.fillMaxWidth().height(44.dp), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)) { Text("确认绑定") }
    }
}
