"""
Agent 4 — Insight Generator
============================
Fourth and final agent in the client data onboarding pipeline.

Responsibility: Read normalized_data (per-order unified records from Agent 3),
compute executive metrics, flag risks, and call Claude to produce a
business-readable narrative report for CS leadership.

Reads from state:
    normalized_data      — dict of order_id -> unified record (from Agent 3)
    inferred_schema      — LLM-derived field groupings (from Agent 3)
    readiness_scores     — per-source AI-readiness scores (from Agent 2)

Writes to state:
    executive_metrics    — all computed metric values
    final_report         — narrative string from Claude
    risk_flags           — list of flagged metrics with explanations
    current_stage        — set to "report_complete"
"""

import json
import os
import sys

from dotenv import load_dotenv
import anthropic

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.schema import METRICS_CONTRACT

load_dotenv()

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# STEP 1 — Compute metrics
# ---------------------------------------------------------------------------

def compute_metrics(normalized_data: dict) -> dict:
    """
    Derive all executive metrics from the per-order unified records.
    Returns a metrics dict ready to pass to Claude and store in state.
    """
    records = list(normalized_data.values())
    total_orders = len(records)

    if total_orders == 0:
        return {"error": "normalized_data is empty — no orders to compute metrics from"}

    # -- Unhappy path --
    orders_with_cs_touch = sum(1 for r in records if r.get("has_cs_touch"))
    happy_path_orders = total_orders - orders_with_cs_touch
    unhappy_path_rate = round(orders_with_cs_touch / total_orders * 100, 1)
    happy_path_rate = round(100 - unhappy_path_rate, 1)

    # -- Touch counts --
    total_touches = sum(r.get("cs_touch_count", 0) for r in records)
    avg_touches_all_orders = round(total_touches / total_orders, 2)
    avg_touches_unhappy_only = (
        round(total_touches / orders_with_cs_touch, 2)
        if orders_with_cs_touch > 0 else 0
    )

    # -- Touch distribution: how many orders have 0, 1, 2, 3+ touches --
    touch_distribution = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for r in records:
        count = r.get("cs_touch_count", 0)
        if count == 0:
            touch_distribution["0"] += 1
        elif count == 1:
            touch_distribution["1"] += 1
        elif count == 2:
            touch_distribution["2"] += 1
        else:
            touch_distribution["3+"] += 1

    # -- High-priority ticket rate --
    all_priorities = []
    for r in records:
        all_priorities.extend(r.get("ticket_priorities", []))
    total_tickets = len([p for p in all_priorities if p is not None])
    high_priority_count = sum(
        1 for p in all_priorities if p and str(p).lower() in ("high", "critical")
    )
    high_priority_ticket_rate = (
        round(high_priority_count / total_tickets * 100, 1)
        if total_tickets > 0 else 0
    )

    # -- Orders by status --
    orders_by_status: dict[str, int] = {}
    for r in records:
        status = r.get("order_status") or "unknown"
        orders_by_status[status] = orders_by_status.get(status, 0) + 1

    # -- Top CS accounts (most tickets) --
    ranked = sorted(records, key=lambda r: r.get("cs_touch_count", 0), reverse=True)
    top_cs_accounts = [
        {
            "company": r.get("company_name"),
            "order_id": r.get("order_id"),
            "cs_touch_count": r.get("cs_touch_count", 0),
            "priorities": r.get("ticket_priorities", []),
        }
        for r in ranked[:3]
        if r.get("cs_touch_count", 0) > 0
    ]

    return {
        "total_orders": total_orders,
        "orders_with_cs_touch": orders_with_cs_touch,
        "happy_path_orders": happy_path_orders,
        "unhappy_path_rate_pct": unhappy_path_rate,
        "happy_path_rate_pct": happy_path_rate,
        "total_cs_touches": total_touches,
        "avg_touches_all_orders": avg_touches_all_orders,
        "avg_touches_unhappy_only": avg_touches_unhappy_only,
        "touch_distribution": touch_distribution,
        "total_tickets": total_tickets,
        "high_priority_ticket_rate_pct": high_priority_ticket_rate,
        "orders_by_status": orders_by_status,
        "top_cs_accounts": top_cs_accounts,
    }


# ---------------------------------------------------------------------------
# STEP 2 — Trending alert logic
# ---------------------------------------------------------------------------

def compute_risk_flags(metrics: dict) -> list[dict]:
    """
    Evaluate computed metrics against thresholds and return a list of flags.
    Each flag is a dict with 'metric', 'value', and 'explanation'.
    """
    flags = []

    unhappy = metrics.get("unhappy_path_rate_pct", 0)
    if unhappy > 40:
        flags.append({
            "metric": "unhappy_path_rate",
            "value": f"{unhappy}%",
            "explanation": (
                f"{unhappy}% of orders required CS intervention — above the 40% risk threshold. "
                "This suggests systemic friction in the customer journey or product delivery."
            ),
        })

    avg_touches = metrics.get("avg_touches_all_orders", 0)
    if avg_touches > 2:
        flags.append({
            "metric": "avg_touches_all_orders",
            "value": avg_touches,
            "explanation": (
                f"Customers require an average of {avg_touches} CS touches per order — "
                "above the 2.0 risk threshold. High-touch accounts drive disproportionate CS cost."
            ),
        })

    hp_rate = metrics.get("high_priority_ticket_rate_pct", 0)
    if hp_rate > 30:
        flags.append({
            "metric": "high_priority_ticket_rate",
            "value": f"{hp_rate}%",
            "explanation": (
                f"{hp_rate}% of tickets are high or critical priority — above the 30% risk threshold. "
                "A high ratio of urgent issues signals unresolved product or onboarding gaps."
            ),
        })

    return flags


# ---------------------------------------------------------------------------
# STEP 3 — Claude narrative report
# ---------------------------------------------------------------------------

def _build_report_prompt(
    metrics: dict,
    risk_flags: list[dict],
    inferred_schema: dict,
    readiness_scores: dict,
) -> str:
    """Assemble the full prompt for Claude's narrative report."""
    metrics_json = json.dumps(metrics, indent=2)
    flags_json = json.dumps(risk_flags, indent=2)
    schema_json = json.dumps(inferred_schema, indent=2)
    scores_json = json.dumps(readiness_scores, indent=2)

    low_quality_sources = [
        source for source, data in readiness_scores.items()
        if isinstance(data, dict) and data.get("score", 100) < 70
    ]
    low_quality_note = (
        f"NOTE: The following data sources scored below 70 on AI readiness and "
        f"may contain unreliable fields: {', '.join(low_quality_sources).upper()}"
        if low_quality_sources else
        "All data sources scored 70 or above on AI readiness."
    )

    return f"""You are a senior data analyst writing a board-ready report for a Customer Success leadership team.

The data pipeline has processed order records across CRM, order management, and ticketing systems.
Below are computed executive metrics, risk flags, and data quality context.

Write a structured report with exactly these sections:

1. EXECUTIVE SUMMARY
   Three sentences. Non-technical. What is the state of CS operations based on this data?

2. METRICS TABLE
   A clean plain-text table of all computed metrics with their values.

3. RISK FLAGS
   For each flag, explain in plain English why it matters to a CS leader.
   If there are no flags, state "No risk thresholds exceeded."

4. TOP 3 RECOMMENDED ACTIONS
   Concrete, prioritized actions CS leadership should take based on these findings.
   Each action should reference a specific metric or account.

5. DATA QUALITY NOTE
   Reference Agent 2 readiness scores. Flag any source scored below 70.
   Explain how low data quality affects confidence in the metrics above.

────────────────────────────────────────────────────────────
COMPUTED METRICS
────────────────────────────────────────────────────────────
{metrics_json}

────────────────────────────────────────────────────────────
RISK FLAGS
────────────────────────────────────────────────────────────
{flags_json}

────────────────────────────────────────────────────────────
AGENT 2 — DATA READINESS SCORES (per source)
────────────────────────────────────────────────────────────
{scores_json}

{low_quality_note}

────────────────────────────────────────────────────────────
INFERRED SCHEMA (field groupings across sources)
────────────────────────────────────────────────────────────
{schema_json}
"""


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------

def run_agent4(state: dict) -> dict:
    """
    Agent 4 — Insight Generator.

    Reads:   state["normalized_data"], state["inferred_schema"], state["readiness_scores"]
    Writes:  state["executive_metrics"], state["final_report"], state["risk_flags"]
             state["current_stage"] = "report_complete"
    """
    normalized_data = state.get("normalized_data", {})
    inferred_schema = state.get("inferred_schema", {})
    readiness_scores = state.get("readiness_scores", {})

    if not normalized_data:
        raise ValueError("Agent 4 requires normalized_data in state. Run Agent 3 first.")

    print("\n[Agent 4] Starting Insight Generator...")

    # ------------------------------------------------------------------
    # STEP 1 — Compute metrics
    # ------------------------------------------------------------------
    print("   Computing executive metrics...")
    metrics = compute_metrics(normalized_data)

    print(f"   Total orders: {metrics.get('total_orders')}")
    print(f"   Unhappy path rate: {metrics.get('unhappy_path_rate_pct')}%")
    print(f"   Avg CS touches (all orders): {metrics.get('avg_touches_all_orders')}")
    print(f"   High-priority ticket rate: {metrics.get('high_priority_ticket_rate_pct')}%")

    # ------------------------------------------------------------------
    # STEP 2 — Risk flags
    # ------------------------------------------------------------------
    print("   Evaluating risk thresholds...")
    risk_flags = compute_risk_flags(metrics)

    if risk_flags:
        print(f"   {len(risk_flags)} risk flag(s) raised:")
        for flag in risk_flags:
            print(f"     - {flag['metric']}: {flag['value']}")
    else:
        print("   No risk thresholds exceeded.")

    # ------------------------------------------------------------------
    # STEP 3 — Claude narrative report
    # ------------------------------------------------------------------
    print("   Sending metrics to Claude for narrative report...")
    prompt = _build_report_prompt(metrics, risk_flags, inferred_schema, readiness_scores)

    response = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    final_report = response.content[0].text.strip()
    print("   Narrative report received.")

    # ------------------------------------------------------------------
    # STEP 4 — Write to state
    # ------------------------------------------------------------------
    print("[Agent 4] Complete.")

    return {
        **state,
        "executive_metrics": metrics,
        "final_report": final_report,
        "risk_flags": risk_flags,
        "current_stage": "report_complete",
    }


# ---------------------------------------------------------------------------
# Entry point — local test (runs full pipeline up to Agent 4)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from agents.agent1_auditor import main as run_audit
    from agents.agent2_scorer import run_agent2
    from agents.agent3_normalizer import run_agent3

    print("Running full pipeline locally for Agent 4 test...")

    audit_findings = run_audit()
    state = {
        "audit_findings":       audit_findings,
        "readiness_scores":     {},
        "normalized_data":      {},
        "inferred_schema":      {},
        "normalization_summary": {},
        "executive_metrics":    {},
        "final_report":         "",
        "human_approved":       False,
        "current_stage":        "audit_complete",
    }

    state = run_agent2(state)
    state = run_agent3(state)
    state = run_agent4(state)

    print("\n" + "=" * 60)
    print("EXECUTIVE METRICS")
    print("=" * 60)
    print(json.dumps(state["executive_metrics"], indent=2))

    print("\n" + "=" * 60)
    print("RISK FLAGS")
    print("=" * 60)
    print(json.dumps(state["risk_flags"], indent=2))

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(state["final_report"])
