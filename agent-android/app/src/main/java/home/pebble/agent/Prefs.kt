package home.pebble.agent

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Small settings and state, in private SharedPreferences. */
class Prefs(context: Context) {
    private val p = context.applicationContext.getSharedPreferences("pebble", Context.MODE_PRIVATE)

    var server: String?
        get() = p.getString("server", null)
        set(v) = p.edit().putString("server", v).apply()
    var token: String?
        get() = p.getString("token", null)
        set(v) = p.edit().putString("token", v).apply()
    var deviceName: String?
        get() = p.getString("device_name", null)
        set(v) = p.edit().putString("device_name", v).apply()
    var kidName: String?
        get() = p.getString("kid_name", null)
        set(v) = p.edit().putString("kid_name", v).apply()

    val paired get() = server != null && token != null

    /** Generated once per install; the server uses it to notice reinstalls. */
    val installId: String
        get() = p.getString("install_id", null) ?: UUID.randomUUID().toString().also {
            p.edit().putString("install_id", it).apply()
        }

    /** Where the next collection starts, and the app open at that moment. */
    var foreground: Foreground?
        get() = if (p.contains("fg_since")) Foreground(p.getString("fg_pkg", null), p.getLong("fg_since", 0)) else null
        set(v) = p.edit().apply {
            if (v == null) remove("fg_pkg").remove("fg_since")
            else putString("fg_pkg", v.pkg).putLong("fg_since", v.since)
        }.apply()

    var lastRun: RunClock?
        get() = if (p.contains("run_wall"))
            RunClock(p.getLong("run_wall", 0), p.getLong("run_elapsed", 0), p.getInt("run_boot", 0)) else null
        set(v) = p.edit().apply {
            if (v == null) remove("run_wall").remove("run_elapsed").remove("run_boot")
            else putLong("run_wall", v.wall).putLong("run_elapsed", v.elapsed).putInt("run_boot", v.bootCount)
        }.apply()

    var permissionOk: Boolean?
        get() = if (p.contains("permission_ok")) p.getBoolean("permission_ok", false) else null
        set(v) = p.edit().apply { if (v == null) remove("permission_ok") else putBoolean("permission_ok", v) }.apply()

    var serverToday: ServerToday?
        get() = p.getString("today", null)?.let {
            val o = JSONObject(it)
            ServerToday(o.getString("date"), o.getLong("used_s"),
                if (o.isNull("limit_s")) null else o.getLong("limit_s"))
        }
        set(v) = p.edit().putString("today", v?.let {
            JSONObject().put("date", it.date).put("used_s", it.usedS).put("limit_s", it.limitS ?: JSONObject.NULL).toString()
        }).apply()

    var exclusions: List<Exclusion>
        get() {
            val a = JSONArray(p.getString("exclusions", "[]"))
            return exclusionsFrom(a)
        }
        set(v) = p.edit().putString("exclusions", JSONArray(v.map {
            JSONObject().put("app_id", it.appId).put("domain", it.domain).put("title_pattern", it.titlePattern)
        }).toString()).apply()

    var lastSync: Long
        get() = p.getLong("last_sync", 0)
        set(v) = p.edit().putLong("last_sync", v).apply()
    var lastError: String?
        get() = p.getString("last_error", null)
        set(v) = p.edit().putString("last_error", v).apply()

    companion object {
        /** The server's "exclusions" list (docs/api.md). */
        fun exclusionsFrom(a: JSONArray): List<Exclusion> = (0 until a.length()).map { i ->
            val o = a.getJSONObject(i)
            Exclusion(o.optString("app_id").ifEmpty { null }, o.optString("domain").ifEmpty { null },
                o.optString("title_pattern").ifEmpty { null })
        }
    }

    /** Pairing with a new token: drop everything tied to the old one. */
    fun startFresh(server: String, token: String, deviceName: String?, kidName: String?) {
        p.edit().clear().putString("install_id", installId).putString("server", server)
            .putString("token", token).putString("device_name", deviceName)
            .putString("kid_name", kidName).commit()
    }
}
