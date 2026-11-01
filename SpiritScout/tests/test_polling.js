"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/spiritscout/web/static/js/polling.js'), 'utf8'), context);
(async () => {
  let time=0, timer, list=0, state=0, visible=true, session=true;
  const scheduler=vm.runInContext('ConsolePolling',context).create({
    now:()=>time, later:fn=>{timer=fn;return 1;}, cancel:()=>{timer=null;},
    refreshList:()=>list++, refreshState:()=>state++, isVisible:()=>visible,
    isSession:()=>session, isRunning:()=>true});
  const advance=async seconds=>{for(let i=0;i<seconds;i++){time+=1000;timer?.();await Promise.resolve();}};
  scheduler.start(); await advance(15);
  assert.equal(list,3,'列表每 5 秒一次，不叠加会话轮询');
  assert.equal(state,5,'活动状态每 3 秒兜底');
  scheduler.stateRequested(); time+=2000;timer();await Promise.resolve();assert.equal(state,5);
  visible=false;await advance(10);assert.equal(list,3,'隐藏后降频');
  visible=true;scheduler.wake();await Promise.resolve();assert.equal(list,4);assert.equal(state,6);
  session=false;await advance(15);assert.equal(list,7);assert.equal(state,6,'离开会话后不轮询旧状态');
  scheduler.stop();await advance(40);assert.equal(list,7);
  // 提醒走同一个调度器：可见 15 秒一档、隐藏 30 秒一档，且不跟会话状态绑定。
  let t2=0,timer2,notes=0,visible2=true;
  const notifier=vm.runInContext('ConsolePolling',context).create({
    now:()=>t2, later:fn=>{timer2=fn;return 1;}, cancel:()=>{timer2=null;},
    refreshList:()=>{}, refreshState:()=>{}, refreshNotify:()=>notes++,
    isVisible:()=>visible2, isSession:()=>false, isRunning:()=>false});
  const advance2=async seconds=>{for(let i=0;i<seconds;i++){t2+=1000;timer2?.();await Promise.resolve();}};
  notifier.start();await advance2(14);assert.equal(notes,0,'启动那一拍不抢跑，别和首屏请求撞车');
  await advance2(2);assert.equal(notes,1,'可见时提醒每 15 秒一次');
  visible2=false;await advance2(29);assert.equal(notes,2,'隐藏后按 30 秒一档（从上次提醒算起）');
  await advance2(29);assert.equal(notes,2,'不满 30 秒不再响');
  await advance2(2);assert.equal(notes,3,'隐藏满 30 秒补一拍');
  notifier.stop();await advance2(90);assert.equal(notes,3,'停表后不再提醒');
  // 两个来源同时刷新列表，只能有一个实际在途请求。
  const source=fs.readFileSync(path.join(__dirname,'../src/spiritscout/web/static/js/core.js'),'utf8');
  let requests=0,resolve;
  const sandbox=vm.createContext({S:{sessions:[],cur:null,view:'home'}, $:()=>({remove(){}}),
    renderSessions(){}, api:()=>{requests++;return new Promise(r=>{resolve=r;});}});
  vm.runInContext(source.slice(source.indexOf('let sessionsInFlight'),source.indexOf('function renderSessions()')),sandbox);
  const first=vm.runInContext('refreshSessions()',sandbox),second=vm.runInContext('refreshSessions()',sandbox);
  assert.equal(first,second);assert.equal(requests,1);resolve({sessions:[]});await first;
  const third=vm.runInContext('refreshSessions()',sandbox);assert.equal(requests,2);resolve({sessions:[]});await third;
  console.log('polling: single scheduler, quiet fallback, visibility, session exit and in-flight dedup passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
