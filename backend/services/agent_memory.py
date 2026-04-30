from __future__ import annotations
import re
from typing import List
from agents.schemas import Message


def build_session_memory(history: List[Message], max_items: int = 6) -> str:
    """
    대화 이력을 슬롯 기반 요약으로 변환.
    최근 메시지 나열이 아니라 구조화된 세션 컨텍스트를 생성.
    """
    if not history:
        return (
            "- Current objective: 없음\n"
            "- Entities under discussion: 없음\n"
            "- User preference: 한국어, 핵심 우선\n"
            "- Open unknowns: 없음\n"
            "- Last resolved point: 없음"
        )

    recent = history[-max_items:]

    # 슬롯 추출
    entities = set()
    last_user_msg = ""
    last_assistant_msg = ""
    current_objective = ""
    metric_mentions = set()

    _METRIC_KEYWORDS = {
        "매출", "영업이익", "순이익", "부채비율", "자산", "현금흐름",
        "배당", "CAPEX", "ROE", "PER", "PBR", "실적", "전망", "주가",
    }

    # 회사명 추출 (간이)
    _COMPANY_PATTERN = re.compile(r"([가-힣A-Za-z]{2,15}(?:전자|자동차|금융|에너지|솔루션|로직스|텔레콤|SDI|화학))")

    for msg in recent:
        text = msg.content.strip()
        if msg.role == "user":
            last_user_msg = text
            # 회사명 추출
            for match in _COMPANY_PATTERN.findall(text):
                entities.add(match)
            # 지표 추출
            for kw in _METRIC_KEYWORDS:
                if kw in text:
                    metric_mentions.add(kw)
        elif msg.role == "assistant":
            last_assistant_msg = text[:150]

    # Current objective 결정
    if last_user_msg:
        current_objective = last_user_msg[:100]

    # 슬롯 조합
    slots = []
    slots.append(f"- Current objective: {current_objective or '없음'}")
    slots.append(f"- Entities: {', '.join(sorted(entities)) if entities else '없음'}")
    slots.append(f"- Metrics mentioned: {', '.join(sorted(metric_mentions)) if metric_mentions else '없음'}")
    slots.append(f"- User preference: 한국어, 핵심 우선")
    slots.append(f"- Open unknowns: 없음")

    if last_assistant_msg:
        resolved = last_assistant_msg.replace("\n", " ")[:100]
        slots.append(f"- Last resolved point: {resolved}")
    else:
        slots.append(f"- Last resolved point: 없음")

    return "\n".join(slots)
