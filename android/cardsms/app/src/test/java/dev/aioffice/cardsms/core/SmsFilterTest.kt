package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SmsFilterTest {
    private val kws = SmsFilter.parseKeywords(SmsFilter.DEFAULT_KEYWORDS)

    @Test fun `기본 키워드는 승인과 취소`() = assertEquals(listOf("승인", "취소"), kws)

    @Test fun `승인 문자는 보낸다`() =
        assertTrue(SmsFilter.shouldForward("[Web발신]\n현대 Amex Gold 승인\n신*재\n24,000원 일시불", kws))

    @Test fun `취소 문자도 보낸다`() =
        assertTrue(SmsFilter.shouldForward("KB국민카드 취소 신*재님 1,000원", kws))

    @Test fun `일반 문자는 안 보낸다`() =
        assertFalse(SmsFilter.shouldForward("엄마 저녁 뭐 먹을까", kws))

    @Test fun `키워드는 쉼표나 줄바꿈으로 나누고 공백을 뗀다`() =
        assertEquals(listOf("승인", "취소", "결제"), SmsFilter.parseKeywords(" 승인, 취소\n결제 ,, "))

    @Test fun `조각은 순서대로 이어 붙이고 null 은 건너뛴다`() =
        assertEquals("앞뒤", SmsFilter.joinParts(listOf("앞", null, "뒤")))
}
