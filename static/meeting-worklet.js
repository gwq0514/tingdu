class LocalMeetingCapture extends AudioWorkletProcessor {
  constructor(){super();this.buffer=new Float32Array(2048);this.used=0;this.capturing=true;this.port.onmessage=e=>{
    const type=typeof e.data==='string'?e.data:e.data?.type;
    if(type==='resume'){this.capturing=true;return}
    if(type==='flush'||type==='pause'){
      this.send();if(type==='pause')this.capturing=false;
      this.port.postMessage({flushed:true,...(e.data?.id!==undefined?{id:e.data.id}:{})});
    }
  }}
  send(){if(this.used){const samples=this.buffer.slice(0,this.used);this.port.postMessage({samples},[samples.buffer]);this.used=0}}
  process(inputs){const channels=inputs[0];if(this.capturing&&channels?.length){for(let i=0;i<channels[0].length;i++){let value=0;for(const c of channels)value+=c[i];this.buffer[this.used++]=value/channels.length;if(this.used===this.buffer.length)this.send()}}return true}
}
registerProcessor('local-meeting-capture',LocalMeetingCapture);
