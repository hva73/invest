import unittest
from development.controller_pilot import loop

class LoopTest(unittest.TestCase):
    def run_case(self, snapshots, rounds=3, rc=0):
        calls = []
        it = iter(snapshots)
        result = loop(lambda i,t: calls.append(i) or rc, lambda: next(it),
                      rounds, 100, lambda: 0)
        return result, calls

    def test_immediate_continue(self):
        self.assertEqual(self.run_case(["a","b","c","d"]), ("round_limit",[0,1,2]))
    def test_no_progress(self):
        self.assertEqual(self.run_case(["a","a"]), ("no_progress",[0]))
    def test_cycle(self):
        self.assertEqual(self.run_case(["a","b","a"]), ("no_progress",[0,1]))
    def test_failure(self):
        self.assertEqual(self.run_case(["a"],rc=1), ("execution_failed",[0]))
    def test_deadline(self):
        self.assertEqual(loop(lambda *_: self.fail(),lambda:"a",3,0,lambda:0),"time_limit")

if __name__ == "__main__":
    unittest.main()
