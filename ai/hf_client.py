"""
HuggingFace InferenceClient wrapper.
Generation model: Qwen/Qwen2.5-72B-Instruct (confirmed working on free tier)
Summarization: facebook/bart-large-cnn
Embeddings: sentence-transformers/all-MiniLM-L6-v2
"""
import logging
from huggingface_hub import InferenceClient
from config import HF_API_KEY, HF_SUMMARIZATION_MODEL, HF_EMBEDDING_MODEL

log = logging.getLogger(__name__)

# Confirmed working on free HF inference tier
HF_GENERATION_MODEL = "Qwen/Qwen2.5-72B-Instruct"

_gen_client: InferenceClient | None = None
_sum_client: InferenceClient | None = None
_emb_client: InferenceClient | None = None


def _gen() -> InferenceClient:
    global _gen_client
    if _gen_client is None:
        _gen_client = InferenceClient(model=HF_GENERATION_MODEL, token=HF_API_KEY)
    return _gen_client


def _sum() -> InferenceClient:
    global _sum_client
    if _sum_client is None:
        _sum_client = InferenceClient(model=HF_SUMMARIZATION_MODEL, token=HF_API_KEY)
    return _sum_client


def _emb() -> InferenceClient:
    global _emb_client
    if _emb_client is None:
        _emb_client = InferenceClient(model=HF_EMBEDDING_MODEL, token=HF_API_KEY)
    return _emb_client


def generate(prompt: str, max_new_tokens: int = 512, temperature: float = 0.4) -> str:
    """Chat completion via Qwen2.5-72B (free tier confirmed)."""
    try:
        clean = prompt.replace("[INST]", "").replace("[/INST]", "").strip()
        response = _gen().chat_completion(
            messages=[{"role": "user", "content": clean}],
            max_tokens=max_new_tokens,
            temperature=max(temperature, 0.01),
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log.error("HF generate error: %s", e)
        return ""


def summarize(text: str, max_length: int = 256, min_length: int = 60) -> str:
    """Abstractive summarization via BART. Falls back to extractive on API failure."""
    if not text or len(text.strip()) < 50:
        return text.strip() if text else ""
    truncated = text[:3000]
    try:
        # HF router v2: pass length params via `parameters` dict
        result = _sum().summarization(
            truncated,
            parameters={"max_length": max_length, "min_length": min_length},
        )
        return result.summary_text.strip()
    except Exception:
        pass
    try:
        # Fallback: call with no length params (use model defaults)
        result = _sum().summarization(truncated)
        return result.summary_text.strip()
    except Exception as e:
        log.debug("HF summarize unavailable, using extractive fallback: %s", e)
        # Extractive fallback — first 3 sentences
        sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if len(s.strip()) > 20]
        return ". ".join(sentences[:3]) + ("." if sentences else "")


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Sentence embeddings via MiniLM-L6-v2."""
    try:
        import numpy as np
        embeddings = []
        for text in texts:
            vec = _emb().feature_extraction(text[:512])
            arr = np.array(vec)
            # Handle (1, N) or (N,) shapes
            if arr.ndim == 2:
                arr = arr.mean(axis=0)
            embeddings.append(arr.tolist())
        return embeddings
    except Exception as e:
        log.error("HF embedding error: %s", e)
        return [[] for _ in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
