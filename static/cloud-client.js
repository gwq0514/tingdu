/* Loaded by cloud_ui.py only. Desktop HTML and recording controller are unchanged. */
(function(){
 const node=id=>document.getElementById(id);
 for(const id of ['browser','subBrowser']){const el=node(id);if(el){el.value='';el.disabled=true;el.hidden=true;if(id==='subBrowser')el.closest('label').hidden=true;}}
 const retry=[...document.querySelectorAll('button')].find(b=>b.textContent==='使用所选浏览器重试');if(retry)retry.textContent='刷新视频列表';
 const info=node('subscriptionInfo');if(info){const update=()=>{if(info.textContent.includes('本机浏览器登录状态'))info.textContent='每次展示 10 个公开视频；需要登录的内容，请在本机获取媒体后上传。'};new MutationObserver(update).observe(info,{childList:true});update();}
 if(typeof renderHistory!=='function')return;
 const waiting=r=>['queued','running'].includes(r.diarization_status)?'发言人处理中':r.summary_status==='running'?'总结处理中':['done','error'].includes(r.status)?'':names[r.status]||'整理中';
 const originalRender=renderHistory;
 renderHistory=function(){originalRender();const groups=new Map();for(const r of filteredHistory()){const key=r.project||'';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}const rows=[...document.querySelectorAll('.history-item')],records=[...groups.values()].flat();rows.forEach((row,i)=>{const label=waiting(records[i]);if(label){const meta=row.querySelector('.history-meta');meta.textContent+=' · '+label;}});};
 const originalRecord=renderRecord;renderRecord=function(r){originalRecord(r);const label=waiting(r);if(label&&r.status==='done'){node('meetingMeta').textContent+=' · '+label;node('recordState').textContent=label;}};
 const originalApi=api;
 api=async function(url,options){if(options?.method!=='DELETE')return originalApi(url,options);const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);try{const r=await fetch(url,{...options,signal:controller.signal});let d;try{d=await r.json()}catch{throw Error('删除请求未完成（HTTP '+r.status+'），请刷新核对记录后重试。')}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'删除未完成，请刷新核对后重试。');return d;}catch(e){if(e.name==='AbortError')throw Error('删除请求等待超时，请刷新核对结果；尚未确认删除成功。');throw e;}finally{clearTimeout(timer);}};
 const form=node('deleteForm'),originalSubmit=form.onsubmit;let checking=false;
 form.onsubmit=async function(e){e.preventDefault();if(e.submitter?.value==='cancel')return originalSubmit(e);if(checking||deleting)return;checking=true;const button=e.submitter||form.querySelector('[value="delete"]');button.disabled=true;node('deleteError').textContent='正在检查所选录音的后台状态…';try{for(const target of deleteTargets){const r=await originalApi('/api/jobs/'+target.id);const label=waiting(r);if(label)throw Error('“'+target.title+'”仍在'+label+'，请完成后再删除。本次未删除任何文件。');}await originalSubmit({...e,preventDefault(){},submitter:button});}catch(error){node('deleteError').textContent=error.message;notice(error.message);}finally{checking=false;button.disabled=false;}};
})();
