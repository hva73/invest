import unittest
from development.controller_pilot import loop, codex_command, parse_events

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

class OptimizationTests(unittest.TestCase):
    def test_verified_after_first_round(self):
        calls = []
        result = loop(lambda i,t: calls.append(i) or 0, lambda: "initial", 3, 100,
                      lambda: 0, verify=lambda: bool(calls))
        self.assertEqual((result,calls),("verified",[0]))
    def test_verified_before_any_model_call(self):
        self.assertEqual(loop(lambda *_: self.fail(),lambda:"initial",3,100,
                              lambda:0,verify=lambda:True),"verified")
    def test_resume_exact_session(self):
        sid = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(codex_command(sid)[-4:], ["resume","--json",sid,"-"])
        self.assertNotIn("resume",codex_command())
    def test_usage_counts_input_and_output_once(self):
        output = '\n'.join(['{"type":"thread.started","thread_id":"12345678-1234-1234-1234-123456789abc"}',
                            '{"type":"turn.completed","usage":{"input_tokens":120,"cached_input_tokens":100,"output_tokens":12}}'])
        self.assertEqual(parse_events(output),("12345678-1234-1234-1234-123456789abc",132,True))
    def test_missing_usage_or_session_not_invented(self):
        self.assertEqual(parse_events('not json'),(None,0,False))

if __name__ == "__main__":
    unittest.main()
