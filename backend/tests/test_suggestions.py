import os
import unittest
from unittest.mock import patch

from backend.suggestions import send_email


class SuggestionEmailTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "title": "Sample Movie",
            "year": 2024,
            "tmdb_id": 123,
            "languages": ["English"],
            "genres": ["Drama"],
            "director": "A. Director",
            "cast": ["An Actor"],
            "autofilled": False,
            "contact_email": "",
            "overview": "A sample story.",
            "note": "",
        }
        self.smtp_config = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.test",
            "SMTP_PASSWORD": "test-password",
        }

    def send_and_get_message(self, recipient_override, default_recipient="fallback@example.test"):
        environment = dict(
            self.smtp_config,
            SUGGESTION_TO=recipient_override,
            SUGGESTION_DEFAULT_TO=default_recipient,
        )
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("backend.suggestions.smtplib.SMTP") as smtp,
        ):
            sent = send_email(self.record)

        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertTrue(sent)
        return message

    def test_email_uses_fallback_recipient_when_override_is_empty(self):
        message = self.send_and_get_message("")
        self.assertEqual(message["To"], "fallback@example.test")

    def test_email_uses_configured_recipient_override(self):
        message = self.send_and_get_message("curator@example.test")
        self.assertEqual(message["To"], "curator@example.test")

    def test_email_is_not_sent_without_a_configured_recipient(self):
        environment = dict(self.smtp_config, SUGGESTION_TO="", SUGGESTION_DEFAULT_TO="")
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("backend.suggestions.smtplib.SMTP") as smtp,
        ):
            sent = send_email(self.record)

        self.assertFalse(sent)
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
