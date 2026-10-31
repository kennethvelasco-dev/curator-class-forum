"""Password validators for account registration."""

from django.core.exceptions import ValidationError


class UppercaseCharacterValidator:
    def validate(self, password, user=None):
        if not any(character.isupper() for character in password):
            raise ValidationError(
                "Password must contain at least one uppercase letter.",
                code="password_no_uppercase",
            )

    def get_help_text(self):
        return "Your password must contain at least one uppercase letter."


class LowercaseCharacterValidator:
    def validate(self, password, user=None):
        if not any(character.islower() for character in password):
            raise ValidationError(
                "Password must contain at least one lowercase letter.",
                code="password_no_lowercase",
            )

    def get_help_text(self):
        return "Your password must contain at least one lowercase letter."


class DigitCharacterValidator:
    def validate(self, password, user=None):
        if not any(character.isdigit() for character in password):
            raise ValidationError(
                "Password must contain at least one digit.",
                code="password_no_digit",
            )

    def get_help_text(self):
        return "Your password must contain at least one digit."
