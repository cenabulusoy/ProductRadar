"use client";
import {useEffect,useRef,useState} from "react";
type Category={categoryId?:string|null;categoryName?:string|null;id?:string|null;name?:string|null;subcategories:Category[]|null};
type Measurement={id:number;ean:string;retrieved_at:string;query:{country_code:string;language:string};official:{url:string|null;categories:Category[]};status:string;provenance:{kind:string;source:string;api_version:string;endpoint:string}};
export function categoryPaths(categories:Category[]):Category[][]{
 function visit(node:Category,path:Category[]):Category[][]{const next=[...path,node];return node.subcategories?.length?node.subcategories.flatMap(child=>visit(child,next)):[next];}
 return categories.flatMap(node=>visit(node,[]));
}
export function productLink(value:string|null){if(value===null)return null;try{const u=new URL(value);return u.protocol==='https:'&&(u.hostname==='bol.com'||u.hostname.endsWith('.bol.com'))&&!u.username&&!u.password?u.href:null;}catch{return null;}}
export function PlacementMeasurement({value}:{value:Measurement}){
 const paths=categoryPaths(value.official.categories),url=productLink(value.official.url);
 return <section className="panel"><h3>Officiële bol-webshopplacement</h3><p>EAN {value.ean} · Opgehaald {value.retrieved_at} · Status {value.status}</p>
  <p>Requestcontext: land {value.query.country_code} · taal {value.query.language}. Niet afzonderlijk teruggegeven als responseveld.</p>
  <p>{value.provenance.kind} · {value.provenance.source} · {value.provenance.api_version} · {value.provenance.endpoint}</p>
  {url?<a href={url} target="_blank" rel="noopener noreferrer">Productpagina op bol</a>:<p>Product-URL onbekend of niet veilig bruikbaar.</p>}
  {!paths.length?<p>Geen categorieën teruggegeven voor deze aanvraag; geen categorie of verkoopvolume afleiden.</p>:
   <><p>Categoriepaden uit de officiële respons · apart weergegeven; padweergave is derived, categorie-ID’s en namen zijn official_measured.</p>
    {paths.map((path,i)=><section key={i}><h4>Categoriepad {i+1}</h4><ol>{path.map((node,j)=><li key={j}>{node.categoryName??node.name??'Onbekend'} · ID {node.categoryId??node.id??'Onbekend'}</li>)}</ol></section>)}
   </>}
  <p>Webshopplacement is iets anders dan Product List-zoekcontext en GPC-classificatie. Dit is geen ranking, vraag, verkoopvolume of score. Ontbrekende niveaus worden niet aangevuld.</p>
 </section>;
}
export function ProductPlacement({api,ean}:{api:string;ean:string}){
 const [items,setItems]=useState<Measurement[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const lock=useRef(false),generation=useRef(0),request=useRef<{key:string;id:string}|null>(null);
 useEffect(()=>{let active=true;generation.current++;request.current=null;lock.current=false;setItems([]);setError('');setBusy(false);
  fetch(`${api}/discovery/placement/${ean}`,{cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error();return r.json();}).then(v=>{if(active)setItems(v.items);}).catch(()=>{if(active)setError('Opgeslagen placement niet beschikbaar.');});
  return()=>{active=false;generation.current++;};},[api,ean]);
 async function measure(){
  if(lock.current)return;lock.current=true;setBusy(true);setError('');const g=generation.current,key=JSON.stringify([api,ean,'NL','nl']);
  if(request.current?.key!==key)request.current={key,id:crypto.randomUUID()};
  try{
   let response:Response;try{response=await fetch(`${api}/discovery/placement`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ean,country:'NL',language:'nl',request_id:request.current.id})});}catch{throw new Error('Verbinding onderbroken; dezelfde aanvraag kan veilig opnieuw worden verstuurd.');}
   if(!response.ok){let text='Placement niet beschikbaar.';try{const b=await response.json();if(typeof b.detail==='string')text=b.detail;}catch{}throw new Error(text);}
   let value;try{value=await response.json();}catch{throw new Error('Onverwacht placementantwoord; laad de opgeslagen metingen opnieuw.');}
   if(g===generation.current){setItems(old=>[value,...old.filter(x=>x.id!==value.id)]);request.current=null;}
  }catch(e){if(g===generation.current)setError(e instanceof Error?e.message:'Placement niet beschikbaar.');}
  finally{if(g===generation.current){lock.current=false;setBusy(false);}}
 }
 return <section className="panel"><h2>Webshopcategorieën · afzonderlijke bron</h2><p>Openen leest alleen opgeslagen placementhistorie. Expliciet ophalen: één EAN, land NL, taal nl.</p>
  <button disabled={busy} onClick={measure}>Webshopplacement ophalen</button>{busy&&<p role="status">Placement ophalen…</p>}{error&&<p role="alert">{error}</p>}
  {!items.length&&!busy&&<p>Geen opgeslagen placementmeting; categorieën blijven onbekend.</p>}
  {items.map(value=><PlacementMeasurement key={value.id} value={value}/>)}
 </section>;
}
