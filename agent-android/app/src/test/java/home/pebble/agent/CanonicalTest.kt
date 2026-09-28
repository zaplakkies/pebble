package home.pebble.agent

import org.junit.Assert.assertEquals
import org.junit.Test

/** Expected values come from Python's json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False). */
class CanonicalTest {
    @Test
    fun matchesPythonForEvents() {
        val record = mapOf("seq" to 1, "id" to "a", "prev_hash" to null, "kind" to "event",
            "at" to "2026-09-28T10:00:00+02:00", "type" to "agent_start",
            "details" to mapOf("new_session" to true, "n" to 3))
        assertEquals("""{"at":"2026-09-28T10:00:00+02:00","details":{"n":3,"new_session":true},"id":"a","kind":"event","prev_hash":null,"seq":1,"type":"agent_start"}""",
            Canonical.encode(record))
        assertEquals("65dd9a43fa43e5202e7669a747be72e1c8a68e9e3cea7479660168a37e1bd822",
            Canonical.hash(record + ("hash" to "ignored")))
    }

    @Test
    fun matchesPythonForEscapesAndNonAscii() {
        val record = mapOf("seq" to 2L, "id" to "b", "prev_hash" to "x", "kind" to "session",
            "start" to "s", "end" to "e", "app_id" to "com.whatsapp",
            "app_name" to "WhatsApp éè 😀 \"q\" \\ /\n\t\u0001",
            "title" to null, "url" to null, "document" to null)
        assertEquals("fa188a1b3f8b607248cc18b5aafe4adca8e5df7e381f4384c31689edc19336cc",
            Canonical.hash(record))
    }

    @Test
    fun lists() {
        assertEquals("""[1,"a",null,{"b":false}]""", Canonical.encode(listOf(1, "a", null, mapOf("b" to false))))
    }
}
