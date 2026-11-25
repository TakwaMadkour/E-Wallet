from wallet_app.result import Result
from wallet_app.services.common import request_fingerprint, replay_or_conflict
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.repositories.wallet_repository import WalletRepository
from wallet_app.repositories.ledger_repository import LedgerRepository
from wallet_app.services.accounting_service import AccountingService
from wallet_app.services.notification_service import NotificationService
from wallet_app.services.audit_service import AuditService
from wallet_app.security_context import authorize_wallet, require_admin
from wallet_app.observability import log_event, new_correlation_id

class ReversalService:
    def __init__(self,db):
        self.db=db; self.transactions=TransactionRepository(); self.wallets=WalletRepository(); self.ledger=LedgerRepository()

    def reverse(self,transaction_id,idempotency_key,principal,reason="Customer support reversal"):
        if not idempotency_key or not str(idempotency_key).strip(): return Result.fail("IDEMPOTENCY_KEY_REQUIRED","An idempotency key is required.")
        if not require_admin(principal): return Result.fail("FORBIDDEN","Only an administrator may reverse a posted transaction.")
        fingerprint=request_fingerprint("reversal",[transaction_id],1,{"reason":reason})
        new_correlation_id()
        conn=self.db.transaction()
        try:
            replay=replay_or_conflict(self.transactions,conn,idempotency_key,fingerprint)
            if replay:
                conn.commit()
                if replay["conflict"]: return Result.fail("IDEMPOTENCY_CONFLICT","Idempotency key was used for another request.")
                return Result.ok("REPLAYED","Previously completed reversal returned.",{"transaction_id":replay["transaction"]["transaction_id"]})
            original=self.transactions.get(conn,transaction_id)
            if not original: conn.rollback(); return Result.fail("TRANSACTION_NOT_FOUND","Original transaction not found.")
            if original["transaction_type"]=="reversal": conn.rollback(); return Result.fail("INVALID_REVERSAL","A reversal transaction cannot itself be reversed.")
            if conn.execute("SELECT 1 FROM transactions WHERE reversal_of_transaction_id=?",(transaction_id,)).fetchone():
                conn.rollback(); return Result.fail("ALREADY_REVERSED","This transaction has already been reversed.")
            entries=conn.execute("SELECT wallet_id,amount_minor FROM ledger_entries WHERE transaction_id=?",(transaction_id,)).fetchall()
            if not entries: conn.rollback(); return Result.fail("LEDGER_MISSING","Original transaction has no wallet ledger entries.")
            wallets=[]
            for entry in entries:
                wid=int(entry["wallet_id"])
                wallets.append(wid)
                if int(entry["amount_minor"])>0:
                    balance=self.wallets.balance(conn,wid)
                    if balance<int(entry["amount_minor"]):
                        conn.rollback(); return Result.fail("REVERSAL_INSUFFICIENT_FUNDS","A recipient wallet no longer has sufficient funds for reversal.",{"wallet_id":wid,"balance_minor":balance,"required_minor":int(entry["amount_minor"])})
            txid=self.transactions.create(conn,idempotency_key,fingerprint,"reversal",int(original["amount_minor"]),f"Reversal of transaction {transaction_id}: {reason}",transaction_id)
            for entry in entries: self.ledger.add(conn,txid,int(entry["wallet_id"]),-int(entry["amount_minor"]))
            original_lines=conn.execute("SELECT account_code,account_id,debit_minor,credit_minor FROM journal_lines WHERE transaction_id=?",(transaction_id,)).fetchall()
            reverse_lines=[]
            for line in original_lines:
                item={"account_code":line["account_code"],"account_id":line["account_id"]}
                if line["debit_minor"]: item["credit"]=int(line["debit_minor"])
                else: item["debit"]=int(line["credit_minor"])
                reverse_lines.append(item)
            if reverse_lines: AccountingService.post(conn,txid,reverse_lines)
            conn.execute("UPDATE transaction_workflows SET state='reversed',updated_at=CURRENT_TIMESTAMP WHERE transaction_id=?",(transaction_id,))
            conn.execute("INSERT INTO transaction_state_events(transaction_id,old_state,new_state,actor_user_id,reason) VALUES(?,'completed','reversed',?,?)",(transaction_id,principal.user_id,reason))
            conn.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,old_value,new_value,reason) VALUES(?,?,?,?,?,?,?)",(principal.user_id,"TRANSACTION_REVERSED","transaction",str(transaction_id),"completed","reversed",reason))
            for wid in set(wallets):
                owner=conn.execute("SELECT user_id FROM wallets WHERE wallet_id=?",(wid,)).fetchone()[0]
                NotificationService.enqueue(conn,owner,"TRANSACTION_REVERSED","Transaction reversed",f"Transaction {transaction_id} was reversed.",txid)
            conn.commit(); log_event("transaction_reversed",transaction_id=txid,operation="reversal",result_code="REVERSAL_COMPLETED")
            return Result.ok("REVERSAL_COMPLETED","Transaction reversed successfully.",{"transaction_id":txid,"reversed_transaction_id":transaction_id})
        except Exception:
            conn.rollback(); return Result.fail("DATABASE_ERROR","Reversal failed; no changes were committed.")
        finally: conn.close()
