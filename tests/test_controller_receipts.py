import json,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
from development import controller_receipts as receipts

class ReceiptsTests(unittest.TestCase):
    def test_delivery_once_and_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"issue-57-1.pr").write_text("https://github.com/hva73/invest/pull/999\n")
            receipts.record(root,"57:1","draft_pr")
            p=root/"receipts/57-1.json"
            with patch.object(receipts,"gh",side_effect=subprocess.TimeoutExpired("gh",30)):
                receipts.flush(root)
            self.assertFalse(json.loads(p.read_text())["notified"])
            with patch.object(receipts,"gh",side_effect=["","posted"]) as gh:
                receipts.flush(root)
                self.assertIn("https://github.com/hva73/invest/pull/999",gh.call_args.args[-1])
                receipts.flush(root)
                self.assertEqual(gh.call_count,2)
            self.assertTrue(json.loads(p.read_text())["notified"])
    def test_uncertain_post_deduplication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            receipts.record(root,"57:2","blocked")
            with patch.object(receipts,"gh",return_value="<!-- escape-controller:57:2 -->") as gh:
                receipts.flush(root)
                gh.assert_called_once()
            self.assertTrue(json.loads((root/"receipts/57-2.json").read_text())["notified"])
    def test_invalid_url_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"issue-57-1.pr").write_text("https://example.com/pull/1")
            with self.assertRaises(ValueError):
                receipts.record(root,"57:1","draft_pr")
