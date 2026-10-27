(function(root){
  const enc=new TextEncoder();
  function safeName(name){return (name||'未命名资源').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/,'').slice(0,75)||'未命名资源'}
  function stamp(seconds){const n=Math.floor(seconds);return `${String(Math.floor(n/3600)).padStart(2,'0')}:${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`}
  function markdown(r){const lines=['# '+r.title,'','来源：'+(r.source==='meeting'?'录音转写':r.source),''];if(r.source==='meeting'&&r.project)lines.push('项目：'+r.project,'');if(r.summary)lines.push('## 核心要点与摘要','',r.summary,'');lines.push('## 原文','');if(r.segments?.length)for(const s of r.segments)lines.push(`[${stamp(s.start)}] ${s.speaker?s.speaker+'：':''}${s.text}`);else lines.push(r.text||'');return lines.join('\n')}
  function entries(records,format='markdown',groupByProject=false){return records.map(r=>({name:(groupByProject&&r.source==='meeting'?safeName(r.project||'未分类')+'/':'')+safeName(r.title)+'--'+r.id.slice(0,8)+(format==='text'?'.txt':'.md'),data:format==='text'?r.title+'\n\n'+(r.summary?'摘要\n'+r.summary+'\n\n':'')+'原文\n'+(r.source==='meeting'&&r.segments?.length?r.segments.map(s=>`[${stamp(s.start)}–${stamp(s.end)}] ${s.speaker?s.speaker+'：':''}${s.text}`).join('\n'):r.text):markdown(r)}))}
  const table=Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0});
  function crc(bytes){let n=0xffffffff;for(const b of bytes)n=table[(n^b)&255]^(n>>>8);return(n^0xffffffff)>>>0}
  function buildZip(items){
    const files=[],central=[];let offset=0,total=0;
    function buffer(size){const bytes=new Uint8Array(size);return[bytes,new DataView(bytes.buffer)]}
    for(const item of items){
      const name=enc.encode(item.name),data=typeof item.data==='string'?enc.encode(item.data):item.data,checksum=crc(data);
      if(name.length>65535||data.length>0xffffffff)throw Error('文件过大，无法打包');
      const[h,v]=buffer(30);v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x800,true);v.setUint16(12,33,true);v.setUint32(14,checksum,true);v.setUint32(18,data.length,true);v.setUint32(22,data.length,true);v.setUint16(26,name.length,true);
      const[c,w]=buffer(46);w.setUint32(0,0x02014b50,true);w.setUint16(4,20,true);w.setUint16(6,20,true);w.setUint16(8,0x800,true);w.setUint16(14,33,true);w.setUint32(16,checksum,true);w.setUint32(20,data.length,true);w.setUint32(24,data.length,true);w.setUint16(28,name.length,true);w.setUint32(42,offset,true);
      files.push(h,name,data);central.push(c,name);offset+=30+name.length+data.length;total+=46+name.length;
    }
    if(items.length>65535||offset+total>0xffffffff)throw Error('导出资源过多，请分批导出');
    const[end,e]=buffer(22);e.setUint32(0,0x06054b50,true);e.setUint16(8,items.length,true);e.setUint16(10,items.length,true);e.setUint32(12,total,true);e.setUint32(16,offset,true);
    return new Blob([...files,...central,end],{type:'application/zip'});
  }
  const api={safeName,stamp,markdown,entries,buildZip};if(typeof module!=='undefined')module.exports=api;else root.ResourceFiles=api;
})(typeof window==='undefined'?globalThis:window);
