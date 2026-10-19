package com.mframa.air

import android.content.Context
import android.content.SharedPreferences

/** User-tunable city air alert settings, stored in SharedPreferences. */
object AlertPrefs {

    private const val FILE = "mframa_alerts"
    private const val KEY_ENABLED = "alerts_enabled"
    private const val KEY_THRESHOLD = "alerts_threshold"
    private const val KEY_LAST_NOTIFY = "alerts_last_notify"
    private const val KEY_LAST_CITY_PM25 = "alerts_last_city_pm25"
    private const val KEY_LAST_CITY_TS = "alerts_last_city_ts"
    private const val KEY_BRIEF_ENABLED = "brief_enabled"

    const val DEFAULT_THRESHOLD = 35f

    val THRESHOLD_STEPS = floatArrayOf(15f, 25f, 35f, 55f, 75f, 100f, 150f)

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun enabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ENABLED, true)

    fun setEnabled(context: Context, v: Boolean) =
        prefs(context).edit().putBoolean(KEY_ENABLED, v).apply()

    fun briefEnabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_BRIEF_ENABLED, true)

    fun setBriefEnabled(context: Context, v: Boolean) =
        prefs(context).edit().putBoolean(KEY_BRIEF_ENABLED, v).apply()

    fun threshold(context: Context): Float =
        prefs(context).getFloat(KEY_THRESHOLD, DEFAULT_THRESHOLD)

    fun setThreshold(context: Context, v: Float) =
        prefs(context).edit().putFloat(KEY_THRESHOLD, v).apply()

    fun thresholdIndex(context: Context): Int {
        val current = threshold(context)
        return THRESHOLD_STEPS.indexOfFirst { it >= current }
            .takeIf { it >= 0 } ?: THRESHOLD_STEPS.indexOfFirst { it == DEFAULT_THRESHOLD }
    }

    /** Index into THRESHOLD_STEPS / alerts_threshold_labels for the current threshold. */
    fun labelIndex(context: Context): Int {
        val current = threshold(context)
        return THRESHOLD_STEPS.indexOfFirst { it == current }
            .takeIf { it >= 0 } ?: thresholdIndex(context)
    }

    /** Latest city-wide PM2.5 reading cached by AlertWorker, for the launch card. */
    fun setLastCity(context: Context, pm25: Double, ts: Long = System.currentTimeMillis()) =
        prefs(context).edit()
            .putFloat(KEY_LAST_CITY_PM25, pm25.toFloat())
            .putLong(KEY_LAST_CITY_TS, ts)
            .apply()

    fun lastCityPm25(context: Context): Float? =
        if (prefs(context).contains(KEY_LAST_CITY_PM25))
            prefs(context).getFloat(KEY_LAST_CITY_PM25, 0f)
        else null

    fun lastCityTs(context: Context): Long =
        prefs(context).getLong(KEY_LAST_CITY_TS, 0L)

    fun lastNotify(context: Context): Long =
        prefs(context).getLong(KEY_LAST_NOTIFY, 0L)

    fun markNotified(context: Context, t: Long = System.currentTimeMillis()) =
        prefs(context).edit().putLong(KEY_LAST_NOTIFY, t).apply()
}
