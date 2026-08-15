"""Per-model capability probe.

A heuristic table for now (refined as we probe real providers/endpoints). Accepts
either bare model names (`gpt-5.5`) or provider-qualified ones (`openai:gpt-5.5`).
"""

from __future__ import annotations

import logging
import re

from .base import ModelCapabilities

logger = logging.getLogger(__name__)

_VISION_KEYWORDS = (
    "vision",
    "llava",
    "bakllava",
    "minicpm-v",
    "pixtral",
    "moondream",
    "internvl",
    "cogvlm",
    "omni",
    "glm-4v",
)


def _has_vision_signal(name: str) -> bool:
    """Return True if model name contains clear vision/multimodal indicators.

    Matches common vision identifiers (e.g. `vision`, `llava`, `omni`, `-vl`, `pixtral`)
    without false-positive matching on version tokens (e.g. `-v1`, `-v2`, `-v3`, `-v4`, `-v1:0`).
    """
    n = name.lower()
    if any(k in n for k in _VISION_KEYWORDS):
        return True
    # Match -vl or _vl or .vl or /vl or :vl followed by digit+b (e.g. vl8b, vl72b) or separator / end
    # e.g., "qwen3-vl8b", "qwen2.5-vl", "qwen-vl", "deepseek-vl", "yi-vl"
    return bool(re.search(r"[-_./:]vl(?:\d+b|[-_./:]|$)", n))


def capabilities_for(model: str) -> ModelCapabilities:
    # Curated models answer from the matrix (exact full-id match — including reseller ids
    # like `together:zai-org/GLM-5.2`, whose names defeat the prefix heuristics below).
    # Custom user-added models fall through to the heuristics, at their own risk.
    from .matrix import entry_for

    entry = entry_for(model)
    if entry is not None:
        logger.debug(
            "capabilities_for curated model=%r -> tools=%s vision=%s pdf=%s parallel_tool_calls=%s streaming=%s",
            model,
            entry.caps.tools,
            entry.caps.vision,
            entry.caps.pdf,
            entry.caps.parallel_tool_calls,
            entry.caps.streaming,
        )
        return entry.caps

    provider = model.split(":", 1)[0].lower() if ":" in model else ""
    name = model.split(":", 1)[-1].lower()  # strip a provider prefix if present

    # Ollama (local) models vary widely and many fake/mishandle parallel tool calls — assume
    # tools work (we only point at tool-capable models) but stay conservative otherwise.
    if provider == "ollama":
        caps = ModelCapabilities(
            tools=True,
            vision=_has_vision_signal(name),
            parallel_tool_calls=False,
            streaming=True,
        )
    # Cloud-account providers (custom-added ids; curated ones answered from the matrix).
    # The family segment decides: Claude keeps its native capabilities; everything else
    # stays conservative until probed (Converse tool calling works across families, but
    # parallel calls and vision vary per model).
    elif provider in ("bedrock", "vertex"):
        if name.startswith(("claude/", "gemini/")):
            caps = ModelCapabilities(
                tools=True, vision=True, pdf=True, parallel_tool_calls=True, streaming=True
            )
        else:
            caps = ModelCapabilities(
                tools=True,
                vision=_has_vision_signal(name),
                parallel_tool_calls=False,
                streaming=True,
            )
    # Claude / Gemini (both native): tools + vision + parallel tool calls + streaming. The
    # engine executes parallel calls sequentially and each converter folds the results into
    # the single next user message — exactly what both APIs require.
    elif provider in ("anthropic", "gemini"):
        caps = ModelCapabilities(
            tools=True, vision=True, pdf=True, parallel_tool_calls=True, streaming=True
        )
    # Modern OpenAI GPT models: tools + vision + parallel tool calls + streaming.
    elif name.startswith(("gpt-5", "gpt-4")):
        caps = ModelCapabilities(
            tools=True, vision=True, pdf=True, parallel_tool_calls=True, streaming=True
        )
    # OpenAI reasoning models: tools yes, parallel tool calls constrained.
    elif name.startswith(("o1", "o3", "o4")):
        caps = ModelCapabilities(
            tools=True,
            vision=_has_vision_signal(name),
            parallel_tool_calls=False,
            streaming=True,
        )
    # OpenAI-compatible vendors (DeepSeek, Z AI/GLM, Kimi, MiniMax, Qwen, xAI/Grok, Mistral):
    # tool calling + streaming across their current lineups; vision enabled when detected.
    elif name.startswith(
        ("deepseek", "glm", "kimi", "minimax", "qwen", "grok", "mistral", "magistral")
    ):
        caps = ModelCapabilities(
            tools=True,
            vision=_has_vision_signal(name),
            parallel_tool_calls=True,
            streaming=True,
        )
    # Conservative default for unknown models.
    else:
        caps = ModelCapabilities(
            tools=True,
            vision=_has_vision_signal(name),
            parallel_tool_calls=False,
            streaming=True,
        )

    logger.debug(
        "capabilities_for model=%r (provider=%r, name=%r) -> tools=%s vision=%s pdf=%s parallel_tool_calls=%s streaming=%s",
        model,
        provider,
        name,
        caps.tools,
        caps.vision,
        caps.pdf,
        caps.parallel_tool_calls,
        caps.streaming,
    )
    return caps

