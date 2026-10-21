/* Windows downloads replace server-side apply/restore. Model-selection tests remain. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).join('\n');

// ---- stub DOM -------------------------------------------------------------
const values = {
  agentBaseUrl: 'http://127.0.0.1:8788/v1',
  agentKeySelect: '__global',
  agentModelSelect: 'model-a',
};
const elements = new Map();
const element = id => {
  if (!elements.has(id)) {
    elements.set(id, {
      id, innerHTML: '', textContent: '', className: '', dataset: {},
      style: {setProperty(){}},
      classList: {add(){}, remove(){}, toggle(){}, contains(){ return false; }},
      addEventListener(){}, removeEventListener(){}, querySelector(){ return null; },
      querySelectorAll(){ return []; }, appendChild(){}, removeChild(){}, focus(){},
      setAttribute(){}, getAttribute(){ return ''; }, removeAttribute(){},
      contains(){ return false; }, closest(){ return null; },
    });
  }
  const el = elements.get(id);
  if (Object.prototype.hasOwnProperty.call(values, id)) el.value = values[id];
  return el;
};

// 面板用 document 级委托监听复选框，所以假 document 得把监听器存下来，测试才
// 能现场派发一个 change 事件（只认含 model-pick 的那个，别误触发别的委托）。
const documentListeners = {};
const fireDocument = (name, ev) => {
  const handler = (documentListeners[name] || []).find(fn => /model-pick/.test(String(fn)));
  assert.ok(handler, '面板没有注册「.model-pick」的 ' + name + ' 委托监听');
  return handler(ev);
};

global.document = {
  getElementById: element,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener(name, fn){ (documentListeners[name] || (documentListeners[name] = [])).push(fn); },
  removeEventListener(){},
  createElement: () => element('created'),
  body: element('body'), head: element('head'), documentElement: element('html'),
  readyState: 'complete',
};
global.window = {
  addEventListener(){}, removeEventListener(){},
  location: {href: 'http://127.0.0.1:8788/', search: '', hash: '', origin: 'http://127.0.0.1:8788'},
  matchMedia: () => ({matches: false, addEventListener(){}}),
};
global.localStorage = {getItem(){ return null; }, setItem(){}, removeItem(){}};
global.sessionStorage = global.localStorage;
global.navigator = {userAgent: 'node'};
global.setInterval = () => 0;
global.clearInterval = () => {};
global.setTimeout = () => 0;
global.clearTimeout = () => {};
global.location = global.window.location;
global.alert = () => {};
global.confirm = () => true;
global.console.log = () => {};

// ---- capture every request the page makes ---------------------------------
// 「网关模型清单」的勾选态：一键配置只把勾选中的模型写进客户端。
// configured=false 模拟「服务端还没存过」——老安装升到带勾选这版后的第一屏。
const SELECTED = {models: ['model-a', 'model-b'], configured: true};
// 勾选的默认态读的是 MODELS_DATA；面板里它挂在 window 上，测试的 window 不是真
// 全局，所以先把真全局铺好，免得 loadModels 之外的路径拿到 undefined。
global.MODELS_DATA = [];
const requests = [];
const respond = (url, opts) => {
  const u = String(url);
  const isPost = !!(opts && String(opts.method || '').toUpperCase() === 'POST');
  let payload;
  if (u.includes('/agents/model-selection')) {
    // POST 回声请求体：真服务端会清洗后回一份规范清单，这里让它别把刚发出去的选择改掉。
    payload = isPost && opts.body
      ? {configured: true, selected_models: (JSON.parse(String(opts.body)).models || []).slice()}
      : {configured: SELECTED.configured, selected_models: SELECTED.models.slice()};
  } else if (u.includes('/agents')) {
    payload = {clients: [], keys: [], models: [], gateway: {base_url: 'http://127.0.0.1:8788/v1'}};
  } else {
    payload = {rows: [], total: 0, accounts: [], slots: [], data: [], results: [], byAccount: []};
  }
  return Promise.resolve({
    status: 200, ok: true,
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  });
};
const realFetch = (url, opts) => respond(url, opts);
global.fetch = (url, opts) => {
  requests.push({url: String(url), opts: opts || {}});
  return respond(url, opts);
};

// ---- load the shipped page scripts ---------------------------------------
const api = new Function(script + `
  window.__setSelection = function(list, configured){
    AGENT_MODEL_SELECTION = new Set((list || []).map(String));
    MODEL_SELECTION_CONFIGURED = configured !== false;
    MODEL_SELECTION_SAVED = MODEL_SELECTION_CONFIGURED ? new Set(AGENT_MODEL_SELECTION) : null;
  };
  window.__setModelsData = function(list){ MODELS_DATA = list; };
  return { loadAgents, copyAgentUrl, loadAgentsAvailability, switchMainTab,
           setSelection: window.__setSelection, setModelsData: window.__setModelsData,
           loadAgentModelSelection, applyModelPickAction, isModelPicked,
           syncModelPickBoxes, saveModelSelection,
           selection: function(){ return Array.from(AGENT_MODEL_SELECTION); },
           isConfigured: function(){ return MODEL_SELECTION_CONFIGURED; },
           currentTab: function(){ return currentMainTab; } };`)();

const CLIENTS = [{
  id: 'claude-code', label: 'Claude Code', desc: 'Anthropic CLI',
  protocol: 'anthropic', config_paths: ['/home/u/.claude/settings.json'],
  installed: true, applied: null,
}];
const MODELS = [
  {id: 'model-a', context_window: 131072},
  {id: 'model-b', context_window: 65536},
];

let checks = 0;
const check = (label, cond, extra) => {
  checks += 1;
  assert.ok(cond, label + (extra ? '  [' + extra + ']' : ''));
};

(async () => {
  const select = list => { SELECTED.models = list; api.setSelection(list); };
  select(['model-a', 'model-b']);
  requests.length = 0;
  window.location.origin = 'https://gateway.example:8443';
  await api.loadAgentsAvailability();
  await api.loadAgents();
  check('download page uses the visitor-facing HTTPS address and port',
        element('agentOpenAIUrl').textContent === 'https://gateway.example:8443/v1');
  check('downloads do not probe the server or POST configuration', requests.length === 0);
  check('Windows EXE is linked', html.includes('releases/download/windows-client/WorkBuddy-Setup.exe'));
  check('no apply or restore function remains in the browser',
        !/function (?:applyAgent|restoreAgent)\(/.test(script));
  check('no browser request can apply or restore server configuration',
        !/postJSON\(['"]\/agents\/(?:apply|restore)/.test(script));
  check('login screen has a public setup link',
        html.slice(html.indexOf('id="panelGate"'), html.indexOf('<main>')).includes('href="/agents/setup"'));
  api.switchMainTab('agents');
  check('remote users can open the agents tab', api.currentTab() === 'agents');
  check('the tab is not hidden remotely', element('btnNavAgents').style.display !== 'none');
  window.location.pathname = '/u/account-a/dashboard';
  api.loadAgents();
  check('pinned-account address is retained',
        element('agentOpenAIUrl').textContent === 'https://gateway.example:8443/u/account-a/v1');
  let copied = '';
  navigator.clipboard = {writeText: async value => { copied = value; }};
  await api.copyAgentUrl('agentOpenAIUrl', null);
  check('copy uses the visitor address', copied === element('agentOpenAIUrl').textContent);
  window.location.pathname = '/';

  // ---- 默认态契约：服务端没存过 = 全部勾选 ---------------------------------
  // 勾选这版之前，「一键配置」写的是整份目录。`agent_models` 还没落过时后端回
  // configured=false，面板必须把空集合读成「全都要」——否则老安装升级后第一次点
  // 一键配置会突然被拒绝，而用户一个模型都没动过。
  const MODEL_IDS = MODELS.map(m => m.id);
  api.setModelsData(MODELS.slice());
  SELECTED.configured = false;
  SELECTED.models = [];
  await api.loadAgentModelSelection();
  check('configured=false 时面板记为「没存过」', api.isConfigured() === false);
  check('从未保存 ⇒ 每个模型都算勾选',
        MODEL_IDS.every(id => api.isModelPicked(id)), JSON.stringify(api.selection()));
  api.syncModelPickBoxes();
  check('从未保存 ⇒ 计数写全量',
        /\(共 2 个\) · 已选 2/.test(element('availModelCount').textContent || ''),
        element('availModelCount').textContent);

  // 从全选态里取消一个：必须先把整份清单物化成显式集合，再动这一项。少了这一步，
  // 「取消 model-b」会被存成「只选了 model-a」——语义正好反了。
  requests.length = 0;
  fireDocument('change', {target: {
    dataset: {modelId: 'model-b'}, checked: false,
    classList: {contains: name => name === 'model-pick'},
  }});
  await api.saveModelSelection();
  const materialiseReq = requests.find(r => r.url.indexOf('/agents/model-selection') !== -1);
  const materialiseBody = JSON.parse((materialiseReq && materialiseReq.opts.body) || '{}');
  check('从未保存时取消一项 → 先物化全量再落盘（存成其余全部）',
        Array.isArray(materialiseBody.models) && materialiseBody.models.length === 1
          && materialiseBody.models[0] === 'model-a', JSON.stringify(materialiseBody.models));
  check('落一次盘就转入「已保存」态', api.isConfigured() === true);

  // ---- 表头三个批量动作 ---------------------------------------------------
  // 做成按钮而不是「反选」复选框：反选是动作、不是状态，复选框形态要么得额外记
  // 一份「反选之前的集合」，要么让界面勾选和实际保存的清单分家。
  api.applyModelPickAction('invert');
  check('反选按当前勾选逐项取反', api.selection().join(',') === 'model-b', api.selection().join(','));
  api.applyModelPickAction('all');
  check('全选勾上整份当前清单',
        MODEL_IDS.every(id => api.isModelPicked(id)) && api.selection().length === 2,
        JSON.stringify(api.selection()));
  api.applyModelPickAction('none');
  requests.length = 0;
  await api.saveModelSelection();
  const clearPost = requests.find(r => r.url.indexOf('/agents/model-selection') !== -1);
  const clearBody = JSON.parse((clearPost && clearPost.opts.body) || '{}');
  check('全不选把空清单落盘（后端据此拒绝写空模型清单，而不是写一份空的）',
        Array.isArray(clearBody.models) && clearBody.models.length === 0, JSON.stringify(clearBody));
  api.syncModelPickBoxes();
  check('全不选 ⇒ 计数写 0，一眼看得出没选',
        /已选 0/.test(element('availModelCount').textContent || ''),
        element('availModelCount').textContent);

  SELECTED.configured = true;
  select(['model-a', 'model-b']);

  process.stdout.write('agent config UI assertions passed (' + checks + ' checks)\n');
})().catch(err => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
