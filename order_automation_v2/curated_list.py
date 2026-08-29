import re
import pandas as pd

from config import CRM_SUPPLIERS, OUTPUT_DIR
from crm import sanitize_filename


def clean_product_name(name) -> str:
    first_line = str(name).split("\n")[0]
    return re.sub(r"\d{2}/\d{2}/\d{4}", "", first_line).strip()


def build_curated_list() -> list:
    merged = {}
    for supplier in CRM_SUPPLIERS:
        path = OUTPUT_DIR / f"{sanitize_filename(supplier)}_orders.xlsx"
        if not path.exists():
            continue
        df = pd.read_excel(path)
        for _, row in df.iterrows():
            name = clean_product_name(row["Product Name"])
            if not name:
                continue
            qty = pd.to_numeric(row["Required Qty"], errors="coerce")
            if pd.isna(qty):
                continue
            qty = int(qty)
            if name not in merged or qty > merged[name]:
                merged[name] = qty

    # Just the two fields that actually matter here - allocate.py's
    # gather_candidates/propose_allocations initialize everything else
    # (candidates, proposed_allocations, remaining_qty, low_confidence_matches)
    # themselves per item, so pre-seeding them here would just be dead weight
    # that gets overwritten before anything reads it.
    return [
        {"product_name": name, "required_qty": qty}
        for name, qty in merged.items()
    ]
