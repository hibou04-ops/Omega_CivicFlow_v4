# -*- coding: utf-8 -*-
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from services.chat_agent_safe_service import _build_context, _classify_professional, _resolve_companies, _static_alias_matches

def check(query: str, db):
    print(f"\n--- {query} ---")
    
    # 1. Alias Matches
    static = _static_alias_matches(query)
    print(f"Static: {[(m.get('canonical'), m.get('score')) for m in static]}")
    
    # 2. Resolve Companies
    resolved = _resolve_companies(query, db)
    print(f"Resolved: company='{resolved.get('company')}' binding='{resolved.get('binding')}' companies={resolved.get('companies')}")
    
    # 3. Context
    context = _build_context(query, [], db)
    print(f"Context: company='{context.get('company')}' focus='{context.get('focus_query')}'")
    
    # 4. Intent
    intent = _classify_professional(query, context)
    print(f"Intent: {intent}")

async def main():
    db = SessionLocal()
    for q in ["LG에너지솔루션", "엘지에너지솔루션", "현대글로비스", "현대차 망했나요?"]:
        check(q, db)
    db.close()

if __name__ == "__main__":
    asyncio.run(main())
