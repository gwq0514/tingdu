const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {indexedDB,IDBObjectStore}=require(process.env.TINGDU_IDB_TEST_MODULE||'fake-indexeddb');
const server=new Map();let ack=0,failAssets=false,offline=false,context,events=[];
const originalPut=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(...args){if(failAssets&&this.name==='assets')throw new DOMException('disk full','QuotaExceededError');return originalPut.apply(this,args)};
function row(id,source='meeting'){return{id,title:'Synthetic cache fixture',source,status:'done',text:'Synthetic transcript',segments:[],summary_status:'done',diarization_status:'done',cloud_revision:'1780000000000000001',created_at:new Date().toISOString(),media_url:'/api/jobs/'+id+'/media',media_file:'source.wav'}}
const answer=x=>new Response(JSON.stringify(x),{headers:{'Content-Type':'application/json'}});
async function fetch(url,options={}){
 if(offline)throw Error('offline');const path=new URL(url,'https://tingdu.online').pathname,id=path.split('/')[3];
 if(path==='/api/jobs'||path==='/api/meetings'&&(!options.method||options.method==='GET'))return answer([...server.values()]);
 if(path.endsWith('/ack')){const key=path.split('/')[4],stored=await context.CloudStore.get('records',key),asset=await context.CloudStore.get('assets',key+':media');assert.ok(stored.record._cloud_saved&&asset,'ACK only after committed metadata AND audio');assert.equal(JSON.parse(options.body).revision,server.get(key).cloud_revision);ack++;server.delete(key);return answer({cleaned:true});}
 if(path==='/api/cloud/chat')return answer({answer:'Synthetic summary'});
 if(options.method==='DELETE')return new Response('',{status:404});
 if(path.endsWith('/media')){if(!server.has(id))return new Response('',{status:404});return new Response(new Blob(['original audio fixture'],{type:'audio/wav'}));}
 if(server.has(id))return answer(server.get(id));return new Response('',{status:404});
}
function page(){const c={fetch,location:{href:'https://tingdu.online/',origin:'https://tingdu.online'},indexedDB,navigator:{storage:{persist:async()=>true}},URL,Response,Blob,CustomEvent,Map,Set,Promise,Date,JSON,Error,console,dispatchEvent:e=>events.push(e.detail)};c.window=c;const v=vm.createContext(c);vm.runInContext(fs.readFileSync('static/cloud-store.js','utf8'),v);return v;}
async function wait(fn){for(let i=0;i<100;i++){if(await fn())return;await new Promise(r=>setTimeout(r,10))}throw Error('test timed out');}
(async()=>{
 context=page();await context.CloudStore.ready;const id='a'.repeat(32);server.set(id,row(id));
 await context.fetch('/api/jobs');await wait(async()=>ack===1);assert.equal(server.size,0);
 const record=await(await context.fetch('/api/jobs/'+id)).json();assert.equal(record.text,'Synthetic transcript');assert.ok(record.media_url.startsWith('blob:'));
 const original=await globalThis.fetch(record.media_url);assert.equal(await original.text(),'original audio fixture');
 context=page();await context.CloudStore.ready;assert.equal((await(await context.fetch('/api/meetings')).json()).length,1,'page reload retains history');
 const result=await(await context.fetch('/api/jobs/'+id+'/chat',{method:'POST',body:JSON.stringify({summary:true,model:'fixture'})})).json();assert.equal(result.answer,'Synthetic summary');assert.equal((await context.CloudStore.get('records',id)).record.summary,'Synthetic summary');
 await context.fetch('/api/meetings/'+id+'?audio_only=true',{method:'DELETE'});assert.equal(await context.CloudStore.get('assets',id+':media'),undefined);assert.equal((await context.CloudStore.get('records',id)).record.text,'Synthetic transcript');
 await context.fetch('/api/meetings/'+id,{method:'DELETE'});assert.equal(await context.CloudStore.get('records',id),undefined);
 const second='b'.repeat(32);server.set(second,row(second));failAssets=true;await context.CloudStore.capture(second);assert.equal(ack,1,'failed local save never ACKs');assert.equal(server.has(second),true);assert.ok(events.some(x=>/本机保存未完成/.test(x)));
 failAssets=false;await context.CloudStore.capture(second);assert.equal(ack,2);assert.equal(server.size,0);
 offline=true;const form=new FormData();form.append('sequence','0');form.append('file',new Blob(['durable microphone chunk']));await assert.rejects(()=>context.fetch('/api/meetings/'+second+'/chunks',{method:'POST',body:form}));const chunk=await context.CloudStore.get('chunks',second+':0');assert.equal(await chunk.blob.text(),'durable microphone chunk');
 offline=false;const orphan='c'.repeat(32),wav=require('./static/meeting-audio.js').wav(new Float32Array(16000),16000);await context.CloudStore.put('records',{key:orphan,record:{...row(orphan),status:'recording',media_url:'',summary_status:'none'}});await context.CloudStore.put('chunks',{key:orphan+':0',id:orphan,sequence:0,blob:new Blob([wav])});const recovered=await(await context.fetch('/api/meetings')).json();const raw=recovered.find(r=>r.id===orphan);assert.equal(raw.status,'error');assert.ok(raw.media_url.startsWith('blob:'));assert.equal((await context.CloudStore.get('assets',orphan+':media')).blob.size,32044);
 console.log('Browser persistence: audio/text survive reload; ACK follows durable storage; failed storage retains server copy; local summary, audio-only/full deletion and offline chunk durability PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
