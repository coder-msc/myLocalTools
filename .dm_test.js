const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');

// 1. 语法
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let ok = true;
scripts.forEach((s, i) => { try { new Function(s); } catch (e) { ok = false; console.log('block', i, 'ERROR:', e.message); } });
console.log(ok ? 'PASS  JS 语法（' + scripts.length + ' 块）' : 'FAIL  JS 语法');

// 2. Tab 三方对齐
const btns = [...html.matchAll(/switchTab\('(\w+)'\)/g)].map(m => m[1]);
const contents = [...html.matchAll(/id="tab-(\w+)"/g)].map(m => m[1]);
const arrMatch = html.match(/const tabs = \[([^\]]+)\]/)[1].replace(/'/g, '').split(',').map(s => s.trim());
console.log(btns.length === contents.length && JSON.stringify(btns) === JSON.stringify(contents) && JSON.stringify(arrMatch) === JSON.stringify(contents)
    ? 'PASS  Tab 按钮x' + btns.length + ' / 内容区 / switchTab 数组三方对齐: ' + arrMatch.join(',')
    : 'FAIL  对齐: btns=' + JSON.stringify(btns) + ' contents=' + JSON.stringify(contents) + ' arr=' + JSON.stringify(arrMatch));

// 3. 渲染引擎仿真
const engine = html.match(/\/\/ ============ 弹幕墙 ============[\s\S]*?function dmTabOff\(\) \{[\s\S]*?\n        \}/)[0];
function makeEnv() {
    const anims = new Set();
    const els = [];
    const el = (id) => {
        if (id === 'dmStage') return { clientWidth: 1000, clientHeight: 352, style: { setProperty() {} } };
        if (id === 'dmEmpty') return { style: { display: '' } };
        return { value: 0 };
    };
    const mkEl = () => {
        const e = {
            className: '', textContent: '', style: {}, _removed: false, offsetWidth: 200,
            animate(kf, opt) {
                const a = { onfinish: null, cancel() { anims.delete(a); }, pause() {}, play() {} };
                anims.add(a);
                e._anim = a;
                return a;
            },
            remove() { e._removed = true; if (e._anim) anims.delete(e._anim); }
        };
        els.push(e);
        return e;
    };
    const doc = {
        getElementById: el,
        createElement: () => mkEl(),
        querySelectorAll: () => [],
    };
    const ctx = new Function('document', 'fetch', 'localStorage', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date',
        engine + '\nreturn {dmPickLane, dmSpawn, dmEnqueue, dmDrain, dmTogglePause, dmClearScreen, getState: () => ({queue: dmSpawnQueue, seen: dmSeenIds, anims, paused: dmPaused})};')(
        doc, () => ({ then() { return this; }, catch() {} }),
        { getItem: () => null, setItem() {} },
        (fn, ms) => 1, () => {}, () => 1, () => {},
        { now: (() => { let t = 1000000; return () => t; })() });
    return { ctx, els, anims };
}

// E1: 9 条轨道分配
let env = makeEnv();
let lanes = [];
for (let i = 0; i < 9; i++) { lanes.push(env.ctx.dmPickLane(200).lane); }
console.log(new Set(lanes).size === 9 ? 'PASS  E1 9 条弹幕分到 9 条不同轨道（' + lanes.join(',') + '）' : 'FAIL  E1 ' + lanes);

// E2: 第 10 条全忙排队
let p10 = env.ctx.dmPickLane(200);
console.log(p10.delay > 0 ? 'PASS  E2 轨道全忙返回 delay=' + p10.delay + 'ms' : 'FAIL  E2 ' + JSON.stringify(p10));

// E3: dmSpawn
let spawned = env.ctx.dmSpawn({ text: 'hi', color: '#fff' });
console.log(spawned === true && env.els.length === 1 && env.els[0].style.top !== undefined ? 'PASS  E3 dmSpawn 创建元素+设轨道' : 'FAIL  E3');

// E4: 防重复 id
env.ctx.dmEnqueue({ id: 'dm_1', text: 'a', color: '#fff', ts: 1 });
env.ctx.dmEnqueue({ id: 'dm_1', text: 'a', color: '#fff', ts: 1 });
console.log(env.ctx.getState().seen.size === 1 ? 'PASS  E4 重复 id 被忽略' : 'FAIL  E4');

// E5: 清屏
env.ctx.dmEnqueue({ id: 'dm_2', text: 'b', color: '#fff', ts: 2 });
env.ctx.dmClearScreen();
let st = env.ctx.getState();
console.log(st.queue.length === 0 && st.anims.size === 0 ? 'PASS  E5 清屏（队列+动画清零）' : 'FAIL  E5 queue=' + st.queue.length + ' anims=' + st.anims.size);

// E6/E7: 暂停排队、恢复发射
let env6 = makeEnv();
env6.ctx.dmEnqueue({ id: 'dm_3', text: 'paused test', color: '#fff', ts: 3 });
env6.ctx.dmTogglePause();
let before = env6.els.length;
env6.ctx.dmEnqueue({ id: 'dm_4', text: 'queued while paused', color: '#fff', ts: 4 });
console.log(env6.els.length === before && env6.ctx.getState().queue.length === 2 ? 'PASS  E6 暂停时排队不发射（队列 ' + env6.ctx.getState().queue.length + ' 条）' : 'FAIL  E6 els=' + env6.els.length);
env6.ctx.dmTogglePause();
console.log(env6.ctx.getState().queue.length === 0 && env6.els.length >= before + 2 ? 'PASS  E7 恢复后队列排空并发射' : 'FAIL  E7 queue=' + env6.ctx.getState().queue.length + ' els=' + env6.els.length);

// 4. DOM 结构
['dmStage', 'dmInput', 'dmColors', 'dmSpeed', 'dmFontSize', 'dmOpacity', 'dmPauseBtn', 'dmEmpty'].forEach(id => {
    if (!html.includes('id="' + id + '"')) { console.log('FAIL  缺少元素 #' + id); ok = false; }
});
console.log(ok ? 'PASS  E8 DOM 元素齐全' : 'FAIL  E8');
console.log((html.match(/onclick="dmSend\(\)"/g) || []).length >= 2 ? 'PASS  E9 dmSend 绑定（按钮+回车）' : 'FAIL  E9');
console.log(/if \(tab === 'danmaku'\) dmTabOn\(\); else dmTabOff\(\);/.test(html) ? 'PASS  E10 Tab 钩子接入 switchTab' : 'FAIL  E10');
