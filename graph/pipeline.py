"""
graph/pipeline.py — LangGraph Orchestration
============================================
Wires the 4-agent client data onboarding pipeline into a StateGraph.

Execution order:
  START
    → run_agent1   (Data Auditor — fully implemented)
    → human_approval
    → run_agent2   (Readiness Scorer — fully implemented)
    → human_approval
    → run_agent3   (Normalizer — fully implemented)
    → human_approval
    → run_agent4   (Insight Generator — fully implemented)
  END

Each agent node receives the full pipeline state, mutates only its own
keys, and returns the updated state. Human approval nodes sit between
every agent handoff; in a later iteration these will pause execution and
surface a Streamlit approval UI.
"""

import sys
import os

# Allow imports from the project root regardless of where the script is run from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from agents.agent2_scorer import run_agent2
from agents.agent3_normalizer import run_agent3 as _run_agent3
from agents.agent4_insight_generator import run_agent4 as _run_agent4


# ---------------------------------------------------------------------------
# Shared pipeline state
# ---------------------------------------------------------------------------

class PipelineState(TypedDict):
    """
    Single state object threaded through every node in the graph.

    Keys:
        audit_findings   — output of Agent 1; raw quality report
        readiness_scores — output of Agent 2; per-source AI-readiness scores
        normalized_data  — output of Agent 3; unified, entity-resolved dataset
        final_report     — output of Agent 4; business-readable remediation report
        human_approved   — set to True by each approval gate before proceeding
        current_stage    — string label updated by each node for observability
    """
    audit_findings:       dict
    readiness_scores:     dict
    normalized_data:      dict
    inferred_schema:      dict
    normalization_summary: dict
    executive_metrics:    dict
    risk_flags:           list
    final_report:         str
    human_approved:       bool
    current_stage:        str


# ---------------------------------------------------------------------------
# Agent 1 — Data Auditor (fully implemented)
# ---------------------------------------------------------------------------

def run_agent1(state: PipelineState) -> PipelineState:
    """
    Load all three raw data exports, audit quality, and store findings.
    Delegates entirely to agents/agent1_auditor.py::main().
    """
    from agents.agent1_auditor import main as audit

    print("\n[Agent 1] Running Data Auditor...")
    findings = audit()

    return {
        **state,
        "audit_findings": findings,
        "current_stage": "audit_complete",
    }


# ---------------------------------------------------------------------------
# Human approval gates
# ---------------------------------------------------------------------------
# Each gate is a separate named node. LangGraph resolves routing by node name,
# so reusing a single node for multiple positions in the linear chain would
# create ambiguous (concurrent) edges and raise InvalidUpdateError.
# Three distinct functions keeps the graph unambiguous while sharing logic.

def _approve(state: PipelineState) -> PipelineState:
    """Shared logic: log the gate and auto-approve."""
    print(f"\n[Approval Gate] Stage '{state['current_stage']}' complete — auto-approved.")
    return {**state, "human_approved": True}

def human_approval_1(state: PipelineState) -> PipelineState:
    """Gate between Agent 1 (Auditor) and Agent 2 (Scorer)."""
    return _approve(state)

def human_approval_2(state: PipelineState) -> PipelineState:
    """Gate between Agent 2 (Scorer) and Agent 3 (Normalizer)."""
    return _approve(state)

def human_approval_3(state: PipelineState) -> PipelineState:
    """Gate between Agent 3 (Normalizer) and Agent 4 (Report Generator)."""
    return _approve(state)


# ---------------------------------------------------------------------------
# Agent 2 — Readiness Scorer (fully implemented, imported above)
# ---------------------------------------------------------------------------
# run_agent2 is imported from agents/agent2_scorer.py


# ---------------------------------------------------------------------------
# Agent 3 — Normalizer (fully implemented, imported above)
# ---------------------------------------------------------------------------

def run_agent3(state: PipelineState) -> PipelineState:
    """Delegate to agents/agent3_normalizer.py::run_agent3()."""
    return _run_agent3(state)


# ---------------------------------------------------------------------------
# Agent 4 — Insight Generator (fully implemented, imported above)
# ---------------------------------------------------------------------------

def run_agent4(state: PipelineState) -> PipelineState:
    """Delegate to agents/agent4_insight_generator.py::run_agent4()."""
    return _run_agent4(state)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """
    Assemble the StateGraph with nodes and edges.

    Three separate human_approval_N nodes are used (one per handoff) because
    LangGraph raises InvalidUpdateError if a single node has multiple outbound
    edges that could fire concurrently. Distinct nodes keep the graph strictly
    linear and unambiguous.
    """
    graph = StateGraph(PipelineState)

    # Register nodes — three distinct approval nodes avoid concurrent-edge errors
    graph.add_node("run_agent1",      run_agent1)
    graph.add_node("human_approval_1", human_approval_1)
    graph.add_node("run_agent2",      run_agent2)
    graph.add_node("human_approval_2", human_approval_2)
    graph.add_node("run_agent3",      run_agent3)
    graph.add_node("human_approval_3", human_approval_3)
    graph.add_node("run_agent4",      run_agent4)

    # Wire edges: strictly linear, no ambiguity
    graph.add_edge(START,               "run_agent1")
    graph.add_edge("run_agent1",        "human_approval_1")
    graph.add_edge("human_approval_1",  "run_agent2")
    graph.add_edge("run_agent2",        "human_approval_2")
    graph.add_edge("human_approval_2",  "run_agent3")
    graph.add_edge("run_agent3",        "human_approval_3")
    graph.add_edge("human_approval_3",  "run_agent4")
    graph.add_edge("run_agent4",        END)

    return graph


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline() -> PipelineState:
    """
    Initialise an empty state, compile the graph, and run it to completion.
    Returns the final state so callers (e.g. the Streamlit UI) can inspect
    any key they need.
    """
    # Empty initial state — each agent populates its own keys
    initial_state: PipelineState = {
        "audit_findings":       {},
        "readiness_scores":     {},
        "normalized_data":      {},
        "inferred_schema":      {},
        "normalization_summary": {},
        "executive_metrics":    {},
        "risk_flags":           [],
        "final_report":         "",
        "human_approved":       False,
        "current_stage":        "initialised",
    }

    app = build_graph().compile()
    final_state = app.invoke(initial_state)
    return final_state


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    final = run_pipeline()
    print(f"\nPipeline finished. Final stage: {final['current_stage']}")
