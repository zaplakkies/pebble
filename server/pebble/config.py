import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'change-me'
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', f"sqlite:///{BASE_DIR / 'instance' / 'pebble.db'}")

    # IANA timezone name, e.g. "Africa/Johannesburg". Empty = use the server's system timezone.
    TIMEZONE = os.environ.get('TIMEZONE') or ''

    # Secret path segment for the management pages (phase 3). Keep it unguessable.
    MANAGE_PATH = os.environ.get('MANAGE_PATH') or 'manage-change-me'

    # How often agents should sync, returned to them on every /sync.
    SYNC_INTERVAL_S = int(os.environ.get('SYNC_INTERVAL_S') or 120)

    # Raise an alert if a device clock differs from the server by more than this.
    CLOCK_SKEW_ALERT_S = int(os.environ.get('CLOCK_SKEW_ALERT_S') or 300)

    # Fraction of the daily limit at which status turns from "under" to "near".
    NEAR_LIMIT_RATIO = float(os.environ.get('NEAR_LIMIT_RATIO') or 0.9)

    # Largest accepted request body (an agent returning after days offline sends a lot).
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
