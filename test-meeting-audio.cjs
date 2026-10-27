const assert=require('node:assert/strict');
const audio=require('./static/meeting-audio.js');
(async()=>{
 for(const rate of [16000,44100,48000]){
  const samples=Float32Array.from({length:rate},(_,i)=>Math.sin(i*2*Math.PI*440/rate)*.5);
  const buffer=audio.wav(samples,rate),v=new DataView(buffer);
  assert.equal(buffer.byteLength,32044);assert.equal(v.getUint32(24,true),16000);assert.equal(v.getUint16(22,true),1);assert.equal(v.getUint32(40,true),32000);
  assert.ok(Math.abs(v.getInt16(44+400*2,true))<3000);
  const combined=await audio.backup([buffer,buffer]).arrayBuffer();assert.equal(combined.byteLength,64044);assert.equal(new DataView(combined).getUint32(40,true),64000);
  assert.deepEqual(new Uint8Array(combined,44,32000),new Uint8Array(buffer,44));
 }
 assert.deepEqual([...audio.join([new Float32Array([1,2]),new Float32Array([3])])],[1,2,3]);
 console.log('Meeting capture: 16k/44.1k/48k resampling, WAV headers, ordered samples and recovery backup OK');
})();
const fs=require('node:fs'),vm=require('node:vm');
let Processor;
vm.runInNewContext(fs.readFileSync('static/meeting-worklet.js','utf8'),{Float32Array,AudioWorkletProcessor:class{constructor(){this.messages=[];this.port={postMessage:m=>this.messages.push(m)}}},registerProcessor:(name,P)=>Processor=P});
const capture=new Processor();
for(let i=0;i<17;i++)capture.process([[new Float32Array(128).fill(.25),new Float32Array(128).fill(.75)]]);
capture.port.onmessage({data:'flush'});
assert.equal(capture.messages[0].samples.length,2048);assert.equal(capture.messages[1].samples.length,128);assert.equal(capture.messages[0].samples[0],.5);assert.equal(capture.messages[2].flushed,true);
const pausedCapture=new Processor();pausedCapture.process([[new Float32Array(128).fill(.1)]]);pausedCapture.port.onmessage({data:{type:'pause',id:1}});
assert.equal(pausedCapture.messages[1].id,1);assert.equal(pausedCapture.messages[1].flushed,true);const before=pausedCapture.messages.length;
pausedCapture.process([[new Float32Array(2048).fill(.9)]]);assert.equal(pausedCapture.messages.length,before);assert.equal(pausedCapture.used,0);
pausedCapture.port.onmessage({data:'resume'});pausedCapture.process([[new Float32Array(128).fill(.2)]]);pausedCapture.port.onmessage({data:{type:'flush',id:2}});
assert.equal(pausedCapture.messages[2].samples.length,128);assert.ok(Math.abs(pausedCapture.messages[2].samples[0]-.2)<1e-6);assert.equal(pausedCapture.messages[3].id,2);
console.log('AudioWorklet pause/resume: tail preserved, paused microphone samples dropped, matching flush acknowledgements OK');
console.log('AudioWorklet: continuous capture, mono mixing, tail flush and acknowledgement OK');

const records=require('./static/export-utils.js');
const grouped=records.entries([{id:'a'.repeat(32),title:'录音一',source:'meeting',project:'项目甲',text:'测试',segments:[]},{id:'b'.repeat(32),title:'录音二',source:'meeting',project:'',text:'测试',segments:[]}],'markdown',true);
assert.equal(grouped[0].name,'项目甲/录音一--aaaaaaaa.md');assert.equal(grouped[1].name,'未分类/录音二--bbbbbbbb.md');assert.ok(grouped[0].data.includes('项目：项目甲'));
console.log('User projects: grouped export paths and record project metadata OK');

const speakerRecord={id:'c'.repeat(32),title:'发言人导出',source:'meeting',project:'',text:'你好',segments:[{start:1,end:2,text:'你好',speaker:'发言人 1'}]};
assert.ok(records.markdown(speakerRecord).includes('发言人 1：你好'));assert.ok(records.entries([speakerRecord],'text')[0].data.includes('发言人 1：你好'));
console.log('Speaker labels included in Markdown and TXT exports OK');
