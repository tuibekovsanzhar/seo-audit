/* Maya Audit page. Plain JavaScript, no build step. It shows what the local API (/api/v1) returns;
   it decides nothing about a website.

   Safety rule for this file: text from the server (which includes text from audited websites) is
   only ever put on the page as text. There is no markup-from-string call here. Links are made only for
   http(s) addresses, through link(). */
"use strict";

const API = "/api/v1";
const state = { token: null, strings: {}, settings: null, language: "en", auditId: null, source: null, ticker: null,
  historyLimit: 30, showHidden: false, draft: { mode: "quick", backlinks: false, search_data: false, local_business: false, archives: false, verify_ownership: false, business_type: "auto" }, lastFocus: null };
const $ = (id) => document.getElementById(id);

const num = (value) => new Intl.NumberFormat(state.language).format(Number(value) || 0);
/* A sentence with its placeholders filled. "{count}" is the value; "{count:page|pages}" is the value and then the
   word for one or for many ("1 page", "3 pages"), the same rule as the server's strings.t(). Give a count as a
   number, not as text: it is written here with the reader's thousands separator. */
function T(key, values) {
  const given = values || {};
  const has = (name) => Object.prototype.hasOwnProperty.call(given, name) && given[name] !== undefined && given[name] !== null;
  const HOLE = /\{(\w+)(?::([^{}]*))?\}/g;
  /* DECISIONS 314: a key this language lacks is said in English; one no table has is "…", never the raw key. */
  let template = state.strings[key] || (state.fallback || {})[key];
  if (!template) { if (window.console) console.warn("Maya Audit: no text for " + key); template = "…"; }
  /* A sentence is never shown with an unfilled hole (the same rule as strings.t()): when a value is missing, the
     sentence's plain form ("<key>.plain") is used if there is one; otherwise the missing value is written "…". */
  const missing = (text) => Array.from(text.matchAll(HOLE)).some((hole) => !has(hole[1]));
  if (missing(template)) {
    const plain = state.strings[key + ".plain"];
    if (plain && !missing(plain)) template = plain;
    else if (window.console) console.warn("Maya Audit: sentence " + key + " was not given every value it needs");
  }
  return template.replace(HOLE, (hole, name, form) => {
    if (!has(name)) return "\u2026";
    const value = given[name], shown = typeof value === "number" ? num(value) : String(value);
    if (!form || form.indexOf("|") < 0) return shown;
    const words = form.split("|");
    return shown + " " + (Number(value) === 1 ? words[0] : words[1]);
  });
}
function money(amount) {
  const value = Number(amount) || 0;
  const digits = (value > 0 && value < 0.1) ? 4 : 2;
  return new Intl.NumberFormat(state.language, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}
function when(stamp, style) {
  if (!stamp) return "";
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return String(stamp);
  return new Intl.DateTimeFormat(state.language, style || { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function duration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  return minutes ? minutes + " " + T("unit.min") + " " + (total % 60) + " " + T("unit.s") : total + " " + T("unit.s");
}
function age(seconds) {
  const hours = Math.round((Number(seconds) || 0) / 3600);
  return hours < 48 ? hours + " " + T("unit.h") : Math.round(hours / 24) + " " + T("unit.d");
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "class") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (["checked", "disabled", "hidden", "open", "selected"].includes(name)) node[name] = Boolean(value);
    else node.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children.flat(3)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
/* The business types as a dropdown (DECISIONS 311): "Otomatik öner" first when offered, Finance as one group. */
function businessSelect(id, choices, value, withAuto, onChange) {
  const select = el("select", { class: "field-input business-select", id });
  if (withAuto) select.append(el("option", { value: "auto", text: T("new.business.auto") }));
  const groups = {};
  for (const choice of choices || []) {
    const option = el("option", { value: choice.id, text: choice.label });
    if (choice.group) {
      if (!groups[choice.group]) { groups[choice.group] = el("optgroup", { label: choice.group_label || choice.group }); select.append(groups[choice.group]); }
      groups[choice.group].append(option);
    } else select.append(option);
  }
  select.value = value || (withAuto ? "auto" : "diger");
  if (onChange) select.addEventListener("change", () => onChange(select.value));
  return select;
}
function add(node, ...children) { node.append(...children.flat(3).filter((c) => c !== null && c !== undefined && c !== false)); return node; }
function fill(node, ...children) { node.replaceChildren(...children.flat(3).filter((c) => c !== null && c !== undefined && c !== false)); return node; }

/* An address from a report becomes a link only when it is plainly http(s); anything else stays text. */
function link(address) {
  let parsed = null;
  try { parsed = new URL(String(address)); } catch (error) { parsed = null; }
  if (!parsed || (parsed.protocol !== "http:" && parsed.protocol !== "https:")) return el("span", { class: "url", text: String(address) });
  return el("a", { class: "url", href: parsed.href, target: "_blank", rel: "noopener noreferrer nofollow", text: String(address) });
}

async function api(method, path, body) {
  const options = { method, headers: {}, credentials: "same-origin" };
  if (method !== "GET") { options.headers["X-Maya-Token"] = state.token; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body === undefined ? {} : body); }
  if (method === "DELETE") { delete options.headers["Content-Type"]; delete options.body; }
  let response;
  try { response = await fetch(API + path, options); } catch (error) { throw new Error(T("error.offline")); }
  let data = null;
  try { data = await response.json(); } catch (error) { data = null; }
  if (!response.ok) {
    const problem = (data && data.error) || {};
    if (response.status === 401 || problem.code === "bad_action_token") { notice(T("error.session")); setTimeout(() => window.location.reload(), 1200); }
    const failure = new Error(problem.message || T("error.request_failed"));
    failure.status = response.status; failure.code = problem.code; failure.details = problem.details || {};
    throw failure;
  }
  return data;
}

function notice(message) {
  const box = $("notice");
  box.textContent = message || "";
  box.hidden = !message;
  if (message) setTimeout(() => { if (box.textContent === message) box.hidden = true; }, 9000);
}
async function guarded(action) {
  try { notice(""); return await action(); } catch (error) { notice(error.message); return null; }
}

/* ---------- history ---------- */

async function loadHistory() {
  const query = $("search").value.trim();
  const data = await guarded(() => api("GET", "/audits?limit=" + state.historyLimit + "&q=" + encodeURIComponent(query) + (state.showHidden ? "&hidden=true" : "")));
  if (!data) return;
  const revised = await guarded(() => api("GET", "/analyses"));
  // DECISIONS 310: revised analyses are their own small section under the audits, one row each (they overlapped).
  const revisedRows = (revised?.analyses || []).filter((item) => !query || String(item.label).toLowerCase().includes(query.toLowerCase()));
  const revisedSection = revisedRows.length ? el("div", { class: "history-section" },
    el("div", { class: "history-heading", text: T("analysis.section") + " (" + num(revisedRows.length) + ")" }),
    revisedRows.map((item) => el("button", { class: "history-open", type: "button", onclick: () => openAudit(item.id) },
      el("span", { class: "history-title", text: item.label }),
      el("span", { class: "history-meta", text: T("analysis.revised") + " · " + when(item.processed_at, { dateStyle: "medium" }) })))) : null;
  const list = $("history");
  // DECISIONS 311: hidden audits are one click away, in their own list; each row can be hidden or shown again.
  const hiddenToggle = data.hidden_total || state.showHidden ? el("button", { class: "button quiet history-hidden", type: "button", "aria-pressed": String(state.showHidden),
    onclick: () => { state.showHidden = !state.showHidden; loadHistory(); } }, state.showHidden ? T("nav.empty.back") : T("nav.hidden", { count: data.hidden_total || 0 })) : null;
  if (!data.audits.length) { fill(list, el("div", { class: "history-empty", text: T(query ? "nav.no_match" : "nav.empty") }), hiddenToggle, revisedSection); return; }
  // Each audit: site, date and time, mode, pages read and how, a plain status and its short ID (DECISIONS 309, 310).
  fill(list, data.audits.map((item) => el("div", { class: "history-item" + (item.id === state.auditId ? " current" : "") },
    el("button", { class: "history-open", type: "button", "aria-current": item.id === state.auditId ? "page" : null, onclick: () => openAudit(item.id) },
      el("span", { class: "history-title", text: item.host }),
      el("span", { class: "history-meta", text: when(item.created_at, { dateStyle: "medium", timeStyle: "short" }) + (item.mode_label ? " · " + item.mode_label : "") }),
      el("span", { class: "history-meta", text: [T("history.pages", { count: item.pages_read || 0 }), item.path_label].filter(Boolean).join(" · ") }),
      el("span", { class: "history-status" }, el("span", { class: "pill status-" + (item.status || item.state), text: item.status_label || item.state_label }),
        el("span", { class: "id", text: item.short_id || "" }))),
    el("div", { class: "history-actions" },
      el("button", { class: "history-hide", type: "button", "aria-label": (item.hidden ? T("nav.unhide") : T("nav.hide.label")) + ": " + item.host,
        title: item.hidden ? T("nav.unhide") : T("nav.hide.label"), onclick: () => hideAudit(item.id, !item.hidden) }, item.hidden ? T("nav.unhide") : T("nav.hide")),
      el("button", { class: "history-delete", type: "button", "aria-label": T("nav.delete") + ": " + item.host, title: T("nav.delete"),
        onclick: () => removeAudit(item.id) }, "✕")))),
    data.total > data.audits.length ? el("button", { class: "button quiet", type: "button", onclick: () => { state.historyLimit += 30; loadHistory(); } }, T("nav.more")) : null,
    hiddenToggle, revisedSection);
}

/* A "?" beside a technical word that has to stay (DECISIONS 310): a button that shows one plain sentence. */
const HINTED = [["canonical", "kanonik"], ["hreflang"], ["noindex"]];
/* DECISIONS 313: the title stays whole; the hints for the terms it uses come after it, in the order they appear. */
function hinted(text) {
  const title = String(text || ""), lower = title.toLowerCase();
  const found = HINTED.map((words) => ({ key: words[0], at: Math.min(...words.map((w) => { const i = lower.indexOf(w); return i < 0 ? Infinity : i; })) }))
    .filter((term) => term.at !== Infinity).sort((a, b) => a.at - b.at);
  return [title, ...found.map((term) => [" ", hint(term.key)])];
}
function hint(key) {
  const tip = el("span", { class: "hint-tip", role: "tooltip", hidden: true, text: T("hint." + key) });
  const button = el("button", { class: "hint", type: "button", "aria-label": T("hint.label", { term: key }), "aria-expanded": "false",
    onclick: (event) => { event.stopPropagation(); tip.hidden = !tip.hidden; button.setAttribute("aria-expanded", String(!tip.hidden)); } }, "?");
  return el("span", { class: "hint-wrap" }, button, tip);
}

async function hideAudit(id, hidden) {
  const answer = await guarded(() => api("PUT", "/audits/" + id + "/hidden", { hidden }));
  if (answer) await loadHistory();
}

async function removeAudit(id) {
  if (!window.confirm(T("nav.delete_confirm"))) return;
  const answer = await guarded(() => api("DELETE", "/audits/" + id));
  if (!answer) return;
  if (state.auditId === id) newAudit(); else await loadHistory();
  // A file another program still holds open stays on disk (Windows): said, never hidden (D-20).
  if (answer.note) notice(answer.note);
}

/* ---------- composer ---------- */

/* The other things a plan may ask for: paid search data, the Google Business Profile of a local business, and archived
   copies as a fallback. Each is a press-to-toggle button; nothing is sent until the plan is started. */
function optionChips(draft, redraw) {
  const chip = (key, on, off) => el("button", { class: "chip", type: "button", "aria-pressed": String(Boolean(draft[key])),
    onclick: () => { draft[key] = !draft[key]; if (key === "search_data" && !draft.search_data) draft.local_business = false; redraw(); } }, T(draft[key] ? on : off));
  return [chip("search_data", "option.search_data.on", "option.search_data.off"),
    draft.search_data ? chip("local_business", "option.local.on", "option.local.off") : null,
    chip("archives", "option.archives.on", "option.archives.off"),
    chip("verify_ownership", "option.verify.on", "option.verify.off")];
}

function drawOptions() {
  const box = $("options");
  // DECISIONS 310: the depth and the extra options are on the New audit card; the composer only asks questions.
  if (state.auditId || $("new-audit-card")) { fill(box); return; }
  const modes = el("div", { class: "chips", role: "radiogroup", "aria-label": T("option.mode") }, state.settings.modes.map((mode) =>
    el("button", { class: "chip", type: "button", role: "radio", "aria-checked": String(state.draft.mode === mode.id),
      onclick: () => { state.draft.mode = mode.id; drawOptions(); } }, mode.label)));
  const backlinks = el("button", { class: "chip", type: "button", "aria-pressed": String(state.draft.backlinks),
    onclick: () => { state.draft.backlinks = !state.draft.backlinks; drawOptions(); } },
    T(state.draft.backlinks ? "option.backlinks.on" : "option.backlinks.off"));
  fill(box, modes, backlinks, optionChips(state.draft, drawOptions));
}

function closeStream() {
  if (state.source) { state.source.close(); state.source = null; }
  if (state.ticker) { clearInterval(state.ticker); state.ticker = null; }
}

function bubble(role, text, items) {
  const body = el("div", { class: "bubble" }, el("p", { text }));
  if (items && items.length) body.append(el("ul", {}, items.map((item) => el("li", { text: item }))));
  return el("div", { class: "msg " + role }, body);
}
function say(node) { const thread = $("thread"); thread.append(node); thread.scrollTop = thread.scrollHeight; return node; }

function newAudit() {
  closeStream();
  state.auditId = null;
  closeDrawer();
  $("page-title").textContent = T("welcome.title");
  $("input").placeholder = T("composer.placeholder.new");
  const address = el("input", { class: "field-input big", type: "text", id: "new-url", autocomplete: "off", spellcheck: "false",
    placeholder: T("new.placeholder"), "aria-describedby": "new-url-error" });
  const problem = el("p", { class: "field-error", id: "new-url-error", role: "alert", hidden: true });
  const go = () => {
    const value = address.value.trim();
    if (!value) { problem.textContent = T("new.error.address"); problem.hidden = false; address.classList.add("bad"); address.focus(); return; }
    problem.hidden = true; address.classList.remove("bad");
    send(value);
  };
  address.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); go(); } });
  const modes = el("div", { class: "modes", role: "radiogroup", "aria-label": T("new.depth") });
  const typicalLine = el("p", { class: "muted small" });
  const drawModes = () => {
    fill(modes, state.settings.modes.map((mode) => el("button", { class: "mode-card" + (state.draft.mode === mode.id ? " on" : ""), type: "button", role: "radio",
      "aria-checked": String(state.draft.mode === mode.id), onclick: () => { state.draft.mode = mode.id; drawModes(); } },
      el("strong", { text: T("new.mode." + mode.id) }), el("span", { class: "muted small", text: T("new.mode." + mode.id + ".about") }),
      mode.typical ? el("span", { class: "small", text: mode.typical.short }) : null)));
    const chosen = state.settings.modes.find((mode) => mode.id === state.draft.mode);
    typicalLine.textContent = chosen && chosen.typical ? T("new.time", { label: chosen.typical.label }) : "";
  };
  const extrasBox = el("div", { class: "chips" });
  const drawExtras = () => fill(extrasBox,
    el("button", { class: "chip", type: "button", "aria-pressed": String(state.draft.backlinks), onclick: () => { state.draft.backlinks = !state.draft.backlinks; drawExtras(); } },
      T(state.draft.backlinks ? "option.backlinks.on" : "option.backlinks.off")), optionChips(state.draft, drawExtras));
  drawModes(); drawExtras();
  const business = businessSelect("new-business", state.settings.business_types, state.draft.business_type, true,
    (value) => { state.draft.business_type = value; });
  const card = el("section", { class: "card new-audit", id: "new-audit-card", "aria-labelledby": "new-url-label" },
    el("label", { class: "field-label", for: "new-url", id: "new-url-label", text: T("new.address") }), address, problem,
    el("div", { class: "field-label", text: T("new.depth") }), modes, typicalLine,
    el("label", { class: "field-label", for: "new-business", text: T("new.business") }), business,
    el("p", { class: "muted small", text: T("new.business.help") }),
    el("details", { class: "extras" }, el("summary", { text: T("new.extras") }), extrasBox),
    el("div", { class: "row" }, el("button", { class: "button primary big", type: "button", onclick: go }, T("new.go")),
      el("span", { class: "muted small", text: T("new.go.note") })));
  const chips = el("div", { class: "chips" },
    (state.settings.demo_sites || []).map((site) => el("button", { class: "chip", type: "button", title: site.about,
      onclick: () => { address.value = site.address; address.focus(); } }, T("chip.demo", { site: site.address }))),
    el("button", { class: "chip", type: "button", onclick: () => { say(bubble("user", T("chip.how"))); say(bubble("assistant", T("help.how"))); } }, T("chip.how")),
    el("button", { class: "chip", type: "button", onclick: () => { say(bubble("user", T("chip.what"))); say(bubble("assistant", T("help.what"))); } }, T("chip.what")));
  fill($("thread"), el("div", { class: "welcome" }, el("h2", { text: T("welcome.title") }), el("p", { text: T("welcome.body") }), card, chips));
  $("composer").hidden = true;
  drawOptions();
  loadHistory();
  address.focus();
}

async function send(text) {
  const value = (text || "").trim();
  if (!value) return;
  $("input").value = "";
  if (state.auditId) {
    say(bubble("user", value));
    const data = await guarded(() => api("POST", "/audits/" + state.auditId + "/messages", { text: value }));
    if (data) say(answer(data.messages[data.messages.length - 1].body));
    return;
  }
  say(bubble("user", value));
  await proposePlan({ url: value, mode: state.draft.mode, backlinks: state.draft.backlinks, search_data: state.draft.search_data, local_business: state.draft.local_business, archives: state.draft.archives, verify_ownership: state.draft.verify_ownership, business_type: state.draft.business_type || "auto", key_pages: [] }, value, true);
}

/* ---------- plan ---------- */

async function proposePlan(request, message, prefill) {
  let body = request;
  try {
    let plan = await api("POST", "/plans", body);
    if (prefill) {  // important pages the person saved for this site are offered, and can be edited before starting
      const profile = await guarded(() => api("GET", "/projects/" + encodeURIComponent(plan.project_id) + "/profile"));
      if (profile && profile.key_pages.length) {
        body = Object.assign({}, request, { key_pages: profile.key_pages });
        plan = await api("POST", "/plans", body);
        plan.prefilled = true;
      }
    }
    say(planCard(plan, body, message));
  } catch (error) {
    say(bubble("assistant", error.message));
  }
}

function facts(rows) {
  return el("dl", { class: "facts" }, rows.filter(Boolean).map(([label, value]) => [el("dt", { text: label }),
    el("dd", {}, Array.isArray(value) ? el("ul", {}, value.map((line) => el("li", { text: line }))) : value)]));
}

function paidBox(cost, onConfirm, confirmed, onBalance) {
  if (!cost.requested) return el("p", { class: "muted small", text: T("paid.off") });
  const box = el("div", { class: "paid" }, el("h3", { text: cost.needs_confirmation || confirmed ? T("paid.title") : T("paid.title.auto", { limit: cost.limits ? money(cost.limits.confirm_usd) : undefined }) }), el("p", { text: T("paid.explain") }));
  const table = el("table", {}, el("caption", { class: "visually-hidden", text: T("plan.label.cost") }));
  for (const call of cost.calls || []) {
    const price = call.state === "paid" ? "$" + money(call.estimate_usd)
      : call.state === "cached" ? T("paid.cached", { age: age(call.cache_age_s) }) : call.state === "not_sent" ? T("paid.not_sent") : call.state;
    table.append(el("tr", {}, el("td", {}, call.purpose || call.title, " ", el("span", { class: "muted small", text: call.target || "" })), el("td", { text: price })));
  }
  box.append(table, el("p", { class: "total", text: T("paid.total", { total: money(cost.total_usd) }) }));
  /* What each DataForSEO API would cost, that the SERP API is not called, and the three limits, before Start. The
     amount is its own element: the sentence is cut where the amount goes, and nothing is ever built as markup. */
  const MARK = "\u0001";
  for (const service of cost.by_service || []) {
    const [before, after] = T("paid.by_service.row", { service: service.service, requests: Number(service.requests) || 0, usd: MARK }).split(MARK);
    box.append(el("p", { class: "small service" }, before, el("strong", { text: money(service.usd) }), after || ""));
  }
  if (cost.limits) {
    if (!cost.serp_api_calls) box.append(el("p", { class: "small", text: T("paid.serp_zero") }));
    box.append(el("p", { class: "small", text: T("paid.limits", { confirm: money(cost.limits.confirm_usd), cap: money(cost.limits.audit_cap_usd), daily: money(cost.limits.daily_usd) }) }));
  }
  if (cost.over_audit_cap) box.append(el("p", { class: "error-text", text: cost.over_audit_cap.message }));
  const budget = cost.budget || {};
  if (budget.spent_today_usd !== null && budget.spent_today_usd !== undefined) {
    box.append(el("p", { class: "small", text: T("paid.today", { spent: money(budget.spent_today_usd), cap: money(budget.daily_cap_usd),
      remaining: money(budget.remaining_today_usd), reset: when(budget.resets_at, { timeStyle: "short", dateStyle: "short" }) }) }));
  }
  const balance = el("p", { class: "small" });
  const showBalance = (info) => fill(balance, info && info.known ? T("paid.balance.known", { balance: money(info.balance_usd), when: when(info.checked_at) }) : (info && info.message) || T("paid.balance.unknown"),
    " ", el("button", { class: "chip", type: "button", onclick: async () => { const fresh = await guarded(() => api("POST", "/budget/provider-balance")); if (fresh) { showBalance(fresh); if (onBalance) onBalance(); } } }, T("paid.balance.check")));
  showBalance(cost.provider_balance);
  box.append(balance);
  if (cost.blocked) box.append(el("p", { class: "error-text", text: cost.blocked.message }));
  else if (confirmed) box.append(el("p", { class: "ok-text", text: T("paid.confirmed", { total: money(confirmed) }) }));
  else if (cost.needs_confirmation && onConfirm) box.append(el("div", { class: "row" }, el("button", { class: "button pay", type: "button", onclick: onConfirm }, T("paid.confirm", { total: money(cost.total_usd) }))));
  else if (!cost.needs_confirmation) box.append(el("p", { text: T("paid.nothing_to_pay") }));
  return box;
}

/* Firecrawl on the plan card: off unless ticked here, for this audit only. Every change makes a new plan; nothing is sent. */
function firecrawlBox(plan, request, live, replan) {
  const reader = plan.firecrawl;
  if (!reader) return null;
  const id = "f" + plan.id.slice(0, 8), options = reader.options || {};
  const box = el("div", { class: "paid" }, el("h3", { text: T("fc.title") }));
  if (!reader.available) { box.append(el("p", { class: "muted small", text: T("fc.unavailable") })); return box; }
  const on = el("input", { type: "checkbox", id: id + "-on", checked: reader.requested, disabled: !live });
  const owner = el("input", { type: "checkbox", id: id + "-owner", checked: reader.requested && options.owner_approved_bypass, disabled: !live });
  const render = el("input", { type: "checkbox", id: id + "-render", checked: reader.requested && options.render_fallback, disabled: !live });
  const cap = el("input", { class: "field-input", type: "number", id: id + "-cap", min: 1, max: reader.max_pages_limit, step: 1, disabled: !live });
  cap.value = options.max_pages || 50;
  const proxy = el("select", { class: "field-input", id: id + "-proxy", disabled: !live }, reader.proxies.map((name) => el("option", { value: name, selected: name === options.proxy }, name)));
  const update = () => replan(Object.assign({}, request, { firecrawl: on.checked, firecrawl_render: on.checked && render.checked,
    firecrawl_max_pages: Math.max(1, Math.min(reader.max_pages_limit, Number(cap.value) || 50)),
    firecrawl_owner_approved: on.checked && owner.checked, firecrawl_proxy: on.checked && owner.checked ? proxy.value : "basic" }));
  on.addEventListener("change", update);
  box.append(el("p", {}, on, " ", el("label", { for: id + "-on" }, el("strong", { text: T("fc.toggle") }))), el("p", { class: "muted small", text: T("fc.toggle.help") }));
  if (!reader.requested) return box;
  box.append(el("ul", { class: "list" }, reader.lines.map((line) => el("li", { text: line }))));
  if (live) {
    owner.addEventListener("change", update);
    add(box, el("div", { class: "pair" }, el("div", {}, el("label", { class: "label", for: id + "-cap", text: T("fc.max_pages") }), cap),
      options.owner_approved_bypass ? el("div", {}, el("label", { class: "label", for: id + "-proxy", text: T("fc.proxy") }), proxy) : null),
      el("p", {}, owner, " ", el("label", { for: id + "-owner", text: T("fc.owner") })), el("p", { class: "muted small", text: T("fc.owner.help") }),
      reader.render_fallback_offered ? el("p", {}, render, " ", el("label", { for: id + "-render", text: T("fc.render") })) : null,
      el("div", { class: "row" }, el("button", { class: "button", type: "button", onclick: update }, T("fc.update"))));
  }
  box.append(el("p", { class: "total", text: reader.cost_line }));
  if (reader.spent_today_credits !== null && reader.spent_today_credits !== undefined) box.append(el("p", { class: "small",
    text: T("fc.today", { spent: num(reader.spent_today_credits), daily: num(reader.daily_credits), remaining: num(reader.remaining_today_credits) }) }));
  if (reader.blocked) box.append(el("p", { class: "error-text", text: reader.blocked.message }));
  else if (plan.confirmation && plan.confirmation.approved_max_credits) box.append(el("p", { class: "ok-text", text: T("fc.confirmed", { credits: num(plan.confirmation.approved_max_credits) }) }));
  return box;
}

/* Fast check and the links to other sites (DECISIONS 219): two switches on the plan card. Each change makes a new plan;
   nothing is sent. Labels and help come from the plan itself and are set as text, never as markup. */
function switchesBox(plan, request, live, replan) {
  const switches = plan.switches;
  if (!switches) return null;
  const id = "s" + plan.id.slice(0, 8);
  const fast = el("input", { type: "checkbox", id: id + "-fast", checked: Boolean(switches.fast_check), disabled: !live });
  const external = el("input", { type: "checkbox", id: id + "-external", checked: switches.external_links !== false, disabled: !live });
  const update = () => replan(Object.assign({}, request, { fast_check: fast.checked, external_links: external.checked }));
  fast.addEventListener("change", update);
  external.addEventListener("change", update);
  return el("div", { class: "switches" },
    el("p", {}, fast, " ", el("label", { for: id + "-fast", text: switches.fast_label })), el("p", { class: "muted small", text: switches.fast_help }),
    el("p", {}, external, " ", el("label", { for: id + "-external", text: switches.external_label })), el("p", { class: "muted small", text: switches.external_help }));
}

function planFacts(plan) {
  return facts([[T("plan.label.site"), plan.target.note ? [plan.target.url, plan.target.note] : plan.target.url], [T("plan.label.scope"), plan.scope_label || T("plan.scope", { mode: plan.mode_label, cap: num(plan.page_cap) })],
    plan.key_pages.length ? [T("plan.key_pages.label"), plan.key_pages] : null,
    [T("plan.label.rendering"), plan.rendering.label], [T("plan.label.time"), plan.duration.label],
    [T("plan.label.included"), plan.included], [T("plan.label.optional"), plan.optional],
    [T("plan.label.unavailable"), plan.unavailable], [T("plan.label.limits"), plan.limitations]]);
}

/* DECISIONS 311: on the plan, the business type asked for, with the suggestion of this site's last audit (or "once the
   homepage is read": the plan itself requests nothing). Changing it makes a new plan; nothing is sent. */
function businessRow(plan, live, onChange) {
  const info = plan.business_type;
  if (!info) return null;
  const id = "pb" + plan.id.slice(0, 8);
  return el("div", { class: "business-row" },
    el("label", { class: "label", for: id, text: T("plan.business.label") }),
    businessSelect(id, info.choices, info.chosen, true, live ? onChange : null),
    el("p", { class: "muted small", text: info.line }));
}

function planCard(plan, request, message) {
  const card = el("section", { class: "card", "aria-label": T("plan.title") });
  const draw = (current, problem) => {
    const live = !current.audit_id && !current.expired;
    /* DECISIONS 310: the plan in three plain lines and one Start button; the full plan (facts, business, markets,
       Firecrawl, switches, costs) is folded under "Planın ayrıntıları" and opens by itself when it needs an answer. */
    const typical = (current.duration || {}).typical;
    const more = el("details", { class: "plan-more", open: Boolean(problem || current.needs_confirmation || (current.firecrawl && current.firecrawl.needs_confirmation) || current.balance_warning) },
      el("summary", { text: T("plan.more") }));
    fill(card, el("h2", { text: T("plan.title") + ": " + current.target.host }),
      el("ul", { class: "plan-short" }, el("li", { text: T("plan.pages", { cap: num(current.page_cap) }) }), typical ? el("li", { text: T("plan.time", { label: typical.label }) }) : null,
        el("li", { text: [current.paid && current.paid.total_usd ? T("plan.cost.short", { total: money(current.paid.total_usd) }) : null,
          current.firecrawl && current.firecrawl.requested && current.firecrawl.max_credits ? T("plan.cost.credits", { credits: num(current.firecrawl.max_credits) }) : null]
          .filter(Boolean).join(" · ") || T("plan.cost.free") })),
      businessRow(current, live, (value) => replan(Object.assign({}, request, { business_type: value }), false)),
      more);
    more.append(planFacts(current));
    if (current.prefilled) more.append(el("p", { class: "muted small", text: T("plan.key_pages.from_profile") }));
    const business = current.business || {};
    const search = current.search_data || {};
    const bid = "b" + current.id.slice(0, 8);
    const brandInput = el("input", { class: "field-input", type: "text", id: bid + "-brand", maxlength: 120 });
    const countryInput = el("input", { class: "field-input", type: "text", id: bid + "-country", maxlength: 80 });
    brandInput.value = business.brand_name || ""; countryInput.value = business.country || "";
    /* Other domains of the same brand, as host names. The server checks every one; nothing typed here is put into the
       page as markup (el() sets text and values only). */
    const familyInput = el("input", { class: "field-input", type: "text", id: bid + "-family", maxlength: 600, placeholder: "other-shop.example" });
    const plannedFamily = current.brand_family_domains || [];
    familyInput.value = plannedFamily.join(", ");
    const familyList = () => familyInput.value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
    const sameFamily = () => familyList().join(",") === plannedFamily.join(",");
    const updating = el("p", { class: "muted small", role: "status" });
    let start = null, busy = false;
    /* The brand and country on the card are the run's: the plan is made again with them whenever one changes, and
       Start waits for the new plan. The saved profile is updated first, so a later plan for this site begins from them. */
    const sameBusiness = () => brandInput.value.trim() === (business.brand_name || "").trim() && countryInput.value.trim() === (business.country || "").trim() && sameFamily();
    const saveBusiness = async (brandName, country, family) => {
      const project = "/projects/" + encodeURIComponent(current.project_id) + "/profile";
      const saved = await api("GET", project);
      /* An unedited suggestion is never saved as the brand (DECISIONS 220): the saved name is kept as it was. */
      await api("PUT", project, { brand_name: brandName !== undefined ? brandName : (saved.brand_name || ""), industry: saved.industry, goals: saved.goals, languages: saved.languages, key_pages: saved.key_pages,
        brand_family_domains: family || [],
        countries: country ? [country].concat(saved.countries.filter((item) => item !== country)) : [] });
    };
    const replan = async (body, save) => {
      if (busy) return;
      busy = true;
      if (start) start.disabled = true;
      updating.textContent = T("plan.market.updating");
      try {
        if (save) await saveBusiness(body.brand_name, body.country, body.brand_family_domains);
        const next = await api("POST", "/plans", body);
        request = body;
        draw(Object.assign(next, { prefilled: current.prefilled }));
      } catch (error) { draw(current, error.message); }
    };
    /* The brand is sent only when the person edited it (DECISIONS 220): the suggestion from the address, posted back
       unchanged, would read as a typed and confirmed name. */
    const brandEdited = () => Boolean(business.brand_confirmed) || brandInput.value.trim() !== (business.brand_name || "").trim();
    const withBusiness = (extra) => {
      const body = Object.assign({}, request, { country: countryInput.value.trim(), brand_family_domains: familyList() }, extra || {});
      if (brandEdited()) body.brand_name = brandInput.value.trim(); else delete body.brand_name;
      return body;
    };
    const businessChanged = () => { if (!sameBusiness()) replan(withBusiness({ market_default_accepted: false }), true); };
    if (live) {
      brandInput.addEventListener("change", businessChanged);
      countryInput.addEventListener("change", businessChanged);
      familyInput.addEventListener("change", businessChanged);
      /* While a field holds something the plan does not, Start is off: the plan on screen is not the one that would run. */
      const typing = () => { if (start) start.disabled = !current.can_start || !sameBusiness(); };
      brandInput.addEventListener("input", typing);
      countryInput.addEventListener("input", typing);
      familyInput.addEventListener("input", typing);
      more.append(el("h3", { text: T("plan.label.business") }), el("div", { class: "pair" },
        el("div", {}, el("label", { class: "label", for: bid + "-brand", text: T("plan.business.brand") }), brandInput),
        el("div", {}, el("label", { class: "label", for: bid + "-country", text: T("plan.business.country") }), countryInput)),
        el("p", { class: "muted small", text: business.note || "" }),
        el("div", {}, el("label", { class: "label", for: bid + "-family", text: T("plan.brand_family") }), familyInput,
          el("p", { class: "muted small", text: T("plan.brand_family.help") })), updating);
    }
    /* The market of each paid panel, in plain lines: search data, ChatGPT (always United States), backlinks (none),
       and where a suggested country came from. */
    if ((search.markets || []).length) more.append(el("ul", { class: "list" }, search.markets.map((line) => el("li", { text: line.text }))));
    if (live && search.requested && !search.market_known) {
      const accept = el("input", { type: "checkbox", id: bid + "-default", checked: Boolean(search.market_default_accepted) });
      accept.addEventListener("change", () => replan(withBusiness({ market_default_accepted: accept.checked }), !sameBusiness()));
      add(card, search.market_block ? el("p", { class: "notice", role: "alert", text: search.market_block.message }) : null,
        el("p", {}, accept, " ", el("label", { for: bid + "-default", text: search.market_default_label || T("plan.market.accept_default") })));
    }
    // One approval per plan. When Firecrawl is part of it, a single button below approves both maximums, each exact.
    const pending = current.to_confirm || {};
    const confirm = async () => {
      const approval = {};
      if (pending.approved_max_usd !== null && pending.approved_max_usd !== undefined) approval.approved_max_usd = pending.approved_max_usd;
      if (pending.approved_max_credits !== null && pending.approved_max_credits !== undefined) approval.approved_max_credits = pending.approved_max_credits;
      try { draw(Object.assign(await api("POST", "/plans/" + current.id + "/confirm", approval), { prefilled: current.prefilled })); }
      catch (error) { draw(current, error.message); }
    };
    const both = Boolean(current.firecrawl && current.firecrawl.needs_confirmation);
    const reread = async () => { const fresh = await guarded(() => api("GET", "/plans/" + current.id)); if (fresh) draw(Object.assign(fresh, { prefilled: current.prefilled })); };
    add(more, el("h3", { text: T("plan.label.cost") }), paidBox(current.paid, live && !both ? confirm : null, current.confirmation && current.confirmation.approved_max_usd, live ? reread : null),
      search.brand_warning ? el("p", { class: "lead small", role: "note", text: search.brand_warning }) : null);
    add(more, firecrawlBox(current, request, live, (body) => replan(body, false)));
    add(more, switchesBox(current, request, live, (body) => replan(body, false)));
    if (live && both && current.needs_confirmation) card.append(el("div", { class: "row" }, el("button", { class: "button pay", type: "button", onclick: confirm }, pending.label)));
    if (problem) card.append(el("p", { class: "error-text", role: "alert", text: problem }));
    if (current.expired) card.append(el("p", { class: "error-text", text: T("plan.expired") }));
    if (current.audit_id) { card.append(el("p", { class: "muted", text: T("plan.started") })); return; }
    /* The account's balance may not cover this plan: said plainly above Start, and Start then asks once how to run. */
    const warning = live ? current.balance_warning : null;
    if (warning) card.append(el("p", { class: "notice", role: "alert", text: warning.message }));
    const editor = el("div", { class: "editor", hidden: true });
    const choices = el("div", { class: "row", hidden: true });
    const begin = async (choice) => {
      start.disabled = true;
      choices.hidden = true;
      const body = { plan_id: current.id, message };
      if (choice) body.balance_choice = choice;
      try { const audit = await api("POST", "/audits", body); openAudit(audit.id); }
      catch (error) {
        if (error.code === "plan_changed" || error.code === "balance_decision_required" || error.code === "balance_choice_not_offered") {
          const fresh = await guarded(() => api("GET", "/plans/" + current.id));
          draw(Object.assign(fresh || current, { prefilled: current.prefilled }), error.message);
        } else draw(current, error.message);
      }
    };
    start = el("button", { class: "button primary", type: "button", disabled: !current.can_start, onclick: () => {
      if (!sameBusiness()) { businessChanged(); return; }
      if (!warning) { begin(null); return; }
      start.disabled = true;
      fill(choices, warning.choices.map((choice) => el("button", { class: "button" + (choice.id === "without_search_data" ? " primary" : ""), type: "button", onclick: () => begin(choice.id) }, choice.label)),
        el("button", { class: "button", type: "button", onclick: () => { choices.hidden = true; start.disabled = !current.can_start; } }, T("plan.balance.choice.cancel")));
      choices.hidden = false;
    } }, T("plan.start"));
    card.append(el("div", { class: "row" }, start, el("button", { class: "button", type: "button", "aria-expanded": "false",
      onclick: (event) => { editor.hidden = !editor.hidden; event.target.setAttribute("aria-expanded", String(!editor.hidden)); if (!editor.hidden) buildEditor(editor, current, request, (next, body) => { request = body; draw(next); }); } }, T("plan.change"))), choices, editor);
  };
  draw(plan);
  return card;
}

function buildEditor(box, plan, request, onUpdate) {
  const options = plan.paid_options || {};
  const draft = { mode: plan.mode, backlinks: Boolean(options.backlinks), search_data: Boolean(options.search_data), local_business: Boolean(options.local_business), archives: Boolean(plan.archives), verify_ownership: Boolean(plan.ownership && plan.ownership.requested) };
  const id = "e" + plan.id.slice(0, 8);
  const pages = el("textarea", { rows: 3, id: id + "-pages", placeholder: "/pricing" });
  pages.value = plan.key_pages.join("\n");
  const modes = el("div", { class: "chips", role: "radiogroup", "aria-label": T("option.mode") });
  const drawModes = () => fill(modes, state.settings.modes.map((mode) => el("button", { class: "chip", type: "button", role: "radio",
    "aria-checked": String(draft.mode === mode.id), onclick: () => { draft.mode = mode.id; drawModes(); } }, mode.label)),
    el("button", { class: "chip", type: "button", "aria-pressed": String(draft.backlinks), onclick: () => { draft.backlinks = !draft.backlinks; drawModes(); } },
      T(draft.backlinks ? "option.backlinks.on" : "option.backlinks.off")), optionChips(draft, () => drawModes()));
  drawModes();
  const problem = el("p", { class: "error-text", role: "alert" });
  fill(box, modes, el("label", { for: id + "-pages", text: T("plan.key_pages.label") }), el("p", { class: "muted small", text: T("plan.key_pages.help") }), pages,
    el("div", { class: "row" }, el("button", { class: "button primary", type: "button", onclick: async () => {
      const body = Object.assign({}, request, { mode: draft.mode, backlinks: draft.backlinks, search_data: draft.search_data, local_business: draft.local_business, archives: draft.archives, verify_ownership: draft.verify_ownership, key_pages: pages.value.split("\n").map((line) => line.trim()).filter(Boolean) });
      try { onUpdate(await api("POST", "/plans", body), body); } catch (error) { problem.textContent = error.message; }
    } }, T("plan.update"))), problem, profileForm(plan.project_id, id));
}

function profileForm(projectId, id) {
  const box = el("details", {}, el("summary", { text: T("profile.title") }));
  const inner = el("div", {}, el("p", { class: "muted small", text: T("profile.help") }));
  box.append(inner);
  box.addEventListener("toggle", async () => {
    if (!box.open || inner.dataset.ready) return;
    inner.dataset.ready = "1";
    const profile = await guarded(() => api("GET", "/projects/" + encodeURIComponent(projectId) + "/profile"));
    if (!profile) return;
    const fields = {};
    for (const name of ["brand_name", "industry", "goals", "countries", "languages"]) {
      fields[name] = el("input", { class: "field-input", type: "text", id: id + "-" + name, maxlength: 300 });
      fields[name].value = Array.isArray(profile[name]) ? profile[name].join(", ") : profile[name];
      inner.append(el("label", { for: id + "-" + name, text: T("profile." + name) }), fields[name]);
    }
    for (const name of ["brand_aliases", "related_organizations"]) {
      fields[name] = el("textarea", { rows: 3, id: id + "-" + name, maxlength: 3630 });
      fields[name].value = (profile[name] || []).join("\n");
      inner.append(el("label", { for: id + "-" + name, text: T("profile." + name) }), fields[name],
        el("p", { class: "muted small", text: T("profile.confirmed_names.help") }));
    }
    fields.key_pages = el("textarea", { rows: 3, id: id + "-pkeys" });
    fields.key_pages.value = profile.key_pages.join("\n");
    const status = el("span", { class: "ok-text", role: "status" });
    const list = (value) => value.split(",").map((part) => part.trim()).filter(Boolean);
    inner.append(el("label", { for: id + "-pkeys", text: T("profile.key_pages") }), fields.key_pages, el("div", { class: "row" },
      el("button", { class: "button", type: "button", onclick: async () => {
        const saved = await guarded(() => api("PUT", "/projects/" + encodeURIComponent(projectId) + "/profile", {
          brand_name: fields.brand_name.value, industry: fields.industry.value, goals: list(fields.goals.value), countries: list(fields.countries.value),
          brand_aliases: fields.brand_aliases.value.split("\n").map(x => x.trim()).filter(Boolean),
          related_organizations: fields.related_organizations.value.split("\n").map(x => x.trim()).filter(Boolean),
          languages: list(fields.languages.value), key_pages: fields.key_pages.value.split("\n").map((line) => line.trim()).filter(Boolean) }));
        status.textContent = saved ? T("profile.saved") : "";
      } }, T("profile.save")), status));
  });
  return box;
}

/* ---------- audit ---------- */

async function openAudit(id) {
  const data = await guarded(() => api("GET", "/audits/" + id + "/conversation"));
  if (!data) return;
  closeStream();
  closeDrawer();
  state.auditId = id;
  window.history.replaceState(null, "", data.audit.analysis ? "#analysis="+encodeURIComponent(id) : location.pathname);
  $("page-title").textContent = data.audit.host;
  $("input").placeholder = T("composer.placeholder.ask");
  $("composer").hidden = false;
  drawOptions();
  // DECISIONS 310: a finished audit's plan is folded into "how the audit ran"; while it runs, it stays on top.
  const folded = !data.audit.active && !["failed", "stopped", "interrupted"].includes(data.audit.state);
  let planNode = null;
  const nodes = data.messages.map((message) => {
    if (message.role === "user") return folded ? null : bubble("user", message.body.text);
    if (message.kind === "plan" && folded && message.plan) { planNode = el("div", {}, el("h4", { text: T("plan.title") }), planFacts(message.plan)); return null; }
    if (message.kind === "plan") return message.plan ? el("section", { class: "card", "aria-label": T("plan.title") }, el("h2", { text: T("plan.title") + ": " + message.plan.target.host }),
      el("details", {}, el("summary", { text: message.plan.scope_label || T("plan.scope", { mode: message.plan.mode_label, cap: num(message.plan.page_cap) }) }), el("div", {}, planFacts(message.plan),
        paidBox(message.plan.paid, null, message.plan.confirmation && message.plan.confirmation.approved_max_usd)))) : null;
    if (message.kind === "audit") return auditCard(data.audit, planNode);
    return answer(message.body);
  }).filter(Boolean);
  fill($("thread"), nodes);
  $("thread").scrollTop = 0;
  loadHistory();
}

function answer(body) {
  const node = bubble("assistant", body.text || "", body.items);
  const inner = node.firstChild;
  if (body.finding_ids && body.finding_ids.length) {
    inner.append(el("div", { class: "row" }, body.finding_ids.map((id, index) => el("button", { class: "chip", type: "button",
      onclick: (event) => openEvidence(id, event.currentTarget) }, T("result.evidence") + " " + (index + 1)))));
  }
  if (body.card && body.card.type === "action_plan") { const slot = el("div"); inner.append(slot); showPlan(slot, body.card.role || ""); }
  if (body.card && body.card.type === "comparison") { const slot = el("div"); inner.append(slot); showComparison(slot); }
  if (body.card && body.card.type === "findings") { const slot = el("div"); inner.append(slot); findingsBrowser(slot, { severity: (body.card.severity || []).join(",") }); }
  if (body.suggestions && body.suggestions.length) inner.append(el("div", { class: "chips row" }, body.suggestions.map((question) =>
    el("button", { class: "chip", type: "button", onclick: () => send(question) }, question))));
  return node;
}

function auditCard(audit, planNode) {
  const card = el("section", { class: "card", "aria-label": audit.host });
  const head = el("div"), body = el("div"), log = el("div", { class: "log", "aria-live": "off" }), result = el("div");
  const logBox = el("details", { hidden: true }, el("summary", { text: T("job.log") }), log);
  card.append(head, body, logBox, result);
  let current = audit, shown = null;
  const elapsed = el("span");
  const tick = () => { if (current.active && current.started_at) elapsed.textContent = T("job.elapsed", { time: duration((Date.now() - new Date(current.started_at).getTime()) / 1000) }); };

  const draw = () => {
    // DECISIONS 310: while it runs, the site, the time left and the steps in plain words; once finished, one line.
    fill(head, current.active
      ? el("div", {}, el("h2", {}, T("job.running.title", { host: current.host }), " ", el("span", { class: "pill", text: current.mode_label })),
          current.started_at ? el("p", { class: "muted small", text: T("job.running.note", { time: when(current.started_at, { timeStyle: "short" }) }) }) : null)
      : el("div", { class: "row job-line" }, el("strong", { text: current.host }), el("span", { class: "muted small", text: [when(current.started_at || current.created_at, { dateStyle: "medium", timeStyle: "short" }), current.mode_label].filter(Boolean).join(" · ") }),
          el("span", { class: "state " + current.state, text: current.state_label }), el("span", { class: "id", text: String(current.id).slice(0, 8) })));
    const c = current.counters;
    const bar = el("div"); bar.style.width = Math.min(100, Math.round(100 * (c.pages_checked || 0) / Math.max(1, c.page_cap))) + "%";
    const parts = [el("ol", { class: "timeline" }, current.timeline.map((step) => el("li", { class: step.status, title: step.reason || "" },
      el("strong", { text: step.label }), el("span", { class: "small", text: step.status_label }))))];
    const continuing = Boolean(current.active && current.firecrawl && current.firecrawl.continuing);
    if (continuing) parts.push(el("p", { class: "busy", role: "status", text: T("fc.offer.running") }));
    else if (current.active || current.can_resume || current.state === "failed") {
      parts.push(current.state === "queued" ? el("p", { text: T("job.queued.note") }) : null,
        el("div", { class: "meter", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": c.page_cap, "aria-valuenow": c.pages_checked || 0, "aria-label": T("result.pages") }, bar),
        c.firecrawl_cap ? el("p", {}, T("job.pages.maya", { checked: num(c.pages_checked), cap: num(c.page_cap) }),
            c.maya_gap_s != null ? " · " + T("job.pace.maya", { gap: num(c.maya_gap_s) }) : "", " ", el("span", { class: "muted small", text: c.page_cap_note }))
          : el("p", {}, T("job.pages", { checked: num(c.pages_checked), cap: num(c.page_cap) }), " ", el("span", { class: "muted small", text: c.page_cap_note })),
        // Each reader's own pace (DECISIONS 295): Maya's gap from this computer, Firecrawl's requests at once and gap.
        c.firecrawl_cap ? el("p", {}, c.firecrawl_gap_s != null
          ? T("job.pace.firecrawl", { read: num(c.firecrawl_read || 0), cap: num(c.firecrawl_cap), at_once: num(c.firecrawl_at_once || 1), gap: num(c.firecrawl_gap_s) })
          : T("job.pages.firecrawl", { read: num(c.firecrawl_read || 0), cap: num(c.firecrawl_cap), at_once: num(c.firecrawl_at_once || 1) })) : null,
        el("p", { class: "muted small", text: T("job.other", { count: num(c.other_fetches) }) + " · " + T("job.requests", { count: num(c.requests_sent) }) }),
        current.active ? el("p", { class: "small" }, elapsed, current.eta.label ? " · " + current.eta.label : "") : null,
        current.current_url ? el("p", { class: "url muted", text: current.current_url }) : null,
        current.state_note ? el("p", { text: current.state_note }) : null,
        current.address_note ? el("p", { class: "muted small", text: current.address_note }) : null,
        current.error ? el("p", { class: "error-text", text: current.error.message }) : null);
    }
    const resumeSlot = el("div");
    const actions = [el("div", { class: "row" },
      current.can_stop ? el("button", { class: "button danger", type: "button", onclick: async () => { const next = await guarded(() => api("POST", "/audits/" + current.id + "/stop")); if (next) { current = next; if (next.note) addLog(next.note); draw(); } } }, T("job.stop")) : null,
      current.can_stop ? el("span", { class: "muted small", text: T("job.stop.explain") }) : null,
      current.can_resume ? el("button", { class: "button primary", type: "button", onclick: () => resumeDialog(resumeSlot) }, T("job.resume")) : null), resumeSlot];
    if (current.active) {
      const read = Math.max(c.pages_checked || 0, c.firecrawl_read || 0);
      bar.style.width = Math.min(100, Math.round(100 * read / Math.max(1, c.page_cap))) + "%";
      const steps = current.timeline.filter((step) => step.status !== "skipped" && step.status !== "unavailable");
      const business = current.business || {};
      fill(body, el("p", { class: "eta" }, el("strong", { text: (current.eta && current.eta.plain) || (current.eta && current.eta.label) || "" }),
          el("span", { class: "muted small", text: " · " + T("job.pages.plain", { read: num(read), cap: num(c.page_cap) }) })),
        business.suggested_line ? el("p", { class: "small business-early", role: "status", text: business.suggested_line }) : null,
        business.chosen_line ? el("p", { class: "muted small", text: business.chosen_line }) : null,
        el("div", { class: "meter", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": c.page_cap, "aria-valuenow": read, "aria-label": T("result.pages") }, bar),
        el("ol", { class: "plain-steps" }, steps.map((step, i) => el("li", { class: step.status },
          el("span", { class: "dot", "aria-hidden": "true", text: step.status === "done" ? "✓" : step.status === "active" ? String(i + 1) : "" }),
          el("span", { text: step.plain || step.label }), el("span", { class: "visually-hidden", text: " (" + step.status_label + ")" })))),
        actions, el("details", { class: "quiet-details" }, el("summary", { text: T("job.details") }), el("div", {}, parts)));
    } else if (current.can_resume || current.state === "failed") {
      fill(body, parts, actions);
    } else {
      fill(body, el("details", { class: "quiet-details" }, el("summary", { text: T("job.details.done") }), el("div", {}, planNode || null, parts)), actions);
    }
    card.classList.toggle("card", Boolean(current.active || current.can_resume || current.state === "failed"));
    card.classList.toggle("job-done", !(current.active || current.can_resume || current.state === "failed"));
    tick();
    logBox.hidden = !log.childNodes.length;
    const key = current.has_report && !current.active ? current.state + ":" + current.finished_at : null;
    // Reading a finished audit through Firecrawl keeps its results on the page; they are replaced when it ends.
    if (continuing) { if (shown === null && current.has_report) { shown = "continuing"; loadSummary(current.id, result, context); } }
    else if (current.active) { fill(result); shown = null; }
    else if (key && key !== shown) { shown = key; loadSummary(current.id, result, context); }
  };
  const addLog = (message) => {
    log.append(el("div", { text: new Intl.DateTimeFormat(state.language, { timeStyle: "medium" }).format(new Date()) + "  " + message }));
    while (log.childNodes.length > 200) log.firstChild.remove();
    logBox.hidden = false;
  };
  // `shown` is cleared so the card is drawn again when the reading ends, even if that is within the same second.
  const context = { onContinue: (next) => { current = next; shown = null; draw(); watch(); loadHistory(); } };
  const refresh = async () => { try { current = await api("GET", "/audits/" + current.id); draw(); } catch (error) { /* the stream's next event tries again */ } };
  const watch = () => {
    closeStream();
    const source = state.source = new EventSource(API + "/audits/" + current.id + "/events");
    state.ticker = setInterval(tick, 1000);
    const on = (name, handler) => source.addEventListener(name, (event) => { let data = {}; try { data = JSON.parse(event.data); } catch (error) { return; } handler(data); });
    on("snapshot", (data) => { current = data.audit; draw(); });
    on("progress", (data) => {
      // Firecrawl's progress and Maya's own arrive side by side (DECISIONS 294): each updates only its own counters.
      if (data.step === "firecrawl") Object.assign(current.counters, { firecrawl_read: data.read, firecrawl_cap: data.page_cap });
      else { Object.assign(current.counters, { pages_checked: data.pages_checked, other_fetches: data.other_fetches, requests_sent: data.requests_sent }); current.current_url = data.url; }
      refreshSoon();
    });
    on("step", refresh); on("state", refresh);
    on("business", refreshSoon);  // DECISIONS 311: the homepage's suggestion, shown in the progress box
    on("log", (data) => addLog(data.message));
    on("done", refresh);
    on("end", (data) => { current = data.audit; closeStream(); draw(); loadHistory(); });
  };
  let pending = null;
  const refreshSoon = () => { if (!pending) pending = setTimeout(() => { pending = null; refresh(); }, 1000); };
  const resumeDialog = async (slot) => {
    const plan = await guarded(() => api("POST", "/audits/" + current.id + "/resume-plan"));
    if (!plan) return;
    const paid = plan.paid, reader = plan.firecrawl || {};
    const approval = {};
    if (paid.needs_confirmation) approval.approved_max_usd = paid.total_usd;
    if (reader.pending && reader.needs_confirmation) approval.approved_max_credits = reader.max_credits;
    const go = async () => { const next = await guarded(() => api("POST", "/audits/" + current.id + "/resume", approval)); if (next) { current = next; draw(); watch(); loadHistory(); } };
    const label = paid.needs_confirmation && approval.approved_max_credits ? T("resume.confirm_paid", { total: money(paid.total_usd) }) + " · " + T("confirm.part.credits", { credits: num(reader.max_credits) })
      : paid.needs_confirmation ? T("resume.confirm_paid", { total: money(paid.total_usd) }) : approval.approved_max_credits ? T("fc.resume.confirm", { credits: num(reader.max_credits) }) : T("resume.confirm");
    fill(slot, el("div", { class: "editor" }, el("h3", { text: T("resume.title") }), el("ul", { class: "list" }, plan.keeps.concat(plan.repeats, [T("resume.left", { count: Number(plan.pages_left) || 0 }), paid.note], reader.pending ? [reader.note] : []).map((line) => el("li", { text: line }))),
      paid.blocked ? el("p", { class: "error-text", text: paid.blocked.message }) : null,
      reader.blocked ? el("p", { class: "error-text", text: reader.blocked.message }) : null,
      el("div", { class: "row" }, el("button", { class: Object.keys(approval).length ? "button pay" : "button primary", type: "button", onclick: go }, label))));
  };
  draw();
  if (audit.active) watch();
  return card;
}

/* ---------- results ---------- */

async function loadSummary(auditId, box, context) {
  const view = await guarded(() => api("GET", "/audits/" + auditId + "/summary"));
  if (view) fill(box, resultView(view, context || {}));
}

// A finding's title and fix as the server worded them for this reader (the report's own English stays in row.title, row.fix).
function shownTitle(row) { return row.title_shown || row.title; }
function shownFix(row) { return row.fix_shown || row.fix; }

function itemRow(row) {
  // Provider diagnostics are advisory actions, not engine findings with finding/evidence endpoints.
  if (row.action_kind === "performance_diagnostic") return el("div", { class: "item" },
    el("div", { class: "item-title" }, el("span", { class: "tag", text: row.severity_label }), shownTitle(row)),
    el("p", { class: "muted small", text: row.why }), el("p", { text: shownFix(row) }));
  // The block has its own card at the top; its finding is one line here, with its evidence one press away.
  if (row.in_block_card && row.pointer) return el("div", { class: "item pointer" }, el("div", { class: "item-title" }, el("span", { class: "tag " + row.severity, text: row.severity_label }), shownTitle(row)),
    el("p", { class: "muted small" }, row.check_id + " · " + row.pointer + " ", el("button", { class: "chip", type: "button", onclick: (event) => openEvidence(row.id, event.currentTarget) }, T("result.evidence"))));
  const pages = el("div");
  const more = el("details", {}, el("summary", { text: T("result.details") }), el("div", {},
    facts([[T("result.what"), row.what], [T("result.why"), row.why], [T("result.fix"), row.requires_fix ? shownFix(row) : T("result.no_fix") + " " + shownFix(row)],
      [T("result.severity"), row.severity_label + ". " + row.severity_meaning], [T("result.confidence"), row.confidence_label],
      [row.estimates.label, row.estimates.owner_label + ", " + row.estimates.effort_label], [T("result.expected"), row.expected_shown || row.expected],
      [T("result.check"), row.check_id + " · " + row.area_label]]),
    el("h4", { text: T("result.pages_affected") + " (" + num(row.pages_total) + ")" }), pages,
    el("div", { class: "row" }, el("button", { class: "button", type: "button", onclick: (event) => openEvidence(row.id, event.currentTarget) }, T("result.evidence")))));
  more.addEventListener("toggle", () => { if (more.open && !pages.dataset.ready) { pages.dataset.ready = "1"; pageList(pages, row.id); } });
  return el("div", { class: "item" }, el("div", { class: "item-title" }, el("span", { class: "tag " + row.severity, text: row.severity_label }), shownTitle(row)),
    row.source ? el("p", { class: "small" }, el("strong", { text: row.source.label }), row.source.notice ? ". " + row.source.notice : "") : null,
    // A rule not yet validated on real sites: a chip and the sentence that asks for a check by hand (DECISIONS 203).
    row.unverified ? el("p", { class: "small unverified-note" }, el("span", { class: "state-chip unverified", text: row.unverified.label }), " ", row.unverified.note) : null,
    el("p", { class: "muted small", text: row.check_id + " · " + row.affects }),
    // Both sides of a price, a brand's names: what the title counts, value by value.
    (row.details || []).length ? el("ul", { class: "list small" }, row.details.map((line) => el("li", { text: line }))) : null,
    el("p", {}, el("strong", { text: T("result.fix") + ": " }), shownFix(row)), more);
}

function pager(total, offset, limit, go) {
  if (total <= limit) return null;
  return el("div", { class: "pager" }, el("button", { class: "button", type: "button", disabled: offset <= 0, onclick: () => go(Math.max(0, offset - limit)) }, T("word.previous")),
    el("span", { text: T("word.of", { from: num(offset + 1), to: num(Math.min(total, offset + limit)), total: num(total) }) }),
    el("button", { class: "button", type: "button", disabled: offset + limit >= total, onclick: () => go(offset + limit) }, T("word.next")));
}

function pageList(box, findingId) {
  const input = el("input", { class: "field-input", type: "search", "aria-label": T("result.pages_search"), placeholder: T("result.pages_search") });
  const list = el("div");
  const load = async (offset) => {
    const data = await guarded(() => api("GET", "/audits/" + state.auditId + "/findings/" + encodeURIComponent(findingId) + "/pages?limit=25&offset=" + offset + "&q=" + encodeURIComponent(input.value.trim())));
    if (!data) return;
    fill(list, el("ul", { class: "list" }, data.pages.map((address) => el("li", {}, link(address)))),
      data.complete ? null : el("p", { class: "muted small", text: T("result.pages_incomplete", { count: num(data.all_pages) }) }), pager(data.total, data.offset, data.limit, load));
  };
  let typing = null;
  input.addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => load(0), 250); });
  fill(box, input, list);
  load(0);
}

function findingsBrowser(box, initial) {
  const filter = Object.assign({ severity: "", area: "", q: "" }, initial || {});
  const list = el("div");
  const select = (label, options, key) => {
    const node = el("select", { "aria-label": label, onchange: (event) => { filter[key] = event.target.value; load(0); } },
      el("option", { value: "", text: label + ": " + T("result.filter.all") }), options.map(([value, text]) => el("option", { value, text, selected: filter[key] === value })));
    return node;
  };
  const search = el("input", { class: "field-input", type: "search", "aria-label": T("result.filter.search"), placeholder: T("result.filter.search") });
  let typing = null;
  search.addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => { filter.q = search.value.trim(); load(0); }, 250); });
  const load = async (offset) => {
    const query = Object.entries({ severity: filter.severity, area: filter.area, q: filter.q, limit: 10, offset }).filter(([, value]) => value !== "").map(([key, value]) => key + "=" + encodeURIComponent(value)).join("&");
    const data = await guarded(() => api("GET", "/audits/" + state.auditId + "/findings?" + query));
    if (!data) return;
    fill(list, data.items.length ? data.items.map(itemRow) : el("p", { class: "muted", text: T("result.filter.none") }), pager(data.total, data.offset, data.limit, load));
  };
  fill(box, el("div", { class: "filters" }, select(T("result.filter.severity"), ["S1", "S2", "S3", "S4", "Info"].map((level) => [level, T("result.severity." + level)]).concat([["S1,S2", T("result.group.fix_now")]]), "severity"),
    select(T("result.filter.area"), ["ACC", "IDX", "RND", "STR", "TSEO", "PRF"].map((area) => [area, T("result.family." + area)]), "area"), search), list);
  load(0);
}

async function showPlan(box, role) {
  const draw = async (who) => {
    const plan = await guarded(() => api("GET", "/audits/" + state.auditId + "/action-plan" + (who ? "?role=" + who : "")));
    if (!plan) return;
    fill(box, el("div", { class: "chips row", role: "radiogroup", "aria-label": T("result.actions.role") }, [["", T("result.actions.everyone")], ["developer", T("owner.developer")], ["content", T("owner.content")], ["seo", T("owner.seo")]].map(([value, label]) =>
      el("button", { class: "chip", type: "button", role: "radio", "aria-checked": String((who || "") === value), onclick: () => draw(value) }, label))),
      el("p", { class: "muted small", text: plan.estimates_note }), plan.total ? null : el("p", { text: T("result.actions.none") }),
      plan.groups.filter((group) => group.items.length).map((group) => el("details", { open: group.id === "fix_now" }, el("summary", { text: group.label + " (" + num(group.items.length) + ")" }), el("div", {}, group.items.map(itemRow)))));
  };
  draw(role || "");
}

async function showComparison(box) {
  const data = await guarded(() => api("GET", "/audits/" + state.auditId + "/comparison"));
  if (!data) return;
  const section = (key) => data[key].length ? el("details", { open: key === "new" || key === "no_longer_reported" }, el("summary", { text: T("compare.section." + key) + " (" + num(data.counts[key]) + ")" }),
    el("ul", { class: "list" }, data[key].map((row) => el("li", {}, el("span", { class: "tag " + row.severity, text: row.severity_label }), shownTitle(row), " ",
      el("span", { class: "muted small", text: row.check_id + (row.pages_before !== undefined ? " · " + T("compare.pages_change", { before: num(row.pages_before), now: Number(row.pages) || 0 }) : "") }),
      row.why || row.note ? el("div", { class: "muted small", text: row.why || row.note }) : null)))) : null;
  fill(box, el("h4", { text: T("compare.title", { date: when(data.older.started_at) }) }), el("p", { text: data.summary_line }),
    data.caution ? el("p", { class: "error-text", text: data.caution }) : null,
    data.differences.length ? el("ul", { class: "list" }, data.differences.map((d) => el("li", { text: d.message }))) : null,
    ["new", "first_seen", "still_reported", "no_longer_reported", "cannot_tell"].map(section), el("p", { class: "muted small", text: data.matching }));
}

/* "/privacy" rather than the whole address: every row of the page table is the same site. */
function pagePath(address) {
  try { const u = new URL(address); return (u.pathname || "/") + u.search; } catch (error) { return address; }
}

/* What this audit covers: direct access, content coverage and real AI crawlers, each as the report records it. Three
   separate facts on three lines, so that pages read through a reader are never mistaken for crawlers being let in. */
function statusBlock(view) {
  const status = view.status;
  if (!status) return null;
  const spend = view.spend || {}, lines = [];
  if (spend.dataforseo) lines.push(T("status.spend.dataforseo", { cost: money(spend.dataforseo.cost_usd || 0), estimate: money(spend.dataforseo.estimated_usd || 0),
    possibly: Number(spend.dataforseo.possibly_billed) || 0, cached: num(spend.dataforseo.from_cache) }));
  if (spend.firecrawl) lines.push(T("status.spend.firecrawl", { credits: Number(spend.firecrawl.credits) || 0, estimate: num(spend.firecrawl.estimated_max_credits || 0),
    possibly: Number(spend.firecrawl.possibly_billed) || 0, cached: num(spend.firecrawl.from_cache), zdr: spend.firecrawl.zero_data_retention_shown || spend.firecrawl.zero_data_retention || "—",
    usd: spend.firecrawl.usd_known ? T("status.spend.usd.known", { usd: money(spend.firecrawl.usd || 0) }) : T("status.spend.usd.unknown") }));
  return el("section", { class: "status-block", "aria-label": status.title }, el("h3", { text: status.title }),
    el("dl", { class: "status-rows" }, status.rows.map((row) => [el("dt", {}, row.label, " ", el("span", { class: "state-chip " + row.state, text: row.state_label })),
      el("dd", { text: row.note })])),
    status.cache_note ? el("p", { class: "small", text: status.cache_note }) : null,
    el("p", { class: "muted small", text: status.duration_line }),
    lines.length ? el("details", { class: "quiet-details" }, el("summary", { text: T("status.spend.title") }), el("div", {}, lines.map((line) => el("p", { class: "small", text: line })))) : null);
}

/* Figures and a table for one paid-data check. Everything is text from the report; nothing is computed here. */
function dataTable(check) {
  const data = check.data || {}, parts = [], shownAs = check.data_shown || {};
  // Figure names, column names and this tool's own words (relevance, yes or no) in the reader's language; every other cell as the provider gave it.
  const named = (text) => (shownAs.labels && Object.prototype.hasOwnProperty.call(shownAs.labels, text) ? shownAs.labels[text] : text);
  const words = shownAs.word_columns || [];
  const cellText = (column, cell) => cell === null || cell === undefined ? "—" : (typeof cell === "number" ? num(cell) : (words.includes(column) ? named(String(cell)) : String(cell)));
  const metrics = Object.entries(data.metrics || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (metrics.length) parts.push(el("ul", { class: "list small" }, metrics.map(([label, value]) => el("li", { text: named(label) + ": " + cellText(label, value) }))));
  const table = data.table;
  if (table && table.rows && table.rows.length) parts.push(el("div", { class: "table-scroll" }, el("table", { class: "data" },
    el("thead", {}, el("tr", {}, table.columns.map((name) => el("th", { scope: "col", text: named(name) })))),
    el("tbody", {}, table.rows.slice(0, 20).map((row) => el("tr", {}, row.map((cell, at) => el("td", { text: cellText(table.columns[at], cell) }))))))),
    table.rows.length > 20 ? el("p", { class: "muted small", text: T("result.data.more", { count: table.rows.length - 20 }) }) : null);
  for (const key of ["ambiguous", "unrelated", "intent_dimensions", "editorial_opportunities"]) { const aside = data[key]; if (aside && aside.rows && aside.rows.length) parts.push(el("details", { class: "quiet-details" }, el("summary", { text: named(aside.title) + ": " + num(aside.rows.length) }),
    el("div", {}, el("p", { class: "muted small", text: (shownAs.notes && shownAs.notes[key]) || aside.note }), el("div", { class: "table-scroll" }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, aside.columns.map((name) => el("th", { scope: "col", text: named(name) })))),
      el("tbody", {}, aside.rows.slice(0, 50).map((row) => el("tr", {}, row.map((cell, at) => el("td", { text: cellText(aside.columns[at], cell) })))))))))); }
  return parts;
}

/* What a third-party reader did for this audit, said before any finding that rests on it. */
function firecrawlStatus(view, folded) {
  const reader = view.firecrawl;
  if (!reader) return null;
  const lines = (reader.lines_shown || reader.lines).filter((line, at) => reader.lines[at] !== reader.notice).map((line) => el("p", { class: "small", text: line }));
  if (reader.spent_line) lines.push(el("p", { class: "small", text: reader.spent_line }));
  if (folded) return el("details", { class: "quiet-details" }, el("summary", { text: T("fc.result.what") }), el("div", {}, lines));
  return el("div", {}, el("p", {}, el("strong", { text: T(reader.used ? "fc.result.title" : "fc.result.not_used") })),
    reader.used && reader.notice ? el("p", {}, el("strong", { text: reader.notice_shown || reader.notice })) : null, lines);
}

/* The Firecrawl choice on a blocked audit: switch it on, accept storage, or retry with a stronger proxy. Nothing is
   sent until every box shown is ticked and the button, which carries the exact maximum, is pressed. */
function offerBox(view, context) {
  const offer = view.firecrawl_offer;
  if (!offer) return null;
  const box = el("div", { class: "offer" }, el("p", { class: "offer-title" }, el("strong", { text: offer.title })), offer.lines.map((line) => el("p", { text: line })));
  if (!offer.choices.length) return box;
  if (!offer.available) { box.append(el("p", { class: "muted small", text: offer.unavailable_reason })); return box; }
  if (offer.blocked) { box.append(el("p", { class: "error-text", text: offer.blocked.message })); return box; }
  const id = "o" + view.audit.id.slice(0, 8);
  const storage = offer.consent.storage ? el("input", { type: "checkbox", id: id + "-storage" }) : null;
  const owner = offer.consent.owner ? el("input", { type: "checkbox", id: id + "-owner" }) : null;
  const proxy = offer.choices.length > 1 ? el("select", { class: "field-input narrow", id: id + "-proxy" }, offer.choices.map((choice) => el("option", { value: choice.proxy, text: choice.proxy_label }))) : null;
  const cost = el("p", { class: "total" }), hint = el("p", { class: "muted small", text: offer.waiting }), problem = el("p", { class: "error-text", role: "alert" });
  const go = el("button", { class: "button pay", type: "button", disabled: true });
  const chosen = () => offer.choices.find((choice) => choice.proxy === (proxy ? proxy.value : offer.choices[0].proxy));
  const ready = () => (!storage || storage.checked) && (!owner || owner.checked);
  const refresh = () => { go.textContent = chosen().label; cost.textContent = chosen().cost_line; go.disabled = !ready(); hint.hidden = ready() || (!storage && !owner); };
  for (const input of [storage, owner, proxy]) if (input) input.addEventListener("change", refresh);
  go.addEventListener("click", async () => {
    const choice = chosen();
    go.disabled = true; go.textContent = T("fc.offer.sending"); go.setAttribute("aria-busy", "true"); problem.textContent = "";
    try {
      const audit = await api("POST", "/audits/" + view.audit.id + "/firecrawl/read", { proxy: choice.proxy, owner_approved_bypass: Boolean(owner && owner.checked),
        accept_content_may_be_stored: Boolean(storage && storage.checked), approved_max_credits: choice.max_credits });
      fill(box, el("p", { class: "busy", role: "status", text: T("fc.offer.running") }));
      if (context.onContinue) context.onContinue(audit); else openAudit(audit.id);
    } catch (error) { go.removeAttribute("aria-busy"); problem.textContent = error.message; refresh(); }
  });
  add(box, storage ? [el("p", { class: "error-text", text: offer.consent.storage_warning }), el("p", { class: "tick" }, storage, " ", el("label", { for: id + "-storage", text: offer.consent.storage_label }))] : null,
    owner ? [el("p", { class: "tick" }, owner, " ", el("label", { for: id + "-owner", text: offer.consent.owner_label })), el("p", { class: "muted small", text: offer.consent.owner_help })] : null,
    proxy ? el("p", {}, el("label", { class: "label", for: id + "-proxy", text: T("fc.offer.choose") }), proxy) : null,
    cost, el("div", { class: "row" }, go), hint, problem, el("p", { class: "muted small", text: offer.offline_note }));
  refresh();
  return box;
}

/* One card for a blocked audit: who blocked it, what that means, what to do, and the Firecrawl choice. The block is
   explained here and nowhere else on the page. */
function blockCard(view, context) {
  const block = view.blocked, o = view.outcome, names = block.sections;
  const card = el("section", { class: "lead block-card", role: "note", "aria-label": block.headline }, el("h3", { text: block.headline }),
    el("p", { class: "status-line" }, el("span", { class: "state " + (o.code || ""), text: o.label || "" }), " ", el("strong", { text: view.pages_stat.line })),
    el("h4", { text: names.who }), block.lines.slice(0, 2).map((line) => el("p", { text: line })),
    el("h4", { text: names.meaning }), block.lines.slice(2).map((line) => el("p", { text: line })),
    el("h4", { text: names.next }), el("ul", { class: "list" }, block.next_steps.map((step) => el("li", { text: step }))),
    block.allowlist ? el("details", { class: "quiet-details" }, el("summary", { text: block.allowlist.title }), el("div", {}, el("p", { class: "small", text: block.allowlist.note }),
      block.allowlist.blocks.map((item) => el("div", {}, el("p", {}, el("strong", { text: item.title_shown || item.title })), el("ol", { class: "list small" }, (item.steps_shown || item.steps).map((step) => el("li", { text: step }))),
        el("pre", { text: item.copy }))))) : null,
    view.verification ? el("details", { class: "quiet-details" }, el("summary", { text: T("verify.title") }), el("div", {},
      view.ownership ? el("p", { class: "small", text: view.ownership.summary_shown || view.ownership.summary }) : null,
      el("ul", { class: "list small" }, (view.verification.instructions_shown || view.verification.instructions).map((line) => el("li", { text: line }))),
      el("pre", { text: view.verification.meta_tag + "\n" + view.verification.txt_record }))) : null);
  const running = view.audit.firecrawl && view.audit.firecrawl.continuing;
  const offer = running ? null : offerBox(view, context);
  if (view.firecrawl || offer || running) add(card, el("h4", { text: names.firecrawl }),
    running ? el("p", { class: "busy", role: "status", text: T("fc.offer.running") }) : null, offer, firecrawlStatus(view, Boolean(offer)));
  add(card, el("details", { class: "quiet-details" }, el("summary", { text: names.status + ": " + (o.label || "") }), el("div", {}, el("p", { class: "small", text: o.reason_shown || o.reason || "" }),
    o.note ? el("p", { class: "muted small", text: o.note }) : null, view.coverage.resumed_note ? el("p", { class: "muted small", text: view.coverage.resumed_note }) : null)));
  return card;
}

/* DECISIONS 310: one path through the results. (1) Summary: the report's verdict and four numbers; (2) what to fix:
   the team report's cards; (3) check these first; (4) downloads; the questions; (5) technical details, folded: every
   section the page had before. (1) and (2) are the team report's own data, from the copy re-evaluated with the
   current engine, so the page and the PDF say the same thing. */
function resultView(view, context) {
  const out = el("div", { class: "results" });
  const analysis = view.audit?.analysis;
  if (analysis) add(out, el("section", {class:"notice"}, el("h2", {text:analysis.label}),
    el("p", {text:T("analysis.notice")}), el("p", {class:"small", text:"ID: "+analysis.id+" · "+T("analysis.source")+": "+analysis.source_audit_id}),
    el("p", {class:"small", text:T("analysis.version")+": "+analysis.analysis_version+" · "+T("analysis.processed")+": "+analysis.processed_at})));
  if (view.blocked) add(out, blockCard(view, context || {}));
  if (view.low_coverage) add(out, el("div", { class: "lowcov", role: "alert", text: view.low_coverage.text }));
  if (view.redirected) add(out, el("div", { class: "lead", role: "note" }, el("p", { text: view.redirected.message }),
    el("div", { class: "row" }, el("button", { class: "button primary", type: "button", onclick: () => { newAudit(); send(view.redirected.to); } }, view.redirected.offer))));
  const overviewSlot = el("div", { class: "overview" });
  const reviewSlot = el("section", { class: "card review-list", "aria-labelledby": "check-first-title" });
  add(out, overviewSlot, reviewSlot);
  const refresh = () => showOverview(overviewSlot, view);
  refresh();
  showReview(reviewSlot, view.audit.id, refresh);
  if (view.team_report) add(out, teamReport(view.team_report));
  if ((view.follow_ups || []).length) add(out, el("section", { class: "followups" }, el("h3", { text: T("result.followups") }),
    el("div", { class: "chips" }, view.follow_ups.map((question) => el("button", { class: "chip", type: "button", onclick: () => send(question) }, question)))));
  const techBox = el("div");
  const tech = el("details", { class: "card tech-details" }, el("summary", {}, el("span", { class: "section-no", text: "5 · " }), T("result.tech.title"),
    el("span", { class: "muted small", text: " — " + T("result.tech.note") })), techBox);
  let built = false;
  const build = () => { if (!built) { built = true; fill(techBox, technicalView(view, context)); } };
  tech.addEventListener("toggle", () => { if (tech.open) build(); });
  add(out, tech);
  out.openTechnical = () => { build(); tech.open = true; };
  return out;
}

function sectionLabel(n, key) { return el("div", { class: "section-label", text: n + " · " + T(key) }); }

async function showOverview(box, view) {
  if (!box.childNodes.length) fill(box, el("section", { class: "card" }, sectionLabel(1, "overview.title"), el("p", { class: "busy", role: "status", text: T("overview.loading") })));
  const lang = state.language === "en" ? "en" : "tr";
  let data;
  try { data = await api("GET", "/audits/" + view.audit.id + "/overview?lang=" + lang); }
  catch (error) { data = { available: false, reason: error.message }; }
  if (!data.available) {
    fill(box, el("section", { class: "card" }, sectionLabel(1, "overview.title"),
      view.headline ? el("h1", { class: "verdict", text: view.headline }) : null,
      el("p", { class: "muted", text: data.reason || T("overview.unavailable") })));
    return;
  }
  const kpi = (k) => el("div", { class: "kpi" }, el("div", { class: "kpi-label", text: k.label }),
    el("div", { class: "kpi-value" }, k.value, k.of ? el("small", { text: " / " + k.of }) : null), el("div", { class: "kpi-sub", text: k.sub }));
  const fixRow = (f) => el("li", { class: "fix" }, el("span", { class: "fix-n", text: String(f.n).padStart(2, "0") }),
    el("div", { class: "fix-body" },
      el("div", { class: "fix-title" }, el("strong", {}, hinted(f.title)), " ", el("span", { class: "sev " + f.severity, text: f.severity_label }),
        f.issue_type_label ? el("span", { class: "itype " + (f.issue_type || "issue"), text: f.issue_type_label }) : null),
      f.chain_line ? el("p", { class: "small", text: f.chain_line }) : null,
      f.template_line ? el("p", { class: "small", text: f.template_line }) : null,
      f.sitemap_line ? el("p", { class: "small", text: f.sitemap_line }) : null,
      f.certificate_line ? el("p", { class: "small", text: f.certificate_line }) : null,
      f.hosts_line ? el("p", { class: "small", text: f.hosts_line }) : null,
      f.why || f.scope ? el("p", { class: "muted small", text: [f.why, f.scope].filter(Boolean).join(" · ") }) : null,
      f.note ? el("p", { class: "small", text: f.note }) : null,
      el("div", { class: "id", text: f.finding_ids.slice(0, 3).join(" · ") + (f.finding_ids.length > 3 ? " +" + (f.finding_ids.length - 3) : "") })),
    el("div", { class: "fix-who" }, el("span", { text: f.owner }), el("span", { class: "muted small", text: f.effort })));
  CONFIRM_SCOPES[view.audit.id] = data.confirm_scopes || {};
  if (REVIEW_REDRAW[view.audit.id]) REVIEW_REDRAW[view.audit.id]();
  const first = data.fixes.slice(0, 5), rest = data.fixes.slice(5);
  fill(box,
    el("section", { class: "card summary", "aria-labelledby": "summary-title" }, sectionLabel(1, "overview.title"),
      el("h1", { class: "verdict", id: "summary-title", text: data.headline }),
      el("div", { class: "kpis" }, data.kpis.map(kpi)),
      data.locales ? el("p", { class: "muted small", text: data.locales }) : null,
      businessBox(view, data.business, () => showOverview(box, view)),
      data.reassessed ? el("p", { class: "muted small", text: data.reassessed }) : null),
    el("section", { class: "card fixes", "aria-labelledby": "fixes-title" }, sectionLabel(2, "fixes.title"),
      el("h2", { id: "fixes-title", text: data.fixes.length ? T("fixes.heading", { count: first.length }) : T("fixes.none") }),
      el("ol", { class: "fix-list" }, first.map(fixRow)),
      rest.length ? el("details", { class: "more" }, el("summary", { text: T("fixes.more", { count: rest.length }) }), el("ol", { class: "fix-list" }, rest.map(fixRow))) : null,
      data.notes ? el("p", { class: "muted small", text: T("fixes.notes", { count: data.notes }) }) : null));
}

/* DECISIONS 311: the business type the summary and key pages use, why, and a dropdown to change it. Saved beside the
   audit; the summary, key pages, team report and appendix are made again from the saved report, nothing is requested. */
function businessBox(view, info, redraw) {
  if (!info) return null;
  const id = "rb" + String(view.audit.id).slice(0, 8);
  const status = el("p", { class: "ok-text small", role: "status" });
  const change = async (value) => {
    const answer = await guarded(() => api("POST", "/audits/" + view.audit.id + "/business-type", { id: value }));
    if (!answer) return;
    status.textContent = answer.message || "";
    await redraw();
  };
  /* DECISIONS 313: one compact line, the reason folded under "Neden?", and the dropdown showing the type in use (the
     suggested one marked "(önerilen)"); choosing the suggested type goes back to the suggestion. */
  const choices = (info.choices || []).map((c) => c.id === info.suggested_id ? Object.assign({}, c, { label: T("result.business.suggested_mark", { label: c.label }) }) : c);
  const select = businessSelect(id, choices, info.id, false, (value) => change(value === info.suggested_id ? "auto" : value));
  return el("div", { class: "business-box" },
    el("div", { class: "business-line" },
      el("span", { class: "business-chip", text: T("result.business.chip", { label: info.label }) }),
      el("details", { class: "business-why" }, el("summary", { text: T("result.business.why") }),
        el("p", { class: "muted small", text: info.chosen_by === "user" ? T("result.business.how.user") : T("result.business.how.suggestion", { reason: info.reason || "" }) })),
      el("label", { class: "label", for: id, text: T("result.business.change") }), select),
    info.not_found ? el("p", { class: "muted small", text: info.not_found }) : null, status);
}

/* "Önce bunları kontrol edin" (Teyit edin, DECISIONS 301, 309, 310). Optional: an unchecked finding stays out of the
   report's cards and in the appendix. Two big buttons; the name is asked once and remembered in this browser; what
   was seen and the card note are optional; a missing name is said beside the field; a saved item moves to "Checked"
   with an Undo. At most three items open, highest severity first; the rest one click away. */
const SHOWN_CHECKS = 3;
const CONFIRM_SCOPES = {};  // audit id -> {first finding id: the scope the PDF prints}, from the overview
const REVIEW_REDRAW = {};
const SEVERITY_RANK = { S1: 0, S2: 1, S3: 2, S4: 3, Info: 4 };
function rememberedName() { try { return localStorage.getItem("maya.reviewer") || ""; } catch (error) { return ""; } }
function rememberName(name) { try { localStorage.setItem("maya.reviewer", name); } catch (error) { /* private window: asked again */ } }

async function showReview(box, auditId, onChange) {
  let data;
  try { data = await api("GET", "/audits/" + auditId + "/review"); } catch (error) { box.replaceChildren(); return; }
  drawReview(box, auditId, data, onChange, null);
}

function drawReview(box, auditId, data, onChange, justSaved) {
  let name = rememberedName();
  REVIEW_REDRAW[auditId] = () => { if (box.isConnected) drawReview(box, auditId, data, onChange, justSaved); };
  const redraw = (next, saved) => { drawReview(box, auditId, next, onChange, saved); if (onChange) onChange(); };
  const fieldId = (row, field) => "chk-" + String(row.finding_id).replace(/[^A-Za-z0-9-]/g, "") + "-" + field;
  const item = (row, index) => {
    const nameInput = el("input", { class: "field-input", type: "text", maxlength: "120", id: fieldId(row, "by"), autocomplete: "name", "aria-describedby": fieldId(row, "by-error") });
    nameInput.value = name;
    const nameError = el("p", { class: "field-error", id: fieldId(row, "by-error"), hidden: true });
    const seen = el("textarea", { class: "field-input", maxlength: "1000", rows: "2", id: fieldId(row, "seen"), placeholder: T("check.seen.example") });
    const note = el("input", { class: "field-input", type: "text", maxlength: "1000", id: fieldId(row, "note"), placeholder: T("check.note.example") });
    const saveError = el("p", { class: "field-error", role: "alert", hidden: true });
    const askName = !name;
    const nameBox = el("div", { class: "field", hidden: !askName }, el("label", { class: "field-label", for: nameInput.id, text: T("check.by") }), nameInput, nameError);
    const extra = el("div", { class: "check-fields", hidden: !(askName && index === 0) },
      el("div", { class: "field" }, el("label", { class: "field-label", for: seen.id }, T("check.seen"), el("span", { class: "muted", text: " " + T("check.optional") })), seen),
      el("div", { class: "field" }, el("label", { class: "field-label", for: note.id }, T("check.note"), el("span", { class: "muted", text: " " + T("check.optional") })), note));
    const who = el("span", { class: "muted small" });
    const drawWho = () => fill(who, name ? T("check.saved_as", { name }) : "", name ? [" · ", el("button", { class: "link", type: "button",
      onclick: () => { nameBox.hidden = false; nameInput.focus(); } }, T("check.change"))] : null,
      extra.hidden ? [name ? " · " : "", el("button", { class: "link", type: "button", onclick: () => { extra.hidden = false; seen.focus(); drawWho(); } }, T("check.add_note"))] : null);
    drawWho();
    const buttons = [];
    const save = async (result) => {
      const by = nameInput.value.trim();
      if (!by) {
        nameBox.hidden = false; nameError.textContent = T("check.error.by"); nameError.hidden = false; nameInput.classList.add("bad"); nameInput.focus(); return;
      }
      nameError.hidden = true; nameInput.classList.remove("bad"); saveError.hidden = true;
      buttons.forEach((b) => { b.disabled = true; });
      try {
        const next = await api("POST", "/audits/" + auditId + "/review", { finding_id: row.finding_id, result, by, seen: seen.value.trim() || null, note: note.value.trim() || null });
        rememberName(by); name = by;
        redraw(next, row.finding_id);
      } catch (error) {
        buttons.forEach((b) => { b.disabled = false; });
        const fields = (error.details && error.details.fields) || {};
        if (fields.by) { nameBox.hidden = false; nameError.textContent = fields.by; nameError.hidden = false; nameInput.classList.add("bad"); nameInput.focus(); }
        else { saveError.textContent = error.message || T("check.error.save"); saveError.hidden = false; }
      }
    };
    buttons.push(el("button", { class: "button ok big", type: "button", "aria-label": T("check.correct") + ": " + row.title, onclick: () => save("confirmed") }, "✓ " + T("check.correct")),
      el("button", { class: "button no big", type: "button", "aria-label": T("check.wrong") + ": " + row.title, onclick: () => save("rejected") }, "✕ " + T("check.wrong")));
    return el("li", { class: "check-item", "data-finding": row.finding_id },
      el("div", { class: "check-head" }, el("strong", {}, hinted(row.title)), el("span", { class: "sev " + row.severity, text: row.severity_label }),
        (CONFIRM_SCOPES[auditId] || {})[row.finding_ids[0]] ? el("span", { class: "muted small", text: CONFIRM_SCOPES[auditId][row.finding_ids[0]] }) : null,
        el("span", { class: "id", text: row.finding_ids.join(" · ") })),
      row.reason_label ? el("p", { class: "muted small", text: row.reason_label }) : null,
      nameBox, extra, el("div", { class: "row" }, buttons, who), saveError);
  };
  const checked = (row) => el("li", { class: "checked-item" + (row.finding_id === justSaved ? " just" : ""), "data-finding": row.finding_id },
    el("div", { class: "check-head" }, el("span", { class: "pill " + (row.manual.result === "confirmed" ? "status-finished" : "status-too_few"),
      text: (row.manual.result === "confirmed" ? "✓ " + T("check.correct") : "✕ " + T("check.wrong")) }), el("strong", {}, hinted(row.title)),
      el("span", { class: "muted small", text: row.manual.by + " · " + row.manual.date }), el("span", { class: "id", text: row.finding_ids.join(" · ") }),
      el("button", { class: "button", type: "button", "aria-label": T("check.undo") + ": " + row.title, onclick: async (event) => {
        event.currentTarget.disabled = true;
        try { redraw(await api("DELETE", "/audits/" + auditId + "/review/" + encodeURIComponent(row.finding_id)), null); }
        catch (error) { event.currentTarget.disabled = false; notice(error.message); }
      } }, T("check.undo"))),
    row.manual.note ? el("p", { class: "muted small", text: T("check.note_shown", { note: row.manual.note }) }) : null);
  const open = data.confirm.slice().sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9));
  const first = open.slice(0, SHOWN_CHECKS), rest = open.slice(SHOWN_CHECKS);
  fill(box, sectionLabel(3, "check.title"),
    el("h2", { id: "check-first-title", text: open.length ? T("check.heading", { count: open.length }) : T("check.none") }),
    el("p", { class: "muted small", text: T("check.how") }),
    el("p", { class: "small optional-line", text: T("check.optional_line") }),
    open.length ? el("ul", { class: "check-list" }, first.map(item)) : null,
    rest.length ? el("details", { class: "more" }, el("summary", { text: T("check.more", { count: rest.length }) }), el("ul", { class: "check-list" }, rest.map((row, i) => item(row, i + first.length)))) : null,
    data.reviewed.length ? el("details", { class: "more checked", open: Boolean(justSaved) }, el("summary", { text: T("check.done_title", { count: data.reviewed.length }) }),
      el("ul", { class: "check-list" }, data.reviewed.map(checked))) : null);
}

function teamReport(team) {
  // One language at a time (DECISIONS 308): the switch decides both files, each click builds that language again, and
  // the file is then offered as an ordinary link under its own name (…-ekip-raporu-tr.pdf / …-team-report-en.pdf). A
  // download a script starts long after the click is blocked by browsers as "multiple downloads". DECISIONS 310: the
  // Downloads card: the language, the team report PDF, the XLSX appendix, and the client brief (DECISIONS 319: built
  // the same way as the team report, in the chosen language, then one ordinary link; a blocked brief says why).
  let lang = team.default_lang || "tr";
  const why = el("div", { class: "team-blocked" });
  const ready = el("div", { class: "team-ready" });
  const langName = (code) => T("team.lang." + code);
  const pdfButton = el("button", { class: "button primary", type: "button" });
  const xlsxLink = el("a", { class: "button", download: "" });
  const briefWhy = el("div", { class: "team-blocked" });
  const briefReady = el("div", { class: "team-ready" });
  const briefButton = el("button", { class: "button", type: "button" });
  const label = () => { pdfButton.textContent = T("download.pdf.build", { language: langName(lang) }); xlsxLink.textContent = T("download.xlsx.get", { language: langName(lang) }); xlsxLink.href = team.xlsx + "?lang=" + lang; briefButton.textContent = T("download.brief.build", { language: langName(lang) }); };
  const choice = (code) => el("button", { class: "button lang" + (code === lang ? " selected" : ""), type: "button", "aria-pressed": String(code === lang), "data-lang": code,
    onclick: (event) => { lang = code; for (const b of event.currentTarget.parentNode.children) { b.classList.toggle("selected", b === event.currentTarget); b.setAttribute("aria-pressed", String(b === event.currentTarget)); } fill(why); fill(ready); fill(briefWhy); fill(briefReady); label(); } }, langName(code));
  pdfButton.onclick = async () => {
    const asked = lang;
    fill(ready);
    fill(why, el("p", { class: "busy small", role: "status", text: T("team.building") + " (" + langName(asked) + ")" }));
    pdfButton.disabled = true;
    let response;
    try { response = await fetch(team.prepare + "?lang=" + asked, { credentials: "same-origin", cache: "no-store" }); }
    catch (error) { pdfButton.disabled = false; fill(why); notice(T("error.offline")); return; }
    pdfButton.disabled = false;
    let body = {};
    try { body = (await response.json()) || {}; } catch (error) { body = {}; }
    if (asked !== lang) { fill(why); return; } // the reader chose the other language meanwhile
    if (!response.ok) {
      const problem = body.error || {};
      const reasons = (problem.details && problem.details.reasons) || [];
      fill(why, el("p", {}, el("strong", { text: problem.message || T("team.blocked") })),
        reasons.length ? el("ul", { class: "list" }, reasons.map((line) => el("li", { text: line }))) : null);
      return;
    }
    fill(why);
    fill(ready, el("p", { class: "small", text: T("team.ready", { language: langName(body.lang), pages: body.pages }) }),
      el("div", { class: "row" },
        el("a", { class: "button primary", href: body.pdf.url, download: body.pdf.filename, "data-lang": body.lang }, T("download.get") + ": " + body.pdf.filename),
        el("a", { class: "button", href: body.xlsx.url, download: body.xlsx.filename, "data-lang": body.lang }, body.xlsx.filename)),
      body.reassessed ? el("p", { class: "muted small", text: body.reassessed }) : null);
  };
  briefButton.onclick = async () => {
    const asked = lang;
    fill(briefReady);
    fill(briefWhy, el("p", { class: "busy small", role: "status", text: T("brief.building") + " (" + langName(asked) + ")" }));
    briefButton.disabled = true;
    let response;
    try { response = await fetch(team.brief + "?lang=" + asked, { credentials: "same-origin", cache: "no-store" }); }
    catch (error) { briefButton.disabled = false; fill(briefWhy); notice(T("error.offline")); return; }
    briefButton.disabled = false;
    let body = {};
    try { body = (await response.json()) || {}; } catch (error) { body = {}; }
    if (asked !== lang) { fill(briefWhy); return; }
    if (!response.ok) {
      const problem = body.error || {};
      const reasons = (problem.details && problem.details.reasons) || [];
      fill(briefWhy, el("p", {}, el("strong", { text: problem.message || T("brief.blocked") })),
        reasons.length ? el("ul", { class: "list" }, reasons.map((line) => el("li", { text: line }))) : null);
      return;
    }
    fill(briefWhy);
    fill(briefReady, el("p", { class: "small", text: T("team.ready", { language: langName(body.lang), pages: body.pages }) }),
      el("div", { class: "row" }, el("a", { class: "button primary", href: body.pdf.url, download: body.pdf.filename, "data-lang": body.lang }, T("download.get") + ": " + body.pdf.filename)));
  };
  label();
  return el("section", { class: "card team-report downloads", "aria-labelledby": "downloads-title" }, sectionLabel(4, "download.title"),
    el("div", { class: "row" }, el("strong", { id: "downloads-title", text: T("team.lang") }), el("span", { class: "row", role: "group", "aria-label": T("team.lang") }, choice("tr"), choice("en"))),
    el("div", { class: "dl-grid" },
      el("div", { class: "dl-card" }, el("strong", { text: T("download.pdf.title") }), el("p", { class: "muted small", text: T("download.pdf.about") }), pdfButton, why, ready),
      el("div", { class: "dl-card" }, el("strong", { text: T("download.xlsx.title") }), el("p", { class: "muted small", text: T("download.xlsx.about") }), xlsxLink),
      team.brief ? el("div", { class: "dl-card brief" }, el("strong", { text: T("download.brief.title") }), el("p", { class: "muted small", text: T("download.brief.about") }), briefButton, briefWhy, briefReady) : null));
}

function technicalView(view, context) {
  const out = el("div");
  const o = view.outcome, c = view.counts, stat = view.pages_stat;
  const analysis = view.audit?.analysis;

  if (view.single_page) add(out, el("p", { class: "small" }, el("strong", { text: view.single_page.title })));
  if (view.headline) add(out, el("p", { class: "headline", text: view.headline }));
  if (!view.blocked) {
    // The page reader of every audit is said once, folded away; a reader used for something unusual is said in full.
    const mainReader = Boolean(view.firecrawl && view.firecrawl.main_reader && view.firecrawl.used);
    if (view.firecrawl && !mainReader) add(out, el("div", { class: "lead", role: "note" }, firecrawlStatus(view, false)));
    add(out, el("div", { class: "outcome " + (o.code || "") }, el("h3", { text: o.label || "" }), el("p", { text: o.reason_shown || o.reason || "" }), o.note ? el("p", { class: "muted small", text: o.note }) : null,
      view.coverage.resumed_note ? el("p", { class: "muted small", text: view.coverage.resumed_note }) : null, view.coverage.sampled_note ? el("p", { class: "muted small", text: view.coverage.sampled_note }) : null));
    if (mainReader) add(out, firecrawlStatus(view, true));
  }
  add(out, statusBlock(view));
  add(out, el("div", { class: "stats" },
    el("div", { class: "stat" }, el("b", { text: num(stat.value) }), stat.label, el("div", { class: "muted small", text: stat.detail }), stat.also ? el("div", { class: "muted small", text: stat.also }) : null),
    el("div", { class: "stat" }, el("b", { text: view.rendering.available ? num(view.rendering.pages_rendered) : "—" }), T("result.rendering"), el("div", { class: "muted small", text: view.rendering.label + (view.rendering.reason ? " (" + (view.rendering.reason_shown || view.rendering.reason) + ")" : "") }))));
  add(out, el("p", { class: "muted small sevs-label", text: T("result.by_severity") }), el("div", { class: "sevs", role: "list" }, ["S1", "S2", "S3", "S4", "Info"].map((level) => el("span", { class: "sev " + level, role: "listitem", text: T("result.severity." + level) + ": " + num(c.by_severity[level]) }))));

  const pr = view.practical;
  if (pr && pr.executive.opportunities.length) add(out, el("h3", { text: T("pdf.exec.opps") }), el("ul", { class: "list" }, pr.executive.opportunities.map((line) => el("li", { text: line }))));
  add(out, el("h3", { text: view.top_title || T("pdf.exec.problems.plain") }));
  if (view.first_action_withheld) add(out, el("p", { class: "muted", text: view.first_action_withheld }));
  if (!view.top.length && !view.blocked) add(out, el("p", { text: T("result.top.none") }));
  add(out, view.top.map((row) => itemRow(Object.assign({}, row, { pointer: view.block_pointer }))));
  const all = el("div"), planSlot = el("div"), compareSlot = el("div");
  add(out, el("div", { class: "row" },
    el("button", { class: "button", type: "button", onclick: () => findingsBrowser(all) }, T("result.all", { count: num(c.findings_total) })),
    el("button", { class: "button", type: "button", onclick: () => showPlan(planSlot, "") }, T("result.actions.title")),
    view.has_previous ? el("button", { class: "button", type: "button", onclick: () => showComparison(compareSlot) }, T("result.compare")) : null), all, planSlot, compareSlot);

  // Which page each problem is on, as the report counts it: the whole site first, then each page with a problem and
  // what is wrong on that page (row.lines, worded by the server).
  const byPage = view.practical && view.practical.by_page;
  if (byPage) add(out, el("details", { class: "quiet-details" }, el("summary", { text: byPage.title + " (" + num(byPage.total) + ")" }), el("div", {},
    byPage.rows.length ? el("div", { class: "table-scroll" }, el("table", { class: "data by-page" },
      el("thead", {}, el("tr", {}, byPage.columns.map((name) => el("th", { scope: "col", text: name })))),
      el("tbody", {}, byPage.rows.slice(0, 500).map((row) => el("tr", {}, el("td", { class: "wrap" }, row.whole_site ? el("strong", { text: row.label }) : pagePath(row.url)),
        el("td", { text: num(row.problems) }), el("td", {}, el("span", { class: "sev " + row.worst_severity, text: row.worst_severity_label })),
        el("td", { class: "wrap" }, el("ul", { class: "list small" }, (row.lines || row.titles).map((line) => el("li", { text: line }))))))))) : null,
    byPage.rows.length > 500 ? el("p", { class: "muted small", text: T("result.more_pages", { count: num(byPage.rows.length - 500) }) }) : null,
    byPage.not_listed.map((entry) => el("p", { class: "small", text: entry.line })),
    // Sitemaps, robots.txt and documents with a problem: files, not pages, so they are listed under the table.
    byPage.files && byPage.files.rows.length ? el("div", {}, el("h4", { text: byPage.files.title }), el("div", { class: "table-scroll" }, el("table", { class: "data by-page" },
      el("thead", {}, el("tr", {}, byPage.files.columns.map((name) => el("th", { scope: "col", text: name })))),
      el("tbody", {}, byPage.files.rows.map((row) => el("tr", {}, el("td", { class: "wrap" }, pagePath(row.url)),
        el("td", { text: num(row.problems) }), el("td", {}, el("span", { class: "sev " + row.worst_severity, text: row.worst_severity_label })),
        el("td", { class: "wrap" }, el("ul", { class: "list small" }, row.lines.map((line) => el("li", { text: line })))))))))) : null,
    el("p", { class: "muted small", text: byPage.note }))));

  if (view.review.length) add(out, el("h3", { text: T("result.review.title") }), el("ul", { class: "list" }, view.review.map((item) => el("li", {}, el("strong", { text: item.title_shown || item.title }), " ",
    el("span", { class: "muted small", text: item.check_id }), el("br"), (item.why_shown || item.why || "") + " " + (item.action_shown || item.action || ""), " ", el("button", { class: "chip", type: "button", onclick: (event) => openEvidence(item.id, event.currentTarget) }, T("result.evidence")),
    (item.details || []).length ? el("ul", { class: "list small" }, item.details.map((line) => el("li", { text: line }))) : null))));

  const coverage = view.coverage;
  add(out, el("h3", { text: T("result.coverage.title") }));
  if (coverage.read_only_note) add(out, el("p", {}, el("strong", { text: coverage.read_only_note })));
  const gaps = coverage.gaps.map((gap) => el("li", {}, el("strong", { text: gap.part_shown || gap.part || "" }), " ", el("span", { class: "muted small", text: gap.checks_label + " · " + T(gap.whole_check ? "result.coverage.whole" : "result.coverage.partial") }), el("br"), gap.reason_shown || gap.reason || ""));
  add(out, gaps.length ? el("details", { open: gaps.length <= 4 }, el("summary", { text: num(gaps.length) }), el("ul", { class: "list" }, gaps)) : (coverage.read_only_note ? null : el("p", { text: T("result.coverage.none") })));
  /* What the time limit cut, and how long each step took (DECISIONS 219). Text nodes only, never markup. */
  if (coverage.skipped_note) add(out, el("p", { class: "notice", role: "note", text: coverage.skipped_note }));
  if (coverage.steps && coverage.steps.rows.length) add(out, el("details", { class: "quiet-details" }, el("summary", { text: coverage.steps.title }),
    el("div", { class: "table-scroll" }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, coverage.steps.columns.map((name) => el("th", { scope: "col", text: name })))),
      el("tbody", {}, coverage.steps.rows.map((row) => el("tr", {}, [row.label, row.time, row.requests, row.waiting].map((cell) => el("td", { text: String(cell) })))))))));

  add(out, el("details", { class: "technical" }, el("summary", { text: view.technical.title }), el("div", {}, el("p", { class: "muted small", text: view.technical.note }),
    el("h4", { text: T("result.gates.title") }), el("ul", { class: "list" }, view.gates.map((gate) => el("li", {}, el("strong", { text: gate.check_id + " " + (gate.title_shown || gate.title) + ": " + (gate.state_label || gate.state) }), ". ", gate.summary_shown || gate.summary))),
    el("h4", { text: T("result.areas.title") }), view.areas.map((area) => el("details", {}, el("summary", { text: area.label + ": " + T("result.areas.row", { problems: Number(area.problems) || 0, notes: Number(area.notes) || 0, not_checked: num(area.not_checked) }) }),
      el("ul", { class: "list" }, area.checks.map((check) => el("li", {}, el("strong", { text: check.check_id + " " + (check.title_shown || check.title) }), " (" + check.status_label + ") ", el("span", { class: "muted", text: (check.read_only_shown ? check.read_only_shown + ". " : "") + (check.summary_shown || check.summary) })))))))));

  add(out, el("h3", { text: T("result.answers.title") }), el("p", { class: "muted small", text: view.answers.note }));
  add(out, view.answers.assessed ? el("ul", { class: "list" }, view.answers.checks.map((check) => el("li", {}, el("strong", { text: check.check_id + " " + (check.title_shown || check.title) }), " (" + check.status_label + ") ", check.summary_shown || check.summary)))
    : el("p", { text: T("result.answers.none") }));

  if (pr) {
    // The practical report in brief: when to do what, counts per area, and every page (loaded when opened).
    add(out, el("h3", { text: T("pdf.timeline") }), pr.timeline.map((step) => el("details", { class: "quiet-details" },
      el("summary", { text: step.label + " (" + num(step.count) + ")" }), el("div", {}, el("p", { class: "muted small", text: step.note }),
        el("ul", { class: "list" }, step.items.map((row) => el("li", { text: "[" + row.severity_label + "] " + row.what + " — " + row.owner + ", " + row.effort }))),
        step.count > step.items.length ? el("p", { class: "muted small", text: T("practical.timeline.more", { count: step.count - step.items.length }) }) : null))));
    add(out, el("details", { class: "quiet-details" }, el("summary", { text: T("pdf.scorecard") }), el("div", {}, el("p", { class: "muted small", text: T("pdf.scorecard.note") }),
      el("div", { class: "table-scroll" }, el("table", { class: "data" },
        el("thead", {}, el("tr", {}, ["pdf.col.area", "pdf.col.checks", "pdf.col.in_order", "result.severity.S1", "result.severity.S2", "result.severity.S3", "result.severity.S4", "pdf.col.notes", "pdf.col.not_checked"].map((key) => el("th", { scope: "col", text: T(key) })))),
        el("tbody", {}, pr.scorecard.map((row) => el("tr", {}, [row.label, row.checks, row.in_order, row.by_severity.S1, row.by_severity.S2, row.by_severity.S3, row.by_severity.S4, row.notes, row.not_checked].map((cell) => el("td", { text: cell === 0 ? "–" : String(cell) }))))))))));
    const pagesBox = el("div", {}, el("p", { class: "busy", role: "status", text: T("result.loading") }));
    const pages = el("details", { class: "quiet-details" }, el("summary", { text: T("pdf.pages") }), pagesBox);
    pages.addEventListener("toggle", async () => {
      if (!pages.open || pages.dataset.loaded) return;
      pages.dataset.loaded = "1";
      try {
        const full = await api("GET", "/audits/" + view.audit.id + "/practical");
        fill(pagesBox, el("p", { class: "muted small", text: full.pages.note }), el("div", { class: "table-scroll" }, el("table", { class: "data" },
          el("thead", {}, el("tr", {}, ["pdf.col.page", "pdf.col.status", "pdf.col.title", "pdf.col.h1", "pdf.col.words", "pdf.col.schema", "pdf.col.issues"].map((key) => el("th", { scope: "col", text: T(key) })))),
          el("tbody", {}, full.pages.rows.slice(0, 500).map((row) => el("tr", {}, [pagePath(row.url), row.status, row.title, row.h1, row.words === null ? null : num(row.words) + (row.words_cut ? "+" : ""), row.schema.join(", "), row.issues || "–"].map((cell) => el("td", { text: cell === null || cell === undefined || cell === "" ? "—" : String(cell) }))))))));
      } catch (error) { fill(pagesBox, el("p", { class: "error-text", text: error.message })); }
    });
    add(out, pages);
  }
  if (view.backlinks) {
    add(out, el("h3", { text: T("result.backlinks.title") }), el("p", { class: "muted small", text: T("result.backlinks.note") }));
    if (!view.backlinks.available) add(out, el("p", { class: "error-text", text: T("result.backlinks.unavailable") }));
    if (view.backlinks.note) add(out, el("p", { class: "notice", role: "note", text: view.backlinks.note_shown || view.backlinks.note }));
    add(out, view.backlinks.checks.map((check) => el("div", { class: "data-panel" }, el("p", {}, el("strong", { text: check.title_shown || check.title }), ": ", check.refusal ? el("span", { class: "error-text", text: check.summary }) : (check.summary_shown || check.summary)),
      dataTable(check), check.data_from ? el("p", { class: "muted small", text: T("result.data.source", { source: "DataForSEO " + (check.endpoint || ""), date: String(check.data_from).slice(0, 10), cache: T(check.from_cache ? "result.data.cached" : "result.data.fresh") }) }) : null)),
      el("p", { class: "small", text: view.backlinks.spent_line }));
  }
  if (view.ownership) add(out, el("h3", { text: T("verify.title") }), el("p", { text: view.ownership.summary_shown || view.ownership.summary }),
    view.ownership.verified ? null : el("ul", { class: "list small" }, (view.ownership.instructions_shown || view.ownership.instructions).map((line) => el("li", { text: line }))));
  if (view.crux) add(out, el("h3", { text: T("result.crux.title") }), el("p", { text: view.crux.summary_shown || view.crux.summary }),
    view.crux.metrics.length ? el("ul", { class: "list" }, view.crux.metrics.map((row) => el("li", { text: row.label + ": " + row.shown + (row.rating ? " (" + (row.rating_shown || row.rating) + ")" : "") }))) : null,
    view.crux.status === "assessed" ? el("p", { class: "muted small", text: T("result.data.source", { source: view.crux.source_shown || view.crux.source, date: view.crux.data_until || "", cache: "" }) }) : null);
  if (view.archives) add(out, el("h3", { text: T("result.archives.title") }), el("p", { class: "muted small", text: view.archives.notice_shown || view.archives.notice }),
    view.archives.sources.map((source) => el("div", { class: "data-panel" }, el("p", {}, el("strong", { text: source.name }), ": " + T("result.archives.pages", { count: Number(source.pages_read) || 0 })),
      source.pages.length ? el("ul", { class: "list" }, source.pages.map((page) => el("li", { text: (page.title || page.url) + " — " + (page.label_shown || page.label) }))) : null,
      source.findings.length ? el("ul", { class: "list" }, source.findings.map((row) => el("li", { text: "[" + row.severity + "] " + row.check_id + " " + (row.title_shown || row.title) }))) : null,
      source.notes.length ? el("details", { class: "quiet-details" }, el("summary", { text: T("result.archives.notes") }), el("ul", { class: "list" }, (source.notes_shown || source.notes).slice(0, 20).map((note) => el("li", { class: "small", text: note })))) : null)));
  if (view.suggested_key_pages.length) add(out, el("p", { class: "muted small", text: T("result.suggest_key_pages") }), el("ul", { class: "list" }, view.suggested_key_pages.map((address) => el("li", {}, link(address)))));

  add(out, el("div", { class: "row" }, profileForm(view.audit.project_id, "saved-" + view.audit.id)));
  add(out, el("h3", { text: T("result.downloads") }), el("p", { class: "muted small", text: T("result.downloads.note") + (view.team_report ? " " + T("result.downloads.other") : "") }));
  add(out, el("div", { class: "row" }, view.downloads.map((item) => item.format === "pdf"
    ? el("button", { class: "button", type: "button", onclick: () => downloadPdf(item.url, view.print_url) }, item.label)
    : el("a", { class: "button", href: item.url, download: "" }, item.label)),
    el("a", { class: "button quiet", href: view.print_url, target: "_blank", rel: "noopener" }, T("result.printable")),
    el("a", { class: "button quiet", href: view.print_url + "?full=true", target: "_blank", rel: "noopener" }, T("concise.full_technical"))));

  return out;
}

async function downloadPdf(url, printUrl) {
  let response;
  try { response = await fetch(url, { credentials: "same-origin" }); } catch (error) { notice(T("error.offline")); return; }
  if (!response.ok) { notice(T("result.pdf_unavailable")); window.open(printUrl, "_blank", "noopener"); return; }
  const blob = await response.blob();
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "");
  const anchor = el("a", { href: URL.createObjectURL(blob), download: name ? name[1] : "maya-audit.pdf" });
  document.body.append(anchor);
  anchor.click();
  setTimeout(() => { URL.revokeObjectURL(anchor.href); anchor.remove(); }, 1000);
}

/* ---------- evidence drawer ---------- */

function closeDrawer() {
  if ($("drawer").hidden) return;
  $("drawer").hidden = true;
  if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
}

async function openEvidence(evidenceId, opener) {
  const data = await guarded(() => api("GET", "/audits/" + state.auditId + "/evidence/" + encodeURIComponent(evidenceId)));
  if (!data) return;
  state.lastFocus = opener || document.activeElement;
  const record = data.record;
  const shown = data.row || {};  // the same finding as the results list words it, in the reader's language
  $("drawer-title").textContent = shown.title_shown || record.title || data.url || evidenceId;
  const section = (title, ...content) => [el("h3", { text: title }), ...content];
  fill($("drawer-body"),
    data.check ? el("p", { class: "muted small", text: data.check.check_id + " " + (data.check.title_shown || data.check.title) + (record.severity ? " · " + T("result.severity." + record.severity) : "") }) : null,
    el("p", { class: "muted small", text: T("result.evidence.note") }),
    record.how_to_fix ? section(T("result.fix"), el("p", { text: shown.fix_shown || record.how_to_fix })) : null,
    record.why_review ? section(T("result.why"), el("p", { text: (shown.why_shown || record.why_review) + " " + (shown.action_shown || record.suggested_action || "") })) : null,
    record.expected ? section(T("result.expected"), el("p", { text: shown.expected_shown || record.expected })) : null,
    (shown.details || []).length ? section(T("detail.title"), el("ul", { class: "list" }, shown.details.map((line) => el("li", { class: "small", text: line })))) : null,
    (record.notes || []).length ? section(T("result.details"), el("ul", { class: "list" }, (shown.notes_shown || record.notes).map((note) => el("li", { text: note })))) : null,
    section(T("result.evidence"), el("pre", { tabindex: 0, text: JSON.stringify(record.evidence !== undefined ? record.evidence : record, null, 2) })));
  $("drawer").hidden = false;
  $("drawer-close").focus();
}

/* ---------- start ---------- */

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("maya-theme", theme); } catch (error) { /* private mode: the choice is just not kept */ }
  // DECISIONS 310: the button names what it does ("Koyu tema"); the full sentence is its accessible name.
  $("theme").textContent = T(theme === "dark" ? "theme.to_light" : "theme.to_dark");
  $("theme").setAttribute("aria-label", T("theme.toggle") + ": " + T(theme === "dark" ? "theme.dark" : "theme.light"));
  $("theme").setAttribute("aria-pressed", String(theme === "dark"));
}

/* DECISIONS 314: when the code on this computer is newer than the running app, say so: the page and its texts belong to
   the process that serves them, and an update shows only after a restart. */
async function checkVersion() {
  let info = null;
  try { info = await api("GET", "/version"); } catch (error) { return; }
  const box = $("restart-banner");
  if (!box) return;
  box.textContent = info && info.restart_needed ? T("app.restart_needed") : "";
  box.hidden = !(info && info.restart_needed);
}

async function boot() {
  let saved = null;
  try { saved = localStorage.getItem("maya-theme"); } catch (error) { saved = null; }
  document.documentElement.setAttribute("data-theme", saved === "dark" ? "dark" : "light");
  try {
    const session = await api("GET", "/session");
    state.token = session.token;
    state.language = session.language;
    state.languages = session.languages || [];
    state.strings = (await api("GET", "/strings?language=" + encodeURIComponent(session.language))).strings;
    state.fallback = session.language === "en" ? {} : (await api("GET", "/strings?language=en")).strings;
    state.settings = await api("GET", "/settings");
  } catch (error) { notice(error.message); return; }
  checkVersion();
  setInterval(checkVersion, 5 * 60 * 1000);
  document.documentElement.lang = state.language;
  document.title = T("app.title");
  $("app-title").textContent = T("app.title");
  $("new-audit").textContent = T("nav.new");
  $("history-title").textContent = T("nav.history");
  $("search").placeholder = T("nav.search");
  $("search").setAttribute("aria-label", T("nav.search"));
  $("input-label").textContent = T("composer.label");
  $("send").textContent = T("composer.send");
  $("drawer-close").textContent = "✕";
  $("drawer-close").setAttribute("aria-label", T("word.close"));
  setTheme(document.documentElement.getAttribute("data-theme"));
  $("language-label").textContent = T("language.label");
  fill($("language"), state.languages.map((item) => el("option", { value: item.id, text: item.label, selected: item.id === state.language })));
  $("language-box").hidden = state.languages.length < 2;
  const chosen = state.languages.find((item) => item.id === state.language);
  // The translation note is kept, folded behind the language select's tooltip, not as a paragraph (DECISIONS 310).
  $("language-note").textContent = (chosen && chosen.note) || "";
  $("language-note").hidden = true;
  $("language").title = (chosen && chosen.note) || "";
  $("language").addEventListener("change", async () => {
    // The choice is kept by the server in a cookie; the page is loaded again so every sentence comes in that language.
    if (await guarded(() => api("PUT", "/session/language", { language: $("language").value }))) window.location.reload();
  });
  $("skip").textContent = T("nav.skip");
  if (state.settings.demo) { $("demo-banner").textContent = T("app.demo_banner"); $("demo-banner").hidden = false; }

  $("new-audit").addEventListener("click", newAudit);
  $("theme").addEventListener("click", () => setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"));
  $("drawer-close").addEventListener("click", closeDrawer);
  let searching = null;
  $("search").addEventListener("input", () => { clearTimeout(searching); searching = setTimeout(loadHistory, 200); });
  $("composer").addEventListener("submit", (event) => { event.preventDefault(); send($("input").value); });
  $("input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send($("input").value); } });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
    if (event.key === "Tab" && !$("drawer").hidden) {  // keep the keyboard inside the open drawer
      const stops = $("drawer").querySelectorAll("button, a[href], pre[tabindex]");
      const first = stops[0], last = stops[stops.length - 1];
      if (!$("drawer").contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  const linked = /^#analysis=(analysis-[a-z0-9-]+)$/.exec(location.hash);
  newAudit();
  if (linked) await openAudit(linked[1]);
}



/* Client-report editing is ordinary application functionality; no agent or provider call. */
async function showClientReport(box, auditId) {
  const base = "/audits/" + auditId + "/client-report";
  const work = await guarded(() => api("POST", base, {}));
  if (!work) return;
  const pending = new Map();
  const pendingNodes = [];
  const refreshPending = () => pendingNodes.forEach(node => { node.disabled = pending.size > 0 || node.dataset.invalid === "1"; });
  const unload = event => { if (pending.size && box.isConnected) { event.preventDefault(); event.returnValue = ""; } };
  window.addEventListener("beforeunload", unload);
  const draw = (w) => {
    pendingNodes.length = 0;
    const status = el("div", { role: "status", class: "client-validation" });
    const showValidation = (v) => fill(status, el("p", { text: T("client.state") + ": " + v.editorial_status + " · " + T("client.verified") + ": " + v.verified_findings }),
      el("p", { class: "muted small", text: T("client.validation.limit") }),
      el("ul", { class: "list error-text" }, v.errors.map(x => el("li", { text: x }))),
      el("ul", { class: "list" }, v.warnings.map(x => el("li", { text: x }))));
    const field = (label, value, rows = 3) => {
      const input = el("textarea", { rows, "aria-label": label, maxlength: 6000 }); input.value = value || "";
      return { input, node: el("label", { class: "client-field" }, el("span", { text: label }), input) };
    };
    const summaryPending = pending.get("summary");
    const one = field(T("client.summary"), summaryPending ? summaryPending.one_read : w.data.summary.one_read);
    const bullets = field(T("client.bullets"), summaryPending ? summaryPending.bullets : w.data.summary.bullets.join("\n"));
    for (const input of [one.input, bullets.input]) input.addEventListener("input", () => {
      pending.set("summary", { one_read: one.input.value, bullets: bullets.input.value }); refreshPending();
    });
    const summary = el("details", { open: true }, el("summary", { text: T("client.summary") }), one.node, bullets.node,
      el("button", { class: "button", type: "button", onclick: async () => {
        const next = await guarded(() => api("PUT", base + "/summary", { revision: w.revision, one_read: one.input.value,
          bullets: bullets.input.value.split("\n").filter(Boolean) })); if (next) { pending.delete("summary"); draw(next); }
      } }, T("client.save_summary")));
    const cards = w.data.cards.concat(w.data.appendix_cards);
    const cardNodes = cards.map((card) => {
      const fields = {}, body = el("div");
      const values = pending.get(card.id) || { title: card.title, explanation: card.why.text, steps: card.steps.join("\n"),
        proposed_text: card.what_to_write.text, proposed_code: card.what_to_write.code, decision: card.what_to_write.decide,
        owner: card.owner, effort: card.effort, verify: card.verify };
      const detail = el("details", { class: "client-card", "data-card-id": card.id, open: pending.has(card.id) },
        el("summary", { text: card.severity + " · " + card.title + (w.data.appendix_cards.includes(card) ? " · " + T("client.appendix") : "") }), body);
      detail.addEventListener("toggle", () => {
        if (!detail.open || body.dataset.ready) return; body.dataset.ready = "1";
        body.append(el("p", { class: "muted", text: T("client.state") + ": " + card._editorial_status + " · " + T("client.saved_not_live") }));
        Object.entries(values).filter(([key]) => key !== "references").forEach(([key,value]) => { fields[key] = field(T("client.field." + key), value); body.append(fields[key].node); });
        const refs = el("select", { multiple: true, "aria-label": T("client.references"), size: 4 }, w.references.map((r,i) =>
          el("option", { value: String(i), selected: pending.has(card.id) ? (values.references || []).includes(i) : (card.what_to_write.derived_from || []).some(x => JSON.stringify(x) === JSON.stringify(r.reference)),
            text: r.reference.url + " · " + r.reference.source + " · " + r.reference.field + " · " + r.reference.read_at + " · " + r.text })));
        const remember = () => {
          pending.set(card.id, { ...Object.fromEntries(Object.entries(fields).map(([k,v]) => [k,v.input.value])),
            references: Array.from(refs.selectedOptions, x => Number(x.value)) }); refreshPending();
        };
        for (const field of Object.values(fields)) field.input.addEventListener("input", remember);
        refs.addEventListener("change", remember);
        body.append(el("label", {}, T("client.references"), refs),
          el("details", {}, el("summary", { text: T("client.evidence") }), el("pre", { text: JSON.stringify({ where: card.where, maya: card.maya, evidence: card.evidence }, null, 2) })),
          el("button", { class: "button", type: "button", onclick: async () => {
            const fieldsOut = Object.fromEntries(Object.entries(fields).map(([k,v]) => [k,v.input.value]));
            fieldsOut.steps = fieldsOut.steps.split("\n").filter(Boolean);
            fieldsOut.references = Array.from(refs.selectedOptions, x => Number(x.value));
            const next = await guarded(() => api("PUT", base + "/cards/" + encodeURIComponent(card.id), { revision: w.revision, ...fieldsOut }));
            if (next) { pending.delete(card.id); draw(next); notice(T("client.saved")); }
          } }, T("client.save_card")));
      });
      return detail;
    });
    const notices = w.data.not_measured.map(row => ({ what: field(T("client.notice.what"), row.what, 1),
      why: field(T("client.notice.why"), row.why), how_to_enable: field(T("client.notice.how"), row.how_to_enable) }));
    const comparison = Object.entries(w.data.changes_since_last || {}).filter(([key,rows]) => Array.isArray(rows)).flatMap(([group,rows]) =>
      rows.map((row,index) => ({ group, index, field: field(group + " · " + (row.reason || ""), row.title, 1) })));
    const notesPending = pending.get("notes");
    if (notesPending) {
      notices.forEach((row,i) => Object.entries(row).forEach(([key,f]) => { f.input.value = notesPending.not_measured[i][key]; }));
      comparison.forEach((r,i) => { r.field.input.value = notesPending.comparison_titles[i].title; });
    }
    const notesBody = () => ({ not_measured: notices.map(row => Object.fromEntries(Object.entries(row).map(([key,f]) => [key,f.input.value]))),
      comparison_titles: comparison.map(r => ({ group:r.group, index:r.index, title:r.field.input.value })) });
    for (const f of notices.flatMap(row => Object.values(row)).concat(comparison.map(r => r.field))) f.input.addEventListener("input", () => {
      pending.set("notes", notesBody()); refreshPending();
    });
    const notesEditor = el("details", { open: pending.has("notes") }, el("summary", { text: T("client.notes") }),
      el("p", { class: "muted small", text: T("client.notes.help") }), notices.map(row => Object.values(row).map(f => f.node)), comparison.map(r => r.field.node),
      el("button", { class: "button", type: "button", onclick: async () => {
        const next = await guarded(() => api("PUT", base + "/notes", { revision:w.revision, ...notesBody() }));
        if (next) { pending.delete("notes"); draw(next); }
      } }, T("client.save_notes")));
    const reviewer = field(T("client.reviewer"), "", 1), reason = field(T("client.reason"), "", 2);
    const download = async (format, mode) => {
      const response = await fetch(API + base + "/export/" + format + "?mode=" + mode, { credentials: "same-origin" });
      if (!response.ok) { const error = await response.json(); notice(error.error.message); return; }
      const blob = await response.blob(), url = URL.createObjectURL(blob);
      const a = el("a", { href: url, download: "maya-client-" + auditId + "-" + mode + "." + format });
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    };
    const exports = ["draft", "final"].flatMap(mode => ["html", "pdf"].map(format =>
      el("button", { class: "button", type: "button", disabled: mode === "final" && !w.validation.valid, "data-invalid": mode === "final" && !w.validation.valid ? "1" : "0",
        onclick: () => guarded(() => download(format, mode)) }, T("client." + mode) + " " + format.toUpperCase())));
    pendingNodes.push(...exports);
    fill(box, el("h3", { text: T("client.action") }), el("p", { class: "lead", text: T("client.help") }),
      el("div", { class: "stats" }, w.data.kpis.map(k => el("div", {}, el("strong", { text: k.label + ": " + k.value }), el("p", { class: "muted small", text: k.note || "" })))),
      el("p", { text: w.data.coverage.line }), el("p", { text: w.data.coverage.score_reason }),
      el("p", { class: "small", text: T("client.identity") + ": " + auditId + " · " + w.source_digest + " · " + T("client.revision") + " " + w.revision }),
      el("p", { class: "error-text", text: T("client.all_findings", { count: cards.length, main: w.data.cards.length, appendix: w.data.appendix_cards.length }) }),
      status, summary, cardNodes, notesEditor,
      el("p", { class: "small" }, el("a", { href: API + base + "/export/json", target: "_blank", rel: "noopener" }, T("client.evidence_download")), " · ", el("a", { href: API + base + "/export/html?mode=draft&full=true", target: "_blank", rel: "noopener" }, T("client.full_evidence"))),
      el("details", {}, el("summary", { text: T("client.performance") }), w.performance.length ? w.performance.map(r => el("div", {}, el("h4", { text: r.title }), el("p", { text: r.why }), el("p", { text: r.fix }))) : el("p", { text: T("client.performance.missing") })),
      el("details", {}, el("summary", { text: T("client.evidence") }), el("pre", { text: JSON.stringify({ ...w.provenance, performance: w.performance_evidence }, null, 2) })),
      el("details", {}, el("summary", { text: T("client.review") }), el("p", { text: T("client.review.help") }), reviewer.node, reason.node,
        el("button", { class: "button", type: "button", onclick: async () => {
          if (pending.size) { notice(T("client.save_first")); return; }
          const next = await guarded(() => api("POST", base + "/review", { revision: w.revision, reviewer: reviewer.input.value, reason: reason.input.value })); if (next) draw(next);
        } }, T("client.review"))),
      el("div", { class: "row" }, el("button", { class: "button", type: "button", onclick: async () => {
        if (pending.size) { notice(T("client.save_first")); return; }
        const v = await guarded(() => api("POST", base + "/validate", {})); if (v) showValidation(v);
      } }, T("client.validate")), el("a", { class: "button", href: API + base + "/preview", target: "_blank", rel: "noopener" }, T("client.preview")), exports),
      el("p", { class: "muted small", text: T("client.save_help") }));
    // Preserve unsaved fields across saves of another section. Preview/final actions use saved data only.
    box.querySelectorAll("a[href*='/client-report/preview']").forEach(a => a.addEventListener("click", event => {
      if (pending.size) { event.preventDefault(); notice(T("client.save_first")); }
    }));
    showValidation(w.validation); refreshPending();
  };
  draw(work);
}

boot();
