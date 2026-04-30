from __future__ import annotations

import logging
import re
from typing import List

from agents.llm_client import LLMClient
from agents.prompts import (
    CORE_SYSTEM_PROMPT,
    build_router_prompt,
    build_planner_prompt,
    build_judge_prompt,
    build_synthesizer_prompt,
    build_critic_prompt,
    build_reviser_prompt,
    build_direct_answer_prompt,
)
from agents.schemas import (
    ChatResponse,
    Citation,
    CriticResult,
    JudgeResult,
    Message,
    PlanResult,
    ResponseMeta,
    RetrievedChunk,
    RouterResult,
)
from services.agent_memory import build_session_memory
from services.agent_retrieval import Retriever

logger = logging.getLogger(__name__)


def _has_chinese(text: str, threshold: float = 0.02) -> bool:
    """중국어 문자 비율이 threshold를 초과하는지 확인"""
    if not text:
        return False
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len(text.replace(" ", ""))
    if total == 0:
        return False
    return (cjk_count / total) > threshold


class AgentOrchestrator:
    def __init__(self, llm: LLMClient, retriever: Retriever) -> None:
        self.llm = llm
        self.retriever = retriever

    def _sanitize_answer(self, ans: str) -> str:
        """응답에서 JSON 잔해를 제거"""
        import json

        ans_clean = re.sub(r"```(?:json)?(.*?)```", r"\1", ans, flags=re.DOTALL).strip()

        start = ans_clean.find("{")
        end = ans_clean.rfind("}")

        if start != -1 and end != -1 and end > start:
            try:
                candidate = ans_clean[start:end+1]
                d = json.loads(candidate)
                if isinstance(d, dict) and d:
                    # JSON dict에서 텍스트 값만 추출
                    extracted = "\n".join([str(v) for v in d.values() if str(v).strip()])
                    if extracted and len(extracted) > 10:
                        return extracted
            except Exception:
                pass

            # JSON이 아닌 텍스트 부분만 추출
            before = ans_clean[:start].strip()
            after = ans_clean[end+1:].strip()
            if before and len(before) > 10:
                return before
            if after and len(after) > 10:
                return after

        return ans.strip()

    def _deterministic_prefilter(
        self, chunks: List[RetrievedChunk], route: RouterResult
    ) -> List[RetrievedChunk]:
        """Judge 전 deterministic prefilter — 명확한 불량 chunk 제거"""
        filtered = []
        entities_lower = [e.lower() for e in route.entities] if route.entities else []

        for chunk in chunks:
            text = chunk.text or ""

            # 1. 텍스트 손상/인코딩 오염 — 중국어 비율 > 10%
            if _has_chinese(text, threshold=0.10):
                logger.debug("[Prefilter] Dropped chunk %s: Chinese corruption", chunk.chunk_id)
                continue

            # 2. 빈 텍스트
            if len(text.strip()) < 30:
                continue

            # 3. Entity mismatch — route에 entities가 있고 chunk에 해당 기업명 없으면 감점
            if entities_lower:
                chunk_lower = text[:2000].lower()
                meta_company = (chunk.metadata.get("company", "") or "").lower()
                entity_found = any(
                    e in chunk_lower or e in meta_company
                    for e in entities_lower
                )
                if not entity_found:
                    logger.debug("[Prefilter] Dropped chunk %s: Entity mismatch", chunk.chunk_id)
                    continue

            filtered.append(chunk)

        logger.info(
            "[Prefilter] %d/%d chunks passed (entities=%s, intent=%s)",
            len(filtered), len(chunks), entities_lower, route.intent,
        )
        return filtered

    async def run(self, user_message: str, history: List[Message]) -> ChatResponse:
        session_memory = build_session_memory(history)
        logger.info(f"[Orchestrator] Starting session for message: {user_message[:50]}...")

        # Telemetry tracking
        telemetry = {
            "intent": "",
            "needs_retrieval": False,
            "retrieval_queries": [],
            "raw_chunk_count": 0,
            "prefiltered_count": 0,
            "kept_count": 0,
            "coverage_gaps": [],
            "final_fallback_reason": "",
        }

        # 1. Router
        route = await self.llm.complete_json(
            system_prompt=CORE_SYSTEM_PROMPT,
            user_prompt=build_router_prompt(user_message, session_memory),
            schema=RouterResult,
            temperature=0.1,
            stage="router",
        )
        telemetry["intent"] = route.intent
        telemetry["needs_retrieval"] = route.needs_retrieval
        logger.info(f"[Orchestrator] Route intent: {route.intent}, needs_retrieval: {route.needs_retrieval}")

        # Direct response for non-retrieval intents
        if not route.needs_retrieval and not route.needs_tools:
            answer = await self.llm.complete_text(
                system_prompt=CORE_SYSTEM_PROMPT,
                user_prompt=build_direct_answer_prompt(user_message, session_memory, route),
                temperature=0.3,
            )
            telemetry["final_fallback_reason"] = "direct_answer"
            self._log_telemetry(telemetry)

            return ChatResponse(
                answer=self._sanitize_answer(answer),
                route=route,
                used_retrieval=False,
                evidence_count=0,
                meta=ResponseMeta(
                    intent=route.intent,
                    confidence="CONSENSUS",
                    evidence_count=0,
                    fallback_reason="direct_answer",
                ),
            )

        # 2. Planner
        plan = await self.llm.complete_json(
            system_prompt=CORE_SYSTEM_PROMPT,
            user_prompt=build_planner_prompt(
                user_message=user_message,
                session_memory=session_memory,
                route=route,
            ),
            schema=PlanResult,
            temperature=0.2,
            stage="planner",
        )
        logger.info(f"[Orchestrator] Planner: evidence needed={len(plan.evidence_needed)}")

        # 3. Retriever — 독립 쿼리 fan-out
        queries = route.retrieval_queries or plan.retrieval_priority
        if not queries:
            queries = [user_message]
        telemetry["retrieval_queries"] = queries

        # 회사 필터 추출
        company_filter = route.entities[0] if route.entities else ""

        raw_chunks = await self.retriever.search(
            queries=queries,
            top_k=12,
            company_filter=company_filter,
            intent=route.intent,
            time_horizon=route.time_horizon,
            prefer_recent=(route.time_horizon in ("current", "forward")),
        )
        telemetry["raw_chunk_count"] = len(raw_chunks)
        logger.info(f"[Orchestrator] Retrieved {len(raw_chunks)} raw chunks.")

        if not raw_chunks:
            # 검색 결과 없음 → 자료 부족 응답
            telemetry["final_fallback_reason"] = "no_retrieval_results"
            self._log_telemetry(telemetry)

            return ChatResponse(
                answer="검색된 자료가 없습니다. 다른 키워드나 기업명으로 다시 질문해 주세요.",
                route=route,
                used_retrieval=True,
                evidence_count=0,
                meta=ResponseMeta(
                    intent=route.intent,
                    confidence="EXPLORATION",
                    evidence_count=0,
                    fallback_reason="no_retrieval_results",
                ),
            )

        # 3.5 Deterministic Prefilter
        prefiltered = self._deterministic_prefilter(raw_chunks, route)
        telemetry["prefiltered_count"] = len(prefiltered)

        if not prefiltered:
            telemetry["final_fallback_reason"] = "all_prefiltered_out"
            self._log_telemetry(telemetry)

            return ChatResponse(
                answer="검색된 자료 중 질문과 관련된 정보를 찾지 못했습니다. 질문을 더 구체적으로 해주세요.",
                route=route,
                used_retrieval=True,
                evidence_count=0,
                meta=ResponseMeta(
                    intent=route.intent,
                    confidence="EXPLORATION",
                    evidence_count=0,
                    fallback_reason="all_prefiltered_out",
                ),
            )

        # 4. Judge
        judge = await self.llm.complete_json(
            system_prompt=CORE_SYSTEM_PROMPT,
            user_prompt=build_judge_prompt(
                user_message=user_message,
                session_memory=session_memory,
                route=route,
                plan=plan,
                chunks=prefiltered,
            ),
            schema=JudgeResult,
            temperature=0.1,
            stage="judge",
        )
        kept_ids = {item.chunk_id for item in judge.kept}
        filtered_chunks = [c for c in prefiltered if c.chunk_id in kept_ids]
        telemetry["kept_count"] = len(filtered_chunks)
        telemetry["coverage_gaps"] = judge.coverage_gaps

        # ★ Judge가 전부 버렸을 때 top-2 재주입 제거 → 자료 부족 경로
        if not filtered_chunks:
            if not judge.enough_evidence:
                telemetry["final_fallback_reason"] = "judge_insufficient_evidence"
                self._log_telemetry(telemetry)

                gaps_text = ", ".join(judge.coverage_gaps) if judge.coverage_gaps else "관련 증거 부족"
                return ChatResponse(
                    answer=f"자료 부족: 검색된 데이터 중 질문에 적합한 근거를 찾지 못했습니다. (부족 항목: {gaps_text})",
                    route=route,
                    used_retrieval=True,
                    evidence_count=0,
                    meta=ResponseMeta(
                        intent=route.intent,
                        confidence="EXPLORATION",
                        evidence_count=0,
                        coverage_gaps=judge.coverage_gaps,
                        fallback_reason="judge_insufficient_evidence",
                    ),
                )
            else:
                # Judge는 enough_evidence=True인데 kept가 없는 이상 케이스
                # 원본 prefiltered 중 상위 3개를 사용하되 로그 남김
                logger.warning("[Orchestrator] Judge kept=0 but enough_evidence=True — using top 3 prefiltered")
                filtered_chunks = prefiltered[:3]
                telemetry["final_fallback_reason"] = "judge_paradox_fallback"

        logger.info(f"[Orchestrator] {len(filtered_chunks)} chunks kept after judging.")

        # 5. Synthesizer
        draft = await self.llm.complete_text(
            system_prompt=CORE_SYSTEM_PROMPT,
            user_prompt=build_synthesizer_prompt(
                user_message=user_message,
                session_memory=session_memory,
                route=route,
                plan=plan,
                chunks=filtered_chunks,
            ),
            temperature=0.35,
        )

        # 6. Critic
        critic = await self.llm.complete_json(
            system_prompt=CORE_SYSTEM_PROMPT,
            user_prompt=build_critic_prompt(
                user_message=user_message,
                route=route,
                plan=plan,
                chunks=filtered_chunks,
                draft_answer=draft,
            ),
            schema=CriticResult,
            temperature=0.1,
            stage="critic",
        )

        # 7. Reviser
        if critic.passed:
            logger.info("[Orchestrator] Critic passed cleanly.")
            final_answer = draft
        else:
            logger.info(f"[Orchestrator] Critic failed. Issues: {critic.issues}. Revising...")
            final_answer = await self.llm.complete_text(
                system_prompt=CORE_SYSTEM_PROMPT,
                user_prompt=build_reviser_prompt(
                    draft_answer=draft,
                    critic=critic,
                ),
                temperature=0.2,
            )

        # Citations 생성
        citations = [
            Citation(
                chunk_id=c.chunk_id,
                source=c.metadata.get("filename", ""),
                text_snippet=(c.text or "")[:200],
            )
            for c in filtered_chunks
        ]

        telemetry["final_fallback_reason"] = telemetry.get("final_fallback_reason") or "normal"
        self._log_telemetry(telemetry)

        return ChatResponse(
            answer=self._sanitize_answer(final_answer),
            route=route,
            used_retrieval=True,
            evidence_count=len(filtered_chunks),
            citations=citations,
            meta=ResponseMeta(
                intent=route.intent,
                confidence=route.complexity.upper() if route.complexity else "INFERENCE",
                evidence_count=len(filtered_chunks),
                coverage_gaps=judge.coverage_gaps,
                fallback_reason=telemetry.get("final_fallback_reason", ""),
            ),
        )

    def _log_telemetry(self, telemetry: dict):
        """각 턴의 주요 지표를 구조화 로그로 출력"""
        logger.info(
            "[TELEMETRY] intent=%s needs_retrieval=%s queries=%d raw=%d prefiltered=%d kept=%d gaps=%s fallback=%s",
            telemetry.get("intent"),
            telemetry.get("needs_retrieval"),
            len(telemetry.get("retrieval_queries", [])),
            telemetry.get("raw_chunk_count", 0),
            telemetry.get("prefiltered_count", 0),
            telemetry.get("kept_count", 0),
            telemetry.get("coverage_gaps", []),
            telemetry.get("final_fallback_reason", ""),
        )
