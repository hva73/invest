import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_dryrun_feedback as feedback


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(json.dumps(data).encode())
        self.status = status


class FeedbackTest(unittest.TestCase):
    def test_posts_fixed_result_without_token(self):
        env = {'GITHUB_REPOSITORY':'hva73/invest', 'GITHUB_RUN_ID':'123', 'GITHUB_RUN_ATTEMPT':'1', 'DRYRUN_RESULT':'success', 'FEEDBACK_TOKEN':'private-token'}
        with patch.dict(os.environ, env, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = [Response([]), Response({}, 201)]
            feedback.main()
            req = factory.return_value.open.call_args.args[0]
            self.assertEqual(req.get_method(), 'POST')
            self.assertNotIn('private-token', req.data.decode())
            self.assertIn('ingen Projects-status er ændret', json.loads(req.data)['body'])

    def test_existing_bot_comment_prevents_duplicate(self):
        env = {'GITHUB_REPOSITORY':'hva73/invest', 'GITHUB_RUN_ID':'123', 'GITHUB_RUN_ATTEMPT':'1', 'DRYRUN_RESULT':'failure', 'FEEDBACK_TOKEN':'fake'}
        comments = [{'user': {'id': 41898282}, 'body': '<!-- escape-projects-dryrun-result:123:1 -->'}]
        with patch.dict(os.environ, env, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = Response(comments)
            feedback.main()
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_untrusted_comment_does_not_suppress_feedback(self):
        env = {'GITHUB_REPOSITORY':'hva73/invest', 'GITHUB_RUN_ID':'123', 'GITHUB_RUN_ATTEMPT':'1', 'DRYRUN_RESULT':'failure', 'FEEDBACK_TOKEN':'fake'}
        comments = [{'user': {'id': 1}, 'body': '<!-- escape-projects-dryrun-result:123:1 -->'}]
        with patch.dict(os.environ, env, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = [Response(comments), Response({}, 201)]
            feedback.main()
            self.assertEqual(factory.return_value.open.call_count, 2)


if __name__ == '__main__': unittest.main()
