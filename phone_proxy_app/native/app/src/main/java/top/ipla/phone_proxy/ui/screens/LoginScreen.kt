package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.ipla.phone_proxy.data.ApiClient
import top.ipla.phone_proxy.data.LoginRequest

@Composable
fun LoginScreen(
    onLoginSuccess: () -> Unit,
    onNavigateToRegister: () -> Unit
) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 30.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            "🐱 养猫",
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )
        Spacer(modifier = Modifier.height(16.dp))

        Text(
            message.ifEmpty { "登录养猫，开始觅食" },
            fontSize = 14.sp,
            color = if (message.contains("失败") || message.contains("错误"))
                MaterialTheme.colorScheme.error
            else MaterialTheme.colorScheme.tertiary
        )
        Spacer(modifier = Modifier.height(16.dp))

        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            label = { Text("手机号或用户名") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("密码") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(20.dp))

        Button(
            onClick = {
                if (username.isBlank() || password.isBlank()) {
                    message = "请填写账号和密码"
                    return@Button
                }
                loading = true
                scope.launch {
                    try {
                        val resp = ApiClient.service.login(
                            LoginRequest(username, password, ApiClient.deviceId)
                        )
                        if (resp.ok == true && resp.token != null) {
                            ApiClient.token = resp.token
                            PhoneProxyApp.instance.prefs.saveAuth(
                                resp.token, username, resp.userId ?: ""
                            )
                            onLoginSuccess()
                        } else {
                            message = resp.error ?: "登录失败"
                        }
                    } catch (e: Exception) {
                        message = "网络错误: ${e.message}"
                    }
                    loading = false
                }
            },
            enabled = !loading,
            modifier = Modifier.fillMaxWidth().height(48.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
        ) {
            Text(if (loading) "登录中…" else "登录", fontSize = 16.sp)
        }
        Spacer(modifier = Modifier.height(12.dp))

        TextButton(onClick = onNavigateToRegister) {
            Text("注册新账号", color = MaterialTheme.colorScheme.onSurface)
        }
    }
}
