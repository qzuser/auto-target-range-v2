/* 计数后缀：K / M / B / T / E / P（千、百万、十亿、万亿、千万亿、百亿亿）。
 *
 * 用量页与会话页共用同一套写法，避免「4.0 万」和「40000」两种口径并存。
 * 规则：
 *   1. 不到 1000 直接给整数（不补小数点）；
 *   2. 每跨一千倍换一个后缀，最多到 P；
 *   3. 有效数字按量级收：<10 两位小数、<100 一位、其余取整，末尾的 0 去掉
 *      （1.20M → 1.2M，2.00K → 2K）；
 *   4. 认不出数字就给「—」，负数带符号。
 */
const COUNT_UNITS = [
  [1e18, "P"], [1e15, "E"], [1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"],
];

function fmtCount(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs < 1000) return sign + String(Math.round(abs));
  for (const [base, suffix] of COUNT_UNITS) {
    if (abs < base) continue;
    const scaled = abs / base;
    const digits = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
    let text = scaled.toFixed(digits);
    if (text.includes(".")) {
      text = text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    }
    return `${sign}${text}${suffix}`;
  }
  return sign + String(Math.round(abs));
}
