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


async def test_miniapp_api_me_no_nested_session(ctx) -> None:
    """api/me работает без вложенных сессий (лечит 500 в SQLite)."""
    token = "123:TESTTOKEN"
    await onboard(ctx, 8890, nsfw=True)
    server = MiniAppServer(ctx.db, token)
    init = _make_init_data(token, 8890)
    request = _FakeRequest(headers={"x-init-data": init})
    resp = await server._api_me(request)
    assert resp.status == 200, resp.body
    data = json.loads(resp.body)
    assert data["consent_nsfw"] is True


async def test_miniapp_static_pages_serve_200(ctx) -> None:
    """Статика Mini App отдаётся без 500 (content_type без charset в строке)."""
    import aiohttp

    server = MiniAppServer(ctx.db, "123:TESTTOKEN")
    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            for path in ("/", "/app.js", "/style.css"):
                async with session.get(f"http://127.0.0.1:8001{path}") as r:
                    assert r.status == 200, f"{path} -> {r.status}"
                    text = await r.text()
                    assert len(text) > 0
    finally:
        await server.stop()


async def test_miniapp_avatar_all_emotions(ctx) -> None:
    """Все 18 эмоций отдаются (crying/scared — через fallback)."""
    import aiohttp

    server = MiniAppServer(ctx.db, "123:TESTTOKEN")
    await server.start()
    emotions = ["neutral", "flirt", "passion", "playful", "tender", "serious",
                "happy", "sad", "angry", "surprised", "shy", "proud", "jealous",
                "bored", "excited", "sleepy", "crying", "scared"]
    try:
        async with aiohttp.ClientSession() as session:
            for emo in emotions:
                async with session.get(f"http://127.0.0.1:8001/api/avatar?style=realistic&emotion={emo}") as r:
                    assert r.status == 200, f"{emo} -> {r.status}"
    finally:
        await server.stop()


async def test_detect_emotion_new() -> None:
    """Детектор эмоций распознаёт новые эмоции."""
    from src.miniapp_server import _detect_emotion_and_stage

    assert _detect_emotion_and_stage("мне грустно без тебя")[0] == "crying"
    assert _detect_emotion_and_stage("я так рада")[0] == "happy"
    assert _detect_emotion_and_stage("ты меня бесишь")[0] == "angry"
    assert _detect_emotion_and_stage("хочу тебя")[0] == "passion"


def test_miniapp_js_no_dead_reference() -> None:
    """app.js НЕ должен вызывать неопределённые функции — иначе весь скрипт
    падает при загрузке и Mini App «не нажимается» (кнопки, чат, аватар)."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "miniapp" / "app.js").read_text(encoding="utf-8")
    # generateOutfit вызывается в addEventListener — должна быть и определена
    assert "function generateOutfit" in js
    assert "generate-outfit" in js
    # Баланс скобок/фигурных скобок — скрипт хотя бы синтаксически цел
    assert js.count("{") == js.count("}"), "несбалансированные фигурные скобки в app.js"
    assert js.count("(") == js.count(")"), "несбалансированные круглые скобки в app.js"
    # Все id, к которым обращается JS, существуют в index.html
    # (кроме динамических, создаваемых в рантайме)
    import re

    html = (Path(__file__).resolve().parents[1] / "miniapp" / "index.html").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r'el\("([^"]+)"\)', js))
    dynamic = {"typing-row"}  # создаётся в рантайме
    missing = js_ids - html_ids - dynamic
    assert not missing, f"JS обращается к несуществующим id: {missing}"


async def test_miniapp_history(ctx) -> None:
    """/api/history возвращает последние сообщения диалога."""
    import hashlib
    import hmac
    import json as _json
    import urllib.parse

    from src.miniapp_server import MiniAppServer

    token = "123:TESTTOKEN"
    await onboard(ctx, 7777, nsfw=True)
    server = MiniAppServer(ctx.db, token)

    user_json = _json.dumps({"id": 7777, "first_name": "T", "is_bot": False})
    pairs = [("user", user_json), ("auth_date", "1700000000")]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    init = urllib.parse.urlencode(pairs + [("hash", digest)])

    # Пишем пару сообщений в диалог пользователя
    from src.database.repositories import ConversationRepository, MessageRepository, UserRepository

    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(7777)
        conversation = await ConversationRepository(session).get_active(user)
        await MessageRepository(session).add(conversation, "user", "привет")
        await MessageRepository(session).add(conversation, "assistant", "привет, дорогой")

    class _Req:
        headers = {"x-init-data": init}

        async def json(self):
            return {}

    resp = await server._api_history(_Req())
    assert resp.status == 200, resp.body
    data = _json.loads(resp.body)
    roles = [m["role"] for m in data["messages"]]
    assert "user" in roles and "assistant" in roles
    assert any(m["content"] == "привет, дорогой" for m in data["messages"])
