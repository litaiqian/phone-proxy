package top.ipla.phone_proxy.data

import com.google.gson.annotations.SerializedName

// ==================== API 通用响应 ====================
data class ApiResponse<T>(
    val ok: Boolean?,
    val error: String? = null
)

// ==================== 登录/注册 ====================
data class LoginRequest(
    val username: String,
    val password: String,
    @SerializedName("device_id") val deviceId: String
)

data class LoginResponse(
    val ok: Boolean?,
    val error: String? = null,
    val token: String? = null,
    @SerializedName("user_id") val userId: String? = null
)

data class RegisterRequest(
    @SerializedName("login_id") val loginId: String,
    val password: String,
    @SerializedName("ref_code") val refCode: String = ""
)

data class RegisterResponse(
    val ok: Boolean?,
    val error: String? = null
)

data class ChangePwRequest(
    @SerializedName("old_password") val oldPassword: String,
    @SerializedName("new_password") val newPassword: String
)

// ==================== 猫粮/首页 ====================
data class CatFoodResponse(
    val ok: Boolean?,
    val error: String? = null,
    @SerializedName("cat_food") val catFood: Double = 0.0,
    @SerializedName("online_today") val onlineToday: Long = 0,
    @SerializedName("proxy_connected") val proxyConnected: Boolean = false,
    @SerializedName("user_id") val userId: String = "",
    @SerializedName("total_food") val totalFood: Double = 0.0
)

// ==================== 推荐 ====================
data class ReferCodeResponse(
    val ok: Boolean?,
    val error: String? = null,
    val code: String? = null
)

data class ReferralItem(
    val phone: String? = null,
    val online: Boolean? = false,
    @SerializedName("online_hours") val onlineHours: Double = 0.0,
    @SerializedName("cat_food") val catFood: Double = 0.0,
    val won: Boolean? = false
)

data class ReferralsResponse(
    val ok: Boolean?,
    val error: String? = null,
    val list: List<ReferralItem>? = null,
    @SerializedName("earned_food") val earnedFood: Double = 0.0
)

// ==================== 绑定账号 ====================
data class SmsRequest(val phone: String)
data class SmsResponse(val ok: Boolean?, val error: String? = null)

data class BindRequest(
    @SerializedName("account_phone") val accountPhone: String,
    val code: String
)

data class BindAccount(
    val phone: String? = null,
    @SerializedName("login_status") val loginStatus: String = "never",
    @SerializedName("account_type") val accountType: String = "normal"
)

data class BindStatusResponse(
    val ok: Boolean?,
    val error: String? = null,
    val accounts: List<BindAccount>? = null
)

// ==================== 订单 ====================
data class OrderItem(
    val date: String? = null,
    val won: Boolean? = false,
    val item: String? = null
)

data class OrdersResponse(
    val ok: Boolean?,
    val error: String? = null,
    val orders: List<OrderItem>? = null
)

// ==================== 团队 ====================
data class TeamMember(
    val phone: String? = null,
    val online: Boolean? = false
)

data class TeamListResponse(
    val ok: Boolean?,
    val error: String? = null,
    val list: List<TeamMember>? = null
)

data class TeamAddRequest(@SerializedName("user_id") val userId: String)

// ==================== 心跳 ====================
data class HeartbeatRequest(empty: Unit = Unit)
data class HeartbeatResponse(val ok: Boolean?, val error: String? = null)

// ==================== 中签通知 ====================
data class WonNotification(
    val type: String = "won",
    val phone: String = "",
    val masked: String = "",
    val item: String = "",
    @SerializedName("order_id") val orderId: String = ""
)
