"""Тесты Mini App: валидация initData и API-эндпоинты."""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse

from src.miniapp_server import MiniAppServer, validate_init_data
from tests.conftest import onboard


def _make_init_data(bot_token: str, user_id: int, *, valid: bool = True) -> str:
    user = json.dumps({"id": user_id, "first_name": "Test", "is_bot": False})
    pairs = [("user", user), ("auth_date", "1700000000")]
    if not valid:
        pairs.append(("hash", "deadbeef" * 8))
        return urllib.parse.urlencode(pairs)
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs.append(("hash", digest))
    return urllib.parse.urlencode(pairs)


def test_validate_init_data_ok() -> None:
    token = "123:TESTTOKEN"
    init = _make_init_data(token, 777)
    data = validate_init_data(init, token)
    assert data is not None
    assert data["user"]["id"] == 777


def test_validate_init_data_wrong_token() -> None:
    init = _make_init_data("123:TESTTOKEN", 777)
    assert validate_init_data(init, "999:OTHER") is None


def test_validate_init_data_tampered() -> None:
    init = _make_init_data("123:TESTTOKEN", 777, valid=False)
    assert validate_init_data(init, "123:TESTTOKEN") is None


async def test_miniapp_api_me(ctx, fake_llm) -> None:
    token = "123:TESTTOKEN"
    await onboard(ctx, 8888, nsfw=True)
    server = MiniAppServer(ctx.db, token)
    init = _make_init_data(token, 8888)
    request = _FakeRequest(headers={"x-init-data": init})
    resp = await server._api_me(request)
    data = json.loads(resp.body)
    assert data["telegram_user_id"] == 8888
    assert data["consent_nsfw"] is True


async def test_miniapp_api_settings(ctx) -> None:
    token = "123:TESTTOKEN"
    await onboard(ctx, 8889, nsfw=True)
    server = MiniAppServer(ctx.db, token)
    init = _make_init_data(token, 8889)
    request = _FakeRequest(
        headers={"x-init-data": init},
        body=json.dumps({"outfit": "кружевное бельё", "speech_style": "страстно"}),
    )
    resp = await server._api_settings(request)
    data = json.loads(resp.body)
    assert data["ok"] is True
    from src.database.repositories import PreferencesRepository, UserRepository

    async with ctx.db.session() as session:
        u = await UserRepository(session).get_by_telegram_id(8889)
        prefs = await PreferencesRepository(session).get_or_create(u)
        assert prefs.outfit == "кружевное бельё"
        assert prefs.speech_style == "страстно"


async def test_miniapp_api_unauthorized(ctx) -> None:
    server = MiniAppServer(ctx.db, "123:TESTTOKEN")
    request = _FakeRequest(headers={"x-init-data": "hash=bad"})
    resp = await server._api_me(request)
    assert resp.status == 401


class _FakeRequest:
    def __init__(self, *, headers: dict, body: str = "") -> None:
        self.headers = headers
        self._body = body

    async def json(self):
        return json.loads(self._body)
