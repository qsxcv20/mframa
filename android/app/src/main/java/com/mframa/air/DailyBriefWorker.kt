package com.mframa.air

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.time.Instant
import java.util.Calendar
import java.util.concurrent.TimeUnit

/**
 * Fully local daily morning brief: once per day around 06:00 local time
 * (WorkManager does not guarantee the exact minute) the worker reads the
 * shared field.json and posts one notification with the city PM2.5 mean,
 * its AQI band, and one line of advice. No account, no third-party push.
 * If the data is more than 6h old (a gap likely caused by a power cut),
 * the advice switches to the outage-night wording.
 */
class DailyBriefWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        return try {
            if (!AlertPrefs.briefEnabled(applicationContext)) return Result.success()
            val snap = FieldClient(applicationContext).get() ?: return Result.retry()
            val city = snap.city_mean
                ?: snap.stations.mapNotNull { it.pm25 }
                    .takeIf { it.isNotEmpty() }?.average()
                ?: return Result.success()
            val pm = city.toInt()
            val level = aqiLevel(applicationContext, city)
            val stale = isStale(snap)
            val text = when {
                stale -> applicationContext.getString(R.string.brief_text_stale, pm, level)
                city <= GOOD_LIMIT -> applicationContext.getString(
                    R.string.brief_text_good, pm, level
                )
                else -> applicationContext.getString(R.string.brief_text_bad, pm, level)
            }
            NotificationHelper.ensureChannels(applicationContext)
            NotificationHelper.postDailyBrief(
                applicationContext,
                applicationContext.getString(R.string.brief_title),
                text
            )
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }

    companion object {
        private const val WORK_NAME = "mframa_daily_brief"
        private const val BRIEF_HOUR = 6
        private const val STALE_MS = 6L * 60 * 60 * 1000
        private const val GOOD_LIMIT = 35.0 // Ghana EPA 24h standard, same as web app

        fun schedule(context: Context) {
            val now = Calendar.getInstance()
            val next = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, BRIEF_HOUR)
                set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
                if (!after(now)) add(Calendar.DAY_OF_YEAR, 1)
            }
            val req = PeriodicWorkRequestBuilder<DailyBriefWorker>(1, TimeUnit.DAYS)
                .setInitialDelay(next.timeInMillis - now.timeInMillis, TimeUnit.MILLISECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, req
            )
        }

        private fun isStale(snap: FieldSnapshot): Boolean {
            val newest = listOfNotNull(
                snap.generated_at_utc,
                snap.stations.mapNotNull { it.updated_utc }.maxOrNull()
            ).mapNotNull { parseUtc(it) }.maxOrNull() ?: return false
            return System.currentTimeMillis() - newest > STALE_MS
        }

        private fun parseUtc(s: String): Long? = try {
            Instant.parse(s).toEpochMilli()
        } catch (e: Exception) {
            null
        }

        private fun aqiLevel(context: Context, pm25: Double): String = context.getString(
            when {
                pm25 <= 12.0 -> R.string.brief_level_good
                pm25 <= 35.4 -> R.string.brief_level_moderate
                pm25 <= 55.4 -> R.string.brief_level_usg
                pm25 <= 150.4 -> R.string.brief_level_unhealthy
                else -> R.string.brief_level_very
            }
        )
    }
}
