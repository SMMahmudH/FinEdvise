/* FinEdvise web interface. Plain JavaScript, no build step.
   Every piece of text from the server or from files is inserted with
   textContent (never innerHTML). Numbers come from the API; nothing is
   calculated here except formatting. */
"use strict";

const TABS = ["home", "plan", "copilot", "financing", "approvals", "records", "security", "extras", "team"];
const state = {
  session: null, overview: null, plans: null, ledger: null, proposals: null, audit: null, financing: null,
  plan: { amount: 77000, week: 1, shocks: new Set(), view: "plan" },
  homeView: "plan", recordsView: "plan", recordKind: "students", recordDraft: null, teamCredential: null,
  chat: [], importReport: null, redteam: null, finPlan: null, finAmount: 45000, reminders: null,
  recordSearch: "", recordPage: 0, recordPageSize: 10,
  occasion: { kind: "picnic", budget: 30000, date: "" },
  busy: false,
};
let liveClockInterval = null;


/* ------------------------------------------------------------ utilities */
const t = (key, vars) => I18N.t(key, vars);
const M = (v) => I18N.money(v);
const D = (s) => I18N.d(s);

function formatDhakaNow() {
  try {
    return new Intl.DateTimeFormat(I18N.lang === "bn" ? "bn-BD" : "en-BD", {
      timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short", hour12: true,
    }).format(new Date());
  } catch (_) { return new Date().toLocaleString(); }
}
function startLiveClock() {
  if (liveClockInterval) return;
  const tick = () => {
    const node = document.getElementById("live-clock");
    if (node) node.textContent = formatDhakaNow();
  };
  tick();
  liveClockInterval = window.setInterval(tick, 30000);
}
function localDhakaDate() {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Dhaka", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const values = Object.fromEntries(parts.filter((p) => p.type !== "literal").map((p) => [p.type, p.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "style") node.style.cssText = v;  // CSSOM, allowed by the strict CSP (no inline style attributes)
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function pick(obj, base) {
  if (!obj) return "";
  return I18N.lang === "bn" ? (obj[base + "_bn"] ?? obj[base + "_en"]) : obj[base + "_en"];
}

async function api(path, body) {
  const opts = { credentials: "same-origin", headers: { "X-FinEdvise": "1" } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok && res.status !== 403) {
    throw new Error((data && data.error) || `HTTP ${res.status}`);
  }
  return { status: res.status, data };
}

async function apiRequireOk(path, body) {
  const result = await api(path, body);
  if (result.status < 200 || result.status >= 300) {
    throw new Error((result.data && result.data.error) || `HTTP ${result.status}`);
  }
  return result;
}

function setAuthVisibility(isVisible) {
  document.getElementById("authRoot").hidden = !isVisible;
  document.querySelector(".topbar").hidden = isVisible;
  document.querySelector(".shell").hidden = isVisible;
}

function showApplication() {
  setAuthVisibility(false);
  const top = document.querySelector(".topbar");
  const shell = document.querySelector(".shell");
  top.hidden = false;
  shell.hidden = false;
  document.getElementById("school").textContent = state.session?.school_name || "";
}

function authField(label, name, type = "text", options = {}) {
  const input = h("input", { id: "auth-" + name, name, type, required: options.required !== false,
    autocomplete: options.autocomplete || (type === "password" ? "current-password" : type === "email" ? "email" : "off"),
    maxlength: options.maxlength || 254, minlength: options.minlength || null,
    placeholder: options.placeholder || "" });
  return { input, node: h("div", { class: "field" }, h("label", { for: "auth-" + name }, label), input) };
}

function renderAuthScreen(mode = "login", message = "") {
  setAuthVisibility(true);
  const root = document.getElementById("authRoot");
  const panel = h("section", { class: "auth-panel" });
  panel.append(h("div", { class: "muted small" }, "FINEDVISE"),
    h("h2", {}, mode === "signup" ? "Register your school" : "Welcome back"),
    h("p", { class: "muted" }, mode === "signup" ? "Your school starts with its own private, empty workspace — add your own records when ready." : "Sign in to access your school's workspace."));
  const tabs = h("div", { class: "auth-tabs" },
    h("button", { type: "button", "aria-pressed": String(mode === "login"), onClick: () => renderAuthScreen("login") }, "Log in"),
    h("button", { type: "button", "aria-pressed": String(mode === "signup"), onClick: () => renderAuthScreen("signup") }, "Create school account"));
  const form = h("form", { class: "auth-form" });
  const fields = {};
  if (mode === "signup") {
    for (const [key, label, type, opts] of [
      ["school_name", "School name", "text", { maxlength: 160, autocomplete: "organization" }],
      ["owner_name", "Owner's full name", "text", { maxlength: 120, autocomplete: "name" }],
      ["phone", "Phone (optional)", "tel", { required: false, maxlength: 40, autocomplete: "tel" }],
      ["address", "School address (optional)", "text", { required: false, maxlength: 250, autocomplete: "street-address" }],
      ["email", "Email address", "email", { autocomplete: "email" }],
      ["password", "Password (at least 10 characters)", "password", { minlength: 10, autocomplete: "new-password", maxlength: 200 }],
      ["confirm_password", "Confirm password", "password", { minlength: 10, autocomplete: "new-password", maxlength: 200 }],
    ]) { const f = authField(label, key, type, opts); fields[key] = f.input; form.append(f.node); }
  } else {
    for (const [key, label, type, opts] of [
      ["email", "Email address", "email", { autocomplete: "username" }],
      ["password", "Password", "password", { autocomplete: "current-password", maxlength: 200 }],
    ]) { const f = authField(label, key, type, opts); fields[key] = f.input; form.append(f.node); }
  }
  const feedback = h("div", { class: "auth-message", role: "status", "aria-live": "polite" }, message);
  const submit = h("button", { class: "btn", type: "submit" }, mode === "signup" ? "Create school workspace" : "Log in");
  form.append(feedback, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    feedback.textContent = "";
    const payload = Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, key === "password" ? field.value : field.value.trim()]));
    if (mode === "signup" && payload.password !== payload.confirm_password) {
      feedback.textContent = "Passwords do not match."; submit.disabled = false; return;
    }
    delete payload.confirm_password;
    try {
      const path = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
      const { data } = await apiRequireOk(path, payload);
      state.session = data.session;
      if (state.session.must_change_password) { renderPasswordChange(true); return; }
      showApplication();
      await refreshOverview();
      if (location.hash === "#team" && state.session.role !== "owner") location.hash = "#records";
      rerender();
    } catch (err) {
      feedback.textContent = err.message || "Could not authenticate. Please try again.";
      submit.disabled = false;
    }
  });
  const panelBottom = h("p", { class: "auth-muted" }, mode === "signup"
    ? "Your owner account controls access for this school. Accountant and agent accounts are created later from Team & Access."
    : "Choose the school account you were given. Your school records stay private to that workspace.");
  panel.append(tabs, form, panelBottom);
  if (mode === "login") loadDemoAccountCard(panel, fields, form, panelBottom);
  const aside = h("aside", { class: "auth-aside" },
    h("div", {}, h("div", { class: "auth-brand" }, h("img", { src: "/favicon.svg", alt: "" }), h("span", {}, "FinEdvise")),
      h("p", { class: "brand-tagline" }, "Smarter Financial Decisions for Education."),
      h("h1", {}, "Make better financial decisions for your school."),
      h("p", {}, "An AI-driven team helping private educational institutions make better financial decisions, manage uncertainty, and grow sustainably.")),
    h("p", { class: "auth-side-note" }, "Financial decision support · Owner-controlled approvals · School-specific workspace"));
  root.replaceChildren(h("div", { class: "auth-layout" }, aside, panel));
}


async function loadDemoAccountCard(panel, fields, form, panelBottom) {
  try {
    const { data } = await api("/api/demo-info");
    if (!data.enabled) return;
    const card = h("section", { class: "demo-login-card" },
      h("div", { class: "eyebrow" }, "JUDGE / PRESENTATION DEMO"),
      h("h3", {}, data.school_name),
      h("p", { class: "muted small" }, data.notice || "Fictional presentation workspace; do not enter real school data."),
      h("div", { class: "demo-credentials" }, h("div", {}, h("span", {}, "Email"), h("code", {}, data.email)),
        h("div", {}, h("span", {}, "Password"), h("code", {}, data.password))),
      h("button", { class: "btn secondary block", type: "button", onClick: () => {
        fields.email.value = data.email; fields.password.value = data.password; form.requestSubmit();
      } }, "Open demo workspace"));
    panel.insertBefore(card, panelBottom);
  } catch (_) { /* demo discovery is optional; regular sign-in stays available */ }
}

function renderPasswordChange(required = false) {
  setAuthVisibility(true);
  const root = document.getElementById("authRoot");
  const current = authField("Current or temporary password", "current_password", "password", { autocomplete: "current-password", maxlength: 200 });
  const next = authField("New password (at least 10 characters)", "new_password", "password", { autocomplete: "new-password", minlength: 10, maxlength: 200 });
  const feedback = h("div", { class: "auth-message", role: "status", "aria-live": "polite" });
  const submit = h("button", { class: "btn", type: "submit" }, "Update password");
  const form = h("form", { class: "auth-form" }, current.node, next.node, feedback, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); submit.disabled = true; feedback.textContent = "";
    try {
      const { data } = await apiRequireOk("/api/auth/change-password", { current_password: current.input.value, new_password: next.input.value });
      state.session = data.session;
      showApplication(); await refreshOverview(); rerender();
    } catch (err) { feedback.textContent = err.message; submit.disabled = false; }
  });
  const panel = h("section", { class: "auth-panel" }, h("div", { class: "muted small" }, "ACCOUNT SECURITY"),
    h("h2", {}, required ? "Set your personal password" : "Change password"),
    h("p", { class: "muted" }, required ? "Your owner supplied a temporary password. Set a new private password before using the application." : "Choose a new password you do not use on another site."), form,
    h("button", { class: "btn secondary", onClick: logout, style: "margin-top:16px" }, "Log out"));
  root.replaceChildren(h("div", { class: "auth-layout" }, h("aside", { class: "auth-aside" },
    h("div", {}, h("div", { class: "auth-brand" }, h("img", { src: "/favicon.svg", alt: "" }), h("span", {}, "FinEdvise")),
      h("h1", {}, "Protect your school account."), h("p", {}, "Every role uses its own login. Your account permissions are checked by the server."))), panel));
}

async function logout() {
  try { await api("/api/auth/logout", {}); } catch (_) { /* local sign-out still clears the interface */ }
  state.session = null; state.overview = null; state.ledger = null; state.chat = [];
  renderAuthScreen("login", "You have been logged out.");
}

function toast(message) {
  document.querySelectorAll(".toast").forEach((n) => n.remove());
  const node = h("div", { class: "toast", role: "status" }, message);
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function savePref(key, value) { try { localStorage.setItem("finedvise." + key, value); } catch (e) { /* storage unavailable */ } }
function loadPref(key, fallback) { try { return localStorage.getItem("finedvise." + key) || fallback; } catch (e) { return fallback; } }

function badge(name) {
  const meaning = state.overview && state.overview.badges[name];
  return h("span", { class: "badge " + name, title: meaning ? meaning[I18N.lang] : name }, name);
}

function statusChip(status) {
  return h("span", { class: "status " + status }, t("st_" + status));
}

/* --------------------------------------------------------- inspector */
function formatMetricValue(metric) {
  if (metric.value === null || metric.value === undefined) return "–";
  if (metric.unit === "BDT") return M(metric.value);
  if (metric.unit === "students") return D(`${I18N.num(metric.value)} ${I18N.lang === "bn" ? "জন" : "students"}`);
  return I18N.num(metric.value);
}

function inspect(metric) {
  closeDrawer();
  const back = h("div", { class: "drawer-back", onClick: closeDrawer });
  const inputs = Object.entries(metric.inputs || {}).map(([k, v]) =>
    h("tr", {}, h("td", {}, k.replace(/_/g, " ")), h("td", { class: typeof v === "number" ? "n" : "" },
      typeof v === "number" ? (Math.abs(v) >= 100 ? I18N.num(v) : D(String(v))) : D(Array.isArray(v) ? v.join(", ") : typeof v === "object" && v ? JSON.stringify(v) : String(v)))));
  const meaning = state.overview && state.overview.badges[metric.badge];
  const drawer = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": t("inspect") },
    h("button", { class: "btn secondary close", onClick: closeDrawer }, t("close")),
    h("div", { class: "muted small" }, t("inspect")),
    h("h3", {}, pick(metric, "label")),
    h("div", { class: "value" }, formatMetricValue(metric)),
    h("div", {}, badge(metric.badge), " ", h("span", { class: "muted small" }, meaning ? meaning[I18N.lang] : "")),
    h("div", { class: "receipt" },
      h("dl", {},
        h("dt", {}, t("formula")), h("dd", {}, h("div", { class: "formula" }, metric.formula || "–")),
        metric.worked ? [h("dt", {}, t("worked")), h("dd", {}, h("div", { class: "formula" }, D(metric.worked)))] : null,
        inputs.length ? [h("dt", {}, t("inputs")), h("dd", {}, h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {}, inputs))))] : null,
        h("dt", {}, t("source")), h("dd", {}, metric.source || "–"),
        pick(metric, "note") ? [h("dt", {}, t("note")), h("dd", {}, D(pick(metric, "note")))] : null)));
  document.body.append(back, drawer);
  drawer.querySelector(".close").focus();
}
function closeDrawer() { document.querySelectorAll(".drawer, .drawer-back").forEach((n) => n.remove()); }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

function ins(metric, text) {
  if (!metric) return h("span", {}, text || "–");
  return h("button", { class: "ins", type: "button", title: t("inspect"), onClick: () => inspect(metric) }, text || formatMetricValue(metric));
}

/* ------------------------------------------------------------- header */
function renderHeader() {
  const o = state.overview;
  document.documentElement.lang = I18N.lang;
  document.getElementById("school").textContent = o ? (I18N.lang === "bn" ? o.meta.school_name_bn : o.meta.school_name_en) : "";
  const controls = document.getElementById("controls");
  controls.replaceChildren();
  if (!o) return;
  const ai = o.agent.mode === "gemini";
  const items = [
    h("span", { class: "chip clock", id: "live-clock", title: "Current date and time · Asia/Dhaka" }, formatDhakaNow()),
    h("span", { class: "chip " + (o.meta?.dataset_label === "EMPTY_WORKSPACE" ? "" : "synthetic"), title: pick(o.meta, "notice") },
      o.meta?.dataset_label === "EMPTY_WORKSPACE" ? t("freshWorkspace") : t("synthetic")),
    h("span", { class: "chip " + (ai ? "mode-ai" : "mode-rule"), title: ai ? t("modeAiHelp") : t("modeRuleHelp") },
      ai ? `${t("modeAi")}: ${o.agent.model}` : t("modeRule")),
    h("div", { class: "seg", role: "group", "aria-label": t("language") },
      h("button", { "aria-pressed": String(I18N.lang === "en"), onClick: () => setLang("en") }, "English"),
      h("button", { "aria-pressed": String(I18N.lang === "bn"), onClick: () => setLang("bn") }, "বাংলা")),
    I18N.lang === "bn" ? h("div", { class: "seg", role: "group", "aria-label": t("digits") },
      h("button", { "aria-pressed": String(I18N.digits === "bn"), onClick: () => setDigits("bn") }, "১২৩"),
      h("button", { "aria-pressed": String(I18N.digits === "latin"), onClick: () => setDigits("latin") }, "123")) : null,
    h("button", { class: "chip", title: state.session ? state.session.email : "", onClick: openRoleDialog }, `${state.session?.full_name || ""} · ${t(o.role || "owner")}`),
    h("button", { class: "chip", onClick: openSettings }, t("settings")),
    h("button", { class: "chip", onClick: logout }, I18N.lang === "bn" ? "লগআউট" : "Log out")];
  controls.append(...items.filter(Boolean));
}

function renderNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  const current = currentTab();
  const role = state.session?.role || "guest";
  const visibleTabs = role === "agent" ? ["records"] : role === "owner" ? TABS : TABS.filter((tab) => !["team", "security"].includes(tab));
  for (const tab of visibleTabs) {
    const count = tab === "approvals" && state.overview ? state.overview.pending_count : 0;
    const label = tab === "team" ? (I18N.lang === "bn" ? "দল ও অ্যাকাউন্ট" : "Team & Access") : t("tabs." + tab);
    nav.appendChild(h("a", { href: "#" + tab, "aria-current": tab === current ? "page" : null },
      h("span", {}, label), count ? h("span", { class: "badge-count", "aria-label": "pending" }, I18N.num(count)) : null));
  }
}

function setLang(lang) { I18N.lang = lang; savePref("lang", lang); rerender(); }
function setDigits(d) { I18N.digits = d; savePref("digits", d); rerender(); }
function currentTab() {
  const tab = location.hash.replace("#", "");
  const role = state.session?.role || "guest";
  if (role === "agent") return "records";
  if (tab === "team" && role !== "owner") return "home";
  return TABS.includes(tab) ? tab : "home";
}

/* --------------------------------------------------------------- pages */
async function refreshOverview() {
  const { data } = await api("/api/overview");
  state.overview = data;
}

function page(id) {
  document.querySelectorAll(".page").forEach((p) => { p.hidden = p.id !== "page-" + id; });
  const node = document.getElementById("page-" + id);
  node.replaceChildren();
  return node;
}

function viewToggle(current, onChange) {
  return h("div", { class: "seg", role: "group", "aria-label": t("view") },
    h("button", { "aria-pressed": String(current === "plan"), onClick: () => onChange("plan") }, t("viewPlan")),
    h("button", { "aria-pressed": String(current === "baseline"), onClick: () => onChange("baseline") }, t("viewBaseline")));
}

function renderHome() {
  const o = state.overview;
  const root = page("home");
  if (o.meta?.dataset_label === "EMPTY_WORKSPACE") {
    const rs = o.record_summary || {};
    const bn = I18N.lang === "bn";
    root.append(
      h("section", { class: "welcome-hero" },
        h("div", { class: "eyebrow" }, bn ? "আপনার নিজস্ব ওয়ার্কস্পেস" : "YOUR PRIVATE WORKSPACE"),
        h("h1", {}, `${bn ? "স্বাগতম" : "Welcome to FinEdvise"}${o.meta.school_name_en ? `, ${o.meta.school_name_en}` : ""}`),
        h("p", { class: "lead" }, "Smarter Financial Decisions for Education."),
        h("p", {}, bn ? "এটি একটি নতুন ও আলাদা স্কুল ওয়ার্কস্পেস। এখানে অন্য স্কুলের শিক্ষার্থী, লেনদেন বা পূর্বাভাস কপি করা হয়নি। নিজের যাচাইকৃত তথ্য যোগ করার পরই প্রকৃত পরিকল্পনা তৈরি হবে।" : "This is a fresh, school-specific workspace. No other school's students, transactions or forecasts have been copied here. Add verified information first, and we'll help you build a useful plan."),
        h("div", { class: "welcome-actions" }, h("a", { class: "btn", href: "#records" }, bn ? "রেকর্ড যোগ করুন" : "Set up school records"),
          h("a", { class: "btn secondary", href: "#extras" }, bn ? "স্কুল কার্যক্রম পরিকল্পনা" : "Plan a school activity"))),
      h("div", { class: "stats-grid" },
        h("section", { class: "stat-card" }, h("span", { class: "stat-label" }, bn ? "শিক্ষার্থী রেকর্ড" : "Student records"), h("strong", {}, I18N.num(rs.students?.active ?? 0)), h("span", { class: "muted small" }, bn ? "নিজের তালিকা যোগ করুন" : "Add your own roster")),
        h("section", { class: "stat-card" }, h("span", { class: "stat-label" }, bn ? "কর্মী রেকর্ড" : "Staff records"), h("strong", {}, I18N.num(rs.staff?.active ?? 0)), h("span", { class: "muted small" }, bn ? "শিক্ষক ও কর্মী যোগ করুন" : "Add teachers and staff")),
        h("section", { class: "stat-card" }, h("span", { class: "stat-label" }, bn ? "আয় এন্ট্রি" : "Income entries"), h("strong", {}, I18N.num(rs.income?.count ?? 0)), h("span", { class: "muted small" }, bn ? "ফি ও অন্যান্য আয় রেকর্ড করুন" : "Record fees and other receipts")),
        h("section", { class: "stat-card" }, h("span", { class: "stat-label" }, bn ? "ব্যয় এন্ট্রি" : "Expense entries"), h("strong", {}, I18N.num(rs.expenses?.count ?? 0)), h("span", { class: "muted small" }, bn ? "পেইড ও বকেয়া আলাদা রাখুন" : "Separate paid and unpaid costs"))),
      h("section", { class: "sheet setup-card" }, h("h2", {}, bn ? "শুরু করার সেরা পথ" : "A good place to start"),
        h("div", { class: "setup-steps" },
          ...(bn ? [
            ["01", "শিক্ষার্থী ও ফি নীতি যোগ করুন", "শ্রেণি, মাসিক ফি ও ভর্তি-অবস্থা লিখুন।"],
            ["02", "শিক্ষক-কর্মী ও বেতনের তথ্য যোগ করুন", "অনুমোদিত রেকর্ড ব্যবহার করুন এবং বেতনের অঙ্ক যাচাই করুন।"],
            ["03", "প্রারম্ভিক নগদ, ব্যাংক ও খরচ দিন", "মূল অনুমান যাচাই না হওয়া পর্যন্ত পূর্বাভাস দেখানো হবে না।"],
            ["04", "আয় ও ব্যয় রেকর্ড করুন", "প্রাপ্ত নগদ ও বকেয়া দায় আলাদা রাখুন।"]
          ] : [
            ["01", "Add students and fee policies", "Record class, monthly fee and enrollment status."],
            ["02", "Add staff and payroll details", "Use authorized records and confirm salary figures."],
            ["03", "Enter opening cash, bank and costs", "Forecasts stay disabled until core assumptions are verified."],
            ["04", "Record income and expenses", "Keep unpaid obligations separate from cash received."]
          ]).map(([n, title, copy]) => h("div", { class: "setup-step" }, h("span", { class: "step-number" }, n), h("div", {}, h("strong", {}, title), h("p", { class: "muted small" }, copy))))),
        h("p", { class: "note warn" }, bn ? "নিরাপদ আর্থিক পূর্বাভাসের জন্য আগে প্রকৃত তথ্য কনফিগার করতে হবে।" : "Financial forecasts are intentionally not shown until your real school assumptions are configured.")),
      h("p", { class: "muted small live-time" }, `${bn ? "বাংলাদেশের বর্তমান সময়" : "Current Bangladesh time"}: ${formatDhakaNow()} · ${bn ? "টাইম জোন" : "Time zone"}: Asia/Dhaka`));
    return;
  }
  const weeks = o.horizon.weeks;
  const stressWhat = I18N.lang === "bn" ? o.stress.label.bn.replace(/^স্ট্রেস টেস্ট: /, "") : o.stress.label.en.replace(/^Stress test: /, "");
  root.append(
    h("section", { class: "hero" },
      h("div", { class: "when" }, `${I18N.lang === "bn" ? "বাংলাদেশের বর্তমান সময়" : "Current Bangladesh time"}: ${formatDhakaNow()} · ${I18N.lang === "bn" ? "সিন্থেটিক ডেমো দৃশ্যপটের তারিখ" : "Demo scenario baseline"}: ${I18N.date(o.meta.scenario_date)}`),
      h("h1", {}, t("safeToday")),
      h("div", { class: "hero-figure" }, ins(o.metrics.sti_base)),
      h("p", { class: "hero-sub" }, t("safeSub", { weeks: I18N.num(weeks) })),
      h("p", { class: "hero-stress" }, t("stressLine", { what: stressWhat, amount: "" }).replace(/।$|\.$/, ""), " ",
        h("strong", {}, ins(o.metrics.sti_stress)), I18N.lang === "bn" ? "।" : "."),
      o.commitments_total ? h("p", { class: "muted" }, `${t("approvedSpend")}: ${M(o.commitments_total)}`) : null,
      h("div", { class: "pinch" + (o.pinch.sti_base > 0 ? "" : " calm") },
        h("strong", {}, t("pinchHead")), h("br"), D(pick(o.pinch, "message")))));

  const chartBox = h("div", { class: "chart-wrap" });
  const rows = o.weeks[state.homeView];
  root.append(h("section", { class: "sheet" },
    h("div", { class: "row", style: "justify-content:space-between;align-items:baseline" },
      h("h2", {}, t("weeksHead", { weeks: I18N.num(weeks) })),
      viewToggle(state.homeView, (v) => { state.homeView = v; renderHome(); })),
    h("p", { class: "lead small" }, t("weeksLead")),
    chartBox,
    h("div", { class: "legend" }, h("span", { class: "l-bar" }, t("legendBar")), h("span", { class: "l-low" }, t("legendLow")),
      h("span", { class: "l-stress" }, t("legendStress")), h("span", { class: "l-reserve" }, t("legendReserve")))));
  drawCashChart(chartBox, rows.base, rows.stress, o.metrics.reserve.value, { ariaLabel: t("weeksHead", { weeks }) });

  const alerts = o.alerts;
  const pos = o.position;
  root.append(h("div", { class: "split" },
    h("section", { class: "sheet" },
      h("h2", {}, t("alertsHead")),
      alerts.length ? h("ul", { class: "alerts" }, alerts.map((a) => h("li", { class: a.severity },
        h("span", { class: "tag" }, a.scenario === "stress" ? t("stress") : t("base")), D(pick(a, "message")))))
        : h("p", { class: "empty" }, t("alertsNone"))),
    h("section", { class: "sheet" },
      h("h2", {}, t("positionHead")),
      h("div", { class: "facts" },
        fact(t("cashNow"), ins(o.metrics.opening_cash), t("cashBreak", { a: M(pos.cash_in_hand), b: M(pos.bank), c: M(pos.bkash_available) }), o.metrics.opening_cash.badge),
        fact(t("pending"), M(pos.bkash_pending.amount), t("pendingNote", { date: I18N.dayMonth(pos.bkash_pending.expected_date) })),
        fact(t("dues"), ins(o.metrics.outstanding), t("duesNote"), "VERIFIED"),
        fact(t("reserve"), ins(o.metrics.reserve), o.reserve_status === "PROPOSED_DEFAULT" ? t("reserveNote") : t("reserveSet"), "ASSUMED"),
        fact(t("tuitionBilled"), ins(o.metrics.billable_tuition), pick(o.metrics.billable_tuition, "note"), "VERIFIED")))));

  root.append(renderAskBox(o));
  const hist = o.history;
  root.append(h("section", { class: "sheet" }, h("h2", {}, t("learnHead")),
    h("p", { class: "lead" }, t("learnText", { f: I18N.num(hist.forecast_extra_admissions), a: I18N.num(hist.actual_extra_admissions),
      fr: I18N.num(hist.forecast_collection_rate, 2), ar: I18N.num(hist.actual_collection_rate, 2),
      now: I18N.num(o.economics.net_contribution.inputs.collection_rate, 2) })),
    h("p", { class: "muted small" }, D(pick(hist, "update")))));

  const rs = o.record_summary;
  const bnHome = I18N.lang === "bn";
  if (rs) root.append(h("section", { class: "sheet" }, h("h2", {}, bnHome ? "আপনার রেকর্ড করা লেনদেন" : "Transactions entered for your school"),
    h("p", { class: "muted small" }, bnHome
      ? "আপনার যোগ বা সম্পাদনা করা আয় ও ব্যয়ের রেকর্ড থেকে এই অংশটি হালনাগাদ হয়। এটি ওপরের সিন্থেটিক ক্যাশ-ফ্লো পূর্বাভাস থেকে আলাদা।"
      : "This section updates from the income and expense records you add or edit. It is separate from the synthetic cash-flow scenario shown above."),
    h("div", { class: "facts" },
      h("div", { class: "fact" }, h("div", { class: "k" }, bnHome ? "পরিশোধিত আয় (Paid)" : "Income marked paid"), h("div", { class: "v" }, M(rs.income.paid)), h("div", { class: "n" }, D(`${I18N.num(rs.income.count)} ${bnHome ? "টি এন্ট্রি" : "entries"}`))),
      h("div", { class: "fact" }, h("div", { class: "k" }, bnHome ? "পরিশোধিত ব্যয় (Paid)" : "Expenses marked paid"), h("div", { class: "v" }, M(rs.expenses.paid)), h("div", { class: "n" }, D(`${I18N.num(rs.expenses.count)} ${bnHome ? "টি এন্ট্রি" : "entries"}`))),
      h("div", { class: "fact" }, h("div", { class: "k" }, bnHome ? "অপরিশোধিত বা পরিকল্পিত আয়" : "Income not marked paid"), h("div", { class: "v" }, M(rs.income.unpaid_or_planned + rs.income.partial)), h("div", { class: "n" }, bnHome ? `বাকি ${M(rs.income.unpaid_or_planned)} · আংশিক ${M(rs.income.partial)}` : `Pending ${M(rs.income.unpaid_or_planned)} · Partial ${M(rs.income.partial)}`)),
      h("div", { class: "fact" }, h("div", { class: "k" }, bnHome ? "অপরিশোধিত বা পরিকল্পিত ব্যয়" : "Expenses not marked paid"), h("div", { class: "v" }, M(rs.expenses.unpaid_or_planned + rs.expenses.partial)), h("div", { class: "n" }, bnHome ? `বাকি ${M(rs.expenses.unpaid_or_planned)} · আংশিক ${M(rs.expenses.partial)}` : `Pending ${M(rs.expenses.unpaid_or_planned)} · Partial ${M(rs.expenses.partial)}`))),
    h("p", { class: "note warn" }, bnHome
      ? "শুধুমাত্র 'paid' চিহ্নিত রেকর্ডগুলো নগদ আদায় বা পরিশোধ হিসেবে গণ্য হয়। আংশিক (partial) এন্ট্রির ক্ষেত্রে পরিশোধিত অংশ আলাদাভাবে রেকর্ড করুন।"
      : "Only records marked paid count as cash received or paid. For partial entries, record the paid portion separately before using these totals as reconciled cash.")));
}

function fact(label, value, note, badgeName) {
  return h("div", { class: "fact" }, h("div", { class: "k" }, label, badgeName ? [" ", badge(badgeName)] : null),
    h("div", { class: "v" }, value), note ? h("div", { class: "n" }, D(note)) : null);
}

function renderAskBox(o) {
  const q = o.next_question;
  if (!q) return null;
  const box = h("section", { class: "sheet" }, h("h2", {}, t("askHead")), h("p", { class: "muted small" }, t("askLead")),
    h("p", { style: "font-size:18px" }, D(I18N.lang === "bn" ? q.q_bn : q.q_en)));
  const actions = h("div", { class: "btn-row" });
  if (q.id === "Q_RESERVE") {
    actions.append(
      h("button", { class: "btn good", onClick: async () => {
        const { status, data } = await api("/api/settings/reserve", { amount: o.metrics.reserve.value });
        if (status === 403) return toast(t("deniedToast", { reason: pick(data.decision, "reason") }));
        await refreshOverview(); rerender();
      } }, `${I18N.lang === "bn" ? "রাখুন" : "Keep"} ${M(o.metrics.reserve.value)}`),
      h("button", { class: "btn secondary", onClick: openSettings }, I18N.lang === "bn" ? "বদলান" : "Change it"));
  } else if (q.where === "financing") {
    actions.append(h("button", { class: "btn secondary", onClick: () => { location.hash = "financing"; } }, t("tabs.financing")));
  } else {
    const input = h("input", { type: "text", maxlength: "300", "aria-label": q.question, style: "flex:1;min-width:220px" });
    actions.append(input, h("button", { class: "btn", onClick: async () => {
      if (!input.value.trim()) return;
      const { status, data } = await api("/api/financing/answer", { question_id: q.id, value: input.value.trim() });
      if (status === 403) return toast(t("deniedToast", { reason: pick(data.decision, "reason") }));
      await refreshOverview(); rerender();
    } }, t("save")));
  }
  box.append(actions);
  return box;
}

/* ------------------------------------------------------------- planner */
const SHOCKS = {
  enrol: { enrolment_drop_pct: 0.15 }, delay1: { fee_delay_weeks: 1 }, delay2: { fee_delay_weeks: 2 },
  cost: { cost_increase_pct: 0.10 }, emergency: { emergency_cost: 15000, emergency_week: 1 }, closure: { closure_week: 3 },
};
let simTimer = null;

function shockPayload() {
  const out = {};
  for (const key of state.plan.shocks) Object.assign(out, SHOCKS[key]);
  return Object.keys(out).length ? out : null;
}

async function renderPlan() {
  const o = state.overview;
  const root = page("plan");
  root.append(h("h1", {}, t("planHead")), h("p", { class: "lead" }, t("planLead")));
  if (o.meta?.dataset_label === "EMPTY_WORKSPACE") {
    root.append(h("section", { class: "sheet setup-card" }, h("h2", {}, I18N.lang === "bn" ? "আপনার স্কুলের পরিকল্পনা শুরু করুন" : "Let's build your school's plan"),
      h("p", {}, I18N.lang === "bn" ? "এখানে কোনো ডেমো ব্যালেন্স ব্যবহার করা হচ্ছে না। শুরু করার আগে আপনার প্রকৃত উদ্বোধনী ব্যালেন্স, ফি, মাসিক খরচ এবং রিজার্ভ লক্ষ্য যোগ করুন।" : "No demo balances are being used here. Before running scenarios, add your real opening balances, fee rules, monthly costs and reserve target."),
      h("a", { class: "btn", href: "#records" }, I18N.lang === "bn" ? "স্কুলের রেকর্ড সেটআপ করুন" : "Set up school records")));
    return;
  }
  const amountText = h("span", { class: "amount" }, M(state.plan.amount));
  const slider = h("input", { type: "range", min: "0", max: "150000", step: "1000", value: String(state.plan.amount), "aria-label": t("amountLabel") });
  const number = h("input", { type: "number", min: "0", max: "10000000", step: "1000", value: String(state.plan.amount), style: "width:140px", "aria-label": t("amountLabel") });
  const sync = (v) => { state.plan.amount = Math.max(0, Math.min(10000000, Number(v) || 0)); amountText.textContent = M(state.plan.amount); slider.value = String(Math.min(150000, state.plan.amount)); number.value = String(state.plan.amount); scheduleSim(); };
  slider.addEventListener("input", () => sync(slider.value));
  number.addEventListener("change", () => sync(number.value));
  const weekSel = h("select", { "aria-label": t("weekLabel"), onChange: (e) => { state.plan.week = Number(e.target.value); scheduleSim(); } },
    o.weeks.plan.base.map((r) => h("option", { value: String(r.index), selected: r.index === state.plan.week ? "selected" : null },
      `${t("weekN", { n: r.index })}: ${I18N.range(r.start, r.end)}`)));
  const toggles = h("div", { class: "toggles" }, Object.keys(SHOCKS).map((key) => h("button", { class: "toggle", type: "button",
    "aria-pressed": String(state.plan.shocks.has(key)), onClick: (e) => {
      if (state.plan.shocks.has(key)) state.plan.shocks.delete(key); else {
        state.plan.shocks.add(key);
        if (key === "delay1") state.plan.shocks.delete("delay2");
        if (key === "delay2") state.plan.shocks.delete("delay1");
      }
      renderPlan();
    } }, t("shock_" + key))));
  root.append(h("section", { class: "sheet" },
    h("div", { class: "row" },
      h("div", { class: "col" }, h("div", { class: "field" }, h("label", {}, t("amountLabel")),
        h("div", { class: "amount-line" }, amountText, number), slider)),
      h("div", { class: "col" }, h("div", { class: "field" }, h("label", {}, t("weekLabel")), weekSel),
        h("div", { class: "field" }, h("label", {}, t("view")), viewToggle(state.plan.view, (v) => { state.plan.view = v; renderPlan(); })))),
    h("h3", { style: "margin-top:10px" }, t("shocksHead")), h("p", { class: "muted small" }, t("shocksLead")), toggles),
    h("div", { id: "sim-out" }, h("p", { class: "muted" }, t("loading"))),
    h("div", { id: "plans-out" }));
  runSim();
  renderPlansTable();
}

function scheduleSim() { clearTimeout(simTimer); simTimer = setTimeout(runSim, 220); }

async function runSim() {
  const out = document.getElementById("sim-out");
  if (!out) return;
  try {
    const { data } = await api("/api/simulate", { amount: state.plan.amount, spend_week: state.plan.week, shocks: shockPayload(), view: state.plan.view });
    renderSimResult(out, data);
  } catch (err) {
    out.replaceChildren(h("p", { class: "note bad" }, t("errorGeneric", { msg: err.message })));
  }
}

function verdictCol(label, block, safe, gap, amount) {
  const cls = amount === 0 ? "ok" : safe ? "ok" : (block.summary.max_cash_shortfall > 0 ? "bad" : "warn");
  const problems = block.alerts;
  return h("div", { class: "verdict " + cls },
    h("div", { class: "head" }, label, block.shock_text && label === t("stress") ? D(`: ${block.shock_text[I18N.lang].join(", ")}`) : ""),
    h("div", {}, t("safeLimit"), ": ", h("span", { class: "big" }, ins(block.sti_metric))),
    amount ? h("p", { style: "margin:6px 0" }, h("strong", {}, safe ? t("verdictSafe") : t("verdictUnsafe")), safe ? "" : ` (${t("gapBy", { gap: M(gap) })})`) : null,
    problems.length ? h("ul", { class: "alerts" }, problems.map((a) => h("li", { class: a.severity }, D(pick(a, "message")))))
      : h("p", { class: "muted small" }, t("noProblems")));
}

function renderSimResult(out, sim) {
  out.replaceChildren();
  const amount = sim.amount;
  out.append(h("div", { class: "verdicts" },
    verdictCol(t("base"), sim.base, sim.safe_in_base, sim.gap_base, amount),
    verdictCol(t("stress"), sim.stress, sim.safe_in_stress, sim.gap_stress, amount)));
  if (sim.stress.carried_total) {
    out.append(h("p", { class: "muted small" }, t("afterWindow", { amount: M(sim.stress.carried_total), weeks: I18N.num(sim.base.rows.length) })));
  }
  const chartBox = h("div", { class: "chart-wrap" });
  out.append(h("section", { class: "sheet" }, chartBox,
    h("div", { class: "legend" }, h("span", { class: "l-bar" }, t("legendBar")), h("span", { class: "l-low" }, t("legendLow")),
      h("span", { class: "l-stress" }, t("legendStress")), h("span", { class: "l-reserve" }, t("legendReserve")))));
  drawCashChart(chartBox, sim.base.rows, sim.stress.rows, sim.reserve, { ariaLabel: t("weekTable") });

  const head = h("tr", {}, ["th_week", "th_dates", "th_in", "th_out", "th_spend", "th_low", "th_close", "th_status"].map((k, i) =>
    h("th", { class: i >= 2 && i <= 6 ? "n" : "" }, t(k))), h("th", { class: "n" }, `${t("stress")}: ${t("th_close")}`), h("th", {}, `${t("stress")}: ${t("th_status")}`));
  const body = sim.base.rows.map((r, i) => {
    const s = sim.stress.rows[i];
    return h("tr", {}, h("td", { class: "nowrap" }, I18N.weekLabel(r.label)), h("td", { class: "nowrap" }, I18N.shortRange(r.start, r.end)),
      h("td", { class: "n" }, M(r.receipts)), h("td", { class: "n" }, M(r.payments + r.committed)), h("td", { class: "n" }, r.spend ? M(r.spend) : "–"),
      h("td", { class: "n" }, M(r.low_point)), h("td", { class: "n" }, M(r.closing)), h("td", {}, statusChip(r.status)),
      h("td", { class: "n" }, M(s.closing)), h("td", {}, statusChip(s.status)));
  });
  out.append(h("section", { class: "sheet" }, h("h2", {}, t("weekTable")), h("div", { class: "table-wrap" }, h("table", { class: "compact" }, h("thead", {}, head), h("tbody", {}, body)))));

  if (sim.break_even) {
    const be = sim.break_even;
    out.append(h("section", { class: "sheet" }, h("h2", {}, t("beHead")),
      h("div", { class: "facts" },
        fact(t("beEcon"), ins(be.economic_break_even), null, "SIMULATED"),
        fact(t("beCash"), ins(be.cash_payback), null, "SIMULATED")),
      h("p", { class: "lead" }, beWhy(be))));
  }
}

function beWhy(be) {
  const nc = be.economics.net_contribution, wc = be.economics.window_cash;
  const parts = t("beWhy", { nc: "\u0000", wc: "\u0001" }).split(/[\u0000\u0001]/);
  return h("span", {}, parts[0], ins(nc), parts[1], ins(wc), parts[2] || "");
}

async function renderPlansTable() {
  const out = document.getElementById("plans-out");
  if (!out) return;
  const { data } = await api("/api/plans");
  state.plans = data;
  const rec = data.plans.find((p) => p.id === data.recommended_plan_id);
  const ok = (summary) => statusChip(summary.ok ? "OK" : summary.max_cash_shortfall > 0 ? "CASH_SHORTFALL" : "RESERVE_BREACH");
  const pair = (L) => h("div", { class: "stack" }, h("span", {}, h("span", { class: "muted tiny" }, t("base") + " "), ok(L.base)),
    h("span", {}, h("span", { class: "muted tiny" }, t("stress") + " "), ok(L.stress)));
  const rows = data.plans.map((p) => {
    const L = p.lump_sum, S = p.staged;
    const est = L.extra_students_estimate;
    return h("tr", { class: p.id === data.recommended_plan_id ? "rec" : "" },
      h("td", {}, h("strong", {}, I18N.lang === "bn" ? L.name_bn : L.name_en), h("div", { class: "num" }, M(L.total)),
        p.id === data.recommended_plan_id ? h("span", { class: "badge VERIFIED" }, t("recommended")) : null),
      h("td", { class: "n" }, D(`${est.downside} / ${est.base} / ${est.upside}`), h("div", {}, badge("ASSUMED"))),
      h("td", { class: "n" }, M(L.gains.base)),
      h("td", { class: "n" }, ins(L.break_even.economic_break_even, I18N.num(L.economic_break_even)), " / ", ins(L.break_even.cash_payback, I18N.num(L.cash_payback_students))),
      h("td", {}, pair(L)),
      h("td", {}, pair(S), S.staging_cost ? h("div", { class: "muted tiny" }, `${t("th_cost")} ${M(S.staging_cost)}`) : null),
      h("td", {}, h("button", { class: "btn secondary", onClick: () => draftPlan(p.id, true) }, I18N.lang === "bn" ? "খসড়া (ধাপে)" : "Draft in stages")));
  });
  const children = [
    h("h2", {}, t("plansHead")), h("p", { class: "muted small" }, t("plansLead")),
    data.commitments_total > 0 ? h("p", { class: "note" }, t("onTopOf", { amount: M(data.commitments_total) })) : null,
    h("div", { class: "table-wrap" }, h("table", { class: "compact" }, h("thead", {}, h("tr", {},
      h("th", {}, t("th_plan")), h("th", { class: "n" }, t("th_students")), h("th", { class: "n" }, t("th_gain")),
      h("th", { class: "n" }, `${t("th_be")} / ${t("th_cashpb")}`), h("th", {}, t("th_paynow")), h("th", {}, t("th_staged")), h("th", {}))),
      h("tbody", {}, rows))),
    h("h3", { style: "margin-top:16px" }, t("whyHead")), h("p", { class: "lead" }, D(data.reason[I18N.lang])),
  ];
  if (rec) {
    const S = rec.staged;
    children.push(h("h3", { style: "margin-top:16px" }, t("stagedHead")), h("p", { class: "muted small" }, t("stagedLead")),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("th_item")), h("th", {}, t("th_paywk")), h("th", { class: "n" }, t("th_amount")), h("th", { class: "n" }, t("th_cost")))),
        h("tbody", {}, S.schedule.map((i) => h("tr", {}, h("td", {}, I18N.lang === "bn" ? i.label_bn : i.label_en),
          h("td", {}, t("weekN", { n: i.pay_week })), h("td", { class: "n" }, M(i.amount)), h("td", { class: "n" }, i.staging_cost ? M(i.staging_cost) : "–")))))),
      h("p", {}, `${t("base")}: `, ok(S.base), "  ", `${t("stress")}: `, ok(S.stress)),
      h("div", { class: "btn-row" }, h("button", { class: "btn good", onClick: () => draftPlan(rec.id, true) }, t("useStaged")),
        h("button", { class: "btn secondary", onClick: () => draftPlan(rec.id, false) }, t("usePaid"))));
  }
  out.replaceChildren(h("section", { class: "sheet" }, children));
}

async function draftPlan(planId, staged) {
  const { status, data } = await api("/api/proposals", { plan_id: planId, staged });
  if (status === 403 || !data.proposal) return toast(t("deniedToast", { reason: pick(data.decision, "reason") }));
  toast(t("draftCreated", { id: data.proposal.id }));
  await refreshOverview(); renderNav();
}

/* ------------------------------------------------------------- copilot */
function renderCopilot() {
  const o = state.overview;
  const root = page("copilot");
  const ai = o.agent.mode === "gemini";
  const log = h("div", { class: "log", id: "chat-log", "aria-live": "polite" });
  state.chat.forEach((m) => log.appendChild(renderMessage(m)));
  if (!state.chat.length) log.appendChild(h("p", { class: "empty" }, t("chatEmpty")));
  const input = h("textarea", { id: "chat-input", rows: "2", placeholder: t("placeholder"), "aria-label": t("placeholder"), maxlength: "2000" });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(input.value); } });
  root.append(
    h("h1", {}, t("copilotHead")),
    h("p", { class: "lead" }, t("copilotLead")),
    h("p", { class: "small" }, h("span", { class: "chip " + (ai ? "mode-ai" : "mode-rule") }, ai ? `${t("modeAi")}: ${o.agent.model}` : t("modeRule")), " ",
      h("span", { class: "muted" }, ai ? t("modeAiHelp") : t("modeRuleHelp"))),
    h("div", { class: "chat" },
      h("div", { class: "suggestions" }, t("suggestions").map((s) => h("button", { type: "button", onClick: () => sendChat(s) }, D(s)))),
      log,
      h("div", { class: "composer" }, input, h("button", { class: "btn", onClick: () => sendChat(input.value) }, t("send")))));
  log.lastElementChild && log.lastElementChild.scrollIntoView({ block: "end" });
}

async function sendChat(text) {
  text = (text || "").trim();
  if (!text || state.busy) return;
  state.busy = true;
  state.chat.push({ role: "user", text });
  const input = document.getElementById("chat-input");
  if (input) input.value = "";
  const log = document.getElementById("chat-log");
  if (log) {
    log.appendChild(renderMessage({ role: "user", text }));
    log.appendChild(h("div", { class: "msg bot typing", id: "typing" }, t("thinking")));
    log.lastElementChild.scrollIntoView({ block: "end" });
  }
  try {
    const { data } = await api("/api/chat", { message: text, lang: I18N.lang });
    state.chat.push({ role: "bot", data });
    if (data.proposals && data.proposals.length) { await refreshOverview(); renderNav(); }
  } catch (err) {
    state.chat.push({ role: "bot", data: { reply: t("errorGeneric", { msg: err.message }), tool_calls: [], guardrail: {} } });
  }
  state.busy = false;
  if (currentTab() === "copilot") renderCopilot();
}

function renderMessage(m) {
  if (m.role === "user") return h("div", { class: "msg user" }, m.text);
  const d = m.data;
  const g = d.guardrail || {};
  const meta = h("div", { class: "meta" });
  const fbWhy = d.fallback_reason === "guardrail" ? t("fbGuard") : d.fallback_reason ? t("fbModel") : "";
  if (d.mode) {
    const specialMode = {
      current_time: I18N.lang === "bn" ? "বাংলাদেশের বর্তমান সময়" : "Current Bangladesh time",
      occasion_guidance: I18N.lang === "bn" ? "স্কুল কার্যক্রম নির্দেশিকা" : "School activity guide",
      workspace_setup: I18N.lang === "bn" ? "ওয়ার্কস্পেস সেটআপ সহায়তা" : "Workspace setup guide",
    };
    meta.append(h("span", { title: d.fallback_reason || "" }, d.mode === "gemini" ? `${t("modeAi")}: ${d.model}`
      : d.mode === "rule_based_fallback" ? `${t("fallback")}${fbWhy ? ` (${fbWhy})` : ""}`
      : specialMode[d.mode] || t("modeRule")));
  }
  if (g.passed !== undefined) {
    const n = g.numbers_checked || 0;
    meta.append(h("span", { class: "guard " + (g.passed ? "pass" : "fail") },
      g.passed ? (n ? `✓ ${t("numbersChecked", { n: I18N.num(n) })}` : t("numbersNone")) : `✗ ${t("guardBlocked", { list: (g.unverified || []).map((u) => u.text).join(", ") })}`));
    if (g.action === "repaired") meta.append(h("span", {}, t("guardRepaired")));
    if (g.action === "fell_back") meta.append(h("span", {}, t("guardFell")));
  }
  const calls = d.tool_calls || [];
  const trace = h("details", { class: "trace" }, h("summary", {}, t("howGot", { n: I18N.num(calls.length) })),
    calls.length ? h("ol", {}, calls.map((c) => h("li", {},
      h("code", {}, `${c.name}(${c.args && Object.keys(c.args).length ? JSON.stringify(c.args) : ""})`), " ",
      h("span", { class: "status " + (c.decision === "ALLOW" ? "ok" : c.decision === "DENY" ? "bad" : "warn") }, `${t("decision")}: ${c.decision || (c.ok ? "ALLOW" : "–")}${c.tier ? " · " + c.tier : ""}`),
      c.result_hash ? h("span", { class: "hash" }, `  #${c.result_hash}`) : null,
      c.error ? h("div", { class: "muted" }, c.error) : null))) : h("p", { class: "muted" }, t("noTools")),
    (g.checked || []).length ? h("p", { class: "small" }, (g.checked || []).map((c) => `${c.text} ${c.verified ? "✓" : "✗"}`).join("   ")) : null);
  const reminders = (d.reminders || []).map((r) => h("div", { class: "draft-card" },
    h("div", { class: "tiny muted" }, t("reminderDraft")), D(r.text),
    h("div", { class: "btn-row" }, h("button", { class: "btn secondary", onClick: async (e) => {
      try { await navigator.clipboard.writeText(D(r.text)); e.target.textContent = t("copied"); } catch (err) { /* clipboard blocked */ }
    } }, t("copy")))));
  const proposals = (d.proposals || []).map((p) => h("p", {}, h("a", { href: "#approvals" }, `${p.id}: ${I18N.lang === "bn" ? p.title_bn : p.title_en} (${M(p.total)})`)));
  const sources = (d.web_sources || []).filter((src) => src.link && src.link.startsWith("https://")).map((src) => h("li", {},
    h("a", { href: src.link, target: "_blank", rel: "noopener noreferrer" }, src.title || src.source || src.link),
    src.source ? h("span", { class: "muted tiny" }, ` · ${src.source}`) : null,
    src.snippet ? h("p", { class: "muted small" }, src.snippet) : null));
  const researchStatus = d.web_research?.attempted && !sources.length ? h("p", { class: "muted tiny research-status" },
    d.web_research.configured ? (I18N.lang === "bn" ? "লাইভ অনুসন্ধান এখন উপলভ্য নয়; নিচের উত্তরটি সংরক্ষিত টুল/নির্দেশনার ভিত্তিতে।" : "Live research is temporarily unavailable; this answer uses the app's available tools and guidance.")
      : (I18N.lang === "bn" ? "লাইভ Google তথ্যসূত্র চালু করতে FINEDVISE_GOOGLE_CSE_API_KEY ও FINEDVISE_GOOGLE_CSE_CX কনফিগার করুন।" : "To enable live Google references, configure FINEDVISE_GOOGLE_CSE_API_KEY and FINEDVISE_GOOGLE_CSE_CX on the server.")) : null;
  return h("div", { class: "msg bot" }, D(d.reply || ""), proposals, reminders, researchStatus,
    sources.length ? h("details", { class: "web-sources", open: true }, h("summary", {}, I18N.lang === "bn" ? `তথ্যসূত্র (${sources.length})` : `References (${sources.length})`), h("ol", {}, sources)) : null, meta, trace);
}

/* ------------------------------------------------------------ financing */
async function renderFinancing() {
  const root = page("financing");
  root.append(h("h1", {}, t("financingHead")), h("p", { class: "lead" }, t("financingLead")));
  if (state.overview.meta?.dataset_label === "EMPTY_WORKSPACE") {
    root.append(h("section", { class: "sheet setup-card" }, h("h2", {}, I18N.lang === "bn" ? "অর্থায়ন মিলিয়ে দেখার আগে" : "Before comparing financing"),
      h("p", {}, I18N.lang === "bn" ? "অর্থায়নের পরামর্শ দেওয়ার জন্য স্কুলের প্রকৃত নগদ প্রবাহ, সম্ভাব্য ঘাটতি এবং যোগ্যতার তথ্য প্রয়োজন। আগে স্কুলের আর্থিক অনুমান যোগ করুন।" : "Responsible financing guidance needs your school's real cash-flow assumptions, the timing and size of any gap, and verified eligibility details."),
      h("a", { class: "btn", href: "#records" }, I18N.lang === "bn" ? "স্কুলের তথ্য যোগ করুন" : "Add school information")));
    return;
  }
  if (!state.plans) { const { data } = await api("/api/plans"); state.plans = data; }
  const planIds = state.plans.plans.map((p) => p.id);
  state.finPlan = state.finPlan || state.plans.recommended_plan_id || planIds[0];
  const sel = h("select", { onChange: (e) => { state.finPlan = e.target.value; renderFinancing(); } },
    state.plans.plans.map((p) => h("option", { value: p.id, selected: p.id === state.finPlan ? "selected" : null },
      `${I18N.lang === "bn" ? p.lump_sum.name_bn : p.lump_sum.name_en} (${M(p.lump_sum.total)})`)),
    h("option", { value: "CUSTOM", selected: state.finPlan === "CUSTOM" ? "selected" : null }, I18N.lang === "bn" ? "নিজস্ব পরিমাণ, এখনই খরচ" : "Custom amount spent now"));
  const amountInput = h("input", { type: "number", min: "1000", step: "1000", value: String(state.finAmount), style: "width:150px" });
  amountInput.addEventListener("change", () => { state.finAmount = Number(amountInput.value) || 0; renderFinancing(); });
  root.append(h("section", { class: "sheet" }, h("div", { class: "row" },
    h("div", { class: "field" }, h("label", {}, t("forPlan")), sel),
    state.finPlan === "CUSTOM" ? h("div", { class: "field" }, h("label", {}, t("th_amount")), amountInput) : null)));
  const body = state.finPlan === "CUSTOM" ? { amount: state.finAmount } : { plan_id: state.finPlan };
  const { data } = await api("/api/financing", body);
  state.financing = data;
  const f = data;
  root.append(h("section", { class: "sheet" },
    f.commitments_total > 0 ? h("p", { class: "note" }, t("onTopOf", { amount: M(f.commitments_total) })) : null,
    h("div", { class: "note " + (f.gap_if_paid_now <= 0 ? "good" : f.borrowing_needed ? "warn" : "good") }, D(f["verdict_" + I18N.lang])),
    h("div", { class: "facts", style: "margin-top:12px" },
      fact(t("gapNow"), M(f.gap_if_paid_now), D(f.stress_text[I18N.lang].join(", ")), "SIMULATED"),
      fact(t("gapAfter"), M(f.gap_after_fixes), f.staging_cost ? `${t("th_cost")}: ${M(f.staging_cost)}` : null, "SIMULATED")),
    f.operational_fixes.length ? [h("h3", { style: "margin-top:14px" }, t("fixesHead")),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("th_item")), h("th", { class: "n" }, t("th_amount")), h("th", {}, t("th_paywk")), h("th", { class: "n" }, t("th_cost")))),
        h("tbody", {}, f.operational_fixes.map((x) => h("tr", {}, h("td", {}, I18N.lang === "bn" ? x.label_bn : x.label_en, h("div", { class: "muted tiny" }, I18N.lang === "bn" ? x.note_bn : x.note_en)),
          h("td", { class: "n" }, M(x.amount)), h("td", {}, t("weekN", { n: x.pay_week })), h("td", { class: "n" }, x.cost ? M(x.cost) : "–"))))))] : null));

  const credit = h("section", { class: "sheet" }, h("h2", {}, t("creditHead")));
  let view = f;
  if (!f.borrowing_needed && f.gap_if_paid_now > 0) {
    const alt = await api("/api/financing", { ...body, without_fixes: true });
    view = alt.data;
    credit.append(h("p", { class: "note good" }, t("noBorrow"), " ", t("compareAnyway", { gap: M(view.gap_after_fixes) })));
  }
  if (!view.borrowing_needed) {
    credit.append(h("p", { class: "muted" }, t("noBorrow")));
  } else {
    credit.append(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["th_option", "th_amount", "th_apr", "th_totalcost", "th_arrives", "th_test", "th_elig", "th_source"].map((k, i) =>
      h("th", { class: i >= 1 && i <= 3 ? "n" : "" }, t(k))))),
      h("tbody", {}, view.credit_options.map((o) => h("tr", {},
        h("td", {}, I18N.lang === "bn" ? o.name_bn : o.name_en, h("div", {}, badge(o.rate_badge), " ", o.terms_badge !== o.rate_badge ? badge(o.terms_badge) : null)),
        h("td", { class: "n" }, M(o.principal), o.principal_note === "lender_minimum" ? h("div", { class: "muted tiny" }, t("lenderMin")) : null),
        h("td", { class: "n", title: `EAR ${o.cost.ear_pct}%` }, D(`${o.cost.apr_pct}%`)),
        h("td", { class: "n" }, M(o.cost.total_cost)),
        h("td", {}, I18N.dayMonth(o.arrives), h("div", { class: "tiny " + (o.arrives_in_time ? "muted" : "pill-fail") }, o.arrives_in_time ? t("weekN", { n: o.arrives_week }) : t("tooLate"))),
        h("td", {}, h("span", { class: o.passes_weakest_week_test ? "pill-pass" : "pill-fail" }, o.passes_weakest_week_test ? t("pass") : o.arrives_in_time ? t("fail") : t("tooLate")),
          o.fail_reason ? h("div", { class: "muted tiny" }, t("fr_" + o.fail_reason, { week: I18N.weekLabel(o.first_fail_week || "") })) : null),
        h("td", {}, t("elig_" + o.eligibility.status), o.eligibility.missing.length ? h("div", { class: "muted tiny" }, o.eligibility.missing.join(", ")) : null),
        h("td", {}, o.sources.map((s) => h("div", {}, h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title.split(" (")[0]), h("span", { class: "muted tiny" }, s.published ? ` ${s.published}` : ""))),
          h("button", { class: "btn secondary", style: "margin-top:4px", onClick: () => showChecklist(o.id) }, t("checklist")))))))));
    credit.append(h("p", { class: "muted tiny" }, t("sourcesChecked", { date: f.checked_on }), " ", D(f.catalogue_notice[I18N.lang])));
  }
  root.append(credit);

  const answers = f.profile || {};
  root.append(h("section", { class: "sheet" }, h("h2", {}, t("eligHead")), h("p", { class: "muted small" }, t("eligLead")),
    f.next_question ? h("p", { class: "note" }, D(f.next_question["q_" + I18N.lang])) : null,
    h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {}, f.questions.map((q) => {
      const current = answers[q.id] ? answers[q.id].value : null;
      const control = q.kind === "number"
        ? h("span", {}, h("input", { type: "number", min: "0", max: "600", value: current === null ? "" : String(current), style: "width:90px", id: "ans-" + q.id }),
            h("button", { class: "btn secondary", onClick: () => saveAnswer(q.id, Number(document.getElementById("ans-" + q.id).value)) }, t("save")))
        : h("div", { class: "seg" }, h("button", { "aria-pressed": String(current === true), onClick: () => saveAnswer(q.id, true) }, t("yes")),
            h("button", { "aria-pressed": String(current === false), onClick: () => saveAnswer(q.id, false) }, t("no")));
      const fromChat = answers[q.id] && answers[q.id].by === "agent";
      return h("tr", {}, h("td", {}, D(q["q_" + I18N.lang]), fromChat ? h("div", { class: "muted tiny" }, t("fromChat")) : null), h("td", {}, control));
    }))))));
}

async function saveAnswer(id, value) {
  const { status, data } = await api("/api/financing/answer", { question_id: id, value });
  if (status === 403) return toast(t("deniedToast", { reason: pick(data.decision, "reason") }));
  renderFinancing();
}

async function showChecklist(optionId) {
  const { data } = await api("/api/financing/checklist?option_id=" + encodeURIComponent(optionId));
  const dlg = h("dialog", {}, h("h3", {}, t("checklistHead")), h("p", {}, I18N.lang === "bn" ? data.name_bn : data.name_en),
    h("ul", { class: "plain" }, (I18N.lang === "bn" ? data.documents_bn : data.documents_en).map((d) => h("li", {}, d))),
    data.documents_source ? h("p", { class: "muted tiny" }, h("a", { href: data.documents_source.url, target: "_blank", rel: "noopener noreferrer" }, data.documents_source.title), ` (${data.documents_source.note || ""})`) : null,
    h("p", { class: "muted small" }, I18N.lang === "bn" ? data.note_bn : data.note_en),
    h("div", { class: "btn-row" }, h("button", { class: "btn", onClick: () => dlg.close() }, t("close"))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.appendChild(dlg);
  dlg.showModal();
}

/* ------------------------------------------------------------ approvals */
async function renderApprovals() {
  const root = page("approvals");
  root.append(h("h1", {}, t("approvalsHead")), h("p", { class: "lead" }, t("approvalsLead")));
  const { data } = await api("/api/proposals");
  state.proposals = data.proposals;
  if (!data.proposals.length) { root.append(h("p", { class: "empty sheet" }, t("noProposals"))); return; }
  for (const p of data.proposals) {
    const c = p.content;
    const title = I18N.lang === "bn" ? c.title_bn : c.title_en;
    root.append(h("article", { class: "proposal " + p.status },
      h("div", { class: "top" }, h("h3", {}, `${p.id}: ${title}`), h("strong", { style: "font-size:22px" }, M(c.total))),
      h("p", { class: "small" }, h("span", { class: "status " + (p.status === "approved" ? "ok" : p.status === "rejected" ? "bad" : "warn") }, t("st_" + p.status)),
        "  ", h("span", { class: "muted" }, t("createdBy", { who: t(p.created_by) }), `, ${p.created_utc.replace("T", " ").slice(0, 16)} UTC`)),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("th_item")), h("th", {}, t("th_paywk")), h("th", { class: "n" }, t("th_amount")), h("th", { class: "n" }, t("th_cost")))),
        h("tbody", {}, c.schedule.map((i) => h("tr", {}, h("td", {}, I18N.lang === "bn" ? i.label_bn : i.label_en), h("td", {}, `${t("weekN", { n: i.pay_week })}, ${I18N.dayMonth(i.pay_date)}`),
          h("td", { class: "n" }, M(i.amount)), h("td", { class: "n" }, i.staging_cost ? M(i.staging_cost) : "–")))))),
      h("p", { class: "small" }, `${t("checks")}: ${t("base")} `, statusChip(c.checks.base_ok ? "OK" : "RESERVE_BREACH"), `  ${t("stress")} `, statusChip(c.checks.stress_ok ? "OK" : "RESERVE_BREACH")),
      c.note ? h("p", { class: "muted small" }, `${t("note")}: `, c.note) : null,
      h("div", { class: "hash", title: p.content_hash }, `SHA-256 ${p.content_hash}`),
      h("div", { class: "btn-row" },
        p.status === "pending" ? [h("button", { class: "btn good", onClick: () => approve(p) }, t("approve")),
          h("button", { class: "btn danger", onClick: () => reject(p) }, t("reject"))] : null,
        h("a", { class: "btn secondary", href: `/api/proposals/${p.id}/memo?lang=${I18N.lang}`, target: "_blank", rel: "noopener" }, t("memo")))));
  }
}

function confirmDialog(title, text) {
  return new Promise((resolve) => {
    const dlg = h("dialog", {}, h("h3", {}, title), h("p", { class: "small hash" }, text),
      h("div", { class: "btn-row" }, h("button", { class: "btn good", onClick: () => { resolve(true); dlg.close(); } }, t("approve")),
        h("button", { class: "btn secondary", onClick: () => { resolve(false); dlg.close(); } }, t("cancel"))));
    dlg.addEventListener("close", () => { dlg.remove(); resolve(false); });
    document.body.appendChild(dlg);
    dlg.showModal();
  });
}

async function approve(p) {
  const title = I18N.lang === "bn" ? p.content.title_bn : p.content.title_en;
  const yes = await confirmDialog(t("confirmApprove", { title, amount: M(p.content.total) }), t("confirmApproveText", { hash: p.content_hash.slice(0, 16) + "…" }));
  if (!yes) return;
  const { status, data } = await api(`/api/proposals/${p.id}/approve`, { content_hash: p.content_hash });
  toast(status === 200 ? t("approvedToast") : t("deniedToast", { reason: pick(data.decision, "reason") }));
  await refreshOverview(); renderNav(); renderApprovals();
}

async function reject(p) {
  const { status, data } = await api(`/api/proposals/${p.id}/reject`, { note: "" });
  toast(status === 200 ? t("rejectedToast") : t("deniedToast", { reason: pick(data.decision, "reason") }));
  await refreshOverview(); renderNav(); renderApprovals();
}

/* -------------------------- school-owned editable records (SQLite API) */
const RECORD_FIELDS = {
  students: [
    ["name", "Student name", "text", true], ["student_id", "Student ID", "text"], ["class", "Class", "text"],
    ["guardian_name", "Guardian name", "text"], ["guardian_phone", "Guardian phone", "tel"],
    ["admission_date", "Admission date", "date"], ["monthly_fee", "Monthly fee (BDT)", "number"],
    ["status", "Status", "select", false, ["active", "inactive", "graduated", "left"]],
  ],
  staff: [
    ["name", "Staff name", "text", true], ["title", "Job title", "text"], ["phone", "Phone", "tel"],
    ["salary", "Monthly salary (BDT)", "number"], ["salary_due_day", "Salary due day (1–31)", "number"],
    ["status", "Status", "select", false, ["active", "inactive", "on_leave"]],
  ],
  income: [
    ["date", "Date", "date", true], ["category", "Income category", "text", true], ["amount", "Amount (BDT)", "number", true],
    ["description", "Description / payer", "text", true], ["payment_method", "Payment method", "text"],
    ["status", "Status", "select", false, ["paid", "unpaid", "partial", "planned", "cancelled"]], ["reference", "Receipt / reference", "text"],
  ],
  expenses: [
    ["date", "Date", "date", true], ["category", "Expense category", "text", true], ["amount", "Amount (BDT)", "number", true],
    ["description", "Description", "text", true], ["supplier", "Supplier / payee", "text"], ["due_date", "Due date", "date"],
    ["payment_method", "Payment method", "text"], ["status", "Status", "select", false, ["paid", "unpaid", "partial", "planned", "cancelled"]],
  ],
  inventory: [
    ["item_name", "Item name", "text", true], ["category", "Category", "text"], ["quantity", "Quantity in stock", "number", true],
    ["unit", "Unit (reams, pieces, sets...)", "text"], ["unit_cost", "Unit cost (BDT)", "number"], ["reorder_level", "Reorder alert level", "number"],
    ["supplier", "Supplier", "text"], ["purchase_date", "Last purchase date", "date"],
  ],
};
const RECORD_LABELS = { students: "Students", staff: "Teachers & Staff", income: "Income", expenses: "Expenses", inventory: "Inventory" };
function canWriteKind(kind) {
  return ["owner", "accountant"].includes(state.session?.role);
}
function recordCell(kind, field, value) {
  if (value === null || value === undefined || value === "") return "–";
  if (["amount", "monthly_fee", "salary", "unit_cost"].includes(field) && Number.isFinite(Number(value))) return M(Number(value));
  if (["quantity", "reorder_level", "salary_due_day"].includes(field) && Number.isFinite(Number(value))) return I18N.num(Number(value));
  return String(value);
}
async function renderEditableRecords(root) {
  const allowedKinds = state.session?.role === "agent" ? ["students", "staff", "inventory"] : Object.keys(RECORD_FIELDS);
  const kind = allowedKinds.includes(state.recordKind) ? state.recordKind : allowedKinds[0];
  state.recordKind = kind;
  const canWrite = canWriteKind(kind);
  const { data } = await api(`/api/records?kind=${encodeURIComponent(kind)}`);
  const records = data.records || [];
  const selectableKinds = allowedKinds;
  const selector = h("select", { "aria-label": "Record type" }, Object.entries(RECORD_LABELS).filter(([value]) => selectableKinds.includes(value)).map(([value, label]) => {
    const option = h("option", { value, selected: value === kind }, I18N.lang === "bn" ? ({ students: "শিক্ষার্থী", staff: "শিক্ষক ও কর্মী", income: "আয়", expenses: "ব্যয়", inventory: "মজুত" }[value]) : label);
    return option;
  }));
  selector.value = kind;
  selector.addEventListener("change", () => { state.recordKind = selector.value; state.recordPage = 0; state.recordSearch = ""; renderRecords(); });
  const search = h("input", { type: "search", class: "record-search", placeholder: I18N.lang === "bn" ? "নাম, শ্রেণি, তারিখ বা বিবরণ খুঁজুন…" : "Search name, class, date or description…",
    "aria-label": I18N.lang === "bn" ? "রেকর্ড খুঁজুন" : "Search records", value: state.recordSearch, autocomplete: "off" });
  const count = h("span", { class: "muted small" });
  const prev = h("button", { class: "btn secondary", type: "button" }, I18N.lang === "bn" ? "আগের" : "Previous");
  const next = h("button", { class: "btn secondary", type: "button" }, I18N.lang === "bn" ? "পরের" : "Next");
  const pageLabel = h("span", { class: "muted small" });
  const toolbar = h("div", { class: "data-toolbar records-toolbar" },
    h("div", { class: "row record-controls" }, selector, search, count),
    canWrite ? h("button", { class: "btn", onClick: () => editRecord(kind, null) }, "+ " + (I18N.lang === "bn" ? "নতুন রেকর্ড" : "Add record")) : null);
  const fields = RECORD_FIELDS[kind];
  const displayKeys = kind === "students" ? ["name", "class", "student_id", "monthly_fee", "status"]
    : kind === "staff" ? ["name", "title", "salary", "status"]
    : kind === "income" ? ["date", "category", "amount", "status"]
    : kind === "expenses" ? ["date", "category", "amount", "status"] : ["item_name", "category", "quantity", "unit_cost"];
  const labelFor = (key) => fields.find((f) => f[0] === key)?.[1] || key;
  const tbody = h("tbody");
  const table = h("div", { class: "table-wrap" }, h("table", { class: "compact record-table" },
    h("thead", {}, h("tr", {}, ...displayKeys.map((key) => h("th", {}, labelFor(key))), h("th", {}, "Actions"))), tbody));
  const pager = h("div", { class: "pager" }, h("div", { class: "row" }, prev, next), pageLabel);

  function drawRows() {
    const needle = state.recordSearch.trim().toLocaleLowerCase();
    const filtered = needle ? records.filter((r) => JSON.stringify(r.data || {}).toLocaleLowerCase().includes(needle)) : records;
    const pages = Math.max(1, Math.ceil(filtered.length / state.recordPageSize));
    state.recordPage = Math.max(0, Math.min(state.recordPage, pages - 1));
    const shown = filtered.slice(state.recordPage * state.recordPageSize, (state.recordPage + 1) * state.recordPageSize);
    count.textContent = `${I18N.num(filtered.length)} ${I18N.lang === "bn" ? "টি মিলে গেছে" : "matching records"}`;
    pageLabel.textContent = filtered.length
      ? `${I18N.num(state.recordPage * state.recordPageSize + 1)}–${I18N.num(Math.min((state.recordPage + 1) * state.recordPageSize, filtered.length))} / ${I18N.num(filtered.length)}`
      : (I18N.lang === "bn" ? "কোনো রেকর্ড পাওয়া যায়নি" : "No matching records");
    prev.disabled = state.recordPage <= 0;
    next.disabled = state.recordPage >= pages - 1;
    tbody.replaceChildren(...(shown.length ? shown.map((r) => h("tr", {}, ...displayKeys.map((key) => h("td", {}, recordCell(kind, key, r.data[key]))),
      h("td", {}, canWrite ? h("div", { class: "record-actions" },
        h("button", { class: "btn secondary", onClick: () => editRecord(kind, r) }, I18N.lang === "bn" ? "সম্পাদনা" : "Edit"),
        h("button", { class: "btn secondary", onClick: async () => {
          if (!window.confirm(I18N.lang === "bn" ? "এই রেকর্ড আর্কাইভ করবেন? ইতিহাসে থাকবে।" : `Archive this ${kind.slice(0, -1)} record? It will be retained in history.`)) return;
          try { await apiRequireOk(`/api/records/${r.id}/archive`, {}); toast(I18N.lang === "bn" ? "রেকর্ড আর্কাইভ হয়েছে।" : "Record archived."); await refreshOverview(); rerender(); }
          catch (err) { toast(err.message); }
        } }, I18N.lang === "bn" ? "আর্কাইভ" : "Archive")) : h("span", { class: "muted small" }, I18N.lang === "bn" ? "শুধু দেখা" : "View only"))))
      : [h("tr", {}, h("td", { colSpan: displayKeys.length + 1, class: "empty" }, I18N.lang === "bn" ? (needle ? "কোনো মিল পাওয়া যায়নি।" : "এখনো কোনো রেকর্ড নেই। শুরু করতে নতুন রেকর্ড যোগ করুন।") : (needle ? "No matching records. Try a shorter search." : "No records yet. Add your first record to get started.")))]));
  }
  search.addEventListener("input", () => { state.recordSearch = search.value; state.recordPage = 0; drawRows(); });
  prev.addEventListener("click", () => { state.recordPage -= 1; drawRows(); });
  next.addEventListener("click", () => { state.recordPage += 1; drawRows(); });
  drawRows();
  root.append(h("section", { class: "sheet records-sheet" }, toolbar, table, pager,
    h("p", { class: "auth-muted" }, I18N.lang === "bn" ? "এই রেকর্ডগুলো কেবল এই স্কুলের ডাটাবেসে সংরক্ষিত হয়। প্রকৃত আর্থিক পূর্বাভাসের জন্য আলাদা করে যাচাইকৃত আর্থিক অনুমান সেট করতে হবে।" : "Records are saved to this school's database. The original forecast engine remains a separate scenario until verified financial assumptions are wired into it.")));
}
function editRecord(kind, record) {
  const data = record ? record.data : {};
  const fields = RECORD_FIELDS[kind];
  const form = h("form", { class: "record-form" });
  const inputs = {};
  fields.forEach(([key, label, type, required, options]) => {
    let input;
    if (type === "select") {
      const defaultStatus = key === "status" && ["income", "expenses"].includes(kind) ? "unpaid" : ["students", "staff"].includes(kind) ? "active" : "";
      input = h("select", { name: key, id: "record-" + key, required: !!required },
        ...(options || []).map((v) => h("option", { value: v, selected: String(data[key] || defaultStatus) === v }, v)));
    } else {
      input = h("input", { name: key, id: "record-" + key, type, required: !!required,
        value: data[key] === undefined || data[key] === null ? "" : String(data[key]),
        step: type === "number" ? "0.01" : null,
        min: type === "number" ? "0" : null,
        maxlength: type === "text" || type === "tel" ? "500" : null,
        placeholder: label });
    }
    inputs[key] = input;
    form.append(h("div", { class: "field" }, h("label", { for: "record-" + key }, label), input));
  });
  const feedback = h("p", { class: "auth-message", role: "status" });
  const save = h("button", { class: "btn", type: "submit" }, record ? "Save changes" : "Create record");
  const cancel = h("button", { class: "btn secondary", type: "button", onClick: () => dialog.close() }, "Cancel");
  const dialog = h("dialog", {}, h("h2", {}, `${record ? "Edit" : "Add"} ${RECORD_LABELS[kind]}`), form,
    feedback, h("div", { class: "btn-row", style: "margin-top:14px" }, save, cancel));
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); save.disabled = true; feedback.textContent = "";
    const payload = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]).filter(([, value]) => value !== ""));
    try {
      await apiRequireOk(record ? `/api/records/${record.id}/update` : "/api/records", record ? { data: payload } : { kind, data: payload });
      dialog.close(); toast(record ? "Record updated." : "Record created."); await refreshOverview(); await rerender();
    } catch (err) { feedback.textContent = err.message; save.disabled = false; }
  });
  dialog.addEventListener("close", () => dialog.remove());
  document.body.appendChild(dialog); dialog.showModal();
}

/* -------------------------------------------------------------- records */
async function renderRecords() {
  const root = page("records");
  root.append(h("h1", {}, I18N.lang === "bn" ? "স্কুলের রেকর্ড" : "School Records"),
    h("p", { class: "lead" }, I18N.lang === "bn" ? "শিক্ষার্থী, কর্মী, আয়, ব্যয় এবং মজুতের তথ্য যোগ করুন বা সম্পাদনা করুন।" : "Add and edit student, staff, income, expense, and inventory records for this school."));
  await renderEditableRecords(root);
  if (state.session?.role === "agent") return;
  if (state.session?.role === "owner") {
    const { data: audit } = await api("/api/records/audit?limit=30");
    const entries = audit.entries || [];
    root.append(h("section", { class: "sheet" }, h("h2", {}, I18N.lang === "bn" ? "সাম্প্রতিক রেকর্ড পরিবর্তনের ইতিহাস" : "Recent record changes"),
      h("p", { class: "muted small" }, I18N.lang === "bn" ? "শুধুমাত্র মালিকের দেখার জন্য: রেকর্ড যোগ, সম্পাদনা, আর্কাইভ ও টিম অ্যাকাউন্টের ইতিহাস।" : "Owner-only history of additions, edits, archives, and team-account changes."),
      entries.length ? h("div", { class: "table-wrap" }, h("table", { class: "compact" },
        h("thead", {}, h("tr", {}, ...["When", "Who", "Action", "Record", "Change summary"].map((label) => h("th", {}, label)))),
        h("tbody", {}, entries.map((entry) => {
          const value = entry.new || entry.old || {};
          const summary = Object.entries(value).slice(0, 5).map(([key, val]) => `${key}: ${String(val)}`).join(" · ");
          const clipped = summary.length > 180 ? summary.slice(0, 177) + "…" : summary || "No field details";
          return h("tr", {}, h("td", { class: "tiny" }, String(entry.at || "").replace("T", " ").slice(0, 19)),
            h("td", {}, entry.actor_name || entry.actor_user_id || "Unknown"), h("td", {}, entry.action),
            h("td", {}, `${entry.kind} · ${String(entry.record_id || "").slice(0, 8)}`), h("td", { class: "small" }, clipped));
        })))) : h("p", { class: "empty" }, "No record changes yet.")));
  }
  if (state.overview.meta?.dataset_label === "EMPTY_WORKSPACE") {
    root.append(h("section", { class: "sheet setup-card" }, h("h2", {}, I18N.lang === "bn" ? "আর্থিক রিপোর্ট পরে এখানে দেখা যাবে" : "Your financial reports will appear here"),
      h("p", {}, I18N.lang === "bn" ? "এই নতুন ওয়ার্কস্পেসে নমুনা মাসিক হিসাব, কৃত্রিম বকেয়া বা ডেমো আমদানি দেখানো হচ্ছে না। নিজের ফি, আয়, ব্যয় ও প্রারম্ভিক ব্যালেন্স যোগ করুন; তারপর যাচাইকৃত তথ্যের ভিত্তিতে পরিকল্পনা সংযুক্ত করা যাবে।" : "This fresh workspace hides sample monthly accounts, invented tuition dues and demo imports. Add your real fee, income, expense and opening-balance records first; forecast integration can then be configured from verified data."),
      h("div", { class: "welcome-actions" }, h("button", { class: "btn", onClick: () => { state.recordKind = "income"; renderRecords(); } }, I18N.lang === "bn" ? "আয়ের রেকর্ড যোগ করুন" : "Add income record"),
        h("button", { class: "btn secondary", onClick: () => { state.recordKind = "expenses"; renderRecords(); } }, I18N.lang === "bn" ? "ব্যয়ের রেকর্ড যোগ করুন" : "Add expense record"))));
    return;
  }
  const { data } = await api("/api/ledger");
  state.ledger = data;
  root.append(h("h2", { style: "margin-top:24px" }, t("recordsHead")), h("p", { class: "lead" }, t("recordsLead", { date: I18N.dayMonth(localDhakaDate()) })));
  const ins_ = data.insight;
  const monthRows = data.months.map((m) => h("tr", {}, h("td", { class: "nowrap" }, I18N.monthName(m.month)), h("td", {}, t("actual"), " ", badge("VERIFIED")),
    h("td", { class: "n" }, M(m.opening_cash)), h("td", { class: "n" }, M(m.tuition_billed)), h("td", { class: "n" }, M(m.tuition_collected)),
    h("td", { class: "n" }, M(m.outstanding_tuition)), h("td", { class: "n" }, M(m.total_inflow)), h("td", { class: "n" }, M(m.total_outflow)), h("td", { class: "n" }, M(m.closing_cash))));
  const fc = data.forecast_months[state.recordsView].map((m) => h("tr", { class: "dim" }, h("td", { class: "nowrap" }, I18N.monthName(m.month)),
    h("td", {}, m.status === "FORECAST" ? t("forecast") : t("actualForecast"), " ", badge("SIMULATED")),
    h("td", { class: "n" }, M(m.opening_cash)), h("td", { class: "n" }, "–"), h("td", { class: "n" }, "–"), h("td", { class: "n" }, "–"),
    h("td", { class: "n" }, M(m.receipts)), h("td", { class: "n" }, M(m.payments)), h("td", { class: "n" }, M(m.closing_cash))));
  root.append(h("details", { class: "sheet fold" },
    h("summary", { class: "fold-summary" }, h("span", {}, h("strong", {}, t("monthsHead")), h("span", { class: "muted small fold-subtitle" }, I18N.lang === "bn" ? "মাসভিত্তিক প্রকৃত ও পূর্বাভাসের বিবরণ" : "Monthly actuals and forecast detail")),
      h("span", { class: "fold-action" }, I18N.lang === "bn" ? "বিস্তারিত দেখুন +" : "View details +")),
    h("div", { class: "fold-body" },
      h("div", { class: "row", style: "justify-content:space-between;align-items:baseline" }, h("span", { class: "muted small" }, I18N.lang === "bn" ? "দৃশ্য নির্বাচন" : "Choose view"),
        viewToggle(state.recordsView, (v) => { state.recordsView = v; renderRecords(); })),
      h("p", { class: "muted small" }, t("insight", { worst: I18N.monthName(ins_.worst_month), wr: I18N.pct(ins_.worst_ratio), best: I18N.monthName(ins_.best_month), br: I18N.pct(ins_.best_ratio) }),
        " ", D(I18N.lang === "bn" ? ins_.worst_note_bn : ins_.worst_note_en)),
      h("div", { class: "table-wrap" }, h("table", { class: "compact" }, h("thead", {}, h("tr", {}, ["th_month", "th_kind", "th_open", "th_billed", "th_collected", "th_outstanding", "th_receipts", "th_payments", "th_closing"].map((k, i) =>
        h("th", { class: i >= 2 ? "n" : "" }, t(k))))), h("tbody", {}, monthRows, fc))))));

  const dues = data.dues;
  root.append(h("details", { class: "sheet fold" },
    h("summary", { class: "fold-summary" }, h("span", {}, h("strong", {}, t("duesHead")), h("span", { class: "muted small fold-subtitle" }, I18N.lang === "bn" ? "শিক্ষার্থীভিত্তিক বকেয়া — প্রয়োজন হলে খুলুন" : "Student-by-student outstanding tuition — open when needed")),
      h("span", { class: "fold-action" }, I18N.lang === "bn" ? "বকেয়া দেখুন +" : "View dues +")),
    h("div", { class: "fold-body" },
      h("p", { class: "note " + (dues.reconciled ? "good" : "warn") }, dues.reconciled ? t("reconciled") : t("notReconciled", { a: M(dues.per_student_total), b: M(dues.ledger_outstanding) })),
      h("div", { class: "table-wrap" }, h("table", { class: "compact" }, h("thead", {}, h("tr", {}, h("th", {}, t("th_student")), h("th", {}, t("th_class")), h("th", { class: "n" }, I18N.lang === "bn" ? "মাসিক ফি" : "Monthly fee"),
        h("th", { class: "n" }, t("th_outstanding")), h("th", { class: "n" }, I18N.lang === "bn" ? "মাস" : "Months"))),
        h("tbody", {}, dues.students.filter((s) => s.dues > 0 || s.status !== "active").map((student) => h("tr", { class: student.status !== "active" ? "dim" : "" },
          h("td", {}, student.name, " ", h("span", { class: "muted tiny" }, student.student_id), student.status !== "active" ? h("span", { class: "muted tiny" }, ` (${student.status})`) : null),
          h("td", {}, student.class), h("td", { class: "n" }, M(student.monthly_fee)), h("td", { class: "n" }, M(student.dues)), h("td", { class: "n" }, I18N.num(student.months_due, 1))))))),
      h("div", { class: "btn-row" }, h("button", { class: "btn secondary", onClick: draftReminders }, t("remindersBtn"))),
      h("div", { id: "reminders-out" }, state.reminders ? renderReminderList(state.reminders) : null))));

  const fileInput = h("input", { type: "file", accept: ".csv,text/csv", class: "visually-hidden", id: "csv-file" });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (file.size > 1000000) return toast("File larger than 1 MB.");
    stageImport(await file.text(), file.name);
  });
  root.append(h("section", { class: "sheet" }, h("h2", {}, t("importHead")), h("p", { class: "lead small" }, t("importLead")),
    h("div", { class: "btn-row" }, h("button", { class: "btn secondary", onClick: async () => { const { data: s } = await api("/api/import/sample"); stageImport(s.csv_text, s.filename); } }, t("loadSample")),
      fileInput, h("label", { for: "csv-file", class: "btn secondary" }, t("chooseFile"))),
    h("div", { id: "import-out" }, state.importReport ? renderImportReport(state.importReport) : null)));

  root.append(h("section", { class: "sheet" }, h("h2", {}, t("journalHead")), h("p", { class: "muted small" }, t("journalLead"),
    " ", data.journal_chain.ok ? t("chainOk", { n: I18N.num(data.journal_chain.count) }) : t("chainBad", { n: data.journal_chain.broken_at })),
    data.journal.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, t("th_time")), h("th", {}, t("th_event")), h("th", {}, t("th_actor")), h("th", {}, t("th_detail")))),
      h("tbody", {}, data.journal.slice().reverse().map((e) => h("tr", {}, h("td", {}, I18N.num(e.seq)), h("td", {}, e.time_utc.replace("T", " ").slice(0, 19)), h("td", {}, e.event), h("td", {}, e.actor),
        h("td", {}, e.proposal_id ? `${e.proposal_id}: ${M(e.total)}` : e.import_id ? `${e.import_id}: ${I18N.num(e.rows)} rows, ${M(e.amount)}` : e.note || "")))))) : h("p", { class: "empty" }, "–")));
}

async function draftReminders() {
  const { data } = await api("/api/reminders", { lang: I18N.lang });
  state.reminders = data.drafts;
  const out = document.getElementById("reminders-out");
  if (out) out.replaceChildren(renderReminderList(data.drafts));
}

function renderReminderList(drafts) {
  return h("div", {}, drafts.map((r) => h("div", { class: "draft-card" }, h("div", { class: "tiny muted" }, t("reminderDraft")), D(r.text))));
}

async function stageImport(text, filename) {
  const { status, data } = await api("/api/import/stage", { csv_text: text, filename });
  if (status !== 200) return toast(t("deniedToast", { reason: data && data.decision ? pick(data.decision, "reason") : (data && data.error) || "" }));
  state.importReport = data;
  const out = document.getElementById("import-out");
  if (out) out.replaceChildren(renderImportReport(data));
}

function renderImportReport(rep) {
  const s = rep.summary;
  const dp = rep.dues_preview;
  return h("div", {},
    h("p", { class: "note" }, t("importSummary", { acc: I18N.num(s.accepted), amt: M(s.accepted_amount), held: I18N.num(s.held), rej: I18N.num(s.rejected), flag: I18N.num(s.flagged_memos) })),
    h("p", { class: "small " + (dp.reconciled_after_import ? "pill-pass" : "") }, t("afterImport", { a: M(dp.per_student_total_after_import), b: M(dp.ledger_outstanding) }), dp.reconciled_after_import ? " ✓" : ""),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["th_row", "th_receipt", "th_student", "th_amount", "th_result", "th_messages"].map((k) => h("th", { class: k === "th_amount" ? "n" : "" }, t(k))))),
      h("tbody", {}, rep.rows.map((r) => h("tr", {}, h("td", {}, I18N.num(r.row)), h("td", {}, r.receipt_no || "–"), h("td", {}, r.student_id || "–"),
        h("td", { class: "n" }, r.amount === null || r.amount === undefined ? "–" : M(r.amount)),
        h("td", {}, h("span", { class: "status " + (r.status === "accepted" ? "ok" : r.status === "held" ? "warn" : "bad") }, t("r_" + r.status))),
        h("td", {}, r.messages.map((m) => h("div", { class: "small" }, I18N.lang === "bn" ? m.bn : m.en)),
          r.memo ? h("div", { class: "tiny muted" }, `memo: `, h("code", {}, r.memo)) : null)))))),
    h("div", { class: "btn-row" }, h("button", { class: "btn good", onClick: async () => {
      const { status, data } = await api(`/api/import/${rep.import_id}/commit`, {});
      if (status !== 200) return toast(t("deniedToast", { reason: pick(data.decision, "reason") }));
      toast(t("importDone")); state.importReport = null; renderRecords();
    } }, t("commitImport"))));
}

/* ----------------------------------------------------- team & permissions */
async function renderTeam() {
  const root = page("team");
  root.append(h("h1", {}, I18N.lang === "bn" ? "দল ও অ্যাকাউন্ট নিয়ন্ত্রণ" : "Team & Access"), h("p", { class: "lead" }, I18N.lang === "bn" ? "স্কুলের হিসাবরক্ষক ও এজেন্টদের জন্য আলাদা অ্যাকাউন্ট তৈরি করুন। প্রত্যেকে নিজস্ব ইমেইল ও পাসওয়ার্ড দিয়ে লগইন করবেন।" : "Create individual accounts for your school's accountant and agents. Each person signs in using their own credentials."));
  const form = h("form", { class: "team-form" });
  const name = h("input", { id: "team-name", name: "full_name", required: true, maxlength: "120", autocomplete: "name" });
  const email = h("input", { id: "team-email", name: "email", required: true, type: "email", maxlength: "254", autocomplete: "email" });
  const phone = h("input", { id: "team-phone", name: "phone", type: "tel", maxlength: "40", autocomplete: "tel" });
  const role = h("select", { id: "team-role", name: "role", required: true }, h("option", { value: "accountant" }, "Accountant"), h("option", { value: "agent" }, "Agent"));
  const error = h("p", { class: "auth-message", role: "status", "aria-live": "polite" });
  const create = h("button", { class: "btn", type: "submit" }, "Create account");
  form.append(
    h("div", { class: "field" }, h("label", { for: "team-name" }, "Full name"), name),
    h("div", { class: "field" }, h("label", { for: "team-email" }, "Email address"), email),
    h("div", { class: "field" }, h("label", { for: "team-phone" }, "Phone (optional)"), phone),
    h("div", { class: "field" }, h("label", { for: "team-role" }, "Role"), role),
    h("div", { class: "field full" }, error, create));
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); create.disabled = true; error.textContent = "";
    try {
      const { data } = await apiRequireOk("/api/team", { full_name: name.value.trim(), email: email.value.trim(), phone: phone.value.trim(), role: role.value });
      state.teamCredential = data.member;
      toast("Account created. Copy the temporary password now.");
      await renderTeam();
    } catch (err) { error.textContent = err.message; create.disabled = false; }
  });
  const { data } = await api("/api/team");
  const members = data.members || [];
  const credential = state.teamCredential ? h("section", { class: "sheet" }, h("h2", {}, "Temporary sign-in details"),
    h("p", { class: "note warn" }, "This temporary password is shown only once. Share it with the team member through a secure channel; they must change it after signing in."),
    h("div", { class: "credential-box" }, h("p", {}, h("strong", {}, state.teamCredential.full_name), " · ", state.teamCredential.role),
      h("p", {}, "Email: ", h("code", {}, state.teamCredential.email)),
      h("p", {}, "Temporary password: ", h("code", {}, state.teamCredential.temporary_password)),
      h("button", { class: "btn secondary", onClick: async () => {
        try { await navigator.clipboard.writeText(`FinEdvise login\nEmail: ${state.teamCredential.email}\nTemporary password: ${state.teamCredential.temporary_password}`); toast("Credentials copied."); }
        catch (_) { toast("Copy is unavailable. Select the credentials and copy them manually."); }
      } }, "Copy credentials"),
      h("button", { class: "btn secondary", style: "margin-left:8px", onClick: () => { state.teamCredential = null; renderTeam(); } }, "Dismiss"))) : null;
  const table = h("div", { class: "table-wrap" }, h("table", { class: "compact" },
    h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", {}, "Email"), h("th", {}, "Role"), h("th", {}, "Status"), h("th", {}, "Access"))),
    h("tbody", {}, members.map((m) => h("tr", {}, h("td", {}, m.full_name), h("td", {}, m.email), h("td", {}, m.role),
      h("td", {}, m.active ? "Active" : "Deactivated", m.must_change_password ? h("div", { class: "tiny muted" }, "Temporary password not changed") : null),
      h("td", {}, m.role === "owner" ? h("span", { class: "muted small" }, "Owner account") : h("button", { class: "btn secondary", onClick: async () => {
        const action = m.active ? "deactivate" : "reactivate";
        if (!window.confirm(`${action} access for ${m.full_name}?`)) return;
        try { await apiRequireOk(`/api/team/${m.user_id}/active`, { active: !m.active }); toast(`Account ${m.active ? "deactivated" : "reactivated"}.`); renderTeam(); }
        catch (err) { toast(err.message); }
      } }, m.active ? "Deactivate" : "Reactivate")))))));
  root.append(h("section", { class: "sheet" }, h("h2", {}, "Create a team account"),
    h("p", { class: "muted small" }, "New users receive a temporary password and must change it before accessing school data."), form),
    credential,
    h("section", { class: "sheet" }, h("h2", {}, "School team"), table,
      h("p", { class: "auth-muted" }, "Accountants can manage school records but cannot approve owner-only actions. Agents have read-only access to student, staff, and inventory records and do not see the financial dashboard.")));
}

function openRoleDialog() {
  const dlg = h("dialog", {}, h("h3", {}, I18N.lang === "bn" ? "অ্যাকাউন্ট" : "Account"),
    h("p", {}, `${state.session?.full_name || ""} · ${state.session?.role || ""}`),
    h("p", { class: "muted small" }, state.session?.email || ""),
    h("div", { class: "btn-row" },
      h("button", { class: "btn secondary", onClick: () => { dlg.close(); renderPasswordChange(false); } }, I18N.lang === "bn" ? "পাসওয়ার্ড পরিবর্তন" : "Change password"),
      h("button", { class: "btn secondary", onClick: () => { dlg.close(); logout(); } }, I18N.lang === "bn" ? "লগআউট" : "Log out"),
      h("button", { class: "btn secondary", onClick: () => dlg.close() }, t("close"))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.appendChild(dlg); dlg.showModal();
}

/* ------------------------------------------------------------- security */
async function renderSecurity() {
  const root = page("security");
  root.append(h("h1", {}, t("securityHead")), h("p", { class: "lead" }, t("securityLead")));
  const { data } = await api("/api/audit?limit=150");
  state.audit = data;
  const dec = (v) => h("span", { class: "status " + (v === "ALLOW" ? "ok" : v === "DENY" ? "bad" : "warn") }, v);
  root.append(h("section", { class: "sheet" }, h("h2", {}, t("tiersHead")),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("th_action")), h("th", {}, t("th_tier")), h("th", {}, t("owner")), h("th", {}, t("accountant")), h("th", {}, "Agent"))),
      h("tbody", {}, data.tiers.map((r) => h("tr", {}, h("td", {}, h("code", {}, r.action)), h("td", {}, r.tier), h("td", {}, dec(r.owner)), h("td", {}, dec(r.accountant)), h("td", {}, dec(r.agent)))))))));

  const ai = state.overview.agent.mode === "gemini";
  const redBox = h("section", { class: "sheet" }, h("h2", {}, t("redHead")), h("p", { class: "lead small" }, t("redLead", { n: I18N.num(23) })),
    h("div", { class: "btn-row" }, h("button", { class: "btn", onClick: () => runRedTeam(false) }, t("runRed")),
      ai ? h("button", { class: "btn secondary", onClick: () => runRedTeam(true) }, t("runRedAi")) : null),
    h("div", { id: "red-out" }, state.redteam ? renderRedTeam(state.redteam) : null));
  root.append(redBox);

  const chain = data.chain;
  root.append(h("section", { class: "sheet" }, h("h2", {}, t("auditHead")), h("p", { class: "muted small" }, t("auditLead")),
    h("p", { class: "note " + (chain.ok ? "good" : "bad") }, chain.ok ? t("chainOk", { n: I18N.num(chain.count) }) : t("chainBad", { n: chain.broken_at })),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, t("th_time")), h("th", {}, t("th_event")), h("th", {}, t("th_actor")), h("th", {}, t("th_detail")))),
      h("tbody", {}, data.entries.slice().reverse().map((e) => h("tr", {}, h("td", {}, I18N.num(e.seq)), h("td", { class: "tiny" }, e.time_utc.replace("T", " ").slice(0, 19)),
        h("td", {}, e.event), h("td", {}, e.actor), h("td", { class: "small" }, auditDetail(e)))))))));
}

function auditDetail(e) {
  if (e.event === "POLICY_DECISION") return `${e.action}: ${e.decision} (${e.tier}, ${e.rule})`;
  if (e.event === "TOOL_RESULT") return `${e.tool} #${(e.result_hash || "").slice(0, 12)}`;
  if (e.event === "CHAT_TURN") return `${e.mode}; tools ${(e.tools || []).join(", ") || "none"}; guardrail ${e.guardrail_passed ? "passed" : "failed"} (${e.numbers_checked})`;
  if (e.event === "CHAT_REQUEST") return e.message_masked || "";
  if (e.proposal_id) return `${e.proposal_id}${e.content_hash ? " #" + e.content_hash.slice(0, 12) : ""}`;
  if (e.import_id) return e.import_id;
  if (e.event === "RED_TEAM_RUN") return `${e.passed}/${e.total} passed (${e.mode})`;
  return e.details ? JSON.stringify(e.details).slice(0, 120) : "";
}

async function runRedTeam(useAi) {
  const out = document.getElementById("red-out");
  out.replaceChildren(h("p", { class: "muted" }, t("loading")));
  try {
    const { data } = await api("/api/redteam/run", { use_ai: useAi });
    state.redteam = data;
    out.replaceChildren(renderRedTeam(data));
  } catch (err) {
    out.replaceChildren(h("p", { class: "note bad" }, t("errorGeneric", { msg: err.message })));
  }
}

function renderRedTeam(r) {
  const v1 = r.v1_comparison;
  return h("div", {},
    h("p", { class: "note " + (r.failed ? "bad" : "good") }, t("redSummary", { p: I18N.num(r.passed), t: I18N.num(r.total) }), ` (${r.agent_mode}${r.model ? ": " + r.model : ""})`),
    h("h3", { style: "margin-top:12px" }, t("v1Head")),
    h("p", {}, t("v1Text", { b: I18N.num(v1.v1_blocked), n: I18N.num(v1.chat_and_csv_attacks), p: I18N.num(v1.v2_passed) })),
    h("p", { class: "muted small" }, I18N.lang === "bn" ? v1.fix_bn : v1.fix_en),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["th_attack", "th_channel", "th_lang", "th_result2", "th_v1", "th_evidence"].map((k) => h("th", {}, t(k))))),
      h("tbody", {}, r.results.map((x) => h("tr", {},
        h("td", {}, h("strong", {}, x.id), " ", x.kind, h("details", {}, h("summary", { class: "tiny" }, I18N.lang === "bn" ? "ইনপুট ও উত্তর" : "Input and reply"),
          h("div", { class: "tiny" }, h("code", {}, x.input)), x.reply ? h("div", { class: "tiny muted" }, x.reply) : null)),
        h("td", {}, x.channel), h("td", {}, x.lang),
        h("td", {}, h("span", { class: x.verdict === "PASS" ? "pill-pass" : "pill-fail" }, x.verdict)),
        h("td", {}, x.v1_keyword_gate_blocked === null || x.v1_keyword_gate_blocked === undefined ? "–" : h("span", { class: x.v1_keyword_gate_blocked ? "pill-pass" : "pill-fail" }, x.v1_keyword_gate_blocked ? t("blocked") : t("missed"))),
        h("td", { class: "small" }, Object.entries(x.checks).map(([k, v]) => h("div", {}, `${v ? "✓" : "✗"} ${k.replace(/_/g, " ")}`)),
          x.tools_called && x.tools_called.length ? h("div", { class: "tiny muted" }, x.tools_called.map((c) => `${c[0]}: ${c[1]}`).join("; ")) : null,
          x.decision ? h("div", { class: "tiny muted" }, x.decision) : null)))))));
}

/* ----------------------------- school events / school-spirit planner */
const OCCASION_GUIDES = {
  picnic: {
    label: "School picnic", bn: "স্কুল পিকনিক", split: [["Transport & venue", 28], ["Food and safe drinking water", 26], ["Safeguarding & first aid", 14], ["Games and learning activities", 16], ["Family communication & permissions", 6], ["Contingency", 10]],
    ideas: ["Use a vetted venue and transport provider; confirm seat belts and an adult supervision plan.", "Collect permissions and emergency contacts privately; nominate a first-aid lead.", "Plan shaded rest, clean drinking water, allergy-aware food and an inclusive activity for every age."],
    bnIdeas: ["যাচাইকৃত স্থান ও পরিবহন নিন; সিটবেল্ট ও প্রাপ্তবয়স্ক তত্ত্বাবধান নিশ্চিত করুন।", "অভিভাবকের অনুমতি ও জরুরি যোগাযোগ নিরাপদে সংগ্রহ করুন; একজন ফার্স্ট-এইড দায়িত্বে রাখুন।", "ছায়া, নিরাপদ পানি, অ্যালার্জি-সচেতন খাবার এবং সব বয়সের উপযোগী কার্যক্রম রাখুন।"]
  },
  party: {
    label: "Class party", bn: "ক্লাস পার্টি", split: [["Allergy-aware snacks & drinks", 25], ["Reusable decorations / student art", 18], ["Games, music & show-and-tell", 20], ["Hygiene & cleanup", 12], ["Inclusive participation", 10], ["Contingency", 15]],
    ideas: ["Let students help make reusable decorations from safe, low-cost craft materials.", "Choose short team games, a reading circle or student showcase so every child can participate.", "Check food allergies and family preferences; set a clear cleanup rota before the party."],
    bnIdeas: ["নিরাপদ ও কম খরচের উপকরণ দিয়ে পুনর্ব্যবহারযোগ্য সাজসজ্জা শিক্ষার্থীদের দিয়ে বানান।", "দলীয় খেলা, বই পড়ার আসর বা শিক্ষার্থীদের পরিবেশনা রাখুন যাতে সবাই অংশ নিতে পারে।", "খাবারের অ্যালার্জি ও পরিবারের পছন্দ যাচাই করুন; আগে থেকেই পরিষ্কারের দায়িত্ব ভাগ করুন।"]
  },
  feast: {
    label: "School feast / food day", bn: "স্কুল ফিস্ট / খাবার দিবস", split: [["Food ingredients", 34], ["Safe water & food hygiene", 16], ["Preparation / serving logistics", 12], ["Dietary inclusion & allergy alternatives", 12], ["Reusable serving items", 10], ["Contingency", 16]],
    ideas: ["Use clean preparation surfaces, safe water and a named adult responsible for food safety.", "Label allergens and keep a simple alternative for children with dietary, medical or religious needs.", "Use reusable plates and a measured serving plan to reduce waste; avoid leaving food unrefrigerated."],
    bnIdeas: ["পরিষ্কার রান্নার স্থান, নিরাপদ পানি এবং খাবারের নিরাপত্তার জন্য নির্দিষ্ট দায়িত্বশীল ব্যক্তি রাখুন।", "খাবারের অ্যালার্জি চিহ্নিত করুন এবং বিশেষ খাদ্য চাহিদার জন্য বিকল্প রাখুন।", "অপচয় কমাতে পুনর্ব্যবহারযোগ্য প্লেট ও পরিমিত পরিবেশনের পরিকল্পনা করুন; খাবার দীর্ঘক্ষণ বাইরে রাখবেন না।"]
  },
  sports: {
    label: "Sports day", bn: "ক্রীড়া দিবস", split: [["Safe equipment & field marking", 22], ["First aid, water & shade", 20], ["Inclusive games and medals", 18], ["Sound / announcements", 12], ["Staff duty & logistics", 13], ["Contingency", 15]],
    ideas: ["Inspect equipment and the playing surface before the event; remove sharp, loose or broken items.", "Offer non-competitive and accessible games alongside races so every learner can join.", "Schedule hydration, shade breaks and first-aid coverage; set a weather cancellation plan."],
    bnIdeas: ["অনুষ্ঠানের আগে সরঞ্জাম ও মাঠ পরীক্ষা করুন; ধারালো, ঢিলা বা ভাঙা জিনিস সরান।", "দৌড়ের পাশাপাশি সহজ ও অন্তর্ভুক্তিমূলক খেলা রাখুন যাতে সবাই অংশ নিতে পারে।", "পানি, ছায়ায় বিশ্রাম ও ফার্স্ট-এইডের ব্যবস্থা রাখুন; আবহাওয়ার জন্য বিকল্প পরিকল্পনা করুন।"]
  },
  decor: {
    label: "Decoration refresh", bn: "সাজসজ্জা নবায়ন", split: [["Reusable banners / display boards", 24], ["Student-made art materials", 18], ["Safe storage & reusable hooks", 14], ["Lighting / electrical safety", 18], ["Repair and touch-up supplies", 14], ["Contingency", 12]],
    ideas: ["Refresh one high-visibility area at a time; prioritise reusable banners, student art and noticeboards.", "Avoid blocking exits or covering safety signage; use safe fixings and keep decorations away from wiring.", "Repair existing boards, benches and play markings before purchasing new display items."],
    bnIdeas: ["একবারে একটি গুরুত্বপূর্ণ স্থান সাজান; পুনর্ব্যবহারযোগ্য ব্যানার, শিক্ষার্থীদের শিল্পকর্ম ও নোটিশ বোর্ডকে অগ্রাধিকার দিন।", "জরুরি বহির্গমন বা নিরাপত্তা নির্দেশনা ঢেকে দেবেন না; বৈদ্যুতিক তার থেকে সাজসজ্জা দূরে রাখুন।", "নতুন জিনিস কেনার আগে পুরোনো বোর্ড, বেঞ্চ ও খেলার দাগ মেরামত করুন।"]
  },
  playground: {
    label: "Playground repair & safety", bn: "খেলার মাঠ মেরামত ও নিরাপত্তা", split: [["Qualified inspection", 12], ["Priority repairs / labour", 34], ["Safe surface / drainage", 22], ["Hardware, fence & anchoring", 14], ["Clear hazards / waste", 6], ["Contingency", 12]],
    ideas: ["Close off unsafe equipment immediately and ask a qualified maintainer to inspect it before reuse.", "Check rust, exposed bolts, unstable anchors, sharp edges, drainage and fall surfaces; document each defect.", "Prioritise safety-critical fixes over decorative upgrades and retain the inspection / repair record."],
    bnIdeas: ["অনিরাপদ সরঞ্জাম সঙ্গে সঙ্গে বন্ধ রাখুন এবং ব্যবহারের আগে দক্ষ মেরামতকারীর পরিদর্শন নিন।", "মরিচা, বেরিয়ে থাকা বোল্ট, নড়বড়ে ভিত্তি, ধারালো প্রান্ত, পানি নিষ্কাশন ও পড়ার পৃষ্ঠ পরীক্ষা করুন।", "সাজসজ্জার আগে নিরাপত্তা-সংক্রান্ত মেরামত করুন এবং পরিদর্শন ও মেরামতের রেকর্ড রাখুন।"]
  }
};
function renderOccasionPlanner() {
  const bn = I18N.lang === "bn";
  if (!state.occasion.date) state.occasion.date = localDhakaDate();
  const kind = h("select", { class: "event-select", "aria-label": bn ? "কার্যক্রম নির্বাচন" : "Select school activity" },
    Object.entries(OCCASION_GUIDES).map(([key, guide]) => h("option", { value: key, selected: key === state.occasion.kind }, bn ? guide.bn : guide.label)));
  kind.value = state.occasion.kind;
  const date = h("input", { type: "date", value: state.occasion.date, "aria-label": bn ? "কার্যক্রমের তারিখ" : "Activity date" });
  const amount = h("input", { type: "number", min: "0", max: "100000000", step: "500", value: String(state.occasion.budget), "aria-label": bn ? "পরিকল্পিত বাজেট" : "Planning budget" });
  const amountDisplay = h("div", { class: "event-budget-display" }, M(state.occasion.budget));
  const results = h("div", { class: "event-result" });
  const saveButton = h("button", { class: "btn secondary", type: "button" }, bn ? "পরিকল্পিত ব্যয় হিসেবে সংরক্ষণ করুন" : "Save as planned expense");
  const fields = h("div", { class: "event-controls" },
    h("div", { class: "field" }, h("label", {}, bn ? "কার্যক্রমের ধরন" : "Activity type"), kind),
    h("div", { class: "field" }, h("label", {}, bn ? "পরিকল্পিত তারিখ" : "Planned date"), date),
    h("div", { class: "field" }, h("label", {}, bn ? "প্রস্তাবিত বাজেট (৳)" : "Planning budget (৳)"), amount, amountDisplay),
    h("p", { class: "muted small" }, bn ? "এটি পরিকল্পনার খসড়া, অনুমোদন নয়। কেনাকাটা বা চুক্তির আগে প্রকৃত নগদ প্রবাহ ও বিকল্প দাম যাচাই করুন।" : "This is a planning draft, not spend approval. Check real cash headroom and compare current vendor quotes before committing."),
    canWriteKind("expenses") ? saveButton : null);
  function update() {
    const guide = OCCASION_GUIDES[kind.value] || OCCASION_GUIDES.picnic;
    const budget = Math.max(0, Math.min(100000000, Number(amount.value) || 0));
    state.occasion = { kind: kind.value, budget, date: date.value || localDhakaDate() };
    amountDisplay.textContent = M(budget);
    const start = Date.parse(`${localDhakaDate()}T12:00:00Z`), target = Date.parse(`${state.occasion.date}T12:00:00Z`);
    const days = Number.isFinite(target - start) ? Math.round((target - start) / 86400000) : 0;
    const timing = days < 0 ? (bn ? "তারিখটি অতীতের — নতুন তারিখ দিন।" : "That date is in the past — choose a new date.")
      : days === 0 ? (bn ? "আজকের কার্যক্রম: দায়িত্ব, পানি, নিরাপত্তা ও শেষ মুহূর্তের সরবরাহ নিশ্চিত করুন।" : "Event is today: confirm staff duties, water, safety and last-mile supplies.")
      : days <= 7 ? (bn ? "সময় কাছাকাছি — জরুরি অনুমতি, সরবরাহকারী ও নিরাপত্তা ব্যবস্থা আগে নিশ্চিত করুন।" : "Coming up soon: confirm permissions, suppliers and safety arrangements first.")
      : days <= 30 ? (bn ? "আগামী কয়েক সপ্তাহের মধ্যে — একাধিক মূল্য নিন, দায়িত্ব ভাগ করুন এবং অন্তর্ভুক্তির পরিকল্পনা করুন।" : "Upcoming soon: compare quotes, assign owners and plan for inclusion.")
      : (bn ? "আগাম পরিকল্পনা — পুনর্ব্যবহার, শিক্ষার্থীদের অংশগ্রহণ এবং পর্যায়ক্রমে কেনাকাটার সুযোগ নিন।" : "Plenty of lead time: prioritise re-use, student participation and staged purchasing.");
    const splits = guide.split.map(([label, pct]) => h("div", { class: "budget-line" },
      h("div", { class: "budget-line-label" }, h("span", {}, bn ? ({"Transport & venue":"যাতায়াত ও স্থান","Food and safe drinking water":"খাবার ও নিরাপদ পানি","Safeguarding & first aid":"নিরাপত্তা ও ফার্স্ট-এইড","Games and learning activities":"খেলা ও শেখার কার্যক্রম","Family communication & permissions":"অভিভাবকের যোগাযোগ ও অনুমতি","Contingency":"জরুরি সংরক্ষণ","Allergy-aware snacks & drinks":"অ্যালার্জি-সচেতন খাবার","Reusable decorations / student art":"পুনর্ব্যবহারযোগ্য সাজসজ্জা / শিক্ষার্থীদের শিল্প","Games, music & show-and-tell":"খেলা, গান ও পরিবেশনা","Hygiene & cleanup":"পরিচ্ছন্নতা ও পরিষ্কার","Inclusive participation":"সবার অংশগ্রহণ","Food ingredients":"খাবারের উপকরণ","Safe water & food hygiene":"নিরাপদ পানি ও খাদ্য স্বাস্থ্যবিধি","Preparation / serving logistics":"প্রস্তুতি ও পরিবেশন","Dietary inclusion & allergy alternatives":"বিশেষ খাদ্য চাহিদার বিকল্প","Reusable serving items":"পুনর্ব্যবহারযোগ্য পরিবেশন সামগ্রী","Safe equipment & field marking":"নিরাপদ সরঞ্জাম ও মাঠ চিহ্নিতকরণ","First aid, water & shade":"ফার্স্ট-এইড, পানি ও ছায়া","Inclusive games and medals":"অন্তর্ভুক্তিমূলক খেলা ও পদক","Sound / announcements":"সাউন্ড ও ঘোষণা","Staff duty & logistics":"কর্মীদের দায়িত্ব ও ব্যবস্থাপনা","Reusable banners / display boards":"পুনর্ব্যবহারযোগ্য ব্যানার / বোর্ড","Student-made art materials":"শিক্ষার্থীদের শিল্প উপকরণ","Safe storage & reusable hooks":"নিরাপদ সংরক্ষণ ও পুনর্ব্যবহারযোগ্য হুক","Lighting / electrical safety":"আলো ও বৈদ্যুতিক নিরাপত্তা","Repair and touch-up supplies":"মেরামত ও রং করার উপকরণ","Qualified inspection":"দক্ষ পরিদর্শন","Priority repairs / labour":"জরুরি মেরামত / শ্রম","Safe surface / drainage":"নিরাপদ পৃষ্ঠ / পানি নিষ্কাশন","Hardware, fence & anchoring":"হার্ডওয়্যার, বেড়া ও সংযোগ","Clear hazards / waste":"ঝুঁকি ও বর্জ্য অপসারণ"}[label] || label) : label), h("span", {}, `${pct}%`)),
      h("div", { class: "budget-track" }, h("span", { style: `width:${pct}%` })),
      h("strong", {}, M(Math.round(budget * pct / 100)))));
    const ideas = (bn ? guide.bnIdeas : guide.ideas).map((idea) => h("li", {}, idea));
    results.replaceChildren(
      h("div", { class: "event-result-head" }, h("div", {}, h("span", { class: "eyebrow" }, bn ? "কোপাইলটের ধারণা" : "COPILOT IDEAS"), h("h3", {}, bn ? guide.bn : guide.label)), h("span", { class: "chip" }, `${days < 0 ? "Past date" : `${I18N.num(days)} ${bn ? "দিন বাকি" : "days away"}`}`)),
      h("div", { class: "event-total" }, h("span", {}, bn ? "পরিকল্পনার মোট বাজেট" : "Planning envelope"), h("strong", {}, M(budget))),
      h("p", { class: "note" }, timing),
      h("h4", {}, bn ? "প্রস্তাবিত বাজেট ভাগ" : "Suggested budget allocation"), h("div", { class: "budget-splits" }, splits),
      h("h4", {}, bn ? "পরিবেশ আরও প্রাণবন্ত করার উপায়" : "Ways to energise the school"), h("ul", { class: "plain idea-list" }, ideas),
      h("p", { class: "muted tiny" }, bn ? "পরামর্শগুলো সাধারণ পরিকল্পনার নির্দেশনা; স্থানীয় নিয়ম, শিশুর নিরাপত্তা, স্কুলের নীতি ও বর্তমান দাম যাচাই করুন।" : "Guidance is general. Check local rules, child safeguarding, school policy and current prices; all amounts above are planning allocations, not quotes."));
    saveButton.disabled = !canWriteKind("expenses") || !state.occasion.date || budget <= 0 || days < 0;
    saveButton.title = saveButton.disabled && budget <= 0 ? (bn ? "ধনাত্মক বাজেট দিন" : "Enter a positive planning budget") : "";
  }
  kind.addEventListener("change", update); date.addEventListener("change", update); amount.addEventListener("input", update);
  saveButton.addEventListener("click", async () => {
    const current = state.occasion; const guide = OCCASION_GUIDES[current.kind];
    if (!canWriteKind("expenses") || !current.date || current.budget <= 0) return;
    try {
      await apiRequireOk("/api/records", { kind: "expenses", data: {
        date: current.date, category: `School event · ${guide.label}`, amount: current.budget,
        description: `Planning draft for ${guide.label}. Suggested allocation only; obtain quotes and confirm cash availability before approval.`,
        supplier: "", due_date: current.date, payment_method: "Not paid", status: "planned"
      }});
      toast(bn ? "পরিকল্পিত ব্যয় রেকর্ডে সংরক্ষিত হয়েছে।" : "Saved to school expenses as a planned item.");
      await refreshOverview();
    } catch (error) { toast(error.message); }
  });
  update();
  return h("section", { class: "sheet occasion-sheet" },
    h("div", { class: "occasion-intro" }, h("div", {}, h("div", { class: "eyebrow" }, bn ? "স্কুলের প্রাণবন্ততা" : "SCHOOL SPIRIT STUDIO"), h("h2", {}, bn ? "কার্যক্রম ও বাজেট কো-পাইলট" : "Occasion & activity copilot"),
      h("p", { class: "muted" }, bn ? "পিকনিক, ক্লাস পার্টি, স্কুল ফিস্ট, ক্রীড়া দিবস, সাজসজ্জা বা মাঠের মেরামতের জন্য পরিকল্পনা তৈরি করুন।" : "Build a thoughtful plan for a picnic, class party, school feast, sports day, decoration refresh or playground repair."))),
    h("div", { class: "occasion-layout" }, h("div", { class: "occasion-controls-card" }, fields), results));
}

/* --------------------------------------------------------------- extras */
async function renderExtras() {
  const root = page("extras");
  root.append(h("h1", {}, t("extrasHead")), h("p", { class: "lead" }, t("extrasLead")), renderOccasionPlanner());
  const { data } = await api("/api/extras");
  const bn = I18N.lang === "bn";
  if (!data.configured) {
    root.append(h("section", { class: "sheet setup-card" }, h("h2", {}, bn ? "স্কুলের নিজস্ব আর্থিক তথ্য যোগ করুন" : "Your own financial assumptions are not set yet"),
      h("p", {}, bn ? "কার্যক্রম পরিকল্পকটি এখনই ব্যবহার করতে পারবেন। তবে কিট ক্রয়, ইভেন্ট ভর্তুকি বা ব্রেক-ইভেনের আর্থিক হিসাবের জন্য প্রকৃত মূল্য, স্টক, অংশগ্রহণকারী ও আয়ের অনুমান যোগ করতে হবে।" : "The activity planner above is available now. The kit-purchase, event-subsidy and break-even calculations need your real prices, stock, attendance and income assumptions before they can be shown."),
      h("a", { class: "btn", href: "#records" }, bn ? "স্কুলের রেকর্ড যোগ করুন" : "Add school records")));
    return;
  }
  const k = data.kit, ev = data.event;
  root.append(h("div", { class: "split" },
    h("section", { class: "sheet" }, h("h2", {}, t("kitHead")),
      h("div", { class: "facts" },
        fact(bn ? "অর্ডার (ক্লাস + অতিরিক্ত)" : "Order (classrooms + extra)", D(`${k.classroom_need} + ${k.extra_units} = ${k.order_qty}`), bn ? `প্রতিটি ${M(k.unit_price)} (বাল্ক দাম)` : `${M(k.unit_price)} each (bulk price)`),
        fact(bn ? "অতিরিক্ত কিটে টাকা" : "Cash in the extra kits", M(k.venture_cost), bn ? `মোট নগদ লাগবে ${M(k.total_cash_needed)}` : `Total cash needed ${M(k.total_cash_needed)}`),
        fact(bn ? "খরচ উঠাতে বিক্রি লাগবে" : "Kits to sell to recover the cost", D(`${k.break_even_units}`), bn ? `প্রতিটি ${M(k.sale_price)}` : `at ${M(k.sale_price)} each`, "SIMULATED"),
        fact(bn ? "চাহিদা (অনুমান)" : "Demand (guess)", D(`${k.demand_estimate.downside} – ${k.demand_estimate.base}`), I18N.lang === "bn" ? k.demand_estimate.source_bn : k.demand_estimate.source_en, "ASSUMED")),
      h("p", { class: "small" }, bn ? `ভালো অনুমানে লাভ ${M(k.base.profit)}; খারাপ অনুমানে ${M(k.downside.profit)} এবং ${k.downside.unsold_units}টি না বিক্রি কিটে ${M(k.downside.cash_locked_in_unsold)} আটকে থাকে।`
        : `Guess-based profit ${M(k.base.profit)}; in the low guess ${M(k.downside.profit)} with ${k.downside.unsold_units} unsold kits locking ${M(k.downside.cash_locked_in_unsold)}.`),
      h("p", { class: "small" }, bn ? `ভাড়ার বিকল্প: মাসে ${M(k.rental_option.monthly_fee)} করে, খরচ উঠতে প্রায় ${D(k.rental_option.months_to_payback)} মাস।` : `Rental option: ${M(k.rental_option.monthly_fee)} a month per kit; about ${k.rental_option.months_to_payback} months to recover the cost.`),
      h("p", { class: "note" }, t("prebook", { n: I18N.num(k.prebooking_rule.prebookings_needed_before_ordering), pct: I18N.pct(k.prebooking_rule.pct) })),
      h("h3", { style: "margin-top:12px" }, t("risks")), h("ul", { class: "plain" }, k.risk_flags.map((r) => h("li", {}, bn ? r.bn : r.en)))),
    h("section", { class: "sheet" }, h("h2", {}, t("eventHead")),
      h("div", { class: "facts" },
        fact(bn ? "মোট খরচ" : "Total cost", M(ev.total_cost), bn ? `${ev.people_fed} জনের খাবার, শিক্ষক ও অতিথিসহ` : `Food for ${ev.people_fed} people, teachers and guests included`),
        fact(bn ? "চাঁদা আদায়" : "Contributions collected", M(ev.collected)),
        fact(bn ? "স্কুলের ভর্তুকি" : "School subsidy", M(ev.school_subsidy), null, "SIMULATED"),
        fact(bn ? "ব্রেক-ইভেন চাঁদা (প্রতিজন)" : "Break-even contribution per student", M(ev.break_even_contribution_per_student), null, "SIMULATED")),
      h("p", {}, bn ? `ভর্তুকি উঠাতে অন্তত ${I18N.num(ev.students_to_cover_subsidy_whole)} জন শিক্ষার্থী ধরে রাখতে বা আনতে হবে (${D(ev.students_to_cover_subsidy)} জনের বছরের অবদান)।`
        : `To cover the subsidy the fair must keep or bring at least ${ev.students_to_cover_subsidy_whole} student (${ev.students_to_cover_subsidy} students' yearly contribution).`),
      h("p", { class: "small" }, badge("ASSUMED"), " ", bn ? `মালিকের ধারণা: ${D(ev.owner_belief.retained_students)} জন ধরে রাখা, ${D(ev.owner_belief.new_admissions)} জন নতুন ভর্তি। ${ev.owner_belief.source_bn}` : `Owner's belief: ${ev.owner_belief.retained_students} kept, ${ev.owner_belief.new_admissions} new admissions. ${ev.owner_belief.source_en}`),
      h("p", { class: "note warn" }, bn ? ev.honest_reading_bn : ev.honest_reading_en))));
}

/* ------------------------------------------------------- settings & role */
function openSettings() {
  const o = state.overview;
  const reserveInput = h("input", { type: "number", min: "0", step: "1000", value: String(o.metrics.reserve.value), style: "width:150px" });
  const theme = loadPref("theme", "system");
  const dlg = h("dialog", {}, h("h3", {}, t("settingsHead")),
    h("div", { class: "field" }, h("label", {}, t("theme")), h("div", { class: "seg" }, ["system", "light", "dark"].map((v) =>
      h("button", { "aria-pressed": String(theme === v), onClick: () => { setTheme(v); dlg.close(); openSettings(); } }, v)))),
    h("div", { class: "field" }, h("label", {}, t("reserveSetting")), h("div", { class: "row" }, reserveInput,
      h("button", { class: "btn", onClick: async () => {
        const { status, data } = await api("/api/settings/reserve", { amount: Number(reserveInput.value) });
        toast(status === 200 ? "✓" : t("deniedToast", { reason: pick(data.decision, "reason") }));
        await refreshOverview(); rerender();
      } }, t("save"))), h("span", { class: "muted tiny" }, t("reserveHelp"))),
    h("div", { class: "field" }, h("label", {}, t("resetSandbox")), h("span", { class: "muted tiny" }, t("resetHelp")),
      h("div", {}, h("button", { class: "btn danger", onClick: async () => {
        if (!window.confirm(t("resetSandbox") + "?")) return;
        const { status, data } = await api("/api/reset", {});
        toast(status === 200 ? "✓" : t("deniedToast", { reason: pick(data.decision, "reason") }));
        state.chat = []; state.importReport = null; state.redteam = null; state.reminders = null;
        await refreshOverview(); dlg.close(); rerender();
      } }, t("resetSandbox")))),
    h("div", { class: "btn-row" }, h("button", { class: "btn secondary", onClick: () => dlg.close() }, t("close"))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.appendChild(dlg);
  dlg.showModal();
}

function setTheme(v) {
  savePref("theme", v);
  if (v === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", v);
}

/* ------------------------------------------------------------- routing */
async function rerender() {
  renderHeader();
  renderNav();
  const tab = currentTab();
  const main = document.getElementById("main");
  try {
    if (state.session?.role === "agent") await renderRecords();
    else if (tab === "team") await renderTeam();
    else if (tab === "home") renderHome();
    else if (tab === "plan") await renderPlan();
    else if (tab === "copilot") renderCopilot();
    else if (tab === "financing") await renderFinancing();
    else if (tab === "approvals") await renderApprovals();
    else if (tab === "records") await renderRecords();
    else if (tab === "security") await renderSecurity();
    else if (tab === "extras") await renderExtras();
  } catch (err) {
    const node = page(tab);
    node.append(h("p", { class: "note bad" }, t("errorGeneric", { msg: err.message })));
  }
  main.focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => { closeDrawer(); rerender(); window.scrollTo(0, 0); });

(async function init() {
  startLiveClock();
  I18N.lang = loadPref("lang", "en");
  I18N.digits = loadPref("digits", "bn");
  setTheme(loadPref("theme", "system"));
  try {
    const { data: session } = await api("/api/session");
    state.session = session.authenticated ? session : null;
    if (!state.session) { renderAuthScreen("login"); return; }
    if (state.session.must_change_password) { renderPasswordChange(true); return; }
    showApplication();
    await refreshOverview();
    rerender();
  } catch (err) {
    const root = document.getElementById("authRoot");
    root.hidden = false;
    root.replaceChildren(h("div", { class: "note bad" }, `Cannot reach the FinEdvise server: ${err.message}`));
  }
})();
