# -*- coding: utf-8 -*-
import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from services.chat_agent_safe_service import _build_context, _classify_professional, _is_company_only_query, _clean_text

def check(query: str, db):
    context = _build_context(query, [], db)
    
    # replicate variables used in _classify_professional
    message = query
    lowered = message.lower()
    stripped = _clean_text(message, 500)
    focus_key = "".join(c for c in (context.get("focus_query") or "") if c.isalnum()).lower() # approximation of _compact
    has_company = bool(context.get("company"))
    has_metric = bool(context.get("metric"))
    company_only = _is_company_only_query(message, context)
    
    intent = _classify_professional(query, context)
    
    return {
        "query": query,
        "internal_vars": {
            "has_company": has_company,
            "has_metric": has_metric,
            "company_only": company_only,
            "focus_key": focus_key,
        },
        "intent": intent,
    }

async def main():
    db = SessionLocal()
    results = []
    for q in ["LG에너지솔루션", "엘지에너지솔루션", "현대글로비스", "현대차 망했나요?"]:
        results.append(check(q, db))
    db.close()
    
    with open('tools/debug_trace.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
