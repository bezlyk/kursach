import sqlite3
import sys
from pathlib import Path

from subscriptions.database import Database
from subscriptions.domain import StorageError
from subscriptions.instance import AlreadyRunning, InstanceLock
from subscriptions.service import SubscriptionService


PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = PROJECT_DIR / "data" / "subscriptions.sqlite3"


def run():
    try:
        import tkinter as tk
        from tkinter import messagebox
        from subscriptions.ui import Application
    except ImportError:
        print("Не найден Tkinter. Установите Python с компонентом Tcl/Tk (в Linux — python3-tk).", file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        print("Не удалось открыть окно. Нужен графический рабочий стол и установленный Tcl/Tk.", file=sys.stderr)
        return 1
    lock = InstanceLock(DATABASE_PATH)
    database = None
    try:
        lock.acquire()
        database = Database(DATABASE_PATH)
        Application(root, SubscriptionService(database))
        root.deiconify()
        root.mainloop()
        return 0
    except (AlreadyRunning, OSError, sqlite3.Error, StorageError) as error:
        if isinstance(error, (AlreadyRunning, StorageError)):
            text = str(error)
        else:
            text = ("Не удалось открыть базу данных. Проверьте права на папку проекта, свободное место "
                    "и доступность файла data/subscriptions.sqlite3. Существующая база не заменялась.")
        messagebox.showerror("Мои подписки", text, parent=root)
        return 1
    finally:
        try:
            if database is not None:
                database.close()
        finally:
            lock.release()
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    sys.exit(run())
