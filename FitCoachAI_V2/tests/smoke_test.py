"""Local database smoke test: python tests/smoke_test.py"""
import os, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

fd, name = tempfile.mkstemp(suffix='.db')
os.close(fd)
os.environ['DATABASE_PATH'] = name
os.environ['FREE_MODE'] = 'true'
from fitcoach.db import (init, save_profile, profile, add_workout, add_nutrition,
                         add_measurement, add_checkin, recent_rows,
                         consume_plan, delete_athlete_data)

init()
uid = 987654321
save_profile(uid, {
    'name':'Smoke Test','age':25,'sex':'unspecified','height':175,'weight':70,
    'goal':'strength','experience':'beginner','equipment':'gym','days':3,
    'recovery':'normal','limitations':'none','medication':'no','notes':''
})
assert profile(uid)['name'] == 'Smoke Test'
add_workout(uid, 'Squat', 3, '10,10,8', 40, 2, '')
add_nutrition(uid, 'Lunch', 650, 35, 70, 20, '')
add_measurement(uid, 70, waist=80)
add_checkin(uid, 7, 4, 2, 5, '')
for table in ('workout_logs','nutrition_logs','body_measurements','daily_checkins'):
    assert len(recent_rows(table, uid)) == 1, table
assert consume_plan(uid)[0] is True
delete_athlete_data(uid)
assert profile(uid) is None
Path(name).unlink(missing_ok=True)
print('PASS: profile, workout, nutrition, measurements, check-in, free mode, delete')
