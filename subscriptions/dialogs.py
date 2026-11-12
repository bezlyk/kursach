import tkinter as tk
from tkinter import ttk

from subscriptions.date_picker import DateEntry
from subscriptions.domain import (
    PERIODS, STATUSES, StorageError, ValidationError, amount_text, format_date, format_money,
)
from subscriptions.widgets import fill_payments, make_payment_table


class FormDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent)
        self.result = None
        self.submitted = False
        self.minsize(510, 330)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body = ttk.Frame(self, padding=20)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.columnconfigure(1, weight=1)
        self.error = tk.StringVar()
        self.bind("<Escape>", lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def field(self, row, label, variable, values=None, date_picker=False):
        ttk.Label(self.body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)
        if date_picker:
            widget = DateEntry(self.body, variable, today=self.service.today)
        elif values is None:
            widget = ttk.Entry(self.body, textvariable=variable, width=32)
        else:
            widget = ttk.Combobox(self.body, textvariable=variable, values=values, state="readonly", width=30)
        widget.grid(row=row, column=1, sticky="ew", pady=6)
        return widget

    def finish(self, row, save_label):
        ttk.Label(self.body, textvariable=self.error, foreground="#a02a30", wraplength=480).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        buttons = ttk.Frame(self.body)
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=8)
        self.save_button = ttk.Button(buttons, text=save_label, style="Accent.TButton", command=self.submit)
        self.save_button.pack(side="left")
        self.update_idletasks()
        width, height = max(self.winfo_reqwidth(), 550), max(self.winfo_reqheight(), 340)
        x = max(0, self.master.winfo_rootx() + (self.master.winfo_width() - width) // 2)
        y = max(0, self.master.winfo_rooty() + (self.master.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.grab_set()

    def submit(self):
        if self.submitted:
            return
        self.submitted = True
        self.save_button.state(["disabled"])
        try:
            self.result = self.save()
        except (ValidationError, StorageError) as error:
            self.error.set(str(error))
            self.submitted = False
            self.save_button.state(["!disabled"])
            return
        self.destroy()

    def save(self):
        raise NotImplementedError


class SubscriptionDialog(FormDialog):
    def __init__(self, parent, service, subscription=None):
        super().__init__(parent, "Изменить подписку" if subscription else "Новая подписка")
        self.service = service
        self.subscription = subscription
        values = {
            "service": subscription.service if subscription else "",
            "plan": subscription.plan if subscription else "",
            "category": subscription.category if subscription else "",
            "amount": amount_text(subscription.amount_cents) if subscription else "",
            "period": PERIODS[subscription.period] if subscription else "Месяц",
            "next_date": format_date(subscription.next_date if subscription else service.today()),
            "active": STATUSES[subscription.active] if subscription else "Активна",
        }
        self.variables = {name: tk.StringVar(value=value) for name, value in values.items()}
        first = self.field(0, "Сервис *", self.variables["service"])
        self.field(1, "Тариф", self.variables["plan"])
        self.field(2, "Категория", self.variables["category"])
        self.field(3, "Стоимость, руб. *", self.variables["amount"])
        self.field(4, "Период оплаты *", self.variables["period"], list(PERIODS.values()))
        self.next_date_field = self.field(5, "Следующая дата *\nДД.ММ.ГГГГ", self.variables["next_date"], date_picker=True)
        if subscription:
            self.field(6, "Статус *", self.variables["active"], list(STATUSES.values()))
        else:
            ttk.Label(self.body, text="Новая подписка будет активной.").grid(row=6, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Label(self.body, text="Примечание").grid(row=7, column=0, sticky="nw", pady=6)
        note_frame = ttk.Frame(self.body)
        note_frame.grid(row=7, column=1, sticky="nsew", pady=6)
        note_frame.rowconfigure(0, weight=1)
        note_frame.columnconfigure(0, weight=1)
        self.body.rowconfigure(7, weight=1)
        self.note = tk.Text(note_frame, width=32, height=4, wrap="word", font="TkDefaultFont")
        scroll = ttk.Scrollbar(note_frame, command=self.note.yview)
        self.note.configure(yscrollcommand=scroll.set)
        self.note.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        if subscription:
            self.note.insert("1.0", subscription.note)
        ttk.Label(self.body, text="* Обязательные поля. Смена статуса здесь не отключает услугу\n"
                  "у поставщика. При смене даты или периода график начнётся заново.",
                  style="Muted.TLabel").grid(row=8, column=0, columnspan=2, sticky="w", pady=8)
        self.finish(9, "Сохранить")
        first.focus_set()

    def save(self):
        data = {name: var.get() for name, var in self.variables.items()}
        data["period"] = next((key for key, value in PERIODS.items() if value == data["period"]), "")
        data["note"] = self.note.get("1.0", "end-1c")
        active = data.pop("active")
        if self.subscription:
            if active not in STATUSES.values():
                raise ValidationError("Статус: выберите «Активна» или «Неактивна».")
            return self.service.update_subscription(self.subscription.id, active=active == "Активна", **data)
        return self.service.create_subscription(**data)


class PaymentDialog(FormDialog):
    def __init__(self, parent, service, subscription):
        super().__init__(parent, "Подтвердить выполненный платёж")
        self.service = service
        self.subscription = subscription
        self.amount = tk.StringVar(value=amount_text(subscription.amount_cents))
        self.actual_date = tk.StringVar(value=format_date(service.today()))
        ttk.Label(self.body, text=subscription.service, style="Title.TLabel", wraplength=450).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(self.body, text=f"Плановая дата: {format_date(subscription.next_date)}").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=6)
        self.field(2, "Сумма, руб. *", self.amount)
        self.actual_date_field = self.field(3, "Фактическая дата *\nДД.ММ.ГГГГ", self.actual_date, date_picker=True)
        ttk.Label(self.body, text="Подтвердите уже выполненную оплату. Программа не списывает деньги.\n"
                  "Следующая дата сдвинется на один период от плановой даты.",
                  wraplength=470, style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=12)
        self.finish(5, "Сохранить платёж")

    def save(self):
        return self.service.record_payment(
            self.subscription.id, self.subscription.next_date, self.amount.get(), self.actual_date.get(),
        )


class ActivationDialog(FormDialog):
    def __init__(self, parent, service, subscription):
        super().__init__(parent, "Возобновить подписку")
        self.service = service
        self.subscription = subscription
        self.next_date = tk.StringVar(value=format_date(subscription.next_date))
        ttk.Label(self.body, text=subscription.service, style="Title.TLabel", wraplength=450).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=12)
        self.next_date_field = self.field(1, "Следующая дата *\nДД.ММ.ГГГГ", self.next_date, date_picker=True)
        ttk.Label(self.body, text="Проверьте дату перед возобновлением учёта.\n"
                  "Статус в программе не меняет подписку у поставщика.",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=12)
        self.finish(3, "Возобновить")

    def save(self):
        return self.service.set_active(self.subscription.id, True, self.next_date.get())


class HistoryDialog(tk.Toplevel):
    def __init__(self, parent, subscription, payments, total):
        super().__init__(parent)
        self.title("История подписки")
        self.transient(parent)
        self.geometry("850x460")
        self.minsize(650, 330)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text=f"{subscription.service} · вся история", style="Title.TLabel", wraplength=800).grid(
            row=0, column=0, sticky="w", padx=18, pady=18)
        frame, self.tree = make_payment_table(self)
        frame.grid(row=1, column=0, sticky="nsew", padx=18)
        fill_payments(self.tree, payments)
        text = f"Всего платежей: {len(payments)}. Итого: {format_money(total)}"
        if not payments:
            text = "Платежей пока нет. Подтвердите первую выполненную оплату."
        ttk.Label(self, text=text).grid(row=2, column=0, sticky="w", padx=18, pady=12)
        ttk.Button(self, text="Закрыть", command=self.destroy).grid(row=3, column=0, sticky="e", padx=18, pady=(0, 18))
        self.bind("<Escape>", lambda event: self.destroy())
        self.grab_set()
