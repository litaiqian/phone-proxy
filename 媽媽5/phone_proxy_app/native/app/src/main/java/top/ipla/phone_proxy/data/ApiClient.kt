package top.ipla.phone_proxy.data

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import top.ipla.phone_proxy.util.LogBuffer
import java.util.concurrent.TimeUnit

object ApiClient {
    const val BASE_URL = "http://8.137.86.132:5000"
    var token: String = ""
    var deviceId: String = ""

    // 自定义日志拦截器：同时输出到 Logcat 和 App 内日志窗
    private val logBufferInterceptor = Interceptor { chain ->
        val request = chain.request()
        val startMs = System.currentTimeMillis()
        val path = request.url.encodedPath.take(120)
        LogBuffer.append("HTTP", "📤 ${request.method} $path")
        val response = chain.proceed(request)
        val elapsed = System.currentTimeMillis() - startMs
        // 检测重定向：记录 Location 头
        if (response.isRedirect) {
            val location = response.header("Location", "(无Location头)")
            LogBuffer.append("REDIRECT", "⚠️ ${response.code} ${request.method} $path → $location")
        }
        val body = response.peekBody(1024 * 1024).string().take(300)
        LogBuffer.append("HTTP", "📥 ${response.code} ${request.method} $path | ${elapsed}ms | $body")
        response
    }

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BODY
    }

    private val authInterceptor = Interceptor { chain ->
        val request = chain.request().newBuilder()
            .addHeader("Content-Type", "application/json")
            .addHeader("X-Device-Id", deviceId)
            .apply {
                if (token.isNotEmpty()) {
                    addHeader("Authorization", "Bearer $token")
                }
            }
            .build()
        chain.proceed(request)
    }

    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .followRedirects(false)  // 禁止自动重定向，避免"Too many follow-up requests"
        .addInterceptor(authInterceptor)
        .addInterceptor(logBufferInterceptor)
        .addInterceptor(loggingInterceptor)
        .build()

    private val retrofit = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(okHttpClient)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val service: ApiService = retrofit.create(ApiService::class.java)

    // ==================== 抢购客户端 API（X-API-TOKEN 鉴权） ====================
    const val RUSH_API_TOKEN = "m9Xk2vLp7Qr4Wn8YbT1cFh6Jd"

    private val rushAuthInterceptor = Interceptor { chain ->
        val request = chain.request().newBuilder()
            .addHeader("Content-Type", "application/json")
            .addHeader("X-API-TOKEN", RUSH_API_TOKEN)
            .addHeader("X-Device-Id", deviceId)
            .build()
        chain.proceed(request)
    }

    private val rushOkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .followRedirects(false)  // 禁止自动重定向
        .addInterceptor(rushAuthInterceptor)
        .addInterceptor(logBufferInterceptor)
        .addInterceptor(loggingInterceptor)
        .build()

    private val rushRetrofit = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(rushOkHttpClient)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val rushService: ApiService = rushRetrofit.create(ApiService::class.java)
}
