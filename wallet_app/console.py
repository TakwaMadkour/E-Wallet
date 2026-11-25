from wallet_app.money import format_money
from wallet_app.services.common import new_idempotency_key
from wallet_app.services.statement_service import StatementService
from wallet_app.services.notification_service import NotificationService
from wallet_app.services.reversal_service import ReversalService
from wallet_app.services.accounting_service import AccountingService
from wallet_app.services.reconciliation_service import ReconciliationService
from wallet_app.services.audit_service import AuditService
from wallet_app.services.policy_service import PolicyService
from wallet_app.security_context import Principal
from wallet_app.services.state_machine_service import TransactionStateMachine
from wallet_app.money import to_minor_units
from getpass import getpass


def show_result(result):
    prefix = "SUCCESS" if result.success else "ERROR"
    print(f"\n[{prefix}] {result.message}")
    if result.data is not None:
        print(result.data)


def read_amount(): return input("Amount (EGP): ").strip()


def customer_menu(user, auth, wallet, transfers, db):
    wallet_id = user["wallet_id"]
    principal = Principal.from_session(user)
    statements = StatementService(db)
    notifications = NotificationService(db)
    state_machine = TransactionStateMachine(db)
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
8. Update profile
9. Notifications
10. Export wallet statement (CSV)
11. Create transfer intent (does not move funds)
0. Logout
""")
        choice = input("Choose: ").strip()
        if choice == "1":
            result = wallet.get_balance(wallet_id, principal)
            if result.success:
                print("Balance:", format_money(result.data["balance_minor"]))
            else:
                show_result(result)
        elif choice == "2":
            result = wallet.deposit(
                wallet_id, read_amount(), new_idempotency_key(), principal)
            show_result(result)
            if result.success and result.data:
                print("New balance:", format_money(
                    result.data["balance_minor"]))
        elif choice == "3":
            result = wallet.withdraw(
                wallet_id, read_amount(), new_idempotency_key(), principal)
            show_result(result)
            if result.success and result.data:
                print("New balance:", format_money(
                    result.data["balance_minor"]))
        elif choice == "4":
            try:
                receiver = int(input("Receiver wallet ID: "))
                result = transfers.transfer(
                    wallet_id, receiver, read_amount(), new_idempotency_key(), principal)
            except ValueError:
                print("Enter a valid wallet ID.")
                continue
            show_result(result)
            if result.success and result.data:
                print("Your new balance:", format_money(
                    result.data["sender_balance_minor"]))
        elif choice == "5":
            result = wallet.history(wallet_id, principal=principal)
            if result.success:
                for row in result.data:
                    print(row["created_at"], row["transaction_type"], format_money(
                        row["amount_minor"]), "TX", row["transaction_id"])
            else:
                show_result(result)
        elif choice == "6":
            print(
                f"Name: {user['name']} | User ID: {user['user_id']} | Wallet ID: {wallet_id}")
        elif choice == "7":
            show_result(auth.change_password(principal, getpass(
                "Current password: "), getpass("New password: ")))
        elif choice == "8":
            current_password = getpass("Current password: ")
            name = input("New name: ").strip()
            email = input("New email: ").strip()
            phone = input("New phone: ").strip()

            result = auth.update_profile(
                principal, current_password, name, email, phone
            )
            show_result(result)

            if result.success:
                user.update(result.data)

        elif choice == "9":
            show_result(notifications.list_for_user(principal))

        elif choice == "10":
            path = input(
                "CSV output path [statement.csv]: ").strip() or "statement.csv"
            show_result(statements.export_csv(wallet_id, principal, path))

        elif choice == "11":
            try:
                receiver = int(input("Receiver wallet ID: "))
                amount = to_minor_units(read_amount())
                show_result(state_machine.create_intent(
                    principal, wallet_id, "transfer",
                    amount, new_idempotency_key(), receiver
                ))
            except ValueError as exc:
                print("Invalid input:", exc)
        elif choice == "0":
            break
        else:
            print("Invalid option.")


def admin_menu(admin, service, db):
    principal = Principal.from_session(admin)
    statements = StatementService(db)
    accounting = AccountingService(db)
    reversals = ReversalService(db)
    reconciliation = ReconciliationService(db)
    audit = AuditService(db)
    policies = PolicyService(db)
    state_machine = TransactionStateMachine(db)
    while True:
        print("""
========== ADMIN MENU ==========
1. List customers
2. Search customers
3. Deactivate customer
4. Activate customer
5. View transactions
6. View ledger
7. View audit logs
8. Run accounting reconciliation
9. View trial balance
10. Export transaction report (CSV)
11. Update transaction policy
12. Reverse a transaction
13. View transaction intents
14. Transition transaction intent
0. Logout
""")
        choice = input("Choose: ").strip()
        if choice == "1":
            show_result(service.list_customers(principal))
        elif choice == "2":
            show_result(service.search_customers(
                input("Search: ").strip(), principal))
        elif choice in ("3", "4"):
            try:
                show_result(service.set_customer_status(
                    int(input("Customer user ID: ")), choice == "4", principal))
            except ValueError:
                print("Enter a valid user ID.")
        elif choice == "5":
            show_result(service.all_transactions(principal=principal))
        elif choice == "6":
            show_result(service.all_ledger_entries(principal=principal))
        elif choice == "7":
            show_result(audit.list_logs(principal))
        elif choice == "8":
            show_result(reconciliation.run(principal))
        elif choice == "9":
            show_result(accounting.trial_balance(principal))
        elif choice == "10":
            path = input("CSV output path [transactions.csv]: ").strip(
            ) or "transactions.csv"
            show_result(statements.export_admin_report(principal, path))
        elif choice == "11":
            key = input(
                "Policy key (max_single_minor/daily_transfer_minor/daily_withdrawal_minor/transfer_fee_bps/transfer_fee_fixed_minor): ").strip()
            try:
                value = int(
                    input("New value (minor units; fee_bps in basis points): "))
                show_result(policies.set_policy(principal, key, value))
            except ValueError:
                print("Enter an integer value.")
        elif choice == "12":
            try:
                txid = int(input("Original transaction ID: "))
            except ValueError:
                print("Enter a valid transaction ID.")
                continue
            show_result(reversals.reverse(txid, new_idempotency_key(), principal, input(
                "Reason: ").strip() or "Administrative reversal"))
        elif choice == "13":
            show_result(state_machine.list_intents(principal))
        elif choice == "14":
            try:
                intent_id = int(input("Intent ID: "))
                state = input(
                    "New state (processing/failed/cancelled/completed): ").strip().lower()
                show_result(state_machine.transition_intent(
                    intent_id, state, principal, input("Reason: ").strip() or None))
            except ValueError:
                print("Enter a valid intent ID.")
        elif choice == "0":
            break
        else:
            print("Invalid option.")
