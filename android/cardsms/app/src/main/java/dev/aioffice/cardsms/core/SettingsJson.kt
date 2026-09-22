package dev.aioffice.cardsms.core

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

data class AppSettings(
    val clientId: String,
    val clientSecret: String,
    val refreshToken: String,
    val subject: String,
    val keywords: List<String>,
)

/** 설정 파일(json) ↔ AppSettings. 필수값이 없으면 어떤 키인지 알려 준다. */
object SettingsJson {
    const val DEFAULT_SUBJECT = "[카드SMS]"

    fun parse(text: String): AppSettings {
        val o = try { JSONObject(text) } catch (e: JSONException) {
            throw IllegalArgumentException("설정 파일 형식이 아닙니다")
        }
        fun need(key: String): String = o.optString(key, "").also {
            if (it.isEmpty()) throw IllegalArgumentException("$key 없음")
        }
        val kws = o.optJSONArray("keywords")?.let { arr -> List(arr.length()) { arr.getString(it) } }
            ?: SmsFilter.parseKeywords(SmsFilter.DEFAULT_KEYWORDS)
        return AppSettings(
            clientId = need("client_id"),
            clientSecret = need("client_secret"),
            refreshToken = need("refresh_token"),
            subject = o.optString("subject", DEFAULT_SUBJECT).ifEmpty { DEFAULT_SUBJECT },
            keywords = kws,
        )
    }

    fun toJson(s: AppSettings): String = JSONObject()
        .put("client_id", s.clientId)
        .put("client_secret", s.clientSecret)
        .put("refresh_token", s.refreshToken)
        .put("subject", s.subject)
        .put("keywords", JSONArray(s.keywords))
        .toString()
}
