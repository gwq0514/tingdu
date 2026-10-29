(function(root){
 function message(s){
  const pending=s.pending_audio_chunks||0,queued=(s.waiting_inference||0)+(s.queued_background_jobs||0);
  if(s.state==='error')return '上次处理未完成，原声与已有文字保留，可稍后重试';
  if(s.state==='yielding')return '正在为录音释放模型资源，总结和视频稍后继续';
  if(s.state==='switching'||s.state==='loading')return '正在准备模型，录音采集可继续，文字会稍后更新';
  if(s.active)return (s.operation_label||'正在处理')+(pending?' · 待转写 '+pending+' 段':'')+(queued?' · 另有任务排队':'');
  if(s.recording_priority)return pending?'录音优先 · 待转写 '+pending+' 段':'录音优先 · 视频和总结将在空闲后继续';
  if(queued||s.state==='waiting')return '任务按顺序处理，模型切换时可能需要等待';
  return '试运行 · 当前空闲，首次处理需要准备模型';
 }
 function apply(s,doc){
  if(s.profile!=='server-2gb'){const p=doc.querySelector('header .pill');if(p)p.textContent='本地处理 · 隐私优先';return;}
  doc.body.dataset.runtimeProfile=s.profile;
  for(const id of ['browser','subBrowser']){const select=doc.getElementById(id);if(select){select.value='';select.disabled=true;select.title='云端无法读取你电脑的浏览器登录状态'}}
  for(const id of ['browserAccessNote','subBrowserAccessNote']){const note=doc.getElementById(id);if(note)note.textContent='需要登录的内容，请先在本机获取媒体后上传。'}
  doc.getElementById('runtimeNotice').hidden=false;
  doc.getElementById('runtimeMessage').textContent=message(s);
  const pill=doc.querySelector('header .pill');if(pill)pill.textContent='云端处理 · 本机保存';
  const storage=doc.getElementById('storageHint');if(storage)storage.textContent='历史与音频保存在当前浏览器；清除网站数据会删除它们，请导出重要资料。';
  const welcome=doc.querySelector('#storageWelcome p');if(welcome)welcome.textContent='历史与音频默认保存在当前浏览器，可额外另存文件夹。内容会临时上传处理，本机保存成功后清理服务器副本；未完成保存的副本24小时到期后清理（仍在处理时延后）。';
  const frame=doc.getElementById('recordingFrame');
  try{const d=frame?.contentDocument;if(d){d.body.dataset.runtimeProfile=s.profile;const note=d.getElementById('storageNote');if(note)note.textContent='原声、原文和总结保存在此浏览器；处理副本按会话隔离，本机保存成功后清理。请导出重要资料，清除网站数据会删除本机历史。';const hint=d.querySelector('.model-hint');if(hint)hint.textContent='完整模型按需准备，忙时将排队，请结合原文核对。'}}catch{}
 }
 root.RuntimeStatus={message,apply};
 if(typeof module!=='undefined')module.exports=root.RuntimeStatus;
 if(typeof document==='undefined')return;
 const open=document.getElementById('runtimeDetails'),close=document.getElementById('closeRuntimeDialog');
 if(open)open.onclick=()=>document.getElementById('runtimeDialog').showModal();
 if(close)close.onclick=()=>document.getElementById('runtimeDialog').close();
 let enabled=false,inFlight=false;
 async function poll(){if(inFlight)return;inFlight=true;try{const r=await fetch('/api/runtime');if(!r.ok)throw Error();const s=await r.json();enabled=s.profile==='server-2gb';apply(s,document)}catch{if(enabled)document.getElementById('runtimeMessage').textContent='处理服务暂时未连接，请留意录音保存状态并保留当前页面';}finally{inFlight=false}}
 poll();setInterval(poll,3000);
})(typeof globalThis!=='undefined'?globalThis:this);
