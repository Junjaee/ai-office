package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class SettingsJsonTest {
    private val ok = """{"client_id":"a","client_secret":"b","refresh_token":"c","subject":"[카드SMS]","keywords":["승인","취소"]}"""

    @Test fun `정상 파일`() {
        val s = SettingsJson.parse(ok)
        assertEquals(AppSettings("a", "b", "c", "[카드SMS]", listOf("승인", "취소")), s)
    }

    @Test fun `제목과 키워드는 없으면 기본값`() {
        val s = SettingsJson.parse("""{"client_id":"a","client_secret":"b","refresh_token":"c"}""")
        assertEquals("[카드SMS]", s.subject)
        assertEquals(listOf("승인", "취소"), s.keywords)
    }

    @Test fun `필수값이 없으면 어떤 키인지 말한다`() {
        val e = assertThrows(IllegalArgumentException::class.java) {
            SettingsJson.parse("""{"client_id":"a","client_secret":"b"}""")
        }
        assertEquals("refresh_token 없음", e.message)
    }

    @Test fun `json 이 아니면 알기 쉬운 오류`() {
        val e = assertThrows(IllegalArgumentException::class.java) { SettingsJson.parse("이건 json 아님") }
        assertEquals("설정 파일 형식이 아닙니다", e.message)
    }

    @Test fun `저장하면 다시 읽을 수 있다`() {
        val s = SettingsJson.parse(ok)
        assertEquals(s, SettingsJson.parse(SettingsJson.toJson(s)))
    }
}
