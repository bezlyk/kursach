import tkinter as tk
from tkinter import ttk

from subscriptions.domain import format_date, format_money


def make_table(parent, columns, height=10):
    frame = ttk.Frame(parent)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[item[0] for item in columns], show="headings", height=height, selectmode="browse")
    for name, title, width in columns:
        tree.heading(name, text=title)
        tree.column(name, width=width, minwidth=80, anchor="w")
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    return frame, tree


def make_payment_table(parent):
    return make_table(parent, [
        ("service", "Сервис", 230), ("planned", "Плановая дата", 150),
        ("actual", "Фактическая дата", 160), ("amount", "Сумма", 150),
    ])


def fill_payments(tree, payments):
    tree.delete(*tree.get_children())
    for payment in payments:
        tree.insert("", "end", iid=str(payment.id), values=(
            payment.service, format_date(payment.planned_date),
            format_date(payment.actual_date), format_money(payment.amount_cents),
        ))


def readonly_text(parent, height=12):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    text = tk.Text(frame, wrap="word", height=height, width=28, relief="flat", padx=12, pady=12,
                   background="#ffffff", foreground="#243348", font="TkDefaultFont", state="disabled")
    scroll = ttk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    return frame, text


def set_text(widget, text):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")
