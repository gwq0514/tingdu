import unittest
from types import SimpleNamespace
import numpy as np
from sensevoice_asr import SenseVoiceModel

class SenseVoiceTests(unittest.TestCase):
    def model(self,result):
        stream=SimpleNamespace(result=result,accept_waveform=lambda *a:None)
        model=SenseVoiceModel.__new__(SenseVoiceModel)
        model.recognizer=SimpleNamespace(create_stream=lambda:stream,decode_stream=lambda s:None)
        return model
    def test_actual_ctc_times_and_text(self):
        model=self.model(SimpleNamespace(text='你好',tokens=['你','好'],timestamps=[.1,.4]))
        segments,info=model.transcribe(np.ones(16000,dtype=np.float32)*.1)
        self.assertEqual(info.duration,1)
        self.assertEqual(segments[0].text,'你好')
        self.assertEqual([w.start for w in segments[0].words],[.1,.4])
    def test_itn_mismatch_keeps_text_without_invented_words(self):
        model=self.model(SimpleNamespace(text='9点',tokens=['九','点'],timestamps=[.1,.4]))
        segments,_=model.transcribe(np.ones(16000,dtype=np.float32)*.1)
        self.assertEqual(segments[0].text,'9点')
        self.assertEqual(segments[0].words,[])
    def test_silence_never_decodes(self):
        model=self.model(None)
        segments,_=model.transcribe(np.zeros(16000,dtype=np.float32))
        self.assertEqual(segments,[])

if __name__=='__main__':unittest.main()
