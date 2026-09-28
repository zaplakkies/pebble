package home.pebble.agent

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Process
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

/**
 * One run of the agent: read what the OS recorded since the last run, queue it, sync.
 * Started every ~15 minutes by PebbleWorker and whenever the app screen opens.
 */
object Agent {
    private const val TAG = "PebbleAgent"
    private const val BATCH = 500
    private val lock = Any()

    fun run(context: Context) = synchronized(lock) {
        val prefs = Prefs(context)
        if (!prefs.paired) return
        try {
            collect(context, prefs)
        } catch (e: Exception) {
            Log.e(TAG, "collect failed", e)
        }
        sync(context, prefs)
        TodayWidget.refresh(context)
    }

    fun hasUsageAccess(context: Context): Boolean {
        val ops = context.getSystemService(AppOpsManager::class.java)
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        } else {
            @Suppress("DEPRECATION")
            ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun collect(context: Context, prefs: Prefs) {
        val store = Store.get(context)
        val now = RunClock(System.currentTimeMillis(), SystemClock.elapsedRealtime(),
            Settings.Global.getInt(context.contentResolver, Settings.Global.BOOT_COUNT, 0))
        val permissionOk = hasUsageAccess(context)
        val previous = prefs.foreground ?: Foreground(null, now.wall)
        // A clock set backwards can put the checkpoint in the future.
        val from = previous.since.coerceAtMost(now.wall)

        val collected = if (permissionOk) {
            Sessions.collect(readEvents(context, from, now.wall), from, now.wall, previous)
        } else {
            Collected(emptyList(), emptyList(), previous)
        }
        val events = Checks.events(prefs.lastRun, now, from, collected, permissionOk, prefs.permissionOk)

        val labels = AppLabels(context.packageManager)
        val records = collected.spans.map { s ->
            s.start to mapOf<String, Any?>("kind" to "session", "start" to Iso.format(s.start),
                "end" to Iso.format(s.end), "app_id" to s.pkg, "app_name" to labels[s.pkg],
                "title" to null, "url" to null, "document" to null)
        } + events.map { e ->
            e.at to mapOf<String, Any?>("kind" to "event", "at" to Iso.format(e.at), "type" to e.type,
                "details" to e.details)
        }
        store.add(records.sortedBy { it.first }.map { it.second })

        // Without usage access the checkpoint stays put, so the history is picked up
        // (backfilled) once access is back.
        if (permissionOk) prefs.foreground = collected.foreground
        prefs.lastRun = now
        prefs.permissionOk = permissionOk
    }

    private fun readEvents(context: Context, from: Long, to: Long): List<UsageEv> {
        val usm = context.getSystemService(UsageStatsManager::class.java)
        val events = usm.queryEvents(from, to) ?: return emptyList()
        val out = mutableListOf<UsageEv>()
        val e = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            out += UsageEv(e.timeStamp, e.eventType, e.packageName ?: "")
        }
        return out
    }

    fun sync(context: Context, prefs: Prefs = Prefs(context)) {
        val store = Store.get(context)
        val server = prefs.server ?: return
        try {
            do {
                val batch = store.pending(BATCH)
                val body = JSONObject()
                    .put("agent_version", BuildConfig.VERSION_NAME)
                    .put("device_time", Iso.format(System.currentTimeMillis()))
                    .put("monotonic_s", SystemClock.elapsedRealtime() / 1000.0)
                    .put("records", JSONArray(batch.map { JSONObject(it.second) }))
                val r = Api.request("POST", "$server/api/v1/sync", prefs.token, prefs.installId,
                    body.toString())
                if (batch.isNotEmpty()) {
                    store.acknowledge(minOf(r.optLong("accepted_through_seq", 0), batch.last().first))
                }
                r.optJSONArray("rejected")?.let { a ->
                    for (i in 0 until a.length()) Log.w(TAG, "server rejected record ${a.getJSONObject(i)}")
                }
                r.optJSONObject("today")?.let {
                    prefs.serverToday = ServerToday(it.getString("date"), it.getLong("used_s"),
                        if (it.isNull("limit_s")) null else it.getLong("limit_s"))
                }
                r.optJSONArray("exclusions")?.let { prefs.exclusions = Prefs.exclusionsFrom(it) }
                prefs.lastSync = System.currentTimeMillis()
                prefs.lastError = null
            } while (batch.size == BATCH && store.pendingCount() > 0)
        } catch (e: ApiError) {
            Log.w(TAG, "sync failed: ${e.message}")
            prefs.lastError = e.message
        }
    }

    fun today(context: Context): TodayStatus {
        val prefs = Prefs(context)
        return Today.status(prefs.serverToday, prefs.exclusions, Store.get(context).pendingSessions(),
            System.currentTimeMillis())
    }

    /** App names ("YouTube") for package names, cached for one run. */
    private class AppLabels(private val pm: PackageManager) {
        private val cache = HashMap<String, String?>()
        operator fun get(pkg: String): String? = cache.getOrPut(pkg) {
            try {
                pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
            } catch (e: PackageManager.NameNotFoundException) {
                null
            }
        }
    }
}
