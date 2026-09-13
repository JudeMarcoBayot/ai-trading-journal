import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


class BybitConfigurationError(RuntimeError):
    pass


class BybitApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class BybitSettings:
    api_key: str
    api_secret: str
    base_url: str = "https://api.bybit.com"
    recv_window: str = "5000"

    @classmethod
    def from_environment(cls) -> "BybitSettings":
        from os import getenv

        api_key = getenv("BYBIT_API_KEY", "")
        api_secret = getenv("BYBIT_API_SECRET", "")
        if not api_key or not api_secret:
            raise BybitConfigurationError(
                "BYBIT_API_KEY and BYBIT_API_SECRET must be configured in the backend environment."
            )
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            base_url=getenv("BYBIT_BASE_URL", "https://api.bybit.com").rstrip("/"),
        )


class BybitClient:
    def __init__(self, settings: BybitSettings) -> None:
        self.settings = settings

    def _signature(self, timestamp: str, query_string: str) -> str:
        payload = f"{timestamp}{self.settings.api_key}{self.settings.recv_window}{query_string}"
        return hmac.new(
            self.settings.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        query_string = urlencode(sorted(params.items()))
        timestamp = str(int(time.time() * 1000))
        headers = {
            "X-BAPI-API-KEY": self.settings.api_key,
            "X-BAPI-SIGN": self._signature(timestamp, query_string),
            "X-BAPI-SIGN-TYPE": "2",
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.settings.recv_window,
        }
        url = f"{path}?{query_string}" if query_string else path
        async with httpx.AsyncClient(base_url=self.settings.base_url, timeout=20) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        if payload.get("retCode") != 0:
            raise BybitApiError(payload.get("retMsg", "Bybit returned an unknown error."))
        return payload

    async def list_executions(
        self,
        category: str = "linear",
        symbol: str | None = None,
        limit: int = 50,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict[str, str | bool | None]]:
        executions, _ = await self.list_executions_page(
            category=category,
            symbol=symbol,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )
        return executions

    async def list_executions_page(
        self,
        category: str = "linear",
        symbol: str | None = None,
        order_id: str | None = None,
        limit: int = 50,
        start_time: int | None = None,
        end_time: int | None = None,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, str | bool | None]], str | None]:
        params: dict[str, str] = {"category": category, "limit": str(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time is not None:
            params["startTime"] = str(start_time)
        if end_time is not None:
            params["endTime"] = str(end_time)
        if cursor:
            params["cursor"] = cursor
        if order_id:
            params["orderId"] = order_id

        result = (await self._get("/v5/execution/list", params)).get("result", {})
        return (
            [self._normalize_execution(item) for item in result.get("list", [])],
            result.get("nextPageCursor") or None,
        )

    async def list_closed_pnl(
        self,
        category: str = "linear",
        symbol: str | None = None,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict[str, str | None]]:
        params: dict[str, str] = {"category": category, "limit": str(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time is not None:
            params["startTime"] = str(start_time)
        if end_time is not None:
            params["endTime"] = str(end_time)

        payload = await self._get("/v5/position/closed-pnl", params)
        return [
            {
                "order_id": item.get("orderId"),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "quantity": item.get("qty"),
                "entry_price": item.get("avgEntryPrice"),
                "exit_price": item.get("avgExitPrice"),
                "closed_pnl": item.get("closedPnl"),
                "created_at": item.get("createdTime"),
            }
            for item in payload.get("result", {}).get("list", [])
        ]

    async def list_positions(
        self,
        category: str = "linear",
        settle_coin: str = "USDT",
    ) -> list[dict[str, str | None]]:
        params = {"category": category, "settleCoin": settle_coin}
        payload = await self._get("/v5/position/list", params)
        return [
            {
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "size": item.get("size"),
                "avg_entry_price": item.get("avgPrice"),
                "mark_price": item.get("markPrice"),
                "unrealized_pnl": item.get("unrealisedPnl"),
                "position_value": item.get("positionValue"),
                "leverage": item.get("leverage"),
            }
            for item in payload.get("result", {}).get("list", [])
            if str(item.get("size") or "0") != "0"
        ]

    async def list_order_history(
        self,
        category: str = "linear",
        symbol: str | None = None,
        order_id: str | None = None,
        order_filter: str | None = None,
        limit: int = 50,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict[str, str | None]]:
        params: dict[str, str] = {"category": category, "limit": str(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if order_id:
            params["orderId"] = order_id
        if order_filter:
            params["orderFilter"] = order_filter
        if start_time is not None:
            params["startTime"] = str(start_time)
        if end_time is not None:
            params["endTime"] = str(end_time)

        payload = await self._get("/v5/order/history", params)
        return [self._normalize_order(item) for item in payload.get("result", {}).get("list", [])]

    async def list_klines(
        self,
        symbol: str,
        interval: str = "15",
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, str]]:
        params: dict[str, str] = {
            "category": "linear",
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": str(limit),
        }
        if start_time is not None:
            params["start"] = str(start_time)
        if end_time is not None:
            params["end"] = str(end_time)

        payload = await self._get("/v5/market/kline", params)
        return [
            {
                "timestamp": item[0],
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "volume": item[5],
                "turnover": item[6],
            }
            for item in payload.get("result", {}).get("list", [])
        ]

    async def attach_tpsl(self, executions: list[dict[str, str | bool | None]]) -> list[dict[str, str | bool | None]]:
        from .analytics import _timestamp_ms, apply_order_tpsl, reconstruct_closed_trades

        orders: list[dict[str, str | None]] = []
        seen: set[str] = set()
        for execution in executions:
            order_id = str(execution.get("order_id") or "")
            if not order_id or order_id in seen:
                continue
            seen.add(order_id)
            try:
                orders.extend(await self.list_order_history(
                    symbol=str(execution.get("symbol") or "") or None,
                    order_id=order_id,
                ))
            except (BybitApiError, httpx.HTTPError):
                continue
        by_symbol: dict[str, list[int]] = {}
        for execution in executions:
            symbol = str(execution.get("symbol") or "")
            if not symbol:
                continue
            by_symbol.setdefault(symbol, []).append(_timestamp_ms(execution.get("executed_at")))
        week = 7 * 24 * 60 * 60 * 1000
        for symbol, times in by_symbol.items():
            start_ms = min(times) - 60_000
            end_ms = max(times) + 60_000
            if end_ms - start_ms > week:
                start_ms = end_ms - week
            try:
                orders.extend(await self.list_order_history(
                    symbol=symbol,
                    order_filter="StopOrder",
                    start_time=start_ms,
                    end_time=end_ms,
                    limit=50,
                ))
            except (BybitApiError, httpx.HTTPError):
                continue
        for execution in executions:
            order_id = str(execution.get("order_id") or "")
            related_orders = [item for item in orders if str(item.get("order_id") or "") == order_id]
            patched = apply_order_tpsl(
                {"order_id": order_id, "symbol": execution.get("symbol")},
                related_orders,
                [execution],
            )
            if patched and patched.get("stop_loss"):
                execution["stop_loss"] = patched["stop_loss"]
            if patched and patched.get("take_profit"):
                execution["take_profit"] = patched["take_profit"]
        for lifecycle in reconstruct_closed_trades(executions):
            related = [
                item for item in executions
                if item.get("order_id") == lifecycle.get("order_id")
                or str(item.get("order_id") or "") in set(lifecycle.get("entry_order_ids") or [])
            ]
            if lifecycle.get("entry_price"):
                for item in executions:
                    if item.get("order_id") == lifecycle.get("order_id") and not item.get("entry_price"):
                        item["entry_price"] = lifecycle["entry_price"]
            patched = apply_order_tpsl(lifecycle, orders, related)
            if not patched:
                continue
            for item in related:
                if patched.get("stop_loss"):
                    item["stop_loss"] = patched["stop_loss"]
                if patched.get("take_profit"):
                    item["take_profit"] = patched["take_profit"]
        return executions

    @staticmethod
    def _normalize_execution(item: dict[str, str]) -> dict[str, str | bool | None]:
        return {
            "external_id": item.get("execId"),
            "order_id": item.get("orderId"),
            "symbol": item.get("symbol"),
            "side": item.get("side"),
            "category": item.get("category") or "linear",
            "quantity": item.get("execQty"),
            "price": item.get("execPrice"),
            "realized_pnl": item.get("execPnl") or "0",
            "fee": item.get("execFee"),
            "fee_currency": item.get("feeCurrency"),
            "executed_at": item.get("execTime"),
            "is_maker": item.get("isMaker") == "true",
            "stop_order_type": item.get("stopOrderType") or None,
            "create_type": item.get("createType") or None,
        }

    @staticmethod
    def _normalize_order(item: dict[str, str]) -> dict[str, str | None]:
        return {
            "order_id": item.get("orderId"),
            "symbol": item.get("symbol"),
            "side": item.get("side"),
            "order_status": item.get("orderStatus"),
            "order_type": item.get("orderType"),
            "stop_order_type": item.get("stopOrderType"),
            "create_type": item.get("createType"),
            "trigger_price": item.get("triggerPrice"),
            "stop_loss": item.get("stopLoss"),
            "take_profit": item.get("takeProfit"),
            "avg_price": item.get("avgPrice"),
        }
