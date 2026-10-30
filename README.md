# Isekai Autopilot — fully automated faceless YouTube channel, $0/month

Daily 60-90 second isekai anime list videos: Unsplash backgrounds, neural TTS
voiceover, burned-in captions, auto-generated thumbnail, auto-uploaded to
YouTube via GitHub Actions cron.

## Cost: $0
| Piece | Service |
|---|---|
| Images | Unsplash API free tier (50 req/hr) |
| Voice | edge-tts (free Microsoft neural voices) |
| Video assembly | FFmpeg + MoviePy |
| Scheduler | GitHub Actions (public repo = 2000 free min/month) |
| Upload | YouTube Data API v3 (free, 10k quota/day; one upload = 1600) |

## Setup (one time, ~30 minutes)

1. **Unsplash key**: https://unsplash.com/developers -> "New Application"
   -> copy the Access Key. GitHub repo -> Settings -> Secrets -> `UNSPLASH_KEY`.

2. **YouTube OAuth**:
   - Go to https://console.cloud.google.com, create a project, enable
     **YouTube Data API v3**.
   - OAuth consent screen: choose **External**, set publishing status to
     **In production** (important: "Testing" mode refresh tokens expire in 7 days).
     With an unverified production app you'll see a warning screen on first
     login — click "Continue". Only your own channel is affected.
   - Credentials -> Create OAuth Client ID -> **Desktop app** -> download JSON,
     rename to `client_secret.json`, place next to `oauth_setup.py`.
   - Run locally: `pip install google-auth-oauthlib google-api-python-client`
     then `python oauth_setup.py`. Log in with your YouTube channel's Google account.
   - Copy the 3 printed values into GitHub Secrets:
     `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.

3. **Push this repo to GitHub** (public, or you'll burn through private-repo minutes).

4. Run the workflow once manually (Actions -> daily-isekai-video -> Run workflow)
   to verify. It then fires every day at 10:00 UTC.

## How a video gets made each day
`main.py` picks the next script from `scripts.json` by date (day N -> video N,
rotating), downloads 7 Unsplash images, generates 7 voiceover segments with
edge-tts, assembles a Ken-Burns-zoom slideshow with FFmpeg-burned captions,
builds a thumbnail with Pillow, and uploads everything via the Data API
(category: Film & Animation).

## Adding more videos
Just append to `scripts.json`. Keep this format per entry:
`{ "caption": "5. Show Name", "keyword": "unsplash search term", "text": "20-35 words of original commentary" }`
Rotate titles across formats (Top 5 / Weirdest / Dark / Beginners / Hidden Gems)
so the channel does not look templated.

## Content rules (important)
- **Never use anime screenshots, clips, or OST.** That is how channels in this
  niche get copyright-struck. Scripts are original commentary/summaries — safe.
- One upload per day max. 6/day is the API ceiling; 1/day is the audience ceiling.
- Fully automated channels usually can't pass YouTube's reused-content review for
  monetization. Grow with it; if it takes off, add real editing/personality later.

## Known limits
- Unsplash demo keys: 50 requests/hour. We use 8 per video. Fine.
- If the Actions run fails mid-upload, just re-run it — the date-keyed script
  rotation means it uploads that day's video again cleanly.
