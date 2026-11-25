import getpass
from wallet_app.database import Database
from wallet_app.services.auth_service import AuthService
from wallet_app.services.wallet_service import WalletService
from wallet_app.services.transfer_service import TransferService
from wallet_app.services.admin_service import AdminService
from wallet_app.console import customer_menu, admin_menu, show_result

def bootstrap_admin(db, auth):
    with db.connect() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if row:
        return
    print("No administrator exists. Create the initial administrator.")
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip()
    phone = input("Admin phone: ").strip()
    password = getpass.getpass("Admin password (8+ characters): ")
    # Admin creation is a controlled first-run setup, not public registration.
    from wallet_app.security import hash_password
    try:
        conn = db.transaction()
        conn.execute(
            "INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?, 'admin')",
            (name, email.lower(), phone, hash_password(password))
        )
        conn.commit()
        conn.close()
        print("Administrator created.")
    except Exception as exc:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        print("Could not create administrator:", exc)

def main():
    db = Database()
    auth = AuthService(db)
    wallet = WalletService(db)
    transfers = TransferService(db)
    admin = AdminService(db)
    bootstrap_admin(db, auth)

    while True:
        print("""
======= ELECTRONIC WALLET =======
1. Register
2. Login
0. Exit
""")
        choice = input("Choose: ").strip()
        if choice == "1":
            result = auth.register(
                input("Name: "), input("Email: "), input("Phone: "),
                getpass.getpass("Password: ")
            )
            show_result(result)
        elif choice == "2":
            identifier = input("Email or phone: ").strip()
            password = getpass.getpass("Password: ")
            result = auth.login(identifier, password)
            show_result(result)
            if result.success:
                if result.data["role"] == "admin":
                    admin_menu(result.data, admin, db)
                else:
                    customer_menu(result.data, auth, wallet, transfers, db)
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()
