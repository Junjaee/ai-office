package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.URLEncoder
import java.util.Base64

class GoogleOAuthTest {
    private val cid = "123456-abcdef.apps.googleusercontent.com"

    // RFC 7636 부록 B 의 검증용 값
    @Test fun `PKCE 챌린지는 S256`() =
        assertEquals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            GoogleOAuth.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"))

    @Test fun `검증자는 43~128자 url-safe`() {
        val v = GoogleOAuth.newVerifier()
        assertTrue(v.length in 43..128)
        assertTrue(Regex("^[A-Za-z0-9._~-]+$").matches(v))
    }

    @Test fun `되돌아올 스킴은 클라이언트 ID 를 뒤집은 것`() {
        assertEquals("com.googleusercontent.apps.123456-abcdef", GoogleOAuth.schemeFor(cid))
        assertEquals("com.googleusercontent.apps.123456-abcdef:/oauth2redirect", GoogleOAuth.redirectUriFor(cid))
        assertNull(GoogleOAuth.schemeFor(""))
        assertNull(GoogleOAuth.schemeFor("이상한값"))
    }

    @Test fun `동의 주소에는 클라이언트·되돌아올 주소·권한·PKCE·상태가 들어간다`() {
        val redirect = GoogleOAuth.redirectUriFor(cid)!!
        val url = GoogleOAuth.authUrl(cid, redirect, "CHAL", "STATE")
        assertTrue(url.startsWith("https://accounts.google.com/o/oauth2/v2/auth?"))
        assertTrue(url.contains("client_id=" + URLEncoder.encode(cid, "UTF-8")))
        assertTrue(url.contains("redirect_uri=" + URLEncoder.encode(redirect, "UTF-8")))
        assertTrue(url.contains("scope=" + URLEncoder.encode(GoogleOAuth.SCOPES, "UTF-8")))
        assertTrue(url.contains("code_challenge=CHAL"))
        assertTrue(url.contains("code_challenge_method=S256"))
        assertTrue(url.contains("state=STATE"))
        assertTrue(url.contains("access_type=offline"))
        assertTrue(url.contains("prompt=consent"))
    }

    @Test fun `토큰 교환 본문에는 비밀값이 없고 PKCE 검증자가 있다`() {
        val body = GoogleOAuth.tokenBody(cid, "CODE", "VERIFIER", "com.googleusercontent.apps.x:/oauth2redirect")
        assertTrue(body.contains("code=CODE"))
        assertTrue(body.contains("code_verifier=VERIFIER"))
        assertTrue(body.contains("grant_type=authorization_code"))
        assertFalse(body.contains("client_secret"))
    }

    @Test fun `앱으로 되돌아온 주소에서 code 와 state 를 꺼낸다`() {
        val r = GoogleOAuth.parseRedirect("com.googleusercontent.apps.123456-abcdef:/oauth2redirect?state=STATE&code=4%2Fabc-def&scope=x")
        assertEquals("4/abc-def", r?.code)
        assertEquals("STATE", r?.state)
        assertNull(GoogleOAuth.parseRedirect("com.googleusercontent.apps.x:/oauth2redirect"))
        assertNull(GoogleOAuth.parseRedirect("cardsms://connected"))
        assertEquals("access_denied", GoogleOAuth.parseRedirect("com.googleusercontent.apps.x:/oauth2redirect?error=access_denied&state=S")?.error)
    }

    @Test fun `id_token 에서 이메일을 읽는다`() {
        val payload = Base64.getUrlEncoder().withoutPadding()
            .encodeToString("""{"sub":"1","email":"me@example.com"}""".toByteArray())
        assertEquals("me@example.com", GoogleOAuth.emailFromIdToken("hdr.$payload.sig"))
        assertNull(GoogleOAuth.emailFromIdToken("깨진토큰"))
    }
}
