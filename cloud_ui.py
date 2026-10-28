"""Cloud-only presentation overlay; packaged desktop assets remain byte-identical."""
from fastapi.responses import HTMLResponse
CLOUD_VERSION='1.1.1-cloud.1'

def page(path):
    html=path.read_text()
    style='''<meta name="tingdu-channel" content="cloud"><meta name="tingdu-version" content="'''+CLOUD_VERSION+'''">
<style>label[for="browser"],#browser,label:has(>#subBrowser),#subBrowserAccessNote{display:none!important}</style>'''
    html=html.replace('</head>',style+'</head>',1) if '</head>' in html else html.replace('<style>',style+'<style>',1)
    return HTMLResponse(html.replace('</body>', '<script src="/static/cloud-client.js?v='+CLOUD_VERSION+'"></script></body>',1) if '</body>' in html else html.replace('</html>','<script src="/static/cloud-client.js?v='+CLOUD_VERSION+'"></script></html>'),headers={'Cache-Control':'no-store','X-Tingdu-Channel':'cloud','X-Tingdu-Version':CLOUD_VERSION})
