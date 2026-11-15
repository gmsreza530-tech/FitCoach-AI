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


if __name__ == "__main__":
    unittest.main()
