"use strict";
/* 单一调度器：SSE 负责即时反馈，轮询负责静默期和断线兜底。
   提醒（解出题 / 待你回答）也挂在这一个调度器上——再开一个 setInterval 就是
   第二个心跳：页面隐藏时两边各降各的频，谁都说不清下一次请求什么时候到。 */
const ConsolePolling = (() => {
  // 提醒比会话状态稀疏一档：它跨会话，不需要跟到秒级
  const NOTIFY_VISIBLE = 15000, NOTIFY_HIDDEN = 30000;
  function create({refreshList, refreshState, refreshNotify, isSession, isRunning,
                   isVisible, now = Date.now, later = setTimeout, cancel = clearTimeout}) {
    let timer = null, stopped = true, lastList = 0, lastState = 0, lastNotify = 0;
    const invoke = callback => { Promise.resolve().then(callback).catch(() => {}); };
    function tick(force = false) {
      if (stopped) return;
      const time = now(), visible = isVisible();
      const listInterval = visible ? 5000 : 30000;
      const stateInterval = visible ? (isRunning() ? 3000 : 15000) : 30000;
      if (force || time - lastList >= listInterval) { lastList = time; invoke(refreshList); }
      if (isSession() && (force || time - lastState >= stateInterval)) {
        lastState = time; invoke(refreshState);
      }
      /* 不绑当前会话：人在首页或设置页时，别处解出题、或有人在等你答，也得知道 */
      if (refreshNotify
          && (force || time - lastNotify >= (visible ? NOTIFY_VISIBLE : NOTIFY_HIDDEN))) {
        lastNotify = time; invoke(refreshNotify);
      }
      timer = later(() => tick(), visible ? 1000 : 5000);
    }
    return {
      listRequested() { lastList = now(); },
      stateRequested() { lastState = now(); },
      notifyRequested() { lastNotify = now(); },
      start() { if (!stopped) return; stopped = false; lastList = lastState = lastNotify = now(); tick(); },
      stop() { stopped = true; if (timer !== null) cancel(timer); timer = null; },
      wake() { if (stopped) return; if (timer !== null) cancel(timer); tick(true); },
    };
  }
  return {create};
})();
