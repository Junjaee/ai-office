package dev.aioffice.cardsms

import android.content.Context
import android.content.Intent
import android.net.Uri
import dev.aioffice.cardsms.core.GoogleOAuth
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket

/** "구글 계정 연결" 흐름.
 *
 * 폰 안에서 잠깐 http://127.0.0.1:포트/ 를 듣는 작은 서버를 열고 브라우저로 구글 동의 화면을 띄운다.
 * 사용자가 허용하면 브라우저가 그 주소로 되돌아오고, 서버가 코드를 받아 토큰으로 바꾼다.
 * (설치형 앱용 OAuth 클라이언트의 표준 방식 — 구글 콘솔에 폰 앱을 따로 등록할 필요가 없다)
 */
class GoogleConnectFlow(private val onResult: (Result<GoogleAccount>) -> Unit) {
    private var server: ServerSocket? = null
    private var verifier = ""
    private var state = ""

    /** 브라우저를 띄운다. 클라이언트 값이 빌드에 없으면 false */
    fun start(ctx: Context): Boolean {
        if (BuildConfig.GOOGLE_CLIENT_ID.isEmpty() || BuildConfig.GOOGLE_CLIENT_SECRET.isEmpty()) {
            onResult(Result.failure(IllegalStateException("이 설치 파일에는 구글 클라이언트 값이 없습니다(빌드 설정)")))
            return false
        }
        stop()
        val ss = ServerSocket(0, 1, InetAddress.getLoopbackAddress()).apply { soTimeout = 5 * 60 * 1000 }
        server = ss
        verifier = GoogleOAuth.newVerifier()
        state = GoogleOAuth.newState()
        val redirect = "http://127.0.0.1:${ss.localPort}/"
        Thread({ serve(ss, redirect) }, "cardsms-oauth").apply { isDaemon = true }.start()
        val url = GoogleOAuth.authUrl(BuildConfig.GOOGLE_CLIENT_ID, redirect, GoogleOAuth.challenge(verifier), state)
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }

    fun stop() {
        runCatching { server?.close() }
        server = null
    }

    private fun serve(ss: ServerSocket, redirect: String) {
        var cb: GoogleOAuth.Callback? = null
        try {
            while (cb == null) {
                val sock = ss.accept()
                cb = handle(sock)
            }
        } catch (e: Exception) {
            if (server === ss) onResult(Result.failure(IllegalStateException("연결 대기가 끝났습니다(5분). 다시 눌러 주세요")))
            return
        } finally {
            if (server === ss) { runCatching { ss.close() }; server = null }
        }
        val c = cb!!
        when {
            c.error != null -> onResult(Result.failure(IllegalStateException("구글이 거부했습니다: ${c.error}")))
            c.state != state -> onResult(Result.failure(IllegalStateException("되돌아온 요청이 이 앱의 것이 아닙니다")))
            c.code == null -> onResult(Result.failure(IllegalStateException("동의 코드가 없습니다")))
            else -> exchange(c.code, redirect)
        }
    }

    /** 요청 한 건 처리. 동의 결과면 그 값을, 아니면(파비콘 등) null */
    private fun handle(sock: Socket): GoogleOAuth.Callback? = sock.use { s ->
        val reader = s.getInputStream().bufferedReader()
        val line = reader.readLine() ?: return null
        while (true) { val h = reader.readLine(); if (h.isNullOrEmpty()) break }   // 헤더는 버린다
        val cb = GoogleOAuth.parseCallback(line)
        val html = when {
            cb == null -> "<p>카드문자 전달</p>"
            cb.error != null -> "<p>연결이 취소되었습니다. 앱으로 돌아가 다시 시도하세요.</p>"
            else -> "<meta http-equiv='refresh' content='1;url=intent://connected#Intent;scheme=cardsms;package=dev.aioffice.cardsms;end'>" +
                "<p style='font-size:20px'>연결 완료! 앱으로 돌아가세요.</p><p><a href='intent://connected#Intent;scheme=cardsms;package=dev.aioffice.cardsms;end'>앱 열기</a></p>"
        }
        val body = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'></head><body>$html</body></html>"
        val bytes = body.toByteArray(Charsets.UTF_8)
        s.getOutputStream().apply {
            write(("HTTP/1.1 ${if (cb == null) "404 Not Found" else "200 OK"}\r\nContent-Type: text/html; charset=utf-8\r\n" +
                "Content-Length: ${bytes.size}\r\nConnection: close\r\n\r\n").toByteArray())
            write(bytes); flush()
        }
        cb
    }

    private fun exchange(code: String, redirect: String) {
        val (status, json) = GmailClient.exchange(code, verifier, redirect)
        val refresh = json?.optString("refresh_token", "").orEmpty()
        if (status !in 200..299 || refresh.isEmpty()) {
            onResult(Result.failure(IllegalStateException("토큰 받기 실패 (HTTP $status)")))
            return
        }
        val email = GoogleOAuth.emailFromIdToken(json?.optString("id_token", "").orEmpty()) ?: "(이메일 확인 불가)"
        onResult(Result.success(GoogleAccount(email, refresh)))
    }
}
