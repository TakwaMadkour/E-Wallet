from wallet_app.result import Result
from wallet_app.security_context import require_admin, authorize_wallet

TRANSITIONS={"pending":{"processing","failed","cancelled"},"processing":{"completed","failed"},"completed":set(),"failed":set(),"cancelled":set()}

class TransactionStateMachine:
    """Tracks pre-posting lifecycle for operations that require asynchronous processing.

    Synchronous local wallet transactions are atomically posted as completed. Intents
    represent requests awaiting a worker/provider and do not affect wallet balances.
    """
    def __init__(self,db): self.db=db

    def create_intent(self,principal,wallet_id,operation,amount_minor,idempotency_key,counterparty_wallet_id=None):
        if principal is None or principal.role!="customer": return Result.fail("FORBIDDEN","Customer authentication required.")
        if operation not in {"deposit","withdrawal","transfer"} or int(amount_minor)<=0 or not idempotency_key:
            return Result.fail("INVALID_INTENT","Valid operation, positive amount and idempotency key are required.")
        with self.db.transaction() as conn:
            if not authorize_wallet(conn,wallet_id,principal): conn.rollback(); return Result.fail("FORBIDDEN","Wallet ownership verification failed.")
            wallet=conn.execute("SELECT u.status FROM wallets w JOIN users u ON u.user_id=w.user_id WHERE w.wallet_id=?",(wallet_id,)).fetchone()
            if not wallet or wallet["status"]!="active": conn.rollback(); return Result.fail("ACCOUNT_INACTIVE","Wallet owner must be active.")
            if operation=="transfer":
                if counterparty_wallet_id is None or int(counterparty_wallet_id)==int(wallet_id): conn.rollback(); return Result.fail("INVALID_COUNTERPARTY","A different counterparty wallet is required.")
                other=conn.execute("SELECT 1 FROM wallets w JOIN users u ON u.user_id=w.user_id WHERE w.wallet_id=? AND u.status='active'",(counterparty_wallet_id,)).fetchone()
                if not other: conn.rollback(); return Result.fail("INVALID_COUNTERPARTY","Counterparty wallet is unavailable.")
            try:
                cur=conn.execute("INSERT INTO transaction_intents(idempotency_key,user_id,wallet_id,counterparty_wallet_id,operation,amount_minor,state) VALUES(?,?,?,?,?,?,'pending')",(idempotency_key,principal.user_id,wallet_id,counterparty_wallet_id,operation,int(amount_minor)))
            except Exception:
                conn.rollback(); return Result.fail("IDEMPOTENCY_CONFLICT","Intent key is already in use.")
            conn.execute("INSERT INTO transaction_intent_events(intent_id,old_state,new_state,actor_user_id,reason) VALUES(?,NULL,'pending',?,'Intent created')",(cur.lastrowid,principal.user_id))
            conn.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,new_value,reason) VALUES(?,?,?,?,?,?)",(principal.user_id,"TRANSACTION_INTENT_CREATED","transaction_intent",str(cur.lastrowid),"pending",operation))
            conn.commit()
            return Result.ok("INTENT_CREATED","Transaction intent created; no funds have moved.",{"intent_id":cur.lastrowid,"state":"pending"})

    def transition_intent(self,intent_id,new_state,principal,reason=None):
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT state FROM transaction_intents WHERE intent_id=?",(intent_id,)).fetchone()
            if not row: conn.rollback(); return Result.fail("INTENT_NOT_FOUND","Transaction intent not found.")
            old=row["state"]
            if new_state not in TRANSITIONS.get(old,set()): conn.rollback(); return Result.fail("INVALID_STATE_TRANSITION",f"Cannot transition from {old} to {new_state}.")
            conn.execute("UPDATE transaction_intents SET state=?,updated_at=CURRENT_TIMESTAMP WHERE intent_id=?",(new_state,intent_id))
            conn.execute("INSERT INTO transaction_intent_events(intent_id,old_state,new_state,actor_user_id,reason) VALUES(?,?,?,?,?)",(intent_id,old,new_state,principal.user_id,reason))
            conn.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,old_value,new_value,reason) VALUES(?,?,?,?,?,?,?)",(principal.user_id,"INTENT_STATE_CHANGED","transaction_intent",str(intent_id),old,new_state,reason))
            owner=conn.execute("SELECT user_id FROM transaction_intents WHERE intent_id=?",(intent_id,)).fetchone()[0]
            conn.execute("INSERT INTO notifications(user_id,notification_type,title,message) VALUES(?,?,?,?)",(owner,"INTENT_STATE_CHANGED","Transaction request updated",f"Your request changed from {old} to {new_state}."))
            conn.commit()
            return Result.ok("STATE_UPDATED","Transaction intent state updated.",{"old_state":old,"new_state":new_state})

    def list_intents(self,principal,limit=200):
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn:
            rows=conn.execute("SELECT * FROM transaction_intents ORDER BY intent_id DESC LIMIT ?",(max(1,min(int(limit),1000)),)).fetchall()
            return Result.ok("INTENTS_FOUND","Transaction intents retrieved.",[dict(r) for r in rows])

    def transition(self,transaction_id,new_state,principal=None,reason=None):
        # Posted transaction states are immutable except through ReversalService.
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        if new_state=="reversed": return Result.fail("USE_REVERSAL_SERVICE","Use ReversalService to reverse a posted transaction.")
        return Result.fail("INVALID_STATE_TRANSITION","Posted local transactions are atomically completed; use transaction intents for asynchronous states.")

    def get_state(self,transaction_id,principal=None):
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn:
            row=conn.execute("SELECT * FROM transaction_workflows WHERE transaction_id=?",(transaction_id,)).fetchone()
            return Result.ok("STATE_FOUND","State retrieved.",dict(row)) if row else Result.fail("TRANSACTION_NOT_FOUND","Transaction not found.")
