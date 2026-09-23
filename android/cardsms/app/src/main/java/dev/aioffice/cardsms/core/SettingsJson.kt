package dev.aioffice.cardsms.core

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/** 등록한 발신번호(숫자만 저장)와 메모(카드 이름 등) */
data class Sender(val number: String, val memo: String)

/** 앱 설정 — 발신번호 목록, 전체 전송 여부, 키워드. 구글 계정은 따로(GoogleAccount) 둔다. */
data class AppSettings(
    val senders: List<Sender>,
    val forwardAll: Boolean,
    val keywords: List<String>,
) {
    /** 숫자만 남겨 저장. 이미 있는 번호(국가번호만 다른 것 포함)면 그대로 둔다. */
    fun addSender(number: String, memo: String): AppSettings {
        val n = SmsFilter.normalizeNumber(number)
        if (n.isEmpty() || SmsFilter.senderMatches(n, senderNumbers())) return this
        return copy(senders = senders + Sender(n, memo.trim()))
    }

    fun removeSender(number: String): AppSettings =
        copy(senders = senders.filterNot { it.number == SmsFilter.normalizeNumber(number) })

    fun senderNumbers(): List<String> = senders.map { it.number }

    companion object {
        val DEFAULT = AppSettings(senders = emptyList(), forwardAll = true,
            keywords = SmsFilter.parseKeywords(SmsFilter.DEFAULT_KEYWORDS))
    }
}

/** 설정 ↔ json (앱 전용 저장소에 넣는 용도). 깨져 있으면 기본 설정. */
object SettingsJson {
    fun parse(text: String): AppSettings {
        if (text.isBlank()) return AppSettings.DEFAULT
        val o = try { JSONObject(text) } catch (e: JSONException) { return AppSettings.DEFAULT }
        val senders = o.optJSONArray("senders")?.let { arr ->
            List(arr.length()) { i ->
                val s = arr.getJSONObject(i)
                Sender(s.optString("number", ""), s.optString("memo", ""))
            }.filter { it.number.isNotEmpty() }
        } ?: emptyList()
        val kws = o.optJSONArray("keywords")?.let { arr -> List(arr.length()) { arr.getString(it) } }
            ?: AppSettings.DEFAULT.keywords
        return AppSettings(senders, o.optBoolean("forward_all", true), kws)
    }

    fun toJson(s: AppSettings): String = JSONObject()
        .put("senders", JSONArray(s.senders.map { JSONObject().put("number", it.number).put("memo", it.memo) }))
        .put("forward_all", s.forwardAll)
        .put("keywords", JSONArray(s.keywords))
        .toString()
}
