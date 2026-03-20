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
- [x] System architecture diagram complete
- [x] Development environment configured and verified
- [x] All dependencies installed
- [x] Anthropic API connected and tested
- [x] GitHub repo created, `.env` protected, pushed to private repo
- [x] Dummy data files created (crm_export.csv, oms_export.csv, tickets_export.json)
- [x] Agent 1 (Data Auditor) built and verified working
- [x] LangGraph pipeline skeleton built (graph/pipeline.py) with all 4 nodes and 3 approval gates wired and running end-to-end
- [ ] RAG reference documents not yet created
- [ ] Agent 2 (Readiness Scorer) not yet built
- [ ] Agent 3 (Normalizer) not yet built
- [ ] Agent 4 (Report Generator) not yet built

## Next Step
Create RAG reference documents in `data/rag_docs/`, then build Agent 2: Readiness Scorer.

## Open Issues
- Pydantic V1 deprecation warning present on run — harmless for now, revisit before deployment
- RAG reference documents not yet created — required before Agent 2 can be built
- LOW: requirements.txt is a Full Lockfile with Dev Packages in Production Shape
  torch==2.10.0, sentence-transformers==5.3.0,
  transformers==5.3.0, scikit-learn, scipy,
  kubernetes==35.0.0, onnxruntime — all pinned and     
  committed. This is fine for reproducibility, but     
  torch alone is ~2GB and kubernetes is unrelated to   
  this project. When deploying to Streamlit Cloud, this
   will cause build failures or extreme slowness

- LOW: human_approved Flag is Meaningless  
  in Current State

  # graph/pipeline.py:86-89
  def _approve(state: PipelineState) ->       
  PipelineState:
      return {**state, "human_approved": True}
  All gates auto-approve unconditionally. The 
  flag is set but never read by any node or   
  conditional edge. The human-in-the-loop     
  design intent requires LangGraph interrupt()
   or interrupt_before — this is worth        
  implementing before agents 2-4 are built, so
   the architecture actually reflects the     
  design.