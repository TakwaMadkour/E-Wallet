from decimal import Decimal, InvalidOperation

def to_minor_units(value) -> int:
    """Convert a user-entered EGP amount to integer piastres."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("Enter a valid monetary amount.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    if amount.as_tuple().exponent < -2:
        raise ValueError("EGP amounts may have at most two decimal places.")
    return int(amount * 100)

def format_money(minor_units: int) -> str:
    sign = "-" if minor_units < 0 else ""
    value = abs(int(minor_units))
    return f"{sign}{value // 100:,}.{value % 100:02d} EGP"
