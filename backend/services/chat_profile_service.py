from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROFILE_PATH = Path(__file__).resolve().parent.parent / "chatbot_profile.json"

DEFAULT_PROFILE: dict[str, Any] = {
    "assistant_name": "Node Omega-Prime",
    "identity_markdown": (
        "Omega CivicFlow \ubb38\uc11c \ubd84\uc11d \ucc57\ubd07 `Node Omega-Prime`\uc785\ub2c8\ub2e4.\n\n"
        "\uc5c5\ub85c\ub4dc\ub41c \ubb38\uc11c, \uad6c\uc870\ud654\ub41c \uc7ac\ubb34 \ud329\ud2b8, DART \uacf5\uc2dc \uac80\uc0c9 \uacb0\uacfc\ub97c \ubc14\ud0d5\uc73c\ub85c \ub2f5\ubcc0\ud569\ub2c8\ub2e4."
    ),
    "help_markdown": (
        "\uc9c8\ubb38 \uc608\uc2dc\n"
        "- \uc791\ub144 \uc2e4\uc801 \uc88b\uc740 \uae30\uc5c5 top10\n"
        "- \uc601\uc5c5\uc774\uc775 \uae30\uc900 \uc0c1\uc704 3\uac1c\n"
        "- \ucd5c\uadfc 3\ub144 \ub9e4\ucd9c \ucd94\uc138\n"
        "- \uc0bc\uc131\uc804\uc790 \ucd5c\uadfc \uc2e4\uc801 \uc694\uc57d\n"
        "- \uc0bc\uc131\uc804\uc790 \uacf5\uc2dc \ucc3e\uc544\uc918"
    ),
    "welcome_markdown": (
        "Node Omega-Prime\uc785\ub2c8\ub2e4.\n\n"
        "\ubb38\uc11c \uae30\ubc18\uc73c\ub85c \uae30\uc5c5 \uc2e4\uc801, \ube44\uad50, \ucd94\uc138, \uacf5\uc2dc\ub97c \uc815\ub9ac\ud574 \ub4dc\ub9bd\ub2c8\ub2e4."
    ),
    "example_queries": [
        "\uc791\ub144 \uc2e4\uc801 \uc88b\uc740 \uae30\uc5c5 top10",
        "\uc601\uc5c5\uc774\uc775 \uae30\uc900 \uc0c1\uc704 3\uac1c",
        "\ucd5c\uadfc 3\ub144 \ub9e4\ucd9c \ucd94\uc138",
        "\uc0bc\uc131\uc804\uc790 \ucd5c\uadfc \uc2e4\uc801 \uc694\uc57d",
        "\uc0bc\uc131\uc804\uc790 \uacf5\uc2dc \ucc3e\uc544\uc918",
    ],
    "response_style": {"language": "ko"},
    "version": "recovery-v3",
}


def _normalize_profile(loaded: dict[str, Any]) -> dict[str, Any]:
    profile = dict(DEFAULT_PROFILE)
    profile.update({k: v for k, v in loaded.items() if v is not None})
    for key in ("assistant_name", "identity_markdown", "help_markdown", "welcome_markdown", "version"):
        if not isinstance(profile.get(key), str) or not str(profile[key]).strip():
            profile[key] = DEFAULT_PROFILE[key]
    example_queries = profile.get("example_queries")
    if not isinstance(example_queries, list):
        profile["example_queries"] = list(DEFAULT_PROFILE["example_queries"])
    else:
        cleaned = [str(item).strip() for item in example_queries if str(item).strip()]
        profile["example_queries"] = cleaned or list(DEFAULT_PROFILE["example_queries"])
    if not isinstance(profile.get("response_style"), dict):
        profile["response_style"] = dict(DEFAULT_PROFILE["response_style"])
    return profile


@lru_cache(maxsize=1)
def _load_profile_cached(mtime_ns: int) -> dict[str, Any]:
    del mtime_ns
    try:
        with PROFILE_PATH.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        if isinstance(loaded, dict):
            return _normalize_profile(loaded)
    except FileNotFoundError:
        logger.info("chatbot_profile.json not found. Using defaults.")
    except Exception as exc:
        logger.warning("chatbot_profile.json load failed: %s", exc)
    return dict(DEFAULT_PROFILE)


def get_chatbot_profile() -> dict[str, Any]:
    try:
        mtime_ns = PROFILE_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = 0
    return _load_profile_cached(mtime_ns)


def get_chatbot_public_config() -> dict[str, Any]:
    profile = get_chatbot_profile()
    return {
        "assistant_name": profile["assistant_name"],
        "welcome_markdown": profile["welcome_markdown"],
        "help_markdown": profile["help_markdown"],
        "example_queries": profile["example_queries"],
        "version": profile["version"],
    }
