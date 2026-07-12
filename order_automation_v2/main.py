import pandas as pd
from playwright.sync_api import sync_playwright

from config import CHROME_PROFILE_DIR, SUPPLIERS, SUPPLIER_DISTRIBUTOR_NAMES, OUTPUT_DIR, BRANCHES, DEFAULT_BRANCH
from crm import fetch_orders_for_supplier, sanitize_filename
from curated_list import build_curated_list
from retailio import open_supplier_tab
from allocate import allocate_all


def scrape_crm(context, username: str, password: str) -> None:
    page = context.pages[0] if context.pages else context.new_page()
    for supplier in SUPPLIERS:
        print(f"Processing supplier: {supplier}")
        df = fetch_orders_for_supplier(page, supplier, username, password)
        if df.empty:
            print(f"No orders found for {supplier}")
            continue
        output_path = OUTPUT_DIR / f"{sanitize_filename(supplier)}_orders.xlsx"
        df.to_excel(output_path, index=False)
        print(f"Exported {len(df)} rows to {output_path}")


def write_allocation_report(curated_list: list) -> None:
    allocation_rows = []
    unfulfilled_rows = []
    needs_review_rows = []
    for item in curated_list:
        for alloc in item["allocations"]:
            allocation_rows.append({
                "Product Name": item["product_name"],
                "Required Qty": item["required_qty"],
                "Supplier": alloc["supplier"],
                "Allocated Qty": alloc["qty"],
                "Has Scheme": alloc["has_scheme"],
                "Retailio Product": alloc["matched_product_name"],
            })
        if item["remaining_qty"] > 0:
            unfulfilled_rows.append({
                "Product Name": item["product_name"],
                "Required Qty": item["required_qty"],
                "Unfulfilled Qty": item["remaining_qty"],
            })
        for rejected in item["low_confidence_matches"]:
            needs_review_rows.append({
                "Product Name": item["product_name"],
                "Required Qty": item["required_qty"],
                "Supplier": rejected["supplier"],
                "Rejected Retailio Product": rejected["matched_product_name"],
                "Similarity": rejected["similarity"],
            })

    report_path = OUTPUT_DIR / "allocation_report.xlsx"
    with pd.ExcelWriter(report_path) as writer:
        pd.DataFrame(allocation_rows).to_excel(writer, sheet_name="Allocations", index=False)
        pd.DataFrame(unfulfilled_rows).to_excel(writer, sheet_name="Unfulfilled", index=False)
        pd.DataFrame(needs_review_rows).to_excel(writer, sheet_name="NeedsReview", index=False)

    print(f"Allocation report written to {report_path}")


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_DIR,
            channel="chrome",
            headless=False,
            chromium_sandbox=True,
            args=["--start-maximized"],
            no_viewport=True,
        )

        credentials = BRANCHES[DEFAULT_BRANCH]
        scrape_crm(context, credentials["username"], credentials["password"])

        curated_list = build_curated_list()
        print(f"Curated list has {len(curated_list)} products")

        pages = {
            supplier: open_supplier_tab(context, SUPPLIER_DISTRIBUTOR_NAMES[supplier])
            for supplier in SUPPLIERS
        }

        allocate_all(pages, curated_list)
        write_allocation_report(curated_list)

        try:
            input("Press Enter to close the browser...")
        except EOFError:
            pass
        context.close()


if __name__ == "__main__":
    main()
