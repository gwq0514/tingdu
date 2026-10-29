# 完整模型 · 2 核 2 GiB 服务器验证方案

状态：代码、运行状态界面和部署模板已准备；目标实例已读取为 Alibaba Cloud Linux 3、x86_64，约 1871 MiB 可用总内存、检查时约 1438 MiB 可用、未配置 Swap，根盘约 33 GiB 可用。已开始目标服务器上的模型容量测试，逐项结果见 [RESULTS.md](RESULTS.md)。**这是单人、使用测试素材的试运行，不能直接开放匿名公众使用。** 桌面版默认不启用该模式。

## 模型与参数保持不变

SenseVoiceSmall INT8、GTCRN、pyannote segmentation + 3D-Speaker 以及当前 Qwen3 0.6B Q8 全部保留。总结仍为 16K 上下文、2048 输出上限，不降量化精度、不缩短上下文。

一个独立音频工作进程缓存语音模型，统一串行处理音频；总结阶段先回收这个进程，再启动独立 Ollama 进程组。总结完毕销毁所属进程组，不触碰其他已安装的 Ollama。后台音频/总结遇到新的录音会让出资源，之后从已保存输入重新执行；录音采集不暂停，转写可能延后。空闲 30 秒回收音频进程。终止大模型正在处理的请求会丢弃这次未完成输出，之后重算，不能承诺立即无等待切换。

排队、加载、处理、让出资源、错误和待转写片段数来自 `/api/runtime`；前端不编造预计完成时间，不承诺实时速度。该接口不返回内容、标题、用户路径或口令。

**2 GiB 仍可能无法运行原来的 16K 总结。** 调度只减少同时驻留的模型，不能减少单个任务的最低内存。Swap 只能兜底且可能严重拖慢；Ollama 也可能拒绝加载。失败时保留原声和文字，不暗中切换小模型。长录音的最终发言人算法仍读取完整原声，可能产生额外内存峰值，必须独立验证。

## 实施顺序

1. 备份现有 1Panel 网站配置，读取系统、内存、Swap、磁盘和端口状态。不要重置系统或安装第二个 Nginx。
2. 在 Linux 上创建专用 `tingdu-pilot` 用户，源码放 `/opt/tingdu-pilot`，工作文件放 `/var/lib/tingdu-pilot/data`，不上传 Mac 的录音、Cookie、订阅、私有词表或管理员口令。目录只允许该用户读写。
3. 安装 Linux 对应架构的 Python 3.13、FFmpeg、Ollama，创建 `.venv` 并安装 `requirements.lock.txt`。**Mac 安装包中的 ARM64 Mach-O 不能复制到 Linux 运行。** Ollama 不作为常驻服务启动，专用端口 11435 必须空闲。
4. 用 `scripts/install_sensevoice.py`、`scripts/install_audio_models.py` 下载并校验权重；两个脚本支持 `TINGDU_DATA_DIR`。准备相同 Qwen GGUF（SHA256 在 `third_party/desktop-components.json`），创建同名 `tingdu-qwen` 模型到专用 `OLLAMA_MODELS`，停止用于初始化的 Ollama。不要使用 `ollama pull` 静默换成另一精度。
5. 将 `tingdu.env.example` 配置为 `/etc/tingdu/pilot.env`。按实例实际磁盘性能评估是否启用 Swap；本方案不自动修改 Swap 或关闭系统安全保护。
6. 在项目环境运行 `deploy/2gb/preflight.py`。安装 systemd 服务后，先通过 SSH 隧道验证：`ssh -L 8768:127.0.0.1:8768 <你的SSH用户>@<服务器IP>`，打开 `http://127.0.0.1:8768`。只监听回环地址，8768/11435 不开放公网。
7. 按下表实测，保留耗时、`systemctl show tingdu-pilot -p MemoryPeak -p MemoryCurrent`、内存/Swap 使用和错误记录。服务内存上限 1500 MiB 是保护值，不能理解为实际只需这些内存。不要在失败时无限重启或取消限制掩盖问题。
8. 私人测试通过后，才在现有 1Panel/OpenResty 中配置证书、Basic Auth 和反向代理。`nginx-https.conf.example` 仅为模板，证书路径与认证文件必须替换；启用对应 `TINGDU_ALLOWED_ORIGINS`，原始 Origin 不能改写。只给本人测试账号使用。

| 验证项 | 观察重点 |
|---|---|
| 3 分钟测试音频导入 | 相同模型是否正常输出，内存峰值 |
| 连续录音 10 分钟 | 待转写片段是否持续积压，原声是否完整 |
| 原声最终发言人校正 | 耗时、额外内存，原文是否完整 |
| 16K 总结与问答 | 是否能加载、首字/总耗时、Swap 压力 |
| 总结期间开始新录音 | 后台被回收、录音优先、结束后重算 |
| 长录音与失败恢复 | OOM 后服务仍可用，文件不损坏、不静默降级 |

**不能通过的项目必须记录为“不满足”，不能宣称全功能已在 2 GiB 稳定上线。** 本地测试不等于 Linux cgroup 下的验证。

## 当前隐私边界

以下描述未启用 `TINGDU_CLOUD_PRIVACY=1` 的旧试运行模式。1.2 新增的浏览器本机保存、隔离和迁移流程见 [CLOUD-PRIVACY.md](CLOUD-PRIVACY.md)；完成实际部署、迁移验证和最终代理切换前，仍保留 owner 密码。

此验证版本仍是单人共享工作目录，处理文件会保留在服务器；未实现多人资源隔离、浏览器离线录音历史、保存确认后的服务器清理。前端会明确提示“仅使用测试素材”。不能声称“用户文件不经服务器”或“只存用户本机”。

正式公开前还需：用户/会话隔离与鉴权、上传限额和防滥用、浏览器本地录音/历史持久保存与回听恢复、确认保存后删除服务器临时数据、断线和超期清理策略。小红书的本机浏览器登录读取不能在服务器上使用，验证期间不传个人 Cookie。

## 已有 Docker 的实例

目标实例已有 Docker 26.1.3、Compose 2.27.0；系统 Python 为 3.6.8，不满足本项目要求，可优先使用 `Dockerfile` 和 `compose.yaml` 隔离依赖，避免在 Alibaba Cloud Linux 3 上替换系统 Python。先确认官方镜像路径和当前 Docker/Compose 可用，再构建。镜像不包含用户文件；模型与测试数据单独放在 `deploy/2gb/data/`，该目录不能提交 Git。

容器仅映射服务器回环地址 8768，不映射 Ollama 11435，也不挂载 Docker socket。1500 MiB 是整个容器（网页服务、推理进程及模型服务合计）的物理内存上限；3500 MiB 是 RAM+Swap 的合计上限，**不会自动创建 Swap，实例初次检查没有 Swap，后续手动兜底测试配置见 RESULTS.md**。若原模型无法在这些限制下运行，必须如实报告失败，不能默默改变模型精度或上下文。


## 相同 GGUF 与可重复测试

发布附件提供与桌面包相同的 Q8 GGUF，安装脚本只接受 `third_party/desktop-components.json` 中固定的 SHA256，不以当前其他 GGUF 替换。容器构建完成后，在没有推理任务时执行：

```sh
docker compose -f deploy/2gb/compose.yaml run --rm --no-deps tingdu-pilot python scripts/install_sensevoice.py
docker compose -f deploy/2gb/compose.yaml run --rm --no-deps tingdu-pilot python scripts/install_audio_models.py
docker compose -f deploy/2gb/compose.yaml run --rm --no-deps tingdu-pilot python scripts/install_server_llm.py
docker compose -f deploy/2gb/compose.yaml up -d
docker compose -f deploy/2gb/compose.yaml exec tingdu-pilot python -u deploy/2gb/benchmark.py
docker compose -f deploy/2gb/compose.yaml exec tingdu-pilot python -u deploy/2gb/benchmark_summary.py
```

第一项容量测试使用合成语音生成 3 分钟导入和约 10 分钟的分段录音，实际耗时至少 10 分钟，不会打开麦克风，会新增带有 Synthetic 标题的测试资源。第二项在测试资源上调用原来的总结请求。重复单一合成声音只能验证容量与流程，不能证明复杂会议识别率或多人发言人区分准确率。内存数值是定时采样的整个容器占用（包括缓存），并非精确的单模型 RSS。


## 本次手动交换空间测试

原 16K 请求在无 Swap 时发生推理进程被终止，诊断日志显示 CPU KV buffer 为 1792 MiB，单是缓存已接近实例总内存。本次使用现有磁盘创建 root 所有、权限 600 的 `/var/lib/tingdu-pilot.swap`（2 GiB），手动启用进行后续测试，未修改模型权重或 16K/2048 请求参数。当前未写入 `/etc/fstab`，重启后不会自动启用；部署脚本也不自动修改系统交换空间。

交换空间不是物理内存，不能据此承诺性能。容器物理内存上限仍为 1500 MiB，RAM+Swap 合计上限仍为 3500 MiB。只有在确认没有活跃推理、物理内存足够回收交换页后，才适合关闭该测试交换空间；不能在模型运行中直接移除交换文件。

目标实例使用 cgroup v1，主机和原容器的 swappiness 均为 0。仅创建交换文件不足以让容器在达到自身内存上限时正常换出匿名页；`compose.yaml` 对试验容器设置 `mem_swappiness: 60`，不修改主机全局 swappiness。这一配置需在同样的内核/cgroup 环境验证，不能直接假定所有服务器兼容。
