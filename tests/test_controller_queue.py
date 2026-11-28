import unittest
from development.controller_queue import plan

def task(i,role="mobile",status="ready",priority=1,paths=("static/mobile.js",),dependencies=()):
    return dict(issue=i,role=role,status=status,priority=priority,paths=paths,dependencies=dependencies)

class QueueTests(unittest.TestCase):
    def test_one_per_role_and_priority(self):
        self.assertEqual([t.issue for t in plan([task(2,priority=2),task(1)])],[1])
    def test_parallel_nonoverlap(self):
        self.assertEqual([t.issue for t in plan([task(1),task(2,"motor",paths=("hotwatch_engine.py",))])],[1,2])
    def test_active_path_conflict(self):
        self.assertEqual(plan([task(1,status="active",paths=("static/",)),task(2,"desktop")]),[])
    def test_dependencies(self):
        self.assertEqual(plan([task(1,status="blocked"),task(2,dependencies=(1,))]),[])
        self.assertEqual([t.issue for t in plan([task(1,status="done"),task(2,dependencies=(1,))])],[2])
    def test_unknown_dependency(self):
        self.assertEqual(plan([task(1,dependencies=(99,))]),[])
    def test_duplicate(self):
        with self.assertRaises(ValueError): plan([task(1),task(1)])
    def test_unsafe_path(self):
        with self.assertRaises(ValueError): plan([task(1,paths=("../x",))])
    def test_parallel_limit_counts_existing_active_workers(self):
        rows = [task(1,status="active"),task(2,"motor",paths=("motor.py",)),task(3,"data",paths=("feed.py",))]
        self.assertEqual([t.issue for t in plan(rows)],[2])
        self.assertEqual([t.issue for t in plan(rows,max_parallel=3)],[2,3])
        self.assertEqual(plan(rows,max_parallel=1),[])
        for bad in (0,6,True):
            with self.assertRaises(ValueError): plan(rows,max_parallel=bad)

    def test_multiple_generations_same_issue_and_review_gate(self):
        first=dict(task(57,role="release"),generation=1)
        second=dict(task(57,role="release",dependencies=("57:1",)),generation=2)
        self.assertEqual([t.key for t in plan([first,second])],[(57,1)])
        self.assertEqual(plan([dict(first,status="blocked"),second]),[])
        self.assertEqual([t.key for t in plan([dict(first,status="done"),second])],[(57,2)])

    def test_independent_approved_next_generation(self):
        first=dict(task(57,role="release"),generation=1,status="blocked")
        second=dict(task(57,role="release"),generation=2)
        self.assertEqual([t.key for t in plan([first,second])],[(57,2)])
