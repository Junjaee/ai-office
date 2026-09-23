package dev.aioffice.cardsms

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 최근 20건 기록. 본문 전체는 남기지 않는다(앞 20자만). 발신번호는 새 카드 번호를 알아내는 데 쓴다. */
class ForwardLog(ctx: Context) {
    private val p = ctx.getSharedPreferences("cardsms", Context.MODE_PRIVATE)
    private val fmt = SimpleDateFormat("MM/dd HH:mm", Locale.KOREA)

    fun add(sender: String, head: String, ok: Boolean, note: String) {
        val arr = JSONArray(p.getString("log", "[]"))
        val entry = JSONObject().put("t", fmt.format(Date())).put("from", sender)
            .put("head", head.take(20).replace('\n', ' ')).put("ok", ok).put("note", note)
        val next = JSONArray().put(entry)
        for (i in 0 until minOf(arr.length(), 19)) next.put(arr.get(i))
        p.edit().putString("log", next.toString()).apply()
    }

    fun lines(): List<String> {
        val arr = JSONArray(p.getString("log", "[]"))
        return List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            val from = o.optString("from", "")
            "${o.getString("t")} ${if (o.getBoolean("ok")) "✓" else "✗"} ${if (from.isEmpty()) "" else "$from "}${o.getString("head")}  ${o.getString("note")}"
        }
    }
}
