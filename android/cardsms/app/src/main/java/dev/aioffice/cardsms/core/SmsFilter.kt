package dev.aioffice.cardsms.core

/** 어떤 문자를 보낼지 — 순수 함수. 안드로이드 의존 없음. */
object SmsFilter {
    const val DEFAULT_KEYWORDS = "승인,취소"

    /** 번호 끝자리가 이만큼은 같아야 같은 번호로 본다(짧은 번호 오인 방지) */
    private const val MIN_DIGITS = 7

    fun parseKeywords(text: String): List<String> =
        text.split(',', '\n').map { it.trim() }.filter { it.isNotEmpty() }

    /** `1577-6200`, `+82 1577-6200`, `15776200` → 숫자만 */
    fun normalizeNumber(text: String): String = text.filter { it.isDigit() }

    /** 등록 번호와 같은 번호인지. 국가번호(+82)가 붙어도 끝자리로 맞춘다. */
    fun senderMatches(sender: String, senders: List<String>): Boolean {
        val s = normalizeNumber(sender)
        if (s.length < MIN_DIGITS) return false
        return senders.any { raw ->
            val n = normalizeNumber(raw)
            n.length >= MIN_DIGITS && (s == n || s.endsWith(n) || n.endsWith(s))
        }
    }

    /** 등록 번호에서 온 문자만. 전체 전송이면 내용과 무관, 아니면 키워드가 있어야 한다. 번호가 없으면 아무것도 안 보낸다. */
    fun shouldForward(sender: String, body: String, senders: List<String>, forwardAll: Boolean,
                      keywords: List<String>): Boolean {
        if (senders.isEmpty() || !senderMatches(sender, senders)) return false
        return forwardAll || keywords.any { body.contains(it) }
    }

    /** 긴 문자는 여러 조각(PDU)으로 온다 — 순서대로 이어 붙인다 */
    fun joinParts(parts: List<String?>): String = parts.filterNotNull().joinToString("")
}
