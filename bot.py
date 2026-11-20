"""
Afghan Allies advocacy bot.

Runs every hour on GitHub Actions. Most runs just check the clock and exit.
When the randomly scheduled time arrives, it asks Gemini for a fresh tweet
and posts it to X, then picks the next random time.

Local test (no posting):   python bot.py --now --dry-run
"""

import argparse
import difflib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
HISTORY_FILE = ROOT / "history.json"
PROMPT_FILE = ROOT / "prompts" / "master_prompt.md"
FACTS_FILE = ROOT / "prompts" / "facts.md"
TOPICS_FILE = ROOT / "prompts" / "topics.json"

# ---------------- Schedule settings (human-like cadence) ----------------
TZ = ZoneInfo(os.getenv("BOT_TIMEZONE", "America/New_York"))
ACTIVE_START_HOUR = 8      # earliest local hour to post
ACTIVE_END_HOUR = 23       # no posts at or after this local hour
MIN_GAP_HOURS = 2.5        # shortest gap between two posts
MAX_GAP_HOURS = 6.5        # longest gap between two posts
MAX_POSTS_PER_DAY = 3      # hard cap (raise to 4 after a few calm weeks)
QUIET_REST_CHANCE = 0.10   # sometimes stop early for the day, like a real person
EARLY_WINDOW_MIN = 15      # if the post is due within 15 min, wait for it in this run

MODELS = [m for m in [os.getenv("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash"] if m]


# ---------------- Small helpers ----------------
def load_env_file():
    """Load .env for local runs (GitHub Actions uses repository secrets instead)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def now_utc():
    return datetime.now(timezone.utc)


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


# ---------------- Scheduling ----------------
def next_morning(after_local):
    day = after_local.date() + timedelta(days=1)
    start = datetime(day.year, day.month, day.day, ACTIVE_START_HOUR, tzinfo=TZ)
    return start + timedelta(minutes=random.randint(0, 150))  # 8:00 - 10:30


def schedule_next(after_utc, posts_today):
    local = after_utc.astimezone(TZ)
    if posts_today >= MAX_POSTS_PER_DAY or (posts_today >= 1 and random.random() < QUIET_REST_CHANCE):
        nxt = next_morning(local)
    else:
        nxt = local + timedelta(minutes=random.randint(int(MIN_GAP_HOURS * 60), int(MAX_GAP_HOURS * 60)))
        if nxt.hour >= ACTIVE_END_HOUR or nxt.date() != local.date():
            nxt = next_morning(local)
        elif nxt.hour < ACTIVE_START_HOUR:
            nxt = nxt.replace(hour=ACTIVE_START_HOUR) + timedelta(minutes=random.randint(0, 150))
    return nxt.astimezone(timezone.utc)


def posts_on_local_day(history, when_utc):
    day = when_utc.astimezone(TZ).date()
    return sum(
        1 for h in history
        if h.get("posted") and datetime.fromisoformat(h["time"]).astimezone(TZ).date() == day
    )


# ---------------- Tweet generation ----------------
def pick_topic_and_format(history):
    cfg = read_json(TOPICS_FILE, {})
    recent_topics = [h.get("topic") for h in history[-6:]]
    recent_formats = [h.get("format") for h in history[-3:]]
    topics = [t for t in cfg["topics"] if t not in recent_topics] or cfg["topics"]
    formats = [f for f in cfg["formats"] if f["name"] not in recent_formats] or cfg["formats"]
    fmt = random.choices(formats, weights=[f["weight"] for f in formats])[0]
    return random.choice(topics), fmt


def build_prompt(topic, fmt, history):
    recent = "\n".join(f"- {h['text']}" for h in history[-25:]) or "(none yet)"
    length = random.choice(["very short (under 100 characters)", "short (100-170 characters)",
                            "medium (170-240 characters)", "medium (170-240 characters)",
                            "full (240-275 characters)"])
    return (
        f"FACTS YOU MAY USE (the only source for any number, date, or law name):\n"
        f"{strip_comments(FACTS_FILE.read_text(encoding='utf-8'))}\n\n"
        f"RECENT TWEETS FROM THIS ACCOUNT (do NOT repeat their ideas, openings, or phrasing):\n{recent}\n\n"
        f"WRITE ONE NEW TWEET NOW.\n"
        f"Topic: {topic}\n"
        f"Format: {fmt['name']} - {fmt['how']}\n"
        f"Length: {length}\n"
        f"Output only the tweet text. No quotes around it, no explanation."
    )


def call_gemini(system_prompt, user_prompt):
    key = os.environ["GEMINI_API_KEY"]
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 1.0, "topP": 0.95, "maxOutputTokens": 2048},
    }
    last_err = None
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            # Key goes in a header, never the URL, so error messages can't expose it.
            r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=60)
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except Exception as e:  # try the next model
            last_err = f"{model}: {e}"
            print(f"Gemini error ({last_err}), trying next model...")
    raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")


def clean_tweet(text):
    text = text.strip().strip('"').strip("“”").strip()
    text = re.sub(r"(?<!\w)@\w+", "", text)              # never auto-mention accounts
    text = re.sub(r"https?://\S+", "", text)              # no links
    text = text.replace("—", ", ").replace("–", "-")      # em dashes look AI-written
    tags = re.findall(r"#\w+", text)
    for extra in tags[2:]:                                # max 2 hashtags
        text = text.replace(extra, "", 1)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([,.!?])", r"\1", text)
    return text.strip()


def too_similar(text, history):
    def norm(s):
        return re.sub(r"[^a-z0-9 ]", "", s.lower())
    t = norm(text)
    opening = " ".join(t.split()[:5])
    for h in history[-60:]:
        o = norm(h["text"])
        if difflib.SequenceMatcher(None, t, o).ratio() > 0.6:
            return True
        if opening and opening == " ".join(o.split()[:5]):
            return True
    return False


def generate_tweet(history):
    system_prompt = strip_comments(PROMPT_FILE.read_text(encoding="utf-8"))
    for attempt in range(1, 5):
        topic, fmt = pick_topic_and_format(history)
        text = clean_tweet(call_gemini(system_prompt, build_prompt(topic, fmt, history)))
        problems = []
        if not text:
            problems.append("empty")
        if len(text) > 280:
            problems.append(f"too long ({len(text)})")
        if text and too_similar(text, history):
            problems.append("too similar to a recent tweet")
        if not problems:
            return text, topic, fmt["name"]
        print(f"Attempt {attempt} rejected: {', '.join(problems)}")
    raise RuntimeError("Could not generate an acceptable tweet after 4 attempts.")


# ---------------- Posting to X ----------------
def post_to_x(text):
    from requests_oauthlib import OAuth1

    auth = OAuth1(
        os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    r = requests.post("https://api.x.com/2/tweets", json={"text": text}, auth=auth, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"X API error {r.status_code}: {r.text}")
    return r.json()["data"]["id"]


# ---------------- Main ----------------
def main():
    load_env_file()
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", action="store_true", help="ignore the schedule and run immediately")
    ap.add_argument("--dry-run", action="store_true", help="generate but do not post")
    args = ap.parse_args()

    posting_enabled = os.getenv("X_POSTING_ENABLED", "false").lower() == "true" and not args.dry_run
    state = read_json(STATE_FILE, {})
    history = read_json(HISTORY_FILE, [])
    now = now_utc()

    if not args.now:
        if "next_post_at" not in state:
            state["next_post_at"] = schedule_next(now, posts_on_local_day(history, now)).isoformat()
            write_json(STATE_FILE, state)
            print(f"First run. Next post scheduled for {state['next_post_at']}")
            return
        due = datetime.fromisoformat(state["next_post_at"])
        wait = (due - now).total_seconds()
        if wait > EARLY_WINDOW_MIN * 60:
            print(f"Not yet. Next post at {due.astimezone(TZ):%a %H:%M %Z} (in {wait / 3600:.1f} h)")
            return
        if wait > 0:
            print(f"Post due in {wait / 60:.0f} min, waiting...")
            time.sleep(wait)

    text, topic, fmt = generate_tweet(history)
    print(f"\nTopic: {topic} | Format: {fmt} | {len(text)} chars\n---\n{text}\n---")

    entry = {"time": now_utc().isoformat(), "topic": topic, "format": fmt, "text": text, "posted": False}
    if posting_enabled:
        try:
            entry["tweet_id"] = post_to_x(text)
            entry["posted"] = True
            print(f"Posted: https://x.com/i/status/{entry['tweet_id']}")
        except Exception as e:
            # Retry in 1-2 hours instead of hammering the API.
            state["next_post_at"] = (now_utc() + timedelta(minutes=random.randint(60, 120))).isoformat()
            state["last_error"] = str(e)[:500]
            write_json(STATE_FILE, state)
            print(f"POST FAILED: {e}")
            sys.exit(1)
    else:
        print("Dry run: not posted (set X_POSTING_ENABLED=true to post).")

    history.append(entry)
    write_json(HISTORY_FILE, history[-200:])
    if not args.now:
        state["next_post_at"] = schedule_next(now_utc(), posts_on_local_day(history, now_utc())).isoformat()
        state.pop("last_error", None)
        write_json(STATE_FILE, state)
        print(f"Next post scheduled for {state['next_post_at']}")


if __name__ == "__main__":
    main()
