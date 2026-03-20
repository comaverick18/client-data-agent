"""
Agent 1 — Data Auditor
======================
First agent in the client data onboarding pipeline.

Responsibility: Load all three raw data exports, inspect their structure,
and surface quality issues (nulls, duplicates, column mismatches, naming
inconsistencies across sources). Produces a single audit_findings dict
that is passed downstream to Agent 2 (Readiness Scorer).

This agent does NOT fix anything — it only observes and reports.
"""

import json
import os
import pandas as pd
from rapidfuzz import fuzz


# ---------------------------------------------------------------------------
# File paths — relative to the project root
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CRM_PATH = os.path.join(DATA_DIR, "crm_export.csv")
OMS_PATH = os.path.join(DATA_DIR, "oms_export.csv")
TICKETS_PATH = os.path.join(DATA_DIR, "tickets_export.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def audit_dataframe(df: pd.DataFrame) -> dict:
    """
    Run standard structural audit on a pandas DataFrame.

    Returns a dict with:
      - row_count: total number of rows
      - columns: ordered list of column names
      - null_counts: {column: count} for every column (0 included for clarity)
      - duplicate_count: number of fully duplicate rows
    """
    # Count null or empty-string values per column.
    # Values that are lists or other iterables (e.g. JSON arrays normalised into
    # a column) are never considered missing — only None, NaN, and "".
    def _is_missing(x) -> bool:
        if x is None:
            return True
        if isinstance(x, list):
            return False  # a list (even empty) is a present value
        try:
            return bool(pd.isna(x)) or (isinstance(x, str) and x.strip() == "")
        except (TypeError, ValueError):
            return False  # non-scalar that isna() can't handle → treat as present

    null_counts = {}
    for col in df.columns:
        null_counts[col] = int(df[col].apply(_is_missing).sum())

    # df.duplicated() requires hashable values; list-valued columns (e.g. JSON
    # arrays) are not hashable, so convert them to strings for this check only.
    df_hashable = df.apply(
        lambda col: col.map(lambda x: str(x) if isinstance(x, list) else x)
    )

    return {
        "row_count": len(df),
        "columns": list(df.columns),
        "null_counts": null_counts,
        "duplicate_count": int(df_hashable.duplicated().sum()),
    }


def audit_json_records(records: list[dict]) -> dict:
    """
    Run standard structural audit on a list of flat-ish JSON records.

    Flattens one level deep (e.g. nested dicts become dotted keys), then
    delegates to audit_dataframe for consistent output shape.
    """
    df = pd.json_normalize(records)
    return audit_dataframe(df)


def extract_company_names(df: pd.DataFrame, col: str) -> list[str]:
    """Return a sorted, deduplicated list of company name strings from a column."""
    return sorted(df[col].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# Cross-source company name comparison
# ---------------------------------------------------------------------------

def build_cross_source_flags(crm_df: pd.DataFrame, oms_df: pd.DataFrame, tickets: list[dict]) -> list[str]:
    """
    Compare company/account name values across the three sources and surface
    observations about inconsistent spelling, casing, or punctuation.

    Uses token_sort_ratio fuzzy matching (threshold ≥ 85) to determine whether
    a normalised name from one source has a likely match in another. This catches
    variants like "nexus dynamics inc." vs "nexus dynamics" that substring checks
    would miss or over-match.
    """
    flags = []

    crm_names = extract_company_names(crm_df, "company_name")
    oms_names = extract_company_names(oms_df, "customer_name")
    ticket_names = sorted({r["account_name"] for r in tickets})

    flags.append(f"CRM company_name distinct values ({len(crm_names)}): {crm_names}")
    flags.append(f"OMS customer_name distinct values ({len(oms_names)}): {oms_names}")
    flags.append(f"Tickets account_name distinct values ({len(ticket_names)}): {ticket_names}")

    # Normalise to lowercase+stripped for overlap analysis
    crm_norm  = {n.lower().strip().rstrip(".") for n in crm_names}
    oms_norm  = {n.lower().strip().rstrip(".") for n in oms_names}
    tick_norm = {n.lower().strip().rstrip(".") for n in ticket_names}

    all_norm = crm_norm | oms_norm | tick_norm

    def fuzzy_match(name: str, name_set: set) -> bool:
        """Return True if any entry in name_set scores ≥ 85 against name."""
        return any(fuzz.token_sort_ratio(name, n) >= 85 for n in name_set)

    for name in sorted(all_norm):
        in_crm  = fuzzy_match(name, crm_norm)
        in_oms  = fuzzy_match(name, oms_norm)
        in_tick = fuzzy_match(name, tick_norm)

        sources = [s for s, present in [("CRM", in_crm), ("OMS", in_oms), ("Tickets", in_tick)] if present]
        if len(sources) < 3:
            missing = [s for s, present in [("CRM", in_crm), ("OMS", in_oms), ("Tickets", in_tick)] if not present]
            flags.append(
                f"Entity '{name}' found in [{', '.join(sources)}] but NOT in [{', '.join(missing)}] "
                f"— may be absent or spelled differently"
            )

    # Flag CRM duplicates by company name (same entity, multiple rows)
    crm_dup_names = crm_df[crm_df.duplicated(subset=["company_name"], keep=False)]["company_name"].unique().tolist()
    if crm_dup_names:
        flags.append(f"CRM has multiple rows sharing the same company_name: {sorted(crm_dup_names)}")

    # Flag mixed casing within CRM company names
    crm_casing_groups: dict[str, list[str]] = {}
    for name in crm_df["company_name"].dropna():
        key = name.lower().strip().rstrip(".")
        crm_casing_groups.setdefault(key, []).append(name)
    mixed = {k: list(set(v)) for k, v in crm_casing_groups.items() if len(set(v)) > 1}
    if mixed:
        for canonical, variants in sorted(mixed.items()):
            flags.append(f"CRM casing/punctuation variants for '{canonical}': {variants}")

    return flags


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------

def main() -> dict:
    """
    Load all three data sources, audit each one, and compile cross-source
    observations into a single audit_findings dictionary.
    """

    # ------------------------------------------------------------------
    # 1. Load and audit the CRM CSV
    # ------------------------------------------------------------------
    print("Loading CRM export...")
    crm_df = pd.read_csv(CRM_PATH, dtype=str)  # dtype=str preserves empties as ""
    crm_audit = audit_dataframe(crm_df)

    # ------------------------------------------------------------------
    # 2. Load and audit the OMS CSV
    # ------------------------------------------------------------------
    print("Loading OMS export...")
    oms_df = pd.read_csv(OMS_PATH, dtype=str)
    oms_audit = audit_dataframe(oms_df)

    # ------------------------------------------------------------------
    # 3. Load and audit the Tickets JSON
    # ------------------------------------------------------------------
    print("Loading Tickets JSON...")
    with open(TICKETS_PATH, "r", encoding="utf-8") as f:
        tickets = json.load(f)
    tickets_audit = audit_json_records(tickets)

    # ------------------------------------------------------------------
    # 4. Cross-source company name analysis
    # ------------------------------------------------------------------
    print("Running cross-source name analysis...")
    cross_flags = build_cross_source_flags(crm_df, oms_df, tickets)

    # ------------------------------------------------------------------
    # 5. Assemble final findings dict
    # ------------------------------------------------------------------
    audit_findings = {
        "crm":     crm_audit,
        "oms":     oms_audit,
        "tickets": tickets_audit,
        "cross_source_flags": cross_flags,
    }

    # ------------------------------------------------------------------
    # 6. Print for verification
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("AUDIT FINDINGS")
    print("=" * 60)
    print(json.dumps(audit_findings, indent=2))

    return audit_findings


if __name__ == "__main__":
    main()
