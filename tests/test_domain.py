import unittest
from datetime import date, datetime

from subscriptions.domain import (
    ValidationError, advance_date, amount_text, format_date, format_money, parse_amount, parse_date, validate_text,
)


class ValidationTests(unittest.TestCase):
    def test_amount_boundaries_and_separators(self):
        for text, cents in (("0,01", 1), ("99999.99", 9999999), (" 300 ", 30000), ("12,5", 1250)):
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text), cents)

    def test_amount_rejects_invalid_formats_and_ranges(self):
        for text in ("", "0", "-1", "+1", "0.001", "1,234", "100000", "NaN", "inf", "1e2", "1 000", "1.", ".5", "1,2.3", "abc"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                parse_amount(text)

    def test_text_is_trimmed_and_not_silently_truncated(self):
        self.assertEqual(validate_text("  Музыка  ", "Сервис", 100, True), "Музыка")
        self.assertEqual(len(validate_text("я" * 100, "Сервис", 100, True)), 100)
        for value in ("", " \t\n", "я" * 101):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_text(value, "Сервис", 100, True)
        for length, label in ((100, "Тариф"), (50, "Категория"), (500, "Примечание")):
            with self.subTest(label=label):
                self.assertEqual(len(validate_text("я" * length, label, length)), length)
                with self.assertRaisesRegex(ValidationError, label):
                    validate_text("я" * (length + 1), label, length)

    def test_calendar_date_validation(self):
        self.assertEqual(parse_date("29.02.2028"), date(2028, 2, 29))
        self.assertEqual(parse_date("01.01.0001"), date(1, 1, 1))
        for value in ("29.02.2027", "31.04.2027", "2027-01-01", "1.1.2027", "01.01.0000", "", datetime(2027, 1, 1)):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_date(value)

    def test_display_formats(self):
        self.assertEqual(format_money(12340), "123,40 руб.")
        self.assertEqual(amount_text(1), "0,01")
        self.assertEqual(format_date(date(1, 2, 3)), "03.02.0001")

    def test_calendar_overflow_is_explained(self):
        with self.assertRaisesRegex(ValidationError, "9999"):
            advance_date(date(9999, 12, 31), "month", date(9999, 12, 31))
        with self.assertRaisesRegex(ValidationError, "9999"):
            advance_date(date(9999, 2, 28), "year", date(9999, 2, 28))


if __name__ == "__main__":
    unittest.main()
