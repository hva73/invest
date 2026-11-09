"""Same offline benchmark, with 120 actual synthetic closed bars per scan."""
import sys
from datetime import timedelta
import benchmark_hotwatch_offline as benchmark
original=benchmark.tick
def tick(at,*args,**kwargs):
 sample=original(at,*args,**kwargs)
 sample.update(price_time_kind='trade',status_at=at.isoformat(),status_feed='us_status',bid_at=at.isoformat(),ask_at=at.isoformat(),quote_feed='us_quotes')
 end=at.replace(second=0,microsecond=0)
 sample['bar_history']=[{'bar_open_at':(end-timedelta(minutes=120-i)).isoformat(),'open':'100','high':'100.1','low':'99.9','close':'100','volume':'100'} for i in range(120)]
 sample['bar_evidence']={'provider_symbol':'MERC.US','market':'us','exchange':'US','timezone':'UTC','session_date':at.date().isoformat(),'open':'00:00:00','close':'23:59:59','working_days':['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],'excluded_dates':[],'schedule_received_at':at.isoformat(),'exchange_open':True,'feed':'eodhd_realtime_history'}
 return sample
benchmark.tick=tick
benchmark.run(int(sys.argv[1]),int(sys.argv[2]),.25)
