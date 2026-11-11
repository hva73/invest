import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_autostart as a
import apply_update


class AutostartTests(unittest.TestCase):
    def test_real_updater_does_not_enable_previously_disabled_autostart(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'escape_app'
            source = target / 'opdatering' / 'release'
            source.mkdir(parents=True)
            (target / 'var').mkdir()
            with sqlite3.connect(target / 'var' / 'escape.db') as db:
                db.execute('CREATE TABLE sample (value TEXT)')
            for name in apply_update.FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic source')
            with a.preserve(target / 'var'):
                apply_update.apply(source, target)
            self.assertFalse((target / 'var' / a.NAMES[0]).exists())
            self.assertFalse((target / 'var' / a.NAMES[1]).exists())

    def test_disabled_and_enabled_states_survive_updater(self):
        for enabled, disabled in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(enabled=enabled, disabled=disabled), tempfile.TemporaryDirectory() as tmp:
                var = Path(tmp)
                before = (enabled, disabled)
                for name, present in zip(a.NAMES, before):
                    if present:
                        (var / name).touch()
                with a.preserve(var):
                    # Existing updater may add enabled when no disabled marker exists.
                    if not (var / a.NAMES[1]).exists():
                        (var / a.NAMES[0]).touch()
                self.assertEqual(tuple((var / n).exists() for n in a.NAMES), before)

    def test_restores_state_on_error_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            var = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                with a.preserve(var):
                    (var / a.NAMES[0]).touch()
                    raise RuntimeError('failed')
            self.assertFalse((var / a.NAMES[0]).exists())
            (var / a.NAMES[0]).symlink_to(var / 'elsewhere')
            with self.assertRaisesRegex(ValueError, 'unexpected_autostart_marker'):
                with a.preserve(var):
                    self.fail('unsafe marker accepted')

if __name__ == '__main__':
    unittest.main()
