"""Render the narrated demo video: real command output + edge-tts narration.

Usage: python demo/render.py   (needs ffmpeg, edge-tts, Pillow and bumprisk on PATH)
Every terminal scene runs its commands for real and shows the actual output;
each scene lasts exactly as long as its narration.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
OUT = os.path.join(ROOT, "demo.mp4")
SHOP = "/tmp/shop-web"
W, H, FPS = 1280, 720, 24
VOICE = "en-US-AndrewNeural"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG, FG = (24, 26, 33), (220, 223, 228)
ANSI = {"31": (255, 95, 95), "32": (95, 215, 120), "33": (240, 200, 80), "2": (130, 135, 145), "36": (90, 200, 230)}
PROMPT = "dev@laptop $ "

SCENES = [
    {"kind": "title", "title": "bumprisk", "sub": "what does this lockfile change\nactually pull in?",
     "say": "This is bumprisk, a small open source tool that answers one question about a pull request: what does "
            "this lockfile change actually pull in? It reads the npm or Python lockfile diff and checks every added "
            "or bumped package against the npm registry, PyPI and O S V."},
    {"kind": "bullets", "title": "The problem",
     "bullets": ["Bot PRs change 3,000 lockfile lines; nobody reads them",
                 "axios 1.14.1 (Mar 31 2026): new dep plain-crypto-js,",
                 "   malicious install script, pulled within hours",
                 "chalk / debug (Sep 2025): hijacked patch releases, ~2 h live",
                 "PyPI: ultralytics 8.3.41, num2words 0.5.15"],
     "say": "Dependency bots open pull requests that change thousands of lockfile lines, and they get approved "
            "because package dot json barely changed. That's where recent attacks landed. In March, a hijacked "
            "axios release quietly added a new dependency with a malicious install script. Last September, chalk "
            "and debug got poisoned patch releases that were live for about two hours. PyPI had the same with "
            "ultralytics and num2words."},
    {"kind": "term", "cwd": "root",
     "cmds": ["bumprisk compare examples/npm/old/package-lock.json examples/npm/new/package-lock.json; echo \"exit $?\""],
     "say": "Here are two real lockfiles from those incidents. bumprisk compare shows plain crypto j s was replaced "
            "by an npm security placeholder, O S V lists the axios, chalk and debug versions as malware, and they "
            "were removed from the registry. vite is a normal bump and is summarised as fine. Exit code one fails "
            "the build."},
    {"kind": "term", "cwd": "root",
     "cmds": ["bumprisk compare examples/python/old/requirements.txt examples/python/new/requirements.txt; echo \"exit $?\""],
     "say": "Same for Python. num2words zero point five fifteen is malware and gone from PyPI, requests two thirty "
            "two zero was yanked, ultralytics eight three forty one was deleted. The urllib3 bump fixes four known "
            "vulnerabilities and adds none, so it is listed as fine. Add dash v to see that note."},
    {"kind": "term", "cwd": "shop",
     "cmds": ["git log --oneline main..", "bumprisk diff --base main; echo \"exit $?\""],
     "say": "Most pull requests aren't incidents, so here's a routine weekly bump in a git repo. bumprisk diff "
            "finds the changed lockfiles itself. axios zero thirty five was published four hours ago, inside the "
            "seven day cooldown. nx is three days old. esbuild is new and runs a postinstall script. typescript is "
            "a major bump. Nothing reaches the high threshold, so it exits zero, but the reviewer knows exactly "
            "what to look at, with an npm diff command for each bump."},
    {"kind": "bullets", "title": "In CI",
     "bullets": ["uses: hamarshehmhmd/bumprisk@v0.1.0",
                 "   compares the PR's lockfiles with the base branch",
                 "Markdown table in the job summary",
                 "--fail-on critical|high|medium|low   --cooldown 7",
                 "npm, yarn, pnpm, requirements, Poetry, uv, PDM, Pipfile"],
     "say": "In GitHub Actions it's one step. It compares the pull request against the base branch, writes a "
            "markdown table to the job summary, and fails at the threshold you pick. It reads npm, yarn and pnpm "
            "lockfiles, plus requirements files, Poetry, uv, P D M and Pipfile locks."},
    {"kind": "bullets", "title": "Try it",
     "bullets": ["curl -fsSL https://raw.githubusercontent.com/",
                 "   hamarshehmhmd/bumprisk/main/install.sh | sh",
                 "bumprisk diff",
                 "Metadata + OSV only: not a tarball malware scanner",
                 "GNU AGPL-3.0 (commercial licenses available)"],
     "say": "To be clear, it doesn't download or scan tarballs. It uses registry metadata and O S V, so a fresh "
            "attack shows up as hours old with a new install script, not as malware. Install it with one line and "
            "run bumprisk diff. It's licensed under the GNU A G P L version 3, with commercial licenses available "
            "from the author. It's on GitHub at hamarsheh m h m d slash bumprisk."},
]


async def tts(text, path):
    import edge_tts
    for attempt in range(8):  # the edge-tts service occasionally returns no audio; retry
        try:
            await edge_tts.Communicate(text, VOICE, rate="+4%").save(path)
            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == 7:
                raise
            await asyncio.sleep(5)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path], text=True)
    return float(out.strip())


def run_cmd(cmd, cwd):
    env = dict(os.environ, FORCE_COLOR="1")
    env.pop("NO_COLOR", None)
    env["PATH"] = os.path.dirname(shutil.which("bumprisk")) + os.pathsep + env["PATH"]
    full = cmd
    p = subprocess.run(["bash", "-c", "shopt -s nullglob; " + full], cwd=cwd, capture_output=True, text=True, env=env)
    out = (p.stdout + p.stderr).rstrip("\n")
    # pretty-print hook JSON
    if out.startswith("{"):
        import json
        try:
            out = json.dumps(json.loads(out), indent=2)
        except ValueError:
            pass
    return out


def parse_ansi(line):
    """Return [(text, color, bold)] spans for a line with SGR codes."""
    spans, color, bold = [], FG, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            for code in (m.group(1) or "0").split(";"):
                if code == "0":
                    color, bold = FG, False
                elif code == "1":
                    bold = True
                elif code in ANSI:
                    color = ANSI[code]
        elif part:
            spans.append((part, color, bold))
    return spans


class Term:
    def __init__(self):
        self.font = ImageFont.truetype(MONO, 15)
        self.bold = ImageFont.truetype(MONO_B, 15)
        self.cw = self.font.getlength("M")
        self.lh = 21
        self.cols = int((W - 80) / self.cw)

    def wrap(self, spans):
        lines, cur, n = [], [], 0
        for text, c, b in spans:
            while text:
                room = self.cols - n
                if len(text) <= room:
                    cur.append((text, c, b)); n += len(text); text = ""
                else:
                    cut = text.rfind(" ", 0, room + 1)
                    cut = cut if cut > 0 else room
                    cur.append((text[:cut], c, b)); lines.append(cur); cur, n = [], 0
                    text = "    " + text[cut:].lstrip(" ")
        lines.append(cur)
        return lines

    def frame(self, lines, cursor=False):
        title = getattr(self, "title", "~/bumprisk — bash")
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 14, W - 20, H - 14], 12, fill=(30, 33, 41), outline=(60, 64, 76))
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([40 + i * 24, 30, 54 + i * 24, 44], fill=c)
        d.text((W // 2, 37), title, font=ImageFont.truetype(SANS, 15), fill=(150, 155, 165), anchor="mm")
        visible = lines[-30:]
        y = 64
        for ln in visible:
            x = 40
            for text, c, b in ln:
                d.text((x, y), text, font=self.bold if b else self.font, fill=c)
                x += self.cw * len(text)
            y += self.lh
        if cursor:
            last = visible[-1] if visible else []
            x = 40 + self.cw * sum(len(t) for t, _, _ in last)
            d.rectangle([x, y - self.lh + 3, x + self.cw - 2, y - 4], fill=FG)
        return img


def card(scene):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if scene["kind"] == "title":
        d.text((W // 2, 280), scene["title"], font=ImageFont.truetype(MONO_B, 84), fill=(95, 215, 120), anchor="mm")
        d.multiline_text((W // 2, 420), scene["sub"], font=ImageFont.truetype(SANS, 34), fill=FG, anchor="mm",
                         align="center", spacing=12)
        d.text((W // 2, 620), "github.com/hamarshehmhmd/bumprisk  ·  npm + PyPI + OSV  ·  GNU AGPL-3.0", font=ImageFont.truetype(SANS, 22),
               fill=(150, 155, 165), anchor="mm")
    else:
        d.text((90, 90), scene["title"], font=ImageFont.truetype(SANS_B, 52), fill=(95, 215, 120))
        f = ImageFont.truetype(SANS, 29)
        y = 200
        for b in scene["bullets"]:
            if b and not b.startswith("   "):
                d.text((90, y), "•", font=f, fill=(240, 200, 80))
            d.text((130, y), b.strip(), font=f, fill=FG)
            y += 58 if b.startswith("   ") or not b else 62
    return img


class Writer:
    def __init__(self, path, audio):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio,
                                   "-af", "apad", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                   "-shortest", path], stdin=subprocess.PIPE)
        self.n = 0

    def put(self, img, count=1):
        data = img.tobytes()
        for _ in range(count):
            self.p.stdin.write(data)
        self.n += count

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        if self.p.returncode:
            sys.exit("ffmpeg failed")


def render_scene(i, scene, workdir):
    workdir = SHOP if scene.get("cwd") == "shop" else ROOT
    audio = os.path.join(BUILD, f"s{i}.mp3")
    if not os.path.exists(audio):
        asyncio.run(tts(scene["say"], audio))
    total = int((duration(audio) + 0.7) * FPS)
    path = os.path.join(BUILD, f"s{i}.mp4")
    w = Writer(path, audio)
    if scene["kind"] != "term":
        w.put(card(scene), total)
        w.close()
        return path
    t = Term()
    if scene.get("cwd") == "shop":
        t.title = "~/shop-web (branch deps/weekly) — bash"
    shown = scene.get("show", scene["cmds"])
    outputs = [run_cmd(c, workdir) for c in scene["cmds"]]
    # When a scene's displayed command differs from what runs (heredoc), show
    # the display lines; the last displayed line always maps to the last command.
    steps = []
    if len(shown) != len(scene["cmds"]):
        steps = [(s, "") for s in shown[:-1]] + [(shown[-1], outputs[-1])]
    else:
        steps = list(zip(shown, outputs))
    # timing budget: typing ~ 30 chars/s, then pause, spread over the narration
    typing = sum(len(s) for s, _ in steps) / 32 * FPS
    pause = max(6, int((total - typing) / max(1, len(steps))) - 4)
    lines = []
    for cmd, out in steps:
        prompt = [(PROMPT, (95, 215, 120), True)]
        for k in range(0, len(cmd) + 1, 2):
            frame = t.frame(lines + t.wrap(prompt + [(cmd[:k], FG, False)]), cursor=True)
            w.put(frame)
        lines += t.wrap(prompt + [(cmd, FG, False)])
        for ol in out.splitlines():
            lines += t.wrap(parse_ansi(ol))
        lines.append([])
        hold = min(pause, max(0, total - w.n))
        w.put(t.frame(lines), hold)
    final = t.frame(lines + t.wrap([(PROMPT, (95, 215, 120), True)]), cursor=True)
    if w.n < total:
        w.put(final, total - w.n)
    w.close()
    return path


def main():
    os.makedirs(BUILD, exist_ok=True)
    subprocess.run(["sh", os.path.join(HERE, "setup.sh"), SHOP], check=True)
    workdir = ROOT
    parts = [render_scene(i, s, workdir) for i, s in enumerate(SCENES)]
    with open(os.path.join(BUILD, "list.txt"), "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    os.path.join(BUILD, "list.txt"), "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", OUT], check=True)
    with open(os.path.join(BUILD, "narration.txt"), "w") as fh:
        fh.write("\n\n".join(s["say"] for s in SCENES) + "\n")
    print(OUT, round(duration(OUT), 1), "s")


if __name__ == "__main__":
    main()
