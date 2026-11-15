"""Regression tests for structured workout JSON generation."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fitcoach import ai


class WorkoutJsonGenerationTests(unittest.TestCase):
    @patch("fitcoach.ai.search_knowledge", return_value=[])
    @patch("fitcoach.ai.Groq")
    def test_truncated_json_is_not_continued_or_concatenated(self, groq_mock, _knowledge):
        groq_mock.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"title":"incomplete"'),
                    finish_reason="length",
                )
            ]
        )

        with patch.object(ai, "GROQ_API_KEY", "test-key"):
            result = ai.ask({}, "برنامه تمرینی بساز", 123, output_format="workout_json")

        self.assertEqual(result, '{"title":"incomplete"')
        self.assertEqual(groq_mock.return_value.chat.completions.create.call_count, 1)
        kwargs = groq_mock.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    @patch("fitcoach.ai.search_knowledge", return_value=[])
    @patch("fitcoach.ai.Groq")
    def test_complete_json_is_returned_without_extra_completion(self, groq_mock, _knowledge):
        expected = '{"title":"complete"}'
        groq_mock.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=expected),
                    finish_reason="stop",
                )
            ]
        )

        with patch.object(ai, "GROQ_API_KEY", "test-key"):
            result = ai.ask({}, "برنامه تمرینی بساز", 123, output_format="workout_json")

        self.assertEqual(result, expected)
        self.assertEqual(groq_mock.return_value.chat.completions.create.call_count, 1)


    @patch("fitcoach.ai.search_knowledge", return_value=[])
    @patch("fitcoach.ai.Groq")
    def test_workout_prompt_contains_full_profile_and_exact_session_count(self, groq_mock, _knowledge):
        groq_mock.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"title":"ok"}'),
                    finish_reason="stop",
                )
            ]
        )
        profile = {
            "name": "Athlete", "age": 25, "sex": "male", "height": 180,
            "weight": 80, "goal": "muscle gain", "experience": "beginner",
            "equipment": "full gym", "days": 4, "recovery": "7 hours sleep",
            "limitations": "no known limitations", "medication": "no",
            "notes": "avoid painful movements",
        }
        with patch.object(ai, "GROQ_API_KEY", "test-key"):
            ai.ask(profile, "برنامه تمرینی بساز", 123, output_format="workout_json")

        messages = groq_mock.return_value.chat.completions.create.call_args.kwargs["messages"]
        system_text = "\\n".join(m["content"] for m in messages if m["role"] == "system")
        for value in ("Athlete", "25", "180", "80", "muscle gain", "beginner",
                      "full gym", "7 hours sleep", "avoid painful movements"):
            self.assertIn(value, system_text)
        self.assertIn("دقیقاً 4 جلسه تمرین", system_text)
        self.assertIn("weekly_schedule باید دقیقاً 4 عضو", system_text)
        self.assertIn("روزهای استراحت را اصلاً داخل weekly_schedule قرار نده", system_text)

if __name__ == "__main__":
    unittest.main()
