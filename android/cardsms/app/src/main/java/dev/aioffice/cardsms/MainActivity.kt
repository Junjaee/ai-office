package dev.aioffice.cardsms

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import dev.aioffice.cardsms.core.SettingsJson
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {
    private lateinit var store: SettingsStore
    private lateinit var log: ForwardLog

    private val pickFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri == null) return@registerForActivityResult
        val text = contentResolver.openInputStream(uri)?.bufferedReader()?.readText() ?: ""
        try {
            store.save(SettingsJson.parse(text))
            toast("설정 저장됨")
        } catch (e: IllegalArgumentException) {
            toast("설정 파일 오류: ${e.message}")
        }
        render()
    }

    private val askSms = registerForActivityResult(ActivityResultContracts.RequestPermission()) { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = SettingsStore(this)
        log = ForwardLog(this)

        findViewById<Button>(R.id.loadSettings).setOnClickListener { pickFile.launch(arrayOf("application/json", "text/plain", "*/*")) }
        findViewById<Button>(R.id.grantSms).setOnClickListener { askSms.launch(Manifest.permission.RECEIVE_SMS) }
        findViewById<Button>(R.id.battery).setOnClickListener {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        }
        findViewById<Button>(R.id.save).setOnClickListener {
            store.saveKeywordsText(findViewById<EditText>(R.id.keywords).text.toString()); toast("저장됨"); render()
        }
        findViewById<Button>(R.id.testSend).setOnClickListener {
            val s = store.load()
            if (s == null) { toast("먼저 설정 파일을 불러오세요"); return@setOnClickListener }
            val now = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA).format(Date())
            ForwardWorker.enqueue(this, "[카드문자앱 테스트]", "카드문자 전달 앱 연결 확인 $now")
            toast("테스트 전송 예약됨 — 잠시 후 기록을 새로고침하세요")
        }
        findViewById<Button>(R.id.refresh).setOnClickListener { render() }
    }

    override fun onResume() { super.onResume(); render() }

    private fun render() {
        val s = store.load()
        val smsOk = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED
        val batteryOk = (getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName)
        findViewById<TextView>(R.id.status).text = listOf(
            (if (s != null) "✓ 설정: 불러옴 (제목 ${s.subject})" else "✗ 설정: 없음 — 설정 파일을 불러오세요"),
            (if (smsOk) "✓ 문자 권한: 허용" else "✗ 문자 권한: 없음 — 허용 버튼"),
            (if (batteryOk) "✓ 배터리 최적화: 제외됨" else "✗ 배터리 최적화: 켜져 있음 — 제외해야 안 멈춤"),
        ).joinToString("\n")
        findViewById<EditText>(R.id.keywords).setText(store.keywordsText())
        findViewById<TextView>(R.id.log).text = log.lines().ifEmpty { listOf("(아직 없음)") }.joinToString("\n")
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
