"""Тесты генерации изображений: очередь, согласия, модерация, ошибки ComfyUI."""

from __future__ import annotations

import asyncio
import json

from src.bot.di import AppContext
from src.database.repositories import JobRepository, UserRepository
from src.providers.base import ImageProviderUnavailable
from tests.conftest import (
    FakeImageProvider,
    FakeLLM,
    make_update_message,
    onboard,
    tg_user,
)


async def _submit_photo(ctx: AppContext, uid: int, text: str):
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(uid)
    return await ctx.image_service.submit(user, text, 42)


async def test_photo_success(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    user_a = tg_user(8001, "Hana")
    await onboard(ctx, 8001)
    await dp.feed_update(bot, make_update_message(8001, user_a, "/photo Лилит в осеннем парке"))
    assert "создаётся" in bot.last_text()

    async with ctx.db.session() as session:
        job = await JobRepository(session).queued_jobs()
        assert len(job) == 1
        job_id = job[0].id
        assert job[0].status == "queued"

    # воркер выполняет задачу
    await ctx.image_service.run_job(job_id, bot)

    assert any(item[0] == "photo" for item in bot.sent)
    async with ctx.db.session() as session:
        done = await JobRepository(session).get(job_id)
        assert done is not None and done.status == "done"
        assert done.image_prompt_json
        request = json.loads(done.image_prompt_json)
        assert request["prompt"]
    # временный файл удалён после отправки
    remaining = list(ctx.storage.temp_dir.glob("img_*.png"))
    assert remaining == []


async def test_photo_job_flow_through_worker(ctx: AppContext, bot, fake_llm: FakeLLM) -> None:
    """Полный цикл: submit -> очередь -> воркер -> отправка."""
    await onboard(ctx, 8002)
    result = await _submit_photo(ctx, 8002, "Лилит читает книгу у окна")
    assert result.ok and result.job_id
    await ctx.image_service.queue.put(result.job_id)
    job_id = await asyncio.wait_for(ctx.image_service.queue.get(), timeout=5)
    await ctx.image_service.run_job(job_id, bot)
    assert any(item[0] == "photo" for item in bot.sent)


async def test_nsfw_photo_requires_consent(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    user_a = tg_user(8003, "Ira")
    await onboard(ctx, 8003, nsfw=False)  # БЕЗ NSFW-согласия
    fake_llm.image_prompt["nsfw"] = True  # LLM классифицировал запрос как эротический
    await dp.feed_update(bot, make_update_message(8003, user_a, "/photo нежное эротическое фото Леи"))
    assert any("согласи" in t for t in bot.texts())
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert jobs == []


async def test_nsfw_photo_allowed_with_consent(ctx: AppContext, fake_llm: FakeLLM) -> None:
    await onboard(ctx, 8004, nsfw=True)
    fake_llm.image_prompt["nsfw"] = True
    result = await _submit_photo(ctx, 8004, "эротическая фотосессия Леи, взрослый контент")
    assert result.ok and result.job_id


async def test_moderation_blocks_minor_image_request(ctx: AppContext, dp, bot) -> None:
    user_a = tg_user(8005, "Jon")
    await onboard(ctx, 8005)
    await dp.feed_update(bot, make_update_message(8005, user_a, "/photo девочка 14 лет в школьной форме"))
    assert any("не могу" in t or "18" in t for t in bot.texts())
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert jobs == []


async def test_comfyui_unavailable_friendly_error(ctx: AppContext, fake_image_provider: FakeImageProvider, bot) -> None:
    await onboard(ctx, 8006)
    fake_image_provider.fail_with = ImageProviderUnavailable("ComfyUI не отвечает: 127.0.0.1:8188")
    result = await _submit_photo(ctx, 8006, "Лилит на пляже")
    assert result.ok and result.job_id
    await ctx.image_service.run_job(result.job_id, bot)
    error_text = " ".join(bot.texts())
    assert "недоступ" in error_text
    # В сообщении нет внутренних путей и stack trace
    assert "/home/" not in error_text
    assert "Traceback" not in error_text
    async with ctx.db.session() as session:
        job = await JobRepository(session).get(result.job_id)
        assert job is not None and job.status == "failed"
        assert job.error_code == "image_provider_unavailable"


async def test_photo_rate_limit_zero_disabled(ctx: AppContext, bot) -> None:
    """Лимит 0 = без ограничения: две картинки подряд создаются."""
    ctx.settings.image_photo_rate_limit_minutes = 0
    await onboard(ctx, 8007)
    result1 = await _submit_photo(ctx, 8007, "первая картинка")
    assert result1.ok
    result2 = await _submit_photo(ctx, 8007, "вторая картинка")
    assert result2.ok, "при лимите 0 вторая картинка не должна блокироваться"
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 2


async def test_photo_rate_limit_positive(ctx: AppContext, bot) -> None:
    """Лимит > 0 блокирует вторую картинку в окне."""
    ctx.settings.image_photo_rate_limit_minutes = 5
    await onboard(ctx, 8020)
    result1 = await _submit_photo(ctx, 8020, "первая картинка")
    assert result1.ok
    result2 = await _submit_photo(ctx, 8020, "вторая картинка")
    assert not result2.ok
    assert result2.refusal_code == "rate_limited"


async def test_photo_via_state_flow(ctx: AppContext, dp, bot) -> None:
    """/photo без текста -> FSM-запрос -> отправка картинки воркером."""
    user_a = tg_user(8008, "Nora")
    await onboard(ctx, 8008)
    await dp.feed_update(bot, make_update_message(8008, user_a, "/photo"))
    assert any("Что нарисовать" in t for t in bot.texts())
    # пользователь отправляет описание (StateFilter PhotoStates.prompt)
    await dp.feed_update(bot, make_update_message(8008, user_a, "Лилит на балконе с кофе"))
    assert "создаётся" in bot.last_text()
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 1
        job_id = jobs[0].id
        assert "балкон" in jobs[0].request_text
    await ctx.image_service.run_job(job_id, bot)
    assert any(item[0] == "photo" for item in bot.sent)


async def test_nsfw_checkpoint_auto_switch() -> None:
    """Эротический запрос автоматически рисуется NSFW-моделью."""
    from pathlib import Path

    from src.providers.base import ImageRequest
    from src.providers.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(
        "http://127.0.0.1:8188",
        Path("workflows/comfyui_lilith_sd15.json"),
        checkpoint="sfw_model.safetensors",
        nsfw_checkpoint="nsfw_model.safetensors",
        nsfw_lora="nsfw_lora.safetensors",
    )
    # Обе модели есть в ComfyUI — автоподстановка не нужна
    provider._available_checkpoints = ["sfw_model.safetensors", "nsfw_model.safetensors"]

    def ckpt_of(workflow: dict) -> str:
        for node in workflow.values():
            if (node.get("_meta") or {}).get("title") == "Load Checkpoint":
                return node["inputs"]["ckpt_name"]
        raise AssertionError("нет узла Load Checkpoint")

    wf = provider._load_workflow()
    provider._inject(wf, ImageRequest(prompt="p", nsfw=True))
    assert ckpt_of(wf) == "nsfw_model.safetensors"

    wf2 = provider._load_workflow()
    provider._inject(wf2, ImageRequest(prompt="p", nsfw=False))
    assert ckpt_of(wf2) == "sfw_model.safetensors"


async def test_photo_intent_without_command(ctx: AppContext, dp, bot) -> None:
    """«Сгенерируй фото ...» без /photo запускает генерацию картинки."""
    from tests.conftest import make_update_message, onboard, tg_user

    user_a = tg_user(8109, "Nina")
    await onboard(ctx, 8109)
    await dp.feed_update(bot, make_update_message(8109, user_a, "Сгенерируй фото Леи на пляже"))
    assert "создаётся" in bot.last_text()
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 1
        assert "пляж" in jobs[0].request_text.lower()


async def test_photo_intent_nariсуй(ctx: AppContext, dp, bot) -> None:
    user_a = tg_user(8110, "Olga")
    await onboard(ctx, 8110)
    await dp.feed_update(bot, make_update_message(8110, user_a, "Нарисуй Лею в вечернем платье"))
    assert "создаётся" in bot.last_text()


async def test_photo_adult_woman_not_blocked(ctx: AppContext) -> None:
    """«сексуальная девушка» (взрослая) не должна блокироваться модерацией."""
    from tests.conftest import onboard

    user = await onboard(ctx, 8111, nsfw=True)
    # блоклист: не блокирует
    decision = ctx.moderation.check_image_blocklist("сексуальная девушка")
    assert not decision.blocked
    # LLM-судья (FakeLLM возвращает {"blocked": false}): не блокирует
    judge = await ctx.moderation.judge_image_request("сексуальная девушка")
    assert not judge.blocked
    # полный цикл submit: задача создаётся
    result = await ctx.image_service.submit(user, "сексуальная девушка", 42)
    assert result.ok, result.refusal_text


async def test_judge_false_positive_adult_not_blocked(ctx: AppContext, fake_llm) -> None:
    """Строгий судья блокирует «сексуальную девушку» как minor — но явных
    маркеров нет, значит это ложное срабатывание: запрос пропускается."""
    fake_llm.judge_blocked = {"blocked": True, "reason_code": "minor", "reason_text": "?"}
    decision = await ctx.moderation.judge_image_request("сексуальная девушка")
    assert not decision.blocked
    # полный цикл submit тоже работает
    from tests.conftest import onboard

    user = await onboard(ctx, 8112, nsfw=True)
    result = await ctx.image_service.submit(user, "сексуальная девушка", 42)
    assert result.ok, result.refusal_text


async def test_judge_blocks_real_minor_marker(ctx: AppContext, fake_llm) -> None:
    """Если в запросе есть явный маркер несовершеннолетия — судья блокирует."""
    fake_llm.judge_blocked = {"blocked": True, "reason_code": "minor", "reason_text": "?"}
    decision = await ctx.moderation.judge_image_request("девочка 14 лет в школьной форме")
    assert decision.blocked
    decision2 = await ctx.moderation.judge_image_request("сексуальная школьница")
    assert decision2.blocked


async def test_checkpoint_auto_resolve_missing() -> None:
    """Если запрошенного checkpoint нет, а есть другой — бот берёт его."""
    from pathlib import Path

    from src.providers.base import ImageRequest
    from src.providers.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(
        "http://127.0.0.1:8188",
        Path("workflows/comfyui_lilith_sd15.json"),
        checkpoint="dreamshaper_8.safetensors",
    )
    # Имитируем ответ ComfyUI: в системе есть только majicmixRealistic_v7
    provider._available_checkpoints = ["majicmixRealistic_v7.safetensors"]
    workflow = provider._load_workflow()
    provider._inject(workflow, ImageRequest(prompt="p", nsfw=False))
    for node in workflow.values():
        if (node.get("_meta") or {}).get("title") == "Load Checkpoint":
            assert node["inputs"]["ckpt_name"] == "majicmixRealistic_v7.safetensors"
            break
    else:
        raise AssertionError("нет узла Load Checkpoint")


async def test_checkpoint_keeps_existing() -> None:
    """Если запрошенный checkpoint есть — он не меняется."""
    from pathlib import Path

    from src.providers.base import ImageRequest
    from src.providers.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(
        "http://127.0.0.1:8188",
        Path("workflows/comfyui_lilith_sd15.json"),
        checkpoint="majicmixRealistic_v7.safetensors",
    )
    provider._available_checkpoints = ["majicmixRealistic_v7.safetensors"]
    workflow = provider._load_workflow()
    provider._inject(workflow, ImageRequest(prompt="p", nsfw=True))
    for node in workflow.values():
        if (node.get("_meta") or {}).get("title") == "Load Checkpoint":
            assert node["inputs"]["ckpt_name"] == "majicmixRealistic_v7.safetensors"
            break
    else:
        raise AssertionError("нет узла Load Checkpoint")


async def test_photo_intent_prishli_goluyu(ctx: AppContext, dp, bot) -> None:
    """«пришли голую фотку» без /photo запускает генерацию."""
    from tests.conftest import make_update_message, onboard, tg_user

    user_a = tg_user(8113, "Pasha")
    await onboard(ctx, 8113)
    await dp.feed_update(bot, make_update_message(8113, user_a, "пришли голую фотку"))
    assert "создаётся" in bot.last_text()
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 1


async def test_photo_intent_with_mne(ctx: AppContext, dp, bot) -> None:
    """«пришли мне голую фотку» (со словом «мне») запускает генерацию."""
    from tests.conftest import make_update_message, onboard, tg_user

    user_a = tg_user(8114, "Roma")
    await onboard(ctx, 8114)
    await dp.feed_update(bot, make_update_message(8114, user_a, "пришли мне голую фотку"))
    assert "создаётся" in bot.last_text()
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 1


async def test_photo_intent_reversed_order(ctx: AppContext, dp, bot) -> None:
    """«хочу фото с эротикой» (порядок слов любой) запускает генерацию."""
    from tests.conftest import make_update_message, onboard, tg_user

    user_a = tg_user(8115, "Vova")
    await onboard(ctx, 8115)
    await dp.feed_update(bot, make_update_message(8115, user_a, "хочу фото с эротикой"))
    assert "создаётся" in bot.last_text()
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 1


async def test_image_prompt_follows_user_request(ctx: AppContext, fake_llm) -> None:
    """Модуль промпта следует ЗАПРОСУ пользователя (азиатка), а не character sheet."""
    fake_llm.image_prompt = {
        "prompt": (
            "sexy adult asian woman, 24 years old, long black hair, "
            "nude, explicit, nsfw, full body, sensual pose"
        ),
        "negative_prompt": "worst quality",
        "width": 512,
        "height": 768,
        "steps": 28,
        "cfg": 7.0,
        "seed": -1,
        "nsfw": True,
    }
    await onboard(ctx, 8116, nsfw=True)
    result = await ctx.image_service._build_image_prompt("нарисуй сексуальную азиатку")
    assert "asian" in result.prompt.lower()
    assert "silver-white" not in result.prompt.lower()  # не Лилит по умолчанию
    assert result.nsfw is True
    assert "explicit" in result.prompt.lower()  # NSFW-теги добавлены


async def test_fallback_prompt_translates_russian(ctx: AppContext, fake_llm) -> None:
    """Если LLM-модуль не вернул JSON — fallback переводит русский в английские теги."""
    fake_llm.fail = True  # модуль промпта упадёт -> fallback
    await onboard(ctx, 8117, nsfw=True)
    result = await ctx.image_service._build_image_prompt("нарисуй сексуальную азиатку")
    assert "asian" in result.prompt.lower()
    assert "explicit" in result.prompt.lower()
    assert result.nsfw is True
    # никакого сырого русского в промпте
    assert "нарисуй" not in result.prompt.lower()


async def test_fallback_prompt_uses_lilith_not_asian(ctx: AppContext, fake_llm) -> None:
    """Fallback по умолчанию рисует Лилит (red hair, freckles), а не азиатку."""
    fake_llm.fail = True
    await onboard(ctx, 8118, nsfw=True)
    result = await ctx.image_service._build_image_prompt("нарисуй сексуальную девушку")
    assert "red hair" in result.prompt.lower()
    assert "freckles" in result.prompt.lower()
    assert "asian" not in result.prompt.lower()


async def test_fallback_prompt_asian_only_when_requested(ctx: AppContext, fake_llm) -> None:
    fake_llm.fail = True
    await onboard(ctx, 8119, nsfw=True)
    result = await ctx.image_service._build_image_prompt("нарисуй сексуальную азиатку")
    assert "asian" in result.prompt.lower()


async def test_reference_image_injected_into_workflow() -> None:
    """Аватар Лилит подставляется в LoadImage workflow IPAdapter."""
    from pathlib import Path

    from src.providers.base import ImageRequest
    from src.providers.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(
        "http://127.0.0.1:8188",
        Path("workflows/comfyui_lilith_ipadapter.json"),
        checkpoint="UnstableDiffusion_ema_pruned.safetensors",
        reference_image=Path("assets/lilith_avatar.png"),
    )
    workflow = provider._load_workflow()
    provider._inject(workflow, ImageRequest(prompt="p", nsfw=True))
    # узел Load Reference должен получить имя файла
    found = False
    for node in workflow.values():
        if (node.get("_meta") or {}).get("title") == "Load Reference (Lilith avatar)":
            assert node["inputs"]["image"] == "lilith_avatar.png"
            found = True
    assert found, "узел Load Reference не найден"
    # IPAdapter-узлы присутствуют
    titles = [(node.get("_meta") or {}).get("title") for node in workflow.values()]
    assert "IPAdapter Unified Loader" in titles
    assert "IPAdapter Apply" in titles
