"""Generate CAPTIONS.md — a ready-to-paste TikTok caption for each day."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from philosophers import DAYS

BASE = "#philosophy #philosophytok #motivation #selfimprovement #wisdom #mindset #fyp"
EXTRA = {"Stoic": "#stoic", "Existential": "#existentialism", "Taoism": "#taoism",
         "Taoist": "#taoism", "Poet": "#poetry #rumi", "Logician": "#logic", "Rationalist": "#logic"}
out = ["# 30 Days of Philosophers — Posting Calendar", "",
       "Post one per day. Copy the caption block into TikTok. Use the matching cover from `covers/`.", "",
       "**Best practice:** post at the same time daily · pin Day 1 · reply to comments with the next day's philosopher.", ""]
for i, p in enumerate(DAYS, 1):
    tags = BASE + "".join(" " + v for k, v in EXTRA.items() if k in p["tag"])
    nxt = f"Tomorrow: {DAYS[i]['name']}." if i < 30 else "That's all 30. Which one changed you most?"
    out += [f"## Day {i:02d} — {p['name']}", "",
            f"**Hook:** {p['hook']}  ", f"**Quote:** “{p['quote']}” — *{p['source']}*", "",
            "```", f"Day {i}/30: {p['name']} — {p['hook'][0].lower() + p['hook'][1:]} 🧠",
            "", f"Try this today: {p['action']}", "", f"{nxt} Follow so you don't miss it.", "", tags, "```", ""]
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "CAPTIONS.md"), "w").write("\n".join(out))
print("CAPTIONS.md written")
