package top.ipla.phone_proxy.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.launch
import top.ipla.phone_proxy.data.*
import top.ipla.phone_proxy.ui.theme.*

// 筛选类型
private enum class FilterType { WHITE, BLACK, WON, PAID, UNPAID }

private fun toggleFilter(current: Set<FilterType>, filter: FilterType): Set<FilterType> {
    return if (filter in current) current - filter else current + filter
}

@Composable
fun TeamScreen() {
    var accounts by remember { mutableStateOf<List<BindAccount>>(emptyList()) }
    var teams by remember { mutableStateOf<List<TeamInfo>>(emptyList()) }
    var selectedTeamId by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var statusMsg by remember { mutableStateOf("") }

    // 活跃的筛选条件集
    var activeFilters by remember { mutableStateOf<Set<FilterType>>(emptySet()) }

    // 展开的账号（点击中奖未付款卡片展示支付链接）
    var expandedPhone by remember { mutableStateOf("") }
    val context = LocalContext.current

    // 统计数据
    var statAccount by remember { mutableIntStateOf(0) }
    var statWhite by remember { mutableIntStateOf(0) }
    var statBlack by remember { mutableIntStateOf(0) }
    var statWon by remember { mutableIntStateOf(0) }
    var statPaid by remember { mutableIntStateOf(0) }
    var statUnpaid by remember { mutableIntStateOf(0) }

    val scope = rememberCoroutineScope()

    fun refreshData() {
        loading = true
        statusMsg = ""
        scope.launch {
            try {
                val tr = ApiClient.service.getTeams()
                if (tr.ok != false) teams = tr.teams

                val br = ApiClient.service.getBindStatus(teamId = selectedTeamId)
                if (br.ok != false) {
                    accounts = br.accounts ?: emptyList()
                    statAccount = accounts.size
                    statWhite = accounts.count { it.accountType == "white" }
                    statBlack = accounts.count { it.accountType == "black" }
                    statWon = accounts.count { it.won }
                    statPaid = accounts.count { it.paid }
                    statUnpaid = statWon - statPaid
                }
            } catch (_: Exception) {
                statusMsg = "❌ 网络错误"
            }
            loading = false
        }
    }

    fun queryBids() {
        loading = true
        statusMsg = ""
        scope.launch {
            try {
                ApiClient.service.refreshBindLogin()
                // 重新加载数据
                val br = ApiClient.service.getBindStatus(teamId = selectedTeamId)
                if (br.ok != false) {
                    accounts = br.accounts ?: emptyList()
                    statAccount = accounts.size
                    statWhite = accounts.count { it.accountType == "white" }
                    statBlack = accounts.count { it.accountType == "black" }
                    statWon = accounts.count { it.won }
                    statPaid = accounts.count { it.paid }
                    statUnpaid = statWon - statPaid
                }
                statusMsg = "✅ 查单完成"
            } catch (_: Exception) {
                statusMsg = "❌ 网络错误"
            }
            loading = false
        }
    }

    // 按筛选条件过滤
    val displayAccounts = remember(accounts, activeFilters) {
        if (activeFilters.isEmpty()) accounts
        else accounts.filter { a ->
            activeFilters.all { f ->
                when (f) {
                    FilterType.WHITE -> a.accountType == "white"
                    FilterType.BLACK -> a.accountType == "black"
                    FilterType.WON -> a.won
                    FilterType.PAID -> a.paid
                    FilterType.UNPAID -> a.won && !a.paid
                }
            }
        }
    }

    LaunchedEffect(Unit) { refreshData() }
    LaunchedEffect(selectedTeamId) { refreshData() }

    Column(modifier = Modifier.fillMaxSize().padding(12.dp)) {
        // 标题 + 按钮
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            Text("👥 团队", fontSize = 17.sp, fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.primary, modifier = Modifier.weight(1f))
            Button(onClick = { refreshData() }, enabled = !loading,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)) {
                Text(if (loading) "⏳" else "🔄 刷新", fontSize = 12.sp)
            }
            Spacer(modifier = Modifier.width(6.dp))
            Button(onClick = { queryBids() }, enabled = !loading,
                colors = ButtonDefaults.buttonColors(containerColor = Gold)) {
                Text("🔍 查单", fontSize = 12.sp)
            }
        }
        if (statusMsg.isNotEmpty()) {
            Text(statusMsg, fontSize = 11.sp, color = if (statusMsg.startsWith("✅")) Green else Red)
        }

        Spacer(modifier = Modifier.height(6.dp))

        // 团队筛选标签
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            val isAll = selectedTeamId == 0
            Surface(shape = RoundedCornerShape(16.dp),
                color = if (isAll) MaterialTheme.colorScheme.primary else CardBg,
                modifier = Modifier.clickable { selectedTeamId = 0 }) {
                Text("全部", fontSize = 12.sp,
                    fontWeight = if (isAll) FontWeight.Bold else FontWeight.Normal,
                    color = if (isAll) Color.White else Grey,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
            }
            teams.forEach { team ->
                val sel = selectedTeamId == team.teamId
                Surface(shape = RoundedCornerShape(16.dp),
                    color = if (sel) MaterialTheme.colorScheme.primary else CardBg,
                    modifier = Modifier.clickable { selectedTeamId = team.teamId }) {
                    Text("${team.name}(${team.accountCount})", fontSize = 12.sp,
                        fontWeight = if (sel) FontWeight.Bold else FontWeight.Normal,
                        color = if (sel) Color.White else Grey,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
                }
            }
        }

        Spacer(modifier = Modifier.height(6.dp))

        // 可点击筛选的统计卡片
        Card(colors = CardDefaults.cardColors(containerColor = CardBg),
            modifier = Modifier.fillMaxWidth()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(6.dp),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                // "账号" 点击清除所有筛选
                FilterChip(activeFilters, null, null,
                    "账号", statAccount, MaterialTheme.colorScheme.primary,
                    onToggle = { activeFilters = emptySet() })
                FilterChip(activeFilters, FilterType.WHITE, FilterType.WHITE,
                    "白号", statWhite, Green,
                    onToggle = { f -> activeFilters = toggleFilter(activeFilters, f) })
                FilterChip(activeFilters, FilterType.BLACK, FilterType.BLACK,
                    "黑号", statBlack, Color(0xFF212529),
                    onToggle = { f -> activeFilters = toggleFilter(activeFilters, f) })
                FilterChip(activeFilters, FilterType.WON, FilterType.WON,
                    "中奖", statWon, Gold,
                    onToggle = { f -> activeFilters = toggleFilter(activeFilters, f) })
                FilterChip(activeFilters, FilterType.PAID, FilterType.PAID,
                    "已付", statPaid, Green,
                    onToggle = { f -> activeFilters = toggleFilter(activeFilters, f) })
                FilterChip(activeFilters, FilterType.UNPAID, FilterType.UNPAID,
                    "待付", statUnpaid, if (statUnpaid > 0) Red else Grey,
                    onToggle = { f -> activeFilters = toggleFilter(activeFilters, f) })
            }
        }

        Spacer(modifier = Modifier.height(4.dp))

        if (displayAccounts.isEmpty() && !loading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无匹配账号", fontSize = 13.sp, color = Grey, textAlign = TextAlign.Center)
            }
        } else {
            LazyColumn(modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(displayAccounts) { a ->
                    val isExpanded = expandedPhone == a.phone
                    Card(
                        modifier = Modifier.fillMaxWidth().clickable {
                            expandedPhone = if (isExpanded) "" else (a.phone ?: "")
                        },
                        colors = CardDefaults.cardColors(containerColor = when {
                            a.paid -> CardBg.copy(alpha = 0.5f)
                            a.won -> Gold.copy(alpha = 0.12f)
                            a.isShared -> CardBg.copy(alpha = 0.7f)
                            else -> CardBg
                        }),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)) {
                            // 第一行：手机号 + 状态
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(a.phone ?: "***", fontSize = 13.sp,
                                    fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                                val (st, sc) = when (a.loginStatus) {
                                    "success" -> if (a.accountType == "black") "黑号" to Color(0xFF212529)
                                    else "正常" to Green
                                    "offline" -> "掉线" to Gold
                                    else -> "未登录" to Red
                                }
                                Surface(shape = RoundedCornerShape(10.dp),
                                    color = sc.copy(alpha = 0.15f)) {
                                    Text(st, fontSize = 11.sp, color = sc,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp))
                                }
                            }
                            // 第二行：中奖结果 + 支付结果
                            Row(modifier = Modifier.padding(top = 2.dp)) {
                                val bidText = when {
                                    a.paid -> "🏆 中奖 | 💳 已付款"
                                    a.won -> "🏆 中奖 | ⏳ 待付款 ${if (a.payUrl.isNotEmpty() || a.payUrlAlipay.isNotEmpty() || a.payUrlWechat.isNotEmpty()) "👇 点击查看支付" else ""}"
                                    a.bidResult.isNotEmpty() -> "📋 ${a.bidResult}"
                                    else -> "📋 暂无结果"
                                }
                                Text(bidText, fontSize = 11.sp,
                                    color = when {
                                        a.paid -> Green
                                        a.won -> Gold
                                        else -> Grey
                                    })
                            }
                            // 共享来源
                            if (a.isShared && a.ownerName.isNotEmpty()) {
                                Text("来自 ${a.ownerName}", fontSize = 10.sp,
                                    color = Gold, modifier = Modifier.padding(top = 1.dp))
                            }
                            // 展开支付链接
                            if (isExpanded && a.won && !a.paid) {
                                Spacer(modifier = Modifier.height(6.dp))
                                Divider(color = Gold.copy(alpha = 0.3f))
                                Spacer(modifier = Modifier.height(4.dp))
                                Text("💳 选择支付方式：", fontSize = 11.sp,
                                    fontWeight = FontWeight.Medium, color = Gold)
                                Row(
                                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                                ) {
                                    if (a.payUrl.isNotEmpty()) {
                                        PayButton("云闪付", Red, a.payUrl, context)
                                    }
                                    if (a.payUrlAlipay.isNotEmpty()) {
                                        PayButton("支付宝", Blue, a.payUrlAlipay, context)
                                    }
                                    if (a.payUrlWechat.isNotEmpty()) {
                                        PayButton("微信", Green, a.payUrlWechat, context)
                                    }
                                }
                                if (a.payUrlAlipay.isEmpty() && a.payUrlWechat.isEmpty() && a.payUrl.isEmpty()) {
                                    Text("暂无支付链接，请等待客户端上报", fontSize = 10.sp, color = Grey)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FilterChip(
    activeFilters: Set<FilterType>,
    thisFilter: FilterType?,
    filterToToggle: FilterType?,
    label: String,
    value: Int,
    color: Color,
    onToggle: ((FilterType) -> Unit)? = null
) {
    val isActive = thisFilter != null && thisFilter in activeFilters
    val bg = if (isActive) color else Color.Transparent
    val fg = if (isActive) Color.White else color

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .clickable {
                if (filterToToggle != null && onToggle != null) {
                    onToggle(filterToToggle)
                }
            }
            .then(if (isActive) Modifier.background(bg) else Modifier)
            .padding(horizontal = 6.dp, vertical = 4.dp)
    ) {
        Text(value.toString(), fontSize = 15.sp, fontWeight = FontWeight.Bold, color = fg)
        Text(label, fontSize = 10.sp, color = fg)
    }
}

@Composable
private fun PayButton(label: String, color: Color, url: String, context: android.content.Context) {
    Button(
        onClick = {
            try {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                context.startActivity(intent)
            } catch (_: Exception) {}
        },
        colors = ButtonDefaults.buttonColors(containerColor = color),
        shape = RoundedCornerShape(6.dp),
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(label, fontSize = 10.sp, color = Color.White)
    }
}
