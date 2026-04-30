import json
from services.cognitive_search_safe import cognitive_search_safe
res = cognitive_search_safe("삼성전자의 작년과 전년도 영업이익은?", top_k=5)
with open("search_out.txt", "w", encoding="utf-8") as f:
    for i, r in enumerate(res):
        f.write(f"[{i}] score: {r.get('score')} | rerank: {r.get('rerank_score')} | comp: {r.get('composite_score')}\n")
        f.write(r.get('chunk')[:200].replace('\n', ' ') + "\n")
        f.write("-" * 50 + "\n")
