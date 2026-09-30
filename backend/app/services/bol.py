"""Read-only bol v10 adapter. Never return or log upstream bodies or credentials."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import os
import re
import threading
import time

import httpx


@dataclass(frozen=True)
class BolSettings:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("BOL_CLIENT_ID", "").strip(),
                   os.environ.get("BOL_CLIENT_SECRET", "").strip())


class BolError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def validate_ean(ean: str) -> None:
    if not re.fullmatch(r"[0-9]{13}", ean):
        raise BolError(400, "Voer een EAN van precies 13 cijfers in.")
    checksum = (10 - sum(int(n) * (1 if i % 2 == 0 else 3)
                         for i, n in enumerate(ean[:12])) % 10) % 10
    if checksum != int(ean[-1]):
        raise BolError(400, "Het controlecijfer van de EAN klopt niet.")


class BolClient:
    def __init__(self, settings: BolSettings, transport=None, clock=time.monotonic):
        self.settings = settings
        self.transport = transport
        self.clock = clock
        self._token = ""
        self._expires = 0.0
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def _request(self, method, url, **kwargs):
        if self.clock() < self._blocked_until:
            raise BolError(429, "Bol vraagt om even te wachten. Probeer het later opnieuw.")
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False,
                              transport=self.transport) as client:
                return client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise BolError(504, "Bol reageert niet op tijd. Probeer het later opnieuw.") from None
        except httpx.RequestError:
            raise BolError(502, "Verbinding met bol is niet beschikbaar.") from None

    def _check(self, response, authentication=False):
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", "60"))
                if not math.isfinite(delay):
                    delay = 60
            except ValueError:
                delay = 60
            self._blocked_until = self.clock() + max(1, min(delay, 3600))
            raise BolError(429, "Bol vraagt om even te wachten. Probeer het later opnieuw.")
        if response.status_code in (401, 403):
            raise BolError(503, "Bol-toegang geweigerd. Controleer de lokale configuratie en accountrechten.")
        if response.status_code == 404 and not authentication:
            raise BolError(404, "Deze EAN is niet gevonden bij bol.")
        if response.status_code != 200:
            raise BolError(502, "Bol kon de aanvraag niet verwerken. Probeer het later opnieuw.")

    @staticmethod
    def _json(response):
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise BolError(502, "Bol gaf een onverwacht antwoord.") from None

    def _access_token(self):
        with self._lock:
            if self._token and self.clock() < self._expires:
                return self._token
            if not self.settings.client_id or not self.settings.client_secret:
                raise BolError(503, "Bol is nog niet ingesteld. Vul de lokale backend-configuratie in.")
            response = self._request(
                "POST", "https://login.bol.com/token",
                auth=httpx.BasicAuth(self.settings.client_id, self.settings.client_secret),
                headers={"Accept": "application/json"},
                data={"grant_type": "client_credentials"},
            )
            self._check(response, authentication=True)
            body = self._json(response)
            token, ttl = body.get("access_token"), body.get("expires_in")
            if (not isinstance(token, str) or not token or "\n" in token or "\r" in token
                    or isinstance(ttl, bool) or not isinstance(ttl, (int, float))
                    or not math.isfinite(ttl) or ttl <= 0
                    or not isinstance(body.get("token_type", "Bearer"), str)
                    or body.get("token_type", "Bearer").lower() != "bearer"):
                raise BolError(502, "Bol gaf een onverwacht authenticatieantwoord.")
            self._token = token
            self._expires = self.clock() + ttl - min(30, ttl / 10)
            return token

    def _get(self, path, params=None):
        for attempt in range(2):
            token = self._access_token()
            response = self._request("GET", "https://api.bol.com/retailer/" + path, params=params,
                                     headers={"Authorization": "Bearer " + token,
                                              "Accept": "application/vnd.retailer.v10+json",
                                              "Accept-Language": "nl"})
            if response.status_code == 401 and attempt == 0:
                with self._lock:
                    if self._token == token:
                        self._token, self._expires = "", 0
                continue
            self._check(response)
            return self._json(response)

    def _text(self, value):
        if not isinstance(value, str):
            return None
        # Defence in depth against accidentally echoed secrets in upstream content.
        for secret in (self.settings.client_id, self.settings.client_secret, self._token):
            if secret:
                value = value.replace(secret, "[afgeschermd]")
        return value[:500]

    def preview(self, ean):
        validate_ean(ean)
        # The single-EAN v10 endpoint returns the product at the root.
        product = self._get("content/catalog-products/" + ean)
        attributes = product.get("attributes")
        if not isinstance(attributes, list):
            raise BolError(502, "Bol gaf geen bruikbare catalogusgegevens.")

        def attribute(identifier):
            for item in attributes:
                if isinstance(item, dict) and item.get("id") == identifier:
                    values = item.get("values", [])
                    if isinstance(values, list) and values and isinstance(values[0], dict):
                        return self._text(values[0].get("value"))
            return None

        warnings, ratings = [], None
        ratings_status = {"status": "ok", "error_code": None}
        try:
            body = self._get("products/" + ean + "/ratings")
            distribution = body.get("ratings")
            if not isinstance(distribution, list):
                raise BolError(502, "Bol gaf geen bruikbare beoordelingen.")
            buckets = {}
            for item in distribution:
                if not isinstance(item, dict):
                    raise BolError(502, "Bol gaf geen bruikbare beoordelingen.")
                star, count = item.get("rating"), item.get("count")
                if type(star) is not int or star not in range(1, 6) or type(count) is not int or count < 0 or star in buckets:
                    raise BolError(502, "Bol gaf geen bruikbare beoordelingen.")
                buckets[star] = count
            total = sum(buckets.values())
            ratings = {"distribution": [{"rating": star, "count": count} for star, count in sorted(buckets.items())],
                       "count": total,
                       "average": round(sum(star * count for star, count in buckets.items()) / total, 2) if total else None}
        except BolError as exc:
            ratings_status = {"status": "unavailable", "error_code": exc.status}
            warnings.append("Beoordelingen niet beschikbaar. " + str(exc))
        from app.services.market import measure_market
        market = measure_market(self, ean)
        gpc = product.get("gpc")
        enrichment = product.get("enrichment")
        return {"ean": ean, "source": "bol Retailer API v10", "language": "nl",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "catalog": {"title": attribute("Title"), "brand": attribute("Brand"),
                            "classification_id": self._text(gpc.get("chunkId")) if isinstance(gpc, dict) else None,
                            "published": product.get("published") if type(product.get("published")) is bool else None,
                            "enrichment": enrichment.get("status") if isinstance(enrichment, dict) and type(enrichment.get("status")) is int else None},
                "bol_product_id": self._text(product.get("productId")),
                "api_version": "v10", "status": "complete" if ratings is not None and market["status"] == "complete" else "partial",
                "endpoints": {"catalog": {"path": "content/catalog-products/{ean}", "version": "v10", "status": "ok", "error_code": None},
                              "ratings": {"path": "products/{ean}/ratings", "version": "v10", **ratings_status}},
                "field_completeness": {"title": attribute("Title") is not None,
                                       "brand": attribute("Brand") is not None,
                                       "classification": isinstance(gpc, dict) and self._text(gpc.get("chunkId")) is not None,
                                       "ratings": ratings is not None},
                "data_kinds": {"catalog": "official_bol", "rating_distribution": "official_bol",
                               "rating_count_and_average": "derived_productradar"},
                "ratings": ratings, "warnings": warnings, "market": market}
