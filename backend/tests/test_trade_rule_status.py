from __future__ import annotations

from backend.app.ai import TradingAnalyst


KNOWLEDGE = [{
    "title": "Max stop loss cap",
    "content": "If price action invalidates the setup or hits the 10% loss threshold, exit the position immediately.",
    "tags": ["risk", "stop-loss"],
    "category": "risk_rule",
}]


def _context(**overrides):
    context = {
        "metrics": {
            "fill_count": 1,
            "trade_count": 1,
            "closed_trades": 1,
            "net_pnl": "-12.50",
            "fees": "1.00",
            "gross_pnl": "-11.50",
        },
        "grouped_orders": [{
            "order_id": "abc-1",
            "symbol": "ETHUSDT",
            "fill_count": 1,
            "realized_pnl": "-12.50",
            "notional": "500",
            "fees": "1.00",
        }],
        "retrieved_knowledge": KNOWLEDGE,
        "chart_context": {},
        "trade_lifecycle": {},
    }
    context.update(overrides)
    return context


def _analysis(**overrides):
    analysis = {
        "summary": "Test summary",
        "trade_reviews": [],
        "fee_impact": "Test fee impact",
        "long_vs_short": "Test direction",
        "repeated_patterns": [],
        "risk_suggestions": [],
        "discipline_suggestions": [],
    }
    analysis.update(overrides)
    return analysis


def test_trade_reviews_use_explicit_compliance_statuses() -> None:
    result = TradingAnalyst._complete_from_data(_analysis(), _context())
    review = result["trade_reviews"][0]
    assert review["rule_status"] in TradingAnalyst.VALID_RULE_STATUSES
    assert 0 <= review["compliance_score"] <= 100


def test_losing_trade_is_not_scored_as_a_violation() -> None:
    result = TradingAnalyst._complete_from_data(_analysis(), _context())
    review = result["trade_reviews"][0]
    assert review["rule_status"] == "fully compliant"
    assert review["compliance_score"] == 100
    assert "P&L" in review["notes"] or "realized" in review["notes"].lower()


def test_missing_stop_lowers_confidence_instead_of_violating() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(),
        _context(
            chart_context={"candles": [{"timestamp": "1", "open": "1", "high": "1", "low": "1", "close": "1"}]},
            trade_lifecycle={
                "direction": "Long",
                "entry_at": "2026-01-01T00:00:00+00:00",
                "exit_at": "2026-01-01T01:00:00+00:00",
                "entry_price": "100",
                "exit_price": "90",
                "holding_seconds": 3600,
            },
        ),
    )
    review = result["trade_reviews"][0]
    assert review["rule_status"] == "fully compliant"
    assert review["confidence"] <= 0.5
    assert any("stop" in item.lower() for item in review["missing_evidence"])


def test_summary_does_not_call_bearish_structure_bullish() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(summary="The trade was a Long entry in ETHUSDT, where the setup was bullish with EMA20 above EMA50, but the trade resulted in a loss due to hitting the stop loss."),
        _context(
            technical_context={
                "trend": "bearish",
                "technical_summary": "The 15-minute structure at entry was bearish (descending channel, bearish CHoCH).",
            }
        ),
    )
    assert "bullish" not in result["summary"].lower() or "bearish" in result["summary"].lower()
    assert result["summary"].lower().startswith("the 15-minute structure at entry was bearish")


def test_summary_does_not_call_bullish_structure_bearish() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(summary="The setup was bearish with EMA20 above EMA50, but price continued higher."),
        _context(
            technical_context={
                "trend": "bullish",
                "technical_summary": "The 15-minute structure at entry was bullish (ascending channel, bullish CHoCH).",
            }
        ),
    )
    assert result["summary"].lower().startswith("the 15-minute structure at entry was bullish")
    assert "setup was bearish" not in result["summary"].lower()


def test_summary_does_not_force_one_way_bias_on_mixed() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(summary="The setup was bullish with EMA20 above EMA50, and the trade was held overnight."),
        _context(
            technical_context={
                "trend": "mixed",
                "technical_summary": "The 15-minute structure at entry was mixed (descending channel, bullish CHoCH).",
            }
        ),
    )
    assert result["summary"].lower().startswith("the 15-minute structure at entry was mixed")


def test_chart_review_appends_detector_smc() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(chart_review="Model only talked about the close candle."),
        _context(
            grouped_orders=[{
                "order_id": "abc-1",
                "symbol": "ETHUSDT",
                "fill_count": 1,
                "realized_pnl": "-12.50",
                "notional": "500",
                "fees": "1.00",
                "average_price": "2453",
                "executed_at": "1",
            }],
            chart_context={"candles": [{"timestamp": "1", "open": "2460", "high": "2466", "low": "2440", "close": "2454"}]},
            trade_lifecycle={"direction": "Long", "entry_price": "2494.17", "exit_price": "2453.26"},
            technical_context={
                "trend": "bearish",
                "technical_summary": "The 15-minute structure at entry was bearish (descending channel, bearish CHoCH).",
                "smc": {
                    "channel": {"direction": "descending"},
                    "choch": [{"type": "Bearish CHoCH"}],
                    "trade_timing_analysis": "The Long trade was entered at index 86 (2494.17) along the upper boundary (premium zone) of the descending parallel channel and exited at index 104 (2453.26).",
                },
            },
        ),
    )
    review = result["chart_review"].lower()
    assert "ranged from" in review
    assert "descending" in review
    assert "premium" in review
    assert "bearish choch" in review
    assert review != "15-minute candle near the recorded long close ranged from 2440 to 2466 and closed at 2454 (open 2460). the recorded close price was 2453.26. the original entry is not present in this order record. no bybit stop-loss was found on the related orders."


def test_model_rule_status_and_notes_are_kept() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(
            trade_reviews=[{
                "order_id": "abc-1",
                "symbol": "ETHUSDT",
                "rule_status": "fully compliant",
                "compliance_score": 88,
                "matched_rules": ["Max stop loss cap"],
                "notes": "The reconstructed exit is consistent with the planned invalidation.",
                "evidence": ["Model cited the reconstructed lifecycle."],
                "missing_evidence": [],
                "confidence": 0.9,
            }]
        ),
        _context(grouped_orders=[{
            "order_id": "abc-1",
            "symbol": "ETHUSDT",
            "fill_count": 4,
            "realized_pnl": "-40",
            "notional": "500",
            "fees": "1.00",
        }]),
    )
    review = result["trade_reviews"][0]
    assert review["rule_status"] == "fully compliant"
    assert review["compliance_score"] == 88
    assert review["notes"] == "The reconstructed exit is consistent with the planned invalidation."
    assert "Model cited the reconstructed lifecycle." in review["evidence"]
    assert review["confidence"] <= 0.5


def test_invalid_model_status_falls_back_to_process_score() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(trade_reviews=[{
            "order_id": "abc-1",
            "rule_status": "looks bad because it lost money",
            "notes": "",
        }]),
        _context(),
    )
    assert result["trade_reviews"][0]["rule_status"] == "fully compliant"


def test_summary_does_not_prepend_fill_and_fee_stats() -> None:
    result = TradingAnalyst._complete_from_data(_analysis(), _context())
    assert result["summary"] == "Test summary"
    prefixed = TradingAnalyst._complete_from_data(
        _analysis(summary="The history contains 1 fills across 1 grouped orders and 1 closed P&L events. Net realized P&L after fees is -21.35791345 USDT. Analyzed trade for ETHUSDT."),
        _context(),
    )
    assert prefixed["summary"] == "Analyzed trade for ETHUSDT."


def test_holding_time_is_formatted_and_exit_reason_is_omitted() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(missing_evidence=["Exit reason recorded by the trader."]),
        _context(
            trade_lifecycle={
                "direction": "Long",
                "entry_at": "2026-01-01T00:00:00+00:00",
                "exit_at": "2026-01-01T01:00:00+00:00",
                "entry_price": "100",
                "exit_price": "90",
                "holding_seconds": 3600,
                "stop_loss": "95",
                "take_profit": "110",
            }
        ),
    )
    review = result["trade_reviews"][0]
    assert any("1h" in item for item in review["evidence"])
    assert any("stop-loss was 95" in item.lower() for item in review["evidence"])
    assert not any("exit reason" in item.lower() for item in review["missing_evidence"])
    assert not any("None seconds" in item for item in review["evidence"])
    zero = TradingAnalyst._complete_from_data(
        _analysis(trade_reviews=[{
            "order_id": "abc-1",
            "evidence": ["Trade duration: 0 seconds."],
            "missing_evidence": ["Trade duration: 0 seconds."],
        }]),
        _context(trade_lifecycle={
            "direction": "Long",
            "entry_at": "2026-01-01T00:00:00+00:00",
            "exit_at": "2026-01-01T01:00:00+00:00",
            "holding_seconds": 3600,
            "stop_loss": "95",
        }),
    )
    zero_review = zero["trade_reviews"][0]
    assert not any("0 second" in item.lower() for item in zero_review["evidence"] + zero_review["missing_evidence"])
    assert any("1h" in item for item in zero_review["evidence"])
    from backend.app.analytics import reconstruct_closed_trades

    orphan = reconstruct_closed_trades([
        {"order_id": "noise-sell", "symbol": "ETHUSDT", "side": "Sell", "quantity": "1", "price": "2400", "fee": "0", "realized_pnl": "-1", "executed_at": "1000"},
        {"order_id": "entry-1", "symbol": "ETHUSDT", "side": "Buy", "quantity": "1", "price": "2500", "fee": "0", "realized_pnl": "0", "executed_at": "1000000000000"},
        {"order_id": "close-1", "symbol": "ETHUSDT", "side": "Sell", "quantity": "1", "price": "2477", "fee": "1", "realized_pnl": "-19", "executed_at": "1000003600000"},
    ])
    close = next(trade for trade in orphan if trade["order_id"] == "close-1")
    assert close["holding_seconds"] == 3600
    aged = reconstruct_closed_trades([
        {"order_id": "old-buy", "symbol": "ETHUSDT", "side": "Buy", "quantity": "1", "price": "2000", "fee": "0", "realized_pnl": "0", "executed_at": "1000000000000"},
        {"order_id": "new-buy", "symbol": "ETHUSDT", "side": "Buy", "quantity": "1", "price": "2500", "fee": "0", "realized_pnl": "0", "executed_at": "1788000000000"},
        {"order_id": "close-2", "symbol": "ETHUSDT", "side": "Sell", "quantity": "1", "price": "2477", "fee": "1", "realized_pnl": "-19", "executed_at": "1788003600000"},
    ])
    recent = next(trade for trade in aged if trade["order_id"] == "close-2")
    assert recent["holding_seconds"] == 3600


def test_model_fee_and_direction_text_are_not_replaced() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(fee_impact="Fees were small relative to the planned stop.", long_vs_short="This close looks like a long exit."),
        _context(),
    )
    assert result["fee_impact"] == "Fees were small relative to the planned stop."
    assert result["long_vs_short"] == "This close looks like a long exit."


def test_model_exit_reason_is_stripped_from_missing_evidence() -> None:
    result = TradingAnalyst._complete_from_data(
        _analysis(trade_reviews=[{
            "order_id": "abc-1",
            "missing_evidence": ["Exit reason recorded by the trader.", "Planned stop-loss and whether it was moved."],
        }]),
        _context(trade_lifecycle={"stop_loss": "95", "holding_seconds": 90}),
    )
    missing = result["trade_reviews"][0]["missing_evidence"]
    assert not any("exit reason" in item.lower() for item in missing)


def test_apply_order_tpsl_reads_stop_orders() -> None:
    from backend.app.analytics import apply_order_tpsl, format_holding

    lifecycle = apply_order_tpsl(
        {"order_id": "close-1", "entry_at": "1", "exit_at": "1"},
        [
            {"order_id": "entry-1", "stop_loss": "2400", "take_profit": "2600"},
            {"order_id": "close-1", "stop_order_type": "StopLoss", "trigger_price": "2400", "create_type": "CreateByStopLoss"},
        ],
    )
    assert lifecycle["stop_loss"] == "2400"
    assert lifecycle["take_profit"] == "2600"
    assert lifecycle["exit_trigger"] == "stop loss"
    triggered = apply_order_tpsl(
        {"order_id": "sl-1", "symbol": "ETHUSDT"},
        [{"order_id": "sl-1", "symbol": "ETHUSDT", "stop_order_type": "StopLoss", "create_type": "CreateByStopLoss", "trigger_price": "2479.18", "stop_loss": ""}],
    )
    assert triggered["stop_loss"] == "2479.18"
    assert format_holding(None) is None
    assert format_holding(0) is None
    assert format_holding(90) == "1m 30s"


def test_grouped_trades_keep_stored_stop_and_target() -> None:
    from backend.app.analytics import group_executions
    from backend.app.main import _fills_for_tpsl_backfill

    trades = group_executions([
        {
            "order_id": "entry-1",
            "symbol": "ETHUSDT",
            "side": "Buy",
            "quantity": "1",
            "price": "2500",
            "fee": "0",
            "realized_pnl": "0",
            "executed_at": "1",
        },
        {
            "order_id": "close-1",
            "symbol": "ETHUSDT",
            "side": "Sell",
            "quantity": "1",
            "price": "2477",
            "fee": "1",
            "realized_pnl": "-19",
            "executed_at": "3",
            "stop_loss": "2400",
            "take_profit": "2600",
        }
    ])
    close = next(trade for trade in trades if trade["order_id"] == "close-1")
    assert close["stop_loss"] == "2400"
    assert close["take_profit"] == "2600"
    assert close["entry_price"] == "2500"
    stamped = group_executions([
        {
            "order_id": "close-2",
            "symbol": "ETHUSDT",
            "side": "Sell",
            "quantity": "1",
            "price": "2477",
            "fee": "1",
            "realized_pnl": "-19",
            "executed_at": "3",
            "entry_price": "2479.18",
        }
    ])
    assert stamped[0]["entry_price"] == "2479.18"
    noisy = group_executions([
        {
            "order_id": "close-3",
            "symbol": "ETHUSDT",
            "side": "Sell",
            "quantity": "1",
            "price": "2477",
            "fee": "1",
            "realized_pnl": "-19",
            "executed_at": "3",
            "entry_price": "2448.771318681318681318681319",
            "stop_loss": "2459.19",
        }
    ])
    assert noisy[0]["entry_price"] == "2448.77"
    from backend.app.analytics import _align_price

    assert _align_price("1.224432069955347650435891984", "1.1193") == "1.2244"
    assert _align_price("1.1168", "1.409") == "1.1168"
    backfill = _fills_for_tpsl_backfill([
        {"order_id": "close-1", "realized_pnl": "-19", "stop_loss": None, "take_profit": None},
        {"order_id": "close-1", "realized_pnl": "0", "stop_loss": None},
        {"order_id": "other-1", "realized_pnl": "5", "stop_loss": "1"},
    ])
    assert {item["order_id"] for item in backfill} == {"close-1"}
    from backend.app.storage import SupabaseStore

    keys_a = set(SupabaseStore._storage_row({"external_id": "a", "executed_at": "1"}).keys())
    keys_b = set(
        SupabaseStore._storage_row(
            {
                "external_id": "b",
                "executed_at": "1",
                "stop_loss": "2479.18",
                "stop_order_type": "StopLoss",
                "create_type": "CreateByStopLoss",
            }
        ).keys()
    )
    assert keys_a == keys_b
    assert "stop_loss" in keys_a
