package com.mframa.air

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Fetches field.json with a 15-minute in-memory reuse window and a disk
 * cache fallback. Never throws: returns null when nothing is available.
 */
class FieldClient(private val context: Context) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()
    private val json = Json { ignoreUnknownKeys = true }
    private val cacheFile: File get() = File(context.filesDir, "field_cache.json")

    @Volatile private var memSnapshot: FieldSnapshot? = null
    @Volatile private var memFetchedAt: Long = 0L

    companion object {
        private const val MEM_TTL_MS = 15L * 60 * 1000
    }

    suspend fun get(url: String = BuildConfig.FIELD_JSON_URL): FieldSnapshot? =
        withContext(Dispatchers.IO) {
            val now = System.currentTimeMillis()
            memSnapshot?.let { if (now - memFetchedAt < MEM_TTL_MS) return@withContext it }

            val fresh = fetch(url)
            if (fresh != null) {
                memSnapshot = fresh
                memFetchedAt = now
                return@withContext fresh
            }
            memSnapshot?.let { return@withContext it }
            readDiskCache()
        }

    private fun fetch(url: String): FieldSnapshot? {
        return try {
            val body = client.newCall(Request.Builder().url(url).build()).execute().use { resp ->
                if (!resp.isSuccessful) null else resp.body?.string()
            } ?: return null
            if (body.length > 512 * 1024) return null
            val snap = json.decodeFromString(FieldSnapshot.serializer(), body)
            try {
                cacheFile.writeText(body, Charsets.UTF_8)
            } catch (_: Exception) {
            }
            snap
        } catch (e: Exception) {
            null
        }
    }

    private fun readDiskCache(): FieldSnapshot? = try {
        if (!cacheFile.exists()) null
        else json.decodeFromString(FieldSnapshot.serializer(), cacheFile.readText(Charsets.UTF_8))
    } catch (e: Exception) {
        null
    }
}
