from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .config import Settings
from .models import LLMResponse, LLMUsage


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4000,
        thinking: bool = False,
        reasoning_effort: str = "low",
        json_mode: bool = False,
    ) -> LLMResponse:
        if not self.settings.api_key:
            raise DeepSeekError(
                "未设置 DeepSeek API Key。请设置 DEEPSEEK_API_KEY 环境变量，"
                "或在本地界面当前会话中输入。"
            )
        selected_model = model or self.settings.default_model
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "stream": False,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if thinking:
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["temperature"] = 0.7
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw = self._request_json(request)

        try:
            choice = raw["choices"][0]
            message = choice["message"]
            usage_raw = raw.get("usage") or {}
            usage = LLMUsage(
                prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
                completion_tokens=int(usage_raw.get("completion_tokens", 0)),
                cache_hit_tokens=int(usage_raw.get("prompt_cache_hit_tokens", 0)),
                cache_miss_tokens=int(usage_raw.get("prompt_cache_miss_tokens", 0)),
            )
            return LLMResponse(
                content=message.get("content") or "",
                reasoning_content=message.get("reasoning_content") or "",
                finish_reason=choice.get("finish_reason") or "",
                model=raw.get("model") or selected_model,
                usage=usage,
                raw=raw,
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DeepSeekError(f"无法解析 DeepSeek API 响应: {raw}") from error

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        # Long JSON responses (especially V2 state updates) are more likely to be
        # interrupted by a transient TLS EOF.  Retry the identical request with
        # increasing pauses; callers persist the approved draft, so this never
        # forces chapter text to be generated again.
        attempts = 5
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.settings.request_timeout_seconds
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                    raise DeepSeekError(
                        f"DeepSeek API 返回 HTTP {error.code}: {body[:800]}"
                    ) from error
            except urllib.error.URLError as error:
                if getattr(error.reason, "winerror", None) == 10013 or "10013" in str(error.reason):
                    raise DeepSeekError(
                        "当前运行进程被 Windows 或沙箱禁止访问外网（WinError 10013）。"
                        "请允许 Python/Streamlit 访问网络，或在普通PowerShell中启动本项目后重试。"
                    ) from error
                if attempt == attempts:
                    raise DeepSeekError(
                        f"无法连接DeepSeek API：{error.reason}，已自动重试{attempts}次"
                    ) from error
            except (http.client.IncompleteRead, ConnectionError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == attempts:
                    raise DeepSeekError(
                        f"DeepSeek响应在传输中断开，已自动重试{attempts}次："
                        f"{type(error).__name__}"
                    ) from error
            # 2, 4, 8, 16 seconds. This gives a short-lived provider/network
            # interruption time to clear without making normal failures hang.
            time.sleep(float(2 ** attempt))
        raise DeepSeekError("DeepSeek API请求失败")

    def test_connection(self, *, model: str | None = None) -> LLMResponse:
        """Make a tiny real completion request to validate the key, endpoint and model."""
        return self.complete(
            [
                {
                    "role": "user",
                    "content": "这是API连接测试。请只回复：连接成功",
                }
            ],
            model=model,
            max_tokens=16,
            thinking=False,
        )


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.rsplit("```", 1)[0].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise DeepSeekError("模型没有返回有效 JSON") from error
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as nested_error:
            raise DeepSeekError("模型返回的 JSON 无法解析") from nested_error
    if not isinstance(value, dict):
        raise DeepSeekError("模型 JSON 顶层必须是对象")
    return value
