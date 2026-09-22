package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class RawMessageTest {
    private val raw = RawMessage.build("[카드SMS]", "현대 승인 24,000원", "Tue, 22 Sep 2026 10:00:00 GMT")

    @Test fun `제목은 UTF-8 로 인코딩한 헤더`() {
        val enc = Base64.getEncoder().encodeToString("[카드SMS]".toByteArray())
        assertTrue(raw.contains("Subject: =?UTF-8?B?$enc?=\r\n"))
    }

    @Test fun `본문은 base64 UTF-8 이고 헤더와 빈 줄로 나뉜다`() {
        val body = Base64.getMimeEncoder(76, "\r\n".toByteArray()).encodeToString("현대 승인 24,000원".toByteArray())
        assertTrue(raw.contains("Content-Type: text/plain; charset=UTF-8\r\n"))
        assertTrue(raw.contains("Content-Transfer-Encoding: base64\r\n"))
        assertTrue(raw.endsWith("\r\n\r\n$body\r\n"))
        assertTrue(raw.contains("Date: Tue, 22 Sep 2026 10:00:00 GMT\r\n"))
        assertTrue(raw.startsWith("From: cardsms <cardsms@aioffice.invalid>\r\n"))
    }

    @Test fun `base64url 은 패딩과 +슬래시가 없다`() {
        val out = RawMessage.toBase64Url("a?b~c>>>")
        assertFalse(out.contains("="))
        assertFalse(out.contains("+"))
        assertFalse(out.contains("/"))
        assertEquals("a?b~c>>>", String(Base64.getUrlDecoder().decode(out)))
    }

    @Test fun `지금 시각은 RFC1123 모양`() =
        assertTrue(Regex("^[A-Z][a-z]{2}, \\d{1,2} [A-Z][a-z]{2} \\d{4} \\d{2}:\\d{2}:\\d{2} GMT$").matches(RawMessage.rfc1123Now()))
}
