# app.py
from flask import Flask, render_template, request, jsonify
from threading import Thread, Event, Lock
from futures_delta_alert import run_live, get_futures_symbols
import time

app = Flask(__name__)

monitor_thread = None
stop_event = Event()
logs = []
sentiment_state = {"text": "Sin datos", "color": "gray", "symbol": "---"}
lock = Lock()

config = {
    "symbols": "BTCUSDT",
    "interval": "5m",
    "sentiment_window": 15,
    "window": 60,
    "refresh": 10,
    "scan_all": False,  # 👈 Nuevo campo
}

# --- Logging central con detección de sentimiento ---
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

def config_getter():
    """Función usada por run_live para obtener configuración en tiempo real."""
    cfg = config.copy()
    if cfg.get("scan_all"):
        try:
            syms = get_futures_symbols()
            cfg["symbols"] = ",".join(syms[:200])  # Limite de seguridad
        except Exception as e:
            log_fn(f"Error al obtener lista de símbolos: {e}")
    return cfg

def run_thread(local_event):
    run_live(config_getter, log_fn, local_event)

# --- Rutas ---
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
    global stop_event
    if stop_event:
        stop_event.set()
        log_fn("⏹ Monitor detenido por usuario.")
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
            # conversión tipo numérico o booleano
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
