package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsJsonTest {
    private val s = AppSettings(
        senders = listOf(Sender("15776200", "현대카드"), Sender("15881688", "")),
        forwardAll = true,
        keywords = listOf("승인", "취소"),
    )

    @Test fun `저장하면 그대로 다시 읽는다`() =
        assertEquals(s, SettingsJson.parse(SettingsJson.toJson(s)))

    @Test fun `빈 문자열이나 깨진 json 은 기본 설정`() {
        assertEquals(AppSettings.DEFAULT, SettingsJson.parse(""))
        assertEquals(AppSettings.DEFAULT, SettingsJson.parse("이건 json 아님"))
    }

    @Test fun `기본 설정 - 번호 없음·전체 전송·키워드 승인 취소`() {
        assertEquals(emptyList<Sender>(), AppSettings.DEFAULT.senders)
        assertEquals(true, AppSettings.DEFAULT.forwardAll)
        assertEquals(listOf("승인", "취소"), AppSettings.DEFAULT.keywords)
    }

    @Test fun `번호 추가는 정리해서 넣고 중복은 무시한다`() {
        val a = AppSettings.DEFAULT.addSender("1577-6200", "현대카드")
        assertEquals(listOf(Sender("15776200", "현대카드")), a.senders)
        assertEquals(a, a.addSender("+82 1577-6200", "다시"))     // 같은 번호 → 그대로
        assertEquals(a, a.addSender("현대", "숫자 없음"))          // 숫자 없으면 무시
    }

    @Test fun `번호 삭제`() =
        assertEquals(listOf(Sender("15881688", "")), s.removeSender("15776200").senders)
}
