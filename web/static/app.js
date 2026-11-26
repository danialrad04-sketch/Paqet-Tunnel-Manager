"use strict";

const $ = (selector) => document.querySelector(selector);
const icons = {
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  route: '<circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/><path d="M7 18h9a3 3 0 0 0 0-6H8a3 3 0 0 1 0-6h9"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.1M7 16.5h.1M12 7.5h5M12 16.5h5"/>',
  activity: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  pause: '<circle cx="12" cy="12" r="9"/><path d="M10 9v6m4-6v6"/>',
  alert: '<path d="m12 3 10 17H2L12 3Zm0 6v4m0 3h.01"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5m10.7-1A8 8 0 0 0 6 6m12 12a8 8 0 0 1-13.7-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 5 5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  logout: '<path d="M10 4H5v16h5m4-12 4 4-4 4m-4-4h11"/>',
  tunnel: '<path d="M3 20v-8a9 9 0 0 1 18 0v8"/><path d="M7 20v-7a5 5 0 0 1 10 0v7"/><path d="M3 20h18"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.7-8.7M17 6l2.5 2.5M15 8l2 2"/>',
  archive: '<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  upload: '<path d="M12 15V4m0 0L8 8m4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  sliders: '<path d="M4 6h10m4 0h2M4 12h4m4 0h8M4 18h12m4 0h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"/>',
  play: '<path d="M7 5v14l11-7L7 5Z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="m12 12 6-6"/>',
  network: '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-2h12v2"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  trash: '<path d="M4 7h16M10 11v6m4-6v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  arrow: '<path d="M15 6l-6 6 6 6"/>',
};
function icon(name) {
  return '<svg viewBox="0 0 24 24" aria-hidden="true">' + icons[name] + '</svg>';
}
document.querySelectorAll("[data-icon]").forEach((el) => { el.innerHTML = icon(el.dataset.icon); });

/* Theme: per-browser preference, falls back to the system setting. */
function storedTheme() {
  try { return localStorage.getItem("paqet-theme"); } catch { return null; }
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content = theme === "light" ? "#fafafa" : "#09090b";
}
applyTheme(storedTheme() || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
$("#theme").onclick = () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  applyTheme(next);
  try { localStorage.setItem("paqet-theme", next); } catch { /* storage unavailable */ }
};

/* Mobile navigation drawer */
const mobileLayout = matchMedia("(max-width: 960px)");
function setMenu(open) {
  const drawer = $("#sidebar");
  const wasOpen = drawer.classList.contains("open");
  drawer.classList.toggle("open", open);
  drawer.inert = mobileLayout.matches && !open;
  $("main").inert = open;
  $("#menu-open").setAttribute("aria-expanded", String(open));
  $("#scrim").hidden = !open;
  if (open) $("#menu-close").focus();
  else if (wasOpen && mobileLayout.matches) $("#menu-open").focus();
}
mobileLayout.addEventListener("change", () => setMenu(false));
setMenu(false);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && $("#sidebar").classList.contains("open")) setMenu(false);
});
$("#menu-open").onclick = () => setMenu(true);
$("#menu-close").onclick = $("#scrim").onclick = () => setMenu(false);

/* Promise-based confirm that matches the panel instead of window.confirm */
function confirmAction(text, {ok = "ادامه", danger = false} = {}) {
  const dialog = $("#confirm-dialog");
  $("#confirm-text").textContent = text;
  $("#confirm-ok").textContent = ok;
  $("#confirm-ok").className = "btn " + (danger ? "destructive" : "primary");
  return new Promise((resolve) => {
    const finish = (value) => {
      $("#confirm-ok").onclick = $("#confirm-cancel").onclick = null;
      dialog.onclose = null;
      if (dialog.open) dialog.close();
      resolve(value);
    };
    $("#confirm-ok").onclick = () => finish(true);
    $("#confirm-cancel").onclick = () => finish(false);
    dialog.onclose = () => finish(false);
    dialog.showModal();
    (danger ? $("#confirm-cancel") : $("#confirm-ok")).focus();
  });
}
const states = {active:"فعال", inactive:"متوقف", failed:"ناموفق", activating:"در حال شروع",
  deactivating:"در حال توقف", reloading:"در حال بارگذاری", unregistered:"بدون سرویس"};
const roles = {server:"سرور", client:"کلاینت"};
const pages = {overview:"نمای کلی", tunnels:"تونل‌ها", relays:"مسیرها و پایش", host:"میزبان", servers:"سرورها و آرشیو"};
const digits = new Intl.NumberFormat("fa-IR");
let tunnels = [];
let selected;
let loading = false;
let toastTimeout;

function showError(selector, message = "") {
  const target = $(selector);
  target.textContent = message;
  target.hidden = !message;
}
function toast(message, error = false) {
  $("#toast").textContent = message;
  $("#toast").classList.toggle("is-error", error);
  $("#toast").hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { $("#toast").hidden = true; }, 3300);
}
async function api(path, body, keepLogin = true) {
  const response = await fetch("/api/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (response.status === 401 && keepLogin) showLogin();
  if (!response.ok) throw new Error(data.error || "ارتباط با پنل برقرار نشد.");
  return data;
}
function showLogin() {
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  $("#workspace").hidden = true;
  $("#login").hidden = false;
  $("#login-form").elements.token.focus();
}
function showWorkspace(demo) {
  $("#login").hidden = true;
  $("#workspace").hidden = false;
  $("#demo").hidden = !demo;
  $("#logout").hidden = demo;
}
function cell(row, value, tag = "span") {
  const element = document.createElement(tag);
  element.textContent = value;
  row.insertCell().append(element);
  return element;
}
const picked = new Set();
let visibleServices = [];
let bulkRunning = false;

function renderSelection() {
  const header = $("#pick-visible");
  const count = visibleServices.filter((name) => picked.has(name)).length;
  header.checked = count > 0 && count === visibleServices.length;
  header.indeterminate = count > 0 && count < visibleServices.length;
  header.disabled = !visibleServices.length || bulkRunning;
  $("#bulk-actions").hidden = !picked.size;
  $("#bulk-count").textContent = digits.format(picked.size) + " تونل انتخاب شده";
}
$("#pick-visible").onchange = (event) => {
  for (const name of visibleServices) {
    if (event.target.checked) picked.add(name);
    else picked.delete(name);
  }
  render();
};
$("#bulk-clear").onclick = () => {
  picked.clear();
  render();
};
$("#bulk-actions").onsubmit = async (event) => {
  event.preventDefault();
  if (bulkRunning || !picked.size) return;
  const form = event.currentTarget;
  const action = form.elements.action.value;
  const names = [...picked];
  if (action !== "start" && !(await confirmAction("عملیات «" + form.elements.action.selectedOptions[0].text + "» روی " + digits.format(names.length) + " تونل اجرا شود؟", {ok:"اجرا", danger:action === "stop"}))) return;
  bulkRunning = true;
  for (const control of form.elements) control.disabled = true;
  render();
  const result = $("#bulk-result");
  result.hidden = false;
  let succeeded = 0;
  const failures = [];
  try {
    for (const [index, name] of names.entries()) {
      result.textContent = "در حال اجرا · " + digits.format(index + 1) + " / " + digits.format(names.length);
      try {
        await api("tunnels/" + name + "/action", {action});
        succeeded++;
        picked.delete(name);
      } catch (error) {
        failures.push(name + " — " + error.message);
        if ($("#workspace").hidden) break;
      }
    }
    result.textContent = [digits.format(succeeded) + " موفق", ...failures].join("\n");
    await refresh();
  } finally {
    bulkRunning = false;
    for (const control of form.elements) control.disabled = false;
    render();
  }
};

function render() {
  const query = $("#query").value.trim().toLowerCase();
  const status = $("#status").value;
  const role = $("#role").value;
  const visible = tunnels.filter((tunnel) =>
    (!query || (tunnel.name + " " + tunnel.endpoint).toLowerCase().includes(query)) &&
    (!status || tunnel.state === status) && (!role || tunnel.role === role));
  const registered = new Set(tunnels.filter((item) => item.state !== "unregistered").map((item) => item.name));
  for (const name of picked) if (!registered.has(name)) picked.delete(name);
  visibleServices = visible.filter((item) => registered.has(item.name)).map((item) => item.name);
  const rows = $("#rows");
  const focused = rows.contains(document.activeElement) ? document.activeElement.getAttribute("aria-label") : null;
  rows.replaceChildren();
  for (const tunnel of visible) {
    const row = rows.insertRow();
    const pick = cell(row, "", "input");
    pick.type = "checkbox";
    pick.checked = picked.has(tunnel.name);
    pick.disabled = bulkRunning || !registered.has(tunnel.name);
    pick.setAttribute("aria-label", "انتخاب " + tunnel.name);
    pick.parentElement.className = "pick";
    row.classList.toggle("is-picked", pick.checked);
    pick.onchange = () => {
      if (pick.checked) picked.add(tunnel.name);
      else picked.delete(tunnel.name);
      row.classList.toggle("is-picked", pick.checked);
      renderSelection();
    };
    row.ondblclick = (event) => {
      if (!event.target.closest("button, input")) openDetails(tunnel.name);
    };
    const identity = cell(row, "", "div");
    identity.className = "identity " + (tunnel.role || "");
    const mark = document.createElement("span");
    mark.innerHTML = icon("route");
    const name = document.createElement("b");
    name.dir = "ltr";
    name.textContent = tunnel.name;
    identity.append(mark, name);
    cell(row, roles[tunnel.role] || "نامشخص");
    const endpoint = tunnel.endpoint && tunnel.endpoint.startsWith(":") ? "0.0.0.0" + tunnel.endpoint : tunnel.endpoint;
    cell(row, endpoint || "—", "code").dir = "ltr";
    const badge = cell(row, states[tunnel.state] || "نامشخص");
    badge.className = "badge " + (Object.hasOwn(states, tunnel.state) ? tunnel.state : "neutral");
    cell(row, tunnel.mode || "—", "code").dir = "ltr";
    const button = cell(row, "مدیریت", "button");
    button.type = "button";
    button.className = "inline-action";
    button.insertAdjacentHTML("beforeend", icon("chevron"));
    button.setAttribute("aria-label", "جزئیات " + tunnel.name);
    button.onclick = () => openDetails(tunnel.name);
  }
  if (focused) rows.querySelector('[aria-label="' + CSS.escape(focused) + '"]')?.focus({preventScroll:true});
  renderSelection();
  const filtered = Boolean(query || status || role);
  $("#empty").hidden = visible.length > 0;
  rows.closest("table").hidden = visible.length === 0;
  $("#empty-title").textContent = tunnels.length ? "تونلی با این فیلترها پیدا نشد" : "هنوز تونلی ساخته نشده";
  $("#empty-text").textContent = tunnels.length ? "عبارت جست‌وجو یا فیلترها را تغییر دهید."
    : "اولین تونل را بسازید تا وضعیت و گزارش آن اینجا نمایش داده شود.";
  $("#empty-create").hidden = filtered && tunnels.length > 0;
  $("#nav-count").textContent = digits.format(tunnels.length);
  $("#nav-count").hidden = !tunnels.length;
  $("#count").textContent = visible.length
    ? digits.format(visible.length) + " از " + digits.format(tunnels.length) + " تونل"
    : (tunnels.length ? "تونلی با این فیلترها پیدا نشد." : "هنوز سرویسی ثبت نشده است.");
}
const regions = {ir:"ایران", foreign:"خارج"};
const topologies = {client:"میزبان کلاینت", server:"میزبان سرور", mixed:"میزبان سرور و کلاینت", unknown:"نقش هنوز شناسایی نشده"};
let currentPage = "overview";
let latestOverview;
let previousSample;
let interfaceRates = {};

function renderIncident() {
  const bad = tunnels.filter((tunnel) => tunnel.state === "failed");
  $("#incident").hidden = currentPage !== "overview" || bad.length === 0;
  $("#incident-title").textContent = digits.format(bad.length) + " سرویس ناموفق";
  $("#incident-list").textContent = bad.slice(0, 4).map((tunnel) => tunnel.name).join("، ") +
    (bad.length > 4 ? " و " + digits.format(bad.length - 4) + " مورد دیگر" : "");
}
const history = {cpu: [], memory: [], rx: [], tx: []};
const HISTORY = 30;
function push(series, value) {
  series.push(Number.isFinite(value) ? value : null);
  if (series.length > HISTORY) series.shift();
}
function sparkPath(series, max) {
  const points = series.map((value, index) => value === null ? null :
    [(index + HISTORY - series.length) * (120 / (HISTORY - 1)), 31 - Math.min(value / max, 1) * 29]);
  let path = "";
  let pen = false;
  for (const point of points) {
    if (!point) { pen = false; continue; }
    path += (pen ? "L" : "M") + point[0].toFixed(1) + " " + point[1].toFixed(1);
    pen = true;
  }
  return path;
}
function drawSpark(id, series, max = 100) {
  const svg = $(id);
  const line = svg.querySelector(".spark-line");
  const fill = svg.querySelector(".spark-fill");
  const d = sparkPath(series, max);
  line.setAttribute("d", d);
  if (fill) {
    const firstX = d.match(/^M([\d.]+)/)?.[1];
    const lastX = d.match(/([\d.]+) [\d.]+$/)?.[1];
    fill.setAttribute("d", d && firstX && lastX ? d + "L" + lastX + " 32L" + firstX + " 32Z" : "");
  }
}
function drawNet() {
  const max = Math.max(1024, ...history.rx.filter(Number.isFinite), ...history.tx.filter(Number.isFinite)) * 1.15;
  const svg = $("#net-spark");
  svg.querySelector(".rx").setAttribute("d", sparkPath(history.rx, max));
  svg.querySelector(".tx").setAttribute("d", sparkPath(history.tx, max));
}
function percent(selector, value) {
  const valid = Number.isFinite(value) && value >= 0 && value <= 100;
  $(selector).textContent = valid ? digits.format(Math.round(value)) + "٪" : "—";
  $(selector + "-meter").value = valid ? value : 0;
  const key = selector.slice(1);
  push(history[key], valid ? value : NaN);
  drawSpark(selector + "-spark", history[key]);
}
function rate(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const unit = value >= 1048576 ? ["MiB/s", 1048576] : value >= 1024 ? ["KiB/s", 1024] : ["B/s", 1];
  return (value / unit[1]).toFixed(unit[1] === 1 ? 0 : 1) + " " + unit[0];
}
function renderRates() {
  const speeds = interfaceRates[$("#sample-interface").value] || [];
  $("#rx").textContent = rate(speeds[0]);
  $("#tx").textContent = rate(speeds[1]);
}
function renderSample(sample, demo) {
  $("#telemetry-note").textContent = demo ? "پایش سیستم‌عامل در حالت نمایشی در دسترس نیست."
    : "نمونه‌برداری هر ۱۰ ثانیه · ترافیک کل رابط انتخابی";
  const counters = sample.interfaces || {};
  const memory = sample.memory || {};
  const seconds = previousSample ? sample.time - previousSample.time : 0;
  interfaceRates = Object.create(null);
  if (seconds > 0) {
    for (const [name, values] of Object.entries(counters)) {
      const old = previousSample.interfaces?.[name];
      if (old) interfaceRates[name] = values.map((value, index) => (value - old[index]) / seconds);
    }
  }
  const select = $("#sample-interface");
  const selection = select.value;
  const names = Object.keys(counters).sort();
  select.replaceChildren(...names.map((name) => new Option(name, name)));
  if (names.includes(selection)) select.value = selection;
  select.disabled = !names.length;
  renderRates();
  const speeds = interfaceRates[select.value] || [];
  push(history.rx, speeds[0]);
  push(history.tx, speeds[1]);
  drawNet();
  const cpu = sample.cpu || [];
  const previousCpu = previousSample?.cpu || [];
  const deltas = cpu.map((value, index) => value - previousCpu[index]);
  const total = deltas.reduce((sum, value) => sum + value, 0);
  percent("#cpu", total > 0 ? (1 - (deltas[3] + deltas[4]) / total) * 100 : NaN);
  percent("#memory", memory.MemTotal > 0 ? (1 - memory.MemAvailable / memory.MemTotal) * 100 : NaN);
  const ready = Boolean(sample.time && (cpu.length || names.length || memory.MemTotal));
  $("#sample-state").textContent = ready ? "در حال پایش" : "داده در دسترس نیست";
  $("#sample-state").className = "badge " + (ready ? "active" : "neutral");
  previousSample = sample;
}
$("#sample-interface").addEventListener("change", () => {
  history.rx.length = history.tx.length = 0;
  drawNet();
  renderRates();
});
$("#show-failed").onclick = () => {
  $("#status").value = "failed";
  $("#query").value = $("#role").value = "";
  selectPage("tunnels");
  render();
};
$("#region-form").elements.region.onchange = (event) => { event.target.dataset.dirty = "true"; };
$("#region-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await api("region", {region:form.elements.region.value});
    delete form.elements.region.dataset.dirty;
    form.elements.region.blur();
    await refresh();
    toast("موقعیت میزبان ذخیره شد.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
};

function renderPath(overview, activeCount) {
  const local = overview.region === "ir" ? "ایران" : overview.region === "foreign" ? "خارج" : overview.host;
  $("#path-local").textContent = local || "—";
  const peers = [...new Set(tunnels.filter((tunnel) => tunnel.role === "client" && tunnel.endpoint)
    .map((tunnel) => tunnel.endpoint.replace(/:\d+$/, "").replace(/^\[|\]$/g, "")))];
  $("#path-remote").dir = peers.length === 1 ? "ltr" : "auto";
  $("#path-remote").textContent = peers.length === 1 ? peers[0]
    : peers.length > 1 ? digits.format(peers.length) + " سرور"
    : overview.topology === "server" ? "کلاینت‌ها" : "—";
  $("#path-count").textContent = digits.format(activeCount) + " فعال از " + digits.format(tunnels.length);
  $(".path-viz").classList.toggle("idle", activeCount === 0);
}
async function refresh() {
  if (loading) return;
  loading = true;
  $("#refresh").disabled = true;
  try {
    const overview = await api("overview");
    latestOverview = overview;
    tunnels = overview.tunnels;
    const topology = topologies[overview.topology] || topologies.unknown;
    $("#topology").textContent = $("#hero-topology").textContent = topology;
    $("#hero-region").textContent = regions[overview.region] || "موقعیت تعیین نشده";
    const region = $("#region-form").elements.region;
    if (document.activeElement !== region && !region.dataset.dirty) region.value = overview.region || "";
    renderSample(overview.sample || {}, overview.demo);
    renderIncident();
    $("#total").textContent = digits.format(tunnels.length);
    for (const state of ["active", "inactive", "failed"]) {
      $("#" + state).textContent = digits.format(tunnels.filter((tunnel) => tunnel.state === state).length);
    }
    $("#sidebar-host").textContent = overview.host;
    $("#hostname").textContent = overview.host;
    $("#core").textContent = overview.core ? "نصب شده" : "در دسترس نیست";
    $("#updated").textContent = $("#sync-time").textContent = new Date().toLocaleTimeString("fa-IR", {hour:"2-digit", minute:"2-digit", second:"2-digit"});
    $("#sync-state").classList.remove("stale");
    const failedCount = tunnels.filter((tunnel) => tunnel.state === "failed").length;
    const activeCount = tunnels.filter((tunnel) => tunnel.state === "active").length;
    $("#failed").closest(".metric").classList.toggle("hot", failedCount > 0);
    renderPath(overview, activeCount);
    showError("#inventory-error");
    render();
    if ($("#details").open) renderDetails();
  } catch (error) {
    showError("#inventory-error", error.message);
    $("#sync-state").classList.add("stale");
    if ($("#host").hidden === false) toast(error.message, true);
  } finally {
    $("#refresh").disabled = false;
    loading = false;
  }
}
function selectPage(page) {
  currentPage = page;
  setMenu(false);
  window.scrollTo({top: 0});
  for (const item of document.querySelectorAll("[data-page]")) {
    const current = item.dataset.page === page;
    item.classList.toggle("selected", current);
    if (current) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  $("#crumb").textContent = pages[page];
  $("#host").hidden = page !== "host";
  $("#relays").hidden = page !== "relays";
  if (page === "relays") loadRelays();
  $("#servers").hidden = page !== "servers";
  $("#tunnels").hidden = !["overview", "tunnels"].includes(page);
  if (page === "host") loadReport();
  if (page === "servers") { loadHosts(); loadArchives(); }
  $("#hero").hidden = $("#metrics").hidden = $("#telemetry").hidden = page !== "overview";
  renderIncident();
}

function reportList(title, lines, direction = "auto") {
  const item = document.createElement("article");
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("ul");
  for (const value of lines.length ? lines : ["داده‌ای ثبت نشده است."]) {
    const row = document.createElement("li");
    row.dir = direction;
    row.textContent = value;
    list.append(row);
  }
  item.append(heading, list);
  return item;
}
async function loadReport() {
  const button = $("#load-report");
  if (button.disabled) return;
  button.disabled = true;
  showError("#report-error");
  try {
    const report = await api("host-report");
    const gib = (bytes) => (bytes / 1073741824).toFixed(1) + " GiB";
    const days = Math.floor(report.uptime / 86400);
    const hours = Math.floor(report.uptime / 3600) % 24;
    const body = $("#host-report");
    body.className = "card-body report-grid";
    body.replaceChildren(
      reportList("سیستم", [report.kernel, "زمان روشن بودن " + digits.format(days) + " روز و " + digits.format(hours) + " ساعت",
        "فضای مصرف‌شدهٔ دیسک " + gib(report.disk[1]) + " از " + gib(report.disk[0])]),
      reportList("رابط‌ها و آدرس‌ها", report.interfaces.map((link) =>
        [link.name, link.state, "MTU " + link.mtu, ...link.addresses].join(" · ")), "ltr"),
      reportList("جدول مسیر اصلی", report.routes.map((route) =>
        [route.destination, route.gateway && "via " + route.gateway, route.interface, route.metric === "" ? "" : "metric " + route.metric].filter(Boolean).join(" · ")), "ltr"),
      reportList("پورت‌های شنود", report.listeners.map(([protocol, address]) => protocol.toUpperCase() + " · " + address), "ltr"),
      reportList("DNS", report.dns, "ltr"),
    );
  } catch (error) {
    showError("#report-error", error.message);
  } finally {
    button.disabled = false;
  }
}
$("#load-report").onclick = loadReport;
function listEntry(list, label, detail) {
  const row = document.createElement("li");
  const title = document.createElement("strong");
  title.textContent = label;
  row.append(title);
  if (detail) {
    const address = document.createElement("code");
    address.dir = "ltr";
    address.textContent = detail;
    row.append(address);
  }
  list.append(row);
  return row;
}
function listButton(row, title, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn outline sm";
  button.textContent = title;
  button.onclick = async () => {
    button.disabled = true;
    try { await action(); } finally { button.disabled = false; }
  };
  row.append(button);
}
const hostsForm = $("#hosts-form");
let editingHost;
hostsForm.onreset = () => {
  editingHost = undefined;
  $("#cancel-host-edit").hidden = true;
};
function renderHosts(hosts) {
  const list = $("#hosts-list");
  list.replaceChildren();
  if (!hosts.length) listEntry(list, "هنوز سروری اضافه نشده است.");
  for (const host of hosts) {
    const address = host.address + ":" + host.port;
    const region = regions[host.region];
    const row = listEntry(list, host.label + (region ? " · " + region : ""), address);
    const link = document.createElement("a");
    link.href = "http://" + address;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "باز کردن پنل";
    row.append(link);
    listButton(row, "ویرایش", async () => {
      editingHost = {address:host.address, port:host.port};
      $("#cancel-host-edit").hidden = false;
      for (const field of ["label", "address", "port", "region"]) hostsForm.elements[field].value = host[field];
      hostsForm.elements.label.focus();
    });
    listButton(row, "حذف از دفتر", async () => {
      showError("#hosts-error");
      try {
        const result = await api("hosts", {...host, action:"remove"});
        renderHosts(result.hosts);
      } catch (error) { showError("#hosts-error", error.message); }
    });
  }
}
async function loadHosts() {
  showError("#hosts-error");
  try { renderHosts((await api("hosts")).hosts); }
  catch (error) { showError("#hosts-error", error.message); }
}
hostsForm.onsubmit = async (event) => {
  event.preventDefault();
  const button = hostsForm.querySelector("[type=submit]");
  button.disabled = true;
  showError("#hosts-error");
  try {
    const result = await api("hosts", {...Object.fromEntries(new FormData(hostsForm)), action:"save", previous:editingHost});
    renderHosts(result.hosts);
    hostsForm.reset();
    toast("سرور ذخیره شد.");
  } catch (error) { showError("#hosts-error", error.message); }
  finally { button.disabled = false; }
};
async function loadArchives() {
  const list = $("#archives-list");
  showError("#archives-error");
  try {
    const {names} = await api("archives");
    list.replaceChildren();
    if (!names.length) listEntry(list, "آرشیو خالی است.");
    for (const name of names) {
      const row = listEntry(list, name);
      listButton(row, "بازیابی تونل", async () => {
        if (!(await confirmAction("تونل " + name + " با وضعیت پیشین سرویس بازیابی شود؟", {ok:"بازیابی"}))) return;
        try {
          await api("archives/" + name + "/restore", {});
          await loadArchives();
          await refresh();
          toast("تونل از آرشیو بازیابی شد.");
        } catch (error) { showError("#archives-error", error.message); }
      });
    }
  } catch (error) { showError("#archives-error", error.message); }
}

const create = $("#create-form");
for (const radio of create.querySelectorAll('[name="role-pick"]')) {
  radio.onchange = () => { create.elements.role.value = radio.value; useRole(); };
}
function useRole() {
  const client = create.elements.role.value === "client";
  for (const radio of create.querySelectorAll('[name="role-pick"]')) radio.checked = radio.value === create.elements.role.value;
  $("#remote-label").hidden = $("#forwards").hidden = !client;
  create.elements.remote.disabled = !client;
  create.elements.remote.required = client;
  create.elements.key.required = client;
  create.elements.key.placeholder = client ? "کلید مشترک سرور" : "برای ساخت خودکار خالی بگذارید";
  $("#forwards").querySelectorAll("input, select").forEach((field) => { field.disabled = !client; });
}
function addForward() {
  if ($("#forward-rows").children.length >= 24) return;
  const row = document.createElement("div");
  row.className = "forward-row";
  row.innerHTML = '<label>IP ورودی کلاینت<input data-field="listen_ip" dir="ltr" value="0.0.0.0" required></label>' +
    '<label>پورت ورودی<input data-field="listen" dir="ltr" type="number" min="1" max="65535" required></label>' +
    '<label>IP مقصد از سمت سرور<input data-field="target_ip" dir="ltr" value="127.0.0.1" required></label>' +
    '<label>پورت مقصد<input data-field="target" dir="ltr" type="number" min="1" max="65535" required></label>' +
    '<label>پروتکل<select data-field="protocol" dir="ltr"><option value="tcp">TCP</option><option value="udp">UDP</option><option value="both">TCP/UDP</option></select></label>' +
    '<button type="button" class="btn ghost icon" aria-label="حذف قانون">' + icon("trash") + '</button>';
  row.querySelector("button").onclick = () => { row.remove(); updateCreatePreview(); };
  $("#forward-rows").append(row);
  updateCreatePreview();
  row.querySelector("input").focus();
}
create.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(create));
  delete data["role-pick"];
  if (peerTransport && data.role === "client") data.transport = peerTransport;
  if (data.role === "client") {
    data.forwards = Array.from($("#forward-rows").children, (row) =>
      Object.fromEntries(Array.from(row.querySelectorAll("[data-field]"), (field) => [field.dataset.field, field.value])));
  }
  const submit = create.querySelector("[type=submit]");
  submit.disabled = true;
  showError("#create-error");
  try {
    const result = await api("tunnels", data);
    $("#create-dialog").close();
    if (result.key) {
      $("#key-value").value = result.key;
      $("#key-dialog").showModal();
    }
    toast("تونل ایجاد شد.");
    await refresh();
  } catch (error) {
    showError("#create-error", error.message);
  } finally {
    submit.disabled = false;
  }
});
const batch = $("#batch-form");
const batchDialog = $("#batch-dialog");
const batchResult = $("#batch-result");
let batchRunning = false;
batchDialog.addEventListener("cancel", (event) => {
  if (batchRunning) event.preventDefault();
});
batchDialog.addEventListener("close", () => {
  batch.reset();
  batchResult.textContent = "";
  batchResult.hidden = true;
  showError("#batch-error");
});
$("#open-batch").onclick = () => batchDialog.showModal();
const batchHint = $("#batch-file-name").textContent;
$("#batch-file").onchange = () => {
  const file = $("#batch-file").files[0];
  $("#batch-file-name").textContent = file ? file.name + " · " + digits.format(Math.ceil(file.size / 1024)) + " کیلوبایت" : batchHint;
};
batch.addEventListener("reset", () => { $("#batch-file-name").textContent = batchHint; });
batch.onsubmit = async (event) => {
  event.preventDefault();
  const file = $("#batch-file").files[0];
  showError("#batch-error");
  batchResult.hidden = true;
  batchResult.textContent = "";
  let entries;
  try {
    if (!file || file.size > 65536) throw new Error("حجم فایل باید کمتر از ۶۴ کیلوبایت باشد.");
    entries = JSON.parse(await file.text());
    if (!Array.isArray(entries) || entries.length < 1 || entries.length > 20 ||
        entries.some((entry) => !entry || typeof entry.name !== "string" || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}$/.test(entry.name))) {
      throw new Error("فایل باید یک آرایه شامل ۱ تا ۲۰ تونل با نام معتبر باشد.");
    }
    if (new Set(entries.map((entry) => entry.name)).size !== entries.length) {
      throw new Error("نام تونل‌ها در فایل باید یکتا باشد.");
    }
  } catch (error) {
    showError("#batch-error", error instanceof SyntaxError ? "فایل JSON معتبر نیست." : error.message);
    return;
  }
  batchRunning = true;
  const buttons = batch.querySelectorAll("button");
  buttons.forEach((button) => { button.disabled = true; });
  batchResult.hidden = false;
  const output = [];
  try {
    for (const [index, entry] of entries.entries()) {
      batchResult.textContent = [...output, "در حال ساخت " + digits.format(index + 1) + " / " + digits.format(entries.length)].join("\n");
      try {
        const result = await api("tunnels", entry, false);
        output.push(entry.name + " — ایجاد شد" + (result.key ? "\n" + result.key : ""));
      } catch (error) {
        output.push(entry.name + " — " + error.message);
      }
    }
    batchResult.textContent = output.join("\n");
    await refresh();
  } finally {
    batchRunning = false;
    buttons.forEach((button) => { button.disabled = false; });
  }
};

function renderDetails() {
  const tunnel = tunnels.find((entry) => entry.name === selected);
  if (!tunnel) return;
  $("#detail-name").textContent = selected;
  $("#detail-state").textContent = [roles[tunnel.role], states[tunnel.state] || "نامشخص",
    tunnel.enabled ? "اجرای خودکار روشن" : "اجرای خودکار خاموش"].filter(Boolean).join(" · ");
  const registered = tunnel.state !== "unregistered";
  $(".service-actions").hidden = $("#log-head").hidden = $("#logs").hidden = !registered;
  $("#edit-config").hidden = !tunnel.editable;
  $("#edit-forward").hidden = $("#edit-config").hidden || tunnel.role !== "client";
  $("#config-history").hidden = !tunnel.editable;
  $("#export-recovery").hidden = !tunnel.editable || tunnel.role !== "client";
  $("#config-rotation").hidden = !tunnel.editable || !registered ||
    !(tunnel.role === "server" || tunnel.forwards.some(rule => rule.protocol === "tcp"));
  $("#export-peer").hidden = $("#edit-config").hidden || tunnel.role !== "server";
  $("#restore").hidden = !tunnel.backup;
  $("#refresh-network").hidden = !tunnel.tunable;
  $("#archive-control").hidden = !tunnel.archivable;
  const listeners = tunnel.forwards.filter(rule => rule.protocol === "tcp").map(rule => rule.listen);
  const choices = $("#probe-listen");
  if (JSON.stringify(listeners) !== choices.dataset.listeners) {
    choices.replaceChildren(...listeners.map(value => new Option(value, value)));
    choices.dataset.listeners = JSON.stringify(listeners);
    clearProbe();
  }
  $("#probe-section").hidden = tunnel.role !== "client" || tunnel.state !== "active" || !listeners.length;
  if ($("#probe-section").hidden) clearProbe();
  $("#diagnostic").hidden = !registered || tunnel.role !== "client" || !tunnel.endpoint;
  const facts = $("#detail-facts");
  facts.replaceChildren();
  for (const [label, value] of [
    ["آدرس", tunnel.endpoint], ["رابط شبکه", tunnel.interface], ["IPv4 محلی", tunnel.local],
    ["منبع نقش", {explicit:"نقش ثبت‌شده در YAML",inferred:"استنباط از آدرس پیکربندی",unknown:"نامشخص"}[tunnel.evidence]],
    ["منبع تنظیمات", {default:"فایل استاندارد",alternate:"مسیر جایگزین در systemd",unresolved:"مسیر قابل تأیید نیست",file:"فایل بدون سرویس"}[tunnel.source]],
    ["شناسهٔ پردازش", tunnel.pid !== "0" && tunnel.pid],
    ["تعداد راه‌اندازی مجدد", tunnel.restarts], ["نتیجهٔ systemd", tunnel.result], ["آخرین فعال‌سازی", tunnel.since],
  ]) {
    if (!value || value === "n/a") continue;
    const item = document.createElement("div");
    const title = document.createElement("dt");
    const text = document.createElement("dd");
    title.textContent = label;
    text.textContent = value;
    text.dir = "auto";
    item.append(title, text);
    facts.append(item);
  }
  $("#detail-forwards").hidden = !tunnel.forwards.length;
  $("#forward-list").replaceChildren(...tunnel.forwards.map((rule) => {
    const line = document.createElement("li");
    line.textContent = rule.protocol.toUpperCase() + " · " + rule.listen + " → " + rule.target;
    return line;
  }));
  $("#autostart").dataset.action = tunnel.enabled ? "disable" : "enable";
  $("#autostart").textContent = tunnel.enabled ? "خاموش کردن اجرای خودکار" : "روشن کردن اجرای خودکار";
}
async function loadLogs() {
  const name = selected;
  $("#reload-logs").disabled = true;
  try {
    const {logs} = await api("tunnels/" + name + "/logs");
    if (selected === name) $("#logs").textContent = logs || "گزارشی ثبت نشده است.";
  } catch (error) {
    if (selected === name) showError("#detail-error", error.message);
  } finally {
    $("#reload-logs").disabled = false;
  }
}
const tuning = $("#tuning");
const tune = $("#tune-form");
const kcpFields = ["nodelay","interval","resend","nocongestion","rcvwnd","sndwnd","smuxbuf","streambuf",
  "dshard","pshard","smuxkalive","smuxktimeout","wdelay","acknodelay"];
for (const key of kcpFields) {
  const label = document.createElement("label");
  label.textContent = key;
  label.className = "field";
  const boolean = ["wdelay", "acknodelay"].includes(key);
  const field = document.createElement(boolean ? "select" : "input");
  field.name = key;
  field.dir = "ltr";
  if (boolean) field.append(new Option("پیش‌فرض", ""), new Option("true"), new Option("false"));
  else { field.type = "number"; field.min = "0"; field.max = "2147483647"; field.placeholder = "پیش‌فرض"; }
  label.append(field);
  $("#advanced-kcp").append(label);
}
tune.onsubmit = async (event) => {
  event.preventDefault();
  const submit = tune.querySelector("[type=submit]");
  submit.disabled = true;
  showError("#detail-error");
  try {
    await api("tunnels/" + selected + "/tune", Object.fromEntries(new FormData(tune)));
    tuning.open = false;
    toast("تنظیمات ذخیره شد.");
    await refresh();
    if ($("#details").open) await loadLogs();
  } catch (error) {
    showError("#detail-error", error.message);
  } finally {
    submit.disabled = false;
  }
};
tuning.addEventListener("toggle", () => {
  if (!tuning.open) return;
  const tunnel = tunnels.find((entry) => entry.name === selected);
  if (!tunnel) return;
  tune.reset();
  tune.elements.mtu.value = tunnel.mtu || "1350";
  for (const field of ["tcpbuf","udpbuf","sockbuf"]) tune.elements[field].value = tunnel.buffers?.[field] ?? "";
  tune.elements.level.value = tunnel.level || "";
  tune.elements.conn.value = tunnel.conn || "1";
  for (const key of kcpFields) tune.elements[key].value = tunnel.advanced?.[key] ?? "";
});
function openDetails(name) {
  selected = name;
  $("#route-result").textContent = "";
  $("#archive-control").open = false;
  $("#archive-form").reset();
  tuning.open = false;
  tuning.hidden = !tunnels.find((tunnel) => tunnel.name === name)?.tunable;
  renderDetails();
  showError("#detail-error");
  $("#logs").textContent = "در حال دریافت گزارش…";
  $("#details").showModal();
  if (!$("#logs").hidden) loadLogs();
}
document.querySelectorAll(".service-actions button").forEach((button) => {
  button.onclick = async () => {
    const peers = document.querySelectorAll(".service-actions button");
    peers.forEach((peer) => { peer.disabled = true; });
    showError("#detail-error");
    try {
      await api("tunnels/" + selected + "/action", {action:button.dataset.action});
      toast("عملیات سرویس انجام شد.");
      await refresh();
      if ($("#details").open) await loadLogs();
    } catch (error) {
      showError("#detail-error", error.message);
    } finally {
      peers.forEach((peer) => { peer.disabled = false; });
    }
  };
});
$("#reload-logs").onclick = loadLogs;
$("#archive-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  const name = selected;
  button.disabled = true;
  showError("#detail-error");
  try {
    await api("tunnels/" + name + "/archive", {confirmation:form.elements.confirmation.value});
    if (selected === name) $("#details").close();
    await refresh();
    toast("تونل به آرشیو منتقل شد.");
  } catch (error) { if (selected === name) showError("#detail-error", error.message); }
  finally { button.disabled = false; }
};
$("#refresh-network").onclick = async () => {
  const name = selected;
  if (!(await confirmAction("رابط، IPv4 و MAC مسیر جدید اعمال شوند؟ تونل فعال دوباره راه‌اندازی می‌شود.", {ok:"اعمال"}))) return;
  const button = $("#refresh-network");
  button.disabled = true;
  showError("#detail-error");
  try {
    await api("tunnels/" + name + "/network", {});
    await refresh();
    toast("تنظیمات شبکه به‌روزرسانی شد.");
  } catch (error) { if (selected === name) showError("#detail-error", error.message); }
  finally { button.disabled = false; }
};
$("#check-route").onclick = async () => {
  const name = selected;
  const button = $("#check-route");
  button.disabled = true;
  try {
    const report = await api("tunnels/" + name + "/preflight");
    const route = report.route;
    if (selected !== name) return;
    const match = route.matches === true ? "مسیر با تنظیمات تونل هم‌خوان است."
      : route.matches === false ? "رابط یا IP مسیر با تنظیمات تونل فرق دارد." : "پیکربندی رابط برای مقایسه در دسترس نیست.";
    $("#route-result").textContent = match + "\n" + route.local + " → " + route.next_hop + " → " + route.target + " · " + route.interface
      + "\n" + "MTU هسته " + (report.configured_mtu || "—") + " · MTU رابط " + (report.interface_mtu || "—")
      + "\n" + ({ok:"بستهٔ ICMP این اندازه عبور کرد.", too_large:"بستهٔ ICMP برای این مسیر بزرگ است.",
        inconclusive:"پاسخ قطعی به ICMP نرسید.", unavailable:"آزمون ICMP اجرا نشد.", demo:"دادهٔ نمایشی"})[report.df_test];
  } catch (error) {
    if (selected === name) $("#route-result").textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
$("#restore").onclick = async () => {
  if (!(await confirmAction("تنظیمات پیش از آخرین ویرایش بازیابی شود؟ سرویس فعال دوباره راه‌اندازی می‌شود.", {ok:"بازگردانی"}))) return;
  const button = $("#restore");
  button.disabled = true;
  showError("#detail-error");
  try {
    await api("tunnels/" + selected + "/restore", {});
    await refresh();
    toast("تنظیمات قبلی بازیابی شد.");
  } catch (error) {
    showError("#detail-error", error.message);
  } finally {
    button.disabled = false;
  }
};
$("#add-forward").onclick = addForward;
create.elements.role.onchange = useRole;
$("#key-dialog").addEventListener("close", () => { $("#key-value").value = ""; });
$("#copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("#key-value").value);
    $("#copy").textContent = "کپی شد ✓";
    toast("کلید در کلیپ‌بورد کپی شد.");
  } catch {
    $("#key-value").select();
  }
};
document.querySelectorAll("[data-close]").forEach((button) => {
  button.onclick = () => button.closest("dialog").close();
});
document.querySelectorAll("[data-create]").forEach((button) => {
  button.onclick = () => {
    create.reset();
    peerTransport = undefined;
    $("#peer-status").textContent = "";
    $("#forward-rows").replaceChildren();
    $("#copy").textContent = "کپی کلید";
    showError("#create-error");
    if (latestOverview?.region === "ir") create.elements.role.value = "client";
    else if (latestOverview?.region === "foreign") create.elements.role.value = "server";
    else if (["client", "server"].includes(latestOverview?.topology)) create.elements.role.value = latestOverview.topology;
    useRole();
    $("#create-dialog").showModal();
  };
});
document.querySelectorAll("[data-page]").forEach((button) => {
  button.onclick = () => selectPage(button.dataset.page);
});
document.querySelectorAll("[data-page-link]").forEach((button) => {
  button.onclick = () => selectPage(button.dataset.pageLink);
});
document.addEventListener("keydown", (event) => {
  if ($("#sidebar").classList.contains("open")) return;
  if (event.key !== "/" || event.ctrlKey || event.metaKey || document.querySelector("dialog[open]")) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName) || $("#workspace").hidden) return;
  event.preventDefault();
  if ($("#tunnels").hidden) selectPage("tunnels");
  $("#query").focus();
});
$("#query").oninput = $("#status").onchange = $("#role").onchange = render;
$("#refresh").onclick = refresh;
$("#logout").onclick = async () => {
  try {
    await api("logout", {});
    showLogin();
  } catch (error) {
    toast(error.message, true);
  }
};
$("#login-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  showError("#login-error");
  try {
    await api("login", {token:form.elements.token.value}, false);
    form.reset();
    showWorkspace(false);
    await refresh();
  } catch (error) {
    showError("#login-error", error.message);
  } finally {
    button.disabled = false;
  }
};
async function init() {
  try {
    const session = await api("session");
    if (session.authenticated) {
      showWorkspace(session.demo);
      await refresh();
    } else showLogin();
  } catch (error) {
    showLogin();
    showError("#login-error", error.message);
  }
}
init();

setInterval(() => {
  if (!document.hidden && !$("#workspace").hidden) refresh();
}, 10000);

let peerTransport;
$("#peer-file").onchange = async (event) => {
  peerTransport = undefined;
  $("#peer-status").textContent = "";
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 65536) throw Error("فایل اتصال بزرگ است.");
    const profile = JSON.parse(await file.text());
    const kcp = profile.transport?.kcp;
    if (profile.format !== "paqet-peer-v1" || !kcp?.key) throw Error("فایل اتصال معتبر نیست.");
    create.elements.port.value = profile.port;
    create.elements.key.value = kcp.key;
    create.elements.mode.value = kcp.mode || "fast";
    create.elements.mtu.value = kcp.mtu || 1350;
    create.elements.conn.value = profile.transport.conn || 1;
    peerTransport = profile.transport;
    $("#peer-status").textContent = "پارامترهای سرور وارد شد. IPv4 عمومی سرور و ورودی‌های کلاینت را مشخص کنید.";
    updateCreatePreview();
  } catch (error) { showError("#create-error", error.message); }
};
$("#export-peer").onclick = async () => {
  try {
    const profile = await api("tunnels/" + selected + "/pair");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(profile, null, 2)], {type:"application/json"}));
    link.download = selected + "-peer.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    toast("فایل اتصال حاوی کلید مشترک است.");
  } catch (error) { showError("#detail-error", error.message); }
};
const yamlForm = $("#yaml-form");
let yamlRevision;
function openYaml(name, text, revision) {
  yamlRevision = revision;
  yamlForm.elements.name.value = name;
  yamlForm.elements.name.readOnly = Boolean(revision);
  $("#preview-yaml").hidden = $("#yaml-group-label").hidden = !revision;
  yamlForm.elements.group.value = "";
  $("#yaml-diff").hidden = true;
  yamlForm.elements.yaml.value = text;
  showError("#yaml-error");
  $("#yaml-dialog").showModal();
}
$("#yaml-dialog").addEventListener("close", () => { yamlForm.reset(); yamlRevision = undefined; });
$("#open-yaml-create").onclick = () => openYaml("", "", null);
$("#edit-config").onclick = async () => {
  const name = selected;
  try {
    const result = await api("tunnels/" + name + "/config");
    if ($("#details").open && name === selected) openYaml(name, result.yaml, result.revision);
  } catch (error) { showError("#detail-error", error.message); }
};
yamlForm.onsubmit = async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(yamlForm));
  const button = yamlForm.querySelector("[type=submit]");
  button.disabled = true;
  try {
    const path = "tunnels/" + data.name;
    if (yamlRevision && data.group) {
      await api(path + "/history", {...data, action:"apply_group", revision:yamlRevision});
    } else {
      await api(yamlRevision ? path + "/config" : "tunnels", {...data, revision:yamlRevision});
    }
    $("#yaml-dialog").close();
    await refresh();
    toast("پیکربندی ذخیره شد.");
  } catch (error) { showError("#yaml-error", error.message); }
  finally { button.disabled = false; }
};

let forwardEdit;
function editRule(rule = {listen:"0.0.0.0:", target:"127.0.0.1:", protocol:"tcp"}) {
  const row = document.createElement("div");
  row.className = "forward-row";
  row.innerHTML = '<label>ورودی کلاینت (IP:port)<input required dir="ltr" name="listen"></label><label>مقصد از سرور (host:port)<input required dir="ltr" name="target"></label><label>پروتکل<select name="protocol"><option>tcp</option><option>udp</option></select></label><button type="button" class="btn outline sm">حذف قانون</button>';
  for (const key of ["listen", "target", "protocol"]) row.querySelector("[name="+key+"]").value = rule[key];
  row.querySelector("button").onclick = () => { row.remove(); updateEditPreview(); };
  $("#edit-forward-rows").append(row);
  updateEditPreview();
}
$("#new-forward-rule").onclick = () => editRule();
$("#edit-forward").onclick = async () => {
  const name = selected;
  try {
    const config = await api("tunnels/" + name + "/config");
    if (selected !== name || !$("#details").open) return;
    forwardEdit = {name, revision:config.revision};
    $("#edit-forward-rows").replaceChildren();
    updateEditPreview();
    for (const rule of config.forwards) editRule(rule);
    showError("#forward-error");
    $("#forward-dialog").showModal();
  } catch (error) { showError("#detail-error", error.message); }
};
$("#forward-form").onsubmit = async (event) => {
  event.preventDefault();
  const rules = Array.from($("#edit-forward-rows").children, row =>
    Object.fromEntries(Array.from(row.querySelectorAll("[name]"), field => [field.name, field.value])));
  const button = event.currentTarget.querySelector("[type=submit]");
  button.disabled = true;
  try {
    await api("tunnels/"+forwardEdit.name+"/forwards", {rules, revision:forwardEdit.revision});
    $("#forward-dialog").close();
    await refresh();
    toast("قوانین انتقال ذخیره شد.");
  } catch (error) { showError("#forward-error", error.message); }
  finally { button.disabled = false; }
};

$("#setup-help").onclick = () => $("#guide-dialog").showModal();
let probeGeneration = 0;
function clearProbe() {
  probeGeneration++;
  $("#probe-live").checked = false;
  $("#probe-result").textContent = "";
}
async function probe() {
  const button = $("#probe-now");
  if (button.disabled || !$("#details").open || $("#probe-section").hidden) return;
  const generation = probeGeneration;
  button.disabled = true;
  try {
    const result = await api("tunnels/" + selected + "/probe", {listen:$("#probe-listen").value});
    if (generation !== probeGeneration) return;
    const labels = {demo:"نمونهٔ نمایشی؛ آزمون شبکه اجرا نشد.", tcp:"ورودی TCP اتصال را پذیرفت. پاسخ TLS دریافت نشد.",
      unreachable:"اتصال به ورودی TCP برقرار نشد.", tls:"پاسخ TLS از مسیر فوروارد دریافت شد."};
    const timing = result.status === "tls" ? " · " + result.version + " · " + digits.format(result.ms) + " ms" : "";
    $("#probe-result").textContent = new Date().toLocaleTimeString("fa-IR") + " · " + labels[result.status] + timing;
  } catch (error) {
    if (generation === probeGeneration) $("#probe-result").textContent = error.message;
  } finally { button.disabled = false; }
}
$("#details").addEventListener("close", clearProbe);
$("#probe-now").onclick = probe;
$("#probe-listen").onchange = clearProbe;
$("#probe-live").onchange = () => { if ($("#probe-live").checked) probe(); };
setInterval(() => { if (!document.hidden && $("#probe-live").checked) probe(); }, 30000);

const relayForm = $("#relay-form");
const routeNames = {paqet:"Paqet", https:"HTTPS", quic:"QUIC", standby:"Paqet آماده‌به‌کار"};
let relayProfile, quicProfile, storedRelayPeer, storedQuicPeer, relayLoading = false;
let quicAvailable = false;

function downloadJson(filename, value) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:"application/json"}));
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function jsonFile(input) {
  const file = input.files[0];
  if (!file) return undefined;
  if (file.size > 65536) throw Error("فایل اتصال بیش از ۶۴ کیلوبایت است.");
  try { return JSON.parse(await file.text()); }
  catch { throw Error("ساختار JSON فایل اتصال معتبر نیست."); }
}

function socketLabel(value) {
  if (!value) return "";
  return Array.isArray(value) ? (value[0].includes(":") ? "[" + value[0] + "]" : value[0]) + ":" + value[1] : value;
}

function updateRelayForm() {
  const {role, transport, listen, target, domain, selected: route, primary, backup, probe, probe_host, probe_path} = relayForm.elements;
  const receiver = role.value === "receiver";
  $("#receiver-fields").hidden = !receiver;
  $("#entry-fields").hidden = receiver;
  domain.required = target.required = receiver;
  const http = !receiver && ["http", "https"].includes(probe.value);
  probe_host.disabled = probe_path.disabled = !http;
  probe_host.required = http;
  relayForm.elements.automatic.disabled = !receiver && probe.value === "tcp";
  if (relayForm.elements.automatic.disabled) relayForm.elements.automatic.checked = false;
  const peer = relayProfile ? relayProfile.domain + ":" + relayProfile.port : storedRelayPeer ? "گیرندهٔ HTTPS ثبت‌شده" : "فایل گیرنده";
  const quic = quicProfile ? quicProfile.domain + ":" + quicProfile.port : storedQuicPeer ? "گیرندهٔ QUIC ثبت‌شده" : "فایل گیرندهٔ QUIC";
  const hops = {paqet:primary.value, standby:backup.value, https:peer, quic};
  listen.placeholder = receiver ? (transport.value === "quic" ? "0.0.0.0:24443" : "0.0.0.0:8443") : "127.0.0.1:24105";
  $("#relay-preview").textContent = receiver
    ? [domain.value || "دامنهٔ خارج", listen.value || (transport.value === "quic" ? "شنوندهٔ UDP" : "شنوندهٔ TLS"), target.value || "مقصد محلی"].join(" → ")
    : ["اتصال کاربر", listen.value || "ورودی ایران", hops[route.value] || routeNames[route.value], "سرویس روی خارج"].join(" → ");
}

function openRelay(row) {
  relayForm.reset();
  relayProfile = quicProfile = undefined;
  storedQuicPeer = Boolean(row?.has_quic_peer);
  $("#quic-profile-status").textContent = storedQuicPeer ? "فایل قبلی حفظ می‌شود." : "اختیاری";
  storedRelayPeer = Boolean(row?.has_peer);
  $("#relay-profile-status").textContent = storedRelayPeer ? "فایل اتصال قبلی حفظ می‌شود." : "اختیاری";
  for (const key of ["name", "role", "transport", "listen", "domain", "target", "primary", "backup", "probe", "probe_host", "probe_path", "budget"]) {
    if (row?.[key] !== undefined) relayForm.elements[key].value = socketLabel(row[key]) || relayForm.elements[key].value;
  }
  relayForm.elements.selected.value = row?.configured || "paqet";
  relayForm.elements.automatic.checked = Boolean(row?.automatic);
  relayForm.elements.name.readOnly = Boolean(row);
  relayForm.elements.role.disabled = Boolean(row);
  relayForm.elements.transport.disabled = Boolean(row);
  relayForm.elements.transport.querySelector('[value="quic"]').disabled = !quicAvailable;
  relayForm.elements.selected.querySelector('[value="quic"]').disabled = !quicAvailable;
  $("#quic-profile").disabled = !quicAvailable;
  showError("#relay-form-error");
  updateRelayForm();
  $("#relay-dialog").showModal();
}

$("#add-relay").onclick = () => openRelay();
relayForm.oninput = updateRelayForm;
for (const [selector, kind] of [["#relay-profile", "https"], ["#quic-profile", "quic"]]) {
  $(selector).onchange = async event => {
    let profile;
    showError("#relay-form-error");
    try {
      const result = await jsonFile(event.target);
      if (result && result.format !== "paqet-" + kind + "-v1") {
        throw Error("فایل از گیرندهٔ " + kind.toUpperCase() + " صادر نشده است.");
      }
      profile = result;
    } catch (error) { showError("#relay-form-error", error.message); }
    if (kind === "quic") quicProfile = profile;
    else relayProfile = profile;
    const stored = kind === "quic" ? storedQuicPeer : storedRelayPeer;
    $(selector + "-status").textContent = profile?.domain || (stored ? "فایل قبلی حفظ می‌شود." : "اختیاری");
    updateRelayForm();
  };
}
relayForm.onsubmit = async (event) => {
  event.preventDefault();
  const button = relayForm.querySelector("[type=submit]");
  button.disabled = true;
  try {
    await api("relays", {...Object.fromEntries(new FormData(relayForm)), action:"save",
      role:relayForm.elements.role.value, automatic:relayForm.elements.automatic.checked,
      transport:relayForm.elements.transport.value,
      peer:relayProfile, keep_peer:storedRelayPeer, quic_peer:quicProfile, keep_quic_peer:storedQuicPeer});
    $("#relay-dialog").close();
    toast("مسیر ذخیره شد.");
    await loadRelays();
  } catch (error) { showError("#relay-form-error", error.message); }
  finally { button.disabled = false; }
};

async function operateRelay(row, action, extra = {}) {
  showError("#relay-error");
  try {
    const result = await api("relays", {name:row.name, action, ...extra});
    if (action === "profile") downloadJson(row.name + "-" + (row.transport || "https") + "-peer.json", result);
    else await loadRelays();
  } catch (error) { showError("#relay-error", error.message); }
}

function addRelayInfo(container, title, detail, direction = "auto") {
  const line = document.createElement("p");
  const heading = document.createElement("strong");
  const text = document.createElement("bdi");
  heading.textContent = title + " ";
  text.dir = direction;
  text.textContent = detail;
  line.append(heading, text);
  container.append(line);
}

function relayCard(row, demo) {
  const card = document.createElement("article");
  card.className = "card relay-card";
  const heading = document.createElement("div");
  heading.className = "card-head";
  const title = document.createElement("h2");
  title.dir = "auto";
  title.textContent = row.name;
  heading.append(title);
  listButton(heading, "ویرایش", () => openRelay(row));
  card.append(heading);
  const body = document.createElement("div");
  body.className = "card-body relay-body";
  card.append(body);
  const status = demo ? "نمایشی" : row.online ? "شنونده فعال" : "شنونده در دسترس نیست";
  addRelayInfo(body, status, row.listen, "ltr");
  const actions = document.createElement("div");
  actions.className = "inventory-actions";
  if (row.role === "receiver") {
    addRelayInfo(body, row.transport === "quic" ? "گیرندهٔ QUIC روی UDP" : "گیرندهٔ HTTPS", row.domain + " → " + socketLabel(row.target), "ltr");
    listButton(actions, "دریافت فایل اتصال", () => operateRelay(row, "profile"));
  } else {
    addRelayInfo(body, "مسیر فعال", routeNames[row.selected] + (row.automatic ? " · جابه‌جایی خودکار" : ""));
    if (row.switched) addRelayInfo(body, "آخرین جابه‌جایی", new Date(row.switched * 1000).toLocaleString("fa-IR"));
    const used = (row.bytes / 1073741824).toFixed(3);
    const forecast = row.projected_days == null ? "" : row.projected_days <= new Date().getUTCDate()
      ? " · با نرخ فعلی در محدودهٔ روز جاری یا زودتر" : " · برآورد روز " + digits.format(Math.ceil(row.projected_days)) + " از ابتدای دوره";
    addRelayInfo(body, "مصرف ماه UTC " + row.month, used + " GiB" +
      (row.budget ? " / " + row.budget + " GiB" + (Number(used) >= row.budget ? " · سقف رد شد" : forecast) : ""));
    addRelayInfo(body, "اتصال‌های باز", digits.format(row.connections));
    const list = document.createElement("ul");
    list.className = "admin-list route-tests";
    for (const route of row.routes) {
      const result = row.tests[route];
      const comparison = row.comparison?.results?.[route];
      const status = result ? (result.ok ? result.ms + " ms" : "خطا") + " · " +
        new Date(result.time * 1000).toLocaleTimeString("fa-IR") : "در انتظار پایش";
      const entry = listEntry(list, routeNames[route], status);
      if (comparison) addRelayInfo(entry, "مقایسه", comparison.ok + "/" + comparison.total + " پاسخ · " +
        (comparison.p50_ms == null ? "—" : comparison.p50_ms + " ms") + " · بار آزمون " + comparison.load_bytes + " B");
      if (row.selected !== route) listButton(entry, "اعمال برای اتصال‌های جدید", () => operateRelay(row, "select", {route}));
    }
    body.append(list);
    if (row.routes.length > 1 && !demo) {
      if (row.comparison?.status === "running") addRelayInfo(body, "مقایسه", "در حال اجرا");
      else listButton(actions, "مقایسهٔ مسیرها", () => operateRelay(row, "compare"));
      if (row.comparison?.status === "error") addRelayInfo(body, "مقایسه", "اندازه‌گیری ناموفق بود.");
    }
    if (row.history.length) {
      const history = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "نتایج اخیر پایش";
      history.append(summary);
      for (const item of row.history.slice(-12).reverse()) {
        addRelayInfo(history, new Date(item.time * 1000).toLocaleTimeString("fa-IR"),
          Object.entries(item.tests).map(([route, result]) => routeNames[route] + " · " + (result.ok ? result.ms + " ms" : "خطا")).join(" | "));
      }
      body.append(history);
    }
  }
  listButton(actions, "حذف مسیر", async () => {
    if (await confirmAction("شنوندهٔ این مسیر بسته شود؟", {ok:"حذف", danger:true})) await operateRelay(row, "remove");
  });
  body.append(actions);
  return card;
}

let lastRelays;
async function loadRelays() {
  if (relayLoading || $("#relays").hidden) return;
  relayLoading = true;
  try {
    const data = await api("relays");
    quicAvailable = data.quic;
    $("#quic-install-hint").hidden = quicAvailable;
    const hash = JSON.stringify(data);
    if (hash === lastRelays) return;
    lastRelays = hash;
    const list = $("#relay-list");
    list.replaceChildren(...data.rows.map(row => relayCard(row, data.demo)));
    if (!data.rows.length) addRelayInfo(list, "هنوز مسیری ثبت نشده است.", "برای آزمایش، مسیر جدید بسازید.");
  } catch (error) { showError("#relay-error", error.message); }
  finally { relayLoading = false; }
}
setInterval(() => { if (!document.hidden && !$("#workspace").hidden) loadRelays(); }, 5000);

let historyName;
let historyRevision;
async function loadHistory() {
  const {entries, revision} = await api("tunnels/" + historyName + "/history");
  historyRevision = revision;
  const list = $("#history-list");
  list.replaceChildren();
  if (!entries.length) listEntry(list, "هنوز نسخه‌ای ثبت نشده است.");
  for (const point of entries) {
    const row = listEntry(list, [point.group || "ویرایش محلی", new Date(point.time * 1000).toLocaleString("fa-IR")].join(" · "), point.revision.slice(0, 12));
    const data = {id:point.id, point:point.revision, revision:historyRevision};
    listButton(row, "نمایش تفاوت", async () => {
      try {
        const {diff} = await api("tunnels/" + historyName + "/history", {...data, action:"diff"});
        const output = $("#history-diff");
        output.textContent = diff || "تفاوتی در فیلدهای قابل نمایش وجود ندارد.";
        output.hidden = false;
      } catch (error) { showError("#history-error", error.message); }
    });
    listButton(row, "بازیابی نسخه", async () => {
      if (!await confirmAction("این نسخه بازیابی شود؟ سرویس فعال دوباره راه‌اندازی خواهد شد.", {ok:"بازیابی"})) return;
      try {
        await api("tunnels/" + historyName + "/history", {...data, action:"restore"});
        $("#history-diff").hidden = true;
        await loadHistory();
        await refresh();
        toast("نسخه بازیابی شد.");
      } catch (error) { showError("#history-error", error.message); }
    });
  }
}
$("#config-history").onclick = async () => {
  historyName = selected;
  $("#checkpoint-form").reset();
  $("#checkpoint-peer").value = "";
  $("#checkpoint-comparison").hidden = $("#history-diff").hidden = true;
  showError("#history-error");
  try { await loadHistory(); $("#history-dialog").showModal(); }
  catch (error) { showError("#detail-error", error.message); }
};
$("#checkpoint-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
    await api("tunnels/" + historyName + "/history", {action:"checkpoint", group:form.elements.group.value});
      await loadHistory();
    toast("نقطهٔ بازیابی ثبت شد.");
  } catch (error) { showError("#history-error", error.message); }
};

$("#preview-yaml").onclick = async () => {
  try {
    const {diff} = await api("tunnels/" + yamlForm.elements.name.value + "/history",
      {action:"preview", yaml:yamlForm.elements.yaml.value});
    const output = $("#yaml-diff");
    output.textContent = diff || "تفاوتی در فیلدهای قابل نمایش وجود ندارد.";
    output.hidden = false;
  } catch (error) { showError("#yaml-error", error.message); }
};

const rotationForm = $("#rotation-form");
let rotationTunnel, rotationRevision;
$("#config-rotation").onclick = async () => {
  const tunnel = tunnels.find(row => row.name === selected);
  if (!tunnel) return;
  try {
    const result = await api("tunnels/" + tunnel.name + "/history");
    rotationTunnel = tunnel;
    rotationRevision = result.revision;
    rotationForm.reset();
    const server = tunnel.role === "server";
    $("#rotation-forward-label").hidden = $("#rotation-file-label").hidden = server;
    $("#rotation-profile").required = !server;
    rotationForm.elements.forward.replaceChildren(...tunnel.forwards.filter(rule => rule.protocol === "tcp")
      .map(rule => new Option(rule.listen + " → " + rule.target, rule.listen)));
    $("#rotation-help").textContent = server
      ? "یک نام و پورت تازه وارد کنید. فایل خروجی را از طریق نشست مدیریتی به پنل کلاینت بدهید."
      : "فایل سرور را وارد کنید. پس از آزمون، ورودی loopback تازه را در بخش مسیرها به‌عنوان Paqet آماده‌به‌کار انتخاب کنید.";
    $("#rotation-result").hidden = true;
    showError("#rotation-error");
    $("#rotation-dialog").showModal();
  } catch (error) { showError("#detail-error", error.message); }
};
rotationForm.onsubmit = async event => {
  event.preventDefault();
  const button = rotationForm.querySelector("[type=submit]");
  button.disabled = true;
  try {
    const profile = await jsonFile($("#rotation-profile"));
    const result = await api("tunnels/" + rotationTunnel.name + "/rotation",
      {...Object.fromEntries(new FormData(rotationForm)), revision:rotationRevision, profile});
    if (result.profile) downloadJson(result.name + "-rotation.json", result.profile);
    $("#rotation-result").textContent = result.listen ? "ورودی تازه " + result.listen : "فایل گردش کلید آماده شد.";
    $("#rotation-result").hidden = false;
    await refresh();
  } catch (error) { showError("#rotation-error", error.message); }
  finally { button.disabled = false; }
};

let supportReport;
$("#share-diagnostic").onclick = async () => {
  try {
    supportReport = await api("tunnels/" + selected + "/diagnostic");
    $("#support-text").textContent = JSON.stringify(supportReport, null, 2);
    $("#support-dialog").showModal();
  } catch (error) { showError("#detail-error", error.message); }
};
$("#download-support").onclick = () => { if (supportReport) downloadJson("paqet-diagnostic.json", supportReport); };

function renderForwardPreview(selector, rows, server) {
  const output = $(selector);
  output.textContent = rows.map(([from, to]) => [from, server, to].join(" → ")).join("\n");
  output.hidden = !rows.length;
}

function updateCreatePreview() {
  const server = (create.elements.remote.value || "IPv4") + ":" + (create.elements.port.value || "KCP");
  const rows = Array.from($("#forward-rows").children, row => {
    const field = key => row.querySelector("[data-field=" + key + "]").value;
    return [field("listen_ip") + ":" + (field("listen") || "?"), field("target_ip") + ":" + (field("target") || "?")];
  });
  renderForwardPreview("#create-route-preview", rows, server);
}
create.addEventListener("input", updateCreatePreview);

function updateEditPreview() {
  const rows = Array.from($("#edit-forward-rows").children,
    row => [row.querySelector("[name=listen]").value, row.querySelector("[name=target]").value]);
  renderForwardPreview("#edit-route-preview", rows, tunnels.find(row => row.name === selected)?.endpoint || "Paqet");
}
$("#edit-forward-rows").addEventListener("input", updateEditPreview);

async function checkpointReceipt(group) {
  return api("tunnels/" + historyName + "/history", {action:"receipt", group});
}
$("#checkpoint-receipt").onclick = async () => {
  const group = $("#checkpoint-form").elements.group;
  if (!group.reportValidity()) return;
  try { downloadJson(group.value + "-status.json", await checkpointReceipt(group.value)); }
  catch (error) { showError("#history-error", error.message); }
};
$("#checkpoint-peer").onchange = async (event) => {
  const output = $("#checkpoint-comparison");
  output.hidden = true;
  showError("#history-error");
  try {
    const peer = await jsonFile(event.target);
    if (!peer) return;
    const status = {changed:"تغییر کرده", at_checkpoint:"در نسخهٔ نقطهٔ بازیابی"};
    if (peer.format !== "paqet-checkpoint-v1" || !Object.hasOwn(status, peer.status) ||
        !["server", "client"].includes(peer.role)) throw Error("فایل وضعیت معتبر نیست.");
    const current = await checkpointReceipt(peer.group);
    if (peer.role === current.role) throw Error("فایل باید از سمت دیگر تونل صادر شده باشد.");
    output.textContent = "شناسهٔ " + current.group + " · این میزبان " + status[current.status] +
      " · میزبان مقابل در زمان صدور فایل " + status[peer.status];
    output.hidden = false;
  } catch (error) { showError("#history-error", error.message); }
};

const recoveryDialog = $("#recovery-dialog");
const recoveryForm = $("#recovery-form");
let recoveryExport, recoveryDraft;

function clearRecoveryPreview() {
  recoveryDraft = undefined;
  $("#recovery-apply").hidden = $("#recovery-summary").hidden = true;
}

function openRecovery(name) {
  recoveryExport = name;
  recoveryForm.reset();
  clearRecoveryPreview();
  showError("#recovery-error");
  $("#recovery-title").textContent = name ? "دریافت فایل بازیابی" : "بازیابی تونل ایران";
  $("#recovery-description").textContent = name
    ? "فایل رمزگذاری‌شده شامل تنظیمات اتصال و کلید مشترک است. فایل و عبارت بازیابی را جداگانه ذخیره کنید. برای انتقال عبارت از نشست مدیریتی روی SSH استفاده کنید."
    : "فایل و عبارت بازیابی را وارد کنید. پنل مسیر به سرور خارج و پورت‌های ورودی را بررسی می‌کند. عبارت بازیابی را از طریق نشست مدیریتی روی SSH وارد کنید.";
  $("#recovery-file-label").hidden = $("#recovery-name-label").hidden = Boolean(name);
  recoveryForm.elements.bundle.required = !name;
  recoveryForm.elements.name.disabled = Boolean(name);
  $("#recovery-submit").textContent = name ? "دریافت فایل رمزگذاری‌شده" : "پیش‌بررسی روی این میزبان";
  recoveryDialog.showModal();
}

$("#open-recovery").onclick = () => openRecovery();
$("#export-recovery").onclick = () => openRecovery(selected);
recoveryForm.oninput = clearRecoveryPreview;
recoveryDialog.onclose = () => {
  recoveryForm.reset();
  clearRecoveryPreview();
};

function renderRecovery(result) {
  const facts = $("#recovery-facts");
  facts.replaceChildren();
  for (const [label, value] of [
    ["نام تونل تازه", result.name], ["کلاینت قبلی", result.source], ["مقصد خارج", result.remote],
    ["رابط خروجی", result.interface], ["IPv4 محلی تشخیص‌داده‌شده", result.local],
  ]) {
    const item = document.createElement("div");
    const title = document.createElement("dt");
    const detail = document.createElement("dd");
    title.textContent = label;
    detail.dir = "ltr";
    detail.textContent = value;
    item.append(title, detail);
    facts.append(item);
  }
  $("#recovery-listeners").replaceChildren(...result.listeners.map(row => {
    const line = document.createElement("li");
    const listener = row.listen === row.original ? row.listen : row.original + " ⇒ " + row.listen;
    line.textContent = row.protocol.toUpperCase() + " · " + listener + (row.target ? " → " + row.target : " · SOCKS5");
    return line;
  }));
  $("#recovery-summary").hidden = $("#recovery-apply").hidden = false;
}

async function recoveryOperation(callback) {
  const controls = [...recoveryForm.elements];
  const disabled = controls.map(field => field.disabled);
  controls.forEach(field => field.disabled = true);
  showError("#recovery-error");
  try { await callback(); }
  catch (error) { showError("#recovery-error", error.message); }
  finally { controls.forEach((field, i) => field.disabled = disabled[i]); }
}

recoveryForm.onsubmit = async event => {
  event.preventDefault();
  await recoveryOperation(async () => {
    const {password, bundle, name} = recoveryForm.elements;
    if (recoveryExport) {
      const encrypted = await api("recovery", {action:"export", name:recoveryExport, password:password.value});
      downloadJson(recoveryExport + "-recovery.json", encrypted);
      recoveryDialog.close();
      toast("فایل بازیابی رمزگذاری‌شده دریافت شد.");
      return;
    }
    clearRecoveryPreview();
    const file = bundle.files[0];
    if (!file || file.size > 400000) throw Error("فایل بازیابی معتبر نیست یا حجم آن زیاد است.");
    const data = {bundle:JSON.parse(await file.text()), name:name.value, password:password.value};
    const result = await api("recovery", {...data, action:"preview"});
    recoveryDraft = {bundle:data.bundle, name:result.name, preview:result.preview};
    renderRecovery(result);
  });
};

$("#recovery-apply").onclick = async () => {
  if (!recoveryDraft) return;
  await recoveryOperation(async () => {
    const result = await api("recovery", {...recoveryDraft, action:"restore",
      password:recoveryForm.elements.password.value});
    recoveryDialog.close();
    await refresh();
    toast(result.demo ? "بازیابی نمایشی انجام شد." : "تونل «" + result.name + "» ساخته و فعال شد.");
    if (tunnels.some(row => row.name === result.name)) openDetails(result.name);
  });
};
recoveryDialog.addEventListener("cancel", event => {
  if ($("#recovery-submit").disabled) event.preventDefault();
});
