package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SmsFilterTest {
    private val kws = SmsFilter.parseKeywords(SmsFilter.DEFAULT_KEYWORDS)
    private val hyundai = listOf("1577-6200")

    @Test fun `기본 키워드는 승인과 취소`() = assertEquals(listOf("승인", "취소"), kws)

    @Test fun `번호 정리 - 숫자만 남긴다`() {
        assertEquals("15776200", SmsFilter.normalizeNumber("1577-6200"))
        assertEquals("15776200", SmsFilter.normalizeNumber(" 1577 6200 "))
        assertEquals("8215776200", SmsFilter.normalizeNumber("+82 1577-6200"))
        assertEquals("", SmsFilter.normalizeNumber("현대카드"))
    }

    @Test fun `발신번호 매칭 - 형태가 달라도 같은 번호면 맞다`() {
        assertTrue(SmsFilter.senderMatches("15776200", hyundai))
        assertTrue(SmsFilter.senderMatches("1577-6200", hyundai))
        assertTrue(SmsFilter.senderMatches("+8215776200", hyundai))
        assertFalse(SmsFilter.senderMatches("15776201", hyundai))
        assertFalse(SmsFilter.senderMatches("010-1234-5678", hyundai))
        assertFalse(SmsFilter.senderMatches("", hyundai))
    }

    @Test fun `짧은 번호는 끝자리만 같아도 매칭하지 않는다`() =
        assertFalse(SmsFilter.senderMatches("01012346200", listOf("6200")))

    @Test fun `전체 전송이면 등록 번호의 문자는 내용과 상관없이 보낸다`() {
        assertTrue(SmsFilter.shouldForward("1577-6200", "안내 문자입니다", hyundai, true, kws))
        assertFalse(SmsFilter.shouldForward("010-1234-5678", "현대카드 승인 24,000원", hyundai, true, kws))
    }

    @Test fun `키워드 모드면 등록 번호이면서 키워드가 있어야 보낸다`() {
        assertTrue(SmsFilter.shouldForward("1577-6200", "현대 Amex Gold 승인 24,000원", hyundai, false, kws))
        assertFalse(SmsFilter.shouldForward("1577-6200", "안내 문자입니다", hyundai, false, kws))
        assertFalse(SmsFilter.shouldForward("010-1234-5678", "친구 승인해줘", hyundai, false, kws))
    }

    @Test fun `등록 번호가 없으면 아무것도 보내지 않는다`() =
        assertFalse(SmsFilter.shouldForward("1577-6200", "승인", emptyList(), true, kws))

    @Test fun `키워드는 쉼표나 줄바꿈으로 나누고 공백을 뗀다`() =
        assertEquals(listOf("승인", "취소", "결제"), SmsFilter.parseKeywords(" 승인, 취소\n결제 ,, "))

    @Test fun `조각은 순서대로 이어 붙이고 null 은 건너뛴다`() =
        assertEquals("앞뒤", SmsFilter.joinParts(listOf("앞", null, "뒤")))
}
