package dev.aioffice.cardsms

import android.content.Context
import dev.aioffice.cardsms.core.AppSettings
import dev.aioffice.cardsms.core.SettingsJson

/** 연결된 구글 계정 — 이메일(표시용)과 리프레시 토큰(메일 넣기용). 값은 로그에 남기지 않는다. */
data class GoogleAccount(val email: String, val refreshToken: String)

/** 앱 전용 저장소(SharedPreferences). 다른 앱은 못 읽는다. */
class SettingsStore(ctx: Context) {
    private val p = ctx.getSharedPreferences("cardsms", Context.MODE_PRIVATE)

    fun load(): AppSettings = SettingsJson.parse(p.getString("settings", "") ?: "")

    fun save(s: AppSettings) { p.edit().putString("settings", SettingsJson.toJson(s)).apply() }

    fun account(): GoogleAccount? {
        val email = p.getString("g_email", null) ?: return null
        val token = p.getString("g_refresh", null) ?: return null
        return GoogleAccount(email, token)
    }

    fun saveAccount(a: GoogleAccount) { p.edit().putString("g_email", a.email).putString("g_refresh", a.refreshToken).apply() }

    fun clearAccount() { p.edit().remove("g_email").remove("g_refresh").apply() }
}
