package com.mframa.air

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

/** Simple 24-bar hourly average PM2.5 chart, drawn directly on a View. */
class HourlyBarView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    private val barPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.mframa_primary)
    }
    private val emptyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.mframa_bar_empty)
    }

    private val hourly = DoubleArray(24) { Double.NaN }

    fun setSamples(samples: List<DoseSample>) {
        val sums = DoubleArray(24)
        val counts = IntArray(24)
        for (s in samples) {
            val h = ((s.t / 3_600_000L) % 24).toInt()
            sums[h] += s.pm25
            counts[h]++
        }
        for (h in 0 until 24) {
            hourly[h] = if (counts[h] > 0) sums[h] / counts[h] else Double.NaN
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width - paddingLeft - paddingRight
        val h = height - paddingTop - paddingBottom
        if (w <= 0 || h <= 0) return
        val maxV = hourly.filter { !it.isNaN() }.maxOrNull()?.coerceAtLeast(10.0) ?: 10.0
        val slot = w / 24f
        val barW = slot * 0.7f
        for (i in 0 until 24) {
            val left = paddingLeft + i * slot + (slot - barW) / 2f
            val v = hourly[i]
            if (v.isNaN()) {
                canvas.drawRect(
                    left, paddingTop + h - 2f, left + barW, paddingTop + h.toFloat(), emptyPaint
                )
            } else {
                val barH = (v / maxV * h).toFloat()
                canvas.drawRect(
                    left, paddingTop + h - barH, left + barW, paddingTop + h.toFloat(), barPaint
                )
            }
        }
    }
}
