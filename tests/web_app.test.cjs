const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name)
    };
    this.value = '';
    this.disabled = false;
    this.checked = false;
    this._text = '';
  }
  get textContent() {
    return this._text + this.children.map(child => child.textContent).join('');
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  set innerHTML(_) {
    throw new Error('Untrusted text must not be rendered as HTML');
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
  appendChild(child) {
    if (child.tagName === '#fragment') this.children.push(...child.children);
    else this.children.push(child);
  }
  replaceChildren(...children) {
    this.children = [];
    this._text = '';
    children.forEach(child => this.appendChild(child));
  }
}

function response(data, status = 200) {
  return { ok: status < 400, status, json: async () => data };
}

async function loadPage(generateResponse, { healthResponse, reducedMotion = true } = {}) {
  const ids = [
    'output', 'receiveBtn', 'prescriptId', 'modeValue', 'modeSelect',
    'stateValue', 'timeValue', 'statusText', 'connectionInfo', 'soundEnabled'
  ];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.modeSelect.value = 'ritual';
  elements.prescriptId.textContent = 'PS-000';
  const screen = new Element();
  const calls = [];
  const context = vm.createContext({
    document: {
      getElementById: id => elements[id],
      querySelector: () => screen,
      createElement: tag => new Element(tag),
      createDocumentFragment: () => new Element('#fragment')
    },
    location: { protocol: 'http:' },
    window: { matchMedia: () => ({ matches: reducedMotion }) },
    fetch: async (url, options) => {
      calls.push({ url, options });
      if (url.endsWith('/health')) {
        return healthResponse || response({
          model: 'test-model', provider: 'openai_compatible', timeout_seconds: 120
        });
      }
      if (generateResponse instanceof Error) throw generateResponse;
      return generateResponse;
    },
    Date, Math, Promise, AbortController, AbortSignal,
    setTimeout: (callback, delay) => delay < 1000 ? setTimeout(callback, 0) : setTimeout(callback, delay),
    clearTimeout
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  return { elements, screen, calls };
}

test('health reports configuration without sending a generation request', async () => {
  const { elements, calls } = await loadPage(response({}));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/health');
  assert.equal(elements.statusText.textContent, 'CONFIG READY');
  assert.match(elements.connectionInfo.textContent, /test-model/);
});

test('selected mode is sent and persistent ID is displayed', async () => {
  const { elements, calls } = await loadPage(response({
    id: 42, mode: 'daily', prescript: '将空杯放到桌面左侧'
  }));
  elements.modeSelect.value = 'daily';
  await elements.receiveBtn.listeners.click();
  assert.equal(calls[1].url, '/generate');
  assert.deepEqual(JSON.parse(calls[1].options.body), { mode: 'daily' });
  assert.equal(elements.prescriptId.textContent, 'PS-042');
  assert.equal(elements.stateValue.textContent, 'IDLE');
  assert.equal(elements.modeValue.textContent, 'DAILY');
  assert.match(elements.output.textContent, /将空杯放到桌面左侧/);
  assert.equal(elements.receiveBtn.disabled, false);
  assert.equal(elements.modeSelect.disabled, false);
  assert.equal(elements.output.attributes['aria-busy'], 'false');
});

test('model text and glyph animation never interpret HTML', async () => {
  const text = '<img src=x onerror=alert(1)>把空杯放到桌面';
  const { elements, screen } = await loadPage(response({
    id: 7, mode: 'ritual', prescript: text
  }), { reducedMotion: false });
  await elements.receiveBtn.listeners.click();
  assert.equal(elements.stateValue.textContent, 'IDLE');
  assert.equal(elements.output.children[0].textContent, text);
  assert.equal(screen.classes.has('is-receiving'), false);
  assert.equal(elements.output.classes.has('scrambling'), false);
});

test('API errors are shown and controls recover without consuming a new ID', async () => {
  const { elements } = await loadPage(response({ detail: '模型服务限流或额度不足' }, 429));
  await elements.receiveBtn.listeners.click();
  assert.match(elements.output.textContent, /模型服务限流或额度不足/);
  assert.equal(elements.stateValue.textContent, 'ERROR');
  assert.equal(elements.statusText.textContent, 'LINK DEGRADED');
  assert.equal(elements.prescriptId.textContent, 'PS-000');
  assert.equal(elements.receiveBtn.disabled, false);
});

test('empty successful responses are treated as errors', async () => {
  const { elements } = await loadPage(response({ id: 1, mode: 'ritual', prescript: '' }));
  await elements.receiveBtn.listeners.click();
  assert.equal(elements.stateValue.textContent, 'ERROR');
  assert.match(elements.output.textContent, /未收到有效指令/);
});

test('configuration errors remain readable', async () => {
  const { elements } = await loadPage(response({}), {
    healthResponse: response({ detail: '请在后端 .env 中设置 LLM_API_KEY。' }, 503)
  });
  assert.equal(elements.statusText.textContent, 'CONFIG ERROR');
  assert.match(elements.connectionInfo.textContent, /LLM_API_KEY/);
});
