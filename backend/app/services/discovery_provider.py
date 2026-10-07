"""Bounded discovery adapter sharing the existing OAuth, transport and throttling."""
from datetime import datetime, timezone
from typing import Protocol
from app.services.bol import BolError, validate_ean


class WhiteSpotsProvider(Protocol):
    def capability(self) -> dict: ...
    def collect(self) -> list[dict]: ...


class UnavailableWhiteSpots:
    def capability(self):
        return {'status': 'unverified', 'beta': True, 'api_version': 'v1',
                'reason': 'Accounttoegang niet aangetoond; geen export opgehaald.'}

    def collect(self):
        raise BolError(503, 'White Spots-toegang is niet geverifieerd.')


white_spots: WhiteSpotsProvider = UnavailableWhiteSpots()


def product_list(client, search_term=None, category_id=None):
    """One page only. List position is not sales, popularity or a global rank."""
    query = {'countryCode': 'NL', 'sort': 'RELEVANCE', 'page': 1}
    if search_term:
        query['searchTerm'] = search_term
    if category_id:
        query['categoryId'] = category_id
    for attempt in range(2):
        token = client._access_token()
        response = client._request('POST', 'https://api.bol.com/retailer/products/list', json=query,
                                   headers={'Authorization': 'Bearer '+token,
                                            'Accept': 'application/vnd.retailer.v10+json',
                                            'Content-Type': 'application/json',
                                            'Accept-Language': 'nl'})
        if response.status_code == 401 and attempt == 0:
            with client._lock:
                if client._token == token:
                    client._token, client._expires = '', 0
            continue
        if response.status_code == 415:
            raise BolError(502, 'Bol accepteert het Product List-requestformaat niet; toegang is niet vastgesteld.')
        if response.status_code == 404:
            raise BolError(404, 'Geen productlijst beschikbaar voor deze zoekcontext.')
        client._check(response)
        body = client._json(response)
        break
    products = body.get('products')
    if not isinstance(products, list) or len(products) > 50 or body.get('sort')!='RELEVANCE':
        raise BolError(502, 'Bol gaf geen begrensde bruikbare productlijst.')
    now = datetime.now(timezone.utc).isoformat()
    records, invalid = [], 0
    for position, item in enumerate(products, 1):
        if not isinstance(item, dict) or not isinstance(item.get('eans'), list):
            invalid += 1
            continue
        title = client._text(item.get('title'))
        if not title or not title.strip() or not item['eans'] or len(item['eans']) > 50:
            invalid += 1
            continue
        for row in item['eans']:
            ean = row.get('ean') if isinstance(row, dict) else None
            try:
                validate_ean(ean or '')
            except BolError:
                invalid += 1
                continue
            records.append({'ean': ean, 'title': title, 'category': category_id,
                            'measured_at': now, 'source': 'bol_product_list', 'api_version': 'v10',
                            'endpoint': 'products/list', 'kind': 'official_measured',
                            'completeness': {'valid_record': True, 'scope': 'page_1', 'all_results_collected': False},
                            'query': {**query, 'searchTerm': client._text(search_term)},
                            'list_position': position, 'position_kind': 'derived'})
    return {'records': records, 'status': 'partial' if invalid else 'complete',
            'invalid_entries': invalid, 'page': 1, 'pagination_complete': False,
            'notice': 'Eén pagina; positie binnen deze zoekcontext, geen verkoopvolume of globale ranking.'}
