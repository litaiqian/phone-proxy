package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(onLogout: () -> Unit) {
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("🏠 首页", "👥 推荐", "👨‍👩‍👧 团队", "👤 我的")

    Scaffold(
        bottomBar = {
            NavigationBar {
                tabs.forEachIndexed { index, title ->
                    NavigationBarItem(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        icon = {
                            Icon(
                                when (index) {
                                    0 -> Icons.Default.Home
                                    1 -> Icons.Default.Groups
                                    2 -> Icons.Default.PersonAdd
                                    else -> Icons.Default.Person
                                },
                                contentDescription = title
                            )
                        },
                        label = { Text(title.take(3)) }
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
            }
        }
    }
}
