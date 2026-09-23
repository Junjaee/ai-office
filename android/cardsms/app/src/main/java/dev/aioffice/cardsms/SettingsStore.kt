package dev.aioffice.cardsms

import android.content.Context
import dev.aioffice.cardsms.core.AccountJson
import dev.aioffice.cardsms.core.AppSettings
import dev.aioffice.cardsms.core.GoogleCreds
import dev.aioffice.cardsms.core.SettingsJson

/** 앱 전용 저장소(SharedPreferences). 다른 앱은 못 읽는다. 값은 로그에 남기지 않는다. */
class SettingsStore(ctx: Context) {
    private val p = ctx.getSharedPreferences("cardsms", Context.MODE_PRIVATE)

    fun load(): AppSettings = SettingsJson.parse(p.getString("settings", "") ?: "")

    fun save(s: AppSettings) { p.edit().putString("settings", SettingsJson.toJson(s)).apply() }

    /** PC 에서 만든 설정 파일로 불러온 구글 계정 값 */
    fun account(): GoogleCreds? = p.getString("account", null)?.let { runCatching { AccountJson.parse(it) }.getOrNull() }

    fun saveAccount(c: GoogleCreds) { p.edit().putString("account", AccountJson.toJson(c)).apply() }

    fun clearAccount() { p.edit().remove("account").apply() }
}
