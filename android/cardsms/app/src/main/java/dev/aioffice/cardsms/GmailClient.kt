package dev.aioffice.cardsms

import dev.aioffice.cardsms.core.AppSettings
import dev.aioffice.cardsms.core.RawMessage
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** 구글 토큰 갱신 + 지메일 insert. 값(토큰)은 로그에 남기지 않는다. */
class GmailClient(private val s: AppSettings) {

    /** @return HTTP 상태와 본문. 네트워크 오류면 status 0 */
    private fun post(url: String, contentType: String, body: ByteArray, bearer: String? = null): Pair<Int, String> {
        val c = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; doOutput = true
            connectTimeout = 15_000; readTimeout = 20_000
            setRequestProperty("Content-Type", contentType)
            if (bearer != null) setRequestProperty("Authorization", "Bearer $bearer")
        }
        return try {
            c.outputStream.use { it.write(body) }
            val status = c.responseCode
            val stream = if (status in 200..299) c.inputStream else c.errorStream
            status to (stream?.bufferedReader()?.readText() ?: "")
        } catch (e: IOException) {
            0 to (e.message ?: "네트워크 오류")
        } finally { c.disconnect() }
    }

    /** 리프레시 토큰으로 액세스 토큰. 실패면 null 과 상태 */
    fun accessToken(): Pair<String?, Int> {
        val form = listOf("client_id" to s.clientId, "client_secret" to s.clientSecret,
            "refresh_token" to s.refreshToken, "grant_type" to "refresh_token")
            .joinToString("&") { (k, v) -> k + "=" + URLEncoder.encode(v, "UTF-8") }
        val (status, text) = post("https://oauth2.googleapis.com/token", "application/x-www-form-urlencoded", form.toByteArray())
        if (status !in 200..299) return null to status
        return runCatching { JSONObject(text).getString("access_token") }.getOrNull() to status
    }

    /** 받은편지함에 메일 한 통 넣기(발송 아님). @return HTTP 상태 */
    fun insert(token: String, subject: String, body: String): Int {
        val raw = RawMessage.toBase64Url(RawMessage.build(subject, body, RawMessage.rfc1123Now()))
        val json = JSONObject().put("raw", raw).put("labelIds", JSONArray(listOf("INBOX", "UNREAD"))).toString()
        return post("https://gmail.googleapis.com/gmail/v1/users/me/messages", "application/json; charset=UTF-8",
            json.toByteArray(Charsets.UTF_8), token).first
    }
}
