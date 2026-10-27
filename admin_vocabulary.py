"""Private administrator service. Always start with loopback binding.
Run: .runtime/bin/python admin_vocabulary.py
Never mount this app in the public content service or proxy its port publicly.
"""
import hmac
import json
import os
import secrets
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from asr_vocabulary import Vocabulary

ROOT=Path(__file__).resolve().parent

def create_app(data=None):
    data=Path(data) if data else ROOT/'data'
    private=data/'admin';private.mkdir(parents=True,exist_ok=True,mode=0o700)
    secret=private/'管理口令.txt'
    if not secret.exists():
        try:
            fd=os.open(secret,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(32)+'\n')
        except FileExistsError:pass
    os.chmod(secret,0o600)
    password=secret.read_text().strip()
    if len(password)<32:raise RuntimeError('管理口令文件无效，请在本机重新生成')
    vocabulary=Vocabulary(private/'asr-vocabulary.json')
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    @app.middleware('http')
    async def protect(request:Request,call_next):
        if not request.client or request.client.host not in ('127.0.0.1','::1'):
            return JSONResponse({'detail':'管理入口仅允许本机连接'},status_code=403)
        if request.headers.get('host','').split(':')[0] not in ('127.0.0.1','localhost'):
            return JSONResponse({'detail':'管理入口仅允许本机访问'},status_code=403)
        if request.headers.get('origin') and request.headers['origin'] not in ('http://127.0.0.1:8767','http://localhost:8767'):
            return JSONResponse({'detail':'不允许其他页面访问管理入口'},status_code=403)
        if request.url.path.startswith('/api/'):
            supplied=request.headers.get('authorization','')
            if not hmac.compare_digest(supplied.encode(),('Bearer '+password).encode()):
                return JSONResponse({'detail':'管理口令不正确'},status_code=401)
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response
    async def body(request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>512000:raise HTTPException(413,'配置内容太大')
        try:return json.loads(raw)
        except (ValueError,UnicodeError):raise HTTPException(400,'数据格式不正确')
    @app.get('/')
    def page():return FileResponse(ROOT/'admin_ui'/'vocabulary.html')
    @app.get('/admin.js')
    def script():return FileResponse(ROOT/'admin_ui'/'vocabulary.js',media_type='text/javascript')
    @app.get('/admin.css')
    def style():return FileResponse(ROOT/'admin_ui'/'vocabulary.css',media_type='text/css')
    @app.get('/api/vocabulary')
    def get():
        try:return vocabulary.read()
        except (ValueError,OSError):raise HTTPException(400,'本机配置文件格式有误，请修复配置后重试')
    @app.put('/api/vocabulary')
    async def put(request:Request):
        value=await body(request)
        if not isinstance(value,dict) or type(value.get('revision')) is not int:raise HTTPException(400,'缺少配置版本，请重新载入')
        try:return vocabulary.save(value,value['revision'])
        except ValueError as e:raise HTTPException(400,str(e))
    @app.post('/api/preview')
    async def preview(request:Request):
        value=await body(request)
        text=value.get('text') if isinstance(value,dict) else None
        if not isinstance(text,str) or len(text)>5000:raise HTTPException(400,'测试文字最多5000字')
        output,_,changes=vocabulary.apply(text,[])
        return {'text':output,'changes':changes}
    return app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_app(),host='127.0.0.1',port=8767,proxy_headers=False,access_log=False)
