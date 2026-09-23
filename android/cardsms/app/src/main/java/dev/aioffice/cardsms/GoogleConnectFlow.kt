package dev.aioffice.cardsms

import android.content.Context
import android.content.Intent
import android.net.Uri
import dev.aioffice.cardsms.core.GoogleOAuth

/** "구글 계정 연결" 흐름 (안드로이드 OAuth 클라이언트 + PKCE).
 *
 * [연결] → 브라우저에 구글 동의 화면 → 허용 → 구글이 브라우저를 이 앱의 스킴으로 보냄 → 안드로이드가 앱을 열며
 * 주소를 넘김 → 코드를 토큰으로 바꿔 저장. 앱이 뒤에서 정리돼도 다시 켜지므로 PKCE 값은 저장소에 둔다.
 */
class GoogleConnectFlow(private val store: SettingsStore) {

    /** 브라우저를 띄운다. 문제가 있으면 사람에게 보여 줄 문구를 돌려준다 */
    fun start(ctx: Context): String? {
        val cid = BuildConfig.GOOGLE_ANDROID_CLIENT_ID
        val redirect = GoogleOAuth.redirectUriFor(cid)
            ?: return "이 설치 파일에는 구글 클라이언트 값이 없습니다(빌드 설정)"
        val verifier = GoogleOAuth.newVerifier()
        val state = GoogleOAuth.newState()
        store.savePending(verifier, state)
        val url = GoogleOAuth.authUrl(cid, redirect, GoogleOAuth.challenge(verifier), state)
        return try {
            ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            null
        } catch (e: Exception) {
            "브라우저를 열 수 없습니다: ${e.message}"
        }
    }

    /** 앱을 연 주소가 구글 되돌아오기면 처리하고 true. 아니면 false */
    fun handleRedirect(uri: String?, onResult: (Result<GoogleAccount>) -> Unit): Boolean {
        val scheme = GoogleOAuth.schemeFor(BuildConfig.GOOGLE_ANDROID_CLIENT_ID) ?: return false
        if (uri == null || !uri.startsWith("$scheme:")) return false
        val cb = GoogleOAuth.parseRedirect(uri) ?: return false
        val pending = store.pending()
        store.clearPending()
        when {
            pending == null -> onResult(Result.failure(IllegalStateException("연결 시작 기록이 없습니다 — [구글 계정 연결]을 다시 누르세요")))
            cb.error != null -> onResult(Result.failure(IllegalStateException("구글이 거부했습니다: ${cb.error}")))
            cb.state != pending.second -> onResult(Result.failure(IllegalStateException("되돌아온 요청이 이 앱의 것이 아닙니다")))
            cb.code == null -> onResult(Result.failure(IllegalStateException("동의 코드가 없습니다")))
            else -> Thread({ exchange(cb.code, pending.first, onResult) }, "cardsms-oauth").start()
        }
        return true
    }

    private fun exchange(code: String, verifier: String, onResult: (Result<GoogleAccount>) -> Unit) {
        val redirect = GoogleOAuth.redirectUriFor(BuildConfig.GOOGLE_ANDROID_CLIENT_ID) ?: return
        val (status, json) = GmailClient.exchange(code, verifier, redirect)
        val refresh = json?.optString("refresh_token", "").orEmpty()
        if (status !in 200..299 || refresh.isEmpty()) {
            val why = json?.optString("error_description", "").orEmpty().ifEmpty { json?.optString("error", "").orEmpty() }
            onResult(Result.failure(IllegalStateException("토큰 받기 실패 (HTTP $status${if (why.isEmpty()) "" else ", $why"})")))
            return
        }
        val email = GoogleOAuth.emailFromIdToken(json?.optString("id_token", "").orEmpty()) ?: "(이메일 확인 불가)"
        onResult(Result.success(GoogleAccount(email, refresh)))
    }
}
