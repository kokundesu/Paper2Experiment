# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.45", "faster-whisper>=1.0", "imageio-ffmpeg>=0.5"]
# ///
"""p2e-video: the whole clip pipeline in one cross-platform tool (macOS, Windows, Linux).

Run every command through uv, which creates the environment on first use:
    uv run p2e_video.py <command> ...

Commands
  setup                                    install headless Chromium, download the speech model, check ffmpeg
  transcribe AUDIO OUT_DIR                 word start times (words.csv) and pauses (pauses.txt) of a recording
  render PAGE OUT.mp4 [--start S] [--dur S] [--srt F]
                                           render an HTML clip page frame by frame to 1080p30 H.264 (no audio)
  level SRT AUDIO OUT.wav TOTAL [--target LUFS]
                                           denoise, even out loudness sentence by sentence, normalise, pad to TOTAL s
  build PAGE AUDIO SRT OUT_DIR NAME TOTAL [--target LUFS]
                                           level + render (with and without subtitles) + mux -> NAME.mp4,
                                           NAME_subtitled.mp4, NAME.srt
  sheet CLIP.mp4 OUT.png T1 T2 ...         one image with the frames at those seconds (3 per row)
  frames RECORDING OUT_DIR [--fps N]       split a screen recording into f00000.jpg ... (1600 px wide)
  merge OUT.mp4 CLIP1 CLIP2 ...            join clips in order into one video

ffmpeg: a system ffmpeg on PATH is used when present, otherwise the one bundled with imageio-ffmpeg (no install).
Loudness: -16 LUFS for group clips (default), -14.4 for personal videos.
"""
from __future__ import annotations

import argparse, csv, re, shutil, statistics, subprocess, sys, tempfile, time
from pathlib import Path

FPS = 30


# ---------------------------------------------------------------- helpers
def ffmpeg_bin() -> str:
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ff(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg; its log (stderr) is returned as text for parsing."""
    return subprocess.run([ffmpeg_bin(), '-hide_banner', *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', check=check)


def duration(path: str | Path) -> float:
    log = ff('-i', str(path), '-f', 'null', '-', check=False).stderr
    times = re.findall(r'time=(\d+):(\d+):([\d.]+)', log)
    if times:
        h, m, s = times[-1]
        return int(h) * 3600 + int(m) * 60 + float(s)
    h, m, s = re.search(r'Duration: (\d+):(\d+):([\d.]+)', log).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def loudness(path: str | Path, start: float | None = None, length: float | None = None) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBFS) of a file, or of one span of it."""
    cut = ['-ss', str(start), '-t', str(length)] if start is not None else []
    log = ff(*cut, '-i', str(path), '-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-', check=False).stderr
    i = float(re.findall(r'I:\s+(-?[\d.]+) LUFS', log)[-1])
    p = re.findall(r'Peak:\s+(-?[\d.]+|-inf) dBFS', log)
    return i, float(p[-1]) if p and p[-1] != '-inf' else float('-inf')


def sec(x: str) -> float:
    h, m, s = x.replace(',', '.').split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def read_srt(path: str | Path) -> list[tuple[float, float, str]]:
    text = Path(path).read_text(encoding='utf-8-sig')
    return [(sec(a), sec(b), t.strip()) for a, b, t in re.findall(r'(\S+) --> (\S+)\s*\n(.+)', text)]


# ---------------------------------------------------------------- setup
def cmd_setup(a):
    print('ffmpeg     ', ffmpeg_bin())
    filters = ff('-filters', check=False).stdout
    missing = [f for f in ('afftdn', 'acompressor', 'alimiter', 'ebur128', 'silencedetect', 'tile') if f' {f} ' not in filters]
    encoders = ff('-encoders', check=False).stdout
    if 'libx264' not in encoders:
        missing.append('libx264')
    print('  missing:', ', '.join(missing) if missing else 'nothing')
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
    print('chromium    installed (Playwright)')
    from faster_whisper import WhisperModel
    WhisperModel('base.en', device='cpu', compute_type='int8')
    print('whisper     base.en ready')
    if missing:
        sys.exit('ffmpeg lacks the features above: install a full build (macOS: brew install ffmpeg; '
                 'Windows: winget install Gyan.FFmpeg) and open a new terminal')


# ---------------------------------------------------------------- transcribe
def cmd_transcribe(a):
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    wav = out / 'a16.wav'
    ff('-y', '-i', a.audio, '-ar', '16000', '-ac', '1', str(wav))
    print(f'duration: {duration(a.audio):.2f} s')
    from faster_whisper import WhisperModel
    model = WhisperModel('base.en', device='cpu', compute_type='int8')
    segments, _ = model.transcribe(str(wav), word_timestamps=True, vad_filter=False)
    words = [(w.start, w.end, w.word.strip()) for s in segments for w in s.words]
    with open(out / 'words.csv', 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows([('start', 'end', 'word'), *[(f'{s:.2f}', f'{e:.2f}', w) for s, e, w in words]])
    print('--- words (start time in s) ---')
    cells = [f'{s:6.2f} {w}' for s, _, w in words]
    for i in range(0, len(cells), 6):
        print('   '.join(cells[i:i + 6]))
    log = ff('-i', str(wav), '-af', 'silencedetect=noise=-40dB:d=0.15', '-f', 'null', '-', check=False).stderr
    marks = [float(x) for x in re.findall(r'silence_(?:start|end): ([\d.]+)', log)]
    pauses = [(marks[i], marks[i + 1]) for i in range(0, len(marks) - 1, 2)]
    (out / 'pauses.txt').write_text('\n'.join(f'{s:.2f}-{e:.2f}' for s, e in pauses) + '\n', encoding='utf-8')
    print('--- pauses (speech resumes at the second number) ---')
    print('  '.join(f'{s:.2f}-{e:.2f}' for s, e in pauses))


# ---------------------------------------------------------------- render
def render(page: str, out: str, start: float = 0.0, dur: float | None = None, srt: str | None = None):
    from playwright.sync_api import sync_playwright
    url = Path(page).resolve().as_uri() + '?capture'
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1)
        pg.goto(url)
        pg.wait_for_function('typeof window.seek === "function"')
        if srt:
            pg.evaluate('c => { window.SUBS = c; }', [list(c) for c in read_srt(srt)])
        end = pg.evaluate('END') if dur is None else start + dur
        n = max(1, int(round((end - start) * FPS)))
        enc = subprocess.Popen([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'image2pipe',
                                '-framerate', str(FPS), '-c:v', 'png', '-i', '-', '-c:v', 'libx264', '-preset', 'slow',
                                '-crf', '16', '-pix_fmt', 'yuv420p', '-r', str(FPS), out], stdin=subprocess.PIPE)
        t0 = time.time()
        for i in range(n):
            pg.evaluate(f'seek({start + i / FPS})')
            pg.wait_for_function('[...document.images].every(im => !im.src || (im.complete && im.naturalWidth > 0))')
            enc.stdin.write(pg.screenshot(type='png'))
            if n > 1 and i % 300 == 0:
                print(f'  {i}/{n} frames, {time.time() - t0:.0f}s', flush=True)
        enc.stdin.close(); enc.wait()
        browser.close()
    print(f'rendered {n} frames -> {out}')


def cmd_render(a):
    render(a.page, a.out, a.start, a.dur, a.srt)


# ---------------------------------------------------------------- level
def level(srt: str, src: str, out: str, total: float, target: float = -16.0):
    """Highpass + light denoise + light compression, then one gain per subtitle span (switched in the middle of the
    pause between sentences), one static gain to the target loudness, and a limiter. Three correction rounds bring
    every sentence within ~0.1 LU of the others. The timeline is untouched, so subtitles and scene times stay valid."""
    segs = [(s, e) for s, e, _ in read_srt(srt)]

    def run(gains):
        cuts = [0.0] + [(segs[i][1] + segs[i + 1][0]) / 2 for i in range(len(segs) - 1)]
        expr = '1'
        for c, g in zip(cuts, gains):   # latest cut outermost: the first true test picks the right gain
            expr = f"if(gte(t\\,{c:.3f})\\,{10 ** (g / 20):.4f}\\,{expr})"
        pre = ("highpass=f=80,afftdn=nr=12:nf=-60:tn=1,acompressor=threshold=0.03:ratio=2.5:attack=10:release=250:knee=4,"
               f"volume=volume='{expr}':eval=frame")
        # not loudnorm: it falls back to its own AGC when a linear gain would clip, undoing the per-sentence gains
        i = float(re.findall(r'I:\s+(-?[\d.]+) LUFS', ff('-i', src, '-af', pre + ',ebur128', '-f', 'null', '-',
                                                          check=False).stderr)[-1])
        post = f"volume={target - i:.2f}dB,alimiter=limit=0.84:attack=5:release=50:level=false"
        ff('-loglevel', 'error', '-y', '-i', src, '-af', f'{pre},{post},aresample=48000,apad=whole_dur={total}',
           '-t', str(total), '-c:a', 'pcm_s16le', out)
        return [loudness(out, s, e - s)[0] for s, e in segs]

    before = [loudness(src, s, e - s)[0] for s, e in segs]
    med = statistics.median(before)
    gains = [max(-8, min(10, med - x)) for x in before]
    for _ in range(3):
        after = run(gains)
        m = statistics.median(after)
        gains = [max(-8, min(10, g + (m - x))) for g, x in zip(gains, after)]
    after = run(gains)
    print(f'target {target} LUFS · sentence spread before {max(before) - min(before):.1f} LU, '
          f'after {max(after) - min(after):.1f} LU')
    for (s, e), x, g, y in zip(segs, before, gains, after):
        print(f'  {s:6.2f}-{e:6.2f}  before {x:6.1f}  gain {g:+5.1f} dB  after {y:6.1f}')


def cmd_level(a):
    level(a.srt, a.audio, a.out, a.total, a.target)


# ---------------------------------------------------------------- build
def cmd_build(a):
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        level(a.srt, a.audio, str(tmp / 'audio.wav'), a.total, a.target)
        render(a.page, str(tmp / 'v.mp4'))
        render(a.page, str(tmp / 'v_sub.mp4'), srt=a.srt)
        for v, name in (('v', a.name), ('v_sub', f'{a.name}_subtitled')):
            ff('-loglevel', 'error', '-y', '-i', str(tmp / f'{v}.mp4'), '-i', str(tmp / 'audio.wav'), '-map', '0:v',
               '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', str(a.total),
               '-movflags', '+faststart', str(out / f'{name}.mp4'))
    shutil.copy(a.srt, out / f'{a.name}.srt')
    i, p = loudness(out / f'{a.name}.mp4')
    print(f'--- {out / (a.name + ".mp4")}\n  length {duration(out / (a.name + ".mp4")):.2f} s · '
          f'loudness {i:.1f} LUFS · peak {p:.1f} dBFS')


# ---------------------------------------------------------------- sheet, frames, merge
def cmd_sheet(a):
    sel = '+'.join(f'eq(n\\,{round(t * FPS)})' for t in a.times)
    rows = (len(a.times) + 2) // 3
    ff('-loglevel', 'error', '-y', '-i', a.clip, '-vf', f"select='{sel}',scale=800:-1,tile=3x{rows}",
       '-frames:v', '1', '-fps_mode', 'vfr', a.out)
    print(a.out)


def cmd_frames(a):
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    ff('-loglevel', 'error', '-y', '-i', a.recording, '-vf', f'fps={a.fps},scale=1600:-2', '-q:v', '3',
       str(out / 'f%05d.jpg'))
    print(f'{len(list(out.glob("f*.jpg")))} frames in {out} (frame i is at i/{a.fps} s of the recording)')


def cmd_merge(a):
    args, f = [], ''
    for i, c in enumerate(a.clips):
        args += ['-i', c]
        f += (f'[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,'
              f'fps={FPS},setsar=1[v{i}];[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];')
    f += ''.join(f'[v{i}][a{i}]' for i in range(len(a.clips))) + f'concat=n={len(a.clips)}:v=1:a=1[v][a]'
    ff('-loglevel', 'error', '-y', *args, '-filter_complex', f, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
       '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
       a.out)
    i, _ = loudness(a.out)
    print(f'{a.out}: {duration(a.out):.1f} s (limit 300 s), {i:.1f} LUFS')


# ---------------------------------------------------------------- CLI
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('setup').set_defaults(fn=cmd_setup)
    s = sub.add_parser('transcribe'); s.add_argument('audio'); s.add_argument('out_dir'); s.set_defaults(fn=cmd_transcribe)
    s = sub.add_parser('render'); s.add_argument('page'); s.add_argument('out')
    s.add_argument('--start', type=float, default=0.0); s.add_argument('--dur', type=float); s.add_argument('--srt')
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser('level'); s.add_argument('srt'); s.add_argument('audio'); s.add_argument('out')
    s.add_argument('total', type=float); s.add_argument('--target', type=float, default=-16.0); s.set_defaults(fn=cmd_level)
    s = sub.add_parser('build')
    for n in ('page', 'audio', 'srt', 'out_dir', 'name'):
        s.add_argument(n)
    s.add_argument('total', type=float); s.add_argument('--target', type=float, default=-16.0); s.set_defaults(fn=cmd_build)
    s = sub.add_parser('sheet'); s.add_argument('clip'); s.add_argument('out'); s.add_argument('times', type=float, nargs='+')
    s.set_defaults(fn=cmd_sheet)
    s = sub.add_parser('frames'); s.add_argument('recording'); s.add_argument('out_dir')
    s.add_argument('--fps', type=float, default=3); s.set_defaults(fn=cmd_frames)
    s = sub.add_parser('merge'); s.add_argument('out'); s.add_argument('clips', nargs='+'); s.set_defaults(fn=cmd_merge)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
