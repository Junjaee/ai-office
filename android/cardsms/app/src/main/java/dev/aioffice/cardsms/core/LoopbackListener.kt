package dev.aioffice.cardsms.core

import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException

/** 구글 동의가 끝나고 브라우저가 되돌아올 `http://127.0.0.1:포트/` 를 듣는 작은 서버. 안드로이드 의존 없음.
 *
 * 크롬은 페이지를 열기 전에 **아무것도 보내지 않는 미리연결**을 여러 개 걸어 둔다. 그래서
 * (1) 연결마다 짧은 읽기 제한을 두고, (2) 한 연결의 오류는 무시하고 다음 연결을 계속 받으며,
 * (3) 대기열(backlog)을 넉넉히 둔다. 이걸 안 하면 진짜 요청이 거부된다(2026-09-23 실측).
 */
class LoopbackListener(
    private val readTimeoutMs: Int = 3_000,
    totalTimeoutMs: Int = 5 * 60 * 1000,
) {
    private val server = ServerSocket(0, 16, InetAddress.getLoopbackAddress()).apply { soTimeout = totalTimeoutMs }

    val port: Int get() = server.localPort
    val redirectUri: String get() = "http://127.0.0.1:$port/"

    /** 동의 결과(code 또는 error)가 올 때까지 막힌다. 시간이 다 되거나 close() 되면 null */
    fun await(): GoogleOAuth.Callback? {
        try {
            while (true) {
                val sock = server.accept()
                val cb = try { handle(sock) } catch (e: Exception) { null }   // 빈 연결·끊긴 연결은 무시
                if (cb != null) return cb
            }
        } catch (e: SocketTimeoutException) {
            return null
        } catch (e: Exception) {
            return null            // close() 로 닫힘
        } finally {
            runCatching { server.close() }
        }
    }

    fun close() { runCatching { server.close() } }

    /** 요청 한 건. 동의 결과면 그 값을, 아니면(파비콘 등) null. 응답도 여기서 보낸다 */
    private fun handle(sock: Socket): GoogleOAuth.Callback? = sock.use { s ->
        s.soTimeout = readTimeoutMs
        val reader = s.getInputStream().bufferedReader()
        val line = reader.readLine() ?: return null
        while (true) { val h = reader.readLine(); if (h.isNullOrEmpty()) break }   // 헤더는 버린다
        val cb = GoogleOAuth.parseCallback(line)
        val html = when {
            cb == null -> "<p>카드문자 전달</p>"
            cb.error != null -> "<p style='font-size:20px'>연결이 취소되었습니다. 앱으로 돌아가 다시 시도하세요.</p>"
            else -> "<meta http-equiv='refresh' content='1;url=$APP_LINK'>" +
                "<p style='font-size:20px'>연결 완료! 앱으로 돌아가세요.</p><p><a href='$APP_LINK'>앱 열기</a></p>"
        }
        val body = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'></head><body>$html</body></html>"
        val bytes = body.toByteArray(Charsets.UTF_8)
        s.getOutputStream().apply {
            write(("HTTP/1.1 ${if (cb == null) "404 Not Found" else "200 OK"}\r\nContent-Type: text/html; charset=utf-8\r\n" +
                "Content-Length: ${bytes.size}\r\nConnection: close\r\n\r\n").toByteArray())
            write(bytes); flush()
        }
        cb
    }

    companion object {
        /** 완료 페이지에서 앱으로 되돌아오는 링크 (매니페스트의 cardsms:// 스킴) */
        const val APP_LINK = "intent://connected#Intent;scheme=cardsms;package=dev.aioffice.cardsms;end"
    }
}
