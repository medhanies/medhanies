"""Console report and CSV/JSON exports.

The console output is structured like an investigator's morning view:
dataset summary, alert volumes by rule (with citations), the SAR-candidate
worklist, and — when ground truth is available — a validation section
showing per-scenario recall and the false-positive count.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from aml_engine.engine import DetectionResult
from aml_engine.models import Dataset, GroundTruth, Severity, SEVERITY_RANK
from aml_engine.rules import build_registry
from aml_engine.scoring import CustomerRisk, sar_worklist

WORKLIST_TOP_N = 15


def _fmt_money(value) -> str:
    return f"${value:,.2f}"


def _rule(line: str = "-", width: int = 78) -> str:
    return line * width


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------

def render_console_report(
    dataset: Dataset,
    result: DetectionResult,
    *,
    min_severity: Severity = Severity.LOW,
    show_eval: bool = True,
) -> str:
    lines: list[str] = []
    txns = dataset.transactions
    first = min(t.timestamp.date() for t in txns) if txns else None
    last = max(t.timestamp.date() for t in txns) if txns else None

    lines.append(_rule("="))
    lines.append("AML TRANSACTION FLAGGING ENGINE — DETECTION REPORT")
    lines.append(_rule("="))
    lines.append(
        f"Dataset: {len(dataset.customers)} customers, {len(dataset.accounts)} accounts, "
        f"{len(txns)} transactions ({first} to {last})"
    )
    lines.append("")

    # --- Alerts by rule ---
    min_rank = SEVERITY_RANK[min_severity]
    visible = [a for a in result.alerts if SEVERITY_RANK[a.tier] >= min_rank]
    lines.append(f"ALERTS BY RULE ({len(visible)} alerts at {min_severity}+)")
    lines.append(_rule())
    by_rule: dict[str, list] = {}
    for alert in visible:
        by_rule.setdefault(alert.rule_id, []).append(alert)
    for rule in build_registry():
        rule_alerts = by_rule.get(rule.rule_id, [])
        if not rule_alerts:
            continue
        lines.append(f"{rule.rule_id}  {rule.name}  [{len(rule_alerts)} alert(s)]")
        lines.append(f"          {rule.citation}")
    if not visible:
        lines.append("(no alerts)")
    lines.append("")

    # --- SAR-candidate worklist ---
    worklist = sar_worklist(result.customer_risks)
    lines.append(f"SAR-CANDIDATE WORKLIST (top {min(WORKLIST_TOP_N, len(worklist))} of {len(worklist)} HIGH+ customers)")
    lines.append(_rule())
    header = f"{'SCORE':>5}  {'TIER':<8}  {'CUSTOMER':<32}  {'RULES':<28}  {'FLAGGED':>14}"
    lines.append(header)
    for risk in worklist[:WORKLIST_TOP_N]:
        lines.append(
            f"{risk.score:>5}  {risk.tier:<8}  "
            f"{(risk.customer_name + ' (' + risk.customer_id + ')'):<32.32}  "
            f"{', '.join(risk.rules_fired):<28.28}  "
            f"{_fmt_money(risk.flagged_amount):>14}"
        )
    if not worklist:
        lines.append("(no customers at HIGH or above)")
    lines.append("")

    # --- Validation against planted scenarios ---
    if show_eval and dataset.ground_truth:
        lines.extend(_render_evaluation(dataset.ground_truth, result))

    return "\n".join(lines)


def _render_evaluation(ground_truth: list[GroundTruth], result: DetectionResult) -> list[str]:
    lines = ["VALIDATION AGAINST PLANTED SCENARIOS", _rule()]
    detected = 0
    flagged_txn_ids = {tid for a in result.alerts for tid in a.txn_ids}
    planted_txn_ids = {tid for gt in ground_truth for tid in gt.txn_ids}

    for gt in ground_truth:
        hits_by_rule = {
            rule_id: any(
                a.rule_id == rule_id and set(a.txn_ids) & set(gt.txn_ids)
                for a in result.alerts
            )
            for rule_id in gt.expected_rule_ids
        }
        ok = all(hits_by_rule.values())
        detected += ok
        status = "DETECTED" if ok else "MISSED"
        rule_status = ", ".join(
            f"{rid}:{'Y' if hit else 'N'}" for rid, hit in hits_by_rule.items()
        )
        lines.append(f"[{status:>8}] {gt.scenario_id} {gt.pattern_name:<20} {rule_status}")

    recall = detected / len(ground_truth) if ground_truth else 0.0
    false_positives = len(flagged_txn_ids - planted_txn_ids)
    lines.append("")
    lines.append(f"Scenario recall: {detected}/{len(ground_truth)} ({recall:.0%})")
    lines.append(
        f"Transactions flagged outside planted scenarios: {false_positives}"
    )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# File exports
# ---------------------------------------------------------------------------

def export_alerts_json(result: DetectionResult, path: Path) -> None:
    payload = [
        {
            "rule_id": a.rule_id,
            "rule_name": a.rule_name,
            "citation": a.citation,
            "severity": a.severity.value,
            "base_score": a.base_score,
            "final_score": a.final_score,
            "tier": a.tier.value,
            "customer_id": a.customer_id,
            "account_id": a.account_id,
            "txn_ids": a.txn_ids,
            "narrative": a.narrative,
        }
        for a in result.alerts
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n")


def export_flagged_transactions_csv(
    dataset: Dataset, result: DetectionResult, path: Path
) -> None:
    txn_by_id = {t.txn_id: t for t in dataset.transactions}
    rules_by_txn: dict[str, set[str]] = {}
    for alert in result.alerts:
        for tid in alert.txn_ids:
            rules_by_txn.setdefault(tid, set()).add(alert.rule_id)

    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["txn_id", "timestamp", "customer_id", "account_id", "txn_type",
             "amount", "originator_country", "beneficiary_country", "rules"]
        )
        for tid in sorted(rules_by_txn):
            txn = txn_by_id.get(tid)
            if txn is None:
                continue
            writer.writerow(
                [txn.txn_id, txn.timestamp.isoformat(), txn.customer_id,
                 txn.account_id, txn.txn_type.value, str(txn.amount),
                 txn.originator_country, txn.beneficiary_country,
                 ";".join(sorted(rules_by_txn[tid]))]
            )


def export_sar_worklist_csv(customer_risks: list[CustomerRisk], path: Path) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["customer_id", "customer_name", "score", "tier", "rules_fired",
             "alert_count", "flagged_amount", "first_activity", "last_activity",
             "narratives"]
        )
        for r in sar_worklist(customer_risks):
            writer.writerow(
                [r.customer_id, r.customer_name, r.score, r.tier.value,
                 ";".join(r.rules_fired), r.alert_count, str(r.flagged_amount),
                 r.first_activity.isoformat() if r.first_activity else "",
                 r.last_activity.isoformat() if r.last_activity else "",
                 " | ".join(r.narratives)]
            )


def export_all(dataset: Dataset, result: DetectionResult, out_dir: Path, fmt: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if fmt in ("json", "both"):
        p = out_dir / "alerts.json"
        export_alerts_json(result, p)
        written.append(p)
    if fmt in ("csv", "both"):
        p1 = out_dir / "flagged_transactions.csv"
        export_flagged_transactions_csv(dataset, result, p1)
        p2 = out_dir / "sar_worklist.csv"
        export_sar_worklist_csv(result.customer_risks, p2)
        written.extend([p1, p2])
    return written


def render_rule_catalog() -> str:
    lines = [_rule("="), "RULE CATALOG", _rule("=")]
    for rule in build_registry():
        lines.append(f"{rule.rule_id}  {rule.name}")
        lines.append(f"    Severity: {rule.severity}   Base score: {rule.base_score}")
        lines.append(f"    Citation: {rule.citation}")
        lines.append(f"    {rule.description}")
        lines.append("")
    return "\n".join(lines)
