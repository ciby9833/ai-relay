#!/bin/sh
# 生成 Relay 演示视频：旁白 → 录屏 → 合成。需要 .env 里 DEV_LOGIN=true、本机装有 Chrome 和 ffmpeg。
# 用法：sh scripts/promo_video/make.sh   产物：scripts/promo_video/out/relay-promo.mp4
set -e
cd "$(dirname "$0")"
ROOT=../..
mkdir -p out && cd out
cp ../record.mjs ../assemble.py ../lines.json .
[ -d node_modules/playwright ] || { npm init -y >/dev/null; npm i playwright@1.56.1; }
# 1. 旁白：每段 TTS 的时长决定每个场景至少停留多久
mkdir -p audio
python3 - <<'PY'
import json, subprocess
lines = json.load(open('lines.json')); d = {}
for k, v in lines.items():
    subprocess.run(['say', '-v', 'Tingting', '-r', '210', '-o', f'audio/{k}.aiff', v], check=True)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', f'audio/{k}.aiff', '-ar', '48000', '-ac', '2', f'audio/{k}.wav'], check=True)
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f'audio/{k}.wav'], capture_output=True, text=True).stdout
    d[k] = round(float(out), 2)
json.dump(d, open('durations.json', 'w'))
PY
# 2. 每次录制前重置演示数据，保证每一遍画面一致
(cd ../$ROOT && docker compose exec -T api python - < scripts/seed_demo.py)
# 3. 录屏（CDP screencast 帧 + 时间戳）  4. 按时间戳合成视频并对齐旁白
node record.mjs
python3 assemble.py
