package dev.aioffice.cardsms.core

enum class Outcome { OK, RETRY, FAIL }

/** HTTP 상태 → 다시 시도할지. 0 은 네트워크 오류(연결 안 됨). */
object Failure {
    fun classify(status: Int): Outcome = when {
        status in 200..299 -> Outcome.OK
        status == 0 || status == 429 || status >= 500 -> Outcome.RETRY
        else -> Outcome.FAIL
    }
}
