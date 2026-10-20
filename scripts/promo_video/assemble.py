import json, subprocess
T = json.load(open('timeline.json')); D = json.load(open('durations.json'))
fr = T['frames']; t0 = fr[0]
a, b = T['sentAt'], T['doneAt']
k = min(1.0, 3.0 / (b - a)) if b - a > 4 else 1.0
def m(t):
    if t <= a: return t - t0
    if t <= b: return a - t0 + (t - a) * k
    return a - t0 + (b - a) * k + (t - b)
end = m(T['endAt'])
with open('concat.txt', 'w') as f:
    for i, t in enumerate(fr):
        nxt = fr[i + 1] if i + 1 < len(fr) else T['endAt']
        f.write(f"file 'frames/{i:05d}.jpg'\nduration {max(0.001, m(nxt) - m(t)):.4f}\n")
    f.write(f"file 'frames/{len(fr)-1:05d}.jpg'\n")
# 旁白：每段在其场景起点（intro 稍后 0.3s）
inputs, filt = [], []
for i, (key, start) in enumerate(T['marks'].items()):
    inputs += ['-i', f'audio/{key}.wav']
    ms = int((m(start) + (0.4 if key in ('intro', 'outro') else 0.15)) * 1000)
    filt.append(f"[{i+1}:a]adelay={ms}|{ms}[a{i}]")
n = len(T['marks'])
fc = ';'.join(filt) + ';' + ''.join(f'[a{i}]' for i in range(n)) + f"amix=inputs={n}:normalize=0,apad,atrim=0:{end:.2f},loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={end-1:.2f}:d=1[aout]"
fc = f"[0:v]fps=30,scale=1920:1200:flags=lanczos,format=yuv420p,fade=t=out:st={end-0.8:.2f}:d=0.8[vout];" + fc
cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', 'concat.txt', *inputs,
       '-filter_complex', fc, '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
       '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-t', f'{end:.2f}', 'relay-promo.mp4']
subprocess.run(cmd, check=True)
print('duration', round(end, 1), 'compress k', round(k, 2))
