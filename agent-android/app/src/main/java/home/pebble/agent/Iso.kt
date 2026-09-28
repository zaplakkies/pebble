package home.pebble.agent

import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

/** ISO-8601 timestamps with UTC offset, to the second, as the API expects. */
object Iso {
    private val FORMAT = DateTimeFormatter.ISO_OFFSET_DATE_TIME

    fun format(millis: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        Instant.ofEpochMilli(millis).atZone(zone).truncatedTo(ChronoUnit.SECONDS)
            .toOffsetDateTime().format(FORMAT)

    fun parse(text: String): Long = OffsetDateTime.parse(text, FORMAT).toInstant().toEpochMilli()
}
