from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
import httpx
from typing import Literal

from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai import AIConfigurationError, AIProviderError, TradingAnalyst, analysis_record
from .bybit import BybitApiError, BybitClient, BybitConfigurationError, BybitSettings
from .analytics import apply_order_tpsl, calculate_metrics, group_executions, reconstruct_closed_trades, _holding_seconds, _lots_from_prior_opens
from .storage import StorageConfigurationError, SupabaseStore, build_knowledge_query
from .technical import analyze_candles, _timestamp

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


class KnowledgeEntry(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)
    category: str = Field(default="trading_rule", max_length=80)


class BybitSyncResponse(BaseModel):
    status: Literal["success"]
    source: Literal["bybit"]
    count: int
    persisted: bool
    next_cursor: str | None
    executions: list[dict[str, str | bool | None]]


app = FastAPI(title="AI Trading Journal API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def persisted_date_bounds(
    start_date: date | None,
    end_date: date | None,
    timezone_offset_minutes: int,
) -> tuple[str | None, str | None]:
    offset = timedelta(minutes=timezone_offset_minutes)
    start_at = (
        (datetime.combine(start_date, time.min, tzinfo=timezone.utc) - offset).isoformat()
        if start_date
        else None
    )
    end_at = (
        (datetime.combine(end_date, time.max, tzinfo=timezone.utc) - offset).isoformat()
        if end_date
        else None
    )
    return start_at, end_at


def _fills_for_tpsl_backfill(executions: list[dict]) -> list[dict]:
    closed_ids = {
        str(item.get("order_id"))
        for item in executions
        if item.get("order_id")
        and float(item.get("realized_pnl") or 0) != 0
        and not item.get("stop_loss")
        and not item.get("take_profit")
    }
    if not closed_ids:
        return []
    needed = set(closed_ids)
    for lifecycle in reconstruct_closed_trades(executions):
        if str(lifecycle.get("order_id") or "") in closed_ids:
            needed.update(str(order_id) for order_id in lifecycle.get("entry_order_ids") or [])
    return [item for item in executions if str(item.get("order_id") or "") in needed]


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/knowledge")
async def create_knowledge_entry(entry: KnowledgeEntry) -> dict[str, object]:
    try:
        record = await SupabaseStore().save_knowledge(
            {
                "title": entry.title,
                "content": entry.content,
                "tags": [tag.strip() for tag in entry.tags if tag and tag.strip()],
                "category": entry.category,
            }
        )
        return {"status": "success", "record": record}
    except StorageConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except httpx.HTTPError as error:
        fallback = {
            "id": f"local-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "title": entry.title,
            "content": entry.content,
            "tags": [tag.strip() for tag in entry.tags if tag and tag.strip()],
            "category": entry.category,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"status": "success", "record": fallback}


@app.get("/api/v1/knowledge", response_model=list[dict[str, object]])
async def get_knowledge(
    query: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=20),
    tags: list[str] | None = Query(default=None),
) -> list[dict[str, object]]:
    try:
        store = SupabaseStore()
        if query or tags:
            return await store.search_knowledge(query or "", limit=limit, tags=tags or [])
        return await store.list_knowledge(limit=limit)
    except StorageConfigurationError:
        return SupabaseStore.fallback_knowledge(query or "", tags or [], limit)
    except httpx.HTTPError:
        return SupabaseStore.fallback_knowledge(query or "", tags or [], limit)


@app.post("/api/v1/sync/bybit", response_model=BybitSyncResponse)
async def sync_bybit_executions(
    symbol: str | None = Query(default=None, min_length=1, max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    cursor: str | None = Query(default=None),
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> BybitSyncResponse:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date.")

    offset = timedelta(minutes=timezone_offset_minutes)
    start_time = (
        int((datetime.combine(start_date, time.min, tzinfo=timezone.utc) - offset).timestamp() * 1000)
        if start_date
        else None
    )
    end_time = (
        int((datetime.combine(end_date, time.max, tzinfo=timezone.utc) - offset).timestamp() * 1000)
        if end_date
        else None
    )
    try:
        client = BybitClient(BybitSettings.from_environment())
        executions, next_cursor = await client.list_executions_page(
            symbol=symbol,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
            cursor=cursor,
        )
        closed_pnl = await client.list_closed_pnl(
            symbol=symbol,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )
    except BybitConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except BybitApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    pnl_by_order = {
        item["order_id"]: item
        for item in closed_pnl
        if item.get("order_id")
    }
    applied_pnl: set[str] = set()
    for execution in executions:
        info = pnl_by_order.get(execution.get("order_id"))
        if not info:
            continue
        order_id = execution.get("order_id")
        if order_id not in applied_pnl and info.get("closed_pnl") is not None:
            execution["realized_pnl"] = info["closed_pnl"]
            applied_pnl.add(order_id)
        if info.get("entry_price"):
            execution["entry_price"] = info["entry_price"]

    try:
        executions = await client.attach_tpsl(executions)
    except (BybitApiError, httpx.HTTPError):
        pass

    persisted = False
    start_at, end_at = persisted_date_bounds(start_date, end_date, timezone_offset_minutes)
    try:
        store = SupabaseStore()
        await store.upsert_executions(executions)
        persisted = True
        stored = await store.list_executions(limit=500, start_at=start_at, end_at=end_at)
        missing = _fills_for_tpsl_backfill(stored)
        if missing:
            try:
                filled = await client.attach_tpsl(missing)
                await store.upsert_executions(filled)
            except (BybitApiError, httpx.HTTPError):
                pass
    except StorageConfigurationError:
        pass
    except httpx.HTTPError as error:
        detail = "Supabase persistence request failed."
        if isinstance(error, httpx.HTTPStatusError):
            body = error.response.text[:800]
            if error.response.status_code == 400 and "PGRST204" in body:
                extra = {"stop_loss", "take_profit", "stop_order_type", "create_type", "entry_price"}
                stripped = [
                    {key: value for key, value in item.items() if key not in extra}
                    for item in executions
                ]
                await SupabaseStore().upsert_executions(stripped)
                persisted = True
                if any(name in body for name in ("stop_loss", "take_profit", "stop_order_type", "create_type")):
                    raise HTTPException(
                        status_code=502,
                        detail="Fills saved, but stop-loss columns are missing in Supabase. Run database/schema.sql and sync again.",
                    ) from error
            else:
                raise HTTPException(status_code=502, detail=f"Could not save fills to Supabase: {body}") from error
        else:
            raise HTTPException(status_code=502, detail=detail) from error

    return BybitSyncResponse(
        status="success",
        source="bybit",
        count=len(executions),
        persisted=persisted,
        next_cursor=next_cursor,
        executions=executions,
    )


@app.get("/api/v1/history", response_model=list[dict[str, object]])
async def get_trade_history(
    limit: int = Query(default=100, ge=1, le=500),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> list[dict[str, object]]:
    try:
        start_at, end_at = persisted_date_bounds(start_date, end_date, timezone_offset_minutes)
        return await SupabaseStore().list_executions(limit=limit, start_at=start_at, end_at=end_at)
    except StorageConfigurationError:
        return []
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Supabase history request failed.") from error


@app.get("/api/v1/trades", response_model=list[dict[str, object]])
async def get_grouped_trades(
    limit: int = Query(default=100, ge=1, le=500),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> list[dict[str, object]]:
    try:
        start_at, end_at = persisted_date_bounds(start_date, end_date, timezone_offset_minutes)
        executions = await SupabaseStore().list_executions(limit=limit, start_at=start_at, end_at=end_at)
        return group_executions(executions)
    except StorageConfigurationError:
        return []
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Supabase trade request failed.") from error


@app.get("/api/v1/metrics", response_model=dict[str, object])
async def get_account_metrics(
    limit: int = Query(default=500, ge=1, le=500),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> dict[str, object]:
    try:
        start_at, end_at = persisted_date_bounds(start_date, end_date, timezone_offset_minutes)
        executions = await SupabaseStore().list_executions(limit=limit, start_at=start_at, end_at=end_at)
        return calculate_metrics(executions)
    except StorageConfigurationError:
        return calculate_metrics([])
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Supabase metrics request failed.") from error


@app.get("/api/v1/positions", response_model=list[dict[str, object]])
async def get_open_positions() -> list[dict[str, object]]:
    try:
        client = BybitClient(BybitSettings.from_environment())
        return await client.list_positions()
    except BybitConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except BybitApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/v1/analyze-history", response_model=dict[str, object])
async def analyze_history(
    limit: int = Query(default=500, ge=1, le=500),
    order_id: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> dict[str, object]:
    try:
        store = SupabaseStore()
        start_at, end_at = persisted_date_bounds(start_date, end_date, timezone_offset_minutes)
        executions = await store.list_executions(limit=limit, start_at=start_at, end_at=end_at)
        if not executions:
            raise HTTPException(status_code=400, detail="Sync Bybit history before requesting an analysis.")
        selected_lifecycle = None
        if order_id:
            close_in_range = [item for item in executions if item.get("order_id") == order_id]
            symbol = str(close_in_range[0].get("symbol") or "") if close_in_range else ""
            close_at = max((str(item.get("executed_at") or "") for item in close_in_range), default="") or None
            lifecycle_source = (
                await store.list_executions(limit=500, symbol=symbol, end_at=close_at)
                if symbol
                else await store.list_executions(limit=500)
            )
            lifecycles = reconstruct_closed_trades(lifecycle_source)
            selected_lifecycle = next((trade for trade in lifecycles if trade.get("order_id") == order_id), None)
            if not selected_lifecycle and symbol and close_at:
                close_ms = _timestamp(close_at)
                selected_lifecycle = next(
                    (
                        trade
                        for trade in lifecycles
                        if trade.get("symbol") == symbol and abs(_timestamp(trade.get("exit_at")) - close_ms) <= 2000
                    ),
                    None,
                )
        metrics = calculate_metrics(executions)
        trades = group_executions(executions)
        if order_id:
            executions = [execution for execution in executions if execution.get("order_id") == order_id]
            if not executions:
                raise HTTPException(status_code=404, detail="That closed trade was not found in the selected history.")
            metrics = calculate_metrics(executions)
            trades = group_executions(executions)
            if not selected_lifecycle and executions:
                sorted_execs = sorted(executions, key=lambda e: _timestamp(e.get("executed_at")))
                first_e = sorted_execs[0]
                last_e = sorted_execs[-1]
                selected_trade = trades[0] if trades else {}
                close_side = str(last_e.get("side") or selected_trade.get("side") or "")
                symbol_fills = [
                    item for item in (lifecycle_source or [])
                    if not selected_trade.get("symbol") or item.get("symbol") == selected_trade.get("symbol")
                ]
                prior_lots = _lots_from_prior_opens(
                    symbol_fills,
                    close_side,
                    last_e.get("executed_at"),
                    last_e.get("quantity") or selected_trade.get("quantity"),
                )
                entry_fill = min(prior_lots, key=lambda lot: _timestamp(lot.get("executed_at"))) if prior_lots else first_e
                selected_lifecycle = {
                    "order_id": order_id,
                    "symbol": selected_trade.get("symbol"),
                    "direction": "Long" if selected_trade.get("side") == "Sell" else "Short" if selected_trade.get("side") == "Buy" else "Mixed",
                    "entry_at": entry_fill.get("executed_at"),
                    "exit_at": last_e.get("executed_at"),
                    "entry_price": str(entry_fill.get("price") or selected_trade.get("entry_price") or selected_trade.get("average_price") or "0"),
                    "exit_price": str(last_e.get("price") or selected_trade.get("average_price") or "0"),
                    "holding_seconds": _holding_seconds(entry_fill.get("executed_at"), last_e.get("executed_at")),
                    "stop_loss": selected_trade.get("stop_loss") or first_e.get("stop_loss"),
                    "take_profit": selected_trade.get("take_profit") or first_e.get("take_profit"),
                }
            if selected_lifecycle:
                selected_lifecycle = apply_order_tpsl(selected_lifecycle, [], lifecycle_source)
                if trades:
                    selected_lifecycle["stop_loss"] = selected_lifecycle.get("stop_loss") or trades[0].get("stop_loss")
                    selected_lifecycle["take_profit"] = selected_lifecycle.get("take_profit") or trades[0].get("take_profit")
                close_side = "Sell" if selected_lifecycle.get("direction") == "Long" else "Buy"
                symbol_fills = [
                    item for item in (lifecycle_source or [])
                    if not selected_lifecycle.get("symbol") or item.get("symbol") == selected_lifecycle.get("symbol")
                ]
                prior_lots = _lots_from_prior_opens(
                    symbol_fills,
                    close_side,
                    selected_lifecycle.get("exit_at"),
                    selected_lifecycle.get("quantity") or (trades[0].get("quantity") if trades else None),
                )
                if prior_lots:
                    entry_fill = min(prior_lots, key=lambda lot: _timestamp(lot.get("executed_at")))
                    selected_lifecycle["entry_at"] = entry_fill.get("executed_at")
                    if not selected_lifecycle.get("entry_price"):
                        selected_lifecycle["entry_price"] = str(entry_fill.get("price") or "")
                    selected_lifecycle["holding_seconds"] = _holding_seconds(
                        entry_fill.get("executed_at"),
                        selected_lifecycle.get("exit_at"),
                    )
        chart_context: dict[str, object] = {
            "available": False,
            "reason": "Chart context is only loaded for an individual trade.",
            "candles": [],
        }
        if order_id and trades:
            try:
                execution_times = []
                for execution in executions:
                    value = execution.get("executed_at")
                    if value is None:
                        continue
                    if str(value).isdigit():
                        execution_times.append(int(str(value)))
                    else:
                        execution_times.append(int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000))
                lifecycle_times = [
                    selected_lifecycle.get("entry_at"),
                    selected_lifecycle.get("exit_at"),
                ] if selected_lifecycle else []
                for value in lifecycle_times:
                    if value is None:
                        continue
                    if str(value).isdigit():
                        execution_times.append(int(str(value)))
                    else:
                        execution_times.append(int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000))
                if execution_times:
                    chart_client = BybitClient(BybitSettings.from_environment())
                    chart_context = {
                        "available": True,
                        "symbol": trades[0].get("symbol"),
                        "interval": "15",
                        "candles": await chart_client.list_klines(
                            symbol=str(trades[0].get("symbol")),
                            interval="15",
                            start_time=min(execution_times) - 24 * 60 * 60 * 1000,
                            end_time=max(execution_times) + 24 * 60 * 60 * 1000,
                            limit=200,
                        ),
                    }
            except (BybitConfigurationError, BybitApiError, httpx.HTTPError) as error:
                chart_context = {
                    "available": False,
                    "reason": f"Chart data could not be loaded: {error}",
                    "candles": [],
                }
        technical_context = (
            analyze_candles(chart_context.get("candles", []), trades[0] if trades else {}, selected_lifecycle)
            if order_id
            else {"available": False, "reason": "Technical analysis is scoped to one selected trade."}
        )
        if technical_context.get("available") and "smc" in technical_context:
            chart_context["smc"] = technical_context["smc"]
        search_query = build_knowledge_query(
            lifecycle=selected_lifecycle,
            trades=trades,
            technical_context=technical_context,
            metrics=metrics,
        )
        try:
            knowledge_context = await store.search_knowledge(search_query, limit=5)
        except (StorageConfigurationError, httpx.HTTPError):
            knowledge_context = SupabaseStore.fallback_knowledge(search_query, limit=5)
        analysis_context = {
            "metrics": metrics,
            "grouped_orders": trades,
            "closed_pnl_orders": [trade for trade in trades if trade.get("realized_pnl") not in (None, "0", "0.0")],
            "retrieved_knowledge": knowledge_context,
            "chart_context": chart_context,
            "trade_lifecycle": selected_lifecycle,
            "technical_context": technical_context,
        }
        analyst = TradingAnalyst()
        analysis = await analyst.analyze(analysis_context)
        record = await store.save_analysis(analysis_record(analysis, analyst.provider))
        return {
            "analysis": analysis.model_dump(),
            "saved": True,
            "created_at": record.get("created_at"),
            "id": record.get("id"),
            "retrieved_knowledge": knowledge_context,
            "chart_context": chart_context,
            "technical_context": technical_context,
            "trade_lifecycle": selected_lifecycle,
        }
    except (AIConfigurationError, StorageConfigurationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except AIProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="AI analysis could not be saved.") from error


@app.get("/api/v1/analyses", response_model=list[dict[str, object]])
async def get_analysis_history(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    try:
        return await SupabaseStore().list_analyses(limit=limit)
    except StorageConfigurationError:
        return []
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="AI analysis history request failed.") from error
