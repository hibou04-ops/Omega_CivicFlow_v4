# -*- coding: utf-8 -*-
"""
Validation script: tests the full company-query pipeline after fix.
Tests: embedding, metadata enrichment, routing, retrieval.
"""
import sys, os, re, json, asyncio, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

from services.company_alias_master import COMPANY_ALIASES, normalize_company_name, aliases_for_company
from services.stock_name_normalizer import PHONETIC_TO_ENGLISH

def _compact(text):
    t = str(text or "").lower()
    t = t.replace("피앤피", "pp").replace("p&p", "pp").replace("피엔피", "pp")
    for phonetic, eng in PHONETIC_TO_ENGLISH.items():
        t = t.replace(phonetic, eng.lower())
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", t)

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

# ── 1. bge-m3 Embedding Test ──
print("=" * 70)
print("[1] BGE-M3 EMBEDDING DIMENSION TEST")
print("=" * 70)

from services.vector_service import _get_embedding, _get_embedding_bge_m3
emb = _get_embedding_bge_m3("테스트 임베딩")
if emb is not None:
    print(f"  OK: bge-m3 produces {len(emb)}-dim embedding")
else:
    print("  FAIL: bge-m3 embedding returned None")

emb2 = _get_embedding("LG에너지솔루션 실적 전망")
if emb2 is not None:
    print(f"  OK: _get_embedding produces {len(emb2)}-dim embedding")
else:
    print("  FAIL: _get_embedding returned None")

# ── 2. SQL Metadata Cache Test ──
print("\n" + "=" * 70)
print("[2] SQL METADATA CACHE TEST")
print("=" * 70)

from services.cognitive_search_safe import _ensure_doc_meta_cache, _doc_meta_cache
_ensure_doc_meta_cache()
print(f"  Cache size: {len(_doc_meta_cache)} documents")

# Check test companies in cache
test_companies = ["LG생활건강", "LG에너지솔루션", "현대자동차", "현대글로비스", "현대다이모스"]
for tc in test_companies:
    tc_lower = tc.lower()
    matching = [
        (doc_id, m.get("company_name_norm", ""))
        for doc_id, m in _doc_meta_cache.items()
        if tc_lower in (m.get("company_name_norm") or "").lower()
        or tc_lower in (m.get("company_name") or "").lower()
    ]
    print(f"  {tc:20s} → {len(matching)} matching docs" + (f" (e.g. doc_id={matching[0][0]})" if matching else " NONE"))

# ── 3. Vector Search Test (with bge-m3 embeddings) ──
print("\n" + "=" * 70)
print("[3] VECTOR SEARCH TEST (bge-m3 compatible)")
print("=" * 70)

from services.cognitive_search_safe import cognitive_search_safe

for q in ["LG생활건강", "LG에너지솔루션", "현대자동차", "현대글로비스", "현대다이모스"]:
    results = cognitive_search_safe(query=q, top_k=3, company_filter=q)
    print(f"\n  Query: {q} → {len(results)} results")
    for r in results[:2]:
        print(f"    company={r.get('company','?'):20s} score={r.get('composite_score',0):.4f} file={r.get('filename','?')[:50]}")

# ── 4. Full Pipeline Test (routing + retrieval) ──
print("\n" + "=" * 70)
print("[4] FULL PIPELINE TEST")
print("=" * 70)

from database import SessionLocal

# Import routing functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))
from services.chat_agent_safe_service import (
    _base_context, _classify_top, _classify_professional,
    _effective_company_filter, _build_query_rewrites,
    run_agent,
)

db = SessionLocal()
try:
    results_table = []
    for q in TEST_QUERIES:
        context = _base_context(q, db, user_id=1)
        top_intent, params = _classify_top(q, context)
        classification = _classify_professional(q, context)
        company_filter = _effective_company_filter(context)

        # Run retrieval
        search_results = cognitive_search_safe(query=q, top_k=3, company_filter=company_filter or context.get("company", ""))

        result = {
            "raw_query": q,
            "normalized_company": context.get("company", ""),
            "binding": context.get("company_binding", "unresolved"),
            "top_route": top_intent,
            "classification_route": classification.get("route", ""),
            "classification_intent": classification.get("intent", ""),
            "company_filter": company_filter,
            "retrieval_attempted": True,
            "hit_count": len(search_results),
            "top_results": [
                f"{r.get('company','?')}|{r.get('filename','?')[:35]}|{r.get('composite_score',0):.3f}"
                for r in search_results[:3]
            ],
        }
        results_table.append(result)

        status = "PASS" if result["hit_count"] > 0 and result["normalized_company"] else "FAIL"
        print(f"\n  [{status}] {q}")
        print(f"    company={result['normalized_company']} binding={result['binding']}")
        print(f"    route={result['top_route']}/{result['classification_route']} intent={result['classification_intent']}")
        print(f"    filter={result['company_filter']} hits={result['hit_count']}")
        if search_results:
            print(f"    top: {result['top_results'][0]}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    passed = sum(1 for r in results_table if r["hit_count"] > 0 and r["normalized_company"])
    print(f"  {passed}/{len(results_table)} queries passed (company resolved + retrieval hit)")
    for r in results_table:
        status = "OK" if r["hit_count"] > 0 and r["normalized_company"] else "FAIL"
        print(f"  [{status:4s}] {r['raw_query']:20s} → {r['normalized_company']:20s} hits={r['hit_count']}")

finally:
    db.close()
