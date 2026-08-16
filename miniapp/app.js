/* Лилит — визуальная новелла в Telegram Mini App */
(function () {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor("#12070f");
    tg.setBackgroundColor("#12070f");
  }

  const INIT_DATA = tg ? tg.initData : "";
  const MODES = { 0: "🤝 Дружеский", 1: "😉 Флирт", 2: "💞 Романтический", 3: "🔞 NSFW" };

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

  // ---- Определение эмоции по тексту (для аватара)
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

  let currentStyle = "realistic";
  let currentEmotion = "neutral";
  let currentStage = 1; // 1=одета, 2=блузка расстёгнута, 3=в белье/чулках, 4=топлес
  let currentClothes = ""; // "" = школьный костюм, "lingerie" = нижнее бельё

  function setAvatar(emotion, stage) {
    currentEmotion = emotion || "neutral";
    if (stage) currentStage = Math.max(1, Math.min(4, stage));
    const stagePath = currentStage > 1 ? "&stage=" + currentStage : "";
    const clothesPath = currentClothes ? "&clothes=" + currentClothes : "";
    el("avatar").src = "/api/avatar?style=" + currentStyle + "&emotion=" + currentEmotion + stagePath + clothesPath;
    const labels = {
      neutral: "😌", flirt: "😏", passion: "🔥", playful: "😜", tender: "💗", serious: "😐",
      happy: "😊", sad: "😢", angry: "😠", surprised: "😲", shy: "😳", proud: "😎",
      jealous: "😒", bored: "🥱", excited: "🤩", sleepy: "😴", crying: "😭", scared: "😨",
      disgust: "🤢", contempt: "🙄", relief: "😮‍💨", thinking: "🤔", confused: "😕"
    };
    el("emotion-tag").textContent = labels[currentEmotion] || "😌";
    // индикатор раскованности
    const mood = ["👗", "👙", "🩲", "🔥"][currentStage - 1];
    el("mood-tag").textContent = mood + " " + currentStage + "/4";
  }

  // ---- Чат (диалог с Лилит через бота)
  let chatHistory = [];
  function addMessage(role, text) {
    chatHistory.push({ role: role, text: text });
    const d = el("dialogue-text");
    d.textContent = (role === "user" ? "Ты: " : "") + text;
    // эмоция по ответу Лилит
    if (role === "assistant") setAvatar(detectEmotion(text));
    d.scrollIntoView({ block: "nearest" });
  }

  function sendChat() {
    const input = el("chat-input");
    const text = input.value.trim();
    if (!text) return;
    lastUserText = text;
    altIndex = -1;
    altList = [];
    input.value = "";
    addMessage("user", text);
    // Лилит «думает»
    el("dialogue-text").textContent = "…";
    api("/api/chat", { method: "POST", body: JSON.stringify({ text: text }) })
      .then(function (res) {
        if (res.reply) addMessage("assistant", res.reply);
        else addMessage("assistant", "…");
        // Лилит реагирует: меняет позу (эмоция) и раскованность (stage)
        if (res.emotion) setAvatar(res.emotion, res.stage || currentStage);
        // Повышение уровня отношений (фича Replika)
        if (res.level_up) {
          var tag = el("level-tag");
          if (tag) tag.textContent = "💜 " + res.level_up;
        }
      })
      .catch(function (e) {
        addMessage("assistant", "… (модель не ответила: " + (e.message || "ошибка") + ")");
      });
  }

  // ---- Генерация образа в выбранном наряде (сервер сам рисует и пришлёт в Telegram)
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

  el("generate-outfit").addEventListener("click", generateOutfit);

  // Кнопка «в белье / одеться»
  const clothesBtn = document.createElement("button");
  clothesBtn.id = "clothes-btn";
  clothesBtn.textContent = "🩲 В белье";
  document.getElementById("input-row").appendChild(clothesBtn);
  clothesBtn.addEventListener("click", function () {
    currentClothes = currentClothes === "lingerie" ? "" : "lingerie";
    clothesBtn.textContent = currentClothes === "lingerie" ? "👗 Одеться" : "🩲 В белье";
    setAvatar(currentEmotion);
  });

  // ---- Свайпы: «🔄 Другой ответ» (фича Character.AI / SillyTavern)
  let lastUserText = "";
  let altIndex = -1;
  let altList = [];

  function doSwipe() {
    if (!lastUserText) return;
    const d = el("dialogue-text");
    d.textContent = "…";
    api("/api/chat/alternatives", { method: "POST", body: JSON.stringify({ text: lastUserText, n: 3 }) })
      .then(function (res) {
        if (!res.alternatives || !res.alternatives.length) throw new Error("нет вариантов");
        altList = res.alternatives;
        altIndex = (altIndex + 1) % altList.length;
        addMessage("assistant", altList[altIndex]);
      })
      .catch(function (e) {
        addMessage("assistant", "… (не получилось: " + (e.message || "ошибка") + ")");
      });
  }

  el("swipe-btn").addEventListener("click", doSwipe);

  el("send-btn").addEventListener("click", sendChat);
  el("chat-input").addEventListener("keydown", function (e) { if (e.key === "Enter") sendChat(); });

  // ---- Вкладки
  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      if (tab === "chat") { el("dialogue-box").style.display = "block"; return; }
      el("dialogue-box").style.display = "none";
      el("tab-" + tab).classList.add("active");
      if (tab === "gallery") loadGallery();
      if (tab === "memory") loadMemory();
      if (tab === "diary") loadDiary();
    });
  });

  // ---- Настройки
  function fillSettings(d) {
    el("s-name").value = d.name || "";
    el("s-mode").value = String(d.mode);
    el("s-style").value = d.image_style || "realistic";
    el("s-creativity").value = String(d.creativity != null ? d.creativity : 1);
    el("s-length").value = String(d.response_length != null ? d.response_length : 1);
    el("s-outfit").value = d.outfit || "";
    el("s-speech").value = d.speech_style || "";
  }

  // Уровень отношений (фича Replika): плашка рядом с именем Лилит
  function fillLevel(d) {
    var tag = el("level-tag");
    if (!tag) return;
    var lvl = d.level || 1;
    var name = d.level_name || "";
    var xpToNext = d.xp_to_next || 0;
    var progress = Math.round((d.level_progress || 0) * 100);
    tag.textContent = "💜 " + lvl + "/7 " + name;
    tag.title = "Уровень отношений: " + name + ". До следующего уровня: " + xpToNext + " XP (прогресс " + progress + "%)";
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
      .then(function (me) { if (me) { fillSettings(me); currentStyle = me.image_style || "realistic"; setAvatar(); } })
      .catch(function (e) { el("save-msg").textContent = "❌ " + e.message; })
      .finally(function () { el("save").disabled = false; });
  });

  // ---- Галерея и память (как раньше)
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
      var entries = res.entries || [];
      if (!entries.length) {
        el("diary").innerHTML = '<p class="hint">Пока пусто. Лилит напишет первую запись вечером, после вашего разговора 💜</p>';
        return;
      }
      el("diary").innerHTML = "";
      entries.forEach(function (item) {
        var card = document.createElement("div");
        card.className = "diary-item";
        var date = document.createElement("div");
        date.className = "diary-date";
        date.textContent = "📅 " + item.date;
        var text = document.createElement("div");
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

  // ---- Старт
  // Любая ошибка ниже должна ПОКАЗЫВАТЬСЯ на экране, а не убивать приложение молча
  window.addEventListener("error", function (ev) {
    try {
      var d = document.getElementById("dialogue-text");
      if (d) d.textContent = "⚠️ Ошибка: " + (ev.message || "неизвестная") + ". Обнови Mini App.";
    } catch (e) { /* ignore */ }
  });

  api("/api/me")
    .then(function (d) {
      fillSettings(d);
      fillLevel(d);
      currentStyle = d.image_style || "realistic";
      setAvatar("flirt");
      addMessage("assistant", "Ну привет, мой дорогой… Я уже заждалась. Что скажешь?");
    })
    .catch(function (e) {
      el("dialogue-text").textContent = "Ошибка: " + e.message + ". Открой бота и нажми /start.";
    });
})();
