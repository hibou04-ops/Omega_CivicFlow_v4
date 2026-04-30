"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Celery Application
에너지 분산 엔진 (Energy Distribution Engine)
Redis 브로커 기반 비동기 태스크 처리
═══════════════════════════════════════════════════════
"""

from celery import Celery
from config import settings

celery_app = Celery(
    "civicflow",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["tasks"],
)

celery_app.conf.update(
    # 태스크 직렬화
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 타임존
    timezone="Asia/Seoul",
    enable_utc=True,
    # 태스크 결과 유효시간 (1시간)
    result_expires=3600,
    # 워커 동시성 (CPU 코어 수 고려)
    worker_concurrency=2,
    # 프리페칭 비활성화 (긴 태스크)
    worker_prefetch_multiplier=1,
    # 태스크 제한시간 (10분)
    task_soft_time_limit=540,
    task_time_limit=600,
)
