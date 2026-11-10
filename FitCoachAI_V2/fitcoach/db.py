"""Database layer for FitCoach AI.

Uses PostgreSQL when DATABASE_URL is configured (production) and SQLite otherwise
(local development). SQL and row access are kept compatible across both drivers.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from fitcoach.config import (
    DATABASE_PATH,
    DATABASE_URL,
    SUBSCRIPTION_DAYS,
    SUBSCRIPTION_PLAN_LIMIT,
    FREE_MODE,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def _is_postgres():
    return bool(DATABASE_URL)


class _Connection:
    """Small DB-API compatibility wrapper for the shared qmark SQL in this module."""

    def __init__(self, connection, postgres=False):
        self._connection = connection
        self._postgres = postgres

    def execute(self, sql, params=()):
        if self._postgres:
            sql = sql.replace("?", "%s")
        return self._connection.execute(sql, params)


@contextmanager
def db():
    """Yield a connection; commit on success and always close the underlying handle."""
    if _is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed. "
                "Install requirements.txt before starting FitCoach AI."
            ) from exc

        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            yield _Connection(connection, postgres=True)
        return

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        yield _Connection(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init():
    """Create the complete schema in the selected backend and backfill accounts."""
    schema = """
    CREATE TABLE IF NOT EXISTS athletes(
      telegram_id INTEGER PRIMARY KEY, name TEXT, age INTEGER, sex TEXT,
      height REAL, weight REAL, goal TEXT, experience TEXT, equipment TEXT,
      days INTEGER, recovery TEXT, limitations TEXT, medication TEXT, notes TEXT,
      created_at TEXT, updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS accounts(
      telegram_id INTEGER PRIMARY KEY,
      username TEXT,
      first_name TEXT,
      last_name TEXT,
      role TEXT NOT NULL DEFAULT 'athlete' CHECK(role IN ('athlete','coach','admin')),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS wallet_transactions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      telegram_id INTEGER NOT NULL,
      amount INTEGER NOT NULL CHECK(amount != 0),
      currency TEXT NOT NULL DEFAULT 'IRT',
      transaction_type TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      reference TEXT UNIQUE,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      FOREIGN KEY(telegram_id) REFERENCES accounts(telegram_id)
    );

    CREATE TABLE IF NOT EXISTS coach_knowledge(
      id INTEGER PRIMARY KEY AUTOINCREMENT, coach_id INTEGER, source_file TEXT,
      sheet_name TEXT, row_num INTEGER, category TEXT, content TEXT, tags TEXT,
      created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS programs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, coach_id INTEGER,
      kind TEXT, request TEXT, content TEXT, status TEXT, created_at TEXT,
      reviewed_at TEXT, review_note TEXT
    );

    CREATE TABLE IF NOT EXISTS progress(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, entry TEXT, created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS access(
      athlete_id INTEGER PRIMARY KEY, plan_type TEXT, expires_at TEXT,
      plans_limit INTEGER, plans_used INTEGER DEFAULT 0, updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS payments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, plan_type TEXT,
      amount INTEGER, status TEXT, reference TEXT, created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS conversations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, role TEXT,
      content TEXT, created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS conversation_sessions(
      athlete_id INTEGER PRIMARY KEY,
      is_active INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS workout_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
      exercise TEXT NOT NULL, sets INTEGER, reps TEXT, weight REAL,
      rir REAL, notes TEXT, created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS nutrition_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
      meal TEXT NOT NULL, calories REAL DEFAULT 0, protein REAL DEFAULT 0,
      carbs REAL DEFAULT 0, fat REAL DEFAULT 0, notes TEXT, created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS body_measurements(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
      weight REAL, waist REAL, chest REAL, arm REAL, thigh REAL,
      body_fat REAL, notes TEXT, created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS daily_checkins(
      id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
      sleep_hours REAL, energy INTEGER, soreness INTEGER, adherence INTEGER,
      notes TEXT, created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_wallet_user_date
      ON wallet_transactions(telegram_id, created_at, id);
    CREATE INDEX IF NOT EXISTS idx_workout_athlete_date
      ON workout_logs(athlete_id,created_at);
    CREATE INDEX IF NOT EXISTS idx_nutrition_athlete_date
      ON nutrition_logs(athlete_id,created_at);
    CREATE INDEX IF NOT EXISTS idx_measure_athlete_date
      ON body_measurements(athlete_id,created_at);
    CREATE INDEX IF NOT EXISTS idx_checkin_athlete_date
      ON daily_checkins(athlete_id,created_at);
    CREATE INDEX IF NOT EXISTS idx_conversations_athlete_id
      ON conversations(athlete_id,id);
    """

    if _is_postgres():
        schema = schema.replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
        )
        for column in ("telegram_id", "athlete_id", "coach_id", "created_by"):
            schema = schema.replace(f"{column} INTEGER", f"{column} BIGINT")
        schema = schema.replace("INTEGER PRIMARY KEY", "BIGINT PRIMARY KEY")

    with db() as connection:
        for statement in schema.split(";"):
            if statement.strip():
                connection.execute(statement)
        connection.execute(
            """
            INSERT INTO accounts
              (telegram_id, role, created_at, updated_at)
            SELECT telegram_id, 'athlete', COALESCE(created_at, ?), COALESCE(updated_at, ?)
            FROM athletes WHERE 1=1
            ON CONFLICT DO NOTHING
            """,
            (now(), now()),
        )
        connection.execute(
            """
            INSERT INTO access
              (athlete_id,plan_type,expires_at,plans_limit,plans_used,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT DO NOTHING
            """,
            (0, "none", "1970-01-01T00:00:00+00:00", 0, 0, now()),
        )


# ---------------------------------------------------------------------------
# Telegram account identity and append-only wallet ledger
# ---------------------------------------------------------------------------

def register_account(telegram_user, role="athlete"):
    """Upsert Telegram identity while preserving the immutable Telegram user ID."""
    if role not in {"athlete", "coach", "admin"}:
        raise ValueError("invalid account role")
    uid = int(telegram_user.id)
    timestamp = now()
    with db() as c:
        c.execute(
            """
            INSERT INTO accounts
              (telegram_id, username, first_name, last_name, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
              username=excluded.username,
              first_name=excluded.first_name,
              last_name=excluded.last_name,
              role=excluded.role,
              updated_at=excluded.updated_at
            """,
            (uid, telegram_user.username, telegram_user.first_name,
             telegram_user.last_name, role, timestamp, timestamp),
        )
        row = c.execute("SELECT * FROM accounts WHERE telegram_id=?", (uid,)).fetchone()
        return dict(row)


def account_info(uid):
    with db() as c:
        row = c.execute(
            "SELECT * FROM accounts WHERE telegram_id=?", (int(uid),)
        ).fetchone()
        return dict(row) if row else None


def wallet_balance(uid):
    """Wallet balance is derived from the immutable ledger; no mutable balance field."""
    with db() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(amount), 0) AS balance "
            "FROM wallet_transactions WHERE telegram_id=?",
            (int(uid),),
        ).fetchone()
        return int(row["balance"])


def add_wallet_transaction(uid, amount, transaction_type, description="",
                           reference=None, created_by=None):
    """Append a wallet entry. A unique reference makes retries idempotent."""
    amount = int(amount)
    if amount == 0:
        raise ValueError("wallet transaction amount cannot be zero")
    if transaction_type not in {"topup", "purchase", "refund", "adjustment"}:
        raise ValueError("invalid wallet transaction type")
    with db() as c:
        cursor = c.execute(
            """
            INSERT INTO wallet_transactions
              (telegram_id, amount, currency, transaction_type, description,
               reference, created_by, created_at)
            VALUES (?, ?, 'TOMAN', ?, ?, ?, ?, ?)
            ON CONFLICT(reference) DO NOTHING
            RETURNING id
            """,
            (int(uid), amount, transaction_type, str(description)[:300],
             reference, created_by, now()),
        )
        row = cursor.fetchone()
        if row:
            return row["id"]
        existing = c.execute(
            "SELECT id FROM wallet_transactions WHERE reference=?", (reference,)
        ).fetchone()
        if existing:
            return existing["id"]
        raise RuntimeError("Wallet transaction was not inserted")


def wallet_history(uid, limit=10):
    limit = max(1, min(int(limit), 50))
    with db() as c:
        return [
            dict(row) for row in c.execute(
                """
                SELECT id, amount, currency, transaction_type, description, reference, created_at
                FROM wallet_transactions WHERE telegram_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (int(uid), limit),
            ).fetchall()
        ]


# ---------------------------------------------------------------------------
# Athlete profile
# ---------------------------------------------------------------------------

def save_profile(uid, d):
    fields = [
        "name", "age", "sex", "height", "weight", "goal", "experience",
        "equipment", "days", "recovery", "limitations", "medication", "notes",
    ]
    with db() as c:
        old = c.execute(
            "SELECT telegram_id FROM athletes WHERE telegram_id=?", (uid,)
        ).fetchone()
        vals = [d.get(k) for k in fields]
        if old:
            c.execute(
                "UPDATE athletes SET "
                + ",".join(k + "=?" for k in fields)
                + ",updated_at=? WHERE telegram_id=?",
                vals + [now(), uid],
            )
        else:
            c.execute(
                "INSERT INTO athletes(telegram_id,"
                + ",".join(fields)
                + ",created_at,updated_at) VALUES("
                + ",".join("?" for _ in range(16))
                + ")",
                [uid] + vals + [now(), now()],
            )


def profile(uid):
    with db() as c:
        row = c.execute(
            "SELECT * FROM athletes WHERE telegram_id=?", (uid,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Persistent coach chat
# ---------------------------------------------------------------------------

def start_conversation(uid):
    """Mark the athlete's coach chat as active without deleting previous history."""
    with db() as c:
        c.execute(
            """
            INSERT INTO conversation_sessions(athlete_id, is_active, updated_at)
            VALUES(?, 1, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                is_active=1, updated_at=excluded.updated_at
            """,
            (uid, now()),
        )


def end_conversation(uid):
    """Close the current coach chat. Existing history remains available."""
    with db() as c:
        c.execute(
            """
            INSERT INTO conversation_sessions(athlete_id, is_active, updated_at)
            VALUES(?, 0, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                is_active=0, updated_at=excluded.updated_at
            """,
            (uid, now()),
        )


def is_conversation_active(uid):
    with db() as c:
        row = c.execute(
            "SELECT is_active FROM conversation_sessions WHERE athlete_id=?",
            (uid,),
        ).fetchone()
        return bool(row["is_active"]) if row else False


def add_conversation_message(uid, role, content):
    """Save one user/assistant message. Only the two supported roles are accepted."""
    if role not in ("user", "assistant"):
        raise ValueError("role must be 'user' or 'assistant'")
    content = str(content or "").strip()
    if not content:
        return
    with db() as c:
        c.execute(
            "INSERT INTO conversations(athlete_id,role,content,created_at) "
            "VALUES(?,?,?,?)",
            (uid, role, content, now()),
        )


def get_conversation_history(uid, limit=12):
    """Return latest messages in chronological order."""
    limit = max(1, min(int(limit), 50))
    with db() as c:
        rows = c.execute(
            """
            SELECT role, content FROM conversations
            WHERE athlete_id=?
            ORDER BY id DESC LIMIT ?
            """,
            (uid, limit),
        ).fetchall()
    rows = list(reversed(rows))
    return [
        {"role": row["role"], "content": row["content"]}
        for row in rows
        if row["role"] in ("user", "assistant") and row["content"]
    ]


def clear_conversation_history(uid):
    """Delete chat messages for this athlete; does not change profile or other records."""
    with db() as c:
        c.execute("DELETE FROM conversations WHERE athlete_id=?", (uid,))


# ---------------------------------------------------------------------------
# Coach knowledge and programs
# ---------------------------------------------------------------------------

def add_knowledge(coach_id, filename, sheet, row, category, content, tags=""):
    with db() as c:
        c.execute(
            "INSERT INTO coach_knowledge"
            "(coach_id,source_file,sheet_name,row_num,category,content,tags,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (coach_id, filename, sheet, row, category, content, tags, now()),
        )


def search_knowledge(coach_id, query, limit=7):
    words = [w.lower() for w in query.split() if len(w) > 2]
    with db() as c:
        rows = c.execute(
            "SELECT * FROM coach_knowledge WHERE coach_id=? "
            "ORDER BY id DESC LIMIT 500",
            (coach_id,),
        ).fetchall()
    scored = []
    for row in rows:
        text = (
            (row["content"] or "")
            + " "
            + (row["tags"] or "")
            + " "
            + (row["category"] or "")
        ).lower()
        score = sum(1 for word in words if word in text)
        if score:
            scored.append((score, row["content"]))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def create_program(uid, coach_id, kind, request, content, status):
    with db() as c:
        row = c.execute(
            "INSERT INTO programs"
            "(athlete_id,coach_id,kind,request,content,status,created_at) "
            "VALUES(?,?,?,?,?,?,?) RETURNING id",
            (uid, coach_id, kind, request, content, status, now()),
        ).fetchone()
        return row["id"]


def get_program(pid):
    with db() as c:
        row = c.execute("SELECT * FROM programs WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None


def pending(coach_id):
    with db() as c:
        return [
            dict(row)
            for row in c.execute(
                "SELECT * FROM programs WHERE coach_id=? AND status='pending' "
                "ORDER BY id",
                (coach_id,),
            ).fetchall()
        ]


def review(pid, status, note=""):
    with db() as c:
        c.execute(
            "UPDATE programs SET status=?,reviewed_at=?,review_note=? WHERE id=?",
            (status, now(), note, pid),
        )


# ---------------------------------------------------------------------------
# Progress and subscription access
# ---------------------------------------------------------------------------

def add_progress(uid, entry):
    with db() as c:
        c.execute(
            "INSERT INTO progress(athlete_id,entry,created_at) VALUES(?,?,?)",
            (uid, entry, now()),
        )


def get_progress(uid):
    with db() as c:
        return [
            row["entry"]
            for row in c.execute(
                "SELECT entry FROM progress WHERE athlete_id=? "
                "ORDER BY id DESC LIMIT 10",
                (uid,),
            ).fetchall()
        ]


def access_info(uid):
    with db() as c:
        row = c.execute(
            "SELECT * FROM access WHERE athlete_id=?", (uid,)
        ).fetchone()
        return dict(row) if row else None


def grant(uid, days=SUBSCRIPTION_DAYS, limit=SUBSCRIPTION_PLAN_LIMIT, plan="subscription"):
    expiry = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with db() as c:
        c.execute(
            "INSERT INTO access"
            "(athlete_id,plan_type,expires_at,plans_limit,plans_used,updated_at) "
            "VALUES(?,?,?,?,0,?) "
            "ON CONFLICT(athlete_id) DO UPDATE SET "
            "plan_type=excluded.plan_type,expires_at=excluded.expires_at,"
            "plans_limit=excluded.plans_limit,plans_used=0,"
            "updated_at=excluded.updated_at",
            (uid, plan, expiry, limit, now()),
        )


def consume_plan(uid):
    if FREE_MODE:
        return True, "حالت رایگان آزمایشی فعال است."
    access = access_info(uid)
    if not access:
        return False, "برای ساخت برنامه، ابتدا دسترسی خریداری یا توسط مربی فعال شود."
    try:
        expiry = datetime.fromisoformat(access["expires_at"])
    except Exception:
        return False, "دسترسی فعال نیست."
    if expiry < datetime.now(timezone.utc):
        return False, "اشتراک پایان یافته است. برنامه‌های قبلی همچنان قابل مشاهده‌اند."
    if access["plans_used"] >= access["plans_limit"]:
        return False, "سقف برنامه‌های این دوره تمام شده است."
    with db() as c:
        c.execute(
            "UPDATE access SET plans_used=plans_used+1,updated_at=? "
            "WHERE athlete_id=?",
            (now(), uid),
        )
    return True, "ok"


def stats():
    with db() as c:
        return (
            c.execute("SELECT COUNT(*) AS total FROM athletes").fetchone()["total"],
            c.execute("SELECT COUNT(*) AS total FROM programs").fetchone()["total"],
            c.execute("SELECT COUNT(*) AS total FROM coach_knowledge").fetchone()["total"],
        )


# ---------------------------------------------------------------------------
# Training, nutrition, measurements, check-ins
# ---------------------------------------------------------------------------

def add_workout(uid, exercise, sets, reps, weight, rir, notes=""):
    with db() as c:
        c.execute(
            "INSERT INTO workout_logs"
            "(athlete_id,exercise,sets,reps,weight,rir,notes,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, exercise, sets, reps, weight, rir, notes, now()),
        )


def add_nutrition(uid, meal, calories, protein, carbs, fat, notes=""):
    with db() as c:
        c.execute(
            "INSERT INTO nutrition_logs"
            "(athlete_id,meal,calories,protein,carbs,fat,notes,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, meal, calories, protein, carbs, fat, notes, now()),
        )


def add_measurement(
    uid, weight, waist=None, chest=None, arm=None, thigh=None,
    body_fat=None, notes=""
):
    with db() as c:
        c.execute(
            "INSERT INTO body_measurements"
            "(athlete_id,weight,waist,chest,arm,thigh,body_fat,notes,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (uid, weight, waist, chest, arm, thigh, body_fat, notes, now()),
        )


def add_checkin(uid, sleep, energy, soreness, adherence, notes=""):
    with db() as c:
        c.execute(
            "INSERT INTO daily_checkins"
            "(athlete_id,sleep_hours,energy,soreness,adherence,notes,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid, sleep, energy, soreness, adherence, notes, now()),
        )


def recent_rows(table, uid, limit=30):
    allowed = {
        "workout_logs", "nutrition_logs", "body_measurements", "daily_checkins"
    }
    if table not in allowed:
        raise ValueError("invalid table")
    with db() as c:
        return [
            dict(row)
            for row in c.execute(
                f"SELECT * FROM {table} WHERE athlete_id=? "
                "ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        ]


def delete_athlete_data(uid):
    with db() as c:
        for table in (
            "athletes", "progress", "access", "programs", "conversations",
            "conversation_sessions", "workout_logs", "nutrition_logs",
            "body_measurements", "daily_checkins",
        ):
            if table == "athletes":
                c.execute("DELETE FROM athletes WHERE telegram_id=?", (uid,))
            else:
                c.execute(f"DELETE FROM {table} WHERE athlete_id=?", (uid,))
