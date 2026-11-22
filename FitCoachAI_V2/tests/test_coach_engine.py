import unittest

from fitcoach.coach_engine import analyze_training_safety, classify_rir, progression_guidance


class CoachEngineTests(unittest.TestCase):
    def test_shoulder_pain_blocks_loaded_upper_body_patterns(self):
        result = analyze_training_safety(
            limitations="خیر",
            training_history="زیر سینه دمبل | یادداشت: سرشونم درد میومد",
        )
        self.assertEqual(result["region"], "shoulder")
        self.assertTrue({"horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull"}.issubset(set(result["blocked_patterns"])))
        self.assertFalse(result["needs_clarification"])

    def test_unspecified_pain_requires_clarification(self):
        result = analyze_training_safety(training_history="یادداشت: موقع تمرین درد داشتم")
        self.assertTrue(result["needs_clarification"])

    def test_no_pain_does_not_trigger_safety_hold(self):
        result = analyze_training_safety(training_history="یادداشت: بدون درد")
        self.assertFalse(result["pain_signal"])

    def test_rir_outside_standard_range_is_not_usable(self):
        result = classify_rir(10)
        self.assertFalse(result["usable"])
        self.assertIn("۰ تا ۵", result["reason"])

    def test_valid_rir_does_not_auto_increase_load(self):
        result = progression_guidance("پرس سینه", 20, "۱۲،۱۲،۱۰", 2)
        self.assertEqual(result["decision"], "observe")

    def test_pain_prevents_progression(self):
        result = progression_guidance("پرس", 20, "۱۰", 2, "سرشانه درد داشت")
        self.assertEqual(result["decision"], "stop_and_review")


if __name__ == "__main__":
    unittest.main()
