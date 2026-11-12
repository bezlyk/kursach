import tkinter as tk
from tkinter import font, messagebox, ttk

from subscriptions.dialogs import ActivationDialog, HistoryDialog, PaymentDialog, SubscriptionDialog
from subscriptions.domain import PERIODS, STATUSES, StorageError, ValidationError, format_date, format_money
from subscriptions.widgets import fill_payments, make_payment_table, make_table, readonly_text, set_text


MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


class Application:
    def __init__(self, root, service):
        self.root = root
        self.service = service
        self.items = {}
        self.category_values = [None]
        self.root.title("Мои подписки — учёт расходов")
        self.root.geometry("1180x800")
        self.root.minsize(900, 650)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._style()
        self.status = tk.StringVar(value="Готово")
        self._header()
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 12))
        self.subscriptions_tab = ttk.Frame(self.notebook, padding=14)
        self.reminders_tab = ttk.Frame(self.notebook, padding=14)
        self.payments_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.subscriptions_tab, text="Мои подписки")
        self.notebook.add(self.reminders_tab, text="К оплате")
        self.notebook.add(self.payments_tab, text="Фактические расходы")
        self._subscriptions_page()
        self._reminders_page()
        self._payments_page()
        ttk.Label(root, textvariable=self.status, style="Muted.TLabel", padding=(20, 0, 20, 10)).grid(row=2, column=0, sticky="ew")
        self.search.trace_add("write", lambda *args: self.safe(self.refresh_list))
        self.refresh_all()

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        available = {name.casefold(): name for name in font.families(self.root)}
        preferred = ("Segoe UI", "DejaVu Sans", "Noto Sans", "Liberation Sans", "Arial")
        family = next((available[name.casefold()] for name in preferred if name.casefold() in available),
                      font.nametofont("TkDefaultFont").actual("family"))
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            font.nametofont(name).configure(family=family, size=10)
        self.root.configure(background="#f3f5f9")
        style.configure(".", font=(family, 10), background="#f3f5f9", foreground="#243348")
        style.configure("TFrame", background="#f3f5f9")
        style.configure("TLabel", background="#f3f5f9")
        style.configure("Title.TLabel", font=(family, 17, "bold"))
        style.configure("Metric.TLabel", font=(family, 19, "bold"), foreground="#2656af")
        style.configure("Muted.TLabel", foreground="#536477")
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background="#2656af", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1f458f"), ("disabled", "#ccd3df")])
        style.configure("Treeview", rowheight=32, fieldbackground="white", background="white")
        style.configure("Treeview.Heading", padding=8, font=(family, 10, "bold"))
        style.map("Treeview", background=[("selected", "#dbe8ff")], foreground=[("selected", "#153969")])
        style.configure("TNotebook.Tab", padding=(18, 10))

    def _header(self):
        header = ttk.Frame(self.root, padding=20)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Мои подписки", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Личный учёт · до пяти активных сервисов · данные на вашем компьютере", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(3, 16))
        self.count = tk.StringVar()
        self.estimate = tk.StringVar()
        ttk.Label(header, textvariable=self.count, style="Metric.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(header, textvariable=self.estimate, style="Metric.TLabel").grid(row=2, column=1, columnspan=2, sticky="e")
        ttk.Label(header, text="Активные подписки", style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Label(header, text="Оценка расходов в месяц", style="Muted.TLabel").grid(row=3, column=1, columnspan=2, sticky="e")

    def _subscriptions_page(self):
        page = self.subscriptions_tab
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        filters = ttk.Frame(page)
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        filters.columnconfigure(0, weight=2)
        filters.columnconfigure(1, weight=1)
        filters.columnconfigure(2, weight=1)
        self.search = tk.StringVar()
        self.status_filter = tk.StringVar(value="Все статусы")
        self.category_filter = tk.StringVar(value="Все категории")
        for column, text in enumerate(("Поиск по названию", "Статус", "Категория")):
            ttk.Label(filters, text=text).grid(row=0, column=column, sticky="w", pady=(0, 4))
        ttk.Entry(filters, textvariable=self.search).grid(row=1, column=0, sticky="ew", padx=(0, 10))
        status_box = ttk.Combobox(filters, textvariable=self.status_filter, state="readonly",
                                 values=("Все статусы", "Активна", "Неактивна"), width=17)
        status_box.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        status_box.bind("<<ComboboxSelected>>", lambda event: self.safe(self.refresh_list))
        self.category_box = ttk.Combobox(filters, textvariable=self.category_filter, state="readonly", width=20)
        self.category_box.grid(row=1, column=2, sticky="ew", padx=(0, 10))
        self.category_box.bind("<<ComboboxSelected>>", lambda event: self.safe(self.refresh_list))
        ttk.Button(filters, text="Сбросить", command=lambda: self.safe(self.reset_filters)).grid(row=1, column=3)
        self.list_message = tk.StringVar()
        ttk.Label(page, textvariable=self.list_message, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 10))
        panes = ttk.Panedwindow(page, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")
        table, self.tree = make_table(panes, [
            ("service", "Сервис", 190), ("amount", "Стоимость", 125), ("period", "Период", 85),
            ("next", "Следующая дата", 140), ("status", "Статус", 110),
        ])
        panes.add(table, weight=3)
        card = ttk.Labelframe(panes, text="Карточка подписки", padding=6)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)
        frame, self.details = readonly_text(card)
        frame.grid(row=0, column=0, sticky="nsew")
        panes.add(card, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.update_details())
        self.tree.bind("<Double-1>", lambda event: self.safe(self.edit_subscription))
        buttons = ttk.Frame(page)
        buttons.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(buttons, text="+ Добавить", style="Accent.TButton", command=lambda: self.safe(self.add_subscription)).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.edit_button = ttk.Button(buttons, text="Изменить", command=lambda: self.safe(self.edit_subscription))
        self.edit_button.grid(row=0, column=1, padx=(0, 8), pady=4)
        self.pay_button = ttk.Button(buttons, text="Отметить оплату", command=lambda: self.safe(self.record_payment))
        self.pay_button.grid(row=0, column=2, padx=(0, 8), pady=4)
        self.history_button = ttk.Button(buttons, text="История", command=lambda: self.safe(self.show_history))
        self.history_button.grid(row=0, column=3, padx=(0, 8), pady=4)
        self.active_button = ttk.Button(buttons, text="Сменить статус", command=lambda: self.safe(self.toggle_active))
        self.active_button.grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        self.delete_button = ttk.Button(buttons, text="Удалить", command=lambda: self.safe(self.delete_subscription))
        self.delete_button.grid(row=1, column=2, sticky="w", pady=4)

    def _reminders_page(self):
        page = self.reminders_tab
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.reminder_message = tk.StringVar()
        ttk.Label(page, textvariable=self.reminder_message, wraplength=800).grid(row=0, column=0, sticky="w", pady=(0, 14))
        table, self.reminder_tree = make_table(page, [
            ("service", "Сервис", 230), ("amount", "Сумма", 140),
            ("date", "Плановая дата", 150), ("text", "Срок оплаты", 240),
        ])
        table.grid(row=1, column=0, sticky="nsew")
        self.reminder_tree.tag_configure("overdue", foreground="#aa3030")
        self.reminder_tree.tag_configure("today", foreground="#815108")
        ttk.Button(page, text="Открыть выбранную подписку", command=lambda: self.safe(self.open_reminder)).grid(
            row=2, column=0, sticky="w", pady=12)
        ttk.Label(page, text="Напоминания пересчитываются при запуске и изменении данных.\n"
                  "Оплату и отключение услуги вы выполняете у поставщика самостоятельно.",
                  style="Muted.TLabel").grid(row=3, column=0, sticky="w")

    def _payments_page(self):
        page = self.payments_tab
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        filters = ttk.Frame(page)
        filters.grid(row=0, column=0, sticky="w", pady=(0, 12))
        today = self.service.today()
        self.month = tk.StringVar(value=MONTHS[today.month - 1])
        self.year = tk.StringVar(value=str(today.year))
        self.history_period = f"{today.year:04d}-{today.month:02d}"
        ttk.Label(filters, text="Месяц фактической оплаты").grid(row=0, column=0, sticky="w", pady=4)
        self.month_box = ttk.Combobox(filters, textvariable=self.month, values=MONTHS, state="readonly", width=15)
        self.month_box.grid(row=1, column=0, padx=(0, 12))
        ttk.Label(filters, text="Год").grid(row=0, column=1, sticky="w", pady=4)
        ttk.Spinbox(filters, from_=1, to=9999, textvariable=self.year, width=8).grid(row=1, column=1, padx=(0, 12))
        ttk.Button(filters, text="Показать", command=lambda: self.safe(self.refresh_payments)).grid(row=1, column=2)
        self.payments_message = tk.StringVar()
        ttk.Label(page, textvariable=self.payments_message).grid(row=1, column=0, sticky="w", pady=(0, 12))
        frame, self.payment_tree = make_payment_table(page)
        frame.grid(row=2, column=0, sticky="nsew")
        self.payment_total = tk.StringVar()
        ttk.Label(page, textvariable=self.payment_total, style="Metric.TLabel").grid(row=3, column=0, sticky="e", pady=16)
        ttk.Label(page, text="Здесь только подтверждённые платежи, включая платежи неактивных подписок.\n"
                  "Оценка расходов в месяц показана отдельно в верхней части окна.", style="Muted.TLabel").grid(row=4, column=0, sticky="w")

    def safe(self, callback):
        try:
            return callback()
        except (ValidationError, StorageError) as error:
            messagebox.showerror("Не удалось выполнить действие", str(error), parent=self.root)
            self.status.set("Действие не выполнено. Проверьте сообщение об ошибке.")
        return None

    def selected(self):
        selection = self.tree.selection()
        if not selection:
            raise ValidationError("Сначала выберите подписку в списке.")
        return self.service.get_subscription(int(selection[0]))

    def refresh_all(self, select_id=None):
        count, estimate = self.service.summary()
        self.count.set(f"{count} из 5")
        self.estimate.set(format_money(estimate))
        categories = self.service.categories()
        old_index = self.category_box.current()
        old_category = self.category_values[old_index] if old_index >= 0 else None
        self.category_values = [None, *categories]
        self.category_box.configure(values=["Все категории", *[f"Категория: {item}" if item else "Без категории" for item in categories]])
        self.category_box.current(self.category_values.index(old_category) if old_category in self.category_values else 0)
        self.refresh_list(select_id)
        self.refresh_reminders()
        self._display_payments(self.history_period)
        self.status.set(f"Данные обновлены · {format_date(self.service.today())}")

    def refresh_list(self, select_id=None):
        previous = self.tree.selection()
        desired = str(select_id) if select_id is not None else (previous[0] if previous else None)
        active = {"Все статусы": None, "Активна": True, "Неактивна": False}[self.status_filter.get()]
        index = self.category_box.current()
        category = self.category_values[index] if index >= 0 else None
        items = self.service.list_subscriptions(self.search.get(), active, category)
        self.items = {str(item.id): item for item in items}
        self.tree.delete(*self.tree.get_children())
        for item in items:
            self.tree.insert("", "end", iid=str(item.id), values=(
                item.service, format_money(item.amount_cents), PERIODS[item.period],
                format_date(item.next_date), STATUSES[item.active],
            ))
        if desired in self.items:
            self.tree.selection_set(desired)
            self.tree.focus(desired)
            self.tree.see(desired)
        if items:
            self.list_message.set(f"Найдено подписок: {len(items)}. Активные — по ближайшей дате оплаты.")
        elif self.service.list_subscriptions():
            self.list_message.set("Совпадений нет. Измените поиск или сбросьте фильтры.")
        else:
            self.list_message.set("Подписок пока нет. Нажмите «+ Добавить», чтобы начать учёт.")
        self.update_details()

    def update_details(self):
        selected = self.tree.selection()
        item = self.items.get(selected[0]) if selected else None
        buttons = (self.edit_button, self.pay_button, self.history_button, self.active_button, self.delete_button)
        for button in buttons:
            button.state(["!disabled"] if item else ["disabled"])
        if item is None:
            set_text(self.details, "Выберите подписку в таблице, чтобы увидеть все сведения и доступные действия.")
            return
        self.pay_button.state(["!disabled"] if item.active else ["disabled"])
        self.active_button.configure(text="Сделать неактивной" if item.active else "Возобновить")
        set_text(self.details,
                 f"{item.service}\n\nТариф: {item.plan or '—'}\nКатегория: {item.category or '—'}\n\n"
                 f"Стоимость: {format_money(item.amount_cents)}\nПериод: {PERIODS[item.period]}\n"
                 f"Следующая дата: {format_date(item.next_date)}\nСтатус: {STATUSES[item.active]}\n\n"
                 f"Примечание:\n{item.note or '—'}\n\nНомер записи: {item.id}\n"
                 f"Исходная дата графика: {format_date(item.anchor_date)}")

    def refresh_reminders(self):
        items = self.service.reminders()
        self.reminder_tree.delete(*self.reminder_tree.get_children())
        for reminder in items:
            item = reminder.subscription
            tag = "overdue" if reminder.days < 0 else "today" if reminder.days == 0 else "upcoming"
            self.reminder_tree.insert("", "end", iid=str(item.id), values=(
                item.service, format_money(item.amount_cents), format_date(item.next_date), reminder.explanation,
            ), tags=(tag,))
        self.notebook.tab(self.reminders_tab, text=f"К оплате ({len(items)})")
        self.reminder_message.set(
            f"На {format_date(self.service.today())}: просроченные оплаты, сегодня и ближайшие 7 дней включительно."
            if items else "Просроченных оплат и оплат в ближайшие 7 дней нет."
        )

    def refresh_payments(self):
        try:
            year = int(self.year.get())
            if not 1 <= year <= 9999:
                raise ValueError
            month = MONTHS.index(self.month.get()) + 1
        except ValueError:
            raise ValidationError("Месяц истории: выберите месяц и год от 1 до 9999.") from None
        period = f"{year:04d}-{month:02d}"
        self._display_payments(period)
        self.history_period = period

    def _display_payments(self, period):
        payments, total = self.service.payment_history(month=period)
        fill_payments(self.payment_tree, payments)
        self.payment_total.set(f"Фактически оплачено: {format_money(total)}")
        self.payments_message.set(f"Платежей за выбранный месяц: {len(payments)}." if payments else "За выбранный месяц платежей нет.")

    def reset_filters(self):
        self.status_filter.set("Все статусы")
        self.category_box.current(0)
        self.search.set("")
        self.refresh_list()

    def add_subscription(self):
        if self.service.summary()[0] >= 5:
            raise ValidationError("Лимит: уже 5 активных подписок. Сначала сделайте одну из них неактивной.")
        dialog = SubscriptionDialog(self.root, self.service)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.reset_filters()
            self.refresh_all(dialog.result.id)
            self.status.set("Подписка сохранена.")

    def edit_subscription(self):
        dialog = SubscriptionDialog(self.root, self.service, self.selected())
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.refresh_all(dialog.result.id)
            self.status.set("Изменения сохранены.")

    def record_payment(self):
        item = self.selected()
        if not item.active:
            raise ValidationError("Платёж: сначала возобновите подписку.")
        dialog = PaymentDialog(self.root, self.service, item)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.refresh_all(item.id)
            self.status.set("Платёж сохранён. Следующая дата сдвинута на один период.")

    def toggle_active(self):
        item = self.selected()
        if item.active:
            confirmed = messagebox.askyesno(
                "Сделать подписку неактивной?",
                f"{item.service}: исключить из оценки расходов и напоминаний?\n\n"
                "История платежей сохранится. Услугу у поставщика нужно отключить самостоятельно.", parent=self.root,
            )
            if not confirmed:
                return
            result = self.service.set_active(item.id, False)
        else:
            dialog = ActivationDialog(self.root, self.service, item)
            self.root.wait_window(dialog)
            result = dialog.result
        if result is not None:
            self.refresh_all(item.id)
            self.status.set("Статус подписки сохранён.")

    def delete_subscription(self):
        item = self.selected()
        if self.service.has_payments(item.id):
            raise ValidationError("У подписки есть платежи: удаление запрещено. Используйте «Сделать неактивной».")
        if not messagebox.askyesno("Удалить подписку?", f"Удалить «{item.service}»? Это действие нельзя отменить.", parent=self.root):
            return
        self.service.delete_subscription(item.id)
        self.refresh_all()
        self.status.set("Подписка удалена.")

    def show_history(self):
        item = self.selected()
        payments, total = self.service.payment_history(item.id)
        dialog = HistoryDialog(self.root, item, payments, total)
        self.root.wait_window(dialog)

    def open_reminder(self):
        selected = self.reminder_tree.selection()
        if not selected:
            raise ValidationError("Выберите строку напоминания.")
        self.reset_filters()
        self.notebook.select(self.subscriptions_tab)
        self.refresh_list(int(selected[0]))
