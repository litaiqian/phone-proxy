package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.data.RegisterRequest

@Composable
fun RegisterScreen(onBack: () -> Unit) {
    var loginId by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var refCode by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center
    ) {
        Text("注册养猫", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            message.ifEmpty { "密码需含字母+数字，至少6位" },
            fontSize = 11.sp,
            color = if (message.contains("成功")) Green else MaterialTheme.colorScheme.tertiary
        )
        Spacer(modifier = Modifier.height(16.dp))

        OutlinedTextField(value = loginId, onValueChange = { loginId = it }, label = { Text("手机号/用户名") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedTextField(value = password, onValueChange = { password = it }, label = { Text("密码（字母+数字）") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedTextField(value = refCode, onValueChange = { refCode = it }, label = { Text("推荐码（选填）") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Spacer(modifier = Modifier.height(16.dp))

        Button(
            onClick = {
                if (loginId.isBlank() || password.isBlank()) { message = "请填写完整"; return@Button }
                val hasLetter = password.any { it.isLetter() }
                val hasDigit = password.any { it.isDigit() }
                if (password.length < 6 || !hasLetter || !hasDigit) { message = "密码至少6位，需含字母和数字"; return@Button }
                loading = true
                scope.launch {
                    try {
                        val resp = ApiClient.service.register(RegisterRequest(loginId, password, refCode))
                        message = if (resp.ok == true) "注册成功！请登录" else (resp.error ?: "注册失败")
                        if (resp.ok == true) {
                            kotlinx.coroutines.delay(1500)
                            onBack()
                        }
                    } catch (e: Exception) { message = "网络错误: ${e.message}" }
                    loading = false
                }
            },
            enabled = !loading,
            modifier = Modifier.fillMaxWidth().height(44.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
        ) { Text(if (loading) "注册中…" else "注册") }
        Spacer(modifier = Modifier.height(8.dp))
        TextButton(onClick = onBack) { Text("← 返回登录") }
    }
}
