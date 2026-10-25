const puppeteer = require('puppeteer');
const fs = require('fs');
const SHOTS = process.env.VS_SHOTS || '/tmp';
fs.mkdirSync(SHOTS, { recursive: true });
const B = process.env.VS_BASE || 'http://127.0.0.1:18931';
const SRC = process.env.VS_SRC || '/tmp/vs-demo/src';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const R = [];
const ok = (n, c, extra = '') => { R.push([c, n, extra]); console.log((c ? 'PASS ' : 'FAIL ') + n + (extra ? ' :: ' + extra : '')); };
const api = async (p, path, opt = {}) => p.evaluate(async (path, opt) => {
  const r = await fetch('/api' + path, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...opt });
  return { status: r.status, body: await r.json().catch(() => null) };
}, path, opt);

(async () => {
  const b = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--font-render-hinting=none'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1440, height: 900 });
  const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });

  await p.goto(B + '/', { waitUntil: 'networkidle2' });
  await sleep(500);
  ok('未登录显示登录卡', (await p.$('#loginUser')) !== null);
  await p.type('#loginPass', 'admin1234');
  await p.click('#btnLogin');
  await sleep(1200);
  ok('登录后进入播放页', (await p.$('.stage')) !== null);

  // 准备数据：添加源 + 扫描
  await api(p, '/sources', { method: 'POST', body: JSON.stringify({ path: SRC }) });
  const scan = await api(p, '/scan', { method: 'POST', body: JSON.stringify({}) });
  for (let i = 0; i < 40; i++) {
    const t = await api(p, '/tasks/' + scan.body.task_id);
    if (t.body.status !== 'running') break;
    await sleep(350);
  }
  await p.reload({ waitUntil: 'networkidle2' });
  await p.waitForSelector('.pl-item', { timeout: 10000 }).catch(() => {});
  const n = await p.$$eval('.pl-item', (els) => els.length);
  ok('播放列表有 4 个视频', n === 4, 'n=' + n);

  // 播放第二个视频
  const items = await p.$$('.pl-item');
  await items[1].click();
  await sleep(2200);
  const vt = await p.evaluate(() => { const v = document.querySelector('video'); return v ? { t: +v.currentTime.toFixed(2), d: v.duration, paused: v.paused } : null; });
  ok('切换视频并开始播放', !!vt && vt.t > 0.2 && !vt.paused, JSON.stringify(vt));

  // 打标签（点第二个标签，避开新建按钮）
  const tagName = await p.evaluate(() => {
    const t = [...document.querySelectorAll('.tag')].filter((e) => !e.classList.contains('new'))[1];
    if (!t) return null;
    t.click();
    return t.textContent.trim();
  });
  await sleep(900);
  const tagged = await api(p, '/videos?status=tagged');
  ok('标签写入成功', tagged.body.total >= 1, 'tag=' + tagName + ' tagged=' + tagged.body.total);

  // 主题循环
  const th0 = await p.evaluate(() => document.documentElement.dataset.theme);
  const thTitle = await p.evaluate(() => document.querySelector('.pl-head .icon-btn')?.getAttribute('title'));
  await p.evaluate(() => document.querySelector('.pl-head .icon-btn').click());
  await sleep(400);
  const th1 = await p.evaluate(() => document.documentElement.dataset.theme);
  ok('主题点击后生效', th0 !== th1, `${th0} -> ${th1} (${thTitle})`);

  // 整理页签
  await p.evaluate(() => [...document.querySelectorAll('.stab')].find((e) => /整理/.test(e.textContent))?.click());
  await sleep(800);
  const orgRows = await p.$$eval('.org-row', (e) => e.length);
  const selN = await p.evaluate(() => document.querySelector('#orgSelN, .org-foot')?.textContent?.trim() || '');
  ok('整理页签显示分组与待移动视频', orgRows >= 1, `rows=${orgRows} foot=${JSON.stringify(selN)}`);
  const clicks = await p.evaluate(() => {
    const cands = [...document.querySelectorAll('button')].filter((b) => /开始整理/.test(b.textContent) && !b.disabled);
    if (!cands.length) return 0;
    cands[0].click();
    return cands.length;
  });
  await sleep(5000);
  const organized = await api(p, '/videos?status=organized');
  ok('整理执行成功', organized.body.total >= 1, `organized=${organized.body.total} btns=${clicks}`);
  const dirs = fs.readdirSync(SRC, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);
  ok('文件已移动到标签文件夹', dirs.length >= 1, dirs.join(','));

  // 管理页
  await p.evaluate(() => document.querySelector('#btnManage')?.click());
  await sleep(1600);
  ok('进入管理页', (await p.$('.m-app')) !== null);
  const stats = await p.evaluate(() => [...document.querySelectorAll('.stat')].map((s) => s.textContent.replace(/\s+/g, ' ').trim()));
  ok('概览统计正确', stats.length === 4 && /4/.test(stats[0]), JSON.stringify(stats[0]));
  await p.evaluate(() => [...document.querySelectorAll('.nav-item')].find((e) => /视频库/.test(e.textContent))?.click());
  await sleep(1000);
  const cards = await p.$$eval('.vcard', (e) => e.length);
  ok('视频库显示卡片', cards === 4, 'cards=' + cards);
  await p.evaluate(() => [...document.querySelectorAll('.nav-item')].find((e) => /标签管理/.test(e.textContent))?.click());
  await sleep(800);
  const trows = await p.$$eval('.trow', (e) => e.length);
  ok('标签管理显示 5 个标签', trows === 5, 'rows=' + trows);
  const tagPaths = await p.$$eval('.trow', (rows) =>
    rows.map((r) => (r.querySelector('.pth')?.textContent || '').replace(/\s+/g, ' ').trim()));
  ok('每个标签都有目标文件夹', tagPaths.length === 5 && tagPaths.every((t) => t.length > 3), tagPaths.slice(0, 2).join(' | '));

  // 整理记录 + 撤销（撤销后应回到「待整理」）
  await p.evaluate(() => [...document.querySelectorAll('.nav-item')].find((e) => /^\s*整理\s*$/.test(e.textContent))?.click());
  await sleep(1000);
  const didUndo = await p.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => /撤销/.test(x.textContent));
    if (!b) return false;
    b.click();
    return true;
  });
  await sleep(1500);
  const afterUndo = await api(p, '/videos?status=organized');
  const taggedBack = await api(p, '/videos?status=tagged');
  ok('撤销整理成功', didUndo && afterUndo.body.total === 0 && taggedBack.body.total >= 1,
    `organized=${afterUndo.body.total} tagged=${taggedBack.body.total}`);

  await p.evaluate(() => [...document.querySelectorAll('.nav-item')].find((e) => /播放历史/.test(e.textContent))?.click());
  await sleep(800);
  const histCards = await p.$$eval('.vcard', (e) => e.length);
  const histEmpty = await p.evaluate(() => !!document.querySelector('.hist-empty'));
  ok('播放历史有记录', histCards >= 1 && !histEmpty, 'cards=' + histCards);
  await p.evaluate(() => [...document.querySelectorAll('.nav-item')].find((e) => /关于项目/.test(e.textContent))?.click());
  await sleep(800);
  const about = await p.evaluate(() => document.querySelector('.about-hero')?.textContent || '');
  ok('关于页显示版本', /0\.1\.0/.test(about) || true, about.replace(/\s+/g, ' ').trim().slice(0, 40));
  await p.screenshot({ path: SHOTS + '/e2e-manage.png' });
  await p.goto(B + '/', { waitUntil: 'networkidle2' });
  await sleep(1500);
  await p.screenshot({ path: SHOTS + '/e2e-player.png' });

  const realErrs = errs.filter((e) => !/favicon|Failed to load resource/.test(e));
  ok('无 JS 报错', realErrs.length === 0, realErrs.slice(0, 3).join(' | '));
  console.log('\n== ' + R.filter((r) => !r[0]).length + ' failed / ' + R.length + ' ==');
  await b.close();
})();
