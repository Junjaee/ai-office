package dev.aioffice.cardsms.core

import org.json.JSONException
import org.json.JSONObject

/** PC 에서 만든 설정 파일(`카드문자전달-설정.json`)의 구글 계정 값. 앱은 이 값으로만 지메일에 메일을 넣는다. */
data class GoogleCreds(val clientId: String, val clientSecret: String, val refreshToken: String, val email: String)

/** 설정 파일 해석. 필수값이 없으면 어떤 키인지 알려 준다. 모르는 키(subject·keywords 등)는 무시한다. */
object AccountJson {
    fun parse(text: String): GoogleCreds {
        val o = try { JSONObject(text) } catch (e: JSONException) {
            throw IllegalArgumentException("설정 파일 형식이 아닙니다")
        }
        fun need(key: String): String = o.optString(key, "").also {
            if (it.isEmpty()) throw IllegalArgumentException("$key 없음")
        }
        return GoogleCreds(
            clientId = need("client_id"),
            clientSecret = need("client_secret"),
            refreshToken = need("refresh_token"),
            email = o.optString("email", ""),
        )
    }

    fun toJson(c: GoogleCreds): String = JSONObject()
        .put("client_id", c.clientId).put("client_secret", c.clientSecret)
        .put("refresh_token", c.refreshToken).put("email", c.email).toString()
}
