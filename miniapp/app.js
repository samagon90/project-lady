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
    const headers = Object.assign({ "X-Init-Data": INIT_DATA }, opts.headers || {});
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

  function setAvatar(emotion, stage) {
    currentEmotion = emotion || "neutral";
    if (stage) currentStage = Math.max(1, Math.min(4, stage));
    const stagePath = currentStage > 1 ? "&stage=" + currentStage : "";
    el("avatar").src = "/api/avatar?style=" + currentStyle + "&emotion=" + currentEmotion + stagePath;
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
      })
      .catch(function () {
        addMessage("assistant", "Связь прервалась… Попробуй ещё раз.");
      });
  }

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
    });
  });

  // ---- Настройки
  function fillSettings(d) {
    el("s-name").value = d.name || "";
    el("s-mode").value = String(d.mode);
    el("s-style").value = d.image_style || "realistic";
    el("s-outfit").value = d.outfit || "";
    el("s-speech").value = d.speech_style || "";
  }

  el("save").addEventListener("click", function () {
    const body = JSON.stringify({
      name: el("s-name").value.trim(),
      mode: parseInt(el("s-mode").value, 10),
      image_style: el("s-style").value,
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
        const cap = document.createElement("div");
        cap.className = "card-date";
        cap.textContent = (img.created_at || "").replace("T", " ").slice(0, 16);
        card.appendChild(cap);
        el("gallery").appendChild(card);
      });
    }).catch(function () { el("gallery").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
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
  api("/api/me")
    .then(function (d) {
      fillSettings(d);
      currentStyle = d.image_style || "realistic";
      setAvatar("flirt");
      addMessage("assistant", "Ну привет, мой дорогой… Я уже заждалась. Что скажешь?");
    })
    .catch(function (e) {
      el("dialogue-text").textContent = "Ошибка: " + e.message + ". Открой бота и нажми /start.";
    });
})();
