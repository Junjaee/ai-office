package dev.aioffice.cardsms.core

import java.net.URLDecoder
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

/** 구글 계정 연결의 순수 계산 부분 — 주소 만들기·PKCE·되돌아온 요청 해석. 네트워크는 여기 없다. */
object GoogleOAuth {
    /** 메일 넣기(insert) + 연결된 계정 이메일을 보여 주기 위한 openid/email */
    const val SCOPES = "https://www.googleapis.com/auth/gmail.insert openid email"
    const val AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    const val TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    const val REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

    data class Callback(val code: String?, val state: String?, val error: String?)

    private val b64 = Base64.getUrlEncoder().withoutPadding()

    fun newVerifier(): String = ByteArray(32).also { SecureRandom().nextBytes(it) }.let(b64::encodeToString)

    fun newState(): String = ByteArray(16).also { SecureRandom().nextBytes(it) }.let(b64::encodeToString)

    fun challenge(verifier: String): String =
        b64.encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII)))

    fun authUrl(clientId: String, redirectUri: String, challenge: String, state: String): String {
        val q = listOf(
            "client_id" to clientId, "redirect_uri" to redirectUri, "response_type" to "code",
            "scope" to SCOPES, "code_challenge" to challenge, "code_challenge_method" to "S256",
            "state" to state, "access_type" to "offline", "prompt" to "consent",
        ).joinToString("&") { (k, v) -> k + "=" + URLEncoder.encode(v, "UTF-8") }
        return "$AUTH_ENDPOINT?$q"
    }

    /** 토큰 교환 요청 본문(form) */
    fun tokenBody(clientId: String, clientSecret: String, code: String, verifier: String, redirectUri: String): String =
        listOf("client_id" to clientId, "client_secret" to clientSecret, "code" to code,
            "code_verifier" to verifier, "redirect_uri" to redirectUri, "grant_type" to "authorization_code")
            .joinToString("&") { (k, v) -> k + "=" + URLEncoder.encode(v, "UTF-8") }

    /** 브라우저가 되돌아온 HTTP 요청의 첫 줄(`GET /?code=…&state=… HTTP/1.1`) 해석. 관련 없는 요청이면 null */
    fun parseCallback(requestLine: String): Callback? {
        val path = requestLine.split(" ").getOrNull(1) ?: return null
        val query = path.substringAfter("?", "")
        if (query.isEmpty()) return null
        val params = query.split("&").mapNotNull { kv ->
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
