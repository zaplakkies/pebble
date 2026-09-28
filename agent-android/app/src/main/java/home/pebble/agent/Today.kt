package home.pebble.agent

import java.time.Instant
import java.time.ZoneId

/** An exclusion rule from the server (docs/api.md). Android sessions have no title or URL. */
data class Exclusion(val appId: String?, val domain: String?, val titlePattern: String?) {
    fun matches(appId: String): Boolean {
        if (this.appId == null && domain == null && titlePattern == null) return false
        // Domain and title rules need a URL or title, which Android sessions don't have.
        if (domain != null || titlePattern != null) return false
        return this.appId.equals(appId, ignoreCase = true)
    }
}

/** The server's last word on today, from /sync or /status. */
data class ServerToday(val date: String, val usedS: Long, val limitS: Long?)

/** A session queued but not yet accepted by the server. */
data class PendingSession(val appId: String, val start: Long, val end: Long)

data class TodayStatus(
    val usedS: Long,
    val limitS: Long?,
    val status: String,      // under | near | over | unknown
    val estimate: Boolean,   // includes time the server hasn't seen yet
)

object Today {
    /** The server's last figure for today plus queued sessions it hasn't counted yet. */
    fun status(
        server: ServerToday?, rules: List<Exclusion>, pending: List<PendingSession>,
        now: Long, zone: ZoneId = ZoneId.systemDefault(),
    ): TodayStatus {
        val today = Instant.ofEpochMilli(now).atZone(zone).toLocalDate()
        val midnight = today.atStartOfDay(zone).toInstant().toEpochMilli()
        val tomorrow = today.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
        val sameDay = server?.date == today.toString()
        var usedMs = if (sameDay) server!!.usedS * 1000 else 0L
        val limit = if (sameDay) server!!.limitS else null

        for (s in pending) {
            if (rules.any { it.matches(s.appId) }) continue
            usedMs += (minOf(s.end, tomorrow) - maxOf(s.start, midnight)).coerceAtLeast(0)
        }
        val used = usedMs / 1000
        val status = when {
            limit == null -> if (sameDay) "under" else "unknown"
            used >= limit -> "over"
            used >= limit * 0.9 -> "near"
            else -> "under"
        }
        return TodayStatus(used, limit, status, estimate = pending.isNotEmpty() || !sameDay)
    }

    fun formatDuration(seconds: Long): String {
        val m = seconds / 60
        return if (m < 60) "${m}m" else "${m / 60}h %02dm".format(m % 60)
    }
}
