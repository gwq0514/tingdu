"""Private, explicit ASR text corrections; NOT acoustic hotword biasing."""
import copy
import json
import os
import re
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

EMPTY = {'enabled':True,'revision':0,'entries':[]}

def validate(value):
    if not isinstance(value,dict) or type(value.get('enabled')) is not bool:
        raise ValueError('请设置是否启用词语纠正')
    entries=value.get('entries')
    if not isinstance(entries,list) or len(entries)>1000:raise ValueError('最多配置1000条词语')
    result=[];seen={};targets=set()
    def term(v):
        if not isinstance(v,str):raise ValueError('词语必须是文字')
        v=v.strip()
        if not 1<=len(v)<=80 or re.search(r'[\x00-\x1f\x7f|]',v):raise ValueError('词语需为1至80字，不能包含换行、控制字符或竖线')
        return v
    for item in entries:
        if not isinstance(item,dict):raise ValueError('词条格式不正确')
        target=term(item.get('term'))
        if target in targets:raise ValueError('正确词语重复：'+target)
        targets.add(target)
        aliases=item.get('aliases')
        if not isinstance(aliases,list) or not 1<=len(aliases)<=10:raise ValueError('每条词语需要1至10个常见误识别写法')
        clean=[]
        for alias in aliases:
            alias=term(alias)
            if len(alias)<2:raise ValueError('误识别写法至少2字，避免单字误替换')
            if alias==target:raise ValueError('正确词语与误识别写法不能相同')
            if alias in seen:raise ValueError('误识别写法重复或冲突：'+alias)
            seen[alias]=target;clean.append(alias)
        result.append({'term':target,'aliases':clean})
    if targets.intersection(seen):raise ValueError('正确词语不能同时作为其他词条的误识别写法')
    return {'enabled':value['enabled'],'entries':result}

class Vocabulary:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self._signature=None;self._rules=None
    def read(self):
        if not self.path.exists():return copy.deepcopy(EMPTY)
        data=json.loads(self.path.read_text(encoding='utf-8'));clean=validate(data)
        revision=data.get('revision',0)
        if type(revision) is not int or revision<0:raise ValueError('配置版本无效')
        return dict(clean,revision=revision)
    def save(self,value,revision):
        clean=validate(value)
        with self.lock:
            current=self.read()
            if revision!=current['revision']:raise ValueError('配置已被其他窗口更新，请重新载入后再保存')
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            temp=self.path.with_name('.'+uuid.uuid4().hex+'.tmp')
            data=dict(clean,revision=current['revision']+1)
            try:
                with temp.open('x',encoding='utf-8') as out:
                    os.chmod(temp,0o600);json.dump(data,out,ensure_ascii=False,indent=2)
                temp.replace(self.path)
            finally:temp.unlink(missing_ok=True)
            return data
    def rules(self):
        with self.lock:
            try:
                stat=self.path.stat();signature=(stat.st_mtime_ns,stat.st_size)
                if signature==self._signature:return self._rules
                data=self.read();mapping={alias:entry['term'] for entry in data['entries'] for alias in entry['aliases']} if data['enabled'] else {}
                parts=[]
                for alias in sorted(mapping,key=len,reverse=True):
                    start=r'(?<![A-Za-z0-9_])' if alias[0].isascii() and (alias[0].isalnum() or alias[0]=='_') else ''
                    end=r'(?![A-Za-z0-9_])' if alias[-1].isascii() and (alias[-1].isalnum() or alias[-1]=='_') else ''
                    parts.append(start+re.escape(alias)+end)
                self._rules=(re.compile('|'.join(parts)),mapping,data['revision']) if parts else None
                self._signature=signature
                return self._rules
            except (OSError,ValueError,TypeError):
                # A broken manual edit must never prevent raw transcription.
                return None
    def apply(self,text,words):
        rules=self.rules()
        if not rules:return text,words,[]
        pattern,mapping,revision=rules;matches=list(pattern.finditer(text))
        if not matches:return text,words,[]
        positions=[];offset=0
        for w in words:
            positions.append((offset,offset+len(w.word),w));offset+=len(w.word)
        # If alignment is already absent/incompatible, keep segment-level times.
        aligned=''.join(w.word for w in words)==text and bool(words)
        output=[];updated=[];changes=[];cursor=0
        def fragment(a,b):
            for start,end,w in positions:
                left=max(a,start);right=min(b,end)
                if left<right:updated.append(SimpleNamespace(start=w.start,end=w.end,word=text[left:right]))
        for m in matches:
            target=mapping[m.group()];output.extend([text[cursor:m.start()],target])
            if aligned:
                fragment(cursor,m.start())
                covered=[w for a,b,w in positions if a<m.end() and b>m.start()]
                updated.append(SimpleNamespace(start=covered[0].start,end=covered[-1].end,word=target))
            changes.append({'from':m.group(),'to':target,'revision':revision})
            cursor=m.end()
        output.append(text[cursor:])
        if aligned:fragment(cursor,len(text))
        return ''.join(output),updated if aligned else [],changes
