package dev.aioffice.cardsms.core

/** 어떤 문자를 보낼지 — 순수 함수. 안드로이드 의존 없음. */
object SmsFilter {
    const val DEFAULT_KEYWORDS = "승인,취소"

    fun parseKeywords(text: String): List<String> =
        text.split(',', '\n').map { it.trim() }.filter { it.isNotEmpty() }

    fun shouldForward(body: String, keywords: List<String>): Boolean =
        keywords.any { body.contains(it) }

    /** 긴 문자는 여러 조각(PDU)으로 온다 — 순서대로 이어 붙인다 */
    fun joinParts(parts: List<String?>): String = parts.filterNotNull().joinToString("")
}
