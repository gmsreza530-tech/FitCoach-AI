import sqlite3
from datetime import datetime, timezone, timedelta
from fitcoach.config import DATABASE_PATH, SUBSCRIPTION_DAYS, SUBSCRIPTION_PLAN_LIMIT, FREE_MODE

def now():
    return datetime.now(timezone.utc).isoformat()

def db():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DATABASE_PATH)
    c.row_factory=sqlite3.Row
    return c

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS athletes(
          telegram_id INTEGER PRIMARY KEY, name TEXT, age INTEGER, sex TEXT,
          height REAL, weight REAL, goal TEXT, experience TEXT, equipment TEXT,
          days INTEGER, recovery TEXT, limitations TEXT, medication TEXT, notes TEXT,
          created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS coach_knowledge(
          id INTEGER PRIMARY KEY AUTOINCREMENT, coach_id INTEGER, source_file TEXT,
          sheet_name TEXT, row_num INTEGER, category TEXT, content TEXT, tags TEXT,
          created_at TEXT);
        CREATE TABLE IF NOT EXISTS programs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, coach_id INTEGER,
          kind TEXT, request TEXT, content TEXT, status TEXT, created_at TEXT,
          reviewed_at TEXT, review_note TEXT);
        CREATE TABLE IF NOT EXISTS progress(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, entry TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS access(
          athlete_id INTEGER PRIMARY KEY, plan_type TEXT, expires_at TEXT,
          plans_limit INTEGER, plans_used INTEGER DEFAULT 0, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS payments(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, plan_type TEXT,
          amount INTEGER, status TEXT, reference TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS conversations(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER, role TEXT,
          content TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS workout_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
          exercise TEXT NOT NULL, sets INTEGER, reps TEXT, weight REAL,
          rir REAL, notes TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS nutrition_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
          meal TEXT NOT NULL, calories REAL DEFAULT 0, protein REAL DEFAULT 0,
          carbs REAL DEFAULT 0, fat REAL DEFAULT 0, notes TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS body_measurements(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
          weight REAL, waist REAL, chest REAL, arm REAL, thigh REAL,
          body_fat REAL, notes TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS daily_checkins(
          id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id INTEGER NOT NULL,
          sleep_hours REAL, energy INTEGER, soreness INTEGER, adherence INTEGER,
          notes TEXT, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_workout_athlete_date ON workout_logs(athlete_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_nutrition_athlete_date ON nutrition_logs(athlete_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_measure_athlete_date ON body_measurements(athlete_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_checkin_athlete_date ON daily_checkins(athlete_id,created_at);
        """)
        c.execute("INSERT OR IGNORE INTO access(athlete_id,plan_type,expires_at,plans_limit,plans_used,updated_at) VALUES(?,?,?,?,?,?)",
                  (0,"none","1970-01-01T00:00:00+00:00",0,0,now()))

def save_profile(uid,d):
    fields=["name","age","sex","height","weight","goal","experience","equipment","days","recovery","limitations","medication","notes"]
    with db() as c:
        old=c.execute("SELECT telegram_id FROM athletes WHERE telegram_id=?",(uid,)).fetchone()
        vals=[d.get(k) for k in fields]
        if old:
            c.execute("UPDATE athletes SET "+",".join(k+"=?" for k in fields)+",updated_at=? WHERE telegram_id=?",
                      vals+[now(),uid])
        else:
            c.execute("INSERT INTO athletes(telegram_id,"+",".join(fields)+",created_at,updated_at) VALUES("+",".join("?" for _ in range(16))+")",
                      [uid]+vals+[now(),now()])

def profile(uid):
    with db() as c:
        r=c.execute("SELECT * FROM athletes WHERE telegram_id=?",(uid,)).fetchone()
        return dict(r) if r else None

def add_knowledge(coach_id,filename,sheet,row,category,content,tags=""):
    with db() as c:
        c.execute("INSERT INTO coach_knowledge(coach_id,source_file,sheet_name,row_num,category,content,tags,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (coach_id,filename,sheet,row,category,content,tags,now()))

def search_knowledge(coach_id,query,limit=7):
    words=[w.lower() for w in query.split() if len(w)>2]
    with db() as c:
        rows=c.execute("SELECT * FROM coach_knowledge WHERE coach_id=? ORDER BY id DESC LIMIT 500",(coach_id,)).fetchall()
    scored=[]
    for r in rows:
        text=(r["content"]+" "+(r["tags"] or "")+" "+(r["category"] or "")).lower()
        score=sum(1 for w in words if w in text)
        if score: scored.append((score,r["content"]))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [x[1] for x in scored[:limit]]

def create_program(uid,coach_id,kind,request,content,status):
    with db() as c:
        cur=c.execute("INSERT INTO programs(athlete_id,coach_id,kind,request,content,status,created_at) VALUES(?,?,?,?,?,?,?)",
                      (uid,coach_id,kind,request,content,status,now()))
        return cur.lastrowid

def get_program(pid):
    with db() as c:
        r=c.execute("SELECT * FROM programs WHERE id=?",(pid,)).fetchone()
        return dict(r) if r else None

def pending(coach_id):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM programs WHERE coach_id=? AND status='pending' ORDER BY id",(coach_id,)).fetchall()]

def review(pid,status,note=""):
    with db() as c:
        c.execute("UPDATE programs SET status=?,reviewed_at=?,review_note=? WHERE id=?",(status,now(),note,pid))

def add_progress(uid,entry):
    with db() as c:
        c.execute("INSERT INTO progress(athlete_id,entry,created_at) VALUES(?,?,?)",(uid,entry,now()))

def get_progress(uid):
    with db() as c:
        return [r["entry"] for r in c.execute("SELECT entry FROM progress WHERE athlete_id=? ORDER BY id DESC LIMIT 10",(uid,)).fetchall()]

def access_info(uid):
    with db() as c:
        r=c.execute("SELECT * FROM access WHERE athlete_id=?",(uid,)).fetchone()
        return dict(r) if r else None

def grant(uid,days=SUBSCRIPTION_DAYS,limit=SUBSCRIPTION_PLAN_LIMIT,plan="subscription"):
    expiry=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()
    with db() as c:
        c.execute("INSERT INTO access(athlete_id,plan_type,expires_at,plans_limit,plans_used,updated_at) VALUES(?,?,?,?,0,?) "
                  "ON CONFLICT(athlete_id) DO UPDATE SET plan_type=excluded.plan_type,expires_at=excluded.expires_at,plans_limit=excluded.plans_limit,plans_used=0,updated_at=excluded.updated_at",
                  (uid,plan,expiry,limit,now()))

def consume_plan(uid):
    if FREE_MODE:
        return True, "حالت رایگان آزمایشی فعال است."
    a=access_info(uid)
    if not a: return False,"برای ساخت برنامه، ابتدا دسترسی خریداری یا توسط مربی فعال شود."
    try: exp=datetime.fromisoformat(a["expires_at"])
    except Exception: return False,"دسترسی فعال نیست."
    if exp < datetime.now(timezone.utc): return False,"اشتراک پایان یافته است. برنامه‌های قبلی همچنان قابل مشاهده‌اند."
    if a["plans_used"]>=a["plans_limit"]: return False,"سقف برنامه‌های این دوره تمام شده است."
    with db() as c: c.execute("UPDATE access SET plans_used=plans_used+1,updated_at=? WHERE athlete_id=?",(now(),uid))
    return True,"ok"

def stats():
    with db() as c:
        return (c.execute("SELECT COUNT(*) FROM athletes").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM programs").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM coach_knowledge").fetchone()[0])


def add_workout(uid, exercise, sets, reps, weight, rir, notes=""):
    with db() as c:
        c.execute("INSERT INTO workout_logs(athlete_id,exercise,sets,reps,weight,rir,notes,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (uid,exercise,sets,reps,weight,rir,notes,now()))

def add_nutrition(uid, meal, calories, protein, carbs, fat, notes=""):
    with db() as c:
        c.execute("INSERT INTO nutrition_logs(athlete_id,meal,calories,protein,carbs,fat,notes,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (uid,meal,calories,protein,carbs,fat,notes,now()))

def add_measurement(uid, weight, waist=None, chest=None, arm=None, thigh=None, body_fat=None, notes=""):
    with db() as c:
        c.execute("INSERT INTO body_measurements(athlete_id,weight,waist,chest,arm,thigh,body_fat,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (uid,weight,waist,chest,arm,thigh,body_fat,notes,now()))

def add_checkin(uid, sleep, energy, soreness, adherence, notes=""):
    with db() as c:
        c.execute("INSERT INTO daily_checkins(athlete_id,sleep_hours,energy,soreness,adherence,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                  (uid,sleep,energy,soreness,adherence,notes,now()))

def recent_rows(table, uid, limit=30):
    allowed={"workout_logs","nutrition_logs","body_measurements","daily_checkins"}
    if table not in allowed: raise ValueError("invalid table")
    with db() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} WHERE athlete_id=? ORDER BY id DESC LIMIT ?",(uid,limit)).fetchall()]

def delete_athlete_data(uid):
    with db() as c:
        for table in ("athletes","progress","access","programs","conversations","workout_logs","nutrition_logs","body_measurements","daily_checkins"):
            c.execute(f"DELETE FROM {table} WHERE athlete_id=?" if table!="athletes" else "DELETE FROM athletes WHERE telegram_id=?",(uid,))
