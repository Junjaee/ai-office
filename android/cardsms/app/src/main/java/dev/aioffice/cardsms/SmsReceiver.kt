package dev.aioffice.cardsms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import dev.aioffice.cardsms.core.SmsFilter

/** 문자가 오면 골라서 전송 작업을 예약한다. 여기서는 네트워크를 쓰지 않는다(수신기는 10초 안에 끝나야 함). */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val body = SmsFilter.joinParts(parts.map { it?.messageBody })
        val settings = SettingsStore(ctx).load() ?: return
        if (!SmsFilter.shouldForward(body, settings.keywords)) return
        ForwardWorker.enqueue(ctx, settings.subject, body)
    }
}
