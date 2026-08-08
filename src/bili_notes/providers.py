from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderPreset:
    provider_id: str
    label: str
    protocol: str
    base_url: str
    model: str
    api_key_env: str


@dataclass(frozen=True)
class EndpointConfig:
    provider: str
    label: str
    protocol: str
    base_url: str
    model: str
    api_key_env: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
        }


@dataclass(frozen=True)
class LLMSettings:
    text: EndpointConfig

    def fingerprint_payload(self) -> dict[str, Any]:
        return {"text": self.text.public_dict()}


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "codex": ProviderPreset("codex", "Codex", "codex", "", "", ""),
    "deepseek": ProviderPreset(
        "deepseek",
        "DeepSeek",
        "openai-chat",
        "https://api.deepseek.com",
        "deepseek-v4-flash",
        "DEEPSEEK_API_KEY",
    ),
    "openai": ProviderPreset(
        "openai",
        "OpenAI",
        "openai-chat",
        "https://api.openai.com/v1",
        "gpt-5.6-terra",
        "OPENAI_API_KEY",
    ),
    "qwen": ProviderPreset(
        "qwen",
        "通义千问",
        "openai-chat",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3.7-plus",
        "DASHSCOPE_API_KEY",
    ),
    "gemini": ProviderPreset(
        "gemini",
        "Google Gemini",
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        "gemini-3.6-flash",
        "GEMINI_API_KEY",
    ),
    "anthropic": ProviderPreset(
        "anthropic",
        "Anthropic Claude",
        "anthropic",
        "https://api.anthropic.com",
        "claude-sonnet-5",
        "ANTHROPIC_API_KEY",
    ),
    "kimi": ProviderPreset(
        "kimi",
        "Moonshot Kimi",
        "openai-chat",
        "https://api.moonshot.cn/v1",
        "kimi-k3",
        "MOONSHOT_API_KEY",
    ),
    "zhipu": ProviderPreset(
        "zhipu",
        "智谱 GLM",
        "openai-chat",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-5.2",
        "ZHIPU_API_KEY",
    ),
    "custom-openai": ProviderPreset(
        "custom-openai",
        "自定义 OpenAI-compatible",
        "openai-chat",
        "",
        "",
        "",
    ),
}

DEFAULT_SETTINGS = {
    "schema_version": 1,
    "text": {"provider": "codex", "model": "", "base_url": ""},
}

KEYRING_SERVICE = "bilibili-video-notes"


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "provider": preset.provider_id,
            "label": preset.label,
            "protocol": preset.protocol,
            "base_url": preset.base_url,
            "model": preset.model,
        }
        for preset in PROVIDER_PRESETS.values()
    ]


def _settings_path(project_root: Path) -> Path:
    return project_root / ".state" / "llm-settings.json"


def _read_settings(project_root: Path) -> dict[str, Any]:
    settings_path = _settings_path(project_root)
    if not settings_path.is_file():
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        value = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderError("AI 设置文件损坏，请在 AI 设置中重新保存。") from exc
    if not isinstance(value, dict):
        raise ProviderError("AI 设置文件格式无效。")
    return value


def _endpoint_from_value(value: dict[str, Any]) -> EndpointConfig:
    provider_id = str(value.get("provider") or "codex")
    preset = PROVIDER_PRESETS.get(provider_id)
    if not preset:
        raise ProviderError(f"未知 AI Provider：{provider_id}")
    model = str(value.get("model") or preset.model).strip()
    base_url = str(value.get("base_url") or preset.base_url).strip().rstrip("/")
    if preset.protocol != "codex" and not model:
        raise ProviderError(f"{preset.label} 缺少模型名称。")
    if preset.protocol != "codex" and not base_url:
        raise ProviderError(f"{preset.label} 缺少 Base URL。")
    return EndpointConfig(
        provider=provider_id,
        label=preset.label,
        protocol=preset.protocol,
        base_url=base_url,
        model=model,
        api_key_env=preset.api_key_env,
    )


def load_llm_settings(project_root: Path) -> LLMSettings:
    raw = _read_settings(project_root)
    text_value = dict(raw.get("text") or {})
    overrides = {
        "provider": os.environ.get("BILI_NOTES_TEXT_PROVIDER"),
        "model": os.environ.get("BILI_NOTES_TEXT_MODEL"),
        "base_url": os.environ.get("BILI_NOTES_TEXT_BASE_URL"),
    }
    text_value.update({key: value for key, value in overrides.items() if value})
    return LLMSettings(text=_endpoint_from_value(text_value))


def _keyring_get(provider: str) -> str:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, f"text:{provider}") or ""
    except Exception:
        return ""


def _keyring_set(provider: str, api_key: str) -> None:
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, f"text:{provider}", api_key)
    except Exception as exc:
        raise ProviderError("无法写入 Windows 凭据库，请改用环境变量提供 API Key。") from exc


def resolve_api_key(config: EndpointConfig) -> str:
    role_env = os.environ.get("BILI_NOTES_TEXT_API_KEY", "").strip()
    provider_env = os.environ.get(config.api_key_env, "").strip() if config.api_key_env else ""
    return role_env or provider_env or _keyring_get(config.provider)


def has_api_key(config: EndpointConfig) -> bool:
    return config.protocol == "codex" or bool(resolve_api_key(config))


def public_settings(project_root: Path) -> dict[str, Any]:
    settings = load_llm_settings(project_root)
    return {
        "ok": True,
        "text": {**settings.text.public_dict(), "has_api_key": has_api_key(settings.text)},
        "presets": provider_catalog(),
    }


def save_llm_settings(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    text_value = {
        "provider": str(payload.get("text_provider") or "codex"),
        "model": str(payload.get("text_model") or ""),
        "base_url": str(payload.get("text_base_url") or ""),
    }
    text = _endpoint_from_value(text_value)
    api_key = str(payload.get("text_api_key") or "").strip()
    if api_key:
        _keyring_set(text.provider, api_key)
    settings_path = _settings_path(project_root)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    stored = {"schema_version": 1, "text": text_value}
    settings_path.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return public_settings(project_root)


def _join_endpoint(base_url: str, suffix: str) -> str:
    if base_url.rstrip("/").endswith(suffix):
        return base_url.rstrip("/")
    return base_url.rstrip("/") + suffix


def _request_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout: int = 600,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "bilibili-video-notes/0.2",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        for value in headers.values():
            secret = value.removeprefix("Bearer ").strip()
            if secret:
                body = body.replace(secret, "[REDACTED]")
        raise ProviderError(f"{exc.code} API 请求失败：{body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"API 连接失败：{exc}") from exc
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderError("API 返回了无法解析的 JSON。") from exc
    if not isinstance(value, dict):
        raise ProviderError("API 返回结构无效。")
    return value


class ProviderClient:
    def __init__(self, config: EndpointConfig):
        self.config = config
        self.api_key = resolve_api_key(config)
        if config.protocol != "codex" and not self.api_key:
            key_hint = config.api_key_env or "BILI_NOTES_TEXT_API_KEY"
            raise ProviderError(
                f"{config.label} 尚未配置 API Key。请打开 AI 设置，或设置 {key_hint}。"
            )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 6000,
        temperature: float = 0.2,
    ) -> str:
        if self.config.protocol == "openai-chat":
            return self._openai_chat(system_prompt, user_prompt, max_tokens, temperature)
        if self.config.protocol == "gemini":
            return self._gemini(system_prompt, user_prompt, max_tokens, temperature)
        if self.config.protocol == "anthropic":
            return self._anthropic(system_prompt, user_prompt, max_tokens, temperature)
        raise ProviderError(f"{self.config.label} 需要由专用运行器调用。")

    def _openai_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }
        if self.config.provider not in {"openai", "kimi"}:
            payload["temperature"] = temperature
        if self.config.provider == "openai":
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        if self.config.provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        response = _request_json(
            _join_endpoint(self.config.base_url, "/chat/completions"),
            {"Authorization": f"Bearer {self.api_key}"},
            payload,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI-compatible API 没有返回正文。") from exc
        if isinstance(content, list):
            content = "".join(
                str(item.get("text") or "") for item in content if isinstance(item, dict)
            )
        return str(content or "").strip()

    def _gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        model = urllib.parse.quote(self.config.model, safe="-._")
        response = _request_json(
            _join_endpoint(self.config.base_url, f"/models/{model}:generateContent"),
            {"x-goog-api-key": self.api_key},
            {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                },
            },
        )
        try:
            blocks = response["candidates"][0]["content"]["parts"]
            content = "".join(str(item.get("text") or "") for item in blocks)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Gemini API 没有返回正文。") from exc
        return content.strip()

    def _anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = _request_json(
            _join_endpoint(self.config.base_url, "/v1/messages"),
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            {
                "model": self.config.model,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}]}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        try:
            content_blocks = response["content"]
            text = "".join(
                str(item.get("text") or "")
                for item in content_blocks
                if isinstance(item, dict) and item.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError("Anthropic API 没有返回正文。") from exc
        return text.strip()
