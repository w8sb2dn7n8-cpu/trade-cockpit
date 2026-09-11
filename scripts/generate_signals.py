"""
Trend-Cockpit - taegliche Signalberechnung
============================================
Laeuft einmal pro Boersentag (siehe .github/workflows/daily-signals.yml) und schreibt
docs/data/signals.json. Diese Datei liest die Web-App (docs/index.html) ein.

Ablauf:
1. S&P-500-Ticker + GICS-Sektor von Wikipedia laden
2. Tageskurse fuer alle Ticker + SPY (Benchmark) + EURUSD=X laden (yfinance)
3. Indikatoren berechnen: SMA50, SMA200, RSI14, ATR14, 6-Monats-Momentum, relative Staerke vs. SPY
4. Cluster zuweisen: D (Trendbruch) > A (starker Trend) > B (Ruecksetzer im Trend) > C (Seitwaerts)
5. Top-Kandidaten (A/B, nach relativer Staerke sortiert) auswaehlen
6. Fuer die Top-Kandidaten: Earnings-Termin pruefen + Claude-Kurzeinordnung (Pro/Contra) erzeugen
7. Alles als JSON schreiben (universe = alle Ticker fuer Depot-Abgleich, top_candidates = Kaufkandidaten)

Hinweis: yfinance ist eine inoffizielle Schnittstelle zu Yahoo Finance und kann gelegentlich
ausfallen oder sich aendern. Bei Fehlern bricht das Skript NICHT komplett ab, sondern schreibt
so viel wie moeglich und markiert fehlende Werte. Die App zeigt das Datum der letzten
erfolgreichen Aktualisierung an, damit veraltete Daten auffallen.
"""

import io
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

LOOKBACK_DAYS = "400d"          # genug Handelstage fuer SMA200 + Puffer
MOMENTUM_WINDOW = 126           # ca. 6 Handelsmonate
TOP_N_CANDIDATES = 10           # die App filtert/kuerzt davon selbst weiter (Positionslimit, Sektor-Cap)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "signals.json")

WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Schritt 1: Universum laden
# ---------------------------------------------------------------------------

def load_universe():
    log("Lade S&P-500-Liste von Wikipedia ...")
    # Wikipedia blockt Abrufe ohne Browser-Kennung (HTTP 403) - daher mit User-Agent laden
    resp = requests.get(
        WIKI_SP500_URL,
        headers={"User-Agent": "trend-cockpit/1.0 (private, nicht-kommerzielle Nutzung)"},
        timeout=30,
    )
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0][["Symbol", "Security", "GICS Sector"]].copy()
    df.columns = ["symbol", "name", "sector"]
    # Yahoo Finance nutzt "-" statt "." bei Tickern wie BRK.B
    df["symbol"] = df["symbol"].str.replace(".", "-", regex=False)
    log(f"{len(df)} Ticker geladen.")
    return df


# ---------------------------------------------------------------------------
# Schritt 2: Kursdaten laden
# ---------------------------------------------------------------------------

def load_prices(tickers):
    log(f"Lade Kursdaten fuer {len(tickers)} Ticker + SPY + EURUSD=X ...")
    all_symbols = tickers + ["SPY", "EURUSD=X"]
    data = yf.download(
        all_symbols,
        period=LOOKBACK_DAYS,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    return data


# ---------------------------------------------------------------------------
# Schritt 3+4: Indikatoren + Cluster je Ticker
# ---------------------------------------------------------------------------

def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def analyze_ticker(symbol, df_ticker, spy_momentum):
    """Berechnet Kennzahlen + Cluster fuer einen Ticker. Gibt dict oder None bei zu wenig Daten zurueck."""
    if df_ticker is None or df_ticker.empty:
        return None
    close = df_ticker["Close"].dropna()
    if len(close) < 210:  # zu kurze Historie fuer SMA200 + 2-Tage-Bestaetigung
        return None
    high = df_ticker["High"]
    low = df_ticker["Low"]

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    rsi14 = compute_rsi(close)
    atr14 = compute_atr(high, low, close)
    momentum_pct = close.pct_change(MOMENTUM_WINDOW) * 100

    last_close = close.iloc[-1]
    last_sma50 = sma50.iloc[-1]
    last_sma200 = sma200.iloc[-1]
    last_rsi = rsi14.iloc[-1]
    last_atr = atr14.iloc[-1]
    last_momentum = momentum_pct.iloc[-1]

    if any(pd.isna(x) for x in [last_sma50, last_sma200, last_rsi, last_atr, last_momentum]):
        return None

    rel_strength = last_momentum - spy_momentum

    # Trendbruch braucht 2 aufeinanderfolgende Schlusskurse unter SMA200 (vermeidet Fehlsignale an einzelnen Tagen)
    below_sma200_2days = bool(
        close.iloc[-1] < sma200.iloc[-1] and close.iloc[-2] < sma200.iloc[-2]
    )

    dist_to_sma50_pct = (last_close - last_sma50) / last_sma50 * 100

    return {
        "symbol": symbol,
        "price_usd": round(float(last_close), 2),
        "sma50": round(float(last_sma50), 2),
        "sma200": round(float(last_sma200), 2),
        "rsi14": round(float(last_rsi), 1),
        "atr14": round(float(last_atr), 2),
        "momentum_pct": round(float(last_momentum), 1),
        "rel_strength_pct": round(float(rel_strength), 1),
        "dist_to_sma50_pct": round(float(dist_to_sma50_pct), 1),
        "_below_sma200_2days": below_sma200_2days,
        "_sma50_below_sma200": bool(last_sma50 < last_sma200),
    }


def assign_clusters(rows, momentum_threshold_top20):
    for r in rows:
        is_d = r["_below_sma200_2days"] or r["_sma50_below_sma200"] or r["momentum_pct"] < 0
        if is_d:
            r["cluster"] = "D"
            r["cluster_reason"] = "Trendbruch: Kurs unter SMA200 (2 Tage bestaetigt), SMA50 unter SMA200 oder negatives 6-Monats-Momentum."
            continue
        is_a = (
            r["price_usd"] > r["sma50"] > r["sma200"]
            and r["momentum_pct"] >= momentum_threshold_top20
            and r["rel_strength_pct"] > 0
        )
        if is_a:
            r["cluster"] = "A"
            r["cluster_reason"] = "Starker Trend: Kurs ueber SMA50/SMA200, Momentum unter den staerksten 20% des Universums, staerker als der S&P 500."
            continue
        is_b = abs(r["dist_to_sma50_pct"]) <= 3 or r["rsi14"] < 40
        if is_b:
            r["cluster"] = "B"
            r["cluster_reason"] = "Ruecksetzer im intakten Aufwaertstrend: nahe SMA50 oder RSI unter 40."
            continue
        r["cluster"] = "C"
        r["cluster_reason"] = "Kein klarer Trend."
    return rows


# ---------------------------------------------------------------------------
# Schritt 6: Earnings-Termin + Claude-Kommentar (nur fuer Top-Kandidaten)
# ---------------------------------------------------------------------------

def check_earnings_soon(symbol):
    try:
        t = yf.Ticker(symbol)
        cal = t.get_earnings_dates(limit=1)
        if cal is None or cal.empty:
            return False, None
        next_date = cal.index[0]
        if next_date.tzinfo is not None:
            next_date = next_date.tz_localize(None)
        days_until = (next_date - datetime.now()).days
        return (0 <= days_until <= 5), str(next_date.date())
    except Exception:
        return False, None


def get_claude_commentary(candidates, name_lookup):
    if not ANTHROPIC_API_KEY:
        log("Kein ANTHROPIC_API_KEY gesetzt - ueberspringe Claude-Kommentare.")
        for c in candidates:
            c["commentary_pro"] = None
            c["commentary_con"] = None
        return candidates

    try:
        import anthropic
    except ImportError:
        log("anthropic-Paket fehlt - ueberspringe Claude-Kommentare.")
        for c in candidates:
            c["commentary_pro"] = None
            c["commentary_con"] = None
        return candidates

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for c in candidates:
        name = name_lookup.get(c["symbol"], c["symbol"])
        prompt = (
            f"Aktie: {name} ({c['symbol']}), Sektor: {c.get('sector', 'unbekannt')}.\n"
            f"Cluster: {c['cluster']} ({c['cluster_reason']}).\n"
            f"Kurs: {c['price_usd']} USD, SMA50: {c['sma50']}, SMA200: {c['sma200']}, "
            f"RSI14: {c['rsi14']}, 6-Monats-Momentum: {c['momentum_pct']}%, "
            f"relative Staerke vs. S&P 500: {c['rel_strength_pct']} Punkte.\n\n"
            "Antworte NUR als JSON-Objekt ohne Markdown-Codeblock, im Format: "
            '{"pro": "...", "con": "..."}. '
            "pro = 1-2 Saetze, warum die technische Einordnung fuer diese Aktie spricht. "
            "con = 1-2 Saetze mit dem wichtigsten Gegenargument oder Risiko (z.B. Bewertung, "
            "Branchenlage, anstehende Ereignisse). Keine Kaufempfehlung aussprechen, "
            "nur die technische Lage einordnen. Deutsch, sachlich, keine Floskeln."
        )
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(text)
            c["commentary_pro"] = parsed.get("pro")
            c["commentary_con"] = parsed.get("con")
        except Exception as e:
            log(f"Claude-Kommentar fehlgeschlagen fuer {c['symbol']}: {e}")
            c["commentary_pro"] = None
            c["commentary_con"] = None
        time.sleep(0.3)  # kleine Pause zwischen Calls

    return candidates


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------

def main():
    universe_df = load_universe()
    tickers = universe_df["symbol"].tolist()
    sector_lookup = dict(zip(universe_df["symbol"], universe_df["sector"]))
    name_lookup = dict(zip(universe_df["symbol"], universe_df["name"]))

    prices = load_prices(tickers)

    # --- SPY (Markt-Filter + Benchmark-Momentum) ---
    spy = prices["SPY"].dropna()
    spy_close = spy["Close"]
    spy_sma200 = spy_close.rolling(200).mean()
    spy_momentum = float(spy_close.pct_change(MOMENTUM_WINDOW).iloc[-1] * 100)
    market_risk_on = bool(spy_close.iloc[-1] > spy_sma200.iloc[-1])

    # --- EUR/USD ---
    try:
        fx = prices["EURUSD=X"]["Close"].dropna().iloc[-1]
        fx_eur_usd = float(fx)  # 1 EUR = fx_eur_usd USD (Yahoo-Konvention)
    except Exception:
        log("EURUSD=X nicht verfuegbar, nutze Fallback-Kurs 1.08")
        fx_eur_usd = 1.08

    # --- Alle Ticker analysieren ---
    log("Berechne Indikatoren je Ticker ...")
    rows = []
    for sym in tickers:
        try:
            df_t = prices[sym] if sym in prices.columns.get_level_values(0) else None
            r = analyze_ticker(sym, df_t, spy_momentum)
            if r:
                r["name"] = name_lookup.get(sym, sym)
                r["sector"] = sector_lookup.get(sym, "unbekannt")
                r["price_eur"] = round(r["price_usd"] / fx_eur_usd, 2)
                rows.append(r)
        except Exception as e:
            log(f"Fehler bei {sym}: {e}")

    log(f"{len(rows)} von {len(tickers)} Tickern erfolgreich berechnet.")

    momentum_values = [r["momentum_pct"] for r in rows]
    momentum_threshold_top20 = float(np.percentile(momentum_values, 80)) if momentum_values else 0.0

    rows = assign_clusters(rows, momentum_threshold_top20)

    # --- Top-Kandidaten (A vor B, dann nach relativer Staerke) ---
    ab_rows = [r for r in rows if r["cluster"] in ("A", "B")]
    ab_rows.sort(key=lambda r: (0 if r["cluster"] == "A" else 1, -r["rel_strength_pct"]))
    top_candidates = [dict(r) for r in ab_rows[:TOP_N_CANDIDATES]]

    log(f"Pruefe Earnings-Termine fuer {len(top_candidates)} Kandidaten ...")
    for c in top_candidates:
        soon, edate = check_earnings_soon(c["symbol"])
        c["earnings_soon"] = soon
        c["earnings_date"] = edate

    log("Hole Claude-Kurzeinordnung fuer Kandidaten ...")
    top_candidates = get_claude_commentary(top_candidates, name_lookup)

    # interne Hilfsfelder aus der Ausgabe entfernen
    for r in rows:
        r.pop("_below_sma200_2days", None)
        r.pop("_sma50_below_sma200", None)
    for c in top_candidates:
        c.pop("_below_sma200_2days", None)
        c.pop("_sma50_below_sma200", None)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_filter": {
            "spy_price": round(float(spy_close.iloc[-1]), 2),
            "spy_sma200": round(float(spy_sma200.iloc[-1]), 2),
            "spy_momentum_6m_pct": round(spy_momentum, 1),
            "risk_on": market_risk_on,
        },
        "fx_eur_usd": round(fx_eur_usd, 4),
        "universe_count": len(rows),
        "top_candidates": top_candidates,
        "universe": rows,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log(f"Fertig. {len(top_candidates)} Kandidaten, {len(rows)} Ticker im Universum. "
        f"Markt-Filter risk_on={market_risk_on}. Datei: {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("FEHLER im Hauptablauf:")
        traceback.print_exc()
        sys.exit(1)
