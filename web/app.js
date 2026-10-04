const output = document.getElementById('output');
const receiveBtn = document.getElementById('receiveBtn');
const prescriptId = document.getElementById('prescriptId');
const modeValue = document.getElementById('modeValue');
const modeSelect = document.getElementById('modeSelect');
const stateValue = document.getElementById('stateValue');
const timeValue = document.getElementById('timeValue');
const statusText = document.getElementById('statusText');
const connectionInfo = document.getElementById('connectionInfo');
const soundEnabled = document.getElementById('soundEnabled');
const screen = document.querySelector('.screen');

// Served by FastAPI; legacy file:// use requires CORS_ALLOW_ORIGINS=null.
const API_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
const SCRAMBLE_SET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*+-/=<>?▓▒░';
let audioCtx = null;
let requestTimeoutMs = 135000;

function nowTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false });
}

function ensureAudio() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  return audioCtx;
}

function beep(freq = 980, duration = 0.06, delay = 0, volume = 0.03) {
  if (!soundEnabled.checked || !audioCtx || audioCtx.state !== 'running') return;
  try {
    const start = audioCtx.currentTime + delay;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'square';
    osc.frequency.setValueAtTime(freq, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.01);
    osc.onended = () => { osc.disconnect(); gain.disconnect(); };
  } catch (_) {
    // Audio support must not prevent receiving a prescript.
  }
}

function tripleBeep() {
  beep(920, 0.05, 0.00);
  beep(1100, 0.05, 0.09);
  beep(980, 0.07, 0.18);
}

function cursor() {
  const span = document.createElement('span');
  span.className = 'cursor';
  span.textContent = '█';
  span.setAttribute('aria-hidden', 'true');
  return span;
}

function displayText(text, isError = false) {
  const span = document.createElement('span');
  span.className = isError ? 'error' : '';
  span.textContent = text;
  output.replaceChildren(span, cursor());
}

function renderGlyphs(chars, lockedCount) {
  const fragment = document.createDocumentFragment();
  chars.forEach((ch, idx) => {
    const span = document.createElement('span');
    span.className = idx < lockedCount ? 'glyph locked' : 'glyph';
    span.textContent = ch;
    fragment.appendChild(span);
  });
  fragment.appendChild(cursor());
  output.replaceChildren(fragment);
}

async function scrambleReveal(finalText) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    displayText(finalText);
    return;
  }
  const chars = Array.from(finalText);
  const step = Math.max(1, Math.ceil(chars.length / 28));
  output.classList.add('scrambling');
  screen.classList.add('is-receiving');
  for (let locked = 0; locked < chars.length; locked += step) {
    for (let round = 0; round < 2; round++) {
      const working = chars.map((ch, idx) =>
        idx < locked || !ch.trim() ? ch : SCRAMBLE_SET[Math.floor(Math.random() * SCRAMBLE_SET.length)]
      );
      renderGlyphs(working, locked);
      beep(700 + (locked % 6) * 45, 0.014, 0, 0.008);
      await new Promise(resolve => setTimeout(resolve, 18));
    }
  }
  displayText(finalText);
}

async function readResponse(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : `服务请求失败（HTTP ${res.status}）`);
  }
  return data;
}

async function checkConfiguration() {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(10000) });
    const data = await readResponse(res);
    connectionInfo.textContent = `模型：${data.model} · ${data.provider} · 配置已就绪`;
    requestTimeoutMs = (data.timeout_seconds + 15) * 1000;
    if (!receiveBtn.disabled) statusText.textContent = 'CONFIG READY';
  } catch (err) {
    connectionInfo.textContent = `配置检查失败：${err.message || '请确认后端已启动'}`;
    if (!receiveBtn.disabled) statusText.textContent = 'CONFIG ERROR';
  }
}

async function fetchPrescript() {
  if (receiveBtn.disabled) return;
  receiveBtn.disabled = true;
  modeSelect.disabled = true;
  output.setAttribute('aria-busy', 'true');
  stateValue.textContent = 'RECEIVING';
  statusText.textContent = 'REQUESTING';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    if (soundEnabled.checked) {
      try {
        ensureAudio();
        if (audioCtx.state === 'suspended') await audioCtx.resume();
      } catch (_) {}
    }
    tripleBeep();
    displayText('正在接收指令…');
    const res = await fetch(`${API_BASE}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: modeSelect.value }),
      signal: controller.signal
    });
    const data = await readResponse(res);
    if (typeof data.prescript !== 'string' || !data.prescript.trim()) {
      throw new Error('未收到有效指令');
    }
    prescriptId.textContent = `PS-${String(data.id).padStart(3, '0')}`;
    modeValue.textContent = data.mode.toUpperCase();
    stateValue.textContent = 'DECODING';
    timeValue.textContent = nowTime();
    statusText.textContent = 'LINK STABLE';
    tripleBeep();
    await scrambleReveal(data.prescript);
    stateValue.textContent = 'IDLE';
  } catch (err) {
    const message = err.name === 'AbortError'
      ? '接收超时，请稍后重试'
      : err instanceof TypeError
        ? '无法连接服务，请确认后端已启动'
        : String(err.message || err);
    displayText(`信号中断：${message}`, true);
    stateValue.textContent = 'ERROR';
    timeValue.textContent = nowTime();
    statusText.textContent = 'LINK DEGRADED';
    beep(260, 0.15);
  } finally {
    clearTimeout(timer);
    screen.classList.remove('is-receiving');
    output.classList.remove('scrambling');
    output.setAttribute('aria-busy', 'false');
    receiveBtn.disabled = false;
    modeSelect.disabled = false;
  }
}

receiveBtn.addEventListener('click', fetchPrescript);
modeSelect.addEventListener('change', () => { modeValue.textContent = modeSelect.value.toUpperCase(); });
timeValue.textContent = nowTime();
checkConfiguration();
