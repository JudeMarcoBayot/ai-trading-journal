import json
import re
from datetime import datetime, timezone
from os import getenv
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from .analytics import format_holding

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


class AIConfigurationError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


class AIAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    trade_reviews: list[dict[str, Any]] = Field(default_factory=list)
    chart_review: str = ""
    technical_review: str = ""
    fee_impact: str
    long_vs_short: str
    repeated_patterns: list[str]
    risk_suggestions: list[str]
    discipline_suggestions: list[str]


class TradeReview(BaseModel):
    order_id: str
    symbol: str
    rule_status: str = Field(pattern=r"^(fully compliant|partially compliant|violated|no rule applied)$")
    compliance_score: int = Field(ge=0, le=100)
    matched_rules: list[str] = Field(default_factory=list)
    notes: str
    evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class TradingAnalyst:
    VALID_RULE_STATUSES = frozenset(
        {"fully compliant", "partially compliant", "violated", "no rule applied"}
    )
    PLACEHOLDER_FEE_IMPACT = "The model did not provide a fee-impact summary."
    PLACEHOLDER_DIRECTION = "The model did not provide a directional comparison."
    PLACEHOLDER_SUMMARY = "Analysis generated from the available trading history."
    _FILL_FEE_PREAMBLE = re.compile(
        r"^The history contains \d+ fills? across \d+ grouped orders? and \d+ closed P&L events?\. "
        r"Net realized P&L after fees is [-\d.]+ USDT\.\s*",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self.provider = getenv("AI_PROVIDER", "ollama").lower()
        self.ollama_url = getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = getenv("OLLAMA_MODEL", "qwen2.5-coder:latest")
        self.gemini_key = getenv("GEMINI_API_KEY", "")
        self.gemini_model = getenv("GEMINI_MODEL", "gemini-2.0-flash")

    async def analyze(self, context: dict[str, Any]) -> AIAnalysis:
        prompt = self._prompt(context)
        if self.provider == "ollama":
            raw = await self._ollama(prompt)
        elif self.provider == "gemini":
            raw = await self._gemini(prompt)
        else:
            raise AIConfigurationError("AI_PROVIDER must be either 'ollama' or 'gemini'.")
        try:
            normalized = self._normalize_response(self._parse_json(raw))
            return AIAnalysis.model_validate(self._complete_from_data(normalized, context))
        except ValidationError as error:
            raise AIProviderError("The AI provider returned incomplete structured analysis.") from error

    async def _ollama(self, prompt: str) -> str:
        payload = {
            "model": self.ollama_model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": "You are a disciplined trading journal analyst. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise AIProviderError(f"Ollama model '{self.ollama_model}' not found. Verify OLLAMA_MODEL in .env or run 'ollama pull {self.ollama_model}'.") from error
            raise AIProviderError(f"Ollama returned HTTP error {error.response.status_code}: {error.response.text}") from error
        except httpx.TimeoutException as error:
            raise AIProviderError(f"Ollama request timed out after 180s for model '{self.ollama_model}'. The model may be taking too long to generate.") from error
        except httpx.HTTPError as error:
            raise AIProviderError(f"Ollama could not be reached at {self.ollama_url}. Check that Ollama is running.") from error
        return response.json().get("message", {}).get("content", "")

    async def _gemini(self, prompt: str) -> str:
        if not self.gemini_key:
            raise AIConfigurationError("GEMINI_API_KEY must be configured when AI_PROVIDER=gemini.")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(url, params={"key": self.gemini_key}, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise AIProviderError("Gemini could not complete the analysis request.") from error
        candidates = response.json().get("candidates", [])
        return candidates[0]["content"]["parts"][0]["text"] if candidates else ""

    @staticmethod
    def _without_fill_fee_preamble(summary: str) -> str:
        return TradingAnalyst._FILL_FEE_PREAMBLE.sub("", summary, count=1).strip()

    _SETUP_BULL = re.compile(
        r"setup was bullish|structure was bullish|trend was bullish|bullish with ema",
        re.I,
    )
    _SETUP_BEAR = re.compile(
        r"setup was bearish|structure was bearish|trend was bearish|bearish with ema",
        re.I,
    )

    @staticmethod
    def _align_summary_to_trend(summary: str, trend: str, technical_summary: str) -> str:
        trend = str(trend or "").lower()
        if trend not in {"bullish", "bearish", "mixed"}:
            return summary
        bull = bool(TradingAnalyst._SETUP_BULL.search(summary))
        bear = bool(TradingAnalyst._SETUP_BEAR.search(summary))
        contradicts = (
            (trend == "bearish" and bull)
            or (trend == "bullish" and bear)
            or (trend == "mixed" and (bull or bear) and "mixed" not in summary.lower())
        )
        if not contradicts:
            return summary
        default_lead = f"The 15-minute structure at entry was {trend}"
        lead = (technical_summary.split(". ")[0].strip() if technical_summary else default_lead)
        if not lead.endswith("."):
            lead += "."
        rest = re.sub(r"^[^.]*\b(?:bullish|bearish)\b[^.]*\.\s*", "", summary, count=1, flags=re.I).strip()
        rest = re.sub(r"(?i)the setup was (?:bullish|bearish) with ema20 above ema50,?\s*", "", rest)
        if not rest:
            return lead
        return f"{lead} {rest}".strip()

    @staticmethod
    def _chart_smc_suffix(technical_context: dict[str, Any]) -> str:
        smc = technical_context.get("smc") or {}
        channel = smc.get("channel") or {}
        choch = smc.get("choch") or []
        timing = str(smc.get("trade_timing_analysis") or "").strip()
        parts: list[str] = []
        trend = str(technical_context.get("trend") or "").strip()
        if trend:
            parts.append(f"Structure at entry was {trend}.")
        direction = str(channel.get("direction") or "").strip()
        if direction:
            parts.append(f"Parallel channel: {direction}.")
        if choch:
            last = str((choch[-1] or {}).get("type") or "").strip()
            if last:
                parts.append(f"Last pre-entry CHoCH: {last}.")
        if timing:
            parts.append(timing)
        return " ".join(parts)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]

        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise AIProviderError(f"The AI provider returned invalid structured output: {error}") from error

    @staticmethod
    def _normalize_response(data: dict[str, Any]) -> dict[str, Any]:
        def first(*keys: str, default: Any = "") -> Any:
            for key in keys:
                value = data.get(key)
                if value not in (None, ""):
                    return value
            return default

        def as_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(item) for item in value]
            if isinstance(value, str) and value:
                return [value]
            return []

        trade_reviews = first("trade_reviews", "tradeReviews", "order_reviews", default=[])
        if isinstance(trade_reviews, dict):
            trade_reviews = [trade_reviews]
        return {
            "summary": first("summary", "overview", "overall_assessment", "overallSummary", "analysis", default="Analysis generated from the available trading history."),
            "trade_reviews": [dict(item) for item in trade_reviews if isinstance(item, dict)],
            "chart_review": first("chart_review", "chartReview", "market_context", default="Chart evidence was not provided."),
            "technical_review": first("technical_review", "technicalReview", "technical_analysis", default="Technical analysis was not provided."),
            "fee_impact": first("fee_impact", "feeImpact", "fee_impact_analysis", default="The model did not provide a fee-impact summary."),
            "long_vs_short": first("long_vs_short", "longVsShort", "long_vs_short_analysis", "directional_analysis", default="The model did not provide a directional comparison."),
            "repeated_patterns": as_list(first("repeated_patterns", "repeatedPatterns", "patterns", default=[])),
            "risk_suggestions": as_list(first("risk_suggestions", "riskSuggestions", "risk_management", "risk_and_discipline", default=[])),
            "discipline_suggestions": as_list(first("discipline_suggestions", "disciplineSuggestions", "discipline", default=[])),
        }

    @staticmethod
    def _reviews_by_order_id(reviews: Any) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        if not isinstance(reviews, list):
            return indexed
        for review in reviews:
            if not isinstance(review, dict):
                continue
            order_id = str(review.get("order_id") or "").strip()
            if order_id:
                indexed[order_id] = review
        return indexed

    @staticmethod
    def _merge_string_list(base: list[str], extra: Any) -> list[str]:
        merged = list(base)
        if not isinstance(extra, list):
            return merged
        seen = {item.lower() for item in merged}
        for item in extra:
            text = str(item).strip()
            if text and text.lower() not in seen:
                merged.append(text)
                seen.add(text.lower())
        return merged

    @staticmethod
    def _is_duration_line(item: str) -> bool:
        text = item.lower()
        return "holding time" in text or "trade duration" in text or "holding duration" in text

    @staticmethod
    def _is_zero_duration(item: str) -> bool:
        text = item.lower()
        if not TradingAnalyst._is_duration_line(item):
            return False
        return "0 second" in text or "none second" in text or "0s" in text or text.strip() in {"0", "0 seconds."}

    @staticmethod
    def _process_compliance(matched_rules: list[str], fee_ratio: float) -> tuple[str, int, str]:
        if not matched_rules:
            return (
                "no rule applied",
                0,
                "No relevant personal rule matched this trade, so compliance could not be assessed from the rulebook.",
            )

        score = 100
        if fee_ratio > 8:
            score -= 30

        if score >= 80:
            return (
                "fully compliant",
                score,
                "Available fill and fee evidence is consistent with the matched rules. Planned stop placement cannot be verified from executions, and realized P&L is not treated as a compliance criterion.",
            )
        if score >= 50:
            return (
                "partially compliant",
                score,
                "Some observable process signals, such as fee burden relative to notional, are inconsistent with the matched rules. Realized P&L was not used to judge compliance.",
            )
        return (
            "violated",
            max(0, score),
            "Observable process signals are materially inconsistent with the matched rules. Realized P&L was not used to judge compliance.",
        )

    @staticmethod
    def _complete_from_data(analysis: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        metrics = context.get("metrics", {})
        orders = context.get("grouped_orders", [])
        knowledge_context = context.get("retrieved_knowledge") or []
        model_reviews = TradingAnalyst._reviews_by_order_id(analysis.get("trade_reviews"))

        rule_titles = [
            str(item.get("title", "")).lower()
            for item in knowledge_context
            if isinstance(item, dict)
        ]
        combined_knowledge = " ".join(rule_titles)

        trade_reviews: list[dict[str, Any]] = []
        for order in orders:
            order_id = str(order.get("order_id") or "unknown-order")
            symbol = str(order.get("symbol") or "UNKNOWN")
            fill_count = int(order.get("fill_count", 0) or 0)
            realized_pnl = float(order.get("realized_pnl") or 0)
            notional = float(order.get("notional") or 0)
            fees = float(order.get("fees") or 0)
            matched_rules = []
            for item in knowledge_context:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", ""))
                content = str(item.get("content", ""))
                lowered = f"{title} {content}".lower()
                if any(keyword in lowered for keyword in ["stop", "risk", "discipline", "execution", "position", "entry", "exit", "fee"]):
                    if any(token in lowered for token in [symbol.lower(), "trade", "risk", "discipline", "stop", "fee", "position"]):
                        matched_rules.append(title)
            if not matched_rules and combined_knowledge:
                matched_rules = [
                    rule_title
                    for rule_title in rule_titles[:3]
                    if any(keyword in rule_title for keyword in ["risk", "stop", "discipline", "position", "fee", "execution"])
                ]

            if not matched_rules:
                matched_rules = []

            fee_ratio = (fees / notional * 100) if notional else 0.0
            chart_context = context.get("chart_context") or {}
            evidence = [
                f"Recorded realized P&L: {realized_pnl:g} USDT.",
                f"Recorded {fill_count} fill{'s' if fill_count != 1 else ''} for this order.",
                f"Fees were {fees:g} USDT ({fee_ratio:.2f}% of notional)." if notional else f"Fees were {fees:g} USDT; notional was unavailable.",
            ]
            missing_evidence = [
                "Planned entry price and setup conditions.",
            ]
            confidence = 0.45
            lifecycle = context.get("trade_lifecycle") or {}
            technical = context.get("technical_context") or {}
            holding = format_holding(lifecycle.get("holding_seconds")) if lifecycle else None
            if lifecycle:
                evidence.extend([
                    f"Reconstructed {lifecycle.get('direction', 'unknown')} lifecycle from {lifecycle.get('entry_at')} to {lifecycle.get('exit_at')}.",
                    f"Reconstructed entry price: {lifecycle.get('entry_price')}; exit price: {lifecycle.get('exit_price')}.",
                ])
                if holding:
                    evidence.append(f"Approximate holding time: {holding}.")
                missing_evidence = [
                    "Planned entry setup and intended risk before execution.",
                ]
                confidence = 0.6
            stop_loss = lifecycle.get("stop_loss") or technical.get("stop_loss")
            take_profit = lifecycle.get("take_profit") or technical.get("take_profit")
            try:
                stop_loss_value = float(stop_loss or 0)
                take_profit_value = float(take_profit or 0)
            except (TypeError, ValueError):
                stop_loss_value = 0
                take_profit_value = 0
            if stop_loss_value:
                evidence.append(f"Bybit stop-loss was {stop_loss_value:g}.")
                if technical.get("sl_hit"):
                    evidence.append("15-minute candles traded through the stop-loss.")
            else:
                missing_evidence.append("Bybit stop-loss on the related orders.")
            if take_profit_value:
                evidence.append(f"Bybit take-profit was {take_profit_value:g}.")
                if technical.get("tp_hit"):
                    evidence.append("15-minute candles traded through the take-profit.")
            if lifecycle.get("exit_trigger"):
                evidence.append(f"The close order looks like a {lifecycle.get('exit_trigger')} fill.")
            if chart_context.get("candles"):
                evidence.append("15-minute OHLCV candles were available around the recorded execution.")
                confidence = 0.75 if lifecycle else 0.65
            else:
                missing_evidence.append("15-minute chart candles around the execution.")
            if any("stop" in item.lower() for item in missing_evidence):
                confidence = min(confidence, 0.5)

            status, score, notes = TradingAnalyst._process_compliance(matched_rules, fee_ratio)
            model_review = model_reviews.get(order_id)
            if model_review:
                model_status = str(model_review.get("rule_status") or "").strip().lower()
                if model_status in TradingAnalyst.VALID_RULE_STATUSES:
                    status = model_status
                model_notes = model_review.get("notes")
                if isinstance(model_notes, str) and model_notes.strip():
                    notes = model_notes.strip()
                model_score = model_review.get("compliance_score")
                if isinstance(model_score, (int, float)):
                    score = max(0, min(100, int(model_score)))
                model_rules = model_review.get("matched_rules")
                if isinstance(model_rules, list) and model_rules:
                    matched_rules = [str(rule) for rule in model_rules if str(rule).strip()]
                evidence = TradingAnalyst._merge_string_list(evidence, model_review.get("evidence"))
                missing_evidence = TradingAnalyst._merge_string_list(
                    missing_evidence, model_review.get("missing_evidence")
                )
            missing_evidence = [
                item for item in missing_evidence
                if "exit reason recorded by the trader" not in item.lower()
                and not TradingAnalyst._is_zero_duration(item)
                and not (holding and TradingAnalyst._is_duration_line(item))
            ]
            evidence = [item for item in evidence if not TradingAnalyst._is_zero_duration(item)]
            if holding:
                evidence = [item for item in evidence if not TradingAnalyst._is_duration_line(item)]
                evidence.append(f"Approximate holding time: {holding}.")
            trade_reviews.append({
                "order_id": order_id,
                "symbol": symbol,
                "rule_status": status,
                "compliance_score": max(0, min(100, score)),
                "matched_rules": matched_rules[:3],
                "notes": notes,
                "evidence": evidence,
                "missing_evidence": missing_evidence,
                "confidence": confidence,
            })

        analysis["trade_reviews"] = trade_reviews[:10]
        chart_context = context.get("chart_context") or {}
        technical_context = context.get("technical_context") or {}
        if technical_context.get("technical_summary"):
            analysis["technical_review"] = technical_context["technical_summary"]
        elif not analysis.get("technical_review"):
            analysis["technical_review"] = "Technical analysis was unavailable for this trade."
        candles = chart_context.get("candles") or []
        if candles and orders:
            trade = orders[0]
            lifecycle = context.get("trade_lifecycle") or {}
            close_price = float(lifecycle.get("exit_price") or trade.get("average_price") or 0)
            executed_at = str(trade.get("executed_at") or "0")
            trade_timestamp = (
                float(executed_at)
                if executed_at.isdigit()
                else datetime.fromisoformat(executed_at.replace("Z", "+00:00")).timestamp() * 1000
            )
            nearest_candle = min(
                candles,
                key=lambda candle: abs(float(candle.get("timestamp") or 0) - trade_timestamp),
            )
            candle_open = float(nearest_candle.get("open") or 0)
            candle_high = float(nearest_candle.get("high") or 0)
            candle_low = float(nearest_candle.get("low") or 0)
            candle_close = float(nearest_candle.get("close") or 0)
            direction = str(lifecycle.get("direction") or ("Long" if trade.get("side") == "Sell" else "Short" if trade.get("side") == "Buy" else "Mixed"))
            lifecycle_text = (
                f"The reconstructed lifecycle ran from {lifecycle.get('entry_at')} at {lifecycle.get('entry_price')} "
                f"to {lifecycle.get('exit_at')} at {lifecycle.get('exit_price')}. "
                if lifecycle
                else "The original entry is not present in this order record. "
            )
            try:
                stop_loss = float(lifecycle.get("stop_loss") or technical_context.get("stop_loss") or 0)
                take_profit = float(lifecycle.get("take_profit") or technical_context.get("take_profit") or 0)
            except (TypeError, ValueError):
                stop_loss = 0
                take_profit = 0
            if stop_loss:
                tpsl_text = f"Bybit stop-loss was {stop_loss:g}"
                tpsl_text += " and 15-minute candles traded through it." if technical_context.get("sl_hit") else "."
                if take_profit:
                    tpsl_text += f" Take-profit was {take_profit:g}"
                    tpsl_text += " and 15-minute candles traded through it." if technical_context.get("tp_hit") else "."
                if lifecycle.get("exit_trigger"):
                    tpsl_text += f" The close looks like a {lifecycle.get('exit_trigger')} fill."
            else:
                tpsl_text = "No Bybit stop-loss was found on the related orders."
            analysis["chart_review"] = (
                f"15-minute candle near the recorded {direction} close ranged from {candle_low:g} to {candle_high:g} "
                f"and closed at {candle_close:g} (open {candle_open:g}). The recorded close price was {close_price:g}. "
                f"{lifecycle_text}{tpsl_text}"
            )
        elif not candles:
            analysis["chart_review"] = "Chart evidence was unavailable, so this review uses fills and saved rules only."
        smc_suffix = TradingAnalyst._chart_smc_suffix(technical_context)
        if smc_suffix:
            analysis["chart_review"] = f"{str(analysis.get('chart_review') or '').rstrip()} {smc_suffix}".strip()

        summary = str(analysis.get("summary") or "")
        analysis["summary"] = TradingAnalyst._without_fill_fee_preamble(summary) or TradingAnalyst.PLACEHOLDER_SUMMARY
        analysis["summary"] = TradingAnalyst._align_summary_to_trend(
            analysis["summary"],
            str(technical_context.get("trend") or ""),
            str(technical_context.get("technical_summary") or ""),
        )
        fee_impact = str(analysis.get("fee_impact") or "")
        if fee_impact in ("", TradingAnalyst.PLACEHOLDER_FEE_IMPACT):
            analysis["fee_impact"] = (
                f"Fees total {metrics.get('fees', '0')} USDT against gross realized P&L of "
                f"{metrics.get('gross_pnl', '0')} USDT. Net P&L after fees is {metrics.get('net_pnl', '0')} USDT."
            )
        direction = str(analysis.get("long_vs_short") or "")
        if direction in ("", TradingAnalyst.PLACEHOLDER_DIRECTION):
            analysis["long_vs_short"] = (
                "Execution history alone cannot reliably distinguish long versus short direction; "
                "position-level data is needed for this comparison."
            )
        if not analysis["repeated_patterns"]:
            multi_fill_orders = sum(1 for order in orders if int(order.get("fill_count", 0)) > 1)
            analysis["repeated_patterns"] = [
                f"{multi_fill_orders} grouped orders contained multiple partial fills." if multi_fill_orders else "No repeated partial-fill pattern was detected in the available orders.",
                f"The history contains {metrics.get('fill_count', 0)} fills across {metrics.get('trade_count', 0)} grouped orders.",
            ]
        if not analysis["risk_suggestions"]:
            analysis["risk_suggestions"] = [
                "Review position size and stop placement before the next entry.",
                "Treat realized P&L and open exposure as separate measures when reviewing performance.",
            ]
        if not analysis["discipline_suggestions"]:
            analysis["discipline_suggestions"] = [
                "Record the setup, invalidation level, and exit reason for every position.",
                "Review fees alongside gross P&L before judging a strategy or symbol.",
            ]
        return analysis

    @staticmethod
    def _prompt(context: dict[str, Any]) -> str:
        knowledge_context = context.get("retrieved_knowledge") or []
        knowledge_block = ""
        if knowledge_context:
            knowledge_block = "\n\nRelevant personal knowledge context:\n" + json.dumps(knowledge_context, default=str)

        return f"""Analyze this trading journal history. Do not promise profits or give certainty. Identify patterns supported by the data and distinguish closed P&L from order activity. The metrics object is authoritative; do not claim that P&L, fees, timestamps, or symbols are missing when those fields contain values.

Use the personal trading knowledge context as a grounding layer when it is relevant. Prefer it for risk rules, execution discipline, and recurring decision frameworks, but do not let it override objective data from the metrics and trade history. Do not treat realized P&L as a rule violation. Judge rule_status from process evidence such as setup, stop, size, fees, and execution. If a planned stop cannot be verified from stored Bybit stop-loss / take-profit on the fills, lower confidence and list it in missing_evidence instead of marking the trade violated. Do not list trader exit reasons; that data is not available. Use trade_lifecycle.stop_loss, take_profit, and exit_trigger when present. If trade_lifecycle.holding_seconds is missing or 0, omit duration from evidence and missing_evidence; never write "0 seconds".

Return JSON with exactly these snake_case keys and no others:
summary (string), trade_reviews (array of objects), chart_review (string), technical_review (string), fee_impact (string), long_vs_short (string), repeated_patterns (array of strings), risk_suggestions (array of strings), discipline_suggestions (array of strings).

Each trade review object should include:
- order_id (string)
- symbol (string)
- rule_status (string, one of 'fully compliant', 'partially compliant', 'violated', or 'no rule applied')
- compliance_score (integer from 0 to 100)
- matched_rules (array of strings)
- notes (string)
- evidence (array of strings containing exact facts used for the decision)
- missing_evidence (array of strings containing facts that were unavailable)
- confidence (number from 0 to 1)

Trading data:
{json.dumps(context, default=str)}{knowledge_block}

Review only the selected trade in this context. Use exact values from its grouped order and technical_context, not generic trading advice. technical_context.trend is the structure at entry; do not call the setup bullish because EMA20 is slightly above EMA50. A descending channel, premium-zone long, or bearish CHoCH/BOS is not a bullish Smart Money long. Use technical_context.technical_summary as the structure narrative. Explain how trend, volatility, support, resistance, pre-entry movement, favorable/adverse excursion, Smart Money strategy elements (Bullish/Bearish Order Blocks, FVGs, BOS, CHoCH, Liquidity Pools), and the Parallel Channel affect the trade. Analyze the exact timing of when the trade happened relative to the channel boundaries, Order Blocks, and market structure shifts. When chart_context contains candles, compare the recorded trade timing and prices with the candle highs, lows, closes, trend, and invalidation area. Do not claim that a stop was hit unless the data supports it. Explain when chart evidence is missing. Check whether the trade aligns with the matched personal rules. Return concrete evidence and missing_evidence for every conclusion. Do not rely on overall symbol rankings or account-wide summaries. If the data is insufficient for a conclusion, say so explicitly."""


def analysis_record(analysis: AIAnalysis, provider: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "summary": analysis.summary,
        "trade_reviews": analysis.trade_reviews,
        "chart_review": analysis.chart_review,
        "technical_review": analysis.technical_review,
        "fee_impact": analysis.fee_impact,
        "long_vs_short": analysis.long_vs_short,
        "repeated_patterns": analysis.repeated_patterns,
        "risk_suggestions": analysis.risk_suggestions,
        "discipline_suggestions": analysis.discipline_suggestions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
