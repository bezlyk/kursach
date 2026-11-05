import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP


MAX_ACTIVE = 5
PERIODS = {"month": "Месяц", "year": "Год"}
STATUSES = {True: "Активна", False: "Неактивна"}


class ValidationError(Exception):
    pass


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class Subscription:
    id: int
    service: str
    plan: str
    category: str
    note: str
    amount_cents: int
    period: str
    next_date: date
    active: bool
    anchor_date: date


@dataclass(frozen=True)
class SubscriptionData:
    service: str
    plan: str
    category: str
    note: str
    amount_cents: int
    period: str
    next_date: date
    active: bool
    anchor_date: date


@dataclass(frozen=True)
class Payment:
    id: int
    subscription_id: int
    service: str
    planned_date: date
    actual_date: date
    amount_cents: int


@dataclass(frozen=True)
class Reminder:
    subscription: Subscription
    days: int
    explanation: str


def validate_text(value, label, maximum, required=False):
    if not isinstance(value, str):
        raise ValidationError(f"{label}: введите текст.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{label}: поле обязательно для заполнения.")
    if len(value) > maximum:
        raise ValidationError(f"{label}: допускается не более {maximum} символов.")
    return value


def parse_amount(value, label="Стоимость"):
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", text):
        raise ValidationError(
            f"{label}: введите число с точкой или запятой, не более двух знаков после неё."
        )
    if len(text) > 16:
        raise ValidationError(f"{label}: допустимо от 0,01 до 99 999,99 руб.")
    amount = Decimal(text.replace(",", "."))
    if not Decimal("0.01") <= amount <= Decimal("99999.99"):
        raise ValidationError(f"{label}: допустимо от 0,01 до 99 999,99 руб.")
    return int(amount * 100)


def parse_date(value, label="Следующая дата оплаты"):
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", value.strip()):
        raise ValidationError(f"{label}: используйте формат ДД.ММ.ГГГГ.")
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        raise ValidationError(f"{label}: такой календарной даты не существует.") from None


def format_date(value):
    return f"{value.day:02d}.{value.month:02d}.{value.year:04d}"


def amount_text(cents):
    return f"{Decimal(cents) / 100:.2f}".replace(".", ",")


def format_money(cents):
    return f"{amount_text(cents)} руб."


def advance_date(planned, period, anchor):
    if period == "month":
        year = planned.year + (planned.month == 12)
        month = planned.month % 12 + 1
    elif period == "year":
        year = planned.year + 1
        month = anchor.month
    else:
        raise ValidationError("Период оплаты: выберите месяц или год.")
    if year > 9999:
        raise ValidationError("Следующая дата оплаты выходит за пределы 9999 года. Измените график.")
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def monthly_estimate(subscriptions):
    active = [item for item in subscriptions if item.active]
    monthly = sum(item.amount_cents for item in active if item.period == "month")
    yearly = sum(item.amount_cents for item in active if item.period == "year")
    total = Decimal(monthly) + Decimal(yearly) / 12
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def reminders(subscriptions, today):
    result = []
    for item in subscriptions:
        days = (item.next_date - today).days
        if not item.active or days > 7:
            continue
        if days < 0:
            explanation = f"Просрочено на {abs(days)} дн."
        elif days == 0:
            explanation = "Оплата сегодня"
        else:
            explanation = f"Оплата через {days} дн."
        result.append(Reminder(item, days, explanation))
    return sorted(result, key=lambda item: (item.days, item.subscription.id))
