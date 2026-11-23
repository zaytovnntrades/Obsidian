"""Render the 30 Days of Philosophers series as 9:16 TikTok videos.

Usage:  python render.py OUT_DIR [day ...]     (no days = all 30)
Needs:  pip install pillow numpy ; ffmpeg on PATH
"""
import colorsys, math, os, random, subprocess, sys, wave
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from philosophers import DAYS

W, H, FPS = 1080, 1920, 30
# TikTok safe zone: avoid right-side buttons and bottom caption area
L, R, TOP, BOT = 90, W - 170, 260, H - 470
BOXW = R - L

def _font(*cands):
    for c in cands:
        if os.path.exists(c): return c
    raise FileNotFoundError(cands)
SERIF_I = _font("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")
SERIF_B = _font("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")
SANS_B = _font("/usr/share/fonts/opentype/inter/Inter-Bold.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
SANS_M = _font("/usr/share/fonts/opentype/inter/Inter-Medium.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
SANS_SB = _font("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", SANS_B)
FC = {}
def F(path, size):
    k = (path, size)
    if k not in FC: FC[k] = ImageFont.truetype(path, size)
    return FC[k]

WHITE, MUTE = (246, 242, 234), (170, 165, 155)

def ease(t): t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3

def wrap(text, font, maxw, d):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=font) <= maxw: cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def fit(text, path, start, maxw, maxh, lh=1.28, minsize=34):
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    s = start
    while True:
        f = F(path, s); lines = wrap(text, f, maxw, d)
        if len(lines) * s * lh <= maxh or s <= minsize: return f, lines, int(s * lh)
        s -= 2

def text_block(lines, font, lh, fill, align="center", x0=L, width=BOXW):
    """Return RGBA layer (cropped height) with the given lines."""
    h = lh * len(lines) + 20
    im = Image.new("RGBA", (W, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        w = d.textlength(ln, font=font)
        x = x0 + (width - w) / 2 if align == "center" else x0
        d.text((x, i * lh), ln, font=font, fill=fill + (255,))
    return im

def accent_for(i):
    h = (0.08 + i * 0.137) % 1.0
    r, g, b = colorsys.hls_to_rgb(h, 0.66, 0.72)
    return (int(r * 255), int(g * 255), int(b * 255)), h

def make_bg(hue):
    y = np.linspace(0, 1, H)[:, None]; x = np.linspace(-1, 1, W)[None, :]
    r1, g1, b1 = colorsys.hls_to_rgb(hue, 0.05, 0.5)
    r2, g2, b2 = colorsys.hls_to_rgb(hue, 0.14, 0.45)
    c1, c2 = np.array([r1, g1, b1]) * 255, np.array([r2, g2, b2]) * 255
    base = c1[None, None, :] * (1 - y[..., None]) + c2[None, None, :] * y[..., None]
    base = np.broadcast_to(base, (H, W, 3)).copy()
    glow = np.exp(-((x * 1.1) ** 2 + ((y - 0.38) * 2.3) ** 2))[..., None]
    base += glow * c2 * 0.9
    vig = 1 - 0.55 * np.clip(np.sqrt(x ** 2 * 0.6 + ((y - 0.5) * 1.6) ** 2), 0, 1)[..., None] ** 2
    base *= vig
    noise = np.random.default_rng(1).normal(0, 3.5, (H, W, 1))
    return Image.fromarray(np.clip(base + noise, 0, 255).astype(np.uint8))

def fade(layer, a):
    if a >= 0.999: return layer
    out = layer.copy(); al = out.getchannel("A").point(lambda v: int(v * a)); out.putalpha(al); return out

def place(frame, layer, y, a, slide=40):
    if a <= 0.003: return
    lay = fade(layer, a)
    frame.alpha_composite(lay, (0, int(y + (1 - a) * slide)))

# ---------- audio ----------
def make_audio(path, dur, root, cues):
    SR = 44100; t = np.arange(int(SR * dur)) / SR
    chord = [1, 1.2599, 1.4983, 2.0]  # minor-ish add9 pad
    pad = sum(0.05 * np.sin(2 * np.pi * root * c * t + 0.3 * np.sin(2 * np.pi * 0.15 * t * (k + 1))) for k, c in enumerate(chord))
    pad += 0.03 * np.sin(2 * np.pi * root / 2 * t)
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.11 * t)
    a = pad * lfo * np.minimum(1, t / 1.5) * np.minimum(1, (dur - t) / 1.8)
    for st, mul in cues:  # soft bell at section changes
        idx = t >= st; x = t[idx] - st
        f = root * 4 * mul
        a[idx] += 0.09 * (np.sin(2 * np.pi * f * x) + 0.4 * np.sin(2 * np.pi * f * 2.01 * x)) * np.exp(-x * 2.2)
    a = (a / np.abs(a).max() * 0.7 * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(a.tobytes())

# ---------- render one day ----------
def render(args):
    idx, out_dir = args
    p = DAYS[idx]; day = idx + 1
    nxt = DAYS[idx + 1]["name"] if idx + 1 < len(DAYS) else None
    acc, hue = accent_for(idx)
    bg = make_bg(hue).convert("RGBA")
    rnd = random.Random(day)

    # timings
    qw, ww = len(p["quote"].split()), len(p["why"].split())
    T1 = 4.0
    T2 = T1 + max(7.0, qw / 2.6 + 3.0)
    T3 = T2 + max(7.5, ww / 3.0 + 2.5)
    T4 = T3 + 6.0
    DUR = T4
    N = int(DUR * FPS)

    # ---- static layers ----
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    # header
    header = Image.new("RGBA", (W, 160), (0, 0, 0, 0)); hd = ImageDraw.Draw(header)
    hd.text((L, 30), f"DAY {day:02d} / 30", font=F(SANS_B, 40), fill=acc + (255,))
    hd.text((L, 85), "30 DAYS OF PHILOSOPHY", font=F(SANS_SB, 28), fill=MUTE + (255,))

    # S1 hook + name
    f, ln, lh = fit(p["hook"], SANS_B, 84, BOXW, 420)
    hook = text_block(ln, f, lh, WHITE); hook_h = lh * len(ln)
    fn, lnn, lhn = fit(p["name"], SERIF_B, 120, BOXW, 300)
    name = text_block(lnn, fn, lhn, acc); name_h = lhn * len(lnn)
    meta = text_block([p["years"], p["tag"]], F(SANS_M, 44), 62, MUTE)
    s1_total = hook_h + 90 + name_h + 30 + 124
    s1_y = TOP + (BOT - TOP - s1_total) / 2 - 40

    # S2 quote (word-by-word reveal, cached states)
    fq, lnq, lhq = fit("“" + p["quote"] + "”", SERIF_I, 120 if len(p["quote"]) < 60 else 96, BOXW, 820, lh=1.3)
    q_h = lhq * len(lnq)
    attrib = text_block([f"— {p['name']}", p["source"]], F(SANS_M, 40), 58, MUTE)
    q_y = TOP + 60 + (BOT - TOP - 60 - q_h - 160) / 2
    words_per_line = [l.split() for l in lnq]
    total_words = sum(len(w) for w in words_per_line)
    qcache = {}
    def quote_layer(k):
        if k not in qcache:
            im = Image.new("RGBA", (W, q_h + 30), (0, 0, 0, 0)); d = ImageDraw.Draw(im); c = 0
            for i, wl in enumerate(words_per_line):
                full = " ".join(wl); lw = d.textlength(full, font=fq); x = L + (BOXW - lw) / 2
                for w in wl:
                    col = WHITE + (255,) if c < k else WHITE + (38,)
                    d.text((x, i * lhq), w, font=fq, fill=col); x += d.textlength(w + " ", font=fq); c += 1
            qcache[k] = im
        return qcache[k]
    bigq = Image.new("RGBA", (W, 400), (0, 0, 0, 0))
    ImageDraw.Draw(bigq).text((L - 20, -40), "“", font=F(SERIF_B, 420), fill=acc + (45,))

    # S3 why
    lab3 = text_block(["WHY IT MATTERS"], F(SANS_B, 40), 50, acc, align="left")
    fw, lnw, lhw = fit(p["why"], SANS_M, 64, BOXW, 900, lh=1.38)
    why = text_block(lnw, fw, lhw, WHITE, align="left"); why_h = lhw * len(lnw)
    s3_y = TOP + (BOT - TOP - why_h - 110) / 2

    # S4 action + CTA
    lab4 = text_block(["TRY THIS TODAY"], F(SANS_B, 40), 50, acc, align="left")
    fa, lna, lha = fit(p["action"], SANS_B, 70, BOXW - 80, 560, lh=1.3)
    act_h = lha * len(lna)
    act = Image.new("RGBA", (W, act_h + 100), (0, 0, 0, 0)); ad = ImageDraw.Draw(act)
    ad.rounded_rectangle([L, 0, R, act_h + 80], radius=28, fill=acc + (34,), outline=acc + (200,), width=4)
    for i, l in enumerate(lna): ad.text((L + 40, 40 + i * lha), l, font=fa, fill=WHITE + (255,))
    if nxt:
        cta_lines = [f"Follow for Day {day + 1}:", nxt]
    else:
        cta_lines = ["You finished all 30 days.", "Which one changed you? Comment below."]
    cta = text_block(cta_lines[:1], F(SANS_M, 44), 60, MUTE)
    fc2, lnc2, lhc2 = fit(cta_lines[1], SERIF_B if nxt else SANS_B, 64 if nxt else 54, BOXW, 200)
    cta2 = text_block(lnc2, fc2, lhc2, acc)
    s4_y = TOP + (BOT - TOP - (act_h + 80) - 70 - 240) / 2

    # dust particles
    dust = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(0.3, 1.2), rnd.uniform(1.5, 4), rnd.uniform(0, 6.28)) for _ in range(70)]

    # ---- audio ----
    roots = [110, 123.5, 130.8, 146.8, 164.8, 98, 87.3]
    wav = os.path.join(out_dir, f".tmp_day{day:02d}.wav")
    make_audio(wav, DUR, roots[idx % len(roots)], [(0.2, 1.0), (T1, 1.26), (T2, 1.5), (T3, 2.0)])

    slug = p["name"].lower().replace(" ", "-").replace("é", "e").replace("ø", "o").replace("'", "")
    out = os.path.join(out_dir, f"day{day:02d}_{slug}.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", wav,
                           "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out],
                          stdin=subprocess.PIPE)
    for i in range(N):
        t = i / FPS
        fr = bg.copy(); d = ImageDraw.Draw(fr)
        for (x, y, v, s, ph) in dust:
            yy = (y - v * i * 1.2) % H; xx = x + 14 * math.sin(t * 0.6 + ph)
            al = int(60 + 50 * math.sin(t * 1.3 + ph))
            d.ellipse([xx - s, yy - s, xx + s, yy + s], fill=acc + (al,))
        # progress bar + header
        d.rounded_rectangle([L, 210, R, 218], radius=4, fill=(255, 255, 255, 30))
        d.rounded_rectangle([L, 210, L + (R - L) * day / 30, 218], radius=4, fill=acc + (230,))
        place(fr, header, 70, ease(t / 0.6), slide=0)
        # section timeline progress (thin line under bar)
        d.rectangle([L, 228, L + (R - L) * min(1, t / DUR), 231], fill=(255, 255, 255, 70))

        def win(t0, t1, fin=0.5, fout=0.45):
            return ease((t - t0) / fin) * (1 - ease((t - (t1 - fout)) / fout))
        # S1
        if t < T1 + 0.1:
            a = win(0, T1)
            place(fr, hook, s1_y, a * ease(t / 0.6))
            place(fr, name, s1_y + hook_h + 90, a * ease((t - 1.2) / 0.6))
            place(fr, meta, s1_y + hook_h + 90 + name_h + 30, a * ease((t - 1.7) / 0.6))
        # S2
        if T1 - 0.1 <= t < T2 + 0.1:
            a = win(T1, T2)
            place(fr, bigq, max(250, q_y - 230), a, slide=0)
            reveal = ease((t - T1 - 0.2) / max(1.5, min(4.5, total_words * 0.14)))
            k = int(round(reveal * total_words))
            place(fr, quote_layer(k), q_y, a)
            place(fr, attrib, q_y + q_h + 50, a * ease((t - T1 - 1.0 - total_words * 0.14) / 0.6))
        # S3
        if T2 - 0.1 <= t < T3 + 0.1:
            a = win(T2, T3)
            place(fr, lab3, s3_y, a)
            place(fr, why, s3_y + 110, a * ease((t - T2 - 0.25) / 0.6))
        # S4
        if t >= T3 - 0.1:
            a = ease((t - T3) / 0.5)
            place(fr, lab4, s4_y, a)
            place(fr, act, s4_y + 70, a * ease((t - T3 - 0.25) / 0.6))
            cy = s4_y + 70 + act_h + 80 + 110
            place(fr, cta, cy, ease((t - T3 - 1.6) / 0.6))
            place(fr, cta2, cy + 64, ease((t - T3 - 1.9) / 0.6))
        rgb = fr.convert("RGB")
        ff.stdin.write(rgb.tobytes())
        if abs(t - (T1 - 1.2)) < 1 / FPS / 2:
            rgb.save(os.path.join(out_dir, "covers", f"day{day:02d}_cover.jpg"), quality=90)
    ff.stdin.close(); ff.wait(); os.remove(wav)
    return day, out, round(DUR, 1)

if __name__ == "__main__":
    out_dir = os.path.abspath(sys.argv[1]); os.makedirs(os.path.join(out_dir, "covers"), exist_ok=True)
    days = [int(x) for x in sys.argv[2:]] or list(range(1, 31))
    with Pool(min(4, os.cpu_count() or 1)) as pool:
        for day, out, dur in pool.imap_unordered(render, [(d - 1, out_dir) for d in days]):
            print(f"Day {day:02d}  {dur:5.1f}s  {os.path.basename(out)}", flush=True)
