import tempfile
import unittest
from pathlib import Path
from wallet_app.database import Database
from wallet_app.services.auth_service import AuthService
from wallet_app.services.wallet_service import WalletService
from wallet_app.services.transfer_service import TransferService
from wallet_app.security_context import Principal
from wallet_app.services.reversal_service import ReversalService
from wallet_app.services.reconciliation_service import ReconciliationService
from wallet_app.services.notification_service import NotificationService
from wallet_app.services.statement_service import StatementService


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.auth = AuthService(self.db)
        self.wallet = WalletService(self.db)
        self.transfer = TransferService(self.db)
        self.reversal = ReversalService(self.db)
        # for the sake of testing
        self.password = "UserWallet#2026Secure"
        a = self.auth.register("Ahmed", "ahmed@example.com",
                               "01000000001", self.password)
        b = self.auth.register("Sara", "sara@example.com",
                               "01000000002", self.password)
        self.wa = a.data["wallet_id"]
        self.wb = b.data["wallet_id"]
        self.pa = Principal(a.data["user_id"], "customer")
        self.pb = Principal(b.data["user_id"], "customer")
        with self.db.transaction() as conn:
            cur = conn.execute("INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?,'admin')",
                               ("Admin", "admin@example.com", "01000000999", "test-hash"))
            self.admin = Principal(cur.lastrowid, "admin")
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_deposit_and_withdraw(self):
        self.assertTrue(self.wallet.deposit(
            self.wa, "1000.00", "dep-1", self.pa).success)
        self.assertTrue(self.wallet.withdraw(
            self.wa, "250.50", "wd-1", self.pa).success)
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 74950)

    def test_insufficient_funds(self):
        result = self.wallet.withdraw(self.wa, "1", "wd-insufficient", self.pa)
        self.assertEqual(result.code, "INSUFFICIENT_FUNDS")

    def test_idempotent_deposit(self):
        first = self.wallet.deposit(self.wa, "10", "same-key", self.pa)
        second = self.wallet.deposit(self.wa, "10", "same-key", self.pa)
        self.assertTrue(first.success and second.success)
        self.assertEqual(second.code, "REPLAYED")
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 1000)

    def test_idempotency_key_payload_conflict(self):
        self.wallet.deposit(self.wa, "10", "same-key", self.pa)
        result = self.wallet.deposit(self.wa, "20", "same-key", self.pa)
        self.assertEqual(result.code, "IDEMPOTENCY_CONFLICT")

    def test_transfer_balances_and_two_entries(self):
        self.wallet.deposit(self.wa, "100", "seed", self.pa)
        result = self.transfer.transfer(
            self.wa, self.wb, "30", "transfer-1", self.pa)
        self.assertTrue(result.success)
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 7000)
        self.assertEqual(self.wallet.get_balance(
            self.wb, self.pb).data["balance_minor"], 3000)
        conn = self.db.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                (result.data["transaction_id"],)
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(count, 2)

    def test_float_precision_is_not_used(self):
        result = self.wallet.deposit(self.wa, "0.001", "too-precise", self.pa)
        self.assertEqual(result.code, "INVALID_AMOUNT")

    def test_authorization_blocks_other_wallet_access(self):
        self.assertEqual(self.wallet.get_balance(
            self.wb, self.pa).code, "FORBIDDEN")
        self.assertEqual(self.wallet.deposit(
            self.wb, "5", "steal", self.pa).code, "FORBIDDEN")

    def test_double_entry_journal_balances_and_reconciles(self):
        self.wallet.deposit(self.wa, "100", "journal-dep", self.pa)
        result = self.transfer.transfer(
            self.wa, self.wb, "25", "journal-transfer", self.pa)
        self.assertTrue(result.success)
        with self.db.connect() as conn:
            totals = conn.execute("SELECT SUM(debit_minor),SUM(credit_minor) FROM journal_lines WHERE transaction_id=?", (
                result.data["transaction_id"],)).fetchone()
            self.assertEqual(totals[0], totals[1])
        recon = ReconciliationService(self.db).run(self.admin)
        self.assertEqual(recon.data["status"], "passed")

    def test_reversal_is_compensating_and_only_once(self):
        deposit = self.wallet.deposit(self.wa, "100", "reverse-seed", self.pa)
        reversal = ReversalService(self.db).reverse(
            deposit.data["transaction_id"], "reverse-key", self.admin, "test")
        self.assertTrue(reversal.success)
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 0)
        again = ReversalService(self.db).reverse(
            deposit.data["transaction_id"], "reverse-key-2", self.admin, "again")
        self.assertEqual(again.code, "ALREADY_REVERSED")
    """
    def test_notifications_and_csv_statement(self):
        self.wallet.deposit(self.wa,"12.34","statement-seed",self.pa)
        notes=NotificationService(self.db).list_for_user(self.pa)
        self.assertTrue(notes.success and len(notes.data)>=1)
        import tempfile, os
        path=os.path.join(self.temp.name,"statement.csv")
        exported=StatementService(self.db).export_csv(self.wa,self.pa,path)
        self.assertTrue(exported.success and os.path.exists(path))
    """

    def test_statement_balances_without_start_date(self):
        self.wallet.deposit(self.wa, "100", "statement-deposit", self.pa)
        self.wallet.withdraw(self.wa, "30", "statement-withdraw", self.pa)

        service = StatementService(self.db)
        statement = service.statement(self.wa, self.pa)

        self.assertTrue(statement.success)
        self.assertEqual(statement.data["opening_balance_minor"], 0)
        self.assertEqual(statement.data["closing_balance_minor"], 7000)

        balances = [
            entry["balance_after_minor"]
            for entry in statement.data["entries"]
        ]
        self.assertEqual(balances, [10000, 7000])

        import csv
        path = Path(self.temp.name) / "statement.csv"

        exported = service.export_csv(self.wa, self.pa, path)
        self.assertTrue(exported.success)

        with path.open(newline="", encoding="utf-8") as file:
            csv_rows = list(csv.DictReader(file))

        csv_balances = [
            int(row["balance_after_minor"])
            for row in csv_rows
        ]
        self.assertEqual(csv_balances, [10000, 7000])

    def test_transfer_fee_is_accounted_for(self):
        self.wallet.deposit(self.wa, "100", "fee-seed", self.pa)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE transaction_policies SET policy_value=100 WHERE policy_key='transfer_fee_bps'")
            conn.commit()
        result = self.transfer.transfer(
            self.wa, self.wb, "10", "fee-transfer", self.pa)
        self.assertTrue(result.success)
        self.assertEqual(result.data["fee_minor"], 10)
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 8990)
        statement = StatementService(self.db).statement(self.wa, self.pa)
        self.assertEqual(statement.data["totals"]["fees_paid_minor"], 10)
        recon = ReconciliationService(self.db).run(self.admin)
        self.assertEqual(recon.data["status"], "passed")

    def test_transaction_intent_state_machine(self):
        from wallet_app.services.state_machine_service import TransactionStateMachine
        machine = TransactionStateMachine(self.db)
        created = machine.create_intent(
            self.pa, self.wa, "transfer", 2500, "intent-1", self.wb)
        self.assertTrue(created.success)
        intent_id = created.data["intent_id"]
        self.assertEqual(machine.transition_intent(
            intent_id, "processing", self.admin, "worker picked up").code, "STATE_UPDATED")
        self.assertEqual(machine.transition_intent(
            intent_id, "completed", self.admin, "provider confirmed").code, "STATE_UPDATED")
        self.assertEqual(machine.transition_intent(
            intent_id, "processing", self.admin).code, "INVALID_STATE_TRANSITION")
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 0)

    def test_concurrent_withdrawals_do_not_overdraw(self):
        from concurrent.futures import ThreadPoolExecutor
        self.wallet.deposit(self.wa, "100", "concurrency-seed", self.pa)
        def withdraw(key): return self.wallet.withdraw(
            self.wa, "80", key, self.pa)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(withdraw, ["parallel-1", "parallel-2"]))
        self.assertEqual(sum(1 for r in results if r.success), 1)
        self.assertEqual(self.wallet.get_balance(
            self.wa, self.pa).data["balance_minor"], 2000)

    def test_admin_methods_require_admin(self):
        from wallet_app.services.admin_service import AdminService
        self.assertEqual(AdminService(self.db).list_customers(
            self.pa).code, "FORBIDDEN")

    def test_statement_totals_account_for_reversed_deposit(self):
        deposit = self.wallet.deposit(
            self.wa, "100", "statement-reversal-deposit", self.pa
        )
        self.assertTrue(deposit.success)

        reversal = ReversalService(self.db).reverse(
            deposit.data["transaction_id"],
            "statement-reversal-key",
            self.admin,
            "Test reversal",
        )
        self.assertTrue(reversal.success)

        statement = StatementService(self.db).statement(
            self.wa, self.pa
        )

        self.assertTrue(statement.success)

        totals = statement.data["totals"]

        self.assertEqual(totals["deposits_minor"], 0)
        self.assertEqual(statement.data["opening_balance_minor"], 0)
        self.assertEqual(statement.data["closing_balance_minor"], 0)

    def test_reversed_withdrawal_releases_daily_limit(self):

        # Configure daily withdrawal limit to 130 EGP.
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO transaction_policies
                    (policy_key, policy_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(policy_key)
                DO UPDATE SET policy_value=excluded.policy_value
                """,
                ("daily_withdrawal_minor", 13000),
            )
            conn.commit()
        # Fund the wallet before withdrawing.
        deposit = self.wallet.deposit(
            self.wa, "200", "deposit-1", self.pa
        )
        self.assertTrue(deposit.success)

        # First withdrawal: 80 EGP.

        first = self.wallet.withdraw(
            self.wa, "80", "withdraw-1", self.pa
        )
        # self.assertTrue(first.success)

        self.assertTrue(
            first.success,
            f"Code: {first.code}, Message: {first.message}"
        )
        # Reverse the first withdrawal.
        reversal = self.reversal.reverse(
            first.data["transaction_id"],
            "reverse-1",
            self.admin,
            "Test reversal",
        )
        self.assertTrue(reversal.success)

        # This should now succeed.
        second = self.wallet.withdraw(
            self.wa, "80", "withdraw-2", self.pa
        )

        self.assertTrue(second.success)

    def test_update_profile_with_correct_password(self):
        result = self.auth.update_profile(
            self.pa,
            self.password,
            "Ahmed Updated",
            "ahmed_new@example.com",
            "01000000111"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.code, "PROFILE_UPDATED")

        conn = self.db.transaction()
        try:
            user = conn.execute(
                "SELECT name, email, phone FROM users WHERE user_id=?",
                (self.pa.user_id,)
            ).fetchone()

            self.assertEqual(user["name"], "Ahmed Updated")
            self.assertEqual(user["email"], "ahmed_new@example.com")
            self.assertEqual(user["phone"], "+201000000111")
        finally:
            conn.close()

    def test_update_profile_with_incorrect_password(self):
        result = self.auth.update_profile(
            self.pa,
            "wrongpassword",
            "Ahmed Updated",
            "ahmed_new@example.com",
            "01000000111"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_CREDENTIALS")

        conn = self.db.transaction()
        try:
            user = conn.execute(
                "SELECT name, email, phone FROM users WHERE user_id=?",
                (self.pa.user_id,)
            ).fetchone()

            self.assertEqual(user["name"], "Ahmed")
            self.assertEqual(user["email"], "ahmed@example.com")
            self.assertEqual(user["phone"], "+201000000001")
        finally:
            conn.close()

    def test_update_profile_creates_audit_log(self):
        result = self.auth.update_profile(
            self.pa,
            self.password,
            "Ahmed Updated",
            "ahmed_new@example.com",
            "01000000111"
        )

        self.assertTrue(result.success)

        conn = self.db.transaction()
        try:
            audit = conn.execute(
                """
                SELECT * FROM audit_logs
                WHERE actor_user_id=?
                AND action='PROFILE_UPDATED'
                AND entity_type='user'
                AND entity_id=?
                """,
                (self.pa.user_id, str(self.pa.user_id))
            ).fetchone()

            self.assertIsNotNone(audit)
        finally:
            conn.close()

    def test_update_profile_with_duplicate_email(self):
        result = self.auth.update_profile(
            self.pa,
            self.password,
            "Ahmed",
            "sara@example.com",
            "01000000111"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "DUPLICATE_USER")

    def test_update_profile_with_duplicate_phone(self):
        result = self.auth.update_profile(
            self.pa,
            self.password,
            "Ahmed",
            "ahmed_new@example.com",
            "01000000002"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "DUPLICATE_USER")

    def test_update_profile_requires_authentication(self):
        result = self.auth.update_profile(
            None,
            "password123",
            "Ahmed",
            "ahmed_new@example.com",
            "01000000111"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "FORBIDDEN")

    def test_register_rejects_invalid_email(self):
        result = self.auth.register(
            "Ahmed",
            "a@",
            "01000000003",
            self.password
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_EMAIL")

    def test_register_rejects_invalid_phone(self):
        result = self.auth.register(
            "Ahmed",
            "ahmed_new@example.com",
            "abc",
            self.password
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_PHONE")

    def test_register_rejects_duplicate_normalized_phone(self):
        result = self.auth.register(
            "Another Ahmed",
            "another_ahmed@example.com",
            "+201000000001",
            self.password
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "DUPLICATE_USER")

    def test_register_rejects_weak_password(self):
        result = self.auth.register(
            "Ahmed",
            "weak_password@example.com",
            "01000000003",
            "12345678"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_PASSWORD")

    def test_register_accepts_valid_data(self):
        result = self.auth.register(
            "Mohamed",
            "mohamed@example.com",
            "01000000003",
            "MohamedWallet#2026"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.code, "REGISTERED")

    def test_update_profile_rejects_invalid_email(self):
        result = self.auth.update_profile(
            self.pa,
            self.password,
            "Ahmed",
            "a@",
            "01000000001"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_EMAIL")

    def test_update_profile_rejects_invalid_phone(self):
        result = self.auth.update_profile(
            self.pa,
            self.password,
            "Ahmed",
            "ahmed@example.com",
            "abc"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_PHONE")

    def test_change_password_rejects_weak_password(self):
        result = self.auth.change_password(
            self.pa,
            self.password,
            "12345678"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.code, "INVALID_PASSWORD")

    def test_change_password_accepts_strong_password(self):
        new_password = "NewAhmedWallet#2027"

        result = self.auth.change_password(
            self.pa,
            self.password,
            new_password
        )

        self.assertTrue(result.success)
        self.assertEqual(result.code, "PASSWORD_CHANGED")

        # Verify the new password works
        result = self.auth.change_password(
            self.pa,
            new_password,
            "AnotherStrongPassword#2028"
        )

        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
