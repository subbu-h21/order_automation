from config import SUPPLIERS
from retailio import search_all_offers, select_and_add_to_cart
from matching import similarity, is_confident_match

# A scheme requiring you to buy more than this many units to get the free
# one(s) is only worth switching away from DRK for if you actually need a
# decent quantity - nobody stretches a 3-unit order into a 14-unit one just
# to capture a 14+1 scheme.
SCHEME_STRETCH_LIMIT = 11
MIN_QTY_TO_STRETCH = 5


def _scheme_worth_switching_for(offer: dict, required_qty: int) -> bool:
    if not offer["has_scheme"]:
        return False
    buy_qty = offer.get("scheme_buy_qty")
    if buy_qty is not None and buy_qty > SCHEME_STRETCH_LIMIT and required_qty < MIN_QTY_TO_STRETCH:
        return False
    return True


def _best_offer(product_name: str, candidates: list):
    """Scores every in-stock candidate card against product_name.

    Returns (best_confident_offer_and_score, best_overall_offer_and_score).
    The first is None if nothing cleared the confidence bar. The second is
    always populated (if there was any in-stock candidate at all) so a
    near-miss can still be logged for Needs Review.
    """
    in_stock = [c for c in candidates if c["available_qty"] > 0]
    if not in_stock:
        return None, None

    scored = [(c, similarity(product_name, c["matched_product_name"])) for c in in_stock]
    confident = [
        (c, score) for c, score in scored
        if is_confident_match(product_name, c["matched_product_name"])
    ]

    best_overall = max(scored, key=lambda pair: pair[1])
    best_confident = max(confident, key=lambda pair: pair[1]) if confident else None
    return best_confident, best_overall


def allocate_product(pages: dict, item: dict, on_progress=None) -> None:
    """Waterfall-allocates one curated-list product across supplier tabs,
    mutating item['remaining_qty'] and item['allocations'] in place."""
    exhausted = set()

    while item["remaining_qty"] > 0 and len(exhausted) < len(SUPPLIERS):
        offers = {}
        for supplier in SUPPLIERS:
            if supplier in exhausted:
                continue

            candidates = search_all_offers(pages[supplier], item["product_name"])
            best_confident, best_overall = _best_offer(item["product_name"], candidates)

            if best_confident is None:
                if best_overall is not None:
                    near_offer, near_score = best_overall
                    item["low_confidence_matches"].append({
                        "supplier": supplier,
                        "matched_product_name": near_offer["matched_product_name"],
                        "similarity": round(near_score, 2),
                    })
                    if on_progress:
                        on_progress(
                            f"{item['product_name']}: rejected low-confidence match "
                            f"\"{near_offer['matched_product_name']}\" from {supplier} "
                            f"(similarity {near_score:.2f})"
                        )
                exhausted.add(supplier)
                continue

            offer, _score = best_confident
            offers[supplier] = offer

        if not offers:
            break

        winner = next(
            (
                s for s in SUPPLIERS
                if s in offers and _scheme_worth_switching_for(offers[s], item["remaining_qty"])
            ),
            next(s for s in SUPPLIERS if s in offers),
        )

        offer = offers[winner]
        requested_qty = min(item["remaining_qty"], offer["available_qty"])

        added_qty = select_and_add_to_cart(
            pages[winner], item["product_name"], offer["index"], requested_qty, on_progress=on_progress
        )

        if added_qty > 0:
            item["allocations"].append({
                "supplier": winner,
                "qty": added_qty,
                "has_scheme": offer["has_scheme"],
                "card_text": offer["card_text"],
                "matched_product_name": offer["matched_product_name"],
            })
            item["remaining_qty"] -= added_qty

            if on_progress:
                on_progress(
                    f"{item['product_name']}: allocated {added_qty} to {winner} "
                    f"(matched \"{offer['matched_product_name']}\")"
                )
        elif on_progress:
            on_progress(
                f"{item['product_name']}: {winner}'s batch \"{offer['matched_product_name']}\" "
                f"couldn't satisfy this order's hidden quantity rules (min/max order limits) - skipped"
            )

        exhausted.add(winner)

    if item["remaining_qty"] > 0 and on_progress:
        on_progress(
            f"{item['product_name']}: {item['remaining_qty']} unit(s) unfulfilled"
        )


def allocate_all(pages: dict, curated_list: list, on_progress=None) -> None:
    for item in curated_list:
        allocate_product(pages, item, on_progress=on_progress)
