from __future__ import annotations

import json
from pathlib import Path

from backend.app.ai import AIAnalysis, TradingAnalyst

CASES_PATH = Path(__file__).resolve().parent / "eval" / "cases.json"


def _cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_frozen_analysis_eval_cases() -> None:
    assert len(_cases()) >= 5
    for case in _cases():
        result = TradingAnalyst._complete_from_data(case["analysis"], case["context"])
        AIAnalysis.model_validate(result)
        review = (result.get("trade_reviews") or [{}])[0]
        expect = case["expect"]
        _assert_case(case["id"], result, review, expect)


def _joined(items: list) -> str:
    return " ".join(str(item).lower() for item in items)


def _assert_case(case_id: str, result: dict, review: dict, expect: dict) -> None:
    prefix = f"{case_id}: "
    if "rule_status" in expect:
        assert review.get("rule_status") == expect["rule_status"], prefix + str(review.get("rule_status"))
    if expect.get("forbidden_status_from_pnl"):
        assert review.get("rule_status") != "violated", prefix + "negative P&L must not force violated"
    if "max_confidence" in expect:
        assert float(review.get("confidence") or 0) <= expect["max_confidence"], prefix + "confidence"
    if "evidence_contains" in expect:
        blob = _joined(review.get("evidence") or [])
        for fragment in expect["evidence_contains"]:
            assert fragment.lower() in blob, prefix + f"evidence missing {fragment}"
    if "evidence_must_not_contain" in expect:
        blob = _joined(review.get("evidence") or [])
        for fragment in expect["evidence_must_not_contain"]:
            assert fragment.lower() not in blob, prefix + f"evidence has {fragment}"
    if "missing_evidence_contains" in expect:
        blob = _joined(review.get("missing_evidence") or [])
        for fragment in expect["missing_evidence_contains"]:
            assert fragment.lower() in blob, prefix + f"missing_evidence missing {fragment}"
    if "missing_evidence_must_not_contain" in expect:
        blob = _joined(review.get("missing_evidence") or [])
        for fragment in expect["missing_evidence_must_not_contain"]:
            assert fragment.lower() not in blob, prefix + f"missing_evidence has {fragment}"
    summary = str(result.get("summary") or "").lower()
    if "summary_startswith" in expect:
        assert summary.startswith(expect["summary_startswith"]), prefix + result.get("summary")
    if "summary_must_not_contain" in expect:
        for fragment in expect["summary_must_not_contain"]:
            assert fragment.lower() not in summary, prefix + f"summary has {fragment}"
    if "chart_review_contains" in expect:
        chart = str(result.get("chart_review") or "").lower()
        for fragment in expect["chart_review_contains"]:
            assert fragment.lower() in chart, prefix + result.get("chart_review")
    if "technical_review_contains" in expect:
        technical = str(result.get("technical_review") or "").lower()
        for fragment in expect["technical_review_contains"]:
            assert fragment.lower() in technical, prefix + result.get("technical_review")
    if "technical_review_must_not_contain" in expect:
        technical = str(result.get("technical_review") or "").lower()
        for fragment in expect["technical_review_must_not_contain"]:
            assert fragment.lower() not in technical, prefix + result.get("technical_review")
    if "fee_impact_contains" in expect:
        fee = str(result.get("fee_impact") or "").lower()
        for fragment in expect["fee_impact_contains"]:
            assert fragment.lower() in fee, prefix + result.get("fee_impact")
    if expect.get("notes_must_not_treat_pnl_as_violation"):
        notes = str(review.get("notes") or "").lower()
        assert "realized p&l was not used" in notes or "not treated as a compliance" in notes or "fee" in notes, prefix + notes
