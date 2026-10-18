package com.mframa.air

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.gms.location.LocationServices
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.util.Locale

/**
 * Offline hospital list from assets/hospitals.json, sorted by haversine
 * distance to the last known location. Tap opens a geo: navigation intent.
 */
class HospitalsActivity : AppCompatActivity() {

    private val json = Json { ignoreUnknownKeys = true }
    private lateinit var adapter: HospitalAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hospitals)

        setSupportActionBar(findViewById(R.id.hospitals_toolbar))
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        adapter = HospitalAdapter { openInMaps(it) }
        val list = findViewById<RecyclerView>(R.id.hospitals_list)
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = adapter

        val hospitals = loadHospitals()
        if (hospitals == null) {
            findViewById<TextView>(R.id.hospitals_empty).visibility = View.VISIBLE
            return
        }
        resolveLocation { lat, lon -> adapter.submit(sortByDistance(hospitals, lat, lon)) }
    }

    private fun loadHospitals(): List<Hospital>? = try {
        val raw = assets.open("hospitals.json").bufferedReader(Charsets.UTF_8).use { it.readText() }
        json.decodeFromString(ListSerializer(Hospital.serializer()), raw)
    } catch (e: Exception) {
        null
    }

    private fun resolveLocation(cb: (Double, Double) -> Unit) {
        DoseStore(this).lastSample()?.let {
            cb(it.lat, it.lon)
            return
        }
        val granted = ContextCompat.checkSelfPermission(
            this, android.Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) {
            try {
                LocationServices.getFusedLocationProviderClient(this).lastLocation
                    .addOnSuccessListener { loc ->
                        if (loc != null) cb(loc.latitude, loc.longitude)
                        else cb(ACCRA_LAT, ACCRA_LON)
                    }
                    .addOnFailureListener { cb(ACCRA_LAT, ACCRA_LON) }
            } catch (e: SecurityException) {
                cb(ACCRA_LAT, ACCRA_LON)
            }
        } else {
            cb(ACCRA_LAT, ACCRA_LON)
        }
    }

    private fun sortByDistance(
        hospitals: List<Hospital>, lat: Double, lon: Double
    ): List<Pair<Hospital, Double>> =
        hospitals.map { it to DoseLogic.haversineKm(lat, lon, it.lat, it.lon) }
            .sortedBy { it.second }

    private fun openInMaps(h: Hospital) {
        val uri = Uri.parse("geo:${h.lat},${h.lon}?q=${h.lat},${h.lon}(${Uri.encode(h.name)})")
        val intent = Intent(Intent.ACTION_VIEW, uri)
        if (intent.resolveActivity(packageManager) != null) {
            startActivity(intent)
        } else {
            Toast.makeText(this, R.string.no_maps_app, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    companion object {
        private const val ACCRA_LAT = 5.6037
        private const val ACCRA_LON = -0.1870
    }

    private class HospitalAdapter(val onClick: (Hospital) -> Unit) :
        RecyclerView.Adapter<HospitalAdapter.VH>() {

        private val items = mutableListOf<Pair<Hospital, Double>>()

        fun submit(data: List<Pair<Hospital, Double>>) {
            items.clear()
            items.addAll(data)
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_hospital, parent, false)
            return VH(v)
        }

        override fun getItemCount(): Int = items.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val (h, dist) = items[position]
            holder.name.text = h.name
            holder.meta.text = buildString {
                append(h.type ?: "Hospital")
                if (h.open24) append(" · 24h")
                h.phone?.let { append(" · ").append(it) }
            }
            holder.distance.text = String.format(Locale.US, "%.1f km", dist)
            holder.itemView.setOnClickListener { onClick(h) }
        }

        class VH(v: View) : RecyclerView.ViewHolder(v) {
            val name: TextView = v.findViewById(R.id.hospital_name)
            val meta: TextView = v.findViewById(R.id.hospital_meta)
            val distance: TextView = v.findViewById(R.id.hospital_distance)
        }
    }
}
