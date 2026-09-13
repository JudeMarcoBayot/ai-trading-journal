from __future__ import annotations

from typing import Any


def analyze_candles(
    candles: list[dict[str, str]],
    trade: dict[str, Any],
    lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = sorted(candles, key=lambda candle: float(candle.get("timestamp") or 0))
    if len(ordered) < 5:
        return {"available": False, "reason": "Not enough candles for technical analysis."}

    values = [
        {
            "timestamp": float(candle.get("timestamp") or 0),
            "open": float(candle.get("open") or 0),
            "high": float(candle.get("high") or 0),
            "low": float(candle.get("low") or 0),
            "close": float(candle.get("close") or 0),
        }
        for candle in ordered
    ]
    true_ranges = []
    for index, candle in enumerate(values):
        previous_close = values[index - 1]["close"] if index else candle["close"]
        true_ranges.append(max(candle["high"] - candle["low"], abs(candle["high"] - previous_close), abs(candle["low"] - previous_close)))
    atr14 = sum(true_ranges[-14:]) / min(14, len(true_ranges))

    direction = str((lifecycle or {}).get("direction") or ("Long" if trade.get("side") == "Sell" else "Short" if trade.get("side") == "Buy" else "Mixed"))
    entry_price = float((lifecycle or {}).get("entry_price") or trade.get("average_price") or 0)
    stop_loss = float((lifecycle or {}).get("stop_loss") or trade.get("stop_loss") or 0)
    take_profit = float((lifecycle or {}).get("take_profit") or trade.get("take_profit") or 0)

    entry_timestamp = _timestamp((lifecycle or {}).get("entry_at"))
    exit_timestamp = _timestamp((lifecycle or {}).get("exit_at") or trade.get("executed_at"))
    exit_index = _nearest_index(values, exit_timestamp) if exit_timestamp else len(values) - 1
    has_lifecycle = bool(lifecycle and entry_timestamp and entry_timestamp != exit_timestamp)
    if has_lifecycle:
        entry_index = _nearest_index(values, entry_timestamp)
    else:
        entry_index = max(0, exit_index - 15)
    if exit_index < entry_index:
        entry_index, exit_index = exit_index, entry_index
    elif exit_index == entry_index and entry_index > 0:
        entry_index = max(0, exit_index - 1)

    prior_index = max(0, entry_index - 10)
    prior_close = values[prior_index]["close"]
    pre_entry_move = ((entry_price - prior_close) / prior_close * 100) if has_lifecycle and prior_close else 0
    window = values[entry_index : exit_index + 1] or [values[-1]]
    highest = max(candle["high"] for candle in window)
    lowest = min(candle["low"] for candle in window)
    if entry_price:
        if direction == "Long":
            favorable_move = (highest - entry_price) / entry_price * 100
            adverse_move = (lowest - entry_price) / entry_price * 100
        elif direction == "Short":
            favorable_move = (entry_price - lowest) / entry_price * 100
            adverse_move = (entry_price - highest) / entry_price * 100
        else:
            favorable_move = 0
            adverse_move = 0
    else:
        favorable_move = 0
        adverse_move = 0

    risk_reward_ratio = 0.0
    sl_hit = False
    tp_hit = False
    if entry_price and stop_loss:
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price) if take_profit else 0
        if risk > 0 and reward > 0:
            risk_reward_ratio = round(reward / risk, 2)
        if direction == "Long":
            sl_hit = lowest <= stop_loss
            tp_hit = take_profit > 0 and highest >= take_profit
        elif direction == "Short":
            sl_hit = highest >= stop_loss
            tp_hit = take_profit > 0 and lowest <= take_profit

    recent = values[max(0, exit_index - 20) : exit_index + 1]
    support = min(candle["low"] for candle in recent)
    resistance = max(candle["high"] for candle in recent)
    pre_entry = values[: entry_index + 1]
    pre_closes = [candle["close"] for candle in pre_entry]
    ema20 = _ema(pre_closes, 20)
    ema50 = _ema(pre_closes, 50)

    swings = _detect_swings(values)
    order_blocks = [
        ob for ob in _detect_order_blocks(values, atr14, max_index=entry_index)
        if ob["start_index"] < entry_index and ob["end_index"] <= entry_index
    ]
    fvgs = [
        f for f in _detect_fvgs(values, atr14, max_index=entry_index)
        if f["start_index"] < entry_index and f["end_index"] <= entry_index
    ]
    bos_detected, choch_detected = _detect_bos_choch(values, swings, max_index=entry_index)
    bos_list = [b for b in bos_detected if b["break_index"] <= entry_index]
    choch_list = [c for c in choch_detected if c["break_index"] <= entry_index]
    liquidity_pools = [
        p for p in _detect_liquidity_pools(values, swings, max_index=entry_index)
        if p["index"] <= entry_index
    ]
    fit_bars = 32
    if len(pre_entry) >= 8:
        fit_src = pre_entry[-fit_bars:] if len(pre_entry) > fit_bars else pre_entry
        index_offset = len(pre_entry) - len(fit_src)
    else:
        fit_src = values
        index_offset = 0
    channel = _fit_parallel_channel(fit_src, atr14, index_offset)
    last = len(values) - 1
    channel = {
        **channel,
        "end_upper": round(channel["slope"] * last + channel["intercept"] + channel["upper_offset"], 6),
        "end_lower": round(channel["slope"] * last + channel["intercept"] + channel["lower_offset"], 6),
        "end_mid": round(channel["slope"] * last + channel["intercept"] + channel["mid_offset"], 6),
    }
    trend, trend_reason = _classify_structure(
        pre_closes,
        values[entry_index]["close"],
        channel["direction"],
        choch_list,
        bos_list,
    )

    timing_analysis = _analyze_trade_timing(
        values=values,
        entry_index=entry_index,
        exit_index=exit_index,
        entry_price=entry_price,
        direction=direction,
        order_blocks=order_blocks,
        channel=channel,
        has_lifecycle=has_lifecycle,
    )

    smc_data = {
        "order_blocks": order_blocks,
        "fvgs": fvgs,
        "bos": bos_list,
        "choch": choch_list,
        "liquidity_pools": liquidity_pools,
        "channel": channel,
        "trade_timing_analysis": timing_analysis,
    }

    reason = f" ({trend_reason})" if trend_reason else ""
    technical_summary = (
        f"The 15-minute structure at entry was {trend}{reason}. EMA20 was {ema20:g} and EMA50 was {ema50:g}. "
        f"Nearby support was {support:g}, resistance was {resistance:g}, and ATR14 was {atr14:g}. "
        f"Smart Money analysis shows an {channel['direction']} parallel channel with "
        f"{len(order_blocks)} order block(s) detected. {timing_analysis} "
        + (f"From entry to exit, maximum favorable movement was {favorable_move:.2f}% and maximum adverse movement was {adverse_move:.2f}%."
            if has_lifecycle else "A complete entry lifecycle was unavailable, so favorable/adverse movement was not measured across the full trade.")
    )

    return {
        "available": True,
        "direction": direction,
        "trend": trend,
        "ema20": round(ema20, 6),
        "ema50": round(ema50, 6),
        "atr14": round(atr14, 6),
        "support": round(support, 6),
        "resistance": round(resistance, 6),
        "pre_entry_move_percent": round(pre_entry_move, 3),
        "max_favorable_excursion_percent": round(favorable_move, 3),
        "max_adverse_excursion_percent": round(adverse_move, 3),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward_ratio": risk_reward_ratio,
        "sl_hit": sl_hit,
        "tp_hit": tp_hit,
        "candle_count": len(values),
        "technical_summary": technical_summary,
        "smc": smc_data,
    }


def _classify_structure(
    pre_closes: list[float],
    close_at_entry: float,
    channel_direction: str,
    choch_list: list[dict[str, Any]],
    bos_list: list[dict[str, Any]],
) -> tuple[str, str]:
    score = 0
    notes: list[str] = []
    if channel_direction == "descending":
        score -= 2
        notes.append("descending channel")
    elif channel_direction == "ascending":
        score += 2
        notes.append("ascending channel")

    last_choch = choch_list[-1] if choch_list else None
    last_bos = bos_list[-1] if bos_list else None
    if last_choch and "Bearish" in str(last_choch.get("type") or ""):
        score -= 2
        notes.append("bearish CHoCH")
    elif last_choch and "Bullish" in str(last_choch.get("type") or ""):
        score += 2
        notes.append("bullish CHoCH")
    elif last_bos and "Bearish" in str(last_bos.get("type") or ""):
        score -= 1
        notes.append("bearish BOS")
    elif last_bos and "Bullish" in str(last_bos.get("type") or ""):
        score += 1
        notes.append("bullish BOS")

    ema20 = _ema(pre_closes, 20)
    ema50 = _ema(pre_closes, 50)
    lookback = min(8, max(3, len(pre_closes) // 4))
    prior = pre_closes[:-lookback] if len(pre_closes) > lookback + 5 else pre_closes
    ema20_prev = _ema(prior, 20)
    buffer = max(abs(ema50) * 0.001, 1e-9)
    if ema20 > ema50 + buffer:
        score += 1
    elif ema20 < ema50 - buffer:
        score -= 1
    if ema20 > ema20_prev + buffer:
        score += 1
        notes.append("rising EMA20")
    elif ema20 < ema20_prev - buffer:
        score -= 1
        notes.append("rolling-over EMA20")
    if close_at_entry > ema20 + buffer:
        score += 1
    elif close_at_entry < ema20 - buffer:
        score -= 1

    if score >= 2:
        return "bullish", ", ".join(notes)
    if score <= -2:
        return "bearish", ", ".join(notes)
    return "mixed", ", ".join(notes) or "no dominant structure"


def _ema(values: list[float], period: int) -> float:
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _nearest_index(values: list[dict[str, float]], timestamp: float) -> int:
    return min(range(len(values)), key=lambda index: abs(values[index]["timestamp"] - timestamp))


def _timestamp(value: Any) -> float:
    if value is None:
        return 0
    text = str(value)
    if text.isdigit():
        return float(text)
    from datetime import datetime

    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000


def _detect_swings(values: list[dict[str, float]], window: int = 2) -> dict[str, list[dict[str, Any]]]:
    highs = []
    lows = []
    n = len(values)
    for i in range(window, n - window):
        c_high = values[i]["high"]
        c_low = values[i]["low"]
        if all(c_high >= values[i + j]["high"] for j in range(-window, window + 1) if j != 0):
            highs.append({"index": i, "timestamp": values[i]["timestamp"], "price": c_high})
        if all(c_low <= values[i + j]["low"] for j in range(-window, window + 1) if j != 0):
            lows.append({"index": i, "timestamp": values[i]["timestamp"], "price": c_low})
    return {"highs": highs, "lows": lows}


def _detect_order_blocks(
    values: list[dict[str, float]], atr: float, max_index: int | None = None
) -> list[dict[str, Any]]:
    obs = []
    n = len(values)
    limit_idx = max(2, min(max_index, n - 1)) if max_index is not None else n - 1
    # Try standard threshold first, fallback to slightly lower if no OBs found
    for mult in (0.25, 0.15):
        threshold = max(atr * mult, 0.0001)
        for i in range(1, max(1, limit_idx - 1)):
            candle = values[i]
            fut_limit = min(i + 5, limit_idx + 1)
            if fut_limit <= i + 1:
                continue

            if candle["close"] < candle["open"]:
                future_max = max(values[j]["high"] for j in range(i + 1, fut_limit))
                if future_max - candle["high"] >= threshold:
                    top = max(candle["open"], candle["close"])
                    bottom = candle["low"]
                    end_idx = limit_idx
                    for k in range(i + 1, limit_idx + 1):
                        if values[k]["low"] < bottom:
                            end_idx = k
                            break
                    obs.append({
                        "type": "Bullish OB",
                        "start_index": i,
                        "end_index": end_idx,
                        "top": round(top, 6),
                        "bottom": round(bottom, 6),
                        "start_timestamp": candle["timestamp"],
                    })

            if candle["close"] > candle["open"]:
                future_min = min(values[j]["low"] for j in range(i + 1, fut_limit))
                if candle["low"] - future_min >= threshold:
                    top = candle["high"]
                    bottom = min(candle["open"], candle["close"])
                    end_idx = limit_idx
                    for k in range(i + 1, limit_idx + 1):
                        if values[k]["high"] > top:
                            end_idx = k
                            break
                    obs.append({
                        "type": "Bearish OB",
                        "start_index": i,
                        "end_index": end_idx,
                        "top": round(top, 6),
                        "bottom": round(bottom, 6),
                        "start_timestamp": candle["timestamp"],
                    })

        if obs:
            break

    bullish = [ob for ob in obs if ob["type"] == "Bullish OB"]
    bearish = [ob for ob in obs if ob["type"] == "Bearish OB"]

    # Deduplicate overlapping OBs of the same type (keep the most recent / prominent)
    def _dedup_obs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        deduped: list[dict[str, Any]] = []
        for item in reversed(items):
            overlap = any(
                abs(item["start_index"] - existing["start_index"]) <= 2
                or (item["bottom"] <= existing["top"] and item["top"] >= existing["bottom"])
                for existing in deduped
            )
            if not overlap:
                deduped.append(item)
            if len(deduped) >= 2:
                break
        return list(reversed(deduped))

    clean_bullish = _dedup_obs(bullish)
    clean_bearish = _dedup_obs(bearish)
    return clean_bullish + clean_bearish


def _detect_fvgs(
    values: list[dict[str, float]], atr: float, max_index: int | None = None
) -> list[dict[str, Any]]:
    fvgs = []
    n = len(values)
    limit_idx = max(2, min(max_index, n - 1)) if max_index is not None else n - 1
    min_gap = max(atr * 0.10, 0.0001)
    for i in range(1, limit_idx):
        if i + 1 > limit_idx:
            break
        prev_c = values[i - 1]
        next_c = values[i + 1]
        if next_c["low"] > prev_c["high"] and (next_c["low"] - prev_c["high"]) >= min_gap:
            fvgs.append({
                "type": "Bullish FVG",
                "start_index": i - 1,
                "end_index": min(i + 12, limit_idx),
                "top": round(next_c["low"], 6),
                "bottom": round(prev_c["high"], 6),
                "label": "FVG",
            })
        elif prev_c["low"] > next_c["high"] and (prev_c["low"] - next_c["high"]) >= min_gap:
            fvgs.append({
                "type": "Bearish FVG",
                "start_index": i - 1,
                "end_index": min(i + 12, limit_idx),
                "top": round(prev_c["low"], 6),
                "bottom": round(next_c["high"], 6),
                "label": "FVG",
            })
    # Deduplicate overlapping FVGs to keep the chart clean
    clean_fvgs: list[dict[str, Any]] = []
    for f in reversed(fvgs):
        overlap = any(
            abs(f["start_index"] - existing["start_index"]) <= 2
            or (f["bottom"] <= existing["top"] and f["top"] >= existing["bottom"])
            for existing in clean_fvgs
        )
        if not overlap:
            clean_fvgs.append(f)
        if len(clean_fvgs) >= 2:
            break
    return list(reversed(clean_fvgs))


def _detect_bos_choch(
    values: list[dict[str, float]],
    swings: dict[str, list[dict[str, Any]]],
    max_index: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bos_list = []
    choch_list = []
    n = len(values)
    limit_idx = max(2, min(max_index, n - 1)) if max_index is not None else n - 1

    for sh in swings["highs"]:
        sh_idx = sh["index"]
        if sh_idx >= limit_idx:
            continue
        sh_price = sh["price"]
        for i in range(sh_idx + 1, limit_idx + 1):
            if values[i]["close"] > sh_price:
                bos_list.append({
                    "type": "Bullish BOS",
                    "from_index": sh_idx,
                    "break_index": i,
                    "price": round(sh_price, 6),
                    "label": "BOS",
                })
                break

    for sl in swings["lows"]:
        sl_idx = sl["index"]
        if sl_idx >= limit_idx:
            continue
        sl_price = sl["price"]
        for i in range(sl_idx + 1, limit_idx + 1):
            if values[i]["close"] < sl_price:
                bos_list.append({
                    "type": "Bearish BOS",
                    "from_index": sl_idx,
                    "break_index": i,
                    "price": round(sl_price, 6),
                    "label": "BOS",
                })
                break

    pre_highs = [sh for sh in swings["highs"] if sh["index"] <= limit_idx]
    pre_lows = [sl for sl in swings["lows"] if sl["index"] <= limit_idx]

    if len(pre_highs) >= 1 and len(pre_lows) >= 1:
        last_high = pre_highs[-1]
        last_low = pre_lows[-1]
        if last_high["index"] > last_low["index"]:
            choch_list.append({
                "type": "Bullish CHoCH",
                "from_index": last_low["index"],
                "break_index": min(last_high["index"] + 2, limit_idx),
                "price": round(last_low["price"], 6),
                "label": "CHoCH",
            })
        else:
            choch_list.append({
                "type": "Bearish CHoCH",
                "from_index": last_high["index"],
                "break_index": min(last_low["index"] + 2, limit_idx),
                "price": round(last_high["price"], 6),
                "label": "CHoCH",
            })

    # Deduplicate BOS that occur at virtually the same break index or price
    clean_bos: list[dict[str, Any]] = []
    for b in reversed(bos_list):
        clash = any(
            abs(b["break_index"] - existing["break_index"]) <= 3
            or abs(b["price"] - existing["price"]) / (b["price"] or 1.0) < 0.0015
            for existing in clean_bos
        )
        if not clash:
            clean_bos.append(b)
        if len(clean_bos) >= 2:
            break
    bos_list = list(reversed(clean_bos))

    return bos_list, choch_list[-2:]


def _detect_liquidity_pools(
    values: list[dict[str, float]],
    swings: dict[str, list[dict[str, Any]]],
    max_index: int | None = None,
) -> list[dict[str, Any]]:
    pools = []
    limit_idx = max(0, min(max_index, len(values) - 1)) if max_index is not None else len(values) - 1
    pre_highs = [sh for sh in swings["highs"] if sh["index"] <= limit_idx]
    pre_lows = [sl for sl in swings["lows"] if sl["index"] <= limit_idx]

    if pre_highs:
        max_high = max(pre_highs, key=lambda x: x["price"])
        pools.append({
            "type": "Buy-side Liquidity",
            "index": max_high["index"],
            "price": round(max_high["price"], 6),
            "label": "BSL",
        })
    if pre_lows:
        min_low = min(pre_lows, key=lambda x: x["price"])
        pools.append({
            "type": "Sell-side Liquidity",
            "index": min_low["index"],
            "price": round(min_low["price"], 6),
            "label": "SSL",
        })
    return pools


def _fit_parallel_channel(
    values: list[dict[str, float]],
    atr: float = 0.0,
    index_offset: int = 0,
) -> dict[str, Any]:
    n = len(values)
    if n < 2:
        return {
            "slope": 0, "intercept": 0, "upper_offset": 0, "lower_offset": 0, "mid_offset": 0,
            "start_upper": 0, "end_upper": 0, "start_lower": 0, "end_lower": 0, "start_mid": 0, "end_mid": 0,
            "direction": "flat",
        }

    x_vals = list(range(n))
    y_vals = [c["close"] for c in values]

    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    num = sum((x_vals[i] - mean_x) * (y_vals[i] - mean_y) for i in range(n))
    den = sum((x_vals[i] - mean_x) ** 2 for i in range(n)) or 1.0

    slope = num / den
    local_intercept = mean_y - slope * mean_x
    intercept = local_intercept - slope * index_offset

    upper_dev = max(values[i]["high"] - (slope * i + local_intercept) for i in range(n))
    lower_dev = min(values[i]["low"] - (slope * i + local_intercept) for i in range(n))
    mid_offset = (upper_dev + lower_dev) / 2
    midline_move = slope * (n - 1)
    threshold = atr if atr > 0 else abs(mean_y) * 0.0001
    direction = (
        "ascending" if midline_move > threshold
        else "descending" if midline_move < -threshold
        else "horizontal"
    )
    start_x = index_offset
    end_x = index_offset + n - 1

    return {
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
        "upper_offset": round(upper_dev, 6),
        "lower_offset": round(lower_dev, 6),
        "mid_offset": round(mid_offset, 6),
        "start_upper": round(slope * start_x + intercept + upper_dev, 6),
        "end_upper": round(slope * end_x + intercept + upper_dev, 6),
        "start_lower": round(slope * start_x + intercept + lower_dev, 6),
        "end_lower": round(slope * end_x + intercept + lower_dev, 6),
        "start_mid": round(slope * start_x + intercept + mid_offset, 6),
        "end_mid": round(slope * end_x + intercept + mid_offset, 6),
        "direction": direction,
    }


def _analyze_trade_timing(
    values: list[dict[str, float]],
    entry_index: int,
    exit_index: int,
    entry_price: float,
    direction: str,
    order_blocks: list[dict[str, Any]],
    channel: dict[str, Any],
    has_lifecycle: bool,
) -> str:
    n = len(values)
    entry_candle = values[min(entry_index, n - 1)]
    exit_candle = values[min(exit_index, n - 1)]

    matched_ob = None
    for ob in order_blocks:
        if ob["start_index"] <= entry_index <= ob["end_index"]:
            if ob["bottom"] * 0.998 <= entry_candle["low"] and entry_candle["high"] <= ob["top"] * 1.002:
                matched_ob = ob["type"]
                break

    entry_mid = channel["slope"] * entry_index + channel["intercept"] + channel["mid_offset"]
    channel_pos = "lower boundary (discount zone)" if entry_candle["close"] < entry_mid else "upper boundary (premium zone)"

    context_str = f"near a {matched_ob}" if matched_ob else f"along the {channel_pos} of the {channel['direction']} parallel channel"

    if not has_lifecycle:
        return (
            f"Based on trade execution context, the {direction} entry was placed near index {entry_index} "
            f"({entry_price or entry_candle['close']:g}) {context_str} and exited at index {exit_index} ({exit_candle['close']:g})."
        )

    return (
        f"The {direction} trade was entered at index {entry_index} ({entry_price or entry_candle['close']:g}) "
        f"{context_str} and exited at index {exit_index} ({exit_candle['close']:g})."
    )
