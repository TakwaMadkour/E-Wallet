from wallet_app.money import format_money
from wallet_app.services.common import new_idempotency_key

def show_result(result):
    prefix = "SUCCESS" if result.success else "ERROR"
    print(f"\n[{prefix}] {result.message}")
    if result.data is not None:
        print(result.data)

def read_amount():
    return input("Amount (EGP): ").strip()

def customer_menu(user, auth, wallet, transfers):
    wallet_id = user["wallet_id"]
    while True:
        print(f"""
========== CUSTOMER MENU ==========
Welcome, {user['name']}
1. View balance
2. Deposit
3. Withdraw
4. Transfer
5. Transaction history
6. View profile (basic)
7. Change password
0. Logout
""")
        choice = input("Choose: ").strip()
        if choice == "1":
            result = wallet.get_balance(wallet_id)
            if result.success:
                print("Balance:", format_money(result.data["balance_minor"]))
            else:
                show_result(result)
        elif choice == "2":
            amount = read_amount()
            result = wallet.deposit(wallet_id, amount, new_idempotency_key())
            show_result(result)
            if result.success and result.data:
                print("New balance:", format_money(result.data["balance_minor"]))
        elif choice == "3":
            amount = read_amount()
            result = wallet.withdraw(wallet_id, amount, new_idempotency_key())
            show_result(result)
            if result.success and result.data:
                print("New balance:", format_money(result.data["balance_minor"]))
        elif choice == "4":
            receiver = input("Receiver wallet ID: ").strip()
            amount = read_amount()
            try:
                result = transfers.transfer(wallet_id, int(receiver), amount,
                                            new_idempotency_key())
            except ValueError:
                print("Enter a valid wallet ID.")
                continue
            show_result(result)
            if result.success and result.data:
                print("Your new balance:",
                      format_money(result.data["sender_balance_minor"]))
        elif choice == "5":
            result = wallet.history(wallet_id)
            if result.success:
                for row in result.data:
                    print(row["created_at"], row["transaction_type"],
                          format_money(row["amount_minor"]), "TX", row["transaction_id"])
            else:
                show_result(result)
        elif choice == "6":
            print(f"Name: {user['name']} | User ID: {user['user_id']} | Wallet ID: {wallet_id}")
        elif choice == "7":
            current = input("Current password: ")
            new = input("New password: ")
            show_result(auth.change_password(user["user_id"], current, new))
        elif choice == "0":
            break
        else:
            print("Invalid option.")

def admin_menu(admin, service):
    while True:
        print("""
========== ADMIN MENU ==========
1. List customers
2. Search customers
3. Deactivate customer
4. Activate customer
5. View transactions
6. View ledger
0. Logout
""")
        choice = input("Choose: ").strip()
        if choice == "1":
            show_result(service.list_customers())
        elif choice == "2":
            show_result(service.search_customers(input("Search: ").strip()))
        elif choice in ("3", "4"):
            try:
                uid = int(input("Customer user ID: "))
                show_result(service.set_customer_status(uid, choice == "4"))
            except ValueError:
                print("Enter a valid user ID.")
        elif choice == "5":
            show_result(service.all_transactions())
        elif choice == "6":
            show_result(service.all_ledger_entries())
        elif choice == "0":
            break
        else:
            print("Invalid option.")
