"""Creator discovery and paged, opt-in local subscriptions. No background crawling."""
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlencode

import yt_dlp
from fastapi import HTTPException
from pydantic import BaseModel, Field

lock=threading.RLock()
BROWSERS=('', 'chrome','safari','edge','firefox')

def canonical(url):
    p=urlparse(url);host=(p.hostname or '').lower()
    if host=='www.bilibili.com' or host=='bilibili.com':
        m=re.search(r'/video/(BV[a-zA-Z0-9]+|av\d+)',p.path)
        if m:return 'bilibili:'+m.group(1)
    if host.endswith('xiaohongshu.com'):
        m=re.search(r'/(?:explore|item)/([a-f0-9]{24})',p.path)
        if m:return 'xiaohongshu:'+m.group(1)
    return url

def record_identity(record):
    return record.get('source_identity') or canonical(record.get('source',''))

def creator_from_info(platform,info):
    if platform=='bilibili':
        uid=str(info.get('uploader_id') or '')
        if not re.fullmatch(r'\d+',uid):return None
        return {'key':'bilibili:'+uid,'platform':'bilibili','id':uid,'name':info.get('uploader') or uid,'url':'https://space.bilibili.com/'+uid+'/upload/video'}
    uid=str(info.get('作者ID') or '')
    if not re.fullmatch(r'[a-f0-9]{24}',uid):return None
    return {'key':'xiaohongshu:'+uid,'platform':'xiaohongshu','id':uid,'name':info.get('作者昵称') or uid,'url':'https://www.xiaohongshu.com/user/profile/'+uid}

def browser_cookies(browser,domain):
    if browser not in BROWSERS:raise HTTPException(400,'请选择有效的本机浏览器')
    if not browser:return {}
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        return {c.name:c.value for c in extract_cookies_from_browser(browser) if c.domain.lstrip('.')==domain or c.domain.endswith('.'+domain)}
    except Exception:
        raise HTTPException(400,'无法读取本机浏览器登录状态，请先在所选浏览器登录，或取消登录状态后重试。')

def fetch_bilibili(creator,cursor,browser):
    from yt_dlp.extractor.bilibili import BilibiliSpaceVideoIE
    page=int(cursor or 1)
    opts={'quiet':True,'socket_timeout':15,'retries':0}
    if browser:opts['cookiesfrombrowser']=(browser,)
    with yt_dlp.YoutubeDL(opts) as y:
        ie=BilibiliSpaceVideoIE(y);ie.initialize()
        query={'mid':creator['id'],'ps':30,'pn':page,'order':'pubdate','platform':'web','web_location':'333.1387',**ie._dm_params}
        try:
            result=ie._download_json('https://api.bilibili.com/x/space/wbi/arc/search',creator['id'],query=ie._sign_wbi(query,creator['id']),headers={'Referer':creator['url'],'Origin':'https://space.bilibili.com'})
        except yt_dlp.utils.ExtractorError as error:
            if getattr(error.cause,'status',None) in (412,429):
                raise HTTPException(429,'B站暂时限制访问（412/429），请稍后重试。已加载的作品保留，也可选择本机已登录的浏览器。')
            raise
    if result.get('code')!=0:raise HTTPException(502,'B站暂未允许读取作品列表，请稍后重试或选择本机已登录的浏览器。')
    data=result.get('data') or {};items=[]
    for v in data.get('list',{}).get('vlist',[]):
        bvid=v.get('bvid','')
        if not re.fullmatch(r'BV[a-zA-Z0-9]+',bvid):continue
        if v.get('meta',{}).get('attribute')==156:continue
        picture=v.get('pic','')
        if picture.startswith('//'):picture='https:'+picture
        if picture.startswith('http://'):picture='https://'+picture[7:]
        items.append({'id':bvid,'title':v.get('title') or bvid,'url':'https://www.bilibili.com/video/'+bvid,'thumbnail':picture,'duration':v.get('length',''),'published_at':v.get('created'),'creator_key':creator['key']})
    total=int(data.get('page',{}).get('count') or 0)
    return {'items':items,'cursor':str(page+1),'has_more':page*30<total,'total':total}

def normalize_xhs(notes,creator):
    result=[]
    for n in notes:
        card=n.get('noteCard') or n.get('note_card') or n
        if card.get('type')!='video':continue
        uid=str(card.get('noteId') or n.get('note_id') or n.get('id') or '')
        if not re.fullmatch(r'[a-f0-9]{24}',uid):continue
        token=n.get('xsecToken') or n.get('xsec_token') or card.get('xsecToken') or card.get('xsec_token') or ''
        cover=card.get('cover') or {};pic=cover.get('urlDefault') or cover.get('url_default') or cover.get('urlPre') or cover.get('url_pre') or ''
        if not pic:
            variants=cover.get('infoList') or cover.get('info_list') or []
            pic=next((v.get('url','') for v in variants if v.get('url')),'')
        if pic.startswith('http://'):pic='https://'+pic[7:]
        result.append({'id':uid,'title':card.get('displayTitle') or card.get('display_title') or card.get('title') or '未命名视频','url':'https://www.xiaohongshu.com/explore/'+uid+('?' + urlencode({'xsec_token':token,'xsec_source':'pc_user'}) if token else ''),'thumbnail':pic,'duration':'','published_at':card.get('time'),'creator_key':creator['key']})
    return result

def fetch_xiaohongshu(creator,cursor,browser):
    from curl_cffi import requests
    cookies=browser_cookies(browser,'xiaohongshu.com')
    if browser and not cookies.get('a1'):
        raise HTTPException(401,'所选浏览器中未找到可用的小红书访问状态。请在该浏览器登录小红书并打开作者主页后重试；应用内浏览器的登录状态与 Chrome / Edge 不通用。')
    if not cursor:
        with requests.Session(impersonate='chrome',cookies=cookies) as client:
            response=client.get(creator['url'],timeout=18)
        if response.status_code!=200:raise HTTPException(502,'小红书暂时限制读取作者主页，请稍后重试。')
        match=re.search(r'window\.__INITIAL_STATE__\s*=\s*(.*?)</script>',response.text,re.S)
        if not match:raise HTTPException(502,'小红书主页需要登录或验证，请选择本机已登录的浏览器。')
        raw=match.group(1).strip().rstrip(';')
        try:state=json.loads(re.sub(r'(?<=[,:\[])\s*undefined(?=[,}\]])','null',raw)).get('user',{})
        except (ValueError,TypeError):raise HTTPException(502,'小红书主页数据格式已变化，请稍后重试。')
        groups=state.get('notes') or [];notes=groups[0] if groups and isinstance(groups[0],list) else groups
        queries=state.get('noteQueries') or [];page=queries[0] if queries else {}
        if not notes and (state.get('bannedInfo') or {}).get('serverBanned') is True:
            raise HTTPException(502,'小红书返回了作者主页受限状态，请先打开作者主页确认是否可访问。')
        if not notes:raise HTTPException(401,'小红书未返回作品列表，暂不能判断作者是否可访问。请在 Chrome / Edge 中登录小红书并打开作者主页，选择对应的本机浏览器，再点击“使用所选浏览器重试”。')
        videos=normalize_xhs(notes,creator)
        # Some anonymous pages contain thirty skeleton cards with empty IDs and titles.
        # They are a login wall, not an empty/complete account and not a usable page.
        if not videos and all(not (n.get('id') or (n.get('noteCard') or {}).get('noteId')) for n in notes):
            raise HTTPException(401,'小红书只返回了占位作品列表，需要本机浏览器登录状态。请选择已登录的浏览器，然后刷新作品。')
        return {'items':videos,'cursor':page.get('cursor') or notes[-1].get('id',''),'has_more':bool(page.get('hasMore',len(notes)>=30)),'total':None}
    if not cookies.get('a1'):
        raise HTTPException(401,'小红书的后续作品分页需要本机浏览器登录状态。请选择已登录小红书的 Chrome / Edge 等浏览器，再点“加载更多”。')
    from xhshow import Xhshow
    params={'num':30,'cursor':cursor,'user_id':creator['id'],'image_formats':'jpg,webp,avif','xsec_token':'','xsec_source':'pc_feed'}
    headers=Xhshow().sign_headers_get('/api/sns/web/v1/user_posted',cookies=cookies,params=params,sign_format='xyw')
    response=requests.get('https://edith.xiaohongshu.com/api/sns/web/v1/user_posted',params=params,cookies=cookies,headers={**headers,'Referer':creator['url'],'Origin':'https://www.xiaohongshu.com'},impersonate='chrome',timeout=18)
    try:reply=response.json()
    except ValueError:raise HTTPException(502,'小红书返回了验证页面，请在浏览器确认能正常访问后重试。')
    if response.status_code!=200 or not reply.get('success'):
        code=reply.get('code')
        if response.status_code==406:
            raise HTTPException(502,'小红书拒绝了作品列表请求格式（HTTP 406），这是接口兼容问题，请勿反复登录。')
        if response.status_code in (429,461,471):
            raise HTTPException(429,'小红书暂时限制访问或要求验证，请在所选浏览器打开作者主页完成验证后稍后重试。')
        if response.status_code==401 or code in (-100, -101):
            raise HTTPException(401,'小红书返回登录状态失效，请在所选浏览器重新登录后重试。')
        raise HTTPException(502,f'小红书未返回作品列表（HTTP {response.status_code}，平台代码 {code}）。登录并非唯一原因，请稍后重试。')
    data=reply.get('data') or {}
    return {'items':normalize_xhs(data.get('notes') or [],creator),'cursor':data.get('cursor',''),'has_more':bool(data.get('has_more')),'total':None}

class SubscribeRequest(BaseModel):
    job_id:str
    browser:str=''

class BatchRequest(BaseModel):
    video_ids:list[str]=Field(min_length=1,max_length=30)
    model:str='sensevoice'
    llm_model:str=''
    browser:str=''


def register(app,engine):
    def atomic(path,data):
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)
    def load_subs():
        p=engine.metadata_dir()/'subscriptions.json'
        return json.loads(p.read_text()) if p.exists() else []
    def cache_path(key):return engine.metadata_dir()/'subscriptions'/ (hashlib.sha256(key.encode()).hexdigest()+'.json')
    def sub(key):
        found=next((s for s in load_subs() if s['key']==key),None)
        if not found:raise HTTPException(404,'该作者尚未订阅')
        return found
    def cache(key):
        p=cache_path(key)
        state=json.loads(p.read_text()) if p.exists() else {}
        return state if state.get('schema')==1 else {'schema':1,'items':[],'cursor':'','has_more':True,'total':None}
    def discover(jid,browser=''):
        if browser not in BROWSERS or (engine.cloud_mode() and browser):raise HTTPException(400,'浏览器参数不合法')
        r=engine.read(jid)
        if r.get('creator'):return r['creator']
        if r['status'] in ('queued','running'):raise HTTPException(409,'请等待视频完成解析，再订阅作者')
        if 'bilibili.com' in r.get('source','') or 'b23.tv' in r.get('source',''):
            opts={'quiet':True,'socket_timeout':15,'retries':0,'noplaylist':True}
            if browser:opts['cookiesfrombrowser']=(browser,)
            try:
                with yt_dlp.YoutubeDL(opts) as y:info=y.extract_info(r['source'],download=False)
            except Exception:raise HTTPException(502,'暂时无法识别 B站作者，请稍后重试')
            creator=creator_from_info('bilibili',info)
        elif 'xiaohongshu.com' in r.get('source','') or 'xhslink.' in r.get('source',''):
            p=engine.DATA/jid/'xhs-result.json'
            if not p.exists():raise HTTPException(400,'缺少该视频的作者信息，请重新导入原始分享链接')
            info=json.loads(p.read_text());creator=creator_from_info('xiaohongshu',info[0]) if info else None
        else:raise HTTPException(400,'目前支持订阅 B站和小红书视频作者，本地文件或正文无法自动识别作者')
        if not creator:raise HTTPException(502,'没有读取到有效的作者信息')
        r['creator']=creator;engine.save(r);return creator

    @app.get('/api/subscriptions')
    def subscriptions():
        with lock:return load_subs()

    @app.get('/api/jobs/{jid}/creator')
    def creator(jid:str,browser:str=''):
        value=discover(jid,browser)
        return {**value,'subscribed':any(s['key']==value['key'] for s in load_subs())}

    @app.post('/api/subscriptions')
    def subscribe(req:SubscribeRequest):
        with lock:
            c=discover(req.job_id,req.browser);subs=load_subs()
            existing=next((s for s in subs if s['key']==c['key']),None)
            if existing:return existing
            c={**c,'subscribed_at':datetime.now(timezone.utc).isoformat()};subs.append(c);atomic(engine.metadata_dir()/'subscriptions.json',subs);return c

    @app.delete('/api/subscriptions/{key}')
    def unsubscribe(key:str):
        with lock:
            sub(key);atomic(engine.metadata_dir()/'subscriptions.json',[s for s in load_subs() if s['key']!=key]);return {'ok':True}

    @app.get('/api/subscriptions/{key}/videos')
    def videos(key:str,offset:int=0,browser:str='',refresh:bool=False):
        if offset<0 or offset>100000:raise HTTPException(400,'分页位置不合法')
        if browser not in BROWSERS or (engine.cloud_mode() and browser):raise HTTPException(400,'浏览器参数不合法')
        with lock:
            creator=sub(key);state=cache(key)
            if refresh:state={'schema':1,'items':[],'cursor':'','has_more':True,'total':None,'retry_after':state.get('retry_after',0)};offset=0
            # Each request is bounded; never crawl the whole account in the background.
            for _ in range(3):
                if len(state['items'])>=offset+10 or not state['has_more']:break
                remaining=int(state.get('retry_after',0)-time.time())
                if remaining>0:raise HTTPException(429,f'平台限制访问，请约 {remaining} 秒后重试；已加载的作品仍可选择。')
                previous=state['cursor']
                try:page=fetch_bilibili(creator,previous,browser) if creator['platform']=='bilibili' else fetch_xiaohongshu(creator,previous,browser)
                except HTTPException as error:
                    if error.status_code==429:
                        state['retry_after']=time.time()+60;atomic(cache_path(key),state)
                    raise
                except Exception:raise HTTPException(502,'平台作品列表暂时不可用，请稍后重试；已加载的作品仍然保留')
                known={v['id'] for v in state['items']}
                for video in page['items']:
                    if video['id'] not in known:
                        state['items'].append(video);known.add(video['id'])
                state.update(cursor=page['cursor'],has_more=page['has_more'],total=page['total'])
                if page['has_more'] and page['cursor']==previous:raise HTTPException(502,'平台没有返回新的分页位置，请刷新作者列表后重试')
                atomic(cache_path(key),state)
            existing={record_identity(json.loads(p.read_text())):json.loads(p.read_text()) for p in engine.record_paths()}
            batch=[]
            for v in state['items'][offset:offset+10]:
                row=dict(v);job=existing.get(canonical(v['url']));row.update(imported=bool(job and job['status']!='error'),job_id=job['id'] if job else None,job_status=job['status'] if job else None);batch.append(row)
            return {'creator':creator,'items':batch,'next_offset':offset+len(batch),'has_more':offset+len(batch)<len(state['items']) or state['has_more'],'total':state['total'],'cached_count':len(state['items'])}

    def process_batch_job(jid,url,asr,browser,llm):
        engine.process(jid,url,None,asr,browser)
        r=engine.read(jid)
        if r['status']!='done':return
        r['summary_status']='running';r['message']='转写完成，正在生成核心要点…';engine.save(r)
        try:
            engine.chat(jid,engine.ChatRequest(model=llm,summary=True))
            r=engine.read(jid);r['summary_status']='done';r['message']='转写与核心要点已生成';engine.save(r)
        except Exception:
            r=engine.read(jid);r['summary_status']='error';r['message']='转写已完成，但摘要生成失败，可在详情页重试';engine.save(r)

    @app.post('/api/subscriptions/{key}/import')
    def batch_import(key:str,req:BatchRequest):
        if req.model != 'sensevoice' or req.browser not in BROWSERS or (engine.cloud_mode() and req.browser):raise HTTPException(400,'模型或浏览器参数不合法')
        engine.require_asr()
        if not req.llm_model.strip():raise HTTPException(400,'请选择用于生成摘要的本地模型')
        # Check locally before enqueueing jobs, instead of discovering hours later that a model is missing.
        health=engine.health()
        if req.llm_model not in health['models']:raise HTTPException(400,'所选本地摘要模型未启动或未安装，请先启动模型服务')
        with lock:
            creator=sub(key);items={v['id']:v for v in cache(key)['items']};ids=list(dict.fromkeys(req.video_ids))
            if engine.cloud_mode() and len(ids)>2:raise HTTPException(429,'云端每批最多导入2个视频，请等待处理完成后继续')
            if any(i not in items for i in ids):raise HTTPException(400,'选择中包含不属于该作者已加载列表的视频，请刷新后重试')
            existing={record_identity(r):r for p in engine.record_paths() if (r:=json.loads(p.read_text()))['status']!='error'}
            added=[];skipped=[]
            for vid in ids:
                v=items[vid];identity=canonical(v['url'])
                if identity in existing:skipped.append({'video_id':vid,'job_id':existing[identity]['id']});continue
                r=engine.new(v['title'],v['url']);r.update(creator=creator,summary_status='pending',batch_subscription=key,thumbnail_url=v.get('thumbnail',''));engine.save(r)
                engine.pool.submit(process_batch_job,r['id'],v['url'],req.model,req.browser,req.llm_model);added.append({'video_id':vid,'job_id':r['id']});existing[identity]=r
            return {'added':added,'skipped':skipped,'message':f"已加入 {len(added)} 个任务，跳过 {len(skipped)} 个已导入视频"}
