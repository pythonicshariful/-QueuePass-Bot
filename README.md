# QueuePass Bot

A multi-session real-browser Queue-it queue monitor and pass-link capture tool built with Python, Playwright (Chromium), and Flask.

---

## ⚠️ Honest Limits & Disclaimers (Read First)

1. **Passing the Queue Is a Lottery — Never a Guarantee**: When a Queue-it sale starts, every session in the pre-queue waiting room is assigned a **random queue position**. Running more isolated browser sessions increases your statistical odds of drawing a low queue number, but **it never guarantees a pass**.
2. **Inventory Can Sell Out**: Even with a good queue position, high-demand football matches have limited ticket allocations that can sell out before your best session reaches the front.
3. **Tokens Are 100% Real, Never Forged**: Queue-it tokens (`queueittoken=e_<event>~ts_<unix>~ce_true~q_<uuid>~rt_queue~h_<64-hex-hmac>`) are cryptographically signed with HMAC-SHA256 by Queue-it's servers. Forging tokens is impossible and is **never** attempted. QueuePass Bot only captures genuine tokens emitted when a real browser session legitimately passes the queue.
4. **Short Token Lifetime (~10–30 Minutes)**: Admitted sessions receive a strict entry window (typically 10 minutes to enter the shop, with token validity lasting ~10–30 minutes depending on the club). **Open the captured pass link in your browser immediately** when notified.
5. **Manual Checkout Only**: QueuePass Bot **never** logs into your account, selects seats, or purchases tickets, and **never** attempts to solve or bypass manual CAPTCHAs. Once a pass link is captured, you open it in your own browser and complete login, seat selection, personalisation, and payment manually.
6. **Proxies Cost Extra and Are Not Included**: Running many parallel sessions effectively requires your own residential or ISP proxies. Proxies are not bundled with this software.
7. **Live Sale Verification**: Automated and local simulated tests verify the browser engine, parser, storage, and Discord notifications, but **a live pass is not proven until an actual match-day sale run**.

---

## Architecture

```text
queue-pass-bot/
  START_QUEUE_BOT.bat    — One-click Windows launcher (auto-installs & opens Dashboard UI)
  run.py                 — Entry point: no args = start dashboard; CLI args = headless/headed run
  app.py                 — Small launcher
  config.json            — Saved settings
  proxies.txt            — Optional proxy list file (auto-synced with Dashboard UI)
  requirements.txt       — Python dependencies
  README.md              — Documentation
  queuebot/
    config.py            — Load/save config.json with defaults
    linkparse.py         — Parse waiting link (c, e, t, cid) + validate Queue-it host
    proxies.py           — Parse + rotate proxies (4 formats supported)
    engine.py            — Playwright multi-session Chromium engine
    queue_monitor.py     — Queue page text parser (Dutch + English) + pass detection
    discord_notify.py    — CiroAIO-styled Discord webhook embed builder + sender
    storage.py           — Write data/last_pass.txt and data/results.json run history
    dashboard.py         — Easy Flask UI + live status/proxy/link validation API
  tests/                 — Full pytest suite + simulated local end-to-end test
  data/                  — Captured pass links and run history output
```

---

## 🚀 Easy 1-Click Start (No Technical Knowledge Required)

On Windows, simply **double-click `START_QUEUE_BOT.bat`**:
1. On first run, it automatically creates a `.venv` environment, installs all Python dependencies, and downloads the Chromium browser.
2. It automatically opens the **Easy Dashboard (`http://127.0.0.1:5055`)** in your web browser.
3. Everything — **waiting links, proxies (paste or load `.txt` file), proxy checking, session count, headless/visible windows, Discord webhook testing, and starting/stopping** — can be controlled directly inside the web dashboard without touching the terminal.

---

## Manual Setup Instructions (Optional)

### 1. Create and Activate a Virtual Environment

**Windows (PowerShell):**
```powershell
cd queue-pass-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
cd queue-pass-bot
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright Chromium Browser

```bash
playwright install chromium
```

---

## Dashboard Usage (Step by Step)

1. Start the web dashboard (runs on `http://127.0.0.1:5055` by default):
   ```bash
   python run.py
   ```
2. Open **`http://127.0.0.1:5055`** in your browser.
3. Configure your run (~15 minutes before the ticket sale starts):
   - **Queue-it Waiting Link**: Paste the waiting room URL (e.g. `https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026&t=https%3A%2F%2Fticketshop.psv.nl%2F&cid=nl-NL`).
   - **Platform Name**: e.g. `PSV` or `Liverpool`.
   - **Task Label**: e.g. `PSV Ticket Drop`.
   - **Number of Sessions**: How many isolated browser contexts to open in parallel (e.g. `5`, `10`, `25`).
   - **Proxies**: Paste one proxy per line in the textarea (passwords are automatically masked in the live status table).
   - **Discord Webhook URL**: Paste your Discord webhook URL (`https://discord.com/api/webhooks/<ID>/<TOKEN>`) to receive instant CiroAIO-style `Task Update` embeds on pass.
   - **Headless Browser Mode**: Keep checked for lower resource usage, or uncheck to watch browser windows visually.
   - **Allow Sessions Without Proxy**: If checked, allows running without proxies when the proxy list is empty. If unchecked, the bot refuses to start unless proxies are provided.
   - **Poll Interval / Hold Winner / Stop Others**:
     - `Poll Interval (sec)`: How often to inspect each session's queue status (default `5`s).
     - `Hold Winner (min)`: Keep the winning browser context open for `10` minutes after passing so session cookies stay warm.
     - `Stop Others (min)`: Keep backup sessions running for `2` minutes after the first pass before closing them.
4. Click **Save Settings** or press **▶ Start Sessions** directly.
5. Watch the **Live Sessions Status** table auto-refresh every 2 seconds. The session with the lowest number of people ahead is highlighted with a `★`.
6. The instant any session passes the queue:
   - A green **QUEUE PASSED!** banner appears at the top of the dashboard with a **Copy Pass Link** button.
   - The full signed link is saved to `data/last_pass.txt` and appended to `data/results.json`.
   - The link is printed to the terminal and sent to your Discord webhook.
7. Click **Copy Pass Link**, open it in your own personal browser, select tickets, log in, and check out manually.

---

## CLI Usage Examples

Run directly from the command line (any option not passed on the CLI falls back to `config.json`):

```bash
# Run 10 headless sessions for a PSV waiting link
python run.py --link "https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026&t=https%3A%2F%2Fticketshop.psv.nl%2F&cid=nl-NL" --sessions 10

# Run 5 visible (headed) browser sessions
python run.py --link "https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026&t=https%3A%2F%2Fticketshop.psv.nl%2F&cid=nl-NL" --sessions 5 --headed

# Specify custom platform and label
python run.py --link "https://liverpoolfc.queue-it.net/?c=liverpoolfc&e=allticketssafetynet&t=https%3A%2F%2Fticketing.liverpoolfc.com%2F&cid=en-GB" --sessions 8 --platform "Liverpool" --label "LFC SafetyNet"
```

---

## Supported Proxy Formats

Add proxies either in the Dashboard textarea (`config.json`) or in `proxies.txt` (one per line, lines starting with `#` are ignored). All 4 common formats are supported:

```text
# 1. Host and Port (IP-authenticated or open proxy)
198.51.100.10:8080

# 2. Host:Port:Username:Password
198.51.100.11:8080:proxyuser:EXAMPLE_PASSWORD_PLACEHOLDER

# 3. Username:Password@Host:Port
proxyuser:EXAMPLE_PASSWORD_PLACEHOLDER@198.51.100.12:8080

# 4. Full URL with scheme (http / https / socks5)
http://proxyuser:EXAMPLE_PASSWORD_PLACEHOLDER@198.51.100.13:8080
```

Sessions rotate over the proxy list in order:
- Session #1 → Proxy #1
- Session #2 → Proxy #2
- Wraps around if `sessions > len(proxies)`.

---

## Sale-Day Checklist

- [ ] **T-30 min**: Verify your proxies are active and low-latency (Dutch/EU residential IPs recommended for PSV).
- [ ] **T-25 min**: Test your Discord webhook URL and confirm your own personal browser is open and ready.
- [ ] **T-15 min**: Copy the official Queue-it waiting room link, paste it into the dashboard (or CLI), set session count, and click **Start Sessions**.
- [ ] **T-10 min**: Confirm all sessions show state `waiting` inside the pre-queue waiting room (Queue-it's automatic Botdeflector PoW will complete by itself).
- [ ] **T-00 (Sale Start)**: Queue-it assigns random queue numbers. Watch the **Best Session** indicator (`★`) in the dashboard table.
- [ ] **On Pass**: Click the link in Discord or the green dashboard banner **immediately** (within 1–2 minutes), add tickets to basket, log in, personalise, and complete checkout manually.

---

## Running the Test Suite

```bash
pytest -v
```

