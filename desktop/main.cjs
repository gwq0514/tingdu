const {app,BrowserWindow,dialog,session,shell,Menu}=require('electron');
const {spawn}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');const http=require('node:http');
const {ORIGIN,localOrigin,allowedPermission}=require('./policy.cjs');
let win,engine,ollama,log,quitting=false,booting=false;
app.setName('听读');
if(!app.requestSingleInstanceLock())app.quit();
app.on('second-instance',()=>{if(win){win.show();win.focus()}});
function getJSON(url,timeout=1500){return new Promise((resolve,reject)=>{const req=http.get(url,r=>{let body='';r.on('data',c=>body+=c);r.on('end',()=>{try{if(r.statusCode!==200)throw Error('HTTP '+r.statusCode);resolve(JSON.parse(body))}catch(e){reject(e)}})});req.setTimeout(timeout,()=>req.destroy(Error('timeout')));req.on('error',reject)})}
async function waitFor(url,process,timeout=90000){const until=Date.now()+timeout;while(Date.now()<until){if(process&&process.exitCode!==null)throw Error('本地服务提前退出，请查看日志。');try{return await getJSON(url)}catch{}await new Promise(r=>setTimeout(r,350))}throw Error('本地服务启动超时。请查看日志。')}
function child(binary,args,env){const p=spawn(binary,args,{env:{...process.env,...env},stdio:['ignore','pipe','pipe']});p.stdout.pipe(log,{end:false});p.stderr.pipe(log,{end:false});p.on('error',e=>log.write(e.message+'\n'));return p}
function copyMissing(source,target){fs.mkdirSync(target,{recursive:true});for(const e of fs.readdirSync(source,{withFileTypes:true})){const from=path.join(source,e.name),to=path.join(target,e.name);if(e.isDirectory())copyMissing(from,to);else if(!fs.existsSync(to)){fs.copyFileSync(from,to);fs.chmodSync(to,0o600)}}}
async function boot(){
 if(booting)return;booting=true;
 const base=app.isPackaged?path.join(process.resourcesPath,'engine'):path.resolve(__dirname,'../build/desktop-resources');
 const data=path.join(app.getPath('userData'),'data');fs.mkdirSync(data,{recursive:true,mode:0o700});
 log=fs.createWriteStream(path.join(app.getPath('userData'),'engine.log'),{flags:'a',mode:0o600});
 try{
  // Do not accidentally attach to another application's or the web edition's engine.
  try{await getJSON(ORIGIN+'/api/storage');throw Error('听读桌面版端口已被占用，请关闭旧实例后重试。')}catch(e){if(e.message.includes('端口'))throw e}
  copyMissing(path.join(base,'models'),path.join(data,'models'));
  copyMissing(path.join(base,'llm'),path.join(data,'llm'));
  const ollamaBin=path.join(base,'ollama','ollama');
  const env={OLLAMA_HOST:'127.0.0.1:18766',OLLAMA_MODELS:path.join(data,'ollama'),OLLAMA_NO_CLOUD:'1',OLLAMA_KEEP_ALIVE:'5m'};
  try{await getJSON('http://127.0.0.1:18766/api/tags');throw Error('听读模型端口已被占用，请关闭旧实例后重试。')}catch(e){if(e.message.includes('端口'))throw e}
  ollama=child(ollamaBin,['serve'],env);await waitFor('http://127.0.0.1:18766/api/tags',ollama);
  const tags=await getJSON('http://127.0.0.1:18766/api/tags');
  if(!tags.models.some(m=>m.name==='tingdu-qwen:latest')){
   const setup=child(ollamaBin,['create','tingdu-qwen','-f',path.join(data,'llm','Modelfile')],env);
   await new Promise((resolve,reject)=>{setup.once('error',reject);setup.once('exit',code=>code===0?resolve():reject(Error('内置总结模型初始化失败')))});
  }
  engine=child(path.join(base,'backend','tingdu-engine'),[],{TINGDU_DATA_DIR:data,TINGDU_PORT:'18765',TINGDU_OLLAMA_URL:'http://127.0.0.1:18766',PATH:path.join(base,'bin')+path.delimiter+process.env.PATH});
  await waitFor(ORIGIN+'/api/storage',engine);
  engine.on('exit',()=>{if(!quitting){dialog.showErrorBox('本地服务已退出','请重新启动听读。你的已保存资料仍保留在本机。')}});
  await win.loadURL(ORIGIN);
 }catch(e){dialog.showErrorBox('听读启动失败',e.message+'\n日志：'+app.getPath('userData')+'/engine.log');quitting=true;app.quit()}
}
app.whenReady().then(async()=>{
 session.defaultSession.setPermissionRequestHandler((wc,permission,callback,details)=>callback(localOrigin(wc.getURL())&&localOrigin(details.requestingUrl||wc.getURL())&&allowedPermission(permission,details)));
 session.defaultSession.setPermissionCheckHandler((wc,permission,origin,details)=>localOrigin(wc?.getURL()||'')&&localOrigin(origin)&&(permission==='media'?details.mediaType==='audio':allowedPermission(permission,details)));
 session.defaultSession.setDevicePermissionHandler(()=>false);
 Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'听读',submenu:[{role:'about'},{label:'打开数据文件夹',click:()=>shell.openPath(path.join(app.getPath('userData'),'data'))},{label:'打开日志文件夹',click:()=>shell.openPath(app.getPath('userData'))},{type:'separator'},{role:'quit'}]},{label:'编辑',submenu:[{role:'undo'},{role:'redo'},{type:'separator'},{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]},{label:'窗口',submenu:[{role:'minimize'},{role:'zoom'},{role:'front'}]}]));
 win=new BrowserWindow({width:1360,height:900,minWidth:780,minHeight:560,backgroundColor:'#ffffff',title:'听读',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
 win.webContents.setWindowOpenHandler(({url})=>{if(/^https?:\/\//.test(url)&&!localOrigin(url))shell.openExternal(url);return {action:'deny'}});
 win.webContents.on('will-navigate',(event,url)=>{if(!localOrigin(url)){event.preventDefault();if(/^https?:\/\//.test(url))shell.openExternal(url)}});
 win.on('close',event=>{if(quitting)return;event.preventDefault();win.webContents.executeJavaScript(`(()=>{const f=document.getElementById('recordingFrame');return !!f?.contentWindow?.pending?.()})()`).then(async active=>{if(active){const {response}=await dialog.showMessageBox(win,{type:'warning',message:'录音尚未保存完成',detail:'请先结束并保存录音，再退出听读。',buttons:['返回录音','仍然退出'],defaultId:0,cancelId:0});if(response===0)return}quitting=true;app.quit()}).catch(()=>{quitting=true;app.quit()})});
 await win.loadFile('loading.html');boot();
});
app.on('before-quit',event=>{if(!quitting&&win&&!win.isDestroyed()){event.preventDefault();win.close();return}engine?.kill('SIGTERM');ollama?.kill('SIGTERM')});
app.on('window-all-closed',()=>{quitting=true;app.quit()});
app.on('activate',()=>{win?.show()});
