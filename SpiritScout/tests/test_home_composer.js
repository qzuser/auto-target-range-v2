const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(value = '') {
    this.value = value;
    this.checked = false;
    this.dataset = {};
    this.style = {};
    this.scrollHeight = 90;
    this.listeners = {};
    this.classes = new Set();
    this.classList = { toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name) };
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  focus() { this.focused = true; }
  closest() { return null; }
}
const elements = Object.fromEntries(['c-go', 'c-mode', 'c-mode-hint', 'c-mission'].map(id => [`#${id}`, new Element()]));
const radios = ['src', 'ctf', 'competition'].map(mode => new Element(mode));
const examples = ['src', 'ctf', 'competition'].map(mode => {
  const element = new Element();
  element.dataset = { mode, mission: `示例 ${mode}` };
  element.textContent = '显示文字 ↗';
  return element;
});
const source = fs.readFileSync('src/spiritscout/web/static/js/console.js', 'utf8');
/* homeSync 现在把发送键判定交给 syncCompSend（有文字或有附件就能发），两段要一起抽。
   syncCompSend 里对 #comp-send 的分支走不到——沙箱 $ 查不到该元素，`if (comp)`
   直接短路，不会碰到沙箱没提供的 compInput / S.compFiles。 */
const slice = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const home = slice('function syncCompSend', '/* 附件入口')
  + slice('const autogrow =', '/* 附件暂存：');
let launches = 0;
const savedModes = [];
vm.runInNewContext(home, {
  $: selector => elements[selector],
  document: { querySelectorAll: selector => selector === '.chip-s' ? examples : radios },
  selxSync() {}, toast() {}, S: { homeFiles: [] },
  launchMission() { launches++; },
  // 模式记忆走服务端：GET 只回一个稳定的默认值，PUT 记下来供断言
  api: async (path, opt) => {
    if (opt?.method === 'PUT') savedModes.push(JSON.parse(opt.body).mode);
    return { mode: 'ctf' };
  },
});
assert.equal(elements['#c-go'].classes.has('ready'), false);
for (const radio of radios) {
  radio.listeners.change();
  assert.equal(elements['#c-mode'].value, radio.value);
  assert.deepEqual(radios.filter(item => item.checked).map(item => item.value), [radio.value]);
}
// 每次切换都要写回服务端，否则重开控制台就忘了上次选的是什么
assert.deepEqual(savedModes.slice(0, 3), ['src', 'ctf', 'competition']);
elements['#c-mission'].value = '实际任务';
elements['#c-mission'].listeners.input();
assert.equal(elements['#c-go'].classes.has('ready'), true);
for (const example of examples) {
  example.onclick();
  assert.equal(elements['#c-mode'].value, example.dataset.mode);
  assert.equal(elements['#c-mission'].value, `${example.dataset.mission}：`);
  assert.equal(elements['#c-mission'].value.includes('↗'), false);
}
elements['#c-mission'].listeners.keydown({ key: 'Enter', isComposing: true });
assert.equal(launches, 0);
console.log('home composer: mode synchronization, examples, ready state and IME input passed');
