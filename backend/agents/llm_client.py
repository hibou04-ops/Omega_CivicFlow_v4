from __future__ import annotations

import json
import logging
import re
from typing import Protocol, Type, TypeVar
from pydantic import BaseModel, ValidationError
import httpx

from config import settings
from services.session_pool import OLLAMA_SEMAPHORE

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        temperature: float = 0.1,
        stage: str = "unknown",
    ) -> T:
        ...

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        ...


# ── Stage별 Safe Fallback 정의 ──
# complete_json 파싱이 완전히 실패했을 때 stage에 따라 안전한 기본값 반환
_STAGE_FALLBACKS: dict[str, dict] = {
    "router": {
        "surface_question": "",
        "latent_goal": "",
        "domain_primary": "F",
        "complexity": "simple",
        "intent": "casual_chat",
        "needs_retrieval": False,
        "needs_tools": False,
        "needs_clarification": True,
        "answer_mode": "direct",
        "entities": [],
        "time_horizon": "current",
        "risk_flags": ["contract_violation_router"],
        "retrieval_queries": [],
        "success_criteria": [],
    },
    "planner": {
        "user_goal": "",
        "subquestions": [],
        "evidence_needed": [],
        "tool_sequence": [],
        "retrieval_priority": [],
        "rejection_rules": [],
        "stop_condition": "fallback_minimal_plan",
    },
    "judge": {
        "kept": [],
        "discarded": [],
        "coverage_gaps": ["parsing_failure"],
        "enough_evidence": False,
    },
    "critic": {
        "passed": True,
        "issues": [],
        "missing_variables": [],
        "false_constraints": [],
        "causal_warnings": [],
        "precision_warnings": [],
        "revision_instructions": [],
    },
}


class OllamaLLMClient:
    def __init__(self):
        self.base_url = getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = getattr(
            settings,
            "OLLAMA_AGENT_MODEL",
            getattr(settings, "OLLAMA_MODEL", "dart-qwen-korean"),
        )

    async def _call_ollama(self, system_prompt: str, user_prompt: str, temperature: float, format_json: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "options": {
                "temperature": temperature,
                "num_predict": 2048,
                "num_gpu": 99,
                "num_batch": 512,
            },
            "keep_alive": "10m",
            "stream": False
        }
        if format_json:
            payload["format"] = "json"

        try:
            async with OLLAMA_SEMAPHORE:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.error(f"Ollama API 호출 오류: {e}")
            raise RuntimeError(f"Ollama connection error: {e}")

    def _robust_parse_json(self, response_text: str) -> dict | None:
        """JSON 파싱 — 실패 시 None 반환 (빈 dict 반환 금지)"""
        text = response_text.strip()

        # 1차: 직접 파싱
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2차: 마크다운 코드 블록 제거
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3차: JSON 구조 탐색
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        # 파싱 완전 실패
        logger.error(f"JSON parsing failed completely: {response_text[:300]}")
        return None

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        temperature: float = 0.1,
        stage: str = "unknown",
    ) -> T:
        """
        strict parse → 1회 repair retry → stage별 safe fallback.
        model_construct 절대 사용 금지.
        """
        raw_output = await self._call_ollama(system_prompt, user_prompt, temperature, format_json=True)

        # 1차: strict parse
        parsed_dict = self._robust_parse_json(raw_output)
        if parsed_dict is not None:
            try:
                return schema.model_validate(parsed_dict)
            except ValidationError as e:
                logger.warning(f"[{stage}] Schema validation failed (attempt 1): {e}")

        # 2차: 1회 repair retry
        if parsed_dict is not None:
            repair_prompt = (
                f"The following JSON has validation errors. Fix it to match the required schema exactly.\n"
                f"Required fields and types are defined by the schema.\n"
                f"Return ONLY the corrected JSON, nothing else.\n\n"
                f"Broken JSON:\n{json.dumps(parsed_dict, ensure_ascii=False)}"
            )
            try:
                repair_output = await self._call_ollama(system_prompt, repair_prompt, 0.05, format_json=True)
                repaired = self._robust_parse_json(repair_output)
                if repaired is not None:
                    try:
                        result = schema.model_validate(repaired)
                        logger.info(f"[{stage}] JSON repaired successfully on retry")
                        return result
                    except ValidationError:
                        pass
            except Exception as repair_err:
                logger.warning(f"[{stage}] Repair retry failed: {repair_err}")

        # 3차: stage별 safe fallback
        logger.error(
            f"[CONTRACT_VIOLATION] stage={stage} — JSON parsing/validation failed after retry. "
            f"Using safe fallback. Raw output preview: {(raw_output or '')[:200]}"
        )
        fallback_dict = _STAGE_FALLBACKS.get(stage, {})
        try:
            return schema.model_validate(fallback_dict)
        except ValidationError:
            # 최후의 보루: 모든 필드를 기본값으로
            return schema.model_validate({})

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        raw = await self._call_ollama(system_prompt, user_prompt, temperature, format_json=False)
        return raw
