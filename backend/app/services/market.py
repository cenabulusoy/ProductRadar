"""NL/NEW Competing Offers: official observations, conservative derived totals."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.services.bol import BolError

PAGE_SIZE = 50
MAX_PAGES = 200


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize(client, row):
    if not isinstance(row, dict):
        return None, False
    # Never infer country/condition when omitted, or include other segments.
    if row.get("countryCode") != "NL" or row.get("condition") != "NEW":
        return None, False
    valid = True
    result = {"countryCode": "NL", "condition": "NEW"}
    for key in ("offerId", "retailerId"):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            result[key] = None
            valid = False
        else:
            result[key] = client._text(value.strip())
    price = row.get("price")
    try:
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError()
        decimal = Decimal(str(price))
        if not decimal.is_finite() or decimal < 0 or decimal > 999999999 or decimal != decimal.quantize(Decimal("0.01")):
            raise ValueError()
        result["price"] = float(decimal)
    except (ValueError, InvalidOperation):
        result["price"] = None
        valid = False
    result["bestOffer"] = row.get("bestOffer") if type(row.get("bestOffer")) is bool else None
    if result["bestOffer"] is None:
        valid = False
    # Optional metadata is allowlisted; never persist the raw upstream body.
    for key in ("fulfilmentMethod", "ultimateOrderTime", "minDeliveryDate", "maxDeliveryDate"):
        result[key] = client._text(row.get(key))
    return result, valid


def measure_market(client, ean):
    started = now()
    offers, seen = [], {}
    issues, pages = [], []
    ended = False
    for page in range(1, MAX_PAGES + 1):
        try:
            body = client._get(f"products/{ean}/offers", params={
                "page": page, "country-code": "NL", "condition": "NEW", "best-offer-only": "false"})
            rows = body.get("offers")
            if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                raise BolError(502, "Bol gaf geen bruikbare lijst met aanbiedingen.")
            pages.append({"page": page, "status": "ok", "received_count": len(rows)})
        except BolError as exc:
            pages.append({"page": page, "status": "error", "error_code": exc.status})
            issues.append("Aanbiedingen niet volledig opgehaald. " + str(exc))
            break
        added = 0
        for row in rows:
            offer, valid = normalize(client, row)
            if not valid:
                issues.append("Een aanbieding mist geldige gegevens of valt buiten NL/NEW.")
            if offer is None:
                continue
            key = offer["offerId"]
            if key and key in seen:
                issues.append("Dubbele aanbieding tussen of binnen pagina's; de markt kan tijdens ophalen zijn veranderd.")
                continue
            if key:
                seen[key] = offer
            offers.append(offer)
            added += 1
        if len(rows) < PAGE_SIZE:
            ended = True
            break
        if not added:
            issues.append("Paginering levert geen nieuwe aanbiedingen op; ophalen gestopt.")
            break
    if not ended and not issues:
        issues.append("De maximale paginagrens is bereikt; de meting is onvolledig.")
    complete = ended and not issues
    status = "complete" if complete else ("partial" if offers else "unavailable")
    prices = [offer["price"] for offer in offers if offer["price"] is not None]
    known_retailers = {offer["retailerId"] for offer in offers if offer["retailerId"] is not None}
    lowest = min((offer for offer in offers if offer["price"] is not None), key=lambda o: (o["price"], o["offerId"] or ""), default=None)
    best = [offer for offer in offers if offer["bestOffer"] is True]
    return {
        "source": "bol Retailer API", "api_version": "v10", "endpoint": "products/{ean}/offers",
        "country": "NL", "condition": "NEW", "currency": "EUR",
        "started_at": started, "measured_at": now(), "status": status,
        "pagination_complete": ended, "pages": pages, "warnings": list(dict.fromkeys(issues)),
        "offers": offers,
        "derived": {
            "offer_count": len(offers) if complete else None,
            "unique_seller_count": len(known_retailers) if complete else None,
            "price_min": min(prices) if complete and prices else None,
            "price_max": max(prices) if complete and prices else None,
            "lowest_offer": lowest if complete else None,
            "best_offers": best if complete else None,
            "observed_offer_count": len(offers), "observed_unique_seller_count": len(known_retailers),
        },
        "data_kinds": {"offers": "official_bol", "counts_price_range_lowest": "derived_productradar",
                       "best_offer_flag": "official_bol"},
    }
