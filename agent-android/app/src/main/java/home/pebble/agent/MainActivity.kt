package home.pebble.agent

import android.app.Activity
import android.app.UiModeManager
import android.content.ComponentName
import android.content.Intent
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import java.util.concurrent.Executors

/** Setup (pairing and permissions) and the kid's own view of today's time. */
class MainActivity : Activity() {
    private val background = Executors.newSingleThreadExecutor()
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        findViewById<Button>(R.id.pair_button).setOnClickListener { pair() }
        findViewById<Button>(R.id.usage_button).setOnClickListener { openUsageAccess() }
        findViewById<Button>(R.id.battery_button).setOnClickListener { askBatteryExemption() }
        findViewById<Button>(R.id.autostart_button).setOnClickListener { openAutostart() }
        findViewById<Button>(R.id.sync_button).setOnClickListener { runAgent() }
        findViewById<Button>(R.id.repair_button).setOnClickListener {
            findViewById<View>(R.id.setup_section).visibility = View.VISIBLE
        }
        findViewById<View>(R.id.autostart_row).visibility =
            if (needsAutostart()) View.VISIBLE else View.GONE
        findViewById<View>(R.id.battery_row).visibility = if (isTv()) View.GONE else View.VISIBLE
    }

    override fun onResume() {
        super.onResume()
        render()
        if (prefs.paired) {
            PebbleWorker.schedule(this)
            runAgent()
        }
    }

    override fun onDestroy() {
        background.shutdown()
        super.onDestroy()
    }

    private fun render() {
        val paired = prefs.paired
        findViewById<View>(R.id.setup_section).visibility = if (paired) View.GONE else View.VISIBLE
        findViewById<View>(R.id.status_section).visibility = if (paired) View.VISIBLE else View.GONE
        if (prefs.server != null) findViewById<EditText>(R.id.server_input).setText(prefs.server)

        val usageOk = Agent.hasUsageAccess(this)
        // A TV box is always plugged in, and Doze and App Standby only apply on battery.
        val batteryOk = isTv() ||
            getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)
        check(R.id.usage_state, R.id.usage_button, usageOk)
        if (usageOk) findViewById<View>(R.id.usage_hint).visibility = View.GONE
        check(R.id.battery_state, R.id.battery_button, batteryOk)
        findViewById<View>(R.id.checklist_section).visibility =
            if (paired && (!usageOk || !batteryOk || needsAutostart())) View.VISIBLE else View.GONE
        if (!paired) return

        val t = Agent.today(this)
        findViewById<TextView>(R.id.today_used).text = Today.formatDuration(t.usedS)
        findViewById<TextView>(R.id.today_limit).text = TodayWidget.describeLimit(this, t)
        findViewById<TextView>(R.id.today_note).text =
            if (t.estimate) getString(R.string.today_estimate) else ""
        findViewById<TextView>(R.id.device_line).text =
            listOfNotNull(prefs.deviceName, prefs.kidName?.let { "for $it" }).joinToString(" ")
        val last = prefs.lastSync
        findViewById<TextView>(R.id.sync_line).text = when {
            prefs.lastError != null -> getString(R.string.sync_error, prefs.lastError)
            last == 0L -> getString(R.string.sync_never)
            else -> getString(R.string.sync_last, DateUtils.getRelativeTimeSpanString(last))
        }
    }

    private fun check(stateId: Int, buttonId: Int, ok: Boolean) {
        findViewById<TextView>(stateId).text = if (ok) "✓" else "✗"
        findViewById<Button>(buttonId).visibility = if (ok) View.GONE else View.VISIBLE
    }

    private fun runAgent() {
        findViewById<TextView>(R.id.sync_line).text = getString(R.string.syncing)
        background.execute {
            Agent.run(this)
            runOnUiThread { if (!isDestroyed) render() }
        }
    }

    private fun pair() {
        val server = Api.normaliseServer(findViewById<EditText>(R.id.server_input).text.toString())
        val code = findViewById<EditText>(R.id.code_input).text.toString()
        val message = findViewById<TextView>(R.id.pair_message)
        message.text = getString(R.string.pairing)
        background.execute {
            val result = runCatching { Api.pair(server, code) }
            runOnUiThread {
                result.onSuccess {
                    // A new token is a fresh device on the server: start a fresh record chain.
                    Store.get(this).reset()
                    prefs.startFresh(server, it.token, it.device, it.kid)
                    PebbleWorker.schedule(this)
                    message.text = ""
                    findViewById<EditText>(R.id.code_input).setText("")
                    render()
                    runAgent()
                }.onFailure { message.text = it.message }
            }
        }
    }

    private fun openUsageAccess() {
        val withPackage = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS, Uri.parse("package:$packageName"))
        if (!tryStart(withPackage) && !tryStart(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))) {
            // Many TV boxes leave this settings page out; adb can still grant it.
            findViewById<TextView>(R.id.usage_hint).apply {
                text = getString(R.string.usage_access_adb, packageName)
                visibility = View.VISIBLE
            }
        }
    }

    private fun askBatteryExemption() {
        val ask = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
        if (!tryStart(ask)) tryStart(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
    }

    private fun isTv() = getSystemService(UiModeManager::class.java).currentModeType ==
        Configuration.UI_MODE_TYPE_TELEVISION

    /** Xiaomi, Oppo, Vivo and Huawei stop background apps unless "autostart" is allowed. */
    private fun needsAutostart() =
        Build.MANUFACTURER.lowercase() in setOf("xiaomi", "redmi", "poco", "oppo", "realme", "vivo", "huawei", "honor")

    private fun openAutostart() {
        val candidates = listOf(
            ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
            ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
            ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
            ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        )
        if (candidates.none { tryStart(Intent().setComponent(it)) }) {
            tryStart(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
    }

    private fun tryStart(intent: Intent): Boolean = try {
        startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }
}
