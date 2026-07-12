import re
import time
from playwright.sync_api import Page, BrowserContext

from config import ORDER_SITE_URL


def ensure_logged_in(context: BrowserContext, on_waiting=None, timeout_seconds: int = 600) -> None:
    """Confirms the persistent profile has a valid Retailio session, opening
    a visible tab and waiting for the user to manually complete login/OTP
    there if the session has expired. Closes the tab once logged in."""
    page = context.new_page()
    page.goto(ORDER_SITE_URL)

    login_link = page.locator('a[href="https://order.retailio.in/rio/secure-login"]')
    login_link.wait_for(state="visible", timeout=15000)
    login_link.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    deadline = time.time() + timeout_seconds
    warned = False
    while "distributor-specific-order" not in page.url:
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for manual Retailio login/OTP")
        if not warned and on_waiting:
            on_waiting()
            warned = True
        page.wait_for_timeout(2000)

    page.close()


def open_supplier_tab(context: BrowserContext, distributor_names: list) -> Page:
    page = context.new_page()
    page.goto(ORDER_SITE_URL)

    login_link = page.locator('a[href="https://order.retailio.in/rio/secure-login"]')
    login_link.wait_for(state="visible", timeout=15000)
    login_link.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    for name in distributor_names:
        row = page.locator("div.oms-list-item", has_text=name)
        checkbox = row.locator('input[type="checkbox"]')
        checkbox.check()
        page.wait_for_timeout(300)

    search_btn = page.locator("button.search-products-button")
    search_btn.wait_for(state="visible", timeout=15000)
    search_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    return page


MAX_CARDS_SCORED = 15


def _primary_cards(page: Page):
    return page.locator('[id^="product-list-"]:not([id*="non-selected"])')


def _parse_card(card_text: str) -> dict:
    has_scheme = "scheme:" in card_text.lower()
    qty_match = re.search(r"Qty\s+([\d,]+)", card_text)
    available_qty = int(qty_match.group(1).replace(",", "")) if qty_match else 0
    matched_product_name = card_text.split("\n")[0].strip()

    scheme_match = re.search(r"Scheme:\s*(\d+)\s*\+\s*(\d+)", card_text, re.IGNORECASE)
    scheme_buy_qty = int(scheme_match.group(1)) if scheme_match else None
    scheme_free_qty = int(scheme_match.group(2)) if scheme_match else None

    return {
        "available_qty": available_qty,
        "has_scheme": has_scheme,
        "scheme_buy_qty": scheme_buy_qty,
        "scheme_free_qty": scheme_free_qty,
        "card_text": card_text,
        "matched_product_name": matched_product_name,
    }


def search_all_offers(page: Page, product_name: str) -> list:
    """Search a product and read every result card's Qty/scheme (up to
    MAX_CARDS_SCORED). Returns [] if this supplier's own catalog has no
    match. Does not open the product modal or affect the cart. Each
    returned dict includes an 'index' for later selection."""
    search_input = page.get_by_placeholder("Search for a product")
    search_input.wait_for(state="visible", timeout=10000)
    search_input.fill("")
    search_input.fill(product_name)
    page.wait_for_timeout(1500)

    cards = _primary_cards(page)
    count = min(cards.count(), MAX_CARDS_SCORED)

    offers = []
    for i in range(count):
        card_text = cards.nth(i).inner_text()
        offer = _parse_card(card_text)
        offer["index"] = i
        offers.append(offer)
    return offers


def select_and_add_to_cart(page: Page, product_name: str, index: int, qty: int) -> None:
    """Re-runs the search (in case the page moved on) and adds the card at
    the given index to the cart with the given quantity."""
    search_input = page.get_by_placeholder("Search for a product")
    search_input.wait_for(state="visible", timeout=10000)
    search_input.fill("")
    search_input.fill(product_name)
    page.wait_for_timeout(1500)

    card = _primary_cards(page).nth(index)
    card.wait_for(state="visible", timeout=10000)
    card.click()

    qty_input = page.locator("#distributor-specific-order-quantity")
    qty_input.wait_for(state="visible", timeout=10000)
    qty_input.fill(str(qty))

    add_button = page.get_by_role("button", name="Add to Cart")
    add_button.click()
    page.wait_for_timeout(1000)

    close_modal(page)


def close_modal(page: Page) -> None:
    close_button = page.locator("div.close-button")
    if close_button.count() > 0:
        close_button.click()
        page.wait_for_timeout(300)
