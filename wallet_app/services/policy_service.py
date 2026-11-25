from wallet_app.result import Result

class PolicyService:
    DEFAULTS={"max_single_minor":100000000,"daily_transfer_minor":200000000,"daily_withdrawal_minor":50000000,"transfer_fee_bps":0,"transfer_fee_fixed_minor":0}
    def __init__(self,db): self.db=db
    @staticmethod
    def get(conn,key):
        row=conn.execute("SELECT policy_value FROM transaction_policies WHERE policy_key=?",(key,)).fetchone()
        return int(row[0]) if row else PolicyService.DEFAULTS[key]
    @staticmethod
    def validate(conn,kind,amount_minor,wallet_id):
        if amount_minor>PolicyService.get(conn,"max_single_minor"):
            return "TRANSACTION_LIMIT_EXCEEDED","Amount exceeds the maximum single-transaction limit."
        if kind in ("transfer","withdrawal"):
            key="daily_transfer_minor" if kind=="transfer" else "daily_withdrawal_minor"
            #spent=conn.execute("SELECT COALESCE(SUM(t.amount_minor),0) FROM transactions t JOIN ledger_entries le ON le.transaction_id=t.transaction_id WHERE le.wallet_id=? AND le.amount_minor<0 AND t.transaction_type=? AND date(t.created_at)=date('now')",(wallet_id,kind)).fetchone()[0]
            spent = conn.execute(
                """
                SELECT COALESCE(SUM(t.amount_minor), 0)
                FROM transactions t
                WHERE t.transaction_type = 'withdrawal'
                AND date(t.created_at) = date('now')
                AND EXISTS (
                    SELECT 1
                    FROM ledger_entries le
                    WHERE le.transaction_id = t.transaction_id
                        AND le.wallet_id = ?
                        AND le.amount_minor < 0
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM transactions r
                    WHERE r.reversal_of_transaction_id = t.transaction_id
                        AND r.transaction_type = 'reversal'
                )
                """,
                (wallet_id,)
            ).fetchone()[0]
            if int(spent)+amount_minor>PolicyService.get(conn,key):
                return "DAILY_LIMIT_EXCEEDED","Daily transaction limit would be exceeded."
        return None
    @staticmethod
    def transfer_fee(conn,amount_minor):
        bps=PolicyService.get(conn,"transfer_fee_bps"); fixed=PolicyService.get(conn,"transfer_fee_fixed_minor")
        return (amount_minor*bps+9999)//10000 + fixed
    def set_policy(self,principal,key,value,reason="Policy update"):
        from wallet_app.security_context import require_admin
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        if key not in self.DEFAULTS or int(value)<0: return Result.fail("INVALID_POLICY","Unknown policy or invalid value.")
        if key=="transfer_fee_bps" and int(value)>10000: return Result.fail("INVALID_POLICY","Transfer fee cannot exceed 100 percent.")
        if int(value)>9_000_000_000_000_000_000: return Result.fail("INVALID_POLICY","Policy value exceeds the supported integer range.")
        with self.db.transaction() as conn:
            old=conn.execute("SELECT policy_value FROM transaction_policies WHERE policy_key=?",(key,)).fetchone()
            conn.execute("INSERT INTO transaction_policies(policy_key,policy_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(policy_key) DO UPDATE SET policy_value=excluded.policy_value,updated_at=CURRENT_TIMESTAMP",(key,int(value)))
            conn.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,old_value,new_value,reason) VALUES(?,?,?,?,?,?,?)",(principal.user_id,"POLICY_UPDATED","transaction_policy",key,str(old[0]) if old else None,str(value),reason))
            conn.commit()
        return Result.ok("POLICY_UPDATED","Transaction policy updated.")
