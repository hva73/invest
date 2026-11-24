"""Run once per minute using the hosting provider's cron scheduler."""
import os,sqlite3
import app,jobs

def main():
    app.init();jobs.schedule(app.connect)
    count=0
    while count<20 and jobs.run_one(app.connect):count+=1
    if os.environ.get('ESCAPE_JOB_RETENTION_ENABLED') == '1':
        try:
            result=jobs.maintain_completed_jobs(app.connect,enabled=True)
            if result is not None:print(f"ESCAPE: retention {result['rows']} afsluttede schedulerjobs; {result['result_bytes']} resultat-byte.")
        except sqlite3.Error:
            # Maintenance must never prevent the primary queue from draining.
            print('ESCAPE: schedulerretention udskudt; database utilgængelig.')
    print(f'ESCAPE: {count} job behandlet. Ingen handler eller betalte AI-kald.')

if __name__=='__main__':main()
