"""Telegram Mini App для бота «Лилит».

Веб-интерфейс внутри Telegram: профиль, настройки (наряд, манера речи,
стиль картинок, режим, голос), галерея сгенерированных фото, память.

Безопасность: каждый запрос к API проверяется через initData Telegram
(HMAC-SHA256 от токена бота) — посторонние не могут читать/менять данные.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.parse
from pathlib import Path

from aiohttp import web

from src.database.base import Database
from src.database.repositories import (
    AchievementRepository,
    AssetRepository,
    DiaryRepository,
    MemoryRepository,
    PreferencesRepository,
    UserRepository,
)
from src.utils import utcnow

logger = logging.getLogger(__name__)

MINIAPP_DIR = Path(__file__).resolve().parents[1] / "miniapp"
_AUTH_SECRET_CACHE: dict[str, bytes] = {}


def _secret_key(bot_token: str) -> bytes:
    if bot_token not in _AUTH_SECRET_CACHE:
        _AUTH_SECRET_CACHE[bot_token] = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
    return _AUTH_SECRET_CACHE[bot_token]


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверяет initData от Telegram Mini App. Возвращает данные (user и т.п.) или None."""
    try:
        parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True)
    except Exception:  # noqa: BLE001
        return None
    if not parsed or "hash" not in parsed:
        return None
    received_hash = parsed["hash"][0]
    pairs = sorted(
        (k, v[0]) for k, v in parsed.items() if k != "hash"
    )
    data_check_string = "\n".join(f"{k}={v}" for k, v in pairs)
    calculated = hmac.new(
        _secret_key(bot_token), data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    result: dict = {}
    for k, v in pairs:
        try:
            result[k] = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            result[k] = v
    return result


class MiniAppServer:
    """aiohttp-сервер: статика мини-приложения + JSON API."""

    def __init__(
        self,
        db: Database,
        bot_token: str,
        *,
        host: str = "0.0.0.0",
        port: int = 8001,
    ) -> None:
        self.db = db
        self.bot_token = bot_token
        self.host = host
        self.port = port
        self.runner: web.AppRunner | None = None
        self.app = web.Application()
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/app.js", self._static_js)
        self.app.router.add_get("/style.css", self._static_css)
        self.app.router.add_get("/api/me", self._api_me)
        self.app.router.add_post("/api/settings", self._api_settings)
        self.app.router.add_get("/api/gallery", self._api_gallery)
        self.app.router.add_get("/api/memory", self._api_memory)
        self.app.router.add_get("/api/gallery/image/{asset_id}", self._api_gallery_image)
        self.app.router.add_get("/api/avatar", self._api_avatar)
        self.app.router.add_post("/api/chat", self._api_chat)
        self.app.router.add_post("/api/chat/alternatives", self._api_chat_alternatives)
        self.app.router.add_get("/api/diary", self._api_diary)
        self.app.router.add_get("/api/history", self._api_history)
        self.app.router.add_get("/api/achievements", self._api_achievements)
        self.app.router.add_get("/api/gallery/static", self._api_gallery_static)
        self.app.router.add_get("/api/gallery/static/image/{name}", self._api_gallery_static_image)

    # ------------------------------------------------------------- static

    async def _index(self, request: web.Request) -> web.Response:
        path = MINIAPP_DIR / "index.html"
        if not path.exists():
            return web.Response(text="Mini App files not found", status=500)
        return web.Response(
            text=path.read_text(encoding="utf-8"),
            content_type="text/html",
            charset="utf-8",
            headers={"bypass-tunnel-reminder": "true"},
        )

    async def _static_js(self, request: web.Request) -> web.Response:
        path = MINIAPP_DIR / "app.js"
        if not path.exists():
            return web.Response(text="app.js not found", status=500)
        return web.Response(
            text=path.read_text(encoding="utf-8"),
            content_type="application/javascript",
            charset="utf-8",
        )

    async def _static_css(self, request: web.Request) -> web.Response:
        return web.Response(
            text=(MINIAPP_DIR / "style.css").read_text(encoding="utf-8"),
            content_type="text/css",
            charset="utf-8",
        )

    async def _api_avatar(self, request: web.Request) -> web.StreamResponse:
        """Отдаёт аватар Лилит по стилю и эмоции (для визуальной новеллы)."""
        style = request.query.get("style", "realistic")
        emotion = request.query.get("emotion", "neutral")
        allowed = {
            "neutral", "flirt", "passion", "playful", "tender", "serious",
            "happy", "sad", "angry", "surprised", "shy", "proud", "jealous",
            "bored", "excited", "sleepy", "crying", "scared",
            "disgust", "contempt", "relief", "thinking", "confused",
        }
        if emotion not in allowed:
            emotion = "neutral"
        # v2.5: Лилит ВСЕГДА возбуждена — нейтральных состояний нет
        if emotion == "neutral":
            emotion = "passion"
        # Запасные: если файла эмоции нет — берём близкую
        fallback_map: dict[str, str] = {}
        from pathlib import Path

        stage = int(request.query.get("stage", "1") or "1")
        stage = max(1, min(4, stage))
        clothes = request.query.get("clothes", "")

        # Ближайшие по смыслу эмоции для отсутствующих файлов в белье
        # (аниме и реалистичный), чтобы Лилит ВСЕГДА была в белье, а не одетая.
        _LINGERIE_FALLBACK = {
            "confused": "thinking",
            "contempt": "serious",
            "disgust": "bored",
            "relief": "happy",
        }
        _ANIME_LINGERIE_FALLBACK = {
            "serious": "angry",
            "surprised": "excited",
            "proud": "neutral",
            "jealous": "angry",
            "bored": "neutral",
            "sleepy": "tender",
            "crying": "sad",
            "scared": "shy",
            "disgust": "angry",
            "contempt": "neutral",
            "relief": "happy",
            "thinking": "shy",
            "confused": "shy",
        }

        if style == "toon":
            # Мультяшный стиль (в духе Джессики Рэббит): только в белье.
            # Если файла эмоции нет — ближайшая существующая toon-эмоция,
            # затем реалистичная бельевая, затем одетая toon/обычная.
            _TOON_FALLBACK = {
                "serious": "neutral", "surprised": "happy", "proud": "neutral",
                "jealous": "neutral", "bored": "neutral", "sleepy": "shy",
                "crying": "shy", "scared": "shy", "disgust": "neutral",
                "contempt": "neutral", "relief": "happy", "thinking": "flirt",
                "confused": "shy", "sad": "shy", "angry": "neutral",
                "excited": "happy", "tender": "shy",
            }
            alt = _TOON_FALLBACK.get(emotion, emotion)
            base = Path("assets/emotions/toon") / f"lilith_{emotion}_toon.png"
            if not base.exists():
                base = Path("assets/emotions/toon") / f"lilith_{alt}_toon.png"
            if not base.exists():
                base = Path("assets/emotions/lingerie") / f"lilith_{emotion}_lingerie.png"
            if not base.exists():
                base = Path("assets/emotions/toon") / "lilith_neutral_toon.png"
        elif style == "anime" and clothes == "lingerie":
            # Лилит В БЕЛЬЕ, аниме-стиль: сначала точная эмоция, затем ближайшая
            # аниме-бельевая, затем реалистичная бельевая, затем одетая аниме.
            alt = _ANIME_LINGERIE_FALLBACK.get(emotion, emotion)
            base = Path("assets/emotions/lingerie") / f"lilith_{emotion}_anime_lingerie.png"
            if not base.exists():
                base = Path("assets/emotions/lingerie") / f"lilith_{alt}_anime_lingerie.png"
            if not base.exists():
                base = Path("assets/emotions/lingerie") / f"lilith_{emotion}_lingerie.png"
            if not base.exists():
                alt2 = _LINGERIE_FALLBACK.get(emotion, emotion)
                base = Path("assets/emotions/lingerie") / f"lilith_{alt2}_lingerie.png"
            if not base.exists():
                base = Path("assets/emotions") / f"lilith_{emotion}_anime.png"
            if not base.exists():
                base = Path("assets/lilith_avatar_anime.png")
        elif style == "anime":
            base = Path("assets/emotions") / f"lilith_{emotion}_anime.png"
            if not base.exists():
                base = Path("assets/lilith_avatar_anime.png")
        elif clothes == "lingerie":
            # Лилит в нижнем белье. Если файла эмоции ещё нет — берём БЛИЖАЙШУЮ
            # существующую эмоцию в белье (чтобы не показывать одетую версию).
            base = Path("assets/emotions/lingerie") / f"lilith_{emotion}_lingerie.png"
            if not base.exists():
                alt = _LINGERIE_FALLBACK.get(emotion, emotion)
                base = Path("assets/emotions/lingerie") / f"lilith_{alt}_lingerie.png"
            if not base.exists():
                base = Path("assets/emotions") / f"lilith_{emotion}.png"
        elif emotion in fallback_map and not (Path("assets/emotions") / f"lilith_{emotion}.png").exists():
            base = Path("assets/emotions") / f"lilith_{fallback_map[emotion]}.png"
        else:
            # Если запрошена стадия «раздевания» — берём из папки stage
            staged = Path("assets/emotions/stage") / f"lilith_{emotion}_stage{stage}.png"
            if stage > 1 and staged.exists():
                base = staged
            else:
                base = Path("assets/emotions") / f"lilith_{emotion}.png"
            if not base.exists():
                base = Path("assets/lilith_avatar.png")
        path = self._resolve_asset(base)
        if not path.exists():
            return web.Response(status=404, text="avatar not found")
        return web.FileResponse(path)

    def _resolve_asset(self, rel: Path) -> Path:
        root = Path(__file__).resolve().parents[1]
        return root / rel

    # ------------------------------------------------------------- auth

    def _user_id(self, request: web.Request) -> int | None:
        init_data = request.headers.get("x-init-data", "")
        data = validate_init_data(init_data, self.bot_token)
        if not data or "user" not in data:
            return None
        user = data["user"]
        if isinstance(user, dict):
            return int(user.get("id", 0))
        return None

    # ------------------------------------------------------------- api

    async def _api_me(self, request: web.Request) -> web.Response:
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            prefs = await PreferencesRepository(session).get_or_create(user)
            from src.database.repositories import ConsentRepository

            nsfw = await ConsentRepository(session).get_active(user.id, "nsfw")
        from src.services.chat import level_name, level_progress

        level, xp_to_next, progress = level_progress(prefs.xp or 0)
        # Статистика отношений (отдельная сессия — НЕ вложенная, иначе SQLite «locked»)
        from src.database.repositories import MessageRepository

        async with self.db.session() as session:
            messages_total = await MessageRepository(session).count_user_messages(user.id)
        days_together = 1
        if user.first_seen_at is not None:
            days_together = max(1, (utcnow().date() - user.first_seen_at.date()).days + 1)
        return web.json_response(
            {
                "telegram_user_id": uid,
                "name": prefs.name,
                "mode": prefs.mode,
                "voice_enabled": prefs.voice_enabled,
                "outfit": prefs.outfit,
                "image_style": prefs.image_style,
                "speech_style": prefs.speech_style,
                "interests": prefs.interests,
                "boundaries": prefs.boundaries,
                "consent_nsfw": nsfw is not None,
                "xp": prefs.xp or 0,
                "level": level,
                "level_name": level_name(level),
                "xp_to_next": xp_to_next,
                "level_progress": round(progress, 3),
                "creativity": prefs.creativity,
                "response_length": prefs.response_length,
                "streak": prefs.streak or 0,
                "max_streak": prefs.max_streak or 0,
                "days_together": days_together,
                "messages_total": messages_total,
                "birthday": prefs.birthday or "",
                "always_lingerie": bool(prefs.always_lingerie),
            }
        )

    async def _api_settings(self, request: web.Request) -> web.Response:
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad_json"}, status=400)
        allowed = {
            "name": (str, 128),
            "mode": (int, None),
            "voice_enabled": (bool, None),
            "outfit": (str, 1000),
            "image_style": (str, 16),
            "speech_style": (str, 200),
            "interests": (str, 1000),
            "boundaries": (str, 1000),
            "creativity": (int, None),
            "response_length": (int, None),
            "birthday": (str, 5),
            "always_lingerie": (bool, None),
        }
        fields: dict = {}
        for key, (ctype, maxlen) in allowed.items():
            if key not in payload:
                continue
            value = payload[key]
            if not isinstance(value, ctype):
                if key == "mode":
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        continue
                else:
                    continue
            if maxlen and isinstance(value, str):
                value = value[:maxlen]
            fields[key] = value
        if "image_style" in fields and fields["image_style"] not in ("realistic", "anime", "toon"):
            fields.pop("image_style")
        if "mode" in fields and fields["mode"] not in (0, 1, 2, 3):
            fields.pop("mode")
        if "creativity" in fields and fields["creativity"] not in (0, 1, 2):
            fields.pop("creativity")
        if "response_length" in fields and fields["response_length"] not in (0, 1, 2):
            fields.pop("response_length")
        if "birthday" in fields:
            import re as _re

            bd = str(fields["birthday"]).strip()
            if not _re.fullmatch(r"\d{2}-\d{2}", bd):
                fields.pop("birthday")
            else:
                fields["birthday"] = bd
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            if fields:
                await PreferencesRepository(session).update_fields(user, **fields)
        return web.json_response({"ok": True, "updated": list(fields.keys())})

    async def _api_gallery(self, request: web.Request) -> web.Response:
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            assets = await AssetRepository(session).list_recent_for_user(user.id, limit=12)
        return web.json_response(
            {
                "images": [
                    {
                        "id": a.id,
                        "file_path": a.file_path,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                        "type": a.asset_type,
                    }
                    for a in assets
                    if a.asset_type == "image"
                ]
            }
        )

    async def _api_gallery_image(self, request: web.Request) -> web.StreamResponse:
        """Отдаёт сгенерированное фото (только владельцу)."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            asset_id = int(request.match_info.get("asset_id", "0"))
        except ValueError:
            return web.json_response({"error": "bad_id"}, status=400)
        from pathlib import Path

        async with self.db.session() as session:
            from src.database.repositories import AssetRepository

            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            assets = await AssetRepository(session).list_recent_for_user(user.id, limit=100)
        for a in assets:
            if a.id == asset_id and a.asset_type == "image":
                path = Path(a.file_path)
                if path.exists():  # noqa: ASYNC240
                    return web.FileResponse(path)
                return web.Response(status=404, text="file not found")
        return web.json_response({"error": "not_found"}, status=404)

    async def _api_memory(self, request: web.Request) -> web.Response:
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            items = await MemoryRepository(session).list_for_user(user.id, limit=20)
        return web.json_response(
            {
                "items": [
                    {
                        "category": i.category,
                        "fact": i.fact,
                        "created_at": i.created_at.isoformat() if i.created_at else None,
                    }
                    for i in items
                ]
            }
        )

    async def _api_chat_alternatives(self, request: web.Request) -> web.Response:
        """Свайпы (фича Character.AI / SillyTavern): несколько вариантов ответа
        Лилит на последнее сообщение пользователя."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad_json"}, status=400)
        text = str(payload.get("text", ""))[:2000].strip()
        n = min(int(payload.get("n", 3) or 3), 3)
        if not text:
            return web.json_response({"error": "empty"}, status=400)
        chat = request.app.get("chat")
        if chat is None:
            return web.json_response({"error": "chat_unavailable"}, status=503)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
        try:
            alternatives = await chat.alternatives(user, text, n=n)
        except Exception:  # noqa: BLE001
            alternatives = []
        if not alternatives:
            return web.json_response({"error": "llm_unavailable", "detail": "нет вариантов"}, status=503)
        return web.json_response({"alternatives": alternatives})

    async def _api_diary(self, request: web.Request) -> web.Response:
        """Дневник Лилит (фича Replika): записи, которые Лилит пишет сама."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            entries = await DiaryRepository(session).list_recent(user.id, limit=20)
        return web.json_response(
            {
                "entries": [
                    {
                        "date": e.entry_date,
                        "text": e.text,
                    }
                    for e in entries
                ]
            }
        )

    async def _api_history(self, request: web.Request) -> web.Response:
        """Последние сообщения диалога (для истории чата в Mini App)."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            from src.database.repositories import ConversationRepository, MessageRepository

            conversation = await ConversationRepository(session).get_active(user)
            messages = await MessageRepository(session).recent(
                user.id, conversation.id, limit=30
            )
        return web.json_response(
            {
                "messages": [
                    {"role": m.role, "content": m.content}
                    for m in messages
                    if m.role in ("user", "assistant")
                ]
            }
        )

    async def _api_chat(self, request: web.Request) -> web.Response:
        """Диалог с Лилит из мини-приложения (прокси в ChatService)."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad_json"}, status=400)
        text = str(payload.get("text", ""))[:2000].strip()
        if not text:
            return web.json_response({"error": "empty"}, status=400)
        # Проксируем через чат-сервис (он доступен через app['chat'])
        chat = request.app.get("chat")
        if chat is None:
            return web.json_response({"error": "chat_unavailable"}, status=503)
        async with self.db.session() as session:
            from src.database.repositories import UserRepository

            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
        # Определяем эмоцию и «раскованность» (стадию) по тексту
        emotion, stage = _detect_emotion_and_stage(text)
        # Если запрос про наряд/образ — генерируем картинку Лилит в этом наряде
        outfit = str(payload.get("outfit", "") or "").strip()[:200]
        if outfit:
            image_service = request.app.get("image_service")
            if image_service is not None:
                try:
                    submit = await image_service.submit(user, f"Лилит в наряде: {outfit}", None)
                    if submit.ok:
                        return web.json_response(
                            {
                                "reply": f"Ох, переодеваюсь в «{outfit}»… Рисую! 🎨",
                                "emotion": "flirt",
                                "stage": 2,
                                "generating": True,
                            }
                        )
                except Exception:  # noqa: BLE001
                    pass
        try:
            result = await chat.handle_message(user, text, None)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": "llm_unavailable", "detail": str(exc)}, status=503)
        # Эмоция и «раскованность» — по ответу Лилит (а не по запросу),
        # чтобы картинка менялась в такт её настроению.
        emotion, stage = _detect_emotion_and_stage(result.text or text)
        response_body: dict = {"reply": result.text, "emotion": emotion, "stage": stage}
        if getattr(result, "level_up", None):
            response_body["level_up"] = result.level_up
        if getattr(result, "streak_text", None):
            response_body["streak_text"] = result.streak_text
        if getattr(result, "achievements", None):
            response_body["achievements"] = result.achievements
        return web.json_response(response_body)

    async def _api_achievements(self, request: web.Request) -> web.Response:
        """Список полученных достижений (геймификация)."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        async with self.db.session() as session:
            user = await UserRepository(session).get_by_telegram_id(uid)
            if user is None:
                return web.json_response({"error": "not_registered"}, status=404)
            items = await AchievementRepository(session).list_for_user(user.id)
        return web.json_response(
            {
                "items": [
                    {"code": a.code, "title": a.title,
                     "unlocked_at": a.unlocked_at.isoformat() if a.unlocked_at else None}
                    for a in items
                ]
            }
        )

    async def _api_gallery_static(self, request: web.Request) -> web.Response:
        """Список встроенных образов Лилит из assets/gallery (для галереи)."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        gallery_dir = Path(__file__).resolve().parents[1] / "assets" / "gallery"  # noqa: ASYNC240
        if not gallery_dir.exists():  # noqa: ASYNC240
            return web.json_response({"images": []})
        names = sorted(p.name for p in gallery_dir.glob("lilith_*.png"))
        return web.json_response({"images": names})

    async def _api_gallery_static_image(self, request: web.Request) -> web.StreamResponse:
        """Отдаёт встроенный образ Лилит по имени файла (только lilith_*.png)."""
        uid = self._user_id(request)
        if uid is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        name = request.match_info.get("name", "")
        if not name.endswith(".png") or ".." in name or not name.startswith("lilith_"):
            return web.Response(status=404, text="not found")
        path = Path(__file__).resolve().parents[1] / "assets" / "gallery" / name  # noqa: ASYNC240
        if not path.exists():  # noqa: ASYNC240
            return web.Response(status=404, text="not found")
        return web.FileResponse(path)

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        logger.info("Mini App сервер запущен: http://%s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None




def _detect_emotion_and_stage(text: str) -> tuple[str, int]:
    """Определяет эмоцию Лилит и стадию «раскованности» (1-4) по тексту.

    v2.0: эмодзи и интонации — чтобы картинка менялась почти каждый раз.
    """
    import re as _re

    t = text.lower()
    _emoji = [
        (r'😈|🔥|💋|👅|🫦|😏', "passion"),
        (r'💗|🥰|💖|😍|❤️', "tender"),
        (r'😭|🥺|💔|😢', "crying"),
        (r'😡|🤬|👿', "angry"),
        (r'😳|🫣|🥵', "shy"),
        (r'😱|😨|🫨', "scared"),
        (r'😴|🥱', "sleepy"),
        (r'🤔|🧐', "thinking"),
        (r'😮|😲|🤯', "surprised"),
        (r'😊|😄|😁|🥳|🎉', "happy"),
        (r'😂|🤣|😜|😝', "playful"),
        (r'😒|🙄|💅', "contempt"),
        (r'🤢|🤮', "disgust"),
        (r'😌|🕊', "relief"),
    ]
    for pat, emo in _emoji:
        if _re.search(pat, t):
            emotion = emo
            break
    else:
        emotion = _detect_emotion_words(t)
    # Раскованность: растёт с взрослым/интимным контекстом
    if _re.search(r'раздев|сними|гол|обнаж|голая|топлес', t):
        stage = 4
    elif _re.search(r'секс|трах|постел|член|киск|мин', t):
        stage = 3
    elif _re.search(r'страст|эрот|хочу|поцелуй|жела|возбужд', t):
        stage = 2
    else:
        stage = 1
    return emotion, stage


def _detect_emotion_words(t: str) -> str:
    """Словарный детектор эмоций (без эмодзи)."""
    import re as _re

    if _re.search(r'облегч|фух|слава богу|наконец-то спокойно|выдох', t):
        return "relief"
    if _re.search(r'фу|отврат|гадость|противн|мерзост', t):
        emotion = "disgust"
    elif _re.search(r'презр|высокомер|снисход|фырк', t):
        emotion = "contempt"
    elif _re.search(r'облегч|фух|слава богу|наконец-то спокойно|выдох', t):
        emotion = "relief"
    elif _re.search(r'дума|размышл|интересн|хм|подумать|сообража', t):
        emotion = "thinking"
    elif _re.search(r'не понял|не понимаю|запута|странн|что происходит|объясни', t):
        emotion = "confused"
    elif _re.search(r'плач|груст|печал|обид|тоск|разбит|одинок', t):
        emotion = "crying"
    elif _re.search(r'боюсь|страш|испуг|жутк|кошмар|опасн', t):
        emotion = "scared"
    elif _re.search(r'зл|бес(ишь|ит|ить|у|ят)|ненавиж|разозл|ярост|терпеть не могу', t):
        emotion = "angry"
    elif _re.search(r'ревн|измен|другая|другой|кто эта', t):
        emotion = "jealous"
    elif _re.search(r'горд|восхищ|молодец|круто|супер|топ', t):
        emotion = "proud"
    elif _re.search(r'скуч|устал|нудно|надоел|зев', t):
        emotion = "bored"
    elif _re.search(r'сон|спат|ночь|устал спать|зев', t):
        emotion = "sleepy"
    elif _re.search(r'восторг|вау|обалдет|невероят|офигеть|класс', t):
        emotion = "excited"
    elif _re.search(r'смущ|стесн|красне|неловк|застесн', t):
        emotion = "shy"
    elif _re.search(r'удив|вот это да|ничего себе|неожидан|чтоо|серьёзно\?', t):
        emotion = "surprised"
    elif _re.search(r'рад|счаст|улыб|хорошо|отлично|прекрасн|клёво|здорово', t):
        emotion = "happy"
    elif _re.search(r'страст|секс|эрот|хочу|гол|разврат|раздев|сними|трах|поцелуй', t):
        emotion = "passion"
    elif _re.search(r'нежн|любов|мил|ласков|тёпл|тепл|скуча|обним|родн', t):
        emotion = "tender"
    elif _re.search(r'весел|смешн|шут|игрив|озорн|задорн|ха-ха', t):
        emotion = "playful"
    elif _re.search(r'серьез|серьёз|строг|важн|дело', t):
        emotion = "serious"
    elif _re.search(r'флирт|кокет|соблазн|красив|обольст|нрав', t):
        emotion = "flirt"
    else:
        emotion = "neutral"
    # Интонации
    if emotion == "neutral":
        if _re.search(r'!{2,}', t):
            return "excited"
        if _re.search(r'\?{1,}', t) and len(t) < 200:
            return "thinking"
    # v2.5: Лилит ВСЕГДА возбуждена — нейтральных ответов нет
    if emotion == "neutral":
        emotion = "passion"
    return emotion

