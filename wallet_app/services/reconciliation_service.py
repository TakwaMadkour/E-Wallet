import json
from wallet_app.result import Result
from wallet_app.security_context import require_admin

class ReconciliationService:
    def __init__(self,db): self.db=db
    def run(self,principal=None):
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.transaction() as conn:
            issues=[]
            unbalanced=conn.execute("SELECT transaction_id,SUM(debit_minor) d,SUM(credit_minor) c,COUNT(*) n FROM journal_lines GROUP BY transaction_id HAVING d!=c OR n<2").fetchall()
            for r in unbalanced: issues.append({"type":"UNBALANCED_JOURNAL","transaction_id":r["transaction_id"],"debits":r["d"],"credits":r["c"]})
            txs=conn.execute("SELECT transaction_id,transaction_type FROM transactions").fetchall()
            for tx in txs:
                txid=tx["transaction_id"]
                entries=conn.execute("SELECT wallet_id,amount_minor FROM ledger_entries WHERE transaction_id=?",(txid,)).fetchall()
                journal=conn.execute("SELECT account_code,account_id,debit_minor,credit_minor FROM journal_lines WHERE transaction_id=?",(txid,)).fetchall()
                if not entries: issues.append({"type":"MISSING_WALLET_LEDGER","transaction_id":txid})
                if not journal: issues.append({"type":"MISSING_JOURNAL","transaction_id":txid})
                expected=2 if tx["transaction_type"] in ("transfer",) else 1
                if tx["transaction_type"] in ("deposit","withdrawal") and len(entries)!=expected:
                    issues.append({"type":"INVALID_LEDGER_ENTRY_COUNT","transaction_id":txid,"count":len(entries)})
                wallet_ids={int(x["wallet_id"]) for x in entries}
                wallet_ids.update(int(x["account_id"]) for x in journal if x["account_code"]=="wallet_liability" and x["account_id"] is not None)
                for wid in wallet_ids:
                    sub=sum(int(x["amount_minor"]) for x in entries if int(x["wallet_id"])==wid)
                    net=sum(int(x["credit_minor"])-int(x["debit_minor"]) for x in journal if x["account_code"]=="wallet_liability" and x["account_id"]==wid)
                    if sub!=net: issues.append({"type":"TRANSACTION_WALLET_JOURNAL_MISMATCH","transaction_id":txid,"wallet_id":wid,"subledger":sub,"journal_net":net})
            # Wallet sub-ledger balances must equal their wallet-liability journal balances.
            wallets=conn.execute("SELECT wallet_id FROM wallets").fetchall()
            for w in wallets:
                sub=int(conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM ledger_entries WHERE wallet_id=?",(w[0],)).fetchone()[0])
                j=conn.execute("SELECT COALESCE(SUM(credit_minor-debit_minor),0) FROM journal_lines WHERE account_code='wallet_liability' AND account_id=?",(w[0],)).fetchone()[0]
                if sub!=int(j): issues.append({"type":"WALLET_RECONCILIATION_MISMATCH","wallet_id":w[0],"subledger":sub,"control_account":int(j)})
            status="passed" if not issues else "failed"
            cur=conn.execute("INSERT INTO reconciliation_runs(status,discrepancies) VALUES(?,?)",(status,json.dumps(issues,sort_keys=True)))
            conn.commit()
            return Result.ok("RECONCILIATION_COMPLETED","Reconciliation completed.",{"run_id":cur.lastrowid,"status":status,"discrepancies":issues})
