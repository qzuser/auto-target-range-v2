"use strict";
// 计数格式：K / M / B / T / E / P 六档，用量页与会话页共用一套口径。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/count.js"), "utf8");

const context = vm.createContext({console});
vm.runInContext(source, context);
const fmt = vm.runInContext("fmtCount", context);

// 千以下原样给整数，不带小数也不带单位
assert.equal(fmt(0), "0");
assert.equal(fmt(7), "7");
assert.equal(fmt(999), "999");
assert.equal(fmt(12.4), "12", "整数位按四舍五入收");

// 六档后缀，每千进一位
assert.equal(fmt(1000), "1K");
assert.equal(fmt(1500), "1.5K");
assert.equal(fmt(45000), "45K");
assert.equal(fmt(123456), "123K");
assert.equal(fmt(1_000_000), "1M");
assert.equal(fmt(2_500_000), "2.5M");
assert.equal(fmt(1_234_567_890), "1.23B");
assert.equal(fmt(4_000_000_000_000), "4T");
assert.equal(fmt(7_500_000_000_000_000), "7.5E");
assert.equal(fmt(1_200_000_000_000_000_000), "1.2P");

// 结尾的 0 去掉：1.20M 写成 1.2M，2.00K 写成 2K
assert.equal(fmt(1_200_000), "1.2M");
assert.equal(fmt(2000), "2K");
assert.equal(fmt(10_000), "10K", "整十不补 .0");

// 负数带符号，脏数据给破折号而不是 NaN
assert.equal(fmt(-2500), "-2.5K");
assert.equal(fmt(null), "0");
assert.equal(fmt(undefined), "—");
assert.equal(fmt("不是数字"), "—");
assert.equal(fmt(Number.POSITIVE_INFINITY), "—");

console.log("test_count_format.js: 全部通过");
