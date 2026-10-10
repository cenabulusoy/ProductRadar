"""Explicit bounded monitoring service, shared by UI and a future scheduler."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json,sqlite3
from fastapi import HTTPException
from app.services import discovery as store
from app.services import discovery_provider as provider
from app.services.bol import BolError,BolClient
from app.services.freshness import LEASE_SECONDS
from app.services.discovery_history import evidence_summary


def now():return datetime.now(timezone.utc)
def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


class BoundedEnrichment:
    """No second client/token: reuse original parser while bounding its GET calls."""
    def __init__(self,client):self.client=client;self.gets=0
    def __getattr__(self,name):return getattr(self.client,name)
    def _get(self,path,params=None):
        if self.gets>=35 or path.endswith('/offers') and (params or {}).get('page',1)>5:
            raise BolError(429,'Monitoring-calllimiet bereikt; meting blijft onvolledig.')
        self.gets+=1
        return self.client._get(path,params=params)
    def preview(self,ean):return BolClient.preview(self,ean)


def migrate_monitoring(db):
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_monitoring_contexts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, parameters TEXT NOT NULL,
        context_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_monitoring_watchlist (
        context_id INTEGER NOT NULL REFERENCES discovery_monitoring_contexts(id),
        candidate_id INTEGER NOT NULL REFERENCES discovery_candidates(id), followed_at TEXT NOT NULL,
        PRIMARY KEY(context_id,candidate_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_monitoring_runs (
        request_id TEXT PRIMARY KEY, context_id INTEGER NOT NULL REFERENCES discovery_monitoring_contexts(id),
        started_at TEXT NOT NULL, lease_until TEXT NOT NULL, completed_at TEXT,
        status TEXT NOT NULL, watched TEXT NOT NULL, result TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_monitoring_measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, context_id INTEGER NOT NULL REFERENCES discovery_monitoring_contexts(id),
        candidate_id INTEGER NOT NULL REFERENCES discovery_candidates(id), run_id TEXT NOT NULL REFERENCES discovery_monitoring_runs(request_id),
        ean TEXT NOT NULL, measured_at TEXT NOT NULL, parameters TEXT NOT NULL, fingerprint TEXT NOT NULL,
        payload TEXT NOT NULL, UNIQUE(context_id,candidate_id,fingerprint))''')
    db.execute('CREATE INDEX IF NOT EXISTS discovery_monitoring_history ON discovery_monitoring_measurements(context_id,candidate_id,measured_at,id)')


def exists(db):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_monitoring_contexts'").fetchone())


def save_context(name,parameters):
    raw=encode(parameters)
    with store.connection(True) as db:
        db.execute('BEGIN IMMEDIATE');migrate_monitoring(db)
        db.execute('INSERT OR IGNORE INTO discovery_monitoring_contexts(name,parameters,context_hash,created_at) VALUES (?,?,?,?)',
                   (name,raw,sha256(raw.encode()).hexdigest(),now().isoformat()))
        return db.execute('SELECT id FROM discovery_monitoring_contexts WHERE context_hash=?',(sha256(raw.encode()).hexdigest(),)).fetchone()[0]


def context(db,cid):
    row=db.execute('SELECT * FROM discovery_monitoring_contexts WHERE id=?',(cid,)).fetchone() if exists(db) else None
    if not row:raise HTTPException(404,'Monitoringcontext niet gevonden.')
    value=dict(row);value['parameters']=json.loads(value['parameters']);return value


def watch(cid,candidate_id,follow=True):
    with store.connection(True) as db:
        db.execute('BEGIN IMMEDIATE');ctx=context(db,cid)
        candidate=db.execute('SELECT id,ean FROM discovery_candidates WHERE id=?',(candidate_id,)).fetchone()
        if not candidate or not candidate['ean']:raise HTTPException(404,'Kandidaat met geldige EAN niet gevonden.')
        if follow:
            count=db.execute('SELECT count(*) FROM discovery_monitoring_watchlist WHERE context_id=?',(cid,)).fetchone()[0]
            already=db.execute('SELECT 1 FROM discovery_monitoring_watchlist WHERE context_id=? AND candidate_id=?',(cid,candidate_id)).fetchone()
            if count>=5 and not already:raise HTTPException(422,'Maximaal vijf gevolgde kandidaten per context.')
            db.execute('INSERT OR IGNORE INTO discovery_monitoring_watchlist VALUES (?,?,?)',(cid,candidate_id,now().isoformat()))
        else:db.execute('DELETE FROM discovery_monitoring_watchlist WHERE context_id=? AND candidate_id=?',(cid,candidate_id))


def contexts():
    with store.connection() as db:
        if not exists(db):return []
        result=[]
        for row in db.execute('SELECT id FROM discovery_monitoring_contexts ORDER BY id'):
            item=context(db,row[0]);item['watched']=[dict(r) for r in db.execute('''SELECT c.id,c.ean,w.followed_at FROM discovery_monitoring_watchlist w
                JOIN discovery_candidates c ON c.id=w.candidate_id WHERE w.context_id=? ORDER BY c.id''',(row[0],))]
            last=db.execute('SELECT request_id,started_at,completed_at,status,lease_until FROM discovery_monitoring_runs WHERE context_id=? ORDER BY started_at DESC,request_id DESC LIMIT 1',(row[0],)).fetchone()
            item['last_run']=dict(last) if last else None
            if last:item['last_run']['lease_expired']=last['status']=='running' and last['lease_until']<=now().isoformat()
            result.append(item)
        return result


def reserve(cid,request_id):
    time=now()
    with store.connection(True) as db:
        db.execute('BEGIN IMMEDIATE');ctx=context(db,cid)
        previous=db.execute('SELECT * FROM discovery_monitoring_runs WHERE request_id=?',(request_id,)).fetchone()
        if previous:
            if previous['context_id']!=cid:raise HTTPException(409,'Deze aanvraag hoort bij een andere context.')
            if previous['status']=='running':raise HTTPException(409,'Deze meetrun loopt nog of is onderbroken. Gebruik na afloop een nieuwe aanvraag.')
            return ctx,None,json.loads(previous['result']) if previous['result'] else {'status':previous['status'],'request_id':request_id}
        # Global lease across monitoring contexts/workers; SQLite serializes reservation.
        active=db.execute("SELECT 1 FROM discovery_monitoring_runs WHERE status='running' AND lease_until>?",(time.isoformat(),)).fetchone()
        if active:raise HTTPException(409,'Er loopt al een monitoringrun. Probeer later opnieuw.')
        db.execute("UPDATE discovery_monitoring_runs SET status='interrupted',completed_at=? WHERE status='running' AND lease_until<=?",(time.isoformat(),time.isoformat()))
        watched=[dict(r) for r in db.execute('''SELECT c.id,c.ean FROM discovery_monitoring_watchlist w JOIN discovery_candidates c
                 ON c.id=w.candidate_id WHERE w.context_id=? ORDER BY c.id''',(cid,))]
        if not watched:raise HTTPException(422,'Volg eerst minstens één kandidaat in deze context.')
        db.execute('INSERT INTO discovery_monitoring_runs VALUES (?,?,?,?,?,?,?,?)',
                   (request_id,cid,time.isoformat(),(time+timedelta(seconds=LEASE_SECONDS)).isoformat(),None,'running',encode(watched),None))
        return ctx,watched,None


def finish(cid,request_id,points,result):
    with store.connection(True) as db:
        db.execute('BEGIN IMMEDIATE')
        run=db.execute('SELECT status,lease_until FROM discovery_monitoring_runs WHERE request_id=?',(request_id,)).fetchone()
        if not run or run['status']!='running' or run['lease_until']<now().isoformat():
            raise HTTPException(409,'Meetlease verlopen; resultaat wordt niet als nieuwe succesvolle run opgeslagen.')
        ctx=context(db,cid);ids=[]
        for point in points:
            time=datetime.fromisoformat(point['measured_at'])
            if time.utcoffset() is None or time>now() or point['parameters']!=ctx['parameters']:
                raise HTTPException(422,'Meetmoment of context ongeldig; er wordt niets opgeslagen.')
            raw=encode(point['payload']);fingerprint=sha256(encode({k:v for k,v in point.items() if k!='run_id'}).encode()).hexdigest()
            db.execute('''INSERT OR IGNORE INTO discovery_monitoring_measurements
                (context_id,candidate_id,run_id,ean,measured_at,parameters,fingerprint,payload) VALUES (?,?,?,?,?,?,?,?)''',
                (cid,point['candidate_id'],request_id,point['ean'],point['measured_at'],encode(point['parameters']),fingerprint,raw))
            ids.append(db.execute('SELECT id FROM discovery_monitoring_measurements WHERE context_id=? AND candidate_id=? AND fingerprint=?',(cid,point['candidate_id'],fingerprint)).fetchone()[0])
        result={**result,'request_id':request_id,'measurement_ids':ids,'completed_at':now().isoformat()}
        db.execute('UPDATE discovery_monitoring_runs SET status=?,completed_at=?,result=? WHERE request_id=?',
                   (result['status'],result['completed_at'],encode(result),request_id))
        return result


def run(cid,request_id,client):
    # Share Sprint 5.1 process guard; DB lease additionally guards monitoring workers.
    from app.api.discovery import collection_lock
    if not collection_lock.acquire(False):raise HTTPException(409,'Er loopt al een discovery-aanvraag.')
    try:
        ctx,watched,cached=reserve(cid,request_id)
        if cached is not None:return cached
        query=ctx['parameters'];points=[]
        enrichment=BoundedEnrichment(client) if isinstance(client,BolClient) else client
        try:
            listing=provider.product_list(client,query.get('searchTerm'),query.get('categoryId'))
            listed={r['ean']:r for r in reversed(listing['records'])}
            list_time=listing['records'][0]['measured_at'] if listing['records'] else now().isoformat()
            list_error=None
        except BolError as exc:
            listing={'status':'failed','records':[]};listed={};list_time=now().isoformat();list_error=exc.status
        for candidate in watched:
            found=listed.get(candidate['ean'])
            payload={'list_status':'observed' if found else ('not_observed' if listing['status']=='complete' else 'unknown'),
                     'position':found['list_position'] if found else None,'list_measured_at':list_time,
                     'list_completeness':listing['status'],'list_error_code':list_error,
                     'provenance':{'list':{'kind':'official_measured' if list_error is None else 'derived','endpoint':'products/list','api_version':'v10','recorded_at':list_time},
                                   'position':{'kind':'derived','source':'ProductRadar context-bound list position','recorded_at':list_time}},
                     'preview':{}}
            if list_error is None:
                try:
                    preview=enrichment.preview(candidate['ean']);payload['preview']=preview
                    payload['status']='complete' if listing['status']=='complete' and preview['status']=='complete' else 'partial'
                    payload['provenance']['enrichment']={'kind':'official_measured','endpoint':'catalog/ratings/offers','api_version':'v10','recorded_at':preview['fetched_at']}
                except BolError as exc:payload.update(status='failed',enrichment_error_code=exc.status)
            else:payload['status']='failed'
            points.append({'candidate_id':candidate['id'],'ean':candidate['ean'],'parameters':query,
                           'measured_at':payload.get('preview',{}).get('fetched_at') or now().isoformat(),'payload':payload})
        status='complete' if all(p['payload']['status']=='complete' for p in points) else 'failed' if all(p['payload']['status']=='failed' for p in points) else 'partial'
        return finish(cid,request_id,points,{'status':status,'watched_count':len(watched),
                      'list_status':listing['status'],'list_error_code':list_error,'list_page':1,
                      'notice':'Handmatige meetrun; geen geschatte verkopen of inkoopadvies.'})
    finally:collection_lock.release()


def history(cid,candidate_id):
    with store.connection() as db:
        ctx=context(db,cid)
        rows=db.execute('SELECT * FROM discovery_monitoring_measurements WHERE context_id=? AND candidate_id=? ORDER BY measured_at,id',(cid,candidate_id)).fetchall()
        points=[]
        for row in rows:
            p=dict(row);p['payload']=json.loads(p['payload']);p['parameters']=json.loads(p['parameters']);points.append(p)
        # A crashed run is explicit unknown evidence, never an invisible gap/fallback.
        for row in db.execute("SELECT * FROM discovery_monitoring_runs WHERE context_id=? AND status IN ('running','interrupted')",(cid,)):
            candidate=next((x for x in json.loads(row['watched']) if x['id']==candidate_id),None)
            if candidate:
                points.append({'id':None,'run_id':row['request_id'],'ean':candidate['ean'],'parameters':ctx['parameters'],
                               'measured_at':row['started_at'],'payload':{'status':row['status'],'list_status':'unknown','preview':{}}})
        points.sort(key=lambda p:(p['measured_at'],p['id'] or 0))
        return {'context':ctx,'candidate_id':candidate_id,'points':points,'demand_evidence':evidence_summary(points),
                'notice':'Historische contextmetingen, geen huidige prijs of geschatte verkopen.'}
