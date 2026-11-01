"""Run once per minute using the hosting provider's cron scheduler."""
import app,jobs

def main():
    app.init();jobs.schedule(app.connect)
    count=0
    while count<20 and jobs.run_one(app.connect):count+=1
    print(f'ESCAPE: {count} job behandlet. Ingen handler eller betalte AI-kald.')

if __name__=='__main__':main()
