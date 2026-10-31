/* 提交任务后附件必须真正清掉，同一个文件不能在下一次选择时复活。

   这一版修的是个隐蔽的状态脱钩：bindAttach 在模块加载时捕获 S.homeFiles 的
   数组引用，而提交后原先写的是 S.homeFiles = []（换新数组）。闭包从此操作孤儿
   数组，于是——
     1) 下次选文件 push 进旧数组，renderFileChips 把上一轮提交过的附件又画回来；
     2) 登记状态（S.homeFiles / S.compFiles）永远是空的，发送键恒灰；
     3) 提交时 [...S.homeFiles] 拿到空数组，附件静默丢失。
   现在统一走 clearFileChips 就地清空，闭包与状态始终是同一个数组。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const SRC = path.join(__dirname, '../src/spiritscout/web/static/js/console.js');
const src = fs.readFileSync(SRC, 'utf8');

/* 抽出附件相关的三段真实实现：渲染、清空、绑定。 */
function slice(startMark, endMark) {
  const start = src.indexOf(startMark);
  assert.ok(start >= 0, `console.js 里找不到 ${startMark}`);
  const at = src.indexOf(endMark, start);
  assert.ok(at > start, `console.js 里找不到 ${endMark}`);
  return src.slice(start, at);
}

function makeEl() {
  const handlers = {};
  const classes = new Set();
  const buttons = [];
  return {
    innerHTML: '', value: '', files: [], handlers, classes, buttons,
    onclick: null,
    classList: {
      toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
    },
    addEventListener(type, fn) { handlers[type] = fn; },
    querySelectorAll(sel) { return sel === 'button' ? buttons : []; },
    click() { this.clicked = (this.clicked || 0) + 1; },
  };
}

const els = {
  '#home-files': makeEl(), '#home-file': makeEl(), '#home-attach': makeEl(),
  '#comp-files': makeEl(), '#comp-file': makeEl(), '#comp-attach': makeEl(),
  '#c-go': makeEl(), '#c-mission': makeEl(), '#c-mode': makeEl(),
  '#comp-send': makeEl(),
};
const S = { homeFiles: [], compFiles: [] };
const syncCalls = [];

const sandbox = {
  S,
  $: sel => els[sel] || null,
  esc: s => String(s),
  fmtSize: n => `${n}B`,
  document: { querySelectorAll: () => [] },
  // bindAttach 只在这些选择器上挂事件；上面的桩已经够用
};
createContext(sandbox);
runInContext(
  slice('function renderFileChips', '/* 发送键可用')
  + slice('function bindAttach', 'bindAttach("#comp-attach"')
  + '\nglobalThis.renderFileChips = renderFileChips;'
  + '\nglobalThis.clearFileChips = clearFileChips;'
  + '\nglobalThis.bindAttach = bindAttach;',
  sandbox,
);

// 模拟模块加载时的绑定：传进去的是 S.homeFiles 的引用
sandbox.bindAttach('#home-attach', '#home-file', S.homeFiles, '#home-files', {});
sandbox.bindAttach('#comp-attach', '#comp-file', S.compFiles, '#comp-files', {});

/* --- 1. 清空必须就地，引用不能换 --- */
const before = S.homeFiles;
S.homeFiles.push({ name: 'a.zip', size: 10 });
sandbox.renderFileChips('#home-files', S.homeFiles);
assert.match(els['#home-files'].innerHTML, /a\.zip/, '选完文件应该渲染出 chip');

const returned = sandbox.clearFileChips('#home-files', S.homeFiles, () => syncCalls.push('home'));
assert.equal(S.homeFiles, before, '清空后必须还是同一个数组（重新赋值会让闭包脱钩）');
assert.equal(returned, before, 'clearFileChips 应返回原数组');
assert.equal(S.homeFiles.length, 0, '清空后长度应为 0');
assert.equal(els['#home-files'].innerHTML, '', 'DOM 里的 chip 必须一起清掉');
assert.deepEqual(syncCalls, ['home'], '清空后要通知发送键重新判定');

/* --- 2. 清空后再选文件，上一轮的附件不能复活 --- */
els['#home-file'].files = [{ name: 'b.zip', size: 20 }];
els['#home-file'].onchange();
assert.equal(S.homeFiles.length, 1, '新选的文件应进同一个数组');
assert.equal(S.homeFiles[0].name, 'b.zip');
assert.match(els['#home-files'].innerHTML, /b\.zip/);
assert.doesNotMatch(els['#home-files'].innerHTML, /a\.zip/,
  '上一轮提交的附件不能跟着新选择复活');

/* --- 3. 会话输入坞同一条规则 --- */
const compBefore = S.compFiles;
S.compFiles.push({ name: 'c.txt', size: 5 });
sandbox.clearFileChips('#comp-files', S.compFiles, () => syncCalls.push('comp'));
assert.equal(S.compFiles, compBefore);
assert.equal(S.compFiles.length, 0);
assert.equal(els['#comp-files'].innerHTML, '');
els['#comp-file'].files = [{ name: 'd.txt', size: 6 }];
els['#comp-file'].onchange();
assert.deepEqual(S.compFiles.map(f => f.name), ['d.txt']);
assert.doesNotMatch(els['#comp-files'].innerHTML, /c\.txt/);

/* --- 4. 提交时读到的就是同一份状态 --- */
assert.deepEqual([...S.homeFiles].map(f => f.name), ['b.zip'],
  'launchMission 用 [...S.homeFiles] 取快照，必须拿得到当前真实状态');

console.log('attach clear: in-place reset keeps closure and state on the same array passed');
