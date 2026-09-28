package home.pebble.agent

import java.security.MessageDigest

/**
 * Canonical JSON for record hashes (docs/api.md, "Hashing"): keys sorted, no whitespace,
 * non-ASCII characters not escaped. Byte-for-byte the same as Python's
 * json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).
 *
 * Supports null, String, Boolean, Int, Long, Map<String, *> and List<*>. Records carry
 * no floating-point numbers, so their formatting never has to match Python's.
 */
object Canonical {
    fun encode(value: Any?): String = StringBuilder().also { write(it, value) }.toString()

    fun hash(record: Map<String, Any?>): String = sha256Hex(encode(record - "hash"))

    fun sha256Hex(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    private fun write(sb: StringBuilder, value: Any?) {
        when (value) {
            null -> sb.append("null")
            is String -> string(sb, value)
            is Boolean, is Int, is Long -> sb.append(value)
            is Map<*, *> -> {
                sb.append('{')
                value.entries.sortedBy { it.key as String }.forEachIndexed { i, e ->
                    if (i > 0) sb.append(',')
                    string(sb, e.key as String)
                    sb.append(':')
                    write(sb, e.value)
                }
                sb.append('}')
            }
            is List<*> -> {
                sb.append('[')
                value.forEachIndexed { i, v ->
                    if (i > 0) sb.append(',')
                    write(sb, v)
                }
                sb.append(']')
            }
            else -> throw IllegalArgumentException("cannot encode ${value::class.java.name}")
        }
    }

    private fun string(sb: StringBuilder, s: String) {
        sb.append('"')
        for (c in s) {
            when (c) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                '\b' -> sb.append("\\b")
                '\u000c' -> sb.append("\\f")
                else -> if (c < ' ') sb.append("\\u%04x".format(c.code)) else sb.append(c)
            }
        }
        sb.append('"')
    }
}
