import sqlite3

from civilwarhelper.config.settings import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "civilwarhelper.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
