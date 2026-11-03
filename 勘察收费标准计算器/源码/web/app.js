/* 工程勘察收费标准计算器（2002） —— 前端逻辑 */
'use strict';

/* 启动诊断日志（供打包后的自检探针读取） */
window.__kc = ['脚本已执行'];
const klog = m => { try { window.__kc.push(m); } catch (e) { } };

/* --------------------------------------------------- 后端接口（本地 HTTP） */
async function rpc(method, ...args) {
  const res = await fetch('/rpc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, args })
  });
  if (!res.ok) throw new Error('本地服务返回 HTTP ' + res.status);
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || '调用失败');
  return j.data;
}
const api = {
  get_standards: () => rpc('get_standards'),
  calc: s => rpc('calc', s),
  default_dir: () => rpc('default_dir'),
  open_path: p => rpc('open_path', p),
  export_excel: p => rpc('export_excel', p),
  export_report: p => rpc('export_report', p),
  save_project: p => rpc('save_project', p),
  load_project: p => rpc('load_project', p),
  parse_lizheng: p => rpc('parse_lizheng', p)
};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const num = v => { const n = parseFloat(v); return isNaN(n) ? 0 : n; };
const r2 = n => Math.round((n + Number.EPSILON) * 100) / 100;
const money = n => '¥' + (Number(n) || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money0 = n => (Number(n) || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const uid = () => Math.random().toString(36).slice(2, 8);

let STD = null;
let S = null;
let R = null;
let MOD = 'soil';
let REF = { tabs: [], active: 0, scope: 'soil' };
let LZ = null;          // 理正解析结果
let calcTimer = null;
let busy = 0;

const CLS_NAME = ['Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ'];
const CLS_COLOR = ['#C9D8EA', '#B4CDB2', '#E6D3A4', '#DBBE99', '#C6ACA0', '#A99A93'];

/* 标准贯入：每层土新增一行时次数默认值 */
const SPT_DEFAULT_QTY = 6;

/* 层号：①②③…，超过 20 个用 (21) 形式 */
const CIRCLE_NO = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
function circleNo(i) { return i < CIRCLE_NO.length ? CIRCLE_NO[i] : '(' + (i + 1) + ')'; }
/* 取当前最大层号的下一个序号 */
function nextCode() {
  return circleNo((S.layers || []).length);
}

/* ------------------------------------------------------------------ 状态 */
function defaultState() {
  return {
    meta: { project: '', owner: '', unit: '' },
    grade: '甲级',
    mode: 'budget',
    qtyMode: 'manual',   // manual = 人工录入；lz = 导入理正备份库
    layers: [
      { code: '①', name: '素填土', cls: 1, bottom: 1.5 },
      { code: '②', name: '黏土', cls: 1, bottom: 8.0 },
      { code: '③', name: '粉质粘土', cls: 1, bottom: 12.0 },
      { code: '④', name: '粉土', cls: 1, bottom: 16.0 },
      { code: '⑤', name: '圆砾', cls: 3, bottom: 24.0 },
      { code: '⑥', name: '泥岩', cls: 3, bottom: 32.0 },
    ],
    holeTypes: [
      { name: '控制孔', count: 10, depth: 32 },
      { name: '鉴别孔', count: 10, depth: 20 },
    ],
    holes: [],
    spt: [],
    dpt: [],
    otherTest: [],
    extraDig: [],
    sample: { undist: { count: 0, device: 'hammer', band: 0 }, disturb: 0, core: 0, point: 0, water: 0 },
    coefSoil: [], coefGlobal: [], coefGeo: [],
    lab: { items: [] },
    labInSite: false,
    geo: { wave: { holes: 0, testLen: 0, method: 'single', minGroup: true, holeNos: [] }, elec: [], extra: [] },
    other: { survey: 0, kantan: 0, yanzao: 0, report: 0, custom: [] },
    float: 0, discount: 0,
  };
}

/* ------------------------------------------------------------------ 路径读写 */
function setPath(obj, path, val) {
  const ps = path.split('.'); let o = obj;
  for (let i = 0; i < ps.length - 1; i++) { if (o[ps[i]] == null) o[ps[i]] = {}; o = o[ps[i]]; }
  o[ps[ps.length - 1]] = val;
}
function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
}

/* ------------------------------------------------------------------ 提示 */
let toastT = null;
function toast(msg, type = '') {
  const t = $('#toast'); t.textContent = msg; t.className = 'toast on ' + type;
  clearTimeout(toastT); toastT = setTimeout(() => t.className = 'toast ' + type, 2600);
}
function mask(on, text) { $('#mask').classList.toggle('on', !!on); if (text) $('#maskText').textContent = text; }
function status(html) { $('#fStatus').innerHTML = html; }

/* ------------------------------------------------------------------ 计算 */
function calcNow(rebuild) {
  clearTimeout(calcTimer);
  calcTimer = setTimeout(async () => {
    if (!S) return;
    // 取样数量变化后，未解除联动的室内试验项目自动跟随
    if (syncLabAuto() && MOD === 'lab') render();
    busy++; status('<span style="color:#8A97A6">计算中…</span>');
    try {
      const res = await api.calc(S);
      busy--;
      if (!res || !res.ok) { status('<span class="err">计算失败：' + esc((res && res.error) || '未知错误') + '</span>'); return; }
      R = res.data;
      paintTotals();
      if (rebuild !== false) paintResults();
      status('<span class="ok">已计算</span>');
      if (R.warnings && R.warnings.length) {
        status('<span style="color:#D98324">' + esc(R.warnings[0]) + (R.warnings.length > 1 ? ' 等' + R.warnings.length + '条' : '') + '</span>');
      }
    } catch (e) {
      busy--; status('<span class="err">' + esc(e.message) + '</span>');
    }
  }, 140);
}

function paintTotals() {
  if (!R) return;
  const t = R.totals;
  const secs = {}; R.sections.forEach(s => secs[s.key] = s);
  const set = (id, v) => { const el = $(id); if (el) el.textContent = v > 0 ? (v / 10000).toFixed(2) + '万' : ''; };
  set('#navSoil', secs.soil ? secs.soil.amount : 0);
  set('#navLab', secs.lab ? secs.lab.amount : 0);
  set('#navGeo', secs.geo ? secs.geo.amount : 0);
  set('#navOther', secs.other ? secs.other.amount : 0);

  // 左栏费用汇总
  const rows = R.sections.map(s => `<tr title="${esc(s.title)}">
      <td>${esc(s.title.replace(/^[一二三四五]、/, ''))}</td>
      <td class="num">${(s.real / 10000).toFixed(2)}</td>
      <td class="num">${(s.amount / 10000).toFixed(2)}</td></tr>`).join('');
  const sumReal = R.sections.reduce((a, s) => a + s.real, 0);
  const sr = $('#sumRows');
  if (sr) sr.innerHTML = rows + `<tr class="tot"><td>合计</td><td class="num">${(sumReal / 10000).toFixed(2)}</td>
    <td class="num">${(t.base / 10000).toFixed(2)}</td></tr>`;
  if ($('#sumBase')) $('#sumBase').textContent = money(t.base);
  if ($('#sumFinal')) $('#sumFinal').textContent = money(t.final);

  const holes = (R.holes || []).length;
  const depth = (R.holes || []).reduce((a, h) => a + (h.depth || 0), 0);
  const ks = $('#kSoil');
  if (ks && R.sections[0]) ks.textContent = '×' + (R.sections[0].coef || 1).toFixed(2);
  $('#fHoles').textContent = holes;
  $('#fDepth').textContent = r2(depth).toLocaleString();
  $('#fLayers').textContent = (S.layers || []).length;

  // 左栏工作量速览
  const el = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  el('#qHoles', holes + ' 个 / ' + r2(depth).toLocaleString() + ' m');
  const sptN = (S.spt || []).reduce((a, t) => a + num(t.count), 0);
  const dptM = (S.dpt || []).reduce((a, t) => a + num(t.meters), 0);
  el('#qSpt', sptN + ' 次 / ' + r2(dptM) + ' m');
  const smp = num((S.sample.undist || {}).count) + num(S.sample.disturb) + num(S.sample.core)
    + num(S.sample.point) + num(S.sample.water);
  const labN = (S.lab.items || []).length;
  el('#qLab', smp + ' 件 / ' + labN + ' 项');
  const nos = (S.geo.wave || {}).holeNos || [];
  const wvH = (S.qtyMode === 'lz' && nos.length)
    ? nos.filter(no => (S.holes || []).some(h => h.no === no)).length
    : num((S.geo.wave || {}).holes);
  const elecP = (S.geo.elec || []).reduce((a, e) => a + num(e.qty), 0);
  el('#qGeo', wvH + ' 孔 / ' + r2(elecP) + ' 点');
}

/* 左栏参数回填（避免覆盖正在输入的框） */
function syncSide() {
  if (!S) return;
  const put = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
  put('#pDisc', S.discount || 0);
}

/* ------------------------------------------------------------------ 顶层渲染 */
function render() {
  $$('.nav').forEach(n => n.classList.toggle('on', n.dataset.mod === MOD));
  const map = { soil: '工程勘察', lab: '室内试验', geo: '工程物探', other: '其他费用' };
  const subs = {
    soil: '标准地层、钻孔布置与各项实物工作量录入',
    lab: '土工、水质、岩石试验费用统计', geo: '钻孔波速、电法勘探及其他物探', other: '定点测量、验槽、报告费等'
  };
  $('#center').innerHTML = `<div class="page-head"><h1>${map[MOD]}</h1><p>${subs[MOD]}</p></div><div id="mod"></div>`;
  const box = $('#mod');
  if (MOD === 'soil') renderSoil(box);
  if (MOD === 'lab') renderLab(box);
  if (MOD === 'geo') renderGeo(box);
  if (MOD === 'other') renderOther(box);
  renderRef();
  paintTotals();
  paintResults();
  syncSide();
  calcNow();
}

/* ------------------------------------------------------------------ 通用组件 */
function coefBox(list, key, title) {
  const on = S[key] || [];
  return `<div class="body"><div class="small" style="margin-bottom:8px">${title}</div>
  <div class="coefs">${list.map(c => `
    <label class="chk ${on.includes(c.id) ? 'on' : ''}">
      <input type="checkbox" data-coef="${key}" value="${c.id}" ${on.includes(c.id) ? 'checked' : ''}>
      <span>${esc(c.name)}</span><span class="v">×${c.v.toFixed(2)}</span>
    </label>`).join('')}</div></div>`;
}

/* --------------------------------------- 模块1 工程勘察（工作量 + 取费一体） */
function renderSoil(box) {
  const lz = S.qtyMode === 'lz';
  box.innerHTML = `
  <div class="card"><div class="body" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <div class="seg">
      <button class="${lz ? '' : 'on'}" data-qtab="manual">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20h16M7 20V9M12 20V4M17 20v-7"/></svg>
        人工录入</button>
      <button class="${lz ? 'on' : ''}" data-qtab="lz">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></svg>
        导入理正备份库</button>
    </div>
    <span class="small">${lz ? '读取理正备份库（.mdb/.accdb）或导出的 Excel，孔深、分层、标贯、动探、取样直接用实测数据'
      : '手工确定标准地层、钻孔布置与各项实物工作量'}</span>
    <span style="flex:1"></span>
    ${lz ? `<button class="btn tiny pri" data-act="importLz">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/></svg>
      ${S.holes.length ? '重新选择备份库' : '选择理正备份库'}</button>` : ''}
    <span class="small">计价类别</span>
    <div class="seg">
      <button class="${S.mode === 'settle' ? '' : 'on'}" data-pmode="budget">预算</button>
      <button class="${S.mode === 'settle' ? 'on' : ''}" data-pmode="settle">结算</button>
    </div>
  </div></div>
  <div id="qbody"></div>`;
  $$('[data-qtab]').forEach(b => b.onclick = () => switchQty(b.dataset.qtab));
  $$('[data-pmode]').forEach(b => b.onclick = () => { S.mode = b.dataset.pmode; render(); });
  renderManual($('#qbody'));
}

/* 两种模式各自保存一份数据：切到人工录入时，界面与数据都回到人工录入那一套；
   切到导入模式时回到理正实测那一套，互不覆盖。 */
function switchQty(mode) {
  if (mode === S.qtyMode) return;
  const pack = () => JSON.parse(JSON.stringify({
    layers: S.layers || [], spt: S.spt || [], dpt: S.dpt || [],
    sample: S.sample || {},
  }));
  S['snap_' + S.qtyMode] = pack();
  const snap = S['snap_' + mode];
  if (snap) {
    S.layers = snap.layers || [];
    S.spt = snap.spt || [];
    S.dpt = snap.dpt || [];
    S.sample = snap.sample || S.sample;
  }
  S.qtyMode = mode;
  render();
}

function renumberLayers() {
  (S.layers || []).forEach((L, i) => { L.code = circleNo(i); });
}

function renderManual(q) {
  const lz = S.qtyMode === 'lz';
  const layers = S.layers || [];
  let acc = 0;
  const segs = layers.map((L, i) => {
    const top = acc, bot = num(L.bottom); acc = Math.max(acc, bot);
    return { ...L, top, bot, i, th: Math.max(0, bot - top) };
  });
  const maxD = Math.max(10, acc);
  const H = 250, W = 150, X0 = 34, X1 = W - 12;
  const yOf = d => 8 + (d / maxD) * (H - 16);
  let ticks = '';
  const step = maxD <= 20 ? 2 : maxD <= 50 ? 5 : 10;
  for (let d = 0; d <= maxD + 1e-9; d += step) {
    const y = yOf(d);
    ticks += `<line x1="${X0 - 4}" y1="${y.toFixed(1)}" x2="${X0}" y2="${y.toFixed(1)}" stroke="#D6DEE8" stroke-width="1"/>
      <text x="${X0 - 6}" y="${(y + 3).toFixed(1)}" font-size="8.5" fill="#8A97A6" text-anchor="end">${d}</text>`;
  }
  const svg = segs.length ? `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    ${segs.map(s => {
      const y1 = yOf(s.top), y2 = yOf(s.bot);
      const h = Math.max(1.5, y2 - y1);
      return `<rect x="${X0}" y="${y1.toFixed(1)}" width="${X1 - X0}" height="${h.toFixed(1)}" fill="${CLS_COLOR[(s.cls || 1) - 1]}" stroke="#fff" stroke-width="1"></rect>
      ${h > 13 ? `<text x="${(X0 + X1) / 2}" y="${(y1 + h / 2 + 3.5).toFixed(1)}" font-size="9.5" fill="#33445A" text-anchor="middle">${esc(s.code || '')}</text>` : ''}`;
    }).join('')}
    ${ticks}
    <line x1="${X0}" y1="8" x2="${X0}" y2="${H - 8}" stroke="#C9D4E2" stroke-width="1"/>
  </svg>` : '';

  // 钻孔 / 进尺：按当前模式取数（人工录入看孔型，导入看实测孔）
  const holesM = lz ? S.holes : [];
  const nHole = lz ? holesM.length : S.holeTypes.reduce((a, h) => a + num(h.count), 0);
  const totalD = lz ? holesM.reduce((a, h) => a + num(h.depth), 0)
                    : S.holeTypes.reduce((a, h) => a + num(h.count) * num(h.depth), 0);
  const maxHole = lz ? Math.max(0, ...holesM.map(h => num(h.depth)))
                     : Math.max(0, ...S.holeTypes.map(h => num(h.depth)));
  const sptTotal = (S.spt || []).reduce((a, t) => a + num(t.count), 0);
  const dptMeters = (S.dpt || []).reduce((a, t) => a + num(t.meters), 0);
  const sptMin = nHole / 3;
  const sptShort = nHole > 0 && sptTotal > 0 && sptTotal <= sptMin;

  // 导入提示只在「导入理正备份库」模式显示
  let banner = '';
  if (lz && LZ && !LZ.ok) {
    banner = `<div class="card"><div class="body"><div class="hint" style="margin:0">读取失败：${esc(LZ.file || '')}　${esc(LZ.error || '').replace(/\n/g, '<br>')}
      <span style="float:right"><button class="btn tiny" data-act="importLz">重新选择</button></span></div></div></div>`;
  } else if (lz && LZ && LZ.ok && S.holes.length) {
    const s = LZ.summary || {};
    const smp = num(s.samples);
    banner = `<div class="card"><div class="body" style="padding:10px 12px">
      <div class="hint ok" style="margin:0;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <span style="flex:1">✔ 已从 <b>${esc(LZ.file || LZ.source || '理正备份库')}</b> 导入：
          <b>${s.holes || S.holes.length}</b> 个钻孔、进尺 <b>${s.totalDepth || r2(totalD)}</b> m、
          <b>${s.layers}</b> 条分层、标贯 <b>${s.spt}</b> 次、动探 <b>${s.dpt}</b> m${smp ? '、取样 <b>' + smp + '</b> 件' : ''}。
          孔深、分层与标贯 / 动探 / 取样均取实测数据。</span>
        <button class="btn tiny" data-act="importLz">重新导入</button>
        <button class="btn tiny ghost" data-act="clearHoles">清除实测数据</button>
      </div></div></div>`;
  }

  // 标准地层：人工录入带层底深与柱状图；导入模式只保留层号 / 名称 / 类别（深度以实测分层为准）
  const layerBody = lz ? `
    <div class="body tight">
      <table><thead><tr><th style="width:10%">层号</th><th style="width:38%">岩土名称</th>
      <th style="width:24%">岩土类别</th><th style="width:20%" class="num">分层记录</th><th style="width:8%"></th></tr></thead>
      <tbody>${layers.length ? layers.map((L, i) => `<tr>
        <td class="ctr"><b style="color:var(--txt-2)">${esc(L.code || circleNo(i))}</b></td>
        <td><input class="cell" data-bind="layers.${i}.name" data-guess="1" list="nameList"
          placeholder="选择或输入岩土名称" value="${esc(L.name)}"></td>
        <td><select class="cell" data-bind="layers.${i}.cls" data-type="int">
          ${CLS_NAME.map((n, k) => `<option value="${k + 1}" ${(L.cls || 1) === k + 1 ? 'selected' : ''}>${n}类</option>`).join('')}
        </select></td>
        <td class="num small">${num(L.count) || '—'}</td>
        <td><button class="del" data-act="delLayer" data-i="${i}">×</button></td></tr>`).join('')
        : `<tr><td colspan="5" style="text-align:center;color:#8A97A6;padding:26px">尚未导入理正备份库，点右上「选择理正备份库」</td></tr>`}
      </tbody></table>
    </div>` : `
    <div class="body">
      <div class="profile">
        ${svg}
        <div class="ptable">
          <table><thead><tr><th style="width:10%">层号</th><th style="width:30%">岩土名称</th><th style="width:19%">岩土类别</th>
          <th style="width:18%">层底深(m)</th><th style="width:15%" class="num">层厚</th><th style="width:8%"></th></tr></thead>
          <tbody>${segs.length ? segs.map((s, i) => `<tr>
            <td class="ctr"><b style="color:var(--txt-2)">${esc(s.code || circleNo(i))}</b></td>
            <td><input class="cell" data-bind="layers.${s.i}.name" data-guess="1" list="nameList"
              placeholder="选择或输入岩土名称" value="${esc(s.name)}"></td>
            <td><select class="cell" data-bind="layers.${s.i}.cls" data-type="int">
              ${CLS_NAME.map((n, k) => `<option value="${k + 1}" ${(s.cls || 1) === k + 1 ? 'selected' : ''}>${n}类</option>`).join('')}
            </select></td>
            <td><input class="cell num" type="number" step="0.1" data-bind="layers.${s.i}.bottom" value="${s.bottom}"></td>
            <td class="num small">${s.th ? s.th.toFixed(2) : '—'}</td>
            <td><button class="del" data-act="delLayer" data-i="${s.i}">×</button></td></tr>`).join('')
        : `<tr><td colspan="6" style="text-align:center;color:#8A97A6;padding:26px">点击右上角「+ 添加地层」开始录入</td></tr>`}
          </tbody></table>
        </div>
      </div>
    </div>`;

  // 钻孔布置：导入模式孔深只读（严格按备份库实测）
  const holeBody = lz ? (S.holes.length ? `
    <div class="body tight" style="max-height:320px;overflow:auto">
      <table><thead><tr><th style="width:96px">孔号</th><th style="width:92px">孔型</th><th style="width:92px" class="num">孔深(m)</th>
        <th style="width:64px" class="num">分层数</th><th>分层（层底/名称/类别）</th></tr></thead>
        <tbody>${S.holes.map(h => `<tr>
          <td class="small">${esc(h.no)}</td>
          <td class="small">${esc(h.type || '钻孔')}</td>
          <td class="num small">${num(h.depth).toFixed(2)}</td>
          <td class="num">${(h.layers || []).length}</td>
          <td class="small">${((h.layers || []).slice(0, 8).map(L => `${L.bottom}m ${esc(L.name)} <span class="tag c${L.cls}">${CLS_NAME[L.cls - 1]}</span>`).join('　'))}${(h.layers || []).length > 8 ? ' …' : ''}</td>
        </tr>`).join('')}
      </tbody></table>
    </div>` : `
    <div class="body"><div class="empty" style="padding:20px">尚未导入钻孔数据，点上方「选择理正备份库」</div></div>`) : `
    <div class="body tight">
      <table><thead><tr><th style="width:150px">孔型</th><th style="width:100px">数量（个）</th>
      <th style="width:120px">孔深（m）</th><th class="num">进尺（m）</th><th style="width:36px"></th></tr></thead>
      <tbody>${S.holeTypes.map((h, i) => `<tr>
        <td><input class="cell" data-bind="holeTypes.${i}.name" value="${esc(h.name)}"></td>
        <td><input class="cell num" type="number" min="0" data-bind="holeTypes.${i}.count" value="${h.count}"></td>
        <td><input class="cell num" type="number" step="0.5" min="0" data-bind="holeTypes.${i}.depth" value="${h.depth}"></td>
        <td class="num">${r2(num(h.count) * num(h.depth)).toLocaleString()}</td>
        <td><button class="del" data-act="delHoleType" data-i="${i}">×</button></td></tr>`).join('')}
      </tbody></table>
    </div>`;

  q.innerHTML = `
  <datalist id="nameList">${(STD.name_presets || []).map(n => `<option value="${esc(n)}"></option>`).join('')}</datalist>
  ${banner}
  <div class="card"><header><h3><span class="idx">1</span>标准地层</h3>
    <span class="desc">${lz ? '按备份库层号顺序排列（同名层不合并），深度以钻孔实测分层为准'
      : '按自上而下顺序录入；层号自动延续，岩土名称可下拉选择或自行输入'}</span>
    <div class="right">${lz ? '' : `
      <button class="btn tiny" data-act="addLayer">+ 添加地层</button>
      <button class="btn tiny ghost" data-act="clearLayer">清空</button>`}
    </div></header>
    ${layerBody}
    <div class="stat">${lz ? `
      <div class="it"><span class="k">地层数</span><span class="v">${layers.length}</span></div>
      <div class="it"><span class="k">分层记录</span><span class="v">${layers.reduce((a, L) => a + num(L.count), 0)} 条</span></div>
      <div class="it"><span class="k">最深孔</span><span class="v">${r2(maxHole)} m</span></div>` : `
      <div class="it"><span class="k">地层总厚</span><span class="v">${acc.toFixed(2)} m</span></div>
      <div class="it"><span class="k">地层数</span><span class="v">${layers.length}</span></div>
      <div class="it"><span class="k">最深层底</span><span class="v">${acc.toFixed(2)} m</span></div>`}
    </div>
  </div>

  <div class="card"><header><h3><span class="idx">2</span>钻孔布置</h3>
    ${lz ? `
      <span class="desc">孔深严格按理正备份库实测值，不可修改</span>
      <div class="right"><span class="small">钻孔总数</span><b>${S.holes.length}</b></div>` : `
      <span class="desc">控制孔数量默认为钻孔总数的一半，可增删孔型</span>
      <div class="right">
        <span class="small">钻孔总数</span>
        <input class="cell" style="width:64px;border-color:var(--line)" type="number" min="0" id="holeTotal" value="${S.holeTypes.reduce((a, h) => a + num(h.count), 0)}">
        <button class="btn tiny" data-act="half">按一半分配</button>
        <button class="btn tiny" data-act="addHoleType">+ 增加孔型</button>
      </div>`}
    </header>
    ${holeBody}
    <div class="stat">
      <div class="it"><span class="k">钻孔数</span><span class="v">${nHole} 个</span></div>
      <div class="it"><span class="k">总进尺</span><span class="v">${r2(totalD).toLocaleString()} m</span></div>
      <div class="it"><span class="k">最深孔</span><span class="v">${r2(maxHole)} m</span></div>
    </div>
  </div>

  <div class="card"><header><h3><span class="idx">3</span>标准贯入试验</h3>
    <span class="desc">逐层添加，自动带出岩土类别与深度档；每层次数默认 ${SPT_DEFAULT_QTY} 次，可修改</span>
    <div class="right"><button class="btn tiny" data-act="addSpt">+ 添加</button></div></header>
    <div class="body tight">
      ${S.spt.length ? `<table><thead><tr><th>试验土层</th><th style="width:70px">类别</th>
      <th style="width:132px">试验深度</th><th style="width:84px">次数</th><th style="width:90px" class="num">单价</th><th style="width:36px"></th></tr></thead>
      <tbody>${S.spt.map((t, i) => `<tr>
        <td><select class="cell" data-layer="spt" data-i="${i}">
          <option value="">— 选择土层 —</option>
          ${layerOptions(t.layerName, t.layerIdx)}</select></td>
        <td><span class="tag c${t.cls || 1}">${CLS_NAME[(t.cls || 1) - 1]}类</span></td>
        <td><select class="cell" data-bind="spt.${i}.band" data-type="int">
          ${['D≤20m', '20&lt;D≤50m', 'D&gt;50m'].map((n, k) => `<option value="${k}" ${num(t.band) === k ? 'selected' : ''}>${n}</option>`).join('')}
        </select></td>
        <td><input class="cell num" type="number" min="0" data-bind="spt.${i}.count" value="${t.count}"></td>
        <td class="num small">${sptPrice(t)}</td>
        <td><button class="del" data-act="delSpt" data-i="${i}">×</button></td></tr>`).join('')}
      </tbody></table>` : `<div class="empty" style="padding:16px">暂无标准贯入试验，点右上「+ 添加」按地层逐层录入（每次默认 ${SPT_DEFAULT_QTY} 次）</div>`}
    </div>
    <div class="stat">
      <div class="it"><span class="k">标贯总次数</span><span class="v">${sptTotal} 次</span></div>
      <div class="it"><span class="k">钻孔总数</span><span class="v">${nHole} 个</span></div>
      <div class="it"><span class="k">1/3 界限</span><span class="v">${r2(sptMin)} 次</span></div>
    </div>
    ${sptShort ? `<div class="body" style="padding-top:0"><div class="hint" style="background:#FFF6E8;border-color:#F5DDB5;color:#8A5A12">
      ⚠ 标贯共 <b>${sptTotal}</b> 次，不大于钻孔总数 <b>${nHole}</b> 个的 1/3（${r2(sptMin)} 次），<b>原位测试可能不满足 1/3 总数要求</b>。</div></div>` : ''}
  </div>

  <div class="card"><header><h3><span class="idx">4</span>圆锥动力触探</h3>
    <span class="desc">重型圆锥动力触探为主，可切换轻型 / 超重型；按触探深度档取费</span>
    <div class="right"><button class="btn tiny" data-act="addDpt">+ 添加</button></div></header>
    <div class="body tight">
      ${S.dpt.length ? `<table><thead><tr><th style="width:104px">类型</th><th>试验土层</th><th style="width:64px">类别</th>
      <th style="width:132px">深度档</th><th style="width:84px">米数</th><th style="width:84px" class="num">单价</th><th style="width:36px"></th></tr></thead>
      <tbody>${S.dpt.map((t, i) => `<tr>
        <td><select class="cell" data-bind="dpt.${i}.kind">
          <option value="dpt_heavy" ${t.kind === 'dpt_heavy' ? 'selected' : ''}>重型</option>
          <option value="dpt_light" ${t.kind === 'dpt_light' ? 'selected' : ''}>轻型</option>
          <option value="dpt_super" ${t.kind === 'dpt_super' ? 'selected' : ''}>超重型</option></select></td>
        <td><select class="cell" data-layer="dpt" data-i="${i}">
          <option value="">— 选择土层 —</option>${layerOptions(t.layerName, t.layerIdx)}</select></td>
        <td><span class="tag c${t.cls || 1}">${CLS_NAME[(t.cls || 1) - 1]}类</span></td>
        <td><select class="cell" data-bind="dpt.${i}.band" data-type="int">
          ${['D≤10m', '10&lt;D≤20m', '20&lt;D≤30m', '30&lt;D≤40m', '40&lt;D≤50m'].map((n, k) => `<option value="${k}" ${num(t.band) === k ? 'selected' : ''}>${n}</option>`).join('')}
        </select></td>
        <td><input class="cell num" type="number" step="0.1" min="0" data-bind="dpt.${i}.meters" value="${t.meters}"></td>
        <td class="num small">${dptPrice(t)}</td>
        <td><button class="del" data-act="delDpt" data-i="${i}">×</button></td></tr>`).join('')}
      </tbody></table>` : `<div class="empty" style="padding:16px">暂无动力触探</div>`}
    </div>
    ${dptMeters > 0 ? `<div class="stat"><div class="it"><span class="k">动探总米数</span><span class="v">${r2(dptMeters)} m</span></div></div>` : ''}
  </div>

  <div class="card"><header><h3><span class="idx">5</span>取样</h3>
    <span class="desc">取土器类型决定取样单价，深度&gt;30m 时按第二档计费；点荷载岩样按「块」计、与取岩芯同价；原状样→常规土工样，扰动样→颗粒分析，岩芯样→单轴抗压，取水→水质简分析</span></header>
    <div class="body">
      <div class="kv" style="grid-template-columns:repeat(4,minmax(0,1fr))">
        <div class="f" style="grid-column:span 2"><label>取土器 / 取原状样</label>
          <select data-bind="sample.undist.device">${(STD.tables.sample.rows).map(r => `<option value="${r.key}" ${S.sample.undist.device === r.key ? 'selected' : ''}>${esc(r.label)}（${r.vals[0]}/${r.vals[1]}）</option>`).join('')}</select></div>
        <div class="f"><label>原状样件数</label><input type="number" min="0" data-bind="sample.undist.count" value="${S.sample.undist.count}"></div>
        <div class="f"><label>取样深度</label>
          <select data-bind="sample.undist.band" data-type="int"><option value="0" ${num(S.sample.undist.band) === 0 ? 'selected' : ''}>≤30m</option>
          <option value="1" ${num(S.sample.undist.band) === 1 ? 'selected' : ''}>&gt;30m</option></select></div>
        <div class="f"><label>扰动样（件）</label><input type="number" min="0" data-bind="sample.disturb" value="${S.sample.disturb}"></div>
        <div class="f"><label>岩芯样（件）</label><input type="number" min="0" data-bind="sample.core" value="${S.sample.core}"></div>
        <div class="f"><label>点荷载岩样（块）</label><input type="number" min="0" data-bind="sample.point" value="${num(S.sample.point)}"></div>
        <div class="f"><label>取水（件）</label><input type="number" min="0" data-bind="sample.water" value="${S.sample.water}"></div>
      </div>
    </div></div>

  <div class="card"><header><h3><span class="idx">6</span>探井 / 探槽 / 平硐</h3>
    <span class="desc">除钻孔外的勘探工作量，按需填加</span>
    <div class="right">
      <select id="digKind" class="mini"><option>探井</option><option>探槽</option><option>平硐</option></select>
      <button class="btn tiny" data-act="addDig">+ 添加</button></div></header>
    ${S.extraDig.length ? `<div class="body tight"><table><thead><tr><th style="width:80px">类型</th><th>规格档</th>
      <th style="width:80px">类别</th><th style="width:100px">工程量</th><th style="width:80px" class="num">单价</th><th style="width:36px"></th></tr></thead>
      <tbody>${S.extraDig.map((d, i) => {
        const tb = STD.tables[{ '探井': 'pit', '探槽': 'trench', '平硐': 'adit' }[d.kind]];
        return `<tr><td>${esc(d.kind)}</td><td><select class="cell" data-bind="extraDig.${i}.row" data-type="int">
          ${tb.rows.map((r, k) => `<option value="${k}" ${num(d.row) === k ? 'selected' : ''}>${esc(r.label)}</option>`).join('')}</select></td>
          <td><select class="cell" data-bind="extraDig.${i}.cls" data-type="int">${CLS_NAME.map((c, k) => `<option value="${k + 1}" ${num(d.cls) === k + 1 ? 'selected' : ''}>${c}</option>`).join('')}</select></td>
          <td><input class="cell num" type="number" data-bind="extraDig.${i}.qty" value="${d.qty}"></td>
          <td class="num small">${tb.rows[Math.min(num(d.row), tb.rows.length - 1)].vals[Math.min(num(d.cls), 6) - 1] || '—'}</td>
          <td><button class="del" data-act="delDig" data-i="${i}">×</button></td></tr>`;
      }).join('')}</tbody></table></div>` : `<div class="body"><div class="small">未添加探井/探槽/平硐</div></div>`}
  </div>

  <div class="card"><header><h3><span class="idx">⚙</span>附加调整系数</h3>
    <span class="desc">按总则1.0.8「相加－个数＋1」合成，不连乘</span>
    <div class="right"><span class="small">综合系数</span>
      <b style="color:var(--pri);font-size:15px" id="kSoil">×${R && R.sections[0] ? (R.sections[0].coef || 1).toFixed(2) : '1.00'}</b></div></header>
  ${coefBox(STD.coef_soil.concat(STD.coef_global), 'coefSoil', '岩土工程勘察附加调整系数（表3.3-5 / 总则1.0.9~1.0.10）')}
  </div>

  <div id="resBox"></div>`;

  const ks = $('#kSoil');
  if (ks && R && R.sections[0]) ks.textContent = '×' + (R.sections[0].coef || 1).toFixed(2);
}

/* 标贯 / 动探的土层下拉：值用「标准地层下标」，这样 ②红黏土、③红黏土 这类同名的两层
   可以分别选取，不会串到同一层上。老项目没有 layerIdx 时按名称回退匹配。 */
function layerIdxOf(name, code) {
  const list = S.layers || [];
  if (code) {
    const i = list.findIndex(L => String(L.lzCode || '') === String(code));
    if (i >= 0) return i;
  }
  const nm = (name == null ? '' : String(name)).trim();
  if (nm) {
    const i = list.findIndex(L => (L.name || '').trim() === nm);
    if (i >= 0) return i;
  }
  return -1;
}
function layerOptions(cur, idx) {
  const list = S.layers || [];
  const sel = (idx != null && idx >= 0 && idx < list.length) ? idx : layerIdxOf(cur, '');
  const opts = list.map((L, i) => `<option value="${i}" ${i === sel ? 'selected' : ''}>${esc((L.code || '') + L.name)}${L.cls ? '（' + CLS_NAME[L.cls - 1] + '）' : ''}</option>`).join('');
  // 引用的地层已被删除 / 改名时，保留一条提示项，避免下拉悄悄变成空值
  const orphan = cur && sel < 0
    ? `<option value="-1" selected>${esc(cur)}（已不在标准地层中）</option>` : '';
  return opts + orphan;
}
function findLayer(name) { return (S.layers || []).find(L => L.name === name); }

/* 标准地层被修改后，同步所有引用该层的记录：
   ① 标贯 / 动探行的土层名称、岩土类别；
   ② 层底深度改动时，若某行的试验深度档仍是旧深度对应的档位（说明是自动带出的、未手工改过），
      则跟着改到新深度对应的档位；
   ③ 理正钻孔分层里的岩土名称与类别（孔内层底属于实测数据，不改）。
   返回被同步的记录条数，用于提示。 */
function bandOfSpt(depth) { return depth <= 20 ? 0 : (depth <= 50 ? 1 : 2); }
function bandOfDpt(depth) { return depth <= 10 ? 0 : depth <= 20 ? 1 : depth <= 30 ? 2 : depth <= 40 ? 3 : 4; }

function syncLayerRefs(idx, field, oldVal) {
  const L = (S.layers || [])[idx];
  if (!L) return 0;
  const nm = (L.name || '').trim();
  const cls = num(L.cls) || 1;
  const old = (oldVal == null ? '' : String(oldVal)).trim();
  // 旧名若仍被另一地层占用，则不做改名，避免两层的记录串在一起
  const renamed = field === 'name' && !!old && !!nm && old !== nm &&
    !(S.layers || []).some((x, i) => i !== idx && (x.name || '').trim() === old);
  const ob = num(oldVal), nb = num(L.bottom);
  let n = 0;

  const fixRows = (list, bandOf) => (list || []).forEach(t => {
    let hit = false;
    // 有下标的按「第几层」精确匹配（同名层不会互相影响）；老数据按名称匹配
    const mine = (t.layerIdx != null) ? (t.layerIdx === idx)
      : (!!nm && (t.layerName || '').trim() === nm);
    if (mine) {
      if (nm && t.layerName !== nm) { t.layerName = nm; hit = true; }
      if (num(t.cls) !== cls) { t.cls = cls; hit = true; }
      if (field === 'bottom') {
        const oband = bandOf(ob), nband = bandOf(nb);
        if (nband !== oband && num(t.band) === oband) { t.band = nband; hit = true; }
      }
      if (t.layerIdx != null) t.layerIdx = idx;
    } else if (renamed && t.layerIdx == null && (t.layerName || '').trim() === old) {
      t.layerName = nm; t.cls = cls; hit = true;
    }
    if (hit) n++;
  });
  fixRows(S.spt, bandOfSpt);
  fixRows(S.dpt, bandOfDpt);

  const lzCode = String(L.lzCode || '');
  (S.holes || []).forEach(h => (h.layers || []).forEach(x => {
    const xn = (x.name || '').trim();
    let hit = false;
    // 理正钻孔分层带层号，按层号精确匹配，同名层不会一起改
    const mine = lzCode ? String(x.code || '') === lzCode
      : (!!nm && xn === nm);
    if (mine) {
      if (nm && x.name !== nm) { x.name = nm; hit = true; }
      if (num(x.cls) !== cls) { x.cls = cls; hit = true; }
    } else if (renamed && !lzCode && xn === old) {
      x.name = nm; x.cls = cls; hit = true;
    }
    if (hit) n++;
  }));
  return n;
}
function sptPrice(t) {
  const tb = STD.tables.spt;
  const cls = Math.min(3, t.cls || 1);
  const row = tb.rows[Math.min(num(t.band), tb.rows.length - 1)];
  const v = row.vals[cls - 1];
  return v == null ? '—' : v + ' 元/次';
}
function dptPrice(t) {
  const tb = STD.tables[t.kind || 'dpt_heavy'];
  const cols = tb.cols;
  const nm = CLS_NAME[(t.cls || 1) - 1];
  const ci = cols.indexOf(nm);
  const row = tb.rows[Math.min(num(t.band), tb.rows.length - 1)];
  if (!row) return '—';
  const v = ci < 0 ? null : row.vals[ci];
  return v == null ? '不适用' : v + ' 元/m';
}

/* ---------------- 理正导入 ----------------
   不再有独立的「选框 + 识别结果」大面板：点「导入理正备份库」按钮选文件后，
   解析结果直接填充到下方人工录入界面（标准地层 / 钻孔 / 标贯 / 动探 / 取样），
   用户可在同一界面继续修改。 */

function applyLzData() {
  if (!LZ || !LZ.ok) return false;
  S.holes = LZ.holes.map(h => ({
    no: h.no, type: h.type || '钻孔', depth: h.depth,
    layers: h.layers.map(L => ({ code: L.code, name: L.name, cls: L.cls, bottom: L.bottom })),
  }));
  // 标准地层：直接采用理正的层序（综合层号 + 亚层号），同名层不合并。
  // 本库就是 ①素填土 ②红黏土 ③红黏土 ④石灰岩 ⑤石灰岩 ⑥充填溶洞 ⑥1溶洞。
  const std = LZ.stdLayers || [];
  if (std.length) {
    S.layers = std.map((x, k) => ({
      code: circleNo(x.no ? x.no - 1 : k) + (num(x.sub) > 0 ? String(x.sub) : ''),
      lzCode: String(x.code || ''),
      name: x.name,
      cls: num(x.cls) || 1,
      bottom: num(x.bottom),
      count: num(x.count) || 0,
    }));
  } else {
    // 旧的 Excel / CSV 导入没有层号信息，退回按名称归并（按平均层底排序）
    const stat = {};
    S.holes.forEach(h => (h.layers || []).forEach(L => {
      if (!L.name) return;
      const it = stat[L.name] = stat[L.name] || { name: L.name, cls: L.cls, sum: 0, n: 0 };
      it.sum += num(L.bottom); it.n++;
    }));
    const seq = Object.keys(stat).map(k => stat[k]).sort((a, b) => (a.sum / a.n) - (b.sum / b.n));
    if (seq.length) {
      S.layers = seq.map((x, k) => ({ code: circleNo(k), lzCode: '', name: x.name, cls: x.cls,
                                      bottom: r2(x.sum / x.n) }));
    }
  }
  const idxOf = (name, code) => {
    const i0 = code ? S.layers.findIndex(L => String(L.lzCode || '') === String(code)) : -1;
    if (i0 >= 0) return i0;
    const i1 = name ? S.layers.findIndex(L => (L.name || '') === name) : -1;
    return i1 >= 0 ? i1 : null;
  };
  S.spt = (LZ.spt || []).map(x => ({
    layerName: x.layerName, layerIdx: idxOf(x.layerName, x.layerCode),
    cls: x.cls, band: x.band, count: x.count,
  }));
  S.dpt = (LZ.dpt || []).map(x => ({
    layerName: x.layerName, layerIdx: idxOf(x.layerName, x.layerCode),
    cls: x.cls, band: x.band, kind: x.kind || 'dpt_heavy', meters: x.meters,
  }));
  // 取样件数（理正取土/岩/水样记录）一并带入
  const smp = LZ.samples;
  if (smp) {
    if (num(smp.undist)) S.sample.undist.count = num(smp.undist);
    if (num(smp.disturb)) S.sample.disturb = num(smp.disturb);
    if (num(smp.core)) S.sample.core = num(smp.core);
    S.sample.point = num(smp.point);
    if (num(smp.water)) S.sample.water = num(smp.water);
  }
  // 取土器默认锤击法厚壁取土器
  if (!S.sample.undist.device) S.sample.undist.device = 'hammer';
  S.mode = 'settle';
  S.qtyMode = 'lz';
  // 物探波速孔选择按新导入的孔号重置（只保留仍存在的孔）
  const nos = S.holes.map(h => h.no);
  S.geo.wave.holeNos = (S.geo.wave.holeNos || []).filter(no => nos.indexOf(no) >= 0);
  LZ.applied = true;
  return true;
}

async function handleLz(file) {
  if (!file) return;
  mask(true, '正在读取 ' + file.name + ' …');
  try {
    const b64 = await readB64(file);
    const nmap = {};
    (STD.name_class ? Object.entries(STD.name_class) : []).forEach(([k, v]) => nmap[k] = v);
    const res = await api.parse_lizheng({ name: file.name, b64, nameClass: nmap });
    res.file = file.name;
    LZ = res;
    if (res.ok) {
      applyLzData();
      mask(false);
      render();
      const s = res.summary || {};
      const smp = num(s.samples);
      toast('已导入 ' + (s.holes || S.holes.length) + ' 个钻孔、' + (s.spt || 0) + ' 条标贯、' + (s.dpt || 0) + ' m 动探'
            + (smp ? '、' + smp + ' 件取样' : ''), 'ok');
      return;
    }
    mask(false);
    render();
    toast(res.error || '解析失败', 'err');
  } catch (e) {
    LZ = { ok: false, error: e.message, file: file.name };
    mask(false);
    render();
    toast(e.message, 'err');
  }
}

function readB64(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
}

/* ------------------------------------------------------------------ 模块3 室内试验 */
/* 只有带 link 的项目才与「工程勘察 · 取样」联动，其余项目一律默认 6 个 */
const LAB_DEFAULT_QTY = 6;
const LAB_PRESET = [
  { id: 'routine', name: '常规土工样', spec: '含水率+密度+比重+液限+塑限+压缩+直剪', unit: '件', price: 169, link: 'undist' },
  { id: 'swell', name: '胀缩试验', spec: '自由膨胀率+膨胀率+膨胀力+收缩', unit: '件', price: 133 },
  { id: 'grain', name: '颗粒分析', spec: '筛析法（碎石类土）', unit: '件', price: 70, link: 'disturb' },
  { id: 'tri_uu', name: '三轴 UU', spec: '不固结不排水', unit: '件', price: 413 },
  { id: 'tri_cu', name: '三轴 CU', spec: '固结不排水', unit: '件', price: 775 },
  { id: 'tri_cd', name: '三轴 CD', spec: '固结排水', unit: '件', price: 1240 },
  { id: 'salt', name: '易溶盐分析', spec: '重量法', unit: '项', price: 132 },
  { id: 'point', name: '点荷载强度', spec: '每组3块', unit: '块', price: 26, link: 'point' },
  { id: 'ucs_nat', name: '天然单轴抗压', spec: '每组3块', unit: '组', price: 47, link: 'core' },
  { id: 'ucs_sat', name: '饱和单轴抗压', spec: '每组3块', unit: '组', price: 70, link: 'core' },
  { id: 'water_q', name: '水质简分析', spec: '', unit: '件', price: 220, link: 'water' },
];

/* 取样数量（用于室内试验默认件数的联动） */
function sampleQty(kind) {
  const s = S.sample || {};
  if (kind === 'undist') return num((s.undist || {}).count);
  if (kind === 'disturb') return num(s.disturb);
  if (kind === 'core') return num(s.core);
  if (kind === 'point') return num(s.point);
  if (kind === 'water') return num(s.water);
  return 0;
}

const SAMPLE_LABEL = { undist: '原状土样', disturb: '扰动土样', core: '岩样', point: '点荷载岩样', water: '水样' };

/* 某试验项目的件数联动来源（按名称匹配预设） */
function labLinkOf(name) {
  return LAB_PRESET.find(p => p.name === name && p.link) || null;
}
function labLinkHint(it) {
  const name = typeof it === 'string' ? it : (it || {}).name;
  const p = labLinkOf(name);
  if (!p) return '默认 ' + LAB_DEFAULT_QTY + '，可手工修改';
  if (it && it.auto === false) {
    return '已解除联动（手工指定），当前取样「' + SAMPLE_LABEL[p.link] + '」为 ' + r2(sampleQty(p.link)) +
      '；点「联动」可恢复';
  }
  return '自动联动「' + SAMPLE_LABEL[p.link] + '」取样数量：当前 ' + r2(sampleQty(p.link));
}

/* 取样数量变化后，把仍处于联动状态（auto !== false）的试验项目件数同步过来 */
function syncLabAuto(silent) {
  let n = 0;
  (S.lab.items || []).forEach(it => {
    if (it.auto === false) return;
    const p = labLinkOf(it.name);
    if (!p) return;
    const q = sampleQty(p.link);
    if (q > 0 && num(it.qty) !== q) { it.qty = q; n++; }
  });
  return n;
}

/* 打开旧项目时，历史条目没有 auto 标记：一律视为手工指定，避免被当前取样数量覆盖 */
function normalizeLabAuto() {
  (S.lab.items || []).forEach(it => { if (it.auto === undefined) it.auto = false; });
}

function renderLab(box) {
  const items = S.lab.items || [];
  const tot = items.reduce((a, i) => a + num(i.qty) * num(i.price), 0);
  box.innerHTML = `
  <div class="card"><header><h3><span class="idx">1</span>快捷添加</h3>
    <span class="desc">常规土工样／颗粒分析／水质简分析／单轴抗压／点荷载强度按取样数量带出并保持联动，其余默认 ${LAB_DEFAULT_QTY} 件</span></header>
    <div class="body">
      <div class="row" style="flex-wrap:wrap;gap:6px">
      ${LAB_PRESET.map(p => {
        const n = p.link ? sampleQty(p.link) : LAB_DEFAULT_QTY;
        const tip = p.link ? '件数默认取' + SAMPLE_LABEL[p.link] + ' ' + r2(n) : '默认 ' + LAB_DEFAULT_QTY + ' 件';
        return `<button class="btn tiny" data-preset="${p.id}" title="${tip}">${esc(p.name)}<span class="small" style="margin-left:4px">${p.price}</span>${p.link ? `<span class="tag">${r2(n)}</span>` : ''}</button>`;
      }).join('')}
      </div>
    </div></div>

  <div class="card"><header><h3><span class="idx">2</span>室内试验项目</h3>
    <span class="desc">技术工作费比例 10%（表8.1）</span>
    <div class="right"><button class="btn tiny" data-act="addLabRow">+ 自定义项目</button></div></header>
    <div class="body tight">
      ${items.length ? `<table><thead><tr><th>项目</th><th style="width:180px">规格 / 说明</th><th style="width:68px">单位</th>
      <th style="width:92px" class="num">单价(元)</th><th style="width:112px">数量</th><th style="width:104px" class="num">金额(元)</th><th style="width:36px"></th></tr></thead>
      <tbody>${items.map((it, i) => `<tr>
        <td><input class="cell" data-bind="lab.items.${i}.name" value="${esc(it.name)}"></td>
        <td><input class="cell" data-bind="lab.items.${i}.spec" value="${esc(it.spec || '')}"></td>
        <td><input class="cell" data-bind="lab.items.${i}.unit" value="${esc(it.unit || '件')}"></td>
        <td><input class="cell num" type="number" step="0.01" data-bind="lab.items.${i}.price" value="${it.price}"></td>
        <td><div class="qtywrap"><input class="cell num" type="number" min="0" data-bind="lab.items.${i}.qty" data-i="${i}" value="${it.qty}" title="${labLinkHint(it)}">${labLinkOf(it.name) ? `<button class="lk ${it.auto === false ? 'off' : ''}" data-act="toggleLabLink" data-i="${i}" title="${it.auto === false ? '点击恢复与取样的自动联动' : '联动中：件数跟随取样数量，点击改为手工指定'}">联</button>` : ''}</div></td>
        <td class="num" style="font-weight:600">${money0(num(it.qty) * num(it.price))}</td>
        <td><button class="del" data-act="delLab" data-i="${i}">×</button></td></tr>`).join('')}
      </tbody></table>` : `<div class="empty" style="padding:20px">尚未添加试验项目</div>`}
    </div>
    <div class="sumline"><span class="small">室内试验实物工作费合计</span><b>${money(tot)}</b></div>
    <div class="body" style="border-top:1px solid var(--line-2)">
      <label class="chk ${S.labInSite ? 'on' : ''}" style="width:fit-content">
        <input type="checkbox" data-bind="labInSite" data-type="bool" ${S.labInSite ? 'checked' : ''}>
        <span>试验移至现场进行（附加调整系数 1.3，表8.5）</span><span class="v">×1.30</span></label>
    </div>
  </div>
  <div id="resBox"></div>
  `;
}

/* ------------------------------------------------------------------ 模块3 工程物探 */
/* 表7.2-1 钻孔波速测试的深度分档：返回 {label, price}，用于界面显示「费用落在哪一档」 */
function waveBandOf(d, method) {
  const T = (STD.tables || {}).wave;
  if (!T || !T.rows || !(d > 0)) return { label: '—', price: 0 };
  const m = method === 'cross' ? 1 : 0;
  for (let i = 0; i < T.rows.length; i++) {
    const r = T.rows[i];
    if (r.rng && d > r.rng[0] && d <= r.rng[1]) {
      const v = r.vals[m];
      return { label: r.label, price: v == null ? 0 : v };
    }
  }
  const tail = T.tail;
  if (tail) {
    const last = T.rows[T.rows.length - 1].vals[m];
    if (last == null) return { label: '超出表范围', price: 0 };
    const n = Math.max(1, Math.ceil((d - tail.start) / tail.step));
    const f = Math.pow(tail.factor, n);
    const lo = tail.start + (n - 1) * tail.step, hi = tail.start + n * tail.step;
    return { label: lo + '<D≤' + hi + 'm（×' + f.toFixed(2) + '）', price: last * f };
  }
  return { label: '—', price: 0 };
}

function renderGeo(box) {
  const g = S.geo, w = g.wave;
  const extra = g.extra || [];
  const lz = S.qtyMode === 'lz' && (S.holes || []).length > 0;
  const method = w.method === 'cross' ? 'cross' : 'single';
  // 按当前计价模式取孔：导入模式看实测孔，人工录入看孔型表
  const nHole = lz ? S.holes.length : S.holeTypes.reduce((a, h) => a + num(h.count), 0);
  const maxD = lz
    ? Math.max(0, ...S.holes.map(h => num(h.depth)))
    : Math.max(0, ...S.holeTypes.map(h => num(h.depth)));
  const picked = (w.holeNos || []).filter(no => (S.holes || []).some(h => h.no === no));
  const pickRows = picked.map(no => (S.holes || []).find(h => h.no === no)).filter(Boolean);
  const pickedM = r2(pickRows.reduce((a, h) => a + num(h.depth), 0));
  const waveLen = lz ? pickedM : (num(w.testLen) || maxD);

  // 按各孔孔深分档汇总：深度档 / 孔数 / 米数 / 单价 / 金额
  const agg = {};
  pickRows.forEach(h => {
    const d = num(h.depth);
    const b = waveBandOf(d, method);
    const k = b.label + '|' + b.price;
    const it = agg[k] = agg[k] || { label: b.label, price: b.price, holes: 0, meters: 0, amount: 0, nos: [] };
    it.holes += 1;
    it.meters = r2(it.meters + d);
    it.amount = r2(it.amount + b.price * d);
    it.nos.push(h.no);
  });
  const bandList = Object.keys(agg).map(k => agg[k]).sort((a, b) => a.price - b.price);
  const bandAmt = r2(bandList.reduce((a, b) => a + b.amount, 0));
  const manualBand = waveBandOf(maxD, method);

  box.innerHTML = `
  <div class="card"><header><h3><span class="idx">1</span>钻孔波速测试</h3>
    <span class="desc">表7.2-1 序号17；按各孔测试深度分档取基价，不足 2 个组日按 2 个组日</span>
    ${lz ? `<div class="right"><span class="small">已选波速孔</span>
      <b style="color:var(--pri)">${picked.length} 孔 / ${r2(pickedM)} m</b>
      <button class="btn tiny" data-act="waveAll">全选</button>
      <button class="btn tiny ghost" data-act="waveNone">清空</button></div>` : ''}</header>
    <div class="body">
      ${lz ? `<div class="kv" style="grid-template-columns:repeat(2,1fr)">
        <div class="f"><label>测试方法</label><select data-bind="geo.wave.method">
          <option value="single" ${w.method === 'single' ? 'selected' : ''}>单孔法</option>
          <option value="cross" ${w.method === 'cross' ? 'selected' : ''}>跨孔法</option></select></div>
        <div class="f"><label>计价长度（米，按所选孔孔深合计）</label>
          <div style="padding:7px 0;font-weight:600;color:var(--pri)">${r2(pickedM)} m</div></div>
      </div>
      <div class="hint info mt10">在下方勾选实际做过波速测试的钻孔，米数按所选钻孔的孔深合计（孔深取理正实测值）；
        单价按<b>各孔自身孔深</b>落在表7.2-1 的哪一档计取，分档结果见下表。</div>`
      : `<div class="kv" style="grid-template-columns:repeat(3,1fr)">
        <div class="f"><label>测试孔数（个）</label><input type="number" min="0" data-bind="geo.wave.holes" value="${w.holes}"></div>
        <div class="f"><label>每孔测试长度（m）</label><input type="number" step="0.5" min="0" data-bind="geo.wave.testLen" value="${w.testLen}" placeholder="空白则按孔深 ${maxD} m"></div>
        <div class="f"><label>测试方法</label><select data-bind="geo.wave.method">
          <option value="single" ${w.method === 'single' ? 'selected' : ''}>单孔法</option>
          <option value="cross" ${w.method === 'cross' ? 'selected' : ''}>跨孔法</option></select></div>
      </div>
      <div class="hint info mt10">孔深自动取本项目<b>最深孔 ${r2(maxD)} m</b>（共 ${nHole} 个钻孔），落在
        <b>${esc(manualBand.label)}</b> 档，单价 <b>${r2(manualBand.price)} 元/m</b>；本次计价长度 ${r2(waveLen)} m，
        金额约 ${(manualBand.price * waveLen).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 元。</div>`}
    </div>
    ${lz && pickRows.length ? `
    <div class="body tight" style="border-top:1px solid var(--line-2)">
      <div class="small" style="padding:6px 6px 2px">已选波速孔 ${pickRows.length} 个：
        ${pickRows.map(h => `<span class="tag">${esc(h.no)}·${r2(num(h.depth))}m·${esc(waveBandOf(num(h.depth), method).label)}档</span>`).join(' ')}</div>
      <table><thead><tr><th style="width:150px">深度档（表7.2-1）</th><th style="width:70px" class="num">孔数</th>
        <th style="width:100px" class="num">测试米数</th><th style="width:110px" class="num">单价(元/m)</th>
        <th style="width:120px" class="num">金额(元)</th><th>孔号</th></tr></thead>
      <tbody>${bandList.map(b => `<tr class="hl">
        <td class="small">${esc(b.label)}</td><td class="num">${b.holes}</td>
        <td class="num">${r2(b.meters)}</td><td class="num">${r2(b.price)}</td>
        <td class="num"><b>${b.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</b></td>
        <td class="small" style="white-space:normal">${b.nos.map(esc).join('、')}</td></tr>`).join('')}
        <tr><td><b>合计</b></td><td class="num"><b>${pickRows.length}</b></td>
          <td class="num"><b>${r2(pickedM)}</b></td><td class="num">—</td>
          <td class="num"><b style="color:#C0392B">${bandAmt.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</b></td>
          <td class="small">${esc(method === 'cross' ? '跨孔法' : '单孔法')}${bandAmt > 0 && bandAmt < 2000 ? '，不足 2 个组日按 2000 元计' : ''}</td></tr>
      </tbody></table>
    </div>` : ''}
    ${lz ? `<div class="body tight" style="border-top:1px solid var(--line-2);max-height:260px;overflow:auto">
      <div class="small" style="padding:6px 6px 2px">勾选做过波速测试的钻孔（孔深取理正实测值，不可改）</div>
      <table><thead><tr><th style="width:58px" class="ctr">波速孔</th><th style="width:110px">孔号</th>
        <th style="width:88px" class="num">孔深(m)</th><th style="width:150px">落在档位</th>
        <th style="width:92px" class="num">单价(元/m)</th><th>孔型</th></tr></thead>
      <tbody>${S.holes.map(h => {
        const on = picked.includes(h.no);
        const b = waveBandOf(num(h.depth), method);
        return `<tr class="${on ? 'hl' : ''}">
        <td class="ctr"><input type="checkbox" data-wave="${esc(h.no)}" ${on ? 'checked' : ''}></td>
        <td class="small">${esc(h.no)}</td>
        <td class="num">${num(h.depth).toFixed(2)}</td>
        <td class="small">${esc(b.label)}</td>
        <td class="num">${on || b.price ? r2(b.price) : '—'}</td>
        <td class="small">${esc(h.type || '钻孔')}</td></tr>`;
      }).join('')}</tbody></table>
    </div>` : ''}
  </div>

  <div class="card"><header><h3><span class="idx">2</span>电法勘探</h3>
    <span class="desc">表7.2-1 序号4，按电极距／测点距两种方式计价；高密度×0.8、激发极化×2.4、充电法×1.2</span>
    <div class="right"><button class="btn tiny" data-act="addElec">+ 添加</button></div></header>
    <div class="body tight">
      ${(g.elec || []).length ? `<table class="elecTb"><thead><tr>
      <th style="width:96px">计价方式</th><th style="width:176px">装置 / 项目</th><th style="width:110px">距离档</th>
      <th style="width:64px">点数</th><th style="width:60px" class="num">基价</th>
      <th style="width:48px" class="ctr">高密度</th><th style="width:44px" class="ctr">激电</th><th style="width:44px" class="ctr">充电</th>
      <th style="width:76px" class="num">单价</th><th style="width:32px"></th></tr></thead>
      <tbody>${g.elec.map((e, i) => {
        const space = e.space === 'point' ? 'point' : 'elec';
        const sp = (STD.elec_spacing || {})[space] || { label: '距离', options: [] };
        const T = (STD.tables[sp.table] || STD.tables.elec);
        const ri = Math.min(num(e.row), T.rows.length - 1);
        const ci = Math.min(num(e.method), T.cols.length - 1);
        const base = (T.rows[ri] || { vals: [] }).vals[ci];
        return `<tr>
          <td><select class="cell" data-bind="geo.elec.${i}.space" data-reset="elec">
            <option value="elec" ${space === 'elec' ? 'selected' : ''}>按电极距</option>
            <option value="point" ${space === 'point' ? 'selected' : ''}>按测点距</option></select></td>
          <td><select class="cell" data-bind="geo.elec.${i}.method" data-type="int">
          ${T.cols.map((c, k) => `<option value="${k}" ${ci === k ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></td>
          <td><select class="cell" data-bind="geo.elec.${i}.row" data-type="int">
          ${T.rows.map((r, k) => `<option value="${k}" ${ri === k ? 'selected' : ''}>${esc(r.label)}</option>`).join('')}</select></td>
          <td><input class="cell num" type="number" min="0" data-bind="geo.elec.${i}.qty" value="${e.qty}"></td>
          <td class="num small">${base == null ? '—' : base}</td>
          <td class="ctr"><input type="checkbox" data-bind="geo.elec.${i}.dense" data-type="bool" ${e.dense ? 'checked' : ''}></td>
          <td class="ctr"><input type="checkbox" data-bind="geo.elec.${i}.ip" data-type="bool" ${e.ip ? 'checked' : ''}></td>
          <td class="ctr"><input type="checkbox" data-bind="geo.elec.${i}.charge" data-type="bool" ${e.charge ? 'checked' : ''}></td>
          <td class="num">${base == null ? '—' : r2(base * (e.dense ? .8 : 1) * (e.ip ? 2.4 : 1) * (e.charge ? 1.2 : 1))}</td>
          <td><button class="del" data-act="delElec" data-i="${i}">×</button></td></tr>`;
      }).join('')}</tbody></table>` : `<div class="empty" style="padding:18px">暂无电法勘探</div>`}
    </div>
    <div class="body" style="border-top:1px solid var(--line-2)"><div class="hint info" style="margin:0">
      <b>按电极距</b>：装置分电测深／中间梯度／四极／联剖／偶极，电极距 L≤100 ~ L&gt;800 共 6 档（其中 600&lt;L≤800、L&gt;800 仅电测深与中间梯度有基价）。<br>
      <b>按测点距</b>：分「自电、梯度单独测量」与「自电、梯度同时测量」两列，测点距 L≤5 / 5&lt;L≤10 / 10&lt;L≤20 / 20&lt;L≤30 共 4 档。</div></div></div>

  <div class="card"><header><h3><span class="idx">3</span>其他物探项目</h3>
    <span class="desc">面波、地质雷达、瞬变电磁、测井、管线探测等</span>
    <div class="right">
      <select id="geoPick" class="mini" style="max-width:280px">${geoOptions()}</select>
      <button class="btn tiny" data-act="addGeoExtra">+ 添加</button></div></header>
    ${extra.length ? `<div class="body tight"><table><thead><tr><th>项目</th><th style="width:150px">单位</th>
      <th style="width:96px" class="num">单价</th><th style="width:82px">数量</th><th style="width:100px" class="num">金额</th><th style="width:36px"></th></tr></thead>
      <tbody>${extra.map((e, i) => `<tr>
        <td><input class="cell" data-bind="geo.extra.${i}.name" value="${esc(e.name)}"></td>
        <td><input class="cell" data-bind="geo.extra.${i}.unit" value="${esc(e.unit)}"></td>
        <td><input class="cell num" type="number" data-bind="geo.extra.${i}.price" value="${e.price}"></td>
        <td><input class="cell num" type="number" min="0" data-bind="geo.extra.${i}.qty" value="${e.qty}"></td>
        <td class="num" style="font-weight:600">${money0(num(e.qty) * num(e.price))}</td>
        <td><button class="del" data-act="delGeoExtra" data-i="${i}">×</button></td></tr>`).join('')}
      </tbody></table></div>` : `<div class="body"><div class="small">未添加其他物探项目</div></div>`}
  </div>

  <div class="card"><header><h3><span class="idx">⚙</span>物探附加调整系数</h3></header>
  ${coefBox(STD.coef_geo, 'coefGeo', '表7.2-1 注：除管线探测外，地形、障碍、干扰条件复杂时 1.2~3.0')}</div>

  <div id="resBox"></div>
  `;
}

function geoOptions() {
  const out = [];
  const push = (tid, key, name, unit, price) => out.push({ tid, key, name, unit, price });
  STD.tables.rayleigh.rows.forEach(r => push('rayleigh', r.key, '面波勘探 ' + r.label, '点', r.vals[0]));
  const lr = STD.tables.radar.rows;
  push('radar', 'p', '地质雷达 点测', '点', lr[0].vals[0]);
  push('radar', 'c', '地质雷达 连续', 'km', lr[1].vals[0]);
  STD.tables.tem.rows.forEach(r => push('tem', r.key, '瞬变电磁 ' + r.label, '点', r.vals[0]));
  STD.tables.logging.rows.forEach(r => push('logging', r.key, '测井 ' + r.label, 'm', r.vals[0]));
  return out.map((o, i) => `<option value="${i}" data-tid="${o.tid}" data-name="${esc(o.name)}" data-unit="${esc(o.unit)}" data-price="${o.price}">${esc(o.name)}（${o.price} 元/${o.unit}）</option>`).join('');
}

/* ------------------------------------------------------------------ 模块5 其他费用 */
function renderOther(box) {
  const o = S.other, custom = o.custom || [];
  const rows = STD.other_items.map(it => {
    const q = num(o[it.id]);
    return `<tr><td>${esc(it.name)}</td><td class="ctr"><span class="small">${it.unit}</span></td>
      <td><input class="cell num" type="number" min="0" data-bind="other.${it.id}" value="${q}"></td>
      <td><input class="cell num" type="number" data-bind="other.${it.id}_price" value="${num(o[it.id + '_price']) || it.price}"></td>
      <td class="num" style="font-weight:600">${money0(q * (num(o[it.id + '_price']) || it.price))}</td></tr>`;
  }).join('');
  box.innerHTML = `
  <div class="card"><header><h3><span class="idx">1</span>其他费用</h3>
    <span class="desc">总则1.0.13 组日 / 台班基价；报告费为增加份数工本费</span></header>
    <div class="body tight">
      <table><thead><tr><th>项目</th><th style="width:70px" class="ctr">单位</th><th style="width:96px">数量</th>
      <th style="width:104px" class="num">单价(元)</th><th style="width:110px" class="num">金额(元)</th></tr></thead>
      <tbody>${rows}</tbody></table>
    </div>
  </div>

  <div class="card"><header><h3><span class="idx">2</span>预留增项</h3>
    <span class="desc">标准中未列明、需与发包人协商确定的费用</span>
    <div class="right"><button class="btn tiny" data-act="addCustom">+ 添加增项</button></div></header>
    ${custom.length ? `<div class="body tight"><table><thead><tr><th>名称</th><th style="width:80px">单位</th>
      <th style="width:90px">数量</th><th style="width:110px" class="num">单价(元)</th><th style="width:110px" class="num">金额</th><th style="width:36px"></th></tr></thead>
      <tbody>${custom.map((c, i) => `<tr>
        <td><input class="cell" data-bind="other.custom.${i}.name" value="${esc(c.name)}"></td>
        <td><input class="cell" data-bind="other.custom.${i}.unit" value="${esc(c.unit)}"></td>
        <td><input class="cell num" type="number" min="0" data-bind="other.custom.${i}.qty" value="${c.qty}"></td>
        <td><input class="cell num" type="number" data-bind="other.custom.${i}.price" value="${c.price}"></td>
        <td class="num" style="font-weight:600">${money0(num(c.qty) * num(c.price))}</td>
        <td><button class="del" data-act="delCustom" data-i="${i}">×</button></td></tr>`).join('')}
      </tbody></table></div>` : `<div class="body"><div class="small">暂无增项</div></div>`}
  </div>
  <div id="resBox"></div>
  `;
}

/* ------------------------------------------------------------------ 结果区 */
function lineTable(lines, unitLabel) {
  return `<table><thead><tr><th>项目</th><th>规格</th><th style="width:56px" class="ctr">单位</th>
    <th style="width:80px" class="num">单价</th><th style="width:80px" class="num">工程量</th>
    <th style="width:88px" class="num">小计</th><th style="width:56px" class="ctr">系数</th>
    <th style="width:96px" class="num">合计</th></tr></thead><tbody>
    ${lines.map(l => `<tr><td>${esc(l.item)}${l.sub ? `<span class="tag c${CLS_NAME.indexOf(l.sub) + 1 || 1}" style="margin-left:5px">${esc(l.sub)}</span>` : ''}</td>
      <td class="small">${esc(l.spec)}</td><td class="ctr small">${esc(l.unit)}</td>
      <td class="num">${money0(l.price)}</td><td class="num">${money0(l.qty)}</td>
      <td class="num">${money0(l.amount)}</td><td class="ctr small">${(l.coef || 1).toFixed(2)}</td>
      <td class="num" style="font-weight:600">${money0(l.total)}</td></tr>`).join('')}
  </tbody></table>`;
}

function paintResults() {
  const box = $('#resBox'); if (!box || !R) return;
  const idx = { soil: 0, lab: 1, geo: 2, other: 3 }[MOD];
  const sec = R.sections[idx];
  if (!sec) { box.innerHTML = ''; return; }
  const groups = sec.groups.map(g => `
    <div class="res-group"><div class="gt">${esc(g.title)}<span class="r">${money0(g.lines.reduce((a, l) => a + l.total, 0))}</span></div>
      ${lineTable(g.lines)}</div>`).join('');
  const rateTxt = sec.techRate ? `技术工作费 = 实物工作费 × ${(sec.techRate * 100).toFixed(0)}%` : '本分部不计技术工作费';
  box.innerHTML = `
  <div class="card"><header><h3><span class="idx">∑</span>${esc(sec.title)} 计算明细</h3>
    <div class="right"><span class="small">${sec.groups.reduce((a, g) => a + g.lines.length, 0)} 条明细</span></div></header>
    ${groups || '<div class="empty">暂无工作量</div>'}
    <div class="formula">${rateTxt}；勘察实物工作收费 = 收费基价 × 实物工作量 × 附加调整系数</div>
    <div class="sumline"><span>实物工作费</span><b>${money(sec.real)}</b></div>
    ${sec.techRate ? `<div class="sumline"><span>技术工作费（×${(sec.techRate).toFixed(2)}）</span><b>${money(sec.tech)}</b></div>` : ''}
    <div class="sumline" style="background:#F4F8FF"><span><b>分部小计</b></span><b style="color:var(--pri);font-size:15px">${money(sec.amount)}</b></div>
    ${R.warnings && R.warnings.length ? `<div class="body" style="border-top:1px solid var(--line-2)">${R.warnings.map(w => `<div class="hint" style="margin-bottom:6px">${esc(w)}</div>`).join('')}</div>` : ''}
  </div>`;
}

/* ------------------------------------------------------------------ 右侧对照 */
function refScope() {
  return {
    soil: [
      { t: '岩土类别', title: '岩土类别划分（表3.3-1）', render: renderClassTable },
      { t: '钻孔', title: '钻孔收费基价（表3.3-2）', render: () => renderStdTable('drill') },
      { t: '取土器', title: '取土、水、石试样（表3.3-3）取土器部分', render: () => renderStdTable('sample') },
      { t: '其他取样', title: '扰动 / 岩芯 / 点荷载 / 取水（表3.3-3）', render: () => renderStdTable('sample_extra') },
      { t: '原位测试', title: '原位测试收费基价（表3.3-4）', render: () => renderStdTable('spt') },
      { t: '动探', title: '动力触探（表3.3-4）', render: () => renderStdTable('dpt_heavy') },
      { t: '调整系数', title: '附加调整系数（表3.3-5）', render: renderCoefTable },
      { t: '技术费', title: '技术工作费收费比例（表3.1-1）', render: renderTechTable },
    ],
    lab: [
      { t: '土工试验', title: '土工试验收费基价（表8.2-1）', render: () => renderStdTable('lab_soil') },
      { t: '水质分析', title: '水质分析（表8.3-1）', render: () => renderStdTable('lab_water') },
      { t: '岩石试验', title: '岩石物理力学试验（表8.4-2）', render: () => renderStdTable('lab_rock') },
      { t: '化学分析', title: '岩石化学分析（表8.4-3 节选）', render: () => renderStdTable('lab_chem') },
      { t: '技术费', title: '室内试验技术工作费', render: renderLabTech },
    ],
    geo: [
      { t: '钻孔波速', title: '钻孔波速测试（表7.2-1 序号17）', render: () => renderStdTable('wave') },
      { t: '电法·电极距', title: '电法勘探 · 按电极距 L（表7.2-1 序号4）', render: () => renderStdTable('elec') },
      { t: '电法·测点距', title: '电法勘探 · 按测点距 L（表7.2-1 序号4 续表）', render: () => renderStdTable('elec_point') },
      { t: '其他物探', title: '面波 / 雷达 / 瞬变电磁', render: renderGeoMisc },
      { t: '测井', title: '测井（表7.2-1 序号16）', render: () => renderStdTable('logging') },
      { t: '技术费', title: '工程物探技术工作费', render: renderGeoTech },
    ],
    other: [
      { t: '组日台班', title: '组日 / 台班基价（总则1.0.13）', render: renderOtherStd },
      { t: '文件份数', title: '勘察文件份数与计费公式（总则1.0.4 / 1.0.14）', render: renderCopies },
    ],
  }[MOD];
}

function renderRef() {
  const tabs = refScope();
  if (REF.scope !== MOD) { REF.scope = MOD; REF.active = 0; }
  if (REF.active >= tabs.length) REF.active = 0;
  const titles = { soil: '工程勘察 · 收费标准对照', lab: '室内试验 · 收费标准对照', geo: '工程物探 · 收费标准对照', other: '其他费用 · 收费标准对照' };
  $('#refTitle').textContent = titles[MOD];
  $('#refTabs').innerHTML = tabs.map((t, i) => `<button class="${i === REF.active ? 'on' : ''}" data-reftab="${i}">${t.t}</button>`).join('');
  $$('[data-reftab]').forEach(b => b.onclick = () => { REF.active = +b.dataset.reftab; renderRef(); });
  const cur = tabs[REF.active];
  $('#refSub').textContent = cur.title;
  $('#refBody').innerHTML = cur.render();
}

function renderStdTable(tid) {
  const t = STD.tables[tid];
  if (!t) return '';
  return `<div class="cap">${esc(t.title)}<span class="unit">${esc(t.unit)}</span></div>
  <table><thead><tr><th style="width:36%">${['sample', 'sample_extra', 'lab_soil', 'lab_rock'].indexOf(tid) >= 0 ? '项目' : '深度 / 项目'}</th>
  ${t.cols.map(c => `<th class="num">${esc(c)}</th>`).join('')}</tr></thead>
  <tbody>${t.rows.map(r => `<tr><td>${esc(r.label)}</td>${r.vals.map(v => `<td class="num">${v == null ? '—' : (typeof v === 'number' ? v.toLocaleString() : esc(v))}</td>`).join('')}</tr>`).join('')}
  </tbody></table>
  ${t.note ? `<div class="note">${esc(t.note)}</div>` : ''}`;
}

function renderClassTable() {
  return `<div class="cap">岩土类别划分（表3.3-1）</div>
  <table><thead><tr><th style="width:44px">类别</th><th>适用范围</th></tr></thead>
  <tbody>${STD.classes.map(c => `<tr><td class="ctr"><span class="tag c${c.id}">${c.name}</span></td>
    <td class="small">${esc(c.desc)}</td></tr>`).join('')}</tbody></table>
  <div class="note">注：岩土的分类和鉴定见国标《岩土工程勘察规范》。同一土层应按其状态（稠度、密实度）与风化程度归入相应类别。</div>`;
}

function renderTechTable() {
  const r = STD.tech_rate['岩土工程勘察'];
  return `<div class="cap">岩土工程勘察技术工作费收费比例（表3.1-1）</div>
  <table><thead><tr><th>勘察等级</th><th class="num">技术工作费比例</th><th class="num">系数</th></tr></thead>
  <tbody>${Object.entries(r).map(([k, v]) => `<tr class="${S.grade === k ? 'hl' : ''}"><td>${k}</td>
    <td class="num">${(v * 100).toFixed(0)}%</td><td class="num">×${v.toFixed(2)}</td></tr>`).join('')}</tbody></table>
  <div class="note">技术工作费 = 实物工作收费 × 技术工作费收费比例。<br>利用已有勘察资料提出勘察报告的只收取技术工作费。</div>`;
}

function renderLabTech() {
  return `<div class="cap">室内试验技术工作费</div>
  <table><thead><tr><th>项目</th><th class="num">比例</th></tr></thead>
  <tbody><tr class="hl"><td>室内试验</td><td class="num">10%</td></tr></tbody></table>
  <div class="note">表8.1：室内试验技术工作费收费比例为 10%。<br>表8.5：土工、水质、岩石室内试验移至现场进行，附加调整系数 1.3。</div>`;
}
function renderGeoTech() {
  return `<div class="cap">工程物探技术工作费</div>
  <table><thead><tr><th>项目</th><th class="num">比例</th></tr></thead>
  <tbody><tr class="hl"><td>工程物探</td><td class="num">22%</td></tr></tbody></table>
  <div class="note">表7.1：工程物探技术工作费收费比例为 22%。<br>物探工作不足一个组日按一个组日计；钻孔波速不足2个组日按2个组日计。</div>`;
}

function renderCoefTable() {
  return `<div class="cap">岩土工程勘探与原位测试附加调整系数（表3.3-5）</div>
  <table><thead><tr><th>项目</th><th class="num">系数</th></tr></thead>
  <tbody>${STD.coef_soil.map(c => `<tr class="${(S.coefSoil || []).includes(c.id) ? 'hl' : ''}"><td class="small">${esc(c.name)}</td>
    <td class="num">${c.v.toFixed(2)}</td></tr>`).join('')}</tbody></table>
  <div class="note">总则1.0.8：两个以上附加调整系数不能连乘，应相加后减去系数个数、再加定值1。<br>
  例：跟管钻进1.5 + 夜间1.2 → 1.5+1.2-2+1 = 1.70。</div>`;
}

function renderGeoMisc() {
  const ids = ['rayleigh', 'radar', 'tem'];
  return ids.map(id => {
    const t = STD.tables[id];
    return `<div class="cap" style="margin-top:8px">${esc(t.title)}<span class="unit">${esc(t.unit)}</span></div>
    <table><thead><tr><th>项目</th>${t.cols.map(c => `<th class="num">${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${t.rows.map(r => `<tr><td class="small">${esc(r.label)}</td>${r.vals.map(v => `<td class="num">${v == null ? '—' : v.toLocaleString()}</td>`).join('')}</tr>`).join('')}</tbody></table>
    ${t.note ? `<div class="note">${esc(t.note)}</div>` : ''}`;
  }).join('');
}

function renderOtherStd() {
  return `<div class="cap">总则 1.0.13 工程勘察组日、台班收费基价</div>
  <table><thead><tr><th>项目</th><th class="num">基价</th></tr></thead>
  <tbody>
    <tr><td>工程测量、岩土工程验槽、检测监测、工程物探</td><td class="num">1000 元/组日</td></tr>
    <tr class="hl"><td>岩土工程勘察</td><td class="num">1360 元/台班</td></tr>
    <tr><td>水文地质勘察</td><td class="num">1680 元/台班</td></tr>
  </tbody></table>
  <div class="note">1.0.11 建设项目由两个以上勘察人承担，对整体性负责的一方可在合同环节按基准价 5% 另计主体勘察协调费（本软件不单列）。<br>
  1.0.12 许可办理、障碍物拆除、修路接电、水上作业船排、大型机具搬运、青苗赔偿等由发包人另行支付。</div>`;
}
function renderCopies() {
  return `<div class="cap">总则 1.0.14 勘察文件份数</div>
  <div class="note">勘察人提供工程勘察文件的标准份数为 <b>4 份</b>。发包人要求增加份数的，由发包人另行支付印制工本费（本软件按 100 元/份 计列，可修改）。</div>
  <div class="cap" style="margin-top:10px">总则 1.0.4 计费公式</div>
  <div class="note" style="font-family:ui-monospace,Consolas,monospace;line-height:1.9">
    勘察收费 = 基准价 × (1 ± 浮动幅度)　← 本软件以「下浮」体现<br>
    基准价 = 实物工作收费 + 技术工作收费<br>
    实物工作收费 = 基价 × 实物工作量 × 附加调整系数<br>
    技术工作收费 = 实物工作收费 × 技术工作费比例
  </div>`;
}

/* ------------------------------------------------------------------ 事件绑定 */
function castEl(el) {
  const t = el.dataset.type;
  if (t === 'bool') {
    if (el.type === 'checkbox') return el.checked;
    return el.value === '1' || el.value === 'true';
  }
  if (t === 'int') return parseInt(el.value, 10) || 0;
  if (el.type === 'number') return el.value === '' ? 0 : num(el.value);
  return el.value;
}

function bindGlobal() {
  // 顶栏
  $('#mProject').oninput = e => { S.meta.project = e.target.value; };
  $('#mOwner').oninput = e => { S.meta.owner = e.target.value; };
  $('#mGrade').onchange = e => { S.grade = e.target.value; calcNow(); render(); };

  // 导航
  $$('.nav').forEach(n => n.onclick = () => { MOD = n.dataset.mod; render(); });

  // 左栏费用汇总参数
  const pDisc = $('#pDisc');
  if (pDisc) pDisc.oninput = () => { S.discount = num(pDisc.value); calcNow(); };

  // 中枢事件
  const center = $('#center');
  center.addEventListener('input', e => {
    const el = e.target;
    // 计价方式切换由 change 统一处理（需重置档位并重绘下拉项）
    if (el.dataset.reset) return;
    if (el.dataset.bind && !el.dataset.layer) {
      const bind = el.dataset.bind;
      const m = bind.match(/^layers\.(\d+)\.(name|cls|bottom)$/);
      const oldVal = m ? getPath(S, bind) : null;
      setPath(S, bind, castEl(el));
      // 手工改动件数 → 该项转为手工指定，不再跟随取样数量
      const mLab = bind.match(/^lab\.items\.(\d+)\.qty$/);
      if (mLab && S.lab.items[+mLab[1]]) S.lab.items[+mLab[1]].auto = false;
      // 标准地层改动 → 同步标贯 / 动探 / 钻孔分层中的引用
      if (m) syncLayerRefs(+m[1], m[2], oldVal);
      calcNow();
    }
  });
  center.addEventListener('change', e => {
    const el = e.target;
    if (el.dataset.wave != null) {
      // 勾选波速孔（导入理正后按实测孔选取，米数自动合计）
      const no = el.dataset.wave;
      const arr = S.geo.wave.holeNos || (S.geo.wave.holeNos = []);
      const k = arr.indexOf(no);
      if (el.checked && k < 0) arr.push(no);
      if (!el.checked && k >= 0) arr.splice(k, 1);
      S.geo.wave.holeNos = arr;
      render(); calcNow(); return;
    }
    if (el.dataset.layer) {
      const list = el.dataset.layer === 'spt' ? S.spt : S.dpt;
      const i = +el.dataset.i;
      const idx = parseInt(el.value, 10);
      const L = (idx >= 0 && S.layers[idx]) ? S.layers[idx] : null;
      list[i].layerIdx = L ? idx : null;
      if (L) {
        list[i].layerName = L.name;
        list[i].cls = num(L.cls) || 1;
      }
      render(); calcNow(); return;
    }
    if (el.type === 'checkbox' && el.dataset.coef) {
      toggleCoef(el.dataset.coef, el.value, el.checked);
      render(); calcNow(); return;
    }
    if (el.dataset.bind) {
      const bind = el.dataset.bind;
      const ml = bind.match(/^layers\.(\d+)\.(name|cls|bottom)$/);
      const oldVal = ml ? getPath(S, bind) : null;
      setPath(S, bind, castEl(el));
      if (el.dataset.guess) {
        // 岩土名称变化 → 按标准对照自动带出岩土类别（用户仍可手动改）
        const cls = guessClass(el.value);
        if (cls) setPath(S, bind.replace(/\.name$/, '.cls'), cls);
        if (ml) syncLayerRefs(+ml[1], ml[2], oldVal);
        render(); calcNow(); return;
      }
      // 手工改类别 / 层底深度 → 同步引用该层的记录
      if (ml) {
        const n = syncLayerRefs(+ml[1], ml[2], oldVal);
        render(); calcNow();
        if (n) toast('已同步 ' + n + ' 条引用该地层的记录', 'ok');
        return;
      }
      if (el.dataset.reset === 'elec') {
        // 切换电极距 / 测点距 计价方式后，原档位与装置在新表中可能不存在，重置为首项
        const m = el.dataset.bind.match(/^geo\.elec\.(\d+)\.space$/);
        if (m) {
          const it = S.geo.elec[+m[1]];
          it.row = 0; it.method = 0;
        }
        render(); calcNow(); return;
      }
      calcNow();
      scheduleRender();
    }
  });
  center.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const act = b.dataset.act, i = +b.dataset.i;
    const A = {
      addLayer: () => {
        const last = S.layers.length ? num(S.layers[S.layers.length - 1].bottom) : 0;
        S.layers.push({ code: circleNo(S.layers.length), name: '', cls: 1, bottom: r2(last + 2) });
        renumberLayers();
      },
      clearLayer: () => {
        S.layers = [];
        if ((S.spt || []).length || (S.dpt || []).length) {
          toast('标准地层已清空，标贯 / 动探中的土层引用请重新选择', '');
        }
      },
      delLayer: () => {
        const L = S.layers[i]; if (!L) return;
        const nm = (L.name || '').trim();
        S.layers.splice(i, 1);
        renumberLayers();
        // 删除地层后，引用该层的标贯 / 动探记录一并移除，避免留下无主的悬空引用
        const hit = t => (t.layerIdx != null) ? (t.layerIdx === i) : (!!nm && (t.layerName || '').trim() === nm);
        const ns = (S.spt || []).filter(hit).length;
        const nd = (S.dpt || []).filter(hit).length;
        if (ns || nd) {
          S.spt = (S.spt || []).filter(t => !hit(t));
          S.dpt = (S.dpt || []).filter(t => !hit(t));
          toast('已删除地层「' + nm + '」，同步移除 ' + ns + ' 条标贯、' + nd + ' 条动探', '');
        }
        // 下标随地层前移
        (S.spt || []).concat(S.dpt || []).forEach(t => {
          if (t.layerIdx != null && t.layerIdx > i) t.layerIdx--;
        });
      },
      addHoleType: () => { S.holeTypes.push({ name: '其他孔', count: 1, depth: 20 }); },
      delHoleType: () => { S.holeTypes.splice(i, 1); },
      half: () => {
        const t = num($('#holeTotal').value);
        const ctrl = Math.round(t / 2), other = t - ctrl;
        if (S.holeTypes.length < 2) S.holeTypes = [{ name: '控制孔', count: ctrl, depth: 30 }, { name: '鉴别孔', count: other, depth: 20 }];
        else { S.holeTypes[0].count = ctrl; S.holeTypes[0].name = '控制孔'; S.holeTypes[1].count = other; S.holeTypes[1].name = '鉴别孔'; }
      },
      addSpt: () => {
        // 每层土一行：优先带出尚未添加过标贯的地层，深度档随层底深度自动匹配，
        // 次数默认 SPT_DEFAULT_QTY，均可手工修改。
        const layers = S.layers || [];
        const used = (S.spt || []).map(t => t.layerIdx != null ? t.layerIdx : layerIdxOf(t.layerName, ''));
        let idx = layers.findIndex((x, i) => x.name && used.indexOf(i) < 0);
        if (idx < 0) idx = layers.findIndex(x => x.name);
        const L = idx >= 0 ? layers[idx] : null;
        const d = L ? num(L.bottom) : 0;
        S.spt.push({
          layerName: L ? L.name : '',
          layerIdx: L ? idx : null,
          cls: L ? (num(L.cls) || 1) : 1,
          band: d <= 20 ? 0 : (d <= 50 ? 1 : 2),
          count: SPT_DEFAULT_QTY,
        });
      },
      delSpt: () => { S.spt.splice(i, 1); },
      addDpt: () => { S.dpt.push({ kind: 'dpt_heavy', layerName: '', layerIdx: null, cls: 1, band: 0, meters: 1 }); },
      delDpt: () => { S.dpt.splice(i, 1); },
      addDig: () => {
        const k = $('#digKind').value;
        S.extraDig.push({ kind: k, row: 0, cls: 1, qty: 1 });
      },
      delDig: () => { S.extraDig.splice(i, 1); },
      addLabRow: () => { S.lab.items.push({ name: '新试验项目', spec: '', unit: '件', price: 0, qty: LAB_DEFAULT_QTY, auto: false }); },
      delLab: () => { S.lab.items.splice(i, 1); },
      toggleLabLink: () => {
        const it = S.lab.items[i]; if (!it) return;
        const p = labLinkOf(it.name);
        if (!p) return;
        if (it.auto === false) {
          it.auto = true;
          const q = sampleQty(p.link);
          if (q > 0) it.qty = q;
          toast('已恢复联动：件数跟随「' + SAMPLE_LABEL[p.link] + '」' + r2(q), 'ok');
        } else {
          it.auto = false;
          toast('已改为手工指定，不再跟随取样数量', '');
        }
      },
      addElec: () => { S.geo.elec.push({ row: 0, method: 0, space: 'elec', qty: 10, dense: false, ip: false, charge: false }); },
      delElec: () => { S.geo.elec.splice(i, 1); },
      waveAll: () => { S.geo.wave.holeNos = (S.holes || []).map(h => h.no); },
      waveNone: () => { S.geo.wave.holeNos = []; },
      addGeoExtra: () => {
        const sel = $('#geoPick'); const o = sel.options[sel.selectedIndex];
        S.geo.extra.push({ name: o.dataset.name, unit: o.dataset.unit, price: num(o.dataset.price), qty: 1, spec: '' });
      },
      delGeoExtra: () => { S.geo.extra.splice(i, 1); },
      clearHoles: () => {
        S.holes = []; if (LZ) LZ.applied = false; S.mode = 'budget';
        S.geo.wave.holeNos = [];
        toast('已清除实测数据，可重新选择备份库，或切到「人工录入」', '');
      },
      importLz: () => { $('#fileLz').click(); },
      addCustom: () => { S.other.custom.push({ name: '增项', unit: '项', qty: 1, price: 0 }); },
      delCustom: () => { S.other.custom.splice(i, 1); },
    };
    if (A[act]) { A[act](); render(); calcNow(); }
  });

  // 快捷添加试验
  center.addEventListener('click', e => {
    const b = e.target.closest('[data-preset]'); if (!b) return;
    const p = LAB_PRESET.find(x => x.id === b.dataset.preset);
    const linked = p.link ? sampleQty(p.link) : 0;
    const has = S.lab.items.find(x => x.name === p.name);
    if (has) {
      if (linked > 0) {
        has.qty = linked;
        has.auto = true;
        toast('「' + p.name + '」件数已联动' + SAMPLE_LABEL[p.link] + '，更新为 ' + r2(linked), 'ok');
      } else {
        toast('「' + p.name + '」已在列表中，可直接修改件数', 'err');
      }
    } else {
      const q0 = (p.link && linked > 0) ? linked : LAB_DEFAULT_QTY;
      S.lab.items.push({ name: p.name, spec: p.spec, unit: p.unit, price: p.price, qty: q0, auto: !!p.link });
      toast('已添加「' + p.name + '」' + r2(q0) + ' ' + p.unit +
        (p.link && linked > 0 ? '（联动' + SAMPLE_LABEL[p.link] + '数量，取样变化时自动跟随）' : '（默认 ' + LAB_DEFAULT_QTY + '）'), 'ok');
    }
    render(); calcNow();
  });

  // 文件
  $('#fileLz').onchange = e => { const f = e.target.files[0]; if (f) handleLz(f); e.target.value = ''; };
  $('#filePrj').onchange = async e => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    mask(true, '正在打开项目…');
    try {
      const b64 = await readB64(f);
      const res = await api.load_project({ b64 });
      if (res.ok) { S = Object.assign(defaultState(), res.state); normalizeLabAuto(); syncTop(); render(); calcNow(); toast('项目已载入', 'ok'); }
      else toast('打开失败：' + res.error, 'err');
    } catch (err) { toast(err.message, 'err'); }
    mask(false);
  };
  $('#btnOpen').onclick = () => $('#filePrj').click();
  $('#btnSave').onclick = () => openDlg('save');
  $('#btnExport').onclick = () => openDlg('export');
  const br = $('#btnReport'); if (br) br.onclick = () => openDlg('report');
}

/* ---------------- 保存 / 导出 对话框 ---------------- */
let DLG_TYPE = 'export';
let DLG_DIR = '';
async function openDlg(type) {
  DLG_TYPE = type;
  let dir = DLG_DIR;
  if (!dir) {
    try { const r = await api.default_dir(); dir = r.dir; } catch (e) { dir = ''; }
    DLG_DIR = dir;
  }
  const proj = (S.meta.project || '工程勘察').replace(/[\\/:*?"<>|]/g, '_').slice(0, 40);
  const d = new Date();
  const stamp = '' + d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
  const modeCn = S.mode === 'settle' ? '结算' : '预算';
  const T = {
    export: { title: '导出 Excel（费用计算书）', name: `${proj}_勘察费用计算书_${stamp}.xlsx`,
      tip: '导出含「费用计算书 / 工作量清单 / 分层明细」三个工作表，导出后可点「打开」定位文件。' },
    save: { title: '保存计价项目', name: `${proj}_勘察计价_${stamp}.kcsj`,
      tip: '项目文件为 .kcsj 格式，可再次打开继续编辑。' },
    report: { title: `生成${modeCn}报告（Word）`, name: `${proj}_勘察费${modeCn}报告_${stamp}.docx`,
      tip: `自动生成《工程勘察费${modeCn}报告》：工程概况、计价依据、工作量统计、费用计算明细、费用统计表。` },
  }[type] || {};
  $('#dlgTitle').textContent = T.title;
  $('#dlgName').value = T.name;
  $('#dlgDir').value = dir;
  $('#dlgTip').innerHTML = T.tip;
  $('#dlgMask').classList.add('on');
  setTimeout(() => $('#dlgName').focus(), 60);
}
function closeDlg() { $('#dlgMask').classList.remove('on'); }
function bindDlg() {
  $('#dlgCancel').onclick = closeDlg;
  $('#dlgMask').onclick = e => { if (e.target.id === 'dlgMask') closeDlg(); };
  $('#btnHelp').onclick = () => $('#helpMask').classList.add('on');
  $('#helpClose').onclick = () => $('#helpMask').classList.remove('on');
  $('#helpMask').onclick = e => { if (e.target.id === 'helpMask') e.currentTarget.classList.remove('on'); };
  $('#dlgOpen').onclick = async () => {
    const r = await api.open_path($('#dlgDir').value);
    if (!r.ok) toast(r.error || '目录不存在', 'err');
  };
  $('#dlgOk').onclick = async () => {
    const dir = $('#dlgDir').value.trim();
    const name = $('#dlgName').value.trim();
    if (!dir) { toast('请填写保存位置', 'err'); return; }
    DLG_DIR = dir;
    closeDlg(); mask(true, DLG_TYPE === 'export' ? '正在生成 Excel…' : (DLG_TYPE === 'report' ? '正在生成报告…' : '正在保存…'));
    try {
      if (DLG_TYPE === 'export') {
        const res = await api.export_excel({ state: S, dir, filename: name });
        mask(false);
        if (res.ok) { toast('已导出：' + res.path, 'ok'); api.open_path(res.path); }
        else toast('导出失败：' + res.error, 'err');
      } else if (DLG_TYPE === 'report') {
        const res = await api.export_report({ state: S, dir, filename: name });
        mask(false);
        if (res.ok) { toast('报告已生成：' + res.path, 'ok'); api.open_path(res.path); }
        else toast('生成失败：' + res.error, 'err');
      } else {
        const res = await api.save_project({ state: S, dir, filename: name });
        mask(false);
        res.ok ? toast('已保存：' + res.path, 'ok') : toast('保存失败：' + res.error, 'err');
      }
    } catch (e) { mask(false); toast(e.message, 'err'); }
  };
}

let renderT = null;
function scheduleRender() {
  clearTimeout(renderT);
  renderT = setTimeout(() => { if (document.activeElement === document.body) render(); }, 90);
}

function toggleCoef(key, id, on) {
  const arr = S[key] || [];
  const i = arr.indexOf(id);
  if (on && i < 0) arr.push(id);
  if (!on && i >= 0) arr.splice(i, 1);
  S[key] = arr;
}

function guessClass(name) {
  if (!name) return 0;
  const dic = STD.name_class || {};
  if (dic[name] != null) return +dic[name];
  const keys = Object.keys(dic).sort((a, b) => b.length - a.length);
  for (const k of keys) if (k && name.includes(k)) return +dic[k];
  if (name.includes('风化')) return name.includes('强风') || name.includes('全风') ? 2 : (name.includes('中风') ? 3 : 4);
  return 0;
}

function syncTop() {
  $('#mProject').value = (S.meta && S.meta.project) || '';
  $('#mOwner').value = (S.meta && S.meta.owner) || '';
  $('#mGrade').value = S.grade || '甲级';
}

/* ------------------------------------------------------------------ 启动 */
function boom(msg) {
  if (document.querySelector('.boot-tip')) return;
  const d = document.createElement('div');
  d.className = 'hint boot-tip';
  d.style.cssText = 'position:fixed;top:64px;left:50%;transform:translateX(-50%);z-index:99;max-width:70vw';
  d.textContent = msg;
  document.body.appendChild(d);
  return d;
}

/* 版本号：由 core/version.py 统一下发，标题、副标题、底栏、帮助同步显示 */
function applyVersion(v) {
  if (!v) return;
  const tag = v.tag || ('v' + v.version + ' by ' + v.author);
  if (v.title) document.title = v.title;
  const b = $('#brandVer'); if (b) b.textContent = tag;
  const f = $('#fVer'); if (f) f.textContent = tag;
  const hp = $('#helpVer');
  if (hp) hp.textContent = '工程勘察收费标准计算器（2002 修订本）　' + tag;
}

function boot() {
  klog('boot 开始 DOM=' + document.readyState);
  let done = false;
  const start = () => {
    if (done) return;
    done = true;
    api.get_standards().then(std => {
      klog('数据已取到 tables=' + Object.keys(std.tables || {}).length);
      const tip = document.querySelector('.boot-tip');
      if (tip) tip.remove();
      STD = std;
      applyVersion(std.version);
      S = defaultState();
      bindGlobal();
      bindDlg();
      syncTop();
      render();
      calcNow();
      klog('渲染完成 centerLen=' + ($('#center') ? $('#center').innerHTML.length : -1));
    }).catch(e => {
      done = false;
      klog('初始化失败 ' + (e && e.message ? e.message : e));
      boom('界面初始化失败：' + (e.message || e) + '（3 秒后自动重试）');
      setTimeout(start, 3000);
    });
  };
  start();
}
boot();
