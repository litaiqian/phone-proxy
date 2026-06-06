package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ipla.phone_proxy.ui.theme.Grey

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(onLogout: () -> Unit) {
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("🏠 首页", "👥 推荐", "👨‍👩‍👧 团队", "👤 我的", "📋 日志")

    Scaffold(
        bottomBar = {
            NavigationBar {
                tabs.forEachIndexed { index, title ->
                    NavigationBarItem(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        icon = {},
                        label = { Text(title, fontSize = 13.sp) }
                    )
                }
            }
        }
    ) { padding ->
        Box(modifier = Modifier.padding(padding)) {
            when (selectedTab) {
                0 -> HomeScreen()
                1 -> Text("推荐功能开发中", modifier = Modifier.padding(24.dp), color = Grey)
                2 -> TeamScreen()
                3 -> ProfileScreen(onLogout = onLogout)
                4 -> LogScreen()
            }
        }
    }
}
