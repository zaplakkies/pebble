package home.pebble.agent

import org.junit.Assert.assertEquals
import org.junit.Test

class SessionsTest {
    private val t0 = 1_790_000_000_000L
    private fun at(s: Int) = t0 + s * 1000L
    private fun ev(s: Int, type: Int, pkg: String = "") = UsageEv(at(s), type, pkg)
    private val none = Foreground(null, t0)

    @Test
    fun appSwitchesMakeSessions() {
        val r = Sessions.collect(listOf(
            ev(10, EvType.ACTIVITY_RESUMED, "yt"),
            ev(70, EvType.ACTIVITY_PAUSED, "yt"),
            ev(70, EvType.ACTIVITY_RESUMED, "chat"),
            ev(100, EvType.ACTIVITY_PAUSED, "chat"),
        ), t0, at(200), none)
        assertEquals(listOf(Span("yt", at(10), at(70)), Span("chat", at(70), at(100))), r.spans)
        assertEquals(Foreground(null, at(200)), r.foreground)
    }

    @Test
    fun openAppIsCutAtNowAndCarriedOver() {
        val first = Sessions.collect(listOf(ev(10, EvType.ACTIVITY_RESUMED, "yt")), t0, at(100), none)
        assertEquals(listOf(Span("yt", at(10), at(100))), first.spans)
        assertEquals(Foreground("yt", at(100)), first.foreground)

        val second = Sessions.collect(listOf(ev(150, EvType.ACTIVITY_PAUSED, "yt")),
            at(100), at(200), first.foreground)
        assertEquals(listOf(Span("yt", at(100), at(150))), second.spans)
    }

    @Test
    fun screenOffAndLockEndTheSession() {
        val r = Sessions.collect(listOf(
            ev(10, EvType.ACTIVITY_RESUMED, "yt"),
            ev(40, EvType.SCREEN_NON_INTERACTIVE),
            ev(100, EvType.SCREEN_INTERACTIVE),
            ev(110, EvType.KEYGUARD_HIDDEN),
            ev(111, EvType.ACTIVITY_RESUMED, "yt"),
            ev(130, EvType.KEYGUARD_SHOWN),
        ), t0, at(200), none)
        assertEquals(listOf(Span("yt", at(10), at(40)), Span("yt", at(111), at(130))), r.spans)
    }

    @Test
    fun activityChangesInsideAnAppAreOneSession() {
        val r = Sessions.collect(listOf(
            ev(10, EvType.ACTIVITY_RESUMED, "yt"),
            ev(20, EvType.ACTIVITY_PAUSED, "yt"),
            ev(21, EvType.ACTIVITY_RESUMED, "yt"),
            ev(50, EvType.ACTIVITY_PAUSED, "yt"),
        ), t0, at(100), none)
        assertEquals(listOf(Span("yt", at(10), at(50))), r.spans)
    }

    @Test
    fun pauseOfABackgroundAppIsIgnored() {
        val r = Sessions.collect(listOf(
            ev(10, EvType.ACTIVITY_RESUMED, "chat"),
            ev(11, EvType.ACTIVITY_PAUSED, "yt"),
            ev(60, EvType.ACTIVITY_PAUSED, "chat"),
        ), t0, at(100), none)
        assertEquals(listOf(Span("chat", at(10), at(60))), r.spans)
    }

    @Test
    fun flashesAreDroppedAndShutdownIsReported() {
        val r = Sessions.collect(listOf(
            ev(10, EvType.ACTIVITY_RESUMED, "launcher"),
            ev(10, EvType.ACTIVITY_PAUSED, "launcher"),
            ev(20, EvType.ACTIVITY_RESUMED, "yt"),
            ev(80, EvType.DEVICE_SHUTDOWN),
            ev(90, EvType.DEVICE_STARTUP),
        ), t0, at(100), none)
        assertEquals(listOf(Span("yt", at(20), at(80))), r.spans)
        assertEquals(listOf(OsEvent(at(80), "os_shutdown"), OsEvent(at(90), "os_boot")), r.osEvents)
    }
}
