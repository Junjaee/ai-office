package dev.aioffice.cardsms

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import dev.aioffice.cardsms.core.SmsFilter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {
    private lateinit var store: SettingsStore
    private lateinit var log: ForwardLog
    private lateinit var connect: GoogleConnectFlow

    private val askSms = registerForActivityResult(ActivityResultContracts.RequestPermission()) { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = SettingsStore(this)
        log = ForwardLog(this)
        connect = GoogleConnectFlow(store)

        findViewById<Button>(R.id.connect).setOnClickListener { onConnectClicked() }
        findViewById<Button>(R.id.grantSms).setOnClickListener { askSms.launch(Manifest.permission.RECEIVE_SMS) }
        findViewById<Button>(R.id.battery).setOnClickListener {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        }
        findViewById<Button>(R.id.addSender).setOnClickListener {
            val number = findViewById<EditText>(R.id.senderInput).text.toString()
            val memo = findViewById<EditText>(R.id.memoInput).text.toString()
            if (SmsFilter.normalizeNumber(number).length < 7) { toast("번호를 7자리 이상 입력하세요"); return@setOnClickListener }
            store.save(store.load().addSender(number, memo))
            findViewById<EditText>(R.id.senderInput).setText("")
            findViewById<EditText>(R.id.memoInput).setText("")
            render()
        }
        findViewById<Button>(R.id.save).setOnClickListener {
            val s = store.load().copy(
                forwardAll = findViewById<CheckBox>(R.id.forwardAll).isChecked,
                keywords = SmsFilter.parseKeywords(findViewById<EditText>(R.id.keywords).text.toString()),
            )
            store.save(s); toast("저장됨"); render()
        }
        findViewById<Button>(R.id.testSend).setOnClickListener {
            if (store.account() == null) { toast("먼저 구글 계정을 연결하세요"); return@setOnClickListener }
            val now = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA).format(Date())
            ForwardWorker.enqueue(this, ForwardWorker.TEST_SUBJECT, "카드문자 전달 앱 연결 확인 $now", "테스트")
            toast("테스트 전송 예약됨 — 잠시 후 기록을 새로고침하세요")
        }
        findViewById<Button>(R.id.refresh).setOnClickListener { render() }

        handleRedirect(intent)
    }

    /** 브라우저가 구글 되돌아오기 주소로 앱을 다시 열 때(singleTop) */
    override fun onNewIntent(intent: Intent?) { super.onNewIntent(intent); handleRedirect(intent) }

    override fun onResume() { super.onResume(); render() }

    private fun handleRedirect(intent: Intent?) {
        val uri = intent?.data?.toString() ?: return
        val handled = connect.handleRedirect(uri) { result ->
            runOnUiThread {
                result.onSuccess { store.saveAccount(it); log.add("구글연결", "연결 성공", true, it.email); toast("연결됨: ${it.email}") }
                    .onFailure { log.add("구글연결", "연결 실패", false, it.message ?: ""); toast(it.message ?: "연결 실패") }
                render()
            }
        }
        if (handled) { intent.data = null; toast("구글 응답 확인 중…") }
    }

    private fun onConnectClicked() {
        val current = store.account()
        if (current != null) {
            store.clearAccount()
            Thread { GmailClient.revoke(current.refreshToken) }.start()
            toast("연결 해제됨"); render(); return
        }
        val problem = connect.start(this)
        if (problem != null) { log.add("구글연결", "시작 실패", false, problem); toast(problem) }
        else { log.add("구글연결", "시작", true, "브라우저에서 허용 대기"); toast("브라우저에서 계정을 고르고 허용을 누르세요") }
        render()
    }

    private fun render() {
        val s = store.load()
        val account = store.account()
        val smsOk = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED
        val batteryOk = (getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName)

        findViewById<TextView>(R.id.status).text = listOf(
            "${getString(R.string.app_name)} v${BuildConfig.VERSION_NAME}",
            (if (account != null) "✓ 구글 계정: ${account.email}" else "✗ 구글 계정: 연결 안 됨 — 아래 [구글 계정 연결]"),
            (if (smsOk) "✓ 문자 권한: 허용" else "✗ 문자 권한: 없음 — [문자 권한 허용]"),
            (if (batteryOk) "✓ 배터리 최적화: 제외됨" else "✗ 배터리 최적화: 켜져 있음 — 제외해야 안 멈춤"),
            (if (s.senders.isEmpty()) "✗ 발신번호: 없음 — 카드사 번호를 추가하세요(없으면 아무것도 안 보냄)" else "✓ 발신번호: ${s.senders.size}개"),
        ).joinToString("\n")
        findViewById<Button>(R.id.connect).text = if (account != null) getString(R.string.disconnect) else getString(R.string.connect)

        val list = findViewById<LinearLayout>(R.id.senderList)
        list.removeAllViews()
        for (sender in s.senders) {
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            row.addView(TextView(this).apply {
                text = if (sender.memo.isEmpty()) sender.number else "${sender.number}  ${sender.memo}"
                textSize = 15f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            row.addView(Button(this).apply {
                text = getString(R.string.delete)
                setOnClickListener { store.save(store.load().removeSender(sender.number)); render() }
            })
            list.addView(row)
        }
        if (s.senders.isEmpty()) list.addView(TextView(this).apply { text = "(등록된 번호 없음)" })

        findViewById<CheckBox>(R.id.forwardAll).isChecked = s.forwardAll
        findViewById<EditText>(R.id.keywords).setText(s.keywords.joinToString(", "))
        findViewById<TextView>(R.id.log).text = log.lines().ifEmpty { listOf("(아직 없음)") }.joinToString("\n")
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
