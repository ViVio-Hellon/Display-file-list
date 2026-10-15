"""小さな Web の土台(標準ライブラリだけ)

Flask を入れられない端末向けに、使う分だけを持つ:
要求 / 応答 / 経路表 / 断りの形。

断りは python-web-tools と同じ形で返す。

    HTTP ステータス + {"error": {"code": "...", "message": "現場向けの日本語"}}

    400 入力の形が違う / 403 資格が無い / 404 無い /
    409 別の誰かが先に変えていた / 422 形は正しいが業務として断る
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import parse_qs


@dataclass
class Request:
    method: str
    path: str
    query: dict = field(default_factory=dict)      # 名前 → 最初の値
    headers: dict = field(default_factory=dict)    # 小文字の名前 → 値
    body: bytes = b""

    @classmethod
    def build(cls, method: str, target: str, headers: dict, body: bytes = b"") -> "Request":
        path, _, qs = target.partition("?")
        query = {k: v[0] for k, v in parse_qs(qs, keep_blank_values=True).items()}
        return cls(method=method.upper(), path=path, query=query,
                   headers={k.lower(): v for k, v in headers.items()}, body=body)

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HttpError(400, "bad_json", "送られた内容を読めませんでした。")
        if not isinstance(data, dict):
            raise HttpError(400, "bad_json", "送られた内容の形が違います。")
        return data


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: dict = field(default_factory=dict)


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 extra: Optional[dict] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}

    def to_response(self) -> Response:
        payload = {"error": {"code": self.code, "message": self.message}}
        payload.update(self.extra)
        return json_response(payload, self.status)


def json_response(data: Any, status: int = 200) -> Response:
    return Response(status=status,
                    body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                    content_type="application/json; charset=utf-8")


def html_response(text: str, status: int = 200) -> Response:
    return Response(status=status, body=text.encode("utf-8"),
                    content_type="text/html; charset=utf-8")


Handler = Callable[[Request], Response]


class Router:
    def __init__(self) -> None:
        self._routes: dict = {}

    def add(self, method: str, path: str, handler: Handler) -> None:
        self._routes[(method.upper(), path)] = handler

    def get(self, path: str) -> Callable[[Handler], Handler]:
        return self._decorator("GET", path)

    def post(self, path: str) -> Callable[[Handler], Handler]:
        return self._decorator("POST", path)

    def _decorator(self, method: str, path: str) -> Callable[[Handler], Handler]:
        def wrap(func: Handler) -> Handler:
            self.add(method, path, func)
            return func
        return wrap

    def find(self, method: str, path: str) -> Optional[Handler]:
        return self._routes.get((method, path))

    def allows(self, path: str) -> list:
        return sorted(m for (m, p) in self._routes if p == path)


def require_text(data: dict, key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise HttpError(400, "bad_field", f"{key} は文字で送ってください。")
    return value


def require_bool(data: dict, key: str) -> bool:
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise HttpError(400, "bad_field", f"{key} は true / false で送ってください。")
    return value
