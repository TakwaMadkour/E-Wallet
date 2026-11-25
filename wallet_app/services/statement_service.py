import csv
from pathlib import Path
from wallet_app.result import Result
from wallet_app.security_context import authorize_wallet


class StatementService:
    def __init__(self, db): self.db = db

    def statement(self, wallet_id, principal, start_date=None, end_date=None):
        with self.db.connect() as conn:
            if not authorize_wallet(conn, wallet_id, principal, allow_admin=True):
                return Result.fail("FORBIDDEN", "You are not authorized to view this wallet statement.")
            wallet = conn.execute(
                "SELECT * FROM wallets WHERE wallet_id=?", (wallet_id,)).fetchone()
            where = ["le.wallet_id=?"]
            params = [wallet_id]
            if start_date:
                where.append("date(le.created_at)>=date(?)")
                params.append(start_date)
            if end_date:
                where.append("date(le.created_at)<=date(?)")
                params.append(end_date)
            # rows = conn.execute("SELECT le.entry_id,le.transaction_id,le.amount_minor,le.created_at,t.transaction_type,t.description FROM ledger_entries le JOIN transactions t ON t.transaction_id=le.transaction_id WHERE " +
            #                    " AND ".join(where)+" ORDER BY le.entry_id", params).fetchall()
            rows = conn.execute(
                """
                SELECT
                    le.entry_id,
                    le.transaction_id,
                    le.amount_minor,
                    le.created_at,
                    t.transaction_type,
                    t.description,
                    t.amount_minor AS transaction_amount_minor,
                    t.reversal_of_transaction_id,
                    COALESCE(original.transaction_type, t.transaction_type)
                        AS effective_transaction_type
                FROM ledger_entries le
                JOIN transactions t
                    ON t.transaction_id = le.transaction_id
                LEFT JOIN transactions original
                    ON original.transaction_id = t.reversal_of_transaction_id
                WHERE
                """ + " AND ".join(where) + """
                ORDER BY le.entry_id
                """,
                params
            ).fetchall()
            # opening=conn.execute("SELECT COALESCE(SUM(le.amount_minor),0) FROM ledger_entries le WHERE le.wallet_id=? AND (? IS NULL OR date(le.created_at)<date(?))",(wallet_id,start_date,start_date)).fetchone()[0]
            if start_date is None:
                opening = 0
            else:
                opening = conn.execute(
                    """
                    SELECT COALESCE(SUM(le.amount_minor), 0)
                    FROM ledger_entries le
                    WHERE le.wallet_id = ?
                    AND date(le.created_at) < date(?)
                    """,
                    (wallet_id, start_date),
                ).fetchone()[0]
            running = int(opening)
            entries = []
            for r in rows:
                running += int(r["amount_minor"])
                item = dict(r)
                item["balance_after_minor"] = running
                entries.append(item)
            transfer_totals = conn.execute("SELECT COALESCE(SUM(CASE WHEN le.amount_minor>0 THEN t.amount_minor ELSE 0 END),0) incoming, COALESCE(SUM(CASE WHEN le.amount_minor<0 THEN t.amount_minor ELSE 0 END),0) outgoing FROM ledger_entries le JOIN transactions t ON t.transaction_id=le.transaction_id WHERE le.wallet_id=? AND t.transaction_type='transfer' AND (? IS NULL OR date(t.created_at)>=date(?)) AND (? IS NULL OR date(t.created_at)<=date(?))", (wallet_id, start_date, start_date, end_date, end_date)).fetchone()
            # totals = {"deposits_minor": sum(x["amount_minor"] for x in entries if x["transaction_type"] == "deposit"),
            #          "withdrawals_minor": -sum(x["amount_minor"] for x in entries if x["transaction_type"] == "withdrawal"),
            #          "incoming_transfers_minor": int(transfer_totals["incoming"]),
            #          "outgoing_transfers_minor": int(transfer_totals["outgoing"])}
            deposits = 0
            withdrawals = 0
            incoming_transfers = 0
            outgoing_transfers = 0

            for entry in entries:
                amount = int(entry["amount_minor"])
                transaction_type = entry["effective_transaction_type"]

                is_reversal = entry["reversal_of_transaction_id"] is not None

                if transaction_type == "deposit":
                    # Original deposit is positive; its reversal is negative.
                    deposits += amount

                elif transaction_type == "withdrawal":
                    # Original withdrawal is negative; its reversal is positive.
                    withdrawals -= amount

                elif transaction_type == "transfer":
                    # Determine the direction of the original transfer.
                    direction = 1 if amount > 0 else -1

                    if is_reversal:
                        direction *= -1

                # A reversal subtracts from the original transfer total.
                    net_amount = int(entry["transaction_amount_minor"])
                    if is_reversal:
                        net_amount *= -1

                    if direction > 0:
                        incoming_transfers += net_amount
                    else:
                        outgoing_transfers += net_amount

            totals = {
                "deposits_minor": deposits,
                "withdrawals_minor": withdrawals,
                "incoming_transfers_minor": incoming_transfers,
                "outgoing_transfers_minor": outgoing_transfers,
            }
            fees = conn.execute("SELECT COALESCE(SUM(j.credit_minor-j.debit_minor),0) FROM journal_lines j JOIN transactions t ON t.transaction_id=j.transaction_id WHERE j.account_code='fee_revenue' AND j.account_id=? AND (? IS NULL OR date(t.created_at)>=date(?)) AND (? IS NULL OR date(t.created_at)<=date(?))",
                                (wallet_id, start_date, start_date, end_date, end_date)).fetchone()[0]
            totals["fees_paid_minor"] = int(fees)
            return Result.ok("STATEMENT_READY", "Statement generated.", {"wallet_id": wallet_id, "currency": wallet["currency"], "opening_balance_minor": int(opening), "closing_balance_minor": running, "totals": totals, "entries": entries})

    def export_csv(self, wallet_id, principal, path, start_date=None, end_date=None):
        result = self.statement(wallet_id, principal, start_date, end_date)
        if not result.success:
            return result
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "entry_id",
                "transaction_id",
                "transaction_type",
                "created_at",
                "description",
                "amount_minor",
                "balance_after_minor",
                "transaction_amount_minor",
                "reversal_of_transaction_id",
                "effective_transaction_type",
            ])
            writer.writeheader()
            writer.writerows(result.data["entries"])
        return Result.ok("STATEMENT_EXPORTED", "CSV statement exported.", {"path": str(target.resolve()), "entry_count": len(result.data["entries"])})

    def export_admin_report(self, principal, path):
        if principal is None or principal.role != "admin":
            return Result.fail("FORBIDDEN", "Administrator access required.")
        with self.db.connect() as conn:
            rows = conn.execute("SELECT t.transaction_id,t.transaction_type,t.amount_minor,t.status,w.state AS workflow_state,t.created_at,t.description FROM transactions t LEFT JOIN transaction_workflows w ON w.transaction_id=t.transaction_id ORDER BY t.transaction_id").fetchall()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                                    "transaction_id", "transaction_type", "amount_minor", "status", "workflow_state", "created_at", "description"])
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
        return Result.ok("REPORT_EXPORTED", "Transaction report exported.", {"path": str(target.resolve()), "row_count": len(rows)})
