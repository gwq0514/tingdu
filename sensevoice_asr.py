"""SenseVoiceSmall INT8 adapter. Offline CPU inference; no audio upload.
Model source: https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
"""
from pathlib import Path
from types import SimpleNamespace
import re
import numpy as np

MODEL_ID = 'sensevoice'

def available(data):
    root = Path(data) / 'models' / MODEL_ID
    return all((root/name).is_file() and (root/name).stat().st_size for name in ('model.int8.onnx','tokens.txt'))

class SenseVoiceModel:
    def __init__(self, root):
        import sherpa_onnx
        root = Path(root)
        from asr_vocabulary import Vocabulary
        self.vocabulary = Vocabulary(root.parent.parent / 'admin' / 'asr-vocabulary.json')
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(root/'model.int8.onnx'), tokens=str(root/'tokens.txt'),
            language='zh', use_itn=True, num_threads=1, provider='cpu', debug=False)

    def transcribe(self, samples, **kwargs):
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        duration = len(samples)/16000
        if not len(samples) or np.max(np.abs(samples)) < .0001:
            return [], SimpleNamespace(duration=duration)
        stream = self.recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self.recognizer.decode_stream(stream)
        result = stream.result
        text = re.sub(r'<\|[^|]*\|>', '', result.text).strip()
        if not text: return [], SimpleNamespace(duration=duration)
        tokens = list(getattr(result,'tokens',[]) or [])
        times = list(getattr(result,'timestamps',[]) or [])
        words = []
        # Use actual CTC token times only when they reproduce displayed text.
        # ITN can rewrite numbers; do not fabricate word alignment in that case.
        cleaned = [re.sub(r'<\|[^|]*\|>', '', t).replace('▁',' ') for t in tokens]
        if len(times)==len(tokens) and ''.join(cleaned).strip()==text:
            for i, word in enumerate(cleaned):
                if not word: continue
                start = max(0.,min(duration,float(times[i])))
                end = min(duration,float(times[i+1])) if i+1<len(times) else min(duration,start+.2)
                words.append(SimpleNamespace(start=start,end=max(start,end),word=word))
        raw_text = text
        changes = []
        if getattr(self,'vocabulary',None):
            text,words,changes = self.vocabulary.apply(text,words)
        return [SimpleNamespace(start=words[0].start if words else 0.,
            end=words[-1].end if words else duration,text=text,words=words,
            raw_text=raw_text,text_corrections=changes)], SimpleNamespace(duration=duration)
