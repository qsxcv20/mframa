package com.mframa.air

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.google.android.material.bottomnavigation.BottomNavigationView
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private var airFragment: Fragment? = null
    private var exposureFragment: Fragment? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        NotificationHelper.ensureChannels(this)

        AlertWorker.schedule(this)
        DailyBriefWorker.schedule(this)
        lifecycleScope.launch { AlertWorker.checkNow(this@MainActivity) }

        val nav = findViewById<BottomNavigationView>(R.id.bottom_nav)
        if (savedInstanceState == null) {
            val air = AirQualityFragment()
            val exposure = ExposureFragment()
            supportFragmentManager.beginTransaction()
                .add(R.id.fragment_container, exposure, "exposure")
                .hide(exposure)
                .add(R.id.fragment_container, air, "air")
                .commit()
            airFragment = air
            exposureFragment = exposure
        } else {
            airFragment = supportFragmentManager.findFragmentByTag("air")
            exposureFragment = supportFragmentManager.findFragmentByTag("exposure")
        }
        nav.setOnItemSelectedListener { item ->
            val air = airFragment ?: return@setOnItemSelectedListener false
            val exposure = exposureFragment ?: return@setOnItemSelectedListener false
            val tx = supportFragmentManager.beginTransaction()
            when (item.itemId) {
                R.id.nav_air -> tx.hide(exposure).show(air)
                R.id.nav_exposure -> tx.hide(air).show(exposure)
                else -> return@setOnItemSelectedListener false
            }
            tx.commit()
            true
        }
    }
}
