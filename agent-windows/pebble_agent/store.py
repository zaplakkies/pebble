"""Local queue of records waiting to be sent, plus small bits of agent state.

Every record gets the next sequence number and a hash covering the previous
record's hash (see docs/api.md), so deleting or editing queued records is
detectable on the server.
"""
import hashlib
import json
import sqlite3
import threading
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def canonical_hash(record):
    body = {k: v for k, v in record.items() if k != 'hash'}
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA busy_timeout=5000')
        self._db.executescript(SCHEMA)

    # ------------------------------------------------------------ state

    def get(self, key, default=None):
        with self._lock:
            row = self._db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self._lock:
            self._db.execute('INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)',
                             (key, json.dumps(value)))

    @property
    def install_id(self):
        value = self.get('install_id')
        if value is None:
            value = str(uuid.uuid4())
            self.set('install_id', value)
        return value

    # ------------------------------------------------------------ records

    def add(self, **fields):
        """Append a record (kind='session' or 'event') to the chain and the queue."""
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                seq = self._state_locked('seq', 0) + 1
                record = {'seq': seq, 'id': str(uuid.uuid4()),
                          'prev_hash': self._state_locked('last_hash', None), **fields}
                record['hash'] = canonical_hash(record)
                self._db.execute('INSERT INTO records (seq, body) VALUES (?, ?)',
                                 (seq, json.dumps(record, ensure_ascii=False)))
                self._set_locked('seq', seq)
                self._set_locked('last_hash', record['hash'])
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise
        return record

    def pending(self, limit=500):
        with self._lock:
            rows = self._db.execute('SELECT body FROM records ORDER BY seq LIMIT ?',
                                    (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def pending_count(self):
        with self._lock:
            return self._db.execute('SELECT COUNT(*) FROM records').fetchone()[0]

    def acknowledge(self, through_seq):
        with self._lock:
            self._db.execute('DELETE FROM records WHERE seq <= ?', (through_seq,))

    def close(self):
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ internals (lock held)

    def _state_locked(self, key, default):
        row = self._db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set_locked(self, key, value):
        self._db.execute('INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)',
                         (key, json.dumps(value)))
