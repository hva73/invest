import tempfile,unittest
from datetime import datetime,timezone
import app,jobs,news
# Synthetic parser fixtures, not application news.
FEED=b'<rss><channel><item><title>Test release</title><link>https://www.ecb.europa.eu/press/test.html</link><pubDate>Fri, 02 Jan 2026 12:00:00 GMT</pubDate><description>&lt;p&gt;Test summary&lt;/p&gt;</description></item></channel></rss>'
class News(unittest.TestCase):
 def test_source_and_dates(self):
  items=news.parse(FEED,datetime(2026,1,3,tzinfo=timezone.utc));self.assertEqual(items[0]['summary'],'Test summary');self.assertEqual(items[0]['published'],'2026-01-02T12:00:00+00:00')
  for data in [FEED.replace(b'https://www.ecb.europa.eu',b'https://untrusted.example'),FEED.replace(b'2026',b'2099'),b'<!DOCTYPE x>'+FEED]:
   with self.assertRaises(ValueError):news.parse(data,datetime(2026,1,3,tzinfo=timezone.utc))
 def test_repeated_feed_deduplicates(self):
  previous=app.DB
  with tempfile.TemporaryDirectory() as d:
   try:
    app.DB=d+'/news.db';app.init();app.create_user('a-test-password-long')
    for key in ['first','second']:
     with app.connect() as c:jobs.enqueue(c,'news',1,key,0)
     jobs.run_one(app.connect,lambda:news.parse(FEED,datetime(2026,1,3,tzinfo=timezone.utc)),at=0)
    self.assertEqual(len(jobs.status(app.connect,1)['news']),1)
   finally:app.DB=previous
