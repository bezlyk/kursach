import re
import sqlite3
from datetime import date
from functools import wraps

from subscriptions.domain import (
    MAX_ACTIVE, PERIODS, StorageError, SubscriptionData, ValidationError,
    advance_date, monthly_estimate, parse_amount, parse_date, reminders, validate_text,
)


def storage_operation(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except sqlite3.IntegrityError as error:
            if "active_limit" in str(error):
                raise ValidationError("Лимит: допускается не более пяти активных подписок.") from error
            if "payments.subscription_id, payments.planned_date" in str(error):
                raise ValidationError("Платёж за эту плановую дату уже сохранён. Обновите карточку.") from error
            raise StorageError("База отклонила изменение. Проверьте данные; операция не сохранена.") from error
        except sqlite3.Error as error:
            raise StorageError(
                "Не удалось выполнить операцию с базой. Проверьте доступ к папке и свободное место. "
                "Операция не подтверждена; обновите данные перед повтором."
            ) from error
    return wrapped


class SubscriptionService:
    def __init__(self, database, today=date.today):
        self.database = database
        self.today = today

    @storage_operation
    def get_subscription(self, subscription_id):
        return self.database.get_subscription(subscription_id)

    @storage_operation
    def list_subscriptions(self, search="", active=None, category=None):
        search = search.strip().casefold()
        return [item for item in self.database.list_subscriptions()
                if search in item.service.casefold()
                and (active is None or item.active == active)
                and (category is None or item.category == category)]

    @storage_operation
    def categories(self):
        return sorted({item.category for item in self.database.list_subscriptions()}, key=str.casefold)

    @storage_operation
    def summary(self):
        items = self.database.list_subscriptions()
        return sum(item.active for item in items), monthly_estimate(items)

    @storage_operation
    def reminders(self):
        return reminders(self.database.list_subscriptions(), self.today())

    def _data(self, service, amount, period, next_date, plan="", category="", note="", active=True):
        service = validate_text(service, "Сервис", 100, required=True)
        plan = validate_text(plan, "Тариф", 100)
        category = validate_text(category, "Категория", 50)
        note = validate_text(note, "Примечание", 500)
        amount_cents = parse_amount(amount)
        if period not in PERIODS:
            raise ValidationError("Период оплаты: выберите месяц или год.")
        next_date = parse_date(next_date)
        if type(active) is not bool:
            raise ValidationError("Статус: выберите «Активна» или «Неактивна».")
        return SubscriptionData(service, plan, category, note, amount_cents, period, next_date, active, next_date)

    def _check_limit(self, old=None, active=True):
        if active and (old is None or not old.active) and self.database.active_count() >= MAX_ACTIVE:
            raise ValidationError("Лимит: уже 5 активных подписок. Сначала сделайте одну из них неактивной.")

    @storage_operation
    def create_subscription(self, service, amount, period, next_date, plan="", category="", note=""):
        data = self._data(service, amount, period, next_date, plan, category, note)
        with self.database.transaction():
            self._check_limit()
            subscription_id = self.database.insert_subscription(data)
        return self.database.get_subscription(subscription_id)

    @storage_operation
    def update_subscription(self, subscription_id, service, amount, period, next_date,
                            plan="", category="", note="", active=True):
        data = self._data(service, amount, period, next_date, plan, category, note, active)
        with self.database.transaction():
            old = self.database.get_subscription(subscription_id)
            self._check_limit(old, active)
            if old.period == data.period and old.next_date == data.next_date:
                data = SubscriptionData(
                    data.service, data.plan, data.category, data.note, data.amount_cents,
                    data.period, data.next_date, data.active, old.anchor_date,
                )
            self.database.update_subscription(subscription_id, data)
        return self.database.get_subscription(subscription_id)

    @storage_operation
    def set_active(self, subscription_id, active, next_date=None):
        if type(active) is not bool:
            raise ValidationError("Статус: выберите «Активна» или «Неактивна».")
        new_date = parse_date(next_date) if next_date is not None else None
        with self.database.transaction():
            old = self.database.get_subscription(subscription_id)
            self._check_limit(old, active)
            next_value = new_date or old.next_date
            anchor = next_value if next_value != old.next_date else old.anchor_date
            data = SubscriptionData(
                old.service, old.plan, old.category, old.note, old.amount_cents,
                old.period, next_value, active, anchor,
            )
            self.database.update_subscription(subscription_id, data)
        return self.database.get_subscription(subscription_id)

    @storage_operation
    def record_payment(self, subscription_id, expected_date, amount, actual_date):
        expected_date = parse_date(expected_date, "Плановая дата")
        actual_date = parse_date(actual_date, "Фактическая дата")
        amount_cents = parse_amount(amount, "Сумма платежа")
        if actual_date > self.today():
            raise ValidationError("Фактическая дата: платёж не может быть позже сегодняшнего дня.")
        with self.database.transaction():
            old = self.database.get_subscription(subscription_id)
            if not old.active:
                raise ValidationError("Платёж: можно подтвердить оплату только активной подписки.")
            if old.next_date != expected_date:
                raise ValidationError("Плановая дата уже изменилась. Закройте форму и проверьте новый период.")
            next_date = advance_date(old.next_date, old.period, old.anchor_date)
            payment_id = self.database.insert_payment(subscription_id, expected_date, actual_date, amount_cents)
            self.database.update_next_date(subscription_id, next_date)
        return payment_id

    @storage_operation
    def delete_subscription(self, subscription_id):
        with self.database.transaction():
            self.database.get_subscription(subscription_id)
            if self.database.has_payments(subscription_id):
                raise ValidationError(
                    "Удаление запрещено: у подписки есть история платежей. Сделайте её неактивной, чтобы сохранить историю."
                )
            self.database.delete_subscription(subscription_id)

    @storage_operation
    def has_payments(self, subscription_id):
        return self.database.has_payments(subscription_id)

    @storage_operation
    def payment_history(self, subscription_id=None, month=None):
        if month is not None:
            if not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) or month.startswith("0000"):
                raise ValidationError("Месяц истории: выберите месяц от 1 до 12 и год от 1 до 9999.")
        payments = self.database.list_payments(subscription_id, month)
        return payments, sum(item.amount_cents for item in payments)
