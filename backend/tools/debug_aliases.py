# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, ".")

from services.company_alias_master import COMPANY_ALIASES, normalize_company_name
from services.chat_agent_safe_service import _static_alias_matches, _dart_matches, _compact

test_keys = [
    "lg에너지솔루션", "엘지에너지솔루션", "현대글로비스",
    "현대차", "현대", "lg생활건강", "현대다이모스",
]

print("=== ALIAS TABLE CHECK ===")
for key in test_keys:
    result = COMPANY_ALIASES.get(key, "NOT FOUND")
    print(f"  {key} -> {result}")

print("\n=== normalize_company_name ===")
for key in test_keys:
    result = normalize_company_name(key)
    print(f"  {key} -> {result}")

print("\n=== _static_alias_matches ===")
test_queries = [
    "LG에너지솔루션", "엘지에너지솔루션", "현대글로비스",
    "현대차 망했나요?", "현대", "LG생활건강",
]
for q in test_queries:
    matches = _static_alias_matches(q)
    canonical_list = [m.get("canonical") for m in matches]
    dart_list = [m.get("canonical") for m in _dart_matches(q)[:2]]
    print(f"  query={q}")
    print(f"    static={canonical_list}")
    print(f"    dart={dart_list}")
    print(f"    compact={_compact(q)}")
