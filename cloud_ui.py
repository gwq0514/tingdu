"""Cloud-only presentation overlay; packaged desktop assets remain byte-identical."""
from fastapi.responses import HTMLResponse
CLOUD_VERSION='1.2.0-cloud.1'

def page(path):
    html=path.read_text()
    style='''<meta name="tingdu-channel" content="cloud"><meta name="tingdu-version" content="'''+CLOUD_VERSION+'''">
<style>label[for="browser"],#browser,label:has(>#subBrowser),#subBrowserAccessNote{display:none!important}</style>'''
    html=html.replace('</head>',style+'</head>',1) if '</head>' in html else html.replace('<style>',style+'<style>',1)
    import os
    if os.environ.get('TINGDU_CLOUD_PRIVACY')=='1':
        html=html.replace('<script src="/static/export-utils', '<script src="/static/cloud-store.js?v='+CLOUD_VERSION+'"></script><script src="/static/export-utils',1)
        html=html.replace('/static/runtime-status.js?v=2','/static/cloud-runtime-status.js?v='+CLOUD_VERSION)
    return HTMLResponse(html.replace('</body>', '<script src="/static/cloud-client.js?v='+CLOUD_VERSION+'"></script></body>',1) if '</body>' in html else html.replace('</html>','<script src="/static/cloud-client.js?v='+CLOUD_VERSION+'"></script></html>'),headers={'Cache-Control':'no-store','X-Tingdu-Channel':'cloud','X-Tingdu-Version':CLOUD_VERSION})
