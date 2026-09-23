package dev.aioffice.cardsms.core

import java.net.URLDecoder
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

/** 구글 계정 연결의 순수 계산 부분 — 주소 만들기·PKCE·되돌아온 주소 해석. 네트워크는 여기 없다.
 *
 * 안드로이드용 OAuth 클라이언트(비밀값 없음, PKCE)를 쓴다. 허용이 끝나면 구글이 브라우저를
 * `com.googleusercontent.apps.<클라이언트ID 앞부분>:/oauth2redirect?code=…` 로 보내고, 그 스킴을 이 앱이 받는다.
 * (폰 안에 임시 서버를 두는 방식은 앱이 뒤에서 정리되면 실패해서 2026-09-23 에 버렸다)
 */
object GoogleOAuth {
    /** 메일 넣기(insert) + 연결된 계정 이메일을 보여 주기 위한 openid/email */
    const val SCOPES = "https://www.googleapis.com/auth/gmail.insert openid email"
    const val AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    const val TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    const val REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
    private const val CLIENT_SUFFIX = ".apps.googleusercontent.com"

    data class Callback(val code: String?, val state: String?, val error: String?)

    private val b64 = Base64.getUrlEncoder().withoutPadding()

    fun newVerifier(): String = ByteArray(32).also { SecureRandom().nextBytes(it) }.let(b64::encodeToString)

    fun newState(): String = ByteArray(16).also { SecureRandom().nextBytes(it) }.let(b64::encodeToString)

    fun challenge(verifier: String): String =
        b64.encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII)))

    /** 안드로이드 클라이언트 ID → 앱으로 되돌아올 스킴(클라이언트 ID 를 뒤집은 것). 모양이 아니면 null */
    fun schemeFor(androidClientId: String): String? {
        val id = androidClientId.trim()
        if (!id.endsWith(CLIENT_SUFFIX) || id.length <= CLIENT_SUFFIX.length) return null
        return "com.googleusercontent.apps." + id.removeSuffix(CLIENT_SUFFIX)
    }

    fun redirectUriFor(androidClientId: String): String? = schemeFor(androidClientId)?.let { "$it:/oauth2redirect" }

    fun authUrl(clientId: String, redirectUri: String, challenge: String, state: String): String {
        val q = listOf(
            "client_id" to clientId, "redirect_uri" to redirectUri, "response_type" to "code",
            "scope" to SCOPES, "code_challenge" to challenge, "code_challenge_method" to "S256",
            "state" to state, "access_type" to "offline", "prompt" to "consent",
        ).joinToString("&") { (k, v) -> k + "=" + URLEncoder.encode(v, "UTF-8") }
        return "$AUTH_ENDPOINT?$q"
    }

    /** 토큰 교환 요청 본문(form). 안드로이드 클라이언트는 비밀값이 없다 — PKCE 가 그 역할 */
    fun tokenBody(clientId: String, code: String, verifier: String, redirectUri: String): String =
        listOf("client_id" to clientId, "code" to code, "code_verifier" to verifier,
            "redirect_uri" to redirectUri, "grant_type" to "authorization_code")
            .joinToString("&") { (k, v) -> k + "=" + URLEncoder.encode(v, "UTF-8") }

    /** 브라우저가 앱을 다시 열며 넘긴 주소(`…:/oauth2redirect?code=…&state=…`) 해석. 관련 없으면 null */
    fun parseRedirect(uri: String): Callback? {
        val query = uri.substringAfter("?", "")
        if (query.isEmpty()) return null
        val params = query.substringBefore("#").split("&").mapNotNull { kv ->
            val i = kv.indexOf("=")
            if (i <= 0) null else URLDecoder.decode(kv.substring(0, i), "UTF-8") to URLDecoder.decode(kv.substring(i + 1), "UTF-8")
        }.toMap()
        if (params["code"] == null && params["error"] == null) return null
        return Callback(params["code"], params["state"], params["error"])
    }

    /** id_token(JWT) 의 payload 에서 email. 못 읽으면 null */
    fun emailFromIdToken(idToken: String): String? = runCatching {
        val payload = idToken.split(".").getOrNull(1) ?: return null
        val json = String(Base64.getUrlDecoder().decode(payload), Charsets.UTF_8)
        org.json.JSONObject(json).optString("email", "").ifEmpty { null }
    }.getOrNull()
}
