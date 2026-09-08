import os
import sqlite3

# 本番ホスティングでは、永続ディスクのマウント先(例: /var/data)をDATA_DIR環境変数で指定する。
# 未設定時はこれまで通りローカルのdata/フォルダを使う。
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "drop.sqlite")

os.makedirs(DATA_DIR, exist_ok=True)

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA foreign_keys = ON")
# WALモード: 複数プロセス(本番はgunicornの複数ワーカー)から同時にアクセスしても、
# 読み取りが書き込みをブロックしにくくなり、"database is locked" が起きにくくなる。
_conn.execute("PRAGMA journal_mode = WAL")
_conn.execute("PRAGMA busy_timeout = 5000")

SCHEMA = """
CREATE TABLE IF NOT EXISTS personalities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  console TEXT DEFAULT '',
  belief TEXT DEFAULT '',
  emotion TEXT DEFAULT '',
  bias TEXT DEFAULT '',
  voice_rhythm TEXT DEFAULT '',
  deflection TEXT DEFAULT '',
  sensory_anchor TEXT DEFAULT '',
  created_by TEXT DEFAULT '',
  is_sample INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  who_or_what TEXT DEFAULT '',
  content TEXT NOT NULL,
  meaning TEXT DEFAULT '',
  influence INTEGER DEFAULT 50,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS relationship_context (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  counterpart_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  notes TEXT DEFAULT '',
  relation_label TEXT DEFAULT '',
  misconception TEXT DEFAULT '',
  trust INTEGER DEFAULT 50,
  distance INTEGER DEFAULT 50,
  tension INTEGER DEFAULT 0,
  influence INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT (datetime('now')),
  UNIQUE(personality_id, counterpart_id)
);

CREATE TABLE IF NOT EXISTS dialogues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_a_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  personality_b_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  topic TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dialogue_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dialogue_id INTEGER NOT NULL REFERENCES dialogues(id) ON DELETE CASCADE,
  speaker_personality_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  turn_index INTEGER NOT NULL,
  content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subjective_memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  counterpart_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  dialogue_id INTEGER REFERENCES dialogues(id) ON DELETE SET NULL,
  turn_index INTEGER,
  content TEXT NOT NULL,
  emotion TEXT DEFAULT '',
  confidence INTEGER DEFAULT 50,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS individuality_c_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_a_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  personality_b_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS personality_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  raw_text TEXT NOT NULL,
  extracted_summary TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS self_discoveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  pattern_observed TEXT DEFAULT '',
  gap TEXT DEFAULT '',
  insight TEXT DEFAULT '',
  previous_console TEXT DEFAULT '',
  new_console TEXT DEFAULT '',
  belief_suggestion TEXT DEFAULT '',
  bias_suggestion TEXT DEFAULT '',
  belief_applied INTEGER DEFAULT 0,
  bias_applied INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scenes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_a_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  personality_b_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  situation TEXT DEFAULT '',
  title TEXT DEFAULT '',
  content TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS access_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  email TEXT DEFAULT '',
  stripe_customer_id TEXT DEFAULT '',
  stripe_subscription_id TEXT DEFAULT '',
  status TEXT DEFAULT 'active',
  monthly_limit INTEGER DEFAULT 50,
  usage_count INTEGER DEFAULT 0,
  usage_period TEXT DEFAULT '',
  bonus_credits INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS individuality_c (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personality_a_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  personality_b_id INTEGER NOT NULL REFERENCES personalities(id) ON DELETE CASCADE,
  dialogue_id INTEGER REFERENCES dialogues(id) ON DELETE SET NULL,
  traces TEXT DEFAULT '',
  differences TEXT DEFAULT '',
  open_questions TEXT DEFAULT '',
  new_questions TEXT DEFAULT '',
  summary TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);
"""


def _migrate():
    """既存のdrop.sqliteに対して、後から追加したカラムを補う(冪等)。"""
    rel_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(relationship_context)")}
    rel_new_cols = {
        "relation_label": "TEXT DEFAULT ''",
        "misconception": "TEXT DEFAULT ''",
        "trust": "INTEGER DEFAULT 50",
        "distance": "INTEGER DEFAULT 50",
        "tension": "INTEGER DEFAULT 0",
        "influence": "INTEGER DEFAULT 0",
    }
    for col, decl in rel_new_cols.items():
        if col not in rel_cols:
            _conn.execute(f"ALTER TABLE relationship_context ADD COLUMN {col} {decl}")

    personality_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(personalities)")}
    personality_new_cols = {
        "voice_rhythm": "TEXT DEFAULT ''",
        "deflection": "TEXT DEFAULT ''",
        "sensory_anchor": "TEXT DEFAULT ''",
        "created_by": "TEXT DEFAULT ''",
        "is_sample": "INTEGER DEFAULT 0",
    }
    for col, decl in personality_new_cols.items():
        if col not in personality_cols:
            _conn.execute(f"ALTER TABLE personalities ADD COLUMN {col} {decl}")

    memory_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(memories)")}
    memory_new_cols = {
        "who_or_what": "TEXT DEFAULT ''",
        "influence": "INTEGER DEFAULT 50",
    }
    for col, decl in memory_new_cols.items():
        if col not in memory_cols:
            _conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {decl}")

    access_code_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(access_codes)")}
    access_code_new_cols = {
        "monthly_limit": "INTEGER DEFAULT 50",
        "usage_count": "INTEGER DEFAULT 0",
        "usage_period": "TEXT DEFAULT ''",
        "bonus_credits": "INTEGER DEFAULT 0",
    }
    for col, decl in access_code_new_cols.items():
        if col not in access_code_cols:
            _conn.execute(f"ALTER TABLE access_codes ADD COLUMN {col} {decl}")

    _conn.commit()


def init_db():
    _conn.executescript(SCHEMA)
    _migrate()
    _conn.commit()


def get_conn():
    return _conn


def query(sql, params=()):
    cur = _conn.execute(sql, params)
    return cur.fetchall()


def query_one(sql, params=()):
    cur = _conn.execute(sql, params)
    return cur.fetchone()


def execute(sql, params=()):
    cur = _conn.execute(sql, params)
    _conn.commit()
    return cur
