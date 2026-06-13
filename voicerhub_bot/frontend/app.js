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
};
const titles = {
  home: ["Головна", "Огляд вашого контенту та найближчих дій."],
  ideas: ["Ідеї", "Генеруйте та зберігайте теми для майбутніх публікацій."],
  plan: ["Контент-план", "Плануйте контент на тиждень або місяць."],
  drafts: ["Чернетки", "Перевіряйте, редагуйте та готуйте матеріали до публікації."],
  calendar: ["Календар", "Плануйте публікації та керуйте графіком виходу контенту."],
  brand: ["Бренд", "Налаштуйте стиль комунікації, рубрики та візуальні правила."],
  analytics: ["Витрати", "Контролюйте AI-витрати, генерації та використання моделей."],
  settings: ["Налаштування", "Керуйте workspace, користувачами, каналами та режимом роботи."],
};
const statusLabels = {
  idea: "Ідея", suggested: "Ідея", draft: "Чернетка", review: "На перевірці",
  needs_changes: "Потрібні правки", ready: "Готово", scheduled: "Заплановано",
  published: "Опубліковано", queued_text: "Генерується", queued_image: "Візуал",
  text_batch: "Генерується", image_batch: "Візуал", failed: "Помилка",
};
const statusOrder = ["idea", "draft", "review", "needs_changes", "ready", "scheduled", "published"];
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const money = value => `$${Number(value || 0).toFixed(2)}`;
const formatDate = value => value ? new Date(value).toLocaleDateString("uk-UA", {day:"2-digit",month:"short"}) : "Без дати";
const plain = value => String(value || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

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
function setView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach(node => node.classList.toggle("active", node.id === `${view}View`));
  document.querySelectorAll(".nav-item[data-view]").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  const [title, subtitle] = titles[view];
  document.querySelector("#pageTitle").textContent = view === "drafts" && state.company?.settings?.workspace_mode === "kanban" ? "Дошка" : title;
  document.querySelector("#pageSubtitle").textContent = subtitle;
  document.body.classList.remove("menu-open");
  renderCurrent();
}
function renderCurrent() {
  if (!state.data || !state.company) return;
  ({home: renderHome, ideas: renderIdeas, plan: renderPlan, drafts: renderDrafts, calendar: renderCalendar, brand: renderBrand, analytics: renderAnalytics, settings: renderSettings}[state.view])();
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
  document.body.classList.toggle("read-only", readOnly);
  [
    "#createButton","#generateIdeas","#manualIdea","#manualDraft",
    "#calendarSchedule","#planForm button[type=submit]",
  ].forEach(selector => {
    const node = document.querySelector(selector);
    if (node) node.hidden = readOnly;
  });
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
    <div class="quick-action featured" data-action="ideas"><span style="font-size:22px">✦</span><div><strong>Згенерувати ідеї</strong><small style="display:block;color:#c7d2fe">AI запропонує теми на основі бренду</small></div></div>
    <div class="quick-action" data-action="plan"><span>▤</span><div><strong>Створити контент-план</strong><small class="muted">На тиждень або місяць</small></div></div>
    <div class="quick-action" data-action="drafts"><span>☷</span><div><strong>Створити чернетку</strong><small class="muted">З ідеї або з нуля</small></div></div>
    <div class="quick-action" data-action="calendar"><span>□</span><div><strong>Запланувати пост</strong><small class="muted">Готова чернетка → календар</small></div></div>`;
  document.querySelectorAll(".quick-action").forEach(node => node.onclick = () => setView(node.dataset.action));
  const upcoming = drafts.filter(x => x.scheduled_at).sort((a,b) => new Date(a.scheduled_at)-new Date(b.scheduled_at)).slice(0,6);
  document.querySelector("#upcomingList").innerHTML = upcoming.length ? upcoming.map(item => `<button class="quick-action" data-draft="${item.id}"><strong style="min-width:54px">${formatDate(item.scheduled_at)}</strong><span style="text-align:left">${esc(item.title)}</span>${pill(item.status)}</button>`).join("") : empty("Публікацій ще немає","Підготуйте чернетку та додайте її до календаря.");
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
  renderFilters(document.querySelector("#ideaFilters"), [["all","Усі рубрики"],...(state.data.rubrics||[]).map(x => [x.slug,x.name])], state.ideaFilter, value => {state.ideaFilter=value;renderIdeas();});
  const items = (state.data.ideas || []).filter(x => state.ideaFilter === "all" || x.product === state.ideaFilter);
  document.querySelector("#ideasGrid").innerHTML = items.length ? items.map(item => `<article class="card idea-card"><div class="row between"><span class="pill idea">${esc((state.data.rubrics||[]).find(x=>x.slug===item.product)?.name||item.product)}</span><button class="icon-button ghost" aria-label="Меню">⋯</button></div><h3>${esc(item.title)}</h3><p>${esc(item.angle || "Перспективна тема для майбутньої публікації.")}</p><footer><small class="muted">${formatDate(item.planned_for)}</small><button class="dark-button" data-generate-idea="${item.id}">Створити чернетку</button></footer></article>`).join("") : empty("У вас ще немає ідей","Згенеруйте перші теми на основі бренду та рубрик.",'<button class="primary" id="emptyGenerateIdeas">✦ Згенерувати ідеї</button>');
  document.querySelectorAll("[data-generate-idea]").forEach(button => button.onclick = () => generateIdea(button));
  document.querySelector("#emptyGenerateIdeas")?.addEventListener("click", () => document.querySelector("#generateIdeas").click());
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
  const planned = (state.data.ideas||[]).filter(x => x.plan_id);
  document.querySelector("#planList").innerHTML = planned.length ? planned.map(item => `<div class="plan-row"><strong>${formatDate(item.planned_for)}</strong><span>${esc(item.title)}</span>${pill(item.status)}</div>`).join("") : empty("Контент-план порожній","Виберіть параметри та створіть перший план.");
}

function renderDrafts() {
  const kanban = state.company.settings?.workspace_mode === "kanban";
  renderFilters(document.querySelector("#draftFilters"), [["all","Усі"],["draft","Чернетки"],["review","На перевірці"],["ready","Готові"],["scheduled","Заплановані"],["published","Опубліковані"]], state.draftFilter, value => {state.draftFilter=value;renderDrafts();});
  const drafts = (state.data.drafts||[]).filter(x => state.draftFilter === "all" || x.status === state.draftFilter);
  const target = document.querySelector("#draftsContent");
  if (kanban) {
    target.innerHTML = `<div class="kanban-board">${statusOrder.map(status => {const rows = status==="idea" ? [] : drafts.filter(x=>x.status===status);return `<section class="kanban-column"><div class="kanban-head"><span>${statusLabels[status]}</span><span>${rows.length}</span></div>${rows.map(item=>`<article class="kanban-card" data-open-draft="${item.id}">${pill(item.status)}<h4>${esc(item.title)}</h4><small class="muted">${formatDate(item.scheduled_at||item.created_at)}</small></article>`).join("")}</section>`;}).join("")}</div>`;
  } else {
    target.innerHTML = drafts.length ? `<div class="draft-grid">${drafts.map(item => `<article class="card draft-card"><div class="draft-cover">${item.image_path?`<img src="${apiUrl(`api/drafts/${item.id}/image`)}" alt="">`:`<strong>${esc(item.visual_title||item.title)}</strong>`}</div><div class="draft-body">${pill(item.status)}<h3>${esc(item.title)}</h3><p class="muted">${esc(plain(item.caption_html).slice(0,130))}</p><footer><small class="muted">${formatDate(item.scheduled_at||item.created_at)}</small><button data-open-draft="${item.id}">Відкрити</button></footer></div></article>`).join("")}</div>` : empty("Чернеток ще немає","Створіть чернетку з ідеї або додайте матеріал вручну.");
  }
  document.querySelectorAll("[data-open-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.openDraft)));
}

function renderCalendar() {
  const year = state.calendarDate.getFullYear(), month = state.calendarDate.getMonth();
  document.querySelector("#calendarTitle").textContent = state.calendarDate.toLocaleDateString("uk-UA",{month:"long",year:"numeric"});
  const drafts = state.data.drafts || [];
  const ready = drafts.filter(x => x.status === "ready");
  document.querySelector("#calendarReady").innerHTML = ready.length ? ready.map(x=>`<button class="quick-action" data-open-draft="${x.id}">${pill(x.status)}<span style="text-align:left">${esc(x.title)}</span></button>`).join("") : `<p class="muted">Немає готових чернеток.</p>`;
  const first = new Date(year,month,1), offset = (first.getDay()+6)%7;
  const start = new Date(year,month,1-offset);
  const cells = [];
  for (let i=0;i<42;i++) {
    const day = new Date(start); day.setDate(start.getDate()+i);
    const key = day.toISOString().slice(0,10);
    const events = drafts.filter(x => x.scheduled_at && new Date(x.scheduled_at).toISOString().slice(0,10)===key);
    cells.push(`<div class="calendar-day ${day.getMonth()!==month?"outside":""} ${key===new Date().toISOString().slice(0,10)?"today":""}"><strong>${day.getDate()}</strong>${events.map(x=>`<button class="calendar-event" data-open-draft="${x.id}">${new Date(x.scheduled_at).toLocaleTimeString("uk-UA",{hour:"2-digit",minute:"2-digit"})} · ${esc(x.title)}</button>`).join("")}</div>`);
  }
  document.querySelector("#calendarGrid").innerHTML = ["Пн","Вт","Ср","Чт","Пт","Сб","Нд"].map(x=>`<div class="calendar-weekday">${x}</div>`).join("")+cells.join("");
  document.querySelectorAll("[data-open-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.openDraft)));
}

function renderBrand() {
  const settings = state.company.settings || {};
  const target = document.querySelector("#brandContent");
  if (state.brandTab === "profile") target.innerHTML = `<div class="brand-layout"><article class="card brand-summary"><div class="row"><span class="workspace-logo">${initials(state.company.name)}</span><div><h2 style="margin:0">${esc(state.company.name)}</h2><span class="muted">${esc(settings.key_services||"Додайте ключові послуги")}</span></div></div><div class="form-grid" style="margin-top:22px"><label>Сайт<input id="brandWebsite" value="${esc(settings.website_url||"")}"></label><label>Основний колір<input id="brandColor" type="color" value="${esc(settings.brand_primary_color||"#6366f1")}"></label><label class="wide">Опис компанії<textarea id="brandDescription">${esc(settings.company_description||"")}</textarea></label></div><button class="primary" id="saveBrandProfile" style="margin-top:14px">Зберегти профіль</button></article><aside class="card panel"><h2>Рубрики</h2>${(state.data.rubrics||[]).map(x=>`<div class="usage-row"><span>${esc(x.name)}</span><strong>${(state.data.ideas||[]).filter(i=>i.product===x.slug).length}</strong></div>`).join("")||'<p class="muted">Ще немає рубрик.</p>'}</aside></div>`;
  else if (state.brandTab === "tone") target.innerHTML = `<article class="card panel"><div class="row between"><div><div class="eyebrow">Стиль комунікації</div><h2>Tone of voice</h2></div><button class="primary" id="saveTone">Зберегти</button></div><textarea id="toneValue">${esc(settings.tone_of_voice||"")}</textarea><div class="tone-boxes" style="margin-top:14px"><div class="tone-good"><strong>✓ Що можна</strong><p>Писати зрозуміло, конкретно та впевнено.</p></div><div class="tone-bad"><strong>× Чого не можна</strong><p>${esc(settings.forbidden_phrases||"Додайте заборонені формулювання.")}</p></div></div></article>`;
  else if (state.brandTab === "rubrics") target.innerHTML = `<article class="card panel"><div class="row between"><h2>Рубрики контенту</h2><button class="primary" id="addRubric">＋ Додати</button></div>${(state.data.rubrics||[]).map(x=>`<div class="usage-row"><span><strong>${esc(x.name)}</strong><small class="muted" style="display:block">${esc(x.description)}</small></span><span>${x.active===0?"Неактивна":"Активна"}</span></div>`).join("")}</article>`;
  else if (state.brandTab === "visuals") target.innerHTML = `<div class="asset-grid">${(state.data.templates||[]).map(x=>`<article class="card asset-card"><img src="${apiUrl(`api/templates/${encodeURIComponent(x.id)}/preview`)}" alt=""><div style="padding:11px"><strong>${esc(x.name)}</strong><small class="muted" style="display:block">${esc(x.description)}</small></div></article>`).join("")}</div>`;
  else target.innerHTML = `<div class="asset-grid">${(state.data.references||[]).map(x=>`<article class="card asset-card"><img src="${apiUrl(`api/references/${x.id}/image`)}" alt=""><div style="padding:10px">${esc(x.name||x.filename||"Матеріал")}</div></article>`).join("")||empty("Матеріалів ще немає","Завантажте логотипи, фото або референси.")}</div>`;
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
}

function renderSettings() {
  const target = document.querySelector("#settingsContent");
  const settings = state.company.settings || {};
  if (state.settingsTab === "workspace") target.innerHTML = `<article class="card settings-card"><div class="row"><span class="workspace-logo">${initials(state.company.name)}</span><div><h2 style="margin:0">${esc(state.company.name)}</h2><span class="muted">${esc(state.company.slug)}</span></div></div><div class="analytics-metrics" style="margin-top:20px"><div class="card metric"><span>Тариф</span><strong>${esc(state.company.plan_code||"custom")}</strong></div><div class="card metric"><span>Користувачі</span><strong>${state.company.user_count}/${state.company.max_users}</strong></div><div class="card metric"><span>Публікації</span><strong>${state.company.publication_count}/${state.company.monthly_publications}</strong></div><div class="card metric"><span>AI-бюджет</span><strong>${money(state.company.monthly_ai_budget)}</strong></div></div><button id="restartOnboarding">Повторити onboarding</button></article>`;
  else if (state.settingsTab === "mode") target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Загальні</div><h2>Режим роботи workspace</h2><p class="muted">Оберіть, як ваша команда працює з контентом.</p><div class="mode-grid"><label class="card panel"><input type="radio" name="workspaceMode" value="pipeline" ${settings.workspace_mode==="pipeline"?"checked":""}> <strong>Редакційний pipeline</strong><p class="muted">Послідовний процес: ідеї → план → чернетки → календар.</p></label><label class="card panel"><input type="radio" name="workspaceMode" value="kanban" ${settings.workspace_mode==="kanban"?"checked":""}> <strong>Контент-дошка Kanban</strong><p class="muted">Усі матеріали за статусами на одній дошці.</p></label></div><button class="primary" id="saveWorkspaceMode">Зберегти режим</button></article>`;
  else if (state.settingsTab === "users") target.innerHTML = `<article class="card settings-card"><div class="row between"><div><h2 style="margin:0">Користувачі workspace</h2><p class="muted">Ролі та доступ команди.</p></div><button class="primary" id="inviteUser">＋ Запросити користувача</button></div><table class="users-table"><thead><tr><th>Користувач</th><th>Роль</th><th>Статус</th><th></th></tr></thead><tbody>${state.users.map(x=>`<tr><td><strong>${esc(x.display_name||x.username)}</strong><small class="muted" style="display:block">${esc(x.email||x.username)}</small></td><td>${esc(x.role||"editor")}</td><td>${x.active?"Активний":"Вимкнений"}</td><td><button data-reset-user="${x.id}">Reset link</button></td></tr>`).join("")}</tbody></table></article>`;
  else if (state.settingsTab === "integrations") target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Telegram</div><h2>Підключення каналу</h2><div class="form-grid"><label>Channel username<input id="telegramChannel" value="${esc(state.company.telegram?.channel_id||"")}"></label><label>Bot token<input id="telegramToken" type="password" placeholder="Вставте новий токен"></label></div><button class="primary" id="saveTelegram" style="margin-top:14px">Перевірити та зберегти</button></article>`;
  else target.innerHTML = `<article class="card settings-card"><h2>Безпека</h2><p class="muted">Змініть пароль або створіть одноразове посилання через адміністратора workspace.</p><div class="form-grid"><label>Новий пароль<input id="ownPassword" type="password" minlength="10"></label></div><button class="primary" id="changePassword" style="margin-top:14px">Змінити пароль</button></article>`;
  bindSettingsActions();
}

async function openEditor(id, push = true) {
  try {
    const draft = await api(`api/drafts/${id}`);
    state.currentDraft = draft;
    if (push) history.pushState({draft:id},"",`${basePath}/workspace/${state.me.organization_slug}/drafts/${id}`);
    const target = document.querySelector("#editorContent");
    target.innerHTML = `<header class="editor-header"><div class="row"><button id="closeEditor">←</button><div>${pill(draft.status)} <strong style="margin-left:8px">${esc(draft.title)}</strong></div></div><div class="row"><button id="regenText">Перегенерувати текст</button><button id="saveDraft">Зберегти</button><button class="primary" id="publishDraft">Опублікувати</button></div></header><div class="editor-grid"><form class="editor-form" id="editorForm"><div class="form-grid"><label>Рубрика<input value="${esc(draft.product)}" disabled></label><label>Дата і час<input id="scheduleAt" type="datetime-local" value="${draft.scheduled_at?new Date(draft.scheduled_at).toISOString().slice(0,16):""}"></label></div><label>Заголовок для поста<input id="editorTitle" value="${esc(draft.title)}"></label><label>Заголовок на візуалі<input id="editorVisualTitle" value="${esc(draft.visual_title||draft.title)}"><small class="muted">Без emoji та зайвих символів.</small></label><label>Текст публікації<textarea id="editorCaption" style="min-height:330px">${esc(draft.caption_html)}</textarea></label><label>Посилання<input id="editorLink" value="${esc(draft.link_url||"")}"></label><div class="row"><button type="button" id="scheduleDraft">Запланувати</button><button type="button" id="cancelSchedule">Повернути в готові</button><button type="button" id="proofreadDraft">Перевірити текст</button></div></form><aside class="editor-preview"><div class="editor-preview-card"><div class="row"><span class="workspace-logo" style="width:30px;height:30px">${initials(state.company.name)}</span><div><strong>${esc(state.company.name)}</strong><small style="display:block;color:#94a3b8">Telegram</small></div></div><img src="${apiUrl(`api/drafts/${id}/image`)}" alt="" onerror="this.style.display='none'"><h2 id="previewTitle">${esc(draft.visual_title||draft.title)}</h2><p id="previewText" style="color:#cbd5e1;white-space:pre-wrap">${esc(plain(draft.caption_html).slice(0,650))}</p></div></aside></div>`;
    document.querySelector("#editorOverlay").hidden = false;
    bindEditorActions();
  } catch (error) { toast(error.message,true); }
}
function closeEditor() {
  document.querySelector("#editorOverlay").hidden = true;
  if (location.pathname.includes("/drafts/")) history.pushState({},"",`${basePath}/`);
}

function showForm(title, fields, submit) {
  document.querySelector("#formTitle").textContent = title;
  document.querySelector("#formBody").innerHTML = `<div class="form-grid">${fields}</div><div class="form-error" id="dynamicError"></div>`;
  document.querySelector("#formOverlay").hidden = false;
  const form = document.querySelector("#dynamicForm");
  form.onsubmit = async event => {
    event.preventDefault();
    try { await submit(new FormData(form)); document.querySelector("#formOverlay").hidden=true; }
    catch (error) { document.querySelector("#dynamicError").textContent=error.message; }
  };
}
function renderWorkspaceChooser(force = false) {
  const workspaces = state.me.workspaces || [];
  if (!force && workspaces.length < 2 && !state.me.is_super_admin) return;
  document.querySelector("#workspaceGrid").innerHTML = workspaces.map(x=>`<button class="card workspace-card ${x.id===state.me.organization_id?"active":""}" data-workspace="${x.id}"><span class="workspace-logo">${initials(x.name)}</span><h3>${esc(x.name)}</h3><p class="muted">${esc(x.plan_code||"custom")} plan</p><div class="workspace-meta"><span>${esc(x.role||"workspace")}</span><span>${x.user_count||0} корист.</span></div></button>`).join("")+`<button class="card workspace-card workspace-create" id="createWorkspace"><span style="font-size:28px">＋</span><strong>Створити workspace</strong><small class="muted">14 днів trial</small></button>`;
  document.querySelector("#workspaceOverlay").hidden = false;
  document.querySelectorAll("[data-workspace]").forEach(button=>button.onclick=async()=>{await api("api/workspace/select",{method:"POST",body:JSON.stringify({organization_id:Number(button.dataset.workspace)})});location.href=`${basePath}/`;});
  document.querySelector("#createWorkspace").onclick = () => showForm("Створити workspace", `<label>Назва<input name="name" required></label><label>Slug<input name="slug" pattern="[A-Za-z0-9-]+" required></label>`, async form => {await api("api/account/trial-workspace",{method:"POST",body:JSON.stringify({name:form.get("name"),slug:form.get("slug")})});location.href=`${basePath}/`;});
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
    1:`<h2>Ласкаво просимо до Content Studio</h2><p class="muted">Налаштуйте workspace за п’ять коротких кроків. Прогрес зберігається після кожного кроку.</p><div class="progress">${[1,2,3,4,5].map(x=>`<span class="${x<=state.onboardingStep?"active":""}"></span>`).join("")}</div><div class="form-grid"><label>Назва компанії<input id="obName" value="${esc(state.company.name)}"></label><label>Slug<input id="obSlug" value="${esc(state.company.slug)}"></label></div>`,
    2:`<h2>Бренд та стиль комунікації</h2><div class="form-grid"><label class="wide">Опис компанії<textarea id="obDescription">${esc(settings.company_description||"")}</textarea></label><label class="wide">Tone of voice<textarea id="obTone">${esc(settings.tone_of_voice||"")}</textarea></label><label>Ключові послуги<textarea id="obServices">${esc(settings.key_services||"")}</textarea></label><label>Заборонені фрази<textarea id="obForbidden">${esc(settings.forbidden_phrases||"")}</textarea></label></div>`,
    3:`<h2>Підключіть Telegram-канал</h2><p class="muted">Цей крок можна пропустити та повернутися в налаштуваннях.</p><div class="form-grid"><label>Channel username<input id="obChannel" value="${esc(state.company.telegram?.channel_id||"")}"></label><label>Bot token<input id="obToken" type="password"></label></div>`,
    4:`<h2>Оберіть рубрики контенту</h2><p class="muted">Додайте по одній рубриці в кожному рядку.</p><textarea id="obRubrics">${(state.data.rubrics||[]).map(x=>x.name).join("\n")}</textarea>`,
    5:`<h2>Створіть перший контент-план</h2><div class="form-grid"><label>Період<select id="obPeriod"><option value="week">Тиждень</option><option value="month">Місяць</option></select></label><label>Кількість постів<input id="obPosts" type="number" value="5" min="1" max="31"></label><label class="wide">Мета<textarea id="obFocus"></textarea></label></div>`,
  };
  document.querySelector("#onboardingBody").innerHTML = contents[state.onboardingStep];
  document.querySelector("#onboardingOverlay").hidden = false;
}
async function saveOnboarding() {
  const step = state.onboardingStep;
  if (step === 1) await api("api/onboarding/company",{method:"PUT",body:JSON.stringify({name:document.querySelector("#obName").value,slug:document.querySelector("#obSlug").value,primary_language:"uk",brand_primary_color:"#6366f1",brand_logo_asset_id:null})});
  if (step === 2) await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#obDescription").value,tone_of_voice:document.querySelector("#obTone").value,key_services:document.querySelector("#obServices").value,forbidden_phrases:document.querySelector("#obForbidden").value,website_url:""})});
  if (step === 3 && document.querySelector("#obToken").value) await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#obChannel").value,bot_token:document.querySelector("#obToken").value})});
  if (step === 4) {
    const rubrics=document.querySelector("#obRubrics").value.split("\n").map(x=>x.trim()).filter(Boolean).map(name=>({name,description:`Публікації для рубрики «${name}».`}));
    if (rubrics.length) await api("api/onboarding/rubrics",{method:"POST",body:JSON.stringify({rubrics})});
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
function bindBrandActions() {
  document.querySelector("#saveBrandProfile")?.addEventListener("click",async()=>{await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#brandDescription").value,tone_of_voice:state.company.settings.tone_of_voice||"",key_services:state.company.settings.key_services||"",forbidden_phrases:state.company.settings.forbidden_phrases||"",website_url:document.querySelector("#brandWebsite").value})});toast("Профіль збережено");await refresh();});
  document.querySelector("#saveTone")?.addEventListener("click",async()=>{await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:state.company.settings.company_description||"",tone_of_voice:document.querySelector("#toneValue").value,key_services:state.company.settings.key_services||"",forbidden_phrases:state.company.settings.forbidden_phrases||"",website_url:state.company.settings.website_url||""})});toast("Tone of voice збережено");await refresh();});
  document.querySelector("#addRubric")?.addEventListener("click",()=>showForm("Додати рубрику",`<label>Назва<input name="name" required></label><label>Slug<input name="slug" pattern="[a-z0-9-]+" required></label><label class="wide">Опис<textarea name="description" minlength="20" required></textarea></label><label class="wide">Інструкції для AI<textarea name="instructions"></textarea></label>`,async form=>{await api("api/rubrics",{method:"POST",body:JSON.stringify({name:form.get("name"),slug:form.get("slug"),description:form.get("description"),instructions:form.get("instructions"),default_link:""})});toast("Рубрику створено");await refresh();renderBrand();}));
}
function bindSettingsActions() {
  document.querySelector("#saveWorkspaceMode")?.addEventListener("click",async()=>{const mode=document.querySelector('[name="workspaceMode"]:checked').value;await api("api/workspace/mode",{method:"PUT",body:JSON.stringify({workspace_mode:mode})});state.company.settings.workspace_mode=mode;applyIdentity();renderSettings();toast("Режим збережено");});
  document.querySelector("#restartOnboarding")?.addEventListener("click",async()=>{await api("api/onboarding/restart",{method:"POST"});showOnboarding(1);});
  document.querySelector("#inviteUser")?.addEventListener("click",()=>showForm("Запросити користувача",`<label>Email<input name="email" type="email" required></label><label>Роль<select name="role"><option value="editor">Editor</option><option value="admin">Admin</option><option value="viewer">Viewer</option></select></label>`,async form=>{const result=await api("api/invitations",{method:"POST",body:JSON.stringify({email:form.get("email"),role:form.get("role")})});await navigator.clipboard.writeText(result.url);toast("Посилання скопійовано");}));
  document.querySelectorAll("[data-reset-user]").forEach(button=>button.onclick=async()=>{const result=await api("api/password-reset/link",{method:"POST",body:JSON.stringify({user_id:Number(button.dataset.resetUser)})});await navigator.clipboard.writeText(result.url);toast("Reset-посилання скопійовано");});
  document.querySelector("#saveTelegram")?.addEventListener("click",async()=>{await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#telegramChannel").value,bot_token:document.querySelector("#telegramToken").value})});toast("Telegram підключено");await refresh();});
  document.querySelector("#changePassword")?.addEventListener("click",async()=>{await api("api/account/password",{method:"PUT",body:JSON.stringify({password:document.querySelector("#ownPassword").value})});location.href=`${basePath}/`;});
}
function bindEditorActions() {
  document.querySelector("#closeEditor").onclick=closeEditor;
  const updatePreview=()=>{document.querySelector("#previewTitle").textContent=document.querySelector("#editorVisualTitle").value;document.querySelector("#previewText").textContent=plain(document.querySelector("#editorCaption").value).slice(0,650);};
  document.querySelector("#editorVisualTitle").oninput=updatePreview;document.querySelector("#editorCaption").oninput=updatePreview;
  document.querySelector("#saveDraft").onclick=async()=>{await api(`api/drafts/${state.currentDraft.id}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#editorTitle").value,visual_title:document.querySelector("#editorVisualTitle").value,caption_html:document.querySelector("#editorCaption").value,link_url:document.querySelector("#editorLink").value})});toast("Зміни збережено");await refresh();};
  document.querySelector("#regenText").onclick=async()=>{await api(`api/drafts/${state.currentDraft.id}/regenerate-text`,{method:"POST",body:JSON.stringify(generationPayload())});toast("Нову версію поставлено в чергу");closeEditor();await refresh();};
  document.querySelector("#proofreadDraft").onclick=async()=>{const draft=await api(`api/drafts/${state.currentDraft.id}/proofread`,{method:"POST",body:JSON.stringify({text_model:"gpt-5.4-mini"})});document.querySelector("#editorCaption").value=draft.caption_html;toast("Текст перевірено");};
  document.querySelector("#scheduleDraft").onclick=async()=>{const value=document.querySelector("#scheduleAt").value;if(!value)return toast("Оберіть дату і час",true);await api(`api/drafts/${state.currentDraft.id}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(value).toISOString()})});toast("Публікацію заплановано");closeEditor();await refresh();};
  document.querySelector("#cancelSchedule").onclick=async()=>{await api(`api/drafts/${state.currentDraft.id}/cancel-schedule`,{method:"POST"});toast("Публікацію повернуто в готові");closeEditor();await refresh();};
  document.querySelector("#publishDraft").onclick=async()=>{if(!confirm("Опублікувати пост зараз?"))return;await api(`api/drafts/${state.currentDraft.id}/publish`,{method:"POST"});toast("Пост опубліковано");closeEditor();await refresh();};
}

async function refresh(background = false) {
  try {
    const [me, company, data, usage] = await Promise.all([api("api/me"),api("api/company"),api("api/dashboard"),api("api/usage")]);
    state.me=me;state.company=company;state.data=data;state.usage=usage;
    if (me.is_admin) state.users=await api("api/users");
    applyIdentity();renderCurrent();
    if (!background && company.settings && !["completed","skipped"].includes(company.settings.onboarding_status) && me.is_admin) showOnboarding(Math.max(1,Number(company.settings.onboarding_step||0)+1));
    const parts=location.pathname.split("/").filter(Boolean);const index=parts.indexOf("workspace");
    if (!background && index>=0 && parts[index+2]==="drafts" && Number(parts[index+3])) openEditor(Number(parts[index+3]),false);
  } catch (error) { if (!background) toast(error.message,true); }
}

document.querySelectorAll(".nav-item[data-view]").forEach(node=>node.onclick=()=>setView(node.dataset.view));
document.querySelector("#mobileMenu").onclick=()=>document.body.classList.add("menu-open");
document.addEventListener("click",event=>{if(document.body.classList.contains("menu-open")&&!event.target.closest(".sidebar")&&!event.target.closest("#mobileMenu"))document.body.classList.remove("menu-open");});
document.querySelector("#workspaceButton").onclick=()=>renderWorkspaceChooser(true);
document.querySelector("#logout").onclick=async()=>{await api("api/logout",{method:"POST"});location.href=`${basePath}/`;};
document.querySelectorAll("[data-close-overlay]").forEach(node=>node.onclick=()=>node.closest(".overlay").hidden=true);
document.querySelector("#generateIdeas").onclick=event=>showForm("Згенерувати ідеї",`<label>Рубрика<select name="product"><option value="all">Усі рубрики</option>${(state.data?.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Кількість<input name="count" type="number" min="1" max="12" value="8"></label><label class="wide">Фокус<textarea name="focus"></textarea></label>`,async form=>{await api("api/ideas/generate",{method:"POST",body:JSON.stringify({product:form.get("product"),count:Number(form.get("count")),focus:form.get("focus"),text_model:"gpt-5.4-mini",tone:"expert"})});toast("Ідеї створено");await refresh();});
document.querySelector("#manualIdea").onclick=()=>showForm("Створити ідею",`<label class="wide">Назва<input name="title" required></label><label>Рубрика<select name="product">${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Орієнтовна дата<input name="planned_for" type="date"></label><label class="wide">Кут подачі<textarea name="angle"></textarea></label>`,async form=>{await api("api/ideas",{method:"POST",body:JSON.stringify({title:form.get("title"),product:form.get("product"),planned_for:form.get("planned_for")||null,angle:form.get("angle")})});toast("Ідею додано");await refresh();});
document.querySelector("#manualDraft").onclick=()=>showForm("Створити чернетку",`<label class="wide">Заголовок<input name="title" required></label><label>Рубрика<select name="product">${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Заголовок на візуалі<input name="visual_title"></label><label class="wide">Текст<textarea name="caption_html" minlength="20" required></textarea></label><label class="wide">Посилання<input name="link_url" type="url"></label>`,async form=>{const draft=await api("api/drafts",{method:"POST",body:JSON.stringify({title:form.get("title"),visual_title:form.get("visual_title"),product:form.get("product"),caption_html:form.get("caption_html"),link_url:form.get("link_url")})});toast("Чернетку створено");await refresh();openEditor(draft.id);});
document.querySelector("#calendarSchedule").onclick=()=>{const ready=(state.data.drafts||[]).filter(x=>x.status==="ready");showForm("Запланувати пост",`<label class="wide">Чернетка<select name="draft_id">${ready.map(x=>`<option value="${x.id}">${esc(x.title)}</option>`).join("")}</select></label><label class="wide">Дата і час<input name="scheduled_at" type="datetime-local" required></label>`,async form=>{await api(`api/drafts/${form.get("draft_id")}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(form.get("scheduled_at")).toISOString()})});toast("Публікацію заплановано");await refresh();});};
document.querySelector("#planForm").onsubmit=async event=>{event.preventDefault();await loading(event.submitter,async()=>{await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({product:document.querySelector("#planProduct").value,period:document.querySelector("#planPeriod").value,posts:Number(document.querySelector("#planPosts").value),start_date:document.querySelector("#planStart").value,focus:document.querySelector("#planFocus").value,text_model:"gpt-5.4-mini",create_as:document.querySelector("#planCreateAs").value,rubric_slugs:[],channel_ids:[]})});toast("Контент-план створено");await refresh();renderPlan();},"Створюємо…");};
document.querySelector("#calendarPrev").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar();};
document.querySelector("#calendarNext").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar();};
document.querySelector("#calendarToday").onclick=()=>{state.calendarDate=new Date();renderCalendar();};
document.querySelector("#onboardingBack").onclick=()=>showOnboarding(state.onboardingStep-1);
document.querySelector("#onboardingNext").onclick=event=>loading(event.currentTarget,saveOnboarding,"Зберігаємо…");
document.querySelector("#skipOnboarding").onclick=async()=>{await api("api/onboarding/skip",{method:"POST"});document.querySelector("#onboardingOverlay").hidden=true;};
document.querySelectorAll("[data-brand-tab]").forEach(node=>node.onclick=()=>{state.brandTab=node.dataset.brandTab;document.querySelectorAll("[data-brand-tab]").forEach(x=>x.classList.toggle("active",x===node));renderBrand();});
document.querySelectorAll("[data-settings]").forEach(node=>node.onclick=()=>{state.settingsTab=node.dataset.settings;document.querySelectorAll("[data-settings]").forEach(x=>x.classList.toggle("active",x===node));renderSettings();});
document.querySelector("#searchButton").onclick=()=>{
  showForm("Пошук",`<label class="wide">Ідеї, чернетки та розділи<input name="query" id="globalSearch" autofocus></label><div class="wide stack" id="searchResults"></div>`,async()=>{});
  const input=document.querySelector("#globalSearch"),results=document.querySelector("#searchResults");
  input.oninput=()=>{const query=input.value.trim().toLowerCase();if(!query){results.innerHTML="";return}const rows=[...(state.data.ideas||[]).map(x=>({...x,type:"Ідея",view:"ideas"})),...(state.data.drafts||[]).map(x=>({...x,type:"Чернетка",view:"drafts"}))].filter(x=>`${x.title} ${x.angle||""} ${plain(x.caption_html||"")}`.toLowerCase().includes(query)).slice(0,8);results.innerHTML=rows.map(x=>`<button type="button" class="quick-action" data-search-view="${x.view}" data-search-draft="${x.type==="Чернетка"?x.id:""}"><span class="pill ${x.type==="Ідея"?"idea":"draft"}">${x.type}</span><span>${esc(x.title)}</span></button>`).join("")||'<p class="muted">Нічого не знайдено.</p>';results.querySelectorAll("button").forEach(button=>button.onclick=()=>{document.querySelector("#formOverlay").hidden=true;if(button.dataset.searchDraft)openEditor(Number(button.dataset.searchDraft));else setView(button.dataset.searchView);});};
};
document.querySelector("#createButton").onclick=()=>setView("ideas");
document.querySelector("#notificationsButton").onclick=()=>{const failed=(state.data?.jobs||[]).filter(x=>x.status==="failed");const expiry=state.company?.plan_expires_at?Math.ceil((new Date(state.company.plan_expires_at)-new Date())/86400000):null;const messages=[];if(failed.length)messages.push(`Помилок генерації: ${failed.length}`);if(state.company?.plan_code==="trial"&&expiry!==null)messages.push(`Trial: ${Math.max(0,expiry)} дн.`);const spend=Number(state.company?.ai_spend||0),budget=Number(state.company?.monthly_ai_budget||0);if(budget&&spend/budget>=.7)messages.push(`Використано ${Math.round(spend/budget*100)}% AI-бюджету`);toast(messages.join(" · ")||"Нових сповіщень немає",!!failed.length);};
document.querySelector("#exportPlan").onclick=()=>exportCsv("content-plan.csv",(state.data.ideas||[]).filter(x=>x.plan_id),["planned_for","title","product","status"]);
document.querySelector("#exportDrafts").onclick=()=>exportCsv("drafts.csv",state.data.drafts||[],["id","title","product","status","scheduled_at"]);
document.querySelector("#exportUsage").onclick=()=>exportCsv("usage.csv",state.data.daily||[],["day","cost"]);
function exportCsv(name,rows,fields){const csv=[fields.join(","),...rows.map(row=>fields.map(key=>`"${String(row[key]??"").replaceAll('"','""')}"`).join(","))].join("\n");const link=document.createElement("a");link.href=URL.createObjectURL(new Blob(["\ufeff"+csv],{type:"text/csv"}));link.download=name;link.click();URL.revokeObjectURL(link.href);}
window.addEventListener("popstate",()=>{if(!location.pathname.includes("/drafts/"))document.querySelector("#editorOverlay").hidden=true;});
refresh();
setInterval(()=>refresh(true),30000);
