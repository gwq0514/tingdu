/* Loaded by cloud_ui.py only. Desktop HTML and recording controller are unchanged. */
(function(){
 const node=id=>document.getElementById(id);
 for(const id of ['browser','subBrowser']){const el=node(id);if(el){el.value='';el.disabled=true;el.hidden=true;if(id==='subBrowser')el.closest('label').hidden=true;}}
 const retry=[...document.querySelectorAll('button')].find(b=>b.textContent==='使用所选浏览器重试');if(retry)retry.textContent='刷新视频列表';
 const info=node('subscriptionInfo');if(info){const update=()=>{if(info.textContent.includes('本机浏览器登录状态'))info.textContent='每次展示 10 个公开视频；需要登录的内容，请在本机获取媒体后上传。'};new MutationObserver(update).observe(info,{childList:true});update();}
 if(window.CloudStore){
  const button=document.createElement('button');button.className='sub';button.textContent='本机保存状态';const header=document.querySelector('header');if(header)header.append(button);
  const savedDialog=document.createElement('dialog');savedDialog.style.cssText='max-width:520px;padding:24px;border:1px solid #dbeafe;border-radius:14px;color:#334155';document.body.append(savedDialog);
  button.onclick=async()=>{const records=await CloudStore.all('records'),assets=await CloudStore.all('assets');let remote=[];try{const response=await CloudStore.native('/api/jobs');if(response.ok)remote=await response.json();}catch{}const pending=records.filter(x=>x.record.cloud_legacy_pending).length;savedDialog.replaceChildren();const title=document.createElement('h2');title.textContent='当前浏览器的保存状态';const detail=document.createElement('p');detail.style.lineHeight='1.8';detail.textContent='本机已保存 '+records.filter(x=>x.record._cloud_saved).length+' 条资料，音频/封面共 '+(assets.reduce((n,x)=>n+x.blob.size,0)/1024/1024).toFixed(1)+' MB。服务器仍有 '+remote.length+' 条处理副本。'+(pending?'旧资料副本待你确认后清理。':'本机保存成功的临时副本会自动清理。');const note=document.createElement('p');note.textContent='资料只属于此浏览器。清除网站数据、更换浏览器或无痕窗口不会保留这份历史，请导出重要资料。';const close=document.createElement('button');close.textContent='知道了';close.onclick=()=>savedDialog.close();savedDialog.append(title,detail,note,close);savedDialog.showModal();};
  const storageText='音频、原文和总结保存在此浏览器。本机保存成功后清理服务器副本；未保存的临时文件24小时到期后清理（仍在处理时延后）。请导出重要资料，清除网站数据会删除本机历史。';
  window.addEventListener('cloud-storage-error',event=>{const note=node('meetingNotice')||node('libraryNotice');if(note)note.textContent=event.detail;});
  if(CloudStore.lastError){const note=node('meetingNotice')||node('libraryNotice');if(note)note.textContent='本机保存未完成：'+CloudStore.lastError;}
  const welcome=document.querySelector('#storageWelcome p');if(welcome)welcome.textContent=storageText;
  const dialog=document.querySelectorAll('#runtimeDialog p');if(dialog.length)dialog[dialog.length-1].textContent=storageText+' 云端单文件100MB，单次录音10分钟，每个会话最多2个待处理任务。';
  const uploaded=node('uploadPanel')?.querySelector('p');if(uploaded)uploaded.textContent='支持 MP4、MOV、MP3、WAV 等，云端最大100MB。';
 }
 if(window.CloudStore&&typeof renderDetails==='function'){
  const details=renderDetails;renderDetails=async function(r){await details(r);node('storageDetail').textContent=r._cloud_local?'已保存到当前浏览器，可直接回听、阅读和导出。请导出重要资料，清除网站数据会删除本机历史。':'正在云端临时处理并保存到当前浏览器，请保持页面打开。';};
  const library=renderLibrary;renderLibrary=function(...args){library(...args);for(const label of document.querySelectorAll('.resource-footer small'))if(label.textContent==='引擎本地工作文件')label.textContent='本机浏览器资料 / 临时处理任务';};
 }
 if(typeof renderHistory!=='function')return;
 const waiting=r=>['queued','running'].includes(r.diarization_status)?'发言人处理中':r.summary_status==='running'?'总结处理中':['done','error'].includes(r.status)?'':names[r.status]||'整理中';
 window.addEventListener?.('cloud-record-cached',event=>{if(session?.finished&&session.id===event.detail.id)session.parts=[];});window.addEventListener?.('cloud-record-deleted',event=>{if(session?.finished&&session.id===event.detail.id)session=null;});
 const originalRender=renderHistory;
 renderHistory=function(){originalRender();const groups=new Map();for(const r of filteredHistory()){const key=r.project||'';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}const rows=[...document.querySelectorAll('.history-item')],records=[...groups.values()].flat();rows.forEach((row,i)=>{const label=waiting(records[i])||(window.CloudStore?(records[i]._cloud_local?'本机已保存':'等待本机保存'):'');if(label){const meta=row.querySelector('.history-meta');meta.textContent+=' · '+label;}});};
 const originalRecord=renderRecord;renderRecord=function(r){originalRecord(r);const label=waiting(r);if(label&&r.status==='done'){node('meetingMeta').textContent+=' · '+label;node('recordState').textContent=label;}if(window.CloudStore){node('storageNote').textContent=r._cloud_local?(r.cloud_legacy_pending?'旧资料已保存在此浏览器，可回听和导出；服务器旧副本待确认后清理。':'已保存在此浏览器，可回听和导出；服务器临时副本会在后台清理。'):'正在处理或保存到此浏览器，请保留页面。服务器临时文件24小时到期后清理（仍在处理时延后）。';if(r._cloud_local)node('retryTranscript').hidden=true;}};
 if(window.CloudStore){const timer=updateTimer;updateTimer=function(){timer();if(session?.recording&&!session.stopping&&session.capturedFrames>=600*16000){notice('已达到云端10分钟上限，正在保存录音。');stopRecording();}};}
 const originalApi=api;
 api=async function(url,options){if(options?.method!=='DELETE')return originalApi(url,options);const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);try{const r=await fetch(url,{...options,signal:controller.signal});let d;try{d=await r.json()}catch{throw Error('删除请求未完成（HTTP '+r.status+'），请刷新核对记录后重试。')}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'删除未完成，请刷新核对后重试。');return d;}catch(e){if(e.name==='AbortError')throw Error('删除请求等待超时，请刷新核对结果；尚未确认删除成功。');throw e;}finally{clearTimeout(timer);}};
 const form=node('deleteForm'),originalSubmit=form.onsubmit;let checking=false;
 form.onsubmit=async function(e){e.preventDefault();if(e.submitter?.value==='cancel')return originalSubmit(e);if(checking||deleting)return;checking=true;const button=e.submitter||form.querySelector('[value="delete"]');button.disabled=true;node('deleteError').textContent='正在检查所选录音的后台状态…';try{for(const target of deleteTargets){const r=await originalApi('/api/jobs/'+target.id);const label=waiting(r);if(label)throw Error('“'+target.title+'”仍在'+label+'，请完成后再删除。本次未删除任何文件。');}await originalSubmit({...e,preventDefault(){},submitter:button});}catch(error){node('deleteError').textContent=error.message;notice(error.message);}finally{checking=false;button.disabled=false;}};
})();
