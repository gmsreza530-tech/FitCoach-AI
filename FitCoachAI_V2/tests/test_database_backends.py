import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fitcoach import db as database


class DatabaseBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fitcoach-test.db"
        self.url_patch = patch.object(database, "DATABASE_URL", "")
        self.path_patch = patch.object(database, "DATABASE_PATH", self.db_path)
        self.url_patch.start()
        self.path_patch.start()
        database.init()

    def tearDown(self):
        self.path_patch.stop()
        self.url_patch.stop()
        self.temp_dir.cleanup()

    def test_account_wallet_and_idempotent_reference(self):
        user = SimpleNamespace(
            id=9876543210, username="athlete", first_name="Test", last_name="User"
        )
        account = database.register_account(user)
        self.assertEqual(account["telegram_id"], user.id)
        self.assertEqual(database.wallet_balance(user.id), 0)

        first_id = database.add_wallet_transaction(
            user.id, 25000, "topup", "test top-up", reference="test-ref-1"
        )
        retry_id = database.add_wallet_transaction(
            user.id, 25000, "topup", "retry", reference="test-ref-1"
        )
        self.assertEqual(first_id, retry_id)
        self.assertEqual(database.wallet_balance(user.id), 25000)
        self.assertEqual(len(database.wallet_history(user.id)), 1)

    def test_profile_chat_and_program_round_trip(self):
        uid = 9876543210
        database.save_profile(uid, {
            "name": "Test", "age": 25, "sex": "—", "height": 180,
            "weight": 80, "goal": "strength", "experience": "beginner",
            "equipment": "gym", "days": 3, "recovery": "good",
            "limitations": "none", "medication": "none", "notes": "",
        })
        self.assertEqual(database.profile(uid)["weight"], 80)

        database.start_conversation(uid)
        self.assertTrue(database.is_conversation_active(uid))
        database.add_conversation_message(uid, "user", "Hello")
        database.add_conversation_message(uid, "assistant", "Hi")
        self.assertEqual(
            [item["role"] for item in database.get_conversation_history(uid)],
            ["user", "assistant"],
        )
        database.end_conversation(uid)
        self.assertFalse(database.is_conversation_active(uid))

        program_id = database.create_program(
            uid, 0, "workout", "build strength", "plan text", "approved"
        )
        self.assertEqual(database.get_program(program_id)["content"], "plan text")
        self.assertEqual(database.stats()[0], 1)

    def test_init_is_idempotent(self):
        database.init()
        database.init()
        self.assertEqual(database.stats(), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
