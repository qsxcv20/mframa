package com.mframa.air

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.SeekBar
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.materialswitch.MaterialSwitch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class ExposureFragment : Fragment() {

    private lateinit var store: DoseStore
    private lateinit var toggle: MaterialSwitch
    private lateinit var toggleAlerts: MaterialSwitch
    private lateinit var seekThreshold: SeekBar
    private lateinit var txtThreshold: TextView
    private lateinit var txtPm25: TextView
    private lateinit var txtDose: TextView
    private lateinit var txtCigs: TextView
    private lateinit var barView: HourlyBarView
    private lateinit var adapter: SampleAdapter

    private val timeFmt = SimpleDateFormat("HH:mm", Locale.US)

    private val permLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
            val fine = grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
                ContextCompat.checkSelfPermission(
                    requireContext(), Manifest.permission.ACCESS_FINE_LOCATION
                ) == PackageManager.PERMISSION_GRANTED
            if (fine) startService() else toggle.isChecked = false
        }

    private val notifPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    private val doseReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            refresh()
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        val root = inflater.inflate(R.layout.fragment_exposure, container, false)
        store = DoseStore(requireContext())
        toggle = root.findViewById(R.id.toggle_service)
        txtPm25 = root.findViewById(R.id.txt_pm25)
        txtDose = root.findViewById(R.id.txt_dose)
        txtCigs = root.findViewById(R.id.txt_cigs)
        barView = root.findViewById(R.id.hourly_bars)
        val list = root.findViewById<RecyclerView>(R.id.samples_list)
        adapter = SampleAdapter(timeFmt)
        list.layoutManager = LinearLayoutManager(requireContext())
        list.adapter = adapter

        toggle.isChecked = store.serviceEnabled
        toggle.setOnCheckedChangeListener { _, checked ->
            if (checked) ensurePermissionsThenStart() else stopService()
        }

        toggleAlerts = root.findViewById(R.id.toggle_alerts)
        seekThreshold = root.findViewById(R.id.seek_threshold)
        txtThreshold = root.findViewById(R.id.txt_threshold)
        toggleAlerts.isChecked = AlertPrefs.enabled(requireContext())
        toggleAlerts.setOnCheckedChangeListener { _, checked ->
            AlertPrefs.setEnabled(requireContext(), checked)
            if (checked) ensureNotificationPermission()
        }
        seekThreshold.progress = AlertPrefs.thresholdIndex(requireContext())
        updateThresholdLabel()
        seekThreshold.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar, progress: Int, fromUser: Boolean) {
                AlertPrefs.setThreshold(requireContext(), AlertPrefs.THRESHOLD_STEPS[progress])
                updateThresholdLabel()
            }

            override fun onStartTrackingTouch(seekBar: SeekBar) {}
            override fun onStopTrackingTouch(seekBar: SeekBar) {}
        })

        root.findViewById<Button>(R.id.btn_hospitals).setOnClickListener {
            startActivity(Intent(requireContext(), HospitalsActivity::class.java))
        }
        refresh()
        return root
    }

    override fun onResume() {
        super.onResume()
        ContextCompat.registerReceiver(
            requireContext(), doseReceiver,
            IntentFilter(ExposureService.ACTION_DOSE_UPDATED),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        refresh()
    }

    override fun onPause() {
        requireContext().unregisterReceiver(doseReceiver)
        super.onPause()
    }

    private fun requiredPermissions(): Array<String> {
        val perms = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) perms.add(Manifest.permission.POST_NOTIFICATIONS)
        return perms.toTypedArray()
    }

    private fun ensurePermissionsThenStart() {
        val missing = requiredPermissions().filter {
            ContextCompat.checkSelfPermission(requireContext(), it) !=
                PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) startService() else permLauncher.launch(missing.toTypedArray())
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33) return
        if (ContextCompat.checkSelfPermission(
                requireContext(), Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        ) return
        notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun startService() {
        store.serviceEnabled = true
        ContextCompat.startForegroundService(
            requireContext(), Intent(requireContext(), ExposureService::class.java)
        )
    }

    private fun stopService() {
        store.serviceEnabled = false
        requireContext().stopService(Intent(requireContext(), ExposureService::class.java))
    }

    private fun updateThresholdLabel() {
        val current = AlertPrefs.threshold(requireContext())
        val idx = AlertPrefs.THRESHOLD_STEPS
            .indexOfFirst { it == current }
            .takeIf { it >= 0 } ?: AlertPrefs.thresholdIndex(requireContext())
        txtThreshold.text =
            resources.getStringArray(R.array.alerts_threshold_labels)[idx]
    }

    private fun refresh() {
        val samples = store.samplesToday()
        val dose = store.todayDose()
        val last = samples.lastOrNull()
        txtPm25.text = if (last != null)
            getString(R.string.exposure_pm25, last.pm25)
        else getString(R.string.exposure_no_data)
        txtDose.text = getString(R.string.exposure_dose, dose)
        txtCigs.text = getString(R.string.exposure_cigs, DoseLogic.cigaretteEquivalent(dose))
        barView.setSamples(samples)
        adapter.submit(samples.asReversed())
    }

    private class SampleAdapter(private val fmt: SimpleDateFormat) :
        RecyclerView.Adapter<SampleAdapter.VH>() {

        private val items = mutableListOf<DoseSample>()

        fun submit(data: List<DoseSample>) {
            items.clear()
            items.addAll(data)
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_sample, parent, false)
            return VH(v)
        }

        override fun getItemCount(): Int = items.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val s = items[position]
            holder.time.text = fmt.format(Date(s.t))
            holder.value.text = String.format(Locale.US, "%.0f µg/m³", s.pm25)
        }

        class VH(v: View) : RecyclerView.ViewHolder(v) {
            val time: TextView = v.findViewById(R.id.sample_time)
            val value: TextView = v.findViewById(R.id.sample_value)
        }
    }
}
