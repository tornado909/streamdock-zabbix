"use strict";

const BRIDGE = "http://127.0.0.1:18398";
const BACKGROUNDS = {ok:"#4CAF50",problem:"#FF0000",warning:"#FFD54F",unknown:"#545E68"};
const contexts = new Map();
let socket = null;
let lastLegacy = {connected:false, tiles:{}};
let lastDynamic = {connected:false, tiles:{}};
let timer = null;
let busy = false;

function send(event, context, payload) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({event, context, payload}));
  }
}
function selector(settings) {
  const id = String(settings.dashboardId || "").trim();
  const page = String(settings.pageId || "").trim();
  const widget = String(settings.widgetId || "").trim();
  if ([id,page,widget].every(v => /^[1-9]\d{0,19}$/.test(v))) {
    return id + ":" + page + ":" + widget;
  }
  return "";
}
function dataFor(settings) {
  const key = selector(settings);
  const live = key ? lastDynamic.tiles[key] : lastLegacy.tiles[settings.tileId || ""];
  if (live) {
    return Object.assign({}, live, {
      label: String(settings.customLabel || "").trim() || live.label || settings.label || "Zabbix",
    });
  }
  return {
    kind: settings.kind || "metric", state:"unknown", color: BACKGROUNDS.unknown,
    display:"?", detail:key ? "НЕТ СВЯЗИ" : "ВЫБЕРИТЕ ВИДЖЕТ",
    label:String(settings.customLabel || "").trim() || settings.label || "Zabbix",
  };
}
function drawCentered(g, text, y, maxWidth, preferredSize, weight) {
  let size = preferredSize;
  const clean = String(text || "");
  do {
    g.font = weight + " " + size + "px Segoe UI, Arial, sans-serif";
    if (g.measureText(clean).width <= maxWidth) break;
    size -= 1;
  } while (size >= 11);
  g.fillText(clean, 72, y);
}
function render(context, settings, force) {
  const data = dataFor(settings);
  const signature = JSON.stringify([
    selector(settings), settings.tileId, data.kind, data.label, data.display,
    data.color, data.state, data.detail, data.url
  ]);
  if (!force && settings._drawSignature === signature) return;
  settings._drawSignature = signature;

  const cv = document.createElement("canvas");
  cv.width = 144;
  cv.height = 144;
  const g = cv.getContext("2d");
  const hex = String(data.color || "");
  g.fillStyle = /^#[a-fA-F0-9]{6}$/.test(hex) ? hex : BACKGROUNDS.unknown;
  g.fillRect(0,0,144,144);
  g.fillStyle = "#FFFFFF";
  g.textAlign = "center";
  g.textBaseline = "middle";

  const lines = String(data.label || "Zabbix").replace(/\r/g,"\n").split(/\n/).map(x=>x.trim()).filter(Boolean).slice(0,4);
  if (data.kind === "metric") {
    const value = String(data.display === undefined ? "?" : data.display);
    drawCentered(g,value,65,135,74,"bold");
    if (data.detail === "°C" || data.detail === "%" || data.detail === "°") {
      g.font = "bold 16px Segoe UI, Arial, sans-serif";
      g.textAlign = "right";
      g.fillText(data.detail,137,24);
      g.textAlign = "center";
    }
    const font = lines.length > 2 ? 15 : 18;
    const dy = lines.length > 2 ? 16 : 18;
    const top = lines.length > 2 ? 98 : lines.length === 2 ? 111 : 123;
    lines.forEach((line,i) => drawCentered(g,line,top+dy*i,135,font,"bold"));
  } else {
    const count = lines.length || 1;
    const top = 72 - (count - 1) * 13;
    lines.forEach((line,i) => drawCentered(g,line,top+26*i,136,25,"normal"));
  }
  if (data.state === "unknown") {
    g.fillStyle = "#F4F4F4";
    g.fillRect(0,135,144,9);
    g.fillStyle = "#353D45";
    g.font = "bold 8px Arial";
    g.fillText("NO DATA",72,139);
  }

  send("setImage",context,{target:0,image:cv.toDataURL("image/png")});
  send("setTitle",context,{target:0,title:""});
}
async function fetchJson(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 7500);
  try {
    const response = await fetch(BRIDGE + path,{cache:"no-store",signal:controller.signal});
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "HTTP " + response.status);
    return result;
  } finally {
    clearTimeout(timer);
  }
}
async function poll() {
  if (busy || !socket || socket.readyState !== WebSocket.OPEN) return;
  busy = true;
  const keys = [...new Set([...contexts.values()].map(selector).filter(Boolean))];
  const legacy = [...contexts.values()].some(settings => !selector(settings) && settings.tileId);

  const jobs = [];
  if (keys.length) {
    jobs.push(fetchJson("/api/render?keys=" + encodeURIComponent(keys.join(",")))
      .then(data => { lastDynamic = data; })
      .catch(err => { lastDynamic = {connected:false,error:String(err.message),tiles:{}}; }));
  }
  if (legacy) {
    jobs.push(fetchJson("/state")
      .then(data => { lastLegacy = data; })
      .catch(err => { lastLegacy = {connected:false,error:String(err.message),tiles:{}}; }));
  }
  try {
    await Promise.all(jobs);
  } finally {
    busy = false;
    contexts.forEach((settings,context) => render(context,settings,false));
  }
}
function connectElgatoStreamDeckSocket(port, uuid, event) {
  socket = new WebSocket("ws://127.0.0.1:" + port);
  socket.onopen = () => {
    socket.send(JSON.stringify({event, uuid}));
    poll();
    if (timer !== null) clearInterval(timer);
    timer = setInterval(poll,5000);
  };
  socket.onmessage = (message) => {
    let msg;
    try {msg = JSON.parse(message.data);} catch {return;}
    if (!String(msg.action || "").startsWith("com.streamdock.zabbix.")) return;
    const context = msg.context;
    if (msg.event === "willAppear") {
      const settings = Object.assign({},msg.payload?.settings || {});
      contexts.set(context,settings);
      render(context,settings,true);
      poll();
    } else if (msg.event === "willDisappear") {
      contexts.delete(context);
    } else if (msg.event === "didReceiveSettings" || msg.event === "sendToPlugin") {
      const settings = contexts.get(context);
      if (settings) {
        Object.assign(settings, msg.event === "didReceiveSettings" ? (msg.payload?.settings || {}) : (msg.payload || {}));
        settings._drawSignature = null;
        render(context,settings,true);
        poll();
      }
    } else if (msg.event === "keyUp") {
      const settings = contexts.get(context);
      if (!settings) return;
      const data = dataFor(settings);
      if (/^https:\/\/[^/]+\/.+/i.test(String(data.url || ""))) {
        send("openUrl",context,{url:data.url});
      }
    }
  };
  socket.onclose = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };
}
