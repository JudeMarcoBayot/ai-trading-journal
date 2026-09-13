from __future__ import annotations

from backend.app.technical import analyze_candles


def test_analyze_candles_detects_smc_and_parallel_channel() -> None:
    candles = [
        {"timestamp": str(1000 + i * 900000), "open": str(100 + i * 0.5), "high": str(102 + i * 0.5), "low": str(99 + i * 0.5), "close": str(101 + i * 0.5)}
        for i in range(20)
    ]
    trade = {"side": "Buy", "average_price": "105.0", "executed_at": str(1000 + 10 * 900000)}
    lifecycle = {
        "direction": "Long",
        "entry_price": "102.5",
        "exit_price": "108.0",
        "entry_at": str(1000 + 5 * 900000),
        "exit_at": str(1000 + 15 * 900000),
    }

    result = analyze_candles(candles, trade, lifecycle)

    assert result["available"] is True
    assert "smc" in result
    smc = result["smc"]
    assert "channel" in smc
    assert smc["channel"]["direction"] == "ascending"
    assert "order_blocks" in smc
    assert "fvgs" in smc
    assert "bos" in smc
    assert "trade_timing_analysis" in smc
    assert "Smart Money analysis" in result["technical_summary"]


def test_smc_structures_are_strictly_before_or_at_entry() -> None:
    # 60 candles: swings and volatility before index 30 and after index 30
    import math

    candles = []
    for i in range(60):
        base = 100 + 10 * math.sin(i / 3.0) + (i * 0.2)
        candles.append({
            "timestamp": str(1000 + i * 900000),
            "open": str(round(base, 2)),
            "high": str(round(base + 2.5, 2)),
            "low": str(round(base - 2.5, 2)),
            "close": str(round(base + (1.0 if i % 2 == 0 else -1.0), 2)),
        })

    entry_idx = 30
    exit_idx = 45
    trade = {"side": "Buy", "average_price": "105.0", "executed_at": str(1000 + exit_idx * 900000)}
    lifecycle = {
        "direction": "Long",
        "entry_price": "105.0",
        "exit_price": "110.0",
        "entry_at": str(1000 + entry_idx * 900000),
        "exit_at": str(1000 + exit_idx * 900000),
    }

    result = analyze_candles(candles, trade, lifecycle)
    assert result["available"] is True
    smc = result["smc"]

    # Verify every order block occurred and ended before or at entry
    for ob in smc["order_blocks"]:
        assert ob["start_index"] < entry_idx, f"Order block started after entry: {ob}"
        assert ob["end_index"] <= entry_idx, f"Order block ended after entry: {ob}"

    # Verify every FVG started and ended before or at entry
    for fvg in smc["fvgs"]:
        assert fvg["start_index"] < entry_idx, f"FVG started after entry: {fvg}"
        assert fvg["end_index"] <= entry_idx, f"FVG ended after entry: {fvg}"

    # Verify every BOS broke before or at entry
    for bos in smc["bos"]:
        assert bos["break_index"] <= entry_idx, f"BOS broke after entry: {bos}"

    # Verify every CHoCH broke before or at entry
    for choch in smc["choch"]:
        assert choch["break_index"] <= entry_idx, f"CHoCH broke after entry: {choch}"

    # Verify liquidity pools are located before or at entry
    for pool in smc["liquidity_pools"]:
        assert pool["index"] <= entry_idx, f"Liquidity pool located after entry: {pool}"


def test_smc_without_lifecycle_estimates_pre_trade_entry() -> None:
    import math

    candles = []
    for i in range(50):
        base = 100 + 5 * math.sin(i / 2.5)
        candles.append({
            "timestamp": str(1000 + i * 900000),
            "open": str(round(base, 2)),
            "high": str(round(base + 2.0, 2)),
            "low": str(round(base - 2.0, 2)),
            "close": str(round(base + 0.5, 2)),
        })

    trade = {"side": "Sell", "average_price": "100.0", "executed_at": str(1000 + 40 * 900000)}
    result = analyze_candles(candles, trade, None)

    assert result["available"] is True
    smc = result["smc"]
    assert "order_blocks" in smc
    assert "channel" in smc
    # When lifecycle is None, exit is index 40, estimated entry is 25
    for ob in smc["order_blocks"]:
        assert ob["start_index"] < 40
        assert ob["end_index"] <= 40
    for pool in smc["liquidity_pools"]:
        assert pool["index"] <= 40


def test_structure_at_entry_is_not_last_candle_ema_cross() -> None:
    from backend.app.technical import _classify_structure

    trend, reason = _classify_structure(
        pre_closes=[2500 - i * 2 for i in range(40)],
        close_at_entry=2420,
        channel_direction="descending",
        choch_list=[{"type": "Bearish CHoCH"}],
        bos_list=[{"type": "Bearish BOS"}],
    )
    assert trend == "bearish"
    assert "descending channel" in reason
    assert "bearish CHoCH" in reason


def _ohlc(i: int, close: float, spread: float = 2.0) -> dict[str, str]:
    return {
        "timestamp": str(1000 + i * 900000),
        "open": str(round(close, 2)),
        "high": str(round(close + spread, 2)),
        "low": str(round(close - spread, 2)),
        "close": str(round(close, 2)),
    }


def test_channel_uses_recent_pre_entry_not_full_day() -> None:
    candles = [_ohlc(i, 2500.0) for i in range(40)]
    for j in range(32):
        close = 2500.0 - j * 5.0
        candles.append(_ohlc(40 + j, close, spread=3.0))
    candles[-1] = {
        **candles[-1],
        "high": "2360",
        "close": "2358",
        "open": "2346",
        "low": "2344",
    }
    candles.extend([_ohlc(72 + k, 2350.0 - k * 2, spread=3.0) for k in range(4)])
    entry_i = 71
    result = analyze_candles(
        candles,
        {"side": "Sell", "average_price": "2340", "executed_at": candles[-1]["timestamp"]},
        {
            "direction": "Long",
            "entry_price": "2358",
            "exit_price": "2340",
            "entry_at": candles[entry_i]["timestamp"],
            "exit_at": candles[-1]["timestamp"],
        },
    )
    channel = result["smc"]["channel"]
    assert channel["direction"] == "descending"
    timing = result["smc"]["trade_timing_analysis"].lower()
    assert "descending" in timing
    assert "premium" in timing


def test_channel_recent_rally_is_ascending_discount() -> None:
    candles = [_ohlc(i, 100.0) for i in range(40)]
    for j in range(32):
        candles.append(_ohlc(40 + j, 100.0 + j * 0.5, spread=0.3))
    candles[-1] = {
        **candles[-1],
        "low": "114.2",
        "close": "114.4",
        "open": "115.5",
        "high": "115.8",
    }
    candles.extend([_ohlc(72 + k, 114.4 + k * 0.2, spread=0.3) for k in range(4)])
    entry_i = 71
    result = analyze_candles(
        candles,
        {"side": "Sell", "average_price": "116", "executed_at": candles[-1]["timestamp"]},
        {
            "direction": "Long",
            "entry_price": "114.4",
            "exit_price": "116",
            "entry_at": candles[entry_i]["timestamp"],
            "exit_at": candles[-1]["timestamp"],
        },
    )
    assert result["smc"]["channel"]["direction"] == "ascending"
    assert "discount" in result["smc"]["trade_timing_analysis"].lower()

