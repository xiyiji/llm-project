"""Configuration loading."""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from typing import Dict, List

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
VAR_DIR = PROJECT_ROOT / "var"


class LLMConfig(BaseModel):
    provider: str = "deepseek"
    small_model: str = "deepseek-chat"
    large_model: str = "deepseek-reasoner"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout_s: int = 60
    pricing_per_1m: Dict[str, Dict[str, float]] = Field(
        default_factory=lambda: {
            "deepseek-chat": {"input": 0.27, "output": 1.10},
            "deepseek-reasoner": {"input": 0.55, "output": 2.19},
        }
    )


class CascadeConfig(BaseModel):
    enabled: bool = True
    confidence_threshold: float = 0.7
    high_stakes_tiers: List[str] = Field(default_factory=lambda: ["VIP", "PREMIUM"])


class CacheConfig(BaseModel):
    enabled: bool = True
    max_entries: int = 512
    ttl_seconds: int = 3600


class ThresholdsConfig(BaseModel):
    perishable_delay_hours: float = 4.0
    premium_perishable_delay_hours: float = 2.0
    vip_exception_threshold: int = 3
    standard_exception_threshold: int = 5
    escalation_attempt_number: int = 3


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    cascade: CascadeConfig = Field(default_factory=CascadeConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    path = PROJECT_ROOT / "config.yaml"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig.model_validate(raw)
    return AppConfig()


def deepseek_api_key() -> str:
    return os.environ.get(get_config().llm.api_key_env, "")
