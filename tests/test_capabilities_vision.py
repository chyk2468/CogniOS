"""Tests for vision capability resolution and outbound image preservation.

Validates:
1. Known vision-capable models resolve vision=True
2. Known text-only models resolve vision=False
3. Local (Ollama) vision models resolve vision=True
4. Local (Ollama) text-only models resolve vision=False
5. Curated model matrix overrides heuristic detection
6. Vision model preserves image_url in TurnEngine._outbound_messages()
7. Text-only model replaces image_url with the standard placeholder in TurnEngine._outbound_messages()
"""

from __future__ import annotations

import pytest

from cogniwork.agent import build_engine
from cogniwork.agents.chat import chat_agent
from cogniwork.attachments import build_user_content
from cogniwork.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    capabilities_for,
)
from cogniwork.providers.matrix import MATRIX


# ---------------------------------------------------------------------------
# 1. Known vision-capable models (vendor / openweight / cloud)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model",
    [
        "qwen3-vl8b",
        "qwen:qwen3-vl8b",
        "qwen2.5-vl",
        "qwen2.5-vl-72b",
        "qwen-vl-max",
        "qwen2-vl-7b-instruct",
        "llama-3.2-11b-vision-instruct",
        "mistral:pixtral-12b",
        "pixtral-large-latest",
        "llava-v1.6-34b",
        "minicpm-v",
        "minicpm-v-2_6",
        "bakllava",
        "moondream2",
        "internvl2-26b",
        "cogvlm-chat",
        "glm-4v-9b",
        "qwen-omni",
        "gpt-4o",
        "openai:gpt-4o-mini",
        "anthropic:claude-3-5-sonnet",
        "gemini:gemini-1.5-flash",
    ],
)
def test_known_vision_models_resolve_vision_true(model: str):
    caps = capabilities_for(model)
    assert caps.vision is True, f"Expected vision=True for {model}, got {caps}"


# ---------------------------------------------------------------------------
# 2. Known text-only models
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model",
    [
        "qwen2.5-coder:32b",
        "qwen:qwen2.5-coder",
        "deepseek-chat",
        "deepseek-v3",
        "deepseek-v4-pro",
        "glm-5.2",
        "zai:glm-5.2",
        "kimi:kimi-k2.6",
        "mistral-large-latest",
        "mistral-large-3",
        "o1-mini",
        "o3-mini",
        "llama-3.3-70b-instruct",
        "meta-llama/llama-3.3-70b-instruct",
        "bedrock:other/amazon.nova-2-pro-v1:0",
    ],
)
def test_known_text_only_models_resolve_vision_false(model: str):
    caps = capabilities_for(model)
    assert caps.vision is False, f"Expected vision=False for {model}, got {caps}"


# ---------------------------------------------------------------------------
# 3. Local (Ollama) vision-capable models
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model",
    [
        "ollama:qwen3-vl8b",
        "ollama:qwen2.5-vl",
        "ollama:llama3.2-vision",
        "ollama:llava",
        "ollama:bakllava",
        "ollama:minicpm-v",
        "ollama:moondream",
    ],
)
def test_local_vision_models_resolve_vision_true(model: str):
    caps = capabilities_for(model)
    assert caps.vision is True, f"Expected vision=True for local model {model}, got {caps}"
    assert caps.tools is True
    assert caps.parallel_tool_calls is False  # conservative for Ollama


# ---------------------------------------------------------------------------
# 4. Local (Ollama) text-only models
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model",
    [
        "ollama:qwen2.5-coder",
        "ollama:qwen2.5-coder:32b",
        "ollama:llama3.3",
        "ollama:deepseek-r1",
        "ollama:mistral",
    ],
)
def test_local_text_only_models_resolve_vision_false(model: str):
    caps = capabilities_for(model)
    assert caps.vision is False, f"Expected vision=False for local text model {model}, got {caps}"
    assert caps.tools is True
    assert caps.parallel_tool_calls is False


# ---------------------------------------------------------------------------
# 5. Curated model matrix overrides heuristic detection
# ---------------------------------------------------------------------------
def test_curated_matrix_overrides_heuristic():
    # Model explicitly in MATRIX with vision=False stays vision=False even if name had ambiguous tokens
    for mid, entry in MATRIX.items():
        caps = capabilities_for(mid)
        assert caps.vision == entry.caps.vision, f"Mismatch for matrix model {mid}"
        assert caps.tools == entry.caps.tools


# ---------------------------------------------------------------------------
# 6. Vision model preserves image_url in _outbound_messages()
# ---------------------------------------------------------------------------
def test_outbound_preserves_images_for_vision_models(tmp_path):
    class CapturingVisionProvider(ProviderClient):
        def __init__(self):
            self.captured_messages = None

        def complete(self, *, model, messages, tools=None, **settings):
            self.captured_messages = messages
            return AssistantTurn(text="Saw image", finish_reason="stop")

        def capabilities(self, model):
            return capabilities_for(model)

    provider = CapturingVisionProvider()
    engine = build_engine(
        agent=chat_agent(),
        model="qwen3-vl8b",
        provider=provider,
        workspace=tmp_path,
    )

    image_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    user_content = build_user_content(
        "What text is on this image?",
        [{"kind": "image", "data_url": image_data_url}],
    )

    engine.messages.append({"role": "user", "content": user_content})
    outbound = engine._outbound_messages()

    user_msg = next(m for m in outbound if m.get("role") == "user")
    parts = user_msg["content"]
    assert isinstance(parts, list)
    
    # Must contain text part and image_url part
    image_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == image_data_url


# ---------------------------------------------------------------------------
# 7. Text-only model replaces image_url with placeholder in _outbound_messages()
# ---------------------------------------------------------------------------
def test_outbound_replaces_images_for_text_only_models(tmp_path):
    class CapturingTextProvider(ProviderClient):
        def __init__(self):
            self.captured_messages = None

        def complete(self, *, model, messages, tools=None, **settings):
            self.captured_messages = messages
            return AssistantTurn(text="Text response", finish_reason="stop")

        def capabilities(self, model):
            return capabilities_for(model)

    provider = CapturingTextProvider()
    engine = build_engine(
        agent=chat_agent(),
        model="qwen2.5-coder:32b",
        provider=provider,
        workspace=tmp_path,
    )

    image_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    user_content = build_user_content(
        "What text is on this image?",
        [{"kind": "image", "data_url": image_data_url}],
    )

    engine.messages.append({"role": "user", "content": user_content})
    outbound = engine._outbound_messages()

    user_msg = next(m for m in outbound if m.get("role") == "user")
    parts = user_msg["content"]
    assert isinstance(parts, list)

    # No image_url parts should remain
    image_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(image_parts) == 0

    # Placeholder text part must be present
    text_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "text"]
    placeholder_parts = [p for p in text_parts if "[image attachment — not viewable by this model]" in p.get("text", "")]
    assert len(placeholder_parts) == 1


# ---------------------------------------------------------------------------
# 8. End-to-end engine.run() flow with image question
# ---------------------------------------------------------------------------
async def test_end_to_end_vision_turn_preserves_image(tmp_path):
    class EchoVisionProvider(ProviderClient):
        def __init__(self):
            self.last_messages = None

        def complete(self, *, model, messages, tools=None, **settings):
            self.last_messages = messages
            # Find image in user messages
            user_msg = next((m for m in messages if m.get("role") == "user"), None)
            if user_msg and isinstance(user_msg.get("content"), list):
                has_image = any(p.get("type") == "image_url" for p in user_msg["content"] if isinstance(p, dict))
                if has_image:
                    return AssistantTurn(text="The image contains: MARATHON MIND OVER MILES 16/02/2026", finish_reason="stop")
            return AssistantTurn(text="I cannot view image attachments.", finish_reason="stop")

        def capabilities(self, model):
            return capabilities_for(model)

    provider = EchoVisionProvider()
    engine = build_engine(
        agent=chat_agent(),
        model="qwen3-vl8b",
        provider=provider,
        workspace=tmp_path,
    )

    image_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    user_content = build_user_content(
        "What text is written on this image?",
        [{"kind": "image", "data_url": image_data_url}],
    )

    events = []
    async for event in engine.run(user_content):
        events.append(event)

    assert provider.last_messages is not None
    user_msg = next(m for m in provider.last_messages if m.get("role") == "user")
    parts = user_msg["content"]
    image_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == image_data_url

    # Check assistant reply in history
    assistant_msg = next(m for m in engine.messages if m.get("role") == "assistant")
    assert "MARATHON" in assistant_msg["content"]

