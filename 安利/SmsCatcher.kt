package com.example.smscatcher

import android.Manifest
import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.telephony.SmsMessage
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import kotlinx.coroutines.*
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : AppCompatActivity() {
    private lateinit var smsReceiver: SmsReceiver
    private lateinit var prefs: SharedPreferences

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences("sms_catcher_prefs", MODE_PRIVATE)

        val serverUrlEdit = findViewById<EditText>(R.id.serverUrlEdit)
        val tokenEdit = findViewById<EditText>(R.id.tokenEdit)
        val saveBtn = findViewById<Button>(R.id.saveBtn)

        serverUrlEdit.setText(prefs.getString("server_url", "http://192.168.1.3:5000"))
        tokenEdit.setText(prefs.getString("api_token", "your-secure-token-change-me"))

        saveBtn.setOnClickListener {
            prefs.edit()
                .putString("server_url", serverUrlEdit.text.toString().trim())
                .putString("api_token", tokenEdit.text.toString().trim())
                .apply()
            Toast.makeText(this, "设置已保存", Toast.LENGTH_SHORT).show()
        }

        val recycler = findViewById<RecyclerView>(R.id.newsRecycler)
        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = NewsAdapter(listOf(
            "今日头条：科技改变生活",
            "体育新闻：本地球队再创佳绩",
            "娱乐资讯：新片上映票房火爆"
        ))

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            requestPermissions(arrayOf(
                Manifest.permission.RECEIVE_SMS,
                Manifest.permission.READ_SMS,
                Manifest.permission.READ_PHONE_STATE,
                Manifest.permission.READ_PHONE_NUMBERS
            ), 1001)
        }

        smsReceiver = SmsReceiver(prefs)
        val filter = IntentFilter("android.provider.Telephony.SMS_RECEIVED")
        registerReceiver(smsReceiver, filter)

        Toast.makeText(this, "新闻更新中...", Toast.LENGTH_SHORT).show()
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(smsReceiver)
    }

    inner class NewsAdapter(private val news: List<String>) : RecyclerView.Adapter<NewsAdapter.ViewHolder>() {
        inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
            val textView: TextView = itemView.findViewById(android.R.id.text1)
        }
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context).inflate(android.R.layout.simple_list_item_1, parent, false)
            return ViewHolder(view)
        }
        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            holder.textView.text = news[position]
        }
        override fun getItemCount() = news.size
    }
}

class SmsReceiver(private val prefs: SharedPreferences) : BroadcastReceiver() {

    @SuppressLint("MissingPermission")
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "android.provider.Telephony.SMS_RECEIVED") return
        val bundle = intent.extras ?: return
        val pdus = bundle["pdus"] as? Array<*> ?: return
        for (pdu in pdus) {
            val sms = SmsMessage.createFromPdu(pdu as ByteArray)
            val body = sms.messageBody ?: ""

            if (!body.contains("【i茅台】")) continue

            val regex = Regex("""【i茅台】[^\d]*(\d{4,6})""")
            val code = regex.find(body)?.groupValues?.get(1) ?: ""
            if (code.isEmpty()) continue

            // 从 Intent 获取卡槽 ID（兼容所有版本，无需调用 SmsMessage.subscriptionId）
            val subId = intent.getIntExtra("subscription", -1)

            val myPhone = getDevicePhoneNumber(context, subId)

            CoroutineScope(Dispatchers.IO).launch {
                sendSmsToServer(context, myPhone, code)
            }
            abortBroadcast()
        }
    }

    @SuppressLint("MissingPermission")
    private fun getDevicePhoneNumber(context: Context, subId: Int): String {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1) {
            val subManager = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as SubscriptionManager
            val subs = subManager.activeSubscriptionInfoList ?: emptyList()
            for (sub in subs) {
                if (sub.subscriptionId == subId) {
                    return sub.number ?: ""
                }
            }
        }
        return try { tm.line1Number ?: "" } catch (e: SecurityException) { "" }
    }

    private suspend fun sendSmsToServer(context: Context, phone: String, code: String) {
        val serverUrl = prefs.getString("server_url", "")?.trimEnd('/') ?: ""
        val token = prefs.getString("api_token", "") ?: ""
        if (serverUrl.isEmpty()) {
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "请先设置服务器地址", Toast.LENGTH_SHORT).show()
            }
            return
        }
        try {
            val url = URL("$serverUrl/api/receive_sms")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("X-API-TOKEN", token)
            conn.doOutput = true
            val json = """{"phone":"$phone","code":"$code"}"""
            conn.outputStream.write(json.toByteArray())
            val responseCode = conn.responseCode
            val responseText = if (responseCode in 200..299) {
                conn.inputStream.bufferedReader().readText()
            } else {
                conn.errorStream?.bufferedReader()?.readText() ?: "未知错误"
            }
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "提交成功: $responseText", Toast.LENGTH_SHORT).show()
            }
        } catch (e: Exception) {
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "连接失败: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }
}