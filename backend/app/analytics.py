from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def group_executions(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for execution in executions:
        key = execution.get("order_id") or execution.get("external_id") or "unknown"
        grouped[key].append(execution)

    trades: list[dict[str, Any]] = []
    for order_id, fills in grouped.items():
        quantity = sum(Decimal(str(fill.get("quantity") or 0)) for fill in fills)
        notional = sum(
            Decimal(str(fill.get("quantity") or 0)) * Decimal(str(fill.get("price") or 0))
            for fill in fills
        )
        fees = sum(Decimal(str(fill.get("fee") or 0)) for fill in fills)
        realized_pnl = sum(Decimal(str(fill.get("realized_pnl") or 0)) for fill in fills)
        weighted_price = notional / quantity if quantity else Decimal("0")
        first_fill = min(fills, key=lambda fill: str(fill.get("executed_at") or ""))
        sides = {str(fill.get("side") or "") for fill in fills}
        stop_loss = next((price for fill in fills if (price := _positive_price(fill.get("stop_loss")))), None)
        take_profit = next((price for fill in fills if (price := _positive_price(fill.get("take_profit")))), None)
        entry_price = next((price for fill in fills if (price := _positive_price(fill.get("entry_price")))), None)

        trades.append(
            {
                "order_id": order_id,
                "symbol": first_fill.get("symbol"),
                "side": next(iter(sides)) if len(sides) == 1 else "Mixed",
                "fill_count": len(fills),
                "quantity": _number(quantity),
                "average_price": _number(weighted_price),
                "notional": _number(notional),
                "fees": _number(fees),
                "realized_pnl": _number(realized_pnl),
                "executed_at": first_fill.get("executed_at"),
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }
        )

    reconstructed_entry = {
        item["order_id"]: item.get("entry_price")
        for item in reconstruct_closed_trades(executions)
        if item.get("order_id") and item.get("entry_price")
    }
    for trade in trades:
        trade["entry_price"] = _align_price(
            trade.get("entry_price") or reconstructed_entry.get(trade["order_id"]),
            trade.get("stop_loss"),
            trade.get("take_profit"),
        )
    return sorted(trades, key=lambda trade: str(trade.get("executed_at") or ""), reverse=True)


def reconstruct_closed_trades(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair opposite-side fills into approximate closed position lifecycles."""
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for execution in executions:
        by_symbol[str(execution.get("symbol") or "UNKNOWN")].append(execution)

    closed: dict[str, dict[str, Any]] = {}
    for symbol, symbol_executions in by_symbol.items():
        lots: list[dict[str, Any]] = []
        position_qty = Decimal("0")
        for execution in sorted(symbol_executions, key=lambda item: _timestamp_ms(item.get("executed_at"))):
            quantity = Decimal(str(execution.get("quantity") or 0))
            price = Decimal(str(execution.get("price") or 0))
            if quantity <= 0 or price <= 0:
                continue
            side = str(execution.get("side") or "")
            signed_quantity = quantity if side == "Buy" else -quantity
            opening = position_qty == 0 or (position_qty > 0 and signed_quantity > 0) or (position_qty < 0 and signed_quantity < 0)
            realized = Decimal(str(execution.get("realized_pnl") or 0)) != 0
            if opening:
                if position_qty == 0 and realized:
                    recovered = _lots_from_prior_opens(symbol_executions, side, execution.get("executed_at"), quantity)
                    qty_sum = sum((lot["quantity"] for lot in recovered), Decimal("0"))
                    if qty_sum > 0:
                        lots.extend(recovered)
                        position_qty = qty_sum if side == "Sell" else -qty_sum
                    else:
                        lots.append({
                            "quantity": quantity,
                            "price": price,
                            "executed_at": execution.get("executed_at"),
                            "order_id": execution.get("order_id"),
                            "stop_loss": execution.get("stop_loss"),
                            "take_profit": execution.get("take_profit"),
                        })
                        position_qty += signed_quantity
                        continue
                else:
                    lots.append({
                        "quantity": quantity,
                        "price": price,
                        "executed_at": execution.get("executed_at"),
                        "order_id": execution.get("order_id"),
                        "stop_loss": execution.get("stop_loss"),
                        "take_profit": execution.get("take_profit"),
                    })
                    position_qty += signed_quantity
                    continue

            remaining = abs(signed_quantity)
            if remaining > 0 and not lots:
                lots.extend(_lots_from_prior_opens(symbol_executions, side, execution.get("executed_at"), remaining))
                qty_sum = sum((lot["quantity"] for lot in lots), Decimal("0"))
                if qty_sum > 0:
                    position_qty = qty_sum if side == "Sell" else -qty_sum
            closed_quantity = Decimal("0")
            entry_notional = Decimal("0")
            entry_times: list[Any] = []
            entry_order_ids: list[str] = []
            direction = "Long" if position_qty > 0 else "Short"
            entry_stop_loss = None
            entry_take_profit = None
            while remaining > 0 and lots:
                lot = lots[0]
                matched = min(remaining, lot["quantity"])
                closed_quantity += matched
                entry_notional += matched * lot["price"]
                entry_times.append(lot.get("executed_at"))
                if lot.get("order_id"):
                    entry_order_ids.append(str(lot["order_id"]))
                entry_stop_loss = entry_stop_loss or _positive_price(lot.get("stop_loss"))
                entry_take_profit = entry_take_profit or _positive_price(lot.get("take_profit"))
                lot["quantity"] -= matched
                remaining -= matched
                if lot["quantity"] <= 0:
                    lots.pop(0)

            if closed_quantity > 0:
                exit_order_id = str(execution.get("order_id") or execution.get("external_id") or "unknown")
                lifecycle = closed.setdefault(
                    exit_order_id,
                    {
                        "order_id": exit_order_id,
                        "symbol": symbol,
                        "direction": direction,
                        "quantity": Decimal("0"),
                        "entry_notional": Decimal("0"),
                        "exit_notional": Decimal("0"),
                        "realized_pnl": Decimal("0"),
                        "fees": Decimal("0"),
                        "entry_times": [],
                        "entry_order_ids": [],
                        "exit_at": execution.get("executed_at"),
                        "stop_loss": _positive_price(execution.get("stop_loss")),
                        "take_profit": _positive_price(execution.get("take_profit")),
                    },
                )
                lifecycle["quantity"] += closed_quantity
                lifecycle["entry_notional"] += entry_notional
                lifecycle["exit_notional"] += closed_quantity * price
                lifecycle["realized_pnl"] += Decimal(str(execution.get("realized_pnl") or 0))
                lifecycle["fees"] += Decimal(str(execution.get("fee") or 0))
                lifecycle["entry_times"].extend(entry_times)
                lifecycle["entry_order_ids"].extend(entry_order_ids)
                lifecycle["stop_loss"] = lifecycle.get("stop_loss") or entry_stop_loss or _positive_price(execution.get("stop_loss"))
                lifecycle["take_profit"] = lifecycle.get("take_profit") or entry_take_profit or _positive_price(execution.get("take_profit"))
            position_qty += signed_quantity

    result = []
    for lifecycle in closed.values():
        entry_at = min(lifecycle["entry_times"], key=_timestamp_ms) if lifecycle["entry_times"] else None
        exit_at = lifecycle["exit_at"]
        close_side = "Sell" if lifecycle["direction"] == "Long" else "Buy"
        walkback = _lots_from_prior_opens(
            by_symbol[lifecycle["symbol"]],
            close_side,
            exit_at,
            lifecycle["quantity"],
        )
        if walkback:
            entry_at = min(walkback, key=lambda lot: _timestamp_ms(lot.get("executed_at"))).get("executed_at")
        result.append(
            {
                "order_id": lifecycle["order_id"],
                "symbol": lifecycle["symbol"],
                "direction": lifecycle["direction"],
                "quantity": _number(lifecycle["quantity"]),
                "entry_price": _align_price(
                    lifecycle["entry_notional"] / lifecycle["quantity"],
                    lifecycle.get("stop_loss"),
                    lifecycle.get("take_profit"),
                ),
                "exit_price": _align_price(
                    lifecycle["exit_notional"] / lifecycle["quantity"],
                    lifecycle.get("stop_loss"),
                    lifecycle.get("take_profit"),
                ),
                "realized_pnl": _number(lifecycle["realized_pnl"]),
                "fees": _number(lifecycle["fees"]),
                "entry_at": entry_at,
                "exit_at": exit_at,
                "holding_seconds": _holding_seconds(entry_at, exit_at),
                "entry_order_ids": sorted(set(lifecycle["entry_order_ids"])),
                "stop_loss": lifecycle.get("stop_loss"),
                "take_profit": lifecycle.get("take_profit"),
                "reconstructed": True,
            }
        )
    return sorted(result, key=lambda trade: _timestamp_ms(trade.get("exit_at")), reverse=True)


def _timestamp_ms(value: Any) -> int:
    if value is None:
        return 0
    text = str(value)
    if text.isdigit():
        return int(text)
    from datetime import datetime

    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def _holding_seconds(entry_at: Any, exit_at: Any) -> int | None:
    if not entry_at or not exit_at:
        return None
    delta = int((_timestamp_ms(exit_at) - _timestamp_ms(entry_at)) / 1000)
    return delta if delta > 0 else None


def format_holding(seconds: Any) -> str | None:
    if seconds is None or seconds == "":
        return None
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    minutes, rem = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m {rem}s" if rem else f"{minutes}m"
    return f"{value} seconds"


def _lots_from_prior_opens(
    executions: list[dict[str, Any]],
    close_side: str,
    close_at: Any,
    close_qty: Any = None,
) -> list[dict[str, Any]]:
    opposite = "Buy" if close_side == "Sell" else "Sell"
    close_ms = _timestamp_ms(close_at)
    try:
        need = Decimal(str(close_qty or 0))
    except (ArithmeticError, ValueError):
        need = Decimal("0")
    picked: list[dict[str, Any]] = []
    for item in sorted(executions, key=lambda row: _timestamp_ms(row.get("executed_at")), reverse=True):
        stamp = _timestamp_ms(item.get("executed_at"))
        if stamp >= close_ms:
            continue
        side = str(item.get("side") or "")
        if side == close_side and Decimal(str(item.get("realized_pnl") or 0)) != 0:
            break
        if side != opposite:
            continue
        quantity = Decimal(str(item.get("quantity") or 0))
        price = Decimal(str(item.get("price") or 0))
        if quantity <= 0 or price <= 0:
            continue
        picked.append({
            "quantity": quantity,
            "price": price,
            "executed_at": item.get("executed_at"),
            "order_id": item.get("order_id"),
            "stop_loss": item.get("stop_loss"),
            "take_profit": item.get("take_profit"),
        })
        if need > 0:
            need -= quantity
            if need <= 0:
                break
        else:
            break
    return list(reversed(picked))


def _positive_price(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text in {"0", "0.0", "0.00"}:
        return None
    try:
        if float(text) <= 0:
            return None
    except ValueError:
        return None
    return text


def apply_order_tpsl(lifecycle: dict[str, Any] | None, orders: list[dict[str, Any]], close_fills: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if not lifecycle:
        return lifecycle
    updated = dict(lifecycle)
    stop_loss = _positive_price(updated.get("stop_loss"))
    take_profit = _positive_price(updated.get("take_profit"))
    exit_trigger = updated.get("exit_trigger")
    symbol = str(updated.get("symbol") or "")
    close_id = str(updated.get("order_id") or "")

    for order in orders:
        if symbol and order.get("symbol") and str(order.get("symbol")) != symbol:
            continue
        stop_loss = stop_loss or _positive_price(order.get("stop_loss"))
        take_profit = take_profit or _positive_price(order.get("take_profit"))
        stop_type = str(order.get("stop_order_type") or "")
        create_type = str(order.get("create_type") or "")
        trigger = _positive_price(order.get("trigger_price"))
        if "StopLoss" in stop_type or stop_type == "Stop":
            stop_loss = stop_loss or trigger
        if "TakeProfit" in stop_type:
            take_profit = take_profit or trigger
        is_close = str(order.get("order_id") or "") == close_id
        if is_close and ("StopLoss" in stop_type or "StopLoss" in create_type or stop_type == "Stop"):
            exit_trigger = "stop loss"
            stop_loss = stop_loss or trigger or _positive_price(order.get("avg_price"))
        if is_close and ("TakeProfit" in stop_type or "TakeProfit" in create_type):
            exit_trigger = "take profit"
            take_profit = take_profit or trigger or _positive_price(order.get("avg_price"))

    for fill in close_fills or []:
        stop_loss = stop_loss or _positive_price(fill.get("stop_loss"))
        take_profit = take_profit or _positive_price(fill.get("take_profit"))
        stop_type = str(fill.get("stop_order_type") or "")
        create_type = str(fill.get("create_type") or "")
        if str(fill.get("order_id") or "") != close_id:
            continue
        if "StopLoss" in stop_type or "StopLoss" in create_type:
            exit_trigger = "stop loss"
        elif "TakeProfit" in stop_type or "TakeProfit" in create_type:
            exit_trigger = "take profit"

    if stop_loss:
        updated["stop_loss"] = stop_loss
    if take_profit:
        updated["take_profit"] = take_profit
    if exit_trigger:
        updated["exit_trigger"] = exit_trigger
    if updated.get("holding_seconds") is None:
        updated["holding_seconds"] = _holding_seconds(updated.get("entry_at"), updated.get("exit_at"))
    return updated


def _number(value: Decimal) -> str:
    return format(value, "f")


def _frac_places(value: Any) -> int | None:
    parsed = _positive_price(value)
    if parsed is None:
        return None
    if "." not in parsed:
        return None
    return len(parsed.split(".", 1)[1])


def _align_price(value: Any, *refs: Any) -> str | None:
    parsed = _positive_price(value)
    if parsed is None:
        return None
    amount = Decimal(parsed)
    places = max((place for ref in refs if (place := _frac_places(ref)) is not None), default=None)
    source_places = _frac_places(parsed)
    if source_places is not None and source_places <= 6:
        places = source_places if places is None else max(places, source_places)
    if places is None:
        places = 2 if amount >= 100 else 4 if amount >= 1 else 6 if amount >= Decimal("0.01") else 8
    return format(amount.quantize(Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP), "f")


def calculate_metrics(executions: list[dict[str, Any]]) -> dict[str, Any]:
    trades = group_executions(executions)
    fees = sum(Decimal(str(trade["fees"])) for trade in trades)
    gross_pnl = sum(Decimal(str(trade["realized_pnl"])) for trade in trades)
    net_pnl = gross_pnl - fees
    winners = sum(1 for trade in trades if Decimal(str(trade["realized_pnl"])) > 0)
    losers = sum(1 for trade in trades if Decimal(str(trade["realized_pnl"])) < 0)
    closed_trades = winners + losers

    symbol_totals: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {"trades": 0, "notional": Decimal("0"), "fees": Decimal("0"), "net_pnl": Decimal("0")}
    )
    for trade in trades:
        symbol = str(trade.get("symbol") or "Unknown")
        totals = symbol_totals[symbol]
        totals["trades"] += 1
        totals["notional"] += Decimal(str(trade["notional"]))
        totals["fees"] += Decimal(str(trade["fees"]))
        totals["net_pnl"] += Decimal(str(trade["realized_pnl"])) - Decimal(str(trade["fees"]))

    return {
        "fill_count": len(executions),
        "trade_count": len(trades),
        "closed_trades": closed_trades,
        "winners": winners,
        "losers": losers,
        "win_rate": round((winners / closed_trades) * 100, 2) if closed_trades else 0,
        "gross_pnl": _number(gross_pnl),
        "fees": _number(fees),
        "net_pnl": _number(net_pnl),
        "notional": _number(sum(Decimal(str(trade["notional"])) for trade in trades)),
        "by_symbol": [
            {
                "symbol": symbol,
                "trades": int(totals["trades"]),
                "notional": _number(totals["notional"]),
                "fees": _number(totals["fees"]),
                "net_pnl": _number(totals["net_pnl"]),
            }
            for symbol, totals in sorted(symbol_totals.items())
        ],
    }
