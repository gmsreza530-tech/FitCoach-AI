import unittest

from fitcoach.program_formatter import WorkoutFormatError, format_workout_plan, validate_workout_plan


def make_plan(push_pattern="horizontal_push", push_focus="Push"):
    return {
        "title": "برنامه آزمایشی",
        "goal": "افزایش قدرت",
        "adaptation_notes": ["برای این تست سابقه تمرینی قابل مقایسه‌ای ارائه نشده است؛ بار تمرین حدس زده نمی‌شود."],
        "weekly_schedule": [
            {
                "day": "روز اول",
                "focus": push_focus,
                "exercises": [
                    {
                        "name": "پرس سینه",
                        "movement_pattern": push_pattern,
                        "muscle_groups": ["chest", "triceps"],
                        "skill_level": "beginner",
                        "sets": 3,
                        "reps": "۸ تا ۱۲",
                        "rest": "۹۰ ثانیه",
                        "rir": 2,
                        "note": "کنترل حرکت",
                    }
                ],
            }
        ],
    }


class WorkoutQualityTests(unittest.TestCase):
    def test_valid_plan_formats(self):
        profile = {"name": "آزمایش", "experience": "مبتدی", "days": "۱", "limitations": "خیر", "medication": "خیر"}
        text = format_workout_plan(make_plan(), profile)
        self.assertIn("برنامه تمرینی FitCoach AI", text)

    def test_push_day_rejects_pull_pattern(self):
        with self.assertRaises(WorkoutFormatError):
            validate_workout_plan(make_plan(push_pattern="vertical_pull"))

    def test_profile_day_count_must_match(self):
        with self.assertRaises(WorkoutFormatError):
            validate_workout_plan(make_plan(), {"days": "۴"})

    def test_beginner_rejects_weighted_pullup(self):
        plan = make_plan()
        ex = plan["weekly_schedule"][0]["exercises"][0]
        ex.update({"name": "بارفیکس با وزنه", "movement_pattern": "vertical_pull", "muscle_groups": ["back"], "skill_level": "advanced"})
        with self.assertRaises(WorkoutFormatError):
            validate_workout_plan(plan, {"experience": "مبتدی"})

    def test_health_flags_require_review(self):
        warnings = validate_workout_plan(make_plan(), {"limitations": "آسیب زانو"})
        self.assertTrue(any("محدودیت پزشکی" in item for item in warnings))

    def test_blocked_pattern_is_hard_rejected(self):
        profile = {"safety_context": {"blocked_patterns": ["horizontal_push"]}}
        with self.assertRaisesRegex(WorkoutFormatError, "الگوی حرکتی ممنوع"):
            validate_workout_plan(make_plan(), profile)

    def test_safety_flag_requires_coach_review(self):
        profile = {"safety_context": {"requires_coach_review": True}}
        warnings = validate_workout_plan(make_plan(), profile)
        self.assertTrue(any("بازبینی مربی" in item for item in warnings))

    def test_exercise_name_is_standardized(self):
        plan = make_plan()
        plan["weekly_schedule"][0]["exercises"][0]["name"] = "پرس دمبل زیر سینه"
        result = format_workout_plan(plan)
        self.assertIn("پرس بالا سینه دمبل", result)



if __name__ == "__main__":
    unittest.main()
