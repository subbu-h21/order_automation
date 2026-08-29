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


# ---------------------------------------------------------------------------
# Phase A - build a reviewable proposal. Searches and scores every supplier's
# catalog for every curated item and works out a default suggested split, but
# never touches a cart. The owner reviews/edits this (dashboard) before
# anything in Phase B (commit_selections, below) is actually placed.
# ---------------------------------------------------------------------------


def gather_candidates(pages: dict, item: dict, on_progress=None) -> None:
    """Searches every supplier's tab for this item and records every
    in-stock candidate, confidence-scored, without deciding or committing
    anything. Mutates item in place: fills item['candidates'] (supplier ->
    list of scored candidate dicts) and item['low_confidence_matches']
    (suppliers with no confident match at all - same near-miss reporting
    "Needs Review" has always shown)."""
    item["candidates"] = {}
    item["low_confidence_matches"] = []

    for supplier in SUPPLIERS:
        offers = search_all_offers(pages[supplier], item["product_name"])
        in_stock = [o for o in offers if o["available_qty"] > 0]

        scored = []
        for offer in in_stock:
            score = similarity(item["product_name"], offer["matched_product_name"])
            confident = is_confident_match(item["product_name"], offer["matched_product_name"])
            scored.append({**offer, "similarity": round(score, 2), "confident": confident})

        item["candidates"][supplier] = scored

        confident_candidates = [c for c in scored if c["confident"]]
        if not confident_candidates and scored:
            near = max(scored, key=lambda c: c["similarity"])
            item["low_confidence_matches"].append({
                "supplier": supplier,
                "matched_product_name": near["matched_product_name"],
                "similarity": near["similarity"],
            })
            if on_progress:
                on_progress(
                    f"{item['product_name']}: no confident match at {supplier} "
                    f"(best near-miss \"{near['matched_product_name']}\", similarity {near['similarity']:.2f})"
                )


def _best_candidate(candidates: list):
    """Given one supplier's already-gathered, confidence-scored candidates,
    returns the single best confident one (or None). Mirrors the pipeline's
    long-standing behavior of only ever trying the top-scoring card per
    supplier - the owner can still manually pick a different candidate for
    that supplier in the review UI."""
    confident = [c for c in candidates if c["confident"]]
    if not confident:
        return None
    return max(confident, key=lambda c: c["similarity"])


def propose_allocations(item: dict) -> None:
    """Pure - no Playwright, no cart interaction. Runs the exact same
    priority + scheme-switch decision this pipeline has always used, over
    item['candidates'] (already gathered by gather_candidates), to produce a
    default suggested split. Fills item['proposed_allocations'] and
    item['remaining_qty']. Mutates item in place."""
    item["proposed_allocations"] = []
    item["remaining_qty"] = item["required_qty"]
    exhausted = set()

    while item["remaining_qty"] > 0 and len(exhausted) < len(SUPPLIERS):
        best_by_supplier = {}
        for supplier in SUPPLIERS:
            if supplier in exhausted:
                continue
            candidate = _best_candidate(item["candidates"].get(supplier, []))
            if candidate is None:
                exhausted.add(supplier)
                continue
            best_by_supplier[supplier] = candidate

        if not best_by_supplier:
            break

        winner = next(
            (
                s for s in SUPPLIERS
                if s in best_by_supplier and _scheme_worth_switching_for(best_by_supplier[s], item["remaining_qty"])
            ),
            next(s for s in SUPPLIERS if s in best_by_supplier),
        )

        candidate = best_by_supplier[winner]
        qty = min(item["remaining_qty"], candidate["available_qty"])

        item["proposed_allocations"].append({
            "supplier": winner,
            "matched_product_name": candidate["matched_product_name"],
            "qty": qty,
            "has_scheme": candidate["has_scheme"],
            "mrp": candidate.get("mrp"),
            "ptr": candidate.get("ptr"),
        })
        item["remaining_qty"] -= qty
        exhausted.add(winner)


def build_proposal(pages: dict, curated_list: list, on_progress=None) -> None:
    """Phase A entry point: for every curated item, gather every supplier's
    candidates and work out a default proposed split. Never adds anything to
    a cart."""
    for item in curated_list:
        gather_candidates(pages, item, on_progress=on_progress)
        propose_allocations(item)
        if on_progress:
            on_progress(
                f"{item['product_name']}: proposed {len(item['proposed_allocations'])} "
                f"allocation(s), {item['remaining_qty']} unit(s) unfulfilled by the default proposal"
            )


# ---------------------------------------------------------------------------
# Phase B - actually place the owner's confirmed selections. Runs in a brand
# new browser session, potentially long after Phase A built the proposal, so
# nothing from Phase A (page objects, card indexes) can be reused - each
# confirmed line is re-searched fresh and matched by product name.
# ---------------------------------------------------------------------------


def commit_selections(pages: dict, selections: list, on_progress=None) -> list:
    """Takes the owner's final confirmed selections - one entry per curated
    product, each with the specific supplier/matched-product/qty line(s)
    they approved - and adds them to the real Retailio carts. Returns data
    reshaped into the same curated_list-item structure this pipeline has
    always produced (product_name, required_qty, allocations, remaining_qty,
    low_confidence_matches), so the existing report-building code needs no
    changes to consume it."""
    results = []
    for selection in selections:
        product_name = selection["product_name"]
        required_qty = selection["required_qty"]
        committed_allocations = []

        for line in selection.get("allocations", []):
            supplier = line["supplier"]
            requested_qty = line["qty"]
            if requested_qty <= 0:
                continue

            # Never let one flaky line (a stale element, a timeout on this
            # one product) abort the rest of the confirm - lines earlier in
            # this same list may already have been added to a real cart, and
            # aborting here would leave the owner no way to safely retry
            # (re-confirming the same selections would re-add those earlier
            # lines a second time). Catch, log, and move on instead, exactly
            # like every other "couldn't do this, don't guess, don't crash"
            # spot in this pipeline.
            try:
                offers = search_all_offers(pages[supplier], product_name)
                match = next(
                    (o for o in offers if o["matched_product_name"] == line["matched_product_name"]),
                    None,
                )
                if match is None:
                    if on_progress:
                        on_progress(
                            f"{product_name}: confirmed pick \"{line['matched_product_name']}\" "
                            f"from {supplier} could not be found anymore - skipping this line"
                        )
                    continue

                added_qty = select_and_add_to_cart(
                    pages[supplier], product_name, match["index"], requested_qty, on_progress=on_progress
                )
                if added_qty > 0:
                    committed_allocations.append({
                        "supplier": supplier,
                        "qty": added_qty,
                        "has_scheme": match["has_scheme"],
                        "card_text": match["card_text"],
                        "matched_product_name": match["matched_product_name"],
                    })
                    if on_progress:
                        on_progress(f"{product_name}: added {added_qty} to {supplier}'s cart")
                elif on_progress:
                    on_progress(
                        f"{product_name}: {supplier}'s batch \"{match['matched_product_name']}\" "
                        f"couldn't satisfy this order's hidden quantity rules (min/max order limits) - skipped"
                    )
            except Exception as exc:
                if on_progress:
                    on_progress(
                        f"{product_name}: error placing this line at {supplier} "
                        f"({exc.__class__.__name__}) - skipping it rather than aborting the rest of the order"
                    )
                continue

        committed_qty = sum(a["qty"] for a in committed_allocations)
        results.append({
            "product_name": product_name,
            "required_qty": required_qty,
            "allocations": committed_allocations,
            "remaining_qty": required_qty - committed_qty,
            # Carried through from the proposal as-is (never re-derived here
            # - Phase B only executes what was already decided, it doesn't
            # re-judge match confidence) so the final report doesn't lose
            # this audit trail just because the owner has since confirmed.
            "low_confidence_matches": selection.get("low_confidence_matches", []),
        })

    return results
