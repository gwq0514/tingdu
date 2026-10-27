# 听读 Mac 桌面版

适配 Apple Silicon（M1/M2/M3/M4 等），当前在 macOS 26.3.1 ARM64 上构建和验证。最低系统声明 macOS 14；其他系统版本尚未实机验证。Intel 版未构建。

安装：打开 DMG，将「听读」拖入「应用程序」，然后启动。当前版本只有本地完整性签名，未使用 Apple Developer ID 签名和公证；系统可能阻止首次打开，请在确认来源后通过「系统设置 → 隐私与安全」允许打开。不要关闭 Gatekeeper 或系统安全保护。

内置 Electron、Python 后端、FFmpeg、SenseVoiceSmall INT8、GTCRN、发言人标记模型及 Qwen3 0.6B 本地总结模型。无需另装 Python、Homebrew 或 Ollama；首次启动整理内置模型，建议预留至少 5 GB 可用磁盘空间。内容在本地处理，链接导入需要联网。

- 桌面数据：`~/Library/Application Support/听读/data/`，与源码网页版本的 `data/` 分开，更新软件不删除资料。
- 窗口菜单「听读 → 打开数据文件夹」可定位文件；可另存到自己选择的目录。
- 浏览器麦克风授权是系统授权；没有你的点击不会主动录音。当前仍使用系统默认输入设备，如选中了 iPhone，请在 Mac「系统设置 → 声音 → 输入」选择 MacBook 麦克风。
- 结束录音并保存后再退出；不要同时运行两个桌面实例。网页开发版可并行使用不同端口。
- Chrome 登录状态只在你主动选择读取该浏览器时使用，macOS 可能要求钥匙串或磁盘权限。平台仍可能限制请求；不保证所有链接均可下载。
- 当前没有自动更新；下载新版本替换应用。请定期备份数据目录。
- 小模型总结可能误解内容，请核对原文。临时发言人标记可能不准确。

## 构建

在 Apple Silicon Mac 使用 Python 3.13 和 Node.js：

```sh
python3.13 -m venv .runtime
.runtime/bin/python -m pip install -r requirements.lock.txt
.runtime/bin/python -m pip install pyinstaller==6.22.3
npm ci --prefix desktop
.runtime/bin/python scripts/install_sensevoice.py
.runtime/bin/python scripts/install_audio_models.py
.runtime/bin/python desktop/build.py
npm run dist --prefix desktop
```

`desktop/build.py` 还需要以下独立组件（不从个人数据自动收集）：

- 已纳入源码的 `third_party/XHS-Downloader/source/`、`locale/`（上游 https://github.com/JoeanAmier/XHS-Downloader，GPLv3）。
- `vendor/ollama/ollama/0.40.3/libexec/`（https://github.com/ollama/ollama，MIT；本次 Homebrew 镜像布局）。
- `data/llm/qwen3-0.6b.gguf` 和相邻 Modelfile（Qwen3-0.6B GGUF Q8_0，Apache-2.0；来源及 SHA256 见 `third_party/desktop-components.json`）。

安装包仅从明确的模型文件白名单取模型，绝不复制用户录音、Cookie、订阅列表、私有词表或管理口令。不要把整个 data 或 vendor 目录放入安装包。

应用使用 127.0.0.1:18765、内置 Ollama 使用 127.0.0.1:18766，均不监听公网地址。管理员词表页面不自动启动。
