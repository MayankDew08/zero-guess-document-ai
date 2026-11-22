from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val is not None and val.strip() != "" else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val is not None and val.strip() != "" else default


@dataclass
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    ollama_fallback_model: str = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:3b-instruct")
    llm_temperature: float = _float("LLM_TEMPERATURE", 0.1)
    llm_max_tokens: int = _int("LLM_MAX_TOKENS", 1024)
    llm_timeout_seconds: float = _float("LLM_TIMEOUT_SECONDS", 120)

    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    embedding_backend: str = os.getenv("EMBEDDING_BACKEND", "sentence-transformers")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")

    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    reranker_top_k: int = _int("RERANKER_TOP_K", 12)
    reranker_keep_top_n: int = _int("RERANKER_KEEP_TOP_N", 5)
    rerank_abstain_threshold: float = _float("RERANK_ABSTAIN_THRESHOLD", 0.25)

    nli_model: str = os.getenv("NLI_MODEL", "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli")
    nli_entailment_threshold: float = _float("NLI_ENTAILMENT_THRESHOLD", 0.65)
    nli_contradiction_threshold: float = _float("NLI_CONTRADICTION_THRESHOLD", 0.70)
    use_fp16: bool = _bool("USE_FP16", True)

    chunk_target_chars: int = _int("CHUNK_TARGET_CHARS", 450)
    chunk_overlap_chars: int = _int("CHUNK_OVERLAP_CHARS", 80)
    hybrid_top_k: int = _int("HYBRID_TOP_K", 12)

    data_dir: str = os.getenv("DATA_DIR", "../data")
    index_dir: str = os.getenv("INDEX_DIR", "../data/index")
    sample_dir: str = os.getenv("SAMPLE_DIR", "../data/samples")
    report_dir: str = os.getenv("REPORT_DIR", "../data/reports")

    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def resolve_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        # Resolve relative to backend/ by default
        backend_root = Path(__file__).resolve().parents[2]
        return (backend_root / p).resolve()

    @property
    def data_path(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def index_path(self) -> Path:
        return self.resolve_path(self.index_dir)

    @property
    def sample_path(self) -> Path:
        return self.resolve_path(self.sample_dir)

    @property
    def report_path(self) -> Path:
        return self.resolve_path(self.report_dir)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
