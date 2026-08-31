"""LLM access layer: DeepSeek small/large models behind a response cache.

The cache is keyed on the full request (model, messages, temperature) and
tracks hit/miss counters, so the cached flag in responses and metrics comes
from actual cache lookups. Token usage is read from the API response and
priced per model, so cost accounting is real. Without DEEPSEEK_API_KEY (or on
any API failure) callers fall back to the deterministic policy engine.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from app.config import deepseek_api_key, get_config


class LLMResponse:
    def __init__(
        self,
        text: str,
        cached: bool,
        latency_ms: int,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ):
        self.text = text
        self.cached = cached
        self.latency_ms = latency_ms
        self.provider = provider
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd


class LLMUnavailableError(Exception):
    pass


class ResponseCache:
    """LRU + TTL cache for chat completions."""

    def __init__(self, max_entries: int, ttl_seconds: int):
        self._store: "OrderedDict[str, Tuple[float, str]]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key_for(model: str, messages: List[Dict], temperature: float) -> str:
        payload = json.dumps(
            {"model": model, "messages": messages, "temperature": temperature},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            stored_at, text = entry
            if time.time() - stored_at > self.ttl_seconds:
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return text

    def put(self, key: str, text: str) -> None:
        with self._lock:
            self._store[key] = (time.time(), text)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def stats(self) -> Dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
            }


def price_for(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = get_config().llm.pricing_per_1m.get(model)
    if not pricing:
        return 0.0
    return round(
        input_tokens / 1_000_000 * pricing.get("input", 0.0)
        + output_tokens / 1_000_000 * pricing.get("output", 0.0),
        8,
    )


class RedisCache:
    """Same interface as ResponseCache, shared across workers via Redis."""

    def __init__(self, url: str, ttl_seconds: int):
        import redis  # optional dependency, only needed for this backend

        self._r = redis.from_url(url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> Optional[str]:
        value = self._r.get(f"llmcache:{key}")
        self._r.incr("llmcache:hits" if value is not None else "llmcache:misses")
        return value

    def put(self, key: str, text: str) -> None:
        self._r.set(f"llmcache:{key}", text, ex=self.ttl_seconds)

    def stats(self) -> Dict:
        hits = int(self._r.get("llmcache:hits") or 0)
        misses = int(self._r.get("llmcache:misses") or 0)
        total = hits + misses
        return {
            "backend": "redis",
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 4) if total else 0.0,
        }


class DeepSeekClient:
    def __init__(self, cache=None):
        import os

        cfg = get_config()
        self.cfg = cfg.llm
        if cache is None:
            redis_url = os.environ.get("REDIS_URL")
            if redis_url:
                cache = RedisCache(redis_url, cfg.cache.ttl_seconds)
            else:
                cache = ResponseCache(cfg.cache.max_entries, cfg.cache.ttl_seconds)
        self.cache = cache
        self.cache_enabled = cfg.cache.enabled
        self._client = None

    def available(self) -> Tuple[bool, Optional[str]]:
        if not deepseek_api_key():
            return False, f"{self.cfg.api_key_env} not configured"
        return True, None

    def _sdk(self):
        if self._client is None:
            from openai import OpenAI  # DeepSeek serves an OpenAI-compatible API

            self._client = OpenAI(
                api_key=deepseek_api_key(),
                base_url=self.cfg.base_url,
                timeout=self.cfg.timeout_s,
            )
        return self._client

    def chat(
        self, messages: List[Dict], json_mode: bool = False, model: Optional[str] = None
    ) -> LLMResponse:
        ok, reason = self.available()
        if not ok:
            raise LLMUnavailableError(reason)
        model = model or self.cfg.small_model

        key = ResponseCache.key_for(model, messages, self.cfg.temperature)
        if self.cache_enabled:
            hit = self.cache.get(key)
            if hit is not None:
                return LLMResponse(hit, True, 0, "deepseek", model)

        start = time.time()
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            completion = self._sdk().chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                **kwargs,
            )
        except Exception as exc:
            # Any API failure (auth, balance, rate limit, network) degrades to
            # the rules baseline instead of surfacing a 500.
            raise LLMUnavailableError(f"{type(exc).__name__}: {exc}") from exc
        text = completion.choices[0].message.content or ""
        latency_ms = int((time.time() - start) * 1000)
        usage = getattr(completion, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        if self.cache_enabled:
            self.cache.put(key, text)
        return LLMResponse(
            text, False, latency_ms, "deepseek", model,
            input_tokens, output_tokens, price_for(model, input_tokens, output_tokens),
        )


_default_client: Optional[DeepSeekClient] = None
_client_lock = threading.Lock()


def get_client() -> DeepSeekClient:
    global _default_client
    with _client_lock:
        if _default_client is None:
            _default_client = DeepSeekClient()
        return _default_client
