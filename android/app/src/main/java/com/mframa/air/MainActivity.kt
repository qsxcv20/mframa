package com.mframa.air

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.google.android.material.bottomnavigation.BottomNavigationView
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private val airFragment: Fragment by lazy { AirQualityFragment() }
    private val exposureFragment: Fragment by lazy { ExposureFragment() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        NotificationHelper.ensureChannels(this)

        AlertWorker.schedule(this)
        lifecycleScope.launch { AlertWorker.checkNow(this@MainActivity) }
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }

        val nav = findViewById<BottomNavigationView>(R.id.bottom_nav)
        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction()
                .add(R.id.fragment_container, exposureFragment, "exposure")
                .hide(exposureFragment)
                .add(R.id.fragment_container, airFragment, "air")
                .commit()
        }
        nav.setOnItemSelectedListener { item ->
            val tx = supportFragmentManager.beginTransaction()
            when (item.itemId) {
                R.id.nav_air -> tx.hide(exposureFragment).show(airFragment)
                R.id.nav_exposure -> tx.hide(airFragment).show(exposureFragment)
                else -> return@setOnItemSelectedListener false
            }
            tx.commit()
            true
        }
    }
}
