/* Лилит — визуальная новелла в Telegram Mini App (v1.8.11) */
(function () {
  "use strict";

  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor("#12070f");
    tg.setBackgroundColor("#12070f");
  }

  const INIT_DATA = tg ? tg.initData : "";

  function el(id) { return document.getElementById(id); }

  function api(path, options) {
    const opts = options || {};
    const headers = Object.assign(
      { "X-Init-Data": INIT_DATA, "bypass-tunnel-reminder": "true" },
      opts.headers || {}
    );
    if (opts.body) headers["Content-Type"] = "application/json";
    return fetch(path, { method: opts.method || "GET", headers, body: opts.body }).then(function (r) {
      if (r.status === 401) throw new Error("Не авторизовано");
      return r.json();
    });
  }

  // ============================== ЭМОЦИИ ==============================

  const EMOTION_LABELS = {
    neutral: "😌", flirt: "😏", passion: "🔥", playful: "😜", tender: "💗", serious: "😐",
    happy: "😊", sad: "😢", angry: "😠", surprised: "😲", shy: "😳", proud: "😎",
    jealous: "😒", bored: "🥱", excited: "🤩", sleepy: "😴", crying: "😭", scared: "😨",
    disgust: "🤢", contempt: "🙄", relief: "😮‍💨", thinking: "🤔", confused: "😕"
  };

  function detectEmotion(text) {
    const t = text.toLowerCase();
    if (/(фу|отврат|гадость|противн|мерзост)/.test(t)) return "disgust";
    if (/(презр|высокомер|снисход|фырк)/.test(t)) return "contempt";
    if (/(облегч|фух|слава богу|выдох)/.test(t)) return "relief";
    if (/(дума|размышл|интересн|хм|подумать)/.test(t)) return "thinking";
    if (/(не понял|не понимаю|запута|странн|объясни)/.test(t)) return "confused";
    if (/(плач|груст|печал|обид|тоск|одинок|разбит)/.test(t)) return "crying";
    if (/(боюсь|страш|испуг|жутк|кошмар)/.test(t)) return "scared";
    if (/(зл|бешу|ненавиж|разозл|ярост)/.test(t)) return "angry";
    if (/(ревн|измен|другая|другой)/.test(t)) return "jealous";
    if (/(горд|восхищ|молодец|круто|супер|топ)/.test(t)) return "proud";
    if (/(скуч|устал|нудно|надоел|зев)/.test(t)) return "bored";
    if (/(сон|спат|ночь|спать|зев)/.test(t)) return "sleepy";
    if (/(восторг|вау|обалдет|невероят|офигеть|класс)/.test(t)) return "excited";
    if (/(смущ|стесн|красне|неловк)/.test(t)) return "shy";
    if (/(удив|вот это да|ничего себе|неожидан|чтоо)/.test(t)) return "surprised";
    if (/(рад|счаст|улыб|хорошо|отлично|прекрасн|клёво|здорово)/.test(t)) return "happy";
    if (/(хочу|страст|поцелуй|разде|гол|секс|эрот|ночь|жела)/.test(t)) return "passion";
    if (/(люблю|скучал|милый|нежно|обним|родн)/.test(t)) return "tender";
    if (/(флирт|кокет|соблазн|красив|нрав)/.test(t)) return "flirt";
    if (/(шут|смешно|ха-ха|прикол|весел)/.test(t)) return "playful";
    if (/(злишь|обид|серьез|серьёз|важн)/.test(t)) return "serious";
    return "neutral";
  }

  // ============================== АВАТАР ==============================

  let currentStyle = "realistic";
  let currentEmotion = "neutral";
  let currentStage = 1;
  let currentClothes = "";

  function setAvatar(emotion, stage) {
    currentEmotion = emotion || "neutral";
    if (stage) currentStage = Math.max(1, Math.min(4, stage));
    const stagePath = currentStage > 1 ? "&stage=" + currentStage : "";
    const clothesPath = currentClothes ? "&clothes=" + currentClothes : "";
    const img = el("avatar");
    img.style.opacity = "0.3";
    img.onload = function () { img.style.opacity = "1"; };
    img.src = "/api/avatar?style=" + currentStyle + "&emotion=" + currentEmotion + stagePath + clothesPath;
    const tag = el("emotion-tag");
    if (tag) tag.textContent = EMOTION_LABELS[currentEmotion] || "😌";
    const mood = el("mood-tag");
    if (mood) mood.textContent = ["👗", "👙", "🩲", "🔥"][currentStage - 1] + " " + currentStage + "/4";
  }

  // ============================== ЧАТ (пузыри) ==============================

  const chatLog = el("chat-log");
  const MAX_BUBBLES = 60;

  function addBubble(role, text) {
    const ph = el("chat-placeholder");
    if (ph) ph.style.display = "none";
    const row = document.createElement("div");
    row.className = "msg-row " + (role === "user" ? "msg-user" : "msg-lilith");

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    if (role === "assistant") {
      const name = document.createElement("div");
      name.className = "msg-name";
      name.textContent = "🖤 Лилит";
      row.appendChild(name);
    }
    row.appendChild(bubble);
    chatLog.appendChild(row);

    // Не даём истории разрастаться бесконечно
    while (chatLog.children.length > MAX_BUBBLES) {
      chatLog.removeChild(chatLog.firstChild);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
    return row;
  }

  function typingBubble() {
    const row = document.createElement("div");
    row.className = "msg-row msg-lilith";
    row.id = "typing-row";
    const bubble = document.createElement("div");
    bubble.className = "bubble typing";
    bubble.textContent = "…";
    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function removeTyping() {
    const row = el("typing-row");
    if (row) row.remove();
  }

  function lastLilithBubble() {
    const rows = chatLog.querySelectorAll(".msg-lilith .bubble");
    return rows.length ? rows[rows.length - 1] : null;
  }

  // ============================== ОТПРАВКА ==============================

  let lastUserText = "";
  let altIndex = -1;
  let altList = [];

  function sendChat(text) {
    const input = el("chat-input");
    const msg = (text != null ? text : input.value).trim();
    if (!msg) return;
    if (text == null) input.value = "";
    lastUserText = msg;
    altIndex = -1;
    altList = [];
    addBubble("user", msg);
    typingBubble();
    api("/api/chat", { method: "POST", body: JSON.stringify({ text: msg }) })
      .then(function (res) {
        removeTyping();
        if (res.reply) {
          addBubble("assistant", res.reply);
          setAvatar(res.emotion, res.stage || currentStage);
        } else {
          addBubble("assistant", "…");
        }
        if (res.level_up) {
          const tag = el("level-tag");
          if (tag) tag.textContent = "💜 " + res.level_up;
          api("/api/me").then(fillLevel).catch(function () {});
        }
      })
      .catch(function (e) {
        removeTyping();
        addBubble("assistant", "… (модель не ответила: " + (e.message || "ошибка") + ")");
      });
  }

  function doSwipe() {
    if (!lastUserText) return;
    const last = lastLilithBubble();
    if (last) last.textContent = "…";
    typingBubble();
    api("/api/chat/alternatives", { method: "POST", body: JSON.stringify({ text: lastUserText, n: 3 }) })
      .then(function (res) {
        removeTyping();
        if (!res.alternatives || !res.alternatives.length) throw new Error("нет вариантов");
        altList = res.alternatives;
        altIndex = (altIndex + 1) % altList.length;
        const reply = altList[altIndex];
        const bubble = lastLilithBubble();
        if (bubble) bubble.textContent = reply; else addBubble("assistant", reply);
        setAvatar(detectEmotion(reply));
      })
      .catch(function (e) {
        removeTyping();
        addBubble("assistant", "… (не получилось: " + (e.message || "ошибка") + ")");
      });
  }

  // ============================== БЫСТРЫЕ ПОДСКАЗКИ ==============================

  const QUICK_PHRASES = ["😏 Покажи себя", "🩲 В белье", "💬 Как дела?", "🎨 Нарисуй нас", "📖 Что помнишь обо мне?"];

  function renderChips() {
    const wrap = el("quick-chips");
    if (!wrap) return;
    wrap.innerHTML = "";
    QUICK_PHRASES.forEach(function (phrase) {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = phrase;
      chip.addEventListener("click", function () { sendChat(phrase); });
      wrap.appendChild(chip);
    });
  }

  // ============================== НАРЯД ==============================

  function generateOutfit() {
    const outfit = el("s-outfit").value.trim();
    if (!outfit) {
      el("save-msg").textContent = "Сначала напиши наряд в поле выше 👗";
      return;
    }
    el("save-msg").textContent = "🎨 Рисую образ в наряде: «" + outfit + "»…";
    api("/api/chat", { method: "POST", body: JSON.stringify({ text: "переоденься в этот наряд", outfit: outfit }) })
      .then(function (res) {
        if (res.generating) {
          el("save-msg").textContent = "✅ Генерация запущена — картинка придёт в Telegram!";
        } else if (res.reply) {
          el("save-msg").textContent = res.reply;
        } else {
          el("save-msg").textContent = "❌ Не получилось, попробуй ещё раз";
        }
      })
      .catch(function (e) {
        el("save-msg").textContent = "❌ " + e.message;
      });
  }

  // ============================== КНОПКИ ЧАТА ==============================

  el("send-btn").addEventListener("click", function () { sendChat(); });
  el("chat-input").addEventListener("keydown", function (e) { if (e.key === "Enter") sendChat(); });
  el("swipe-btn").addEventListener("click", doSwipe);
  el("clothes-btn").addEventListener("click", function () {
    currentClothes = currentClothes === "lingerie" ? "" : "lingerie";
    el("clothes-btn").textContent = currentClothes === "lingerie" ? "👗" : "🩲";
    setAvatar(currentEmotion);
  });
  el("generate-outfit").addEventListener("click", generateOutfit);

  // ============================== ВКЛАДКИ ==============================

  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      if (tab === "chat") { el("chat-box").style.display = "flex"; return; }
      el("chat-box").style.display = "none";
      el("tab-" + tab).classList.add("active");
      if (tab === "gallery") loadGallery();
      if (tab === "memory") loadMemory();
      if (tab === "diary") loadDiary();
    });
  });

  // ============================== НАСТРОЙКИ ==============================

  function fillSettings(d) {
    el("s-name").value = d.name || "";
    el("s-mode").value = String(d.mode);
    el("s-style").value = d.image_style || "realistic";
    el("s-creativity").value = String(d.creativity != null ? d.creativity : 1);
    el("s-length").value = String(d.response_length != null ? d.response_length : 1);
    el("s-outfit").value = d.outfit || "";
    el("s-speech").value = d.speech_style || "";
  }

  function fillLevel(d) {
    const tag = el("level-tag");
    if (!tag) return;
    const lvl = d.level || 1;
    const name = d.level_name || "";
    tag.textContent = "💜 " + lvl + "/7 " + name;
    const fill = el("xp-fill");
    if (fill) {
      const progress = Math.max(0, Math.min(1, d.level_progress || 0));
      fill.style.width = Math.round(progress * 100) + "%";
    }
  }

  el("save").addEventListener("click", function () {
    const body = JSON.stringify({
      name: el("s-name").value.trim(),
      mode: parseInt(el("s-mode").value, 10),
      image_style: el("s-style").value,
      creativity: parseInt(el("s-creativity").value, 10),
      response_length: parseInt(el("s-length").value, 10),
      outfit: el("s-outfit").value.trim(),
      speech_style: el("s-speech").value.trim(),
    });
    el("save").disabled = true;
    el("save-msg").textContent = "Сохраняю…";
    api("/api/settings", { method: "POST", body: body })
      .then(function (res) {
        el("save-msg").textContent = res.ok ? "✅ Сохранено!" : "❌ Ошибка";
        if (res.ok) return api("/api/me");
      })
      .then(function (me) { if (me) { fillSettings(me); currentStyle = me.image_style || "realistic"; fillLevel(me); setAvatar(); } })
      .catch(function (e) { el("save-msg").textContent = "❌ " + e.message; })
      .finally(function () { el("save").disabled = false; });
  });

  // ============================== ГАЛЕРЕЯ / ДНЕВНИК / ПАМЯТЬ ==============================

  function loadGallery() {
    el("gallery").innerHTML = '<p class="hint">Загрузка…</p>';
    api("/api/gallery").then(function (res) {
      const images = (res.images || []).filter(function (i) { return i.file_path; });
      if (!images.length) { el("gallery").innerHTML = '<p class="hint">Пока пусто. Напиши «нарисуй…» боту.</p>'; return; }
      el("gallery").innerHTML = "";
      images.forEach(function (img) {
        const card = document.createElement("div");
        card.className = "card";
        const pic = document.createElement("img");
        pic.className = "card-img";
        pic.src = "/api/gallery/image/" + img.id;
        pic.alt = "Lilith";
        pic.loading = "lazy";
        const cap = document.createElement("div");
        cap.className = "card-date";
        cap.textContent = (img.created_at || "").replace("T", " ").slice(0, 16);
        card.appendChild(pic);
        card.appendChild(cap);
        el("gallery").appendChild(card);
      });
    }).catch(function () { el("gallery").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
  }

  function loadDiary() {
    el("diary").innerHTML = '<p class="hint">Загрузка…</p>';
    api("/api/diary").then(function (res) {
      const entries = res.entries || [];
      if (!entries.length) {
        el("diary").innerHTML = '<p class="hint">Пока пусто. Лилит напишет первую запись вечером, после вашего разговора 💜</p>';
        return;
      }
      el("diary").innerHTML = "";
      entries.forEach(function (item) {
        const card = document.createElement("div");
        card.className = "diary-item";
        const date = document.createElement("div");
        date.className = "diary-date";
        date.textContent = "📅 " + item.date;
        const text = document.createElement("div");
        text.textContent = item.text;
        card.appendChild(date);
        card.appendChild(text);
        el("diary").appendChild(card);
      });
    }).catch(function () { el("diary").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
  }

  function loadMemory() {
    el("memory").innerHTML = '<p class="hint">Загрузка…</p>';
    api("/api/memory").then(function (res) {
      const items = res.items || [];
      if (!items.length) { el("memory").innerHTML = '<p class="hint">Память пуста.</p>'; return; }
      el("memory").innerHTML = "";
      items.forEach(function (item) {
        const row = document.createElement("div");
        row.className = "memory-item";
        row.innerHTML = "<span class='tag'>" + escapeHtml(item.category) + "</span> " + escapeHtml(item.fact);
        el("memory").appendChild(row);
      });
    }).catch(function () { el("memory").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ============================== СТАРТ ==============================

  if (!window.Telegram || !window.Telegram.WebApp) {
    const d0 = el("chat-placeholder");
    if (d0) d0.textContent = "🖤 Это приложение Лилит. Открой его ВНУТРИ Telegram: напиши боту /app — и всё заработает.";
  }

  window.addEventListener("error", function (ev) {
    try {
      const d = el("chat-placeholder");
      if (d) d.textContent = "⚠️ Ошибка: " + (ev.message || "неизвестная") + ". Обнови Mini App.";
    } catch (e) { /* ignore */ }
  });

  renderChips();

  api("/api/me")
    .then(function (d) {
      fillSettings(d);
      fillLevel(d);
      currentStyle = d.image_style || "realistic";
      // Подгружаем историю диалога
      return api("/api/history").then(function (h) {
        const messages = h.messages || [];
        messages.forEach(function (m) { addBubble(m.role, m.content); });
        setAvatar("flirt");
        if (!messages.length) {
          addBubble("assistant", "Ну привет, мой дорогой… Я уже заждалась. Что скажешь?");
        }
      });
    })
    .catch(function (e) {
      const d = el("chat-placeholder");
      if (d) d.textContent = "Ошибка: " + e.message + ". Открой бота и нажми /start.";
    });
})();
