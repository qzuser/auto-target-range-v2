"""测试用的进程启动预算：按本机实测放大超时，而不是写死秒数。

这些用例验证的是「进程树收口」和「超时回收」，不是「进程启动有多快」。
机器被别的进程占满时，一次 ``python -c pass`` 的耗时能从 0.05 秒涨到 4 秒，
写死的 0.7 / 2 / 3 秒预算就会把「还没启动完」误判成「挂死」——那是环境负载，
不是回归。这里量一次裸启动基线再按倍数放大：正常机器上预算仍是原来的短秒数，
只有机器真的慢时才放宽，测试意图不变。

基线在进程内只量一次（``functools.cache``），避免每个用例重复付这几百毫秒。
"""

from __future__ import annotations

import functools
import subprocess
import sys
import time

# 单次采样的上限：启动本身再慢也不该超过这个数，超了说明环境已经不适合跑这类
# 用例，宁可让测试以「超时」失败也不要无限期挂着。
_SAMPLE_TIMEOUT = 120.0


@functools.cache
def spawn_seconds(samples: int = 3) -> float:
    """量一次裸启动耗时，取中位数（单次采样噪声大）。"""
    costs: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True,
                       timeout=_SAMPLE_TIMEOUT, check=False)
        costs.append(time.perf_counter() - started)
    return sorted(costs)[len(costs) // 2]


def budget(base: float, factor: float = 2.0) -> float:
    """不低于 ``base``，且至少容得下 ``factor`` 次裸启动。

    ``base`` 是正常机器上够用的秒数；``factor`` 越大越宽松，按被启动的进程
    个数选——父进程自己启动是 2，父进程还要再拉起孙进程就用 3 以上。
    """
    return max(base, spawn_seconds() * factor)


def reap_window(child_sleep: float, *, margin: float = 0.3) -> float:
    """等后代「该写却没写」的观察窗口：后代自己的 sleep + 一次启动 + 余量。

    这几个用例的断言是「后代已被收口，所以不该有写入」。窗口贴着后代的
    sleep 走会两头出问题：等太短，慢机器上后代还没轮到写，测试会**假通过**；
    等太长，本来就没必要。按后代自己的 sleep 加上它要启动的时间来算，
    收口真的失效时一定抓得到。
    """
    return child_sleep + spawn_seconds() * 1.5 + margin
