# config/schema.py
# Defines the fields Agent 4 needs to compute executive metrics.
# This is a contract, not a normalization target — Agent 3 produces records
# shaped like this; Agent 4 reads them to compute business metrics.

METRICS_CONTRACT = {
    "order_id": None,           # primary join key (from OMS)
    "company_name": None,       # canonical name after fuzzy match
    "order_status": None,       # from OMS
    "cs_touch_count": None,     # computed: number of tickets linked to this order
    "ticket_ids": [],           # list of ticket IDs linked to this order
    "ticket_priorities": [],    # list of priority values from linked tickets
    "has_cs_touch": None,       # bool: True if cs_touch_count > 0 (unhappy path)
    "crm_health_score": None,   # from CRM if available
    "contract_value": None,     # from CRM if available
}
