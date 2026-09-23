package dev.aioffice.cardsms

import android.content.Context
import android.content.Intent
import android.net.Uri
import dev.aioffice.cardsms.core.GoogleOAuth
import dev.aioffice.cardsms.core.LoopbackListener

/** "구글 계정 연결" 흐름.
 *
 * 폰 안에서 잠깐 http://127.0.0.1:포트/ 를 듣는 작은 서버(LoopbackListener)를 열고 브라우저로 구글 동의 화면을 띄운다.
 * 사용자가 허용하면 브라우저가 그 주소로 되돌아오고, 서버가 코드를 받아 토큰으로 바꾼다.
 * (설치형 앱용 OAuth 클라이언트의 표준 방식 — 구글 콘솔에 폰 앱을 따로 등록할 필요가 없다)
 */
class GoogleConnectFlow(private val onResult: (Result<GoogleAccount>) -> Unit) {
    private var listener: LoopbackListener? = null

    /** 브라우저를 띄운다. 클라이언트 값이 빌드에 없으면 false */
    fun start(ctx: Context): Boolean {
        if (BuildConfig.GOOGLE_CLIENT_ID.isEmpty() || BuildConfig.GOOGLE_CLIENT_SECRET.isEmpty()) {
            onResult(Result.failure(IllegalStateException("이 설치 파일에는 구글 클라이언트 값이 없습니다(빌드 설정)")))
            return false
        }
        stop()
        val l = LoopbackListener()
        listener = l
        val verifier = GoogleOAuth.newVerifier()
        val state = GoogleOAuth.newState()
        val redirect = l.redirectUri
        Thread({ run(l, verifier, state, redirect) }, "cardsms-oauth").apply { isDaemon = true }.start()
        val url = GoogleOAuth.authUrl(BuildConfig.GOOGLE_CLIENT_ID, redirect, GoogleOAuth.challenge(verifier), state)
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }

    fun stop() {
        listener?.close()
        listener = null
    }

    private fun run(l: LoopbackListener, verifier: String, state: String, redirect: String) {
        val cb = l.await()
        if (listener === l) listener = null
        when {
            cb == null -> onResult(Result.failure(IllegalStateException("연결 대기가 끝났습니다(5분). 다시 눌러 주세요")))
            cb.error != null -> onResult(Result.failure(IllegalStateException("구글이 거부했습니다: ${cb.error}")))
            cb.state != state -> onResult(Result.failure(IllegalStateException("되돌아온 요청이 이 앱의 것이 아닙니다")))
            cb.code == null -> onResult(Result.failure(IllegalStateException("동의 코드가 없습니다")))
            else -> exchange(cb.code, verifier, redirect)
        }
    }

    private fun exchange(code: String, verifier: String, redirect: String) {
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
