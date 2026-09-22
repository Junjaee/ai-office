package dev.aioffice.cardsms

import android.content.Context
import dev.aioffice.cardsms.core.AppSettings
import dev.aioffice.cardsms.core.SettingsJson
import dev.aioffice.cardsms.core.SmsFilter

/** 앱 전용 저장소(SharedPreferences). 다른 앱은 못 읽는다. */
class SettingsStore(ctx: Context) {
    private val p = ctx.getSharedPreferences("cardsms", Context.MODE_PRIVATE)

    fun load(): AppSettings? = p.getString("settings", null)?.let { runCatching { SettingsJson.parse(it) }.getOrNull() }

    fun save(s: AppSettings) { p.edit().putString("settings", SettingsJson.toJson(s)).apply() }

    fun keywordsText(): String = load()?.keywords?.joinToString(",") ?: SmsFilter.DEFAULT_KEYWORDS

    fun saveKeywordsText(text: String) {
        val s = load() ?: return
        save(s.copy(keywords = SmsFilter.parseKeywords(text).ifEmpty { SmsFilter.parseKeywords(SmsFilter.DEFAULT_KEYWORDS) }))
    }
}
