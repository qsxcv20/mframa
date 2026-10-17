package com.mframa.air

import android.Manifest
import android.content.pm.PackageManager
import android.location.Location
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Foreground location service. Balanced power accuracy, 15min interval,
 * no wake lock: a fix may arrive while dozing, the dose math caps gaps.
 */
class ExposureService : LifecycleService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var fused: FusedLocationProviderClient
    private lateinit var store: DoseStore
    private lateinit var fieldClient: FieldClient

    companion object {
        const val ACTION_DOSE_UPDATED = "com.mframa.air.DOSE_UPDATED"
        private const val INTERVAL_MS = 15L * 60 * 1000
        private const val FASTEST_MS = 10L * 60 * 1000
    }

    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            result.lastLocation?.let { handleLocation(it) }
        }
    }

    override fun onCreate() {
        super.onCreate()
        NotificationHelper.ensureChannels(this)
        fused = LocationServices.getFusedLocationProviderClient(this)
        store = DoseStore(this)
        fieldClient = FieldClient(this)
    }

    override fun onStartCommand(intent: android.content.Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        startForeground(NotificationHelper.ID_SERVICE, NotificationHelper.serviceNotification(this))
        subscribeLocation()
        return START_STICKY
    }

    private fun subscribeLocation() {
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            stopSelf()
            return
        }
        val req = LocationRequest.Builder(Priority.PRIORITY_BALANCED_POWER_ACCURACY, INTERVAL_MS)
            .setMinUpdateIntervalMillis(FASTEST_MS)
            .build()
        try {
            fused.requestLocationUpdates(req, callback, Looper.getMainLooper())
        } catch (e: SecurityException) {
            stopSelf()
        }
    }

    private fun handleLocation(loc: Location) {
        scope.launch {
            val snap = fieldClient.get()
            val pm25 = snap?.let { DoseLogic.estimatePm25(it, loc.latitude, loc.longitude) }
            if (pm25 == null) {
                NotificationHelper.postAdvisory(
                    this@ExposureService,
                    getString(R.string.notif_retry_title),
                    getString(R.string.notif_retry_text)
                )
                return@launch
            }
            val dose = store.addSample(System.currentTimeMillis(), loc.latitude, loc.longitude, pm25)
            val eval = DoseLogic.evaluate(store.samplesToday(), dose, pm25)
            when (eval.level) {
                DoseLogic.AlertLevel.MEDICAL ->
                    NotificationHelper.postHealthAlert(
                        this@ExposureService,
                        getString(R.string.notif_health_title),
                        eval.reason + " " + getString(R.string.notif_health_suffix)
                    )
                DoseLogic.AlertLevel.STRONG_ADVISORY ->
                    NotificationHelper.postAdvisory(
                        this@ExposureService,
                        getString(R.string.notif_strong_title),
                        eval.reason
                    )
                DoseLogic.AlertLevel.ADVISORY ->
                    NotificationHelper.postAdvisory(
                        this@ExposureService,
                        getString(R.string.notif_advisory_title),
                        eval.reason
                    )
                DoseLogic.AlertLevel.NONE -> Unit
            }
            this@ExposureService.sendBroadcast(
                android.content.Intent(ACTION_DOSE_UPDATED).setPackage(packageName)
            )
        }
    }

    override fun onDestroy() {
        fused.removeLocationUpdates(callback)
        scope.cancel()
        super.onDestroy()
    }
}
