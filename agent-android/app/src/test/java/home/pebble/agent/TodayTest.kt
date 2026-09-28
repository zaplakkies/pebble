package home.pebble.agent

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

class TodayTest {
    private val zone = ZoneId.of("Africa/Johannesburg")
    private fun t(h: Int, m: Int = 0, day: Int = 28) =
        LocalDateTime.of(2026, 9, day, h, m).atZone(zone).toInstant().toEpochMilli()

    @Test
    fun serverFigurePlusPendingMinusExclusions() {
        val server = ServerToday("2026-09-28", 3600, 7200)
        val pending = listOf(
            PendingSession("com.google.android.youtube", t(10), t(10, 30)),
            PendingSession("com.google.android.apps.classroom", t(11), t(12)),
            PendingSession("com.whatsapp", t(23, 50, day = 27), t(0, 10)),  // 10 min today
        )
        val rules = listOf(Exclusion("com.google.android.apps.classroom", null, null),
            Exclusion(null, "classroom.google.com", null))
        val s = Today.status(server, rules, pending, t(12), zone)
        assertEquals(3600L + 40 * 60, s.usedS)
        assertEquals("under", s.status)
        assertEquals(true, s.estimate)
    }

    @Test
    fun yesterdaysServerFigureIsIgnored() {
        val s = Today.status(ServerToday("2026-09-27", 9000, 7200), emptyList(), emptyList(), t(8), zone)
        assertEquals(0L, s.usedS)
        assertEquals("unknown", s.status)
    }

    @Test
    fun nearAndOver() {
        assertEquals("near", Today.status(ServerToday("2026-09-28", 6500, 7200), emptyList(), emptyList(), t(12), zone).status)
        assertEquals("over", Today.status(ServerToday("2026-09-28", 7200, 7200), emptyList(), emptyList(), t(12), zone).status)
    }

    @Test
    fun isoRoundTrip() {
        assertEquals("2026-09-28T10:00:00+02:00", Iso.format(t(10), zone))
        assertEquals(t(10), Iso.parse("2026-09-28T10:00:00+02:00"))
    }

    @Test
    fun durations() {
        assertEquals("7m", Today.formatDuration(7 * 60 + 59))
        assertEquals("2h 05m", Today.formatDuration(125 * 60))
    }
}
