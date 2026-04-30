# -*- coding: utf-8 -*-
"""
Validation script for company-query retrieval fix.
Tests all 10 required queries against the live backend API.
"""
import sys
import json
import httpx

BASE_URL = "http://127.0.0.1:8765/panel/chat"

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


def test_query(query: str, client: httpx.Client) -> dict:
    """Send a chat query and extract diagnostic info."""
    try:
        resp = client.post(
            BASE_URL,
            json={"message": query, "history": []},
            timeout=30.0,
        )
        data = resp.json()
    except Exception as e:
        return {
            "raw_query": query,
            "error": str(e),
            "pass": False,
        }

    meta = data.get("meta", {})
    payload = data.get("payload", {})
    citations = data.get("citations") or payload.get("citations", [])
    reply = data.get("reply", "")

    # Determine if retrieval was attempted
    tools_used = data.get("tools_used", [])
    retrieval_attempted = any(
        t in tools_used
        for t in ["chromadb_search", "structured_facts", "search_my_documents"]
    )
    # Also check if route went to a knowledge path
    intent = meta.get("intent", "")
    rag_density = meta.get("rag_density", "R0")

    # A query passes if:
    # 1. company binding is authoritative or candidate_confirmed
    # 2. OR the intent is a retrieval-type intent (not "unsupported")
    # 3. AND the reply isn't just the generic unsupported/greeting text
    company_binding = meta.get("company_binding", "unresolved")
    is_retrieval_intent = intent in [
        "company_summary", "document_qa", "qa", "stock_outlook",
        "trend", "ranking_compare", "dart_search",
    ]
    is_generic = intent in ["greeting", "identity", "unsupported", "capability_help", "product_help"]
    is_no_data = "자료 부족" == reply.strip()

    passed = (
        company_binding in ("authoritative", "candidate_confirmed")
        and not is_generic
    )

    return {
        "raw_query": query,
        "normalized_company": meta.get("company_binding_detail", ""),
        "intent": intent,
        "company_binding": company_binding,
        "rag_density": rag_density,
        "retrieval_attempted": retrieval_attempted,
        "evidence_count": meta.get("evidence_count", 0),
        "tools_used": tools_used,
        "citation_count": len(citations),
        "reply_preview": reply[:120],
        "pass": passed,
    }


def main():
    print("=" * 70)
    print("  Omega CivicFlow — Company Query Retrieval Validation")
    print("=" * 70)

    client = httpx.Client(timeout=30.0)
    results = []
    pass_count = 0
    fail_count = 0

    for query in TEST_QUERIES:
        print(f"\n▶ Testing: {query}")
        result = test_query(query, client)
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
        print(f"  evidence_count={result.get('evidence_count', 0)}")
        print(f"  reply: {result.get('reply_preview', '')[:80]}")
        if result.get("error"):
            print(f"  ERROR: {result['error']}")

    print("\n" + "=" * 70)
    print(f"  Results: {pass_count} PASS / {fail_count} FAIL / {len(TEST_QUERIES)} total")
    print("=" * 70)

    # Save results
    out_path = "tools/validation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Detailed results saved to: {out_path}")


if __name__ == "__main__":
    main()
