import json
import logging
import math
import re
from collections import Counter
from typing import Any

from text_to_sql_agent import cache as cache_backend
from text_to_sql_agent.config import Settings


LOGGER = logging.getLogger(__name__)
SEMANTIC_CACHE_VERSION = "v1"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "have",
    "has",
    "in",
    "of",
    "on",
    "show",
    "the",
    "to",
    "which",
    "who",
    "with",
}
SYNONYMS = {
    "accounts": "customer",
    "account": "customer",
    "balances": "balance",
    "clients": "customer",
    "client": "customer",
    "customers": "customer",
    "customer": "customer",
    "due": "balance",
    "invoices": "invoice",
    "owed": "balance",
    "owes": "balance",
    "owing": "balance",
    "overdue": "overdue",
    "unpaid": "overdue",
}


def lookup_semantic_sql(question: str, namespace_payload: dict[str, Any], settings: Settings) -> str | None:
    if not settings.enable_semantic_cache:
        return None

    client = cache_backend.get_redis_client(settings.redis_url)
    if client is None:
        return None

    cache_key = _semantic_cache_key(namespace_payload)
    try:
        entries = _load_entries(client, cache_key)
    except Exception as exc:
        LOGGER.warning("Semantic cache read failed: %s", exc)
        return None

    query_vector = _question_vector(question)
    best_score = 0.0
    best_sql: str | None = None
    for entry in entries:
        score = _cosine_similarity(query_vector, Counter(entry.get("vector") or {}))
        if score > best_score:
            best_score = score
            best_sql = str(entry.get("sql") or "")

    if best_sql and best_score >= settings.semantic_cache_threshold:
        LOGGER.info("Semantic SQL cache hit with score %.4f", best_score)
        return best_sql
    return None


def store_semantic_sql(question: str, sql: str, namespace_payload: dict[str, Any], settings: Settings) -> None:
    if not settings.enable_semantic_cache:
        return

    client = cache_backend.get_redis_client(settings.redis_url)
    if client is None:
        return

    cache_key = _semantic_cache_key(namespace_payload)
    try:
        entries = _load_entries(client, cache_key)
        normalized_question = _normalize_question(question)
        entries = [entry for entry in entries if entry.get("normalized_question") != normalized_question]
        entries.insert(
            0,
            {
                "question": question,
                "normalized_question": normalized_question,
                "vector": dict(_question_vector(question)),
                "sql": sql,
                "version": SEMANTIC_CACHE_VERSION,
            },
        )
        trimmed = entries[: settings.semantic_cache_max_entries]
        client.setex(cache_key, settings.cache_ttl_seconds, json.dumps(trimmed, separators=(",", ":")))
    except Exception as exc:
        LOGGER.warning("Semantic cache write failed: %s", exc)


def _semantic_cache_key(namespace_payload: dict[str, Any]) -> str:
    payload = {"semantic_cache_version": SEMANTIC_CACHE_VERSION, **namespace_payload}
    return cache_backend.build_cache_key("semantic-generated-sql", payload)


def _load_entries(client: Any, cache_key: str) -> list[dict[str, Any]]:
    raw = client.get(cache_key)
    if not raw:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(str(raw))
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _question_vector(question: str) -> Counter[str]:
    return Counter(_tokenize(_normalize_question(question)))


def _normalize_question(question: str) -> str:
    tokens = _tokenize(question)
    return " ".join(tokens)


def _tokenize(text: str) -> list[str]:
    normalized: list[str] = []
    for raw_token in re.findall(r"[A-Za-z0-9]+", text.lower()):
        token = SYNONYMS.get(raw_token, raw_token)
        if token.endswith("s") and len(token) > 3:
            token = token[:-1]
        token = SYNONYMS.get(token, token)
        if token not in STOPWORDS:
            normalized.append(token)
    return normalized


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0

    shared = set(left).intersection(right)
    dot_product = sum(left[token] * right[token] for token in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot_product / (left_norm * right_norm)
