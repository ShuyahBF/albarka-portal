import asyncio, os, sys
sys.path.insert(0, "/app/backend")
os.chdir("/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from db import db  # noqa

async def main():
    print("cron_runs:", await db.cron_runs.count_documents({}))
    for r in await db.cron_runs.find({}, {"_id": 0}).sort("received_at", -1).to_list(3):
        print("  ", r)
    print("notification_log:", await db.notification_log.count_documents({}))
    for r in await db.notification_log.find({}, {"_id": 0}).sort("created_at", -1).to_list(5):
        print("  ", r)
    # how many echeances match J-7 / J-1 windows
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    for d in (7, 1):
        t = (today + timedelta(days=d)).isoformat()
        n = await db.echeances.count_documents({"due_date": {"$regex": f"^{t}"},
              "status": {"$in": ["a_venir", "en_cours", "en_retard"]}})
        print(f"J-{d} ({t}) matching echeances:", n)

asyncio.run(main())
