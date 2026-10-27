# Audio model provenance

The application runs these models locally through **sherpa-onnx 1.13.8** (Apache-2.0). No user audio is sent to the model distributors. Downloaded weights are under gitignored `data/models/audio/`, not embedded in the source release. Installation URLs and SHA-256 digests are fixed in `audio_processing.ASSETS`; `scripts/install_audio_models.py` verifies them before use.

| Model | Source | Licence / notice |
| --- | --- | --- |
| GTCRN | [Original implementation](https://github.com/Xiaobin-Rong/gtcrn), [official sherpa-onnx ONNX release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speech-enhancement-models) | MIT; see GTCRN-LICENSE.txt |
| pyannote segmentation 3.0 int8 | [Original model](https://huggingface.co/pyannote/segmentation-3.0), [public sherpa-onnx export archive](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models) | MIT notice included in that archive, retained verbatim as pyannote-export-LICENSE.txt; copyright CNRS |
| 3D-Speaker ERes2Net base zh-cn 16k | [Original implementation](https://github.com/modelscope/3D-Speaker), [official sherpa-onnx release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models) | Apache-2.0; see 3D-Speaker-LICENSE.txt |
| sherpa-onnx runtime | [Source](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0; see sherpa-onnx-LICENSE.txt |

GTCRN: Xiaobin Rong and collaborators, “GTCRN: A Speech Enhancement Model Requiring Ultralow Computational Resources,” ICASSP 2024.

The pyannote export archive explicitly identifies its source as `pyannote/segmentation-3.0`. We use the model export documented and publicly distributed by sherpa-onnx. No access token is requested or copied.

Speaker labels identify anonymous clusters within one recording. They are not real-world identity claims, an enrolled voiceprint database, or guaranteed separation of simultaneous speakers. Overlap and unknown assignments are displayed explicitly.

## SenseVoiceSmall INT8
- Source model: https://github.com/QwenAudio/SenseVoice (MIT; see SenseVoice-LICENSE.txt).
- Official sherpa-onnx export: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
- Same export on publisher Hugging Face: https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
- Weights SHA-256: c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51
- Tokens SHA-256: f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc
- Local path: data/models/sensevoice/ (excluded from Git); install via scripts/install_sensevoice.py.
