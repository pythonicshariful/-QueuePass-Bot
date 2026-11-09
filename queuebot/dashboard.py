"""Flask dashboard UI and JSON status/control API for QueuePass Bot."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template_string, request

from .config import load_config, save_config
from .discord_notify import build_pass_embed_payload, send_discord_pass_webhook
from .engine import QueuePassEngine
from .linkparse import parse_waiting_link
from .proxies import assign_proxies_for_sessions, parse_proxy, parse_proxy_list
from .storage import load_results_history, read_last_pass

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>QueuePass Bot — Easy Control Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #1e293b;
      --panel-alt: #162032;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #3b82f6;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 20px;
      line-height: 1.45;
    }
    .container {
      max-width: 1240px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 18px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 14px;
      flex-wrap: wrap;
      gap: 12px;
    }
    h1 { margin: 0; font-size: 1.55rem; }
    .subtitle { color: var(--muted); font-size: 0.92rem; margin-top: 4px; }
    .badge {
      display: inline-block;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .badge-idle { background: #334155; color: #cbd5e1; }
    .badge-running { background: rgba(59,130,246,0.2); color: #60a5fa; border: 1px solid #3b82f6; }
    .badge-passed { background: rgba(16,185,129,0.2); color: #34d399; border: 1px solid #10b981; }
    .badge-challenge { background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid #f59e0b; }
    .badge-error { background: rgba(239,68,68,0.2); color: #f87171; border: 1px solid #ef4444; }

    /* Quick How-To Strip */
    .howto-strip {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 20px;
    }
    @media (max-width: 900px) {
      .howto-strip { grid-template-columns: 1fr 1fr; }
    }
    .howto-step {
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 0.85rem;
    }
    .howto-step strong {
      display: block;
      color: #60a5fa;
      margin-bottom: 3px;
    }

    /* Big Pass Banner */
    #pass-banner {
      display: none;
      background: linear-gradient(135deg, rgba(16,185,129,0.25), rgba(5,150,105,0.15));
      border: 2px solid var(--success);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 22px;
      box-shadow: 0 8px 24px rgba(16,185,129,0.15);
    }
    #pass-banner h2 {
      margin: 0 0 8px 0;
      color: #34d399;
      font-size: 1.35rem;
    }
    .pass-link-row {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    .pass-link-box {
      flex: 1;
      background: #090d16;
      border: 1px solid var(--border);
      padding: 12px;
      border-radius: 8px;
      font-family: monospace;
      font-size: 0.95rem;
      word-break: break-all;
      color: #a7f3d0;
    }

    #error-banner {
      display: none;
      background: rgba(239,68,68,0.16);
      border: 1px solid var(--danger);
      color: #fca5a5;
      padding: 12px 16px;
      border-radius: 8px;
      margin-bottom: 16px;
      font-weight: 500;
    }
    #info-banner {
      display: none;
      background: rgba(16,185,129,0.16);
      border: 1px solid var(--success);
      color: #a7f3d0;
      padding: 12px 16px;
      border-radius: 8px;
      margin-bottom: 16px;
      font-weight: 500;
    }

    .grid {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 20px;
      margin-bottom: 22px;
    }
    @media (max-width: 960px) {
      .grid { grid-template-columns: 1fr; }
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px;
      margin-bottom: 20px;
    }
    .card h3 {
      margin: 0 0 14px 0;
      font-size: 1.05rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .form-group {
      margin-bottom: 14px;
    }
    .form-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    .form-row-4 {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }
    @media (max-width: 700px) {
      .form-row, .form-row-4 { grid-template-columns: 1fr; }
    }
    label {
      display: block;
      font-size: 0.85rem;
      color: #cbd5e1;
      font-weight: 600;
      margin-bottom: 5px;
    }
    .help-text {
      font-size: 0.78rem;
      color: var(--muted);
      margin-top: 4px;
    }
    input[type="text"], input[type="number"], textarea {
      width: 100%;
      background: #0f172a;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 9px 11px;
      border-radius: 6px;
      font-size: 0.92rem;
    }
    input[type="text"]:focus, input[type="number"]:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
    }
    textarea {
      min-height: 125px;
      font-family: monospace;
      resize: vertical;
    }
    .input-with-btn {
      display: flex;
      gap: 8px;
    }
    .input-with-btn input { flex: 1; }
    .preset-pills {
      display: flex;
      gap: 6px;
      margin-top: 6px;
      flex-wrap: wrap;
    }
    .pill-btn {
      background: #334155;
      color: #e2e8f0;
      padding: 4px 10px;
      font-size: 0.78rem;
      border-radius: 999px;
      border: none;
      cursor: pointer;
    }
    .pill-btn:hover { background: var(--accent); color: white; }

    .toggle-box {
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 10px;
    }
    .toggle-box label {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text);
      cursor: pointer;
      font-size: 0.92rem;
      margin: 0;
    }
    .toggle-box input[type="checkbox"] {
      width: 18px;
      height: 18px;
      cursor: pointer;
    }

    .btn-row {
      display: flex;
      gap: 12px;
      margin-top: 16px;
      flex-wrap: wrap;
    }
    button {
      padding: 10px 18px;
      border-radius: 6px;
      border: none;
      font-weight: 600;
      cursor: pointer;
      font-size: 0.92rem;
      transition: opacity 0.15s;
    }
    button:hover { opacity: 0.92; }
    .btn-start { background: var(--success); color: #052e16; font-size: 1rem; padding: 12px 24px; }
    .btn-stop { background: var(--danger); color: white; font-size: 1rem; padding: 12px 20px; }
    .btn-save { background: var(--accent); color: white; }
    .btn-secondary { background: #334155; color: #f8fafc; padding: 8px 14px; font-size: 0.84rem; }
    .btn-copy { background: var(--success); color: #052e16; }

    .status-box {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 11px;
      font-size: 0.83rem;
      margin-top: 8px;
      display: none;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }
    th, td {
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
    }
    th {
      color: var(--muted);
      font-weight: 600;
      background: rgba(15,23,42,0.5);
    }
    .progress-bar-bg {
      width: 90px;
      background: #0f172a;
      height: 10px;
      border-radius: 999px;
      overflow: hidden;
      display: inline-block;
      vertical-align: middle;
      margin-right: 6px;
    }
    .progress-bar-fill {
      height: 100%;
      background: var(--accent);
    }
    .best-row {
      background: rgba(16, 185, 129, 0.08);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>QueuePass Bot — Easy Dashboard</h1>
        <div class="subtitle">Everything is controlled right here in your browser &bull; No command-line needed</div>
      </div>
      <div>
        <a href="/api/download-zip" style="color:#60a5fa;font-size:0.85rem;margin-right:12px;text-decoration:none;border:1px solid #334155;padding:6px 12px;border-radius:6px;">&#128230; Download Delivery ZIP</a>
        <span id="engine-state-badge" class="badge badge-idle">IDLE / READY</span>
      </div>
    </header>

    <div class="howto-strip">
      <div class="howto-step">
        <strong>Step 1: Paste Queue Link</strong>
        Paste the Queue-it waiting room URL ~15 mins before the ticket sale starts.
      </div>
      <div class="howto-step">
        <strong>Step 2: Set Sessions &amp; Proxies</strong>
        Choose how many browsers to open. Paste proxies or run without proxies.
      </div>
      <div class="howto-step">
        <strong>Step 3: Click "Start Sessions"</strong>
        All sessions enter the waiting room and automatically monitor your place in line.
      </div>
      <div class="howto-step">
        <strong>Step 4: Open Pass Link &amp; Buy</strong>
        When a session passes, copy the green Pass Link, open it in your browser, and check out manually!
      </div>
    </div>

    <div id="pass-banner">
      <h2>&#127881; QUEUE PASSED! Open this Direct Pass Link in your browser right now:</h2>
      <div class="pass-link-row">
        <div id="pass-link-text" class="pass-link-box"></div>
        <button type="button" class="btn-copy" onclick="copyPassLink()">&#128203; Copy Pass Link</button>
        <a id="pass-link-anchor" href="#" target="_blank" rel="noopener noreferrer" style="color:#34d399;font-weight:700;text-decoration:none;padding:10px 14px;border:1px solid #10b981;border-radius:6px;">Open in New Tab &rarr;</a>
      </div>
    </div>

    <div id="error-banner"></div>
    <div id="info-banner"></div>

    <form id="config-form" onsubmit="event.preventDefault(); saveSettings(true);">
      <div class="grid">
        <!-- LEFT COLUMN: Step 1 & Step 3 -->
        <div class="card" style="margin-bottom:0;">
          <h3>
            <span>1. Sale Link &amp; Session Settings</span>
            <button type="button" class="btn-secondary" onclick="checkWaitingLink()">Check Link</button>
          </h3>

          <div class="form-group">
            <label for="waiting_link">Queue-it Waiting Room Link</label>
            <input type="text" id="waiting_link" name="waiting_link" value="{{ config.waiting_link }}" placeholder="https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026&t=https%3A%2F%2Fticketshop.psv.nl%2F&cid=nl-NL" />
            <div class="help-text">Paste the full Queue-it link from the ticket shop here.</div>
            <div id="link-check-box" class="status-box"></div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label for="platform">Club / Platform</label>
              <input type="text" id="platform" name="platform" value="{{ config.platform }}" />
              <div class="preset-pills">
                <button type="button" class="pill-btn" onclick="setPreset('PSV', 'PSV Ticket Drop')">PSV</button>
                <button type="button" class="pill-btn" onclick="setPreset('Liverpool', 'LFC Ticket Sale')">Liverpool</button>
              </div>
            </div>
            <div class="form-group">
              <label for="task_label">Task Name / Label</label>
              <input type="text" id="task_label" name="task_label" value="{{ config.task_label }}" />
              <div class="help-text">Shown in Discord &amp; history</div>
            </div>
            <div class="form-group">
              <label for="sessions">Number of Sessions</label>
              <input type="number" id="sessions" name="sessions" min="1" max="100" value="{{ config.sessions }}" />
              <div class="help-text">How many queue spots to open</div>
            </div>
          </div>

          <div class="toggle-box">
            <label>
              <input type="checkbox" id="headless" name="headless" {% if config.headless %}checked{% endif %} />
              <span><strong>Run in Background (Headless Mode)</strong> — Uncheck if you want to see the browser windows on your screen.</span>
            </label>
          </div>

          <div class="form-row-4">
            <div class="form-group">
              <label for="poll_interval_sec">Check Every (sec)</label>
              <input type="number" id="poll_interval_sec" name="poll_interval_sec" step="0.5" min="0.5" value="{{ config.poll_interval_sec }}" />
            </div>
            <div class="form-group">
              <label for="hold_minutes_after_pass">Hold Winner (min)</label>
              <input type="number" id="hold_minutes_after_pass" name="hold_minutes_after_pass" step="0.5" min="0" value="{{ config.hold_minutes_after_pass }}" />
            </div>
            <div class="form-group">
              <label for="stop_others_minutes_after_pass">Keep Backups (min)</label>
              <input type="number" id="stop_others_minutes_after_pass" name="stop_others_minutes_after_pass" step="0.5" min="0" value="{{ config.stop_others_minutes_after_pass }}" />
            </div>
            <div class="form-group">
              <label for="dashboard_port">UI Port</label>
              <input type="number" id="dashboard_port" name="dashboard_port" min="1024" max="65535" value="{{ config.dashboard_port }}" />
            </div>
          </div>

          <div class="btn-row">
            <button type="button" class="btn-start" onclick="startEngine()">&#9654; Start Sessions Now</button>
            <button type="button" class="btn-stop" onclick="stopEngine()">&#9632; Stop All</button>
            <button type="submit" class="btn-save">&#128190; Save All Settings</button>
          </div>
        </div>

        <!-- RIGHT COLUMN: Step 2 Proxies & Discord -->
        <div class="card" style="margin-bottom:0;">
          <h3>
            <span>2. Proxies &amp; Discord Notifications</span>
            <div style="display:flex;gap:6px;">
              <input type="file" id="proxy-file-input" accept=".txt" style="display:none;" onchange="loadProxyFile(event)" />
              <button type="button" class="btn-secondary" onclick="document.getElementById('proxy-file-input').click()">&#128194; Load .txt File</button>
              <button type="button" class="btn-secondary" onclick="validateProxiesUI()">&#10004; Check Proxies</button>
            </div>
          </h3>

          <div class="toggle-box">
            <label>
              <input type="checkbox" id="allow_no_proxy" name="allow_no_proxy" {% if config.allow_no_proxy %}checked{% endif %} />
              <span><strong>Allow running without proxies</strong> (use my own internet if proxy list is empty)</span>
            </label>
          </div>

          <div class="form-group">
            <label for="proxies">
              Proxy List (One per line — <span id="proxy-count-label">0 proxies</span>)
              <button type="button" onclick="clearProxies()" style="float:right;background:none;border:none;color:#f87171;font-size:0.78rem;padding:0;cursor:pointer;">Clear List</button>
            </label>
            <textarea id="proxies" name="proxies" oninput="updateProxyCount()" placeholder="Paste proxies here (one per line). Accepted formats:&#10;host:port&#10;host:port:username:password&#10;username:password@host:port&#10;http://username:password@host:port">{{ proxies_text }}</textarea>
            <div class="help-text">Session #1 uses Proxy #1, Session #2 uses Proxy #2, wrapping around automatically. Saved automatically when you click Save or Start.</div>
            <div id="proxy-check-box" class="status-box"></div>
          </div>

          <div class="form-group">
            <label for="discord_webhook_url">Discord Webhook URL (Optional — Sends instant pass link to your Discord)</label>
            <div class="input-with-btn">
              <input type="text" id="discord_webhook_url" name="discord_webhook_url" value="{{ config.discord_webhook_url }}" placeholder="https://discord.com/api/webhooks/..." />
              <button type="button" class="btn-secondary" onclick="testDiscordWebhook()">Test Discord</button>
            </div>
            <div id="webhook-check-box" class="status-box"></div>
          </div>
        </div>
      </div>
    </form>

    <!-- LIVE SESSIONS TABLE -->
    <div class="card">
      <h3>
        <span>3. Live Queue Sessions Status</span>
        <span id="best-summary" style="font-size:0.88rem;color:#34d399;font-weight:600;"></span>
      </h3>
      <table>
        <thead>
          <tr>
            <th>Session #</th>
            <th>Proxy (Password Masked)</th>
            <th>State</th>
            <th>Queue Number</th>
            <th>People Ahead</th>
            <th>Wait Estimate</th>
            <th>Progress</th>
          </tr>
        </thead>
        <tbody id="sessions-tbody">
          <tr><td colspan="7" style="color:var(--muted);text-align:center;">No active sessions running. Paste your Queue-it link above and click <strong>Start Sessions Now</strong>.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- CAPTURED PASS LINKS HISTORY -->
    <div class="card">
      <h3>
        <span>4. Captured Pass Links History</span>
        <span style="font-size:0.82rem;color:var(--muted);font-weight:normal;">Saved in <code>data/last_pass.txt</code> &amp; <code>data/results.json</code></span>
      </h3>
      <table>
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Platform / Label</th>
            <th>Winning Session</th>
            <th>Queue #</th>
            <th>Direct Pass Link</th>
          </tr>
        </thead>
        <tbody id="history-tbody">
          <tr><td colspan="5" style="color:var(--muted);text-align:center;">No pass links captured yet.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    function updateProxyCount() {
      const raw = document.getElementById('proxies').value || '';
      const count = raw.split('\\n').map(s => s.trim()).filter(s => s && !s.startsWith('#')).length;
      document.getElementById('proxy-count-label').textContent = count + (count === 1 ? ' proxy' : ' proxies');
    }

    function setPreset(platform, label) {
      document.getElementById('platform').value = platform;
      document.getElementById('task_label').value = label;
    }

    function clearProxies() {
      document.getElementById('proxies').value = '';
      updateProxyCount();
    }

    function loadProxyFile(event) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = function(e) {
        document.getElementById('proxies').value = e.target.result || '';
        updateProxyCount();
        validateProxiesUI();
      };
      reader.readAsText(file);
    }

    function collectFormConfig() {
      const proxiesRaw = document.getElementById('proxies').value;
      const proxiesList = proxiesRaw.split('\\n').map(s => s.trim()).filter(s => s && !s.startsWith('#'));
      return {
        waiting_link: document.getElementById('waiting_link').value.trim(),
        platform: document.getElementById('platform').value.trim() || 'PSV',
        task_label: document.getElementById('task_label').value.trim() || 'Ticket Drop',
        sessions: parseInt(document.getElementById('sessions').value, 10) || 5,
        poll_interval_sec: parseFloat(document.getElementById('poll_interval_sec').value) || 5,
        hold_minutes_after_pass: parseFloat(document.getElementById('hold_minutes_after_pass').value) || 10,
        stop_others_minutes_after_pass: parseFloat(document.getElementById('stop_others_minutes_after_pass').value) || 2,
        dashboard_port: parseInt(document.getElementById('dashboard_port').value, 10) || 5055,
        headless: document.getElementById('headless').checked,
        allow_no_proxy: document.getElementById('allow_no_proxy').checked,
        proxies: proxiesList,
        discord_webhook_url: document.getElementById('discord_webhook_url').value.trim()
      };
    }

    function showError(msg) {
      const el = document.getElementById('error-banner');
      if (msg) {
        el.textContent = msg;
        el.style.display = 'block';
      } else {
        el.style.display = 'none';
      }
    }

    function showInfo(msg) {
      const el = document.getElementById('info-banner');
      if (msg) {
        el.textContent = msg;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 4000);
      } else {
        el.style.display = 'none';
      }
    }

    async function saveSettings(showMessage) {
      showError('');
      const payload = collectFormConfig();
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || 'Failed to save configuration.');
      } else if (showMessage) {
        showInfo('Settings and proxies saved to config.json and proxies.txt!');
      }
    }

    async function checkWaitingLink() {
      const box = document.getElementById('link-check-box');
      const link = document.getElementById('waiting_link').value.trim();
      const res = await fetch('/api/validate-link', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ waiting_link: link })
      });
      const data = await res.json();
      box.style.display = 'block';
      if (res.ok && data.ok) {
        box.style.color = '#34d399';
        box.textContent = `Valid Queue-it Link! Customer: ${data.c} | Event: ${data.e} | Target Shop: ${data.t || '(default)'} | Locale: ${data.cid}`;
      } else {
        box.style.color = '#f87171';
        box.textContent = data.error || 'Invalid Queue-it waiting link.';
      }
    }

    async function validateProxiesUI() {
      const box = document.getElementById('proxy-check-box');
      const cfg = collectFormConfig();
      const res = await fetch('/api/validate-proxies', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          proxies: cfg.proxies,
          sessions: cfg.sessions,
          allow_no_proxy: cfg.allow_no_proxy
        })
      });
      const data = await res.json();
      box.style.display = 'block';
      if (res.ok && data.ok) {
        box.style.color = '#34d399';
        box.innerHTML = `<strong>${data.message}</strong><br/>` + (data.preview || []).slice(0, 6).join(' &bull; ');
      } else {
        box.style.color = '#f87171';
        box.textContent = data.error || 'Proxy validation failed.';
      }
    }

    async function testDiscordWebhook() {
      const box = document.getElementById('webhook-check-box');
      const url = document.getElementById('discord_webhook_url').value.trim();
      box.style.display = 'block';
      box.style.color = '#94a3b8';
      box.textContent = 'Sending test notification to Discord...';
      const res = await fetch('/api/test-webhook', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          discord_webhook_url: url,
          platform: document.getElementById('platform').value.trim() || 'PSV',
          task_label: document.getElementById('task_label').value.trim() || 'Test Alert'
        })
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        box.style.color = '#34d399';
        box.textContent = 'Test notification sent! Check your Discord channel.';
      } else {
        box.style.color = '#f87171';
        box.textContent = data.error || 'Could not send Discord webhook.';
      }
    }

    async function startEngine() {
      showError('');
      const payload = collectFormConfig();
      const res = await fetch('/api/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || 'Failed to start engine.');
      } else {
        showInfo('Sessions launched! Monitoring Queue-it waiting room...');
        refreshStatus();
      }
    }

    async function stopEngine() {
      await fetch('/api/stop', { method: 'POST' });
      showInfo('Stopping all browser sessions...');
      refreshStatus();
    }

    function copyPassLink() {
      const txt = document.getElementById('pass-link-text').textContent;
      if (txt && navigator.clipboard) {
        navigator.clipboard.writeText(txt);
        showInfo('Pass link copied to clipboard! Paste it into your personal browser now.');
      }
    }

    function copyText(txt) {
      if (txt && navigator.clipboard) {
        navigator.clipboard.writeText(txt);
        showInfo('Copied link to clipboard!');
      }
    }

    function badgeForState(state) {
      if (state === 'passed') return '<span class="badge badge-passed">passed</span>';
      if (state === 'in-queue') return '<span class="badge badge-running">in-queue</span>';
      if (state === 'challenge') return '<span class="badge badge-challenge">challenge</span>';
      if (state === 'error') return '<span class="badge badge-error">error</span>';
      return '<span class="badge badge-idle">' + (state || 'waiting') + '</span>';
    }

    async function refreshStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const badge = document.getElementById('engine-state-badge');
        if (data.pass_link && data.running) {
          badge.className = 'badge badge-passed';
          badge.textContent = 'PASSED (HOLDING SESSION)';
        } else if (data.running) {
          badge.className = 'badge badge-running';
          badge.textContent = 'RUNNING (' + (data.elapsed_formatted || '0s') + ')';
        } else if (data.pass_link) {
          badge.className = 'badge badge-passed';
          badge.textContent = 'PASSED / READY';
        } else {
          badge.className = 'badge badge-idle';
          badge.textContent = 'IDLE / READY';
        }

        if (data.last_error) {
          showError(data.last_error);
        }

        const banner = document.getElementById('pass-banner');
        if (data.pass_link) {
          banner.style.display = 'block';
          document.getElementById('pass-link-text').textContent = data.pass_link;
          document.getElementById('pass-link-anchor').href = data.pass_link;
        } else {
          banner.style.display = 'none';
        }

        const bestSummary = document.getElementById('best-summary');
        if (data.best_session) {
          const b = data.best_session;
          bestSummary.textContent = '★ Best Session: #' + b.session_id +
            (b.people_ahead !== null && b.people_ahead !== undefined ? ' (' + b.people_ahead.toLocaleString() + ' ahead)' : '');
        } else {
          bestSummary.textContent = '';
        }

        const tbody = document.getElementById('sessions-tbody');
        const sessions = data.sessions || [];
        if (sessions.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" style="color:var(--muted);text-align:center;">No active sessions running. Paste your Queue-it link above and click <strong>Start Sessions Now</strong>.</td></tr>';
        } else {
          const bestId = data.best_session ? data.best_session.session_id : null;
          tbody.innerHTML = sessions.map(s => {
            const isBest = (s.session_id === bestId);
            const pct = (s.progress !== null && s.progress !== undefined) ? s.progress : 0;
            const progHtml = (s.progress !== null && s.progress !== undefined)
              ? `<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:${pct}%"></div></div>${pct}%`
              : '&mdash;';
            return `<tr class="${isBest ? 'best-row' : ''}">
              <td><strong>#${s.session_id}</strong> ${isBest ? '&#9733;' : ''}</td>
              <td><code>${s.proxy || 'Direct (No Proxy)'}</code></td>
              <td>${badgeForState(s.state)}</td>
              <td>${s.queue_number !== null && s.queue_number !== undefined ? s.queue_number : '&mdash;'}</td>
              <td>${s.people_ahead !== null && s.people_ahead !== undefined ? s.people_ahead.toLocaleString() : '&mdash;'}</td>
              <td>${s.estimated_wait || '&mdash;'}</td>
              <td>${progHtml}</td>
            </tr>`;
          }).join('');
        }

        const htbody = document.getElementById('history-tbody');
        const history = data.history || [];
        if (history.length === 0) {
          htbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;">No pass links captured yet.</td></tr>';
        } else {
          htbody.innerHTML = history.slice().reverse().slice(0, 10).map(h => {
            const qnum = (h.queue_stats && h.queue_stats.queue_number !== null && h.queue_stats.queue_number !== undefined)
              ? h.queue_stats.queue_number
              : '&mdash;';
            const safeLink = (h.link || '').replace(/'/g, "\\'");
            return `<tr>
              <td style="font-size:0.82rem;color:var(--muted);">${h.timestamp || ''}</td>
              <td><strong>${h.platform || ''}</strong> &mdash; ${h.label || ''}</td>
              <td>#${h.session || 1}</td>
              <td>${qnum}</td>
              <td>
                <button type="button" class="btn-secondary" onclick="copyText('${safeLink}')">Copy Link</button>
                <a href="${h.link || '#'}" target="_blank" rel="noopener noreferrer" style="color:#60a5fa;margin-left:8px;font-size:0.84rem;">Open &rarr;</a>
              </td>
            </tr>`;
          }).join('');
        }
      } catch (e) {
        // Ignore transient fetch errors
      }
    }

    updateProxyCount();
    setInterval(refreshStatus, 2000);
    refreshStatus();
  </script>
</body>
</html>
"""


def create_app(
    config_path: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> Flask:
    """Create and configure the Flask dashboard application."""
    flask_app = Flask(__name__)
    flask_app.config["CONFIG_PATH"] = config_path
    flask_app.config["DATA_DIR"] = data_dir
    flask_app.config["ENGINE"] = None

    @flask_app.route("/", methods=["GET"])
    def index() -> str:
        cfg = load_config(flask_app.config["CONFIG_PATH"])
        proxies_text = "\n".join(cfg.get("proxies") or [])
        return render_template_string(
            DASHBOARD_HTML,
            config=cfg,
            proxies_text=proxies_text,
        )

    @flask_app.route("/api/status", methods=["GET"])
    def api_status() -> Any:
        engine: QueuePassEngine | None = flask_app.config.get("ENGINE")
        cfg = load_config(flask_app.config["CONFIG_PATH"])
        history = load_results_history(flask_app.config["DATA_DIR"])
        if engine is not None:
            status = engine.get_status()
        else:
            status = {
                "task_id": None,
                "running": False,
                "platform": cfg.get("platform", "PSV"),
                "task_label": cfg.get("task_label", ""),
                "waiting_link": cfg.get("waiting_link", ""),
                "queue_host": "",
                "elapsed_sec": 0.0,
                "elapsed_formatted": "0s",
                "pass_link": read_last_pass(flask_app.config["DATA_DIR"]),
                "winning_session_id": None,
                "best_session": None,
                "best_ahead": None,
                "last_error": None,
                "sessions": [],
            }
        status["history_count"] = len(history)
        status["history"] = history
        return jsonify(status)

    @flask_app.route("/api/config", methods=["POST"])
    def api_save_config() -> Any:
        payload = request.get_json(silent=True) or {}
        saved = save_config(payload, flask_app.config["CONFIG_PATH"])
        return jsonify({"ok": True, "config": saved})

    @flask_app.route("/api/validate-link", methods=["POST"])
    def api_validate_link() -> Any:
        payload = request.get_json(silent=True) or {}
        link = str(payload.get("waiting_link") or "").strip()
        try:
            parsed = parse_waiting_link(link)
            return jsonify(
                {
                    "ok": True,
                    "host": parsed.host,
                    "c": parsed.c,
                    "e": parsed.e,
                    "t": parsed.t,
                    "cid": parsed.cid,
                }
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @flask_app.route("/api/validate-proxies", methods=["POST"])
    def api_validate_proxies() -> Any:
        payload = request.get_json(silent=True) or {}
        raw_proxies = payload.get("proxies") or []
        num_sessions = max(1, int(payload.get("sessions") or 5))
        allow_no_proxy = bool(payload.get("allow_no_proxy", True))

        if isinstance(raw_proxies, str):
            lines = [
                line.strip()
                for line in raw_proxies.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        else:
            lines = [
                str(line).strip()
                for line in raw_proxies
                if str(line).strip() and not str(line).strip().startswith("#")
            ]

        parsed_list = []
        for idx, line in enumerate(lines, start=1):
            try:
                parsed_list.append(parse_proxy(line))
            except ValueError as exc:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": f"Line {idx} is invalid ({line}): {exc}",
                        }
                    ),
                    400,
                )

        try:
            assigned = assign_proxies_for_sessions(
                parsed_list,
                num_sessions=num_sessions,
                allow_no_proxy=allow_no_proxy,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        preview = [
            f"Session #{i} → {p.masked if p else 'Direct (No Proxy)'}"
            for i, p in enumerate(assigned, start=1)
        ]
        msg = (
            f"All {len(parsed_list)} proxy(s) valid! Ready for {num_sessions} session(s)."
            if parsed_list
            else f"No proxies entered — {num_sessions} session(s) will use Direct connection."
        )
        return jsonify({"ok": True, "message": msg, "preview": preview})

    @flask_app.route("/api/test-webhook", methods=["POST"])
    def api_test_webhook() -> Any:
        payload = request.get_json(silent=True) or {}
        webhook_url = str(payload.get("discord_webhook_url") or "").strip()
        if not webhook_url:
            return jsonify({"ok": False, "error": "Please enter a Discord Webhook URL first."}), 400

        test_embed = build_pass_embed_payload(
            task_id="test-00000000-0000-0000-0000-000000000000",
            platform=str(payload.get("platform") or "PSV"),
            task_label=str(payload.get("task_label") or "Webhook Test"),
            queue_host="psveindhoven.queue-it.net",
            session_id=1,
            queue_number=1234,
            best_ahead=0,
            time_in_queue=42,
            pass_link="https://ticketshop.psv.nl/?queueittoken=EXAMPLE_TEST_NOTIFICATION",
        )
        ok = send_discord_pass_webhook(webhook_url, test_embed)
        if not ok:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Discord rejected the webhook or URL could not be reached.",
                    }
                ),
                400,
            )
        return jsonify({"ok": True})

    @flask_app.route("/api/start", methods=["POST"])
    def api_start() -> Any:
        engine: QueuePassEngine | None = flask_app.config.get("ENGINE")
        if engine is not None and engine.running:
            return jsonify({"ok": False, "error": "Engine is already running."}), 400

        payload = request.get_json(silent=True)
        if payload:
            cfg = save_config(payload, flask_app.config["CONFIG_PATH"])
        else:
            cfg = load_config(flask_app.config["CONFIG_PATH"])

        new_engine = QueuePassEngine(cfg, data_dir=flask_app.config["DATA_DIR"])
        try:
            new_engine.start_in_background()
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        flask_app.config["ENGINE"] = new_engine
        return jsonify({"ok": True, "status": new_engine.get_status()})

    @flask_app.route("/api/stop", methods=["POST"])
    def api_stop() -> Any:
        engine: QueuePassEngine | None = flask_app.config.get("ENGINE")
        if engine is not None:
            engine.stop()
        return jsonify({"ok": True})

    @flask_app.route("/api/download-zip", methods=["GET"])
    def api_download_zip() -> Response:
        project_root = Path(__file__).resolve().parent.parent
        exclude_dirs = {".venv", "__pycache__", ".pytest_cache"}
        exclude_data_files = {"last_pass.txt", "results.json"}

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirnames, filenames in os.walk(project_root):
                dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
                rel_dir = Path(dirpath).relative_to(project_root.parent)
                for fname in filenames:
                    if fname.endswith((".pyc", ".pyo", ".zip")):
                        continue
                    if Path(dirpath).name == "data" and fname in exclude_data_files:
                        continue
                    full_path = Path(dirpath) / fname
                    arcname = str(rel_dir / fname).replace("\\", "/")
                    zf.write(full_path, arcname=arcname)
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=queue-pass-bot.zip"
            },
        )

    return flask_app


app = create_app()
