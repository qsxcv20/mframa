package com.mframa.air

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Periodically checks the shared field.json for city-wide PM2.5 and posts a
 * local notification when it exceeds the user's own threshold. No account,
 * no phone number, no third-party push service: the app polls the same data
 * file the website uses. WorkManager keeps the schedule across reboots.
 */
class AlertWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        checkNow(applicationContext)
        return Result.success()
    }

    companion object {
        private const val WORK_NAME = "mframa_city_air_alerts"
        private const val COOLDOWN_MS = 6L * 60 * 60 * 1000

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<AlertWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, req
            )
        }

        /** One immediate check (app start). Never throws. */
        suspend fun checkNow(context: Context) {
            try {
                if (!AlertPrefs.enabled(context)) return
                val snap = FieldClient(context).get() ?: return
                val city = snap.city_mean
                    ?: snap.stations.mapNotNull { it.pm25 }
                        .takeIf { it.isNotEmpty() }?.average()
                    ?: return
                val threshold = AlertPrefs.threshold(context).toDouble()
                if (city < threshold) return
                val now = System.currentTimeMillis()
                if (now - AlertPrefs.lastNotify(context) < COOLDOWN_MS) return
                AlertPrefs.markNotified(context, now)
                NotificationHelper.ensureChannels(context)
                NotificationHelper.postCityAlert(
                    context,
                    context.getString(R.string.notif_city_title),
                    context.getString(
                        R.string.notif_city_text, city.toInt(), threshold.toInt()
                    )
                )
            } catch (_: Exception) {
            }
        }
    }
}
