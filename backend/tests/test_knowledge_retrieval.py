import asyncio

from backend.app.storage import (
    DEFAULT_TRADE_KNOWLEDGE,
    build_knowledge_query,
    embed_texts,
    embedding_cosine,
    rank_knowledge,
)


def test_knowledge_query_includes_trade_facts() -> None:
    query = build_knowledge_query(
        lifecycle={
            "symbol": "ETHUSDT",
            "direction": "Long",
            "stop_loss": None,
        },
        trades=[{"symbol": "ETHUSDT", "fees": 12, "notional": 100}],
        technical_context={
            "trend": "bearish",
            "smc": {"channel": {"direction": "descending"}, "choch": [{"type": "Bearish CHoCH"}]},
        },
    )
    lowered = query.lower()
    assert "ethusdt" in lowered
    assert "long" in lowered
    assert "bearish" in lowered
    assert "descending" in lowered
    assert "invalidation" in lowered
    assert "fee" in lowered


def test_knowledge_query_skips_invalidation_when_stop_exists() -> None:
    query = build_knowledge_query(
        lifecycle={"stop_loss": "2340"},
        trades=[{"fees": 0, "notional": 500}],
    )
    assert "invalidation" not in query.lower()


def test_fee_query_ranks_fee_rule_first() -> None:
    ranked = rank_knowledge(DEFAULT_TRADE_KNOWLEDGE, query="fees fee drag net pnl", limit=4)
    assert ranked[0]["id"] == "default-2"
    assert ranked[0]["retrieval"] == "keyword"


def test_stop_query_ranks_risk_rule_first() -> None:
    ranked = rank_knowledge(DEFAULT_TRADE_KNOWLEDGE, query="stop invalidation stop-loss", limit=4)
    assert ranked[0]["id"] == "default-1"


def test_paraphrase_vectors_rank_fee_rule_without_fee_tokens() -> None:
    query_vec = [1.0, 0.0]
    row_vecs = [[0.0, 1.0] for _ in DEFAULT_TRADE_KNOWLEDGE]
    fee_index = next(i for i, row in enumerate(DEFAULT_TRADE_KNOWLEDGE) if row["id"] == "default-2")
    row_vecs[fee_index] = [1.0, 0.0]
    ranked = rank_knowledge(
        DEFAULT_TRADE_KNOWLEDGE,
        query="broker costs versus winnings",
        limit=4,
        query_vec=query_vec,
        row_vecs=row_vecs,
    )
    assert ranked[0]["id"] == "default-2"


def test_keyword_only_when_vectors_missing() -> None:
    ranked = rank_knowledge(DEFAULT_TRADE_KNOWLEDGE, query="broker costs versus winnings", limit=4)
    assert ranked == []


def test_embedding_cosine_is_1_for_aligned_unit_vectors() -> None:
    assert abs(embedding_cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9


def test_embed_texts_returns_none_for_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "unknown")
    assert asyncio.run(embed_texts(["stop loss"])) is None


def test_embed_texts_returns_none_when_ollama_model_missing(monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "")
    assert asyncio.run(embed_texts(["stop loss"])) is None
