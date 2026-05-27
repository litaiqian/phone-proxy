package top.ipla.phone_proxy.ui.screens

import android.content.Intent
import android.os.Build
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.ipla.phone_proxy.PhoneProxyApp
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.data.ChangePwRequest
import top.ipla.phone_proxy.service.ProxyForegroundService

@Composable
fun ProfileScreen(onLogout: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var showChangePw by remember { mutableStateOf(false) }
    var oldPw by remember { mutableStateOf("") }
    var newPw by remember { mutableStateOf("") }
    var pwMsg by remember { mutableStateOf("") }

    val username = remember { mutableStateOf("") }
    val userId = remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        PhoneProxyApp.instance.prefs.username.collect { username.value = it ?: "未登录" }
        PhoneProxyApp.instance.prefs.userId.collect { userId.value = it ?: "---" }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("👤 ${username.value}", fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Spacer(modifier = Modifier.height(4.dp))
        Text("ID: ${userId.value}", fontSize = 13.sp, color = Grey)
        Spacer(modifier = Modifier.height(24.dp))

        Button(onClick = { /* 查单 */ }, modifier = Modifier.fillMaxWidth().height(44.dp)) { Text("📋 查单记录") }
        Spacer(modifier = Modifier.height(8.dp))
        Button(onClick = { showChangePw = true }, modifier = Modifier.fillMaxWidth().height(44.dp)) { Text("🔑 修改密码") }

        if (showChangePw) {
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedTextField(value = oldPw, onValueChange = { oldPw = it }, label = { Text("旧密码") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(value = newPw, onValueChange = { newPw = it }, label = { Text("新密码") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(modifier = Modifier.height(4.dp))
            Text(pwMsg, fontSize = 12.sp, color = Gold)
            Button(onClick = {
                scope.launch {
                    try {
                        val r = ApiClient.service.changePassword(ChangePwRequest(oldPw, newPw))
                        pwMsg = if (r.ok != false) "修改成功" else r.error ?: "修改失败"
                    } catch (_: Exception) { pwMsg = "网络错误" }
                }
            }, modifier = Modifier.fillMaxWidth().height(40.dp), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)) {
                Text("确认修改")
            }
        }

        Spacer(modifier = Modifier.weight(1f))

        Button(onClick = {
            scope.launch { PhoneProxyApp.instance.prefs.clearAuth() }
            ApiClient.token = ""
            context.stopService(Intent(context, ProxyForegroundService::class.java))
            onLogout()
        }, modifier = Modifier.fillMaxWidth().height(44.dp), colors = ButtonDefaults.buttonColors(containerColor = Red)) {
            Text("🚪 退出登录")
        }
    }
}
