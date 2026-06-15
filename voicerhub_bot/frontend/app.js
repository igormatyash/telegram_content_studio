const basePath = document.body.dataset.basePath || "";
const apiUrl = path => `${basePath}/${path.replace(/^\/+/, "")}`;
const state = {
  me: null,
  company: null,
  data: null,
  users: [],
  view: "home",
  ideaFilter: "all",
  draftFilter: "all",
  brandTab: "profile",
  settingsTab: "workspace",
  calendarDate: new Date(),
  onboardingStep: 1,
  usage: null,
  referral: null,
  platformUsage: null,
  platformPeriod: "month",
  platformSection: "overview",
  platformClientId: null,
  platformData: {},
  lists: {},
  selected: {},
  roles: null,
};
const viewRoutes = {
  home: "dashboard",
  ideas: "ideas",
  plan: "content-plan",
  drafts: "drafts",
  calendar: "calendar",
  brand: "brand",
  analytics: "expenses",
  settings: "settings",
  platform: "platform",
};
const routeViews = Object.fromEntries(
  Object.entries(viewRoutes).map(([view, route]) => [route, view]),
);
const titles = {
  home: ["Головна", "Огляд вашого контенту та найближчих дій."],
  ideas: ["Ідеї", "Генеруйте та зберігайте теми для майбутніх публікацій."],
  plan: ["Контент-план", "Плануйте контент на тиждень або місяць."],
  drafts: ["Чернетки", "Перевіряйте, редагуйте та готуйте матеріали до публікації."],
  calendar: ["Календар", "Плануйте публікації та керуйте графіком виходу контенту."],
  brand: ["Бренд", "Налаштуйте стиль комунікації, рубрики та візуальні правила."],
  analytics: ["Витрати", "Контролюйте AI-витрати, генерації та використання моделей."],
  settings: ["Налаштування", "Керуйте workspace, користувачами, каналами та режимом роботи."],
  platform: ["Платформа", "Клієнти, компанії, активність і витрати сервісу."],
};
const statusLabels = {
  idea: "Ідея", suggested: "Ідея", draft: "Чернетка", review: "На перевірці",
  needs_changes: "Потрібні правки", ready: "Готово", scheduled: "Заплановано",
  published: "Опубліковано", queued_text: "Генерується", queued_image: "Візуал",
  text_batch: "Генерується", image_batch: "Візуал", failed: "Помилка",
  error: "Помилка", cancelled: "Скасовано",
};
const statusOrder = ["idea", "draft", "review", "needs_changes", "ready", "scheduled", "published"];
const statusActions = {
  draft: [["review","На перевірку"],["ready","Позначити готовим"]],
  review: [["needs_changes","Повернути на правки"],["ready","Погодити"]],
  needs_changes: [["draft","Повернути в чернетки"]],
  ready: [["draft","Повернути в чернетки"]],
};
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const money = value => `$${Number(value || 0).toFixed(2)}`;
const formatDate = value => value ? new Date(value).toLocaleDateString("uk-UA", {day:"2-digit",month:"short"}) : "Без дати";
const blockedPreviewTags = new Set(["SCRIPT","STYLE","IFRAME","OBJECT","EMBED","FORM","INPUT","BUTTON","SVG"]);
const plain = value => {
  const documentValue = new DOMParser().parseFromString(String(value || ""), "text/html");
  documentValue.body.querySelectorAll([...blockedPreviewTags].join(",")).forEach(node=>node.remove());
  return (documentValue.body.textContent || "").replace(/\s+/g, " ").trim();
};
const allowedPreviewTags = new Set(["B","STRONG","I","EM","U","S","BR","CODE","PRE","A","BLOCKQUOTE"]);
function safeHtml(value) {
  const source = new DOMParser().parseFromString(String(value || ""), "text/html");
  const clean = document.implementation.createHTMLDocument("");
  const copy = node => {
    if (node.nodeType === Node.TEXT_NODE) return clean.createTextNode(node.textContent || "");
    if (node.nodeType !== Node.ELEMENT_NODE) return clean.createTextNode("");
    if (blockedPreviewTags.has(node.tagName)) return clean.createTextNode("");
    if (!allowedPreviewTags.has(node.tagName)) {
      const fragment = clean.createDocumentFragment();
      [...node.childNodes].forEach(child => fragment.append(copy(child)));
      return fragment;
    }
    const element = clean.createElement(node.tagName.toLowerCase());
    if (node.tagName === "A") {
      const href = node.getAttribute("href") || "";
      if (/^(https?:|mailto:)/i.test(href)) {
        element.setAttribute("href", href);
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer");
      }
    }
    [...node.childNodes].forEach(child => element.append(copy(child)));
    return element;
  };
  const output = clean.createElement("div");
  [...source.body.childNodes].forEach(node => output.append(copy(node)));
  return output.innerHTML;
}
const can = permission => Boolean(state.me?.is_super_admin || state.me?.permissions?.includes(permission));
const pageParams = extra => {
  const current = new URLSearchParams(location.search);
  const query = new URLSearchParams({
    page: current.get("page") || "1",
    per_page: current.get("per_page") || "25",
  });
  if (current.get("search")) query.set("search", current.get("search"));
  for (const [key, value] of Object.entries(extra || {})) {
    if (value && value !== "all") query.set(key, value);
  }
  return query;
};
function pagedData(key, endpoint, extra, rerender) {
  const query = pageParams(extra);
  const signature = `${endpoint}?${query}`;
  const current = state.lists[key];
  if (current?.signature === signature) return current.data;
  if (current?.loading === signature) return null;
  state.lists[key] = {loading: signature};
  api(signature).then(data => {
    state.lists[key] = {signature, data};
    rerender();
  }).catch(error => {
    state.lists[key] = {signature, error};
    toast(error.message, true);
    rerender();
  });
  return null;
}
function updateListQuery(values, rerender, key) {
  const query = new URLSearchParams(location.search);
  for (const [name, value] of Object.entries(values)) {
    if (value === null || value === "" || value === "1" && name === "page") query.delete(name);
    else query.set(name, value);
  }
  history.pushState({view:state.view}, "", `${location.pathname}${query.size ? `?${query}` : ""}`);
  delete state.lists[key];
  rerender();
}
function pagination(data, key, rerender) {
  if (!data || !data.total_pages) return "";
  const start = data.total ? (data.page - 1) * data.per_page + 1 : 0;
  const end = Math.min(data.total, data.page * data.per_page);
  const pages = [];
  for (let page = Math.max(1, data.page - 2); page <= Math.min(data.total_pages, data.page + 2); page += 1) pages.push(page);
  queueMicrotask(() => {
    document.querySelectorAll(`[data-pagination="${key}"] [data-page]`).forEach(button => button.onclick = () => updateListQuery({page:button.dataset.page}, rerender, key));
    document.querySelector(`[data-pagination="${key}"] select`)?.addEventListener("change", event => updateListQuery({page:"1",per_page:event.target.value}, rerender, key));
  });
  return `<nav class="pagination" data-pagination="${key}" aria-label="Пагінація"><span>Показано ${start}–${end} з ${data.total}</span><div><button data-page="${Math.max(1,data.page-1)}" ${data.page<=1?"disabled":""}>Назад</button>${pages.map(page=>`<button data-page="${page}" class="${page===data.page?"active":""}">${page}</button>`).join("")}<button data-page="${Math.min(data.total_pages,data.page+1)}" ${data.page>=data.total_pages?"disabled":""}>Вперед</button></div><label>На сторінці<select>${[10,25,50,100].map(size=>`<option value="${size}" ${size===data.per_page?"selected":""}>${size}</option>`).join("")}</select></label></nav>`;
}
function selected(key) {
  if (!state.selected[key]) state.selected[key] = new Set();
  return state.selected[key];
}
function selectionCheckbox(key, id) {
  return `<input class="row-check" type="checkbox" aria-label="Обрати" data-select-key="${key}" data-select-id="${esc(id)}" ${selected(key).has(String(id))?"checked":""}>`;
}
function bindSelection(key, target, renderBar) {
  target.querySelectorAll(`[data-select-key="${key}"]`).forEach(input => input.onchange = () => {
    if (input.checked) selected(key).add(String(input.dataset.selectId));
    else selected(key).delete(String(input.dataset.selectId));
    renderBar();
  });
  target.querySelectorAll(`[data-select-all="${key}"]`).forEach(input => input.onchange = () => {
    target.querySelectorAll(`[data-select-key="${key}"]`).forEach(row => {
      row.checked = input.checked;
      if (row.checked) selected(key).add(String(row.dataset.selectId));
      else selected(key).delete(String(row.dataset.selectId));
    });
    renderBar();
  });
}
function bulkBar(key, actions) {
  const count = selected(key).size;
  if (!count) return "";
  return `<div class="bulk-bar"><strong>Обрано: ${count}</strong>${actions.map(([action,label,kind=""])=>`<button class="${kind}" data-bulk-action="${action}">${label}</button>`).join("")}<button data-clear-selection>Скасувати вибір</button></div>`;
}
const icon = name => ({
  ideas: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 22h4"/><path d="M8.2 15.4A7 7 0 1 1 15.8 15.4C14.7 16.2 14 17 14 18h-4c0-1-.7-1.8-1.8-2.6Z"/></svg>',
  plan: '<svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/></svg>',
  drafts: '<svg viewBox="0 0 24 24"><path d="M4 5h6v14H4zM14 5h6v8h-6zM14 17h6v2h-6z"/></svg>',
  calendar: '<svg viewBox="0 0 24 24"><path d="M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2ZM3 9h18M8 2v4M16 2v4"/></svg>',
}[name] || "");

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  headers["X-Requested-With"] = "VoicerHubAdmin";
  const response = await fetch(apiUrl(path), {...options, headers});
  if (response.status === 401) {
    location.href = `${basePath}/`;
    throw new Error("Потрібно увійти");
  }
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data.detail || data || "Помилка запиту");
  return data;
}

function toast(message, error = false) {
  const node = document.querySelector("#toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.hidden = true, 3600);
}
async function loading(button, task, label = "Зачекайте…") {
  const old = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span>${label}`;
  try { return await task(); }
  catch (error) { toast(error.message, true); throw error; }
  finally { button.disabled = false; button.innerHTML = old; }
}
function initials(name) {
  return String(name || "CS").split(/\s+/).slice(0,2).map(x => x[0]).join("").toUpperCase();
}
function pill(status) {
  const normalized = status === "suggested" ? "idea" : status;
  return `<span class="pill ${esc(normalized)}">${esc(statusLabels[status] || status)}</span>`;
}
function empty(title, text, action = "") {
  return `<div class="empty-state"><div style="font-size:28px;color:#818cf8">✦</div><h3>${esc(title)}</h3><p class="muted">${esc(text)}</p>${action}</div>`;
}
function notificationStorageKey() {
  return `content-studio:read-notifications:${state.me?.id || "guest"}:${state.me?.organization_id || "none"}`;
}
function readNotificationKeys() {
  try {
    return new Set(JSON.parse(localStorage.getItem(notificationStorageKey()) || "[]"));
  } catch {
    return new Set();
  }
}
function saveReadNotificationKeys(keys) {
  localStorage.setItem(notificationStorageKey(), JSON.stringify([...keys]));
}
function notificationItems({includeRead = false} = {}) {
  const failed = (state.data?.jobs || []).filter(job => job.status === "failed");
  const items = failed.map(job => ({
    key: `failed-job:${job.id}`,
    type: "error",
    jobId: job.id,
    title: "Не вдалося згенерувати матеріал",
    text: job.topic || job.error || `Завдання #${job.id}`,
    action: "Перейдіть у чернетки, перевірте дані та повторіть генерацію.",
  }));
  const expiry = state.company?.plan_expires_at
    ? Math.ceil((new Date(state.company.plan_expires_at) - new Date()) / 86400000)
    : null;
  if (state.company?.plan_code === "trial" && expiry !== null && expiry <= 7) {
    items.push({
      key: `trial:${state.company.plan_expires_at}`,
      type: expiry <= 0 ? "error" : "warning",
      title: expiry <= 0 ? "Trial завершився" : "Trial скоро завершиться",
      text: expiry <= 0 ? "Оберіть тариф для продовження роботи." : `Залишилося ${expiry} дн.`,
      action: "Перевірте тариф у налаштуваннях workspace.",
    });
  }
  const spend = Number(state.company?.ai_spend || state.data?.totals?.total_cost || 0);
  const budget = Number(state.company?.monthly_ai_budget || 0);
  if (budget && spend / budget >= .7) {
    items.push({
      key: `budget:${new Date().toISOString().slice(0, 7)}:${budget}`,
      type: spend >= budget ? "error" : "warning",
      title: "AI-бюджет майже використано",
      text: `${money(spend)} з ${money(budget)} (${Math.round(spend / budget * 100)}%).`,
      action: "Відкрийте розділ «Витрати» для деталізації.",
    });
  }
  const readKeys = readNotificationKeys();
  return items
    .map(item => ({...item, read: readKeys.has(item.key)}))
    .filter(item => includeRead || !item.read);
}
function updateNotificationBadge() {
  const notificationCount = notificationItems().length;
  const notificationBadge = document.querySelector("#notificationCount");
  notificationBadge.textContent = notificationCount;
  notificationBadge.hidden = notificationCount === 0;
  document.querySelector("#notificationsButton").classList.toggle("has-events", notificationCount > 0);
}
function appPathname() {
  const normalizedBase = basePath.replace(/\/+$/, "");
  return normalizedBase && location.pathname.startsWith(normalizedBase)
    ? location.pathname.slice(normalizedBase.length) || "/"
    : location.pathname;
}
function routeFromLocation() {
  const parts = appPathname().split("/").filter(Boolean);
  if (parts[0] === "platform") {
    const sections = new Set(["clients","organizations","users","referrals","activity","expenses"]);
    state.platformSection = sections.has(parts[1]) ? parts[1] : "overview";
    state.platformClientId = state.platformSection === "clients" && Number(parts[2])
      ? Number(parts[2])
      : null;
    return {view:"platform",draftId:null};
  }
  const workspaceIndex = parts.indexOf("workspace");
  if (
    workspaceIndex >= 0
    && parts[workspaceIndex + 2] === "drafts"
    && Number(parts[workspaceIndex + 3])
  ) {
    return {
      view: history.state?.fromView || "drafts",
      draftId: Number(parts[workspaceIndex + 3]),
    };
  }
  return {view: routeViews[parts[0]] || "home", draftId: null};
}
function queryForView(view) {
  const query = new URLSearchParams();
  const current = new URLSearchParams(location.search);
  const pathParts = appPathname().split("/").filter(Boolean);
  const sameList = view === "platform"
    ? pathParts[0] === "platform" && (pathParts[1] || "overview") === state.platformSection
    : pathParts[0] === viewRoutes[view];
  if (sameList) {
    for (const key of ["page","per_page","search"]) {
      const value = current.get(key);
      if (value) query.set(key, value);
    }
  }
  if (view === "ideas" && state.ideaFilter !== "all") query.set("rubric", state.ideaFilter);
  if (view === "drafts" && state.draftFilter !== "all") query.set("status", state.draftFilter);
  if (view === "calendar") {
    query.set("view", "month");
    query.set(
      "date",
      `${state.calendarDate.getFullYear()}-${String(state.calendarDate.getMonth() + 1).padStart(2, "0")}`,
    );
  }
  if (view === "brand" && state.brandTab !== "profile") query.set("tab", state.brandTab);
  if (view === "settings" && state.settingsTab !== "workspace") query.set("tab", state.settingsTab);
  if (view === "platform" && state.platformSection === "clients" && !state.platformClientId) {
    for (const key of ["source","period","active","workspace"]) {
      const value = current.get(key);
      if (value) query.set(key, value);
    }
  }
  return query.toString();
}
function urlForView(view) {
  const query = queryForView(view);
  let route = viewRoutes[view];
  if (view === "platform") {
    route = state.platformSection === "overview"
      ? "platform"
      : `platform/${state.platformSection}${state.platformClientId ? `/${state.platformClientId}` : ""}`;
  }
  return `${basePath}/${route}${query ? `?${query}` : ""}`;
}
function readRouteState() {
  const query = new URLSearchParams(location.search);
  state.ideaFilter = query.get("rubric") || "all";
  state.draftFilter = query.get("status") || "all";
  if (/^\d{4}-\d{2}$/.test(query.get("date") || "")) {
    const [year, month] = query.get("date").split("-").map(Number);
    state.calendarDate = new Date(year, month - 1, 1);
  }
  state.brandTab = query.get("tab") || "profile";
  state.settingsTab = query.get("tab") || "workspace";
  return routeFromLocation();
}
function updateViewUrl(view, {replace = false} = {}) {
  history[replace ? "replaceState" : "pushState"]({view}, "", urlForView(view));
}
function setView(view, {push = true, replace = false} = {}) {
  if (!viewRoutes[view]) view = "home";
  if (view === "platform" && !state.me?.is_super_admin) view = "home";
  state.view = view;
  if (push) updateViewUrl(view, {replace});
  document.querySelectorAll(".view").forEach(node => node.classList.toggle("active", node.id === `${view}View`));
  document.querySelectorAll(".nav-item[data-view]").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  const [title, subtitle] = titles[view];
  document.querySelector("#pageTitle").textContent = view === "drafts" && state.company?.settings?.workspace_mode === "kanban" ? "Дошка" : title;
  document.querySelector("#pageSubtitle").textContent = subtitle;
  document.body.classList.remove("menu-open");
  renderCurrent();
}
async function applyLocationRoute({openDraft = true} = {}) {
  const route = readRouteState();
  setView(route.view, {push: false});
  document.querySelectorAll("[data-brand-tab]").forEach(node => node.classList.toggle("active", node.dataset.brandTab === state.brandTab));
  document.querySelectorAll("[data-settings]").forEach(node => node.classList.toggle("active", node.dataset.settings === state.settingsTab));
  if (route.draftId && openDraft && state.data) {
    await openEditor(route.draftId, false);
  } else if (!route.draftId) {
    document.querySelector("#editorOverlay").hidden = true;
    state.currentDraft = null;
  }
  if (route.view === "platform" && state.me?.is_super_admin) {
    await loadPlatformSection();
  }
}
function renderCurrent() {
  if (!state.data || !state.company) return;
  ({home: renderHome, ideas: renderIdeas, plan: renderPlan, drafts: renderDrafts, calendar: renderCalendar, brand: renderBrand, analytics: renderAnalytics, settings: renderSettings, platform: renderPlatform}[state.view])();
}

function applyIdentity() {
  const role = state.me.role || "platform_admin";
  document.querySelector("#userName").textContent = state.me.display_name || state.me.username;
  document.querySelector("#userRole").textContent = role;
  const avatar = document.querySelector("#userAvatar");
  if (state.me.avatar_url) avatar.src = state.me.avatar_url;
  else avatar.removeAttribute("src");
  avatar.alt = state.me.display_name || state.me.username;
  document.querySelector("#workspaceName").textContent = state.company.name;
  document.querySelector("#workspaceLogo").textContent = initials(state.company.name);
  document.querySelector("#workspacePlan").textContent = `${role} · ${state.company.plan_code || "custom"} plan`;
  document.querySelector("#ideasCount").textContent = (state.data.ideas || []).length;
  document.querySelector("#draftsCount").textContent = (state.data.drafts || []).filter(x => x.status !== "published").length;
  const kanban = state.company.settings?.workspace_mode === "kanban";
  document.querySelectorAll(".pipeline-only").forEach(node => node.hidden = kanban);
  document.querySelector("#draftsNavLabel").textContent = kanban ? "Дошка" : "Чернетки";
  document.querySelector("#analyticsNavLabel").textContent = kanban ? "Аналітика" : "Витрати";
  const readOnly = role === "viewer";
  const canAdmin = ["platform_admin", "owner", "admin"].includes(role);
  document.body.classList.toggle("read-only", readOnly);
  document.body.classList.toggle("non-admin", !canAdmin);
  document.querySelector("#platformNav").hidden = !state.me.is_super_admin;
  document.querySelectorAll("[data-platform-section]").forEach(node => {
    node.classList.toggle(
      "active",
      state.view === "platform" && node.dataset.platformSection === state.platformSection,
    );
  });
  [
    "#createButton","#generateIdeas","#manualIdea","#manualDraft",
    "#calendarSchedule","#planForm button[type=submit]",
  ].forEach(selector => {
    const node = document.querySelector(selector);
    if (node) node.hidden = readOnly;
  });
  updateNotificationBadge();
  renderSystemBanner();
}

function renderSystemBanner() {
  const banner = document.querySelector("#systemBanner");
  const expiry = state.company?.plan_expires_at
    ? Math.ceil((new Date(state.company.plan_expires_at) - new Date()) / 86400000)
    : null;
  if (!navigator.onLine) {
    banner.textContent = "Немає з’єднання з мережею. Зміни стануть доступними після відновлення зв’язку.";
    banner.className = "system-banner error";
    banner.hidden = false;
  } else if (expiry !== null && expiry <= 0) {
    banner.textContent = "Термін тарифу завершився. AI-генерація та публікація тимчасово недоступні.";
    banner.className = "system-banner error";
    banner.hidden = false;
  } else if (state.company?.plan_code === "trial" && expiry !== null && expiry <= 3) {
    banner.textContent = `Trial завершується через ${expiry} дн. Оберіть тариф, щоб зберегти доступ до генерації.`;
    banner.className = "system-banner";
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

function renderHome() {
  const drafts = state.data.drafts || [];
  const ideas = state.data.ideas || [];
  const counts = {
    idea: ideas.filter(x => ["idea","suggested"].includes(x.status)).length,
    draft: drafts.filter(x => x.status === "draft").length,
    review: drafts.filter(x => x.status === "review").length,
    ready: drafts.filter(x => x.status === "ready").length,
    scheduled: drafts.filter(x => x.status === "scheduled").length,
    published: drafts.filter(x => x.status === "published").length,
  };
  document.querySelector("#homeMetrics").innerHTML = [
    ["idea","Ідеї",counts.idea,"Нові теми"],
    ["draft","Чернетки",counts.draft,"У роботі"],
    ["review","На перевірці",counts.review,"Потребують уваги"],
    ["ready","Готово",counts.ready,"Очікують публікації"],
    ["scheduled","Заплановано",counts.scheduled,"У календарі"],
    ["published","Опубліковано",counts.published,"За весь час"],
  ].map(([status,label,value,note]) => `<article class="card metric">${pill(status)}<strong>${value}</strong><small>${note}</small></article>`).join("");
  document.querySelector("#quickActions").innerHTML = `
    <div class="quick-action featured" data-action="ideas"><span class="action-icon">${icon("ideas")}</span><div><strong>Згенерувати ідеї</strong><small style="display:block;color:#c7d2fe">AI запропонує теми на основі бренду</small></div></div>
    <div class="quick-action" data-action="plan"><span class="action-icon">${icon("plan")}</span><div><strong>Створити контент-план</strong><small class="muted">На тиждень або місяць</small></div></div>
    <div class="quick-action" data-action="drafts"><span class="action-icon">${icon("drafts")}</span><div><strong>Створити чернетку</strong><small class="muted">З ідеї або з нуля</small></div></div>
    <div class="quick-action" data-action="calendar"><span class="action-icon">${icon("calendar")}</span><div><strong>Запланувати пост</strong><small class="muted">Чернетка з візуалом → календар</small></div></div>`;
  document.querySelectorAll(".quick-action").forEach(node => node.onclick = () => setView(node.dataset.action));
  const upcoming = drafts.filter(x => x.scheduled_at).sort((a,b) => new Date(a.scheduled_at)-new Date(b.scheduled_at)).slice(0,6);
  document.querySelector("#upcomingList").innerHTML = upcoming.length ? upcoming.map(item => `<button class="quick-action" data-draft="${item.id}"><strong style="min-width:54px">${formatDate(item.scheduled_at)}</strong><span style="text-align:left">${esc(plain(item.title))}</span>${pill(item.status)}</button>`).join("") : empty("Публікацій ще немає","Підготуйте чернетку та додайте її до календаря.");
  document.querySelectorAll("[data-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.draft)));
  const total = Number(state.data.totals?.total_cost || 0);
  const budget = Number(state.company.monthly_ai_budget || 0);
  const percent = budget ? Math.min(100, total / budget * 100) : 0;
  document.querySelector("#usageCard").innerHTML = `<div class="eyebrow" style="color:#c4b5fd">AI-витрати · місяць</div><strong>${money(total)}</strong><small>${percent.toFixed(0)}% ліміту · бюджет ${money(budget)}</small><div style="height:4px;margin-top:18px;border-radius:9px;background:rgba(255,255,255,.12)"><div style="height:100%;width:${percent}%;border-radius:9px;background:linear-gradient(90deg,#818cf8,#d946ef)"></div></div>`;
  const settings = state.company.settings || {};
  const fields = ["company_description","tone_of_voice","key_services","website_url"];
  const complete = Math.round(fields.filter(key => settings[key]).length / fields.length * 100);
  document.querySelector("#brandProgress").innerHTML = `<div class="eyebrow">Бренд-профіль</div><h2>Наповнений на ${complete}%</h2><p class="muted">Заповнений бренд-профіль робить AI-результати точнішими.</p><button data-open-view="brand">Доповнити профіль →</button>`;
  bindViewLinks();
}

function renderFilters(target, values, active, callback) {
  target.innerHTML = values.map(([value,label]) => `<button class="${value===active?"active":""}" data-filter="${value}">${label}</button>`).join("");
  target.querySelectorAll("button").forEach(button => button.onclick = () => callback(button.dataset.filter));
}
function renderIdeas() {
  renderFilters(document.querySelector("#ideaFilters"), [["all","Усі рубрики"],...(state.data.rubrics||[]).map(x => [x.slug,x.name])], state.ideaFilter, value => {
    state.ideaFilter=value;
    delete state.lists.ideas;
    updateListQuery({page:"1",rubric:value==="all"?null:value},renderIdeas,"ideas");
  });
  const data = pagedData("ideas","api/ideas",{rubric:state.ideaFilter},renderIdeas);
  const target = document.querySelector("#ideasGrid");
  if (!data) {
    target.innerHTML = '<span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span>';
    return;
  }
  const items = data.items || [];
  target.innerHTML = `${bulkBar("ideas",[["create_drafts","Створити чернетки"],["assign_rubric","Призначити рубрику"],["delete","Видалити","danger"]])}<div class="idea-grid">${items.length ? items.map(item => `<article class="card idea-card selectable-card">${selectionCheckbox("ideas",item.id)}<div class="row between"><span class="pill idea">${esc((state.data.rubrics||[]).find(x=>x.slug===item.product)?.name||item.product)}</span><small class="muted">${formatDate(item.planned_for)}</small></div><h3>${esc(item.title_plain||plain(item.title))}</h3><div class="formatted-preview">${safeHtml(item.angle_preview||item.angle||"Перспективна тема для майбутньої публікації.")}</div><footer>${can("ideas.delete")?`<button class="ghost danger" data-delete-idea="${item.id}">Видалити</button>`:""}${can("content.create")?`<button class="dark-button" data-generate-idea="${item.id}">Створити чернетку</button>`:""}</footer></article>`).join("") : empty("У вас ще немає ідей","Згенеруйте перші теми на основі бренду та рубрик.",can("ideas.create")?'<button class="primary" id="emptyGenerateIdeas">✦ Згенерувати ідеї</button>':"")}</div>${pagination(data,"ideas",renderIdeas)}`;
  bindSelection("ideas",target,renderIdeas);
  target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("ideas").clear();renderIdeas();});
  target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runIdeaBulk(button.dataset.bulkAction));
  document.querySelectorAll("[data-generate-idea]").forEach(button => button.onclick = () => generateIdea(button));
  document.querySelectorAll("[data-delete-idea]").forEach(button => button.onclick = async () => {
    if (!confirm("Видалити цю ідею?")) return;
    await api(`api/ideas/${button.dataset.deleteIdea}`, {method:"DELETE"});
    toast("Ідею видалено");
    await refresh();
  });
  document.querySelector("#emptyGenerateIdeas")?.addEventListener("click", () => document.querySelector("#generateIdeas").click());
}
async function runIdeaBulk(action) {
  const ids=[...selected("ideas")].map(Number);
  if (!ids.length) return;
  let value="";
  if (action==="delete"&&!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`)) return;
  if (action==="assign_rubric") {
    value=prompt(`Slug рубрики:\n${(state.data.rubrics||[]).map(x=>x.slug).join(", ")}`)||"";
    if (!value) return;
  }
  await api("api/ideas/bulk",{method:"POST",body:JSON.stringify({ids,action,value})});
  selected("ideas").clear();delete state.lists.ideas;toast("Масову дію виконано");await refresh(true);renderIdeas();
}
async function generateIdea(button) {
  await loading(button, async () => {
    await api(`api/ideas/${button.dataset.generateIdea}/generate`, {method:"POST",body:JSON.stringify(generationPayload())});
    toast("Чернетку поставлено в чергу");
    await refresh();
    setView("drafts");
  }, "Створюємо…");
}
function generationPayload() {
  return {text_model:"gpt-5.4-mini",image_model:"gpt-image-2",reference_ids:[],template_id:"editorial-dark",logo_reference_id:null,company_logo_reference_id:null,link_url:"",tone:"expert",generation_mode:"fast"};
}

function renderPlan() {
  const select = document.querySelector("#planProduct");
  select.innerHTML = `<option value="all">Усі рубрики</option>${(state.data.rubrics||[]).filter(x=>x.active!==0).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}`;
  if (!document.querySelector("#planStart").value) document.querySelector("#planStart").value = new Date().toISOString().slice(0,10);
  const data = pagedData("plan","api/content-plan/items",{},renderPlan);
  const target=document.querySelector("#planList");
  if(!data){target.innerHTML='<span class="skeleton"></span><span class="skeleton"></span>';return;}
  const planned=data.items||[];
  target.innerHTML=`${bulkBar("plan",[["delete","Видалити","danger"]])}${planned.length?planned.map(item=>`<div class="plan-row plan-row-detailed">${selectionCheckbox("plan",item.id)}<strong>${formatDate(item.planned_for)}</strong><span><strong>${esc(item.title_plain||plain(item.title))}</strong>${item.error_message?`<small class="plan-error">${esc(item.error_message)}</small>`:""}</span>${pill(item.status)}${["failed","error","cancelled"].includes(item.status)?`<div class="row plan-actions">${item.job_id?`<button data-retry-job="${item.job_id}">Повторити</button><button data-job-details="${item.job_id}">Деталі</button><button class="danger" data-delete-job="${item.job_id}">Видалити</button>`:""}</div>`:""}</div>`).join(""):empty("Контент-план порожній","Виберіть параметри та створіть перший план.")}${pagination(data,"plan",renderPlan)}`;
  bindSelection("plan",target,renderPlan);
  target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("plan").clear();renderPlan();});
  target.querySelector("[data-bulk-action='delete']")?.addEventListener("click",async()=>{
    const ids=[...selected("plan")].map(Number);if(!ids.length||!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`))return;
    await api("api/ideas/bulk",{method:"POST",body:JSON.stringify({ids,action:"delete",value:""})});selected("plan").clear();delete state.lists.plan;await refresh(true);renderPlan();
  });
  target.querySelectorAll("[data-retry-job]").forEach(button=>button.onclick=async()=>{await loading(button,()=>api(`api/jobs/${button.dataset.retryJob}/retry-fast`,{method:"POST"}),"Повторюємо…");delete state.lists.plan;toast("Генерацію повторено");renderPlan();});
  target.querySelectorAll("[data-job-details]").forEach(button=>button.onclick=()=>{const item=planned.find(row=>String(row.job_id)===button.dataset.jobDetails);showForm("Деталі помилки",`<div class="wide callout warning"><strong>${esc(item?.error_message||"Помилка генерації")}</strong><p>${esc(item?.error||"Спробуйте повторити генерацію або перевірте налаштування AI.")}</p></div>`,null);});
  target.querySelectorAll("[data-delete-job]").forEach(button=>button.onclick=async()=>{if(!confirm("Видалити помилкове завдання?"))return;await api(`api/jobs/${button.dataset.deleteJob}`,{method:"DELETE"});delete state.lists.plan;toast("Запис видалено");renderPlan();});
}

function renderDrafts() {
  const kanban = state.company.settings?.workspace_mode === "kanban";
  renderFilters(document.querySelector("#draftFilters"), [["all","Усі"],["draft","Чернетки"],["review","На перевірці"],["ready","Готові"],["scheduled","Заплановані"],["published","Опубліковані"]], state.draftFilter, value => {
    state.draftFilter=value;delete state.lists.drafts;updateListQuery({page:"1",status:value==="all"?null:value},renderDrafts,"drafts");
  });
  const data=pagedData("drafts","api/drafts",{status:state.draftFilter},renderDrafts);
  const target = document.querySelector("#draftsContent");
  if(!data){target.innerHTML='<div class="draft-grid"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div>';return;}
  const drafts=data.items||[];
  const bar=bulkBar("drafts",[["status","Змінити статус"],["assign_rubric","Призначити рубрику"],["delete","Видалити","danger"]]);
  if (kanban) {
    target.innerHTML = `${bar}<div class="kanban-board">${statusOrder.map(status => {const rows = status==="idea" ? [] : drafts.filter(x=>x.status===status);return `<section class="kanban-column"><div class="kanban-head"><span>${statusLabels[status]}</span><span>${rows.length}</span></div>${rows.map(item=>`<article class="kanban-card selectable-card">${selectionCheckbox("drafts",item.id)}<button class="kanban-open" data-open-draft="${item.id}">${pill(item.status)}<h4>${esc(item.title_plain||plain(item.title))}</h4><small class="muted">${formatDate(item.scheduled_at||item.created_at)}</small></button><div class="kanban-actions">${can("content.edit")?(statusActions[item.status]||[]).map(([next,label])=>`<button data-transition-draft="${item.id}" data-transition-status="${next}">${label}</button>`).join(""):""}</div></article>`).join("")}</section>`;}).join("")}</div>${pagination(data,"drafts",renderDrafts)}`;
  } else {
    target.innerHTML = `${bar}${drafts.length ? `<div class="draft-grid">${drafts.map(item => `<article class="card draft-card selectable-card">${selectionCheckbox("drafts",item.id)}<div class="draft-cover">${item.image_path?`<img src="${apiUrl(`api/drafts/${item.id}/image`)}" alt="">`:`<strong>${esc(plain(item.visual_title||item.title))}</strong>`}</div><div class="draft-body">${pill(item.status)}<h3>${esc(item.title_plain||plain(item.title))}</h3><p class="muted">${esc((item.caption_plain||plain(item.caption_html)).slice(0,130))}</p><footer><small class="muted">${formatDate(item.scheduled_at||item.created_at)}</small><button data-open-draft="${item.id}">Відкрити</button></footer></div></article>`).join("")}</div>` : empty("Чернеток ще немає","Створіть чернетку з ідеї або додайте матеріал вручну.")}${pagination(data,"drafts",renderDrafts)}`;
  }
  bindSelection("drafts",target,renderDrafts);
  target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("drafts").clear();renderDrafts();});
  target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runDraftBulk(button.dataset.bulkAction));
  document.querySelectorAll("[data-open-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.openDraft)));
  document.querySelectorAll("[data-transition-draft]").forEach(node => node.onclick = async () => {
    await api(`api/drafts/${node.dataset.transitionDraft}/status`, {method:"POST",body:JSON.stringify({status:node.dataset.transitionStatus})});
    toast(`Статус змінено: ${statusLabels[node.dataset.transitionStatus]}`);
    await refresh();
  });
}
async function runDraftBulk(action) {
  const ids=[...selected("drafts")].map(Number);if(!ids.length)return;
  let value="";
  if(action==="delete"&&!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`))return;
  if(action==="assign_rubric"){value=prompt(`Slug рубрики:\n${(state.data.rubrics||[]).map(x=>x.slug).join(", ")}`)||"";if(!value)return;}
  if(action==="status"){value=prompt("Новий статус: draft, review, needs_changes, ready")||"";if(!value)return;}
  await api("api/drafts/bulk",{method:"POST",body:JSON.stringify({ids,action,value})});selected("drafts").clear();delete state.lists.drafts;toast("Масову дію виконано");await refresh(true);renderDrafts();
}

function renderCalendar() {
  const year = state.calendarDate.getFullYear(), month = state.calendarDate.getMonth();
  document.querySelector("#calendarTitle").textContent = state.calendarDate.toLocaleDateString("uk-UA",{month:"long",year:"numeric"});
  const drafts = state.data.drafts || [];
  const schedulable = drafts.filter(x => x.status !== "published" && !x.scheduled_at);
  document.querySelector("#calendarReady").innerHTML = schedulable.length
    ? schedulable.map(x=>`<button class="quick-action" data-schedule-draft="${x.id}">${pill(x.status)}<span style="min-width:0;text-align:left"><strong>${esc(plain(x.title))}</strong><small class="muted">${x.image_path ? "Можна запланувати" : "Спочатку потрібен візуал"}</small></span></button>`).join("")
    : `<p class="muted">Усі матеріали вже заплановані або опубліковані.</p>`;
  const first = new Date(year,month,1), offset = (first.getDay()+6)%7;
  const start = new Date(year,month,1-offset);
  const cells = [];
  for (let i=0;i<42;i++) {
    const day = new Date(start); day.setDate(start.getDate()+i);
    const key = day.toISOString().slice(0,10);
    const events = drafts.filter(x => x.scheduled_at && new Date(x.scheduled_at).toISOString().slice(0,10)===key);
    cells.push(`<div class="calendar-day ${day.getMonth()!==month?"outside":""} ${key===new Date().toISOString().slice(0,10)?"today":""}"><strong>${day.getDate()}</strong>${events.map(x=>`<button class="calendar-event" data-open-draft="${x.id}">${new Date(x.scheduled_at).toLocaleTimeString("uk-UA",{hour:"2-digit",minute:"2-digit"})} · ${esc(plain(x.title))}</button>`).join("")}</div>`);
  }
  document.querySelector("#calendarGrid").innerHTML = ["Пн","Вт","Ср","Чт","Пт","Сб","Нд"].map(x=>`<div class="calendar-weekday">${x}</div>`).join("")+cells.join("");
  document.querySelectorAll("[data-open-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.openDraft)));
  document.querySelectorAll("[data-schedule-draft]").forEach(node => node.onclick = () => openScheduleForm(Number(node.dataset.scheduleDraft)));
}
function openScheduleForm(selectedId = null) {
  const drafts = (state.data.drafts || []).filter(x => x.status !== "published" && !x.scheduled_at);
  const eligible = drafts.filter(x => x.image_path);
  if (!eligible.length) {
    showForm(
      "Немає матеріалів для планування",
      `<div class="wide callout warning"><strong>Чому список порожній?</strong><p>У календар можна додати будь-яку неопубліковану чернетку, але для публікації потрібен готовий візуал. Відкрийте чернетку та згенеруйте або додайте зображення.</p></div>${drafts.map(x=>`<div class="wide schedule-row">${pill(x.status)}<span>${esc(plain(x.title))}</span><small>Немає візуалу</small></div>`).join("")}`,
      null,
    );
    return;
  }
  showForm(
    "Запланувати публікацію",
    `<div class="wide callout"><strong>Чернетка буде затверджена</strong><p>Після вибору дати матеріал отримає статус «Заплановано». Перед публікацією його ще можна відкрити, відредагувати або повернути в готові.</p></div>
    <label class="wide">Матеріал<select name="draft_id">${eligible.map(x=>`<option value="${x.id}" ${x.id===selectedId?"selected":""}>${esc(plain(x.title))} — ${esc(statusLabels[x.status]||x.status)}</option>`).join("")}</select></label>
    <label class="wide">Дата і час<input name="scheduled_at" type="datetime-local" min="${new Date(Date.now()+60000).toISOString().slice(0,16)}" required></label>`,
    async form => {
      await api(`api/drafts/${form.get("draft_id")}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(form.get("scheduled_at")).toISOString()})});
      toast("Публікацію додано до календаря");
      await refresh();
      renderCalendar();
    },
    {submitLabel:"Запланувати"},
  );
}

function renderBrand() {
  const settings = state.company.settings || {};
  const target = document.querySelector("#brandContent");
  if (state.brandTab === "profile") target.innerHTML = `<div class="brand-layout"><article class="card brand-summary"><div class="row"><span class="workspace-logo">${initials(state.company.name)}</span><div><h2 style="margin:0">${esc(state.company.name)}</h2><span class="muted">${esc(settings.key_services||"Додайте ключові послуги")}</span></div></div><div class="form-grid" style="margin-top:22px"><label>Сайт<input id="brandWebsite" type="url" placeholder="https://company.ua" value="${esc(settings.website_url||"")}"><small class="field-help">Сайт допомагає AI точніше зрозуміти продукт і термінологію.</small></label><label>Основний колір<input id="brandColor" type="color" value="${esc(settings.brand_primary_color||"#6366f1")}"><small class="field-help">Використовується у візуальних шаблонах.</small></label><label class="wide">Опис компанії<textarea id="brandDescription" placeholder="Хто ви, для кого працюєте, яку проблему вирішуєте і чим відрізняєтесь. 3–6 конкретних речень.">${esc(settings.company_description||"")}</textarea><small class="field-help">Приклад: «VoicerHub допомагає бізнесу автоматизувати голосові комунікації. Наші клієнти — контакт-центри та сервісні команди…»</small></label><label class="wide">Ключові продукти або послуги<textarea id="brandServices" placeholder="Назва продукту — коротко яку задачу він вирішує">${esc(settings.key_services||"")}</textarea><small class="field-help">Додайте конкретні назви, цільову аудиторію та користь. Це стане контекстом для генерації.</small></label></div><button class="primary" id="saveBrandProfile" style="margin-top:14px">Зберегти профіль</button></article><aside class="card panel"><h2>Рубрики</h2>${(state.data.rubrics||[]).map(x=>`<div class="usage-row"><span>${esc(x.name)}</span><strong>${(state.data.ideas||[]).filter(i=>i.product===x.slug).length}</strong></div>`).join("")||'<p class="muted">Ще немає рубрик.</p>'}</aside></div>`;
  else if (state.brandTab === "tone") target.innerHTML = `<article class="card panel"><div class="row between"><div><div class="eyebrow">Стиль комунікації</div><h2>Tone of voice</h2><p class="muted">Опишіть, як бренд звучить у текстах. Не використовуйте абстрактні слова без прикладів.</p></div><button class="primary" id="saveTone">Зберегти</button></div><textarea id="toneValue" placeholder="Пишемо українською, короткими реченнями. Звертаємося на «ви». Тон експертний, але доброзичливий. Пояснюємо терміни простими словами.">${esc(settings.tone_of_voice||"")}</textarea><small class="field-help">Добре: правила, довжина речень, форма звертання, рівень експертності та 1–2 приклади. Погано: лише «професійно та сучасно».</small><div class="tone-boxes" style="margin-top:14px"><div class="tone-good"><strong>✓ Що можна</strong><p>Писати зрозуміло, конкретно та впевнено; підкріплювати тези прикладами.</p></div><div class="tone-bad"><strong>× Чого не можна</strong><p>${esc(settings.forbidden_phrases||"Вкажіть кліше, перебільшення, небажані слова та обіцянки.")}</p></div></div></article>`;
  else if (state.brandTab === "rubrics") {
    const data=pagedData("rubrics","api/rubrics",{},renderBrand);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const rows=data.items||[];
    target.innerHTML=`<article class="card panel"><div class="row between"><div><h2>Рубрики контенту</h2><p class="muted">Рубрики допомагають Content Studio створювати контент системно. Кожна рубрика задає тему, ціль, тон і правила для AI.</p></div>${can("rubrics.manage")?'<button class="primary" id="addRubric">＋ Створити рубрику</button>':""}</div><div class="callout"><strong>Як AI використовує рубрики</strong><p>Під час генерації ідей і контент-плану AI чергує різні формати та не повторює один тип контенту.</p></div>${bulkBar("rubrics",[["activate","Активувати"],["deactivate","Деактивувати"],["delete","Видалити","danger"]])}${rows.length?`<div class="table-wrap"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="rubrics" aria-label="Обрати всі"></th><th>Рубрика</th><th>Ціль</th><th>Тон</th><th>Статус</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td>${selectionCheckbox("rubrics",x.id)}</td><td><strong>${esc(x.name)}</strong><small>${esc(x.description)}</small></td><td>${esc(x.goal||"—")}</td><td>${esc(x.tone||"—")}</td><td>${x.active?"Активна":"Неактивна"}</td><td>${can("rubrics.manage")?`<button data-edit-rubric="${x.id}">Редагувати</button>`:""}</td></tr>`).join("")}</tbody></table></div>`:empty("У вас ще немає рубрик","Створіть рубрики, щоб AI міг планувати експертні пости, кейси, поради, новини та продажні матеріали.",can("rubrics.manage")?'<button class="primary" id="emptyAddRubric">Створити рубрику</button>':"")}${pagination(data,"rubrics",renderBrand)}</article>`;
    bindSelection("rubrics",target,renderBrand);target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("rubrics").clear();renderBrand();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runRubricBulk(button.dataset.bulkAction));
    target.querySelectorAll("[data-edit-rubric]").forEach(button=>button.onclick=()=>openRubricForm(rows.find(x=>x.id===Number(button.dataset.editRubric))));
  } else if (state.brandTab === "visuals") {
    const data=pagedData("visuals","api/brand/visual-styles",{},renderBrand);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const builtIns=(state.data.templates||[]).filter(x=>!x.custom);
    const rows=data.items||[];
    target.innerHTML=`<div class="row between brand-section-head"><div><h2>Візуальні стилі</h2><p class="muted">Збережіть правила кольорів, настрою та композиції, які AI використовуватиме для зображень.</p></div>${can("visual_styles.manage")?'<button class="primary" id="addVisualStyle">＋ Створити стиль</button>':""}</div><div class="callout"><strong>Вбудовані стилі</strong><p>Глобальні шаблони доступні для використання, але не редагуються.</p></div><div class="asset-grid">${builtIns.map(x=>`<article class="card asset-card"><img src="${apiUrl(`api/templates/${encodeURIComponent(x.id)}/preview`)}" alt=""><div class="asset-body"><strong>${esc(x.name)}</strong><small>${esc(x.description)}</small><span class="pill ready">Системний</span></div></article>`).join("")}</div><h3>Стилі workspace</h3>${bulkBar("visuals",[["activate","Активувати"],["deactivate","Деактивувати"],["delete","Видалити","danger"]])}<div class="asset-grid">${rows.map(x=>`<article class="card asset-card selectable-card">${selectionCheckbox("visuals",x.id)}${x.preview_path?`<img src="${apiUrl(`api/templates/${encodeURIComponent(x.id)}/preview`)}" alt="">`:'<div class="asset-placeholder">Попередній перегляд</div>'}<div class="asset-body"><strong>${esc(x.name)}</strong><small>${esc(x.description)}</small><div class="row"><button data-edit-style="${esc(x.id)}">Редагувати</button><button data-duplicate-style="${esc(x.id)}">Дублювати</button></div></div></article>`).join("")||empty("Власних стилів ще немає","Створіть стиль для генерації візуалів у впізнаваній манері бренду.")}</div>${pagination(data,"visuals",renderBrand)}`;
    bindSelection("visuals",target,renderBrand);target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("visuals").clear();renderBrand();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runBrandBulk("visuals",button.dataset.bulkAction));
    target.querySelectorAll("[data-edit-style]").forEach(button=>button.onclick=()=>openVisualStyleForm(rows.find(x=>x.id===button.dataset.editStyle)));
    target.querySelectorAll("[data-duplicate-style]").forEach(button=>button.onclick=async()=>{await api(`api/templates/${button.dataset.duplicateStyle}/duplicate`,{method:"POST"});delete state.lists.visuals;toast("Стиль дубльовано");renderBrand();});
  } else if (state.brandTab === "assets") {
    const data=pagedData("assets","api/brand/materials",{},renderBrand);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const rows=data.items||[];
    target.innerHTML=`<div class="row between brand-section-head"><div><h2>Матеріали бренду</h2><p class="muted">Матеріали допомагають AI краще розуміти стиль компанії: логотипи, кольори, презентації, брендбук і референси.</p></div>${can("brand_materials.manage")?'<div class="row"><button id="addMaterialLink">Додати посилання</button><button class="primary" id="uploadMaterial">Завантажити матеріал</button></div>':""}</div>${bulkBar("assets",[["activate","Активувати"],["deactivate","Деактивувати"],["delete","Видалити","danger"]])}<div class="asset-grid">${rows.map(x=>`<article class="card asset-card selectable-card">${selectionCheckbox("assets",x.id)}${x.path&&x.media_type?.startsWith("image/")?`<img src="${apiUrl(`api/references/${x.id}/image`)}" alt="">`:`<div class="asset-placeholder">${x.source_url?"Посилання":esc((x.filename||"Файл").split(".").pop().toUpperCase())}</div>`}<div class="asset-body"><strong>${esc(x.name||x.filename||"Матеріал")}</strong><small>${esc(x.material_type)} · ${x.active?"Активний":"Неактивний"}</small>${x.source_url?`<a href="${esc(x.source_url)}" target="_blank" rel="noopener">Відкрити посилання</a>`:""}${can("brand_materials.manage")?`<div class="row"><button data-edit-material="${x.id}">Редагувати</button><button class="danger" data-delete-material="${x.id}">Видалити</button></div>`:""}</div></article>`).join("")||empty("Матеріалів ще немає","Завантажте логотип, фото, референс або додайте важливе посилання.")}</div>${pagination(data,"assets",renderBrand)}`;
    bindSelection("assets",target,renderBrand);
    target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("assets").clear();renderBrand();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runBrandBulk("assets",button.dataset.bulkAction));
    target.querySelectorAll("[data-edit-material]").forEach(button=>button.onclick=()=>openMaterialForm(rows.find(x=>x.id===Number(button.dataset.editMaterial))));
    target.querySelectorAll("[data-delete-material]").forEach(button=>button.onclick=async()=>{if(!confirm("Видалити матеріал?"))return;await api(`api/references/${button.dataset.deleteMaterial}`,{method:"DELETE"});delete state.lists.assets;renderBrand();});
  } else {
    const materials=state.data.references||[];
    target.innerHTML=`<div class="appearance-layout"><article class="card panel"><div class="eyebrow">Брендований workspace</div><h2>Оформлення</h2><div class="form-grid"><label>Назва workspace<input id="appearanceName" value="${esc(state.company.name)}"></label><label>Короткий опис<input id="appearanceDescription" value="${esc(settings.workspace_short_description||"")}"></label><label>Основний колір<input id="appearancePrimary" type="color" value="${esc(settings.brand_primary_color||"#6366f1")}"></label><label>Додатковий колір<input id="appearanceSecondary" type="color" value="${esc(settings.brand_secondary_color||"#a855f7")}"></label><label>Аватар workspace<select id="appearanceAvatar"><option value="">Ініціали компанії</option>${materials.map(x=>`<option value="${x.id}" ${Number(settings.workspace_avatar_asset_id)===x.id?"selected":""}>${esc(x.name)}</option>`).join("")}</select></label><label>Логотип компанії<select id="appearanceLogo"><option value="">Не вибрано</option>${materials.map(x=>`<option value="${x.id}" ${Number(settings.brand_logo_asset_id)===x.id?"selected":""}>${esc(x.name)}</option>`).join("")}</select></label></div>${can("workspace.settings")?'<button class="primary" id="saveAppearance">Зберегти оформлення</button>':""}</article><aside class="card workspace-preview" id="appearancePreview" style="--preview-primary:${esc(settings.brand_primary_color||"#6366f1")};--preview-secondary:${esc(settings.brand_secondary_color||"#a855f7")}"><div class="eyebrow">Так workspace виглядатиме в інтерфейсі</div><span class="workspace-logo">${initials(state.company.name)}</span><h3>${esc(state.company.name)}</h3><p>${esc(settings.workspace_short_description||"Контент, бренд і публікації в одному просторі.")}</p><div class="preview-nav"><span>Головна</span><span>Ідеї</span><span>Чернетки</span></div></aside></div>`;
  }
  bindBrandActions();
}

function renderAnalytics() {
  const totals = state.data.totals || {};
  const jobs = state.data.jobs || [];
  const drafts = state.data.drafts || [];
  document.querySelector("#analyticsMetrics").innerHTML = [
    ["AI-витрати цього місяця",money(totals.total_cost)],
    ["Генерації",jobs.length],
    ["Зображення",jobs.filter(x=>x.image_model).length],
    ["Опубліковано",drafts.filter(x=>x.status==="published").length],
  ].map(([label,value],i)=>`<article class="${i===0?"usage-card":"card metric"}"><span>${label}</span><strong>${value}</strong></article>`).join("");
  const daily = [...(state.data.daily||[])].reverse();
  const max = Math.max(...daily.map(x=>Number(x.cost)),.01);
  document.querySelector("#usageChart").innerHTML = daily.length ? daily.map(x=>`<div class="chart-bar" title="${x.day}: ${money(x.cost)}" style="height:${Math.max(3,Number(x.cost)/max*100)}%"></div>`).join("") : `<p class="muted">Дані з’являться після першої AI-генерації.</p>`;
  const models = state.usage?.models || [];
  document.querySelector("#modelUsage").innerHTML = models.map(row=>`<div class="usage-row"><span>${esc(row.model)}<small class="muted" style="display:block">${row.operations} операцій</small></span><strong>${money(row.cost)}</strong></div>`).join("")||'<p class="muted">Немає даних.</p>';
  const rubrics = state.usage?.rubrics || [];
  document.querySelector("#rubricUsage").innerHTML = rubrics.map(row=>`<div class="usage-row"><span>${esc((state.data.rubrics||[]).find(x=>x.slug===row.rubric_slug)?.name||row.rubric_slug)}</span><strong>${money(row.cost)}</strong></div>`).join("")||'<p class="muted">Немає даних.</p>';
  renderPlatformAnalytics();
}

function renderPlatformAnalytics() {
  const target = document.querySelector("#platformAnalytics");
  if (!state.me?.is_super_admin) {
    target.hidden = true;
    return;
  }
  target.hidden = false;
  const report = state.platformUsage;
  target.innerHTML = `<article class="card panel platform-panel">
    <div class="row between platform-head">
      <div><div class="eyebrow">Platform admin</div><h2>Витрати всіх компаній</h2><p class="muted">Агрегований звіт без перемикання між workspace.</p></div>
      <div class="filters">${[["today","Сьогодні"],["7d","7 днів"],["month","Місяць"],["all","Весь час"]].map(([value,label])=>`<button class="${state.platformPeriod===value?"active":""}" data-platform-period="${value}">${label}</button>`).join("")}</div>
    </div>
    ${report ? `<div class="analytics-metrics platform-metrics">
      <div class="card metric"><span>Загальні витрати</span><strong>${money(report.totals.cost)}</strong></div>
      <div class="card metric"><span>Операції</span><strong>${report.totals.operations}</strong></div>
      <div class="card metric"><span>Тексти</span><strong>${report.totals.text_generations}</strong></div>
      <div class="card metric"><span>Зображення</span><strong>${report.totals.image_generations}</strong></div>
    </div>
    <div class="table-wrap"><table class="users-table"><thead><tr><th>Компанія</th><th>Операції</th><th>Тексти</th><th>Зображення</th><th>Витрати</th></tr></thead><tbody>${report.companies.map(row=>`<tr><td><strong>${esc(row.organization_name)}</strong></td><td>${row.operations}</td><td>${row.text_generations}</td><td>${row.image_generations}</td><td><strong>${money(row.cost)}</strong></td></tr>`).join("")}</tbody></table></div>` : '<div class="skeleton" style="min-height:160px"></div>'}
  </article>`;
  target.querySelectorAll("[data-platform-period]").forEach(button => button.onclick = async () => {
    state.platformPeriod = button.dataset.platformPeriod;
    state.platformUsage = null;
    renderPlatformAnalytics();
    state.platformUsage = await api(`api/platform/usage?period=${state.platformPeriod}`);
    renderPlatformAnalytics();
  });
}

const platformMeta = {
  overview: ["Огляд платформи","Ключові метрики реєстрацій, клієнтів і використання."],
  clients: ["Клієнти","Усі зареєстровані клієнти та джерела їх залучення."],
  organizations: ["Компанії","Workspace, власники, контент, ліміти та активність."],
  users: ["Користувачі","Загальний список акаунтів сервісу."],
  referrals: ["Реферали","Посилання, переходи та реферальні реєстрації."],
  activity: ["Активність","Журнал важливих дій і входів без відкритих IP-адрес."],
  expenses: ["Витрати","AI-витрати по компаніях, моделях і користувачах."],
};
const platformDate = value => value
  ? new Date(value).toLocaleString("uk-UA",{dateStyle:"short",timeStyle:"short"})
  : "—";
function platformEmpty(title, text) {
  return `<div class="empty-state"><h3>${esc(title)}</h3><p class="muted">${esc(text)}</p></div>`;
}
async function openPlatformSection(section, {push = true, clientId = null} = {}) {
  state.platformSection = section;
  state.platformClientId = clientId;
  state.platformData[section] = null;
  setView("platform",{push});
  await loadPlatformSection();
}
async function loadPlatformSection(force = false) {
  if (!state.me?.is_super_admin) return;
  const section = state.platformSection;
  const cacheKey = state.platformClientId ? `client-${state.platformClientId}` : section;
  if (!force && state.platformData[cacheKey]) {
    renderPlatform();
    return;
  }
  document.querySelector("#platformContent").innerHTML = '<div class="platform-loading"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div>';
  try {
    let data;
    if (section === "overview") data = await api("api/platform/overview");
    else if (section === "clients" && state.platformClientId) data = await api(`api/platform/clients/${state.platformClientId}`);
    else if (section === "clients") data = await api(`api/platform/clients?${new URLSearchParams(location.search)}`);
    else if (section === "organizations") data = await api(`api/platform/organizations/details?${pageParams()}`);
    else if (section === "users") data = await api(`api/platform/users?${pageParams()}`);
    else if (section === "referrals") data = await api(`api/platform/referrals?${pageParams()}`);
    else if (section === "activity") data = await api(`api/platform/activity?${pageParams()}`);
    else data = await api(`api/platform/usage?period=${state.platformPeriod}&${pageParams()}`);
    state.platformData[cacheKey] = data;
    renderPlatform();
  } catch (error) {
    document.querySelector("#platformContent").innerHTML = platformEmpty("Не вдалося завантажити дані",error.message);
  }
}
function renderPlatform() {
  const target = document.querySelector("#platformContent");
  if (!target || !state.me?.is_super_admin) return;
  const [heading, description] = platformMeta[state.platformSection];
  document.querySelector("#platformHeading").textContent = heading;
  document.querySelector("#platformDescription").textContent = description;
  document.querySelectorAll("[data-platform-section]").forEach(node => node.classList.toggle("active",node.dataset.platformSection===state.platformSection));
  const key = state.platformClientId ? `client-${state.platformClientId}` : state.platformSection;
  const data = state.platformData[key];
  if (!data) return;
  if (state.platformSection === "overview") {
    const m = data.metrics;
    target.innerHTML = `<div class="platform-metric-grid">${[
      ["Нові сьогодні",m.registrations_today],["Нові за 7 днів",m.registrations_7d],
      ["Користувачі",m.users_total],["Компанії",m.organizations_total],
      ["Активні компанії",m.active_organizations],["Workspace за місяць",m.new_workspaces_month],
      ["AI-витрати за місяць",money(m.ai_cost_month)],["Публікації",m.publications_total],
      ["Реферальні реєстрації",m.referral_signups],
    ].map(([label,value])=>`<article class="card metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`).join("")}</div>
    <div class="platform-grid"><article class="card panel"><h2>Реєстрації по днях</h2>${data.registrations_by_day.length?`<div class="platform-bars">${data.registrations_by_day.map(row=>`<div title="${row.day}: ${row.count}"><span style="height:${Math.max(8,row.count*18)}px"></span><small>${row.day.slice(5)}</small></div>`).join("")}</div>`:platformEmpty("Клієнтів ще немає","Нові реєстрації з’являться в цьому розділі.")}</article>
    <article class="card panel"><h2>Топ компаній за usage</h2>${data.top_organizations.map(row=>`<div class="usage-row"><span><strong>${esc(row.name)}</strong><small class="muted" style="display:block">${row.draft_count} чернеток · ${row.published_count} публікацій</small></span><strong>${money(row.ai_cost)}</strong></div>`).join("")||'<p class="muted">Ще немає usage.</p>'}</article></div>`;
  } else if (state.platformSection === "clients" && state.platformClientId) {
    const client=data.client;
    target.innerHTML = `<button id="backToClients">← До списку клієнтів</button><div class="client-profile card panel"><div class="row between"><div><div class="eyebrow">Клієнт #${client.id}</div><h2>${esc(client.display_name||client.username)}</h2><p class="muted">${esc(client.email||client.username)}</p></div><span class="pill ${client.active?"ready":"failed"}">${client.active?"Активний":"Вимкнений"}</span></div>
    <div class="platform-detail-grid">${[
      ["Дата реєстрації",platformDate(client.created_at)],["Останній вхід",platformDate(client.last_login_at)],
      ["Кількість входів",client.login_count],["Остання активність",platformDate(client.last_seen_at)],
      ["Джерело",client.registration_source],["Referral code",client.referral_code||"—"],
      ["UTM source",client.utm_source||"—"],["AI usage",`${client.usage_operations} · ${money(client.ai_cost)}`],
      ["Ідеї",data.content_totals.ideas],["Чернетки",data.content_totals.drafts],
      ["Публікації",data.content_totals.published],
    ].map(([label,value])=>`<div><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join("")}</div></div>
    <div class="platform-grid"><article class="card panel"><h2>Компанії та ролі</h2>${data.organizations.map(row=>`<div class="usage-row"><span><strong>${esc(row.name)}</strong><small class="muted" style="display:block">${esc(row.role)} · ${row.draft_count||0} чернеток</small></span><button data-switch-workspace="${row.id}">Перейти</button></div>`).join("")||'<p class="muted">Workspace не створено.</p>'}</article>
    <article class="card panel"><h2>Timeline активності</h2>${data.activity.slice(0,20).map(row=>`<div class="timeline-row"><span></span><div><strong>${esc(row.action)}</strong><small>${platformDate(row.created_at)} · ${esc(row.organization_name||"Без workspace")}</small><p>${esc(row.details||"")}</p></div></div>`).join("")||'<p class="muted">Подій ще немає.</p>'}</article></div>`;
    document.querySelector("#backToClients").onclick=()=>openPlatformSection("clients");
  } else if (state.platformSection === "clients") {
    const query=new URLSearchParams(location.search);
    target.innerHTML = `<form class="platform-filters" id="clientFilters"><input name="search" placeholder="Email, ім’я або компанія" value="${esc(query.get("search")||"")}"><select name="source"><option value="">Усі джерела</option><option value="referral" ${query.get("source")==="referral"?"selected":""}>Referral</option><option value="direct" ${query.get("source")==="direct"?"selected":""}>Direct</option></select><select name="period"><option value="">Весь період</option><option value="7d" ${query.get("period")==="7d"?"selected":""}>7 днів</option><option value="30d" ${query.get("period")==="30d"?"selected":""}>30 днів</option></select><select name="workspace"><option value="">Будь-який workspace</option><option value="yes" ${query.get("workspace")==="yes"?"selected":""}>Є workspace</option><option value="no" ${query.get("workspace")==="no"?"selected":""}>Без workspace</option></select><button class="primary">Застосувати</button></form>
    ${bulkBar("platform-clients",[["export","Експортувати CSV"],["deactivate","Деактивувати","danger"]])}${data.clients.length?`<div class="table-wrap card"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-clients"></th><th>Клієнт</th><th>Реєстрація</th><th>Останній вхід</th><th>Компанії</th><th>Джерело</th><th>Витрати</th><th></th></tr></thead><tbody>${data.clients.map(row=>`<tr><td>${selectionCheckbox("platform-clients",row.id)}</td><td><strong>${esc(row.display_name||row.username)}</strong><small>${esc(row.email||row.username)}</small></td><td>${platformDate(row.created_at)}</td><td>${platformDate(row.last_login_at)}</td><td>${row.organization_count}<small>${esc(row.primary_organization_name)}</small></td><td>${esc(row.registration_source)}<small>${esc(row.referral_code||"")}</small></td><td>${money(row.ai_cost)}</td><td><button data-client="${row.id}">Профіль</button></td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Клієнтів ще немає","Нові реєстрації з’являться в цьому розділі.")}${pagination(data,"platform-clients",()=>loadPlatformSection(true))}`;
    document.querySelector("#clientFilters").onsubmit=async event=>{event.preventDefault();const params=new URLSearchParams(new FormData(event.currentTarget));for(const [key,value] of [...params])if(!value)params.delete(key);history.pushState({view:"platform"},"",`${basePath}/platform/clients${params.size?`?${params}`:""}`);state.platformData.clients=null;await loadPlatformSection(true);};
    document.querySelectorAll("[data-client]").forEach(button=>button.onclick=()=>openPlatformSection("clients",{clientId:Number(button.dataset.client)}));
  } else if (state.platformSection === "organizations") {
    target.innerHTML = `${bulkBar("platform-organizations",[["export","Експортувати CSV"],["deactivate","Деактивувати","danger"]])}${data.organizations.length?`<div class="table-wrap card"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-organizations"></th><th>Компанія</th><th>Owner</th><th>Створено</th><th>Команда</th><th>Контент</th><th>AI-витрати</th><th>Onboarding</th><th></th></tr></thead><tbody>${data.organizations.map(row=>`<tr><td>${selectionCheckbox("platform-organizations",row.id)}</td><td><strong>${esc(row.name)}</strong><small>${esc(row.slug)} · ${esc(row.plan_code||"custom")}</small></td><td>${esc(row.owner_name||"—")}<small>${esc(row.owner_email||"")}</small></td><td>${platformDate(row.created_at)}</td><td>${row.user_count}/${row.max_users}</td><td>${row.draft_count} / ${row.scheduled_count} / ${row.published_count}<small>чернетки / план / публікації</small></td><td>${money(row.ai_cost)}</td><td>${esc(row.onboarding_status)}</td><td><button data-switch-workspace="${row.id}">Перейти</button></td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Компаній ще немає","Створені workspace з’являться тут.")}${pagination(data,"platform-organizations",()=>loadPlatformSection(true))}`;
  } else if (state.platformSection === "users") {
    target.innerHTML = `${bulkBar("platform-users",[["export","Експортувати CSV"],["deactivate","Деактивувати","danger"]])}${data.users.length?`<div class="table-wrap card"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-users"></th><th>Користувач</th><th>Реєстрація</th><th>Останній вхід</th><th>Email verified</th><th>Workspace</th><th>Джерело</th><th>Статус</th></tr></thead><tbody>${data.users.map(row=>`<tr><td>${selectionCheckbox("platform-users",row.id)}</td><td><strong>${esc(row.display_name||row.username)}</strong><small>${esc(row.email||row.username)}</small></td><td>${platformDate(row.created_at)}</td><td>${platformDate(row.last_login_at)}</td><td>${row.email_verified?"Так":"Ні"}</td><td>${row.organization_count}</td><td>${esc(row.registration_source)}</td><td>${row.active?"Активний":"Вимкнений"}</td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Користувачів ще немає","Нові акаунти з’являться тут.")}${pagination(data,"platform-users",()=>loadPlatformSection(true))}`;
  } else if (state.platformSection === "referrals") {
    target.innerHTML = `${bulkBar("platform-referrals",[["export","Експортувати CSV"],["deactivate","Вимкнути","danger"]])}<div class="platform-grid"><article class="card panel"><h2>Реферальні посилання</h2>${data.codes.length?`<div class="table-wrap"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-referrals"></th><th>Код</th><th>Власник</th><th>Компанія</th><th>Переходи</th><th>Реєстрації</th><th>Статус</th></tr></thead><tbody>${data.codes.map(row=>`<tr><td>${selectionCheckbox("platform-referrals",row.id)}</td><td class="masked">${esc(row.code)}</td><td>${esc(row.owner_display_name||row.owner_username)}</td><td>${esc(row.owner_organization_name||"—")}</td><td>${row.clicks}</td><td>${row.signups}</td><td>${esc(row.status)}</td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Поки немає реферальних посилань","Посилання з’являться після відкриття реферального блоку користувачами.")}</article>
    <article class="card panel"><h2>Реферальні реєстрації</h2>${data.signups.map(row=>`<div class="usage-row"><span><strong>${esc(row.new_email||row.new_username)}</strong><small class="muted" style="display:block">Запросив: ${esc(row.referrer_username)} · ${esc(row.utm_source||"direct")}</small></span><small>${platformDate(row.created_at)}</small></div>`).join("")||platformEmpty("Поки немає реферальних реєстрацій","Коли користувачі зареєструються за посиланням, вони з’являться тут.")}</article></div>${pagination(data,"platform-referrals",()=>loadPlatformSection(true))}`;
  } else if (state.platformSection === "activity") {
    target.innerHTML = `${bulkBar("platform-activity",[["export","Експортувати CSV"]])}<div class="platform-grid"><article class="card panel"><h2>Події платформи</h2>${data.events.map(row=>`<div class="timeline-row selectable-row">${selectionCheckbox("platform-activity",row.id)}<div><strong>${esc(row.action)}</strong><small>${platformDate(row.created_at)} · ${esc(row.display_name||row.username||"Система")} · ${esc(row.organization_name||"Без workspace")}</small><p>${esc(plain(row.details||""))}</p></div></div>`).join("")||'<p class="muted">Подій ще немає.</p>'}</article><article class="card panel"><h2>Останні входи</h2>${data.logins.map(row=>`<div class="usage-row"><span><strong>${esc(row.display_name||row.username||"Невідомий користувач")}</strong><small class="muted" style="display:block">${esc(row.organization_name||"Без workspace")} · ${platformDate(row.created_at)}</small></span><span class="${row.success?"success-text":"danger-text"}">${row.success?"Успішно":"Помилка"}</span></div>`).join("")||'<p class="muted">Входів ще немає.</p>'}</article></div>${pagination(data,"platform-activity",()=>loadPlatformSection(true))}`;
  } else {
    const report=data;
    target.innerHTML = `<div class="filters platform-periods">${[["today","Сьогодні"],["7d","7 днів"],["month","Місяць"],["all","Весь час"]].map(([value,label])=>`<button class="${state.platformPeriod===value?"active":""}" data-platform-expense-period="${value}">${label}</button>`).join("")}</div><div class="platform-metric-grid">${[["Загальні витрати",money(report.totals.cost)],["Операції",report.totals.operations],["Тексти",report.totals.text_generations],["Зображення",report.totals.image_generations]].map(([label,value])=>`<article class="card metric"><span>${label}</span><strong>${value}</strong></article>`).join("")}</div><div class="table-wrap card"><table class="users-table"><thead><tr><th>Компанія</th><th>Операції</th><th>Тексти</th><th>Зображення</th><th>Витрати</th></tr></thead><tbody>${report.companies.map(row=>`<tr><td><strong>${esc(row.organization_name)}</strong></td><td>${row.operations}</td><td>${row.text_generations}</td><td>${row.image_generations}</td><td>${money(row.cost)}</td></tr>`).join("")}</tbody></table></div>${pagination(report,"platform-expenses",()=>loadPlatformSection(true))}`;
    document.querySelectorAll("[data-platform-expense-period]").forEach(button=>button.onclick=async()=>{state.platformPeriod=button.dataset.platformExpensePeriod;state.platformData.expenses=null;await loadPlatformSection(true);});
  }
  for(const key of ["platform-clients","platform-organizations","platform-users","platform-referrals","platform-activity"]){
    bindSelection(key,target,renderPlatform);
  }
  target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runPlatformBulk(button.dataset.bulkAction));
  target.querySelectorAll("[data-clear-selection]").forEach(button=>button.onclick=()=>{for(const key of Object.keys(state.selected).filter(x=>x.startsWith("platform-")))selected(key).clear();renderPlatform();});
  document.querySelectorAll("[data-switch-workspace]").forEach(button=>button.onclick=async()=>{await api("api/workspace/select",{method:"POST",body:JSON.stringify({organization_id:Number(button.dataset.switchWorkspace)})});location.href=`${basePath}/dashboard`;});
}
async function runPlatformBulk(action){
  const key=`platform-${state.platformSection}`;
  const ids=[...selected(key)].map(Number);
  if(action==="export"){downloadCsv((state.platformData[state.platformSection]?.items||[]),state.platformSection);return;}
  if(!ids.length)return;
  if(action==="deactivate"&&!confirm(`Деактивувати ${ids.length} записів?`))return;
  await api(`api/platform/bulk/${state.platformSection}`,{method:"POST",body:JSON.stringify({ids,action,value:""})});selected(key).clear();state.platformData[state.platformSection]=null;toast("Статус оновлено");await loadPlatformSection(true);
}
function downloadCsv(rows,name){
  if(!rows.length)return toast("Немає даних для експорту",true);
  const keys=Object.keys(rows[0]);const cell=value=>`"${String(value??"").replaceAll('"','""')}"`;
  const blob=new Blob([[keys.join(","),...rows.map(row=>keys.map(key=>cell(row[key])).join(","))].join("\n")],{type:"text/csv;charset=utf-8"});
  const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=`${name}.csv`;link.click();URL.revokeObjectURL(link.href);
}

function renderSettings() {
  const target = document.querySelector("#settingsContent");
  const settings = state.company.settings || {};
  if (state.settingsTab === "workspace") target.innerHTML = `<article class="card settings-card"><div class="row"><span class="workspace-logo">${initials(state.company.name)}</span><div><h2 style="margin:0">${esc(state.company.name)}</h2><span class="muted">${esc(state.company.slug)}</span></div></div><div class="analytics-metrics" style="margin-top:20px"><div class="card metric"><span>Тариф</span><strong>${esc(state.company.plan_code||"custom")}</strong></div><div class="card metric"><span>Користувачі</span><strong>${state.company.user_count}/${state.company.max_users}</strong></div><div class="card metric"><span>Публікації</span><strong>${state.company.publication_count}/${state.company.monthly_publications}</strong></div><div class="card metric"><span>AI-бюджет</span><strong>${money(state.company.monthly_ai_budget)}</strong></div></div><button id="restartOnboarding">Повторити onboarding</button></article>`;
  else if (state.settingsTab === "mode") target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Загальні</div><h2>Режим роботи workspace</h2><p class="muted">Оберіть, як ваша команда працює з контентом.</p><div class="mode-grid"><label class="card panel"><input type="radio" name="workspaceMode" value="pipeline" ${settings.workspace_mode==="pipeline"?"checked":""}> <strong>Редакційний pipeline</strong><p class="muted">Послідовний процес: ідеї → план → чернетки → календар.</p></label><label class="card panel"><input type="radio" name="workspaceMode" value="kanban" ${settings.workspace_mode==="kanban"?"checked":""}> <strong>Контент-дошка Kanban</strong><p class="muted">Усі матеріали за статусами на одній дошці.</p></label></div><button class="primary" id="saveWorkspaceMode">Зберегти режим</button></article>`;
  else if (state.settingsTab === "users") {
    const data=pagedData("users","api/users",{},renderSettings);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const rows=data.items||[];
    target.innerHTML=`<article class="card settings-card"><div class="row between"><div><h2 style="margin:0">Користувачі workspace</h2><p class="muted">Запрошуйте команду та призначайте зрозумілі ролі.</p></div>${can("users.invite")?'<button class="primary" id="inviteUser">＋ Запросити користувача</button>':""}</div>${bulkBar("users",[["role","Змінити роль"],["deactivate","Деактивувати"],["remove","Видалити з workspace","danger"]])}<div class="table-wrap"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="users" aria-label="Обрати всіх"></th><th>Користувач</th><th>Роль</th><th>Статус</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td>${selectionCheckbox("users",x.id)}</td><td><strong>${esc(x.display_name||x.username)}</strong><small>${esc(x.email||x.username)}</small></td><td>${esc(x.role||"editor")}</td><td>${x.active?"Активний":"Вимкнений"}</td><td>${can("users.invite")?`<button data-reset-user="${x.id}">Reset link</button>`:""}</td></tr>`).join("")}</tbody></table></div>${pagination(data,"users",renderSettings)}</article>`;
    bindSelection("users",target,renderSettings);target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("users").clear();renderSettings();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runUserBulk(button.dataset.bulkAction));
  }
  else if (state.settingsTab === "roles") {
    if(!state.roles){target.innerHTML='<span class="skeleton"></span>';api("api/roles").then(data=>{state.roles=data;renderSettings();}).catch(error=>toast(error.message,true));return;}
    target.innerHTML=`<article class="card settings-card"><div class="eyebrow">Права доступу</div><h2>Ролі workspace</h2><p class="muted">Platform Admin є окремою платформною роллю. Ролі нижче діють лише всередині поточного workspace. Наведіть курсор або сфокусуйте право, щоб побачити пояснення.</p><div class="roles-list">${state.roles.items.map(role=>`<details class="role-card"><summary><span><strong>${esc(role.label)}</strong><small>${esc(role.description)}</small></span><span>${role.user_count} корист. · ${role.permissions.length} прав</span></summary><div class="permission-grid">${(role.permission_details||role.permissions.map(key=>({key,label:key,description:key}))).map(permission=>`<span class="permission-chip" tabindex="0" data-tooltip="${esc(permission.description)}" aria-label="${esc(`${permission.label}. ${permission.description}`)}"><strong>${esc(permission.label)}</strong><small>${esc(permission.key)}</small></span>`).join("")}</div></details>`).join("")}</div></article>`;
  }
  else if (state.settingsTab === "referral") {
    const referral = state.referral || {};
    const disabled = referral.status === "disabled";
    target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Реферальна програма</div><h2>Запрошуйте нових користувачів</h2><p class="muted">Поділіться персональним посиланням. Тут відображається лише ваша статистика в поточному workspace.</p><div class="referral-link"><input id="referralUrl" readonly value="${esc(referral.url||"")}"><button id="copyReferral" ${disabled?"disabled":""}>Скопіювати посилання</button></div>${disabled?'<div class="callout warning"><strong>Посилання вимкнено</strong><p>Оновіть код, щоб знову приймати реферальні переходи.</p></div>':""}<div class="analytics-metrics" style="margin-top:18px"><div class="card metric"><span>Переходи</span><strong>${Number(referral.clicks||0)}</strong></div><div class="card metric"><span>Реєстрації</span><strong>${Number(referral.signups||0)}</strong></div><div class="card metric"><span>Активні клієнти</span><strong>${Number(referral.active_clients||0)}</strong></div><div class="card metric"><span>Статус</span><strong style="font-size:18px">${disabled?"Вимкнено":"Активне"}</strong></div></div><div class="row"><button id="rotateReferral">Оновити код</button><button class="danger" id="disableReferral" ${disabled?"disabled":""}>Вимкнути посилання</button></div></article>`;
  }
  else if (state.settingsTab === "integrations") target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Telegram</div><h2>Підключення каналу</h2><p class="muted">1. Створіть бота через @BotFather. 2. Додайте його адміністратором каналу. 3. Вкажіть @username каналу та token.</p><div class="form-grid"><label>Channel username<input id="telegramChannel" placeholder="@company_channel" value="${esc(state.company.telegram?.channel_id||"")}"><small class="field-help">Канал має бути публічним або доступним боту.</small></label><label>Bot token<input id="telegramToken" type="password" placeholder="123456789:AA..."><small class="field-help">Token зберігається зашифрованим і не показується повторно.</small></label></div><div class="connection-status ${state.company.telegram?.connected?"success":""}" id="telegramStatus">${state.company.telegram?.connected?`Підключено: @${esc(state.company.telegram.bot_username||"bot")}`:"Введіть дані для автоматичної перевірки."}</div><div class="row" style="margin-top:14px"><button id="testTelegram">Перевірити підключення</button><button class="primary" id="saveTelegram">Перевірити та зберегти</button></div></article>`;
  else target.innerHTML = `<article class="card settings-card"><h2>Безпека</h2><p class="muted">Змініть пароль або створіть одноразове посилання через адміністратора workspace.</p><div class="form-grid"><label>Новий пароль<input id="ownPassword" type="password" minlength="10"></label></div><button class="primary" id="changePassword" style="margin-top:14px">Змінити пароль</button></article>`;
  bindSettingsActions();
}

async function openEditor(id, push = true) {
  try {
    const draft = await api(`api/drafts/${id}`);
    state.currentDraft = draft;
    if (push) {
      history.pushState(
        {draftId:id,fromView:state.view,pushed:true},
        "",
        `${basePath}/workspace/${state.me.organization_slug}/drafts/${id}`,
      );
    }
    const target = document.querySelector("#editorContent");
    target.innerHTML = `<header class="editor-header"><div class="row editor-title-row"><button id="closeEditor">←</button><div>${pill(draft.status)} <strong style="margin-left:8px">${esc(plain(draft.title))}</strong></div></div><div class="row editor-actions"><button id="regenText">Перегенерувати текст</button><button id="saveDraft">Зберегти</button><button class="primary" id="publishDraft" ${["ready","scheduled"].includes(draft.status)?"":"disabled title=\"Спочатку погодьте матеріал\""}>Опублікувати</button></div></header><div class="editor-grid"><form class="editor-form" id="editorForm"><div class="status-actions">${(statusActions[draft.status]||[]).map(([next,label])=>`<button type="button" data-editor-status="${next}">${label}</button>`).join("")}</div><div class="form-grid"><label>Рубрика<input value="${esc(draft.product)}" disabled></label><label>Дата і час<input id="scheduleAt" type="datetime-local" value="${draft.scheduled_at?new Date(draft.scheduled_at).toISOString().slice(0,16):""}"></label></div><label>Заголовок для поста<input id="editorTitle" value="${esc(draft.title)}"></label><label>Заголовок на візуалі<input id="editorVisualTitle" value="${esc(draft.visual_title||draft.title)}"><small class="muted">Без emoji та зайвих символів.</small></label><label>Текст публікації<textarea id="editorCaption" style="min-height:330px">${esc(draft.caption_html)}</textarea></label><label>Посилання<input id="editorLink" value="${esc(draft.link_url||"")}"></label><div class="row editor-secondary-actions"><button type="button" id="scheduleDraft" ${draft.image_path?"":"disabled title=\"Спочатку потрібен візуал\""}>Запланувати</button><button type="button" id="cancelSchedule" ${draft.status==="scheduled"?"":"hidden"}>Повернути в готові</button><button type="button" id="proofreadDraft">Перевірити текст</button></div></form><aside class="editor-preview"><div class="editor-preview-card"><div class="row"><span class="workspace-logo" style="width:30px;height:30px">${initials(state.company.name)}</span><div><strong>${esc(state.company.name)}</strong><small style="display:block;color:#94a3b8">Telegram</small></div></div><img src="${apiUrl(`api/drafts/${id}/image`)}" alt="" onerror="this.style.display='none'"><h2 id="previewTitle">${esc(plain(draft.visual_title||draft.title))}</h2><div id="previewText" class="telegram-preview-text">${safeHtml(draft.caption_html)}</div></div></aside></div>`;
    document.querySelector("#editorOverlay").hidden = false;
    bindEditorActions();
  } catch (error) { toast(error.message,true); }
}
function closeEditor() {
  document.querySelector("#editorOverlay").hidden = true;
  if (routeFromLocation().draftId) {
    if (history.state?.pushed) history.back();
    else {
      state.view = history.state?.fromView || "drafts";
      updateViewUrl(state.view, {replace:true});
      setView(state.view, {push:false});
    }
  }
}

function showForm(title, fields, submit, options = {}) {
  document.querySelector("#formTitle").textContent = title;
  document.querySelector("#formBody").innerHTML = `<div class="form-grid">${fields}</div><div class="form-error" id="dynamicError"></div>`;
  document.querySelector("#formOverlay").hidden = false;
  const form = document.querySelector("#dynamicForm");
  const submitButton = form.querySelector('button[type="submit"]');
  const cancelButton = form.querySelector("[data-close-overlay]");
  submitButton.hidden = !submit;
  submitButton.textContent = options.submitLabel || "Зберегти";
  cancelButton.textContent = submit ? "Скасувати" : "Закрити";
  form.onsubmit = async event => {
    event.preventDefault();
    if (!submit) return;
    try { await submit(new FormData(form)); document.querySelector("#formOverlay").hidden=true; }
    catch (error) { document.querySelector("#dynamicError").textContent=error.message; }
  };
}
function renderWorkspaceChooser(force = false) {
  const workspaces = state.me.workspaces || [];
  if (!force && workspaces.length < 2 && !state.me.is_super_admin) return;
  document.querySelector("#workspaceGrid").innerHTML = workspaces.map(x=>`<button class="card workspace-card ${x.id===state.me.organization_id?"active":""}" data-workspace="${x.id}"><span class="workspace-logo">${initials(x.name)}</span><h3>${esc(x.name)}</h3><p class="muted">${esc(x.plan_code||"custom")} plan</p><div class="workspace-meta"><span>${esc(x.role||"workspace")}</span><span>${x.user_count||0} корист.</span></div></button>`).join("")+`<button class="card workspace-card workspace-create" id="createWorkspace"><span style="font-size:28px">＋</span><strong>${state.me.is_super_admin?"Створити компанію":"Створити workspace"}</strong><small class="muted">${state.me.is_super_admin?"Разом із власником":"14 днів trial"}</small></button>`;
  document.querySelector("#workspaceOverlay").hidden = false;
  document.querySelectorAll("[data-workspace]").forEach(button=>button.onclick=async()=>{await api("api/workspace/select",{method:"POST",body:JSON.stringify({organization_id:Number(button.dataset.workspace)})});location.href=`${basePath}/`;});
  document.querySelector("#createWorkspace").onclick = () => {
    if (state.me.is_super_admin) {
      showForm(
        "Створити компанію та власника",
        `<div class="wide callout"><strong>Що відбудеться</strong><p>Буде створено порожній workspace і окремий owner-акаунт. Onboarding відкриється власнику під час першого входу, а не вам.</p></div>
        <label>Назва компанії<input name="name" required placeholder="Acme Ukraine"></label>
        <details class="wide advanced-field"><summary>Змінити URL вручну</summary><label>Slug<input name="slug" pattern="[A-Za-z0-9-]+" placeholder="acme-ukraine"><small class="field-help">Необов’язково. Якщо поле порожнє, URL буде створено автоматично.</small></label></details>
        <label>Ім’я власника<input name="owner_display_name" required placeholder="Олена Коваль"></label>
        <label>Email власника<input name="owner_email" type="email" placeholder="owner@company.ua"></label>
        <label>Логін власника<input name="owner_username" required pattern="[A-Za-z0-9._-]+" placeholder="acme.owner"></label>
        <label>Тимчасовий пароль<input name="owner_password" type="password" minlength="10" required></label>
        <label>Ліміт користувачів<input name="max_users" type="number" min="1" max="50" value="3"></label>
        <label>Публікацій на місяць<input name="monthly_publications" type="number" min="1" value="30"></label>
        <label>AI-бюджет, $<input name="monthly_ai_budget" type="number" min="0" step="0.01" value="8"></label>`,
        async form => {
          const created = await api("api/organizations", {method:"POST", body:JSON.stringify({
            name: form.get("name"), slug: form.get("slug"),
            owner_display_name: form.get("owner_display_name"),
            owner_email: form.get("owner_email") || null,
            owner_username: form.get("owner_username"),
            owner_password: form.get("owner_password"),
            max_users: Number(form.get("max_users")), max_channels: 1,
            monthly_publications: Number(form.get("monthly_publications")),
            monthly_ai_budget: Number(form.get("monthly_ai_budget")),
          })});
          state.me = await api("api/me");
          toast(`Компанію ${created.name} створено. Передайте власнику логін і тимчасовий пароль.`);
          renderWorkspaceChooser(true);
        },
        {submitLabel:"Створити компанію"},
      );
    } else {
      showForm("Створити workspace", `<label class="wide">Назва<input name="name" required><small class="field-help">URL буде створено автоматично з назви.</small></label><details class="wide advanced-field"><summary>Змінити URL вручну</summary><label>Slug<input name="slug" pattern="[A-Za-z0-9-]+"></label></details>`, async form => {await api("api/account/trial-workspace",{method:"POST",body:JSON.stringify({name:form.get("name"),slug:form.get("slug")||""})});location.href=`${basePath}/`;});
    }
  };
}

function showOnboarding(step) {
  state.onboardingStep = Math.max(1,Math.min(5,step));
  const names = ["Компанія","Бренд","Канали","Рубрики","Перший план"];
  document.querySelector("#onboardingSteps").innerHTML = names.map((name,index)=>`<div class="onboarding-step ${index+1===state.onboardingStep?"active":""}">${index+1}. ${name}</div>`).join("");
  document.querySelector("#onboardingTitle").textContent = names[state.onboardingStep-1];
  document.querySelector("#onboardingBack").disabled = state.onboardingStep === 1;
  document.querySelector("#onboardingNext").textContent = state.onboardingStep === 5 ? "Завершити" : "Далі →";
  const settings = state.company.settings || {};
  const contents = {
    1:`<h2>Ласкаво просимо до Content Studio</h2><p class="muted">Налаштуйте workspace за п’ять коротких кроків. Прогрес зберігається після кожного кроку.</p><div class="progress">${[1,2,3,4,5].map(x=>`<span class="${x<=state.onboardingStep?"active":""}"></span>`).join("")}</div><div class="form-grid"><label class="wide">Назва компанії<input id="obName" value="${esc(state.company.name)}"><small class="field-help">Технічний URL система створює автоматично.</small></label></div>`,
    2:`<h2>Бренд та стиль комунікації</h2><p class="muted">Ці дані використовуються як постійний контекст для AI. Пишіть факти й правила, а не рекламні гасла.</p><div class="form-grid"><label class="wide">Опис компанії<textarea id="obDescription" placeholder="Хто ви, для кого працюєте, яку проблему вирішуєте і чим відрізняєтесь.">${esc(settings.company_description||"")}</textarea><small class="field-help">3–6 конкретних речень. Назвіть аудиторію, продукт і користь.</small></label><label class="wide">Tone of voice<textarea id="obTone" placeholder="Пишемо коротко, звертаємося на «ви», пояснюємо терміни простими словами…">${esc(settings.tone_of_voice||"")}</textarea><small class="field-help">Опишіть форму звертання, довжину, емоційність, рівень експертності та наведіть приклад.</small></label><label>Ключові послуги<textarea id="obServices" placeholder="Продукт — яку задачу вирішує">${esc(settings.key_services||"")}</textarea></label><label>Заборонені фрази<textarea id="obForbidden" placeholder="Кліше, перебільшення, небажані обіцянки">${esc(settings.forbidden_phrases||"")}</textarea></label></div>`,
    3:`<h2>Підключіть Telegram-канал</h2><p class="muted">Додайте бота адміністратором каналу. Ми перевіримо token, канал і права до збереження.</p><div class="form-grid"><label>Channel username<input id="obChannel" placeholder="@company_channel" value="${esc(state.company.telegram?.channel_id||"")}"></label><label>Bot token<input id="obToken" type="password" placeholder="123456789:AA..."></label></div><div class="connection-status" id="obTelegramStatus">Введіть обидва значення для перевірки.</div><button type="button" id="obTestTelegram" style="margin-top:12px">Перевірити зараз</button>`,
    4:`<h2>Додайте рубрики контенту</h2><p class="muted">Рубрика — це постійний напрям контенту. Для кожної вкажіть назву та поясніть, про що писати.</p><div class="rubric-builder" id="obRubricRows"></div><button type="button" id="obAddRubric">＋ Додати рубрику</button>`,
    5:`<h2>Створіть перший контент-план</h2><p class="muted">AI використає бренд-профіль і рубрики. План створиться як ідеї, які можна переглянути до генерації чернеток.</p><div class="form-grid"><label>Період<select id="obPeriod"><option value="week">Тиждень</option><option value="month">Місяць</option></select></label><label>Кількість постів<input id="obPosts" type="number" value="5" min="1" max="31"></label><label class="wide">Мета<textarea id="obFocus" placeholder="Наприклад: познайомити аудиторію з новим продуктом і зібрати заявки"></textarea></label></div>`,
  };
  document.querySelector("#onboardingBody").innerHTML = contents[state.onboardingStep];
  document.querySelector("#onboardingOverlay").hidden = false;
  if (state.onboardingStep === 3) bindTelegramValidation("obChannel", "obToken", "obTelegramStatus", "obTestTelegram");
  if (state.onboardingStep === 4) {
    const container = document.querySelector("#obRubricRows");
    const existing = (state.data.rubrics || []).map(row => ({name:row.name,description:row.description}));
    const addRow = (rubric = {}) => {
      const row = document.createElement("div");
      row.className = "rubric-row";
      row.innerHTML = `<label>Назва<input data-rubric-name value="${esc(rubric.name||"")}" placeholder="Експертні поради"></label><label>Що публікуємо<textarea data-rubric-description placeholder="Практичні інструкції, кейси та відповіді на часті питання.">${esc(rubric.description||"")}</textarea></label><button type="button" class="icon-button danger" data-remove-rubric aria-label="Видалити рубрику">×</button>`;
      row.querySelector("[data-remove-rubric]").onclick = () => row.remove();
      container.append(row);
    };
    (existing.length ? existing : [{name:"",description:""}]).forEach(addRow);
    document.querySelector("#obAddRubric").onclick = () => addRow();
  }
}
async function saveOnboarding() {
  const step = state.onboardingStep;
  if (step === 1) await api("api/onboarding/company",{method:"PUT",body:JSON.stringify({name:document.querySelector("#obName").value,slug:"",primary_language:"uk",brand_primary_color:"#6366f1",brand_logo_asset_id:null})});
  if (step === 2) await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#obDescription").value,tone_of_voice:document.querySelector("#obTone").value,key_services:document.querySelector("#obServices").value,forbidden_phrases:document.querySelector("#obForbidden").value,website_url:""})});
  if (step === 3 && document.querySelector("#obToken").value) await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#obChannel").value,bot_token:document.querySelector("#obToken").value})});
  if (step === 4) {
    const rubrics = [...document.querySelectorAll(".rubric-row")].map(row => ({
      name: row.querySelector("[data-rubric-name]").value.trim(),
      description: row.querySelector("[data-rubric-description]").value.trim(),
    })).filter(row => row.name || row.description);
    if (!rubrics.length) throw new Error("Додайте хоча б одну рубрику");
    if (rubrics.some(row => row.name.length < 2 || row.description.length < 10)) throw new Error("Для кожної рубрики заповніть назву та опис від 10 символів");
    await api("api/onboarding/rubrics",{method:"POST",body:JSON.stringify({rubrics})});
  }
  if (step === 5) {
    await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({product:"all",period:document.querySelector("#obPeriod").value,posts:Number(document.querySelector("#obPosts").value),start_date:new Date().toISOString().slice(0,10),focus:document.querySelector("#obFocus").value,text_model:"gpt-5.4-mini",create_as:"ideas",rubric_slugs:[],channel_ids:[]})});
    await api("api/onboarding/complete",{method:"POST"});
    document.querySelector("#onboardingOverlay").hidden=true;
    await refresh();
    return;
  }
  await refresh();
  showOnboarding(step+1);
}

function bindViewLinks() { document.querySelectorAll("[data-open-view]").forEach(node=>node.onclick=()=>setView(node.dataset.openView)); }
const rubricTemplates = [
  ["Експертний пост","Пояснює професійну тему та демонструє експертизу.","Підвищити довіру","Експертний і зрозумілий","Що клієнт має знати перед стартом проєкту"],
  ["Кейс","Показує задачу, рішення та вимірюваний результат.","Довести цінність на практиці","Конкретний і фактологічний","Як ми скоротили час обробки звернень"],
  ["Освітній пост","Навчає аудиторію корисному підходу або інструменту.","Дати практичну користь","Доброзичливий експертний","5 помилок під час впровадження"],
  ["Новини компанії","Розповідає про зміни, події та команду.","Підтримувати контакт з аудиторією","Живий і впевнений","Запустили новий напрям"],
  ["Продажний пост","Пояснює пропозицію через проблему та користь.","Створити запит на продукт","Переконливий без тиску","Кому підійде новий пакет"],
  ["Поради клієнтам","Дає короткі рекомендації для щоденної роботи.","Підвищити корисність бренду","Практичний","Як підготувати команду до змін"],
  ["FAQ","Відповідає на типові запитання клієнтів.","Зняти заперечення","Прямий і простий","Скільки триває запуск"],
  ["Закулісся бізнесу","Показує процеси, людей та культуру.","Зробити бренд людяним","Відкритий","Як команда готує реліз"],
  ["Відгуки клієнтів","Показує досвід клієнта та результат.","Посилити соціальний доказ","Щирий","Що змінилося після впровадження"],
  ["Продуктовий пост","Розкриває функцію продукту через сценарій.","Пояснити цінність функції","Предметний","Як автоматизація економить час"],
];
function rubricFields(item={}) {
  return `<label>Назва рубрики<input name="name" required value="${esc(item.name||"")}"></label><label>Шаблон<select name="template"><option value="">З нуля</option>${rubricTemplates.map(([name])=>`<option value="${esc(name)}">${esc(name)}</option>`).join("")}</select></label><label class="wide">Опис<textarea name="description" minlength="20" required>${esc(item.description||"")}</textarea></label><label>Ціль рубрики<input name="goal" value="${esc(item.goal||"")}"></label><label>Тон комунікації<input name="tone" value="${esc(item.tone||"")}"></label><label class="wide">Приклад теми<input name="example_topic" value="${esc(item.example_topic||"")}"></label><label class="wide">Правила для AI<textarea name="instructions">${esc(item.instructions||"")}</textarea></label><label class="check-label wide"><input name="active" type="checkbox" ${item.active===0?"":"checked"}> Активна рубрика</label>`;
}
function openRubricForm(item=null) {
  showForm(item?"Редагувати рубрику":"Створити рубрику",rubricFields(item||{}),async form=>{
    const payload={name:form.get("name"),description:form.get("description"),goal:form.get("goal"),tone:form.get("tone"),example_topic:form.get("example_topic"),instructions:form.get("instructions"),default_link:item?.default_link||"",active:form.get("active")==="on"};
    await api(item?`api/rubrics/${item.id}`:"api/rubrics",{method:item?"PUT":"POST",body:JSON.stringify(payload)});
    delete state.lists.rubrics;toast("Рубрику збережено");await refresh(true);renderBrand();
  });
  const template=document.querySelector('[name="template"]');
  template.onchange=()=>{const preset=rubricTemplates.find(([name])=>name===template.value);if(!preset)return;const form=document.querySelector("#dynamicForm");form.elements.name.value=preset[0];form.elements.description.value=preset[1];form.elements.goal.value=preset[2];form.elements.tone.value=preset[3];form.elements.example_topic.value=preset[4];};
}
async function runRubricBulk(action) {
  const ids=[...selected("rubrics")].map(Number);if(!ids.length)return;
  if(action==="delete"&&!confirm(`Видалити ${ids.length} рубрик?\nЦю дію не можна буде скасувати.`))return;
  await api("api/rubrics/bulk",{method:"POST",body:JSON.stringify({ids,action,value:""})});selected("rubrics").clear();delete state.lists.rubrics;toast("Рубрики оновлено");await refresh(true);renderBrand();
}
async function runBrandBulk(kind,action){
  const ids=[...selected(kind)];
  if(!ids.length)return;
  if(action==="delete"&&!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`))return;
  const endpoint=kind==="visuals"?"api/templates/bulk":"api/brand/materials/bulk";
  await api(endpoint,{method:"POST",body:JSON.stringify({ids,action,value:""})});selected(kind).clear();delete state.lists[kind];toast("Матеріали оновлено");await refresh(true);renderBrand();
}
function visualStyleFields(item={}) {
  return `<label>Назва стилю<input name="name" required value="${esc(item.name||"")}"></label><label>Колір<input name="accent" type="color" value="${esc(item.accent||"#6366f1")}"></label><label class="wide">Опис стилю<textarea name="description" minlength="5" required>${esc(item.description||"")}</textarea></label><label class="wide">Настрій / vibe<input name="mood" value="${esc(item.mood||"")}"></label><label class="wide">Що використовувати<textarea name="use_rules">${esc(item.use_rules||"")}</textarea></label><label class="wide">Що не використовувати<textarea name="avoid_rules">${esc(item.avoid_rules||"")}</textarea></label><label class="wide">Промпт для AI<textarea name="prompt" minlength="30" required>${esc(item.prompt||"Створюй чисті професійні візуали для бренду з чіткою композицією та без зайвого тексту.")}</textarea></label><label class="wide">Приклади промптів<textarea name="prompt_examples">${esc(item.prompt_examples||"")}</textarea></label><label class="check-label wide"><input name="active" type="checkbox" ${item.active===0?"":"checked"}> Активний стиль</label>`;
}
function openVisualStyleForm(item=null) {
  showForm(item?"Редагувати візуальний стиль":"Створити візуальний стиль",visualStyleFields(item||{}),async form=>{
    const payload={name:form.get("name"),description:form.get("description"),prompt:form.get("prompt"),layout:item?.layout||"top_left",accent:form.get("accent"),mood:form.get("mood"),use_rules:form.get("use_rules"),avoid_rules:form.get("avoid_rules"),prompt_examples:form.get("prompt_examples"),active:form.get("active")==="on"};
    await api(item?`api/templates/${encodeURIComponent(item.id)}`:"api/templates",{method:item?"PUT":"POST",body:JSON.stringify(payload)});delete state.lists.visuals;toast("Візуальний стиль збережено");renderBrand();
  });
}
function openMaterialForm(item) {
  showForm("Редагувати матеріал",`<label>Назва<input name="name" value="${esc(item.name)}" required></label><label>Тип<select name="material_type">${["logo","brandbook","presentation","photo","reference_image","document","link","other"].map(type=>`<option value="${type}" ${item.material_type===type?"selected":""}>${type}</option>`).join("")}</select></label><label class="wide">URL<input name="source_url" value="${esc(item.source_url||"")}"></label><label class="wide">Опис<textarea name="description">${esc(item.description||"")}</textarea></label><label class="check-label wide"><input name="active" type="checkbox" ${item.active===0?"":"checked"}> Активний матеріал</label>`,async form=>{await api(`api/brand/materials/${item.id}`,{method:"PUT",body:JSON.stringify({name:form.get("name"),material_type:form.get("material_type"),source_url:form.get("source_url"),description:form.get("description"),active:form.get("active")==="on"})});delete state.lists.assets;toast("Матеріал збережено");renderBrand();});
}
function bindBrandActions() {
  document.querySelector("#saveBrandProfile")?.addEventListener("click",async()=>{
    await api("api/onboarding/company",{method:"PUT",body:JSON.stringify({name:state.company.name,slug:state.company.slug,primary_language:state.company.settings.primary_language||"uk",brand_primary_color:document.querySelector("#brandColor").value,brand_logo_asset_id:state.company.settings.brand_logo_asset_id||null})});
    await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#brandDescription").value,tone_of_voice:state.company.settings.tone_of_voice||"",key_services:document.querySelector("#brandServices").value,forbidden_phrases:state.company.settings.forbidden_phrases||"",website_url:document.querySelector("#brandWebsite").value})});
    toast("Профіль збережено");
    await refresh();
  });
  document.querySelector("#saveTone")?.addEventListener("click",async()=>{await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:state.company.settings.company_description||"",tone_of_voice:document.querySelector("#toneValue").value,key_services:state.company.settings.key_services||"",forbidden_phrases:state.company.settings.forbidden_phrases||"",website_url:state.company.settings.website_url||""})});toast("Tone of voice збережено");await refresh();});
  document.querySelector("#addRubric")?.addEventListener("click",()=>openRubricForm());
  document.querySelector("#emptyAddRubric")?.addEventListener("click",()=>openRubricForm());
  document.querySelector("#addVisualStyle")?.addEventListener("click",()=>openVisualStyleForm());
  document.querySelector("#addMaterialLink")?.addEventListener("click",()=>showForm("Додати посилання",`<label>Назва<input name="name" required></label><label>Тип<select name="material_type"><option value="link">Посилання</option><option value="brandbook">Брендбук</option><option value="presentation">Презентація</option><option value="document">Документ</option><option value="other">Інше</option></select></label><label class="wide">URL<input name="source_url" type="url" required></label><label class="wide">Опис<textarea name="description"></textarea></label>`,async form=>{await api("api/brand/materials/link",{method:"POST",body:JSON.stringify({name:form.get("name"),material_type:form.get("material_type"),source_url:form.get("source_url"),description:form.get("description"),active:true})});delete state.lists.assets;toast("Посилання додано");renderBrand();}));
  document.querySelector("#uploadMaterial")?.addEventListener("click",()=>showForm("Завантажити матеріал",`<label>Назва<input name="name"></label><label>Тип<select name="material_type"><option value="logo">Логотип</option><option value="brandbook">Брендбук</option><option value="presentation">Презентація</option><option value="photo">Фото</option><option value="reference_image">Референс зображення</option><option value="document">Документ</option><option value="other">Інше</option></select></label><label class="wide">Файл<input name="file" type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.docx,.pptx" required></label><label class="wide">Опис<textarea name="description"></textarea><small class="field-help">PNG, JPG, WebP, PDF, DOCX або PPTX до 20 MB.</small></label>`,async form=>{await api("api/references",{method:"POST",body:form});delete state.lists.assets;toast("Матеріал завантажено");await refresh(true);renderBrand();}));
  const updateAppearancePreview=()=>{const preview=document.querySelector("#appearancePreview");if(!preview)return;preview.style.setProperty("--preview-primary",document.querySelector("#appearancePrimary").value);preview.style.setProperty("--preview-secondary",document.querySelector("#appearanceSecondary").value);preview.querySelector("h3").textContent=document.querySelector("#appearanceName").value;preview.querySelector("p").textContent=document.querySelector("#appearanceDescription").value||"Контент, бренд і публікації в одному просторі.";};
  ["#appearanceName","#appearanceDescription","#appearancePrimary","#appearanceSecondary"].forEach(selector=>document.querySelector(selector)?.addEventListener("input",updateAppearancePreview));
  document.querySelector("#saveAppearance")?.addEventListener("click",async()=>{const result=await api("api/workspace/appearance",{method:"PUT",body:JSON.stringify({name:document.querySelector("#appearanceName").value,slug:"",short_description:document.querySelector("#appearanceDescription").value,primary_color:document.querySelector("#appearancePrimary").value,secondary_color:document.querySelector("#appearanceSecondary").value,avatar_asset_id:Number(document.querySelector("#appearanceAvatar").value)||null,logo_asset_id:Number(document.querySelector("#appearanceLogo").value)||null,favicon_asset_id:null})});state.company={...state.company,...result.company,settings:result.settings};applyIdentity();toast("Оформлення збережено");renderBrand();});
}
function bindTelegramValidation(channelId, tokenId, statusId, buttonId) {
  const channel = document.querySelector(`#${channelId}`);
  const token = document.querySelector(`#${tokenId}`);
  const status = document.querySelector(`#${statusId}`);
  const button = document.querySelector(`#${buttonId}`);
  let timer;
  const validate = async () => {
    if (!channel.value.trim() || token.value.trim().length < 20) {
      status.className = "connection-status";
      status.textContent = "Введіть @username каналу та повний bot token.";
      return false;
    }
    status.className = "connection-status checking";
    status.textContent = "Перевіряємо бота, канал і права адміністратора…";
    try {
      const result = await api("api/company/telegram/validate", {method:"POST",body:JSON.stringify({channel_id:channel.value.trim(),bot_token:token.value.trim()})});
      status.className = "connection-status success";
      status.textContent = `Підключення працює: @${result.bot_username}, права ${result.membership_status}.`;
      return true;
    } catch (error) {
      status.className = "connection-status error";
      status.textContent = error.message;
      return false;
    }
  };
  const queue = () => {
    clearTimeout(timer);
    timer = setTimeout(validate, 700);
  };
  channel.addEventListener("input", queue);
  token.addEventListener("input", queue);
  channel.addEventListener("blur", validate);
  token.addEventListener("blur", validate);
  if (button) button.onclick = validate;
  return validate;
}
function bindSettingsActions() {
  document.querySelector("#saveWorkspaceMode")?.addEventListener("click",async()=>{const mode=document.querySelector('[name="workspaceMode"]:checked').value;await api("api/workspace/mode",{method:"PUT",body:JSON.stringify({workspace_mode:mode})});state.company.settings.workspace_mode=mode;applyIdentity();renderSettings();toast("Режим збережено");});
  document.querySelector("#restartOnboarding")?.addEventListener("click",async()=>{await api("api/onboarding/restart",{method:"POST"});showOnboarding(1);});
  document.querySelector("#inviteUser")?.addEventListener("click",()=>showForm("Запросити користувача",`<label>Email<input name="email" type="email" required></label><label>Роль<select name="role"><option value="admin">Адміністратор</option><option value="content_manager">Контент-менеджер</option><option value="editor">Редактор</option><option value="publisher">Публікатор</option><option value="viewer">Переглядач</option></select></label>`,async form=>{const result=await api("api/invitations",{method:"POST",body:JSON.stringify({email:form.get("email"),role:form.get("role")})});await navigator.clipboard.writeText(result.url);toast("Посилання скопійовано");}));
  document.querySelectorAll("[data-reset-user]").forEach(button=>button.onclick=async()=>{const result=await api("api/password-reset/link",{method:"POST",body:JSON.stringify({user_id:Number(button.dataset.resetUser)})});await navigator.clipboard.writeText(result.url);toast("Reset-посилання скопійовано");});
  document.querySelector("#copyReferral")?.addEventListener("click",async()=>{await navigator.clipboard.writeText(state.referral.url);toast("Реферальне посилання скопійовано");});
  document.querySelector("#rotateReferral")?.addEventListener("click",async()=>{state.referral=await api("api/referrals/me/rotate",{method:"POST"});renderSettings();toast("Створено новий реферальний код");});
  document.querySelector("#disableReferral")?.addEventListener("click",async()=>{if(!confirm("Вимкнути поточне реферальне посилання?"))return;state.referral=await api("api/referrals/me/disable",{method:"POST"});renderSettings();toast("Реферальне посилання вимкнено");});
  const telegramValidator = document.querySelector("#telegramChannel")
    ? bindTelegramValidation("telegramChannel", "telegramToken", "telegramStatus", "testTelegram")
    : null;
  document.querySelector("#saveTelegram")?.addEventListener("click",async()=>{
    if (!await telegramValidator()) return;
    await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#telegramChannel").value,bot_token:document.querySelector("#telegramToken").value})});
    toast("Telegram підключено");
    await refresh();
  });
  document.querySelector("#changePassword")?.addEventListener("click",async()=>{await api("api/account/password",{method:"PUT",body:JSON.stringify({password:document.querySelector("#ownPassword").value})});location.href=`${basePath}/`;});
}
async function runUserBulk(action) {
  const ids=[...selected("users")].map(Number);if(!ids.length)return;
  let value="";
  if(action==="role"){value=prompt("Нова роль: admin, content_manager, editor, publisher, viewer")||"";if(!value)return;}
  if(action==="remove"&&!confirm(`Видалити ${ids.length} користувачів з workspace?`))return;
  await api("api/users/bulk",{method:"POST",body:JSON.stringify({ids,action,value})});selected("users").clear();delete state.lists.users;toast("Користувачів оновлено");renderSettings();
}
function bindEditorActions() {
  document.querySelector("#closeEditor").onclick=closeEditor;
  const updatePreview=()=>{document.querySelector("#previewTitle").textContent=plain(document.querySelector("#editorVisualTitle").value);document.querySelector("#previewText").innerHTML=safeHtml(document.querySelector("#editorCaption").value);};
  document.querySelector("#editorVisualTitle").oninput=updatePreview;document.querySelector("#editorCaption").oninput=updatePreview;
  document.querySelectorAll("[data-editor-status]").forEach(button => button.onclick = async () => {
    const draft = await api(`api/drafts/${state.currentDraft.id}/status`, {method:"POST",body:JSON.stringify({status:button.dataset.editorStatus})});
    toast(`Статус змінено: ${statusLabels[draft.status]}`);
    await refresh(true);
    await openEditor(draft.id, false);
  });
  document.querySelector("#saveDraft").onclick=async()=>{await api(`api/drafts/${state.currentDraft.id}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#editorTitle").value,visual_title:document.querySelector("#editorVisualTitle").value,caption_html:document.querySelector("#editorCaption").value,link_url:document.querySelector("#editorLink").value})});toast("Зміни збережено");await refresh();};
  document.querySelector("#regenText").onclick=async()=>{await api(`api/drafts/${state.currentDraft.id}/regenerate-text`,{method:"POST",body:JSON.stringify(generationPayload())});toast("Нову версію поставлено в чергу");closeEditor();await refresh();};
  document.querySelector("#proofreadDraft").onclick=async()=>{const draft=await api(`api/drafts/${state.currentDraft.id}/proofread`,{method:"POST",body:JSON.stringify({text_model:"gpt-5.4-mini"})});document.querySelector("#editorCaption").value=draft.caption_html;toast("Текст перевірено");};
  document.querySelector("#scheduleDraft").onclick=async()=>{const value=document.querySelector("#scheduleAt").value;if(!value)return toast("Оберіть дату і час",true);await api(`api/drafts/${state.currentDraft.id}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(value).toISOString()})});toast("Публікацію заплановано");closeEditor();await refresh();};
  document.querySelector("#cancelSchedule").onclick=async()=>{await api(`api/drafts/${state.currentDraft.id}/cancel-schedule`,{method:"POST"});toast("Публікацію повернуто в готові");closeEditor();await refresh();};
  document.querySelector("#publishDraft").onclick=async()=>{if(!confirm("Опублікувати пост зараз?"))return;await api(`api/drafts/${state.currentDraft.id}/publish`,{method:"POST"});toast("Пост опубліковано");closeEditor();await refresh();};
}

async function refresh(background = false) {
  try {
    const [me, company, data, usage, referral] = await Promise.all([api("api/me"),api("api/company"),api("api/dashboard"),api("api/usage"),api("api/referrals/me")]);
    state.me=me;state.company=company;state.data=data;state.usage=usage;state.referral=referral;
    if (me.is_super_admin) state.platformUsage = await api(`api/platform/usage?period=${state.platformPeriod}`);
    if (me.is_admin) state.users=await api("api/users");
    applyIdentity();
    if (!background) await applyLocationRoute();
    else renderCurrent();
    if (!background && company.settings && !["completed","skipped"].includes(company.settings.onboarding_status) && ["owner","admin"].includes(me.role)) showOnboarding(Math.max(1,Number(company.settings.onboarding_step||0)+1));
  } catch (error) { if (!background) toast(error.message,true); }
}

document.querySelectorAll(".nav-item[data-view]").forEach(node=>node.onclick=()=>{document.body.classList.remove("menu-open");setView(node.dataset.view);});
document.querySelectorAll("[data-platform-section]").forEach(node=>node.onclick=()=>{document.body.classList.remove("menu-open");openPlatformSection(node.dataset.platformSection);});
document.querySelector("#platformRefresh").onclick=()=>loadPlatformSection(true);
document.querySelector("#mobileMenu").onclick=()=>document.body.classList.add("menu-open");
document.addEventListener("click",event=>{if(document.body.classList.contains("menu-open")&&!event.target.closest(".sidebar")&&!event.target.closest("#mobileMenu"))document.body.classList.remove("menu-open");});
document.querySelector("#workspaceButton").onclick=()=>renderWorkspaceChooser(true);
document.querySelector("#logout").onclick=async()=>{await api("api/logout",{method:"POST"});location.href=`${basePath}/`;};
document.querySelectorAll("[data-close-overlay]").forEach(node=>node.onclick=()=>node.closest(".overlay").hidden=true);
document.addEventListener("keydown", event => {
  const overlay = [...document.querySelectorAll(".overlay:not([hidden])")].pop();
  if (!overlay) return;
  if (event.key === "Escape" && overlay.id !== "onboardingOverlay") {
    overlay.hidden = true;
    if (overlay.id === "editorOverlay") closeEditor();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = [...overlay.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(node => !node.hidden);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
window.addEventListener("online", renderSystemBanner);
window.addEventListener("offline", renderSystemBanner);
function syncVisualViewport() {
  const viewport = window.visualViewport;
  const height = Math.round(viewport?.height || window.innerHeight);
  const offsetTop = Math.round(viewport?.offsetTop || 0);
  const keyboardInset = Math.max(0, Math.round(window.innerHeight - height - offsetTop));
  document.documentElement.style.setProperty("--visual-viewport-height", `${height}px`);
  document.documentElement.style.setProperty("--visual-viewport-top", `${offsetTop}px`);
  document.documentElement.style.setProperty("--keyboard-inset", `${keyboardInset}px`);
  document.body.classList.toggle("keyboard-open", keyboardInset > 120);
  if (keyboardInset > 120 && document.activeElement?.matches("input,textarea,select")) {
    requestAnimationFrame(() => document.activeElement?.scrollIntoView({block:"nearest"}));
  }
}
window.visualViewport?.addEventListener("resize", syncVisualViewport);
window.visualViewport?.addEventListener("scroll", syncVisualViewport);
window.addEventListener("resize", syncVisualViewport);
syncVisualViewport();
document.querySelector("#generateIdeas").onclick=event=>showForm("Згенерувати ідеї",`<label>Рубрика<select name="product"><option value="all">Усі рубрики</option>${(state.data?.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Кількість<input name="count" type="number" min="1" max="12" value="8"></label><label class="wide">Фокус<textarea name="focus"></textarea></label>`,async form=>{await api("api/ideas/generate",{method:"POST",body:JSON.stringify({product:form.get("product"),count:Number(form.get("count")),focus:form.get("focus"),text_model:"gpt-5.4-mini",tone:"expert"})});toast("Ідеї створено");await refresh();});
document.querySelector("#manualIdea").onclick=()=>showForm("Створити ідею",`<label class="wide">Назва<input name="title" required></label><label>Рубрика<select name="product">${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Орієнтовна дата<input name="planned_for" type="date"></label><label class="wide">Кут подачі<textarea name="angle"></textarea></label>`,async form=>{await api("api/ideas",{method:"POST",body:JSON.stringify({title:form.get("title"),product:form.get("product"),planned_for:form.get("planned_for")||null,angle:form.get("angle")})});toast("Ідею додано");await refresh();});
document.querySelector("#manualDraft").onclick=()=>showForm("Створити чернетку",`<label class="wide">Заголовок<input name="title" required></label><label>Рубрика<select name="product">${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Заголовок на візуалі<input name="visual_title"></label><label class="wide">Текст<textarea name="caption_html" minlength="20" required></textarea></label><label class="wide">Посилання<input name="link_url" type="url"></label>`,async form=>{const draft=await api("api/drafts",{method:"POST",body:JSON.stringify({title:form.get("title"),visual_title:form.get("visual_title"),product:form.get("product"),caption_html:form.get("caption_html"),link_url:form.get("link_url")})});toast("Чернетку створено");await refresh();openEditor(draft.id);});
document.querySelector("#calendarSchedule").onclick=()=>openScheduleForm();
document.querySelector("#planForm").onsubmit=async event=>{event.preventDefault();await loading(event.submitter,async()=>{await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({product:document.querySelector("#planProduct").value,period:document.querySelector("#planPeriod").value,posts:Number(document.querySelector("#planPosts").value),start_date:document.querySelector("#planStart").value,focus:document.querySelector("#planFocus").value,text_model:"gpt-5.4-mini",create_as:document.querySelector("#planCreateAs").value,rubric_slugs:[],channel_ids:[]})});toast("Контент-план створено");await refresh();renderPlan();},"Створюємо…");};
document.querySelector("#calendarPrev").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);updateViewUrl("calendar");renderCalendar();};
document.querySelector("#calendarNext").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);updateViewUrl("calendar");renderCalendar();};
document.querySelector("#calendarToday").onclick=()=>{state.calendarDate=new Date();updateViewUrl("calendar");renderCalendar();};
document.querySelector("#onboardingBack").onclick=()=>showOnboarding(state.onboardingStep-1);
document.querySelector("#onboardingNext").onclick=event=>loading(event.currentTarget,saveOnboarding,"Зберігаємо…");
document.querySelector("#skipOnboarding").onclick=async()=>{await api("api/onboarding/skip",{method:"POST"});document.querySelector("#onboardingOverlay").hidden=true;};
document.querySelectorAll("[data-brand-tab]").forEach(node=>node.onclick=()=>{state.brandTab=node.dataset.brandTab;const query=new URLSearchParams();if(state.brandTab!=="profile")query.set("tab",state.brandTab);history.pushState({view:"brand"},"",`${basePath}/brand${query.size?`?${query}`:""}`);document.querySelectorAll("[data-brand-tab]").forEach(x=>x.classList.toggle("active",x===node));renderBrand();});
document.querySelectorAll("[data-settings]").forEach(node=>node.onclick=()=>{state.settingsTab=node.dataset.settings;const query=new URLSearchParams();if(state.settingsTab!=="workspace")query.set("tab",state.settingsTab);history.pushState({view:"settings"},"",`${basePath}/settings${query.size?`?${query}`:""}`);document.querySelectorAll("[data-settings]").forEach(x=>x.classList.toggle("active",x===node));renderSettings();});
document.querySelector("#searchButton").onclick=()=>{
  showForm("Пошук",`<label class="wide">Ідеї, чернетки та розділи<input name="query" id="globalSearch" autofocus></label><div class="wide stack" id="searchResults"></div>`,async()=>{});
  const input=document.querySelector("#globalSearch"),results=document.querySelector("#searchResults");
  input.oninput=()=>{const query=input.value.trim().toLowerCase();if(!query){results.innerHTML="";return}const rows=[...(state.data.ideas||[]).map(x=>({...x,type:"Ідея",view:"ideas"})),...(state.data.drafts||[]).map(x=>({...x,type:"Чернетка",view:"drafts"}))].filter(x=>`${plain(x.title)} ${plain(x.angle||"")} ${plain(x.caption_html||"")}`.toLowerCase().includes(query)).slice(0,8);results.innerHTML=rows.map(x=>`<button type="button" class="quick-action" data-search-view="${x.view}" data-search-draft="${x.type==="Чернетка"?x.id:""}"><span class="pill ${x.type==="Ідея"?"idea":"draft"}">${x.type}</span><span>${esc(plain(x.title))}</span></button>`).join("")||'<p class="muted">Нічого не знайдено.</p>';results.querySelectorAll("button").forEach(button=>button.onclick=()=>{document.querySelector("#formOverlay").hidden=true;if(button.dataset.searchDraft)openEditor(Number(button.dataset.searchDraft));else setView(button.dataset.searchView);});};
};
document.querySelector("#createButton").onclick=()=>showForm(
  "Що створити?",
  `<button type="button" class="wide quick-action" data-create-action="idea"><span class="action-icon">✦</span><span><strong>Ідеї з AI</strong><small class="muted">Згенерувати теми за брендом і рубриками</small></span></button>
   <button type="button" class="wide quick-action" data-create-action="draft"><span class="action-icon">＋</span><span><strong>Чернетку вручну</strong><small class="muted">Додати готовий текст або почати з нуля</small></span></button>
   <button type="button" class="wide quick-action" data-create-action="plan"><span class="action-icon">▤</span><span><strong>Контент-план</strong><small class="muted">Спланувати публікації на період</small></span></button>`,
  null,
);
document.querySelector("#formBody").addEventListener("click", event => {
  const button = event.target.closest("[data-create-action]");
  if (!button) return;
  document.querySelector("#formOverlay").hidden = true;
  if (button.dataset.createAction === "idea") { setView("ideas"); document.querySelector("#generateIdeas").click(); }
  if (button.dataset.createAction === "draft") { setView("drafts"); document.querySelector("#manualDraft").click(); }
  if (button.dataset.createAction === "plan") setView("plan");
});
function openNotifications() {
  const items = notificationItems({includeRead:true});
  const unreadCount = items.filter(item => !item.read).length;
  showForm(
    "Сповіщення",
    items.length ? `<div class="wide notification-toolbar"><span>${unreadCount ? `Непрочитаних: ${unreadCount}` : "Усі сповіщення прочитані"}</span><button type="button" id="readAllNotifications" ${unreadCount ? "" : "disabled"}>Прочитати все</button></div>${items.map(item=>`<article class="wide notification-item ${item.type} ${item.read?"read":""}"><div class="row between"><strong>${esc(item.title)}</strong>${item.read?'<span class="notification-read-label">Прочитано</span>':""}</div><p>${esc(item.text)}</p><small>${esc(item.action)}</small>${item.jobId?`<button type="button" data-retry-job="${item.jobId}">Повторити швидку генерацію</button>`:""}</article>`).join("")}` : `<div class="wide empty-state"><h3>Все гаразд</h3><p class="muted">Немає помилок генерації, попереджень про тариф або бюджет.</p></div>`,
    null,
  );
  document.querySelector("#readAllNotifications")?.addEventListener("click", () => {
    saveReadNotificationKeys(new Set(items.map(item => item.key)));
    updateNotificationBadge();
    openNotifications();
  });
  document.querySelectorAll("[data-retry-job]").forEach(button => button.onclick = async () => {
    await loading(button, async () => {
      const readKeys = readNotificationKeys();
      readKeys.delete(`failed-job:${button.dataset.retryJob}`);
      saveReadNotificationKeys(readKeys);
      await api(`api/jobs/${button.dataset.retryJob}/retry-fast`, {method:"POST"});
      toast("Генерацію перезапущено");
      document.querySelector("#formOverlay").hidden = true;
      await refresh();
    }, "Запускаємо…");
  });
}
document.querySelector("#notificationsButton").onclick=openNotifications;
document.querySelector("#exportPlan").onclick=()=>exportCsv("content-plan.csv",(state.data.ideas||[]).filter(x=>x.plan_id),["planned_for","title","product","status"]);
document.querySelector("#exportDrafts").onclick=()=>exportCsv("drafts.csv",state.data.drafts||[],["id","title","product","status","scheduled_at"]);
document.querySelector("#exportUsage").onclick=()=>exportCsv("usage.csv",state.data.daily||[],["day","cost"]);
function exportCsv(name,rows,fields){const csv=[fields.join(","),...rows.map(row=>fields.map(key=>`"${String(row[key]??"").replaceAll('"','""')}"`).join(","))].join("\n");const link=document.createElement("a");link.href=URL.createObjectURL(new Blob(["\ufeff"+csv],{type:"text/csv"}));link.download=name;link.click();URL.revokeObjectURL(link.href);}
window.addEventListener("popstate",()=>applyLocationRoute());
const initialRoute = readRouteState();
state.view = initialRoute.view;
history.replaceState(
  initialRoute.draftId
    ? {draftId:initialRoute.draftId,fromView:"drafts"}
    : {view:initialRoute.view},
  "",
  initialRoute.draftId ? location.href : urlForView(initialRoute.view),
);
refresh();
setInterval(()=>refresh(true),30000);
