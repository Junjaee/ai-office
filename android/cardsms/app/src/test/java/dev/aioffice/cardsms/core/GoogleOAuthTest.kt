package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class GoogleOAuthTest {
    // RFC 7636 부록 B 의 검증용 값
    @Test fun `PKCE 챌린지는 S256`() =
        assertEquals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            GoogleOAuth.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"))

    @Test fun `검증자는 43~128자 url-safe`() {
        val v = GoogleOAuth.newVerifier()
        assertTrue(v.length in 43..128)
        assertTrue(Regex("^[A-Za-z0-9._~-]+$").matches(v))
    }

    @Test fun `동의 주소에는 클라이언트·되돌아올 주소·권한·PKCE·상태가 들어간다`() {
        val url = GoogleOAuth.authUrl("CID", "http://127.0.0.1:4321/", "CHAL", "STATE")
        assertTrue(url.startsWith("https://accounts.google.com/o/oauth2/v2/auth?"))
        assertTrue(url.contains("client_id=CID"))
        assertTrue(url.contains("redirect_uri=http%3A%2F%2F127.0.0.1%3A4321%2F"))
        assertTrue(url.contains("scope=" + java.net.URLEncoder.encode(GoogleOAuth.SCOPES, "UTF-8")))
        assertTrue(url.contains("code_challenge=CHAL"))
        assertTrue(url.contains("code_challenge_method=S256"))
        assertTrue(url.contains("state=STATE"))
        assertTrue(url.contains("access_type=offline"))
        assertTrue(url.contains("prompt=consent"))
    }

    @Test fun `되돌아온 요청 줄에서 code 와 state 를 꺼낸다`() {
        val r = GoogleOAuth.parseCallback("GET /?state=STATE&code=4%2Fabc-def&scope=x HTTP/1.1")
        assertEquals("4/abc-def", r?.code)
        assertEquals("STATE", r?.state)
        assertNull(GoogleOAuth.parseCallback("GET /favicon.ico HTTP/1.1"))
        assertEquals("access_denied", GoogleOAuth.parseCallback("GET /?error=access_denied&state=S HTTP/1.1")?.error)
    }

    @Test fun `id_token 에서 이메일을 읽는다`() {
        val payload = Base64.getUrlEncoder().withoutPadding()
            .encodeToString("""{"sub":"1","email":"me@example.com"}""".toByteArray())
        assertEquals("me@example.com", GoogleOAuth.emailFromIdToken("hdr.$payload.sig"))
        assertNull(GoogleOAuth.emailFromIdToken("깨진토큰"))
    }
}
