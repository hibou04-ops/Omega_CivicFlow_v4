"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Task Dispatcher
서버 프로세스에서 Celery 태스크를 안전하게 디스패치하는 유틸리티
Celery를 import하지 않고 Redis에 직접 메시지를 게시
═══════════════════════════════════════════════════════
"""

import json
import uuid
import logging
import redis as redis_lib
from config import settings

logger = logging.getLogger("omega.civicflow.dispatcher")

_redis = None


def _get_redis():
    global _redis
    if _redis is None:
        _redis = redis_lib.Redis.from_url(settings.REDIS_URL)
    return _redis


def dispatch_task(task_name: str, args: list = None, kwargs: dict = None) -> str:
    """
    Celery 태스크를 Redis 브로커를 통해 디스패치
    Celery 프로토콜 v2 메시지 포맷 사용
    Returns: task_id
    """
    task_id = str(uuid.uuid4())
    
    body = json.dumps({
        "id": task_id,
        "task": task_name,
        "args": args or [],
        "kwargs": kwargs or {},
        "retries": 0,
    })

    headers = {
        "id": task_id,
        "task": task_name,
        "lang": "py",
        "root_id": task_id,
        "parent_id": None,
        "group": None,
    }

    properties = {
        "correlation_id": task_id,
        "content_type": "application/json",
        "content_encoding": "utf-8",
        "delivery_mode": 2,
        "delivery_tag": str(uuid.uuid4()),
    }

    message = json.dumps([
        [args or [], kwargs or {}, {"callbacks": None, "errbacks": None, "chain": None, "chord": None}],
        "application/json",
        "utf-8",
    ])

    r = _get_redis()
    r.lpush("celery", json.dumps({
        "body": body,
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "headers": headers,
        "properties": {
            **properties,
            "body_encoding": "base64",
            "delivery_info": {"exchange": "", "routing_key": "celery"},
        },
    }))

    logger.info(f"📤 태스크 디스패치 → {task_name} (id={task_id[:8]})")
    return task_id


def get_task_result(task_id: str) -> dict:
    """Celery 태스크 결과를 Redis에서 조회"""
    r = _get_redis()
    key = f"celery-task-meta-{task_id}"
    data = r.get(key)
    if data:
        return json.loads(data)
    return None
