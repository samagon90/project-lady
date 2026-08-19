/* Лилит — автономная визуальная новелла (офлайн, без сервера) */
(function () {
  "use strict";

  var DATA = window.NOVEL_DATA;
  var data = DATA && DATA.scenarios ? DATA.scenarios : null;

  function el(id) { return document.getElementById(id); }

  // ============================== 18+ ГЕЙТ ==============================
  el("gate-enter").addEventListener("click", function () {
    try { localStorage.setItem("lilith_adult", "1"); } catch (e) { /* ignore */ }
    el("age-gate").style.display = "none";
    el("novel").style.display = "flex";
    if (data) showMenu();
  });

  el("gate-leave").addEventListener("click", function () {
    document.body.innerHTML = "<div style='padding:40px;text-align:center;color:#9a8494'>Приложение закрыто. Возвращайся, когда тебе будет 18 🖤</div>";
  });

  // Если уже подтверждал — пропускаем гейт
  try {
    if (localStorage.getItem("lilith_adult") === "1") {
      el("age-gate").style.display = "none";
      el("novel").style.display = "flex";
      if (data) showMenu();
    }
  } catch (e) { /* ignore */ }

  var currentData = null;
  var currentNodeId = null;

  // ============================== МЕНЮ ==============================
  function showMenu() {
    var img = el("novel-image");
    if (img) img.style.display = "none";
    el("novel-actions").style.display = "none";
    var textEl = el("novel-text");
    if (!data) {
      textEl.innerHTML = "<div class='novel-narrator'>Ошибка: данные не загружены.</div>";
      return;
    }
    var html = "<div class='novel-narrator'>📚 Выбери историю (18+):</div>";
    html += "<button class='novel-choice scenario-title' id='novel-gallery-btn'>"
      + "<span class='scenario-title-text'>🖼 Галерея — все фото Лилит</span>"
      + "<span class='scenario-sub'>просмотр всех изображений без игры</span></button>";
    // Продолжить с сохранения
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem("lilith_progress") || "null"); } catch (e) { saved = null; }
    if (saved && data[saved.scenario]) {
      html += "<button class='novel-choice scenario-title' id='novel-continue'>"
        + "<span class='scenario-title-text'>▶ Продолжить: " + data[saved.scenario].title + "</span>"
        + "<span class='scenario-sub'>продолжить с места остановки</span></button>";
    }
    textEl.innerHTML = html;

    var gbtn = el("novel-gallery-btn");
    if (gbtn) gbtn.addEventListener("click", function () { showGallery(); });

    var cont = el("novel-continue");
    if (cont) cont.addEventListener("click", function () {
      if (saved && data[saved.scenario]) {
        currentData = data[saved.scenario];
        currentNodeId = saved.node || currentData.start;
        renderNode();
      }
    });

    var choicesEl = el("novel-choices");
    choicesEl.innerHTML = "";
    choicesEl.style.display = "flex";
    Object.keys(data).forEach(function (sid) {
      var sc = data[sid];
      var btn = document.createElement("button");
      btn.className = "novel-choice scenario-title";
      var title = document.createElement("div");
      title.className = "scenario-title-text";
      title.textContent = sc.title;
      var sub = document.createElement("div");
      sub.className = "scenario-sub";
      sub.textContent = sc.subtitle + " · " + Object.keys(sc.nodes).length + " сцен";
      btn.appendChild(title);
      btn.appendChild(sub);
      btn.addEventListener("click", function () {
        currentData = sc;
        currentNodeId = sc.start;
        renderNode();
      });
      choicesEl.appendChild(btn);
    });
  }

  // ============================== ГАЛЕРЕЯ (все фото) ==============================
  var galleryList = window.GALLERY || [];
  var viewerIndex = 0;

  function seriesName(name) {
    var m = name.match(/^lilith_([a-z0-9]+)_/);
    var map = {
      real: "📸 Реальные", teacher: "👩🏫 Учительница", boss: "👠 Доминанта",
      alchemy: "🧪 Алхимик", animehot: "🔥 Аниме", naughty: "🔥 Развратная",
      novel: "🍸 Новелла", lingerie: "🩲 Бельё", latex: "🖤 Латекс",
      latex2: "🖤 Латекс 2", v2: "💜 Образы v2", nurse: "👩⚕️ Медсестра",
      business: "👔 Бизнес-леди", bizling: "👔 Бизнес-леди в белье"
    };
    return (m && map[m[1]]) ? map[m[1]] : "✨ Образы";
  }

  function showGallery() {
    currentData = null;
    el("novel-actions").style.display = "none";
    el("novel-choices").style.display = "none";
    el("novel-image").style.display = "none";
    el("novel-text").innerHTML =
      "<div class='novel-narrator'>🖼 Все фото Лилит (" + galleryList.length + "):</div>";
    var grid = document.createElement("div");
    grid.id = "gallery-grid";
    galleryList.forEach(function (name, i) {
      var item = document.createElement("div");
      item.className = "gallery-item";
      var img = document.createElement("img");
      img.src = "images/" + name;
      img.loading = "lazy";
      var label = document.createElement("div");
      label.className = "gallery-label";
      label.textContent = seriesName(name);
      item.appendChild(img);
      item.appendChild(label);
      item.addEventListener("click", function () { openViewer(i); });
      grid.appendChild(item);
    });
    el("novel-text").appendChild(grid);
  }

  function openViewer(i) {
    viewerIndex = i;
    el("viewer").style.display = "flex";
    renderViewer();
  }

  function renderViewer() {
    var name = galleryList[viewerIndex];
    el("viewer-img").src = "images/" + name;
    el("viewer-name").textContent = (viewerIndex + 1) + " / " + galleryList.length +
      " · " + seriesName(name);
  }

  // Кнопки просмотрщика (создаём один раз)
  var viewerDiv = document.createElement("div");
  viewerDiv.id = "viewer";
  viewerDiv.innerHTML =
    "<img id='viewer-img' alt=''>" +
    "<div id='viewer-name'></div>" +
    "<div id='viewer-controls'>" +
    "<button id='viewer-prev'>◀</button>" +
    "<button id='viewer-close'>✕ Закрыть</button>" +
    "<button id='viewer-next'>▶</button></div>";
  document.body.appendChild(viewerDiv);
  el("viewer-close").addEventListener("click", function () {
    el("viewer").style.display = "none";
  });
  el("viewer-prev").addEventListener("click", function () {
    viewerIndex = (viewerIndex - 1 + galleryList.length) % galleryList.length;
    renderViewer();
  });
  el("viewer-next").addEventListener("click", function () {
    viewerIndex = (viewerIndex + 1) % galleryList.length;
    renderViewer();
  });

  // ============================== УЗЕЛ ==============================
  function renderNode() {
    if (!currentData) return;
    var node = currentData.nodes[currentNodeId];
    if (!node) return;
    var img = el("novel-image");
    img.style.display = "block";
    img.src = "images/" + node.image;

    var textEl = el("novel-text");
    var html = "<div class='novel-narrator'>" + esc(node.narrator || "") + "</div>";
    if (node.lilith) {
      html += "<div class='novel-lilith'>🖤 Лилит: " + esc(node.lilith) + "</div>";
    }
    textEl.innerHTML = html;

    var choicesEl = el("novel-choices");
    choicesEl.innerHTML = "";
    (node.choices || []).forEach(function (choice) {
      var btn = document.createElement("button");
      btn.className = "novel-choice";
      btn.textContent = choice[0];
      btn.addEventListener("click", function () {
        currentNodeId = choice[1];
        try {
          localStorage.setItem("lilith_progress", JSON.stringify({
            scenario: currentData._id || "",
            node: currentNodeId
          }));
        } catch (e) { /* ignore */ }
        renderNode();
      });
      choicesEl.appendChild(btn);
    });

    var isEnding = !!node.ending;
    el("novel-actions").style.display = "block";
    el("novel-restart").style.display = isEnding ? "block" : "none";
    el("novel-menu-btn").style.display = "block";
    choicesEl.style.display = isEnding ? "none" : "flex";
  }

  el("novel-restart").addEventListener("click", function () {
    currentNodeId = currentData.start;
    renderNode();
  });

  el("novel-menu-btn").addEventListener("click", showMenu);

  // ============================== helpers ==============================
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Присваиваем _id сценариям (для сохранения прогресса)
  if (data) {
    Object.keys(data).forEach(function (sid) { data[sid]._id = sid; });
  }
})();
