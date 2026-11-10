"""Unit tests for the deterministic workout formatter."""
import unittest

from fitcoach.program_formatter import format_workout_plan, WorkoutFormatError


VALID = {
    "title": "برنامه افزایش قدرت",
    "goal": "قدرت",
    "warmup": "۵ تا ۱۰ دقیقه فعالیت سبک",
    "weekly_schedule": [
        {
            "day": "روز اول",
            "focus": "پایین تنه",
            "exercises": [
                {
                    "name": "اسکوات",
                    "sets": "۳",
                    "reps": "۸ تا ۱۰",
                    "rest": "۱۲۰ ثانیه",
                    "rir": "۲",
                    "note": "دامنه کنترل‌شده",
                }
            ],
        }
    ],
    "cooldown": "راه رفتن آرام",
    "general_notes": ["افزایش وزنه تدریجی باشد"],
    "medical_cautions": [],
}


class WorkoutFormatterTests(unittest.TestCase):
    def test_renders_stable_persian_sections(self):
        result = format_workout_plan(VALID, {"name": "آزمون", "goal": "قدرت"})
        self.assertIn("🏋️‍♂️ برنامه تمرینی FitCoach AI", result)
        self.assertIn("📅 روز اول | پایین تنه", result)
        self.assertIn("ست: ۳  |  تکرار: ۸ تا ۱۰", result)
        self.assertIn("استراحت: ۱۲۰ ثانیه  |  RIR: ۲", result)
        self.assertIn("آزمون", result)

    def test_rejects_missing_exercise_fields(self):
        broken = dict(VALID)
        broken["weekly_schedule"] = [{
            "day": "روز اول",
            "exercises": [{"name": "اسکوات", "sets": "۳", "reps": "۱۰"}],
        }]
        with self.assertRaises(WorkoutFormatError):
            format_workout_plan(broken)

    def test_rejects_invalid_day_count(self):
        with self.assertRaises(WorkoutFormatError):
            format_workout_plan({"weekly_schedule": []})

    def test_accepts_json_fenced_response(self):
        import json
        result = format_workout_plan("```json\\n" + json.dumps(VALID, ensure_ascii=False) + "\\n```")
        self.assertIn("برنامه تمرینی FitCoach AI", result)


if __name__ == "__main__":
    unittest.main()
