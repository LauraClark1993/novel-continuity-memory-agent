import http.client
import json

from novel_memory_agent.config import Settings
from novel_memory_agent.deepseek import DeepSeekClient
from novel_memory_agent.models import LLMResponse


class RecordingClient(DeepSeekClient):
    def __init__(self) -> None:
        super().__init__(Settings(api_key="test-key"))
        self.last_messages = None
        self.last_kwargs = None

    def complete(self, messages, **kwargs) -> LLMResponse:
        self.last_messages = messages
        self.last_kwargs = kwargs
        return LLMResponse(content="连接成功", model="deepseek-v4-flash")


def test_connection_uses_tiny_non_thinking_request() -> None:
    client = RecordingClient()
    response = client.test_connection()
    assert response.content == "连接成功"
    assert client.last_kwargs["max_tokens"] == 16
    assert client.last_kwargs["thinking"] is False


def test_transport_incomplete_read_is_retried(monkeypatch) -> None:
    calls = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [{"message": {"content": "连接成功"}, "finish_reason": "stop"}],
                    "usage": {},
                }
            ).encode()

    def fake_urlopen(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        if calls < 3:
            raise http.client.IncompleteRead(b"")
        return Response()

    monkeypatch.setattr("novel_memory_agent.deepseek.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("novel_memory_agent.deepseek.time.sleep", lambda _: None)
    client = DeepSeekClient(Settings(api_key="test-key"))
    response = client.test_connection()
    assert response.content == "连接成功"
    assert calls == 3
