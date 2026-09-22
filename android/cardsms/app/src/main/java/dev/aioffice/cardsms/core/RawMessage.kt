package dev.aioffice.cardsms.core

import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Base64

/** 지메일 insert 에 넣을 RFC822 메일 — 순수 함수 */
object RawMessage {
    private const val CRLF = "\r\n"

    fun build(subject: String, body: String, dateRfc1123: String): String {
        val subj = Base64.getEncoder().encodeToString(subject.toByteArray(Charsets.UTF_8))
        val text = Base64.getMimeEncoder(76, CRLF.toByteArray()).encodeToString(body.toByteArray(Charsets.UTF_8))
        return "From: cardsms <cardsms@aioffice.invalid>" + CRLF +
            "Subject: =?UTF-8?B?$subj?=" + CRLF +
            "Date: $dateRfc1123" + CRLF +
            "MIME-Version: 1.0" + CRLF +
            "Content-Type: text/plain; charset=UTF-8" + CRLF +
            "Content-Transfer-Encoding: base64" + CRLF +
            CRLF + text + CRLF
    }

    fun toBase64Url(raw: String): String =
        Base64.getUrlEncoder().withoutPadding().encodeToString(raw.toByteArray(Charsets.UTF_8))

    fun rfc1123Now(): String =
        DateTimeFormatter.RFC_1123_DATE_TIME.format(ZonedDateTime.now(ZoneOffset.UTC))
}
