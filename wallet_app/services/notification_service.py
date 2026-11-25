from wallet_app.result import Result

class NotificationService:
    def __init__(self, db): self.db=db
    @staticmethod
    def enqueue(conn,user_id,kind,title,message,transaction_id=None):
        conn.execute("INSERT INTO notifications(user_id,notification_type,title,message,transaction_id) VALUES(?,?,?,?,?)",
                     (user_id,kind,title,message,transaction_id))
    def list_for_user(self,principal,limit=100):
        if principal is None: return Result.fail("FORBIDDEN","Authentication required.")
        user_id=principal.user_id
        with self.db.connect() as conn:
            rows=conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY notification_id DESC LIMIT ?",(user_id,max(1,min(int(limit),500)))).fetchall()
            return Result.ok("NOTIFICATIONS_FOUND","Notifications retrieved.",[dict(r) for r in rows])
    def mark_read(self,principal,notification_id):
        if principal is None: return Result.fail("FORBIDDEN","Authentication required.")
        with self.db.transaction() as conn:
            cur=conn.execute("UPDATE notifications SET is_read=1 WHERE notification_id=? AND user_id=?",(notification_id,principal.user_id))
            if not cur.rowcount: conn.rollback(); return Result.fail("NOTIFICATION_NOT_FOUND","Notification not found.")
            conn.commit(); return Result.ok("NOTIFICATION_READ","Notification marked as read.")
