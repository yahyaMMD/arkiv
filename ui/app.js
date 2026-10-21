const ui = { selected: "", state: null, modalAction: null, bound: false, timer: null };

function setVisible(node, visible) {
  node.hidden = !visible;
  node.classList.toggle("hidden", !visible);
}

const $ = (id) => document.getElementById(id);

const API_ROUTES = {
  get_state: { method: "GET", path: "/api/state" },
  list_files: { method: "GET", path: "/api/files", query: (category) => ({ category: category || "" }) },
  choose_folder: { method: "POST", path: "/api/choose_folder" },
  confirm_library: { method: "POST", path: "/api/confirm_library", body: (path) => ({ path }) },
  start_sort: { method: "POST", path: "/api/start_sort" },
  cancel_sort: { method: "POST", path: "/api/cancel_sort" },
  undo_last: { method: "POST", path: "/api/undo_last" },
  set_auto_sort: { method: "POST", path: "/api/set_auto_sort", body: (enabled) => ({ enabled: Boolean(enabled) }) },
  set_model: { method: "POST", path: "/api/set_model", body: (model) => ({ model }) },
  set_api_key: { method: "POST", path: "/api/set_api_key", body: (key) => ({ key }) },
  test_connection: { method: "POST", path: "/api/test_connection" },
  open_root: { method: "POST", path: "/api/open_root" },
  open_category: { method: "POST", path: "/api/open_category", body: (name) => ({ name }) },
  reveal_file: { method: "POST", path: "/api/reveal_file", body: (path) => ({ path }) },
};

async function call(name, ...args) {
  if (window.__arkivDemo && typeof window.__arkivDemo[name] === "function") {
    return window.__arkivDemo[name](...args);
  }
  const route = API_ROUTES[name];
  if (!route) throw new Error(`Unknown Arkiv action: ${name}`);
  let url = route.path;
  if (route.query) {
    const params = new URLSearchParams(route.query(...args));
    url = `${url}?${params.toString()}`;
  }
  const options = { method: route.method, headers: { Accept: "application/json" } };
  if (route.method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(route.body ? route.body(...args) : {});
  }
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(text || "Arkiv returned an invalid response.");
  }
  if (!response.ok) {
    const message = (data && data.error) || `Arkiv request failed (${response.status}).`;
    throw new Error(message);
  }
  return data;
}

function toast(message) {
  if (!message) return;
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => node.classList.remove("show"), 4200);
}

function shortModel(id) {
  const names = {
    "google/gemini-2.5-flash": "Gemini 2.5 Flash",
    "google/gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    "openai/gpt-4.1-mini": "GPT-4.1 mini",
    "openai/gpt-4o-mini": "GPT-4o mini",
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
  };
  return names[id] || id || "Model";
}

function percent(value) {
  const number = Number(value || 0);
  return `${Math.round(number * 100)}%`;
}

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function button(className, label, attrs) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.textContent = label;
  Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function openModal({ kicker, title, body, confirmLabel, onConfirm }) {
  $("modal-kicker").textContent = kicker || "";
  $("modal-title").textContent = title || "";
  $("modal-body").textContent = body || "";
  $("modal-ok").textContent = confirmLabel || "Continue";
  ui.modalAction = onConfirm;
  $("modal").classList.remove("hidden");
}

function closeModal() {
  $("modal").classList.add("hidden");
  ui.modalAction = null;
}

function openSettings() {
  const state = ui.state || {};
  const select = $("model");
  if (state.model && !Array.from(select.options).some((option) => option.value === state.model)) {
    const extra = document.createElement("option");
    extra.value = state.model;
    extra.textContent = state.model;
    select.appendChild(extra);
  }
  if (document.activeElement !== select) select.value = state.model || select.value;
  $("key-hint").textContent = state.key_hint ? `Saved key ending ${state.key_hint.slice(-4)}` : "No key saved yet.";
  $("key-status").textContent = "";
  $("settings").classList.remove("hidden");
}

function closeSettings() {
  $("settings").classList.add("hidden");
}

async function refresh() {
  if (refresh.running) return;
  refresh.running = true;
  try {
    const state = await call("get_state");
    if (ui.selected && !(state.categories || []).some((item) => item.name === ui.selected)) {
      ui.selected = "";
    }
    if (ui.selected) state.visible = await call("list_files", ui.selected);
    else state.visible = state.recent || [];
    ui.state = state;
    ui.bootFailures = 0;
    render(state);
  } catch (error) {
    ui.bootFailures = (ui.bootFailures || 0) + 1;
    if (!$("boot").classList.contains("hidden") && ui.bootFailures >= 3) {
      $("boot").textContent = "Connecting to Arkiv…";
    }
    if (!$("boot").classList.contains("hidden") && ui.bootFailures >= 20) {
      $("boot").textContent = "Could not connect to Arkiv. Close the window and open START Arkiv.bat again.";
    }
  } finally {
    refresh.running = false;
  }
}

function render(state) {
  $("boot").classList.add("hidden");
  const ready = Boolean(state.root);
  setVisible($("welcome"), !ready);
  setVisible($("library"), ready);
  setVisible($("path-button"), ready);
  setVisible($("watch"), ready);
  setVisible($("model-button"), ready);
  if (!ready) return;

  $("path-button").textContent = state.root;
  $("watch").setAttribute("aria-pressed", state.auto_sort ? "true" : "false");
  $("watch-label").textContent = state.auto_sort ? "Watching for new files" : "Watch off";
  $("model-button").textContent = shortModel(state.model);
  const filed = state.stats ? state.stats.files : 0;
  const categories = state.stats ? state.stats.categories : 0;
  $("stat-line").textContent = `${filed} filed · ${categories} categories`;
  renderCategories(state);
  renderDesk(state);
  renderLedger(state);
}

function samePaint(node, signature) {
  if (node.dataset.paint === signature) return true;
  node.dataset.paint = signature;
  return false;
}

function renderCategories(state) {
  const list = $("category-list");
  const signature = JSON.stringify([ui.selected, state.unsorted, state.sorting, state.stats, state.categories, state.unsorted_label]);
  if (samePaint(list, signature)) return;
  const scroll = list.scrollTop;
  const rows = [];
  rows.push(categoryRow("__all__", "Entire library", state.stats.files, !ui.selected, "Everything already filed"));
  if (state.unsorted > 0 && !state.sorting) {
    rows.push(categoryRow("__waiting__", "Waiting", state.unsorted, false, state.unsorted_label));
  }
  (state.categories || []).forEach((category) => {
    rows.push(categoryRow(
      category.name,
      category.name,
      category.count,
      ui.selected === category.name,
      category.description || "",
    ));
  });
  list.replaceChildren(...rows);
  list.scrollTop = scroll;
}

function categoryRow(id, name, count, active, detail) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = `cat${active ? " active" : ""}`;
  node.dataset.category = id;
  const title = document.createElement("strong");
  title.textContent = name;
  const total = document.createElement("em");
  total.className = "nums";
  total.textContent = String(count || 0);
  node.append(title, total);
  if (detail) {
    const small = document.createElement("small");
    small.textContent = detail;
    node.append(small);
  }
  return node;
}

function renderDesk(state) {
  const progress = state.progress || {};
  const sorting = Boolean(state.sorting);
  const kicker = $("desk-kicker");
  const title = $("desk-title");
  const text = $("desk-text");
  const bar = $("progress");
  if (sorting) {
    const phase = progress.phase;
    if (phase === "counting") kicker.textContent = "Counting";
    else if (phase === "taxonomy") kicker.textContent = "Choosing categories";
    else kicker.textContent = `Filing ${progress.current || 0} of ${progress.total || 0}`;
    title.textContent = progress.file || state.root_name || "Library";
    text.textContent = progress.detail || "Reading the next file.";
    const total = Number(progress.total || 0);
    const current = Number(progress.current || 0);
    const amount = phase === "taxonomy" ? 8 : total ? Math.min(100, Math.round((current / total) * 100)) : 0;
    $("bar-fill").style.width = `${amount}%`;
    $("progress-label").textContent = progress.file ? progress.file : state.unsorted_label;
    bar.classList.remove("hidden");
  } else {
    kicker.textContent = ui.selected ? "Category" : "Library";
    title.textContent = ui.selected || state.root_name || "Library";
    if (ui.selected) {
      const match = (state.categories || []).find((item) => item.name === ui.selected);
      text.textContent = match && match.description ? match.description : "Files filed in this category.";
    } else if (state.unsorted > 0) {
      text.textContent = `${state.unsorted_label} waiting to be filed. Arkiv will read each one and move it into a category folder.`;
    } else {
      text.textContent = state.message || "Every file already in this library has a category. New files dropped here will be classified too.";
    }
    bar.classList.add("hidden");
  }

  const actions = $("desk-actions");
  const actionKey = JSON.stringify([sorting, state.unsorted, ui.selected, progress.phase, progress.current, progress.total]);
  const controls = [];
  if (sorting) {
    controls.push(button("btn ghost", "Stop", { "data-action": "cancel" }));
  } else {
    const waiting = Number(state.unsorted || 0);
    const label = waiting ? `Classify ${waiting} ${waiting === 1 ? "file" : "files"}` : "Library is current";
    const start = button("btn primary", label, { "data-action": "sort" });
    if (!waiting) start.disabled = true;
    controls.push(start);
    controls.push(button("btn ghost", "Undo last filing", { "data-action": "undo" }));
    if (ui.selected) controls.push(button("btn ghost", "Open category folder", { "data-action": "open-category" }));
  }
  if (!samePaint(actions, actionKey)) actions.replaceChildren(...controls);
  renderCard(state);
}

function renderCard(state) {
  const card = $("card");
  const latest = (state.recent || [])[0];
  if (samePaint(card, JSON.stringify(latest || null))) return;
  card.className = "card";
  if (!latest) {
    card.replaceChildren();
    const index = document.createElement("p");
    index.className = "index";
    index.textContent = "Catalog";
    const title = document.createElement("h3");
    title.textContent = "Nothing filed yet";
    const copy = document.createElement("p");
    copy.textContent = "The catalog card will show each file after Arkiv reads it.";
    card.append(index, title, copy);
    return;
  }
  if (latest.status === "error") card.classList.add("is-error");
  const index = document.createElement("p");
  index.className = "index";
  index.textContent = latest.status === "error" ? "Could not file" : (latest.category || "Filed");
  const title = document.createElement("h3");
  title.textContent = latest.name || "File";
  const copy = document.createElement("p");
  copy.textContent = latest.status === "error" ? (latest.error || "The model could not read this file.") : (latest.summary || "");
  const meta = document.createElement("p");
  meta.className = "meta nums";
  const bits = [];
  if (latest.status !== "error" && latest.confidence) bits.push(percent(latest.confidence));
  if (latest.updated_at) bits.push(when(latest.updated_at));
  meta.textContent = bits.join(" · ");
  card.replaceChildren(index, title, copy, meta);
}

function renderLedger(state) {
  const files = state.visible || [];
  const list = $("ledger-list");
  if (samePaint(list, JSON.stringify([ui.selected, files]))) {
    $("ledger-kicker").textContent = ui.selected ? ui.selected : "Latest filings";
    $("ledger-count").textContent = files.length ? `${files.length} shown` : "";
    return;
  }
  $("ledger-kicker").textContent = ui.selected ? ui.selected : "Latest filings";
  $("ledger-count").textContent = files.length ? `${files.length} shown` : "";
  const scroll = list.scrollTop;
  if (!files.length) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "Classifications will appear here, one file at a time.";
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...files.map(entryRow));
  list.scrollTop = scroll;
}

function entryRow(item) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = `entry${item.status === "error" ? " is-error" : ""}`;
  node.dataset.path = item.current_path || "";
  const row = document.createElement("div");
  row.className = "row";
  const name = document.createElement("strong");
  name.textContent = item.name || "File";
  const pill = document.createElement("span");
  pill.className = "pill";
  pill.textContent = item.status === "error" ? "Not filed" : (item.category || "Filed");
  row.append(name, pill);
  const summary = document.createElement("p");
  summary.className = "clamp";
  summary.textContent = item.status === "error" ? (item.error || "") : (item.summary || "");
  const meta = document.createElement("small");
  meta.textContent = when(item.updated_at);
  node.append(row, summary, meta);
  return node;
}

async function chooseFolder() {
  try {
    const result = await call("choose_folder");
    if (!result || !result.ok) {
      if (result && result.error) toast(result.error);
      return;
    }
    const state = ui.state || {};
    const switching = state.root && state.root !== result.path;
    const empty = result.count === 0;
    let title = "File this library?";
    let body = `Arkiv found ${result.label} in "${result.name}". It will read each file and move it into a category folder inside that same folder. You can undo the most recent filing. Short excerpts are sent to OpenRouter.`;
    let confirmLabel = "Start classifying";
    if (empty) {
      title = "Watch this folder?";
      body = `"${result.name}" has no files yet. Arkiv will keep using it and classify anything you add.`;
      confirmLabel = "Use this folder";
    } else if (switching) {
      title = "Switch the library?";
      body = `Arkiv will leave "${state.root_name}" and file ${result.label} in "${result.name}". Files already moved stay where they are.`;
      confirmLabel = "Switch and classify";
    } else if (state.root) {
      title = "Classify waiting files?";
      body = `${result.label} in "${result.name}" are not in a category folder yet.`;
      confirmLabel = "Classify";
    }
    openModal({
      kicker: "Library",
      title,
      body,
      confirmLabel,
      onConfirm: async () => {
        const response = await call("confirm_library", result.path);
        if (!response.ok) {
          toast(response.error || "Could not use that folder.");
          if ((response.error || "").toLowerCase().includes("key")) openSettings();
        }
        await refresh();
      },
    });
  } catch (error) {
    toast("Could not open the folder picker.");
  }
}

async function startSort() {
  const response = await call("start_sort");
  if (!response.ok) toast(response.error || "Could not start.");
  await refresh();
}

async function undo() {
  const response = await call("undo_last");
  if (!response.ok) toast(response.error || "Could not undo.");
  else if (response.message) toast(response.message);
  await refresh();
}

function bind() {
  if (ui.bound) return;
  ui.bound = true;
  $("choose").addEventListener("click", chooseFolder);
  $("change").addEventListener("click", chooseFolder);
  $("settings-open").addEventListener("click", openSettings);
  $("model-button").addEventListener("click", openSettings);
  $("settings-close").addEventListener("click", closeSettings);
  $("modal-cancel").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (event) => {
    if (event.target.id === "modal") closeModal();
  });
  $("modal-ok").addEventListener("click", async () => {
    const action = ui.modalAction;
    closeModal();
    if (action) await action();
  });
  $("watch").addEventListener("click", async () => {
    const enabled = $("watch").getAttribute("aria-pressed") !== "true";
    const response = await call("set_auto_sort", enabled);
    if (!response.ok && response.error) toast(response.error);
    await refresh();
  });
  $("reveal").addEventListener("click", () => call("open_root"));
  $("path-button").addEventListener("click", () => call("open_root"));
  $("desk-actions").addEventListener("click", async (event) => {
    const action = event.target.closest("[data-action]");
    if (!action) return;
    if (action.dataset.action === "sort") await startSort();
    if (action.dataset.action === "undo") await undo();
    if (action.dataset.action === "cancel") await call("cancel_sort");
    if (action.dataset.action === "open-category" && ui.selected) {
      const response = await call("open_category", ui.selected);
      if (!response.ok) toast(response.error || "Could not open that folder.");
    }
  });
  $("category-list").addEventListener("click", (event) => {
    const node = event.target.closest("[data-category]");
    if (!node) return;
    const value = node.dataset.category;
    if (value === "__waiting__") {
      ui.selected = "";
    } else {
      ui.selected = value === "__all__" ? "" : value;
    }
    refresh();
  });
  $("ledger-list").addEventListener("click", async (event) => {
    const node = event.target.closest("[data-path]");
    if (!node || !node.dataset.path) return;
    const response = await call("reveal_file", node.dataset.path);
    if (response && !response.ok && response.error) toast(response.error);
  });
  $("model").addEventListener("change", async () => {
    const response = await call("set_model", $("model").value);
    if (!response.ok) toast(response.error || "Could not change the model.");
    await refresh();
  });
  $("save-key").addEventListener("click", saveKey);
  $("test-key").addEventListener("click", async () => {
    $("key-status").textContent = "Contacting OpenRouter…";
    const saved = await saveKey(false);
    if (!saved) return;
    const response = await call("test_connection");
    $("key-status").textContent = response.message || "";
    if (!response.ok) toast(response.message);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeModal();
    closeSettings();
  });
}

async function saveKey(showToast = true) {
  const custom = $("custom-model").value.trim();
  if (custom) {
    const model = await call("set_model", custom);
    if (!model.ok) {
      toast(model.error || "Could not save that model.");
      return false;
    }
  }
  const response = await call("set_api_key", $("api-key").value);
  if (!response.ok) {
    toast(response.error || "Could not save the key.");
    return false;
  }
  $("api-key").value = "";
  if (showToast) toast("Key saved.");
  await refresh();
  if (ui.state && ui.state.key_hint) {
    $("key-hint").textContent = `Saved key ending ${ui.state.key_hint.slice(-4)}`;
  }
  return true;
}

function start() {
  if (ui.started) return;
  ui.started = true;
  bind();
  refresh();
  if (!ui.timer) ui.timer = setInterval(refresh, 700);
}

async function waitForApi() {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch("/api/ping", { cache: "no-store" });
      if (response.ok) return true;
    } catch {
      // server still coming up
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  return false;
}

async function bootWhenReady() {
  if (new URLSearchParams(location.search).has("demo")) {
    window.__arkivDemo = createDemo();
    start();
    return;
  }
  $("boot").textContent = "Opening the library…";
  const ready = await waitForApi();
  if (!ready) {
    $("boot").textContent = "Could not connect to Arkiv. Close this window and open START Arkiv.bat again.";
    return;
  }
  start();
}

bootWhenReady();

function createDemo() {
  const state = {
    root: "",
    root_name: "",
    model: "google/gemini-2.5-flash",
    auto_sort: true,
    watching: false,
    confirmed: false,
    has_key: true,
    key_hint: "••••demo",
    unsorted: 0,
    unsorted_label: "Empty folder",
    sorting: false,
    progress: { phase: "idle", current: 0, total: 0, file: "", detail: "" },
    message: "",
    categories: [],
    recent: [],
    stats: { files: 0, categories: 0 },
  };
  const samples = [
    ["invoice-march.pdf", "Invoices", "A supplier invoice for March rent.", 0.94],
    ["lecture-notes.docx", "Schoolwork", "Notes from a philosophy lecture.", 0.9],
    ["screenshot.png", "Screenshots", "A screen capture of a proof layout.", 0.88],
    ["holiday.mov", "Videos", "A short video named like a holiday clip.", 0.8],
  ];
  let cursor = 0;
  let timer = null;

  function tick() {
    if (cursor >= samples.length) {
      state.sorting = false;
      state.progress = { phase: "idle", current: samples.length, total: samples.length, file: "", detail: "" };
      state.unsorted = 0;
      state.unsorted_label = "Empty folder";
      state.message = "Filed 4 files into 4 categories.";
      state.watching = state.auto_sort;
      return;
    }
    const [name, category, summary, confidence] = samples[cursor];
    cursor += 1;
    state.sorting = true;
    state.progress = {
      phase: "classifying",
      current: cursor,
      total: samples.length,
      file: name,
      detail: `${category} · ${summary}`,
    };
    const existing = state.categories.find((item) => item.name === category);
    if (existing) existing.count += 1;
    else state.categories.push({ name: category, description: summary, count: 1 });
    state.recent.unshift({
      name,
      category,
      summary,
      confidence,
      current_path: `/demo/${category}/${name}`,
      status: "filed",
      updated_at: new Date().toISOString(),
    });
    state.stats.files += 1;
    state.stats.categories = state.categories.length;
    state.unsorted = samples.length - cursor;
    timer = setTimeout(tick, 700);
  }

  return {
    get_state: async () => JSON.parse(JSON.stringify(state)),
    list_files: async (category) => state.recent.filter((item) => item.category === category),
    choose_folder: async () => ({ ok: true, path: "/demo/Papers", name: "Papers", count: 4, label: "4 files · 2.4 MB" }),
    confirm_library: async () => {
      state.root = "/demo/Papers";
      state.root_name = "Papers";
      state.confirmed = true;
      state.unsorted = 4;
      state.unsorted_label = "4 files · 2.4 MB";
      state.sorting = true;
      state.progress = { phase: "taxonomy", current: 0, total: 4, file: "", detail: "Choosing categories" };
      clearTimeout(timer);
      cursor = 0;
      timer = setTimeout(tick, 600);
      return { ok: true };
    },
    start_sort: async () => ({ ok: true }),
    cancel_sort: async () => {
      clearTimeout(timer);
      state.sorting = false;
      state.message = "Stopped.";
      return { ok: true };
    },
    undo_last: async () => {
      state.recent = [];
      state.categories = [];
      state.stats = { files: 0, categories: 0 };
      state.unsorted = 4;
      state.unsorted_label = "4 files · 2.4 MB";
      state.message = "Moved 4 files back.";
      return { ok: true, message: state.message };
    },
    set_auto_sort: async (enabled) => {
      state.auto_sort = Boolean(enabled);
      state.watching = Boolean(enabled) && Boolean(state.root);
      return { ok: true, auto_sort: state.auto_sort };
    },
    set_model: async (model) => {
      state.model = model;
      return { ok: true };
    },
    set_api_key: async () => ({ ok: true, key_hint: "••••demo" }),
    test_connection: async () => ({ ok: true, message: "Connected with Gemini 2.5 Flash." }),
    open_root: async () => ({ ok: true }),
    open_category: async () => ({ ok: true }),
    reveal_file: async () => ({ ok: true }),
  };
}
