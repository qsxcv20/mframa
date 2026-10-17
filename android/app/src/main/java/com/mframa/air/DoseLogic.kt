package com.mframa.air

import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Pure Kotlin dose engine: grid interpolation, dose accumulation,
 * cigarette equivalence, alert thresholds. No Android dependencies.
 */
object DoseLogic {

    /** Cap on the integration gap so long outages do not inflate dose. */
    const val MAX_STEP_MS: Long = 60L * 60 * 1000

    /** Berkeley Earth rule: 22 µg/m³ over 24h ≈ 1 cigarette. */
    const val CIG_UG_H: Double = 22.0 * 24.0

    const val ADVISORY_PM25: Double = 55.0
    const val ADVISORY_DOSE: Double = 140.0
    const val MEDICAL_DOSE: Double = 330.0
    const val MEDICAL_PM25: Double = 150.0

    enum class AlertLevel { NONE, ADVISORY, STRONG_ADVISORY, MEDICAL }

    data class Evaluation(val level: AlertLevel, val reason: String)

    // ---- spatial --------------------------------------------------------

    fun haversineKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2).pow(2) +
            cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dLon / 2).pow(2)
        return 2 * r * asin(min(1.0, sqrt(a)))
    }

    /**
     * Bilinear interpolation over the PM2.5 grid. Rows run lat0 -> lat1,
     * columns lon0 -> lon1. Null cells degrade to IDW over the valid
     * corners of the containing cell, then to the nearest valid grid cell.
     */
    fun bilinear(grid: List<List<Double?>>, bbox: Bbox, step: Double, lat: Double, lon: Double): Double? {
        if (grid.isEmpty() || grid[0].isEmpty() || step <= 0) return null
        val rows = grid.size
        val cols = grid[0].size
        val fx = ((lon - bbox.lon0) / step).coerceIn(0.0, cols - 1.0)
        val fy = ((lat - bbox.lat0) / step).coerceIn(0.0, rows - 1.0)
        val x0 = floor(fx).toInt().coerceIn(0, cols - 1)
        val y0 = floor(fy).toInt().coerceIn(0, rows - 1)
        val x1 = (x0 + 1).coerceAtMost(cols - 1)
        val y1 = (y0 + 1).coerceAtMost(rows - 1)
        val tx = fx - x0
        val ty = fy - y0

        val v00 = grid[y0][x0]
        val v10 = grid[y0][x1]
        val v01 = grid[y1][x0]
        val v11 = grid[y1][x1]

        if (v00 != null && v10 != null && v01 != null && v11 != null) {
            return v00 * (1 - tx) * (1 - ty) + v10 * tx * (1 - ty) +
                v01 * (1 - tx) * ty + v11 * tx * ty
        }

        val corners = listOf(
            Triple(x0.toDouble(), y0.toDouble(), v00),
            Triple(x1.toDouble(), y0.toDouble(), v10),
            Triple(x0.toDouble(), y1.toDouble(), v01),
            Triple(x1.toDouble(), y1.toDouble(), v11)
        )
        var wsum = 0.0
        var sum = 0.0
        for ((cx, cy, v) in corners) {
            if (v == null) continue
            val d = sqrt((fx - cx) * (fx - cx) + (fy - cy) * (fy - cy))
            if (d < 1e-9) return v
            val w = 1.0 / (d * d)
            wsum += w
            sum += w * v
        }
        if (wsum > 0) return sum / wsum

        var best: Double? = null
        var bestD = Long.MAX_VALUE
        for (r in 0 until rows) {
            for (c in 0 until cols) {
                val v = grid[r][c] ?: continue
                val d = (r - y0).toLong() * (r - y0) + (c - x0).toLong() * (c - x0)
                if (d < bestD) {
                    bestD = d
                    best = v
                }
            }
        }
        return best
    }

    /** Inverse-distance-weighted estimate from stations (km, power 2). */
    fun idwStations(stations: List<Station>, lat: Double, lon: Double): Double? {
        val valid = stations.filter { it.pm25 != null }
        if (valid.isEmpty()) return null
        var wsum = 0.0
        var sum = 0.0
        for (s in valid) {
            val d = haversineKm(lat, lon, s.lat, s.lon)
            if (d < 1e-6) return s.pm25
            val w = 1.0 / (d * d)
            wsum += w
            sum += w * s.pm25!!
        }
        return sum / wsum
    }

    fun estimatePm25(snap: FieldSnapshot, lat: Double, lon: Double): Double? {
        bilinear(snap.grid.pm25, snap.bbox, snap.grid.step, lat, lon)?.let { return it }
        idwStations(snap.stations, lat, lon)?.let { return it }
        return snap.city_mean
    }

    // ---- dose -----------------------------------------------------------

    /** Dose increment in µg·h/m³ for a sample held over dtMs (capped). */
    fun doseIncrement(pm25: Double, dtMs: Long): Double {
        val dt = min(abs(dtMs), MAX_STEP_MS)
        return pm25 * dt / 3_600_000.0
    }

    fun cigaretteEquivalent(doseUhM3: Double): Double = doseUhM3 / CIG_UG_H

    // ---- thresholds -----------------------------------------------------

    fun evaluate(recent: List<DoseSample>, todayDose: Double, currentPm25: Double?): Evaluation {
        if (todayDose > MEDICAL_DOSE) {
            return Evaluation(AlertLevel.MEDICAL, "Today's dose ${todayDose.toInt()} µg·h/m³ exceeds ${MEDICAL_DOSE.toInt()}")
        }
        if (currentPm25 != null && currentPm25 > MEDICAL_PM25) {
            return Evaluation(AlertLevel.MEDICAL, "Current PM2.5 ${currentPm25.toInt()} µg/m³ exceeds ${MEDICAL_PM25.toInt()}")
        }
        if (todayDose > ADVISORY_DOSE) {
            return Evaluation(AlertLevel.STRONG_ADVISORY, "Today's dose ${todayDose.toInt()} µg·h/m³ exceeds ${ADVISORY_DOSE.toInt()}")
        }
        val last3 = recent.takeLast(3)
        if (last3.size == 3 && last3.all { it.pm25 > ADVISORY_PM25 }) {
            return Evaluation(AlertLevel.ADVISORY, "PM2.5 above ${ADVISORY_PM25.toInt()} µg/m³ for 3 consecutive samples")
        }
        return Evaluation(AlertLevel.NONE, "")
    }

    // ---- day rollover (Ghana is UTC+0, so UTC day == local day) ---------

    private val DAY_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")

    fun dayKey(tMs: Long): String =
        Instant.ofEpochMilli(tMs).atOffset(ZoneOffset.UTC).format(DAY_FMT)

    fun isSameUtcDay(t1Ms: Long, t2Ms: Long): Boolean = dayKey(t1Ms) == dayKey(t2Ms)
}
