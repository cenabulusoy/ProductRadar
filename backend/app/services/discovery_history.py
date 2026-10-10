"""Pure historical evidence, never sales estimates or Decision policy changes."""
from datetime import datetime
from decimal import Decimal
from app.analysis.scoring_v2 import observed_market


def timestamp(value):
    time=datetime.fromisoformat(value)
    if time.utcoffset() is None: raise ValueError('Timezone required')
    return time


def rating(point):
    preview=point.get('payload',{}).get('preview',{})
    endpoint=preview.get('endpoints',{}).get('ratings',{})
    if (preview.get('ean')!=point.get('ean') or preview.get('api_version')!='v10' or
        preview.get('source')!='bol Retailer API v10' or preview.get('language')!='nl' or
        endpoint.get('status')!='ok' or endpoint.get('version')!='v10' or
        endpoint.get('path')!='products/{ean}/ratings' or preview.get('fetched_at')!=point.get('measured_at')):return None
    ratings=preview.get('ratings')
    if not isinstance(ratings,dict) or type(ratings.get('count')) is not int or ratings['count']<0:return None
    rows=ratings.get('distribution')
    if not isinstance(rows,list):return None
    stars=set();total=0
    for row in rows:
        if not isinstance(row,dict) or type(row.get('rating')) is not int or row['rating'] not in range(1,6) or row['rating'] in stars or type(row.get('count')) is not int or row['count']<0:return None
        stars.add(row['rating']);total+=row['count']
    return ratings['count'] if total==ratings['count'] and stars==set(range(1,6)) else None


def market(point):
    payload=point.get('payload',{}).get('preview',{}).get('market')
    if not isinstance(payload,dict):return None
    try:
        when=timestamp(payload['measured_at'])
        result=observed_market({'id':point.get('id') or 0,'measured_at':payload['measured_at'],'payload':payload},when)
        if result['status']!='complete':return None
        result['relevant_price']=result['reference'].get('price')
        return result
    except (KeyError,ValueError,TypeError):return None


def compare(previous,current):
    names=['rating_count_delta','rating_growth_per_day','rating_growth_per_30_days','seller_count_delta',
           'offer_count_delta','relevant_price_delta','price_min_delta','price_max_delta',
           'best_offer_changed','list_position_delta','fulfilment_changed','delivery_changed']
    result={name:None for name in names}
    result.update(kind='derived',comparison_version='discovery-history/1',reason='no_previous_comparable_measurement',
                  previous_id=previous.get('id') if previous else None,current_id=current.get('id') if current else None,
                  interval_days=None,metric_reasons={})
    if not previous or not current:return result
    if previous.get('ean')!=current.get('ean') or previous.get('parameters')!=current.get('parameters'):
        result['reason']='different_identity_or_context';return result
    ids=[p.get('payload',{}).get('preview',{}).get('bol_product_id') for p in (previous,current)]
    if all(ids) and ids[0]!=ids[1]:result['reason']='conflicting_product_identity';return result
    try:
        interval=(timestamp(current['measured_at'])-timestamp(previous['measured_at'])).total_seconds()/86400
    except (KeyError,ValueError,TypeError):result['reason']='invalid_timestamp';return result
    if interval<=0:result['reason']='non_positive_interval';return result
    result.update(reason='comparable_context',interval_days=interval)
    old,new=rating(previous),rating(current)
    if old is not None and new is not None:
        result['rating_count_delta']=new-old
        if 14<=interval<=60 and new>=old:
            result['rating_growth_per_day']=(new-old)/interval
            result['rating_growth_per_30_days']=30*(new-old)/interval
        else:result['metric_reasons']['rating_growth']='interval_outside_14_60_days' if new>=old else 'rating_count_decreased'
    else:result['metric_reasons']['ratings']='missing_or_incomplete_ratings'
    a,b=market(previous),market(current)
    if a and b:
        for name,key in [('seller_count_delta','unique_seller_count'),('offer_count_delta','offer_count'),
                         ('relevant_price_delta','relevant_price'),('price_min_delta','price_min'),('price_max_delta','price_max')]:
            if a.get(key) is not None and b.get(key) is not None:
                result[name]=float(Decimal(str(b[key]))-Decimal(str(a[key]))) if 'price' in key else b[key]-a[key]
        ao,bo=a.get('relevant_offer') or {},b.get('relevant_offer') or {}
        # Compare actual best-offer identity; fallback lowest offer is not a buybox observation.
        if ao.get('bestOffer') is True and bo.get('bestOffer') is True and ao.get('offerId') and bo.get('offerId'):
            result['best_offer_changed']=ao['offerId']!=bo['offerId']
        if ao.get('fulfilmentMethod') and bo.get('fulfilmentMethod'):
            result['fulfilment_changed']=ao['fulfilmentMethod']!=bo['fulfilmentMethod']
        def lead(offer,point):
            try:
                if not offer.get('minDeliveryDate') or not offer.get('maxDeliveryDate'):return None
                day=timestamp(point['payload']['preview']['market']['measured_at']).date()
                return tuple((datetime.fromisoformat(offer[k]).date()-day).days for k in ('minDeliveryDate','maxDeliveryDate'))
            except (KeyError,ValueError,TypeError):return None
        la,lb=lead(ao,previous),lead(bo,current)
        if la is not None and lb is not None:result['delivery_changed']=la!=lb
    else:result['metric_reasons']['market']='missing_or_incomplete_market'
    pa,pb=previous.get('payload',{}),current.get('payload',{})
    if pa.get('list_status')=='observed' and pb.get('list_status')=='observed' and pa.get('list_completeness')=='complete' and pb.get('list_completeness')=='complete' and pa.get('position') is not None and pb.get('position') is not None:
        try:
            valid_time=timestamp(pb.get('list_measured_at',current['measured_at']))>timestamp(pa.get('list_measured_at',previous['measured_at']))
        except (ValueError,TypeError):valid_time=False
        if valid_time:result['list_position_delta']=pb['position']-pa['position']
        else:result['metric_reasons']['list_position']='non_positive_list_interval'
    else:result['metric_reasons']['list_position']='not_observed_or_failed_in_this_page_context'
    return result


def evidence_summary(points):
    comparison=compare(points[-2],points[-1]) if len(points)>=2 else compare(None,points[-1] if points else None)
    # Latest failed point stays visible. Do not jump across missing ratings to invent growth.
    growth=None
    if points and rating(points[-1]) is not None:
        for older in reversed(points[:-1]):
            if rating(older) is None:break
            candidate=compare(older,points[-1])
            if candidate['rating_growth_per_day'] is not None:
                growth=candidate;break
    return {'kind':'derived','rating_history':'bruikbaar' if growth else 'onvoldoende',
            'rating_measurements':sum(rating(p) is not None for p in points),
            'market_measurements':sum(market(p) is not None for p in points),
            'seller_trend_available':comparison['seller_count_delta'] is not None,
            'price_trend_available':comparison['relevant_price_delta'] is not None,
            'list_position_history':'contextgebonden',
            'list_observations':sum(p.get('payload',{}).get('list_status')=='observed' for p in points),
            'actual_sales_evidence':None,'estimated_monthly_sales':None,'demand_score':None,
            'comparison':comparison,'rating_growth':growth,
            'notice':'Ratinggroei is een afgeleid demand-signaal, geen verkoopvolume. Twee complete vergelijkbare meetpunten met 14–60 dagen interval zijn de ondergrens; meer meetpunten zijn wenselijk.'}
