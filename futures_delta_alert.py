#!/usr/bin/env python3
# futures_delta_alert.py (modificado con soporte Footprint)
import os
import time
import math
import pandas as pd
from datetime import datetime, timedelta
from binance.client import Client
from dotenv import load_dotenv
import threading

# Sonido
try:
    import winsound  # windows
except Exception:
    winsound = None
try:
    from playsound import playsound
except Exception:
    playsound = None

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
if not API_KEY:
    print("ERROR: coloca tus BINANCE_API_KEY y BINANCE_API_SECRET en .env")

client = None
def ensure_client():
    global client
    if client is None:
        if not API_KEY:
            raise RuntimeError("Faltan API_KEY/API_SECRET en variables de entorno.")
        client = Client(API_KEY, API_SECRET)
    return client

# --------------------------
# Parámetros por defecto
# --------------------------
WINDOW = 60
LIMIT = 300
LATERAL_THRESH = 0.004
DELTA_RATIO = 0.6
MIN_POSITIVE_FRAC = 0.25
MIN_CUM_DELTA = 0
BREAKOUT_MOVE = 0.008
BREAKOUT_VOLUME_MULT = 1.5
COOLDOWN = 300
REFRESH = 15
SYMBOL_DEFAULT = "BTCUSDT"
INTERVAL_DEFAULT = "5m"
# --------------------------

def play_alert_sound():
    try:
        if winsound:
            winsound.Beep(1000, 500)
        elif playsound:
            pass
        else:
            print("\a", end="")
    except Exception:
        print("🔔 ALERT (no sound playable)")

def friendly_print(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def get_futures_symbols():
    exchange_info = client.futures_exchange_info()
    symbols = [
        s["symbol"]
        for s in exchange_info["symbols"]
        if s["contractType"] == "PERPETUAL" and s["symbol"].endswith("USDT")
    ]
    return symbols

def fetch_klines(symbol, interval, limit=LIMIT):
    try:
        cl = ensure_client()
        raw = cl.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        friendly_print(f"Error API klines {symbol}:{interval}: {e}")
        return None
    data = []
    for k in raw:
        open_t = pd.to_datetime(k[0], unit="ms")
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        vol = float(k[5])
        taker_buy = float(k[9]) if len(k) > 9 else vol/2
        taker_sell = vol - taker_buy
        delta = taker_buy - taker_sell
        data.append({
            "time": open_t, "open": o, "high": h, "low": l, "close": c,
            "volume": vol, "taker_buy": taker_buy, "taker_sell": taker_sell, "delta": delta
        })
    df = pd.DataFrame(data)
    if df.empty:
        return None
    df["cvd"] = df["delta"].cumsum()
    return df

def detect_accumulation(df, window=WINDOW, lateral_thresh=LATERAL_THRESH,
                        delta_ratio=DELTA_RATIO, min_frac=MIN_POSITIVE_FRAC,
                        min_cumdelta=MIN_CUM_DELTA):
    if df is None or len(df) < window:
        return (False, False, None, None, None, "Insuficientes datos")

    window_df = df.iloc[-window:]
    price_max = window_df["high"].max()
    price_min = window_df["low"].min()
    price_mean = window_df["close"].mean()
    rel_range = (price_max - price_min) / price_mean
    is_lateral = rel_range < lateral_thresh

    agresivas = window_df[ (window_df["delta"].abs() > window_df["volume"] * delta_ratio) ]
    frac_agresivas = len(agresivas) / window
    cumdelta = window_df["delta"].sum()

    if frac_agresivas >= min_frac and abs(cumdelta) > abs(min_cumdelta):
        direction = "BUY" if cumdelta > 0 else "SELL"
        is_accum = True
    else:
        direction = None
        is_accum = False

    summary = {
        "rel_range": rel_range,
        "frac_agresivas": frac_agresivas,
        "cumdelta": cumdelta,
        "avg_volume": window_df["volume"].mean(),
        "price_max": price_max,
        "price_min": price_min
    }
    return (is_lateral, is_accum, direction, price_max, price_min, summary)

def detect_breakout(df, direction, price_max, price_min, summary,
                    breakout_move=BREAKOUT_MOVE, breakout_vol_mult=BREAKOUT_VOLUME_MULT):
    last = df.iloc[-1]
    avg_vol = summary["avg_volume"]
    if direction == "BUY":
        move_rel = (last["close"] - price_max) / price_max
        cond_price = move_rel > breakout_move
    elif direction == "SELL":
        move_rel = (price_min - last["close"]) / price_min
        cond_price = move_rel > breakout_move
    else:
        return (False, None, "No hay dirección definida")

    cond_vol = last["volume"] > avg_vol * breakout_vol_mult
    cond_delta = (last["delta"] > 0) if direction == "BUY" else (last["delta"] < 0)

    if cond_price and cond_vol and cond_delta:
        side = "BUY" if direction == "BUY" else "SELL"
        reason = f"move_rel={move_rel:.4f} vol={last['volume']:.1f} avg={avg_vol:.1f} delta={last['delta']:.1f}"
        return (True, side, reason)
    else:
        return (False, None, f"no cumple breakout price:{cond_price}, vol:{cond_vol}, delta:{cond_delta}")

# --------------------------
# run_scan con soporte footprint_callback
# --------------------------
def run_scan(config_getter, log_fn=None, stop_event=None, footprint_callback=None):
    if log_fn is None:
        log_fn = friendly_print
    if stop_event is None:
        stop_event = threading.Event()

    last_signal_times = {}
    try:
        ensure_client()
    except Exception as e:
        log_fn(f"Error al inicializar cliente: {e}")
        return

    log_fn("Iniciando modo SCAN (barrido de pares).")

    while not stop_event.is_set():
        cfg = config_getter()
        interval = cfg.get("interval", INTERVAL_DEFAULT)
        refresh = int(cfg.get("refresh", REFRESH))
        window = int(cfg.get("window", WINDOW))
        lateral = float(cfg.get("lateral", LATERAL_THRESH))
        delta_ratio = float(cfg.get("delta_ratio", DELTA_RATIO))
        min_frac = float(cfg.get("min_frac", MIN_POSITIVE_FRAC))
        min_cum = float(cfg.get("min_cum", MIN_CUM_DELTA))
        breakout_move = float(cfg.get("breakout_move", BREAKOUT_MOVE))
        breakout_vol_mult = float(cfg.get("breakout_vol_mult", BREAKOUT_VOLUME_MULT))
        cooldown = int(cfg.get("cooldown", COOLDOWN))

        symbols_req = cfg.get("symbols", "ALL")
        if isinstance(symbols_req, str):
            if symbols_req.strip().upper() == "ALL":
                symbols = get_futures_symbols()
            else:
                symbols = [s.strip().upper() for s in symbols_req.split(",") if s.strip()]
        elif isinstance(symbols_req, (list, tuple)):
            symbols = [s.upper() for s in symbols_req]
        else:
            symbols = [SYMBOL_DEFAULT]

        for sym in symbols:
            if stop_event.is_set():
                break
            try:
                df = fetch_klines(sym, interval, limit=max(LIMIT, window+20))
                if df is None:
                    continue

                # Callback gráfico footprint
                if callable(footprint_callback):
                    footprint_callback((df.tail(50), sym))

                is_lateral, is_accum, direction, pmax, pmin, summary = detect_accumulation(
                    df, window=window, lateral_thresh=lateral,
                    delta_ratio=delta_ratio, min_frac=min_frac, min_cumdelta=min_cum
                )

                if is_lateral and is_accum:
                    now = datetime.now()
                    last_t = last_signal_times.get(sym)
                    if last_t is None or (now - last_t).total_seconds() > cooldown:

                        # --- Cálculo de sentimiento ---
                        n_sent = min(10, len(df))
                        recent_sent = df.tail(n_sent)
                        buy_money = (recent_sent["close"] * recent_sent["taker_buy"]).sum()
                        sell_money = (recent_sent["close"] * recent_sent["taker_sell"]).sum()
                        total_money = buy_money + sell_money
                        sentiment_str = ""
                        if total_money > 0:
                            score = (buy_money - sell_money) / total_money
                            prob_buy = (score + 1) / 2 * 100
                            prob_sell = 100 - prob_buy
                            if prob_buy > 60:
                                sentiment_str = f"| 🟢 Sentimiento COMPRADOR {prob_buy:.1f}%"
                            elif prob_buy < 40:
                                sentiment_str = f"| 🔴 Sentimiento VENDEDOR {prob_sell:.1f}%"
                            else:
                                sentiment_str = f"| 🟡 Sentimiento NEUTRAL ({prob_buy:.1f}% Buy / {prob_sell:.1f}% Sell)"

                        # --- Divergencia Delta–Precio ---
                        n_div = min(20, len(df))
                        recent_div = df.tail(n_div)
                        price_change = recent_div["close"].iloc[-1] - recent_div["close"].iloc[0]
                        cvd_change = recent_div["cvd"].iloc[-1] - recent_div["cvd"].iloc[0]
                        div_str = ""
                        if price_change > 0 and cvd_change < 0:
                            div_str = "| ⚠️ Divergencia BAJISTA (Precio↑ / Delta↓)"
                        elif price_change < 0 and cvd_change > 0:
                            div_str = "| ⚠️ Divergencia ALCISTA (Precio↓ / Delta↑)"

                        # --- Imbalance % ---
                        delta_pos = df[df["delta"] > 0]["delta"].sum()
                        delta_neg = abs(df[df["delta"] < 0]["delta"].sum())
                        total_vol = df["volume"].sum()
                        imbalance = 0
                        imb_str = ""
                        if total_vol > 0:
                            imbalance = (delta_pos - delta_neg) / total_vol * 100
                            if imbalance > 10:
                                imb_str = f"| 🟢 Imbalance +{imbalance:.1f}% (compras dominantes)"
                            elif imbalance < -10:
                                imb_str = f"| 🔴 Imbalance {imbalance:.1f}% (ventas dominantes)"
                            else:
                                imb_str = f"| 🟡 Imbalance {imbalance:.1f}% (equilibrado)"

                        # --- Estrategia compuesta (score) ---
                        score = 50  # punto neutro

                        # 1. Sentimiento
                        if prob_buy > 60:
                            score += (prob_buy - 50) * 0.8  # ponderación
                        elif prob_buy < 40:
                            score -= (50 - prob_buy) * 0.8

                        # 2. Imbalance
                        if imbalance > 10:
                            score += abs(imbalance) * 0.4
                        elif imbalance < -10:
                            score -= abs(imbalance) * 0.4

                        # 3. Divergencia
                        if "Divergencia ALCISTA" in div_str:
                            score += 10
                        elif "Divergencia BAJISTA" in div_str:
                            score -= 10

                        # 4. Dirección detectada
                        if direction == "BUY":
                            score += 5
                        elif direction == "SELL":
                            score -= 5

                        # Limitar score entre 0 y 100
                        score = max(0, min(100, score))

                        # Determinar texto final
                        if score >= 70:
                            strategy_str = f"| 🟢 Estrategia: Condiciones óptimas para COMPRA (score={score:.0f}%)"
                        elif score <= 30:
                            strategy_str = f"| 🔴 Estrategia: Condiciones óptimas para VENTA (score={score:.0f}%)"
                        else:
                            strategy_str = f"| 🟡 Estrategia: Mercado neutral (score={score:.0f}%)"

                        # --- Mensaje final ---
                        msg = (
                        f"🔎 ACUMULACIÓN: {sym} dir={direction} "
                        f"range={summary['rel_range']:.4f} cumdelta={summary['cumdelta']:.1f} "
                        f"{sentiment_str} {imb_str} {div_str} {strategy_str}"
                        )
                        log_fn(msg)
                        play_alert_sound()
                        last_signal_times[sym] = now



                    is_break, side, reason = detect_breakout(
                        df, direction, pmax, pmin, summary,
                        breakout_move=breakout_move, breakout_vol_mult=breakout_vol_mult
                    )
                    if is_break:
                        log_fn(f"🚀 BREAKOUT {sym} -> {side} | {reason}")
                        play_alert_sound()
                        last_signal_times[sym] = datetime.now()
                time.sleep(0.3)
            except Exception as e:
                log_fn(f"Error scanning {sym}: {e}")
                time.sleep(0.5)

        for _ in range(int(refresh)):
            if stop_event.is_set(): break
            time.sleep(1)

    log_fn("Scan detenido por stop_event.")

def run_live(a=None, b=None, c=None, d=None):
    # a puede ser config_getter
    if callable(a):
        config_getter = a
        log_fn = b if callable(b) or b is not None else friendly_print
        stop_event = c if isinstance(c, threading.Event) else None
        footprint_callback = d if callable(d) else None
        return run_scan(config_getter, log_fn=log_fn, stop_event=stop_event, footprint_callback=footprint_callback)

    # Modo legacy
    symbol = a if a else SYMBOL_DEFAULT
    interval = b if b else INTERVAL_DEFAULT
    refresh = int(c) if c else REFRESH
    friendly_print(f"Iniciando monitor en {symbol} interval={interval} refresh={refresh}s")
    last_signal_time = None
    accumulation_state = None

    try:
        ensure_client()
    except Exception as e:
        friendly_print("Error inicializando cliente: " + str(e))
        return

    while True:
        try:
            df = fetch_klines(symbol, interval, limit=LIMIT)
            if df is None:
                time.sleep(refresh)
                continue
            if callable(d):
                d(df.tail(50))
            is_lateral, is_accum, direction, pmax, pmin, summary = detect_accumulation(df)
            if is_lateral and is_accum:
                friendly_print(f"🔎 ACUMULACIÓN: {symbol} dir={direction}")
        except KeyboardInterrupt:
            friendly_print("Programa detenido por usuario.")
            break
        except Exception as e:
            friendly_print("Error en loop principal: " + str(e))
        time.sleep(refresh)
