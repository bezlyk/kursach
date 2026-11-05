import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from subscriptions.database import Database
from subscriptions.domain import StorageError, ValidationError, amount_text
from subscriptions.service import SubscriptionService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "subscriptions.sqlite3"
        self.database = Database(self.path)
        self.addCleanup(lambda: self.database.close())
        self.today = date(2027, 3, 10)
        self.service = SubscriptionService(self.database, today=lambda: self.today)

    def create(self, name="Музыка", amount="300", period="month", next_date=None, **fields):
        return self.service.create_subscription(name, amount, period, next_date or self.today, **fields)

    def edit(self, item, **changes):
        fields = dict(service=item.service, amount=amount_text(item.amount_cents), period=item.period,
                      next_date=item.next_date, plan=item.plan, category=item.category, note=item.note, active=item.active)
        fields.update(changes)
        return self.service.update_subscription(item.id, **fields)

    def pay(self, item, amount="300", actual_date=None):
        return self.service.record_payment(item.id, item.next_date, amount, actual_date or self.today)

    def test_first_database_is_empty_and_read_operations_do_not_create_payments(self):
        self.assertEqual(self.service.list_subscriptions(), [])
        self.assertEqual(self.service.summary(), (0, 0))
        self.assertEqual(self.service.reminders(), [])
        self.create(next_date=date(2027, 1, 1))
        self.service.list_subscriptions()
        self.service.reminders()
        self.assertEqual(self.service.payment_history(), ([], 0))

    def test_five_active_limit_and_edit_at_capacity(self):
        items = [self.create(str(i)) for i in range(5)]
        with self.assertRaisesRegex(ValidationError, "5"):
            self.create("Шестая")
        updated = self.edit(items[0], service="Исправлено", amount="400,50")
        self.assertEqual(updated.service, "Исправлено")
        self.assertEqual(updated.amount_cents, 40050)
        self.assertEqual(self.service.summary()[0], 5)

    def test_reactivation_limit_and_free_slot(self):
        inactive = self.create("Старая")
        self.service.set_active(inactive.id, False)
        items = [self.create(str(i)) for i in range(5)]
        with self.assertRaises(ValidationError):
            self.service.set_active(inactive.id, True)
        with self.assertRaises(ValidationError):
            self.edit(self.service.get_subscription(inactive.id), active=True)
        self.service.set_active(items[0].id, False)
        result = self.service.set_active(inactive.id, True, date(2027, 4, 30))
        self.assertTrue(result.active)
        self.assertEqual(result.anchor_date, date(2027, 4, 30))
        self.assertEqual(self.service.summary()[0], 5)
        self.service.set_active(result.id, False)
        self.assertTrue(self.create("Новая").active)

    def test_validation_leaves_existing_data_unchanged(self):
        item = self.create()
        invalid = [dict(service=" "), dict(service="я" * 101), dict(plan="я" * 101), dict(category="я" * 51),
                   dict(note="я" * 501), dict(amount="1,234"), dict(next_date="30.02.2027"),
                   dict(period="week"), dict(active="Активна")]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.edit(item, **changes)
            self.assertEqual(self.service.get_subscription(item.id), item)
        self.assertEqual(len(self.service.list_subscriptions()), 1)

    def test_mixed_monthly_estimate_and_actual_are_separate(self):
        monthly = self.create(amount="300")
        yearly = self.create("Годовая", "1200", "year")
        self.assertEqual(self.service.summary(), (2, 40000))
        self.pay(yearly, "1100")
        self.service.set_active(yearly.id, False)
        self.assertEqual(self.service.summary(), (1, 30000))
        self.assertEqual(self.service.payment_history(month="2027-03")[1], 110000)
        self.assertEqual([r.subscription.id for r in self.service.reminders()], [monthly.id])

    def test_estimate_rounds_only_total_using_half_up(self):
        self.create("Год 1", "0.01", "year")
        self.create("Год 2", "0.05", "year")
        self.assertEqual(self.service.summary(), (2, 1))

    def test_monthly_and_yearly_estimates(self):
        item = self.create(amount="1200", period="year")
        self.assertEqual(self.service.summary(), (1, 10000))
        self.edit(item, period="month")
        self.assertEqual(self.service.summary(), (1, 120000))
        self.service.set_active(item.id, False)
        self.assertEqual(self.service.summary(), (0, 0))

    def test_reminder_boundaries_and_inactive_exclusion(self):
        for days in (-1, 0, 7, 8):
            self.create(str(days), next_date=self.today + timedelta(days=days))
        inactive = self.create("Неактивная", next_date=self.today)
        self.service.set_active(inactive.id, False)
        result = self.service.reminders()
        self.assertEqual([r.days for r in result], [-1, 0, 7])
        self.assertIn("Просрочено", result[0].explanation)
        self.assertEqual(result[1].explanation, "Оплата сегодня")

    def test_monthly_schedule_restores_day_after_february_and_late_payment(self):
        item = self.create(next_date=date(2027, 1, 31))
        self.pay(item)
        february = self.service.get_subscription(item.id)
        self.assertEqual(february.next_date, date(2027, 2, 28))
        self.assertLess(february.next_date, self.today)
        self.pay(february)
        march = self.service.get_subscription(item.id)
        self.assertEqual(march.next_date, date(2027, 3, 31))
        history, total = self.service.payment_history(item.id)
        self.assertEqual(total, 60000)
        self.assertEqual({p.planned_date for p in history}, {date(2027, 1, 31), date(2027, 2, 28)})

    def test_yearly_schedule_restores_leap_day(self):
        self.today = date(2029, 3, 10)
        item = self.create(period="year", next_date=date(2024, 2, 29))
        for expected in (date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)):
            self.pay(item)
            item = self.service.get_subscription(item.id)
            self.assertEqual(item.next_date, expected)

    def test_anchor_survives_price_and_status_edits(self):
        item = self.create(next_date=date(2027, 1, 31))
        self.pay(item)
        item = self.service.get_subscription(item.id)
        item = self.edit(item, amount="555")
        self.service.set_active(item.id, False)
        item = self.service.set_active(item.id, True)
        self.pay(item)
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2027, 3, 31))

    def test_date_and_period_changes_reset_anchor_without_rewriting_history(self):
        item = self.create(next_date=date(2027, 1, 31))
        self.pay(item, "250")
        before, total = self.service.payment_history(item.id)
        item = self.edit(self.service.get_subscription(item.id), next_date=date(2027, 2, 15), amount="500")
        self.pay(item)
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2027, 3, 15))
        item = self.edit(self.service.get_subscription(item.id), period="year")
        self.pay(item)
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2028, 3, 15))
        after, _ = self.service.payment_history(item.id)
        self.assertIn(before[0], after)
        self.assertEqual(total, 25000)

    def test_future_payment_and_inactive_payment_are_rejected(self):
        item = self.create()
        with self.assertRaisesRegex(ValidationError, "Фактическая дата"):
            self.pay(item, actual_date=self.today + timedelta(days=1))
        self.service.set_active(item.id, False)
        with self.assertRaisesRegex(ValidationError, "активной"):
            self.pay(item)
        self.assertEqual(self.service.payment_history(), ([], 0))

    def test_stale_confirmation_cannot_pay_next_period(self):
        item = self.create()
        self.pay(item)
        with self.assertRaisesRegex(ValidationError, "изменилась"):
            self.pay(item)
        self.assertEqual(len(self.service.payment_history()[0]), 1)
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2027, 4, 10))

    def test_duplicate_period_is_protected_even_after_resetting_schedule(self):
        item = self.create()
        self.pay(item)
        item = self.edit(self.service.get_subscription(item.id), next_date=item.next_date)
        with self.assertRaisesRegex(ValidationError, "уже сохранён"):
            self.pay(item)
        self.assertEqual(len(self.service.payment_history()[0]), 1)
        self.assertEqual(self.service.get_subscription(item.id).next_date, item.next_date)

    def test_payment_insert_failure_rolls_back_both_changes(self):
        item = self.create()
        self.database.connection.execute("""CREATE TRIGGER reject_payment BEFORE INSERT ON payments
            BEGIN SELECT RAISE(ABORT, 'test write failure'); END""")
        with self.assertRaises(StorageError):
            self.pay(item)
        self.assertEqual(self.service.get_subscription(item.id), item)
        self.assertEqual(self.service.payment_history(), ([], 0))

    def test_next_date_update_failure_rolls_back_inserted_payment(self):
        item = self.create()
        self.database.connection.execute("""CREATE TRIGGER reject_date BEFORE UPDATE OF next_date ON subscriptions
            BEGIN SELECT RAISE(ABORT, 'test date failure'); END""")
        with self.assertRaises(StorageError):
            self.pay(item)
        self.assertEqual(self.service.get_subscription(item.id), item)
        self.assertEqual(self.service.payment_history(), ([], 0))

    def test_delete_with_history_is_blocked_by_service_and_foreign_key(self):
        item = self.create()
        self.pay(item)
        with self.assertRaisesRegex(ValidationError, "неактивной"):
            self.service.delete_subscription(item.id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.connection.execute("DELETE FROM subscriptions WHERE id = ?", (item.id,))
        self.assertEqual(len(self.service.payment_history()[0]), 1)
        removable = self.create("Ошибочная")
        self.service.delete_subscription(removable.id)
        self.assertEqual(len(self.service.list_subscriptions()), 1)

    def test_database_constraints_reject_invalid_values_and_limit(self):
        item = self.create()
        for field, value in (("amount_cents", 0), ("amount_cents", 10000000), ("amount_cents", 1.5),
                             ("service", ""), ("period", "week"), ("next_date", "2027-02-30"), ("active", 2)):
            with self.subTest(field=field, value=value), self.assertRaises(sqlite3.IntegrityError):
                self.database.connection.execute(f"UPDATE subscriptions SET {field} = ? WHERE id = ?", (value, item.id))
        for i in range(4):
            self.create(str(i))
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.connection.execute("""INSERT INTO subscriptions
                (service, amount_cents, period, next_date, active, anchor_date)
                VALUES ('Шестая', 100, 'month', '2027-03-10', 1, '2027-03-10')""")

    def test_persistence_after_reopening(self):
        item = self.create(note="Мои данные")
        self.pay(item, "325,50")
        expected = self.service.get_subscription(item.id)
        expected_payments = self.service.payment_history()
        self.database.close()
        self.database = Database(self.path)
        self.service = SubscriptionService(self.database, today=lambda: self.today)
        self.assertEqual(self.service.get_subscription(item.id), expected)
        self.assertEqual(self.service.payment_history(), expected_payments)

    def test_cyrillic_casefold_combined_filters_and_sort(self):
        first = self.create("Яндекс Музыка", category="Музыка", next_date=date(2027, 3, 15))
        self.create("ЯНДЕКС Плюс", category="Видео", next_date=date(2027, 3, 12))
        inactive = self.create("яндекс архив", category="Музыка")
        self.service.set_active(inactive.id, False)
        self.assertEqual([x.id for x in self.service.list_subscriptions("яНдЕкС", True, "Музыка")], [first.id])
        self.assertEqual([x.id for x in self.service.list_subscriptions("архив", False)], [inactive.id])
        self.assertEqual([x.service for x in self.service.list_subscriptions()], ["ЯНДЕКС Плюс", "Яндекс Музыка", "яндекс архив"])
        self.assertEqual(len(self.service.list_subscriptions()), 3)
        self.assertEqual(self.service.list_subscriptions("Не существует"), [])
        self.assertEqual(self.service.summary(), (2, 60000))

    def test_actual_month_includes_inactive_and_uses_actual_date(self):
        item = self.create(next_date=date(2027, 1, 31))
        self.pay(item, "100", date(2027, 2, 28))
        self.pay(self.service.get_subscription(item.id), "200", date(2027, 3, 1))
        self.service.set_active(item.id, False)
        self.assertEqual(self.service.payment_history(month="2027-01"), ([], 0))
        self.assertEqual(self.service.payment_history(month="2027-02")[1], 10000)
        self.assertEqual(self.service.payment_history(month="2027-03")[1], 20000)
        for month in ("2027-00", "2027-13", "0000-01", "27-01", "2027-1"):
            with self.subTest(month=month), self.assertRaises(ValidationError):
                self.service.payment_history(month=month)


if __name__ == "__main__":
    unittest.main()
