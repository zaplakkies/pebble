package home.pebble.agent

/**
 * Turns Android usage events into foreground sessions. Pure logic, no Android calls, so
 * it is unit-tested on any machine. Collector.kt feeds it from UsageStatsManager.
 */

/** One usage event. Types are the UsageEvents.Event constants (same numbers). */
data class UsageEv(val time: Long, val type: Int, val pkg: String)

object EvType {
    const val ACTIVITY_RESUMED = 1
    const val ACTIVITY_PAUSED = 2
    const val SCREEN_INTERACTIVE = 15
    const val SCREEN_NON_INTERACTIVE = 16
    const val KEYGUARD_SHOWN = 17
    const val KEYGUARD_HIDDEN = 18
    const val ACTIVITY_STOPPED = 23
    const val DEVICE_SHUTDOWN = 26
    const val DEVICE_STARTUP = 27
}

/** A stretch of one app in the foreground, in epoch milliseconds. */
data class Span(val pkg: String, val start: Long, val end: Long) {
    val durationMs get() = end - start
}

data class OsEvent(val time: Long, val type: String)

/** What was in the foreground at the end of the last run, carried into the next. */
data class Foreground(val pkg: String?, val since: Long)

data class Collected(val spans: List<Span>, val osEvents: List<OsEvent>, val foreground: Foreground) {
    val usedMs get() = spans.sumOf { it.durationMs }
}

object Sessions {
    /** Shorter spans are noise (an app flashing past during a switch). */
    const val MIN_SPAN_MS = 1_000L
    /** An app that reappears within this gap (activity change inside it) continues its span. */
    const val MERGE_GAP_MS = 2_000L

    /**
     * Build sessions for [from, to). [previous] is the foreground app carried over from the
     * last run. An app still open at [to] is cut there and carried on in the result, so
     * each run reports everything up to now.
     */
    fun collect(events: List<UsageEv>, from: Long, to: Long, previous: Foreground): Collected {
        val spans = mutableListOf<Span>()
        val osEvents = mutableListOf<OsEvent>()
        var current = previous.pkg
        var since = from

        fun close(at: Long) {
            val pkg = current ?: return
            current = null
            val end = at.coerceIn(since, to)
            val last = spans.lastOrNull()
            if (last != null && last.pkg == pkg && since - last.end <= MERGE_GAP_MS) {
                spans[spans.lastIndex] = last.copy(end = end)
            } else if (end - since > 0) {
                spans += Span(pkg, since, end)
            }
        }

        for (e in events.sortedBy { it.time }) {
            val t = e.time.coerceIn(from, to)
            when (e.type) {
                EvType.ACTIVITY_RESUMED -> if (e.pkg != current) {
                    close(t)
                    current = e.pkg
                    since = t
                }
                EvType.ACTIVITY_PAUSED, EvType.ACTIVITY_STOPPED -> if (e.pkg == current) close(t)
                EvType.SCREEN_NON_INTERACTIVE, EvType.KEYGUARD_SHOWN -> close(t)
                EvType.DEVICE_SHUTDOWN -> {
                    close(t)
                    osEvents += OsEvent(t, "os_shutdown")
                }
                EvType.DEVICE_STARTUP -> {
                    close(t)
                    osEvents += OsEvent(t, "os_boot")
                }
            }
        }
        val stillOpen = current
        close(to)
        return Collected(spans.filter { it.durationMs >= MIN_SPAN_MS }, osEvents,
            Foreground(stillOpen, to))
    }
}
