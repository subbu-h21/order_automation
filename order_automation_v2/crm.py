import re
import pandas as pd
from playwright.sync_api import Page

from config import CRM_URL


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:"*?<>|]+', "_", name).strip()


def login(page: Page, username: str, password: str) -> None:
    page.goto(CRM_URL)
    page.locator('input[name="user"]').fill(username)
    password_field = page.locator('input[name="pass"]')
    password_field.fill(password)
    password_field.press("Tab")

    login_button = page.locator(
        "xpath=//button[.//span[contains(text(),'Login')] and not(@disabled)]"
    )
    login_button.wait_for(state="visible", timeout=15000)
    login_button.click()


def open_saved_po(page: Page) -> None:
    reorder_button = page.locator(
        "xpath=//button[.//div[text()=' Re-Ordering Process ']]"
    )
    reorder_button.wait_for(state="visible", timeout=15000)
    reorder_button.click()

    saved_po_button = page.locator(
        "xpath=//span[@class='lnklbl' and text()='Saved PO']"
    )
    saved_po_button.wait_for(state="visible", timeout=15000)
    saved_po_button.click()


def fetch_supplier_orders(page: Page, supplier: str) -> pd.DataFrame:
    search_bar = page.locator('input[placeholder="Search Supplier"]')
    search_bar.wait_for(state="visible", timeout=15000)
    search_bar.fill("")
    search_bar.fill(supplier)

    view_details = page.locator(
        f"xpath=//tr[td[contains(normalize-space(.),'{supplier}')]]//span[text()='View Details']"
    )
    view_details.wait_for(state="visible", timeout=15000)
    view_details.click()

    table = page.locator("#itemTab")
    table.wait_for(state="visible", timeout=15000)
    rows = table.locator("tr").all()[1:]  # skip header row

    data = []
    for row in rows:
        cols = row.locator("td").all()
        if len(cols) < 9:
            continue
        data.append({
            "SL No": cols[1].inner_text().strip(),
            "Product Name": cols[2].inner_text().strip(),
            "Company": cols[3].inner_text().strip(),
            "Unit": cols[4].inner_text().strip(),
            "Suggested Qty": cols[5].inner_text().strip(),
            "Required Qty": cols[6].inner_text().strip(),
            "Offer Qty": cols[7].inner_text().strip(),
            "MRP": cols[8].inner_text().strip(),
        })

    return pd.DataFrame(data)


def fetch_orders_for_supplier(page: Page, supplier: str, username: str, password: str) -> pd.DataFrame:
    login(page, username, password)
    open_saved_po(page)
    return fetch_supplier_orders(page, supplier)
