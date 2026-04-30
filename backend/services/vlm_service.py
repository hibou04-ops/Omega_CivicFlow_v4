"""
═══════════════════════════════════════════════════════
Omega CivicFlow — VLM Service
파인튜닝된 Qwen2.5-VL 모델 (RunPod vLLM) 연동 서비스
OpenAI 호환 API로 이미지+텍스트 분석
═══════════════════════════════════════════════════════
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════

from config import settings

VLLM_BASE_URL = settings.VLLM_BASE_URL
VLLM_MODEL = settings.VLLM_MODEL
VLLM_TIMEOUT = 120  # 초

# ═══════════════════════════════════════════════════════
# 분석 프롬프트
# ═══════════════════════════════════════════════════════

ANALYSIS_SYSTEM_PROMPT = """당신은 DART 금융공시 전문 분석 AI입니다.
문서를 분석하여 다음 JSON 형식으로 정확하게 응답하세요:

{
  "summary": "문서 핵심 내용 2~4문장 요약",
  "category": "유상증자|무상증자|전환사채|신주인수권부사채|자기주식|합병|분할|기타",
  "company_name": "회사명",
  "document_type": "공시 유형",
  "key_points": ["핵심 포인트1", "핵심 포인트2"],
  "key_changes": [{"field": "항목", "before": "이전", "after": "이후"}],
  "financial_metrics": "주요 재무 수치 요약",
  "risk_notes": ["리스크1", "리스크2"]
}

반드시 유효한 JSON만 출력하세요."""

ANALYSIS_USER_PROMPT = """아래 DART 공시문서를 분석해주세요.

{text}

위 내용을 분석하여 JSON 형식으로 응답해주세요."""


# ═══════════════════════════════════════════════════════
# VLM Service 클래스
# ═══════════════════════════════════════════════════════

class VLMService:
    """
    RunPod vLLM (Qwen2.5-VL 파인튜닝 모델) 연동 서비스
    텍스트 및 이미지 기반 DART 문서 분석
    """

    def __init__(self):
        self.base_url = VLLM_BASE_URL.rstrip("/")
        self.model = VLLM_MODEL
        self.client = httpx.AsyncClient(timeout=VLLM_TIMEOUT)

    async def check_health(self) -> bool:
        """vLLM 서버 상태 확인"""
        try:
            resp = await self.client.get(f"{self.base_url}/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        텍스트 기반 문서 분석 (OCR 추출 텍스트 입력)
        Returns: analyze_document()와 동일한 구조의 dict
        """
        start_time = time.time()

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT + f"\n[현재 시간: {__import__('datetime').datetime.now().strftime('%Y년 %m월 %d일 %H:%M')} KST]"},
            {
                "role": "user",
                "content": ANALYSIS_USER_PROMPT.format(
                    text=text[:6000]  # 토큰 제한
                )
            }
        ]

        try:
            resp = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.1,
                    "stream": False,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            processing_time = time.time() - start_time

            # JSON 파싱
            return self._parse_response(raw_content, processing_time)

        except httpx.TimeoutException:
            logger.error("vLLM 서버 타임아웃 (120초 초과)")
            return self._error_result("vLLM 타임아웃 — RunPod 서버 상태를 확인하세요")
        except httpx.ConnectError:
            logger.error(f"vLLM 서버 연결 실패: {self.base_url}")
            return self._error_result(f"vLLM 서버 연결 실패: {self.base_url}")
        except Exception as e:
            logger.error(f"VLM 분석 실패: {e}")
            return self._error_result(f"VLM 분석 오류: {str(e)}")

    async def analyze_image(self, image_path: str, hint_text: str = "") -> Dict[str, Any]:
        """
        이미지 기반 문서 분석 (Qwen2.5-VL 비전 능력 활용)
        OCR 단계를 건너뛰고 이미지 직접 분석
        """
        start_time = time.time()

        try:
            # 이미지 base64 인코딩
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            ext = Path(image_path).suffix.lower().lstrip(".")
            mime = f"image/{'jpeg' if ext == 'jpg' else ext}"

            content = [
                {"type": "text", "text": ANALYSIS_SYSTEM_PROMPT + f"\n[현재 시간: {__import__('datetime').datetime.now().strftime('%Y년 %m월 %d일 %H:%M')} KST]"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{img_b64}"}
                },
                {"type": "text", "text": "위 공시문서 이미지를 분석하여 JSON으로 응답하세요."}
            ]

            if hint_text:
                content.append({
                    "type": "text",
                    "text": f"\n[OCR 힌트]: {hint_text[:1000]}"
                })

            resp = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 1024,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()

            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            processing_time = time.time() - start_time

            return self._parse_response(raw_content, processing_time)

        except FileNotFoundError:
            return self._error_result(f"이미지 파일 없음: {image_path}")
        except Exception as e:
            logger.error(f"VLM 이미지 분석 실패: {e}")
            return self._error_result(f"VLM 이미지 분석 오류: {str(e)}")

    def _parse_response(self, raw: str, processing_time: float) -> Dict[str, Any]:
        """LLM 응답에서 JSON 추출"""
        # 마크다운 코드블록 제거
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            ).strip()

        # JSON 추출 시도
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            # { ... } 블록만 추출
            import re
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except Exception:
                    parsed = {"summary": clean}
            else:
                parsed = {"summary": clean}

        # 공통 필드 보장
        return {
            "summary": parsed.get("summary", ""),
            "category": parsed.get("category", "기타"),
            "company_name": parsed.get("company_name", ""),
            "document_type": parsed.get("document_type", {"primary": "기타공시", "secondary": ""}),
            "key_points": parsed.get("key_points", []),
            "key_changes": parsed.get("key_changes", []),
            "financial_metrics": parsed.get("financial_metrics", ""),
            "insight_vectors": parsed.get("financial_metrics", ""),
            "risk_notes": parsed.get("risk_notes", []),
            "evidence": "",
            "evidence_detailed": [],
            "offering_terms": {},
            "third_party_allotment": {},
            "_processing_time": processing_time,
            "_model": f"vllm:{self.model}",
            "_is_error": False,
        }

    def _error_result(self, message: str) -> Dict[str, Any]:
        """에러 결과 반환"""
        return {
            "summary": message,
            "category": "기타",
            "company_name": "",
            "document_type": {"primary": "기타공시", "secondary": ""},
            "key_points": [],
            "key_changes": [],
            "financial_metrics": "",
            "insight_vectors": "",
            "risk_notes": [],
            "evidence": "",
            "evidence_detailed": [],
            "offering_terms": {},
            "third_party_allotment": {},
            "_processing_time": 0.0,
            "_model": f"vllm:{self.model}",
            "_is_error": True,
        }

    async def close(self):
        await self.client.aclose()


# 싱글톤
vlm_service = VLMService()
