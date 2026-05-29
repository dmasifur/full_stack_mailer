import dns.resolver
from email_validator import EmailNotValidError, validate_email


class EmailValidationResult:
    def __init__(
        self,
        is_valid: bool,
        reason: str | None = None,
    ) -> None:
        self.is_vliad = is_valid
        self.reason = reason


def validate_email_address(email: str) -> EmailValidationResult:

    try:
        validated = validate_email(email)

        normalize_email = validated.email
        domain = normalize_email.split("@"[1])

        dns.resolver.resolve(domain, "MX")

        return EmailValidationResult(is_valid=True)
    except EmailNotValidError as exc:
        return EmailValidationResult(is_valid=False, reason=f"invalid_email:{exc!s}")
    except dns.resolver.NXDOMAIN:
        return EmailValidationResult(
            is_valid=False,
            reason="domain_not_found",
        )
    except dns.resolver.NoAnswer:
        return EmailValidationResult(is_valid=False, reason="missing_mx_record")

    except Exception as exc:
        return EmailValidationResult(
            is_valid=False, reason=f"dns_validation_error: {exc!s}"
        )
