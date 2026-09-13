import math
from datetime import datetime, timezone
from dotenv import load_dotenv
from os import getenv
from pathlib import Path
from typing import Any

import httpx


class StorageConfigurationError(RuntimeError):
    pass


DEFAULT_TRADE_KNOWLEDGE = [
    {
        "id": "default-1",
        "title": "Risk-first journal rule",
        "content": "Treat every trade as a process decision, not a prediction. Risk only a small fraction of account capital per setup and define a stop before entering. If the invalidation level is broken, the thesis is invalid regardless of optimism.",
        "tags": ["risk", "discipline", "stop-loss"],
        "category": "trading_rule",
    },
    {
        "id": "default-2",
        "title": "Fee discipline",
        "content": "Fees matter materially. Review gross P&L, net P&L, and fee impact together. A strategy that wins gross but loses after fees is still a net drag on account growth.",
        "tags": ["fees", "performance", "risk"],
        "category": "trading_rule",
    },
    {
        "id": "default-3",
        "title": "Repeatable setup review",
        "content": "Before the next trade, define the setup, invalidation point, target, and reason for size. Review the last five similar trades to assess whether the plan is still repeatable or whether emotions are overriding discipline.",
        "tags": ["discipline", "execution", "review"],
        "category": "trading_rule",
    },
    {
        "id": "default-4",
        "title": "Position management",
        "content": "Limit concentration and avoid increasing size after loss. When a symbol is already a large account weight, add only if the risk-adjusted case is still attractive; otherwise pass.",
        "tags": ["position-sizing", "risk", "portfolio"],
        "category": "portfolio_rule",
    },
]

# ponytail: query-time neural embeddings (no pgvector); cache by id+content hash if analyze latency hurts.
_COSINE_WEIGHT = 3.0
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vec))
    if not norm:
        return vec
    return [value / norm for value in vec]


def embedding_cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    load_dotenv(_ENV_PATH, override=False)
    if not texts:
        return []
    provider = getenv("AI_PROVIDER", "ollama").lower()
    try:
        if provider == "ollama":
            vectors = await _embed_ollama(texts)
        elif provider == "gemini":
            vectors = await _embed_gemini(texts)
        else:
            return None
        if vectors is None or len(vectors) != len(texts):
            return None
        return [_l2_normalize([float(value) for value in vector]) for vector in vectors]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None


async def _embed_ollama(texts: list[str]) -> list[list[float]] | None:
    model = getenv("OLLAMA_EMBED_MODEL", "").strip()
    if not model:
        return None
    base = getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{base}/api/embed", json={"model": model, "input": texts})
        response.raise_for_status()
    embeddings = response.json().get("embeddings")
    if not isinstance(embeddings, list):
        return None
    return embeddings


async def _embed_gemini(texts: list[str]) -> list[list[float]] | None:
    key = getenv("GEMINI_API_KEY", "").strip()
    model = getenv("GEMINI_EMBED_MODEL", "text-embedding-004").strip()
    if not key or not model:
        return None
    model_id = model if model.startswith("models/") else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_id}:batchEmbedContents"
    payload = {
        "requests": [
            {"model": model_id, "content": {"parts": [{"text": text or " "}]}}
            for text in texts
        ]
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, params={"key": key}, json=payload)
        response.raise_for_status()
    embeddings = response.json().get("embeddings") or []
    values = [item.get("values") for item in embeddings if isinstance(item, dict)]
    return values if all(isinstance(item, list) for item in values) else None


def build_knowledge_query(
    lifecycle: dict[str, Any] | None = None,
    trades: list[dict[str, Any]] | None = None,
    technical_context: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> str:
    lifecycle = lifecycle or {}
    technical_context = technical_context or {}
    metrics = metrics or {}
    trade = (trades or [{}])[0] if trades else {}
    tokens = ["risk", "discipline", "execution"]
    symbol = str(lifecycle.get("symbol") or trade.get("symbol") or "").strip()
    direction = str(lifecycle.get("direction") or "").strip().lower()
    if symbol:
        tokens.append(symbol)
    if direction:
        tokens.append(direction)
    try:
        fees = float(trade.get("fees") or metrics.get("fees") or 0)
        notional = float(trade.get("notional") or 0)
    except (TypeError, ValueError):
        fees, notional = 0.0, 0.0
    fee_ratio = (fees / notional * 100) if notional else 0.0
    if fee_ratio > 8 or fees:
        tokens.extend(["fee", "fees"])
    stop_loss = lifecycle.get("stop_loss") or technical_context.get("stop_loss") or trade.get("stop_loss")
    try:
        has_stop = float(stop_loss or 0) != 0
    except (TypeError, ValueError):
        has_stop = bool(stop_loss)
    tokens.extend(["stop", "stop-loss"] if not has_stop else ["stop", "risk"])
    if not has_stop:
        tokens.append("invalidation")
    trend = str(technical_context.get("trend") or "").strip().lower()
    if trend:
        tokens.append(trend)
    smc = technical_context.get("smc") or {}
    channel = str((smc.get("channel") or {}).get("direction") or "").strip()
    if channel:
        tokens.append(channel)
    if smc.get("choch") or smc.get("bos"):
        tokens.append("structure")
    tokens.extend(["position", "sizing"])
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        key = token.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(token)
    return " ".join(ordered)


def _knowledge_text(row: dict[str, Any]) -> str:
    tags = " ".join(str(tag) for tag in (row.get("tags") or []) if tag)
    return f"{row.get('title', '')} {row.get('content', '')} {tags}"


def rank_knowledge(
    rows: list[dict[str, Any]],
    query: str = "",
    tags: list[str] | None = None,
    limit: int = 5,
    query_vec: list[float] | None = None,
    row_vecs: list[list[float]] | None = None,
) -> list[dict[str, Any]]:
    text = " ".join((query or "").lower().split())
    tag_filter = {tag.lower() for tag in (tags or []) if tag}
    use_vectors = (
        query_vec is not None
        and row_vecs is not None
        and len(row_vecs) == len(rows)
        and len(query_vec) > 0
        and all(len(vector) == len(query_vec) for vector in row_vecs)
    )
    scored: list[tuple[float, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        title = str(row.get("title", "")).lower()
        body = str(row.get("content", "")).lower()
        row_tags = [str(tag).lower() for tag in row.get("tags", []) or []]
        combined = f"{title} {body} {' '.join(row_tags)}"
        score = 0.0
        if text:
            for fragment in text.split():
                if fragment in combined:
                    score += 2.0
                if fragment in title or fragment in body:
                    score += 1.5
        if tag_filter:
            score += len(tag_filter.intersection(set(row_tags))) * 3.0
        if not text and not tag_filter:
            score = 1.0
        if use_vectors:
            score += _COSINE_WEIGHT * embedding_cosine(query_vec, row_vecs[index])
        elif score <= 0:
            continue
        if score <= 0:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked: list[dict[str, Any]] = []
    for score, row in scored[:limit]:
        item = dict(row)
        item["relevance_score"] = round(score, 2)
        item["retrieval"] = "embedding" if use_vectors else "keyword"
        ranked.append(item)
    return ranked


class SupabaseStore:
    def __init__(self) -> None:
        self.url = getenv("SUPABASE_URL", "").rstrip("/")
        if self.url.endswith("/rest/v1"):
            self.url = self.url[: -len("/rest/v1")]
        self.service_role_key = getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not self.url or not self.service_role_key:
            raise StorageConfigurationError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured to persist history."
            )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }

    async def upsert_executions(self, executions: list[dict[str, Any]]) -> None:
        if not executions:
            return
        unique: dict[str, dict[str, Any]] = {}
        for execution in executions:
            row = self._storage_row(execution)
            key = str(row.get("external_id") or "")
            if key:
                unique[key] = row
        rows = list(unique.values())
        headers = {
            **self.headers,
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        # PostgREST PGRST102: null fields are dropped, so mixed SL/TP rows must be grouped by key set.
        grouped: dict[frozenset[str], list[dict[str, Any]]] = {}
        for row in rows:
            compact = {key: value for key, value in row.items() if value is not None}
            grouped.setdefault(frozenset(compact), []).append(compact)
        async with httpx.AsyncClient(timeout=40) as client:
            for batch in grouped.values():
                for offset in range(0, len(batch), 50):
                    response = await client.post(
                        f"{self.url}/rest/v1/bybit_executions?on_conflict=external_id",
                        headers=headers,
                        json=batch[offset : offset + 50],
                    )
                    response.raise_for_status()

    @staticmethod
    def _storage_row(execution: dict[str, Any]) -> dict[str, Any]:
        row = {
            "external_id": execution.get("external_id"),
            "order_id": execution.get("order_id"),
            "symbol": execution.get("symbol"),
            "category": execution.get("category") or "linear",
            "side": execution.get("side"),
            "quantity": str(execution.get("quantity") or "0"),
            "price": str(execution.get("price") or "0"),
            "realized_pnl": str(execution.get("realized_pnl") or "0"),
            "fee": str(execution.get("fee") or "0"),
            "fee_currency": execution.get("fee_currency"),
            "is_maker": bool(execution.get("is_maker")),
        }
        executed_at = execution.get("executed_at")
        if executed_at and str(executed_at).isdigit():
            row["executed_at"] = datetime.fromtimestamp(
                int(executed_at) / 1000,
                tz=timezone.utc,
            ).isoformat()
        else:
            row["executed_at"] = executed_at
        stop_loss = execution.get("stop_loss")
        take_profit = execution.get("take_profit")
        entry_price = execution.get("entry_price")
        row["entry_price"] = str(entry_price) if entry_price not in (None, "", "0", "0.0", "0.00") else None
        row["stop_loss"] = str(stop_loss) if stop_loss not in (None, "", "0", "0.0", "0.00") else None
        row["take_profit"] = str(take_profit) if take_profit not in (None, "", "0", "0.0", "0.00") else None
        stop_type = str(execution.get("stop_order_type") or "")
        row["stop_order_type"] = stop_type if stop_type and stop_type.upper() != "UNKNOWN" else None
        row["create_type"] = execution.get("create_type") or None
        return row

    async def list_executions(
        self,
        limit: int = 100,
        start_at: str | None = None,
        end_at: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            "select": "*",
            "order": "executed_at.desc",
            "limit": str(limit),
        }
        if symbol:
            params["symbol"] = f"eq.{symbol}"
        if start_at and end_at:
            params["and"] = f"(executed_at.gte.{start_at},executed_at.lte.{end_at})"
        elif start_at:
            params["executed_at"] = f"gte.{start_at}"
        elif end_at:
            params["executed_at"] = f"lte.{end_at}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.url}/rest/v1/bybit_executions",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def save_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        headers = {**self.headers, "Prefer": "return=representation"}
        payload = dict(analysis)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.url}/rest/v1/ai_analyses",
                headers=headers,
                json=payload,
            )
            if response.status_code in (200, 201):
                rows = response.json()
                return rows[0] if rows else payload

            error_text = response.text or ""
            if "technical_review" in error_text or "chart_review" in error_text or "trade_reviews" in error_text or "best_symbol" in error_text or "worst_symbol" in error_text:
                legacy_payload = {
                    "provider": payload.get("provider", "unknown"),
                    "summary": payload.get("summary", ""),
                    "best_symbol": "N/A",
                    "worst_symbol": "N/A",
                    "fee_impact": payload.get("fee_impact", ""),
                    "long_vs_short": payload.get("long_vs_short", ""),
                    "repeated_patterns": payload.get("repeated_patterns", []),
                    "risk_suggestions": payload.get("risk_suggestions", []),
                    "discipline_suggestions": payload.get("discipline_suggestions", []),
                    "created_at": payload.get("created_at") or datetime.now(timezone.utc).isoformat(),
                }
                fallback_response = await client.post(
                    f"{self.url}/rest/v1/ai_analyses",
                    headers=headers,
                    json=legacy_payload,
                )
                fallback_response.raise_for_status()
                rows = fallback_response.json()
                return rows[0] if rows else legacy_payload
            response.raise_for_status()
            rows = response.json()
            return rows[0] if rows else payload

    async def list_analyses(self, limit: int = 20) -> list[dict[str, Any]]:
        params = {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.url}/rest/v1/ai_analyses",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def save_knowledge(self, entry: dict[str, Any]) -> dict[str, Any]:
        headers = {**self.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.url}/rest/v1/trading_knowledge",
                headers=headers,
                json=entry,
            )
            if response.status_code == 404:
                fallback = dict(entry)
                fallback["id"] = f"local-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
                fallback["created_at"] = datetime.now(timezone.utc).isoformat()
                return fallback
            response.raise_for_status()
            rows = response.json()
            return rows[0] if rows else entry

    async def list_knowledge(self, limit: int = 20) -> list[dict[str, Any]]:
        params = {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.url}/rest/v1/trading_knowledge",
                headers=self.headers,
                params=params,
            )
            if response.status_code == 404:
                return self.fallback_knowledge(limit=limit)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def fallback_knowledge(query: str = "", tags: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
        return rank_knowledge(DEFAULT_TRADE_KNOWLEDGE, query=query, tags=tags, limit=limit)

    async def search_knowledge(
        self,
        query: str,
        limit: int = 5,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            rows = await self.list_knowledge(limit=50)
        except (StorageConfigurationError, httpx.HTTPError):
            return self.fallback_knowledge(query=query, tags=tags, limit=limit)
        if not rows:
            return self.fallback_knowledge(query=query, tags=tags, limit=limit)
        vectors = await embed_texts([query or " "] + [_knowledge_text(row) for row in rows])
        query_vec = None
        row_vecs = None
        if vectors and len(vectors) == len(rows) + 1:
            query_vec, *row_vecs = vectors
        ranked = rank_knowledge(
            rows,
            query=query,
            tags=tags,
            limit=limit,
            query_vec=query_vec,
            row_vecs=row_vecs,
        )
        return ranked or self.fallback_knowledge(query=query, tags=tags, limit=limit)
