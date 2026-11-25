from wallet_app.result import Result
from wallet_app.security_context import require_admin

class AuditService:
    def __init__(self,db): self.db=db
    @staticmethod
    def record(conn,actor,action,entity_type,entity_id=None,old_value=None,new_value=None,reason=None,correlation_id=None):
        conn.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,old_value,new_value,reason,correlation_id) VALUES(?,?,?,?,?,?,?,?)",(actor,action,entity_type,str(entity_id) if entity_id is not None else None,old_value,new_value,reason,correlation_id))
    def list_logs(self,principal,limit=200):
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn:
            rows=conn.execute("SELECT * FROM audit_logs ORDER BY audit_id DESC LIMIT ?",(max(1,min(int(limit),1000)),)).fetchall()
            return Result.ok("AUDIT_LOGS_FOUND","Audit logs retrieved.",[dict(r) for r in rows])
