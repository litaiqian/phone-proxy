package top.ipla.phone_proxy.data

import com.google.gson.annotations.SerializedName
import retrofit2.http.*

// ==================== 抢购客户端数据类 ====================

data class RushConfigResponse(
    @SerializedName("rush_hour") val rushHour: Int = 9,
    @SerializedName("rush_minute") val rushMinute: Int = 0,
    @SerializedName("rush_second") val rushSecond: Int = 0,
    @SerializedName("rush_millisecond") val rushMillisecond: Int = 0,
    @SerializedName("rush_count") val rushCount: Int = 100,
    @SerializedName("task_frequency") val taskFrequency: Int = 100,
    @SerializedName("rush_paused") val rushPaused: Int = 0,
    @SerializedName("item_code") val itemCode: String = "IMTP1000313",
    @SerializedName("act_id") val actId: String = "",
    @SerializedName("multi_open_count") val multiOpenCount: Int = 1,
    @SerializedName("phone_proxy_enabled") val phoneProxyEnabled: Boolean = false,
    @SerializedName("logged_in_count") val loggedInCount: Int = 0,
    @SerializedName("proxy_enabled") val proxyEnabled: Boolean = false
)

data class TaskInfo(
    val phone: String = "",
    val token: String = "",
    val cookie: String = "",
    @SerializedName("user_id") val userId: String = "",
    @SerializedName("mt_device_id") val mtDeviceId: String = "",
    @SerializedName("raw_device_id") val rawDeviceId: String = "",
    @SerializedName("user_agent") val userAgent: String = "",
    @SerializedName("webview_ua") val webviewUa: String = "",
    @SerializedName("mt_r") val mtR: String = "",
    @SerializedName("mt_sn") val mtSn: String = "",
    @SerializedName("h5_did") val h5Did: String = "",
    @SerializedName("h5_start_id") val h5StartId: String = "",
    @SerializedName("device_id") val deviceId: String = "",
    @SerializedName("bs_device_id") val bsDeviceId: String = "",
    val amount: Int = 1,
    @SerializedName("item_code") val itemCode: String = "IMTP1000313",
    @SerializedName("address_id") val addressId: Int = 0,
    @SerializedName("store_id") val storeId: String = "0",
    @SerializedName("device_key") val deviceKey: String = "",
    @SerializedName("proxy_ip") val proxyIp: String = ""
)

data class GetTasksRequest(
    @SerializedName("uploader_id") val uploaderId: Int = 0,
    val batch: Int = 0
)

data class GetTasksResponse(
    val status: String = "",
    val batch: Int = 0,
    val tasks: List<TaskInfo> = emptyList()
)

data class RushHeartbeatRequest(
    @SerializedName("uploader_id") val uploaderId: Int = 0,
    val batch: Int = 0,
    @SerializedName("client_uuid") val clientUuid: String = "",
    @SerializedName("task_count") val taskCount: Int = 0,
    @SerializedName("device_key") val deviceKey: String = ""
)

data class RushHeartbeatResponse(
    val status: String = "",
    @SerializedName("device_count") val deviceCount: Int = 0
)

data class ReportResultRequest(
    val phone: String = "",
    val success: Boolean = false,
    @SerializedName("order_id") val orderId: String = "",
    @SerializedName("h5_url") val h5Url: String = "",
    val error: String = "",
    @SerializedName("ip_blocked") val ipBlocked: Boolean = false,
    @SerializedName("account_black") val accountBlack: Boolean = false
)

data class ReportResultResponse(
    val status: String = "",
    @SerializedName("new_proxy_ip") val newProxyIp: String = ""
)

data class DeviceBindingsResponse(
    val status: String = "",
    val bindings: Map<String, String> = emptyMap(),
    val count: Int = 0
)

data class BindDeviceRequest(
    val phone: String = "",
    @SerializedName("device_key") val deviceKey: String = "",
    @SerializedName("device_info") val deviceInfo: Map<String, String> = emptyMap()
)

data class BindDeviceResponse(
    val status: String = "",
    @SerializedName("device_key") val deviceKey: String = "",
    @SerializedName("new_binding") val newBinding: Boolean = false,
    val message: String = ""
)

data class UploadLogRequest(
    val uuid: String = "",
    val log: String = "",
    val day: String = "",
    @SerializedName("public_ip") val publicIp: String = ""
)

data class UploadLogResponse(
    val status: String = "",
    val file: String = ""
)

// ==================== 手机抢购专用 API ====================
data class PhoneHeartbeatRequest(
    val identity: String = "",
    @SerializedName("uploader_id") val uploaderId: Int = 0,
    @SerializedName("device_info") val deviceInfo: Map<String, String> = emptyMap(),
    @SerializedName("device_tag") val deviceTag: String = "",
    @SerializedName("force_deploy") val forceDeploy: Boolean = false
)

data class AccountInfo(
    val phone: String = "",
    val token: String = "",
    val cookie: String = "",
    @SerializedName("user_id") val userId: String = "",
    @SerializedName("mt_device_id") val mtDeviceId: String = "",
    @SerializedName("raw_device_id") val rawDeviceId: String = "",
    @SerializedName("user_agent") val userAgent: String = "",
    @SerializedName("webview_ua") val webviewUa: String = "",
    @SerializedName("mt_r") val mtR: String = "",
    @SerializedName("mt_sn") val mtSn: String = "",
    @SerializedName("h5_did") val h5Did: String = "",
    @SerializedName("h5_start_id") val h5StartId: String = "",
    @SerializedName("bs_device_id") val bsDeviceId: String = "",
    val amount: Int = 1,
    @SerializedName("item_code") val itemCode: String = "IMTP1000313",
    @SerializedName("item_name") val itemName: String = "",
    @SerializedName("device_key") val deviceKey: String = "",
    @SerializedName("proxy_ip") val proxyIp: String = "",
    @SerializedName("sku_id") val skuId: String = "",
    @SerializedName("activity_id") val activityId: String = ""
)

data class PhoneRushConfig(
    @SerializedName("rush_hour") val rushHour: Int = 9,
    @SerializedName("rush_minute") val rushMinute: Int = 0,
    @SerializedName("rush_second") val rushSecond: Int = 0,
    @SerializedName("rush_millisecond") val rushMillisecond: Int = 0,
    @SerializedName("rush_count") val rushCount: Int = 100,
    @SerializedName("task_frequency") val taskFrequency: Int = 100,
    @SerializedName("rush_attempts") val rushAttempts: Int = 10000,
    @SerializedName("multi_open_count") val multiOpenCount: Int = 3,
    @SerializedName("interval_mode") val intervalMode: Int = 0,
    @SerializedName("rush_paused") val rushPaused: Int = 0,
    @SerializedName("proxy_enabled") val proxyEnabled: Boolean = false,
    @SerializedName("proxy_url") val proxyUrl: String = "",
    @SerializedName("item_code") val itemCode: String = "IMTP1000313",
    @SerializedName("act_id") val actId: String = "",
    @SerializedName("sku_id") val skuId: String = ""
)

data class PhoneHeartbeatResponse(
    @SerializedName("has_data") val hasData: Boolean = false,
    @SerializedName("phone_rush_enabled") val phoneRushEnabled: Int = 0,
    @SerializedName("rush_paused") val rushPaused: Int = 0,
    val status: String = "pending",
    @SerializedName("rush_config") val rushConfig: PhoneRushConfig? = null,
    val accounts: List<AccountInfo> = emptyList(),
    @SerializedName("multi_open_count") val multiOpenCount: Int = 3
)

data class PhoneReadyRequest(
    val identity: String = "",
    @SerializedName("uploader_id") val uploaderId: Int = 0,
    @SerializedName("verified_count") val verifiedCount: Int = 0,
    @SerializedName("deployment_id") val deploymentId: String = ""
)

data class PhoneReadyResponse(
    val status: String = "",
    val message: String = "",
    @SerializedName("deployed_count") val deployedCount: Int = 0,
    @SerializedName("online_count") val onlineCount: Int = 0
)

data class PhoneStatusResponse(
    @SerializedName("phone_rush_enabled") val phoneRushEnabled: Int = 0,
    @SerializedName("rush_paused") val rushPaused: Int = 0,
    @SerializedName("proxy_enabled") val proxyEnabled: Boolean = false,
    @SerializedName("proxy_url") val proxyUrl: String = "",
    val stats: PhoneStats? = null
)

// ==================== 空壳架构：预构建请求包 ====================

/** 服务端预构建的单个 HTTP 请求包（所有加密已在服务端完成） */
data class PrebuiltPacket(
    @SerializedName("account_index") val accountIndex: Int = 0,
    val phone: String = "",
    val url: String = "",
    val method: String = "POST",
    val headers: Map<String, String> = emptyMap(),
    val body: String = "",
    @SerializedName("raw_device_id") val rawDeviceId: String = ""  // 用于生成实时 MT-K/V
)

/** 服务端下发的预构建包集合 */
data class PrebuiltPackets(
    val type: String = "prebuilt_packets",
    @SerializedName("round_id") val roundId: String = "",
    @SerializedName("rush_time") val rushTime: String = "",       // "HH:mm:ss.SSS"
    @SerializedName("frequency_ms") val frequencyMs: Int = 100,
    @SerializedName("rush_count") val rushCount: Int = 100,
    val packets: List<PrebuiltPacket> = emptyList()
)

/** 手机转发给服务端的单次请求结果 */
data class RushRelayResponse(
    val type: String = "rush_response",
    @SerializedName("round_id") val roundId: String = "",
    @SerializedName("account_index") val accountIndex: Int = 0,
    val phone: String = "",
    @SerializedName("http_status") val httpStatus: Int = 0,
    @SerializedName("response_code") val responseCode: Int = 0,
    val body: String = "",
    @SerializedName("server_time") val serverTime: String = "",
    @SerializedName("elapsed_ms") val elapsedMs: Long = 0
)

/** 服务端下发的后续请求（组单/下单/支付） */
data class RelayRequest(
    val type: String = "relay_request",
    @SerializedName("round_id") val roundId: String = "",
    @SerializedName("account_index") val accountIndex: Int = 0,
    val phone: String = "",
    val url: String = "",
    val method: String = "POST",
    val headers: Map<String, String> = emptyMap(),
    val body: String = "",
    @SerializedName("raw_device_id") val rawDeviceId: String = ""
)

data class PhoneStats(
    @SerializedName("online_count") val onlineCount: Int = 0,
    @SerializedName("deployed_count") val deployedCount: Int = 0,
    @SerializedName("pending_count") val pendingCount: Int = 0
)

// ==================== 团队 ====================
data class TeamInfo(
    @SerializedName("team_id") val teamId: Int = 0,
    val name: String = "",
    @SerializedName("owner_name") val ownerName: String = "",
    @SerializedName("is_owner") val isOwner: Boolean = false,
    @SerializedName("account_count") val accountCount: Int = 0,
    @SerializedName("login_count") val loginCount: Int = 0,
    @SerializedName("won_count") val wonCount: Int = 0,
    @SerializedName("paid_count") val paidCount: Int = 0,
    @SerializedName("unpaid_count") val unpaidCount: Int = 0
)

data class TeamsResponse(
    val ok: Boolean?,
    val error: String? = null,
    val teams: List<TeamInfo> = emptyList(),
    @SerializedName("all_account_count") val allAccountCount: Int = 0,
    @SerializedName("all_login_count") val allLoginCount: Int = 0,
    @SerializedName("all_won_count") val allWonCount: Int = 0,
    @SerializedName("all_paid_count") val allPaidCount: Int = 0,
    @SerializedName("all_unpaid_count") val allUnpaidCount: Int = 0
)

interface ApiService {
    // ==================== 登录/注册 ====================
    @POST("/api/app/login")
    suspend fun login(@Body request: LoginRequest): LoginResponse

    @POST("/api/app/register")
    suspend fun register(@Body request: RegisterRequest): RegisterResponse

    @POST("/api/app/change_password")
    suspend fun changePassword(@Body request: ChangePwRequest): ApiResponse<Unit>

    // ==================== 首页 ====================
    @GET("/api/app/cat_food")
    suspend fun getCatFood(): CatFoodResponse

    @POST("/api/app/heartbeat")
    suspend fun heartbeat(): HeartbeatResponse

    // ==================== 推荐 ====================
    @GET("/api/app/refer_code")
    suspend fun getReferCode(): ReferCodeResponse

    @GET("/api/app/referrals")
    suspend fun getReferrals(): ReferralsResponse

    // ==================== 绑定 ====================
    @POST("/api/app/send_sms")
    suspend fun sendSms(@Body request: SmsRequest): SmsResponse

    @POST("/api/app/bind_account")
    suspend fun bindAccount(@Body request: BindRequest): ApiResponse<Unit>

    @GET("/api/app/bind_status")
    suspend fun getBindStatus(@Query("team_id") teamId: Int = 0): BindStatusResponse

    @POST("/api/app/refresh_bind_login")
    suspend fun refreshBindLogin(): ApiResponse<Unit>

    // ==================== 团队（App 只读） ====================
    @GET("/api/app/teams")
    suspend fun getTeams(): TeamsResponse

    // ==================== 订单 ====================
    @GET("/api/app/orders")
    suspend fun getOrders(): OrdersResponse

    // ==================== 抢购客户端 API ====================
    @GET("/api/client/get_config")
    suspend fun getRushConfig(@Query("uploader_id") uploaderId: Int = 0): RushConfigResponse

    @POST("/api/client/get_tasks")
    suspend fun getRushTasks(@Body request: GetTasksRequest): GetTasksResponse

    @POST("/api/client/heartbeat")
    suspend fun rushHeartbeat(@Body request: RushHeartbeatRequest): RushHeartbeatResponse

    @POST("/api/client/report_result")
    suspend fun reportRushResult(@Body request: ReportResultRequest): ReportResultResponse

    @GET("/api/client/get_device_bindings")
    suspend fun getDeviceBindings(@Query("uploader_id") uploaderId: Int = 0): DeviceBindingsResponse

    @POST("/api/client/upload_log")
    suspend fun uploadLog(@Body request: UploadLogRequest): UploadLogResponse

    @POST("/api/client/bind_device")
    suspend fun bindDevice(@Body request: BindDeviceRequest): BindDeviceResponse

    // ==================== 手机抢购（新架构） ====================
    @POST("/api/phone/heartbeat")
    suspend fun phoneHeartbeat(@Body request: PhoneHeartbeatRequest): PhoneHeartbeatResponse

    @POST("/api/phone/ready")
    suspend fun phoneReady(@Body request: PhoneReadyRequest): PhoneReadyResponse

    @GET("/api/phone/status")
    suspend fun phoneStatus(
        @Query("identity") identity: String,
        @Query("uploader_id") uploaderId: Int = 0
    ): PhoneStatusResponse
}