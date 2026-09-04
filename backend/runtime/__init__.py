"""硬件感知模型运行时(Issue:Hardware-Aware Model Runtime)。

- :mod:`hardware` — 真实执行设备发现(CPU/GPU/稳定身份/容量观测);
- :mod:`manager` — MODEL × WORKLOAD × DEVICE 策略解析与单一驻留运行时。

设计契约(冻结):同一模型 + 同一 GPU + Query/Sync → 至多一个活跃驻留实例;
Online Query 优先于 Background Sync;Configured ≠ Effective;容量状态证据驱动。
"""
