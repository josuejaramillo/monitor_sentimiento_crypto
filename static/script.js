// static/script.js
let logsDiv, sentimentBox;
let updateTimer = null;

window.onload = () => {
  logsDiv = document.getElementById("logs");
  sentimentBox = document.getElementById("sentimentBox");

  updateLogs();
  updateSentiment();

  setInterval(updateLogs, 2000);
  setInterval(updateSentiment, 2000);

  document.getElementById("startBtn").onclick = () => fetch("/start", { method: "POST" });
  document.getElementById("stopBtn").onclick = () => fetch("/stop", { method: "POST" });
  document.getElementById("clearBtn").onclick = clearLogs;

  // Activar auto-actualización de configuración
  const fields = ["symbols", "interval", "sentiment_window", "window", "refresh", "scan_all"];
  fields.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const eventType = el.type === "checkbox" ? "change" : "input";
    el.addEventListener(eventType, () => scheduleConfigUpdate());
  });
};

// --- Auto actualización config ---
function scheduleConfigUpdate() {
  if (updateTimer) clearTimeout(updateTimer);
  updateTimer = setTimeout(updateConfig, 500);
}

function updateConfig() {
  const payload = {
    symbols: document.getElementById("symbols").value,
    interval: document.getElementById("interval").value,
    sentiment_window: document.getElementById("sentiment_window").value,
    window: document.getElementById("window").value,
    refresh: document.getElementById("refresh").value,
    scan_all: document.getElementById("scan_all").checked,
  };
  fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// --- Logs con colores ---
function updateLogs() {
  fetch("/logs")
    .then(res => res.json())
    .then(data => {
      logsDiv.innerHTML = data.map(colorizeLog).join("<br>");
      logsDiv.scrollTop = logsDiv.scrollHeight;
    });
}

function colorizeLog(line) {
  // Reemplazos clave → span con color
  return line
    .replace(/dir=BUY/g, '<span style="color:lime; font-weight:bold;">dir=BUY</span>')
    .replace(/dir=SELL/g, '<span style="color:#ff5555; font-weight:bold;">dir=SELL</span>')
    .replace(/🟢/g, '<span style="color:lime;">🟢</span>')
    .replace(/🔴/g, '<span style="color:#ff5555;">🔴</span>')
    .replace(/🟡/g, '<span style="color:yellow;">🟡</span>')
    .replace(/⚠️/g, '<span style="color:orange;">⚠️</span>')
    .replace(/⚙️/g, '<span style="color:deepskyblue;">⚙️</span>')
    .replace(/▶️/g, '<span style="color:lime;">▶️</span>')
    .replace(/⏹/g, '<span style="color:#ff5555;">⏹</span>')
    .replace(/🧹/g, '<span style="color:#aaa;">🧹</span>');
}

// --- Sentimiento ---
function updateSentiment() {
  fetch("/status")
    .then(res => res.json())
    .then(s => {
      sentimentBox.textContent = s.text;
      sentimentBox.style.color = s.color || "white";
    });
}

function clearLogs() {
  fetch("/clear_logs", { method: "POST" })
    .then(() => (logsDiv.innerHTML = ""));
}
