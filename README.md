# AI Trading Journal

A FastAPI + React journal that reviews **closed Bybit trades**. An LLM writes the narrative; fills, metrics, and pre-entry market structure are computed in code and treated as source of truth.

This is an **applied LLM product**, not a trading bot and not a trained model.

## Problem

Fills and P&L do not explain whether a trade followed *your* process. The app reconstructs a trade, scores 15-minute structure **before entry**, retrieves personal rules, then asks Gemini or Ollama for a structured review with evidence and gaps.

## Pipeline

```
Bybit fills / klines  →  trade reconstruction + metrics
                      →  EMA / ATR / SMC (clipped to pre-entry)
                      →  trade-specific knowledge retrieval
                      →  LLM JSON (Ollama or Gemini)
                      →  parse + schema + deterministic merge
                      →  persist ai_analyses
```

### Computed (do not trust the model for these)

- Grouped fills, reconstructed entry/exit, holding time, fees, net vs gross P&L (`backend/app/analytics.py`)
- EMA, ATR, MFE/MAE, R:R, SL/TP hits, order blocks / FVG / BOS / CHoCH / liquidity / parallel channel, **pre-entry only** (`backend/app/technical.py`)
- Evidence lists, missing-evidence, confidence, fee-impact fallbacks, chart/technical review text (`TradingAnalyst._complete_from_data` in `backend/app/ai.py`)

### Generated (LLM, then validated)

- Summary, pattern notes, risk/discipline suggestions, optional `rule_status` / notes
- Must be valid JSON matching `AIAnalysis`. Invalid or incomplete output → HTTP 502

Retrieval is **trade-specific keyword overlap plus neural embeddings** (Gemini or Ollama embed models, cosine rerank). Keyword search is the fallback if embedding fails. This is not a vector-database index or an agent loop.

Frozen merge-eval cases live in `backend/tests/eval/cases.json` (schema, no P&L-as-violation, trend alignment). They run with `pytest backend/tests`.

## Guardrails

- Metrics in the prompt are authoritative; the model must not claim P&L or symbols are missing when they are present.
- Realized P&L is **not** a rule violation. Process evidence only (stop, fees, size, execution).
- Unverified planned stops lower **confidence** and go in `missing_evidence` instead of `violated`.
- Provider parse failures are 502; missing API config is 503.

## Failure mode (and the fix)

Models often call a long “bullish” because EMA20 is slightly above EMA50 while the pre-entry channel and last CHoCH are bearish. `_align_summary_to_trend` rewrites that lead sentence from `technical_context.trend` / `technical_summary` so the narrative cannot contradict the computed structure.

That is the product pattern: **features first, language second, post-check what the model still gets wrong.**

## Run

- Backend: from `backend/`, `uvicorn app.main:app --reload --port 8000` (venv + `backend/.env`).
- Frontend: from `frontend/`, `npm run dev`.
- Tests: from repo root, `pytest backend/tests`.

Env names only: `BYBIT_*`, `AI_PROVIDER` (`ollama`|`gemini`), `OLLAMA_*`, `GEMINI_*`, `OLLAMA_EMBED_MODEL`, `GEMINI_EMBED_MODEL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. Frontend: `VITE_API_URL`.

For local embeddings: `ollama pull nomic-embed-text` and set `OLLAMA_EMBED_MODEL`.
