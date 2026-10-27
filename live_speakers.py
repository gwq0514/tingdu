"""Provisional per-recording speaker labels. No cross-recording voiceprint store."""
import threading
from functools import lru_cache
from pathlib import Path
import numpy as np
from audio_processing import AudioModels, label_segments

class LiveSpeakers:
    def __init__(self,root):
        self.root=Path(root);self.analysis=AudioModels(root)
        # Separate from final-pass diarization: a paused background pass must
        # never hold the lock needed by live audio.
        self.extractor=None;self.lock=threading.RLock();self.sessions={}
    def clear(self,jid):
        with self.lock:self.sessions.pop(jid,None)
    def embedding(self,samples):
        import sherpa_onnx as s
        if self.extractor is None:
            config=s.SpeakerEmbeddingExtractorConfig(model=str(self.root/'speaker-embedding.onnx'),num_threads=1,provider='cpu')
            if not config.validate():raise RuntimeError('实时发言人模型未就绪')
            self.extractor=s.SpeakerEmbeddingExtractor(config)
        stream=self.extractor.create_stream();stream.accept_waveform(16000,np.ascontiguousarray(samples,dtype=np.float32));stream.input_finished()
        if not self.extractor.is_ready(stream):return None
        vector=np.asarray(self.extractor.compute(stream),dtype=np.float32);norm=np.linalg.norm(vector)
        if not np.isfinite(vector).all() or norm<1e-6:return None
        return vector/norm
    def match(self,jid,vector):
        prototypes=self.sessions.setdefault(jid,[])
        if not prototypes:
            prototypes.append(vector.copy());return 1
        scores=np.asarray([np.dot(p,vector) for p in prototypes]);best=int(np.argmax(scores));score=float(scores[best])
        second=float(np.partition(scores,-2)[-2]) if len(scores)>1 else -1
        if score>=.60 and score-second>=.08:
            mean=prototypes[best]*.9+vector*.1;prototypes[best]=mean/np.linalg.norm(mean);return best+1
        if score<.45 and len(prototypes)<24:
            prototypes.append(vector.copy());return len(prototypes)
        return None
    def process(self,jid,samples,segments,offset):
        with self.lock:
            if not all((self.root/name).is_file() for name in ('speaker-segmentation.onnx','speaker-embedding.onnx')):raise RuntimeError('实时发言人模型未安装')
            local=self.analysis.diarize(samples)
            mapping={}
            for speaker in sorted(set(t['speaker_id'] for t in local)):
                pieces=[]
                for turn in local:
                    if turn['speaker_id']!=speaker:continue
                    # Do not enroll overlapping speech into a person's prototype.
                    if any(other['speaker_id']!=speaker and min(other['end'],turn['end'])>max(other['start'],turn['start']) for other in local):continue
                    pieces.append(samples[int(turn['start']*16000):int(turn['end']*16000)])
                speech=np.concatenate(pieces)[:6*16000] if pieces else np.empty(0,dtype=np.float32)
                if len(speech)<.8*16000:continue
                vector=self.embedding(speech)
                if vector is not None:mapping[speaker]=self.match(jid,vector)
            turns=[{'start':t['start']+offset,'end':t['end']+offset,'speaker_id':mapping[t['speaker_id']]} for t in local if mapping.get(t['speaker_id'])]
            labeled=label_segments(segments,turns)
            for row in labeled:row['speaker_provisional']=True
            return labeled,len(self.sessions.get(jid,[]))

@lru_cache(maxsize=2)
def service(data):return LiveSpeakers(Path(data)/'models'/'audio')
