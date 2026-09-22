package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Test

class FailureTest {
    @Test fun `2xx 는 성공`() = assertEquals(Outcome.OK, Failure.classify(200))

    @Test fun `토큰·권한·요청 오류는 다시 해도 안 되니 실패`() {
        assertEquals(Outcome.FAIL, Failure.classify(400))
        assertEquals(Outcome.FAIL, Failure.classify(401))
        assertEquals(Outcome.FAIL, Failure.classify(403))
    }

    @Test fun `한도·서버 오류·네트워크(0) 는 재시도`() {
        assertEquals(Outcome.RETRY, Failure.classify(429))
        assertEquals(Outcome.RETRY, Failure.classify(500))
        assertEquals(Outcome.RETRY, Failure.classify(503))
        assertEquals(Outcome.RETRY, Failure.classify(0))
    }
}
