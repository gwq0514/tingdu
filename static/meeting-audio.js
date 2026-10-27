(function(root){
  // Resample each complete capture interval to PCM16; no cloud speech service.
  function wav(samples, rate){
    const length=Math.round(samples.length*16000/rate), buffer=new ArrayBuffer(44+length*2),v=new DataView(buffer);
    const put=(offset,text)=>{for(let i=0;i<text.length;i++)v.setUint8(offset+i,text.charCodeAt(i))};
    put(0,'RIFF');v.setUint32(4,36+length*2,true);put(8,'WAVE');put(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);put(36,'data');v.setUint32(40,length*2,true);
    for(let i=0;i<length;i++){const start=Math.floor(i*rate/16000),end=Math.min(samples.length,Math.max(start+1,Math.floor((i+1)*rate/16000)));let sum=0;for(let j=start;j<end;j++)sum+=samples[j];const value=Math.max(-1,Math.min(1,sum/(end-start)));v.setInt16(44+i*2,Math.round(value*(value<0?32768:32767)),true)}
    return buffer;
  }
  function join(parts){const n=parts.reduce((a,p)=>a+p.length,0),result=new Float32Array(n);let pos=0;for(const part of parts){result.set(part,pos);pos+=part.length}return result}
  function backup(parts){const length=parts.reduce((n,p)=>n+p.byteLength-44,0),head=new Uint8Array(wav(new Float32Array(0),16000));const v=new DataView(head.buffer);v.setUint32(4,36+length,true);v.setUint32(40,length,true);return new Blob([head,...parts.map(p=>new Uint8Array(p,44))],{type:'audio/wav'})}
  const api={wav,join,backup};if(typeof module!=='undefined')module.exports=api;else root.MeetingAudio=api;
})(typeof window==='undefined'?globalThis:window);
