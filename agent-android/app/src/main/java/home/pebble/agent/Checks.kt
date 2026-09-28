package home.pebble.agent

/**
 * Tamper checks between two runs of the collector. Pure logic; Agent.kt supplies the clocks.
 *
 * Android runs the agent every ~15 minutes rather than continuously, so these compare
 * this run with the last one.
 */

/** Clocks at one run. elapsed = SystemClock.elapsedRealtime(), bootCount = Settings.Global.BOOT_COUNT. */
data class RunClock(val wall: Long, val elapsed: Long, val bootCount: Int)

/** An event record to queue, before seq and hashes are added. */
data class PendingEvent(val at: Long, val type: String, val details: Map<String, Any?>? = null)

object Checks {
    /** Wall and elapsed clocks disagreeing by more than this = someone changed the time. */
    const val CLOCK_JUMP_MS = 90_000L
    /** A run later than this after the previous one is a gap worth looking at. */
    const val GAP_MS = 60 * 60_000L
    /** ...and it is reported when the device was used at least this long in it. */
    const val GAP_USE_MS = 10 * 60_000L

    fun rebooted(last: RunClock?, now: RunClock) =
        last == null || now.bootCount != last.bootCount || now.elapsed < last.elapsed

    /** Wall-clock change since the last run in ms, or null when there wasn't one (or a reboot). */
    fun clockJump(last: RunClock?, now: RunClock): Long? {
        if (last == null || rebooted(last, now)) return null
        val delta = (now.wall - last.wall) - (now.elapsed - last.elapsed)
        return if (kotlin.math.abs(delta) > CLOCK_JUMP_MS) delta else null
    }

    /**
     * Events for this run. [from] is where collection started (the last run), [usedMs] the
     * foreground time found in [from, now.wall) from the OS history.
     */
    fun events(last: RunClock?, now: RunClock, from: Long, collected: Collected,
               permissionOk: Boolean, permissionWasOk: Boolean?): List<PendingEvent> {
        val out = mutableListOf<PendingEvent>()
        if (rebooted(last, now)) {
            out += PendingEvent(now.wall, "agent_start", mapOf("new_session" to true))
        }
        clockJump(last, now)?.let {
            out += PendingEvent(now.wall, "clock_jump", mapOf("delta_s" to it / 1000))
        }
        if (permissionWasOk != null && permissionWasOk != permissionOk) {
            out += PendingEvent(now.wall, if (permissionOk) "permission_restored" else "permission_lost",
                mapOf("permission" to "Usage access"))
        }
        out += collected.osEvents.map { PendingEvent(it.time, it.type) }

        val window = now.wall - from
        if (last != null && window > GAP_MS && collected.spans.isNotEmpty()) {
            val details = mapOf("from" to Iso.format(from), "to" to Iso.format(now.wall))
            out += PendingEvent(now.wall, "backfill", details + ("sessions" to collected.spans.size))
            if (collected.usedMs >= GAP_USE_MS) {
                // slept_s = time not in use, so the server's "not running for N min" is time in use.
                out += PendingEvent(now.wall, "agent_gap",
                    details + ("slept_s" to (window - collected.usedMs) / 1000))
            }
        }
        return out.sortedBy { it.at }
    }
}
