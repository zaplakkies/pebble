package home.pebble.agent

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.util.UUID

/**
 * Local queue of records waiting for the server. Each record gets the next sequence
 * number and joins the hash chain (docs/api.md) in the same transaction as the insert,
 * so the chain survives the app being killed at any point.
 */
class Store(context: Context) : SQLiteOpenHelper(context, "queue.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""CREATE TABLE records (
            seq INTEGER PRIMARY KEY, body TEXT NOT NULL, kind TEXT NOT NULL,
            app_id TEXT, start_ms INTEGER, end_ms INTEGER)""")
        db.execSQL("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {}

    /** Append records (maps without seq/id/prev_hash/hash), in order. */
    fun add(records: List<Map<String, Any?>>) {
        if (records.isEmpty()) return
        val db = writableDatabase
        db.beginTransaction()
        try {
            var seq = meta(db, "seq")?.toLong() ?: 0L
            var prev = meta(db, "last_hash")
            for (fields in records) {
                seq += 1
                val record = fields + mapOf("seq" to seq, "id" to UUID.randomUUID().toString(),
                    "prev_hash" to prev)
                val hash = Canonical.hash(record)
                val body = Canonical.encode(record + ("hash" to hash))
                db.insertOrThrow("records", null, ContentValues().apply {
                    put("seq", seq)
                    put("body", body)
                    put("kind", fields["kind"] as String)
                    if (fields["kind"] == "session") {
                        put("app_id", fields["app_id"] as String)
                        put("start_ms", Iso.parse(fields["start"] as String))
                        put("end_ms", Iso.parse(fields["end"] as String))
                    }
                })
                prev = hash
            }
            setMeta(db, "seq", seq.toString())
            setMeta(db, "last_hash", prev)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    /** Up to [limit] queued records as JSON text, oldest first, with their seq. */
    fun pending(limit: Int): List<Pair<Long, String>> =
        readableDatabase.rawQuery("SELECT seq, body FROM records ORDER BY seq LIMIT ?",
            arrayOf(limit.toString())).use { c ->
            buildList { while (c.moveToNext()) add(c.getLong(0) to c.getString(1)) }
        }

    fun pendingCount(): Int =
        readableDatabase.rawQuery("SELECT COUNT(*) FROM records", null).use { c ->
            c.moveToFirst(); c.getInt(0)
        }

    fun pendingSessions(): List<PendingSession> =
        readableDatabase.rawQuery(
            "SELECT app_id, start_ms, end_ms FROM records WHERE kind = 'session'", null).use { c ->
            buildList { while (c.moveToNext()) add(PendingSession(c.getString(0), c.getLong(1), c.getLong(2))) }
        }

    /** The server has everything up to and including [seq]. */
    fun acknowledge(seq: Long) {
        writableDatabase.delete("records", "seq <= ?", arrayOf(seq.toString()))
    }

    /** Forget the queue and chain: a new token means a fresh record chain on the server. */
    fun reset() {
        val db = writableDatabase
        db.delete("records", null, null)
        db.delete("meta", null, null)
    }

    private fun meta(db: SQLiteDatabase, key: String): String? =
        db.rawQuery("SELECT v FROM meta WHERE k = ?", arrayOf(key)).use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        }

    private fun setMeta(db: SQLiteDatabase, key: String, value: String?) {
        db.insertWithOnConflict("meta", null, ContentValues().apply { put("k", key); put("v", value) },
            SQLiteDatabase.CONFLICT_REPLACE)
    }

    companion object {
        @Volatile private var instance: Store? = null
        fun get(context: Context): Store =
            instance ?: synchronized(this) {
                instance ?: Store(context.applicationContext).also { instance = it }
            }
    }
}
