from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Domain = Literal["F", "E", "S", "D", "R"]
Complexity = Literal["simple", "analytical", "strategic"]
AnswerMode = Literal["direct", "analytical", "strategic"]

Intent = Literal[
    "casual_chat",
    "model_identity",
    "company_financial_summary",
    "stock_outlook",
    "peer_comparison",
    "data_lookup",
    "unsupported",
]

ConfidenceLabel = Literal[
    "AXIOM",
    "CONSENSUS",
    "INFERENCE",
    "SPECULATION",
    "EXPLORATION",
]


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[Message] = Field(default_factory=list)


class RouterResult(BaseModel):
    surface_question: str = Field(default="")
    latent_goal: str = Field(default="")
    domain_primary: Domain = Field(default="F")
    domain_secondary: List[Domain] = Field(default_factory=list)
    complexity: Complexity = Field(default="analytical")
    intent: Intent = Field(default="casual_chat")
    needs_retrieval: bool = Field(default=False)
    needs_tools: bool = Field(default=False)
    needs_clarification: bool = Field(default=False)
    answer_mode: AnswerMode = Field(default="analytical")
    entities: List[str] = Field(default_factory=list)
    time_horizon: Literal["none", "past", "current", "forward"] = Field(default="current")
    risk_flags: List[str] = Field(default_factory=list)
    retrieval_queries: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)


class Citation(BaseModel):
    chunk_id: str = Field(default="")
    source: str = Field(default="")
    text_snippet: str = Field(default="")


class ResponseMeta(BaseModel):
    intent: str = Field(default="")
    confidence: str = Field(default="")
    evidence_count: int = Field(default=0)
    coverage_gaps: List[str] = Field(default_factory=list)
    fallback_reason: str = Field(default="")
    rag_density: str = Field(default="")


class ChatResponse(BaseModel):
    answer: str
    route: Optional[RouterResult] = None
    used_retrieval: bool = False
    evidence_count: int = 0
    payload: Optional[Dict[str, Any]] = None
    citations: List[Citation] = Field(default_factory=list)
    meta: Optional[ResponseMeta] = None


class PlanResult(BaseModel):
    user_goal: str = Field(default="")
    subquestions: List[str] = Field(default_factory=list)
    evidence_needed: List[str] = Field(default_factory=list)
    tool_sequence: List[str] = Field(default_factory=list)
    retrieval_priority: List[str] = Field(default_factory=list)
    rejection_rules: List[str] = Field(default_factory=list)
    stop_condition: str = Field(default="")


class RetrievedChunk(BaseModel):
    chunk_id: str
    source_class: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KeptChunk(BaseModel):
    chunk_id: str = Field(default="")
    relevance_score: int = Field(ge=0, le=100, default=50)
    reason: str = Field(default="")
    source_class: str = Field(default="")
    time_sensitivity: Literal["low", "medium", "high"] = Field(default="medium")
    supports: List[str] = Field(default_factory=list)


class DiscardedChunk(BaseModel):
    chunk_id: str = Field(default="")
    reason: str = Field(default="")


class JudgeResult(BaseModel):
    kept: List[KeptChunk] = Field(default_factory=list)
    discarded: List[DiscardedChunk] = Field(default_factory=list)
    coverage_gaps: List[str] = Field(default_factory=list)
    enough_evidence: bool = Field(default=True)


class CriticResult(BaseModel):
    passed: bool = Field(default=True)
    issues: List[str] = Field(default_factory=list)
    missing_variables: List[str] = Field(default_factory=list)
    false_constraints: List[str] = Field(default_factory=list)
    causal_warnings: List[str] = Field(default_factory=list)
    precision_warnings: List[str] = Field(default_factory=list)
    revision_instructions: List[str] = Field(default_factory=list)
