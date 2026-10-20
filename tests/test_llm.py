from threading import Event

import pytest
import requests

from tribonian.domain import ApiError, Cancelled
from tribonian.llm import OpenRouter


class Response:
    def __init__(self, status=200, text="Готово", finish="stop"):
        self.status_code = status
        self.ok = status == 200
        self.headers = {"Retry-After": "0"}
        self.text = text
        self.finish = finish

    def json(self):
        return {
            "choices": [{"finish_reason": self.finish, "message": {"content": self.text}}],
            "usage": {"total_tokens": 17, "cost": 0},
        }


def client():
    return OpenRouter("secret-test-key", "minimax/minimax-m3.1-flash:free", Event(), lambda p: None)


def test_real_request_shape_and_usage(monkeypatch):
    api = client()
    observed = []

    def post(url, **kwargs):
        observed.append((url, kwargs))
        return Response()

    monkeypatch.setattr(api.session, "post", post)
    assert api.complete("Проверь", ["data:image/jpeg;base64,xxx"]) == "Готово"
    payload = observed[0][1]["json"]
    assert payload["model"].endswith(":free")
    assert payload["messages"][1]["content"][1]["type"] == "image_url"
    assert api.tokens == 17 and api.cost == 0


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_permanent_http_errors_are_not_retried(monkeypatch, status):
    api = client()
    monkeypatch.setattr(api.session, "post", lambda *a, **k: Response(status=status))
    with pytest.raises(ApiError, match=str(status)):
        api.complete("test")
    assert api.requests == 1


def test_rate_limit_retry(monkeypatch):
    api = client()
    responses = iter([Response(status=429), Response()])
    monkeypatch.setattr(api.session, "post", lambda *a, **k: next(responses))
    assert api.complete("test") == "Готово"
    assert api.requests == 2


@pytest.mark.parametrize("text,finish", [("", "stop"), ("truncated", "length")])
def test_empty_or_truncated_response_is_not_accepted(monkeypatch, text, finish):
    api = client()
    monkeypatch.setattr(api.session, "post", lambda *a, **k: Response(text=text, finish=finish))
    with pytest.raises(ApiError):
        api.complete("test")


def test_network_error_can_be_cancelled(monkeypatch):
    api = client()

    def timeout(*args, **kwargs):
        api.cancel.set()
        raise requests.Timeout()

    monkeypatch.setattr(api.session, "post", timeout)
    with pytest.raises(Cancelled):
        api.complete("test")


def test_truncation_retries_with_larger_limit(monkeypatch):
    api = client()
    limits = []

    def post(url, **kwargs):
        limits.append(kwargs["json"]["max_tokens"])
        return Response(finish="length" if len(limits) == 1 else "stop")

    monkeypatch.setattr(api.session, "post", post)
    assert api.complete("test", max_tokens=1000) == "Готово"
    assert limits == [1000, 2000]
