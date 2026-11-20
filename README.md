# Afghan Allies X Bot

Posts 2–3 unique, human-sounding advocacy tweets a day at random times (8am–11pm US Eastern).
Gemini writes the tweets and GitHub Actions posts them, so your PC and phone can stay off. Free.

## How it posts like a person, not a bot
- Random gaps of 2.5–6.5 hours, never on a fixed clock. The first post of the day lands between 8:00 and 10:30.
- Usually 2–3 posts a day, never more than 3. Some days it stops early.
- Different topic, format, and length each time, and drafts that look too much like recent tweets get rejected.
- No @mentions and no links (automated mentions are the #1 reason X flags bots), with 0–2 hashtags.
- Labeled as automated on X (step 6 below), which X's rules require for bots.

## Files you'll edit
| File | What it is |
|---|---|
| `prompts/master_prompt.md` | The voice and rules Gemini follows |
| `prompts/facts.md` | The only facts and numbers the bot may use. **Keep it current.** |
| `prompts/topics.json` | The topics and tweet styles it rotates through |
| `history.json` | Created automatically: every tweet it has written |

## Setup

### 1. GitHub account and private repo
1. Sign up at github.com (free).
2. Click **New repository**, name it `allies-bot`, and choose **Private**.
3. Upload every file in this folder **except `.env`**, keeping the folder structure (`.github/workflows/post.yml` and `prompts/`).
   The easiest way is GitHub Desktop, or drag the folder onto the "uploading an existing file" page.

### 2. Add your secrets
In the repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from aistudio.google.com |
| `X_API_KEY` | X app "API Key" (Consumer Key) |
| `X_API_SECRET` | X app "API Key Secret" |
| `X_ACCESS_TOKEN` | X app "Access Token" |
| `X_ACCESS_TOKEN_SECRET` | X app "Access Token Secret" |

Secrets are encrypted, and nobody can read them, not even from the repo.

### 3. X developer keys (once your account is unlocked)
1. Go to developer.x.com and sign up for the **Free** tier.
   It asks what you'll use the API for. Answer honestly, for example: "Posting my own advocacy tweets about Afghan allies, generated with AI and published automatically to my own account. No mentions, replies, or likes."
2. In your app's **User authentication settings**, set permissions to **Read and write**.
3. **After** changing the permissions, go to **Keys and tokens** and generate the **Access Token and Secret**.
   Tokens created before the change are read-only and will fail with a 403 error.

### 4. Test in dry-run mode (works now, even while X is locked)
Go to **Actions → Afghan Allies bot → Run workflow**, tick **post_now**, and run it.
Open the run log to see the tweet it wrote. Nothing gets posted yet.

### 5. Turn on real posting
Go to **Settings → Secrets and variables → Actions → Variables tab → New variable** and add:
`X_POSTING_ENABLED` = `true`

To pause the bot at any time, change it to `false`.

### 6. Label your account as automated (important)
On X, go to **Settings → Your account → Account information → Automation**, and set your own account as the managing account.
Your profile then shows an "Automated" label, which protects you from being suspended as a spam bot.

## Good habits
- It's capped at 3 posts a day (`MAX_POSTS_PER_DAY` in `bot.py`). After a lock, X watches accounts more closely. Raise it to 4 only after a few calm weeks.
- Log in and post or reply manually now and then. Purely automated accounts look less real.
- Read `history.json` every week or so, and update `facts.md` when the news changes.

## Cost
Gemini's free tier and the X API free tier cover a few posts a day. Check developer.x.com, because X changes its limits often.
A private repo gets 2,000 free GitHub Actions minutes a month, and this bot uses about 1,000–1,400.
