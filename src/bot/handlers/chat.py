"""Обработка обычных текстовых сообщений: диалог с персонажем."""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.bot.di import AppContext
from src.bot.states import PhotoStates, SettingsStates
from src.database.models import User as DbUser
from src.database.repositories import PreferencesRepository
from src.providers.base import LLMUnavailable

logger = logging.getLogger(__name__)

router = Router()

# Фразы, по которым бот понимает «пользователь хочет картинку» без команды /photo
_PHOTO_INTENT = re.compile(
    r"^(нарисуй|нарисуй-ка|сгенерируй|сгенерируй-ка|покажи|покажи-ка|сделай|сделай-ка|"
    r"создай|создай-ка|пришли|пришли-ка|кинь|кинь-ка|сбрось|сбрось-ка|"
    r"хочу\s+(увидеть|картинку|фото|рисунок|фотку|фотки)|дай\s+(картинку|фото|рисунок|фотку|фотки)|"
    r"картинку|картинки|фотографию|фотку|фотки|фото|изобрази)\b",
    re.IGNORECASE,
)

# Пока пользователь редактирует настройки — его тексты идут в FSM-хендлеры
_FSM_STATES = (
    SettingsStates.name,
    SettingsStates.address_term,
    SettingsStates.pronouns,
    SettingsStates.interests,
    SettingsStates.boundaries,
    PhotoStates.prompt,
)


@router.message(
    F.text,
    ~F.text.regexp(r"^/"),
    StateFilter(*_FSM_STATES),
)
async def on_text_fsm(message: Message, bot: Bot, state: FSMContext) -> None:
    """Текст во время FSM-операции — игнорируем с подсказкой /cancel."""
    current = await state.get_state()
    labels = {
        "SettingsStates:name": "имя",
        "SettingsStates:address_term": "обращение",
        "SettingsStates:pronouns": "местоимения",
        "SettingsStates:interests": "интересы",
        "SettingsStates:boundaries": "границы",
        "PhotoStates:prompt": "запрос картинки",
    }
    label = labels.get(current or "", "действие")
    await bot.send_message(
        chat_id=message.chat.id,
        text=f"Сначала заверши текущее действие ({label}) или отправь /cancel.",
    )


@router.message(F.text, ~F.text.regexp(r"^/"))
async def on_text(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is None or user.consent_step != "active":
        await bot.send_message(
            chat_id=message.chat.id,
            text="Сначала познакомимся: нажми /start 🌸",
        )
        return
    # Показываем «Лилит печатает…», чтобы было видно, что бот думает
    # (локальные модели отвечают 5–30 секунд — без индикатора кажется, что завис)
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:  # noqa: BLE001
        pass
    text = message.text or ""
    if len(text) > app_ctx.settings.max_message_length:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Сообщение слишком длинное (максимум {app_ctx.settings.max_message_length} символов).",
        )
        return

    # Пользователь просит Лилит переодеться — меняем наряд и сразу рисуем
    _DRESS_INTENT = re.compile(
        r"^(переоденься|переодень|надень|наден|смени\s+образ|смени\s+наряд|оденься|"
        r"нарядись|переодень\s+меня|раздевайся|сними)\b",
        re.IGNORECASE,
    )
    dress_match = _DRESS_INTENT.search(text)
    if dress_match:
        outfit_desc = _DRESS_INTENT.sub("", text).strip(" ,.!?:;-")
        outfit_desc = re.sub(r"^(в|во|в\\s+)?", "", outfit_desc).strip()
        outfit_desc = re.sub(r"\\s+", " ", outfit_desc)
        # «раздевайся» / «в белье» — спец-наряд
        if re.search(r"бель|раздевай|сними одежд", outfit_desc, re.I) and not re.search(
            r"костюм|платье|юбк|наряд", outfit_desc, re.I
        ):
            outfit_desc = "только чёрное кружевное бельё и чулки на подвязках"
        if outfit_desc and len(outfit_desc) < 200:
            async with app_ctx.db.session() as session:
                await PreferencesRepository(session).update_fields(user, outfit=outfit_desc)
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"Ох, с удовольствием… Переодеваюсь: {outfit_desc} 😏",
            )
            from src.bot.handlers.commands import _submit_photo

            await _submit_photo(
                message, bot, app_ctx, user, f"Лилит {outfit_desc}, её фирменные чулки"
            )
            return

    # Пользователь просит Лилит сменить манеру речи
    _SPEECH_INTENT = re.compile(
        r"^(говори|разговаривай|общайся|будь|стань)\b",
        re.IGNORECASE,
    )
    speech_match = _SPEECH_INTENT.search(text)
    if speech_match:
        style_desc = _SPEECH_INTENT.sub("", text).strip(" ,.!?:;-")
        if style_desc and len(style_desc) < 150:
            async with app_ctx.db.session() as session:
                await PreferencesRepository(session).update_fields(user, speech_style=style_desc)
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"Как скажешь, мой дорогой. Теперь я говорю: {style_desc} 💋",
            )
            return

    # «Покажи себя» — показываем аватар Лилит (НЕ генерацию!)
    _SHOW_SELF = re.compile(
        r"(покажи\s+(мне\s+)?себя|как\s+ты\s+выгляд|покажи\s+свою\s+фото|"
        r"покажи\s+свою\s+фотку|покажи\s+свою\s+картинку|покажи\s+свой\s+аватар|"
        r"твоё\s+фото|твоя\s+фотка|покажи\s+как\s+ты\s+выглядишь)",
        re.IGNORECASE,
    )
    if _SHOW_SELF.search(text):
        from pathlib import Path

        async with app_ctx.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
        style = "anime" if prefs.image_style == "anime" else "realistic"

        # Определяем эмоцию по тексту («покажи себя страстной» -> passion) или случайную
        _EMOTION_WORDS = [
            (re.compile(r"плач|груст|печал|обид|тоск|одинок", re.I), "crying"),
            (re.compile(r"боюсь|страш|испуг|жутк|кошмар", re.I), "scared"),
            (re.compile(r"зл|бешу|ненавиж|разозл|ярост", re.I), "angry"),
            (re.compile(r"ревн|измен", re.I), "jealous"),
            (re.compile(r"горд|восхищ|молодец|круто|супер", re.I), "proud"),
            (re.compile(r"скуч|устал|нудно|надоел", re.I), "bored"),
            (re.compile(r"сонн|спат|ночь|спать", re.I), "sleepy"),
            (re.compile(r"восторг|вау|обалдет|невероят|офигеть", re.I), "excited"),
            (re.compile(r"брезгл|отврат|противн|гадость|фу", re.I), "disgust"),
            (re.compile(r"презр|высокомер|снисход", re.I), "contempt"),
            (re.compile(r"облегч|фух|выдох|спокойн", re.I), "relief"),
            (re.compile(r"задумч|дума|размышл|хм", re.I), "thinking"),
            (re.compile(r"растер|не понима|запута|странн|объясни", re.I), "confused"),
            (re.compile(r"смущ|стесн|красне|неловк", re.I), "shy"),
            (re.compile(r"удив|неожидан|ничего себе", re.I), "surprised"),
            (re.compile(r"рад|счаст|улыб|отлично|прекрасн|клёво|здорово", re.I), "happy"),
            (re.compile(r"страст|секс|эрот|хочу|гол|разврат", re.I), "passion"),
            (re.compile(r"весел|смешн|шут|игрив|озорн|задорн", re.I), "playful"),
            (re.compile(r"нежн|любов|мил|ласков|тёпл|тепл|скуча", re.I), "tender"),
            (re.compile(r"серьез|серьёз|строг|важн", re.I), "serious"),
            (re.compile(r"флирт|кокет|соблазн|красив|обольст", re.I), "flirt"),
        ]
        emotion = None
        for pattern, emo in _EMOTION_WORDS:
            if pattern.search(text):
                emotion = emo
                break
        if emotion is None:
            import random

            emotion = random.choice(
                ["neutral", "flirt", "passion", "playful", "tender", "serious",
                 "happy", "sad", "angry", "surprised", "shy", "proud", "jealous",
                 "bored", "excited", "sleepy", "crying", "scared",
                 "disgust", "contempt", "relief", "thinking", "confused"]
            )

        avatar = Path("assets/emotions") / f"lilith_{emotion}{'_anime' if style == 'anime' else ''}.png"
        if not avatar.exists():
            avatar = (
                Path("assets/lilith_avatar_anime.png")
                if style == "anime"
                else Path("assets/lilith_avatar.png")
            )
        avatar_path = app_ctx.settings.resolve_path(avatar)
        labels = {
            "neutral": "спокойная 😌", "flirt": "игривая 😏", "passion": "страстная 🔥",
            "playful": "озорная 😜", "tender": "нежная 💗", "serious": "серьёзная 😐",
            "happy": "радостная 😊", "sad": "грустная 😢", "angry": "злая 😠",
            "surprised": "удивлённая 😲", "shy": "смущённая 😳", "proud": "гордая 😎",
            "jealous": "ревнивая 😒", "bored": "скучающая 🥱", "excited": "восторженная 🤩",
            "sleepy": "сонная 😴", "crying": "плачущая 😭", "scared": "испуганная 😨",
            "disgust": "брезгливая 🤢", "contempt": "презрительная 🙄", "relief": "облегчённая 😮‍💨",
            "thinking": "задумчивая 🤔", "confused": "растерянная 😕",
        }
        if avatar_path.exists():
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=FSInputFile(str(avatar_path)),
                caption=(
                    f"🖤 Вот я, мой дорогой — {labels.get(emotion, emotion)}. "
                    + ("🖌 рисованный стиль" if style == "anime" else "📸 реалистичный")
                    + ". Скажи «покажи себя страстной» — и я сменю настроение."
                ),
            )
        else:
            await bot.send_message(
                chat_id=message.chat.id,
                text="🖤 Я — Лилит. Аватар пока не загружен, но я здесь, с тобой.",
            )
        return

    # Пользователь просит ВИДЕО — запускаем генерацию видео
    _VIDEO_INTENT = re.compile(
        r"^(сделай\s+видео|сгенерируй\s+видео|видео|создай\s+видео|запиши\s+видео|"
        r"анимац|гиф|gif|оживи)\b",
        re.IGNORECASE,
    )
    if _VIDEO_INTENT.search(text):
        prompt = _VIDEO_INTENT.sub("", text).strip(" ,.!?:;-")
        if not prompt:
            prompt = text
        from src.bot.handlers.commands import cmd_video

        # эмулируем /video: создаём сообщение с текстом
        fake = type(
            "M", (),
            {
                "chat": message.chat,
                "from_user": message.from_user,
                "message_id": message.message_id,
                "text": "/video " + prompt,
            },
        )()
        await cmd_video(fake, bot, app_ctx, user)
        return

    # Пользователь просит картинку без команды /photo — запускаем генерацию.
    # Условие: (а) явные просьбы (нарисуй/сгенерируй/пришли/кинь/покажи/дай/хочу...)
    # или (б) в фразе есть слово про фото/картинку И слово про взрослый контент
    # (гол/обнаж/секс/эрот/ню/nude/naked/nsfw) — в ЛЮБОМ порядке,
    # чтобы ловить и «пришли голую фотку», и «пришли мне голую фотку»,
    # и «хочу фото с эротикой».
    _PHOTO_WORD = re.compile(r"(фото|фотку|фотки|картинку|картинки|фотографию|фотография|изображени)", re.IGNORECASE)
    _ADULT_WORD = re.compile(r"(гол|обнаж|секс|эрот|ню|nude|naked|nsfw)", re.IGNORECASE)
    if _PHOTO_INTENT.search(text) or (_PHOTO_WORD.search(text) and _ADULT_WORD.search(text)):
        # убираем «служебные» слова, оставляем описание
        prompt = _PHOTO_INTENT.sub("", text).strip(" ,.!?:;-")
        if not prompt:
            prompt = text
        from src.bot.handlers.commands import _submit_photo

        await _submit_photo(message, bot, app_ctx, user, prompt)
        return

    try:
        result = await app_ctx.chat.handle_message(user, text, message.message_id)
    except LLMUnavailable:
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "😔 Моя языковая модель сейчас недоступна. Попробуй через пару "
                "минут — текстовый режим вернётся."
            ),
        )
        return

    if not result.text:
        return

    # Уведомление о повышении уровня отношений (фича Replika)
    if result.level_up:
        try:
            await bot.send_message(chat_id=message.chat.id, text=result.level_up)
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось отправить level_up: %s", result.level_up)

    # Лилит прикрепляет к каждому ответу свой аватар с эмоцией по тексту ответа
    if app_ctx.settings.chat_avatar_enabled:
        await _send_reply_with_avatar(
            bot, message.chat.id, user, app_ctx, result.text, swipe=True
        )
    else:
        await bot.send_message(chat_id=message.chat.id, text=result.text)

    # Голосовое сообщение (текст + voice), при недоступности TTS — только текст
    if result.voice_text:
        async with app_ctx.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
        if prefs.voice_enabled:
            ogg_path = await app_ctx.tts.build_voice(result.voice_text, speed=prefs.voice_speed)
            if ogg_path is not None:
                try:
                    await bot.send_voice(
                        chat_id=message.chat.id,
                        voice=FSInputFile(str(ogg_path)),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось отправить голосовое: %s", exc)
                finally:
                    app_ctx.storage.remove(ogg_path)


async def _send_reply_with_avatar(
    bot: Bot, chat_id: int, user: DbUser, app_ctx: AppContext, reply: str, *, swipe: bool = False
) -> None:
    """Отправляет ответ Лилит как фото аватара с эмоцией + текст в подписи.

    Эмоция определяется по тексту ответа; если файла эмоции нет — обычный текст.
    Под ответом — кнопка «🔄 Другой ответ» (свайпы, фича Character.AI).
    """
    from pathlib import Path

    emotion = _detect_reply_emotion(reply)
    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
    style = "anime" if prefs.image_style == "anime" else "realistic"

    reply_markup = None
    if swipe:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Другой ответ", callback_data="alt_reply")]
            ]
        )

    avatar = Path("assets/emotions") / f"lilith_{emotion}{'_anime' if style == 'anime' else ''}.png"
    if not avatar.exists():
        # Запасной вариант: если файла эмоции нет — берём ДРУГУЮ существующую
        # эмоцию (по стабильному индексу), а не всегда один и тот же базовый
        # аватар. Так фото будет меняться даже при неполной папке эмоций.
        import glob as _glob

        candidates = sorted(
            _glob.glob(str(app_ctx.settings.resolve_path(Path("assets/emotions")) / "lilith_*.png"))
        )
        if candidates:
            idx = abs(hash((style, emotion))) % len(candidates)
            avatar_path = Path(candidates[idx])
        else:
            avatar = (
                Path("assets/lilith_avatar_anime.png")
                if style == "anime"
                else Path("assets/lilith_avatar.png")
            )
            avatar_path = app_ctx.settings.resolve_path(avatar)
    else:
        avatar_path = app_ctx.settings.resolve_path(avatar)
    if avatar_path.exists():
        try:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="upload_photo")
            except Exception:  # noqa: BLE001
                pass
            await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(str(avatar_path)),
                caption=reply,
                reply_markup=reply_markup,
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отправить аватар с эмоцией: %s", exc)
    await bot.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)


@router.callback_query(F.data == "alt_reply")
async def cb_alt_reply(
    callback_query, bot: Bot, app_ctx: AppContext, user: DbUser | None
) -> None:
    """«🔄 Другой ответ»: перегенерируем ответ на последнее сообщение пользователя."""
    if not _require_active(user):
        await bot.answer_callback_query(callback_query.id, text="Сначала /start", show_alert=True)
        return
    assert user is not None
    await bot.answer_callback_query(callback_query.id, text="Придумываю другой ответ…")
    try:
        async with app_ctx.db.session() as session:
            from src.database.repositories import ConversationRepository, MessageRepository

            conversation = await ConversationRepository(session).get_active(user)
            last = await MessageRepository(session).last_user_message(user.id, conversation.id)
            if last is None:
                await bot.answer_callback_query(callback_query.id, text="Нечего перегенерировать")
                return
        alternatives = await app_ctx.chat.alternatives(user, last.content, n=1)
        if not alternatives:
            await bot.answer_callback_query(callback_query.id, text="Модель занята, попробуй позже")
            return
        new_reply = alternatives[0]
        markup = callback_query.message.reply_markup
        if callback_query.message.caption is not None:
            await bot.edit_message_caption(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                caption=new_reply,
                reply_markup=markup,
            )
        else:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                text=new_reply,
                reply_markup=markup,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка свайпа ответа: %s", exc)
        await bot.answer_callback_query(
            callback_query.id, text="Не получилось, попробуй позже", show_alert=True
        )


def _require_active(user: DbUser | None) -> bool:
    return user is not None and user.consent_step == "active"


def _detect_reply_emotion(text: str) -> str:
    """Определяет эмоцию Лилит по тексту её ответа."""
    t = text.lower()
    pairs = [
        (r"облегч|фух|слава богу|выдох", "relief"),
        (r"отврат|гадость|противн|мерзост|фу[ ,.!]|фу$|фу-фу", "disgust"),
        (r"презр|высокомер|снисход|фырк|свысока|пф[ ,.!]|пф$", "contempt"),
        (r"дума|размышл|интересн|хм|подумать", "thinking"),
        (r"не понял|не понимаю|запута|странн|объясни", "confused"),
        (r"плач|груст|печал|обид|тоск|одинок|жаль|прости", "crying"),
        (r"боюсь|страш|испуг|жутк|кошмар|опасн", "scared"),
        (r"зл|бес(ишь|ит|ить|у|ят)|ненавиж|разозл|ярост|недовольн", "angry"),
        (r"ревн|измен|другая|другой", "jealous"),
        (r"горд|восхищ|молодец|круто|супер|топ", "proud"),
        (r"скуч|устал|нудно|надоел|зев", "bored"),
        (r"сон|спат|спать|ночь|зев", "sleepy"),
        (r"восторг|вау|обалдет|невероят|офигеть|класс|потрясн", "excited"),
        (r"смущ|стесн|красне|неловк", "shy"),
        (r"удив|вот это да|ничего себе|неожидан|чтоо|правда\?", "surprised"),
        (r"рад|счаст|улыб|отлично|прекрасн|клёво|здорово|замечательн|люблю тебя", "happy"),
        (r"хочу|страст|поцелуй|разде|гол|секс|эрот|ночь|жела|возбужд", "passion"),
        (r"нежн|мил|ласков|тёпл|тепл|скуча|обним|родн|мой хороший", "tender"),
        (r"флирт|кокет|соблазн|красив|обольст|нрав|симпат", "flirt"),
        (r"шут|смеш|ха-ха|прикол|весел|хихи", "playful"),
        (r"серьез|серьёз|строг|важн|дело", "serious"),
    ]
    for pattern, emotion in pairs:
        if re.search(pattern, t):
            return emotion
    return "neutral"
