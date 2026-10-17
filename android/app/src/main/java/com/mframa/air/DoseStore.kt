package com.mframa.air

import android.content.Context
import android.content.SharedPreferences
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * SharedPreferences-backed store: today's samples + dose, archived daily
 * totals, and the service on/off flag. Day rollover is automatic (UTC).
 */
class DoseStore(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("mframa_dose", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true }

    companion object {
        private const val KEY_DAY = "day_key"
        private const val KEY_TODAY_DOSE = "today_dose"
        private const val KEY_SAMPLES = "samples_today"
        private const val KEY_DAILY = "daily_totals"
        private const val KEY_SERVICE_ENABLED = "service_enabled"
        private const val MAX_SAMPLES = 96 // 24h at 15min cadence
    }

    var serviceEnabled: Boolean
        get() = prefs.getBoolean(KEY_SERVICE_ENABLED, false)
        set(v) = prefs.edit().putBoolean(KEY_SERVICE_ENABLED, v).apply()

    fun samplesToday(): List<DoseSample> {
        val raw = prefs.getString(KEY_SAMPLES, null) ?: return emptyList()
        return try {
            json.decodeFromString(ListSerializer(DoseSample.serializer()), raw)
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun todayDose(): Double = prefs.getFloat(KEY_TODAY_DOSE, 0f).toDouble()

    fun dailyTotals(): Map<String, Double> {
        val raw = prefs.getString(KEY_DAILY, null) ?: return emptyMap()
        return try {
            json.decodeFromString(
                MapSerializer(String.serializer(), Double.serializer()), raw
            )
        } catch (e: Exception) {
            emptyMap()
        }
    }

    fun lastSample(): DoseSample? = samplesToday().lastOrNull()

    /** Adds a sample, archiving yesterday if the UTC day rolled over. */
    @Synchronized
    fun addSample(t: Long, lat: Double, lon: Double, pm25: Double): Double {
        val nowKey = DoseLogic.dayKey(t)
        val storedKey = prefs.getString(KEY_DAY, null)
        var dose = todayDose()
        var samples = samplesToday()

        if (storedKey != null && storedKey != nowKey) {
            val daily = dailyTotals().toMutableMap()
            if (dose > 0) daily[storedKey] = dose
            prefs.edit()
                .putString(KEY_DAILY, json.encodeToString(MapSerializer(String.serializer(), Double.serializer()), daily))
                .apply()
            dose = 0.0
            samples = emptyList()
        }

        val last = samples.lastOrNull()
        if (last != null) {
            dose += DoseLogic.doseIncrement(pm25, t - last.t)
        }
        samples = (samples + DoseSample(t, lat, lon, pm25)).takeLast(MAX_SAMPLES)

        prefs.edit()
            .putString(KEY_DAY, nowKey)
            .putFloat(KEY_TODAY_DOSE, dose.toFloat())
            .putString(KEY_SAMPLES, json.encodeToString(ListSerializer(DoseSample.serializer()), samples))
            .apply()
        return dose
    }
}
