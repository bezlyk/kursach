import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import main

try:
    import tkinter as tk
    from subscriptions.dialogs import ActivationDialog, HistoryDialog, PaymentDialog, SubscriptionDialog
    from subscriptions.date_picker import CalendarDialog
    from subscriptions.ui import Application
except ImportError:
    tk = None

from subscriptions.database import Database
from subscriptions.service import SubscriptionService


@unittest.skipIf(tk is None, "Tkinter не установлен")
class InterfaceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Нет графического экрана: {error}")
        self.addCleanup(self.root.destroy)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / "ui.sqlite3")
        self.addCleanup(self.database.close)
        self.service = SubscriptionService(self.database, today=lambda: date(2027, 3, 10))
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        self.app = Application(self.root, self.service)
        self.root.update()

    def tearDown(self):
        self.root.update()
        self.assertEqual(self.callback_errors, [])

    def create(self, name="Музыка", **fields):
        return self.service.create_subscription(name, "300", "month", date(2027, 3, 10), **fields)

    def select(self, item):
        self.app.refresh_all(item.id)
        self.root.update()

    def schedule_dialog(self, dialog_type, action):
        def when_visible():
            dialogs = [child for child in self.root.winfo_children()
                       if isinstance(child, dialog_type) and child.winfo_viewable()]
            if not dialogs:
                self.root.after(10, when_visible)
                return
            action(dialogs[0])
        self.root.after_idle(when_visible)

    def test_initial_empty_state_and_buttons_at_minimum_size(self):
        self.assertEqual(self.app.count.get(), "0 из 5")
        self.assertEqual(self.app.estimate.get(), "0,00 руб.")
        self.assertIn("Добавить", self.app.list_message.get())
        self.assertTrue(self.app.pay_button.instate(["disabled"]))
        self.root.geometry("900x650")
        self.root.update()
        for button in (self.app.edit_button, self.app.pay_button, self.app.delete_button, self.app.active_button):
            with self.subTest(button=button):
                self.assertGreaterEqual(button.winfo_rootx(), self.root.winfo_rootx())
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())

    def test_add_through_dialog_updates_table_and_summary(self):
        def fill_form(dialog):
            dialog.variables["service"].set("Кинотеатр")
            dialog.variables["amount"].set("250,50")
            dialog.variables["category"].set("Видео")
            dialog.save_button.invoke()
        self.schedule_dialog(SubscriptionDialog, fill_form)
        self.app.add_subscription()
        self.assertEqual(self.app.count.get(), "1 из 5")
        self.assertEqual(self.app.estimate.get(), "250,50 руб.")
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.assertIn("Кинотеатр", self.app.details.get("1.0", "end"))

    def choose_calendar_date(self, field, value):
        def select_day():
            pickers = [child for child in field.winfo_children()
                       if isinstance(child, CalendarDialog) and child.winfo_viewable()]
            if not pickers:
                self.root.after(10, select_day)
                return
            picker = pickers[0]
            picker.year_value.set(str(value.year))
            picker.month_box.current(value.month - 1)
            picker.month_box.event_generate("<<ComboboxSelected>>")
            picker.day_buttons[value.day].invoke()
        self.root.after_idle(select_day)
        field.calendar_button.invoke()

    def test_subscription_calendar_adds_and_edits_without_automatic_save(self):
        dialog = SubscriptionDialog(self.root, self.service)
        dialog.variables["service"].set("Кино")
        dialog.variables["amount"].set("100")
        self.choose_calendar_date(dialog.next_date_field, date(2028, 2, 29))
        self.assertEqual(self.service.list_subscriptions(), [])
        self.assertEqual(self.root.grab_current(), dialog)
        dialog.save_button.invoke()
        item = self.service.list_subscriptions()[0]
        self.assertEqual(item.next_date, date(2028, 2, 29))
        editing = SubscriptionDialog(self.root, self.service, item)
        self.choose_calendar_date(editing.next_date_field, date(2028, 3, 31))
        editing.save_button.invoke()
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2028, 3, 31))

    def test_payment_calendar_keeps_future_date_validation(self):
        item = self.create()
        dialog = PaymentDialog(self.root, self.service, item)
        self.choose_calendar_date(dialog.actual_date_field, date(2027, 3, 11))
        dialog.save_button.invoke()
        self.assertIn("Фактическая дата", dialog.error.get())
        self.assertEqual(self.service.payment_history(), ([], 0))
        self.choose_calendar_date(dialog.actual_date_field, date(2027, 3, 9))
        dialog.save_button.invoke()
        payments, total = self.service.payment_history(item.id)
        self.assertEqual((len(payments), total), (1, 30000))
        self.assertEqual(payments[0].actual_date, date(2027, 3, 9))

    def test_activation_calendar_saves_selected_next_date(self):
        item = self.create()
        self.service.set_active(item.id, False)
        dialog = ActivationDialog(self.root, self.service, self.service.get_subscription(item.id))
        self.choose_calendar_date(dialog.next_date_field, date(2027, 4, 15))
        self.assertFalse(self.service.get_subscription(item.id).active)
        dialog.save_button.invoke()
        updated = self.service.get_subscription(item.id)
        self.assertTrue(updated.active)
        self.assertEqual(updated.next_date, date(2027, 4, 15))

    def test_form_error_allows_correction_and_cancel_does_not_write(self):
        dialog = SubscriptionDialog(self.root, self.service)
        dialog.variables["service"].set("Кино")
        dialog.variables["amount"].set("0")
        dialog.submit()
        self.assertIn("Стоимость", dialog.error.get())
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.service.list_subscriptions(), [])
        dialog.variables["amount"].set("100")
        dialog.submit()
        item = self.service.list_subscriptions()[0]
        editing = SubscriptionDialog(self.root, self.service, item)
        editing.variables["service"].set("Не сохранять")
        editing.destroy()
        self.assertEqual(self.service.get_subscription(item.id), item)

    def test_edit_dialog_saves_all_fields(self):
        item = self.create()
        dialog = SubscriptionDialog(self.root, self.service, item)
        changes = {"service": "Архив", "amount": "1200", "plan": "Семейный", "category": "Видео",
                   "period": "Год", "next_date": "31.12.2027", "active": "Неактивна"}
        for key, value in changes.items():
            dialog.variables[key].set(value)
        dialog.note.insert("1.0", "Заметка")
        dialog.submit()
        updated = self.service.get_subscription(item.id)
        self.assertEqual((updated.service, updated.plan, updated.category, updated.note), ("Архив", "Семейный", "Видео", "Заметка"))
        self.assertEqual((updated.period, updated.next_date, updated.active), ("year", date(2027, 12, 31), False))

    def test_payment_form_defaults_error_cancel_and_double_submit(self):
        item = self.create()
        dialog = PaymentDialog(self.root, self.service, item)
        self.assertEqual(dialog.amount.get(), "300,00")
        self.assertEqual(dialog.actual_date.get(), "10.03.2027")
        dialog.actual_date.set("11.03.2027")
        dialog.submit()
        self.assertIn("Фактическая дата", dialog.error.get())
        self.assertEqual(self.service.payment_history(), ([], 0))
        dialog.actual_date.set("09.03.2027")
        dialog.amount.set("299,90")
        dialog.submit()
        dialog.submit()
        history, total = self.service.payment_history(item.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(total, 29990)
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2027, 4, 10))
        canceled = PaymentDialog(self.root, self.service, self.service.get_subscription(item.id))
        canceled.destroy()
        self.assertEqual(len(self.service.payment_history()[0]), 1)

    def test_payment_action_refreshes_history_date_and_reminders(self):
        item = self.create()
        self.select(item)
        self.schedule_dialog(PaymentDialog, lambda dialog: dialog.save_button.invoke())
        self.app.record_payment()
        self.assertEqual(len(self.app.payment_tree.get_children()), 1)
        self.assertEqual(len(self.app.reminder_tree.get_children()), 0)
        self.assertIn("10.04.2027", self.app.details.get("1.0", "end"))
        self.assertIn("Платёж сохранён", self.app.status.get())

    def test_combined_filters_and_summary_independence(self):
        item = self.create("Яндекс Музыка", category="Музыка")
        other = self.create("ЯНДЕКС Плюс", category="Видео")
        self.select(item)
        self.app.search.set("яНдЕкС")
        self.app.status_filter.set("Активна")
        self.app.category_box.current(self.app.category_values.index("Музыка"))
        self.app.refresh_list()
        self.assertEqual(self.app.tree.get_children(), (str(item.id),))
        self.assertEqual(self.app.count.get(), "2 из 5")
        self.assertEqual(self.app.estimate.get(), "600,00 руб.")
        self.app.search.set("нет совпадения")
        self.assertIn("Совпадений нет", self.app.list_message.get())
        self.app.reset_filters()
        self.assertEqual(set(self.app.tree.get_children()), {str(item.id), str(other.id)})

    def test_deactivation_cancel_confirm_and_activation_date(self):
        item = self.create()
        self.service.record_payment(item.id, item.next_date, "300", item.next_date)
        self.select(item)
        with patch("subscriptions.ui.messagebox.askyesno", return_value=False):
            self.app.toggle_active()
        self.assertTrue(self.service.get_subscription(item.id).active)
        with patch("subscriptions.ui.messagebox.askyesno", return_value=True):
            self.app.toggle_active()
        self.assertFalse(self.service.get_subscription(item.id).active)
        self.assertEqual(self.app.count.get(), "0 из 5")
        self.assertTrue(self.app.pay_button.instate(["disabled"]))
        self.assertEqual(len(self.app.payment_tree.get_children()), 1)
        dialog = ActivationDialog(self.root, self.service, self.service.get_subscription(item.id))
        dialog.next_date.set("15.05.2027")
        dialog.submit()
        self.assertEqual(self.service.get_subscription(item.id).next_date, date(2027, 5, 15))
        self.assertTrue(self.service.get_subscription(item.id).active)

    def test_delete_cancel_confirm_and_block_with_history(self):
        item = self.create()
        self.select(item)
        with patch("subscriptions.ui.messagebox.askyesno", return_value=False):
            self.app.delete_subscription()
        self.assertEqual(len(self.service.list_subscriptions()), 1)
        with patch("subscriptions.ui.messagebox.askyesno", return_value=True):
            self.app.delete_subscription()
        self.assertEqual(self.service.list_subscriptions(), [])
        item = self.create()
        self.service.record_payment(item.id, item.next_date, "300", item.next_date)
        self.select(item)
        with patch("subscriptions.ui.messagebox.showerror") as show_error:
            self.app.safe(self.app.delete_subscription)
        show_error.assert_called_once()
        self.assertEqual(len(self.service.list_subscriptions()), 1)

    def test_month_history_and_subscription_history_window(self):
        item = self.create()
        self.service.record_payment(item.id, item.next_date, "250", date(2027, 2, 28))
        self.select(item)
        self.app.month.set("Февраль")
        self.app.refresh_payments()
        self.assertEqual(len(self.app.payment_tree.get_children()), 1)
        self.assertIn("250,00", self.app.payment_total.get())
        self.app.year.set("ошибка")
        self.app.refresh_all(item.id)
        self.assertEqual(len(self.app.payment_tree.get_children()), 1)
        with patch("subscriptions.ui.messagebox.showerror") as error:
            self.app.safe(self.app.refresh_payments)
        error.assert_called_once()
        payments, total = self.service.payment_history(item.id)
        history = HistoryDialog(self.root, item, payments, total)
        self.assertEqual(len(history.tree.get_children()), 1)
        history.destroy()

    def test_reminder_opens_subscription_and_clears_filters(self):
        item = self.create()
        self.app.refresh_all()
        self.app.search.set("нет совпадений")
        self.app.reminder_tree.selection_set(str(item.id))
        self.app.open_reminder()
        self.assertEqual(self.app.tree.selection(), (str(item.id),))
        self.assertEqual(self.app.search.get(), "")

    def test_category_labels_do_not_collide(self):
        uncategorized = self.create("Без категории")
        named = self.create("Названная", category="Без категории")
        self.app.refresh_all()
        for category, expected in (("", uncategorized.id), ("Без категории", named.id)):
            self.app.category_box.current(self.app.category_values.index(category))
            self.app.refresh_list()
            self.assertEqual(self.app.tree.get_children(), (str(expected),))


@unittest.skipIf(tk is None, "Tkinter не установлен")
class EntryPointTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Нет графического экрана: {error}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data" / "subscriptions.sqlite3"
        self.addCleanup(self.close_root)

    def close_root(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_main_starts_closes_and_creates_empty_database(self):
        self.root.after(50, self.root.quit)
        with patch.object(main, "DATABASE_PATH", self.path), patch.object(tk, "Tk", return_value=self.root):
            self.assertEqual(main.run(), 0)
        database = Database(self.path)
        self.addCleanup(database.close)
        self.assertEqual(database.list_subscriptions(), [])

    def test_second_instance_displays_message_and_preserves_database(self):
        from subscriptions.instance import InstanceLock
        first = InstanceLock(self.path)
        first.acquire()
        self.addCleanup(first.release)
        with patch.object(main, "DATABASE_PATH", self.path), patch.object(tk, "Tk", return_value=self.root), \
                patch("tkinter.messagebox.showerror") as error:
            self.assertEqual(main.run(), 1)
        self.assertIn("другом экземпляре", error.call_args.args[1])
        self.assertFalse(self.path.exists())

    def test_startup_storage_error_is_explained_and_lock_released(self):
        from subscriptions.instance import InstanceLock
        self.path.mkdir(parents=True)
        with patch.object(main, "DATABASE_PATH", self.path), patch.object(tk, "Tk", return_value=self.root), \
                patch("tkinter.messagebox.showerror") as error:
            self.assertEqual(main.run(), 1)
        self.assertIn("Не удалось открыть базу", error.call_args.args[1])
        self.assertTrue(self.path.is_dir())
        retry = InstanceLock(self.path)
        retry.acquire()
        retry.release()


if __name__ == "__main__":
    unittest.main()
