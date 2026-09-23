package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class AccountJsonTest {
    @Test fun `PC 에서 만든 설정 파일을 읽는다 (여분 키는 무시)`() {
        val c = AccountJson.parse("""{"client_id":"a","client_secret":"b","refresh_token":"c","subject":"[카드SMS]","keywords":["승인"]}""")
        assertEquals(GoogleCreds("a", "b", "c", ""), c)
    }

    @Test fun `이메일이 있으면 같이 읽는다`() =
        assertEquals("me@example.com",
            AccountJson.parse("""{"client_id":"a","client_secret":"b","refresh_token":"c","email":"me@example.com"}""").email)

    @Test fun `필수값이 없으면 어떤 키인지 말한다`() {
        val e = assertThrows(IllegalArgumentException::class.java) {
            AccountJson.parse("""{"client_id":"a","client_secret":"b"}""")
        }
        assertEquals("refresh_token 없음", e.message)
    }

    @Test fun `json 이 아니면 알기 쉬운 오류`() {
        val e = assertThrows(IllegalArgumentException::class.java) { AccountJson.parse("이건 json 아님") }
        assertEquals("설정 파일 형식이 아닙니다", e.message)
    }

    @Test fun `저장하면 다시 읽을 수 있다`() {
        val c = GoogleCreds("a", "b", "c", "me@example.com")
        assertEquals(c, AccountJson.parse(AccountJson.toJson(c)))
    }
}
