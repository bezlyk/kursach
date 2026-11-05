import errno
import os
from pathlib import Path


class AlreadyRunning(Exception):
    pass


class InstanceLock:
    def __init__(self, database_path):
        self.path = Path(str(Path(database_path).resolve()) + ".lock")
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            lock_file.close()
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise AlreadyRunning("Этот файл базы уже открыт в другом экземпляре приложения. Закройте его и повторите запуск.") from error
            raise
        self.file = lock_file

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None
