import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_storage_cleanup as cleanup


class Scope(unittest.TestCase):
    def test_only_old_known_staging_entries(self):
        row = {'file': 'old.zip', 'type': 'file', 'mode': 33188, 'mtime': 1794309918}
        self.assertEqual(cleanup.checked_path(row), cleanup.ROOT + '/old.zip')
        for changes in ({'file': '..'}, {'file': '../var'}, {'file': '/home/nordicr4/escape_app'},
                        {'file': '.escape-release-19922l6v'}, {'mode': 41471}, {'mtime': 1999999999}, {'type': 'link'}):
            with self.assertRaises(ValueError): cleanup.checked_path({**row, **changes})

    def test_changed_metadata_cannot_match_plan(self):
        row = {'file': 'old.zip', 'type': 'file', 'mode': 33188, 'mtime': 1794309918, 'size': '42'}
        self.assertTrue(cleanup.matches(row, row))
        for key in row:
            self.assertFalse(cleanup.matches(row, {**row, key: 'changed'}))


if __name__ == '__main__': unittest.main()
