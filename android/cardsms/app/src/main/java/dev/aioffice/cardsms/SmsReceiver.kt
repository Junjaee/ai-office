package dev.aioffice.cardsms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import dev.aioffice.cardsms.core.SmsFilter

/** 문자가 오면 등록 번호인지 보고 전송 작업을 예약한다. 여기서는 네트워크를 쓰지 않는다(수신기는 10초 안에 끝나야 함). */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        if (parts.isEmpty()) return
        val sender = parts[0]?.originatingAddress ?: ""
        val body = SmsFilter.joinParts(parts.map { it?.messageBody })
        val s = SettingsStore(ctx).load()
        if (!SmsFilter.shouldForward(sender, body, s.senderNumbers(), s.forwardAll, s.keywords)) return
        ForwardWorker.enqueue(ctx, ForwardWorker.SUBJECT, body, sender)
    }
}
