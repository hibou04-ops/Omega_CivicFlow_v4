# -*- coding: utf-8 -*-
"""
Direct validation script — bypasses HTTP auth, calls run_agent directly.
Tests all 10 required queries against the live code+DB.
"""
import sys
import json
import asyncio
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from services.chat_agent_safe_service import run_agent

TEST_QUERIES = [
    "LG생활건강",
    "LG에너지솔루션",
    "lg에너지솔루션",
    "엘지에너지솔루션",
    "현대",
    "현대차",
    "현대자동차",
    "현대글로비스",
    "현대다이모스",
    "현대차 망했나요?",
]


async def test_query(query: str, user_id: int, db) -> dict:
    try:
        result = await run_agent(
            user_message=query,
            history=[],
            user_id=user_id,
            db=db,
        )
    except Exception as e:
        return {
            "raw_query": query,
            "error": str(e),
            "pass": False,
        }

    meta = result.get("meta", {})
    payload = result.get("payload", {})
    citations = result.get("citations") or (payload.get("citations") if payload else []) or []
    reply = result.get("reply", "")
    tools_used = result.get("tools_used", [])
    intent = meta.get("intent", "")
    company_binding = meta.get("company_binding", "unresolved")
    rag_density = meta.get("rag_density", "R0")
    evidence_count = meta.get("evidence_count", 0)

    is_generic = intent in ["greeting", "identity", "unsupported", "capability_help", "product_help"]

    passed = (
        company_binding in ("authoritative", "candidate_confirmed")
        and not is_generic
    )

    return {
        "raw_query": query,
        "normalized_company": "",  # extracted from context in agent
        "intent": intent,
        "company_binding": company_binding,
        "rag_density": rag_density,
        "retrieval_attempted": any(t in tools_used for t in ["chromadb_search", "structured_facts"]),
        "evidence_count": evidence_count,
        "tools_used": tools_used,
        "citation_count": len(citations),
        "reply_preview": reply[:150].replace("\n", " "),
        "pass": passed,
    }


async def main():
    print("=" * 70)
    print("  Omega CivicFlow — Company Query Retrieval Validation (Direct)")
    print("=" * 70)

    # Get a DB session
    db = SessionLocal()
    user_id = 1  # test user

    results = []
    pass_count = 0
    fail_count = 0

    for query in TEST_QUERIES:
        print(f"\n▶ Testing: {query}")
        result = await test_query(query, user_id, db)
        results.append(result)

        status = "✓ PASS" if result["pass"] else "✗ FAIL"
        if result["pass"]:
            pass_count += 1
        else:
            fail_count += 1

        print(f"  {status}")
        print(f"  intent={result.get('intent', '?')}")
        print(f"  binding={result.get('company_binding', '?')}")
        print(f"  rag_density={result.get('rag_density', '?')}")
        print(f"  tools={result.get('tools_used', [])}")
        print(f"  evidence={result.get('evidence_count', 0)} citations={result.get('citation_count', 0)}")
        print(f"  reply: {result.get('reply_preview', '')[:100]}")
        if result.get("error"):
            print(f"  ERROR: {result['error']}")

    print("\n" + "=" * 70)
    print(f"  Results: {pass_count} PASS / {fail_count} FAIL / {len(TEST_QUERIES)} total")
    print("=" * 70)

    # Save results
    out_path = Path(__file__).parent / "validation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Results saved to: {out_path}")

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
