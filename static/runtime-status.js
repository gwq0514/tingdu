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
  for(const id of ['browserAccessNote','subBrowserAccessNote']){const note=doc.getElementById(id);if(note)note.textContent='云端试运行无法读取你电脑的浏览器登录状态。需要登录的内容，请先在本机获取媒体后上传测试。'}
  doc.getElementById('runtimeNotice').hidden=false;
  doc.getElementById('runtimeMessage').textContent=message(s);
  const pill=doc.querySelector('header .pill');if(pill)pill.textContent='完整模型 · 试运行';
  const storage=doc.getElementById('storageHint');if(storage)storage.textContent='保存文件夹位于你的设备。当前试运行仍保留处理工作文件，请仅使用测试素材。';
  const welcome=doc.querySelector('#storageWelcome p');if(welcome)welcome.textContent='保存文件夹位于你的设备。部署验证期间，内容会交给测试服务处理，请使用测试素材。';
  const frame=doc.getElementById('recordingFrame');
  try{const d=frame?.contentDocument;if(d){d.body.dataset.runtimeProfile=s.profile;const note=d.getElementById('storageNote');if(note)note.textContent='部署验证期间，内容由测试服务处理并保留工作文件。请使用测试素材并自行导出；尚未开放多人隔离和自动清理。';const hint=d.querySelector('.model-hint');if(hint)hint.textContent='完整模型按需准备，忙时将排队，请结合原文核对。'}}catch{}
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
