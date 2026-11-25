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
  deactivating:"در حال توقف", reloading:"در حال بارگذاری"};
const roles = {server:"سرور", client:"کلاینت"};
const pages = {overview:"نمای کلی", tunnels:"تونل‌ها", host:"میزبان"};
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
function render() {
  const query = $("#query").value.trim().toLowerCase();
  const status = $("#status").value;
  const role = $("#role").value;
  const visible = tunnels.filter((tunnel) =>
    (!query || (tunnel.name + " " + tunnel.endpoint).toLowerCase().includes(query)) &&
    (!status || tunnel.state === status) && (!role || tunnel.role === role));
  const rows = $("#rows");
  rows.replaceChildren();
  for (const tunnel of visible) {
    const row = rows.insertRow();
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
  $("#count").textContent = visible.length
    ? digits.format(visible.length) + " از " + digits.format(tunnels.length) + " تونل"
    : (tunnels.length ? "تونلی با این فیلترها پیدا نشد." : "هنوز سرویسی ثبت نشده است.");
}
async function refresh() {
  if (loading) return;
  loading = true;
  $("#refresh").disabled = true;
  try {
    const overview = await api("overview");
    tunnels = overview.tunnels;
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
  for (const item of document.querySelectorAll("[data-page]")) {
    const current = item.dataset.page === page;
    item.classList.toggle("selected", current);
    if (current) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  $("#crumb").textContent = pages[page];
  $("#host").hidden = page !== "host";
  $("#tunnels").hidden = page === "host";
  $("#hero").hidden = $("#metrics").hidden = page !== "overview";
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
  tuning.open = false;
  tuning.hidden = !tunnels.find((tunnel) => tunnel.name === name)?.tunable;
  renderDetails();
  showError("#detail-error");
  $("#logs").textContent = "در حال دریافت گزارش…";
  $("#details").showModal();
  loadLogs();
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
