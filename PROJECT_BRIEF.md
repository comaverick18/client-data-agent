# PROJECT BRIEF — Client Data Onboarding Intelligence Agent

## One-Line Description
A 4-agent system that ingests messy data from multiple simulated enterprise sources, audits quality, scores AI-readiness, normalizes data across all sources by client entity, and outputs a business-readable remediation report — with human approval gates between each agent.

## Business Problem
Customer Success and Strategy & Operations teams at companies like Tempus AI operate with fragmented, untrustworthy data spread across multiple tools (CRM, order management, ticketing). There is no standardized process for onboarding new data sources, validating field definitions, or producing a trusted, queryable data layer. This prototype automates that process.

## 4-Agent Architecture

**Agent 1 — Data Auditor**
- Ingests all three data exports, maps fields, identifies gaps and inconsistencies
- Outputs: audit findings report → Human Approval Gate 1

**Agent 2 — Readiness Scorer**
- Scores each source against RAG-retrieved best practices, prioritizes problem areas
- Outputs: scored data sources with gap analysis → Human Approval Gate 2

**Agent 3 — Normalizer**
- Merges ALL sources by client entity (not just highest priority), maps fields to canonical schema
- Handles fuzzy entity matching across sources (e.g. "Acme Corp" vs "ACME")
- Accepts a list of data sources — designed to be extensible
- Outputs: normalized unified dataset with proposed field definitions → Human Approval Gate 3

**Agent 4 — Report Generator**
- Synthesizes all prior outputs into structured business-readable remediation report
- Outputs: final report with field mapping recommendations, data hygiene actions, aggregation rules, cross-source normalization guidance → User

## Human-in-the-Loop
Approval gates between each agent handoff, visible in Streamlit UI.

## Data Sources (all dummy/simulated)
- Source 1: CRM export (CSV) — simulates Salesforce, messy field names, nulls, duplicates
- Source 2: Order Management System export (CSV) — simulates internal tooling, inconsistent schema
- Source 3: Ticketing/Support System export (JSON) — simulates Zendesk or similar, unstructured fields

## RAG Components
- Best-practice data dictionary document (dummy content)
- Past client patterns document (dummy content)
- Vector DB: ChromaDB
- Embeddings: Anthropic or sentence-transformers
- Semantic search: Used by Agent 2 to match incoming fields against best-practice definitions

## Tech Stack
- LangGraph — agent orchestration
- LangChain — RAG and retrieval
- ChromaDB — vector storage
- Anthropic Claude API (primary LLM) — `claude-sonnet-4-20250514`
- Google Gemini API (backup, $300 credit available)
- Streamlit — UI
- Python 3.x, Git/GitHub (private repo), Streamlit Cloud (deployment)

## Development Environment
- Windows/PC, PowerShell 7
- Python venv at `C:\Users\comat\GitProjects\client-data-agent`
- Activate venv: `venv\Scripts\Activate.ps1`
- VS Code
- GitHub repo: `comaverick18/client-data-agent` (private)

## Architectural Decisions
- Agent 3 normalizes across ALL sources for the same client entity, not just highest priority
- Agent 3 accepts a list of sources (extensible design)
- LLM handles fuzzy entity matching between sources
- Anthropic as primary LLM, Gemini as fallback

## Current Status
- ✅ System architecture diagram complete
- ✅ Development environment configured and verified
- ✅ All dependencies installed
- ✅ Anthropic API connected and tested
- ✅ GitHub repo created, `.env` protected, pushed to private repo
- ✅ Dummy data files created (crm_export.csv, oms_export.csv, tickets_export.json)
- ✅ Agent 1 (Data Auditor) built and verified working
- ✅ LangGraph pipeline skeleton built (graph/pipeline.py) with all 4 nodes and 3 approval gates wired and running end-to-end
- ✅ RAG reference documents created in data/rag_docs/
- ✅ RAG engine built and verified (src/rag_engine.py)
- ✅ Agent 2 (Readiness Scorer) built and verified working
- ✅ Agent 2 wired into graph/pipeline.py
- ✅ All SpaceMesh references removed from project
- ✅ Deprecated LangChain imports fixed
- ✅ Absolute paths fixed in rag_engine.py
- ✅ Fuzzy match logic fixed in Agent 1 (rapidfuzz)
- ✅ API keys rotated, clean git history established
- ✅ Agent 3 (Normalizer) built and verified — per-order join, order_id primary key, fuzzy company name fallback, dynamic schema inference via LLM
- ✅ Agent 4 (Insight Generator) built and verified — exception rate 53.3%, high-priority ticket rate 50%, narrative report generated, 2 risk flags raised
- ✅ Full pipeline runs end to end (all 4 agents + 3 approval gates)
- ✅ config/schema.py updated to METRICS_CONTRACT
- ✅ PipelineState TypedDict updated with all new keys
- ✅ Fuzzy clustering fix applied — ACME/VERTEX/MERIDIAN variants now correctly collapsed via suffix stripping preprocessing

## Next Step
Build Streamlit UI

## Open Issues
- "Happy path" / "unhappy path" are informal terms — rename to industry standard in all user-facing output: STP rate (straight-through processing rate) and exception rate
- 'Orbital Sys.' and 'Orbital Systems' not collapsing in canonical map — abbreviation too short for suffix stripping to catch
- 'Pinnacle Ind.' and 'Pinnacle Industries' not collapsing — same root cause
- RAG engine loads embedding model 3x per pipeline run — optimize to single instance before deployment
- Human approval gates are auto-approve no-ops — implement real LangGraph interrupt() before final demo
- requirements.txt contains heavy packages (torch, kubernetes) — clean up before Streamlit Cloud deployment
- Pydantic V1 deprecation warning on run — harmless for now, revisit before deployment