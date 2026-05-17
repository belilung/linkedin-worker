# LinkedIn Worker — install & run

**English** · [Русский](INSTALL.ru.md)

Tool for automating LinkedIn outreach: scrapes search results, generates personalized messages and comments via Claude AI, sends DMs and comments through the browser.

Runs on **Windows**, **macOS** and **Ubuntu/Linux**.

---

## What you'll need

- **Python 3.11 or newer** — [download](https://www.python.org/downloads/)
  On Windows, tick **"Add Python to PATH"** during install.
- **Anthropic API key** — [get one](https://console.anthropic.com/settings/keys)
  Top up at least $5. 200 messages costs roughly $0.60.

---

## Quick start

### 1. Unpack the archive

Unpack `linkedin-worker-student.zip` into any folder. Open a terminal inside it.

- **macOS:** right-click the folder in Finder → "New Terminal at Folder"
- **Windows:** in Explorer, type `cmd` into the address bar and press Enter
- **Linux:** right-click → "Open Terminal Here"

### 2. Run the installer

**macOS / Linux:**
```bash
./setup.sh
```

If it complains about permissions: `chmod +x setup.sh` first.

**Windows:**
```cmd
setup.bat
```

The script creates a virtualenv, installs dependencies, downloads Chromium, and seeds `.env` and `config.yaml` from templates.

### 3. Paste your API key

Open `.env` in any text editor and add your key:

```
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

### 4. Configure the campaign

Open `config.yaml` — every field has inline comments.

The minimum you should change:
- `campaign.context` — who you are and what you're offering (Claude uses this to score lead relevance)
- `campaign.search_url` — LinkedIn People search URL (see below)
- `voice.sample_message` — a sample message in your voice
- `connect_campaign.keywords` — keywords for post search

**How to get `search_url`:**
1. Go to linkedin.com
2. Search → People → set filters (country, industry, title)
3. Copy the URL from the address bar

### 5. Log in to LinkedIn

Activate the virtualenv and run login:

**macOS / Linux:**
```bash
source venv/bin/activate
linkedin-worker login
```

**Windows:**
```cmd
venv\Scripts\activate.bat
linkedin-worker login
```

A browser window opens. Sign in to LinkedIn manually, then press Enter in the terminal. Cookies are saved to `data/cookies/`.

**Important:** activate the venv (as above) before every session with the worker.

---

## Running

There are 3 workflows — pick the one that matches your goal.

### `run` — DM existing 1st-degree connections

Searches people by `search_url`, filters **only 1st-degree connections**, scrapes profiles, generates a personalized message, and sends it.

```bash
linkedin-worker run --dry-run        # Preview — generates messages but doesn't send
linkedin-worker run                  # Full run — sends DMs
linkedin-worker run --no-headless    # Show the browser window (for debugging)
```

### `connect` — comment on other people's posts + send Connect

Searches **posts** by keywords, generates a comment via Claude, posts it, and optionally sends a Connect request to the author.

Good fit for **cold outreach** to people you're not connected to yet.

```bash
linkedin-worker connect --dry-run    # Preview
linkedin-worker connect              # Posts comments + sends Connect
linkedin-worker connect --no-connect # Comments only, no Connect
```

### `dm-recent` — DM people who accepted your Connect

Finds people who accepted your Connect in the last N days, scrapes their profiles, generates a message, and sends it.

```bash
linkedin-worker dm-recent --dry-run  # Preview
linkedin-worker dm-recent            # Full run
linkedin-worker dm-recent --days 7   # Last 7 days (default is 14)
```

### Typical 3-step flow

1. `linkedin-worker connect` — comments + Connect requests to cold leads
2. Wait a few days while people accept
3. `linkedin-worker dm-recent` — DM those who accepted

### Utilities

```bash
linkedin-worker status               # Send statistics
linkedin-worker export               # Export all activity to CSV
```

---

## Options

| Flag | What it does | Where it works |
|---|---|---|
| `--dry-run` | Generate but don't send | run, connect, dm-recent |
| `--no-headless` | Show the browser window | run, connect, dm-recent |
| `--batch-size N` | Leads per run | run, connect |
| `--config path.yaml` | Use a different config | all |
| `--max-pages N` | Search pages to crawl | run |
| `--no-connect` | Comment only, skip Connect | connect |
| `--keywords "text"` | Override keywords | connect |
| `--days N` | Connect freshness (default 14) | dm-recent |

---

## Headless vs visible browser

By default the browser is **visible** (`headless: false`). It's safer — LinkedIn can detect headless browsers and may ban you.

- `headless: false` — window visible, safer, **recommended**
- `headless: true` — window hidden, faster, higher detection risk

Change it in `config.yaml` (`session.headless`) or via the `--no-headless` / `--headless` flag.

**Safety rules:**
- Delays between actions no less than 3–8 seconds (`session.min_delay_seconds`)
- No more than 20–40 Connect requests per day
- No more than 50–100 comments per day
- Always start with `--dry-run`

---

## Troubleshooting

### `ANTHROPIC_API_KEY not set`
Check that `.env` is in the project root and contains the key.

### `Playwright browser not found`
```bash
playwright install chromium
```

### Linux: missing system libraries
```bash
sudo playwright install-deps chromium
```

### `Not logged in`
Cookies expired. Re-login:
```bash
linkedin-worker login
```

### LinkedIn asks for email / phone verification on login
Confirm manually in the browser, then press Enter in the terminal — `linkedin-worker login` will wait.

### Account got blocked / "temporarily restricted"
Dial activity down:
- Raise delays: `min_delay_seconds: 8`, `max_delay_seconds: 15`
- Lower `batch_size` to 5
- Run with `headless: false`
- No more than 20 Connects / 50 comments per day

---

## Cost

- **200 messages ≈ $0.60** via the Anthropic API
- Claude Sonnet: input ~$3 / 1M tokens, output ~$15 / 1M tokens

---

## Project layout

```
.
├── src/linkedin_worker/    # worker code
├── tests/                  # tests (optional for running)
├── config.example.yaml     # config template
├── .env.example            # .env template
├── setup.sh / setup.bat    # installers
├── import_cookies.py       # import cookies from a browser extension (optional)
└── data/                   # cookies, DB, screenshots (created on first run)
```

`data/` is gitignored — it holds your cookies and history DB. Don't share that folder with anyone.
