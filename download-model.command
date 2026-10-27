#!/bin/zsh
cd "$(dirname "$0")"
if [ ! -x .runtime/bin/python ]; then
  echo '请先双击 start.command 安装运行环境。'
  exit 1
fi
.runtime/bin/python scripts/install_sensevoice.py || exit 1
echo 'SenseVoiceSmall INT8 模型已安装并校验完成。'
