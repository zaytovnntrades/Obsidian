# 30 Days of Philosophers (TikTok series)

30 vertical 9:16 videos (1080×1920, 30 fps, about 26–35 s each), one philosopher per day.
Every video has four parts: **hook → quote (revealed word by word) → why it matters → try this today + next-day teaser**.
Each quote is traceable to the philosopher's own work, and the source is shown on screen.

| File | What |
|---|---|
| `philosophers.py` | All 30 entries: quote, source, explanation, action, hook. **Edit this to change the content.** |
| `render.py` | Renders the videos (Pillow + numpy + ffmpeg) |
| `make_captions.py` | Builds `CAPTIONS.md` |
| `CAPTIONS.md` | Ready-to-paste TikTok caption and hashtags for each day |
| `covers/` | A cover image for each video |

```bash
pip install pillow numpy          # plus ffmpeg on your PATH
python render.py out              # all 30 (about 6 min on 4 cores)
python render.py out 1 7 30       # only some days
python make_captions.py
```
