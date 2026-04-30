# -*- coding: utf-8 -*-
import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from services.chat_agent_safe_service import _build_context, _classify_professional

def check(query: str, db):
    context = _build_context(query, [], db, user_id=1)
    intent = _classify_professional(query, context)
    return {
        "query": query,
        "company": context.get("company"),
        "binding": context.get("company_binding"),
        "intent": intent,
    }

async def main():
    db = SessionLocal()
    results = [check(q, db) for q in ["LG에너지솔루션", "현대글로비스", "현대차 망했나요?"]]
    db.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
