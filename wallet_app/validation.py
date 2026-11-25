
from email_validator import validate_email, EmailNotValidError
import phonenumbers
from phonenumbers import PhoneNumberFormat


def normalize_email(email):
    if not isinstance(email, str):
        raise ValueError("Email must be text.")

    try:
        result = validate_email(
            email.strip(),
            check_deliverability=False
        )
        return result.normalized.lower()
    except EmailNotValidError:
        raise ValueError("Enter a valid email address.")


def normalize_phone(phone):
    if not isinstance(phone, str):
        raise ValueError("Phone number must be text.")

    try:
        parsed = phonenumbers.parse(phone.strip(), "EG")

        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("Enter a valid Egyptian phone number.")

        return phonenumbers.format_number(
            parsed,
            PhoneNumberFormat.E164
        )

    except phonenumbers.NumberParseException:
        raise ValueError("Enter a valid Egyptian phone number.")
