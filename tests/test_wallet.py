import tempfile
import unittest
from pathlib import Path
from wallet_app.database import Database
from wallet_app.services.auth_service import AuthService
from wallet_app.services.wallet_service import WalletService
from wallet_app.services.transfer_service import TransferService

class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.auth = AuthService(self.db)
        self.wallet = WalletService(self.db)
        self.transfer = TransferService(self.db)
        a = self.auth.register("Ahmed", "ahmed@example.com", "01000000001", "password123")
        b = self.auth.register("Sara", "sara@example.com", "01000000002", "password123")
        self.wa = a.data["wallet_id"]
        self.wb = b.data["wallet_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_deposit_and_withdraw(self):
        self.assertTrue(self.wallet.deposit(self.wa, "1000.00", "dep-1").success)
        self.assertTrue(self.wallet.withdraw(self.wa, "250.50", "wd-1").success)
        self.assertEqual(self.wallet.get_balance(self.wa).data["balance_minor"], 74950)

    def test_insufficient_funds(self):
        result = self.wallet.withdraw(self.wa, "1", "wd-insufficient")
        self.assertEqual(result.code, "INSUFFICIENT_FUNDS")

    def test_idempotent_deposit(self):
        first = self.wallet.deposit(self.wa, "10", "same-key")
        second = self.wallet.deposit(self.wa, "10", "same-key")
        self.assertTrue(first.success and second.success)
        self.assertEqual(second.code, "REPLAYED")
        self.assertEqual(self.wallet.get_balance(self.wa).data["balance_minor"], 1000)

    def test_idempotency_key_payload_conflict(self):
        self.wallet.deposit(self.wa, "10", "same-key")
        result = self.wallet.deposit(self.wa, "20", "same-key")
        self.assertEqual(result.code, "IDEMPOTENCY_CONFLICT")

    def test_transfer_balances_and_two_entries(self):
        self.wallet.deposit(self.wa, "100", "seed")
        result = self.transfer.transfer(self.wa, self.wb, "30", "transfer-1")
        self.assertTrue(result.success)
        self.assertEqual(self.wallet.get_balance(self.wa).data["balance_minor"], 7000)
        self.assertEqual(self.wallet.get_balance(self.wb).data["balance_minor"], 3000)
        with self.db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                (result.data["transaction_id"],)
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_float_precision_is_not_used(self):
        result = self.wallet.deposit(self.wa, "0.001", "too-precise")
        self.assertEqual(result.code, "INVALID_AMOUNT")

if __name__ == "__main__":
    unittest.main()
