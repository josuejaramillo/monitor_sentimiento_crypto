# app.py
from flask import Flask, render_template, request, jsonify
from threading import Thread, Event, Lock
from futures_delta_alert import run_live, get_futures_symbols
import time, requests, os

app = Flask(__name__)

# --- Estado global ---
monitor_thread = None
stop_event = Event()
logs = []
sentiment_state = {"text": "Sin datos", "color": "gray", "symbol": "---"}
lock = Lock()

# --- Configuración inicial ---
config = {
    "symbols": "BTCUSDT",
    "interval": "5m",
    "sentiment_window": 15,
    "window": 60,
    "refresh": 10,
    "scan_all": False,
}

# --- Logging y sentimiento ---
def log_fn(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with lock:
        logs.append(line)
        if len(logs) > 300:
            logs.pop(0)
        if "Sentimiento" in msg:
            if "COMPRADOR" in msg:
                sentiment_state.update({"text": msg, "color": "lime"})
            elif "VENDEDOR" in msg:
                sentiment_state.update({"text": msg, "color": "red"})
            elif "NEUTRAL" in msg:
                sentiment_state.update({"text": msg, "color": "yellow"})

# --- Configuración dinámica ---
def config_getter():
    cfg = config.copy()
    if cfg.get("scan_all"):
        try:
            syms = get_futures_symbols()
            cfg["symbols"] = ",".join(syms[:200])  # límite de seguridad
        except Exception as e:
            log_fn(f"Error al obtener lista de símbolos: {e}")
    return cfg

# --- Hilo principal ---
def run_thread(local_event):
    run_live(config_getter, log_fn, local_event)

# --- Keep-alive para evitar suspensión ---
def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if not url:
        return
    while True:
        try:
            requests.get(url, timeout=5)
        except Exception:
            pass
        time.sleep(600)  # cada 10 minutos

# --- Rutas Flask ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/logs")
def get_logs():
    with lock:
        return jsonify(logs[-100:])

@app.route("/status")
def get_status():
    with lock:
        return jsonify(sentiment_state)

@app.route("/start", methods=["POST"])
def start_monitor():
    global monitor_thread, stop_event
    if monitor_thread and monitor_thread.is_alive():
        log_fn("⚠️ Monitor ya está activo.")
        return jsonify({"status": "already running"})

    stop_event = Event()
    monitor_thread = Thread(target=run_thread, args=(stop_event,), daemon=True)
    monitor_thread.start()
    log_fn("▶️ Monitor iniciado correctamente.")
    return jsonify({"status": "started"})

@app.route("/stop", methods=["POST"])
def stop_monitor():
    global monitor_thread, stop_event
    if monitor_thread and monitor_thread.is_alive():
        log_fn("⏹ Solicitando detención del monitor...")
        stop_event.set()
        monitor_thread.join(timeout=5)
        monitor_thread = None
        log_fn("✅ Monitor detenido correctamente.")
    else:
        log_fn("⚠️ No había monitor activo.")
    return jsonify({"status": "stopped"})

@app.route("/config", methods=["POST"])
def update_config():
    data = request.json
    changes = []
    for key, val in data.items():
        if key in config:
            old = config[key]
            # convierte a número o booleano si corresponde
            if isinstance(old, bool):
                val = bool(val)
            else:
                try:
                    val = int(val) if str(val).isdigit() else float(val)
                except:
                    pass
            config[key] = val
            if old != val:
                changes.append(f"{key}: {old} → {val}")
    if changes:
        log_fn("⚙️ Configuración actualizada: " + ", ".join(changes))
    return jsonify({"status": "updated", "config": config})

@app.route("/clear_logs", methods=["POST"])
def clear_logs():
    with lock:
        logs.clear()
    log_fn("🧹 Logs limpiados manualmente desde la interfaz.")
    return jsonify({"status": "cleared"})

# --- Inicialización ---
if __name__ == "__main__":
    # Arrancar keep-alive solo si está en Render o Railway
    if os.environ.get("RENDER") == "true" or os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        Thread(target=keep_alive, daemon=True).start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
