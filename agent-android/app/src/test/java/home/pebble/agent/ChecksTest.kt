package home.pebble.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ChecksTest {
    private val t0 = 1_790_000_000_000L
    private val min = 60_000L
    private val last = RunClock(t0, 5_000_000, 7)
    private fun later(ms: Long, clockShift: Long = 0) =
        RunClock(t0 + ms + clockShift, last.elapsed + ms, 7)
    private fun used(ms: Long, from: Long = t0) =
        Collected(if (ms > 0) listOf(Span("yt", from, from + ms)) else emptyList(), emptyList(), Foreground(null, 0))
    private fun types(events: List<PendingEvent>) = events.map { it.type }

    @Test
    fun firstRunAndRebootStartANewSession() {
        assertEquals(listOf("agent_start"),
            types(Checks.events(null, last, t0, used(0), true, null)))
        val rebooted = RunClock(t0 + 20 * min, 1000, 8)
        val e = Checks.events(last, rebooted, t0, used(0), true, true)
        assertEquals(listOf("agent_start"), types(e))
        assertEquals(mapOf("new_session" to true), e[0].details)
    }

    @Test
    fun normalRunHasNoEvents() {
        assertEquals(emptyList<String>(), types(Checks.events(last, later(15 * min), t0, used(10 * min), true, true)))
    }

    @Test
    fun clockJump() {
        assertNull(Checks.clockJump(last, later(15 * min, clockShift = 60_000)))
        assertEquals(-3_600_000L, Checks.clockJump(last, later(15 * min, clockShift = -3_600_000)))
        val e = Checks.events(last, later(15 * min, clockShift = 7_200_000), t0, used(0), true, true)
        assertEquals(listOf("clock_jump"), types(e))
        assertEquals(7200L, e[0].details!!["delta_s"])
    }

    @Test
    fun permissionChanges() {
        assertEquals(listOf("permission_lost"), types(Checks.events(last, later(15 * min), t0, used(0), false, true)))
        assertEquals(listOf("permission_restored"), types(Checks.events(last, later(15 * min), t0, used(0), true, false)))
    }

    @Test
    fun longGapWithUseIsBackfilledAndReported() {
        val now = later(3 * 60 * min)
        val e = Checks.events(last, now, t0, used(40 * min), true, true)
        assertEquals(listOf("backfill", "agent_gap"), types(e))
        assertEquals((180 - 40) * 60L, e[1].details!!["slept_s"])
        assertEquals(Iso.format(t0), e[1].details!!["from"])
    }

    @Test
    fun longGapWithLittleUseIsOnlyBackfill() {
        assertEquals(listOf("backfill"), types(Checks.events(last, later(3 * 60 * min), t0, used(5 * min), true, true)))
        // Overnight with the screen off: nothing at all.
        assertEquals(emptyList<String>(), types(Checks.events(last, later(8 * 60 * min), t0, used(0), true, true)))
    }
}
