"""
Agent 2 — Readiness Scorer
===========================
Second agent in the client data onboarding pipeline.

Responsibility: Read audit_findings from state (produced by Agent 1),
retrieve best-practice field definitions from the RAG engine, and use
Claude to score each data source's AI readiness on a 0–100 scale.

This agent does NOT fix anything — it only scores and prioritises.
"""

import json
import os
import sys

from dotenv import load_dotenv
import anthropic

# Allow imports from the project root regardless of where the script is run from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag_engine import query_rag

load_dotenv()


# ---------------------------------------------------------------------------
# Claude client
# ---------------------------------------------------------------------------

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(audit_findings: dict, rag_crm: str, rag_oms: str, rag_tickets: str) -> str:
    """
    Assemble the full prompt sent to Claude.

    Includes:
    - The system instruction and output format requirement
    - The raw audit findings from Agent 1 (row counts, nulls, duplicates, flags)
    - RAG-retrieved best-practice standards for each source type
    """
    audit_json = json.dumps(audit_findings, indent=2)

    return f"""You are a data readiness expert. Based on the audit findings and \
best practice standards below, score each data source 0-100 for AI readiness. \
Consider: field completeness, null rates, duplicate rates, and schema consistency. \
Return ONLY valid JSON, no other text.

The JSON must match this exact structure:
{{
  "crm": {{
    "score": <integer 0-100>,
    "gaps": [<list of specific gap descriptions>],
    "priority": <"LOW" | "MEDIUM" | "HIGH">
  }},
  "oms": {{
    "score": <integer 0-100>,
    "gaps": [<list of specific gap descriptions>],
    "priority": <"LOW" | "MEDIUM" | "HIGH">
  }},
  "tickets": {{
    "score": <integer 0-100>,
    "gaps": [<list of specific gap descriptions>],
    "priority": <"LOW" | "MEDIUM" | "HIGH">
  }}
}}

Priority guide: HIGH = score < 70, MEDIUM = 70–84, LOW = 85+

────────────────────────────────────────────────────────────
AUDIT FINDINGS (from Agent 1)
────────────────────────────────────────────────────────────
{audit_json}

────────────────────────────────────────────────────────────
BEST PRACTICE STANDARDS — CRM
────────────────────────────────────────────────────────────
{rag_crm}

────────────────────────────────────────────────────────────
BEST PRACTICE STANDARDS — ORDER MANAGEMENT
────────────────────────────────────────────────────────────
{rag_oms}

────────────────────────────────────────────────────────────
BEST PRACTICE STANDARDS — TICKETING / SUPPORT
────────────────────────────────────────────────────────────
{rag_tickets}
"""


# ---------------------------------------------------------------------------
# Agent 2 main function
# ---------------------------------------------------------------------------

def run_agent2(state: dict) -> dict:
    """
    Score each data source's AI readiness using RAG + Claude.

    Reads:   state["audit_findings"]  — dict produced by Agent 1
    Writes:  state["readiness_scores"] — scored dict with gaps and priority
             state["current_stage"]    — set to "scoring_complete"
    """

    # ------------------------------------------------------------------
    # 1. Read audit findings from state
    # ------------------------------------------------------------------
    audit_findings = state.get("audit_findings", {})
    if not audit_findings:
        raise ValueError("Agent 2 requires audit_findings in state. Run Agent 1 first.")

    print("\n[Agent 2] Starting Readiness Scorer...")

    # ------------------------------------------------------------------
    # 2. Retrieve best-practice standards via RAG (one query per source)
    # ------------------------------------------------------------------
    print("   Querying RAG for CRM best practices...")
    rag_crm = query_rag("required fields and quality rules for CRM data")

    print("   Querying RAG for OMS best practices...")
    rag_oms = query_rag("required fields and quality rules for Order Management data")

    print("   Querying RAG for ticketing best practices...")
    rag_tickets = query_rag("required fields and quality rules for ticketing support data")

    # ------------------------------------------------------------------
    # 3. Build prompt and call Claude
    # ------------------------------------------------------------------
    print("   Sending audit findings + RAG context to Claude...")
    prompt = _build_prompt(audit_findings, rag_crm, rag_oms, rag_tickets)

    response = _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()

    # ------------------------------------------------------------------
    # 4. Parse Claude's JSON response
    # ------------------------------------------------------------------
    # Claude is instructed to return only valid JSON. Strip markdown fences
    # defensively in case the model wraps the output anyway.
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    readiness_scores = json.loads(raw_text)

    # ------------------------------------------------------------------
    # 5. Print scores for each source
    # ------------------------------------------------------------------
    for source in ("crm", "oms", "tickets"):
        entry = readiness_scores.get(source, {})
        print(
            f"   [{source.upper()}] Score: {entry.get('score')} | "
            f"Priority: {entry.get('priority')} | "
            f"Gaps: {entry.get('gaps')}"
        )

    print("[Agent 2] Scoring complete.")

    # ------------------------------------------------------------------
    # 6. Store results in state and return
    # ------------------------------------------------------------------
    return {
        **state,
        "readiness_scores": readiness_scores,
        "current_stage": "scoring_complete",
    }


# ---------------------------------------------------------------------------
# Entry point — runs the full pipeline up to Agent 2 for local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from agents.agent1_auditor import main as run_audit

    # Simulate the state dict that LangGraph would pass in
    audit_findings = run_audit()
    state = {
        "audit_findings":   audit_findings,
        "readiness_scores": {},
        "normalized_data":  {},
        "final_report":     "",
        "human_approved":   False,
        "current_stage":    "audit_complete",
    }

    final_state = run_agent2(state)

    print("\n" + "=" * 60)
    print("READINESS SCORES")
    print("=" * 60)
    print(json.dumps(final_state["readiness_scores"], indent=2))
