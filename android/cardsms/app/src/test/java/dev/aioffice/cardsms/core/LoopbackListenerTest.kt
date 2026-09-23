package dev.aioffice.cardsms.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class LoopbackListenerTest {
    private fun request(port: Int, line: String): String = Socket(InetAddress.getLoopbackAddress(), port).use { s ->
        s.getOutputStream().write("$line\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".toByteArray())
        s.getOutputStream().flush()
        s.getInputStream().bufferedReader().readText()
    }

    @Test fun `크롬의 빈 미리연결이 앞에 있어도 진짜 요청을 받는다`() {
        val l = LoopbackListener(readTimeoutMs = 300)
        val pool = Executors.newSingleThreadExecutor()
        val result = pool.submit<GoogleOAuth.Callback?> { l.await() }

        val idle1 = Socket(InetAddress.getLoopbackAddress(), l.port)   // 아무것도 안 보내는 연결
        val idle2 = Socket(InetAddress.getLoopbackAddress(), l.port)
        val res = request(l.port, "GET /?state=S&code=abc HTTP/1.1")
        assertTrue(res.startsWith("HTTP/1.1 200 OK"))
        assertTrue(res.contains("연결 완료"))

        val cb = result.get(10, TimeUnit.SECONDS)
        assertEquals("abc", cb?.code)
        assertEquals("S", cb?.state)
        idle1.close(); idle2.close(); l.close(); pool.shutdownNow()
    }

    @Test fun `관련 없는 요청(파비콘)은 404 로 답하고 계속 기다린다`() {
        val l = LoopbackListener(readTimeoutMs = 300)
        val pool = Executors.newSingleThreadExecutor()
        val result = pool.submit<GoogleOAuth.Callback?> { l.await() }
        assertTrue(request(l.port, "GET /favicon.ico HTTP/1.1").startsWith("HTTP/1.1 404"))
        request(l.port, "GET /?error=access_denied&state=S HTTP/1.1")
        assertEquals("access_denied", result.get(10, TimeUnit.SECONDS)?.error)
        l.close(); pool.shutdownNow()
    }

    @Test fun `닫으면 null 로 끝난다`() {
        val l = LoopbackListener(readTimeoutMs = 300)
        val pool = Executors.newSingleThreadExecutor()
        val result = pool.submit<GoogleOAuth.Callback?> { l.await() }
        Thread.sleep(100); l.close()
        assertNull(result.get(10, TimeUnit.SECONDS))
        pool.shutdownNow()
    }
}
