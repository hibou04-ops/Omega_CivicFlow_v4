from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from services.chat_agent_safe_service import run_agent as run_safe_agent


async def run_agent(
    user_message: str,
    history: List[Dict[str, Any]],
    user_id: int,
    db: Session,
) -> Dict[str, Any]:
    return await run_safe_agent(
        user_message=user_message,
        history=history,
        user_id=user_id,
        db=db,
    )
