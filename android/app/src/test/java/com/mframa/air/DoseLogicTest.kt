package com.mframa.air

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DoseLogicTest {

    private val bbox = Bbox(lat0 = 5.45, lat1 = 5.75, lon0 = -0.40, lon1 = 0.10)
    private val step = 0.01

    private fun gridOf(v: Double, rows: Int = 4, cols: Int = 4): List<List<Double?>> =
        List(rows) { List(cols) { v } }

    // ---- bilinear --------------------------------------------------------

    @Test
    fun `bilinear exact at grid point`() {
        val grid = gridOf(30.0)
        val v = DoseLogic.bilinear(grid, bbox, step, 5.47, -0.38)
        assertEquals(30.0, v!!, 1e-9)
    }

    @Test
    fun `bilinear center of cell averages corners`() {
        val grid: List<List<Double?>> = listOf(
            listOf(10.0, 20.0),
            listOf(30.0, 40.0)
        )
        val b = Bbox(lat0 = 0.0, lat1 = 1.0, lon0 = 0.0, lon1 = 1.0)
        val v = DoseLogic.bilinear(grid, b, 1.0, 0.5, 0.5)
        assertEquals(25.0, v!!, 1e-9)
    }

    // Query exactly on the null corner of a degenerate lookup returns the
    // first valid corner; a centered query averages the three valid corners.
    @Test
    fun `bilinear one null corner degrades to idw of valid corners`() {
        val grid: List<List<Double?>> = listOf(
            listOf(null, 20.0),
            listOf(30.0, 40.0)
        )
        val b = Bbox(lat0 = 0.0, lat1 = 1.0, lon0 = 0.0, lon1 = 1.0)
        val v = DoseLogic.bilinear(grid, b, 0.5, 0.25, 0.25)
        assertEquals(30.0, v!!, 1e-9) // equidistant -> mean of 20, 30, 40
    }

    @Test
    fun `bilinear all corners null falls back to nearest valid grid cell`() {
        val grid: List<List<Double?>> = listOf(
            listOf(null, null, null),
            listOf(null, null, null),
            listOf(null, null, 99.0)
        )
        val b = Bbox(lat0 = 0.0, lat1 = 2.0, lon0 = 0.0, lon1 = 2.0)
        val v = DoseLogic.bilinear(grid, b, 1.0, 0.0, 0.0)
        assertEquals(99.0, v!!, 1e-9)
    }

    @Test
    fun `bilinear fully null grid returns null`() {
        val grid: List<List<Double?>> = listOf(listOf(null, null), listOf(null, null))
        assertNull(DoseLogic.bilinear(grid, bbox, step, 5.5, -0.2))
    }

    @Test
    fun `bilinear empty grid returns null`() {
        assertNull(DoseLogic.bilinear(emptyList(), bbox, step, 5.5, -0.2))
    }

    // ---- station IDW ------------------------------------------------------

    @Test
    fun `idw stations weights nearer station more`() {
        val stations = listOf(
            Station("near", 5.50, -0.20, 40.0),
            Station("far", 5.70, 0.05, 80.0)
        )
        val v = DoseLogic.idwStations(stations, 5.501, -0.20)!!
        assertTrue(v < 50.0) // strongly pulled toward the near station
    }

    @Test
    fun `idw stations ignores null pm25 and empty list returns null`() {
        assertNull(DoseLogic.idwStations(emptyList(), 5.5, -0.2))
        val onlyNull = listOf(Station("x", 5.5, -0.2, null))
        assertNull(DoseLogic.idwStations(onlyNull, 5.5, -0.2))
    }

    @Test
    fun `estimatePm25 falls back grid to stations to city mean`() {
        val nullGrid = Grid(step, listOf(listOf(null, null), listOf(null, null)))
        val st = Station("s", 5.5, -0.2, 42.0)
        val withStations = FieldSnapshot(null, bbox, nullGrid, listOf(st), 28.4)
        assertEquals(42.0, DoseLogic.estimatePm25(withStations, 5.5, -0.2)!!, 1e-9)

        val noStations = FieldSnapshot(null, bbox, nullGrid, emptyList(), 28.4)
        assertEquals(28.4, DoseLogic.estimatePm25(noStations, 5.5, -0.2)!!, 1e-9)

        val nothing = FieldSnapshot(null, bbox, nullGrid, emptyList(), null)
        assertNull(DoseLogic.estimatePm25(nothing, 5.5, -0.2))
    }

    // ---- dose -------------------------------------------------------------

    @Test
    fun `dose increment is pm25 times hours`() {
        val d = DoseLogic.doseIncrement(50.0, 15L * 60 * 1000)
        assertEquals(12.5, d, 1e-9)
    }

    @Test
    fun `dose increment caps gap at one hour`() {
        val d = DoseLogic.doseIncrement(50.0, 6L * 60 * 60 * 1000)
        assertEquals(50.0, d, 1e-9)
    }

    @Test
    fun `cigarette equivalent follows berkeley earth rule`() {
        assertEquals(1.0, DoseLogic.cigaretteEquivalent(528.0), 1e-9)
        assertEquals(0.5, DoseLogic.cigaretteEquivalent(264.0), 1e-9)
    }

    // ---- thresholds --------------------------------------------------------

    private fun samples(vararg pm: Double): List<DoseSample> =
        pm.mapIndexed { i, v -> DoseSample(i * 900_000L, 5.5, -0.2, v) }

    @Test
    fun `advisory after 3 consecutive samples above 55`() {
        val e = DoseLogic.evaluate(samples(60.0, 58.0, 56.0), 50.0, 56.0)
        assertEquals(DoseLogic.AlertLevel.ADVISORY, e.level)
    }

    @Test
    fun `no advisory when one of last three is low`() {
        val e = DoseLogic.evaluate(samples(60.0, 30.0, 56.0), 50.0, 56.0)
        assertEquals(DoseLogic.AlertLevel.NONE, e.level)
    }

    @Test
    fun `no advisory with fewer than 3 samples`() {
        val e = DoseLogic.evaluate(samples(60.0, 60.0), 0.0, 60.0)
        assertEquals(DoseLogic.AlertLevel.NONE, e.level)
    }

    @Test
    fun `strong advisory when dose above 140`() {
        val e = DoseLogic.evaluate(samples(10.0), 141.0, 10.0)
        assertEquals(DoseLogic.AlertLevel.STRONG_ADVISORY, e.level)
    }

    @Test
    fun `medical when dose above 330`() {
        val e = DoseLogic.evaluate(samples(10.0), 331.0, 10.0)
        assertEquals(DoseLogic.AlertLevel.MEDICAL, e.level)
    }

    @Test
    fun `medical when current pm25 above 150 regardless of dose`() {
        val e = DoseLogic.evaluate(samples(20.0), 10.0, 151.0)
        assertEquals(DoseLogic.AlertLevel.MEDICAL, e.level)
    }

    @Test
    fun `medical beats advisory precedence`() {
        val e = DoseLogic.evaluate(samples(60.0, 60.0, 60.0), 331.0, 60.0)
        assertEquals(DoseLogic.AlertLevel.MEDICAL, e.level)
    }

    @Test
    fun `none under normal conditions`() {
        val e = DoseLogic.evaluate(samples(20.0, 25.0, 30.0), 40.0, 30.0)
        assertEquals(DoseLogic.AlertLevel.NONE, e.level)
    }

    // ---- day rollover -------------------------------------------------------

    @Test
    fun `utc day key changes at midnight`() {
        // 2026-10-18T23:59:59Z vs 2026-10-19T00:00:00Z
        val before = 1792367999000L
        val after = 1792368000000L
        assertEquals("2026-10-18", DoseLogic.dayKey(before))
        assertEquals("2026-10-19", DoseLogic.dayKey(after))
        assertTrue(!DoseLogic.isSameUtcDay(before, after))
    }

    @Test
    fun `same utc day within day`() {
        val morning = 1792368000000L
        val evening = morning + 12L * 60 * 60 * 1000
        assertTrue(DoseLogic.isSameUtcDay(morning, evening))
    }

    // ---- haversine -----------------------------------------------------------

    @Test
    fun `haversine accra to kumasi is roughly 200km`() {
        val d = DoseLogic.haversineKm(5.6037, -0.1870, 6.6885, -1.6244)
        assertEquals(200.0, d, 15.0)
    }

    @Test
    fun `haversine zero for same point`() {
        assertEquals(0.0, DoseLogic.haversineKm(5.6, -0.18, 5.6, -0.18), 1e-9)
    }
}
