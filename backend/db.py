"""MongoDB connection and small helpers."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


def serialize(doc):
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def serialize_many(docs):
    return [serialize(d) for d in docs]
