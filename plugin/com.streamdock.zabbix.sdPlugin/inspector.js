"use strict";

const API = "http://127.0.0.1:18398";
const $ = (id) => document.getElementById(id);

const IS_RU = (navigator.language || "en").toLowerCase().startsWith("ru");
const RU_STRINGS = {
  "Preview: ": "Предпросмотр: ",
  "Loading widgets...": "Загрузка виджетов...",
  "Loading Zabbix widgets...": "Чтение виджетов Zabbix...",
  "Untitled": "Без названия",
  "no item binding": "нет привязанного элемента",
  "Select widget": "Выберите виджет",
  "Available widgets: ": "Доступно виджетов: ",
  "There are no Item value widgets on this page.": "На выбранной странице нет виджетов «Значение элемента данных».",
  "Select a widget, then save the selection.": "Выберите виджет и сохраните настройку.",
  "Cannot load widgets": "Не удалось загрузить виджеты",
  "Widget request failed: ": "Ошибка получения виджетов: ",
  "Loading pages...": "Загрузка страниц...",
  "Select page": "Выберите страницу",
  "Enter a numeric Dashboard ID.": "Укажите числовой ID Dashboard.",
  "Loading dashboard pages...": "Чтение страниц Dashboard...",
  "No accessible dashboard pages.": "У Dashboard нет доступных страниц.",
  "Saved page no longer exists. Choose another.": "Сохранённая страница больше не существует. Выберите другую.",
  "Cannot load pages": "Не удалось загрузить страницы",
  "Dashboard error: ": "Ошибка Dashboard: ",
  "Connecting to the local Zabbix bridge...": "Подключение к локальному мосту Zabbix...",
  "Select Dashboard": "Выберите Dashboard",
  "Choose a Dashboard or enter its ID manually.": "Выберите Dashboard из списка или укажите ID вручную.",
  "Dashboard list unavailable": "Список временно недоступен",
  "Dashboard request failed: ": "Ошибка получения Dashboard: ",
  "Not connected to HotSpot.": "Нет подключения к HotSpot.",
  "Press Open to load an ID": "Нажмите Открыть для ID",
  "Choose a Dashboard, page and widget first.": "Сначала выберите Dashboard, страницу и виджет.",
  "Selection saved for this key.": "Выбор сохранён для этой кнопки.",
  "Zabbix · Item value": "Zabbix · Значение элемента данных",
  "Or enter Dashboard ID": "Или указать ID Dashboard",
  "Example: 1": "Например: 1",
  "Open": "Открыть",
  "Dashboard page": "Страница Dashboard",
  "Item value widget": "Виджет «Значение элемента данных»",
  "Custom label (optional)": "Своя подпись (необязательно)",
  "Default from Zabbix": "По умолчанию из Zabbix",
  "Save selection": "Сохранить выбор",
  "Widgets and colors come from Zabbix. Credentials stay encrypted on Windows.": "Виджеты и цвета загружаются из Zabbix. Учётные данные остаются в защищённом хранилище Windows."
};
function t(value) {
  const key = String(value);
  return IS_RU ? (RU_STRINGS[key] || key) : key;
}
document.documentElement.lang = IS_RU ? "ru" : "en";
document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.textContent); });
document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.placeholder); });

let socket = null;
let context = "";
let action = "";
let savedSettings = {};
let didInitialize = false;
let epoch = 0;
let renderEpoch = 0;
let lastPreviewLabel = "";

function message(text, error) {
  $("message").textContent = text || "";
  $("message").className = error ? "error" : "";
}
function validId(id) {
  return /^[1-9]\d{0,19}$/.test(String(id || "").trim());
}
function fill(select, items, placeholder, selected) {
  select.replaceChildren();
  select.appendChild(new Option(placeholder, ""));
  items.forEach(({value, label, disabled}) => {
    const option = new Option(label, value);
    option.disabled = Boolean(disabled);
    select.appendChild(option);
  });
  select.disabled = !items.length;
  select.value = items.some(item => item.value === String(selected)) ? String(selected) : "";
}
async function request(path, timeoutMs) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs || 8500);
  try {
    const response = await fetch(API + path, {cache: "no-store", signal: abort.signal});
    const data = await response.json();
    if (!response.ok || data.error) {
      throw new Error(data.error || "HTTP " + response.status);
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}
function selected() {
  return {
    dashboardId: String($("dashboardId").value || "").trim(),
    pageId: String($("pages").value || "").trim(),
    widgetId: String($("widgets").value || "").trim()
  };
}
function updateSave() {
  const v = selected();
  const current = $("widgets").selectedOptions[0];
  $("apply").disabled = !(validId(v.dashboardId) && validId(v.pageId) && validId(v.widgetId) && current && !current.disabled);
}
function showUnavailable() {
  $("preview").hidden = true;
  $("previewValue").textContent = "";
  $("previewLabel").textContent = "";
}
async function preview() {
  const serial = ++renderEpoch;
  updateSave();
  const v = selected();
  if ($("apply").disabled) {
    showUnavailable();
    return;
  }
  const key = [v.dashboardId, v.pageId, v.widgetId].join(":");
  try {
    const response = await request("/api/render?keys=" + encodeURIComponent(key), 8500);
    if (serial !== renderEpoch) return;
    const tile = response.tiles && response.tiles[key];
    if (!tile) {
      showUnavailable();
      return;
    }
    $("preview").hidden = false;
    const background = String(tile.color || "#545E68");
    $("preview").style.background = /^#[a-fA-F0-9]{6}$/.test(background) ? background : "#545E68";
    $("previewValue").textContent = tile.display || "";
    lastPreviewLabel = tile.label || "Zabbix";
    $("previewLabel").textContent = $("customLabel").value.trim() || lastPreviewLabel;
  } catch (error) {
    if (serial === renderEpoch) {
      showUnavailable();
      message(t("Preview: ") + error.message, true);
    }
  }
}
async function loadWidgets(dashboardId, pageId, wantedWidget) {
  const current = ++epoch;
  showUnavailable();
  updateSave();
  fill($("widgets"), [], t("Loading widgets..."), "");
  $("widgetCount").textContent = "";
  if (!validId(dashboardId) || !validId(pageId)) return;
  message(t("Loading Zabbix widgets..."));
  try {
    const data = await request(
      "/api/catalog/widgets?dashboard_id=" + encodeURIComponent(dashboardId) +
      "&page_id=" + encodeURIComponent(pageId), 10000);
    if (current !== epoch) return;
    const entries = data.widgets || [];
    const options = entries.map(w => ({
      value: String(w.widgetId),
      disabled: !w.resolved,
      label: String(w.name || w.itemName || t("Untitled")).replace(/\s*\n\s*/g," / ") +
             (w.host ? " | " + w.host : "") +
             (w.itemName ? " · " + w.itemName : "") +
             " [#" + w.widgetId + "]" + (!w.resolved ? " · " + t("no item binding") : "")
    }));
    fill($("widgets"), options, t("Select widget"), wantedWidget || "");
    $("widgetCount").textContent = t("Available widgets: ") + entries.length;
    if (!entries.length) {
      message(t("There are no Item value widgets on this page."), false);
    } else {
      message(t("Select a widget, then save the selection."), false);
    }
    updateSave();
    if ($("widgets").value) await preview();
  } catch (error) {
    if (current !== epoch) return;
    fill($("widgets"), [], t("Cannot load widgets"), "");
    message(t("Widget request failed: ") + error.message, true);
  }
}
async function loadPages(dashboardId, wantedPage, wantedWidget) {
  const current = ++epoch;
  fill($("pages"), [], t("Loading pages..."), "");
  fill($("widgets"), [], t("Select page"), "");
  $("widgetCount").textContent = "";
  showUnavailable();
  updateSave();
  if (!validId(dashboardId)) {
    message(t("Enter a numeric Dashboard ID."), true);
    return;
  }
  $("dashboardId").value = dashboardId;
  message(t("Loading dashboard pages..."));
  try {
    const data = await request("/api/catalog/pages?dashboard_id=" + encodeURIComponent(dashboardId), 10000);
    if (current !== epoch) return;
    const list = (data.pages || []).map(p => ({
      value: String(p.pageId),
      label: (p.name || t("Untitled")) + " (" + p.widgetsCount + ")"
    }));
    fill($("pages"), list, t("Select page"), wantedPage || "");
    if (!list.length) {
      message(t("No accessible dashboard pages."), false);
      return;
    }
    if (!$("pages").value && !wantedPage) {
      const preferred = (data.pages || []).find(p => p.widgetsCount > 0) || data.pages[0];
      $("pages").value = String(preferred.pageId);
    }
    const actualPage = $("pages").value;
    $("dashboards").value = [...$("dashboards").options].some(o => o.value === dashboardId) ? dashboardId : "";
    if (actualPage) await loadWidgets(dashboardId, actualPage, wantedWidget);
    else message(t("Saved page no longer exists. Choose another."), true);
  } catch (error) {
    if (current !== epoch) return;
    fill($("pages"), [], t("Cannot load pages"), "");
    message(t("Dashboard error: ") + error.message, true);
  }
}
async function initialize(settings) {
  savedSettings = Object.assign({}, settings || {});
  $("customLabel").value = savedSettings.customLabel || "";
  message(t("Connecting to the local Zabbix bridge..."));
  try {
    const data = await request("/api/catalog/dashboards", 10000);
    const choices = (data.dashboards || []).map(d => ({
      value: String(d.dashboardId),
      label: (d.name || t("Untitled")) + " (#" + d.dashboardId + ")"
    }));
    fill($("dashboards"), choices, t("Select Dashboard"), savedSettings.dashboardId || "");
    const dashboardId = String(savedSettings.dashboardId || "");
    if (dashboardId) {
      $("dashboardId").value = dashboardId;
      await loadPages(dashboardId, String(savedSettings.pageId || ""), String(savedSettings.widgetId || ""));
    } else {
      message(t("Choose a Dashboard or enter its ID manually."));
    }
  } catch (error) {
    fill($("dashboards"), [], t("Dashboard list unavailable"), "");
    const dashboardId = String(savedSettings.dashboardId || "");
    if (dashboardId) {
      await loadPages(dashboardId, String(savedSettings.pageId || ""), String(savedSettings.widgetId || ""));
    } else {
      message(t("Dashboard request failed: ") + error.message, true);
    }
  }
}
function connectElgatoStreamDeckSocket(port, uuid, event, app, info) {
  const data = JSON.parse(info);
  context = data.context;
  action = data.action;
  socket = new WebSocket("ws://127.0.0.1:" + port);
  socket.onopen = () => {
    socket.send(JSON.stringify({event, uuid}));
  };
  socket.onmessage = (e) => {
    let received;
    try {received = JSON.parse(e.data);} catch {return;}
    if (received.event === "didReceiveSettings") {
      savedSettings = Object.assign({}, received.payload?.settings || {});
      if (!didInitialize) {
        didInitialize = true;
        initialize(savedSettings);
      }
    }
  };
  socket.onerror = () => message(t("Not connected to HotSpot."), true);
}

$("dashboards").addEventListener("change", () => {
  const id = $("dashboards").value;
  if (id) loadPages(id, "", "");
});
$("openDashboard").addEventListener("click", () => {
  loadPages($("dashboardId").value.trim(), "", "");
});
$("dashboardId").addEventListener("input", () => {
  epoch++;
  fill($("pages"), [], t("Press Open to load an ID"), "");
  fill($("widgets"), [], t("Select page"), "");
  showUnavailable();
  updateSave();
});
$("dashboardId").addEventListener("keydown", e => {
  if (e.key === "Enter") {
    e.preventDefault();
    loadPages($("dashboardId").value.trim(), "", "");
  }
});
$("pages").addEventListener("change", () => {
  loadWidgets($("dashboardId").value.trim(), $("pages").value, "");
});
$("widgets").addEventListener("change", preview);
$("customLabel").addEventListener("input", () => {
  $("previewLabel").textContent = $("customLabel").value.trim() || lastPreviewLabel;
  updateSave();
});
$("apply").addEventListener("click", () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    message(t("Not connected to HotSpot."), true);
    return;
  }
  const ids = selected();
  if (![ids.dashboardId, ids.pageId, ids.widgetId].every(validId)) {
    message(t("Choose a Dashboard, page and widget first."), true);
    return;
  }
  const updated = Object.assign({}, savedSettings, ids, {
    customLabel: $("customLabel").value.trim()
  });
  socket.send(JSON.stringify({event:"setSettings", context, payload: updated}));
  socket.send(JSON.stringify({event:"sendToPlugin", action, context, payload: updated}));
  savedSettings = updated;
  message(t("Selection saved for this key."));
});
