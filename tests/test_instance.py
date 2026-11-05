import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from subscriptions.instance import AlreadyRunning, InstanceLock


PROJECT = Path(__file__).resolve().parents[1]


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "subscriptions.sqlite3"

    def test_second_process_cannot_open_same_database(self):
        lock = InstanceLock(self.path)
        lock.acquire()
        self.addCleanup(lock.release)
        code = """import sys
from subscriptions.instance import InstanceLock, AlreadyRunning
lock = InstanceLock(sys.argv[1])
try:
    lock.acquire()
except AlreadyRunning:
    print('already-running')
    sys.exit(2)
sys.exit(0)
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], cwd=PROJECT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("already-running", result.stdout)

    def test_crash_releases_lock_without_deleting_file(self):
        code = """import sys
from subscriptions.instance import InstanceLock
lock = InstanceLock(sys.argv[1])
lock.acquire()
print('locked', flush=True)
input()
"""
        child = subprocess.Popen([sys.executable, "-c", code, str(self.path)], cwd=PROJECT,
                                 stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            second = InstanceLock(self.path)
            with self.assertRaises(AlreadyRunning):
                second.acquire()
        finally:
            child.kill()
            child.communicate(timeout=10)
        after_crash = InstanceLock(self.path)
        after_crash.acquire()
        after_crash.release()
        self.assertTrue(after_crash.path.exists())

    def test_database_path_does_not_depend_on_working_directory(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT)
        result = subprocess.run([sys.executable, "-c", "import main; print(main.DATABASE_PATH)"],
                                cwd=self.temp.name, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), PROJECT / "data" / "subscriptions.sqlite3")


if __name__ == "__main__":
    unittest.main()
