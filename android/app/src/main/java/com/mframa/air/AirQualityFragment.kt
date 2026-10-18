package com.mframa.air

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.fragment.app.Fragment

class AirQualityFragment : Fragment() {

    private var webView: WebView? = null

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
              'a[href*="streamlit.io"], [class*="viewerBadge"]'
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
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        // Fallback pinch-to-zoom for the whole page (e.g. enlarging the map)
        web.settings.setSupportZoom(true)
        web.settings.builtInZoomControls = true
        web.settings.displayZoomControls = false
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
                loading.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String) {
                loading.visibility = View.GONE
                view.evaluateJavascript(hideBadgeJs, null)
            }
        }
        if (savedInstanceState == null) {
            web.loadUrl(BuildConfig.WEB_URL)
        }
        webView = web
        return root
    }

    override fun onDestroyView() {
        webView?.destroy()
        webView = null
        super.onDestroyView()
    }
}
