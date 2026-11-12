import unittest
from datetime import date

try:
    import tkinter as tk
    from subscriptions.date_picker import CalendarDialog, DateEntry
except ImportError:
    tk = None


@unittest.skipIf(tk is None, "Tkinter не установлен")
class CalendarTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Нет графического экрана: {error}")
        self.addCleanup(self.root.destroy)
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        self.root.update()

    def tearDown(self):
        self.assertEqual(self.callback_errors, [])

    def schedule_calendar(self, field, action):
        def when_visible():
            pickers = [child for child in field.winfo_children()
                       if isinstance(child, CalendarDialog) and child.winfo_viewable()]
            if not pickers:
                self.root.after(10, when_visible)
                return
            action(pickers[0])
        self.root.after_idle(when_visible)

    def test_leap_year_days_and_monday_first_grid(self):
        picker = CalendarDialog(self.root, date(2024, 2, 29), date(2027, 3, 10))
        self.assertEqual(set(picker.day_buttons), set(range(1, 30)))
        self.assertEqual(picker.day_buttons[29].grid_info()["column"], 3)
        picker.day_buttons[29].invoke()
        self.assertEqual(picker.result, date(2024, 2, 29))

    def test_year_rollover_and_date_range_boundaries(self):
        picker = CalendarDialog(self.root, date(2027, 12, 31), date(2027, 3, 10))
        picker.next_button.invoke()
        self.assertEqual((picker.year, picker.month), (2028, 1))
        picker.previous_button.invoke()
        self.assertEqual((picker.year, picker.month), (2027, 12))
        picker.destroy()
        for initial, disabled_button in ((date.min, "previous_button"), (date.max, "next_button")):
            with self.subTest(initial=initial):
                picker = CalendarDialog(self.root, initial, date(2027, 3, 10))
                self.assertTrue(getattr(picker, disabled_button).instate(["disabled"]))
                getattr(picker, disabled_button).invoke()
                self.assertEqual((picker.year, picker.month), (initial.year, initial.month))
                picker.destroy()

    def test_changing_year_checks_input_and_rebuilds_february(self):
        picker = CalendarDialog(self.root, date(2027, 2, 28), date(2027, 3, 10))
        picker.year_value.set("не год")
        self.assertFalse(picker.change_period())
        self.assertIn("год", picker.error.get())
        self.assertEqual((picker.year, picker.month), (2027, 2))
        picker.day_buttons[1].invoke()
        self.assertIsNone(picker.result)
        self.assertTrue(picker.winfo_exists())
        picker.year_value.set("2028")
        self.assertTrue(picker.change_period())
        picker.day_buttons[29].invoke()
        self.assertEqual(picker.result, date(2028, 2, 29))

    def test_manual_entry_calendar_choice_and_today_action(self):
        value = tk.StringVar(value="01.03.2027")
        field = DateEntry(self.root, value, today=lambda: date(2027, 3, 10))
        field.pack()
        self.root.update()
        field.entry.delete(0, "end")
        field.entry.insert(0, "29.02.2024")
        self.assertEqual(value.get(), "29.02.2024")

        def select_day(picker):
            self.assertEqual((picker.year, picker.month), (2024, 2))
            picker.day_buttons[28].invoke()

        self.schedule_calendar(field, select_day)
        field.calendar_button.invoke()
        self.assertEqual(value.get(), "28.02.2024")

        def select_today(picker):
            # Действие «Сегодня» доступно даже при другом открытом месяце.
            def find_button(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == "TButton" and child.cget("text") == "Сегодня":
                        return child
                    found = find_button(child)
                    if found is not None:
                        return found
            find_button(picker).invoke()

        self.schedule_calendar(field, select_today)
        field.calendar_button.invoke()
        self.assertEqual(value.get(), "10.03.2027")

    def test_cancel_preserves_invalid_manual_value_and_restores_parent_grab(self):
        parent = tk.Toplevel(self.root)
        value = tk.StringVar(value="не исправлять автоматически")
        field = DateEntry(parent, value, today=lambda: date(2027, 3, 10))
        field.pack()
        self.root.update()
        parent.grab_set()

        def cancel(picker):
            self.assertEqual((picker.year, picker.month), (2027, 3))
            picker.event_generate("<Escape>")
            # На виртуальном экране без оконного менеджера фокус может ещё не прийти.
            if picker.winfo_exists():
                picker.destroy()

        self.schedule_calendar(field, cancel)
        field.calendar_button.invoke()
        self.assertEqual(value.get(), "не исправлять автоматически")
        self.assertEqual(self.root.grab_current(), parent)


if __name__ == "__main__":
    unittest.main()
