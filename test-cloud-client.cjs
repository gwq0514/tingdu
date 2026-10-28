const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{value:'chrome',textContent:'',closest(){return this},querySelector(){return button}});return nodes.get(id)};
const button={value:'delete',disabled:false},form=get('deleteForm');let submits=0,deletes=0,state={status:'done',summary_status:'running'},message='';
form.onsubmit=async()=>{submits++};
const c=vm.createContext({document:{getElementById:get,querySelectorAll:()=>[]},MutationObserver:class{observe(){}},setTimeout,clearTimeout,AbortController,console,
 renderHistory(){},renderRecord(){},filteredHistory:()=>[],names:{},notice:t=>message=t,
 api:async()=>state,fetch:async()=>{deletes++;return{ok:false,status:409,json:async()=>({detail:'请等待后台处理完成'})}},deleting:false,deleteTargets:[{id:'test',title:'Synthetic fixture'}]});
vm.runInContext(fs.readFileSync('static/cloud-client.js','utf8'),c);
(async()=>{
 assert.equal(get('browser').hidden,true);assert.equal(get('subBrowser').hidden,true);assert.equal(get('browser').value,'');
 await form.onsubmit({preventDefault(){},submitter:button});assert.equal(submits,0);assert.equal(deletes,0);assert.match(message,/总结处理中/);assert.equal(button.disabled,false);
 state={status:'done',summary_status:'done',diarization_status:'running'};await form.onsubmit({preventDefault(){},submitter:button});assert.equal(submits,0);assert.match(message,/发言人处理中/);
 state={status:'done',summary_status:'done',diarization_status:'done'};await form.onsubmit({preventDefault(){},submitter:button});assert.equal(submits,1);
 await assert.rejects(()=>c.api('/api/meetings/test',{method:'DELETE'}),/后台处理完成/);
 console.log('Cloud-only UI: browser controls hidden, pending work blocks deletion before any mutation, completed records proceed, server errors retained.');
})().catch(e=>{console.error(e);process.exitCode=1});
