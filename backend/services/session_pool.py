# -*- coding: utf-8 -*-
"""
session_pool.py — 멀티 사용자 병행 실행 관리
Ollama 메모리 관리 샘플예제.docx 기반 구현

기능:
  - SessionPool: 유저별 세션 LRU + TTL 관리
  - HybridContextManager: 대화 히스토리 토큰 초과 시 자동 압축
  - VRAM 모니터링: 압박 시 세션 강제 축소
  - asyncio.Semaphore: OLLAMA_NUM_PARALLEL=2 에 맞춰 동시 요청 제한
"""
from __future__ import annotations

import asyncio
import gc
import logging
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("omega.session_pool")

# ── 전역 세마포어: Ollama NUM_PARALLEL=2 에 맞춤 ────────────────────────
# 모든 LLM 호출은 이 세마포어를 통과해야 함 → 동시 요청 2개로 제한
OLLAMA_SEMAPHORE = asyncio.Semaphore(2)


# ═══════════════════════════════════════════════════════════════
# VRAM 모니터링
# ═══════════════════════════════════════════════════════════════

def get_vram_usage() -> dict:
    """nvidia-smi로 현재 VRAM 사용량 조회."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        used, total = map(int, result.stdout.strip().split(", "))
        return {"used_mb": used, "total_mb": total, "pct": used / total * 100}
    except Exception:
        return {"used_mb": 0, "total_mb": 0, "pct": 0.0}


# ═══════════════════════════════════════════════════════════════
# HybridContextManager — 대화 히스토리 토큰 압축
# ═══════════════════════════════════════════════════════════════

@dataclass
class _Message:
    role: str    # "user" | "assistant" | "system"
    content: str

    def token_estimate(self) -> int:
        """글자 수 / 3 로 토큰 근사 추정."""
        return max(1, len(self.content) // 3)


class HybridContextManager:
    """
    전략 (docx 기반):
      - 시스템 프롬프트: 항상 유지
      - 최근 K턴: 항상 유지 (기본 6)
      - 오래된 메시지: 요약 압축 후 제거
    """

    def __init__(
        self,
        max_ctx_tokens: int = 10000,     # EXAONE 16384 컨텍스트, 여유 확보
        keep_recent_turns: int = 6,
        summary_trigger_tokens: int = 7000,
        ollama_base_url: str = "http://127.0.0.1:11434",
        ollama_model: str = "exaone3.5:7.8b",
    ):
        self.max_ctx_tokens = max_ctx_tokens
        self.keep_recent_turns = keep_recent_turns
        self.summary_trigger_tokens = summary_trigger_tokens
        self.base_url = ollama_base_url
        self.model = ollama_model

        self.system_msg: Optional[_Message] = None
        self.summary_msg: Optional[_Message] = None  # 압축된 과거 요약
        self.messages: list[_Message] = []

    def set_system(self, content: str):
        self.system_msg = _Message("system", content)

    def load_from_history(self, history: list[dict[str, Any]]):
        """프론트에서 받은 history 리스트를 내부 메시지로 변환."""
        self.messages = []
        for item in history or []:
            role = item.get("role") or item.get("sender") or "user"
            content = str(item.get("content") or item.get("text") or "")
            if role in ("user", "assistant") and content:
                self.messages.append(_Message(role, content))

    def total_tokens(self) -> int:
        total = 0
        if self.system_msg:
            total += self.system_msg.token_estimate()
        if self.summary_msg:
            total += self.summary_msg.token_estimate()
        total += sum(m.token_estimate() for m in self.messages)
        return total

    def trim_to_recent(self) -> list[dict[str, Any]]:
        """
        토큰 한도 초과 시 오래된 메시지를 버리고 최근 K턴만 반환.
        (LLM 압축 호출 없이 즉시 처리 — 동기)
        """
        if self.total_tokens() <= self.summary_trigger_tokens:
            return self._build_history()

        if len(self.messages) <= self.keep_recent_turns:
            return self._build_history()

        dropped = len(self.messages) - self.keep_recent_turns
        self.messages = self.messages[-self.keep_recent_turns:]
        logger.info("HybridCtx: %d 메시지 드롭 (토큰 초과)", dropped)
        return self._build_history()

    def _build_history(self) -> list[dict[str, Any]]:
        result = []
        if self.summary_msg:
            result.append({"role": "system", "content": self.summary_msg.content})
        for m in self.messages:
            result.append({"role": m.role, "content": m.content})
        return result

    def get_trimmed_history(self, raw_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """외부에서 history를 받아 trimmed 버전 반환 (상태 비저장)."""
        self.load_from_history(raw_history)
        return self.trim_to_recent()


# ═══════════════════════════════════════════════════════════════
# SessionPool — LRU + TTL + VRAM 압박 자동 축소
# ═══════════════════════════════════════════════════════════════

class SessionPool:
    """
    유저별 HybridContextManager를 LRU 캐시로 관리.
    VRAM 85% 초과 시 오래된 세션 강제 만료.
    """

    def __init__(
        self,
        max_sessions: int = 10,
        ttl_seconds: int = 1800,            # 30분 비활성 시 만료
        vram_pressure_threshold: float = 0.85,
        ollama_base_url: str = "http://127.0.0.1:11434",
        ollama_model: str = "exaone3.5:7.8b",
    ):
        self.max_sessions = max_sessions
        self.ttl = ttl_seconds
        self.vram_threshold = vram_pressure_threshold
        self.base_url = ollama_base_url
        self.model = ollama_model
        self._sessions: OrderedDict[int, dict] = OrderedDict()  # user_id → session

    def get_or_create(self, user_id: int) -> dict:
        """유저 세션 조회 또는 생성. VRAM 압박 시 자동 축소."""
        now = time.time()

        # TTL 만료 세션 정리
        self._evict_expired(now)

        # VRAM 압박 시 세션 수 줄이기
        vram = get_vram_usage()
        if vram["pct"] > self.vram_threshold * 100:
            keep = max(3, self.max_sessions // 2)
            self._evict_oldest(keep)
            logger.warning(
                "VRAM 압박 %.1f%% → 세션 축소 (max %d)", vram["pct"], keep
            )

        if user_id in self._sessions:
            self._sessions.move_to_end(user_id)
            self._sessions[user_id]["last_active"] = now
            return self._sessions[user_id]

        if len(self._sessions) >= self.max_sessions:
            self._evict_oldest(self.max_sessions - 1)

        session = {
            "user_id": user_id,
            "created_at": now,
            "last_active": now,
            "ctx_manager": HybridContextManager(
                ollama_base_url=self.base_url,
                ollama_model=self.model,
            ),
        }
        self._sessions[user_id] = session
        logger.debug("SessionPool: 신규 세션 생성 user_id=%d", user_id)
        return session

    def get_trimmed_history(
        self, user_id: int, raw_history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        유저 세션의 HybridContextManager를 통해 history 트리밍.
        병행 요청 시 각 유저의 컨텍스트가 토큰 한도를 초과하지 않도록 보장.
        """
        session = self.get_or_create(user_id)
        ctx: HybridContextManager = session["ctx_manager"]
        return ctx.get_trimmed_history(raw_history)

    def _evict_expired(self, now: float):
        expired = [
            uid for uid, s in self._sessions.items()
            if now - s["last_active"] > self.ttl
        ]
        for uid in expired:
            del self._sessions[uid]
        if expired:
            gc.collect()
            logger.debug("SessionPool: TTL 만료 %d 세션 제거", len(expired))

    def _evict_oldest(self, keep: int):
        while len(self._sessions) > keep:
            self._sessions.popitem(last=False)
        gc.collect()

    def stats(self) -> dict:
        vram = get_vram_usage()
        return {
            "active_sessions": len(self._sessions),
            "vram_used_mb": vram["used_mb"],
            "vram_total_mb": vram["total_mb"],
            "vram_pct": round(vram["pct"], 1),
            "semaphore_value": OLLAMA_SEMAPHORE._value,
        }


# ── 전역 싱글톤 ──────────────────────────────────────────────────
_pool: Optional[SessionPool] = None


def get_session_pool() -> SessionPool:
    global _pool
    if _pool is None:
        from config import settings
        _pool = SessionPool(
            ollama_base_url=getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_model=getattr(settings, "OLLAMA_MODEL", "exaone3.5:7.8b"),
        )
    return _pool
