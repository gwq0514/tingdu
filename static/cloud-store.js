/* Cloud-only IndexedDB persistence and temporary-server protocol. No desktop imports. */
(function(root){
 const native=root.fetch.bind(root),urls=new Map(),syncing=new Set();let db;
 const ready=new Promise((resolve,reject)=>{const q=indexedDB.open('tingdu-cloud-local-v1',1);q.onupgradeneeded=()=>{for(const name of ['records','assets','chunks','meta'])q.result.createObjectStore(name,{keyPath:'key'});};q.onsuccess=()=>{db=q.result;resolve(db);};q.onerror=()=>reject(q.error);});
 const request=q=>new Promise((resolve,reject)=>{q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
 async function get(store,key){await ready;return request(db.transaction(store).objectStore(store).get(key));}
 async function all(store){await ready;return request(db.transaction(store).objectStore(store).getAll());}
 async function put(store,value){await ready;return new Promise((resolve,reject)=>{const t=db.transaction(store,'readwrite');t.objectStore(store).put(value);t.oncomplete=resolve;t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||Error('本机保存被中止'));});}
 async function forget(id,audioOnly=false){await ready;for(const [key,url] of urls)if(key.startsWith(id+':')){URL.revokeObjectURL(url);urls.delete(key);}return new Promise((resolve,reject)=>{const t=db.transaction(['records','assets','chunks'],'readwrite');if(!audioOnly)t.objectStore('records').delete(id);for(const store of ['assets','chunks']){const c=t.objectStore(store).openCursor();c.onsuccess=()=>{const row=c.result;if(!row)return;if(row.value.id===id)row.delete();row.continue();};}t.oncomplete=resolve;t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error);});}
 function fail(error){if(root.CloudStore)root.CloudStore.lastError=error.message;root.dispatchEvent(new CustomEvent('cloud-storage-error',{detail:'本机保存未完成：'+error.message+'。请保留页面并导出备份；服务器临时副本24小时到期后清理（仍在处理时延后）。'}));}
 function clean(r){const copy={...r};for(const k of ['cloud_owner','local_path','processing_directory','_cloud_local'])delete copy[k];for(const k of ['media_url','enhanced_url','cover_url'])if(copy[k]?.startsWith('blob:'))copy[k]='';return copy;}
 function terminal(r){return ['done','error'].includes(r.status)&&r.summary_status!=='running'&&!['queued','running'].includes(r.diarization_status);}
 async function materialize(record){const r={...record};for(const [kind,field] of [['media','media_url'],['enhanced','enhanced_url'],['cover','cover_url']]){const a=await get('assets',r.id+':'+kind);if(a){const key=a.key+':'+a.updated;if(!urls.has(key))urls.set(key,URL.createObjectURL(a.blob));r[field]=urls.get(key);}}const local=await get('records',r.id);r._cloud_local=!!record._cloud_saved||!!(local?.record._cloud_saved&&local.record.cloud_revision===record.cloud_revision);return r;}
 async function persist(r){if(!r?.id)return;const previous=await get('records',r.id);if(previous?.record.cloud_revision&&r.cloud_revision&&previous.record.cloud_revision>r.cloud_revision)return previous.record;const record={...(previous?.record||{}),...clean(r)};await put('records',{key:r.id,record});return record;}
 async function capture(id){if(syncing.has(id))return;syncing.add(id);try{const response=await native('/api/jobs/'+id);if(!response.ok)return;const r=await response.json();await persist(r);if(!['done','error'].includes(r.status))return;
  for(const [kind,field] of [['media','media_url'],['enhanced','enhanced_url'],['cover','cover_url']]){if(!r[field])continue;const key=id+':'+kind;if((await get('assets',key))?.revision===r.cloud_revision)continue;const asset=await native(r[field]);if(!asset.ok)throw Error('无法保存原声或封面，请稍后重试');await put('assets',{key,id,blob:await asset.blob(),revision:r.cloud_revision,updated:Date.now()});}
  const latest=await get('records',id);if(latest?.record.cloud_revision>r.cloud_revision)return;const record=clean(r);record._cloud_saved=true;await put('records',{key:id,record});if(r.media_url)root.dispatchEvent(new CustomEvent('cloud-record-cached',{detail:{id}}));
  if(terminal(r)){const ack=await native('/api/cloud/jobs/'+id+'/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:r.cloud_revision})});if(ack.ok){record._cloud_cleaned=true;await put('records',{key:id,record});await removeChunks(id);}}
 }catch(e){fail(e);}finally{syncing.delete(id);}}
 async function removeChunks(id){await ready;await new Promise((resolve,reject)=>{const t=db.transaction('chunks','readwrite'),q=t.objectStore('chunks').openCursor();q.onsuccess=()=>{const c=q.result;if(!c)return;if(c.value.id===id)c.delete();c.continue();};t.oncomplete=resolve;t.onerror=()=>reject(t.error);});}
 async function recoverChunks(record){
  if(!['recording','running'].includes(record.status)||await get('assets',record.id+':media'))return record;
  const chunks=(await all('chunks')).filter(x=>x.id===record.id).sort((a,b)=>a.sequence-b.sequence);if(!chunks.length)return record;
  const parts=await Promise.all(chunks.map(x=>x.blob.arrayBuffer())),header=parts[0].slice(0,44),view=new DataView(header),length=parts.reduce((n,p)=>n+p.byteLength-44,0);if(header.byteLength!==44)return record;
  view.setUint32(4,36+length,true);view.setUint32(40,length,true);const blob=new Blob([header,...parts.map(p=>p.slice(44))],{type:'audio/wav'});
  await put('assets',{key:record.id+':media',id:record.id,blob,updated:Date.now()});
  const r={...record,status:'error',duration:length/32000,media_file:'source.wav',media_url:'/api/jobs/'+record.id+'/media',summary_status:record.summary_status==='running'?'error':record.summary_status,diarization_status:'error',_cloud_saved:true,message:'云端临时处理文件已到期，本机录音片段已恢复为原声，可回听、下载后重新上传。'};
  await put('records',{key:r.id,record:r});return r;
 }
 const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 async function remote(url,options){try{return await native(url,options);}catch{return null;}}
 async function meta(name,remoteResponse){const cached=await get('meta',name);let value=cached?.value||[];if(remoteResponse?.ok){const latest=await remoteResponse.json();value=[...new Map([...value,...latest].map(x=>[typeof x==='string'?x:x.key,x])).values()];await put('meta',{key:name,value});}return value;}
 async function subscriptionRestore(key){const cached=(await get('meta','subscriptions'))?.value||[],creator=cached.find(x=>x.key===decodeURIComponent(key));if(creator)await native('/api/cloud/subscriptions/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(creator)});}
 async function fetchLocal(input,options={}){
  const url=typeof input==='string'?input:input.url,u=new URL(url,location.href),method=(options.method||'GET').toUpperCase();if(u.origin!==location.origin||!u.pathname.startsWith('/api/'))return native(input,options);
  await ready;const path=u.pathname;
  if(path==='/api/jobs'||path==='/api/meetings'&&method==='GET'){
   const response=await remote(url,options),local=await all('records'),merged=new Map(local.map(x=>[x.key,x.record]));if(response?.ok){const rows=await response.json();const ids=new Set(rows.map(x=>x.id));for(const [id,record] of merged)if(!ids.has(id))merged.set(id,await recoverChunks(record));for(const row of rows){merged.set(row.id,{...(merged.get(row.id)||{}),...row});capture(row.id);}}
   const rows=[...merged.values()].filter(r=>path!=='/api/meetings'||r.source==='meeting');return json(await Promise.all(rows.map(materialize)));
  }
  const match=path.match(/^\/api\/(jobs|meetings)\/([a-f0-9]{32})(?:\/(.*))?$/);
  if(match){const [,kind,id,action]=match,cached=await get('records',id);
   if(method==='GET'&&!action){const response=await remote(url,options);if(response?.ok){const r=await response.json();await persist(r);capture(id);return json(await materialize(r));}if(cached&&(response?.status===404||!response))return json(await materialize(cached.record));return response||json({detail:'服务暂不可用，尚无本机副本'},503);}
   if(method==='POST'&&action==='chunks'){const file=options.body.get('file'),sequence=Number(options.body.get('sequence'));await put('chunks',{key:id+':'+sequence,id,sequence,blob:file});}
   if(method==='POST'&&action==='chat'){
    let response=await remote(url,options);if(response?.status===404&&cached){const body=JSON.parse(options.body);response=await native('/api/cloud/chat',{...options,body:JSON.stringify({...body,record:cached.record})});if(response.ok){const result=await response.json();if(body.summary){cached.record.summary=result.answer;cached.record.summary_status='done';await put('records',cached);}return json(result);}}return response||json({detail:'模型服务未连接，原声和原文仍在本机'},503);
   }
   if(method==='PATCH'&&!action){const response=await remote(url,options);if(response?.ok){const r=await response.json();await persist(r);return json(await materialize(r));}if(response?.status===404&&cached){const update=JSON.parse(options.body);cached.record={...cached.record,...update};await put('records',cached);return json(await materialize(cached.record));}return response||json({detail:'修改未完成'},503);}
   if(method==='DELETE'&&!action){const response=await remote(url,options);if(!response||!response.ok&&response.status!==404)return response||json({detail:'未能确认服务器副本已清理，本机记录未删除'},503);const audioOnly=u.searchParams.get('audio_only')==='true';await forget(id,audioOnly);if(audioOnly&&cached){cached.record={...cached.record,audio_deleted:true,media_url:'',enhanced_url:'',media_file:'',message:'本机音频已删除，文字与总结保留。'};await put('records',cached);}root.dispatchEvent(new CustomEvent('cloud-record-deleted',{detail:{id}}));return json({id,deleted:audioOnly?'audio':'record'});}
   if(method==='POST'&&action==='retry'&&cached){const response=await remote(url,options);return response?.status===404?json({detail:'服务器临时音频已清理。请下载本机原声后重新上传转写。'},409):response;}
  }
  if(path==='/api/recording-projects'){
   if(method==='GET')return json(await meta('projects',await remote(url,options)));
   if(method==='POST'){const response=await remote(url,options);if(response?.ok){const r=await response.json(),names=(await get('meta','projects'))?.value||[];await put('meta',{key:'projects',value:[...new Set([...names,r.name])]});return json(r);}return response||json({detail:'分类保存未完成'},503);}
  }
  if(path==='/api/meetings'&&method==='POST'){const body=JSON.parse(options.body);if(body.project)await native('/api/recording-projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:body.project})});}
  if(path==='/api/subscriptions'){
   if(method==='GET')return json(await meta('subscriptions',await remote(url,options)));
   if(method==='POST'){const body=JSON.parse(options.body),r=await get('records',body.job_id);if(r?.record.creator){const value=await meta('subscriptions'),creator={...r.record.creator,subscribed_at:new Date().toISOString()};await put('meta',{key:'subscriptions',value:[...new Map([...value,creator].map(x=>[x.key,x])).values()]});return json(creator);}}
  }
  const sub=path.match(/^\/api\/subscriptions\/([^/]+)(?:\/(videos|import))?$/);
  if(sub){if(method==='DELETE'){const response=await remote(url,options);if(response&&!response.ok&&response.status!==404)return response;const value=((await get('meta','subscriptions'))?.value||[]).filter(x=>x.key!==decodeURIComponent(sub[1]));await put('meta',{key:'subscriptions',value});return json({ok:true});}if(sub[2])await subscriptionRestore(sub[1]);}
  const response=await native(input,options);
  if(response.ok&&method==='POST'&&(path==='/api/import'||path==='/api/upload'||path==='/api/meetings')){const r=await response.clone().json();await persist(r);capture(r.id);}
  return response;
 }
 root.CloudStore={ready,get,all,put,forget,capture,materialize,native,terminal};
 root.fetch=async(...args)=>{try{return await fetchLocal(...args);}catch(error){if(error.name==='QuotaExceededError'||error.name==='UnknownError')fail(error);throw error;}};
 ready.then(()=>navigator.storage?.persist?.()).catch(fail);
})(window);
