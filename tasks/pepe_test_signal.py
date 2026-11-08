"""Enable a clearly labelled, one-hour UI test signal; never contacts Pluto."""
import argparse,sqlite3,time
from pathlib import Path


def enable(database,username,portfolio_name,now=None):
 now=time.time() if now is None else now
 with sqlite3.connect(f'file:{Path(database).resolve()}?mode=rw',uri=True) as c:
  c.execute('PRAGMA foreign_keys=ON')
  rows=c.execute("SELECT u.id,p.id FROM users u JOIN portfolios p ON p.user_id=u.id WHERE u.username=? AND u.active=1 AND p.name=? COLLATE NOCASE AND p.source='pluto' AND p.kind='portfolio' AND p.active=1",(username,portfolio_name)).fetchall()
  if len(rows)!=1:raise ValueError('Bruger og aktivt hoveddepot kunne ikke identificeres entydigt. Ingen ændring foretaget.')
  uid,pid=rows[0]
  c.execute('INSERT OR REPLACE INTO manual_test_signals(user_id,portfolio_id,ticker,amount,expires) VALUES(?,?,?,?,?)',(uid,pid,'PEPE','20',now+3600))
 return now+3600

if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Vis et tydeligt PEPE-købstestsignal i én time. Opretter ingen ordre.')
 parser.add_argument('--user',default='owner');parser.add_argument('--portfolio',default='Heine Vindum Andersen');parser.add_argument('--db',default='var/escape.db')
 args=parser.parse_args();enable(args.db,args.user,args.portfolio)
 print('PEPE-testsignal aktiveret i én time. Ingen handel eller Pluto-kald er foretaget. Opdatér forsiden.')
