# -*- coding: utf-8 -*-
"""
Diagnostic script: traces company-query pipeline end-to-end.
Checks: alias resolution, routing, ChromaDB retrieval, metadata matching.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
from services.company_alias_master import COMPANY_ALIASES, normalize_company_name, aliases_for_company

# ── 1. Alias Resolution Test ──
print("=" * 60)
print("[1] ALIAS RESOLUTION")
print("=" * 60)

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

for q in TEST_QUERIES:
    canonical = normalize_company_name(q)
    print(f"  {q:20s} → {canonical}")

# ── 2. Static Alias Matching (simulate _static_alias_matches) ──
print("\n" + "=" * 60)
print("[2] STATIC ALIAS MATCHING (_compact-based)")
print("=" * 60)

from services.stock_name_normalizer import PHONETIC_TO_ENGLISH

def _compact(text):
    t = str(text or "").lower()
    t = t.replace("피앤피", "pp").replace("p&p", "pp").replace("피엔피", "pp")
    for phonetic, eng in PHONETIC_TO_ENGLISH.items():
        t = t.replace(phonetic, eng.lower())
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", t)

STATIC_COMPANY_ALIASES = dict(COMPANY_ALIASES)

for q in TEST_QUERIES:
    compact_query = _compact(q)
    matches = []
    for alias, canonical in STATIC_COMPANY_ALIASES.items():
        alias_key = _compact(alias)
        if alias_key and len(alias_key) >= 2 and alias_key in compact_query:
            score = 98 + min(len(alias_key), 10) * 0.01
            matches.append((canonical, alias_key, score))
    # dedupe by canonical, keep highest score
    best = {}
    for canonical, ak, sc in matches:
        if canonical not in best or sc > best[canonical][1]:
            best[canonical] = (ak, sc)
    sorted_matches = sorted(best.items(), key=lambda x: x[1][1], reverse=True)
    top = sorted_matches[0] if sorted_matches else None
    print(f"  {q:20s} compact={compact_query:20s} → top={top[0] if top else 'NONE':20s} (matches={len(sorted_matches)})")

# ── 3. ChromaDB Collection Check ──
print("\n" + "=" * 60)
print("[3] CHROMADB COLLECTION STATUS")
print("=" * 60)

try:
    from services.vector_service import COLLECTION_NAME, _get_collection
    col = _get_collection(COLLECTION_NAME)
    if col is None:
        print(f"  ✗ Collection '{COLLECTION_NAME}' is None!")
    else:
        count = col.count()
        print(f"  ✓ Collection '{COLLECTION_NAME}' has {count} documents")

        if count > 0:
            # Sample metadata to check company_name field
            sample = col.peek(limit=10)
            print(f"\n  Sample metadata keys: {list(sample['metadatas'][0].keys()) if sample['metadatas'] else 'NONE'}")

            # Check company_name values
            companies_seen = set()
            sample_large = col.get(limit=200, include=["metadatas"])
            for meta in (sample_large.get("metadatas") or []):
                cn = meta.get("company_name", "")
                if cn:
                    companies_seen.add(cn)
            print(f"  Distinct company_name values (sample of 200): {len(companies_seen)}")
            for cn in sorted(companies_seen)[:30]:
                print(f"    - {cn}")

            # Check if test companies exist in metadata
            print(f"\n  Test company presence in metadata:")
            test_companies = ["LG생활건강", "LG에너지솔루션", "현대자동차", "현대글로비스", "현대다이모스"]
            for tc in test_companies:
                found = tc in companies_seen
                # Also check case-insensitive
                found_ci = any(tc.lower() == cn.lower() for cn in companies_seen)
                # Also check partial
                found_partial = any(tc in cn or cn in tc for cn in companies_seen)
                print(f"    {tc:20s} exact={found} ci={found_ci} partial={found_partial}")
except Exception as e:
    print(f"  ✗ ChromaDB error: {e}")

# ── 4. Cognitive Search Direct Test ──
print("\n" + "=" * 60)
print("[4] COGNITIVE SEARCH DIRECT TEST")
print("=" * 60)

try:
    from services.cognitive_search_safe import cognitive_search_safe, _normalize_company_for_search

    for q in ["LG생활건강", "LG에너지솔루션", "현대자동차", "현대글로비스"]:
        variants = _normalize_company_for_search(q)
        print(f"\n  Query: {q}")
        print(f"  Variants: {variants[:5]}")

        results = cognitive_search_safe(query=q, top_k=3, company_filter=q)
        print(f"  Results: {len(results)}")
        for r in results[:2]:
            print(f"    - company={r.get('company','?')} file={r.get('filename','?')[:40]} score={r.get('composite_score',0):.3f}")

        if not results:
            # Try without company filter
            results_no_filter = cognitive_search_safe(query=q, top_k=3, company_filter="")
            print(f"  Results (no company filter): {len(results_no_filter)}")
            for r in results_no_filter[:2]:
                print(f"    - company={r.get('company','?')} file={r.get('filename','?')[:40]} score={r.get('composite_score',0):.3f}")
except Exception as e:
    print(f"  ✗ Search error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
