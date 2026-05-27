package top.ipla.phone_proxy.data

import retrofit2.http.*

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
    suspend fun getBindStatus(): BindStatusResponse

    @POST("/api/app/refresh_bind_login")
    suspend fun refreshBindLogin(): ApiResponse<Unit>

    // ==================== 订单 ====================
    @GET("/api/app/orders")
    suspend fun getOrders(): OrdersResponse
}
