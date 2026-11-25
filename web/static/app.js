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
};
function icon(name) {
  return '<svg viewBox="0 0 24 24" aria-hidden="true">' + icons[name] + '</svg>';
}
document.querySelectorAll("[data-icon]").forEach((el) => { el.innerHTML = icon(el.dataset.icon); });
const states = {active:"فعال", inactive:"متوقف", failed:"ناموفق", activating:"در حال شروع",
  deactivating:"در حال توقف", reloading:"در حال بارگذاری", unregistered:"بدون سرویس"};
const roles = {server:"سرور", client:"کلاینت"};
const pages = {overview:"نمای کلی", tunnels:"تونل‌ها", host:"میزبان", servers:"سرورها و آرشیو"};
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
function toast(message) {
  $("#toast").textContent = message;
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
  if (action !== "start" && !window.confirm("عملیات روی " + digits.format(names.length) + " تونل اجرا شود؟")) return;
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
  rows.replaceChildren();
  for (const tunnel of visible) {
    const row = rows.insertRow();
    const pick = cell(row, "", "input");
    pick.type = "checkbox";
    pick.checked = picked.has(tunnel.name);
    pick.disabled = bulkRunning || !registered.has(tunnel.name);
    pick.setAttribute("aria-label", "انتخاب " + tunnel.name);
    pick.parentElement.className = "pick";
    pick.onchange = () => {
      if (pick.checked) picked.add(tunnel.name);
      else picked.delete(tunnel.name);
      renderSelection();
    };
    const identity = cell(row, "", "div");
    identity.className = "identity";
    const mark = document.createElement("span");
    mark.innerHTML = icon("route");
    const name = document.createElement("b");
    name.dir = "ltr";
    name.textContent = tunnel.name;
    identity.append(mark, name);
    cell(row, roles[tunnel.role] || "نامشخص");
    cell(row, tunnel.endpoint || "—", "code").dir = "ltr";
    const badge = cell(row, states[tunnel.state] || "نامشخص");
    badge.className = "badge " + (Object.hasOwn(states, tunnel.state) ? tunnel.state : "neutral");
    cell(row, tunnel.mode || "—", "code").dir = "ltr";
    const button = cell(row, "جزئیات", "button");
    button.type = "button";
    button.className = "inline-action";
    button.setAttribute("aria-label", "جزئیات " + tunnel.name);
    button.onclick = () => openDetails(tunnel.name);
  }
  renderSelection();
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
function percent(selector, value) {
  const valid = Number.isFinite(value) && value >= 0 && value <= 100;
  $(selector).textContent = valid ? digits.format(Math.round(value)) + "٪" : "—";
  $(selector + "-meter").value = valid ? value : 0;
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
$("#sample-interface").addEventListener("change", renderRates);
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
    toast(error.message);
  } finally {
    button.disabled = false;
  }
};

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
    $("#updated").textContent = new Date().toLocaleTimeString("fa-IR");
    showError("#inventory-error");
    render();
    if ($("#details").open) renderDetails();
  } catch (error) {
    showError("#inventory-error", error.message);
    if ($("#host").hidden === false) toast(error.message);
  } finally {
    $("#refresh").disabled = false;
    loading = false;
  }
}
function selectPage(page) {
  currentPage = page;
  for (const item of document.querySelectorAll("[data-page]")) {
    const current = item.dataset.page === page;
    item.classList.toggle("selected", current);
    if (current) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  $("#crumb").textContent = pages[page];
  $("#host").hidden = page !== "host";
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
    body.className = "report-grid";
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
  button.className = "secondary";
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
        if (!window.confirm("تونل " + name + " با وضعیت پیشین سرویس بازیابی شود؟")) return;
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
function useRole() {
  const client = create.elements.role.value === "client";
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
  row.innerHTML = '<label>ورودی<input data-field="listen" dir="ltr" type="number" min="1" max="65535" required></label>' +
    '<label>مقصد<input data-field="target" dir="ltr" type="number" min="1" max="65535" required></label>' +
    '<label>پروتکل<select data-field="protocol" dir="ltr"><option value="tcp">TCP</option><option value="udp">UDP</option><option value="both">TCP/UDP</option></select></label>' +
    '<button type="button" class="icon-button" aria-label="حذف قانون">' + icon("close") + '</button>';
  row.querySelector("button").onclick = () => row.remove();
  $("#forward-rows").append(row);
  row.querySelector("input").focus();
}
create.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(create));
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
  $("#restore").hidden = !tunnel.backup;
  $("#refresh-network").hidden = !tunnel.tunable;
  $("#archive-control").hidden = !tunnel.archivable;
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
  tune.elements.conn.value = tunnel.conn || "1";
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
  if (!window.confirm("رابط، IPv4 و MAC مسیر جدید اعمال شوند؟ تونل فعال دوباره راه‌اندازی می‌شود.")) return;
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
    const route = await api("tunnels/" + name + "/diagnose");
    if (selected !== name) return;
    const match = route.matches === true ? "مسیر با تنظیمات تونل هم‌خوان است."
      : route.matches === false ? "رابط یا IP مسیر با تنظیمات تونل فرق دارد." : "پیکربندی رابط برای مقایسه در دسترس نیست.";
    $("#route-result").textContent = match + "\n" + route.local + " → " + route.next_hop + " → " + route.target + " · " + route.interface;
  } catch (error) {
    if (selected === name) $("#route-result").textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
$("#restore").onclick = async () => {
  if (!window.confirm("تنظیمات پیش از آخرین ویرایش بازیابی شود؟ سرویس فعال دوباره راه‌اندازی می‌شود.")) return;
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
    $("#copy").textContent = "کپی شد";
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
$("#query").oninput = $("#status").onchange = $("#role").onchange = render;
$("#refresh").onclick = refresh;
$("#logout").onclick = async () => {
  try {
    await api("logout", {});
    showLogin();
  } catch (error) {
    toast(error.message);
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
