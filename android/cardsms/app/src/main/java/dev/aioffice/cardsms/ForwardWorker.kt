package dev.aioffice.cardsms

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import dev.aioffice.cardsms.core.Failure
import dev.aioffice.cardsms.core.Outcome
import java.util.concurrent.TimeUnit

/** 문자 한 통을 지메일에 넣는 작업. 네트워크가 없으면 기다리고, 실패하면 30초·1분·2분… 늘려 가며 최대 20번. */
class ForwardWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val subject = inputData.getString(KEY_SUBJECT) ?: return Result.failure()
        val body = inputData.getString(KEY_BODY) ?: return Result.failure()
        val log = ForwardLog(applicationContext)
        val settings = SettingsStore(applicationContext).load()
        if (settings == null) { log.add(body, false, "설정 없음 — 설정 파일을 불러오세요"); return Result.failure() }

        val client = GmailClient(settings)
        val (token, tokenStatus) = client.accessToken()
        val status = if (token == null) tokenStatus else client.insert(token, subject, body)
        return when (Failure.classify(status)) {
            Outcome.OK -> { log.add(body, true, "전송"); Result.success() }
            Outcome.RETRY -> if (runAttemptCount + 1 >= MAX_ATTEMPTS) {
                log.add(body, false, "포기(${MAX_ATTEMPTS}회 실패, HTTP $status)"); Result.failure()
            } else { log.add(body, false, "재시도 예정 (HTTP $status)"); Result.retry() }
            Outcome.FAIL -> { log.add(body, false, if (token == null) "토큰 오류 HTTP $status — 설정 파일 다시 발급" else "거부 HTTP $status"); Result.failure() }
        }
    }

    companion object {
        const val KEY_SUBJECT = "subject"
        const val KEY_BODY = "body"
        const val MAX_ATTEMPTS = 20

        fun enqueue(ctx: Context, subject: String, body: String) {
            val req = OneTimeWorkRequestBuilder<ForwardWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .setInputData(workDataOf(KEY_SUBJECT to subject, KEY_BODY to body))
                .build()
            WorkManager.getInstance(ctx).enqueue(req)
        }
    }
}
