/* Лилит Mini App — логика */
(function () {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor("#12070f");
    tg.setBackgroundColor("#12070f");
  }

  const INIT_DATA = tg ? tg.initData : "";

  function api(path, options) {
    const opts = options || {};
    const headers = Object.assign(
      { "X-Init-Data": INIT_DATA },
      opts.headers || {}
    );
    if (opts.body) headers["Content-Type"] = "application/json";
    return fetch(path, { method: opts.method || "GET", headers, body: opts.body }).then(function (r) {
      if (r.status === 401) throw new Error("Не авторизовано");
      return r.json();
    });
  }

  function el(id) { return document.getElementById(id); }

  const MODES = { 0: "🤝 Дружеский", 1: "😉 Флирт", 2: "💞 Романтический", 3: "🔞 NSFW" };

  // ---- вкладки
  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      el("tab-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "gallery") loadGallery();
      if (btn.dataset.tab === "memory") loadMemory();
    });
  });

  // ---- профиль
  function fillProfile(d) {
    el("p-name").textContent = d.name || "—";
    el("p-mode").textContent = MODES[d.mode] || d.mode;
    el("p-voice").textContent = d.voice_enabled ? "🎙 вкл" : "🔇 выкл";
    el("p-style").textContent = d.image_style === "anime" ? "🖌 аниме" : "📸 реалистичный";
    el("p-outfit").textContent = d.outfit || "—";
    el("p-speech").textContent = d.speech_style || "—";
    el("p-nsfw").textContent = d.consent_nsfw ? "✅ есть" : "—";
    el("mode-label").textContent = MODES[d.mode] || "";
  }

  // ---- настройки
  function fillSettings(d) {
    el("s-name").value = d.name || "";
    el("s-mode").value = String(d.mode);
    el("s-style").value = d.image_style || "realistic";
    el("s-voice").value = d.voice_enabled ? "true" : "false";
    el("s-outfit").value = d.outfit || "";
    el("s-speech").value = d.speech_style || "";
  }

  el("save").addEventListener("click", function () {
    const body = JSON.stringify({
      name: el("s-name").value.trim(),
      mode: parseInt(el("s-mode").value, 10),
      image_style: el("s-style").value,
      voice_enabled: el("s-voice").value === "true",
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
      .then(function (me) { if (me) { fillProfile(me); fillSettings(me); } })
      .catch(function (e) { el("save-msg").textContent = "❌ " + e.message; })
      .finally(function () { el("save").disabled = false; });
  });

  // ---- галерея
  function loadGallery() {
    el("gallery").innerHTML = '<p class="hint">Загрузка…</p>';
    api("/api/gallery")
      .then(function (res) {
        const images = (res.images || []).filter(function (i) { return i.file_path; });
        if (!images.length) {
          el("gallery").innerHTML = '<p class="hint">Пока нет сгенерированных фото. Отправь боту «нарисуй…»</p>';
          return;
        }
        el("gallery").innerHTML = "";
        images.forEach(function (img) {
          const card = document.createElement("div");
          card.className = "card";
          const caption = document.createElement("div");
          caption.className = "card-date";
          caption.textContent = (img.created_at || "").replace("T", " ").slice(0, 16);
          card.appendChild(caption);
          el("gallery").appendChild(card);
        });
      })
      .catch(function () { el("gallery").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
  }

  // ---- память
  function loadMemory() {
    el("memory").innerHTML = '<p class="hint">Загрузка…</p>';
    api("/api/memory")
      .then(function (res) {
        const items = res.items || [];
        if (!items.length) {
          el("memory").innerHTML = '<p class="hint">Память пуста — Лилит запомнит всё важное по ходу разговора.</p>';
          return;
        }
        el("memory").innerHTML = "";
        items.forEach(function (item) {
          const row = document.createElement("div");
          row.className = "memory-item";
          row.innerHTML = "<span class='tag'>" + escapeHtml(item.category) + "</span> " + escapeHtml(item.fact);
          el("memory").appendChild(row);
        });
      })
      .catch(function () { el("memory").innerHTML = '<p class="hint">Не удалось загрузить</p>'; });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---- старт
  api("/api/me")
    .then(function (d) { fillProfile(d); fillSettings(d); })
    .catch(function (e) {
      el("tab-profile").innerHTML = '<p class="hint">Ошибка: ' + escapeHtml(e.message) + '. Открой бота и нажми /start.</p>';
    });
})();
