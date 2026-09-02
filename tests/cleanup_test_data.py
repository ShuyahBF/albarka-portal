import asyncio, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from db import db  # noqa

async def main():
    r = await db.cron_runs.delete_many({"run_id": {"$regex": "^TEST-"}})
    print("cron_runs TEST deleted:", r.deleted_count)
    ech = await db.echeances.find({"title": {"$regex": "^TEST"}}, {"_id": 0, "id": 1}).to_list(200)
    ids = [e["id"] for e in ech]
    if ids:
        await db.notification_log.delete_many({"echeance_id": {"$in": ids}})
        d = await db.echeances.delete_many({"id": {"$in": ids}})
        print("TEST echeances deleted:", d.deleted_count)
    else:
        print("no leftover TEST echeances")
    print("remaining notification_log:", await db.notification_log.count_documents({}))
    # purge orphan logs (échéance no longer exists)
    logs = await db.notification_log.find({}, {"_id": 0, "echeance_id": 1}).to_list(1000)
    orphans = [l["echeance_id"] for l in logs
               if not await db.echeances.find_one({"id": l["echeance_id"]})]
    if orphans:
        o = await db.notification_log.delete_many({"echeance_id": {"$in": orphans}})
        print("orphan notification_log deleted:", o.deleted_count)
    print("final notification_log:", await db.notification_log.count_documents({}))
    print("remaining cron_runs:", await db.cron_runs.count_documents({}))

asyncio.run(main())
