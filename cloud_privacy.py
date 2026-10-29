"""Anonymous browser capabilities and temporary, owner-isolated cloud workspaces.
Only installed in the opt-in cloud privacy profile. Never used by the desktop.
"""
import contextvars,hashlib,hmac,json,os,re,secrets,shutil,threading,time
from pathlib import Path
from fastapi import HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

owner_context=contextvars.ContextVar('cloud_owner',default=None)
ip_context=contextvars.ContextVar('cloud_ip',default='')
creation_lock=threading.RLock()
admissions={}
COOKIE='__Host-tingdu-session'
MAX_UPLOAD=100*1024**2
MAX_RECORDING_SECONDS=600
TTL=24*3600

def enabled(engine):return engine.LOW_MEMORY and os.environ.get('TINGDU_CLOUD_PRIVACY')=='1'
def owner():return owner_context.get()
def metadata(engine):
    if not enabled(engine):return engine.DATA
    who=owner()
    if not who:raise HTTPException(401,'请刷新页面建立自己的处理会话')
    p=engine.DATA/'.sessions'/who;p.mkdir(parents=True,exist_ok=True);return p

def owned(engine,rec):return not enabled(engine) or owner() is None or rec.get('cloud_owner')==owner()
def clean(value):
    if isinstance(value,list):return [clean(x) for x in value]
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('cloud_owner','local_path','processing_directory')}
    return value

def terminal(r):return not r.get('cloud_ephemeral') and r.get('status') in ('done','error') and r.get('summary_status')!='running' and r.get('diarization_status') not in ('queued','running')

class Guard(BaseHTTPMiddleware):
    def __init__(self,app,engine):
        super().__init__(app);self.engine=engine;self.lock=threading.RLock();self.rates={}
        p=engine.DATA/'.cloud-session-key'
        try:
            fd=os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32))
        except FileExistsError:pass
        self.key=p.read_bytes()
    def issue(self):
        token=secrets.token_hex(32);return token+'.'+hmac.new(self.key,token.encode(),hashlib.sha256).hexdigest()
    def verify(self,value):
        if not re.fullmatch(r'[a-f0-9]{64}\.[a-f0-9]{64}',value or ''):return None
        token,sig=value.split('.')
        return hashlib.sha256(token.encode()).hexdigest() if hmac.compare_digest(sig,hmac.new(self.key,token.encode(),hashlib.sha256).hexdigest()) else None
    async def dispatch(self,request,call_next):
        if not enabled(self.engine):return await call_next(request)
        path=request.url.path
        if path.startswith('/admin') or path.startswith('/api/admin'):return JSONResponse({'detail':'未开放此入口'},404)
        if path.startswith('/static/'):return await call_next(request)
        cookie=request.cookies.get(COOKIE,'');who=self.verify(cookie)
        if not who:
            if path not in ('/','/meetings','/api/cloud/session','/private/migrate'):return JSONResponse({'detail':'请刷新页面建立自己的处理会话'},401)
            cookie=self.issue();who=self.verify(cookie)
        # Secure-cookie based capabilities require same-origin writes, never trust Host rewrites.
        if request.method not in ('GET','HEAD','OPTIONS'):
            origins=set(x.strip() for x in os.environ.get('TINGDU_ALLOWED_ORIGINS','').split(',') if x.strip())
            if request.headers.get('origin') not in origins:return JSONResponse({'detail':'请从本站页面操作'},403)
            if int(request.headers.get('content-length','0') or 0)>MAX_UPLOAD+1024*1024:return JSONResponse({'detail':'云端单文件最多100MB'},413)
        context=owner_context.set(who)
        ip_token=ip_context.set(hashlib.sha256((request.headers.get('x-forwarded-for') or (request.client.host if request.client else '')).encode()).hexdigest())
        try:
            response=await call_next(request)
        finally:
            owner_context.reset(context);ip_context.reset(ip_token)
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='same-origin'
        response.set_cookie(COOKIE,cookie,max_age=7*86400,httponly=True,secure=True,samesite='strict',path='/')
        return response

def reserve(engine):
    if not enabled(engine) or owner() is None:return
    records=[json.loads(p.read_text()) for p in engine.DATA.glob('*/record.json')]
    mine=[r for r in records if r.get('cloud_owner')==owner()]
    if sum(not terminal(r) for r in mine)>=2:raise HTTPException(429,'你已有2个任务处理中，请完成后再导入')
    if sum(not terminal(r) for r in records if r.get('cloud_owner'))>=8:raise HTTPException(429,'当前处理队列已满，请稍后重试')
    if len([r for r in mine if time.time()-__import__('datetime').datetime.fromisoformat(r['created_at']).timestamp()<3600])>=20:raise HTTPException(429,'每个会话每小时最多创建20个任务')
    if shutil.disk_usage(engine.DATA).free<2*1024**3:raise HTTPException(503,'临时处理空间不足，请稍后重试')
    now=time.time()
    for key in list(admissions):
        admissions[key]=[x for x in admissions[key] if now-x<3600]
        if not admissions[key]:admissions.pop(key)
    for key,limit in ((owner(),20),('ip:'+ip_context.get(),60),('global',120)):
        if len(admissions.get(key,[]))>=limit:raise HTTPException(429,'当前使用次数已达上限，请稍后重试')
    for key in (owner(),'ip:'+ip_context.get(),'global'):admissions.setdefault(key,[]).append(now)

def register(app,engine):
    app.add_middleware(Guard,engine=engine)
    @app.get('/api/cloud/session')
    def session():return {'mode':'browser-local','temporary_hours':24,'max_upload_mb':100,'max_recording_seconds':600,'version':'1.2.0-cloud.1'}
    @app.post('/api/cloud/subscriptions/restore')
    def restore_subscription(body:dict):
        from subscriptions import creator_from_info,lock
        platform=body.get('platform');uid=str(body.get('id',''))
        if platform=='bilibili':creator=creator_from_info(platform,{'uploader_id':uid,'uploader':str(body.get('name',uid))[:120]})
        elif platform=='xiaohongshu':creator=creator_from_info(platform,{'作者ID':uid,'作者昵称':str(body.get('name',uid))[:120]})
        else:creator=None
        if not creator:raise HTTPException(400,'作者信息无效')
        p=metadata(engine)/'subscriptions.json'
        with lock:
            records=json.loads(p.read_text()) if p.exists() else []
            if not any(r['key']==creator['key'] for r in records):
                if len(records)>=50:raise HTTPException(429,'最多保存50位订阅作者')
                records.append(creator);p.write_text(json.dumps(records,ensure_ascii=False))
        return creator
    @app.post('/api/cloud/jobs/{jid}/ack')
    def ack(jid:str,body:dict):
        from meetings import deletion_lock
        with deletion_lock(jid,True):
            r=engine.read(jid)
            if r.get('cloud_legacy_pending'):raise HTTPException(409,'旧资料已迁入本机，服务器旧副本待确认后清理')
            if body.get('revision')!=r.get('cloud_revision'):raise HTTPException(409,'内容刚刚更新，请先保存最新版本')
            if not terminal(r):raise HTTPException(409,'处理仍在进行，暂不清理')
            with engine.active_chat_lock:
                if engine.active_chats.get(jid):raise HTTPException(409,'回答仍在生成，暂不清理')
            root=engine.folder(jid);stage=engine.DATA/'.deleting'/secrets.token_hex(16);stage.parent.mkdir(exist_ok=True)
            root.replace(stage);shutil.rmtree(stage)
        return {'cleaned':True}
    @app.post('/api/cloud/chat')
    def chat(body:dict):
        record=body.get('record',{});text=record.get('text','');question=body.get('question','');model=body.get('model','')
        if not isinstance(text,str) or not 1<=len(text)<=200000 or not isinstance(question,str) or len(question)>4000:raise HTTPException(400,'原文或问题长度不合法')
        if model not in engine.health()['models']:raise HTTPException(400,'模型未就绪')
        r=engine.new(str(record.get('title','本机记录'))[:120], 'meeting' if record.get('source')=='meeting' else 'text')
        r.update(status='done',text=text,segments=[],summary=record.get('summary',''),summary_status='none',cloud_ephemeral=True);engine.save(r)
        try:return engine.chat(r['id'],engine.ChatRequest(model=model,summary=bool(body.get('summary')),question=question))
        finally:
            from meetings import recording_lock
            with recording_lock(r['id']):shutil.rmtree(engine.DATA/r['id'],ignore_errors=True)
    @app.post('/api/cloud/claim-legacy')
    def claim(request:Request):
        # Set only by a dedicated Basic-Auth-protected nginx location, never on public routes.
        if not os.environ.get('TINGDU_LEGACY_CLAIM_TOKEN') or not hmac.compare_digest(request.headers.get('x-tingdu-legacy-owner',''),os.environ['TINGDU_LEGACY_CLAIM_TOKEN']):raise HTTPException(403,'请从受密码保护的旧资料迁移页操作')
        count=0
        for p in engine.DATA.glob('*/record.json'):
            r=json.loads(p.read_text())
            if not r.get('cloud_owner'):
                r['cloud_owner']=owner();r['cloud_legacy_pending']=True;engine.save(r);count+=1
        for name in ('recording-projects.json','subscriptions.json'):
            src=engine.DATA/name;dest=metadata(engine)/name
            if src.exists() and not dest.exists():shutil.copy2(src,dest)
        return {'claimed':count}
    @app.get('/private/migrate')
    def migrate():
        from fastapi.responses import HTMLResponse
        return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>旧资料迁移</title><h1>把旧资料保存到当前浏览器</h1><p>此页面须使用原 owner 密码。点击后在听读页面保持联网，请等待每条资料完成本机保存，并验证能够打开和回听。服务器旧副本会保留，待确认后再清理。请另外导出重要资料。</p><button id="claim">迁移我的旧资料</button><p id="message"></p><script>document.getElementById('claim').onclick=async()=>{const r=await fetch('/api/cloud/claim-legacy',{method:'POST'});document.getElementById('message').textContent=r.ok?'已认领旧资料，请打开听读等待本机保存。':'迁移未完成';if(r.ok)location.href='/'}</script></html>''')
    def sweep():
        while True:
            time.sleep(60)
            if not enabled(engine):continue
            state=engine.low_runtime.status()
            if state.get('active') or state.get('waiting_inference') or engine.recording_priority.busy() or engine.pool._work_queue.qsize():continue
            from meetings import recording_lock
            for p in engine.DATA.glob('*/record.json'):
                try:
                    r=json.loads(p.read_text())
                    # Legacy resources are preserved until their owner explicitly migrates them.
                    if not r.get('cloud_owner') or r.get('cloud_legacy_pending') or time.time()-p.stat().st_mtime<TTL:continue
                    lock=recording_lock(r['id'])
                    if not lock.acquire(blocking=False):continue
                    try:
                        with engine.active_chat_lock:
                            if engine.active_chats.get(r['id']):continue
                        shutil.rmtree(p.parent)
                    finally:lock.release()
                except (OSError,ValueError):pass
            for p in (engine.DATA/'.sessions').glob('*'):
                try:
                    if p.is_dir() and time.time()-p.stat().st_mtime>TTL:shutil.rmtree(p)
                except OSError:pass
    @app.on_event('startup')
    def start_sweep():threading.Thread(target=sweep,daemon=True,name='cloud-temp-cleaner').start()
