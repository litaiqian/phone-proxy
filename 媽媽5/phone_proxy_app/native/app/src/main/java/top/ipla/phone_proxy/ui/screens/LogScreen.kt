package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import top.ipla.phone_proxy.util.LogBuffer

@Composable
fun LogScreen() {
    val logs by LogBuffer.logs.collectAsState()
    val listState = rememberLazyListState()
    val clipboardManager = LocalClipboardManager.current
    var copyFeedback by remember { mutableStateOf(false) }

    // 智能跟随：用户在底部时自动滚到底部，离开底部则不跟
    LaunchedEffect(logs.size) {
        if (logs.isNotEmpty()) {
            val layoutInfo = listState.layoutInfo
            val lastVisible = layoutInfo.visibleItemsInfo.lastOrNull()
            val atBottom = lastVisible != null && lastVisible.index == logs.size - 1
            if (atBottom) {
                listState.animateScrollToItem(logs.size - 1)
            }
        }
    }

    // 复制反馈2秒后自动消失
    LaunchedEffect(copyFeedback) {
        if (copyFeedback) {
            delay(2000)
            copyFeedback = false
        }
    }

    Column(modifier = Modifier.fillMaxSize().background(Color(0xFF1A1A2E))) {
        // 顶部工具栏
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "📋 实时日志 (${logs.size})",
                    fontSize = 14.sp,
                    color = Color(0xFFFFA000)
                )
                if (copyFeedback) {
                    Text(
                        "  ✅ 已复制",
                        fontSize = 12.sp,
                        color = Color(0xFF4CAF50)
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = {
                    if (logs.isNotEmpty()) {
                        val allLogs = logs.joinToString("\n")
                        clipboardManager.setText(AnnotatedString(allLogs))
                        copyFeedback = true
                    }
                }) {
                    Text("📋 复制全部", fontSize = 12.sp, color = Color(0xFF4CAF50))
                }
                TextButton(onClick = { LogBuffer.clear() }) {
                    Text("清空", fontSize = 12.sp, color = Color(0xFF64B5F6))
                }
            }
        }
        HorizontalDivider(color = Color(0xFFFFA000).copy(alpha = 0.2f))

        if (logs.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("⏳", fontSize = 32.sp)
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        "等待日志…\n心跳 / 抢购 / WebSocket 消息会实时显示",
                        fontSize = 12.sp,
                        color = Color(0xFF616161),
                        lineHeight = 18.sp
                    )
                }
            }
        } else {
            SelectionContainer {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize().padding(horizontal = 4.dp)
                ) {
                    items(logs) { line ->
                        val color = when {
                            line.contains("ERROR") || line.contains("❌") || line.contains("失败") ||
                            line.contains("异常") || line.contains("💥") -> Color(0xFFFF5252)
                            line.contains("✅") || line.contains("成功") || line.contains("2000") ||
                            line.contains("🏆") -> Color(0xFF4CAF50)
                            line.contains("📲") || line.contains("📊") || line.contains("💳") ||
                            line.contains("🔵") || line.contains("🟢") || line.contains("🔴") -> Color(0xFF03A9F4)
                            line.contains("⚠️") || line.contains("⏳") || line.contains("暂停") ||
                            line.contains("WARN") -> Color(0xFFFFA000)
                            line.contains("🔄") || line.contains("转链") || line.contains("预热") -> Color(0xFFCE93D8)
                            line.contains("❤️") || line.contains("心跳") || line.contains("HB") -> Color(0xFF80CBC4)
                            line.contains("⚡") || line.contains("IP") || line.contains("CDN") -> Color(0xFFFFAB40)
                            line.contains("📋") || line.contains("📦") || line.contains("DEBUG") -> Color(0xFF90A4AE)
                            line.contains("[MT]") -> Color(0xFFFF6D00)
                            else -> Color(0xFF78909C)
                        }
                        Text(
                            text = line,
                            fontSize = 9.5.sp,
                            fontFamily = FontFamily.Monospace,
                            color = color,
                            modifier = Modifier.padding(vertical = 1.dp, horizontal = 4.dp),
                            lineHeight = 13.sp
                        )
                    }
                }
            }
        }
    }
}
