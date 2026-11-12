"""Выбор даты в календаре с сохранением обычного текстового ввода."""

import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk

from subscriptions.domain import ValidationError, format_date, parse_date


MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


class CalendarDialog(tk.Toplevel):
    def __init__(self, parent, initial_date, today):
        super().__init__(parent)
        self.withdraw()
        self.title("Выбор даты")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        self.initial_date = initial_date
        self.today = today
        self.year, self.month = initial_date.year, initial_date.month
        self.previous_grab = self.grab_current()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", self._cancel)

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        controls = ttk.Frame(body)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(1, weight=1)
        self.previous_button = ttk.Button(controls, text="‹", width=3, command=lambda: self.shift_month(-1))
        self.previous_button.grid(row=0, column=0, padx=(0, 6))
        self.month_box = ttk.Combobox(controls, values=MONTHS, state="readonly", width=12)
        self.month_box.grid(row=0, column=1, sticky="ew")
        self.month_box.bind("<<ComboboxSelected>>", self.change_period)
        self.year_value = tk.StringVar(value=str(self.year))
        year_box = ttk.Spinbox(controls, from_=1, to=9999, width=6,
                               textvariable=self.year_value, command=self.change_period)
        year_box.grid(row=0, column=2, padx=6)
        year_box.bind("<Return>", self.change_period)
        year_box.bind("<FocusOut>", self.change_period)
        self.next_button = ttk.Button(controls, text="›", width=3, command=lambda: self.shift_month(1))
        self.next_button.grid(row=0, column=3)

        self.days_frame = ttk.Frame(body)
        self.days_frame.grid(row=1, column=0, sticky="ew")
        self.error = tk.StringVar()
        ttk.Label(body, textvariable=self.error, foreground="#a02a30", wraplength=330).grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        actions = ttk.Frame(body)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Сегодня", command=lambda: self.choose(self.today)).pack(side="left")
        ttk.Button(actions, text="Отмена", command=self.destroy).pack(side="right")
        self.draw_month()

        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        x = max(0, min(parent.winfo_rootx(), self.winfo_screenwidth() - width))
        y = parent.winfo_rooty() + parent.winfo_height() + 4
        if y + height > self.winfo_screenheight():
            y = max(0, parent.winfo_rooty() - height - 4)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.grab_set()
        self.day_buttons[initial_date.day].focus_set()

    def _cancel(self, event=None):
        self.destroy()
        return "break"

    def change_period(self, event=None):
        try:
            year = int(self.year_value.get())
            month = self.month_box.current() + 1
            date(year, month, 1)
        except ValueError:
            self.error.set("Выберите месяц и год от 1 до 9999.")
            return False
        self.error.set("")
        if (year, month) != (self.year, self.month):
            self.year, self.month = year, month
            self.draw_month()
        return True

    def shift_month(self, offset):
        if not self.change_period():
            return
        ordinal = (self.year - 1) * 12 + self.month - 1 + offset
        if not 0 <= ordinal < 9999 * 12:
            return
        self.year, month_index = divmod(ordinal, 12)
        self.year += 1
        self.month = month_index + 1
        self.draw_month()

    def draw_month(self):
        self.month_box.current(self.month - 1)
        self.year_value.set(str(self.year))
        self.previous_button.state(["disabled"] if (self.year, self.month) == (1, 1) else ["!disabled"])
        self.next_button.state(["disabled"] if (self.year, self.month) == (9999, 12) else ["!disabled"])
        for child in self.days_frame.winfo_children():
            child.destroy()
        for column, label in enumerate(("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")):
            ttk.Label(self.days_frame, text=label, anchor="center").grid(row=0, column=column, sticky="ew")
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        self.day_buttons = {}
        for row in range(6):
            for column in range(7):
                day = weeks[row][column] if row < len(weeks) else 0
                button = ttk.Button(self.days_frame, text=str(day) if day else "", width=3)
                button.grid(row=row + 1, column=column, padx=1, pady=1)
                if day:
                    selected = date(self.year, self.month, day)
                    button.configure(command=lambda value=day: self.choose_day(value))
                    if selected == self.initial_date:
                        button.configure(style="Accent.TButton")
                    self.day_buttons[day] = button
                else:
                    button.state(["disabled"])

    def choose_day(self, day):
        if not self.change_period():
            return
        try:
            value = date(self.year, self.month, day)
        except ValueError:
            self.error.set("В выбранном месяце нет такого дня.")
            return
        self.choose(value)

    def choose(self, value):
        self.result = value
        self.destroy()

    def destroy(self):
        previous_grab = self.previous_grab
        super().destroy()
        if previous_grab is not None:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
            except tk.TclError:
                # Родительское окно также могло закрыться при завершении программы.
                pass


class DateEntry(ttk.Frame):
    def __init__(self, parent, variable, today=date.today):
        super().__init__(parent)
        self.variable = variable
        self.today = today
        self.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(self, textvariable=variable, width=20)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.calendar_button = ttk.Button(self, text="Календарь", command=self.open_calendar)
        self.calendar_button.grid(row=0, column=1, padx=(8, 0))

    def open_calendar(self):
        try:
            initial_date = parse_date(self.variable.get())
        except ValidationError:
            initial_date = self.today()
        dialog = CalendarDialog(self, initial_date, self.today())
        self.wait_window(dialog)
        if self.winfo_exists():
            if dialog.result is not None:
                self.variable.set(format_date(dialog.result))
            self.entry.focus_set()
