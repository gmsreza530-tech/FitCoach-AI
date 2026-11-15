"""Regression tests for quota and coach-review hardening."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fitcoach import db as database


class ProductionHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(database, "DATABASE_PATH", Path(self.temp_dir.name) / "test.sqlite"),
            patch.object(database, "DATABASE_URL", ""),
            patch.object(database, "FREE_MODE", False),
        ]
        for item in self.patches:
            item.start()
        database.init()
        database.register_account(
            type("TelegramUser", (), {
                "id": 1001, "username": "athlete", "first_name": "Test",
                "last_name": None,
            })(),
            role="athlete",
        )

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_preflight_does_not_consume_quota(self):
        database.grant(1001, days=30, limit=2)
        allowed, _ = database.check_plan_access(1001)
        self.assertTrue(allowed)
        self.assertEqual(database.access_info(1001)["plans_used"], 0)

    def test_quota_consumption_is_bounded(self):
        database.grant(1001, days=30, limit=1)
        self.assertTrue(database.consume_plan(1001)[0])
        self.assertFalse(database.consume_plan(1001)[0])
        self.assertEqual(database.access_info(1001)["plans_used"], 1)

    def test_athlete_roster_is_scoped_to_assigned_coach(self):
        coach_one = type("TelegramUser", (), {
            "id": 2002, "username": "coach1", "first_name": "Coach1",
            "last_name": None,
        })()
        coach_two = type("TelegramUser", (), {
            "id": 3003, "username": "coach2", "first_name": "Coach2",
            "last_name": None,
        })()
        database.register_account(coach_one, role="coach")
        database.register_account(coach_two, role="coach")
        database.assign_athlete(1001, 2002)
        self.assertEqual(database.athlete_coach(1001), 2002)
        self.assertEqual([row["telegram_id"] for row in database.list_coach_athletes(2002)], [1001])
        self.assertEqual(database.list_coach_athletes(3003), [])

    def test_review_is_pending_only_and_coach_scoped(self):
        program_id = database.create_program(
            1001, 2002, "workout", "request", "content", "pending"
        )
        self.assertFalse(database.review(program_id, "approved", coach_id=3003))
        self.assertTrue(database.review(program_id, "approved", coach_id=2002))
        self.assertFalse(database.review(program_id, "rejected", coach_id=2002))
        self.assertEqual(database.get_program(program_id)["status"], "approved")


if __name__ == "__main__":
    unittest.main()
