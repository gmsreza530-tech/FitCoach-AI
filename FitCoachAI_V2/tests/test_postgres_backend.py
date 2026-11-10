"""PostgreSQL integration test. Runs only when DATABASE_URL points to a test database."""
import os
import time
import unittest
from types import SimpleNamespace

from fitcoach import db as database


@unittest.skipUnless(database.DATABASE_URL, "DATABASE_URL is not configured")
class PostgreSQLBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init()
        cls.uid = time.time_ns() % 8_000_000_000_000_000_000
        cls.reference = f"ci-postgres-{cls.uid}"
        database.register_account(SimpleNamespace(
            id=cls.uid, username="ci_test", first_name="CI", last_name="Postgres"
        ))

    @classmethod
    def tearDownClass(cls):
        with database.db() as connection:
            for table in (
                "wallet_transactions", "payments", "programs", "conversations",
                "conversation_sessions", "progress", "access", "athletes",
                "accounts",
            ):
                key = "telegram_id" if table in {"accounts", "athletes"} else "athlete_id"
                if table == "wallet_transactions":
                    connection.execute("DELETE FROM wallet_transactions WHERE telegram_id=?", (cls.uid,))
                elif table == "accounts":
                    connection.execute("DELETE FROM accounts WHERE telegram_id=?", (cls.uid,))
                else:
                    connection.execute(f"DELETE FROM {table} WHERE {key}=?", (cls.uid,))

    def test_schema_and_core_flows(self):
        with database.db() as connection:
            for table in (
                "accounts", "wallet_transactions", "athletes", "programs",
                "payments", "conversations", "conversation_sessions",
                "workout_logs", "nutrition_logs", "body_measurements",
                "daily_checkins",
            ):
                row = connection.execute(
                    "SELECT to_regclass(?) AS table_name", (f"public.{table}",)
                ).fetchone()
                self.assertIsNotNone(row["table_name"], f"missing table: {table}")

        transaction_id = database.add_wallet_transaction(
            self.uid, 12345, "topup", "CI test", reference=self.reference
        )
        retry_id = database.add_wallet_transaction(
            self.uid, 12345, "topup", "CI retry", reference=self.reference
        )
        self.assertEqual(transaction_id, retry_id)
        self.assertEqual(database.wallet_balance(self.uid), 12345)

        database.save_profile(self.uid, {
            "name": "Postgres CI", "age": 25, "sex": "unspecified",
            "height": 180, "weight": 80, "goal": "strength",
            "experience": "beginner", "equipment": "gym", "days": 3,
            "recovery": "normal", "limitations": "none",
            "medication": "none", "notes": "",
        })
        self.assertEqual(database.profile(self.uid)["name"], "Postgres CI")

        database.start_conversation(self.uid)
        database.add_conversation_message(self.uid, "user", "hello")
        database.add_conversation_message(self.uid, "assistant", "hello back")
        self.assertTrue(database.is_conversation_active(self.uid))
        self.assertEqual(len(database.get_conversation_history(self.uid)), 2)

        program_id = database.create_program(
            self.uid, 0, "workout", "CI", "program body", "pending"
        )
        self.assertEqual(database.get_program(program_id)["content"], "program body")


if __name__ == "__main__":
    unittest.main()
