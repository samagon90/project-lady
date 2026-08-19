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
    // Эмодзи — самый надёжный маркер эмоции (v2.0)
    const emo = [
      [/😈|🔥|💋|👅|🫦|😏/, "passion"],
      [/💗|🥰|💖|😍|❤️/, "tender"],
      [/😭|🥺|💔|😢/, "crying"],
      [/😡|🤬|👿/, "angry"],
      [/😳|🫣|🥵/, "shy"],
      [/😱|😨|🫨/, "scared"],
      [/😴|🥱/, "sleepy"],
      [/🤔|🧐/, "thinking"],
      [/😮|😲|🤯/, "surprised"],
      [/😊|😄|😁|🥳|🎉/, "happy"],
      [/😂|🤣|😜|😝/, "playful"],
      [/😒|🙄|💅/, "contempt"],
      [/🤢|🤮/, "disgust"],
      [/😌|🕊/, "relief"]
    ];
    for (var i = 0; i < emo.length; i++) {
      if (emo[i][0].test(t)) return emo[i][1];
    }
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
    if (/!{2,}/.test(t)) return "excited";
    if (/\?/.test(t) && t.length < 200) return "thinking";
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
    // cache-bust: гарантирует, что браузер перерисует фото при каждом ответе
    const bust = "&_=" + Date.now();
    // toon-стиль: аватар всегда из папки toon (бельевой)
    const styleParam = currentStyle === "toon" ? "toon" : currentStyle;
    img.src = "/api/avatar?style=" + styleParam + "&emotion=" + currentEmotion + stagePath + clothesPath + bust;
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

  // ============================== ПАНЕЛЬ ЭМОЦИЙ (v2.1) ==============================
  // Тап по смайлику эмоции (угол аватара) открывает выбор настроения Лилит.
  const EMOTION_ORDER = ["neutral","flirt","passion","playful","tender","serious",
    "happy","sad","angry","surprised","shy","proud","jealous","bored","excited",
    "sleepy","crying","scared","disgust","contempt","relief","thinking","confused"];

  function buildEmotionPanel() {
    const panel = document.createElement("div");
    panel.id = "emotion-panel";
    panel.className = "emotion-panel";
    panel.style.display = "none";
    EMOTION_ORDER.forEach(function (emotion) {
      const btn = document.createElement("button");
      btn.className = "emotion-btn";
      btn.textContent = EMOTION_LABELS[emotion] || "😌";
      btn.title = emotion;
      btn.addEventListener("click", function () {
        haptic();
        setAvatar(emotion);
        panel.style.display = "none";
      });
      panel.appendChild(btn);
    });
    document.getElementById("avatar-wrap").appendChild(panel);
    const tag = el("emotion-tag");
    if (tag) tag.style.cursor = "pointer";
    if (tag) tag.addEventListener("click", function () {
      haptic();
      panel.style.display = panel.style.display === "none" ? "flex" : "none";
    });
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

  // ============================== НОВЕЛЛА (v2.7) ==============================

  let novelData = null;
  let novelNodeId = null;

  function loadNovel() {
    const box = el("novel-box");
    if (!box) return;
    api("/api/novel")
      .then(function (data) {
        novelData = data;
        if (data.errors && data.errors.length) {
          el("novel-text").textContent = "⚠️ Сценарий повреждён: " + data.errors.join("; ");
          return;
        }
        novelNodeId = data.start || "start";
        renderNovelNode();
      })
      .catch(function (e) {
        el("novel-text").textContent = "Не удалось загрузить новеллу: " + e.message;
      });
  }

  function renderNovelNode() {
    if (!novelData || !novelNodeId) return;
    const node = novelData.nodes[novelNodeId];
    if (!node) return;
    const img = el("novel-image");
    img.src = "/api/gallery/static/image/" + encodeURIComponent(node.image) + "?_=" + Date.now();
    img.style.display = "block";

    const textEl = el("novel-text");
    let html = "<div class='novel-narrator'>" + escapeHtml(node.narrator || "") + "</div>";
    if (node.lilith) {
      html += "<div class='novel-lilith'>🖤 Лилит: " + escapeHtml(node.lilith) + "</div>";
    }
    textEl.innerHTML = html;

    const choicesEl = el("novel-choices");
    choicesEl.innerHTML = "";
    (node.choices || []).forEach(function (choice) {
      const btn = document.createElement("button");
      btn.className = "novel-choice";
      btn.textContent = choice[0];
      btn.addEventListener("click", function () {
        haptic();
        novelNodeId = choice[1];
        renderNovelNode();
      });
      choicesEl.appendChild(btn);
    });

    const isEnding = !!node.ending;
    el("novel-actions").style.display = isEnding ? "block" : "none";
    choicesEl.style.display = isEnding ? "none" : "flex";
  }

  el("novel-restart").addEventListener("click", function () {
    haptic();
    novelNodeId = novelData.start || "start";
    renderNovelNode();
  });

  el("novel-back").addEventListener("click", function () {
    haptic();
    document.querySelector('.tab[data-tab="chat"]').click();
  });

  // ============================== СЦЕНЫ (v2.0) ==============================

  const SCENES = [
    { emoji: "🕯", title: "Вечер при свечах", desc: "романтика, вино, разговоры до утра", text: "Давай устроим вечер при свечах… Ты, я, тёплый плед и никаких телефонов. Начни." },
    { emoji: "👑", title: "Госпожа и слуга", desc: "игра в подчинение, дерзкая Лилит", text: "Встань на колени, мой хороший. Сегодня я буду госпожой, а ты — послушным. Играем?" },
    { emoji: "💋", title: "Страстная ночь", desc: "жаркий разговор без запретов", text: "Сегодня я не буду сдерживаться… И тебе не советую. Расскажи, чего ты хочешь." },
    { emoji: "🥰", title: "Нежность", desc: "обнимашки, забота, тёплые слова", text: "Иди сюда. Обниму, поцелую в макушку и расскажу, как ты мне дорог. Мне так хорошо с тобой." },
    { emoji: "😈", title: "Ревность", desc: "дразнилки и проверка чувств", text: "Я видела, как ты смотрел на другую… Хочешь объясниться? Я умею быть очень ревнивой." },
    { emoji: "🌙", title: "Сказка на ночь", desc: "уютные истории перед сном", text: "Ложись поудобнее. Я расскажу тебе сказку — только наша, тёплая, с хорошим концом." }
  ];

  function renderScenes() {
    const wrap = el("scenes");
    if (!wrap) return;
    wrap.innerHTML = "";
    SCENES.forEach(function (scene) {
      const card = document.createElement("button");
      card.className = "scene-card";
      const title = document.createElement("div");
      title.className = "scene-title";
      title.textContent = scene.emoji + " " + scene.title;
      const desc = document.createElement("div");
      desc.className = "scene-desc";
      desc.textContent = scene.desc;
      card.appendChild(title);
      card.appendChild(desc);
      card.addEventListener("click", function () {
        // Переключаемся в чат и отправляем сценарий
        document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
        document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("active"); });
        document.querySelector('.tab[data-tab="chat"]').classList.add("active");
        el("chat-box").style.display = "flex";
        sendChat(scene.text);
      });
      wrap.appendChild(card);
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
      if (tab === "diary") loadDiary();
      if (tab === "settings") { loadStats(); loadMemory(); }
      if (tab === "scenes") renderScenes();
      if (tab === "novel") loadNovel();
    });
  });

  // ============================== НАСТРОЙКИ ==============================

  function haptic() {
    try { if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light"); } catch (e) { /* ignore */ }
  }

  function fillSettings(d) {
    el("s-name").value = d.name || "";
    el("s-mode").value = String(d.mode);
    el("s-style").value = d.image_style || "realistic";
    el("s-creativity").value = String(d.creativity != null ? d.creativity : 1);
    el("s-length").value = String(d.response_length != null ? d.response_length : 1);
    el("s-outfit").value = d.outfit || "";
    el("s-speech").value = d.speech_style || "";
    el("s-birthday").value = d.birthday || "";
    el("s-lingerie").checked = d.always_lingerie !== false;
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
      birthday: el("s-birthday").value.trim(),
      always_lingerie: el("s-lingerie").checked,
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

  // ============================== СТАТИСТИКА / ДОСТИЖЕНИЯ (v2.0) ==============================

  function loadStats() {
    const wrap = el("stats");
    if (!wrap) return;
    api("/api/me")
      .then(function (d) {
        const lines = [
          "💜 Уровень: " + (d.level_name || "") + " (" + (d.level || 1) + "/7)",
          "🔥 Серия дней: " + (d.streak || 0) + (d.max_streak ? " (рекорд " + d.max_streak + ")" : ""),
          "🗓 Вместе: " + (d.days_together || 1) + " дн.",
          "💬 Сообщений: " + (d.messages_total || 0),
          "⭐ XP: " + (d.xp || 0)
        ];
        wrap.innerHTML = lines.map(function (l) { return "<div class='stat-line'>" + l + "</div>"; }).join("");
      })
      .catch(function () { wrap.innerHTML = '<p class="hint">Не удалось загрузить</p>'; });

    const achWrap = el("achievements");
    if (!achWrap) return;
    api("/api/achievements")
      .then(function (res) {
        const items = res.items || [];
        if (!items.length) { achWrap.innerHTML = '<p class="hint">Пока нет. Общайся — и они появятся 🏆</p>'; return; }
        achWrap.innerHTML = "";
        items.forEach(function (item) {
          const row = document.createElement("div");
          row.className = "achievement";
          row.textContent = item.title;
          achWrap.appendChild(row);
        });
      })
      .catch(function () { achWrap.innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
  }

  // ============================== ГАЛЕРЕЯ / ДНЕВНИК / ПАМЯТЬ ==============================

  function galleryCard(picSrc, caption, alt) {
    const card = document.createElement("div");
    card.className = "card";
    const pic = document.createElement("img");
    pic.className = "card-img";
    pic.src = picSrc;
    pic.alt = alt || "Lilith";
    pic.loading = "lazy";
    const cap = document.createElement("div");
    cap.className = "card-date";
    cap.textContent = caption || "";
    card.appendChild(pic);
    card.appendChild(cap);
    return card;
  }

  function loadGallery() {
    el("gallery").innerHTML = '<p class="hint">Загрузка…</p>';
    // Встроенные образы Лилит (assets/gallery) + сгенерированные пользователем
    Promise.all([api("/api/gallery/static"), api("/api/gallery")])
      .then(function (results) {
        const staticImages = (results[0].images || []);
        const userImages = (results[1].images || []).filter(function (i) { return i.file_path; });
        if (!staticImages.length && !userImages.length) {
          el("gallery").innerHTML = '<p class="hint">Пока пусто. Напиши «нарисуй…» боту.</p>';
          return;
        }
        el("gallery").innerHTML = "";
        // Реалистичные фото (как реальная девушка) — отдельная секция
        const realImages = staticImages.filter(function (n) { return n.indexOf("lilith_real_") === 0; });
        // Серия «Алхимик 2042» (ведьма-зельевар) — своя секция
        const alchemyImages = staticImages.filter(function (n) { return n.indexOf("lilith_alchemy_") === 0; });
        // Серия «Строгая учительница» — своя секция
        const teacherImages = staticImages.filter(function (n) { return n.indexOf("lilith_teacher_") === 0; });
        // Серия «Доминанта» (юбка-карандаш, каблуки, ракурс снизу) — своя секция
        const bossImages = staticImages.filter(function (n) { return n.indexOf("lilith_boss_") === 0; });
        const artImages = staticImages.filter(function (n) {
          return n.indexOf("lilith_real_") !== 0 && n.indexOf("lilith_alchemy_") !== 0
            && n.indexOf("lilith_teacher_") !== 0 && n.indexOf("lilith_boss_") !== 0;
        });

        function appendStaticSection(title, names) {
          if (!names.length) return;
          const h = document.createElement("h3");
          h.className = "gallery-header";
          h.textContent = title;
          el("gallery").appendChild(h);
          names.forEach(function (name) {
            const capIcon = title === "📸 Реальные фото" ? "📸"
              : (title === "🧪 Алхимик 2042" ? "🧪"
              : (title === "👩🏫 Строгая учительница" ? "👩🏫"
              : (title === "👠 Доминанта" ? "👠" : "✨")));
            const card = galleryCard("/api/gallery/static/image/" + encodeURIComponent(name), capIcon, "Lilith");
            const wear = document.createElement("button");
            wear.className = "wear-btn";
            wear.textContent = "👗 Надеть";
            wear.addEventListener("click", function () {
              haptic();
              const pretty = name.replace(/^lilith_/, "").replace(/_/g, " ").replace(/\.png$/, "");
              api("/api/settings", { method: "POST", body: JSON.stringify({ outfit: pretty }) })
                .then(function (res) {
                  if (res.ok) {
                    wear.textContent = "✅ Надето";
                    wear.disabled = true;
                    el("s-outfit").value = pretty;
                  }
                })
                .catch(function () { wear.textContent = "❌"; });
            });
            card.appendChild(wear);
            el("gallery").appendChild(card);
          });
        }

        appendStaticSection("📸 Реальные фото", realImages);
        appendStaticSection("🧪 Алхимик 2042", alchemyImages);
        appendStaticSection("👩🏫 Строгая учительница", teacherImages);
        appendStaticSection("👠 Доминанта", bossImages);
        appendStaticSection("✨ Образы Лилит", artImages);
        if (userImages.length) {
          const h = document.createElement("h3");
          h.className = "gallery-header";
          h.textContent = "🎨 Твои фото";
          el("gallery").appendChild(h);
          userImages.forEach(function (img) {
            el("gallery").appendChild(
              galleryCard(
                "/api/gallery/image/" + img.id,
                (img.created_at || "").replace("T", " ").slice(0, 16),
                "Lilith"
              )
            );
          });
        }
      })
      .catch(function () { el("gallery").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
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

  // ============================== ПОДЕЛИТЬСЯ (v2.1) ==============================
  el("share-btn").addEventListener("click", function () {
    haptic();
    try {
      if (tg) {
        tg.openTelegramLink("https://t.me/share/url?url=" + encodeURIComponent("https://t.me/LilithCompanionBot") + "&text=" + encodeURIComponent("Познакомься с Лилит 🖤 Она ждёт именно тебя"));
      } else {
        window.open("https://t.me/share/url?url=" + encodeURIComponent("https://t.me/LilithCompanionBot") + "&text=" + encodeURIComponent("Познакомься с Лилит 🖤"), "_blank");
      }
    } catch (e) { /* ignore */ }
  });

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
  renderScenes();
  loadStats();
  buildEmotionPanel();

  api("/api/me")
    .then(function (d) {
      fillSettings(d);
      fillLevel(d);
      currentStyle = d.image_style || "realistic";
      // Лилит всегда в белье — по умолчанию показываем бельевой аватар
      if (d.always_lingerie !== false && !currentClothes) {
        currentClothes = "lingerie";
        el("clothes-btn").textContent = "👗";
      }
      // Подгружаем историю диалога
      return api("/api/history").then(function (h) {
        const messages = h.messages || [];
        messages.forEach(function (m) { addBubble(m.role, m.content); });
        setAvatar("passion");
        if (!messages.length) {
          addBubble("assistant", "Ну привет, мой дорогой… Я уже заждалась. И я уже разгорячилась… Что скажешь?");
        }
      });
    })
    .catch(function (e) {
      const d = el("chat-placeholder");
      if (d) d.textContent = "Ошибка: " + e.message + ". Открой бота и нажми /start.";
    });
})();
