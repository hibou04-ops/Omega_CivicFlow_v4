# -*- coding: utf-8 -*-
import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from services.chat_agent_safe_service import _build_context, _classify_professional, _is_company_only_query, _clean_text, _remove_companies, _company_terms_for_context

def check(query: str, db):
    context = _build_context(query, [], db)
    
    terms = _company_terms_for_context(context)
    stripped = _clean_text(query, 500)
    residual = _remove_companies(stripped, terms)
    
    company_only = _is_company_only_query(query, context)
    intent = _classify_professional(query, context)
    
    return {
        "query": query,
        "internal_vars": {
            "resolved_company": context.get("company"),
            "terms": terms,
            "stripped": stripped,
            "residual": residual,
            "company_only": company_only,
        },
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
