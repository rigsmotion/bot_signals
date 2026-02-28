"""
╔══════════════════════════════════════════════════════════════╗
║          CRYPTO SCALPING BOT - HIGH ACCURACY SIGNALS         ║
║         Signals for LONG/SHORT on 10 top crypto pairs        ║
╚══════════════════════════════════════════════════════════════╝

УСТАНОВКА:
    pip install ccxt pandas numpy ta colorama

ЗАПУСК:
    python crypto_scalping_bot.py

ОПИСАНИЕ:
    Бот использует 7 индикаторов для генерации точных скальпинг-сигналов:
    - RSI (Relative Strength Index)
    - MACD (Moving Average Convergence Divergence)
    - Bollinger Bands
    - EMA Cross (9/21)
    - Volume Analysis
    - ATR (Average True Range) — для стоп-лоссов
    - Stochastic RSI
    
    Сигнал генерируется только при совпадении 4+ из 7 индикаторов
"""

import ccxt
import pandas as pd
import numpy as np
import time
import os
from datetime import datetime
from colorama import Fore, Back, Style, init

init(autoreset=True)

# ═══════════════════════════════════════════
#              КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════

CONFIG = {
    # Биржа (binance, bybit, okx, kucoin и др.)
    "EXCHANGE": "bybit",

    # API ключи (оставь пустыми для только чтения данных без торговли)
    "API_KEY": "OK59FVYcekcK7st6Kv",
    "API_SECRET": "gJ1ixee7mmYI3xlanNoCsCGm8JBwp4bfL0wZ",

    # Топ-10 пар для скальпинга
    "SYMBOLS": [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "BNB/USDT",
        "XRP/USDT",
        "DOGE/USDT",
        "ADA/USDT",
        "AVAX/USDT",
        "MATIC/USDT",
        "LINK/USDT",
    ],

    # Таймфрейм для скальпинга (1m, 3m, 5m, 15m)
    "TIMEFRAME": "5m",

    # Количество свечей для анализа
    "CANDLES_LIMIT": 100,

    # Минимальное количество совпавших индикаторов для сигнала (из 7)
    "MIN_CONFIRMATIONS": 4,

    # Интервал обновления сигналов (секунды)
    "SCAN_INTERVAL": 30,

    # Риск на сделку (% от депозита)
    "RISK_PERCENT": 1.0,

    # ATR множитель для стоп-лосса
    "ATR_SL_MULTIPLIER": 1.5,

    # ATR множитель для тейк-профита
    "ATR_TP_MULTIPLIER": 2.5,
}

# ═══════════════════════════════════════════
#           ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ
# ═══════════════════════════════════════════

def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(close: pd.Series, period=20, std_dev=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def calculate_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def calculate_stoch_rsi(close: pd.Series, period=14, smooth_k=3, smooth_d=3):
    rsi = calculate_rsi(close, period)
    rsi_min = rsi.rolling(period).min()
    rsi_max = rsi.rolling(period).max()
    stoch = 100 * (rsi - rsi_min) / (rsi_max - rsi_min + 1e-10)
    k = stoch.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d


def calculate_volume_signal(volume: pd.Series, close: pd.Series, period=20):
    vol_ma = volume.rolling(period).mean()
    vol_ratio = volume / vol_ma
    # Положительное давление объёма (OBV-like)
    price_change = close.diff()
    obv = (volume * np.sign(price_change)).cumsum()
    return vol_ratio, obv


# ═══════════════════════════════════════════
#           ДВИЖОК СИГНАЛОВ
# ═══════════════════════════════════════════

def analyze_symbol(df: pd.DataFrame, symbol: str) -> dict:
    """
    Анализирует символ и возвращает сигнал с подтверждениями.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    results = {
        "symbol": symbol,
        "price": round(close.iloc[-1], 6),
        "signal": "НЕЙТРАЛЬНО",
        "confirmations": 0,
        "indicators": {},
        "stop_loss": None,
        "take_profit": None,
        "strength": 0,
    }

    long_signals = 0
    short_signals = 0
    indicators = {}

    # ── 1. RSI ─────────────────────────────────
    rsi = calculate_rsi(close)
    rsi_val = rsi.iloc[-1]
    indicators["RSI"] = round(rsi_val, 2)

    if rsi_val < 35:
        long_signals += 1
        indicators["RSI_signal"] = "LONG ✓"
    elif rsi_val > 65:
        short_signals += 1
        indicators["RSI_signal"] = "SHORT ✓"
    else:
        indicators["RSI_signal"] = "нейтрально"

    # ── 2. MACD ────────────────────────────────
    macd_line, signal_line, histogram = calculate_macd(close)
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    hist_val = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2]
    indicators["MACD_hist"] = round(hist_val, 6)

    if hist_val > 0 and hist_val > hist_prev:
        long_signals += 1
        indicators["MACD_signal"] = "LONG ✓"
    elif hist_val < 0 and hist_val < hist_prev:
        short_signals += 1
        indicators["MACD_signal"] = "SHORT ✓"
    else:
        indicators["MACD_signal"] = "нейтрально"

    # ── 3. Bollinger Bands ─────────────────────
    bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(close)
    price = close.iloc[-1]
    bb_pos = (price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1] + 1e-10)
    indicators["BB_pos"] = round(bb_pos * 100, 1)

    if bb_pos < 0.15:
        long_signals += 1
        indicators["BB_signal"] = "LONG ✓"
    elif bb_pos > 0.85:
        short_signals += 1
        indicators["BB_signal"] = "SHORT ✓"
    else:
        indicators["BB_signal"] = "нейтрально"

    # ── 4. EMA Cross (9/21) ────────────────────
    ema9 = calculate_ema(close, 9)
    ema21 = calculate_ema(close, 21)
    ema9_curr = ema9.iloc[-1]
    ema21_curr = ema21.iloc[-1]
    ema9_prev = ema9.iloc[-2]
    ema21_prev = ema21.iloc[-2]
    indicators["EMA9"] = round(ema9_curr, 4)
    indicators["EMA21"] = round(ema21_curr, 4)

    # Бычье пересечение
    if ema9_prev <= ema21_prev and ema9_curr > ema21_curr:
        long_signals += 1
        indicators["EMA_signal"] = "LONG ✓ (пересечение)"
    # Медвежье пересечение
    elif ema9_prev >= ema21_prev and ema9_curr < ema21_curr:
        short_signals += 1
        indicators["EMA_signal"] = "SHORT ✓ (пересечение)"
    # Уже выше/ниже
    elif ema9_curr > ema21_curr and price > ema9_curr:
        long_signals += 1
        indicators["EMA_signal"] = "LONG ✓ (выше EMA)"
    elif ema9_curr < ema21_curr and price < ema9_curr:
        short_signals += 1
        indicators["EMA_signal"] = "SHORT ✓ (ниже EMA)"
    else:
        indicators["EMA_signal"] = "нейтрально"

    # ── 5. Volume Analysis ─────────────────────
    vol_ratio, obv = calculate_volume_signal(volume, close)
    vol_ratio_val = vol_ratio.iloc[-1]
    obv_trend = obv.iloc[-1] - obv.iloc[-5]  # OBV тренд за 5 свечей
    indicators["Vol_ratio"] = round(vol_ratio_val, 2)

    price_trend = close.iloc[-1] - close.iloc[-5]

    if vol_ratio_val > 1.5 and price_trend > 0:
        long_signals += 1
        indicators["Volume_signal"] = "LONG ✓ (высокий объём + рост)"
    elif vol_ratio_val > 1.5 and price_trend < 0:
        short_signals += 1
        indicators["Volume_signal"] = "SHORT ✓ (высокий объём + падение)"
    elif obv_trend > 0:
        long_signals += 0.5
        indicators["Volume_signal"] = "слабый LONG"
    elif obv_trend < 0:
        short_signals += 0.5
        indicators["Volume_signal"] = "слабый SHORT"
    else:
        indicators["Volume_signal"] = "нейтрально"

    # ── 6. Stochastic RSI ──────────────────────
    stoch_k, stoch_d = calculate_stoch_rsi(close)
    k_val = stoch_k.iloc[-1]
    d_val = stoch_d.iloc[-1]
    k_prev = stoch_k.iloc[-2]
    indicators["StochRSI_K"] = round(k_val, 2)
    indicators["StochRSI_D"] = round(d_val, 2)

    if k_val < 20 and k_val > k_prev:
        long_signals += 1
        indicators["StochRSI_signal"] = "LONG ✓ (перепродан + разворот)"
    elif k_val > 80 and k_val < k_prev:
        short_signals += 1
        indicators["StochRSI_signal"] = "SHORT ✓ (перекуплен + разворот)"
    elif k_val < 30:
        long_signals += 0.5
        indicators["StochRSI_signal"] = "слабый LONG"
    elif k_val > 70:
        short_signals += 0.5
        indicators["StochRSI_signal"] = "слабый SHORT"
    else:
        indicators["StochRSI_signal"] = "нейтрально"

    # ── 7. ATR + Price Position ────────────────
    atr = calculate_atr(high, low, close)
    atr_val = atr.iloc[-1]
    indicators["ATR"] = round(atr_val, 6)

    # Процентное движение за последние 3 свечи vs ATR
    recent_move = abs(close.iloc[-1] - close.iloc[-3])
    if recent_move < atr_val * 0.5:
        # Маленькое движение = возможный прорыв
        if close.iloc[-1] > ema21_curr:
            long_signals += 0.5
            indicators["ATR_signal"] = "накопление LONG"
        else:
            short_signals += 0.5
            indicators["ATR_signal"] = "накопление SHORT"
    else:
        indicators["ATR_signal"] = "активное движение"

    # ── Итоговый сигнал ────────────────────────
    total = long_signals + short_signals
    results["indicators"] = indicators

    if long_signals >= CONFIG["MIN_CONFIRMATIONS"] and long_signals > short_signals:
        results["signal"] = "LONG"
        results["confirmations"] = int(long_signals)
        results["strength"] = round(long_signals / 7 * 100)
        results["stop_loss"] = round(price - atr_val * CONFIG["ATR_SL_MULTIPLIER"], 6)
        results["take_profit"] = round(price + atr_val * CONFIG["ATR_TP_MULTIPLIER"], 6)

    elif short_signals >= CONFIG["MIN_CONFIRMATIONS"] and short_signals > long_signals:
        results["signal"] = "SHORT"
        results["confirmations"] = int(short_signals)
        results["strength"] = round(short_signals / 7 * 100)
        results["stop_loss"] = round(price + atr_val * CONFIG["ATR_SL_MULTIPLIER"], 6)
        results["take_profit"] = round(price - atr_val * CONFIG["ATR_TP_MULTIPLIER"], 6)

    return results


# ═══════════════════════════════════════════
#              ОТОБРАЖЕНИЕ
# ═══════════════════════════════════════════

def print_header():
    os.system("cls" if os.name == "nt" else "clear")
    print(Fore.CYAN + "═" * 70)
    print(Fore.CYAN + "  🚀  CRYPTO SCALPING BOT — HIGH ACCURACY SIGNALS")
    print(Fore.CYAN + f"  ⏰  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   |   Таймфрейм: {CONFIG['TIMEFRAME']}")
    print(Fore.CYAN + "═" * 70)


def print_signal(result: dict):
    sig = result["signal"]
    sym = result["symbol"]
    price = result["price"]
    strength = result["strength"]
    confirmations = result["confirmations"]

    if sig == "LONG":
        color = Fore.GREEN
        emoji = "🟢"
        bar = "▲"
    elif sig == "SHORT":
        color = Fore.RED
        emoji = "🔴"
        bar = "▼"
    else:
        color = Fore.YELLOW
        emoji = "⚪"
        bar = "─"

    strength_bar = "█" * (strength // 10) + "░" * (10 - strength // 10)

    print(f"\n{color}{emoji} {sym:<12} {bar} {sig:<10} Цена: {price:<14}", end="")

    if sig != "НЕЙТРАЛЬНО":
        print(f"[{strength_bar}] {strength}%  ({confirmations}/7 подтверждений)")
        print(f"   {Fore.WHITE}SL: {result['stop_loss']:<14} TP: {result['take_profit']}")

        # Детали индикаторов
        ind = result["indicators"]
        print(f"   {Fore.CYAN}RSI:{ind.get('RSI','?'):6}  MACD:{ind.get('MACD_hist','?'):>10}  BB%:{ind.get('BB_pos','?'):5}%")
        print(f"   {Fore.CYAN}StochK:{ind.get('StochRSI_K','?'):5}  Vol:{ind.get('Vol_ratio','?'):4}x  ATR:{ind.get('ATR','?')}")

        signals_line = "   "
        for key in ["RSI_signal", "MACD_signal", "BB_signal", "EMA_signal", "Volume_signal", "StochRSI_signal"]:
            val = ind.get(key, "")
            if "LONG ✓" in val:
                signals_line += f"{Fore.GREEN}{val:<28}"
            elif "SHORT ✓" in val:
                signals_line += f"{Fore.RED}{val:<28}"
        print(signals_line)
    else:
        print(f"Недостаточно подтверждений")


def print_summary(results: list):
    longs = [r for r in results if r["signal"] == "LONG"]
    shorts = [r for r in results if r["signal"] == "SHORT"]

    print(f"\n{Fore.CYAN}{'─'*70}")
    print(f"{Fore.WHITE}  📊 ИТОГ: {Fore.GREEN}{len(longs)} LONG  {Fore.RED}{len(shorts)} SHORT  {Fore.YELLOW}{len(results)-len(longs)-len(shorts)} нейтрально")

    if longs:
        best_long = max(longs, key=lambda x: x["strength"])
        print(f"  {Fore.GREEN}🏆 Лучший LONG:  {best_long['symbol']} — сила {best_long['strength']}%")
    if shorts:
        best_short = max(shorts, key=lambda x: x["strength"])
        print(f"  {Fore.RED}🏆 Лучший SHORT: {best_short['symbol']} — сила {best_short['strength']}%")

    print(f"{Fore.CYAN}{'─'*70}")
    print(f"  Следующее обновление через {CONFIG['SCAN_INTERVAL']} сек... (Ctrl+C для выхода)")


# ═══════════════════════════════════════════
#              ОСНОВНОЙ ЦИКЛ
# ═══════════════════════════════════════════

def get_exchange():
    exchange_class = getattr(ccxt, CONFIG["EXCHANGE"])
    exchange = exchange_class({
        "apiKey": CONFIG["API_KEY"],
        "secret": CONFIG["API_SECRET"],
        "enableRateLimit": True,
        "options": {"defaultType": "future"},  # Для фьючерсов (лонг/шорт)
    })
    return exchange


def fetch_ohlcv(exchange, symbol: str) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(symbol, CONFIG["TIMEFRAME"], limit=CONFIG["CANDLES_LIMIT"])
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def run():
    print(Fore.CYAN + "\n  Инициализация биржи...")
    exchange = get_exchange()
    print(Fore.GREEN + f"  ✅ Подключено к {CONFIG['EXCHANGE'].upper()}")
    print(Fore.CYAN + f"  Сканирование {len(CONFIG['SYMBOLS'])} пар каждые {CONFIG['SCAN_INTERVAL']} сек...")
    time.sleep(1)

    while True:
        try:
            print_header()
            results = []

            for symbol in CONFIG["SYMBOLS"]:
                try:
                    df = fetch_ohlcv(exchange, symbol)
                    result = analyze_symbol(df, symbol)
                    results.append(result)
                    print_signal(result)
                except Exception as e:
                    print(f"{Fore.YELLOW}  ⚠️  {symbol}: ошибка — {e}")

            print_summary(results)

            # Лог в файл
            log_signals(results)

            time.sleep(CONFIG["SCAN_INTERVAL"])

        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}  Бот остановлен.")
            break
        except Exception as e:
            print(f"{Fore.RED}  Ошибка: {e}")
            time.sleep(10)


def log_signals(results: list):
    """Сохраняет сигналы в CSV файл."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("signals_log.csv", "a") as f:
        for r in results:
            if r["signal"] != "НЕЙТРАЛЬНО":
                f.write(f"{timestamp},{r['symbol']},{r['signal']},{r['price']},{r['strength']},{r['stop_loss']},{r['take_profit']}\n")


# ═══════════════════════════════════════════
#              БЭКТЕСТ (DEMO MODE)
# ═══════════════════════════════════════════

def demo_backtest():
    """
    Демо-режим: генерирует тестовые данные и показывает как работают сигналы.
    Используй это если нет API ключей.
    """
    print(Fore.CYAN + "\n  📊 DEMO BACKTEST MODE\n")

    # Генерация синтетических OHLCV данных
    np.random.seed(42)
    n = 100
    price = 50000.0
    prices = [price]
    for _ in range(n - 1):
        change = np.random.normal(0, 0.002)
        price *= (1 + change)
        prices.append(price)

    df = pd.DataFrame({
        "close": prices,
        "open": [p * (1 + np.random.normal(0, 0.001)) for p in prices],
        "high": [p * (1 + abs(np.random.normal(0, 0.002))) for p in prices],
        "low": [p * (1 - abs(np.random.normal(0, 0.002))) for p in prices],
        "volume": [np.random.uniform(100, 1000) * p for p in prices],
    })

    result = analyze_symbol(df, "BTC/USDT [DEMO]")
    print_signal(result)
    print(f"\n{Fore.WHITE}  Это демо-режим с синтетическими данными.")
    print(f"  Для реальной работы укажи API_KEY и API_SECRET в CONFIG.\n")


if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        try:
            demo_backtest()
        except Exception as e:
            print(f"Demo error: {e}")
    else:
        try:
            import ccxt
            run()
        except ImportError:
            print(Fore.RED + "\n  ❌ Библиотека ccxt не установлена!")
            print(Fore.YELLOW + "  Запусти: pip install ccxt pandas numpy colorama")
            print(Fore.WHITE + "\n  Для демо без установки запусти: python crypto_scalping_bot.py --demo\n")
