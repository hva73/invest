import unittest
from development.controller_pilot import loop, codex_command, parse_events, usage_breakdown, context_exhausted, execution_prompt, MODEL_POLICY, model_args

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
    def test_analysis_only_turn_can_switch_approach(self):
        calls=[]; stalls=[]
        snapshots=iter(["a","a","b","c"])
        result=loop(lambda i,t:calls.append(i) or 0,lambda:next(snapshots),3,100,lambda:0,
                    verify=lambda:len(calls)==3,on_stall=lambda i:stalls.append(i) or True)
        self.assertEqual((result,calls,stalls),("verified",[0,1,2],[0]))
    def test_stall_retries_remain_bounded(self):
        calls=[]
        self.assertEqual(loop(lambda i,t:calls.append(i) or 0,lambda:"a",5,100,lambda:0,
                              on_stall=lambda i:i<2),"no_progress")
        self.assertEqual(calls,[0,1,2])
    def test_execution_prompt_retains_scope_on_fresh_approach(self):
        p=execution_prompt(114,"motor","approved task",["trade_service.py"],2,"fresh")
        for phrase in ("different implementation method","approved task","trade_service.py","actual passing targeted tests","No production access"):
            self.assertIn(phrase,p)

    def test_failure(self):
        self.assertEqual(self.run_case(["a"],rc=1), ("execution_failed",[0]))
    def test_deadline(self):
        self.assertEqual(loop(lambda *_: self.fail(),lambda:"a",3,0,lambda:0),"time_limit")

class OptimizationTests(unittest.TestCase):
    def test_token_ceiling_preserves_successful_round(self):
        calls = []
        result = loop(lambda i,t: calls.append(i) or 0, lambda: "initial", 3, 100,
                      lambda: 0, exhausted=lambda: bool(calls))
        self.assertEqual((result,calls),("token_limit",[0]))

    def test_verified_after_first_round(self):
        calls = []
        result = loop(lambda i,t: calls.append(i) or 0, lambda: "initial", 3, 100,
                      lambda: 0, verify=lambda: bool(calls))
        self.assertEqual((result,calls),("verified",[0]))
    def test_verified_before_any_model_call(self):
        self.assertEqual(loop(lambda *_: self.fail(),lambda:"initial",3,100,
                              lambda:0,verify=lambda:True),"verified")
    def test_explicit_model_policy_for_every_role(self):
        expected={"release":("sol","high"),"mobile":("sol","high"),
                  "motor":("astra","high"),"data":("astra","high"),
                  "desktop":("sol","high"),"coordinator":("sol","medium")}
        self.assertEqual(set(MODEL_POLICY),set(expected))
        for role,(model,effort) in expected.items():
            args=model_args(role)
            self.assertEqual(args,["--model","gpt-6.2-"+model,"-c",'model_reasoning_effort="'+effort+'"'])
            if role!="coordinator":
                self.assertEqual(codex_command(role=role)[6:10],args)
                self.assertEqual(codex_command("12345678-1234-1234-1234-123456789abc",role)[6:10],args)

    def test_resume_exact_session(self):
        sid = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(codex_command(sid)[-4:], ["resume","--json",sid,"-"])
        self.assertNotIn("resume",codex_command())
    def test_usage_counts_input_and_output_once(self):
        output = '\n'.join(['{"type":"thread.started","thread_id":"12345678-1234-1234-1234-123456789abc"}',
                            '{"type":"turn.completed","usage":{"input_tokens":120,"cached_input_tokens":100,"output_tokens":12}}'])
        self.assertEqual(parse_events(output),("12345678-1234-1234-1234-123456789abc",132,True))
    def test_cache_metrics_distinguish_gross_and_uncached(self):
        raw = '{"type":"turn.completed","usage":{"input_tokens":230000,"cached_input_tokens":220000,"output_tokens":4068}}'
        self.assertEqual(usage_breakdown(raw),dict(input=230000,cached=220000,output=4068,gross=234068,uncached_plus_output=14068))

    def test_missing_cache_is_unknown(self):
        raw = '{"type":"turn.completed","usage":{"input_tokens":120,"output_tokens":12}}'
        self.assertIsNone(usage_breakdown(raw)["uncached_plus_output"])
        self.assertIsNone(usage_breakdown("invalid")["uncached_plus_output"])

    def test_context_exhaustion_is_explicit_and_not_generic_error(self):
        self.assertTrue(context_exhausted('{"type":"turn.failed","error":{"message":"context_length_exceeded"}}'))
        self.assertFalse(context_exhausted('{"type":"turn.failed","error":{"message":"usage limit reached"}}'))
        self.assertFalse(context_exhausted('{"type":"item.completed","message":"context window exceeded"}'))

    def test_missing_usage_or_session_not_invented(self):
        self.assertEqual(parse_events('not json'),(None,0,False))

if __name__ == "__main__":
    unittest.main()
