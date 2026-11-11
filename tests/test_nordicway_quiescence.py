import fcntl
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import nordicway_quiescence as q


class QuiescenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.var = Path(self.tmp.name)
        (self.var / 'hotwatch-autostart.enabled').touch()
        self.clean = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))

    def tearDown(self): self.tmp.cleanup()

    def test_marker_restored_after_work(self):
        with q.stopped_motor(self.var, runner=self.clean):
            self.assertTrue((self.var / 'hotwatch-autostart.disabled').is_file())
        self.assertTrue((self.var / 'hotwatch-autostart.enabled').is_file())
        self.assertFalse((self.var / 'hotwatch-autostart.disabled').exists())

    def test_existing_disabled_marker_is_preserved(self):
        (self.var / 'hotwatch-autostart.disabled').touch()
        with q.stopped_motor(self.var, runner=self.clean): pass
        self.assertTrue((self.var / 'hotwatch-autostart.disabled').is_file())
        self.assertTrue((self.var / 'hotwatch-autostart.enabled').is_file())

    def test_held_worker_lock_blocks_and_restores_marker(self):
        fd = os.open(self.var / 'hotwatch-worker.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(TimeoutError, 'motor_not_stopped'):
                with q.stopped_motor(self.var, timeout=0, runner=self.clean): self.fail()
        finally:
            os.close(fd)
        self.assertFalse((self.var / 'hotwatch-autostart.disabled').exists())

    def test_process_blocks_even_without_a_lock(self):
        proc = Mock(return_value=subprocess.CompletedProcess(
            [], 0, '/usr/bin/python /home/user/hotwatch_service.py --run\n', ''))
        with self.assertRaisesRegex(TimeoutError, 'motor_not_stopped'):
            with q.stopped_motor(self.var, timeout=0, runner=proc): self.fail()
        self.assertFalse((self.var / 'hotwatch-autostart.disabled').exists())

    def test_ps_failure_fails_closed(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            with q.stopped_motor(self.var, runner=Mock(side_effect=subprocess.TimeoutExpired('ps', 5))): self.fail()
        self.assertFalse((self.var / 'hotwatch-autostart.disabled').exists())


if __name__ == '__main__': unittest.main()
