# AI Trading Journal

FastAPI backend + Vite/React SPA. The UI talks only to FastAPI (`VITE_API_URL`, default `http://localhost:8000`). Do not search `venv` or `node_modules`. Do not add a router, chart library, or frontend Supabase client unless asked. Ponytail (YAGNI ladder) is always on via `.cursor/rules/ponytail.mdc` — do not replace this file with ponytail's upstream `AGENTS.md`.

## Run

- Backend: from `backend/`, `uvicorn app.main:app --reload --port 8000` (venv + `backend/.env`).
- Frontend: from `frontend/`, `npm run dev`.
- Tests: from repo root, `pytest backend/tests`.

## Env (names only)

Backend: `BYBIT_*`, `AI_PROVIDER` (`ollama`|`gemini`), `OLLAMA_*`, `GEMINI_*`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
Frontend: `VITE_API_URL` (used). `VITE_SUPABASE_*` stubs are unused.

## Layout

| Path | Role |
|------|------|
| `backend/app/main.py` | Routes under `/api/v1`; CORS `localhost:5173`/`5174` |
| `backend/app/bybit.py` | Bybit REST (fills, PnL, positions, klines) |
| `backend/app/storage.py` | Supabase REST; knowledge fallbacks |
| `backend/app/analytics.py` | Group fills, reconstruct trades, metrics |
| `backend/app/technical.py` | EMA/ATR + SMC (`analyze_candles`) |
| `backend/app/ai.py` | Ollama/Gemini analyst + JSON normalize |
| `backend/tests/` | Import via `from backend.app...` |
| `database/schema.sql` | `bybit_executions`, `ai_analyses`, `trading_knowledge` |
| `frontend/src/App.tsx` | Entire UI (types, fetch, fallback SMC, SVG `TradeChart`) |
| `frontend/src/App.css` | Semantic classes (not Tailwind utilities) |

## Conventions

- Closing **Sell = Long**, **Buy = Short**.
- Date filters use `timezone_offset_minutes`; they apply on initial load, sync, and analyze — not on every date change.
- Chart/SMC is per selected trade (15m klines ±1 day). Backend SMC is clipped to **pre-entry**. Prefer `chart_context.smc`; frontend `computeFallbackSMC` is backup only.
- Missing config → 503; provider/API failures → 502. Unconfigured Supabase returns empty lists / fallback knowledge.
- App modules use relative imports (`from .ai import ...`).
