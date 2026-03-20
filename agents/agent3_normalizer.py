"""
Agent 3 — Normalizer
====================
Third agent in the client data onboarding pipeline.

Responsibility: Load all three raw data exports, infer a canonical schema
via Claude, resolve company name variants to canonical names, then build one
unified record PER ORDER (keyed by order_id). OMS is the spine — every
ORD-XXXXX becomes exactly one record. CRM and ticket data are joined in by
fuzzy company name or by order_id (for tickets).

Writes to state:
  normalized_data       — dict of order_id -> unified record
  inferred_schema       — dict of canonical_field -> [source fields]
  normalization_summary — summary stats for Agent 4
"""

import json
import os
import pandas as pd
from rapidfuzz import fuzz
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Helpers — kept exactly as original
# ---------------------------------------------------------------------------

def _find_column(df, candidates):
    """Find first matching column name (case-insensitive). Returns col name or None."""
    for col in df.columns:
        if col.lower() in [c.lower() for c in candidates]:
            return col
    return None


def _coalesce(*values):
    """Return the first non-None, non-empty value. Like SQL COALESCE."""
    for v in values:
        if v is not None and str(v).strip() not in ("", "nan", "None"):
            return v
    return None


# ---------------------------------------------------------------------------
# Fuzzy clustering — kept exactly as original
# ---------------------------------------------------------------------------

_STRIP_SUFFIXES = {
    "corp", "inc", "llc", "ltd", "co", "industries", "solutions",
    "tech", "global", "systems", "networks", "dynamics",
}

def _normalize_for_comparison(name: str) -> str:
    """
    Strip common corporate suffixes and lowercase for comparison only.
    The original name string is never modified — this is used solely
    to compute fuzzy similarity scores between name pairs.
    """
    tokens = name.lower().strip().rstrip(".").split()
    filtered = [t.rstrip(".") for t in tokens if t.rstrip(".") not in _STRIP_SUFFIXES]
    return " ".join(filtered) if filtered else name.lower().strip()


def fuzzy_cluster_names(names_by_source, threshold=82):
    """
    Cluster company name strings across all sources by fuzzy similarity.
    threshold=82 means strings must be 82%+ similar to join a cluster.
    Lower = more aggressive merging. 80-85 is a good enterprise range.

    Preprocessing: common corporate suffixes (Corp, Inc, LLC, etc.) are
    stripped and names are lowercased before scoring so that short-form
    variants like 'ACME' match 'Acme Corp' correctly. Original strings
    are preserved in the returned clusters for Claude to canonicalize.
    """
    all_names = []
    for source, name_list in names_by_source.items():
        for name in name_list:
            raw = str(name)
            all_names.append({
                "name": raw,
                "normalized": _normalize_for_comparison(raw),
                "source": source,
            })

    if not all_names:
        return []

    clusters = []
    used = set()

    for i, item in enumerate(all_names):
        if i in used:
            continue

        cluster = [item["name"]]
        used.add(i)

        for j, other in enumerate(all_names):
            if j in used or j == i:
                continue

            score = fuzz.token_sort_ratio(item["normalized"], other["normalized"])
            if score >= threshold:
                cluster.append(other["name"])
                used.add(j)

        clusters.append(cluster)

    return clusters


# ---------------------------------------------------------------------------
# Canonical name resolution — kept exactly as original
# ---------------------------------------------------------------------------

def resolve_canonical_names(clusters):
    """
    For multi-name clusters, ask Claude to pick the canonical (best) name.
    Returns a lookup dict: variant_name -> canonical_name
    """
    canonical_map = {}

    single_clusters = [c for c in clusters if len(c) == 1]
    multi_clusters = [c for c in clusters if len(c) > 1]

    for cluster in single_clusters:
        canonical_map[cluster[0]] = cluster[0]

    if not multi_clusters:
        return canonical_map

    clusters_text = "\n".join(
        [f"Cluster {i+1}: {json.dumps(cluster)}" for i, cluster in enumerate(multi_clusters)]
    )

    prompt = f"""You are resolving company name variants into canonical names for a data normalization pipeline.

For each cluster below, these name strings likely refer to the same company.
Pick the most formal, complete version as the canonical name.

Rules:
- Prefer full legal-style names over abbreviations ("Acme Corporation" over "ACME")
- Preserve capitalization of proper nouns
- If a cluster has only 1 entry, return it as-is
- Return ONLY valid JSON, no explanation

Input clusters:
{clusters_text}

Return a JSON object mapping every variant to its canonical name.
Example format:
{{
  "ACME": "Acme Corporation",
  "acme corp.": "Acme Corporation",
  "Acme Corporation": "Acme Corporation"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        llm_map = json.loads(raw)
        canonical_map.update(llm_map)
    except json.JSONDecodeError:
        print("WARNING: LLM JSON parse failed — falling back to first-item canonical names")
        for cluster in multi_clusters:
            for name in cluster:
                canonical_map[name] = cluster[0]

    return canonical_map


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------

def run_agent3(state: dict) -> dict:
    """
    Agent 3 — Normalizer.
    Merges CRM, OMS, and ticket data into one unified record per order_id.
    OMS is the spine. CRM joins by fuzzy company name. Tickets join by
    order_id (primary) or fuzzy company name (fallback for order_id: null).
    """
    print("\n[Agent 3] Normalizer starting...")

    # ------------------------------------------------------------------
    # STEP 1 — Load data from disk
    # ------------------------------------------------------------------
    base_path = os.path.join(os.path.dirname(__file__), "..", "data")

    crm_df = pd.read_csv(os.path.join(base_path, "crm_export.csv"), dtype=str)
    oms_df = pd.read_csv(os.path.join(base_path, "oms_export.csv"), dtype=str)

    with open(os.path.join(base_path, "tickets_export.json"), "r", encoding="utf-8") as f:
        tickets_data = json.load(f)

    print(f"   Loaded {len(crm_df)} CRM rows, {len(oms_df)} OMS rows, {len(tickets_data)} tickets")

    # ------------------------------------------------------------------
    # STEP 2 — Infer schema dynamically via Claude
    # ------------------------------------------------------------------
    crm_fields = list(crm_df.columns)
    oms_fields = list(oms_df.columns)
    ticket_fields = list(tickets_data[0].keys()) if tickets_data else []

    schema_prompt = f"""Here are field names from 3 enterprise data sources being merged.
CRM fields: {crm_fields}
OMS fields: {oms_fields}
Ticket fields: {ticket_fields}
Group these into clusters of synonyms. For each cluster pick a canonical field name.
Return ONLY valid JSON in this format:
{{ "canonical_field_name": ["source_field_1", "source_field_2"] }}
Only group fields that are clearly synonymous. Leave unique fields as single-item lists."""

    schema_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": schema_prompt}]
    )

    raw_schema = schema_response.content[0].text.strip()
    if raw_schema.startswith("```"):
        raw_schema = raw_schema.split("```")[1]
        if raw_schema.startswith("json"):
            raw_schema = raw_schema[4:]
    raw_schema = raw_schema.strip()

    try:
        inferred_schema = json.loads(raw_schema)
    except json.JSONDecodeError:
        print("   WARNING: Schema inference JSON parse failed — using empty schema")
        inferred_schema = {}

    print(f"   Inferred schema: {len(inferred_schema)} canonical fields")

    # ------------------------------------------------------------------
    # STEP 3 — Build canonical company name map
    # ------------------------------------------------------------------
    crm_name_col = _find_column(crm_df, ["company_name", "company", "account", "client"])
    oms_name_col = _find_column(oms_df, ["customer_name", "company_name", "company", "client"])

    names_by_source = {
        "crm": crm_df[crm_name_col].dropna().unique().tolist() if crm_name_col else [],
        "oms": oms_df[oms_name_col].dropna().unique().tolist() if oms_name_col else [],
        "tickets": list({t["account_name"] for t in tickets_data if t.get("account_name")}),
    }

    clusters = fuzzy_cluster_names(names_by_source, threshold=82)
    canonical_map = resolve_canonical_names(clusters)
    print(f"   Canonical name map: {canonical_map}")

    # ------------------------------------------------------------------
    # STEP 4 — Build per-order unified records (OMS as spine)
    # ------------------------------------------------------------------
    unified = {}  # order_id -> record

    for _, row in oms_df.iterrows():
        order_id = row.get("order_id")
        if not order_id:
            continue
        raw_customer = str(row.get(oms_name_col, "")) if oms_name_col else ""
        unified[order_id] = {
            "order_id": order_id,
            "company_name": canonical_map.get(raw_customer, raw_customer),
            "order_status": row.get("order_status"),
            "product_name": row.get("product_name"),
            "total_value": row.get("total_value"),
            "ticket_ids": [],
            "ticket_priorities": [],
            "ticket_categories": [],
            "cs_touch_count": 0,
            "has_cs_touch": False,
            "crm_health_score": None,
            "crm_contract_value": None,
            "crm_subscription_tier": None,
            "crm_client_id": None,
        }

    # Attach tickets — order_id match first, fuzzy company fallback for nulls
    for ticket in tickets_data:
        ticket_order_id = ticket.get("order_id")

        if ticket_order_id and ticket_order_id in unified:
            record = unified[ticket_order_id]
            record["ticket_ids"].append(ticket.get("ticket_id"))
            record["ticket_priorities"].append(ticket.get("priority"))
            record["ticket_categories"].append(ticket.get("category"))
            record["cs_touch_count"] += 1
            record["has_cs_touch"] = True
        elif ticket_order_id is None:
            # Fuzzy fallback: match account_name against all record company names
            ticket_company = str(ticket.get("account_name", ""))
            best_order_id = None
            best_score = 0
            for oid, record in unified.items():
                score = fuzz.token_sort_ratio(ticket_company, record["company_name"])
                if score >= 82 and score > best_score:
                    best_score = score
                    best_order_id = oid
            if best_order_id:
                record = unified[best_order_id]
                record["ticket_ids"].append(ticket.get("ticket_id"))
                record["ticket_priorities"].append(ticket.get("priority"))
                record["ticket_categories"].append(ticket.get("category"))
                record["cs_touch_count"] += 1
                record["has_cs_touch"] = True

    # Attach CRM data — fuzzy company name match
    if crm_name_col:
        for _, row in crm_df.iterrows():
            crm_company = str(row.get(crm_name_col, ""))
            crm_canonical = canonical_map.get(crm_company, crm_company)

            best_order_id = None
            best_score = 0
            for oid, record in unified.items():
                score = fuzz.token_sort_ratio(crm_canonical, record["company_name"])
                if score >= 82 and score > best_score:
                    best_score = score
                    best_order_id = oid

            if best_order_id:
                record = unified[best_order_id]
                record["crm_health_score"] = _coalesce(record["crm_health_score"], row.get("health_score"))
                record["crm_contract_value"] = _coalesce(record["crm_contract_value"], row.get("contract_value"))
                record["crm_subscription_tier"] = _coalesce(record["crm_subscription_tier"], row.get("subscription_tier"))
                record["crm_client_id"] = _coalesce(record["crm_client_id"], row.get("client_id"))

    # ------------------------------------------------------------------
    # STEP 5 — Compute summary stats
    # ------------------------------------------------------------------
    total_orders = len(unified)
    orders_with_cs_touch = sum(1 for r in unified.values() if r["has_cs_touch"])
    happy_path_orders = total_orders - orders_with_cs_touch
    total_cs_touches = sum(r["cs_touch_count"] for r in unified.values())

    normalization_summary = {
        "total_orders": total_orders,
        "orders_with_cs_touch": orders_with_cs_touch,
        "happy_path_orders": happy_path_orders,
        "total_cs_touches": total_cs_touches,
        "canonical_name_map": canonical_map,
        "sources_merged": ["crm", "oms", "tickets"],
    }

    print(f"   Total orders: {total_orders}")
    print(f"   Orders with CS touch (unhappy path): {orders_with_cs_touch}")
    print(f"   Happy path orders: {happy_path_orders}")

    # ------------------------------------------------------------------
    # STEP 6 — Write to state
    # ------------------------------------------------------------------
    state["normalized_data"] = unified
    state["inferred_schema"] = inferred_schema
    state["normalization_summary"] = normalization_summary

    print("[Agent 3] Normalization complete.")
    return state


# ---------------------------------------------------------------------------
# Entry point — local test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_state = {
        "audit_findings": {},
        "readiness_scores": {},
        "normalized_data": {},
        "final_report": "",
        "human_approved": False,
        "current_stage": "scoring_complete",
    }

    final_state = run_agent3(test_state)

    print("\n" + "=" * 60)
    print("NORMALIZATION SUMMARY")
    print("=" * 60)
    print(json.dumps(final_state["normalization_summary"], indent=2))

    print("\n" + "=" * 60)
    print("UNIFIED RECORDS (per order_id)")
    print("=" * 60)
    print(json.dumps(final_state["normalized_data"], indent=2))
