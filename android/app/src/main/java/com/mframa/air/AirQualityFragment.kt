package com.mframa.air

import android.annotation.SuppressLint
import android.Manifest
import android.content.ActivityNotFoundException
import android.content.pm.PackageManager
import android.content.Intent
import android.os.Bundle
import android.text.format.DateUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.GeolocationPermissions
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebChromeClient
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.activity.result.contract.ActivityResultContracts
import java.util.Locale

class AirQualityFragment : Fragment() {

    private var webView: WebView? = null

    // The Streamlit page asks for HTML5 geolocation to auto-pick the nearest
    // monitor. WebView forwards that request here; we map it onto the Android
    // runtime location permission and answer the page's callback.
    private var pendingGeoOrigin: String? = null
    private var pendingGeoCallback: GeolocationPermissions.Callback? = null
    private val locationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
            val granted = grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
                grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
            pendingGeoCallback?.invoke(pendingGeoOrigin, granted, false)
            pendingGeoCallback = null
            pendingGeoOrigin = null
        }

    // The Streamlit Cloud wrapper redirects anonymous viewers through
    // share.streamlit.io to establish a session — that host must stay
    // loadable or the app never starts. Everything else (e.g. Telegram
    // t.me links, the "Hosted with Streamlit" badge) is handed to the
    // system browser instead of loading inside the WebView.
    private fun isAllowedHost(host: String?): Boolean {
        if (host == null) return false
        return host == "streamlit.app" || host.endsWith(".streamlit.app") ||
            host == "share.streamlit.io" || host == "ntfy.sh"
    }

    // Hides the viewer badge rendered by the Streamlit Cloud wrapper page
    // (outside the app iframe, so the web app's own CSS cannot reach it).
    private val hideBadgeJs = """
        (function() {
          function hideBadges() {
            document.querySelectorAll(
              'a[href*="streamlit.io"], [class*="viewerBadge"], ' +
              '[data-testid="stToolbar"], [data-testid="stHeader"], ' +
              '[data-testid="stAppDeployButton"], [data-testid="stDecoration"], ' +
              '[data-testid="stFooter"], [class*="embeddedAppMetaBlock"]'
            ).forEach(function(e) { e.style.display = 'none'; });
          }
          hideBadges();
          if (!window.__mframaBadgeHider) {
            window.__mframaBadgeHider = setInterval(hideBadges, 1500);
          }
        })();
    """.trimIndent()

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        val root = inflater.inflate(R.layout.fragment_air, container, false)
        val web = root.findViewById<WebView>(R.id.webview)
        val loading = root.findViewById<View>(R.id.loading_overlay)
        val errorOverlay = root.findViewById<View>(R.id.error_overlay)
        bindLaunchCard(root)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        // Allow the Streamlit page's "Use my location" button (HTML5
        // geolocation) to drive the nearest-station picker.
        web.settings.setGeolocationEnabled(true)
        // Fallback pinch-to-zoom for the whole page (e.g. enlarging the map)
        web.settings.setSupportZoom(true)
        web.settings.builtInZoomControls = true
        web.settings.displayZoomControls = false
        web.webChromeClient = object : WebChromeClient() {
            override fun onGeolocationPermissionsShowPrompt(
                origin: String?,
                callback: GeolocationPermissions.Callback
            ) {
                val hasPermission = ContextCompat.checkSelfPermission(
                    requireContext(), Manifest.permission.ACCESS_FINE_LOCATION
                ) == PackageManager.PERMISSION_GRANTED ||
                    ContextCompat.checkSelfPermission(
                        requireContext(), Manifest.permission.ACCESS_COARSE_LOCATION
                    ) == PackageManager.PERMISSION_GRANTED
                if (hasPermission) {
                    // Already granted (e.g. for exposure tracking) — answer now.
                    callback.invoke(origin, true, false)
                } else {
                    // Ask once; the launcher answers the page callback.
                    pendingGeoOrigin = origin
                    pendingGeoCallback = callback
                    locationPermissionLauncher.launch(
                        arrayOf(
                            Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION
                        )
                    )
                }
            }
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                if (!request.isForMainFrame) return false
                if (isAllowedHost(request.url.host)) return false
                val scheme = request.url.scheme
                if (scheme == "http" || scheme == "https") {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, request.url))
                    } catch (e: ActivityNotFoundException) {
                        // No browser installed — leave the link dead rather than crash.
                    }
                }
                return true
            }

            override fun onPageStarted(
                view: WebView,
                url: String,
                favicon: android.graphics.Bitmap?
            ) {
                errorOverlay.visibility = View.GONE
                loading.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String) {
                loading.visibility = View.GONE
                view.evaluateJavascript(hideBadgeJs, null)
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: android.webkit.WebResourceError
            ) {
                if (!request.isForMainFrame) return
                loading.visibility = View.GONE
                errorOverlay.visibility = View.VISIBLE
            }
        }
        root.findViewById<View>(R.id.btn_retry).setOnClickListener {
            errorOverlay.visibility = View.GONE
            if (web.url != null) web.reload() else loadWebApp(web)
        }
        val restored = savedInstanceState != null && web.restoreState(savedInstanceState) != null
        if (!restored) loadWebApp(web)
        webView = web
        return root
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView?.saveState(outState)
    }

    // ?from=app tells the web app it runs inside the native shell, so
    // it can hide ntfy/Telegram signup guidance in favor of the
    // built-in alerts on the My Exposure page. embed=true strips the
    // Streamlit toolbar (Fork/GitHub/menu) that page-injected JS
    // cannot reach inside the wrapper iframe.
    private fun loadWebApp(web: WebView) {
        val sep = if ('?' in BuildConfig.WEB_URL) '&' else '?'
        web.loadUrl(BuildConfig.WEB_URL + sep + "from=app&embed=true")
    }

    override fun onDestroyView() {
        webView?.destroy()
        webView = null
        super.onDestroyView()
    }

    // Fills the launch card with the last city reading cached by AlertWorker.
    // Without a cache (first install) it degrades to a plain "Loading…".
    private fun bindLaunchCard(root: View) {
        val cached = AlertPrefs.lastCityPm25(requireContext())
        if (cached == null) {
            root.findViewById<View>(R.id.txt_splash_pm25).visibility = View.GONE
            root.findViewById<View>(R.id.txt_splash_age).visibility = View.GONE
            root.findViewById<View>(R.id.txt_splash_threshold).visibility = View.GONE
            root.findViewById<View>(R.id.txt_splash_updating).visibility = View.GONE
            root.findViewById<View>(R.id.txt_splash_loading).visibility = View.VISIBLE
            return
        }
        root.findViewById<TextView>(R.id.txt_splash_pm25).text =
            String.format(Locale.US, "%.0f µg/m³", cached)
        root.findViewById<TextView>(R.id.txt_splash_age).text =
            DateUtils.getRelativeTimeSpanString(AlertPrefs.lastCityTs(requireContext()))
        val labels = resources.getStringArray(R.array.alerts_threshold_labels)
        root.findViewById<TextView>(R.id.txt_splash_threshold).text =
            labels[AlertPrefs.labelIndex(requireContext())]
    }
}
