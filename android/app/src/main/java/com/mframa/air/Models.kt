package com.mframa.air

import kotlinx.serialization.Serializable

@Serializable
data class Bbox(val lat0: Double, val lat1: Double, val lon0: Double, val lon1: Double)

@Serializable
data class Grid(val step: Double, val pm25: List<List<Double?>>)

@Serializable
data class Station(
    val name: String,
    val lat: Double,
    val lon: Double,
    val pm25: Double? = null,
    val updated_utc: String? = null
)

@Serializable
data class FieldSnapshot(
    val generated_at_utc: String? = null,
    val bbox: Bbox,
    val grid: Grid,
    val stations: List<Station> = emptyList(),
    val city_mean: Double? = null
)

@Serializable
data class DoseSample(val t: Long, val lat: Double, val lon: Double, val pm25: Double)

@Serializable
data class Hospital(
    val name: String,
    val lat: Double,
    val lon: Double,
    val type: String? = null,
    val phone: String? = null,
    val open24: Boolean = false
)
