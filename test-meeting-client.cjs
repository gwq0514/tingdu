// Exercise the real recording controller with a synthetic device; never opens a microphone.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const elements=new Map();
class Element{
 constructor(){this.value='';this.children=[];this.dataset={};this.textContent='';this.classList={toggle(){}};this.scrollHeight=0;this.scrollTop=0;this.clientHeight=0;this.attributes={}}
 append(...x){this.children.push(...x)}replaceChildren(...x){this.children=x}setAttribute(k,v){this.attributes[k]=v}getAttribute(k){return this.attributes[k]}removeAttribute(k){delete this.attributes[k]}pause(){}play(){return Promise.resolve()}click(){}showModal(){this.open=true}close(){this.open=false}
}
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
let healthCalls=0;
let batchRecords=null,deleteCalls=[],blockedDelete=false;
let record,uploads=[],finishCount=0,startCount=0,stopped=false,capture,failures=0,failDevice=false;
const track={stop(){stopped=true}};
class Context{constructor(){this.sampleRate=16000;this.audioWorklet={addModule:async()=>{}};this.destination={}}resume(){this.state="running";return Promise.resolve()}suspend(){this.state="suspended";return Promise.resolve()}close(){this.state="closed";return Promise.resolve()}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}}
class Worklet{constructor(){capture=this;this.port={postMessage:command=>{if(command.type==='flush'||command.type==='pause')this.port.onmessage({data:{flushed:true,id:command.id}})}}}connect(){}disconnect(){}}
async function fetch(url,opts={}){
 let result;
 if(opts.method==='DELETE'){const id=url.split('/')[3].split('?')[0];deleteCalls.push(id);if(blockedDelete&&id==='b'.repeat(32))return {ok:false,json:async()=>({detail:'仍在后台处理'})};if(!url.includes('audio_only=true'))batchRecords=batchRecords.filter(r=>r.id!==id);result={id}}
 else if(url==='/api/health'){healthCalls++;result={models:[]}}
 else if(url==='/api/recording-projects')result=[];
 else if(url==='/api/meetings'&&opts.method==='POST'){assert.equal(JSON.parse(opts.body).project,'');startCount++;uploads=[];record={id:'a'.repeat(32),title:'Synthetic meeting',created_at:new Date().toISOString(),status:'recording',recording_chunks:[],segments:[],text:'',duration:0};result=record}
 else if(url.endsWith('/chunks')){if(failures>0){failures--;return {ok:false,json:async()=>({detail:'Synthetic save failure'})}}const seq=Number(opts.body.get('sequence'));assert.equal(seq,uploads.length);const raw=await opts.body.get('file').arrayBuffer();uploads.push(raw);record.recording_chunks.push({});result={ok:true}}
 else if(url.endsWith('/finish')){assert.equal(JSON.parse(opts.body).chunks,uploads.length);record.status='done';finishCount++;result=record}
 else if(url==='/api/meetings')result=batchRecords||(record?[record]:[]);
 else if(url.startsWith('/api/jobs/'))result=record;
 else throw Error(url);
 return {ok:true,json:async()=>structuredClone(result)};
}
const context=vm.createContext({console,Float32Array,ArrayBuffer,DataView,Blob,FormData,AbortSignal,URL,Date,Promise,Map,Set,JSON,setTimeout,clearTimeout,setInterval(){},fetch,structuredClone,ResourceFiles:require('./static/export-utils.js'),MeetingAudio:require('./static/meeting-audio.js'),AudioContext:Context,AudioWorkletNode:Worklet,navigator:{mediaDevices:{getUserMedia:async()=>{if(failDevice)throw Error('Synthetic microphone unavailable');return {getAudioTracks:()=>[track],getTracks:()=>[track]}}}},document:{body:{dataset:{}},getElementById:el,createElement:()=>new Element(),createTextNode:text=>text},window:{AudioWorkletNode:Worklet,addEventListener(){}}});
vm.runInContext(fs.readFileSync('static/meetings.js','utf8'),context);
(async()=>{
 await new Promise(r=>setImmediate(r));
 assert.equal(vm.runInContext('document.body.dataset.stage',context),'idle');
 const initialHealthCalls=healthCalls;
 await vm.runInContext('startRecording()',context);
 assert.equal(healthCalls,initialHealthCalls,'开始录音不等待摘要模型检查');
 assert.equal(vm.runInContext('document.body.dataset.stage',context),'recording');
 for(let i=0;i<64;i++)capture.port.onmessage({data:{samples:new Float32Array(2048).fill(.1)}});
 capture.port.onmessage({data:{samples:new Float32Array(333).fill(.2)}});
 await vm.runInContext('stopRecording()',context);
 assert.equal(vm.runInContext('document.body.dataset.stage',context),'detail');
 assert.ok(stopped);assert.ok(uploads.every(b=>new DataView(b).getUint32(40,true)/32000<=4.13));assert.equal(finishCount,1);assert.equal(uploads.length,3);
 const frames=uploads.reduce((n,b)=>n+new DataView(b).getUint32(40,true)/2,0);assert.equal(frames,64*2048+333);
 assert.equal(vm.runInContext('pending()',context),false);
 vm.runInContext('resetView()',context);assert.equal(vm.runInContext('document.body.dataset.stage',context),'idle');
 failures=2;await vm.runInContext('startRecording()',context);
 for(let i=0;i<64;i++)capture.port.onmessage({data:{samples:new Float32Array(2048).fill(.1)}});
 await vm.runInContext('stopRecording()',context);
 assert.equal(vm.runInContext('pending()',context),true);assert.ok(vm.runInContext('session.parts.length',context)>0);
 await vm.runInContext('finishSaving()',context);assert.equal(vm.runInContext('pending()',context),false);assert.equal(uploads.length,2);assert.equal(finishCount,2);
 vm.runInContext('resetView()',context);await vm.runInContext('startRecording()',context);const starts=startCount,recordId=record.id;stopped=false;
 capture.port.onmessage({data:{samples:new Float32Array(32000).fill(.1)}});
 await vm.runInContext('pauseRecording()',context);assert.equal(vm.runInContext('session.paused',context),true);assert.equal(vm.runInContext('session.context.state',context),'suspended');assert.ok(stopped);assert.equal(track.onended,null);assert.equal(el('recordState').textContent,'已暂停');assert.equal(el('pauseRecording').textContent,'继续录音');
 const pausedFrames=vm.runInContext('session.capturedFrames',context);vm.runInContext('updateTimer()',context);const pausedTimer=el('recordTimer').textContent;
 capture.port.onmessage({data:{samples:new Float32Array(32000).fill(.9)}});vm.runInContext('updateTimer()',context);assert.equal(vm.runInContext('session.capturedFrames',context),pausedFrames);assert.equal(el('recordTimer').textContent,pausedTimer);
 failDevice=true;await vm.runInContext('resumeRecording()',context);assert.equal(vm.runInContext('session.paused',context),true);assert.equal(vm.runInContext('session.accepting',context),false);
 failDevice=false;await vm.runInContext('resumeRecording()',context);assert.equal(record.id,recordId);assert.equal(startCount,starts);assert.equal(vm.runInContext('session.paused',context),false);capture.port.onmessage({data:{flushed:true,id:1}});assert.equal(vm.runInContext('session.accepting',context),true);
 capture.port.onmessage({data:{samples:new Float32Array(16000).fill(.2)}});await vm.runInContext('pauseRecording()',context);await vm.runInContext('resumeRecording()',context);
 capture.port.onmessage({data:{samples:new Float32Array(8000).fill(.3)}});await vm.runInContext('stopRecording()',context);
 assert.equal(startCount,starts);assert.equal(uploads.length,3);assert.equal(uploads.reduce((n,b)=>n+new DataView(b).getUint32(40,true)/2,0),56000);assert.equal(vm.runInContext('session.capturedFrames',context),56000);
 assert.equal(new DataView(uploads[0]).getInt16(44,true),3277);assert.equal(new DataView(uploads[1]).getInt16(44,true),6553);assert.equal(new DataView(uploads[2]).getInt16(44,true),9830);
 vm.runInContext('resetView()',context);await vm.runInContext('startRecording()',context);capture.port.onmessage({data:{samples:new Float32Array(1000).fill(.1)}});await vm.runInContext('pauseRecording()',context);await vm.runInContext('stopRecording()',context);assert.equal(vm.runInContext('pending()',context),false);assert.equal(uploads.length,1);assert.equal(new DataView(uploads[0]).getUint32(40,true)/2,1000);
 console.log('Pause/resume: microphone released, paused audio ignored, timer frozen, same recording, failed resume recovery, repeated pauses and stop while paused OK');
 batchRecords=[{...record,id:'a'.repeat(32),status:'done',title:'可删除记录'},{...record,id:'b'.repeat(32),status:'error',title:'失败记录'},{...record,id:'c'.repeat(32),status:'recording',title:'正在录音'}];context.batchFixture=batchRecords;
 vm.runInContext('session=null;history=batchFixture;selected=history[0].id;current=history[0];checked=new Set([history[0].id,history[1].id]);renderHistory()',context);
 assert.equal(el('deleteBatch').disabled,false);el('deleteBatch').onclick();assert.ok(el('deleteTitle').textContent.includes('2 条'));assert.equal(deleteCalls.length,0);
 await el('deleteForm').onsubmit({preventDefault(){},submitter:{value:'cancel'}});assert.equal(deleteCalls.length,0);assert.equal(el('deleteDialog').open,false);
 el('deleteBatch').onclick();blockedDelete=true;
 await el('deleteForm').onsubmit({preventDefault(){},submitter:{value:'delete'}});
 assert.deepEqual(deleteCalls,['a'.repeat(32),'b'.repeat(32)]);assert.equal(vm.runInContext('checked.size',context),1);assert.equal(vm.runInContext('checked.has("b".repeat(32))',context),true);assert.ok(el('meetingNotice').textContent.includes('1 项未删除'));assert.equal(vm.runInContext('current',context),null);
 blockedDelete=false;el('deleteBatch').onclick();el('deleteScope').value='audio';await el('deleteForm').onsubmit({preventDefault(){},submitter:{value:'delete'}});assert.equal(vm.runInContext('checked.size',context),0);assert.equal(batchRecords.length,2);
 console.log('Batch deletion: confirmation, error-record selection, partial failure retention and audio-only mode OK');
 console.log('Meeting client: start, continuous capture, ordered uploads, final tail, stop tracks, save failure recovery and finish OK');
})().catch(e=>{console.error(e);process.exitCode=1});
