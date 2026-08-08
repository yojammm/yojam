#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HBM3 命令调度性能模型——v19.1 中文回归候选版
================================================================

版本信息
--------
版本          : v19.1
发布状态      : mandatory latch 迟滞 + cross-SID 串行 + Age 优先级 + BG-Interleave + RW 4 态机 + Refresh Refine 回归候选版
注释语言      : 中文
行为兼容性    : 继承 v16.3 Refresh Refine 与 v15 READ tRL/txn_id 链表资源；
              新增 RW 4 态调度机 (默认开启, 旧 batch/alternating 走 fallback)
地址单位      : 1 个逻辑地址单位对应 32 字节 ColumnCommand
时间单位      : 1 个模型 cycle = 1 个 DFI cycle = 2 个 HBM CK

模型用途
--------
本模型用于生成 HBM 工作负载、执行地址转换，并在 JEDEC/HBM 时序约束下模拟
ACT、PRE、RD、WR 与 REFpb 等命令的调度过程。模型可用于调度策略验证，以及
8H/12H 配置、随机/线性访问和不同读写组合的相对性能比较。

总体数据流
----------
系统逻辑地址 LA
    │
    ├─ 配置与 density code 解析
    ├─ 访问范围合法性检查
    ├─ 12H SID 重映射（Type0 或 Type1）
    ├─ 地址字段解码（COL/BG/SID/BA/ROW）
    ├─ Transaction 按 page 拆分为 segment
    ├─ 生成 ColumnCommand 与 BurstCommandGroup
    └─ 调度器生成 ACT/PRE/RD/WR/REFpb 命令并统计性能
├─ ColScheduler (v16.4 RW 4 态机, v18/v19/v19.1 同)
├─ RowScheduler (v17 BG 交织, v18 新增 age 优先级, ACT/PRE, 4 态机下按 state 过滤可见 CAM, v19/v19.1 同)
└─ RefreshScheduler (per-SID rolling-set, tRREFD, debt, v19 新增 cross-SID 串行, v19.1 新增 mandatory latch 迟滞)



v19.1 关键特性 (本期新增, 重点)
---------------------------------
1. **mandatory 触发引入 latch 迟滞机制** (`mandatory_latch` + `postpone_low_thr`)
     - 新增 `_mandatory_latch: bool` 字段 (默认 False): 当前是否处于 mandatory 状态
     - 新增 `_mandatory_refresh_count: int` 字段 (默认 0): latch 内已刷的 REFpb 数
     - 新增 `postpone_low_thr: int = 2` 参数: mandatory 进入后至少刷几个 REFpb
       才解除 latch (迟滞, 避免 debt 附近 on/off 抖动); 默认 2
2. **latch 状态机**:
     - 入口: `_update_mandatory_latch()` 在 `try_issue` 与 `is_mandatory_needed`
       入口都调, 仅在 `debt ≥ max_postpone_credits` 且 `_mandatory_latch == False`
       时触发 False→True 跳变, 同时 reset count, `_debt_prevention_trigger_count += 1`
     - 出口: `_issue_mandatory_refpb()` 每发一个 mandatory REFpb, count + 1;
       刷满 `postpone_low_thr` 个后 `_mandatory_latch = False`
     - 幂等: 多次调用不会重复触发
3. **拆开 mandatory 触发阈值 vs 协议硬上限** (从 v19 抽过来):
     - `max_postpone_credits = 8` (REFpb 个数): debt≥该值进入 `mandatory_latch`
       与 `_debt_at_limit_cycles` 等“软预警”路径; 默认 8
     - `postpone_low_thr = 2`: mandatory 进入后至少刷几个 REFpb 才解除 latch
       (迟滞, 避免 debt 附近 on/off 抖动); 默认 2
     - `max_postpone_refab_debt = max_postpone_refab_rounds × num_banks`
       (默认 9×N): 协议硬上限, 仅用于 fail-fast 与 debt 合法范围校验
     - v18 之前两者共用 `max_postpone_credits`, 同时承担“软预警 + 硬上限”,
       数值混淆；v19 解耦后语义更清晰
4. **`is_mandatory` 判定简化**:
     - v19: `is_mandatory = (critical_next_opportunity or prepare_due or _drain_target_bank == target)`
     - v19.1: `is_mandatory = (self._mandatory_latch or prepare_due)`
     - 去掉 `critical_next_opportunity` (由 `_mandatory_latch` 替代, 更稳定)
     - 去掉 `_drain_target_bank == target` (mandatory 不再锁 drain target, 每 cycle 重选)
5. **mandatory 路径改为三段式 tier 选 bank**:
     - tier 1: IDLE + CAM 不命中 + AC timing OK → 直接 REFpb (零干扰)
     - tier 2: IDLE + CAM 命中 + AC timing OK → 直接 REFpb (row 已关, CAM 命令延迟 re-ACT)
     - tier 3: ACTING → force-PRE `candidates[0]` (最紧急); 非 ACTING 或时序不满足则本 cycle 让位
     - 不再像 v19 那样锁 drain target, 避免目标抖动
6. **non-mandatory 路径修复 (遍历)**:
     - 旧实现只试 `candidates[0]` 的 AC timing, 第一个被挡即 return None
     - v19.1 改为遍历整组候选 (rolling-set 剩余 ∩ CAM 未占用), 找第一个 IDLE +
       timing OK 的 bank 发出; 全部不满足才放弃, 避免漏发
7. **新增 `is_mandatory_needed()` 探测方法**:
     - 只判断当前 cycle 是否需要 mandatory REFpb, 不发出命令
     - 编排器用它在 row_scheduler 之前预判, 决定 mandatory REFpb 是否抢占 row bus
     - 内部仍调 `_update_mandatory_latch()` (确保 latch 状态同步)
8. **行为兼容性**:
     - v19 设 `postpone_low_thr = 1` 可等价于 v19 行为 (立即解除 latch, 无迟滞)
     - v18 之前 mandatory 触发路径无迟滞, v19.1 默认 2 个 REFpb 窗口期是新增语义
     - mandatory tier 1/2 优先于 tier 3 force-PRE, 保持对 ACT/PRE 的最小干扰

v19 关键特性 (本期新增, 重点)
-----------------------------
1. **REFpb 调度新增 cross-SID 串行策略**
     - 同一时刻只有一个 SID 的 bank 进入 candidates (rolling-set 选优域)
     - 当前活动 SID 的 rolling-set 全部刷完一次 (16 banks) 后,
       推进到下一个 SID (`_active_sid = (_active_sid + 1) % _num_sid`)
     - 目的: 减少 SID 之间 tRREFD / tFAW / tRRD 闸串扰, 让一个 SID
       在“清静”的 channel 窗口内集中完成一个 set 的 16 个 REFpb,
       避免 12H 多 SID 下不同 SID 的候选彼此拖延
2. 新增字段: `RefreshScheduler._num_sid / _active_sid / _advance_pending`
     - `_active_sid`: 当前活动的 SID
     - `_advance_pending`: 活动 SID 的 set 刚刷完时置 True,
       下次 `_collect_candidates()` 时推进到下一 SID
3. 新增参数: `RefreshScheduler(max_postpone_refab_rounds: int = 9)`
     - 协议 fail-fast 硬上限轮数 (默认 9 ↔ per-bank 间隔 ≤ 9×tREFI,
       对应 JEDEC "refresh postpone all bank" 上限)
4. `_prepare_deadline_cycle` 初值改为 `_hard_deadline_cycle`
     (首个 cycle 即被 `_update_prepare_deadlines` 重算, 初值仅占位)
5. **8-run 性能对比表逻辑提取**: 从 `main()` 抽出 `_write_comparison(runs, log_fp)`,
   让 `main()` 只负责流程编排
6. **行为兼容性**:
     - 单 SID 配置 (8H 2 SID / 4H 1 SID) cross-SID 串行语义退化为“逐 SID 串行刷”,
       与 v18 等价 (仅按 SID 顺序);
     - 4H (1 SID) 配置: `_num_sid=1`, `_active_sid` 始终为 0, 与 v18 完全等价;
     - mandatory 触发路径行为不变, 仅阈值与上限语义解耦.

v18 关键特性 (本期新增, 重点)
-----------------------------
1. **ACT 调度新增 Age 优先级** (`age_priority`, 默认 True)
2. 优先规则: 在所有 eligible bank 中, 优先选**ACT 等待最久**的 bank
     - 目的: 防止个别 bank 因调度偏向而长期得不到 ACT, 保证公平性
3. Age 定义: `current_cycle - min(entry.entry_cycle for entry in cams
   if entry.bank_id == bank.bank_id and not all dispatched)`
     - 即该 bank 上**最老的未派发 burst entry** 的等待 cycle 数
4. 优先级链: age (desc) > BG 交织 (tiebreaker) > RR (last tiebreaker)
5. 新增 `age_priority: bool = True` 参数; 设 False 退回 v17 行为 (无 age 优先级)
6. 新增统计:
     - `age_priority_used` — 实际应用 age 优先级的次数 (即选出的 bank 是 age 最大的)
     - 各 bank ACT 等待时间分布 (sanity, summary 显示)
7. **与 BG 交织优先级组合**: age 选 max 时, 多个并列 age 才看 BG 交织; 不强制 BG
8. **与 RW 4 态机正交**: age 只影响 ACT 选择, 不影响 ColScheduler 状态机

v17 关键特性 (继承, 上版本)
-----------------------------
1. **ACT 调度新增 BG 交织优先级** (`bg_interleave_priority`, 默认 True)
2. 优先规则: 在所有 eligible bank 中, 优先选**同 SID 但不同 BG** 的 bank 进行 ACT
     - 目的: 把 ACT 分散到 SID 内的多个 BG, 提升 BG 级并行, 减少 tRRDL 集中
3. 实现机制:
     - 维护 `self._last_act_bg_per_sid: List[int]` — 每个 SID 上次 ACT 的 BG (初始 -1)
     - 每次 ACT 后更新: `_last_act_bg_per_sid[bank.sid_id] = bank.bank_group_id`
     - 选 bank 时: 优先 `_last_act_bg_per_sid[bank.sid_id] != bank.bank_group_id` 的;
       无候选时 fallback 到"同 BG 或其他 SID"
4. RR 仲裁顺序保持不变, 仅在 RR 之前做 BG 优先级过滤
5. 新增 `num_sid` 参数透传到 RowScheduler (用于初始化 per-SID 跟踪)
6. 统计:
     - `bg_interleave_hits` — 选中 BG 不同的 bank 的次数
     - `bg_interleave_fallback` — 无 BG 不同的候选, 退回同 BG 的次数
7. **向后兼容**: 设 `bg_interleave_priority=False` 恢复 v16.4 行为 (无 BG 优先级, 纯 RR)
8. **与 4 态机正交**: BG 交织优先级只影响 ACT 选择, 不影响 ColScheduler 状态机
9. **与 RW 切换正交**: 切态不重置 BG 跟踪, 跨态切回仍保持 BG 交替节奏

v16.4 关键特性 (继承, 上版本)
-------------------------------
1. **新增 RW 4 态调度状态机** 替换原 batch (stick-to-one-side + preparation phase)
   与 alternating 的"两态 + 隐式 prep"模型。
2. 4 态机状态:
     - RD      : 正常 RD 模式 — 只发 RD CAM 的 ACT + RD
     - WR      : 正常 WR 模式 — 只发 WR CAM 的 ACT + WR
     - RD_WR   : 过渡态 RD→WR — drain RD CAM RD, 同时开 WR CAM 的 ACT
     - WR_RD   : 过渡态 WR→RD — drain WR CAM WR, 同时开 RD CAM 的 ACT
3. 状态转移 (用户规约):
     - RD → WR     : RD CAM 空 且 WR CAM 有活 (直切, 不走过渡)
     - RD → RD_WR  : 当前在 RD, WR CAM 有活, 倒计时 batch_timeout_cycles → 0
     - RD_WR → WR  : WR CAM 有可派发命令 (bank ACT + col ready) 或 RD CAM 已空
                     或 **WR 已开 ≥ preparation_min_banks 个 ACT 且至少 1 个 col ready** (v18.1+)
     - WR → RD     : WR CAM 空 且 RD CAM 有活
     - WR → WR_RD  : 当前在 WR, RD CAM 有活, 倒计时到 0
     - WR_RD → RD  : RD CAM 有可派发命令 或 WR CAM 已空
                     或 **RD 已开 ≥ preparation_min_banks 个 ACT 且至少 1 个 col ready** (v18.1+)
4. **row 视野按 state 通道化**:
     - RD / WR : row 只看对应 mode 的 CAM (不开对向)
     - RD_WR    : row 只看 WR CAM (不开新 RD bank, 让 source RD banks drain)
     - WR_RD    : row 只看 RD CAM (不开新 WR bank, 让 source WR banks drain)
5. **col 派发按 state 限制**:
     - RD / RD_WR : 只发 RD col 命令 (后者是 drain)
     - WR / WR_RD : 只发 WR col 命令 (后者是 drain)
     - 过渡态不开 source 侧新 ACT, 让现有 bank 自然通过 autoprecharge (RDA/WRA) 关闭
6. 初始 state 固定 RD; 纯 R / 纯 W workload 时, 4 态机自然停在单一 state (无影响)。
7. 新增 `rw_4state_mode: bool = True` 参数; 设 False 走原 batch/alternating 行为 (向后兼容)。
8. 新增 `[RW 4 态机统计 (v16.3+)]` summary 段: 直切次数 / 进入过渡次数 / 退出过渡次数 / 各 state 驻留 cycle 数 / 百分比。
9. **性能影响** (num_transactions=2000, 12H 配置):
     - 单边 workload (纯 R / 纯 W) : ±0%
     - 50/50 batch linear : +19.8% (旧 0.74 → 新 0.88)
     - 50/50 batch random : +30.6% (旧 0.64 → 新 0.84)
     - 50/50 alt linear/random: 与 batch 同 (4 态机下 batch_scheduling 标志被忽略)

v16.3 关键特性 (继承自 v16.3 Refresh Refine)
-------------------------------------------
1. 继承 v15 的地址转换、CAM 调度、RDA/WRA、READ tRL 与 txn_id 链表资源模型。
2. 时钟关系按 data rate → DQS → HBM CK → DFI CLK 统一换算；模型内部使用 DFI cycle。
3. REFpb nominal opportunity 按 tREFIpb=ceil(tREFI/总 bank 数) 在 Channel 级产生。
4. Channel refresh debt 定义为 nominal REFpb 数减去实际 REFpb 数，不再按等待 cycle 累加 postpone。
5. 第一版不主动 pull-in；实际 REFpb 数不超前于 nominal opportunity。
6. 每个 SID 独立维护 16-bank rolling-set bitmap，当前 set 内禁止重复刷新同一 bank。
7. 一个 SID 的 16 个 bank 全部完成后标记 set complete；下一 set 首条 REFpb 等待 tRFCpb boundary。
8. 每个 bank 维护 last refresh、normal due 与 9×tREFI hard deadline。
9. REFpb 候选使用无副作用的 rolling-set 查询，并按 prepare/hard deadline、age 与 bank 状态排序。
10. 拆分 normal due、动态 prepare deadline 与 9×tREFI hard deadline；RDA/WRA guard 使用 prepare deadline。
11. tRREFD 按 Channel 全局约束，不因 SID 不同而解除。
12. ACT→REFpb 按同 BG=tRRDL、异 BG=tRRDS 检查。
13. ACT 与 REFpb 共享 Channel 级 tFAW rolling window，窗口内合计最多 4 条。
14. REFpb、debt、force-PRE、tFAW/tRRD/tRREFD block、rolling-set 和 deadline 均提供统计。
15. debt 触发 mandatory 的阈值 = max_postpone_credits (默认 8, REFpb 个数)；协议硬上限 = 9×N (N=num_banks; "refresh postpone all bank" 9 轮 ↔ per-bank 间隔 ≤ 9×tREFI), 超过即 fail-fast。采用"per-bank hard_deadline 提前排空 + channel debt fail-fast"双保险；根据 bank 剩余 tRAS/col-to-PRE/tRP 与 Channel timing 预算启动 mandatory drain。
16. READ/WRITE 分别直接检查 tRCDRD/tRCDWR，不再限制二者大小关系。
17. rolling-set block 统计为 bank-cycle，set-boundary 统计为 SID-cycle，查询函数不再修改 set 状态。
18. Deadline violation 拆分为事件数、违规 cycle 数、唯一违规 bank 数和最大连续违规周期。
19. 当前版本暂未实现主动 pull-in、REFab、RFM 和 self-refresh。
20. Non-mandatory REFpb 候选 bank 过滤: 当 REFpb 不属于 mandatory 时, REFpb 候选 bank 集合剔除 R/W CAM 中仍有未派发命令的 bank; 若剔除后候选为空, REFpb 本 cycle 不发, 等下一 cycle 重试。

v17 改动点 (代码级清单)
---------------------------
新增:
  + `RWState` 枚举 (RD / WR / RD_WR / WR_RD) — 在 RWType 之后
  + `ColScheduler._rw_state: RWState` 字段 (初始 RD)
  + `ColScheduler._rw_switch_timer: int` 字段
  + `ColScheduler._rw_4state_mode: bool` 字段
  + 5 个统计字段 (_direct_switch / _enter_transition / _exit_transition / _cycles_in_state)
  + `ColScheduler._update_rw_state()` 方法 (状态转移)
  + `ColScheduler._try_issue_4state()` 方法 (4 态机主入口)
  + `ColScheduler.get_rw_4state_stats()` getter
  + `_format_rw_4state_stats()` summary 格式化函数
  + `HBMCommandScheduler.rw_4state_mode` 参数 + 透传到 ColScheduler
  + `SimulationConfig.rw_4state_mode` 字段

修改:
  ~ `ColScheduler.try_issue()` 增加 rw_4state_mode 分支
  ~ `ColScheduler.get_row_candidate_cams()` 4 态机路径: 按 state 过滤可见 CAM
  ~ 调度策略 summary 行增加 "4 态机" 选项显示
  ~ 新增 `[RW 4 态机统计 (v16.3+)]` summary 段

兼容:
  ✓ 旧 batch/alternating 行为 (rw_4state_mode=False) 完整保留
  ✓ v15 run_len 约束 (不影响, 在 batch/alternating 路径下生效)
  ✓ v15 链表资源 (与 4 态机正交, 互不影响)

v17 (BG 交织) 改动点 (代码级清单)
----------------------------------
新增:
  + `RowScheduler._last_act_bg_per_sid: List[int]` 字段 (per-SID 上次 ACT 的 BG, 初始 -1)
  + `RowScheduler._bg_interleave_hits: int` 统计 (选中 BG 不同的次数)
  + `RowScheduler._bg_interleave_fallback: int` 统计 (无可用 BG 不同, 退回同 BG 的次数)
  + `RowScheduler._select_act_with_bg_priority()` 方法 (BG 优先 + RR fallback)
  + `RowScheduler.get_bg_interleave_stats()` getter
  + `_format_bg_interleave_stats()` summary 格式化函数
  + `RowScheduler` 新参数 `num_sid: int` 和 `bg_interleave_priority: bool = True`
  + `HBMCommandScheduler.bg_interleave_priority` 参数 + 透传到 RowScheduler

修改:
  ~ `RowScheduler._try_activate()` 选 ACT 改走 `_select_act_with_bg_priority()`
  ~ `try_issue()` 后置统计: ACT 后更新 `_last_act_bg_per_sid[bank.sid_id]`
  ~ 新增 `[BG 交织 ACT 统计 (v17+)]` summary 段
  ~ 调度策略 summary 行增加 "BG 交织" 选项显示 (HBMCommandScheduler._build_summary_lines)

兼容:
  ✓ 旧 RR 行为 (bg_interleave_priority=False) 完整保留
  ✓ v16.4 RW 4 态机不受影响 (BG 交织只影响 ACT 选择, 跟 ColScheduler 状态机正交)
  ✓ RefreshScheduler / ColScheduler 内部状态完全不动
  ✓ per-SID BG 跟踪天然处理 SID 维度, 不需 SID 索引参数外暴露

v18 改动点 (代码级清单)
------------------------
新增:
  + `RowScheduler._age_priority: bool` 字段
  + `RowScheduler._age_priority_used: int` 统计 (age 实际生效的次数)
  + `RowScheduler._max_age_seen: int` 统计 (见过的最大 age)
  + `RowScheduler._compute_bank_act_age()` 方法 (算 bank 的 ACT 等待年龄)
  + `RowScheduler._select_act_with_age_priority()` 方法 (age 优先 + BG 交织 + RR 三级排序)
  + `RowScheduler.get_age_priority_stats()` getter
  + `_format_age_priority_stats()` summary 格式化函数
  + `RowScheduler` 新参数 `age_priority: bool = True`
  + `HBMCommandScheduler.age_priority` 参数 + 透传到 RowScheduler

修改:
  ~ `RowScheduler._try_activate()` 选 ACT 改走 `_select_act_with_age_priority()`
    (age_priority=True 时), 否则走 v17 的 `_select_act_with_bg_priority()`
  ~ 新增 `[Age 优先级 ACT 统计 (v18+)]` summary 段
  ~ 调度策略 summary 行增加 "Age" 选项显示 (ON / OFF)

兼容:
  ✓ v17 BG 交织行为完整保留 (age_priority=False)
  ✓ v16.4 RW 4 态机不受影响
  ✓ 与 refresh / col scheduler 内部状态完全正交

12H Type0 地址映射
------------------
COL[2:0]  = LA[2:0]
BG[1:0]   = LA[4:3]
SID[1:0]  = LA[6:5]
BA[1:0]   = LA[8:7]
ROW[14:0] = LA[23:9]
LA[25:24] 保留为 Type0 SID 重映射顶部交换位。

地址处理顺序
------------
系统地址范围检查 → 12H SID 重映射 → 地址字段解码 → page segment 生成。

维护约束
--------
* 修改地址映射时，必须同步检查地址位唯一性、容量范围和 SID 合法性。
* 12H 有效 SID 为 0、1、2；原始 SID=3 必须在解码前完成重映射。
* REFpb postpone debt、per-SID rolling-set、per-bank hard deadline 与 timing block 必须保持独立语义。
* rolling-set 仅决定下一条 REFpb 可选择的 bank；tFAW、tRRD、tRREFD 仍是 Channel 级约束。
* 当前无主动 pull-in，若后续加入，应单独维护 refresh balance，并检查相应窗口限制。
* v15 链表/RL 资源仍要求每 cycle 最多申请 4 个节点、释放 1 个头节点。
* v17 RW 4 态机是 ColScheduler 的可选模式（默认开），不影响 RowScheduler 和 RefreshScheduler 内部状态。
* v17 4 态机下，batch_scheduling 标志被忽略；切回原行为需显式设 rw_4state_mode=False。
* v17 BG 交织优先级是 RowScheduler 的可选 ACT 选优 (默认开), 切回原行为需设 bg_interleave_priority=False。
* v17 BG 跟踪仅按 SID 索引, 切态 (R/W 4 态机) 不重置, 跨态保持 BG 交替节奏。
* v18 Age 优先级是 RowScheduler 的可选 ACT 选优 (默认开), 切回 v17 需设 age_priority=False。
* v18 Age 跟踪基于 CAM 中 burst entry 的 entry_cycle, 切态不重置 (与 BG 跟踪一致).

版本演进摘要
------------
v1-v4 : 基础调度、时序与刷新框架。
v5    : 可读性重构，拆分时钟、时序、bank、行/列调度与报告模块。
v6    : 上游准入、读写独立节流与 HBM SID 布局修正。
v7-v8 : 配置、密度与多堆叠高度支持逐步完善。
v9    : page segment、dispatch_id 与 12H SID remap 集成。
v10   : 更新 12H Type0 地址映射并完成 8H/12H 128B 回归。
v11   : 将 tRREFD 从 per-SID 修正为 Channel 全局约束。
v12   : CAM 内同 page Write 连续派发；最后一个 page-hit 使用 WRA。
v13   : CAM 内同 page Read 连续派发；最后一个 page-hit 使用 RDA。
v14   : 同类型 CAM 中无相同 page 请求时，segment 最后一条直接使用 RDA/WRA。
v15   : 引入 READ tRL、txn_id 链表资源池与头节点释放规则；统一 HBM CK/DFI 换算。
v16   : 重构 REFpb：Channel opportunity/debt、per-SID rolling-set、tRFCpb set boundary、
        per-bank 9×tREFI deadline、deadline-aware 调度，以及 ACT+REFpb tFAW/ACT→REFpb tRRD。
v16.1 : debt≤8 改为 fail-fast 硬约束；deadline violation 统计拆分。
v16.2 : 修复独立 tRCDRD/tRCDWR eligibility；以最坏准备时延驱动 debt 预防；
        rolling-set 查询去副作用并修正统计语义；拆分 normal/prepare/hard deadline；
        完成标准 16 组、多 seed 与 refresh 压力回归。
v16.3 : Non-mandatory REFpb 选 bank 时过滤 CAM 占用 bank (cam_busy_banks filter)；
        完成 8H/12H 16-case 32-run 性能对比 (几何平均 +0.49%)。
v17   : 新增 RW 4 态调度状态机 (RD/WR/RD_WR/WR_RD)，替换原 batch + prep 的隐式 2 态；
        50/50 batch perf +20%~+30%；保持向后兼容 (rw_4state_mode=False)。
v17.1 : 注释级 patch, 仅重定义性能统计区间。READ 区间延伸到最后一个 link node
        释放, WRITE 区间保持末条命令发出, 混合 workload 取两类区间长度最大值。
        调度策略、时序参数、refresher 逻辑、LinkListManager 均无变动。
v17+  : (合并入 v18) ACT 调度新增 BG 交织优先级 (同 SID 不同 BG 优先 ACT),
        把 ACT 分散到多 BG 提升 BG 级并行, 减少 tRRDL 集中; 与 4 态机正交;
        默认开, 可关 (bg_interleave_priority=False)。
v18   : ACT 调度新增 Age 优先级 (ACT 等待最久的 bank 优先), 防止调度偏向;
        优先级链: age (desc) > BG 交织 (tiebreaker) > RR; 默认开, 可关 (age_priority=False).
v19   : REFpb 调度新增 cross-SID 串行 (同一时刻只一个 SID 进 candidates, 刷完推进到下一 SID); 拆开 mandatory 触发阈值与协议硬上限 (max_postpone_credits=8 / max_postpone_refab_rounds=9×N); 8-run 性能对比表逻辑提取为 _write_comparison(runs, log_fp)。
v19.1 : REFpb mandatory 引入 latch 迟滞机制 (`mandatory_latch` + `postpone_low_thr`, 默认 2); `is_mandatory` 判定简化为 `_mandatory_latch or prepare_due`; mandatory 路径改三段式 tier 选 bank (tier1 IDLE+CAM空闲 / tier2 IDLE+CAM命中 / tier3 force-PRE); non-mandatory 路径修复整组候选遍历, 避免漏发.
"""

import math
import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, TextIO


# ============================================================
#  常量
# ============================================================

INITIAL_CYCLE_SENTINEL: int = -10**9   #: "无限远的过去" 哨兵
# v6.6: R/W 独立节流 (上游真实时序)
# - R 实时, 1 cycle / entry (无 col 累加器)
# - W 上游 col-level 累加, 满 entry col 数才下发, 节流 = entry 内 col 数
# - R 跟 W 节流独立 (互不阻塞)
# BURST_ADMIT_INTERVAL_CYCLES (统一 4 cycle 节流) 已弃用, 见 commit_msg_v6.6
R_ADMIT_INTERVAL_CYCLES: int = 1      #: R 准入间隔, 1 cycle / entry (实时)
COMMAND_SIZE_BYTES: int = 32             #: 一个 ColumnCommand 对应的连续数据粒度
MAX_CYCLES_FACTOR: int = 100           #: max_cycles = total_cmds × 此值
# v15: 链表/RL 默认配置
DEFAULT_T_RL_NS: float = 53.0             #: READ 读返回时延默认 53 ns
DEFAULT_LINK_NODE_COUNT: int = 192        #: 总链路节点数上限
DEFAULT_LINK_LIST_COUNT: int = 31         #: 链表条数上限
LINK_NODE_GRANT_PER_CYCLE: int = 4        #: 每 cycle 最多申请的 link node 数 (= burst 长度)
LINK_NODE_FREE_PER_CYCLE: int = 1         #: 每 cycle 最多释放的 link node 数 (= 每 cycle 读返回数)


# ============================================================
#  HBM3 SID 组织结构（依据 JESD238B.01 Table 5 与 Note 7）
# ============================================================
#   4H (16 banks)  : 1 SID × 4 groups × 4 banks
#   8H (32 banks)  : 2 SID × 4 groups × 4 banks
#   12H (48 banks) : 3 SID × 4 groups × 4 banks  (NOTE 7: SID[1:0]=11 invalid → 3 SID)
#   16H (64 banks) : 4 SID × 4 groups × 4 banks
# 4 banks per bank group, N SID × groups_per_sid bank groups × 4 banks
# (12H 实际只有 3 SID, 不是 4 SID — v6.4 改错了, v6.5 修正)
SID_LAYOUT_TABLE = {
    16: (1, 4),    # (num_sid, groups_per_sid)
    32: (2, 4),
    48: (3, 4),    # v6.5 修正: per JESD238B.01 Table 5 NOTE 7, 48 banks SID[1:0]=11 invalid
    64: (4, 4),
}


# ============================================================
#  HBM 配置、密度编码与 SID 重映射
# ============================================================
# density_code 为用户提供的 JEDEC 风格 4 位密度/配置编码。
# 默认编码：
#   8H  -> 0001
#   12H -> 0010
# 特殊 12H 9Gb/PC 使用 1010，并要求采用 Type1 重映射。
CONFIGURATION_TO_BANKS = {"4H": 16, "8H": 32, "12H": 48, "16H": 64}
BANKS_TO_CONFIGURATION = {v: k for k, v in CONFIGURATION_TO_BANKS.items()}
DEFAULT_DENSITY_CODE = {"8H": 0b0001, "12H": 0b0010}

# max_system_la 使用 ColumnCommand 地址单位（每单位 32B），与仿真器 LA 定义一致。
# 对传统 4H/16H 配置保留原有地址范围。
DENSITY_CONFIG_TABLE = {
    ("4H", None):   {"effective_bits": 24, "max_system_la": 1 << 24, "sid_remap_type": None},
    ("8H", 0b0001): {"effective_bits": 25, "max_system_la": 1 << 25, "sid_remap_type": None},
    ("12H", 0b0010): {"effective_bits": 26, "max_system_la": 3 << 24, "sid_remap_type": 0},
    ("12H", 0b1010): {"effective_bits": 26, "max_system_la": 9 << 22, "sid_remap_type": 1},
    ("16H", None):  {"effective_bits": 26, "max_system_la": 1 << 26, "sid_remap_type": None},
}

# 未启用 SID 重映射的配置继续使用兼容旧版本的地址映射。
LEGACY_DEFAULT_ADDR_MAP = {
    "col0pos": 0, "col1pos": 1, "col2pos": 2, "col3pos": 8, "col4pos": 9,
    "ba0pos": 6, "ba1pos": 7,
    "bg0pos": 3, "bg1pos": 4,
    "sid0pos": 5, "sid1pos": 25,
}
for _i in range(15):
    LEGACY_DEFAULT_ADDR_MAP[f"row{_i}pos"] = 10 + _i

# 12H Type0 地址映射（v10 统一定义）。
# COL[2:0]=LA[2:0], BG[1:0]=LA[4:3], SID[1:0]=LA[6:5],
# BA[1:0]=LA[8:7], ROW[14:0]=LA[23:9].
# LA[25:24] 保留为 Type0 重映射使用的顶部两位。
DEFAULT_ADDR_MAP_12H_TYPE0 = {
    "col_bits": 3,
    **{f"col{i}pos": i for i in range(3)},
    "bg0pos": 3, "bg1pos": 4,
    "sid0pos": 5, "sid1pos": 6,
    "ba0pos": 7, "ba1pos": 8,
}
for _i in range(15):
    DEFAULT_ADDR_MAP_12H_TYPE0[f"row{_i}pos"] = 9 + _i

# 12H Type1 默认映射，依据 sid_remap.docx。
# ROW[14:13] at UIF[25:24], auxiliary ROW[10:9] at UIF[23:22], SID at UIF[8:7].
DEFAULT_ADDR_MAP_12H_TYPE1 = {
    **{f"col{i}pos": i for i in range(5)},
    "ba0pos": 5, "ba1pos": 6,
    "sid0pos": 7, "sid1pos": 8,
    "bg0pos": 9, "bg1pos": 10,
}
for _i in range(9):
    DEFAULT_ADDR_MAP_12H_TYPE1[f"row{_i}pos"] = 11 + _i
DEFAULT_ADDR_MAP_12H_TYPE1.update({
    "row9pos": 22, "row10pos": 23,
    "row11pos": 20, "row12pos": 21,
    "row13pos": 24, "row14pos": 25,
})

# 为兼容旧调用方保留的导出名称。
DEFAULT_ADDR_MAP = LEGACY_DEFAULT_ADDR_MAP


def _compute_sid_layout(num_banks: int, banks_per_bank_group: int = 4) -> Tuple[int, int]:
    """根据总 bank 数计算 SID 数量以及每个 SID 的 bank group 数。"""
    if num_banks not in SID_LAYOUT_TABLE:
        raise ValueError(f"unsupported num_banks={num_banks} (expect 16/32/48/64)")
    num_sid, groups_per_sid = SID_LAYOUT_TABLE[num_banks]
    if num_banks != num_sid * groups_per_sid * banks_per_bank_group:
        raise ValueError("num_banks/banks_per_bank_group is inconsistent with HBM SID layout")
    return num_sid, groups_per_sid


def _bank_id_to_sid(bank_id: int, banks_per_bank_group: int, groups_per_sid: int) -> int:
    """将全局 bank_id 转换为对应的 SID 编号。"""
    return (bank_id // banks_per_bank_group) // groups_per_sid


def _bank_id_to_sid_bg_ba(bank_id: int, banks_per_bank_group: int,
                           groups_per_sid: int) -> Tuple[int, int, int]:
    """将全局 bank_id 解码为 SID、BG 与 BA。"""
    sid = (bank_id // banks_per_bank_group) // groups_per_sid
    bg = (bank_id // banks_per_bank_group) % groups_per_sid
    ba = bank_id % banks_per_bank_group
    return sid, bg, ba


def _normalize_configuration(num_banks: int, configuration: Optional[str],
                             density_code: Optional[int]) -> Tuple[str, Optional[int], dict]:
    """校验并规范化堆叠配置、density code 与派生几何参数。"""
    expected = BANKS_TO_CONFIGURATION.get(num_banks)
    if expected is None:
        raise ValueError(f"unsupported num_banks={num_banks}; expect 16/32/48/64")
    config = expected if configuration is None else configuration.upper()
    if config not in CONFIGURATION_TO_BANKS:
        raise ValueError(f"unsupported configuration={configuration!r}; expect 4H/8H/12H/16H")
    if CONFIGURATION_TO_BANKS[config] != num_banks:
        raise ValueError(f"configuration={config} requires num_banks={CONFIGURATION_TO_BANKS[config]}, got {num_banks}")
    if density_code is None:
        density_code = DEFAULT_DENSITY_CODE.get(config)
    if density_code is not None and not 0 <= density_code <= 0b1111:
        raise ValueError(f"density_code must be a 4-bit value, got {density_code}")
    key = (config, density_code) if config in ("8H", "12H") else (config, None)
    if key not in DENSITY_CONFIG_TABLE:
        raise ValueError(f"unsupported configuration/density combination: {config}, {density_code:04b}")
    return config, density_code, dict(DENSITY_CONFIG_TABLE[key])


def _default_addr_map_for(remap_type: Optional[int]) -> dict:
    """根据 SID 重映射类型返回默认地址映射副本。"""
    if remap_type == 0:
        return dict(DEFAULT_ADDR_MAP_12H_TYPE0)
    if remap_type == 1:
        return dict(DEFAULT_ADDR_MAP_12H_TYPE1)
    return dict(LEGACY_DEFAULT_ADDR_MAP)


def _validate_addr_map(addr_map: dict, remap_type: Optional[int], effective_bits: int) -> None:
    """检查地址映射字段完整性、位位置唯一性以及重映射约束。"""
    col_bits = int(addr_map.get("col_bits", 5))
    if col_bits <= 0:
        raise ValueError("addr_map col_bits must be positive")
    names = ([f"col{i}pos" for i in range(col_bits)] + [f"ba{i}pos" for i in range(2)] +
             [f"bg{i}pos" for i in range(2)] + [f"sid{i}pos" for i in range(2)] +
             [f"row{i}pos" for i in range(15)])
    missing = [n for n in names if n not in addr_map]
    if missing:
        raise ValueError(f"addr_map missing fields: {missing}")
    positions = [addr_map[n] for n in names]
    if len(set(positions)) != len(positions):
        raise ValueError("addr_map bit positions must be unique")
    if min(positions) < 0 or max(positions) >= 26:
        raise ValueError("addr_map positions must be within the 26-bit UIF address")
    if remap_type is not None:
        top = {effective_bits - 2, effective_bits - 1}
        sid = {addr_map["sid0pos"], addr_map["sid1pos"]}
        if top & sid:
            raise ValueError("12H SID remap requires SID bits not to overlap UIF top two bits")
    if remap_type == 1:
        if {addr_map["row13pos"], addr_map["row14pos"]} != {effective_bits - 2, effective_bits - 1}:
            raise ValueError("12H type-1 requires ROW[14:13] at UIF top two bits")
        aux = {addr_map["row9pos"], addr_map["row10pos"]}
        if aux != {effective_bits - 4, effective_bits - 3}:
            raise ValueError("12H type-1 requires ROW[10:9] at UIF next-highest two bits")


def _extract_addr_fields(la: int, addr_map: dict) -> Tuple[int, int, int, int, int]:
    """按照地址映射从 UIF 地址提取 COL、BA、BG、SID 与 ROW。"""
    def _extract_field(base_name: str, num_bits: int) -> int:
        value = 0
        for i in range(num_bits):
            value |= ((la >> addr_map[f"{base_name}{i}pos"]) & 1) << i
        return value
    col_bits = int(addr_map.get("col_bits", 5))
    return (_extract_field("col", col_bits), _extract_field("ba", 2),
            _extract_field("bg", 2), _extract_field("sid", 2),
            _extract_field("row", 15))


def _get_bits(value: int, positions: Tuple[int, int]) -> int:
    """从指定的两个位位置提取一个 2 位字段。"""
    return ((value >> positions[0]) & 1) | (((value >> positions[1]) & 1) << 1)


def _set_bits(value: int, positions: Tuple[int, int], bits: int) -> int:
    """将 2 位字段写入指定的两个位位置并返回新值。"""
    for i, pos in enumerate(positions):
        value = (value & ~(1 << pos)) | (((bits >> i) & 1) << pos)
    return value


def _remap_12h_la(system_la: int, addr_map: dict, remap_type: Optional[int],
                   effective_bits: int) -> int:
    """对 12H 地址执行 Type0/Type1 SID 重映射，避免产生非法 SID=3。"""
    if remap_type is None:
        return system_la
    top_pos = (effective_bits - 2, effective_bits - 1)  # LSB, MSB of two-bit group
    sid_pos = (addr_map["sid0pos"], addr_map["sid1pos"])
    top = _get_bits(system_la, top_pos)
    sid = _get_bits(system_la, sid_pos)
    mapped = system_la
    if remap_type == 0:
        if sid == 0b11:
            mapped = _set_bits(mapped, sid_pos, top)
            mapped = _set_bits(mapped, top_pos, 0b11)
        return mapped

    # type 1 mapping table from sid_remap.docx.
    aux_pos = (addr_map["row9pos"], addr_map["row10pos"])
    aux = _get_bits(system_la, aux_pos)
    if top in (0b00, 0b01) and sid == 0b11:
        mapped = _set_bits(mapped, top_pos, 0b10)
        mapped = _set_bits(mapped, sid_pos, 0b01 if top == 0b00 else 0b10)
    elif top == 0b10:
        # Protocol-contiguous upper range requires aux=00 before remap.
        if aux != 0:
            raise ValueError(f"invalid type-1 system address: top=10 requires aux=00, la={system_la}")
        mapped = _set_bits(mapped, aux_pos, sid)
        mapped = _set_bits(mapped, sid_pos, 0b00)
    return mapped


def _is_la_valid(la: int, max_system_la: int) -> bool:
    """判断逻辑地址是否位于当前配置允许的系统地址范围内。"""
    return 0 <= la < max_system_la


def _gen_linear_la(txn_id: int, cmds_per_transaction: int, max_system_la: int) -> int:
    """生成合法的线性逻辑地址；必要时在工作负载边界回绕。"""
    if cmds_per_transaction > max_system_la:
        raise ValueError("one workload is larger than the protocol address range")
    max_start = max_system_la - cmds_per_transaction
    slots = max_start // cmds_per_transaction + 1
    return (txn_id % slots) * cmds_per_transaction


def _gen_random_la(rng: random.Random, cmds_per_transaction: int,
                   max_system_la: int) -> int:
    """在 density code 定义的完整合法地址范围内生成随机逻辑地址。

    地址以一个 workload 为单位对齐。最后一个合法起始地址必须满足：
        base_la + cmds_per_transaction - 1 < max_system_la

    因此随机槽位数量完全由 ``max_system_la`` 和 workload 大小决定，
    不再使用历史 ``ROW_ID_MAX`` 限制随机工作集。
    """
    if cmds_per_transaction > max_system_la:
        raise ValueError("one workload is larger than the protocol address range")
    max_start = max_system_la - cmds_per_transaction
    max_slot = max_start // cmds_per_transaction
    return rng.randint(0, max_slot) * cmds_per_transaction


WL_TWTR_OFFSET: int = 2                #: WL+2+tWTR 公式里的 +2 (spec Table 33)
RW_RNG_SEED_OFFSET: int = 1            #: R/W RNG 相对主 RNG 的 seed 偏移
BURST_GROUP_SIZE: int = 4              #: 每个 burst command group 的命令数上限
STUCK_FALLBACK_CYCLES: int = 4         #: 当前 mode 连续卡死多少 cycle 允许 stuck-fallback (> tCCDl 气泡)


# ============================================================
#  枚举
# ============================================================

class BankState(Enum):
    """描述单个 DRAM bank 的状态枚举。"""
    IDLE          = 0
    ACT_WAIT      = 1
    ACTING        = 2
    PRE_WAIT      = 3
    AUTO_PRE_WAIT = 4   #: WRA/RDA 后等待内部 precharge 完成，不占用 Row command bus
    REFRESHING    = 5   #: per-bank refresh 期间, row + col 命令都被拒


class RWType(Enum):
    """描述读命令与写命令类型。"""
    READ  = "READ"
    WRITE = "WRITE"
    NONE  = "NONE"


class RWState(Enum):
    """ 4 态 R/W 调度状态机.

    4 个状态语义:
      RD     : 正常 RD 模式 — 只发 RD CAM 的 ACT + RD
      WR     : 正常 WR 模式 — 只发 WR CAM 的 ACT + WR
      RD_WR  : 过渡态 RD→WR — drain RD CAM RD, 同时开 WR CAM 的 ACT
      WR_RD  : 过渡态 WR→RD — drain WR CAM WR, 同时开 RD CAM 的 ACT

    状态转移:
      RD → WR     : RD CAM 空 且 WR CAM 有活 (直接切, 不走过渡)
      RD → RD_WR  : 当前在 RD 状态, WR CAM 有活, 倒计时 batch_timeout_cycles 到 0 时
      RD_WR → WR  : WR CAM 有可派发命令 (bank ACT + col ready) 或 RD CAM 已空
                     或 WR 已开 ≥ preparation_min_banks 个 ACT 且至少 1 个 col ready
      WR → RD     : WR CAM 空 且 RD CAM 有活
      WR → WR_RD  : 当前在 WR 状态, RD CAM 有活, 倒计时到 0 时
      WR_RD → RD  : RD CAM 有可派发命令 或 WR CAM 已空
                     或 RD 已开 ≥ preparation_min_banks 个 ACT 且至少 1 个 col ready
    """
    RD    = "RD"
    WR    = "WR"
    RD_WR = "RD_WR"   #: 过渡: drain RD + open WR
    WR_RD = "WR_RD"   #: 过渡: drain WR + open RD


class RowCommandType(Enum):
    """描述行命令类型，包括 ACT 与 PRE。"""
    ACT = "ACT"
    PRE = "PRE"
    REFPB = "REFpb"   #: per-bank refresh (HBM3 标配, REFab 暂不实现)


def _opposite_type(rw_type: RWType) -> RWType:
    """READ ↔ WRITE (仅用于 batch 调度, 不会传入 NONE)"""
    return RWType.WRITE if rw_type == RWType.READ else RWType.READ


def _format_preparation_stats(stats: dict) -> List[str]:
    """把 ColScheduler.get_preparation_stats() 的 dict 格式化成 summary 行.

    三种切换路径:
      empty_fallback  — current 模式 CAM 空, 跳切到对向 (最频繁, 50/50 主导)
      atomic_switch   — timeout 触发, target 已 ready, 不进 prep
      prep phase      — timeout 触发, target 未 ready, 走准备期 (细分子: ready/max_dispatches/current_empty)
    """
    phase_count = stats['phase_count']
    total_cycles = stats['total_cycles']
    exits = stats['exit_counts']
    atomic = stats.get('atomic_switch_count', 0)
    empty = stats.get('empty_fallback_count', 0)
    total = stats.get('total_switch_count', phase_count + atomic + empty)
    return [
        f"    总切换次数          : {total}",
        f"      ├ empty-fallback  : {empty}  (current CAM 空, 跳切对向 — 50/50 主导)",
        f"      ├ atomic (timeout): {atomic} (timeout 触发, target ready, 跳 prep)",
        f"      └ prep phase      : {phase_count}  (timeout 触发, target 未 ready)",
        f"    drain 派发次数      : {stats.get('drain_dispatch_count', 0)}  "
        f"(in-flight 对向 txn 续发, 防 stranding)",
        f"    准备期总 cycle 数   : {total_cycles}",
        f"    退出分布            : "
        f"ready={exits.get('ready', 0)}, "
        f"max_dispatches={exits.get('max_dispatches', 0)} (degraded), "
        f"current_empty={exits.get('current_empty', 0)} (CAM 物理空, degraded), "
        f"prep_timeout={exits.get('prep_timeout', 0)} (degraded)",
    ]


def _format_refresh_stats(stats: dict) -> List[str]:
    """格式化 Channel debt、per-SID rolling-set 与 REFpb timing 统计。"""
    lines = [
        f"    REFpb 总数              : {stats['refresh_count']}",
        f"    tREFIpb                 : {stats.get('t_refi_pb_cycles', 0)} cycles",
        f"    nominal opportunities   : {stats.get('nominal_refpb_count', 0)}",
        f"    当前/最大 debt          : {stats.get('current_debt', 0)} / {stats.get('max_debt', 0)}",
        f"    debt 偿还次数           : {stats.get('debt_repaid_count', 0)}",
        f"    debt=上限 cycle         : {stats.get('debt_at_limit_cycles', 0)}",
        f"    debt overflow           : {stats.get('debt_overflow_count', 0)}",
        f"    force-PRE 次数          : {stats['force_pre_count']}",
        f"    tRAS 等待               : {stats['t_ras_wait_count']}",
        f"    col-to-PRE 等待         : {stats['t_col2pre_wait_count']}",
        f"    REFpb tRREFD 阻塞       : {stats.get('rrefd_blocked_count', 0)}",
        f"    ACT→REFpb tRRD 阻塞     : {stats.get('trrd_refpb_blocked_count', 0)}",
        f"    ACT+REFpb tFAW 阻塞     : {stats.get('tfaw_refpb_blocked_count', 0)}",
        f"    rolling-set blocked bank-cycles : {stats.get('rolling_set_blocked_bank_cycles', 0)}",
        f"    set-boundary blocked SID-cycles  : {stats.get('set_boundary_blocked_sid_cycles', 0)}",
        f"    最大 bank refresh interval: {stats.get('max_refresh_interval', 0)} cycles",
        f"    9×tREFI 违规事件数      : {stats.get('hard_deadline_violation_event_count', 0)}",
        f"    9×tREFI 违规 cycle 数   : {stats.get('hard_deadline_violation_cycle_count', 0)}",
        f"    9×tREFI 唯一违规 bank 数: {stats.get('hard_deadline_violated_bank_count', 0)}",
        f"    最大连续违规周期        : {stats.get('hard_deadline_max_consecutive_cycles', 0)}",
        f"    ── ref_priority 策略统计 ──",
        f"    non-mandatory 让位给 row : {stats.get('non_mandatory_yield_count', 0)}",
        f"    non-mandatory 兜底发出   : {stats.get('non_mandatory_fallback_issued_count', 0)}",
        f"    non-mandatory REFpb 发出 : {stats.get('non_mandatory_refpb_count', 0)}",
        f"    non-mandatory opportunity: {stats.get('non_mandatory_opportunity_cycles', 0)}",
    ]
    for sid, item in stats.get('sid_stats', {}).items():
        lines.append(
            f"    SID{sid}: completed_sets={item['completed_sets']}, "
            f"set={item['current_set_id']}, progress={item['current_progress']}/16, "
            f"max_set_duration={item['max_set_duration']}")
    return lines


def _format_preparation_history(history: List[dict],
                                max_lines: int = 50) -> List[str]:
    """把 ColScheduler.get_preparation_history() 格式化成 per-prep 明细表.

    每行: 序号 | start_cycle | end_cycle | dur | target | snapshot_banks
          | disp(current) | act(target) | pre(target) | exit_reason

    行数太多时 (>max_lines) 截断, 保留首尾各 max_lines//2, 中间用省略行代替.
    """
    if not history:
        return ["    (无准备期)"]

    def _row(idx: int, p: dict) -> str:
        return (f"    {idx:>4}  {p['start_cycle']:>6}  {p['end_cycle']:>6}  "
                f"{p['duration']:>4}  {p['target']:>5}  {p['snapshot_banks']:>3}  "
                f"{p['dispatch_count']:>3}  {p['act_count']:>3}  {p['pre_count']:>3}  "
                f"{p['exit_reason']}")

    header = (f"      #  start  end   dur  target  banks  disp  act  pre  exit_reason\n"
              f"    {'─'*4}  {'─'*5}  {'─'*5}  {'─'*3}  {'─'*5}  {'─'*5}  "
              f"{'─'*4}  {'─'*3}  {'─'*3}  {'─'*11}")

    lines = [header]
    n = len(history)
    if n <= max_lines:
        for i, p in enumerate(history, 1):
            lines.append(_row(i, p))
    else:
        half = max_lines // 2
        for i, p in enumerate(history[:half], 1):
            lines.append(_row(i, p))
        lines.append(f"    ... ({n - max_lines} more prep phases omitted) ...")
        for i, p in enumerate(history[-half:], n - half + 1):
            lines.append(_row(i, p))
    return lines


def _format_sid_aware_stats(stats: dict) -> List[str]:
    """把 ColScheduler.get_sid_aware_stats() 格式化成 summary 行.

    字段:
      enabled            — 开关是否打开
      same_sid_hits      — 选了同 SID 的次数
      cross_sid_fallback — 同 SID 池空, 退到跨 SID 池的次数
      total_decisions    — same + cross 总数
      same_sid_ratio     — same / total (越高代表单 SID 内排队压力越大)
    """
    if not stats['enabled']:
        return ["    (SID-aware 关闭, 走默认 RR; 开: sid_aware=True)"]
    return [
        f"    enabled             : True",
        f"    same_sid_hits       : {stats['same_sid_hits']}  (选了同 SID, 跳过 tCCDR 检查)",
        f"    cross_sid_fallback  : {stats['cross_sid_fallback']}  (同 SID 池空, 退到跨 SID 池)",
        f"    total_decisions     : {stats['total_decisions']}",
        f"    same_sid_ratio      : {stats['same_sid_ratio']:.3f}  "
        f"(= same / total, 接近 1 = 同 SID 总是有活, 跨 SID 极少)",
    ]


def _format_rw_4state_stats(stats: dict) -> List[str]:
    """把 ColScheduler.get_rw_4state_stats() 格式化成 summary 行.

    字段:
      enabled                    — rw_4state_mode 是否开启
      current_state              — 仿真末 state
      direct_switch_count        — CAM 空触发的直切 (RD→WR / WR→RD)
      enter_transition_count     — 进入 RD_WR / WR_RD 次数
      exit_transition_count      — 退出过渡态次数
      exit_via_target_act_count  — 退出过渡态时, 触发原因是
                                   "对向已开 ≥ preparation_min_banks 个 ACT" 的次数
      cycles_in_state            — 各 state 驻留 cycle 数
    """
    if not stats['enabled']:
        return [f"    4 态机               : 禁用 (走原 batch/alternating 模式)"]
    cis = stats['cycles_in_state']
    total_cycles = sum(cis.values()) or 1
    return [
        f"    enabled              : True (RD/WR/RD_WR/WR_RD 四态机)",
        f"    仿真末 state         : {stats['current_state']}",
        f"    直切次数 (CAM 空触发): {stats['direct_switch_count']}  "
        f"(RD→WR / WR→RD)",
        f"    进入过渡态次数       : {stats['enter_transition_count']}  "
        f"(timeout 倒计时到 0 触发 RD_WR / WR_RD)",
        f"    退出过渡态次数       : {stats['exit_transition_count']}  "
        f"(target dispatchable / source CAM 空 / 对向 ACT≥N+col ready)",
        f"    退出: 对向 ACT≥N+col : {stats['exit_via_target_act_count']}  "
        f"(target ACT bank ≥ preparation_min_banks 且 ≥1 个 col ready, 提前切)",
        f"    状态驻留 (cycle)     : RD={cis['RD']:>5d} ({cis['RD']/total_cycles*100:5.1f}%), "
        f"WR={cis['WR']:>5d} ({cis['WR']/total_cycles*100:5.1f}%), "
        f"RD_WR={cis['RD_WR']:>4d} ({cis['RD_WR']/total_cycles*100:4.1f}%), "
        f"WR_RD={cis['WR_RD']:>4d} ({cis['WR_RD']/total_cycles*100:4.1f}%)",
    ]


def _format_bg_interleave_stats(stats: dict) -> List[str]:
    """v17+: 把 RowScheduler.get_bg_interleave_stats() 格式化成 summary 行.

    字段:
      enabled              — bg_interleave_priority 是否开启
      bg_interleave_hits   — 选中 BG 不同于同 SID 上次 ACT 的次数
      bg_interleave_fallback— 无可用不同 BG, 退回原 RR 的次数
      last_act_bg_per_sid  — 各 SID 当前 last ACT 的 BG (sanity)
    """
    if not stats['enabled']:
        return [f"    BG 交织优先级       : 禁用 (走原 RR)"]
    hits = stats['bg_interleave_hits']
    fb = stats['bg_interleave_fallback']
    total = hits + fb
    ratio = hits / total * 100 if total > 0 else 0.0
    last_bg = stats['last_act_bg_per_sid']
    last_bg_str = ", ".join(f"SID{i}={bg}" for i, bg in enumerate(last_bg))
    return [
        f"    enabled             : True (同 SID 不同 BG 优先 ACT)",
        f"    BG 交织命中         : {hits}  (选中 BG 不同于同 SID 上次 ACT)",
        f"    BG 交织 fallback    : {fb}  (无可用不同 BG, 退回 RR)",
        f"    命中比              : {ratio:5.1f}%  (高 = 几乎总能找到不同 BG)",
        f"    各 SID 当前 last BG : {last_bg_str}",
    ]


def _format_age_priority_stats(stats: dict) -> List[str]:
    """v18+: 把 RowScheduler.get_age_priority_stats() 格式化成 summary 行.

    字段:
      enabled            — age_priority 是否开启
      age_priority_used  — age 实际生效的次数 (选出的 bank 是 age 最大且非并列)
      max_age_seen       — 仿真期内见过的最大 ACT 等待年龄 (cycles)
    """
    if not stats['enabled']:
        return [f"    Age 优先级         : 禁用 (走 v17 BG 交织 + RR)"]
    return [
        f"    enabled           : True (age > BG 交织 > RR 三级排序)",
        f"    age 生效次数      : {stats['age_priority_used']}  "
        f"(选出的 bank 是 age 最大且非并列, 平局不算)",
        f"    最大 ACT 等待年龄  : {stats['max_age_seen']} cycles  "
        f"(高 = 出现过长等待, 触发公平性约束)",
    ]


def _format_link_node_stats(stats: dict) -> List[str]:
    """格式化 V15 链表资源统计."""
    if not stats.get("enabled", False):
        return ["    (V15 link list 关闭)"]
    return [
        f"    链表配置              : "
        f"link_node_count={stats['link_node_count']} "
        f"link_list_count={stats['link_list_count']} "
        f"tRL={stats['t_rl_cycles']} cycles ({stats['t_rl_ns']:.1f} ns)",
        f"    每 cycle 申请上限     : {stats['grant_per_cycle']}  "
        f"(与一个 burst 的 4 条命令对齐)",
        f"    每 cycle 释放上限     : {stats['free_per_cycle']}  "
        f"(与每 cycle 最多 1 个读返回对齐)",
        f"    READ 总申请节点数     : {stats['total_nodes_requested']}",
        f"    READ 因节点不足被拒次数 : {stats['admit_blocked_count']}  "
        f"(burst 长度 > 当前可用节点)",
        f"    READ 节点 data_ready  : {stats['data_ready_count']}",
        f"    READ 节点释放数       : {stats['released_count']}",
        f"    链表完全释放次数      : {stats['list_freed_count']}",
        f"    新 txn 选空闲链表次数 : {stats['idle_list_selected']}",
        f"    新 txn 随机复用链表次数 : {stats['reused_list_selected']}",
        f"    同 txn 串到同链表的次数 : {stats['same_txn_appended']}",
    ]


# ============================================================
#  数据结构
# ============================================================

@dataclass
class ColumnCommand:
    """一条 32B Column 命令 (is_write=False 为 READ)."""
    transaction_id: int
    segment_id: int
    dispatch_id: int
    bank_id: int
    bank_group_id: int
    sid_id: int
    ba_id: int
    bg_id: int
    row_id: int
    col_index: int              #: workload 内顺序号
    segment_col_index: int      #: page-hit segment 内顺序号, 从 0 开始
    segment_cmd_count: int      #: 当前 page-hit segment 的 command 总数
    column_address: int = 0
    logical_address: int = 0          #: original contiguous system/UIF address
    mapped_logical_address: int = 0   #: post-remap DRAM address
    is_write: bool = False
    auto_precharge: bool = False  #: 派发时动态标记；WRITE=True 表示 WRA，READ=True 表示 RDA
    entry_cycle: int = INITIAL_CYCLE_SENTINEL
    issue_cycle: int = INITIAL_CYCLE_SENTINEL   #: V15: READ 真正派发 cycle, 用于 tRL 计算

    @property
    def page_key(self) -> Tuple[int, int, int, int]:
        """返回用于 page-hit 判断的 (SID, BG, BA, ROW) 键。"""
        return (self.sid_id, self.bg_id, self.ba_id, self.row_id)

    @property
    def txn_id(self) -> int:
        """V15: 返回事务 id (当前等同 transaction_id)."""
        return self.transaction_id


@dataclass
class BurstCommandGroup:
    """同一 page-hit segment 的 1-4 条同类型 Column 命令，CAM 最小单位。"""
    transaction_id: int
    segment_id: int
    dispatch_id: int
    bank_id: int
    bank_group_id: int
    sid_id: int
    ba_id: int
    bg_id: int
    row_id: int
    starting_col_index: int
    commands: List[ColumnCommand] = field(default_factory=list)
    entry_cycle: int = INITIAL_CYCLE_SENTINEL
    next_dispatch_index: int = 0

    @property
    def page_key(self) -> Tuple[int, int, int, int]:
        """返回用于 page-hit 判断的 (SID, BG, BA, ROW) 键。"""
        return (self.sid_id, self.bg_id, self.ba_id, self.row_id)

    @property
    def txn_id(self) -> int:
        return self.transaction_id

    def __post_init__(self) -> None:
        """完成 dataclass 构造后的完整性检查与派生字段初始化。"""
        assert self.commands, "BurstCommandGroup 不能为空"
        assert len(self.commands) <= BURST_GROUP_SIZE
        assert all(cmd.page_key == self.page_key for cmd in self.commands), \
            "CAM entry 不得混入不同 (SID,BG,BA,ROW) 的命令"
        assert all(cmd.dispatch_id == self.dispatch_id for cmd in self.commands)


@dataclass
class RowCommand:
    """一条已决定的 Row 命令 (ACT 或 PRE)"""
    kind: RowCommandType
    bank_id: int
    row_id: int


@dataclass
class _ColBusState:
    """Col 通道的派发历史 (tCCDs/tCCDl/tCCDR/turnaround 检查用), 由 ColScheduler 持有并更新"""
    num_bank_groups: int
    num_sid: int           #: HBM3 SID 数 (per JESD238B.01 Table 5), 用于 tCCDR
    last_dispatch_cycle: int = INITIAL_CYCLE_SENTINEL
    last_rw_type: RWType = RWType.NONE
    last_bank_group: int = -1
    last_dispatch_sid: int = -1

    def __post_init__(self):
        """完成 dataclass 构造后的完整性检查与派生字段初始化。"""
        self.last_dispatch_cycle_per_bg = [INITIAL_CYCLE_SENTINEL] * self.num_bank_groups
        # HBM3 inter-SID tCCDR 检查: 每个 SID 上次派发 cycle
        self.last_dispatch_cycle_per_sid = [INITIAL_CYCLE_SENTINEL] * self.num_sid


@dataclass
class LinkNode:
    """V15: 单个链路节点.

    字段:
      node_id        : 节点全局 id (0..link_node_count-1)
      txn_id         : 所属事务 id
      list_id        : 所属链表 id
      prev/next      : 链表内前后节点 id, -1 表示端点
      col_cmd        : 关联 ColumnCommand (申请时绑定, 关系固定不变)
      acquire_cycle  : 节点申请入池的 cycle (trace, 不参与 ready 判定)
      issued_cycle   : READ 派发 cycle (用于 tRL 计时起点)
      data_ready     : 读数据是否已返回
      released       : 是否已经释放回空闲池

    V15 fix: issued_cycle 必须由 READ 派发时 (mark_dispatched) 写入,
    不能用申请 cycle 代替, 否则 tRL 从入 CAM 算起, 可能在 READ 派发
    之前就 ready 并被释放, 违反"读数据返回之后才允许释放"的语义.
    """
    node_id: int
    txn_id: int
    list_id: int
    prev: int = -1
    next: int = -1
    col_cmd: Optional[ColumnCommand] = None
    acquire_cycle: int = INITIAL_CYCLE_SENTINEL
    issued_cycle: int = INITIAL_CYCLE_SENTINEL
    data_ready: bool = False
    released: bool = True   #: True 表示该节点处于空闲池


@dataclass
class LinkList:
    """V15: 单条 link list."""
    list_id: int
    txn_id: int
    head: int = -1
    tail: int = -1
    size: int = 0


class LinkListManager:
    """V15 链表资源管理器.

    功能:
      - 维护 link_node_count 个节点与 link_list_count 条链表
      - 根据 txn_id 申请节点: 同 txn 串同链; 优先空闲链, 否则随机复用
      - 标记数据 ready 并 head-only 释放
      - 每 cycle 最多申请 grant_per_cycle 个节点, 最多释放 free_per_cycle 个

    申请流程 (_acquire_nodes_for_burst):
      1. 计算本 burst 需要的节点数 (≤ 4)
      2. 如果可用节点 < 所需数量, 拒绝 (False)
      3. 优先空出 <= grant_per_cycle 个节点:
         - 同 txn 已有 list: 追加到该 list 尾部
         - 否则: 优先 list_size==0 的空闲 list, 都不空闲则 RNG 选一条已有 list
      4. 全部节点 issue_cycle 同步记录, 由 release 阶段根据 tRL 标记 ready

    释放流程 (_release_one_ready_node):
      1. 扫描所有 list, 找 head 节点 (col_cmd) data_ready=True 的 list
      2. 取其中链表 id 最小的一条 (确定性), 释放其 head 节点
      3. head.next 若存在则成为新 head
      4. list size 减 1; 减到 0 时回收 list (重置 txn 映射)
      5. 节点 released=True, data_ready 复位
    """

    def __init__(self,
                 link_node_count: int,
                 link_list_count: int,
                 grant_per_cycle: int,
                 free_per_cycle: int,
                 rng: Optional[random.Random] = None,
                 log_fp: Optional[TextIO] = None,
                 t_rl_cycles: int = 0,
                 t_rl_ns: float = 0.0) -> None:
        if link_node_count <= 0:
            raise ValueError("link_node_count 必须 > 0")
        if link_list_count <= 0 or link_list_count > link_node_count:
            raise ValueError("link_list_count 必须在 (0, link_node_count] 范围")
        if grant_per_cycle <= 0:
            raise ValueError("grant_per_cycle 必须 > 0")
        if free_per_cycle <= 0:
            raise ValueError("free_per_cycle 必须 > 0")
        self._link_node_count = link_node_count
        self._link_list_count = link_list_count
        self._grant_per_cycle = min(grant_per_cycle, BURST_GROUP_SIZE)
        self._free_per_cycle = free_per_cycle
        # tRL 参数: 传给 get_stats, 让 summary 显示正确的 tRL 配置.
        # 原来硬编码 0/0.0, 是历史 bug.
        self._t_rl_cycles = t_rl_cycles
        self._t_rl_ns = t_rl_ns
        self._rng = rng if rng is not None else random.Random(0xC0FFEE)
        # 可选 log 句柄: 非 None 时在 4 个关键事件 (acquire 成功/失败/data_ready/release)
        # 各写一行详细事件. 终端不打印 (用户只看 summary + cycle 行). 仅在传 log_fp 时启用.
        self._log_fp = log_fp
        # 节点池: 全部初始为空闲
        self._nodes: List[LinkNode] = [
            LinkNode(node_id=i, txn_id=-1, list_id=-1, released=True)
            for i in range(link_node_count)
        ]
        # 链表池
        self._lists: List[LinkList] = [
            LinkList(list_id=i, txn_id=-1) for i in range(link_list_count)
        ]
        # txn → 链表 映射 (保证同 txn 串同一链)
        self._txn_to_list: dict = {}
        # 统计
        self._total_requested: int = 0
        self._admit_blocked: int = 0
        self._data_ready_count: int = 0
        self._released_count: int = 0
        self._list_freed_count: int = 0
        # 性能统计：最后一个 READ 对应 link node 实际释放的 cycle。
        # 由 release_ready_nodes(current_cycle) 更新；无 READ 时保持 sentinel。
        self._last_node_release_cycle: int = INITIAL_CYCLE_SENTINEL
        self._idle_list_selected: int = 0
        self._reused_list_selected: int = 0
        self._same_txn_appended: int = 0

    # ---- 资源状态查询 ----

    def available_node_count(self) -> int:
        """当前可申请 (released=True) 的节点数."""
        return sum(1 for n in self._nodes if n.released)

    def link_list_count(self) -> int:
        return self._link_list_count

    def link_node_count(self) -> int:
        return self._link_node_count

    # ---- log 句柄 ----

    def set_log_fp(self, log_fp: Optional[TextIO]) -> None:
        """运行时设置 log 句柄 (可单独调用, 不影响 __init__ 签名)."""
        self._log_fp = log_fp

    def _log_event(self, msg: str) -> None:
        """写入一条 V15 链路事件到 log. 仅在 log_fp 不为空时调用.

        设计: 与 print/log 双写分离, 此函数**只写 log 不写 console**, 终端保持简洁.
        所有事件以 `[V15-Link]` 前缀, 便于在 log 中 grep 过滤.
        """
        if self._log_fp is not None:
            self._log_fp.write(msg + "\n")
            self._log_fp.flush()  # 立即落盘, 防止中途崩溃丢 log

    # ---- 申请阶段 ----

    def _allocate_from_pool(self, count: int) -> List[int]:
        """从空闲池里取出 count 个节点 id (按 node_id 升序, 确定性)."""
        if count <= 0:
            return []
        ids = [n.node_id for n in self._nodes if n.released]
        ids.sort()
        if len(ids) < count:
            return []
        chosen = ids[:count]
        # 注意: 此时还未设置 prev/next, 由 caller 设置
        return chosen

    def _choose_list_for_txn(self, txn_id: int) -> Tuple[int, bool]:
        """为新 txn 选一条链表. 优先 list_size==0 的空闲链, 否则 RNG 复用已有链.

        Returns: (list_id, is_idle)
          - is_idle=True: 选的是空闲 list (无 txn 占用)
          - is_idle=False: 选的是已有 txn 的 list (复用, 计入 reused_list_selected)
        """
        # 1) 同 txn 已有链 → 直接返回 (调用方通常先 _lookup_txn_list 检查, 这里兜底)
        if txn_id in self._txn_to_list:
            return self._txn_to_list[txn_id], True

        # 2) 优先空闲 (size==0) 的 list
        idle_lists = [lst.list_id for lst in self._lists if lst.size == 0]
        if idle_lists:
            chosen = idle_lists[0]   # 确定性选最小 id
            self._idle_list_selected += 1
            return chosen, True

        # 3) 全部链表都被占用 → 随机选一条 (确定性 RNG, 配 seed)
        occupied = [lst.list_id for lst in self._lists if lst.size > 0]
        if not occupied:
            # 极端兜底, 不应发生 (上面 idle 已覆盖)
            chosen = self._lists[0].list_id
            return chosen, True
        chosen = self._rng.choice(occupied)
        self._reused_list_selected += 1
        return chosen, False

    def _lookup_txn_list(self, txn_id: int) -> int:
        """返回 txn 当前所在的 list_id, 不存在返回 -1."""
        return self._txn_to_list.get(txn_id, -1)

    def acquire_nodes_for_burst(self, txn_id: int, burst_entry: BurstCommandGroup,
                                 current_cycle: int) -> bool:
        """为 READ burst 申请 link node. 一次申请 = burst 内命令数 (≤ 4).

        Returns:
          True  : 全部节点已申请并 attach 到合适的 list, 可走 cmd 派发
          False : 可用节点不足, 不允许该 burst 入 READ CAM

        V15 fix: 申请阶段只绑定 node.col_cmd (关系固定), 不写 issued_cycle.
        issued_cycle 必须等 READ 真正派发 (mark_dispatched) 时再写, 才是
        tRL 计时起点. 申请时记录 acquire_cycle (仅 trace) 用于调试.
        """
        # WRITE burst 不需要申请 link node
        if burst_entry.commands[0].is_write:
            return True

        burst_size = len(burst_entry.commands)
        if burst_size <= 0:
            return True

        # 1) 检查可用节点是否足够 (本 burst 长度 + 当 cycle 还没用掉的 grant 配额)
        #    简化处理: 物理上 self._grant_per_cycle 限制在 _acquire_and_link 内
        #    一次性 burst 申请 burst_size 个节点; grant_per_cycle 仅限制"每 cycle 总
        #    申请数 ≤ 4", 因此 burst_size ≤ grant_per_cycle 直接放过, 否则拒.
        if burst_size > self._grant_per_cycle:
            # 超过每 cycle 申请上限 (一个 burst 不可能 > 4, 但防御性检查)
            self._admit_blocked += 1
            self._log_event(
                f"  [V15-Link] cycle={current_cycle} acquire BLOCKED: txn={txn_id}, "
                f"burst_size={burst_size} > grant_per_cycle={self._grant_per_cycle}")
            return False

        avail = self.available_node_count()
        if avail < burst_size:
            self._admit_blocked += 1
            self._log_event(
                f"  [V15-Link] cycle={current_cycle} acquire BLOCKED: txn={txn_id}, "
                f"burst_size={burst_size}, available={avail}")
            return False

        # 2) 取出节点
        node_ids = self._allocate_from_pool(burst_size)
        if len(node_ids) < burst_size:
            # 不应发生 (上面已检查), 兜底
            self._admit_blocked += 1
            return False

        # 3) 选链表
        existing_list = self._lookup_txn_list(txn_id)
        if existing_list != -1:
            list_id = existing_list
            self._same_txn_appended += 1
        else:
            list_id, _is_idle = self._choose_list_for_txn(txn_id)
            self._txn_to_list[txn_id] = list_id
            # 如果是空闲 list 被新 txn 占用, 更新 list.txn_id
            if self._lists[list_id].txn_id == -1:
                self._lists[list_id].txn_id = txn_id

        target_list = self._lists[list_id]

        # 4) 把节点 append 到该 list 尾部, 仅记录 col_cmd 绑定 + acquire_cycle (trace).
        #    V15 fix: 不再写 issued_cycle / col_cmd.issue_cycle, 这两个由 mark_dispatched
        #    在 READ 真正派发时写, 保证 tRL 起点是派发 cycle 而非入 CAM cycle.
        cmds = burst_entry.commands
        for offset, nid in enumerate(node_ids):
            node = self._nodes[nid]
            node.released = False
            node.txn_id = txn_id
            node.list_id = list_id
            node.col_cmd = cmds[offset]
            node.acquire_cycle = current_cycle
            # issued_cycle 保持 INITIAL_CYCLE_SENTINEL, 表示"尚未派发, 不参与 ready 判定"
            node.issued_cycle = INITIAL_CYCLE_SENTINEL
            node.data_ready = False
            node.prev = target_list.tail
            node.next = -1
            if target_list.tail != -1:
                self._nodes[target_list.tail].next = nid
            else:
                target_list.head = nid
            target_list.tail = nid
            target_list.size += 1
            self._total_requested += 1

        # 申请成功 - 详细 log 事件
        head_nid = node_ids[0] if node_ids else -1
        avail_after = self.available_node_count()
        self._log_event(
            f"  [V15-Link] cycle={current_cycle} acquire OK: txn={txn_id}, "
            f"burst_size={burst_size}, list=L{list_id}, head=node{head_nid}, "
            f"avail_after={avail_after}, total_requested={self._total_requested}")
        return True

    def mark_dispatched(self, col_cmd: ColumnCommand, current_cycle: int) -> None:
        """标记一个 READ col_cmd 已派发: 写 col_cmd.issue_cycle 与对应 node.issued_cycle.

        V15 fix: 这个方法才是 tRL 计时的真正起点. 由 ColScheduler._complete_dispatch
        在每条 READ 派发成功后调用一次. WRITE 不走 link node, 不调此方法.

        col_cmd → node 的查找: 同一个 col_cmd 对象只会被一个 node 绑定 (申请时设置),
        所以反向查 "node.col_cmd is col_cmd" 即可. O(N) 扫一遍节点池 (N=link_node_count)
        是可接受的, 也可以未来换成 dict 反向索引. 同一 cycle 多次派发时 O(N) 不影响热点.

        防御性: 如果 col_cmd 没有对应 node (例如 WRITE 误调, 或 free 后复用), 静默 no-op.
        """
        for node in self._nodes:
            if node.col_cmd is col_cmd and not node.released:
                node.issued_cycle = current_cycle
                col_cmd.issue_cycle = current_cycle
                # 之前 acquire 时的 trace 保留, 不覆盖
                self._log_event(
                    f"  [V15-Link] cycle={current_cycle} dispatched: "
                    f"txn={node.txn_id}, node=node{node.node_id}, "
                    f"acquire→dispatch Δ={current_cycle - node.acquire_cycle} cycles")
                return
        # 找不到对应 node: 静默 no-op, 不抛异常 (WRITE / free 后复用场景)

    # ---- 释放阶段 ----

    def update_data_ready(self, current_cycle: int, t_rl_cycles: int) -> None:
        """扫描所有未释放节点, 标记到期 (issue + tRL ≤ current) 的为 data_ready.

        每 cycle 调用一次 (放在 release 之前). 同一 cycle 可能多个节点一起 ready,
        记为一行聚合事件, 避免 log 被重读运行淹没.
        """
        if t_rl_cycles <= 0:
            t_rl_cycles = 0
        newly_ready = 0
        for node in self._nodes:
            if node.released or node.col_cmd is None:
                continue
            if node.data_ready:
                continue
            if node.issued_cycle == INITIAL_CYCLE_SENTINEL:
                continue
            if current_cycle >= node.issued_cycle + t_rl_cycles:
                node.data_ready = True
                self._data_ready_count += 1
                newly_ready += 1
        if newly_ready > 0:
            self._log_event(
                f"  [V15-Link] cycle={current_cycle} data_ready: count={newly_ready}, "
                f"total_data_ready={self._data_ready_count}")

    def release_ready_nodes(self, current_cycle: int = INITIAL_CYCLE_SENTINEL) -> int:
        """每 cycle 最多释放 free_per_cycle 个节点. 只能释放每条 list 的 head 节点,
        且 head 节点必须 data_ready=True. 释放后:
          - 节点 released=True
          - 若 list size → 0, 回收 list, 清 txn 映射
        Returns: 实际释放的节点数.
        """
        released = 0
        # 确定性遍历: list_id 升序, 找到 head ready 的第一条优先释放
        # 每个 list 一次只释放 1 个 head (即使后续 node 也 ready, 必须等下一 cycle)
        for lst in self._lists:
            if released >= self._free_per_cycle:
                break
            if lst.size == 0 or lst.head == -1:
                continue
            head_node = self._nodes[lst.head]
            if not head_node.data_ready or head_node.released:
                continue
            # 释放 head
            new_head = head_node.next
            # 解链
            if new_head != -1:
                self._nodes[new_head].prev = -1
            else:
                lst.tail = -1
            lst.head = new_head
            prev_size = lst.size
            lst.size -= 1
            released_txn = head_node.txn_id
            head_node.released = True
            head_node.data_ready = False
            head_node.next = -1
            head_node.prev = -1
            head_node.col_cmd = None
            head_node.issued_cycle = INITIAL_CYCLE_SENTINEL
            # 节点归还, 但 list_id / txn_id 保留作为历史 (释放后无业务影响)
            head_node.txn_id = -1
            head_node.list_id = -1
            self._released_count += 1
            if current_cycle != INITIAL_CYCLE_SENTINEL:
                self._last_node_release_cycle = current_cycle
            released += 1
            # 链表全空 → 回收
            list_freed_now = False
            if lst.size == 0:
                old_txn = lst.txn_id
                if old_txn != -1 and self._txn_to_list.get(old_txn) == lst.list_id:
                    self._txn_to_list.pop(old_txn, None)
                lst.txn_id = -1
                self._list_freed_count += 1
                list_freed_now = True
            # log 事件: 释放 head + (可选) 链表回收. 同一 cycle 多条 list 释放合并到独立行.
            suffix = ""
            if list_freed_now:
                suffix = f", list FREED (total_list_freed={self._list_freed_count})"
            self._log_event(
                f"  [V15-Link] cycle=release release head: list=L{lst.list_id}, "
                f"txn={released_txn}, node=node{head_node.node_id}, "
                f"list_size={prev_size}→{lst.size}, total_released={self._released_count}{suffix}")

        return released

    # ---- 统计 / 调试 ----

    def get_stats(self) -> dict:
        return {
            "enabled": True,
            "link_node_count": self._link_node_count,
            "link_list_count": self._link_list_count,
            "t_rl_cycles": self._t_rl_cycles,   # V15 fix: 原来硬编码 0, 现在从 __init__ 参数读
            "t_rl_ns": self._t_rl_ns,           # 同上
            "grant_per_cycle": self._grant_per_cycle,
            "free_per_cycle": self._free_per_cycle,
            "total_nodes_requested": self._total_requested,
            "admit_blocked_count": self._admit_blocked,
            "data_ready_count": self._data_ready_count,
            "released_count": self._released_count,
            "list_freed_count": self._list_freed_count,
            "last_node_release_cycle": self._last_node_release_cycle,
            "idle_list_selected": self._idle_list_selected,
            "reused_list_selected": self._reused_list_selected,
            "same_txn_appended": self._same_txn_appended,
        }


@dataclass(frozen=True)
class SimulationConfig:
    """原始构造参数 + 派生常量 (只读, 供 summary 显示与各部件查询)"""
    data_rate_gbps: float
    num_banks: int
    banks_per_bank_group: int
    num_bank_groups: int
    t_rcdrd_ns: float
    t_rcdwr_ns: float
    t_rp_ns: float
    t_rc_ns: float
    t_ras_ns: float
    t_rtp_hbmck: int
    t_wr_ns: float
    wl_hbmck: int
    t_ccd_s: int
    t_ccd_l: int
    t_rrd_s: int
    t_rrd_l: int
    t_faw_hbmck: int
    t_rtw_ns: float
    t_wtrl_hbmck: int
    t_wtrs_hbmck: int
    read_cam_depth: int
    write_cam_depth: int
    num_transactions: int
    cmds_per_transaction: int
    workload_size_bytes: int  #: 每个 workload/transaction 的连续字节数
    addr_mode: str            #: v7: "linear" / "random" (替代旧 case)
    addr_map: dict            #: bit position mapping used after configuration selection
    configuration: str
    density_code: Optional[int]
    sid_remap_type: Optional[int]
    max_system_la: int
    seed: int
    read_ratio: float
    batch_timeout_cycles: int
    # 准备期 (preparation phase) 配置 — timeout 后两阶段切模式机制
    preparation_min_banks: int           #: 目标模式"准备好"的最小 bank 数 (snapshot 不足时按 snapshot 全数算)
    preparation_max_dispatches: int     #: 准备期内 current mode 最多发几条 (软上限, 触发 degraded 强切)
    preparation_max_cycles: int         #: 准备期总时长上限 (硬上限, 触发 prep_timeout degraded 强切)
    initial_batch_type: str
    batch_scheduling: bool
    rw_4state_mode: bool                 #: v16.3+: 启用 4 态 R/W 状态机 (RD/WR/RD_WR/WR_RD)
    bg_interleave_priority: bool          #: v17+: ACT 选优时同 SID 不同 BG 优先 (BG 交织)
    age_priority: bool                    #: v18+: ACT 选优时 ACT 等待最久的 bank 优先 (age 优先级)
    write_auto_precharge: bool       #: True 时，最后一个 page-hit WRITE 使用 WRA
    read_auto_precharge: bool        #: True 时，最后一个 page-hit READ 使用 RDA
    wra_refresh_guard_cycles: int     #: WRA 路径在 refresh deadline 前停止串接的提前量
    rda_refresh_guard_cycles: int     #: RDA 路径在 refresh deadline 前停止串接的提前量
    wra_only_after_page_hit: bool      #: 兼容开关；False 表示同类型 CAM 无 page-hit 时直接 WRA
    rda_only_after_page_hit: bool      #: 兼容开关；False 表示同类型 CAM 无 page-hit 时直接 RDA
    # Refresh 配置 (HBM3 per-bank refresh, 错峰 stagger)
    # ⚠️ 注意: 此处的"per-bank 间隔"≠ spec 的 tREFIpb (channel-level 平均 rate = tREFI/N).
    # 真正的 spec tREFIpb = tREFI/32 = 122ns (channel 每 122ns 发一个 REFpb 的平均 rate).
    # 但每个具体 bank 实际被刷新的间隔 = tREFI = 3.9μs (N=32 个 bank 一个 tREFI 窗口内刷完).
    # 所以本参数 = per-bank 实际刷新间隔 = tREFI (设备级, 8-High = 3.9μs = 4680 cycles).
    t_refi_per_bank_cycles: int                 #: 每个 bank 相邻两次 refresh 的间隔 (per-bank interval, = tREFI)
    t_rfc_pb_ns: float                    #: per-bank refresh 命令耗时 (bank 阻塞时间, HBM3 ~200ns)
    # ---- V15 新增 ----
    t_rl_ns: float
    link_node_count: int
    link_list_count: int
    t_rl_cycles: int

    @property
    def total_cmds(self) -> int:
        """返回本次仿真的 ColumnCommand 总数。"""
        return self.num_transactions * self.cmds_per_transaction


# ============================================================
#  Clock model
# ============================================================

class ClockModel:
    """HBM3 时钟与模型 cycle 的统一换算。

    本模型采用以下固定 PHY/MC 结构：

      * ``data_rate_gbps`` 是每个 DQ pin 的 DDR data rate。
      * DQS 频率 = data rate / 2。
      * HBM CK 与 DQS 的频率比为 1:2，因此 HBM CK = data rate / 4。
      * PHY/DFI clock 与 HBM CK 的频率比为 1:2，因此 DFI CLK = HBM CK / 2。
      * 1 个模型 cycle = 1 个 DFI clock cycle = 2 个 HBM CK = 4 个 DQS cycle。
      * 两个 pseudo channel 分别由两个 MC 控制，并交替占用 HBM CK phase：
          - MC0 固定使用 DFI cycle 内的 HBM phase 0；
          - MC1 固定使用 DFI cycle 内的 HBM phase 1。

    以 9.6 Gbps 为例：DQS=4.8 GHz，HBM CK=2.4 GHz，DFI CLK=1.2 GHz，
    tDQS=0.20833 ns，tCK=0.41667 ns，tDFI=0.83333 ns。

    当前调度器以完整 DFI cycle 为最小时间粒度。所有以 nCK 给出的 timing
    均保守向上取整为 ``ceil(nCK / 2)`` 个模型 cycle。phase 0/1 只用于描述
    两个 MC 在一个 DFI cycle 内的固定命令位置；如果后续需要精确检查跨 MC 的
    亚 cycle 间隔，应使用 ``dfi_phase_to_hbmck()`` 转成绝对 HBM CK 时间戳。
    """

    DQS_PER_HBM_CK: int = 2
    HBM_CK_PER_DFI_CYCLE: int = 2
    MC0_PHASE: int = 0
    MC1_PHASE: int = 1

    def __init__(self, data_rate_gbps: float):
        """初始化时钟模型；data_rate_gbps 表示 DDR pin data rate。"""
        if data_rate_gbps <= 0:
            raise ValueError(f"data_rate_gbps 必须 > 0, 当前 {data_rate_gbps}")
        self.data_rate_gbps = data_rate_gbps

    @property
    def dqs_freq_ghz(self) -> float:
        """DQS 频率，单位 GHz；DDR data rate = 2 × DQS。"""
        return self.data_rate_gbps / 2.0

    @property
    def hbm_ck_freq_ghz(self) -> float:
        """HBM CK 频率，单位 GHz；DQS = 2 × HBM CK。"""
        return self.dqs_freq_ghz / self.DQS_PER_HBM_CK

    @property
    def dfi_clk_freq_ghz(self) -> float:
        """PHY/DFI clock 频率，单位 GHz；DFI CLK = HBM CK / 2。"""
        return self.hbm_ck_freq_ghz / self.HBM_CK_PER_DFI_CYCLE

    @property
    def tdqs_ns(self) -> float:
        """一个 DQS 周期的时间，单位 ns。"""
        return 1.0 / self.dqs_freq_ghz

    @property
    def tck_hbm_ns(self) -> float:
        """一个 HBM CK 周期的时间，单位 ns。"""
        return 1.0 / self.hbm_ck_freq_ghz

    @property
    def tdfi_ns(self) -> float:
        """一个 DFI/model cycle 的时间，单位 ns。"""
        return self.HBM_CK_PER_DFI_CYCLE * self.tck_hbm_ns

    def ns_to_hbmck(self, ns_val: float) -> int:
        """ns → HBM CK，按整数 nCK 语义向上取整。"""
        if ns_val < 0:
            raise ValueError(f"ns timing 必须 >= 0, 当前 {ns_val}")
        return math.ceil(ns_val / self.tck_hbm_ns)

    def ns_to_cycles(self, ns_val: float) -> int:
        """ns → DFI/model cycles；等价于 ceil(ceil(ns/tCK) / 2)。"""
        return self.hbmck_to_cycles(self.ns_to_hbmck(ns_val))

    def hbmck_to_cycles(self, n: int) -> int:
        """HBM CK → DFI/model cycles：ceil(n / 2)。"""
        if n < 0:
            raise ValueError(f"HBM CK timing 必须 >= 0, 当前 {n}")
        ratio = self.HBM_CK_PER_DFI_CYCLE
        return (n + ratio - 1) // ratio

    def dfi_phase_to_hbmck(self, dfi_cycle: int, mc_phase: int) -> int:
        """将 ``(DFI cycle, MC phase)`` 转换为绝对 HBM CK 序号。

        MC0 只能使用 phase 0，MC1 只能使用 phase 1。返回值可用于未来实现
        跨 MC 的精确 nCK timing 检查，而不丢失一个 DFI cycle 内的 phase 信息。
        """
        if dfi_cycle < 0:
            raise ValueError(f"dfi_cycle 必须 >= 0, 当前 {dfi_cycle}")
        if mc_phase not in (self.MC0_PHASE, self.MC1_PHASE):
            raise ValueError(f"mc_phase 必须为 0 或 1, 当前 {mc_phase}")
        return dfi_cycle * self.HBM_CK_PER_DFI_CYCLE + mc_phase


# ============================================================
#  Timing parameters
# ============================================================

@dataclass(frozen=True)
class TimingParameters:
    """所有 DRAM timing 值, 单位 DFI cycles (model 内部单位)"""
    # ---- Bank timing ----
    t_rcdrd_cycles: int
    t_rcdwr_cycles: int
    t_rp_cycles: int
    t_rc_cycles: int
    t_ras_cycles: int
    t_rtp_cycles: int
    write_ap_cycles: int
    # ---- 通道 timing ----
    t_ccd_s_cycles: int
    t_ccd_l_cycles: int
    t_ccdr_cycles: int         #: HBM3 inter-SID tCCDR (READ only)，输入单位为 DFI/model cycle
    t_rrd_s_cycles: int
    t_rrd_l_cycles: int
    t_faw_cycles: int
    # ---- R/W Turnaround ----
    t_rtw_cycles: int
    write_to_read_same_bg_cycles: int
    write_to_read_diff_bg_cycles: int
    # ---- Refresh (HBM3 REFpb) ----
    t_rfc_pb_cycles: int   #: per-bank refresh cycle time (bank 阻塞时间)
    t_rrefd_cycles: int    #: REFpb → REFpb (不同 bank, 跨 SID 生效) / REFpb → ACT (不同 bank, 跨 SID 生效) 最小间隔
                          #: per JESD238B.01 §6.3.2.6 Table 35 NOTE 3 + Table 84
                          #: tRREFD = 8 ns (spec) → ceil(8/tCK)=20 HBM CK → 10 DFI cycles @ 9.6 Gbps
    # (t_refi_ab_cycles / t_refi_per_bank_cycles / t_rfc_ab_cycles 留作 future use, 暂未参与逻辑)

    @classmethod
    def from_inputs(cls,
                    clock: ClockModel,
                    t_rcdrd_ns: float, t_rcdwr_ns: float, t_rp_ns: float,
                    t_rc_ns: float, t_ras_ns: float, t_rtp_hbmck: int,
                    t_wr_ns: float, wl_hbmck: int,
                    t_ccd_s: int, t_ccd_l: int,
                    t_rrd_s: int, t_rrd_l: int, t_faw_hbmck: int,
                    t_rtw_ns: float, t_wtrl_hbmck: int, t_wtrs_hbmck: int,
                    t_rfc_pb_ns: float = 200.0,
                    t_ccdr_cycles: int = 2   # HBM3 inter-SID tCCDR；此参数已是 DFI/model cycle，不再做 nCK 换算
                    ) -> "TimingParameters":
        """从原始 ns / HBM CK 输入派生所有 cycles 值"""
        t_wr_hbmck = math.ceil(t_wr_ns / clock.tck_hbm_ns)

        return cls(
            t_rcdrd_cycles=clock.ns_to_cycles(t_rcdrd_ns),
            t_rcdwr_cycles=clock.ns_to_cycles(t_rcdwr_ns),
            t_rp_cycles=clock.ns_to_cycles(t_rp_ns),
            t_rc_cycles=clock.ns_to_cycles(t_rc_ns),
            t_ras_cycles=clock.ns_to_cycles(t_ras_ns),
            t_rtp_cycles=clock.hbmck_to_cycles(t_rtp_hbmck),
            write_ap_cycles=clock.hbmck_to_cycles(
                wl_hbmck + WL_TWTR_OFFSET + t_wr_hbmck),
            t_ccd_s_cycles=t_ccd_s,
            t_ccd_l_cycles=t_ccd_l,
            t_ccdr_cycles=t_ccdr_cycles,
            t_rrd_s_cycles=t_rrd_s,
            t_rrd_l_cycles=t_rrd_l,
            t_faw_cycles=clock.hbmck_to_cycles(t_faw_hbmck),
            t_rtw_cycles=clock.ns_to_cycles(t_rtw_ns),
            write_to_read_same_bg_cycles=clock.hbmck_to_cycles(
                wl_hbmck + WL_TWTR_OFFSET + t_wtrl_hbmck),
            write_to_read_diff_bg_cycles=clock.hbmck_to_cycles(
                wl_hbmck + WL_TWTR_OFFSET + t_wtrs_hbmck),
            t_rfc_pb_cycles=clock.ns_to_cycles(t_rfc_pb_ns),
            t_rrefd_cycles=clock.ns_to_cycles(8.0),  # JESD238B.01 Table 84: tRREFD = 8 ns
        )

    def validate(self) -> None:
        """校验 timing 参数为非负。

        v16.2 起，READ/WRITE 分别直接检查 tRCDRD/tRCDWR，
        不再要求 tRCDWR <= tRCDRD。
        """
        for name, value in self.__dict__.items():
            if isinstance(value, int) and value < 0:
                raise ValueError(f"{name} 必须 >= 0，当前 {value}")


# ============================================================
#  DRAM bank
# ============================================================

class DRAMBank:
    """单个 DRAM bank 的运行时状态 + 状态机.

    状态转移:
        IDLE --ACT--> ACT_WAIT --[t_rcdwr]--> (write_timing_satisfied=True)
                               --[t_rcdrd]--> ACTING --PRE--> PRE_WAIT --[t_rp]--> IDLE
        ACTING --(force PRE)--> PRE_WAIT --[t_rp]--> IDLE (force-pre for refresh, state preserved)
        ACT_WAIT/ACTING --WRA--> AUTO_PRE_WAIT --[max(tRAS, write_ap)+tRP]--> IDLE
        ACTING          --RDA--> AUTO_PRE_WAIT --[max(tRAS, tRTP)+tRP]--> IDLE
        IDLE --REFpb--> REFRESHING --[t_rfc_pb]--> IDLE (state preserved for in-flight entry)
    注: ACT_WAIT 不接受 force-PRE (force_precharge_for_refresh 对 ACT_WAIT 返 False),
        需等 tick 走到 ACTING 后, 由 RefreshScheduler 重试.
    """

    def __init__(self, bank_id: int, bank_group_id: int):
        """初始化对象状态及其依赖组件。"""
        self.bank_id = bank_id
        self.bank_group_id = bank_group_id
        self.state = BankState.IDLE
        self.last_act_at = INITIAL_CYCLE_SENTINEL   # 不随状态重置, t_rc 检查用
        self.last_col_at = INITIAL_CYCLE_SENTINEL
        self.last_pre_at = INITIAL_CYCLE_SENTINEL
        self.serving_dispatch_id = -1
        self.cols_dispatched = 0
        self.precharge_pending = False
        self.page_hit_chain_active = False
        self.open_row = -1
        self.last_col_rw_type = RWType.NONE   # 不随状态重置, PRE 时机检查用
        self.write_timing_satisfied = False
        self._refresh_start_cycle: int = INITIAL_CYCLE_SENTINEL
        self._auto_precharge_complete_cycle: int = INITIAL_CYCLE_SENTINEL
        self._force_pre_for_refresh: bool = False   # 标记: PRE_WAIT→IDLE 时不要 reset

    def tick(self, current_cycle: int, timing: TimingParameters) -> None:
        """每个 cycle 推进一次状态机 (Row/Col 调度之前调用, 结果当 cycle 对调度可见)"""
        if self.state == BankState.ACT_WAIT:
            if (not self.write_timing_satisfied
                    and current_cycle >= self.last_act_at + timing.t_rcdwr_cycles):
                self.write_timing_satisfied = True
            if current_cycle >= self.last_act_at + timing.t_rcdrd_cycles:
                self.state = BankState.ACTING
        elif self.state == BankState.PRE_WAIT:
            if current_cycle >= self.last_pre_at + timing.t_rp_cycles:
                if self._force_pre_for_refresh:
                    # Force PRE for refresh: PRE_WAIT→IDLE 但不 reset in-flight 状态
                    # (cols_dispatched/serving_dispatch_id/open_row), 让 in-flight entry 续派.
                    self.state = BankState.IDLE
                    self._force_pre_for_refresh = False
                    # 清除"stale" 标记 (autoprecharge/timing-satisfied): bank 现在是空的,
                    # 这些 flag 描述的是上一轮 row 的状态, 必须清. 但 in-flight 信息保留.
                    self._clear_stale_flags_on_idle()
                else:
                    self._reset_to_idle()
        elif self.state == BankState.AUTO_PRE_WAIT:
            if current_cycle >= self._auto_precharge_complete_cycle:
                # WRA/RDA 内部 precharge 完成。该路径等价于显式 PRE 完成后回到 IDLE，
                # 但没有占用独立 Row command slot。
                self._reset_to_idle()
        elif self.state == BankState.REFRESHING:
            if current_cycle >= self._refresh_start_cycle + timing.t_rfc_pb_cycles:
                # Refresh 完成, 回到 IDLE. 同样保留 in-flight 状态.
                self.state = BankState.IDLE
                # 清除 stale 标记 (同 force-PRE): bank 是空的, precharge_pending 等
                # 必须清, 否则 row scheduler 找不到 ACT/PRE 候选会卡住.
                self._clear_stale_flags_on_idle()
                # 不调 _reset_to_idle, 保留 cols_dispatched/serving_dispatch_id/open_row

    def _clear_stale_flags_on_idle(self) -> None:
        """Bank 经过 force-PRE/REFRESHING → IDLE 时, 清理"描述上一轮 row 状态"的 stale 标记.

        关键判断: precharge_pending (entry 是否已经全派完?)
          - precharge_pending=True  →  4 个 col 全部派完, entry 早已从 CAM 移走,
             cols_dispatched/serving_dispatch_id/open_row 都是 stale, 必须 reset
             (否则新 entry 想 ACT 这个 bank 时, row scheduler 检查
             `col_cmd.segment_col_index == bank.cols_dispatched` 会因为 0 != 4 失败,
             bank 永远 ACT 不了, 永久卡住)
          - precharge_pending=False →  in-flight (entry 还在 CAM 等续派),
             保留 cols_dispatched/serving_dispatch_id/open_row 让 row scheduler 续 ACT

        无条件清除:
          - write_timing_satisfied : 描述旧 row 状态, 现在没 row open, 下次 ACT 会重置
        """
        if self.precharge_pending:
            # entry 已 done, 全部 reset
            self.cols_dispatched = 0
            self.serving_dispatch_id = -1
            self.open_row = -1
        # else: in-flight, 保留 cols_dispatched/serving_dispatch_id/open_row 让 row scheduler 续 ACT
        self.precharge_pending = False
        self.page_hit_chain_active = False
        self.write_timing_satisfied = False

    def _reset_to_idle(self) -> None:
        """PRE_WAIT → IDLE: 保留 last_act_at (t_rc) 和 last_col_rw_type (PRE 检查)"""
        self.state = BankState.IDLE
        self.serving_dispatch_id = -1
        self.cols_dispatched = 0
        self.precharge_pending = False
        self.page_hit_chain_active = False
        self.open_row = -1
        self.write_timing_satisfied = False

    # ---- 自动预充电相关 ----

    def start_write_auto_precharge(self, current_cycle: int,
                                   timing: TimingParameters) -> None:
        """发送 WRA 后启动 bank 内部自动预充电。

        显式 PRE 路径需要先等待 ``last_col + write_ap`` 与 ``last_act + tRAS``，
        再占用一个 Row command slot 发 PRE，随后等待 tRP。WRA 将 PRE 附着在
        最后一条 WRITE 上，因此不占 Row bus，但 bank 仍必须等待同样的内部时序。
        """
        precharge_start = max(
            current_cycle + timing.write_ap_cycles,
            self.last_act_at + timing.t_ras_cycles,
        )
        self._auto_precharge_complete_cycle = precharge_start + timing.t_rp_cycles
        self.precharge_pending = False
        self.state = BankState.AUTO_PRE_WAIT

    def start_read_auto_precharge(self, current_cycle: int,
                                  timing: TimingParameters) -> None:
        """发送 RDA 后启动 bank 内部自动预充电。

        显式 PRE 路径需要先等待 ``last_col + tRTP`` 与 ``last_act + tRAS``，
        再占用一个 Row command slot 发 PRE，随后等待 tRP。RDA 将 PRE 附着在
        最后一条 READ 上，因此不占 Row bus，但 bank 仍必须等待同样的内部时序。
        """
        precharge_start = max(
            current_cycle + timing.t_rtp_cycles,
            self.last_act_at + timing.t_ras_cycles,
        )
        self._auto_precharge_complete_cycle = precharge_start + timing.t_rp_cycles
        self.precharge_pending = False
        self.state = BankState.AUTO_PRE_WAIT

    # ---- refresh 相关 ----

    def start_refresh(self, current_cycle: int) -> None:
        """启动 REFpb. 假设 bank 已 IDLE (或调用方保证)."""
        self.state = BankState.REFRESHING
        self._refresh_start_cycle = current_cycle
        # 注意: 不 reset cols_dispatched/serving_dispatch_id/open_row,
        # in-flight entry 在 refresh 后会 re-ACT 续派.

    def force_precharge_for_refresh(self, current_cycle: int) -> bool:
        """为 refresh 强制 PRE bank. 返回 True 表示已发起 PRE (或已在 PRE_WAIT 路上),
        False 表示无需 force (IDLE/REFRESHING) 或不允许 (ACT_WAIT, tRAS 必不满足).

        调用方 (RefreshScheduler) **必须先自行检查** tRAS 和 col-to-pre 时序都满足,
        本方法不检查 timing — 只做状态转移. 状态变化:
          IDLE      → 不动 (不需要 force PRE, RefreshScheduler 走 IDLE 路径发 REFPB)
          ACT_WAIT  → 返回 False (tRAS 必不满足, 且尚无 col, 没 col-to-pre 概念)
          ACTING    → PRE_WAIT, 设 _force_pre_for_refresh=True (in-flight 续派)
          PRE_WAIT  → 仅设 _force_pre_for_refresh=True (标记为 force, tick 时不 reset)
          REFRESHING→ 不动 (已经在 refresh)
        """
        if self.state == BankState.ACT_WAIT:
            return False
        if self.state == BankState.ACTING:
            self.state = BankState.PRE_WAIT
            self.last_pre_at = current_cycle
            self._force_pre_for_refresh = True
            return True
        if self.state == BankState.PRE_WAIT:
            # 已经在 PRE_WAIT, 仅补 force-pre 标记, 让 tick 走保留 in-flight 分支
            self._force_pre_for_refresh = True
            return True
        # IDLE, REFRESHING: 不需要 force PRE
        return False


# ============================================================
#  Workload generator
# ============================================================

class WorkloadGenerator:
    """由 seed 生成 burst command groups (per-txn 整组同 R/W).

    RNG 隔离: 主 RNG (seed) 决定逻辑地址 LA (v7: 替代旧 case 的 bank/row 直接生成),
    R/W RNG (seed + RW_RNG_SEED_OFFSET) 决定类型.

    v7 地址生成 (替代旧 case=1/2):
      - addr_mode="linear": la = (txn_id * CPT) % max_la (线性增长, CPT 倍数)
      - addr_mode="random": 在 density code 对应的完整合法地址范围内随机采样，
        并按 CPT 对齐，确保连续 workload 不越过地址上限
      - 按 addr_map bit position 映射表分解 LA → (col, ba, bg, sid, row)
      - bank_id = sid * groups_per_sid * 4 + bg * 4 + ba
      - row_id = row 字段值
      - pattern base 按 CPT 对齐；逐条生成 base_la + 0..CPT-1 的连续地址
      - txn 内 col_index 仍为 0~CPT-1；真实 column 保存到 column_address
    """

    def __init__(self,
                 num_transactions: int,
                 cmds_per_transaction: int,
                 num_banks: int,
                 banks_per_bank_group: int,
                 addr_mode: str,
                 seed: int,
                 read_ratio: float,
                 addr_map: Optional[dict] = None,
                 configuration: Optional[str] = None,
                 density_code: Optional[int] = None,
                 txn_id_assignment: str = "sequential"):
        """初始化对象状态及其依赖组件。"""
        if txn_id_assignment not in ("sequential", "random"):
            raise ValueError(
                f"txn_id_assignment 必须是 'sequential' 或 'random', 当前 '{txn_id_assignment}'")
        self.num_transactions = num_transactions
        self.cmds_per_transaction = cmds_per_transaction
        self.num_banks = num_banks
        self.banks_per_bank_group = banks_per_bank_group
        self.addr_mode = addr_mode
        self.seed = seed
        self.read_ratio = read_ratio
        self.txn_id_assignment = txn_id_assignment
        # HBM3 SID layout + configuration-derived density/remap.
        self._num_sid, self._groups_per_sid = _compute_sid_layout(
            num_banks, banks_per_bank_group)
        self.configuration, self.density_code, geometry = _normalize_configuration(
            num_banks, configuration, density_code)
        self.sid_remap_type = geometry["sid_remap_type"]
        self.max_system_la = geometry["max_system_la"]
        self.effective_bits = geometry["effective_bits"]
        self._addr_map = (dict(addr_map) if addr_map is not None
                          else _default_addr_map_for(self.sid_remap_type))
        _validate_addr_map(self._addr_map, self.sid_remap_type, self.effective_bits)

    def generate(self) -> Tuple[List[BurstCommandGroup],
                               List[BurstCommandGroup],
                               List[BurstCommandGroup]]:
        """生成 workload，先按完整 page key 分段，再按最多 4 条拆 CAM entry。"""
        rng_main = random.Random(self.seed)
        rng_rw = random.Random(self.seed + RW_RNG_SEED_OFFSET)
        all_entries: List[BurstCommandGroup] = []
        r_entries: List[BurstCommandGroup] = []
        w_entries: List[BurstCommandGroup] = []
        next_dispatch_id = 0

        # txn_id 分配策略:
        #   "sequential": txn_id = 0, 1, 2, ..., num_transactions-1 (默认, 保持向后兼容)
        #   "random"    : 每个 workload 独立 rng_txn.randint(0, num_transactions-1)
        #                  允许重复 (同 txn_id 共享同一 link list) 和空缺 (某些 txn_id 永不出现)
        #   独立 RNG (rng_txn), 不与地址生成 RNG (rng_main) 耦合
        if self.txn_id_assignment == "random":
            rng_txn = random.Random(self.seed + 0xBADCAFE)

        for i in range(self.num_transactions):
            if self.txn_id_assignment == "sequential":
                txn_id = i
            else:  # "random"
                txn_id = rng_txn.randint(0, self.num_transactions - 1)
            if self.addr_mode == "linear":
                base_la = _gen_linear_la(txn_id, self.cmds_per_transaction, self.max_system_la)
            elif self.addr_mode == "random":
                base_la = _gen_random_la(rng_main, self.cmds_per_transaction, self.max_system_la)
            else:
                raise ValueError(f"addr_mode 必须是 'linear' 或 'random', 当前 '{self.addr_mode}'")

            is_write = (rng_rw.random() >= self.read_ratio)
            decoded = []
            for workload_col_index in range(self.cmds_per_transaction):
                command_la = base_la + workload_col_index
                if not _is_la_valid(command_la, self.max_system_la):
                    raise ValueError(
                        f"txn {txn_id} workload crosses protocol range: "
                        f"base_la={base_la}, command_la={command_la}, max={self.max_system_la-1}")
                mapped_la = _remap_12h_la(
                    command_la, self._addr_map, self.sid_remap_type, self.effective_bits)
                column_address, ba, bg, sid, row_id = _extract_addr_fields(
                    mapped_la, self._addr_map)
                if self.sid_remap_type is not None and sid == 0b11:
                    raise AssertionError(f"12H remap failed: SID=11, system_la={command_la}, mapped_la={mapped_la}")
                if self.sid_remap_type == 1 and ((row_id >> 13) & 0b11) == 0b11:
                    raise AssertionError(f"12H type-1 remap failed: ROW[14:13]=11, mapped_la={mapped_la}")
                bank_id = (sid * self._groups_per_sid * self.banks_per_bank_group
                           + bg * self.banks_per_bank_group + ba)
                if bank_id >= self.num_banks:
                    raise ValueError(f"addr_map 将 LA={command_la} 映射到非法 bank_id={bank_id}")
                bank_group_id = bank_id // self.banks_per_bank_group
                decoded.append((workload_col_index, command_la, mapped_la, column_address,
                                ba, bg, sid, row_id, bank_id, bank_group_id))

            # 连续相同 (SID,BG,BA,ROW) 才是一个 page-hit segment。
            segments = []
            current = []
            current_key = None
            for item in decoded:
                key = (item[6], item[5], item[4], item[7])
                if current and key != current_key:
                    segments.append(current)
                    current = []
                current.append(item)
                current_key = key
            if current:
                segments.append(current)

            for segment_id, segment in enumerate(segments):
                dispatch_id = next_dispatch_id
                next_dispatch_id += 1
                segment_cmd_count = len(segment)
                commands: List[ColumnCommand] = []
                for segment_col_index, item in enumerate(segment):
                    (workload_col_index, command_la, mapped_la, column_address,
                     ba, bg, sid, row_id, bank_id, bank_group_id) = item
                    commands.append(ColumnCommand(
                        transaction_id=txn_id,
                        segment_id=segment_id,
                        dispatch_id=dispatch_id,
                        bank_id=bank_id,
                        bank_group_id=bank_group_id,
                        sid_id=sid,
                        ba_id=ba,
                        bg_id=bg,
                        row_id=row_id,
                        col_index=workload_col_index,
                        segment_col_index=segment_col_index,
                        segment_cmd_count=segment_cmd_count,
                        column_address=column_address,
                        logical_address=command_la,
                        mapped_logical_address=mapped_la,
                        is_write=is_write,
                    ))

                for offset in range(0, segment_cmd_count, BURST_GROUP_SIZE):
                    entry_cmds = commands[offset:offset + BURST_GROUP_SIZE]
                    first = entry_cmds[0]
                    entry = BurstCommandGroup(
                        transaction_id=txn_id,
                        segment_id=segment_id,
                        dispatch_id=dispatch_id,
                        bank_id=first.bank_id,
                        bank_group_id=first.bank_group_id,
                        sid_id=first.sid_id,
                        ba_id=first.ba_id,
                        bg_id=first.bg_id,
                        row_id=first.row_id,
                        starting_col_index=first.segment_col_index,
                        commands=entry_cmds,
                    )
                    all_entries.append(entry)
                    (w_entries if is_write else r_entries).append(entry)

        return all_entries, r_entries, w_entries


# ============================================================
#  Col eligibility checker
# ============================================================

class ColEligibilityChecker:
    """检查 ColumnCommand 是否可在当前 cycle 派发 (纯查询, 无副作用).

    5 条约束:
      1. bank 状态 (R/W 分流: READ 要求 ACTING; WRITE 允许 ACT_WAIT + write_timing_satisfied)
      2. txn 匹配 (cmd.dispatch_id == bank.serving_dispatch_id)
      3. col 按序 (cmd.segment_col_index == bank.cols_dispatched)
      4. tCCD (per-bg tCCDl + 全局 tCCDs)
      5. R/W turnaround (R→W: tRTW; W→R: WL+2+tWTR 分 same/diff bg)
    """

    def __init__(self, banks: List[DRAMBank], timing: TimingParameters):
        """初始化对象状态及其依赖组件。"""
        self._banks = banks
        self._timing = timing

    def check(self, col_cmd: ColumnCommand, current_cycle: int,
              bus: _ColBusState) -> bool:
        """检查候选 ColumnCommand 是否满足全部派发约束。"""
        return (self._bank_state_ok(col_cmd, current_cycle)
                and self._txn_and_order_ok(col_cmd)
                and self._tccd_ok(col_cmd, current_cycle, bus)
                and self._turnaround_ok(col_cmd, current_cycle, bus))

    def _bank_state_ok(self, col_cmd: ColumnCommand, current_cycle: int) -> bool:
        """直接按 ACT 时间检查 READ/WRITE 各自的 tRCD。

        READ 检查 tRCDRD，WRITE 检查 tRCDWR，因此两者大小关系不受限制。
        ACT_WAIT/ACTING 只表示 row 已经 ACT，是否能发列命令由时间戳决定。
        """
        bank = self._banks[col_cmd.bank_id]
        if bank.state not in (BankState.ACT_WAIT, BankState.ACTING):
            return False
        required = (self._timing.t_rcdwr_cycles if col_cmd.is_write
                    else self._timing.t_rcdrd_cycles)
        return current_cycle >= bank.last_act_at + required

    def _txn_and_order_ok(self, col_cmd: ColumnCommand) -> bool:
        """检查 dispatch 依赖以及 segment 内命令顺序。"""
        bank = self._banks[col_cmd.bank_id]
        return (col_cmd.dispatch_id == bank.serving_dispatch_id
                and col_cmd.segment_col_index == bank.cols_dispatched)

    def _tccd_ok(self, col_cmd: ColumnCommand, current_cycle: int,
                 bus: _ColBusState) -> bool:
        # 1. per-bg 检查 (same bg 必须 tCCDL=3 DFI)
        """检查同类或跨 bank-group 列命令的 tCCD 约束。"""
        if (current_cycle
                < bus.last_dispatch_cycle_per_bg[col_cmd.bank_group_id]
                + self._timing.t_ccd_l_cycles):
            return False
        # 2. bus-wide 检查 (tCCDS=1 DFI, 任何 col 间隔最小值)
        if current_cycle < bus.last_dispatch_cycle + self._timing.t_ccd_s_cycles:
            return False
        # 3. HBM3 inter-SID tCCDR 检查（READ only；参数单位为 DFI/model cycle）
        #    spec JESD238B.01 Table 93 Note 17: 仅 READ 跨 SID 用 tCCDR, WRITE 仍用 tCCDS
        #    SID 数 (num_sid) per spec Table 5: 16→1, 32→2, 48→4, 64→4
        #    同一 SID 内的不同 bank_group 走 tCCDS, 跨 SID 走 tCCDR
        if (not col_cmd.is_write
                and col_cmd.sid_id != bus.last_dispatch_sid
                and current_cycle < bus.last_dispatch_cycle
                                  + self._timing.t_ccdr_cycles):
            return False
        return True

    def _turnaround_ok(self, col_cmd: ColumnCommand, current_cycle: int,
                       bus: _ColBusState) -> bool:
        """检查读写切换相关的总线 turnaround 约束。"""
        current_type = RWType.WRITE if col_cmd.is_write else RWType.READ
        if bus.last_rw_type in (RWType.NONE, current_type):
            return True
        if current_type == RWType.WRITE:   # R → W: tRTW
            return current_cycle >= bus.last_dispatch_cycle + self._timing.t_rtw_cycles
        # W → R: WL+2+tWTR, same/diff bg 不同
        gap = (self._timing.write_to_read_same_bg_cycles
               if col_cmd.bank_group_id == bus.last_bank_group
               else self._timing.write_to_read_diff_bg_cycles)
        return current_cycle >= bus.last_dispatch_cycle + gap


# ============================================================
#  Refresh scheduler
# ============================================================

@dataclass
class SidRefpbRollingState:
    """每个 SID 独立维护的 REFpb rolling-set 状态。"""
    sid_id: int
    bank_ids: List[int]
    refreshed_mask: int = 0
    set_id: int = 0
    set_start_cycle: int = INITIAL_CYCLE_SENTINEL
    set_complete_cycle: int = INITIAL_CYCLE_SENTINEL
    completed_set_count: int = 0
    max_set_duration: int = 0


class RefreshScheduler:
    """HBM3 REFpb 调度器（v16.3）。

    五层语义严格分离：
      * Channel nominal opportunity：每 tREFIpb 产生一条 REFpb 义务；
      * Channel debt：nominal - actual；debt ≥ max_postpone_credits(默认 8) 触发 mandatory, 范围硬上限 0..9×N (N=num_banks; 协议 "refresh postpone all bank" 9 轮 ↔ per-bank 间隔 ≤ 9×tREFI)；
      * per-SID rolling-set：决定下一条 REFpb 可以选择哪个 bank；
      * per-bank normal/prepare/hard deadline：决定何时开始排空及最晚完成时刻；
      * timing：决定当前 cycle 是否真的允许发 PRE/REFpb。

    第一版不主动 pull-in。rolling-set 查询无副作用，只有 REFpb 真正成功派发时
    才打开下一 set 并更新 bitmap。
    """

    def __init__(self,
                 banks: List[DRAMBank],
                 timing: TimingParameters,
                 num_banks: int,
                 t_refi_per_bank_cycles: int,
                 max_postpone_credits: int = 8,
                 #: 协议 "refresh postpone all bank" 上限轮数 (9×tREFI); fail-fast debt 上限 = 该值 × num_banks
                 max_postpone_refab_rounds: int = 9,
                 #: mandatory 进入后至少刷几个 REFpb 才解除 (迟滞, 避免 debt 附近 on/off 抖动)
                 postpone_low_thr: int = 2,
                 last_refpb_state: Optional[dict] = None,
                 bank_sid: Optional[List[int]] = None,
                 last_act_state: Optional[dict] = None,
                 act_refpb_faw_cycles: Optional[List[int]] = None):
        self._banks = banks
        self._timing = timing
        self._num_banks = num_banks
        self._t_refi_per_bank_cycles = t_refi_per_bank_cycles
        self._t_refi_pb_cycles = max(1, math.ceil(t_refi_per_bank_cycles / num_banks))
        # max_postpone_credits: 触发 mandatory 的 debt 阈值 (REFpb 个数, 默认 8);
        #   mandatory_latch 进入阈值 / prepare_deadline debt-at-limit 项 / _debt_at_limit_cycles 均用它.
        # max_postpone_refab_debt: 协议硬上限 = max_postpone_refab_rounds × num_banks
        #   (9 轮 postpone_refab ↔ per-bank 间隔 ≤ 9×tREFI); 仅用于 fail-fast 与 debt 合法范围校验.
        self._max_postpone_credits = max_postpone_credits
        self._max_postpone_refab_debt = max_postpone_refab_rounds * num_banks
        self._postpone_low_thr = postpone_low_thr
        if postpone_low_thr < 1:
            raise ValueError(f"postpone_low_thr 必须 >= 1, 当前 {postpone_low_thr}")
        # mandatory 迟滞: debt>=max_postpone_credits 进入 latch, 刷满 postpone_low_thr 个 REFpb 才解除
        self._mandatory_latch = False
        self._mandatory_refresh_count = 0
        self._last_refpb_state = last_refpb_state
        self._last_act_state = last_act_state
        self._act_refpb_faw_cycles = (act_refpb_faw_cycles
                                      if act_refpb_faw_cycles is not None else [])

        if bank_sid is None or len(bank_sid) != num_banks:
            raise ValueError("bank_sid 必须提供完整的 bank→SID 映射")
        self._bank_sid = list(bank_sid)

        # ---- Channel nominal opportunity / debt ----
        self._next_nominal_refpb_cycle = 0
        self._nominal_refpb_count = 0
        self._actual_refpb_count = 0
        self._refresh_debt = 0
        self._max_refresh_debt = 0
        self._debt_repaid_count = 0
        self._debt_at_limit_cycles = 0
        self._debt_overflow_count = 0
        self._debt_prevention_trigger_count = 0
        self._time_budget_mandatory_cycles = 0

        # ---- per-SID rolling-set ----
        sid_to_banks = {}
        for bank_id, sid in enumerate(self._bank_sid):
            sid_to_banks.setdefault(sid, []).append(bank_id)
        self._sid_states = {}
        self._bank_local_index = [-1] * num_banks
        self._sid_full_mask = {}
        for sid, bank_ids in sorted(sid_to_banks.items()):
            if len(bank_ids) != 16:
                raise ValueError(f"SID{sid} 必须恰好包含 16 个 bank，当前 {len(bank_ids)}")
            self._sid_states[sid] = SidRefpbRollingState(sid, list(bank_ids))
            self._sid_full_mask[sid] = (1 << len(bank_ids)) - 1
            for local_idx, bank_id in enumerate(bank_ids):
                self._bank_local_index[bank_id] = local_idx

        # ---- cross-SID 串行: 同一时刻只允许一个 SID 进 candidates (先刷完一个 SID 再下一个) ----
        self._num_sid = len(self._sid_states)
        self._active_sid = min(self._sid_states)  # 从最小 SID 开始
        self._advance_pending = False  # 活动 SID 的 set 刚刷完 → 下次 _collect_candidates 推进到下一 SID

        # ---- per-bank refresh age / deadline ----
        stagger = self._t_refi_pb_cycles
        self._normal_due_cycle = [i * stagger for i in range(num_banks)]
        self._last_refresh_cycle = [due - t_refi_per_bank_cycles
                                    for due in self._normal_due_cycle]
        self._hard_deadline_cycle = [last + 9 * t_refi_per_bank_cycles
                                     for last in self._last_refresh_cycle]
        # 动态更新，ColScheduler 用它决定何时停止 page-hit 串接。
        # prepare_deadline 初值仅占位; 首个 cycle 即被 _update_prepare_deadlines 重算为
        # hard_deadline − latency (不再依赖 normal_due).
        self._prepare_deadline_cycle = list(self._hard_deadline_cycle)
        self._next_refresh_cycle = self._prepare_deadline_cycle  # 兼容旧接口
        self._refresh_pending = [False] * num_banks

        # ---- stats ----
        self._refresh_count = 0
        self._force_pre_count = 0
        self._t_ras_wait_count = 0
        self._t_col2pre_wait_count = 0
        self._max_refresh_latency = 0
        self._max_refresh_interval = 0
        self._hard_deadline_violation_event_count = 0
        self._hard_deadline_violation_cycle_count = 0
        self._hard_deadline_violated_banks = set()
        self._hard_deadline_active = [False] * num_banks
        self._hard_deadline_consecutive_cycles = [0] * num_banks
        self._hard_deadline_max_consecutive_cycles = 0
        self._rrefd_blocked_count = 0
        self._trrd_refpb_blocked_count = 0
        self._tfaw_refpb_blocked_count = 0
        # 明确统计语义：bank-cycle 与 SID-cycle，不再冒充“发命令被挡次数”。
        self._rolling_set_blocked_bank_cycles = 0
        self._set_boundary_blocked_sid_cycles = 0
        self._refpb_issue_block_events = 0
        self._bank_not_idle_block_count = 0
        # ---- v16.3 ref策略调整: non-mandatory 路径专用统计 ----
        # 非 mandatory 时, 由于目标 bank 已在 CAM 中而被跳过候选的次数
        self._cam_busy_skip_count = 0
        # 非 mandatory 时, 全部候选 bank 都在 CAM, 本 cycle 选择等待的次数
        self._cam_all_busy_wait_count = 0
        # non-mandatory 时, 让位给 row_scheduler（本 cycle row 发出了 PRE/ACT）,
        # refresh 暂不发, 等待后续 cycle 的次数
        self._non_mandatory_yield_count = 0
        # non-mandatory 路径实际发出 REFpb 的次数 (mandatory 仍走原计数)
        self._non_mandatory_refpb_count = 0
        # non-mandatory 路径累计 nominal opportunity 数 (用于 yield 率计算)
        self._non_mandatory_opportunity_cycles = 0
        # ref_priority: non-mandatory 时, row_scheduler 没发, refresh 兜底发出的次数
        # (= ACT/PRE 都不存在候选, refresh 拿到 row bus 时的 non-mandatory REFpb)
        self._non_mandatory_fallback_issued_count = 0

    def _update_nominal_opportunities(self, current_cycle: int) -> None:
        """推进 nominal opportunity；debt 超过协议上限 (9×N) 前 fail-fast。"""
        while current_cycle >= self._next_nominal_refpb_cycle:
            prospective_nominal = self._nominal_refpb_count + 1
            prospective_debt = prospective_nominal - self._actual_refpb_count
            if prospective_debt > self._max_postpone_refab_debt:
                self._debt_overflow_count += 1
                raise RuntimeError(
                    "REFpb postponed debt 上限违规: "
                    f"cycle={current_cycle}, debt={self._refresh_debt}, "
                    f"next_debt={prospective_debt}, limit={self._max_postpone_refab_debt}, "
                    f"nominal={self._nominal_refpb_count}, actual={self._actual_refpb_count}")
            self._nominal_refpb_count = prospective_nominal
            self._next_nominal_refpb_cycle += self._t_refi_pb_cycles

        self._refresh_debt = self._nominal_refpb_count - self._actual_refpb_count
        if not 0 <= self._refresh_debt <= self._max_postpone_refab_debt:
            raise AssertionError(f"非法 refresh debt={self._refresh_debt}")
        self._max_refresh_debt = max(self._max_refresh_debt, self._refresh_debt)
        if self._refresh_debt >= self._max_postpone_credits:
            self._debt_at_limit_cycles += 1

    def _prune_faw(self, current_cycle: int) -> None:
        cutoff = current_cycle - self._timing.t_faw_cycles
        while self._act_refpb_faw_cycles and self._act_refpb_faw_cycles[0] <= cutoff:
            self._act_refpb_faw_cycles.pop(0)

    # ---- rolling-set：纯查询与成功派发后的提交分开 ----

    def _set_boundary_ready(self, sid: int, current_cycle: int) -> bool:
        state = self._sid_states[sid]
        if state.refreshed_mask != self._sid_full_mask[sid]:
            return True
        return current_cycle >= state.set_complete_cycle + self._timing.t_rfc_pb_cycles

    def _rolling_set_query_allows(self, bank_id: int, current_cycle: int) -> bool:
        sid = self._bank_sid[bank_id]
        state = self._sid_states[sid]
        if state.refreshed_mask == self._sid_full_mask[sid]:
            # boundary 满足时，所有 bank 都是“虚拟下一 set”的合法候选；暂不改状态。
            return self._set_boundary_ready(sid, current_cycle)
        bit = 1 << self._bank_local_index[bank_id]
        return not bool(state.refreshed_mask & bit)

    def _collect_candidates(self, current_cycle: int) -> List[int]:
        # cross-SID 串行: 活动 SID 的 set 刚刷完 → 推进到下一个 SID (幂等: is_mandatory_needed
        # 与 try_issue 都调本函数, 第二次调用时 flag 已清, 不会重复推进).
        if self._advance_pending:
            self._active_sid = (self._active_sid + 1) % self._num_sid
            self._advance_pending = False
        active_sid = self._active_sid
        state = self._sid_states[active_sid]

        # 仅统计活动 SID 的 boundary block (非活动 SID 不参与候选, 不计).
        if (state.refreshed_mask == self._sid_full_mask[active_sid]
                and not self._set_boundary_ready(active_sid, current_cycle)):
            self._set_boundary_blocked_sid_cycles += 1

        # 只收活动 SID 的 bank: 先刷完该 SID 的 16 个, 才允许推进到下一个 SID.
        candidates = []
        for bank_id in state.bank_ids:
            if self._rolling_set_query_allows(bank_id, current_cycle):
                candidates.append(bank_id)
            elif state.refreshed_mask != self._sid_full_mask[active_sid]:
                self._rolling_set_blocked_bank_cycles += 1
        return candidates

    def _open_next_set_for_successful_refpb(self, sid: int, current_cycle: int) -> None:
        state = self._sid_states[sid]
        if state.refreshed_mask != self._sid_full_mask[sid]:
            return
        if not self._set_boundary_ready(sid, current_cycle):
            raise AssertionError(f"SID{sid} set boundary 尚未满足却准备发下一 set REFpb")
        state.set_id += 1
        state.refreshed_mask = 0
        state.set_start_cycle = INITIAL_CYCLE_SENTINEL
        state.set_complete_cycle = INITIAL_CYCLE_SENTINEL

    # ---- prepare deadline / time budget ----

    def _channel_timing_budget(self) -> int:
        return max(self._timing.t_rrefd_cycles,
                   self._timing.t_rrd_l_cycles,
                   self._timing.t_faw_cycles)

    def _estimate_prepare_latency(self, bank_id: int, current_cycle: int) -> int:
        """保守估计从当前 bank 状态到可合法发 REFpb 的剩余 cycle。"""
        bank = self._banks[bank_id]
        channel_wait = self._channel_timing_budget()
        if bank.state == BankState.IDLE:
            return channel_wait
        if bank.state == BankState.REFRESHING:
            remain = max(0, bank._refresh_start_cycle + self._timing.t_rfc_pb_cycles
                         - current_cycle)
            return remain + channel_wait
        if bank.state == BankState.PRE_WAIT:
            return max(0, bank.last_pre_at + self._timing.t_rp_cycles
                       - current_cycle) + channel_wait
        if bank.state == BankState.AUTO_PRE_WAIT:
            return max(0, bank._auto_precharge_complete_cycle - current_cycle) + channel_wait

        # ACT_WAIT 必须等 row 可进入可 PRE 状态；ACTING 同样检查 tRAS/col-to-PRE。
        wait_acting = max(0, bank.last_act_at + self._timing.t_rcdrd_cycles
                          - current_cycle)
        wait_ras = max(0, bank.last_act_at + self._timing.t_ras_cycles
                       - current_cycle)
        if bank.last_col_at == INITIAL_CYCLE_SENTINEL:
            wait_col = 0
        else:
            wait_col = max(0, bank.last_col_at + self._col_to_pre_delay_cycles(bank)
                           - current_cycle)
        return max(wait_acting, wait_ras, wait_col) + self._timing.t_rp_cycles + channel_wait

    def _update_prepare_deadlines(self, current_cycle: int) -> None:
        for bank_id in range(self._num_banks):
            latency = self._estimate_prepare_latency(bank_id, current_cycle)
            # prepare_deadline = "最晚开始排空(force-PRE)的时刻" = hard_deadline − latency.
            # 不与 normal_due 取 min: normal_due 只是 nominal 时刻, 不是 deadline; 提前排空
            # 的唯一理由是赶 hard_deadline. 旧 min(normal_due, hard_deadline−latency) 会在
            # nominal 一到就触发 mandatory, 过度抢占 row bus, 并因 drain-lock 长时间锁死单一
            # bank (见 cycle196 BA2: normal_due=196 即触发 mandatory 锁住 BA2, 其余 13 个可发
            # bank 被忽略直到 274).
            deadline = self._hard_deadline_cycle[bank_id] - latency
            # debt=8 时，下一个 nominal opportunity 是绝对关键边界。
            if self._refresh_debt >= self._max_postpone_credits:
                deadline = min(deadline, self._next_nominal_refpb_cycle - latency)
            self._prepare_deadline_cycle[bank_id] = deadline

    def _candidate_sort_key(self, bank_id: int, current_cycle: int):
        return (self._prepare_deadline_cycle[bank_id],
                self._hard_deadline_cycle[bank_id],
                self._banks[bank_id].state != BankState.IDLE,
                self._last_refresh_cycle[bank_id],
                bank_id)

    def _timing_allows_refpb(self, bank_id: int, current_cycle: int,
                             count_stats: bool = True) -> bool:
        """检查 tRREFD / tRRD_L·S / tFAW 是否允许对本 bank 发 REFpb.

        count_stats=False 时只做判定, 不累加 block 计数 — 供 non-mandatory
        候选遍历使用, 避免一次 cycle 探测多个候选时把 per-reason block
        计数器放大成"每候选一次". mandatory 单目标路径仍用默认 True,
        保持"每 cycle 至多一次"的统计语义.
        """
        bank = self._banks[bank_id]
        if self._last_refpb_state is not None:
            last_cycle = self._last_refpb_state["cycle"]
            last_bank = self._last_refpb_state["bank"]
            if (last_bank != -1 and bank_id != last_bank
                    and current_cycle < last_cycle + self._timing.t_rrefd_cycles):
                if count_stats:
                    self._rrefd_blocked_count += 1
                    self._refpb_issue_block_events += 1
                return False
        if self._last_act_state is not None:
            last_cycle = self._last_act_state["cycle"]
            last_bank = self._last_act_state["bank"]
            last_bg = self._last_act_state["bank_group"]
            if last_bank != -1 and bank_id != last_bank:
                gap = (self._timing.t_rrd_l_cycles
                       if bank.bank_group_id == last_bg
                       else self._timing.t_rrd_s_cycles)
                if current_cycle < last_cycle + gap:
                    if count_stats:
                        self._trrd_refpb_blocked_count += 1
                        self._refpb_issue_block_events += 1
                    return False
        self._prune_faw(current_cycle)
        if len(self._act_refpb_faw_cycles) >= 4:
            if count_stats:
                self._tfaw_refpb_blocked_count += 1
                self._refpb_issue_block_events += 1
            return False
        return True

    def _update_hard_deadline_stats(self, current_cycle: int) -> None:
        for bank_id in range(self._num_banks):
            violated = current_cycle > self._hard_deadline_cycle[bank_id]
            if violated:
                self._hard_deadline_violation_cycle_count += 1
                self._hard_deadline_violated_banks.add(bank_id)
                self._hard_deadline_consecutive_cycles[bank_id] += 1
                self._hard_deadline_max_consecutive_cycles = max(
                    self._hard_deadline_max_consecutive_cycles,
                    self._hard_deadline_consecutive_cycles[bank_id])
                if not self._hard_deadline_active[bank_id]:
                    self._hard_deadline_violation_event_count += 1
                    self._hard_deadline_active[bank_id] = True
            else:
                self._hard_deadline_active[bank_id] = False
                self._hard_deadline_consecutive_cycles[bank_id] = 0

    def _issue_mandatory_refpb(self, bank_id: int, current_cycle: int) -> RowCommand:
        """发出 mandatory REFpb (调用方已确认 IDLE + AC timing OK). 返回 RowCommand."""
        bank = self._banks[bank_id]
        bank.start_refresh(current_cycle)
        self._record_refresh(bank_id, current_cycle)
        if self._last_refpb_state is not None:
            self._last_refpb_state["cycle"] = current_cycle
            self._last_refpb_state["bank"] = bank_id
        self._act_refpb_faw_cycles.append(current_cycle)
        for i in range(self._num_banks):
            self._refresh_pending[i] = (i == bank_id)
        # mandatory latch 计数: 每发一个 mandatory REFpb, count+1; 刷满 postpone_low_thr 解除 latch.
        # 仅 latch=True 时计 (prepare_due 一次性, 不置 latch/不计 count).
        if self._mandatory_latch:
            self._mandatory_refresh_count += 1
            if self._mandatory_refresh_count >= self._postpone_low_thr:
                self._mandatory_latch = False
        return RowCommand(RowCommandType.REFPB, bank_id, -1)

    def _update_mandatory_latch(self) -> None:
        """mandatory 迟滞: debt>=max_postpone_credits 进入 latch (reset count);
        解除由 _issue_mandatory_refpb 刷满 postpone_low_thr 个 REFpb 触发.
        幂等: is_mandatory_needed 与 try_issue 都调, 仅 False→True 跳变时 reset count.
        """
        if self._refresh_debt >= self._max_postpone_credits and not self._mandatory_latch:
            self._mandatory_latch = True
            self._mandatory_refresh_count = 0
            self._debt_prevention_trigger_count += 1

    def try_issue(self, current_cycle: int,
                  cam_busy_banks: Optional[set] = None,
                  via_fallback: bool = False
                  ) -> Tuple[Optional[RowCommand], bool]:
        """尝试发一个 REFpb / force-PRE. 返回 (row_cmd, is_mandatory).

        v16.3 重构:
          - 新增第二个返回值 is_mandatory, 告诉编排器本次发出的 row_cmd 是否
            属于 mandatory 路径 (mandatory_latch / prepare_due).
            mandatory=true 时编排器允许 REFpb 抢占 row bus.
          - 新增 cam_busy_banks 参数: 当前 CAM 中还有未派发 cmd 的 bank 集合.
            非 mandatory 路径会从中过滤候选; 过滤后 candidates 为空则本 cycle
            暂不发 (累计 _cam_all_busy_wait_count), 等下一 cycle 再看.
          - 新增 via_fallback: True 表示本调用是编排器在 row_scheduler 没拿到
            row bus 之后的"兜底"调用. non-mandatory 路径发出时, 同步累加
            _non_mandatory_fallback_issued_count (与原 _non_mandatory_refpb_count
            并行计数, 区分"通过 row_bus 抢占" vs "ACT/PRE 让出来后再发").
        """
        self._update_nominal_opportunities(current_cycle)
        self._update_hard_deadline_stats(current_cycle)
        self._update_prepare_deadlines(current_cycle)
        if self._refresh_debt <= 0:
            for i in range(self._num_banks):
                self._refresh_pending[i] = False
            return None, False
        self._update_mandatory_latch()

        candidates = self._collect_candidates(current_cycle)
        if not candidates:
            return None, False
        candidates.sort(key=lambda bid: self._candidate_sort_key(bid, current_cycle))
        target = candidates[0]  # 最紧急 (排序后第一); mandatory tier 3 force-PRE 用
        prepare_due = current_cycle >= self._prepare_deadline_cycle[target]
        is_mandatory = (self._mandatory_latch or prepare_due)

        # ---- v16.3 非 mandatory 路径: 过滤 CAM 已占用 bank ----
        # 语义: non-mandatory 路径会累计 opportunity cycles (用于统计).
        # 若 cam_busy_banks 过滤后 candidates 为空, 不发 REFpb, 本 cycle "等待".
        if not is_mandatory:
            self._non_mandatory_opportunity_cycles += 1
            if cam_busy_banks:
                raw_count = len(candidates)
                filtered = [b for b in candidates if b not in cam_busy_banks]
                self._cam_busy_skip_count += (raw_count - len(filtered))
                if not filtered:
                    # 所有候选 bank 都在 CAM, 本 cycle 暂不发, 等下一 cycle.
                    self._cam_all_busy_wait_count += 1
                    for i in range(self._num_banks):
                        self._refresh_pending[i] = False
                    return None, False
                # 必须按原始 sort key 重排, 不光按 bank_id, 保证优先级一致.
                candidates = filtered

            # 遍历整组候选 (rolling-set 剩余 ∩ CAM 未占用), 找第一个 IDLE 且
            # AC timing (tRREFD/tRRD/tFAW) 满足的 bank 发出; 全部不满足才放弃.
            # 修复: 旧实现只取 candidates[0] 试 timing, 第一个被挡即 return None,
            #       未遍历组内其余 bank, 导致本可发出的 non-mandatory REFpb 被漏发.
            # 注: 探测用 count_stats=False, per-reason block 计数仅在 mandatory
            #     单目标路径累加, 保持"每 cycle 至多一次"的统计语义; non-mandatory
            #     的"有机会但未发出"由 _non_mandatory_opportunity_cycles 与 issued
            #     计数之差体现.
            for cand in candidates:
                cand_bank = self._banks[cand]
                if cand_bank.state != BankState.IDLE:
                    continue
                if not self._timing_allows_refpb(cand, current_cycle,
                                                 count_stats=False):
                    continue
                # 命中: 发出 non-mandatory REFpb.
                cand_bank.start_refresh(current_cycle)
                self._non_mandatory_refpb_count += 1
                # ref_priority: 仅当本 cycle 是 "row_scheduler 没发 → refresh 兜底"
                # 的调用, 才计 fallback; 否则视作正常 non-mandatory 抢占 row bus
                # (这在 ref_priority 策略下不应该再出现, 但保留计数方便回归).
                if via_fallback:
                    self._non_mandatory_fallback_issued_count += 1
                self._record_refresh(cand, current_cycle)
                if self._last_refpb_state is not None:
                    self._last_refpb_state["cycle"] = current_cycle
                    self._last_refpb_state["bank"] = cand
                self._act_refpb_faw_cycles.append(current_cycle)
                for i in range(self._num_banks):
                    self._refresh_pending[i] = (i == cand)
                return RowCommand(RowCommandType.REFPB, cand, -1), False
            # 整组候选均无法发出 (全非 IDLE 或 AC timing 全不满足).
            for i in range(self._num_banks):
                self._refresh_pending[i] = False
            return None, False

        # ---- mandatory 路径: 三级优先级选 bank (不锁 drain target, 每 cycle 重选) ----
        # tier 1: IDLE + CAM 不命中 + timing OK → 直接 REFpb (零干扰)
        # tier 2: IDLE + CAM 命中  + timing OK → 直接 REFpb (row 已关, CAM 命令延迟 re-ACT)
        # tier 3: ACTING → force-PRE candidates[0] (最紧急); 非 ACTING / 时序不满足则 block
        self._time_budget_mandatory_cycles += 1
        cam_busy = cam_busy_banks if cam_busy_banks is not None else set()

        for tier_need_free in (True, False):
            for cand in candidates:
                if self._banks[cand].state != BankState.IDLE:
                    continue
                in_cam = cand in cam_busy
                if tier_need_free:
                    if in_cam:
                        continue
                elif not in_cam:
                    continue  # not-in-CAM 已在 tier 1 处理
                if not self._timing_allows_refpb(cand, current_cycle, count_stats=False):
                    continue
                return self._issue_mandatory_refpb(cand, current_cycle), True

        # tier 3: force-PRE candidates[0] (最紧急 ACTING); 否则让位等下 cycle
        target = candidates[0]
        for i in range(self._num_banks):
            self._refresh_pending[i] = (i == target)
        bank = self._banks[target]
        if bank.state == BankState.ACTING:
            if current_cycle < bank.last_act_at + self._timing.t_ras_cycles:
                self._t_ras_wait_count += 1
                return None, False
            col2pre = self._col_to_pre_delay_cycles(bank)
            if (bank.last_col_at != INITIAL_CYCLE_SENTINEL
                    and current_cycle < bank.last_col_at + col2pre):
                self._t_col2pre_wait_count += 1
                return None, False
            if bank.force_precharge_for_refresh(current_cycle):
                self._force_pre_count += 1
                return RowCommand(RowCommandType.PRE, target, bank.open_row), True
            self._bank_not_idle_block_count += 1
        return None, False

    def is_mandatory_needed(self, current_cycle: int,
                            cam_busy_banks: Optional[set] = None) -> bool:
        """只判断当前 cycle 是否需要 mandatory REFpb, 不发出命令.

        mandatory 触发: mandatory_latch (debt≥max_postpone_credits 进入, 刷满
        postpone_low_thr 个 REFpb 才解除) 或 prepare_due (candidates[0] 临近 hard_deadline).
        cam_busy_banks 不影响 mandatory 判定 (保留参数为编排器 API 兼容).
        """
        self._update_nominal_opportunities(current_cycle)
        self._update_prepare_deadlines(current_cycle)
        if self._refresh_debt <= 0:
            return False
        self._update_mandatory_latch()
        candidates = self._collect_candidates(current_cycle)
        if not candidates:
            return False
        candidates.sort(key=lambda bid: self._candidate_sort_key(bid, current_cycle))
        target = candidates[0]
        prepare_due = current_cycle >= self._prepare_deadline_cycle[target]
        return bool(self._mandatory_latch or prepare_due)

    def record_yield(self) -> None:
        """编排器在 row_scheduler 成功发命令但 refresh 被让位时调用.

        v16.3: non-mandatory 路径专用计数器. 供编排器表达
        "本 cycle REFpb 本来可以发, 但 row_scheduler 先占了 row bus".
        """
        self._non_mandatory_yield_count += 1

    def _col_to_pre_delay_cycles(self, bank: DRAMBank) -> int:
        return (self._timing.write_ap_cycles
                if bank.last_col_rw_type == RWType.WRITE
                else self._timing.t_rtp_cycles)

    def _record_refresh(self, bank_id: int, current_cycle: int) -> None:
        previous_debt = self._refresh_debt
        self._refresh_count += 1
        self._actual_refpb_count += 1
        self._refresh_debt = self._nominal_refpb_count - self._actual_refpb_count
        if previous_debt > self._refresh_debt:
            self._debt_repaid_count += 1
        self._refresh_pending[bank_id] = False

        old_last = self._last_refresh_cycle[bank_id]
        interval = current_cycle - old_last
        self._max_refresh_interval = max(self._max_refresh_interval, interval)
        self._max_refresh_latency = max(
            self._max_refresh_latency, interval - self._t_refi_per_bank_cycles)
        self._last_refresh_cycle[bank_id] = current_cycle
        self._normal_due_cycle[bank_id] = current_cycle + self._t_refi_per_bank_cycles
        self._hard_deadline_cycle[bank_id] = current_cycle + 9 * self._t_refi_per_bank_cycles
        self._hard_deadline_active[bank_id] = False
        self._hard_deadline_consecutive_cycles[bank_id] = 0

        sid = self._bank_sid[bank_id]
        self._open_next_set_for_successful_refpb(sid, current_cycle)
        state = self._sid_states[sid]
        bit = 1 << self._bank_local_index[bank_id]
        if state.refreshed_mask & bit:
            raise AssertionError(f"SID{sid} set{state.set_id} 内 bank{bank_id} 重复 REFpb")
        if state.refreshed_mask == 0:
            state.set_start_cycle = current_cycle
        state.refreshed_mask |= bit
        if state.refreshed_mask == self._sid_full_mask[sid]:
            state.completed_set_count += 1
            state.set_complete_cycle = current_cycle
            duration = current_cycle - state.set_start_cycle
            state.max_set_duration = max(state.max_set_duration, duration)
            # 活动 SID 的 set 刚刷完 → 标记推进 (下次 _collect_candidates 推进到下一 SID)
            if sid == self._active_sid:
                self._advance_pending = True

    @property
    def refresh_pending(self) -> List[bool]:
        return self._refresh_pending

    @property
    def next_refresh_cycle(self) -> List[int]:
        """兼容接口：v16.2 返回动态 prepare deadline，而非 hard deadline。"""
        return self._next_refresh_cycle

    @property
    def normal_refresh_cycle(self) -> List[int]:
        return self._normal_due_cycle

    @property
    def hard_refresh_deadline(self) -> List[int]:
        return self._hard_deadline_cycle

    def get_stats(self) -> dict:
        sid_stats = {}
        for sid, state in sorted(self._sid_states.items()):
            sid_stats[sid] = {
                "completed_sets": state.completed_set_count,
                "current_set_id": state.set_id,
                "current_progress": bin(state.refreshed_mask).count("1"),
                "set_complete": state.refreshed_mask == self._sid_full_mask[sid],
                "max_set_duration": state.max_set_duration,
            }
        # v16.3: 并 missing 了 mandatory 路径计数与 non-mandatory 路径专用计数 — 上面
        # 各变量已保留。本 dict 同时上报旧字段名 (避免下游脚本报错) 与 v16.3 新字段.
        return {
            "refresh_count": self._refresh_count,
            "force_pre_count": self._force_pre_count,
            "postpone_count": self._refresh_debt,
            "t_ras_wait_count": self._t_ras_wait_count,
            "t_col2pre_wait_count": self._t_col2pre_wait_count,
            "max_refresh_latency": self._max_refresh_latency,
            "max_postpone_observed": self._max_refresh_debt,
            "t_refi_pb_cycles": self._t_refi_pb_cycles,
            "nominal_refpb_count": self._nominal_refpb_count,
            "actual_refpb_count": self._actual_refpb_count,
            "current_debt": self._refresh_debt,
            "max_debt": self._max_refresh_debt,
            "debt_repaid_count": self._debt_repaid_count,
            "debt_at_limit_cycles": self._debt_at_limit_cycles,
            "debt_overflow_count": self._debt_overflow_count,
            "debt_prevention_trigger_count": self._debt_prevention_trigger_count,
            "time_budget_mandatory_cycles": self._time_budget_mandatory_cycles,
            "rrefd_blocked_count": self._rrefd_blocked_count,
            "trrd_refpb_blocked_count": self._trrd_refpb_blocked_count,
            "tfaw_refpb_blocked_count": self._tfaw_refpb_blocked_count,
            "rolling_set_block_count": self._rolling_set_blocked_bank_cycles,
            "rolling_set_blocked_bank_cycles": self._rolling_set_blocked_bank_cycles,
            "set_boundary_block_count": self._set_boundary_blocked_sid_cycles,
            "set_boundary_blocked_sid_cycles": self._set_boundary_blocked_sid_cycles,
            "refpb_issue_block_events": self._refpb_issue_block_events,
            "bank_not_idle_block_count": self._bank_not_idle_block_count,
            "max_refresh_interval": self._max_refresh_interval,
            "hard_deadline_violation_count": self._hard_deadline_violation_event_count,
            "hard_deadline_violation_event_count": self._hard_deadline_violation_event_count,
            "hard_deadline_violation_cycle_count": self._hard_deadline_violation_cycle_count,
            "hard_deadline_violated_bank_count": len(self._hard_deadline_violated_banks),
            "hard_deadline_max_consecutive_cycles": self._hard_deadline_max_consecutive_cycles,
            "sid_stats": sid_stats,
            # v16.3 新增字段
            "cam_busy_skip_count": self._cam_busy_skip_count,
            "cam_all_busy_wait_count": self._cam_all_busy_wait_count,
            "non_mandatory_yield_count": self._non_mandatory_yield_count,
            "non_mandatory_refpb_count": self._non_mandatory_refpb_count,
            "non_mandatory_opportunity_cycles": self._non_mandatory_opportunity_cycles,
            # ref_priority (v16.3+): non-mandatory 时 row 没发 → refresh 兜底发出的次数
            "non_mandatory_fallback_issued_count": self._non_mandatory_fallback_issued_count,
        }

# ============================================================
#  Row scheduler
# ============================================================

class RowScheduler:
    """PRE/ACT 调度: 优先 PRE, 然后 ACT, RR 仲裁.

    自持有 ACT 通道 tracker (last_act_cycle 全局/per-bg, recent_act_cycles 供 tFAW),
    派发成功后自行更新, 编排器只需计数.

    v17+: 新增 BG 交织 ACT 选优 (默认开). 维护每个 SID 的 last_act_bg, 选 ACT
    时优先同 SID 不同 BG 的 bank, 提升 BG 级并行, 减少 tRRDL 集中.
    """

    def __init__(self, banks: List[DRAMBank], timing: TimingParameters,
                 num_bank_groups: int,
                 num_sid: int = 0,
                 last_refpb_state: Optional[dict] = None,
                 bank_sid: Optional[List[int]] = None,
                 last_act_state: Optional[dict] = None,
                 act_refpb_faw_cycles: Optional[List[int]] = None,
                 bg_interleave_priority: bool = True,
                 age_priority: bool = True):
        """初始化对象状态及其依赖组件。

        v17+: bg_interleave_priority=True 时启用 ACT BG 交织优先级.
        v18+: age_priority=True 时启用 ACT Age 优先级 (选等待最久的 bank).
              age > BG 交织 > RR 三级排序; age 不同时 BG 不看.
        """
        self._banks = banks
        self._timing = timing
        self._rr_pointer = 0
        self._last_act_cycle = INITIAL_CYCLE_SENTINEL
        self._last_act_cycle_per_bg = [INITIAL_CYCLE_SENTINEL] * num_bank_groups
        self._recent_act_cycles: List[int] = []
        self._last_act_state = last_act_state
        self._act_refpb_faw_cycles = (act_refpb_faw_cycles
                                      if act_refpb_faw_cycles is not None else [])
        # tRREFD (JESD238B.01 §6.3.2.6 Table 35): REFpb → ACT (different bank)
        # 由 RefreshScheduler 写, 这里读. Channel 全局 shared state.
        self._last_refpb_state = last_refpb_state
        self._bank_sid = bank_sid
        self._rrefd_act_blocked_count: int = 0  # tRREFD 闸在 ACT 路径上 block 的次数
        # v17+: BG 交织优先级
        self._bg_interleave_priority: bool = bg_interleave_priority
        # 推断 num_sid: 优先用参数, 否则从 banks 推 (max(bank_sid)+1), 兜底 num_bank_groups
        if num_sid > 0:
            self._num_sid: int = num_sid
        elif bank_sid is not None and len(bank_sid) > 0:
            self._num_sid = max(bank_sid) + 1
        else:
            self._num_sid = max(1, num_bank_groups // 4)
        # per-SID 上次 ACT 的 BG (初始 -1 表示该 SID 还没 ACT 过)
        self._last_act_bg_per_sid: List[int] = [-1] * self._num_sid
        # BG 交织统计
        self._bg_interleave_hits: int = 0       #: 选中 BG 不同于同 SID 上次 ACT 的次数
        self._bg_interleave_fallback: int = 0    #: 无可用不同 BG, 退回同 BG 的次数
        # v18+: Age 优先级
        self._age_priority: bool = age_priority
        self._age_priority_used: int = 0         #: 实际用 age 选优的次数 (即 age 不是平局)
        self._max_age_seen: int = 0             #: 仿真期内见过的最大 age (cycles)

    def try_issue(self, current_cycle: int,
                  cams: List[BurstCommandGroup]) -> Optional[RowCommand]:
        """尝试发一个 Row 命令: 先 PRE 后 ACT, 每 cycle 最多一个.

        cams 是当前 mode 可见的 CAM 列表, 由 ColScheduler.get_row_candidate_cams 决定:
          - NORMAL READ  → [read_cam]
          - NORMAL WRITE → [write_cam]
          - PREPARING    → [read_cam, write_cam]

        ACT 按 cams 里的 bank 通道化 (mode 语义: 不给对向 bank 提前 ACT);
        PRE 不通道化, 扫全部 bank — autoprecharge 是 bank 自治行为,
        对向 mode 遗留的已完成 bank 必须能被 PRE, 否则永久挂在 ACTING.
        """
        row_cmd = self._try_precharge(current_cycle)
        if row_cmd is None:
            row_cmd = self._try_activate(current_cycle, cams)
        if row_cmd is not None and row_cmd.kind == RowCommandType.ACT:
            bank = self._banks[row_cmd.bank_id]
            self._last_act_cycle = current_cycle
            self._last_act_cycle_per_bg[bank.bank_group_id] = current_cycle
            self._recent_act_cycles.append(current_cycle)
            self._act_refpb_faw_cycles.append(current_cycle)
            if self._last_act_state is not None:
                self._last_act_state["cycle"] = current_cycle
                self._last_act_state["bank"] = bank.bank_id
                self._last_act_state["bank_group"] = bank.bank_group_id
            # v17+: 更新 per-SID last ACT BG (供下次 BG 交织选优用)
            if self._bg_interleave_priority and self._bank_sid is not None:
                sid_id = self._bank_sid[bank.bank_id]
                if 0 <= sid_id < self._num_sid:
                    self._last_act_bg_per_sid[sid_id] = bank.bank_group_id
        return row_cmd

    # ---- PRE ----

    def _try_precharge(self, current_cycle: int) -> Optional[RowCommand]:
        """PRE 扫全部 bank (不按 mode 通道化).

        只有 precharge_pending=True 的 bank 会被 PRE (即已完成全部 col 的 bank),
        这是 bank 自治的收尾行为, 与当前 mode 无关. 若按 mode 过滤, 对向 mode
        遗留的已完成 bank 会永远等不到 PRE, 进而挡住该 bank 后续所有 ACT.
        """
        pre_eligible = self._collect_pre_eligible_banks(current_cycle)
        if not pre_eligible:
            return None

        selected = self._rr_select(pre_eligible, lambda b: b.bank_id)
        selected.state = BankState.PRE_WAIT
        selected.last_pre_at = current_cycle
        selected.precharge_pending = False
        return RowCommand(RowCommandType.PRE, selected.bank_id, selected.open_row)

    def _collect_pre_eligible_banks(self, current_cycle: int) -> List[DRAMBank]:
        """PRE 条件: precharge_pending + ACTING +
        距 last_col ≥ tColToPre(R/W 分流) + 距 last_act ≥ tRAS"""
        result = []
        for bank in self._banks:
            if not (bank.precharge_pending and bank.state == BankState.ACTING):
                continue
            if current_cycle < bank.last_col_at + self._col_to_pre_delay_cycles(bank):
                continue
            if current_cycle < bank.last_act_at + self._timing.t_ras_cycles:
                continue
            result.append(bank)
        return result

    def _col_to_pre_delay_cycles(self, bank: DRAMBank) -> int:
        """READ: t_rtp_cycles; WRITE: write_ap_cycles (= WL+2+tWR)"""
        if bank.last_col_rw_type == RWType.WRITE:
            return self._timing.write_ap_cycles
        return self._timing.t_rtp_cycles

    # ---- ACT ----

    def _try_activate(self, current_cycle: int,
                      cams: List[BurstCommandGroup]) -> Optional[RowCommand]:
        # 短路: 全局 t_rrd_s / t_faw 不满足直接跳过 (避免无谓的 bank 遍历)
        """收集并选择当前周期可以发出的 ACT 命令。"""
        if current_cycle < self._last_act_cycle + self._timing.t_rrd_s_cycles:
            return None
        cutoff = current_cycle - self._timing.t_faw_cycles
        while self._act_refpb_faw_cycles and self._act_refpb_faw_cycles[0] <= cutoff:
            self._act_refpb_faw_cycles.pop(0)
        if len(self._act_refpb_faw_cycles) >= 4:
            return None

        act_eligible = self._collect_act_eligible_banks(current_cycle, cams)
        if not act_eligible:
            return None

        # v17+: BG 交织优先级 (默认开) — 优先选同 SID 不同 BG 的 bank
        # v18+: Age 优先级 (默认开) — age > BG 交织 > RR, age 是主排序
        if self._age_priority:
            bank, row_id, dispatch_id = self._select_act_with_age_priority(
                act_eligible, cams, current_cycle)
        elif self._bg_interleave_priority:
            bank, row_id, dispatch_id = self._select_act_with_bg_priority(act_eligible)
        else:
            bank, row_id, dispatch_id = self._rr_select(act_eligible, lambda x: x[0].bank_id)
        bank.state = BankState.ACT_WAIT
        bank.last_act_at = current_cycle
        bank.serving_dispatch_id = dispatch_id
        bank.open_row = row_id
        bank.page_hit_chain_active = False
        bank.write_timing_satisfied = False
        return RowCommand(RowCommandType.ACT, bank.bank_id, row_id)

    def _select_act_with_bg_priority(self,
                                    candidates: List[Tuple['DRAMBank', int, int]]
                                    ) -> Tuple['DRAMBank', int, int]:
        """v17+: BG 交织优先级选 bank.

        规则: 优先选 BG 不同于该 SID 上次 ACT 的 bank. 内部 RR 选最小 bank_id.
        无可用不同 BG 的候选时, 退回所有候选, 累加 fallback 计数.

        Returns: (bank, row_id, dispatch_id) 三元组.
        """
        preferred = []
        for entry in candidates:
            bank = entry[0]
            sid_id = self._bank_sid[bank.bank_id] if self._bank_sid is not None else 0
            last_bg = (self._last_act_bg_per_sid[sid_id]
                       if 0 <= sid_id < self._num_sid else -1)
            # 优先条件: 该 SID 已 ACT 过 (last_bg != -1) 且当前 BG != last_bg
            if last_bg != -1 and bank.bank_group_id != last_bg:
                preferred.append(entry)

        if preferred:
            self._bg_interleave_hits += 1
            return self._rr_select(preferred, lambda x: x[0].bank_id)

        # 无 BG 不同的候选: 退回所有 candidates (同 BG 或初始 -1 状态)
        self._bg_interleave_fallback += 1
        return self._rr_select(candidates, lambda x: x[0].bank_id)

    # ---- v18+ Age 优先级 ----

    def _compute_bank_act_age(self, bank: 'DRAMBank',
                             cams: List['BurstCommandGroup'],
                             current_cycle: int) -> int:
        """v18+: 算 bank 的 ACT 等待年龄 = current_cycle - min(entry.entry_cycle).

        仅考虑 cams 里 bank_id 匹配且仍有未派发 cmd 的 burst entry.
        若 bank 不在 cams 中 (cams 列表为空场景), 返回 0.
        """
        min_cycle = None
        for entry in cams:
            if entry.bank_id != bank.bank_id:
                continue
            if entry.next_dispatch_index >= len(entry.commands):
                continue
            if min_cycle is None or entry.entry_cycle < min_cycle:
                min_cycle = entry.entry_cycle
        if min_cycle is None:
            return 0
        return current_cycle - min_cycle

    def _select_act_with_age_priority(self,
                                    candidates: List[Tuple['DRAMBank', int, int]],
                                    cams: List['BurstCommandGroup'],
                                    current_cycle: int) -> Tuple['DRAMBank', int, int]:
        """v18+: Age 优先级选 bank (age > BG 交织 > RR).

        排序键: (-age, bg_interleave_score, bank_id)
          - age 越大越优先 (主)
          - BG 不同于该 SID 上次 ACT 的优先 (次)
          - 同样条件下 bank_id 升序 (RR, last tiebreaker)
        """
        max_age = 0

        def sort_key(entry):
            nonlocal max_age
            bank = entry[0]
            age = self._compute_bank_act_age(bank, cams, current_cycle)
            if age > max_age:
                max_age = age
            # BG 交织得分: 0 = 不同 BG (优先), 1 = 同 BG (或初始)
            sid_id = (self._bank_sid[bank.bank_id]
                      if self._bank_sid is not None else 0)
            last_bg = (self._last_act_bg_per_sid[sid_id]
                       if 0 <= sid_id < self._num_sid else -1)
            bg_score = 0 if (last_bg != -1 and bank.bank_group_id != last_bg) else 1
            return (-age, bg_score, bank.bank_id)

        sorted_candidates = sorted(candidates, key=sort_key)
        # 统计: 选出的 bank 是否真的是 age 最大的 (非并列)
        top_age = self._compute_bank_act_age(sorted_candidates[0][0], cams, current_cycle)
        second_age = (self._compute_bank_act_age(sorted_candidates[1][0], cams, current_cycle)
                      if len(sorted_candidates) > 1 else top_age)
        if top_age > second_age:
            self._age_priority_used += 1
        if max_age > self._max_age_seen:
            self._max_age_seen = max_age
        return sorted_candidates[0]

    def _collect_act_eligible_banks(self, current_cycle: int,
                                    cams: List[BurstCommandGroup]
                                    ) -> List[Tuple[DRAMBank, int, int]]:
        """ACT 条件: IDLE + 距 last_act ≥ tRC + 同 bg 距 last_act ≥ tRRDl + cams 有该 bank 待派发 cmd

        cams 由 ColScheduler.get_row_candidate_cams 决定 (按 mode 通道化),
        所以这里只在当前 mode (或准备期的目标 mode) 涉及的 bank 里找 ACT 机会.

        v6.7: 加 tRREFD 闸 (JESD238B.01 §6.3.2.6 Table 35 NOTE 3)
          REFpb → ACT（不同 bank，跨 SID 生效）≥ 8ns = t_rrefd_cycles
          同 bank 情况由 state != IDLE 排除 (tRFCpb 240 cycles 保护).
        """
        result = []
        for bank in self._banks:
            if bank.state != BankState.IDLE:
                continue
            if current_cycle < bank.last_act_at + self._timing.t_rc_cycles:
                continue
            if (current_cycle
                    < self._last_act_cycle_per_bg[bank.bank_group_id]
                    + self._timing.t_rrd_l_cycles):
                continue
            # tRREFD: 最近 REFpb 作用于其他 bank 时，跨 SID 同样需要等待
            if self._last_refpb_state is not None:
                last_cycle = self._last_refpb_state["cycle"]
                last_bank = self._last_refpb_state["bank"]
                if (last_bank != -1 and bank.bank_id != last_bank
                        and current_cycle < last_cycle + self._timing.t_rrefd_cycles):
                    self._rrefd_act_blocked_count += 1
                    continue
            for burst_entry in cams:
                if burst_entry.bank_id != bank.bank_id:
                    continue
                if burst_entry.next_dispatch_index >= len(burst_entry.commands):
                    continue
                col_cmd = burst_entry.commands[burst_entry.next_dispatch_index]
                if col_cmd.segment_col_index == bank.cols_dispatched:
                    result.append((bank, col_cmd.row_id, col_cmd.dispatch_id))
                    break
        return result

    # ---- RR ----

    def _rr_select(self, candidates: List, key_fn):
        """从 rr_pointer 找第一个 key ≥ pointer, 找不到 wrap 到最小 key"""
        candidates_sorted = sorted(candidates, key=key_fn)
        selected = next(
            (c for c in candidates_sorted if key_fn(c) >= self._rr_pointer),
            candidates_sorted[0]
        )
        self._rr_pointer = (key_fn(selected) + 1) % len(self._banks)
        return selected

    # ---- v17+ 统计 ----

    def get_bg_interleave_stats(self) -> dict:
        """v17+: 返回 BG 交织 ACT 选优统计.

        字段:
          enabled              : bg_interleave_priority 是否开启
          bg_interleave_hits   : 选中 BG 不同于同 SID 上次 ACT 的次数
          bg_interleave_fallback: 无可用不同 BG, 退回原 RR 的次数
          last_act_bg_per_sid  : 各 SID 当前 last ACT 的 BG (sanity)
        """
        return {
            'enabled': self._bg_interleave_priority,
            'bg_interleave_hits': self._bg_interleave_hits,
            'bg_interleave_fallback': self._bg_interleave_fallback,
            'last_act_bg_per_sid': list(self._last_act_bg_per_sid),
        }

    def get_age_priority_stats(self) -> dict:
        """v18+: 返回 Age 优先级 ACT 选优统计.

        字段:
          enabled            : age_priority 是否开启
          age_priority_used  : age 实际生效 (选出的 bank 是 age 最大且非并列) 的次数
          max_age_seen       : 仿真期内见过的最大 ACT 等待年龄 (cycles)
        """
        return {
            'enabled': self._age_priority,
            'age_priority_used': self._age_priority_used,
            'max_age_seen': self._max_age_seen,
        }


# ============================================================
#  Col scheduler
# ============================================================

class ColScheduler:
    """R/W Column 调度: Batch (stick-to-one-side) 或 Alternating.

    自持有 Col 通道 tracker (_ColBusState: last dispatch cycle 全局/per-bg +
    turnaround 所需的 last_rw_type/last_bank_group), 一笔派发的全部副作用
    (bank 状态、bus tracker、CAM 移除、autoprecharge 触发) 都在 _try_issue_of_type
    一处完成.
    """

    def __init__(self,
                 banks: List[DRAMBank],
                 timing: TimingParameters,
                 num_banks: int,
                 num_bank_groups: int,
                 num_sid: int,
                 cmds_per_transaction: int,
                 batch_scheduling: bool,
                 batch_timeout_cycles: int,
                 initial_batch_type: RWType,
                 preparation_min_banks: int = 8,
                 preparation_max_dispatches: int = 16,
                 preparation_max_cycles: int = 64,
                 sid_aware: bool = False,
                 write_auto_precharge: bool = True,
                 read_auto_precharge: bool = True,
                 refresh_pending: Optional[List[bool]] = None,
                 next_refresh_cycle: Optional[List[int]] = None,
                 wra_refresh_guard_cycles: int = 64,
                 rda_refresh_guard_cycles: int = 256,
                 wra_only_after_page_hit: bool = False,
                 rda_only_after_page_hit: bool = False,
                 rw_4state_mode: bool = True):
        """初始化对象状态及其依赖组件。"""
        self._banks = banks
        self._timing = timing
        self._eligibility = ColEligibilityChecker(banks, timing)
        self._num_banks = num_banks
        self._num_sid = num_sid
        self._cmds_per_transaction = cmds_per_transaction
        self._batch_scheduling = batch_scheduling
        self._batch_timeout_cycles = batch_timeout_cycles
        # SID-aware 软优化: 派发时优先选同 SID (避免不必要的 tCCDR 等待);
        # 仅在同 SID 池为空时退到跨 SID 池. 默认 off (向后兼容).
        self._sid_aware = sid_aware
        self._write_auto_precharge = write_auto_precharge
        self._read_auto_precharge = read_auto_precharge
        self._refresh_pending = refresh_pending
        self._next_refresh_cycle = next_refresh_cycle
        self._wra_refresh_guard_cycles = max(0, wra_refresh_guard_cycles)
        self._rda_refresh_guard_cycles = max(0, rda_refresh_guard_cycles)
        self._wra_only_after_page_hit = wra_only_after_page_hit
        self._rda_only_after_page_hit = rda_only_after_page_hit
        # 准备期参数 (timeout 后两阶段切模式机制)
        self._preparation_min_banks = preparation_min_banks
        self._preparation_max_dispatches = preparation_max_dispatches
        self._preparation_max_cycles = preparation_max_cycles
        # v16.3+ 新增: 4 态 R/W 调度状态机
        self._rw_4state_mode: bool = rw_4state_mode
        self._rw_state: RWState = RWState.RD
        self._rw_switch_timer: int = 0   #: 倒计时, batch_timeout_cycles → 0
        # 4 态机统计
        self._rw_4state_direct_switch: int = 0    #: RD→WR / WR→RD (empty 触发的直切)
        self._rw_4state_enter_transition: int = 0  #: 进入 RD_WR / WR_RD 的次数
        self._rw_4state_exit_transition: int = 0   #: 从 RD_WR / WR_RD 退出的次数
        # 新增: 过渡态退出时, 触发原因是 "对向已开够 ACT" 的次数
        # RD_WR → WR 时, WR CAM 中已 ACT (state ∈ {ACT_WAIT, ACTING}) 的 bank 数 ≥ preparation_min_banks
        # WR_RD → RD 时, RD CAM 中已 ACT 的 bank 数 ≥ preparation_min_banks
        self._rw_4state_exit_via_target_act: int = 0  #: 退出过渡态时, 对向已开够 ACT 的次数
        # 各状态驻留 cycle 数 (for summary)
        self._rw_4state_cycles_in_state: dict = {
            'RD': 0, 'WR': 0, 'RD_WR': 0, 'WR_RD': 0,
        }

        self._bus = _ColBusState(num_bank_groups, num_sid)
        self._rr_pointer_read = 0
        self._rr_pointer_write = 0
        self._current_batch_type = initial_batch_type
        self._current_batch_dispatch_count = 0
        self._rr_pointer_drain = 0
        self._current_stuck_cycles = 0   #: 当前 mode + drain 连续不可派发的 cycle 数
        self._drain_dispatch_count = 0   #: drain (in-flight 对向 txn 续发) 总次数

        # ---- 准备期状态 ----
        # _preparation_state is None → NORMAL 模式
        # _preparation_state is dict  → PREPARING:
        #   {
        #     'target': RWType,                   # 准备切到哪一侧
        #     'target_banks_snapshot': set[int],  # 进入时 snapshot 的对向 CAM 涉及的 bank
        #     'start_cycle': int,                 # 进入准备期的 cycle
        #     'dispatch_count': int,              # 准备期内 current mode 已发的 R/W 条数
        #     'act_count': int,                   # 准备期内发生在 target bank 上的 ACT 数
        #     'pre_count': int,                   # 准备期内发生在 target bank 上的 PRE 数
        #   }
        self._preparation_state: Optional[dict] = None

        # 准备期统计 (for summary)
        self._preparation_phase_count: int = 0
        self._preparation_total_cycles: int = 0
        self._preparation_exit_counts: dict = {
            'ready': 0, 'max_dispatches': 0, 'current_empty': 0, 'prep_timeout': 0}
        # timeout 触发后, 对向已 ready 直接 atomic 切, 不进 prep 的次数
        # (与 _preparation_phase_count 互补: 两者之和 = timeout 触发的总切换数)
        self._atomic_switch_count: int = 0
        # current 模式 CAM 空 + 对向有活 触发的 empty-fallback 切换次数
        # 50/50 + channelized 设计下, 这是最频繁的切换路径 (timeout 几乎不触发)
        self._empty_fallback_count: int = 0
        # 每次准备期的明细 (按完成顺序追加), 供 per-prep log 用
        self._preparation_history: List[dict] = []

        # ---- SID-aware 统计 (仅在 sid_aware=True 时累计) ----
        self._sid_aware_same_hits: int = 0   #: 同 SID 池有候选, 实际选了同 SID 的次数
        self._sid_aware_fallback: int = 0    #: 同 SID 池空, 退到跨 SID 池的次数

        # ---- WRA/RDA 自动预充电统计 ----
        self._wra_count: int = 0
        self._rda_count: int = 0
        self._normal_write_count: int = 0
        self._normal_read_count: int = 0
        self._write_page_hit_chain_count: int = 0
        self._read_page_hit_chain_count: int = 0

    def try_issue(self, current_cycle: int,
                  read_cam: List[BurstCommandGroup],
                  write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """按模式选择调度策略, 尝试发一个 Col 命令.

        v16.3+: rw_4state_mode=True 时走 4 态机 (RD/WR/RD_WR/WR_RD), 否则走
        原有 batch (preparation) 或 alternating 模式.
        """
        if self._rw_4state_mode:
            return self._try_issue_4state(current_cycle, read_cam, write_cam)
        if self._batch_scheduling:
            return self._try_issue_batch(current_cycle, read_cam, write_cam)
        return self._try_issue_alternating(current_cycle, read_cam, write_cam)

    # ---- v16.3+ 4 态 R/W 调度状态机 ----

    def _update_rw_state(self, current_cycle: int,
                         read_cam: List[BurstCommandGroup],
                         write_cam: List[BurstCommandGroup]) -> None:
        """更新 4 态 R/W 状态机 (每 cycle try_issue 开头调用一次).

        转移规则 (用户规约):
          RD → WR     : RD CAM 空 且 WR CAM 有活 (直切, 不走过渡)
          RD → RD_WR  : WR CAM 有活, 倒计时从 batch_timeout_cycles → 0
          RD_WR → WR  : WR CAM 有可派发命令 (bank ACT + col ready) 或 RD CAM 已空
                       或 **WR 已开 ≥ preparation_min_banks 个 ACT 且至少 1 个 col ready**
          WR → RD     : WR CAM 空 且 RD CAM 有活
          WR → WR_RD  : RD CAM 有活, 倒计时 → 0
          WR_RD → RD  : RD CAM 有可派发命令 或 WR CAM 已空
                       或 **RD 已开 ≥ preparation_min_banks 个 ACT 且至少 1 个 col ready**
        """
        # 统计: 上一 cycle 处于哪个 state
        self._rw_4state_cycles_in_state[self._rw_state.name] += 1

        state = self._rw_state
        rd_has = self._cam_has_unprocessed(read_cam)
        wr_has = self._cam_has_unprocessed(write_cam)

        if state == RWState.RD:
            if not rd_has and wr_has:
                # 规则 1: RD CAM 空, WR 有活, 直切
                self._rw_state = RWState.WR
                self._rw_switch_timer = 0
                self._rw_4state_direct_switch += 1
            elif wr_has:
                # 规则 2: WR 有活, 倒计时
                if self._rw_switch_timer == 0:
                    self._rw_switch_timer = self._batch_timeout_cycles
                else:
                    self._rw_switch_timer -= 1
                    if self._rw_switch_timer == 0:
                        self._rw_state = RWState.RD_WR
                        self._rw_4state_enter_transition += 1
            # else: wr 没活, 保持 RD, 不动 timer

        elif state == RWState.WR:
            if not wr_has and rd_has:
                self._rw_state = RWState.RD
                self._rw_switch_timer = 0
                self._rw_4state_direct_switch += 1
            elif rd_has:
                if self._rw_switch_timer == 0:
                    self._rw_switch_timer = self._batch_timeout_cycles
                else:
                    self._rw_switch_timer -= 1
                    if self._rw_switch_timer == 0:
                        self._rw_state = RWState.WR_RD
                        self._rw_4state_enter_transition += 1

        elif state == RWState.RD_WR:
            # 退出条件 (3 选 1):
            #   a) WR CAM 有可派发命令 (bank ACT + col ready) — target 立即可用
            #   b) RD CAM 已空 — source drain 完毕, 无需过渡
            #   c) WR 已开 ≥ preparation_min_banks 个 ACT 且 至少 1 个 col ready
            #      (target ACT 池足够 + 不需要等 tRCD, 可立即切到 WR)
            wr_dispatchable = wr_has and self._has_dispatchable(
                current_cycle, RWType.WRITE, read_cam, write_cam)
            wr_acted_count = self._count_acted_banks_in_cam(write_cam)
            wr_target_ready = (wr_acted_count >= self._preparation_min_banks
                               and wr_dispatchable)
            if wr_dispatchable or not rd_has or wr_target_ready:
                self._rw_state = RWState.WR
                self._rw_switch_timer = 0
                self._rw_4state_exit_transition += 1
                # 退出原因 = 新条件 (ACT ≥ N 且 col ready 且 source 未空)
                if wr_target_ready and rd_has:
                    self._rw_4state_exit_via_target_act += 1

        elif state == RWState.WR_RD:
            # 退出条件 (3 选 1):
            #   a) RD CAM 有可派发命令 (bank ACT + col ready)
            #   b) WR CAM 已空
            #   c) RD 已开 ≥ preparation_min_banks 个 ACT 且 至少 1 个 col ready
            rd_dispatchable = rd_has and self._has_dispatchable(
                current_cycle, RWType.READ, read_cam, write_cam)
            rd_acted_count = self._count_acted_banks_in_cam(read_cam)
            rd_target_ready = (rd_acted_count >= self._preparation_min_banks
                               and rd_dispatchable)
            if rd_dispatchable or not wr_has or rd_target_ready:
                self._rw_state = RWState.RD
                self._rw_switch_timer = 0
                self._rw_4state_exit_transition += 1
                if rd_target_ready and wr_has:
                    self._rw_4state_exit_via_target_act += 1

    def _count_acted_banks_in_cam(self, cam: List[BurstCommandGroup]) -> int:
        """统计 cam 中涉及的 bank 中, 已处于 ACT_WAIT 或 ACTING 状态的 distinct bank 数.

        用途: 4 态机过渡态退出判定. 当对向 CAM 中已 ACT 的 bank 数
        达到 preparation_min_banks (且对向有 ≥1 个 col ready), 视为"target ACT 池
        已开够 + 切过去能立刻派发", 允许提前退出过渡态.

        注意: 仅算 `next_dispatch_index < len(commands)` 的 entry (还有活要派发);
        已全派发的 entry 涉及的 bank 不算 (该 bank 已被 autoprecharge, 与 target 无关).
        """
        acted_banks = set()
        for entry in cam:
            if entry.next_dispatch_index >= len(entry.commands):
                continue
            bank = self._banks[entry.bank_id]
            if bank.state in (BankState.ACT_WAIT, BankState.ACTING):
                acted_banks.add(entry.bank_id)
        return len(acted_banks)

    def _try_issue_4state(self, current_cycle: int,
                          read_cam: List[BurstCommandGroup],
                          write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """4 态 R/W 调度主入口.

        每 cycle 流程:
          1. _update_rw_state — 检查是否要切态
          2. 根据当前 state 决定派发哪个 CAM 的 col 命令:
             - RD     : RD CAM RD 命令
             - WR     : WR CAM WR 命令
             - RD_WR  : RD CAM RD 命令 (drain), WR CAM 由 row 侧开 ACT
             - WR_RD  : WR CAM WR 命令 (drain), RD CAM 由 row 侧开 ACT
        """
        self._update_rw_state(current_cycle, read_cam, write_cam)
        state = self._rw_state

        if state == RWState.RD:
            return self._try_issue_of_type(current_cycle, RWType.READ, read_cam, write_cam)
        if state == RWState.WR:
            return self._try_issue_of_type(current_cycle, RWType.WRITE, read_cam, write_cam)
        if state == RWState.RD_WR:
            # 过渡: 只发 RD (drain RD CAM), 不发 WR col
            return self._try_issue_of_type(current_cycle, RWType.READ, read_cam, write_cam)
        if state == RWState.WR_RD:
            # 过渡: 只发 WR (drain WR CAM), 不发 RD col
            return self._try_issue_of_type(current_cycle, RWType.WRITE, read_cam, write_cam)
        return None

    # ---- Batch 策略 ----

    def _try_issue_batch(self, current_cycle: int,
                         read_cam: List[BurstCommandGroup],
                         write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """stick-to-one-side + 准备期 (preparation phase) 机制.

        这是两阶段切模式的核心入口, 优先级链:

        1. 已经在准备期 → 走 _continue_preparation (检 exit, 继续发 current R/W)
        2. 不在准备期:
           a. timeout 触发 + A2 满足 + 对向有活 (has_work):
              - 若对向已 ready (row scheduler 提前 ACT 好) → atomic 切 (不进 prep)
              - 否则 → 进入准备期, 走 _continue_preparation
           b. empty-fallback: current 侧没活干 (has_work=False) + 对向有活 → atomic 切
              关键: 切完才能让 row scheduler 给对向 bank ACT, 不切就永远卡住
           c. 否则, 继续按 current_batch_type 发

        准备期内不再走 empty-fallback 跳切, 避免绕过准备期直接 atomic 切.

        "有活干" (has_work) vs "可派发" (dispatchable) 的区别:
          - has_work  : CAM 里还有未处理的 cmd, 不管 bank 状态
          - dispatchable: 现在就能派发 (bank state OK + 时序 OK)
        切模式决策用 has_work, 实际派发用 _try_issue_of_type 内部检查 dispatchable.
        """
        current_type = self._current_batch_type
        other_type = _opposite_type(current_type)

        # 当前 mode 和对向 mode 的 CAM 引用
        current_cam = read_cam if current_type == RWType.READ else write_cam
        other_cam = write_cam if current_type == RWType.READ else read_cam

        # 切模式决策: 看 "有活干" (不卡 dispatchable — 切完才能 ACT)
        current_has_work = self._cam_has_unprocessed(current_cam)
        other_has_work = self._cam_has_unprocessed(other_cam)
        other_starving = (self._oldest_entry_wait(other_type, current_cycle, read_cam, write_cam)
                          >= self._batch_timeout_cycles)

        # 卡死检测: 当前 mode 发不出, drain (in-flight 对向 txn) 也发不出.
        # 连续卡 STUCK_FALLBACK_CYCLES 以上才认为真卡死 (滤掉 tCCD/turnaround 短气泡).
        current_dispatchable = self._has_dispatchable(
            current_cycle, current_type, read_cam, write_cam)
        drain_dispatchable = self._has_dispatchable_inflight(
            current_cycle, read_cam, write_cam)
        if current_dispatchable or drain_dispatchable:
            self._current_stuck_cycles = 0
        else:
            self._current_stuck_cycles += 1
        current_stuck = (not current_dispatchable and not drain_dispatchable)

        # ---- 1. 已在准备期 → 走准备期逻辑 ----
        if self._preparation_state is not None:
            return self._continue_preparation(current_cycle, read_cam, write_cam)

        # ---- 2a. timeout + A2 + 对向有活 → 检查 ready / 进 prep ----
        # A2 豁免: 当前侧真卡死时 (current+drain 都发不出), 不再有"先发 1 条"可等,
        # 允许直接走 timeout 切换/准备期, 否则卡死态会自我锁死 (count=0 永远不满足 A2).
        if (other_starving
                and (self._current_batch_dispatch_count >= 1 or current_stuck)  # A2 防抖/豁免
                and other_has_work):
            # 2a-i. 对向已 ready (row scheduler 提前 ACT 好) → atomic 切, 不进 prep
            other_banks = self._snapshot_target_banks(other_type, read_cam, write_cam)
            if self._is_target_banks_ready(other_type, other_banks, target_cam=other_cam):
                self._current_batch_type = other_type
                self._current_batch_dispatch_count = 0
                self._atomic_switch_count += 1
                return self._try_issue_of_type(
                    current_cycle, other_type, read_cam, write_cam)
            # 2a-ii. 对向未 ready → 进 prep
            self._enter_preparation(other_type, current_cycle, read_cam, write_cam)
            return self._continue_preparation(current_cycle, read_cam, write_cam)

        # ---- 2b. empty-fallback: current CAM 全空, atomic 切 ----
        # 准备期救不了"current 模式真没活干"的场景, 这里直接跳切
        if not current_has_work and other_has_work:
            self._current_batch_type = other_type
            self._current_batch_dispatch_count = 0
            self._empty_fallback_count += 1
            current_type = other_type
        # ---- 2b'. stuck-fallback: current 真卡死 (current+drain 都发不出) 持续
        # STUCK_FALLBACK_CYCLES 以上, 且对向现在就能发 → atomic 切.
        # 对向只是"有活但不可派发"时, 交给 2a 的 timeout/准备期处理.
        elif (self._current_stuck_cycles >= STUCK_FALLBACK_CYCLES
                and self._has_dispatchable(current_cycle, other_type, read_cam, write_cam)):
            self._current_batch_type = other_type
            self._current_batch_dispatch_count = 0
            self._empty_fallback_count += 1
            current_type = other_type

        # ---- 2c. 正常发, 发不出则 drain in-flight 对向 txn ----
        return self._issue_current_else_drain(current_cycle, current_type,
                                              read_cam, write_cam)

    # ---- 准备期: 进入 / 检退出 / 继续 / 退出 / ready 判定 ----

    def _enter_preparation(self, target_type: RWType, current_cycle: int,
                           read_cam: List[BurstCommandGroup],
                           write_cam: List[BurstCommandGroup]) -> None:
        """进入准备期: snapshot 对向 CAM 涉及的 bank, 准备等 row scheduler ACT.

        snapshot 语义: 进入时 distinct bank_ids 集合, 之后整个准备期不变.
        理由: CAM 里的 entry 会随 R/W 派发被 remove, dynamic 算会让阈值抖动.

        调用方 (_try_issue_batch) 应在调用本方法前先确认 target NOT ready;
        本方法不做 ready 检查, 直接进入准备期.
        """
        target_cam = write_cam if target_type == RWType.WRITE else read_cam
        target_banks_snapshot = self._snapshot_target_banks(target_type, read_cam, write_cam)

        self._preparation_state = {
            'target': target_type,
            'target_banks_snapshot': target_banks_snapshot,
            'target_cam': target_cam,   # 留 snapshot 引用, _is_preparation_ready 用做 row-match
            'start_cycle': current_cycle,
            'dispatch_count': 0,   # 准备期内 current mode 已发的 R/W 条数 (软上限用)
            'act_count': 0,        # 准备期内发生在 target bank 上的 ACT 数 (由 record_row_event 累加)
            'pre_count': 0,        # 准备期内发生在 target bank 上的 PRE 数 (同上)
        }
        self._preparation_phase_count += 1

    def _snapshot_target_banks(self, target_type: RWType,
                               read_cam: List[BurstCommandGroup],
                               write_cam: List[BurstCommandGroup]) -> set:
        """Snapshot target CAM 里所有 cmd 涉及的 distinct bank_id 集合.

        仅算当前还有 cmd 待派发的 entry (next_dispatch_index < len(commands)),
        已被全派发的 entry 涉及的 bank 不算 (bank 已经被 autoprecharge, 与 target 无关).
        """
        target_cam = write_cam if target_type == RWType.WRITE else read_cam
        banks = set()
        for entry in target_cam:
            if entry.next_dispatch_index < len(entry.commands):
                banks.add(entry.bank_id)
        return banks

    def _cam_has_unprocessed(self, cam: List[BurstCommandGroup]) -> bool:
        """检查 cam 里是否还有未派发完的 cmd (任何 entry.next_dispatch_index < len(commands)).

        与 _has_dispatchable 的区别:
          - has_dispatchable: 现在就能派发 (bank state OK + 时序 OK)
          - has_unprocessed:  只要 CAM 里有活干就算 (不管 bank 现在是不是 ready)

        用于切模式决策. 关键场景: 在读模式下, 写 CAM 的 bank 永远不会被 ACT
        (row scheduler 按 mode 通道化, 只看 read_cam), 所以写命令"不可派发".
        但写 CAM 里有 32 个未处理命令, 必须切到 W 才能让 row scheduler 给写 bank ACT.
        此时 has_dispatchable=False 但 has_unprocessed=True, 仍应触发 empty-fallback.
        """
        return any(entry.next_dispatch_index < len(entry.commands) for entry in cam)

    @staticmethod
    def _bank_row_matches_target(bank: 'DRAMBank',
                                 target_cam: List['BurstCommandGroup']) -> bool:
        """Check bank.open_row 是否命中 target CAM 中某个 entry 的 row.

        这是 page-open 检查: ACTING bank 能立刻 dispatch target 的前提是 row 匹配.
        若 bank 还 ACTING 但 row 不匹配 (上一轮模式留下的 stale ACT), 不能直接用,
        需要 PRE+ACT 才能复用.
        """
        for entry in target_cam:
            if entry.next_dispatch_index >= len(entry.commands):
                continue
            cmd = entry.commands[entry.next_dispatch_index]
            if cmd.row_id == bank.open_row:
                return True
        return False

    def _is_target_banks_ready(self, target_type: RWType,
                               target_banks: set,
                               target_cam: Optional[List[BurstCommandGroup]] = None
                               ) -> bool:
        """根据 target_banks 判断 target 模式是否已 ready.

        阈值逻辑:
          - len(target_banks) <  preparation_min_banks: 全部 ready 才算
          - len(target_banks) >= preparation_min_banks: 至少 N 个 ready 即可

        "准备好" 的 bank 状态 (与 ColEligibilityChecker._bank_state_ok 对齐):
          - 对 R 目标: bank.state == ACTING
          - 对 W 目标: bank.state == ACTING, 或 ACT_WAIT + write_timing_satisfied

        target_cam 传进来时, 多一道 row-match 检查: ACTING bank 的 open_row 必须
        命中 target CAM 中某个 entry 的 row, 否则是 stale ACT (上一轮模式留下
        的, row 不匹配), 视作未 ready. 真正的 "ready" 发生在 row scheduler 在
        prep 阶段给对端 ACT 完之后, 用 row-match 判定.

        target_cam 为 None 时跳过 row-match 检查 (用于 atomic switch 路径,
        atomic 不做 PRE+ACT, 直接以 state 判定).
        """
        if not target_banks:
            return True
        prepared = 0
        for bank_id in target_banks:
            bank = self._banks[bank_id]
            if target_type == RWType.READ:
                if bank.state == BankState.ACTING:
                    if (target_cam is not None
                            and not self._bank_row_matches_target(bank, target_cam)):
                        continue   # stale ACT, 跳过不计
                    prepared += 1
            else:  # WRITE
                if bank.state == BankState.ACTING:
                    if (target_cam is not None
                            and not self._bank_row_matches_target(bank, target_cam)):
                        continue
                    prepared += 1
                elif (bank.state == BankState.ACT_WAIT
                      and bank.write_timing_satisfied):
                    prepared += 1
        if len(target_banks) < self._preparation_min_banks:
            return prepared == len(target_banks)
        return prepared >= self._preparation_min_banks

    def record_row_event(self, row_cmd: Optional[RowCommand]) -> None:
        """由 HBMCommandScheduler 在每次 row 调度后调用. 累计发生在 target bank 上的 ACT/PRE.

        只统计 target_banks_snapshot 里的 bank: 准备期的目标就是给这些 bank ACT 起来,
        统计其他 bank 没有意义, 反而会混进 current mode 的 row 操作.

        注: PRE 的语义"为目标准备"比较微妙 — PRE 关闭的是当前行, 不一定为 target 服务.
        但只要发生在 target bank 上, 就视作"为 target 腾出资源", 计入.
        """
        if self._preparation_state is None or row_cmd is None:
            return
        if row_cmd.bank_id not in self._preparation_state['target_banks_snapshot']:
            return
        if row_cmd.kind == RowCommandType.ACT:
            self._preparation_state['act_count'] += 1
        else:  # PRE
            self._preparation_state['pre_count'] += 1

    def _is_preparation_ready(self) -> bool:
        """判断目标模式是否"准备好" (用 row-match 严格检查).

        与 atomic switch 路径不同: prep 内 row scheduler 看到双 CAM, 会给
        target bank ACT 起来 (row 是匹配新 entry 的). 所以 prep 走完后,
        用 row-match 判定更准确: ACTING bank 的 row 必须命中 target CAM
        才算 ready (排除 stale ACT).
        """
        state = self._preparation_state
        if state is None:
            return False
        return self._is_target_banks_ready(state['target'],
                                           state['target_banks_snapshot'],
                                           state['target_cam'])

    def _check_preparation_exit(self, current_cycle: int,
                                read_cam: List[BurstCommandGroup],
                                write_cam: List[BurstCommandGroup]) -> Optional[str]:
        """检准备期退出条件. 优先级 (从优到劣):
          1. 'ready'           目标准备好, 正常退出
          2. 'max_dispatches'  准备期内 current mode 已发 M 条 (软上限, degraded)
          3. 'current_empty'   current 模式 CAM 物理空 (无任何未处理命令, degraded)
          4. 'prep_timeout'    准备期总时长超 preparation_max_cycles (兜底, degraded)
          None                 都不满足, 继续准备

        Returns: 退出 reason 字符串 / None
        """
        if self._preparation_state is None:
            return None

        # 1. 正常退出: 目标 ready
        if self._is_preparation_ready():
            return 'ready'

        # 2. 软上限: 准备期 dispatch 数触顶 (degraded)
        if (self._preparation_state['dispatch_count']
                >= self._preparation_max_dispatches):
            return 'max_dispatches'

        # 3. 硬空: current 模式 CAM 已无任何未处理命令 (degraded).
        # 语义: CAM 物理空才退, 不是"本 cycle 无可派发" — 后者会把 bank 周转
        # (ACT_WAIT/PRE_WAIT/tCCD) 的正常空窗误判为空, 导致 prep 中位存活 0 cycle,
        # 永远等不到 target ready. CAM 不空就继续等 (drain/空转), 由 prep_timeout 兜底.
        current_cam = (read_cam if self._current_batch_type == RWType.READ
                       else write_cam)
        if not self._cam_has_unprocessed(current_cam):
            return 'current_empty'

        # 4. 兜底: 准备期总时长超限 (degraded).
        # 防新语义下 "CAM 一直不空 + target 永远备不齐 + current 一直发不出"
        # 把准备期锁死; 到时强切, 让步给对向.
        if (current_cycle - self._preparation_state['start_cycle']
                >= self._preparation_max_cycles):
            return 'prep_timeout'

        return None

    def _continue_preparation(self, current_cycle: int,
                              read_cam: List[BurstCommandGroup],
                              write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """准备期每 cycle 的逻辑.

        顺序: 检 exit → (退出则翻 mode + 发 target) → (没退则发 current R/W + dispatch_count++)

        把 exit 检查放在发命令之前, 避免同 cycle 双发 (current + target 各一条).
        """
        # 计入"在准备期"的一个 cycle (用于 summary 统计)
        self._preparation_total_cycles += 1

        # 1. 检退出条件
        exit_reason = self._check_preparation_exit(current_cycle, read_cam, write_cam)
        if exit_reason is not None:
            return self._exit_and_dispatch(current_cycle, exit_reason, read_cam, write_cam)

        # 2. 没退出, 继续发 current mode R/W, 发不出则 drain in-flight 对向 txn
        col_cmd = self._issue_current_else_drain(
            current_cycle, self._current_batch_type, read_cam, write_cam)
        if (col_cmd is not None
                and (col_cmd.is_write == (self._current_batch_type == RWType.WRITE))):
            self._preparation_state['dispatch_count'] += 1
        return col_cmd

    def _exit_and_dispatch(self, current_cycle: int, exit_reason: str,
                           read_cam: List[BurstCommandGroup],
                           write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """退出准备期: 翻 mode, 清 prep_state, 累计 exit 统计 + 写入 per-prep history, 发 target R/W.

        被 _continue_preparation 调用, 此时 _preparation_state 一定非空.
        """
        state = self._preparation_state
        target = state['target']

        # ---- 写 per-prep history (在清状态之前) ----
        self._preparation_history.append({
            'start_cycle': state['start_cycle'],
            'end_cycle': current_cycle,
            'duration': current_cycle - state['start_cycle'],
            'target': target.value,                 # 'READ' / 'WRITE'
            'snapshot_banks': len(state['target_banks_snapshot']),
            'dispatch_count': state['dispatch_count'],
            'act_count': state['act_count'],
            'pre_count': state['pre_count'],
            'exit_reason': exit_reason,
        })

        # 翻 mode + 清状态
        self._current_batch_type = target
        self._current_batch_dispatch_count = 0
        self._preparation_exit_counts[exit_reason] = (
            self._preparation_exit_counts.get(exit_reason, 0) + 1)
        self._preparation_state = None

        # 发 target R/W (本 cycle)
        return self._try_issue_of_type(current_cycle, target, read_cam, write_cam)

    # ---- 公开 API: 准备期统计 (供 HBMCommandScheduler 写 summary) ----

    def get_preparation_stats(self) -> dict:
        """返回准备期聚合统计快照 (dict, 调用方按需格式化)."""
        return {
            'phase_count': self._preparation_phase_count,
            'total_cycles': self._preparation_total_cycles,
            'exit_counts': dict(self._preparation_exit_counts),
            'atomic_switch_count': self._atomic_switch_count,
            'empty_fallback_count': self._empty_fallback_count,
            'drain_dispatch_count': self._drain_dispatch_count,
            'total_switch_count': (
                self._preparation_phase_count
                + self._atomic_switch_count
                + self._empty_fallback_count
            ),
        }

    def get_preparation_history(self) -> List[dict]:
        """返回每次准备期的明细列表 (按完成顺序, 已完成的 phase).

        每条 dict: start_cycle, end_cycle, duration, target, snapshot_banks,
                   dispatch_count, act_count, pre_count, exit_reason.
        """
        return list(self._preparation_history)   # 返回拷贝, 避免外部修改内部状态

    def get_sid_aware_stats(self) -> dict:
        """返回 SID-aware 选优统计 (仅在 sid_aware=True 时累计, 否则全 0).

        same_sid_hits   : eligible 池有同 SID, 选了同 SID 的次数 (期望大量)
        cross_sid_fallback: 同 SID 池空, 退到跨 SID 池的次数 (代表单 SID 真没活)
        total_decisions  : same + cross 的总数 (= sid_aware 参与的派发决策数)
        """
        same = self._sid_aware_same_hits
        cross = self._sid_aware_fallback
        return {
            'enabled': self._sid_aware,
            'same_sid_hits': same,
            'cross_sid_fallback': cross,
            'total_decisions': same + cross,
            'same_sid_ratio': same / (same + cross) if (same + cross) else 0.0,
        }

    def get_rw_4state_stats(self) -> dict:
        """v16.3+: 4 态 R/W 调度状态机统计.

        字段:
          enabled                    : rw_4state_mode 是否开启
          current_state              : 仿真结束时的 state
          direct_switch_count        : RD→WR / WR→RD (CAM 空触发的直切) 总数
          enter_transition_count     : 进入 RD_WR / WR_RD 的总次数
          exit_transition_count      : 从 RD_WR / WR_RD 退出的总次数
          exit_via_target_act_count  : 退出过渡态时, 触发原因是
                                       "对向已开 ≥ preparation_min_banks 个 ACT" 的次数
          cycles_in_state            : 各 state 驻留的 cycle 数
        """
        return {
            'enabled': self._rw_4state_mode,
            'current_state': self._rw_state.name,
            'direct_switch_count': self._rw_4state_direct_switch,
            'enter_transition_count': self._rw_4state_enter_transition,
            'exit_transition_count': self._rw_4state_exit_transition,
            'exit_via_target_act_count': self._rw_4state_exit_via_target_act,
            'cycles_in_state': dict(self._rw_4state_cycles_in_state),
        }

    def get_auto_precharge_stats(self) -> dict:
        """返回 WRA/RDA 自动预充电与同 page 串接统计。"""
        page_hit_chain_count = (self._write_page_hit_chain_count
                                + self._read_page_hit_chain_count)
        return {
            'enabled': self._write_auto_precharge or self._read_auto_precharge,
            'wra_enabled': self._write_auto_precharge,
            'rda_enabled': self._read_auto_precharge,
            'wra_count': self._wra_count,
            'rda_count': self._rda_count,
            'normal_write_count': self._normal_write_count,
            'normal_read_count': self._normal_read_count,
            'wra_saved_pre_count': self._wra_count,
            'rda_saved_pre_count': self._rda_count,
            'saved_pre_count': self._wra_count + self._rda_count + page_hit_chain_count,
            'saved_act_count': page_hit_chain_count,
            'page_hit_chain_count': page_hit_chain_count,
            'write_page_hit_chain_count': self._write_page_hit_chain_count,
            'read_page_hit_chain_count': self._read_page_hit_chain_count,
        }

    def get_row_candidate_cams(self,
                               read_cam: List[BurstCommandGroup],
                               write_cam: List[BurstCommandGroup]
                               ) -> List[BurstCommandGroup]:
        """返回当前 row_scheduler 可见的 CAM 列表 (按 mode 通道化).

        规则 (R/W 物理共享 bank 但调度分通道, 贴近真实 HBM 控制器):
          - Alternating 模式:                  → [read_cam, write_cam] (两通道都看, 准备交替)
          - Batch NORMAL + READ:               → [read_cam]            (只看读队列)
          - Batch NORMAL + WRITE:              → [write_cam]           (只看写队列)
          - Batch PREPARING:                   → [read_cam, write_cam] (目标 bank 也需 ACT)
          - 4 态机 RD:                         → [read_cam]            (ACT only RD)
          - 4 态机 WR:                         → [write_cam]           (ACT only WR)
          - 4 态机 RD_WR (过渡: drain RD, 开 WR): → [write_cam]           (不开新 RD, 只开 WR)
          - 4 态机 WR_RD (过渡: drain WR, 开 RD): → [read_cam]            (不开新 WR, 只开 RD)

        意义:
          - 正常 batch / 4 态机 RD/WR 模式下, row scheduler 看不到对向的 CAM,
            自然不会提前 ACT 对向 bank
          - 准备期 / 过渡态开窗口, 让 row scheduler 给 target bank ACT
          - 4 态机过渡态关键: 过渡时不开新的 source 侧 ACT, 否则会重新打开
            source 侧 bank, 干扰 drain 语义
        """
        # 4 态机路径
        if self._rw_4state_mode:
            state = self._rw_state
            if state == RWState.RD:
                return list(read_cam)
            if state == RWState.WR:
                return list(write_cam)
            if state == RWState.RD_WR:
                # 过渡 RD→WR: 只开 WR 的 bank (不开新 RD, 让现有 RD banks drain)
                return list(write_cam)
            if state == RWState.WR_RD:
                # 过渡 WR→RD: 只开 RD 的 bank (不开新 WR, 让现有 WR banks drain)
                return list(read_cam)
        # 兼容: Alternating 模式: 必须同时看两个 CAM
        if not self._batch_scheduling:
            return list(read_cam) + list(write_cam)
        # Batch 模式 + 准备期: 目标 bank 也需要 ACT/PRE
        if self._preparation_state is not None:
            return list(read_cam) + list(write_cam)
        # Batch 模式 + 正常: 只给当前 mode 的 CAM
        if self._current_batch_type == RWType.READ:
            return list(read_cam)
        return list(write_cam)

    # ---- Alternating 策略 ----

    def _try_issue_alternating(self, current_cycle: int,
                               read_cam: List[BurstCommandGroup],
                               write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """优先尝试相反类型, 不行再 fallback. 配合 tRTW 建模后, 切换方向被 block
        期间只能 fallback, 自然形成长 R/W 段, 效果与 Batch 接近."""
        preferred_type = _opposite_type(self._current_batch_type)

        col_cmd = self._try_issue_of_type(current_cycle, preferred_type, read_cam, write_cam)
        if col_cmd is not None:
            self._current_batch_type = preferred_type
            return col_cmd

        return self._try_issue_of_type(current_cycle, self._current_batch_type,
                                       read_cam, write_cam)

    # ---- 派发 ----

    def _try_issue_of_type(self, current_cycle: int,
                           r_w_type: RWType,
                           read_cam: List[BurstCommandGroup],
                           write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """指定 R/W 类型, RR 选一个派发; 命中后完成全部副作用"""
        is_write = (r_w_type == RWType.WRITE)
        target_cam = write_cam if is_write else read_cam
        rr_pointer = self._rr_pointer_write if is_write else self._rr_pointer_read

        dispatchable = []
        for burst_entry in target_cam:
            if burst_entry.next_dispatch_index >= len(burst_entry.commands):
                continue
            col_cmd = burst_entry.commands[burst_entry.next_dispatch_index]
            if self._eligibility.check(col_cmd, current_cycle, self._bus):
                dispatchable.append((burst_entry, col_cmd))

        if not dispatchable:
            return None

        dispatchable.sort(key=lambda x: x[1].bank_id)

        # ---- SID-aware 选优 ----
        # 软优化: 同 SID (跟 bus.last_dispatch_sid 相同) 优先于跨 SID.
        # 跨 SID 仍受 _eligibility.check 内的 tCCDR 硬卡 (>= 2 DFI).
        # 同 SID 池空时退到跨 SID 池 (避免饿死).
        if self._sid_aware and self._bus.last_dispatch_sid >= 0:
            last_sid = self._bus.last_dispatch_sid
            same_sid = [e for e in dispatchable if e[1].sid_id == last_sid]
            cross_sid = [e for e in dispatchable if e[1].sid_id != last_sid]
            # 统计
            self._sid_aware_same_hits += len(same_sid) > 0
            self._sid_aware_fallback += len(same_sid) == 0 and len(cross_sid) > 0
            pool = same_sid if same_sid else cross_sid
        else:
            pool = dispatchable

        selected = next(
            (e for e in pool if e[1].bank_id >= rr_pointer),
            pool[0]
        )
        new_rr = (selected[1].bank_id + 1) % self._num_banks
        if is_write:
            self._rr_pointer_write = new_rr
        else:
            self._rr_pointer_read = new_rr

        burst_entry, col_cmd = selected
        self._complete_dispatch(burst_entry, col_cmd, current_cycle, target_cam)
        return col_cmd

    @staticmethod
    def _find_next_same_page_entry(
            current_entry: BurstCommandGroup,
            target_cam: List[BurstCommandGroup]) -> Optional[BurstCommandGroup]:
        """在当前 R/W CAM 中选择下一个已排队的同 page entry。

        只使用已经进入 CAM 的请求，不预测尚未准入的未来流量。选择最早入 CAM、
        transaction_id 最小的 entry，保证结果稳定且不会让后来请求插队。
        """
        candidates = [
            entry for entry in target_cam
            if entry is not current_entry
            and entry.page_key == current_entry.page_key
            and entry.next_dispatch_index < len(entry.commands)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda e: (e.entry_cycle, e.transaction_id, e.segment_id))

    def _complete_dispatch(self, burst_entry: BurstCommandGroup,
                           col_cmd: ColumnCommand, current_cycle: int,
                           target_cam: List[BurstCommandGroup]) -> None:
        """一笔派发的全部副作用: bank 状态 + autoprecharge 触发 + bus tracker +
        batch 计数 + CAM 移除 (_try_issue_of_type 与 drain 共用)"""
        bank = self._banks[col_cmd.bank_id]
        bank.cols_dispatched += 1
        bank.last_col_at = current_cycle
        bank.last_col_rw_type = RWType.WRITE if col_cmd.is_write else RWType.READ

        segment_complete = bank.cols_dispatched >= col_cmd.segment_cmd_count

        # “最后一个 page-hit 使用 WRA/RDA”策略：
        #   1. 当前 segment 完成后，先在同类型 CAM 中寻找已排队的同 page entry；
        #   2. 若存在，保持 row open，直接把 bank 交给下一个 dispatch（不 PRE、不 ACT）；
        #   3. 若不存在，最后一条 WRITE/READ 分别以 WRA/RDA 发送，内部完成 precharge。
        next_page_hit = None
        auto_precharge_enabled = (self._write_auto_precharge if col_cmd.is_write
                                  else self._read_auto_precharge)
        col_to_pre_delay = (self._timing.write_ap_cycles if col_cmd.is_write
                            else self._timing.t_rtp_cycles)
        refresh_guard = (self._wra_refresh_guard_cycles if col_cmd.is_write
                         else self._rda_refresh_guard_cycles)
        only_after_page_hit = (self._wra_only_after_page_hit if col_cmd.is_write
                               else self._rda_only_after_page_hit)

        # 若 refresh 已 pending，或预计当前命令采用 WRA/RDA 后 bank 变为 IDLE 之前
        # refresh deadline 就会到达，则不再串接下一笔 page-hit，提前收尾。
        projected_auto_pre_idle_cycle = max(
            current_cycle + col_to_pre_delay,
            bank.last_act_at + self._timing.t_ras_cycles,
        ) + self._timing.t_rp_cycles
        refresh_is_pending = bool(
            (self._refresh_pending is not None
             and self._refresh_pending[col_cmd.bank_id])
            or (self._next_refresh_cycle is not None
                and projected_auto_pre_idle_cycle + refresh_guard
                    >= self._next_refresh_cycle[col_cmd.bank_id])
        )
        if auto_precharge_enabled and segment_complete and not refresh_is_pending:
            next_page_hit = self._find_next_same_page_entry(burst_entry, target_cam)

        use_auto_precharge = bool(
            auto_precharge_enabled
            and segment_complete
            and next_page_hit is None
            and (not only_after_page_hit or bank.page_hit_chain_active)
        )
        col_cmd.auto_precharge = use_auto_precharge

        if col_cmd.is_write:
            if use_auto_precharge:
                self._wra_count += 1
                bank.start_write_auto_precharge(current_cycle, self._timing)
            else:
                self._normal_write_count += 1
        else:
            if use_auto_precharge:
                self._rda_count += 1
                bank.start_read_auto_precharge(current_cycle, self._timing)
            else:
                self._normal_read_count += 1

        if next_page_hit is not None:
            next_cmd = next_page_hit.commands[next_page_hit.next_dispatch_index]
            # 同一 bank 同一 row 已经打开，直接切换服务对象。
            assert next_cmd.page_key == col_cmd.page_key
            assert next_cmd.segment_col_index == 0
            bank.serving_dispatch_id = next_cmd.dispatch_id
            bank.cols_dispatched = 0
            bank.precharge_pending = False
            bank.page_hit_chain_active = True
            if col_cmd.is_write:
                self._write_page_hit_chain_count += 1
            else:
                self._read_page_hit_chain_count += 1
        elif segment_complete and not use_auto_precharge:
            # 自动预充电关闭时继续使用显式 PRE
            bank.precharge_pending = True

        self._bus.last_dispatch_cycle = current_cycle
        self._bus.last_dispatch_cycle_per_bg[col_cmd.bank_group_id] = current_cycle
        self._bus.last_dispatch_cycle_per_sid[col_cmd.sid_id] = current_cycle
        self._bus.last_rw_type = bank.last_col_rw_type
        self._bus.last_bank_group = col_cmd.bank_group_id
        self._bus.last_dispatch_sid = col_cmd.sid_id

        self._current_batch_dispatch_count += 1

        burst_entry.next_dispatch_index += 1
        if burst_entry.next_dispatch_index >= len(burst_entry.commands):
            target_cam.remove(burst_entry)

    # ---- drain: in-flight 对向 txn 续发 ----

    def _issue_current_else_drain(self, current_cycle: int,
                                  current_type: RWType,
                                  read_cam: List[BurstCommandGroup],
                                  write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """先发当前 mode; 发不出则 drain 两个 CAM 里的 in-flight txn (兜底防 stranding)"""
        col_cmd = self._try_issue_of_type(current_cycle, current_type, read_cam, write_cam)
        if col_cmd is not None:
            return col_cmd
        return self._try_drain_inflight(current_cycle, read_cam, write_cam)

    def _try_drain_inflight(self, current_cycle: int,
                            read_cam: List[BurstCommandGroup],
                            write_cam: List[BurstCommandGroup]) -> Optional[ColumnCommand]:
        """扫描两个 CAM, 派发任何 bank 已打开且正在服务其 txn 的 cmd (RR 独立指针).

        背景: mode 翻转可能留下"对向 mode 的半截 txn" (bank ACTING, 只发了部分 col).
        这类 bank 必须能 drain 到完成 → precharge_pending → PRE, 否则永久 stranding.
        对向 CAM 里 bank 未打开的 entry 天然被 eligibility 的 bank 状态检查排除,
        不会变相提前启动对向 txn — drain 只续发, 不新开.
        """
        dispatchable = []
        for cam in (read_cam, write_cam):
            for entry in cam:
                if entry.next_dispatch_index >= len(entry.commands):
                    continue
                col_cmd = entry.commands[entry.next_dispatch_index]
                if self._eligibility.check(col_cmd, current_cycle, self._bus):
                    dispatchable.append((entry, col_cmd))
        if not dispatchable:
            return None

        dispatchable.sort(key=lambda x: x[1].bank_id)
        selected = next(
            (e for e in dispatchable if e[1].bank_id >= self._rr_pointer_drain),
            dispatchable[0]
        )
        self._rr_pointer_drain = (selected[1].bank_id + 1) % self._num_banks

        burst_entry, col_cmd = selected
        cam = write_cam if col_cmd.is_write else read_cam
        self._complete_dispatch(burst_entry, col_cmd, current_cycle, cam)
        self._drain_dispatch_count += 1
        return col_cmd

    def _has_dispatchable_inflight(self, current_cycle: int,
                                   read_cam: List[BurstCommandGroup],
                                   write_cam: List[BurstCommandGroup]) -> bool:
        """两个 CAM 里是否有 in-flight (bank 已打开服务其 txn) 可派发的 cmd"""
        for cam in (read_cam, write_cam):
            for entry in cam:
                if entry.next_dispatch_index >= len(entry.commands):
                    continue
                col_cmd = entry.commands[entry.next_dispatch_index]
                if self._eligibility.check(col_cmd, current_cycle, self._bus):
                    return True
        return False

    # ---- helpers ----

    def _has_dispatchable(self, current_cycle: int, r_w_type: RWType,
                          read_cam: List[BurstCommandGroup],
                          write_cam: List[BurstCommandGroup]) -> bool:
        """指定类型是否有可立即派发的 cmd (与 _try_issue_of_type 同一套检查, 无副作用)"""
        target_cam = write_cam if r_w_type == RWType.WRITE else read_cam
        for burst_entry in target_cam:
            if burst_entry.next_dispatch_index >= len(burst_entry.commands):
                continue
            col_cmd = burst_entry.commands[burst_entry.next_dispatch_index]
            if self._eligibility.check(col_cmd, current_cycle, self._bus):
                return True
        return False

    @staticmethod
    def _oldest_entry_wait(r_w_type: RWType, current_cycle: int,
                           read_cam: List[BurstCommandGroup],
                           write_cam: List[BurstCommandGroup]) -> int:
        """指定类型 CAM 中最早 entry 已等待的 cycles (CAM 空返回 0)"""
        target_cam = write_cam if r_w_type == RWType.WRITE else read_cam
        if not target_cam:
            return 0
        return current_cycle - min(e.entry_cycle for e in target_cam)


# ============================================================
#  Simulation reporter (log + summary)
# ============================================================

class SimulationReporter:
    """每 cycle 状态行 / summary 的格式化与双写 (console + 可选 log file)"""

    _W_CYCLE, _W_REMAIN, _W_CAM, _W_ROW, _W_COL = 7, 8, 38, 34, 44
    HEADER = (f"  {'Cyc':>{_W_CYCLE}} | {'Remain':>{_W_REMAIN}} | "
              f"{'CAM_Entry':>{_W_CAM}} | {'Row_Cmd':>{_W_ROW}} | {'Col_Cmd':>{_W_COL}}")
    SEPARATOR = (f"  {'─'*_W_CYCLE}─┼─{'─'*_W_REMAIN}─┼─{'─'*_W_CAM}─┼─"
                 f"{'─'*_W_ROW}─┼─{'─'*_W_COL}")

    def __init__(self, log_fp: Optional[TextIO] = None, verbose_cycles: int = 200,
                 banks_per_bank_group: int = 4, groups_per_sid: int = 4):
        """初始化对象状态及其依赖组件。"""
        self._log_fp = log_fp
        self._verbose_boundary = verbose_cycles
        self._bpgrp = banks_per_bank_group
        self._gpsid = groups_per_sid

    def _addr(self, bank_id: int) -> str:
        """bank_id -> 'SID[0] BG[1] BA[3]' 三段分组格式 (spec Table 5 物理布局)

        字段间用空格, 段内用方括号 — 人眼可一眼分段, 不用心算
        """
        sid, bg, ba = _bank_id_to_sid_bg_ba(bank_id, self._bpgrp, self._gpsid)
        return f"SID[{sid}] BG[{bg}] BA[{ba}]"

    def _emit(self, line: str) -> None:
        """将格式化文本写入目标输出流。"""
        print(line)
        if self._log_fp:
            self._log_fp.write(line + "\n")

    def print_header(self, cfg: SimulationConfig, num_burst_entries: int) -> None:
        """输出仿真日志表头。"""
        self._emit(f"\n  仿真开始: {cfg.total_cmds}条Col命令 "
                   f"({num_burst_entries}个burst entries), "
                   f"addr_mode={cfg.addr_mode}, read_ratio={cfg.read_ratio}")
        self._emit(self.HEADER)
        self._emit(self.SEPARATOR)

    def write_cycle_line(self, current_cycle: int, line: str,
                         should_print: bool) -> None:
        """正常打印本行; 越过 verbose 边界时只在边界 cycle 打一次省略号"""
        if should_print:
            self._emit(line)
        elif current_cycle == self._verbose_boundary:
            self._emit("  ... (后续cycle省略) ...")

    def format_cycle_line(self,
                          current_cycle: int,
                          cam_remaining: Tuple[int, int],
                          entered_entry: Optional[BurstCommandGroup],
                          row_cmd: Optional[RowCommand],
                          col_cmd: Optional[ColumnCommand]) -> str:
        """把一个 cycle 的状态拼成对齐的一行 (无操作的列用 "--")"""
        read_remain, write_remain = cam_remaining
        remain_s = f"R{read_remain}/W{write_remain}"

        if entered_entry:
            col_start = entered_entry.starting_col_index
            col_end = col_start + len(entered_entry.commands) - 1
            rw = "W" if entered_entry.commands[0].is_write else "R"
            cam_s = (f"{rw} {self._addr(entered_entry.bank_id)} col[{col_start}]"
                     if col_start == col_end
                     else f"{rw} {self._addr(entered_entry.bank_id)} col[{col_start}-{col_end}]")
        else:
            cam_s = "--"

        row_s = ("--"
                 if not row_cmd
                 else f"{row_cmd.kind.value} {self._addr(row_cmd.bank_id)} row--"
                 if row_cmd.kind == RowCommandType.REFPB
                 else f"{row_cmd.kind.value} {self._addr(row_cmd.bank_id)} row{row_cmd.row_id}")

        col_s = (f"{self._addr(col_cmd.bank_id)} txn={col_cmd.transaction_id} "
                 f"col={col_cmd.col_index} "
                 f"{('WRA' if col_cmd.is_write else 'RDA') if col_cmd.auto_precharge else ('W' if col_cmd.is_write else 'R')}"
                 if col_cmd else "--")

        return (f"  {current_cycle:>{self._W_CYCLE}} | {remain_s:>{self._W_REMAIN}} | "
                f"{cam_s:>{self._W_CAM}} | {row_s:>{self._W_ROW}} | {col_s:>{self._W_COL}}")

    def print_lines(self, lines: List[str]) -> None:
        """按顺序输出多行日志文本。"""
        for line in lines:
            self._emit(line)


# ============================================================
#  HBM Command Scheduler (orchestrator)
# ============================================================

class HBMCommandScheduler:
    """HBM3 内存控制器命令调度器 (DFI 视角) 编排器.

    每个 cycle 的执行顺序 (`_run_one_cycle`):
      1. `_try_admit_burst_entry`  — 按节流把下一个 burst command group 入对应 R/W CAM
      2. bank.tick                 — 推进所有 bank 状态机 (结果当 cycle 对调度可见)
      3. ref_priority 策略 (v16.3+):
         - mandatory REFpb (prepare_due / hard_deadline / debt ≥ max_postpone):
             refresh 抢占 row bus; 仅当 timing 闸不允许时退让给 row.
         - non-mandatory REFpb:
             ACT/PRE 优先; row_scheduler 没发时 refresh 兜底 (via_fallback=True).
         优先级链: mandatory REFpb > ACT/PRE > non-mandatory REFpb.
      4. ColScheduler.try_issue    — Batch 或 Alternating
      5. SimulationReporter        — 写一行日志

    通道 tracker (last act/col cycle 等) 归各调度器自持有, 编排器只保留
    CAM、burst 准入节流和统计变量.

    Note: 公开 API 保持向后兼容, 构造参数与 v2 一致, simulate() 仍可用.
    """

    def __init__(self,
                 # ---- Clock model ----
                 data_rate_gbps: float = 9.6,
                 # ---- DRAM 结构 ----
                 num_banks: int = 48,
                 banks_per_bank_group: int = 4,
                 # ---- Bank timing (ns / HBM CK 输入) ----
                 t_rcdrd_ns: float = 18.0,
                 t_rcdwr_ns: float = 12.0,
                 t_rp_ns:    float = 18.0,
                 t_rc_ns:    float = 52.0,
                 t_ras_ns:   float = 34.0,
                 t_rtp_hbmck: int   = 5,
                 t_wr_ns:    float   = 21.0,
                 wl_hbmck:   int     = 16,
                 # ---- 通道 timing (cycles, 除 t_faw 用 HBM CK) ----
                 t_ccd_s: int = 1,
                 t_ccd_l: int = 3,
                 t_ccdr_cycles: int = 2,        # HBM3 inter-SID tCCDR（READ only）；输入单位为 DFI/model cycle
                 t_rrd_s: int = 3,
                 t_rrd_l: int = 3,
                 t_faw_hbmck: int = 24,
                 # ---- R/W Turnaround ----
                 t_rtw_ns:  float = 23.0,
                 t_wtrl_hbmck: int = 4,
                 t_wtrs_hbmck: int = 2,
                 # ---- CAM 深度 ----
                 read_cam_depth:  int = 32,
                 write_cam_depth: int = 32,
                 # ---- 激励 ----
                 num_transactions: int = 10000,
                 cmds_per_transaction: int = 4,
                 workload_size_bytes: Optional[int] = None,
                 # ---- v7: 地址生成 (替代旧 case=1/2) ----
                 addr_mode: str = "linear",      #: "linear" / "random"
                 addr_map: Optional[dict] = None,  #: None selects configuration-compliant map
                 configuration: Optional[str] = None, #: auto-derived from num_banks when None
                 density_code: Optional[int] = None, #: 8H default 0001; 12H default 0010
                 seed: int   = 42,
                 # ---- Workload ----
                 read_ratio:      float = 1.0,
                 # ---- Batch 调度 ----
                 batch_timeout_cycles: int   = 800,
                 #: 准备期目标 bank ready 阈值 (<N 则全 ready)
                 preparation_min_banks: int  = 8,
                 #: 准备期内 current mode 最多发几条 (软上限)
                 preparation_max_dispatches: int = 16,
                 #: 准备期总时长上限 (硬上限, 兜底防锁死)
                 preparation_max_cycles: int = 64,
                 # 接受字符串, 内部转 RWType
                 initial_batch_type: str    = "READ",
                 batch_scheduling: bool      = True,
                 # 4 态 R/W 调度状态机
                 # True = RD/WR/RD_WR/WR_RD 四态, 初始 RD, 切态按 CAM 空 + batch_timeout_cycles 倒计时
                 # False = 原 batch (preparation phase) 或 alternating 模式
                 rw_4state_mode: bool        = True,
                 # ---- SID-aware 优化 (col 派发时优先同 SID, 减少 tCCDR 等待) ----
                 sid_aware: bool            = False,    #: 软优化开关 (默认 off, 保持向后兼容)
                 write_auto_precharge: bool = True,     #: 最后一个 page-hit WRITE 使用 WRA
                 read_auto_precharge: bool = True,      #: 最后一个 page-hit READ 使用 RDA
                 #: WRA refresh deadline guard（可配置）
                 wra_refresh_guard_cycles: int = 64,
                 #: RDA refresh deadline guard（可配置）
                 rda_refresh_guard_cycles: int = 256,
                 #: 同类型 CAM 无 page-hit 时直接使用 WRA
                 wra_only_after_page_hit: bool = False,
                 #: 同类型 CAM 无 page-hit 时直接使用 RDA
                 rda_only_after_page_hit: bool = False,
                 # ---- Refresh (HBM3 per-bank, REFpb) ----
                 # t_refi_per_bank_cycles = 每个 bank 相邻两次 refresh 的间隔 (per-bank interval)
                 #  ⚠️ 跟 spec 的 tREFIpb (= tREFI/N = channel-level 平均 rate) **不是一个东西**:
                 #     - spec tREFIpb = 122ns (8-High N=32), 是 channel 每 122ns 发一个 REFpb 的平均 rate
                 #     - 每个具体 bank 实际被刷新的间隔 = tREFI = 3.9μs (N 个 bank 在 1 个 tREFI 窗口内全刷完)
                 #   所以本参数物理意义 = per-bank interval ≈ tREFI (设备级), 8-High 默认 4680 cycles.
                 # 历史值备注: 早期默认 2340 (= 1.95μs = tREFI/2, 协议里没这个数, 应是笔误);
                 #            中间改成 307 (= rolling 256ns) 后 case 1 perf 跌到 0.275 (过严).
                 #: per-bank refresh 间隔 cycles (~3.9 μs @ 1.2 GHz DFI, = tREFI per 8-High)
                 t_refi_per_bank_cycles: int = 4680,
                 #: per-bank refresh 命令耗时 (~200 ns, bank 阻塞时间)
                 t_rfc_pb_ns: float = 200.0,
                 #: 触发 mandatory 的 debt 阈值 (REFpb 个数, 默认 8)
                 max_postpone_credits: int = 8,
                 #: 协议 "refresh postpone all bank" 上限轮数 (9×tREFI); fail-fast debt 上限 = 该值 × num_banks
                 max_postpone_refab_rounds: int = 9,
                 #: mandatory 进入后至少刷几个 REFpb 才解除 (迟滞, 避免 debt 附近 on/off 抖动)
                 postpone_low_thr: int = 2,
                 # ---- V15 新增参数 ----
                 t_rl_ns: float = DEFAULT_T_RL_NS,
                 link_node_count: int = DEFAULT_LINK_NODE_COUNT,
                 link_list_count: int = DEFAULT_LINK_LIST_COUNT,
                 # ---- V15.1 新增参数 ----
                 #   "sequential": txn_id 顺序 0..N-1 (默认, 保持向后兼容)
                 #   "random"    : 每个 workload 独立 randint(0, N-1), 允许重复/空缺
                 txn_id_assignment: str = "sequential",
                 # V15 link list 专用 log 句柄. 与主 log 分离, 写到独立文件.
                 # 默认 None 不写 (主入口 main() 会自动打开 dram_sim_link_log.txt).
                 link_log_fp: Optional[TextIO] = None,
                 # ---- v17+ 新增参数 ----
                 # ACT 调度时, 优先选同 SID 不同 BG 的 bank (BG 交织)
                 # 提升 BG 级并行, 减少 tRRDL 集中. False = 走原 RR.
                 bg_interleave_priority: bool = True,
                 # ---- v18+ 新增参数 ----
                 # ACT 调度时, 优先选 ACT 等待最久的 bank (age 优先级)
                 # 防止调度偏向, 保证公平. False = 退回 v17 (仅 BG 交织 + RR).
                 # 优先级链: age (desc) > BG 交织 (tiebreaker) > RR.
                 age_priority: bool = True):
        """构造调度器: 参数校验 → clock/timing → workload/banks → schedulers.

        Raises:
            ValueError: read_ratio 越界 / cam_depth < 1 / initial_batch_type 非法 /
                        timing 参数非法。
        """
        if workload_size_bytes is not None:
            if workload_size_bytes <= 0 or workload_size_bytes % COMMAND_SIZE_BYTES != 0:
                raise ValueError(
                    f"workload_size_bytes 必须是 {COMMAND_SIZE_BYTES}B 的正整数倍, "
                    f"当前 {workload_size_bytes}")
            cmds_per_transaction = workload_size_bytes // COMMAND_SIZE_BYTES
        else:
            workload_size_bytes = cmds_per_transaction * COMMAND_SIZE_BYTES

        if cmds_per_transaction <= 0:
            raise ValueError("cmds_per_transaction 必须 > 0")
        if wra_refresh_guard_cycles < 0:
            raise ValueError("wra_refresh_guard_cycles 必须 >= 0")
        if rda_refresh_guard_cycles < 0:
            raise ValueError("rda_refresh_guard_cycles 必须 >= 0")
        if link_node_count <= 0:
            raise ValueError("link_node_count 必须 > 0")
        if link_list_count <= 0 or link_list_count > link_node_count:
            raise ValueError("link_list_count 必须在 (0, link_node_count] 范围")
        if txn_id_assignment not in ("sequential", "random"):
            raise ValueError(
                f"txn_id_assignment 必须是 'sequential' 或 'random', 当前 '{txn_id_assignment}'")
        self._txn_id_assignment = txn_id_assignment

        num_bank_groups = num_banks // banks_per_bank_group
        # Derive and validate configuration/density/remap before creating config/workload.
        resolved_configuration, resolved_density_code, geometry = _normalize_configuration(
            num_banks, configuration, density_code)
        resolved_addr_map = (dict(addr_map) if addr_map is not None
                             else _default_addr_map_for(geometry["sid_remap_type"]))
        _validate_addr_map(resolved_addr_map, geometry["sid_remap_type"], geometry["effective_bits"])
        # HBM3 SID 数 (per JESD238B.01 Table 5 + NOTE 7): 16→1, 32→2, 48→3, 64→4
        num_sid, _ = _compute_sid_layout(num_banks, banks_per_bank_group)

        # 提前构造 clock/timing 以便把 tRL 转换为 cycles
        clock = ClockModel(data_rate_gbps)
        t_rl_cycles = clock.ns_to_cycles(t_rl_ns)

        self._config = SimulationConfig(
            data_rate_gbps=data_rate_gbps,
            num_banks=num_banks,
            banks_per_bank_group=banks_per_bank_group,
            num_bank_groups=num_bank_groups,
            t_rcdrd_ns=t_rcdrd_ns, t_rcdwr_ns=t_rcdwr_ns,
            t_rp_ns=t_rp_ns, t_rc_ns=t_rc_ns, t_ras_ns=t_ras_ns,
            t_rtp_hbmck=t_rtp_hbmck, t_wr_ns=t_wr_ns, wl_hbmck=wl_hbmck,
            t_ccd_s=t_ccd_s, t_ccd_l=t_ccd_l,
            t_rrd_s=t_rrd_s, t_rrd_l=t_rrd_l, t_faw_hbmck=t_faw_hbmck,
            t_rtw_ns=t_rtw_ns, t_wtrl_hbmck=t_wtrl_hbmck, t_wtrs_hbmck=t_wtrs_hbmck,
            read_cam_depth=read_cam_depth, write_cam_depth=write_cam_depth,
            num_transactions=num_transactions,
            cmds_per_transaction=cmds_per_transaction,
            workload_size_bytes=workload_size_bytes,
            addr_mode=addr_mode, addr_map=resolved_addr_map,
            configuration=resolved_configuration, density_code=resolved_density_code,
            sid_remap_type=geometry["sid_remap_type"], max_system_la=geometry["max_system_la"],
            seed=seed, read_ratio=read_ratio,
            batch_timeout_cycles=batch_timeout_cycles,
            preparation_min_banks=preparation_min_banks,
            preparation_max_dispatches=preparation_max_dispatches,
            preparation_max_cycles=preparation_max_cycles,
            initial_batch_type=initial_batch_type,
            batch_scheduling=batch_scheduling,
            rw_4state_mode=rw_4state_mode,
            bg_interleave_priority=bg_interleave_priority,
            age_priority=age_priority,
            write_auto_precharge=write_auto_precharge,
            read_auto_precharge=read_auto_precharge,
            wra_refresh_guard_cycles=wra_refresh_guard_cycles,
            rda_refresh_guard_cycles=rda_refresh_guard_cycles,
            wra_only_after_page_hit=wra_only_after_page_hit,
            rda_only_after_page_hit=rda_only_after_page_hit,
            t_refi_per_bank_cycles=t_refi_per_bank_cycles,
            t_rfc_pb_ns=t_rfc_pb_ns,
            t_rl_ns=t_rl_ns,
            link_node_count=link_node_count,
            link_list_count=link_list_count,
            t_rl_cycles=t_rl_cycles,
        )
        self._validate_inputs(read_ratio, read_cam_depth, write_cam_depth,
                              initial_batch_type)

        self._clock = clock
        self._timing = TimingParameters.from_inputs(
            self._clock,
            t_rcdrd_ns, t_rcdwr_ns, t_rp_ns, t_rc_ns, t_ras_ns, t_rtp_hbmck,
            t_wr_ns, wl_hbmck,
            t_ccd_s, t_ccd_l, t_rrd_s, t_rrd_l, t_faw_hbmck,
            t_rtw_ns, t_wtrl_hbmck, t_wtrs_hbmck,
            t_rfc_pb_ns=t_rfc_pb_ns,
            t_ccdr_cycles=t_ccdr_cycles,
        )
        self._timing.validate()

        workload_gen = WorkloadGenerator(
            num_transactions=num_transactions,
            cmds_per_transaction=cmds_per_transaction,
            num_banks=num_banks,
            banks_per_bank_group=banks_per_bank_group,
            addr_mode=addr_mode, seed=seed, read_ratio=read_ratio,
            addr_map=resolved_addr_map, configuration=resolved_configuration,
            density_code=resolved_density_code,
            txn_id_assignment=txn_id_assignment,
        )
        all_entries, r_entries, w_entries = workload_gen.generate()
        self._all_burst_entries = all_entries
        # 拆开存: 准入阶段走 RR, 不再按 workload 顺序
        self._r_entries = r_entries
        self._w_entries = w_entries
        self._next_r_index = 0
        self._next_w_index = 0
        # admission RR: True 下一拍优先 R, False 下一拍优先 W (alternating)
        self._admission_rr_is_r: bool = True
        self._banks = [DRAMBank(i, i // banks_per_bank_group)
                       for i in range(num_banks)]

        # ---- tRREFD 跨调度器状态 (Channel 全局) ----
        # 最近一次 REFpb 的 cycle 和 bank。不同 SID 的不同 bank 同样受 tRREFD 约束。
        self._last_refpb_state = {"cycle": INITIAL_CYCLE_SENTINEL, "bank": -1}
        self._last_act_state = {
            "cycle": INITIAL_CYCLE_SENTINEL, "bank": -1, "bank_group": -1
        }
        self._act_refpb_faw_cycles: List[int] = []
        # precompute bank_id → sid 映射, refresh + row 路径都用
        self._bank_sid: List[int] = [
            _bank_id_to_sid(bid, banks_per_bank_group, _compute_sid_layout(num_banks, banks_per_bank_group)[1])
            for bid in range(num_banks)
        ]

        initial_rw_type = (RWType.READ if initial_batch_type == "READ"
                           else RWType.WRITE)
        self._refresh_scheduler = RefreshScheduler(
            self._banks, self._timing, num_banks, t_refi_per_bank_cycles,
            max_postpone_credits=max_postpone_credits,
            max_postpone_refab_rounds=max_postpone_refab_rounds,
            postpone_low_thr=postpone_low_thr,
            last_refpb_state=self._last_refpb_state,
            bank_sid=self._bank_sid,
            last_act_state=self._last_act_state,
            act_refpb_faw_cycles=self._act_refpb_faw_cycles)
        self._row_scheduler = RowScheduler(
            self._banks, self._timing, num_bank_groups,
            num_sid=num_sid,
            last_refpb_state=self._last_refpb_state,
            bank_sid=self._bank_sid,
            last_act_state=self._last_act_state,
            act_refpb_faw_cycles=self._act_refpb_faw_cycles,
            bg_interleave_priority=bg_interleave_priority,
            age_priority=age_priority)
        self._col_scheduler = ColScheduler(
            self._banks, self._timing, num_banks, num_bank_groups, num_sid,
            cmds_per_transaction, batch_scheduling, batch_timeout_cycles,
            initial_rw_type,
            preparation_min_banks=preparation_min_banks,
            preparation_max_dispatches=preparation_max_dispatches,
            preparation_max_cycles=preparation_max_cycles,
            sid_aware=sid_aware,
            write_auto_precharge=write_auto_precharge,
            read_auto_precharge=read_auto_precharge,
            refresh_pending=self._refresh_scheduler.refresh_pending,
            next_refresh_cycle=self._refresh_scheduler.next_refresh_cycle,
            wra_refresh_guard_cycles=wra_refresh_guard_cycles,
            rda_refresh_guard_cycles=rda_refresh_guard_cycles,
            wra_only_after_page_hit=wra_only_after_page_hit,
            rda_only_after_page_hit=rda_only_after_page_hit,
            rw_4state_mode=rw_4state_mode,
        )

        # ---- CAM + 准入节流 (v6.6: R/W 独立节流 + W col 累加器) ----
        self._read_cam: List[BurstCommandGroup] = []
        self._write_cam: List[BurstCommandGroup] = []
        # R/W 各自节流计时 (互不阻塞)
        self._next_r_admit_cycle: int = 0
        self._next_w_admit_cycle: int = 0
        # W 上游每 cycle 接收当前预拆 entry 的 1 条 command。
        # 收齐该 entry 的全部 1~4 条后，在最后一条到达的同 cycle admit。
        self._w_col_buffer: List['ColumnCommand'] = []

        # ---- V15 link list manager ----
        # 复用 workload 的 RNG (主 seed) 让选择行为可复现
        link_rng = random.Random(seed + 0xBADC0DE)
        # link_log_fp 是 V15 链路事件专用的 log 句柄. 与主 log_fp 分离,
        # 使主 log 仅含 cycle 行 + summary, V15 事件写到独立文件. 默认 None
        # (不写) 让单测 / 轻量场景下不生成 V15 log.
        self._link_list_mgr = LinkListManager(
            link_node_count=link_node_count,
            link_list_count=link_list_count,
            grant_per_cycle=LINK_NODE_GRANT_PER_CYCLE,
            free_per_cycle=LINK_NODE_FREE_PER_CYCLE,
            rng=link_rng,
            log_fp=link_log_fp,
            t_rl_cycles=t_rl_cycles,   # V15 fix: 传入实际 tRL, 之前没有传, get_stats 只能硬编码 0
            t_rl_ns=t_rl_ns,
        )

        # ---- 统计 ----
        self._simulation_start_cycle: Optional[int] = None
        self._simulation_end_cycle: Optional[int] = None
        # 分类型性能起点：分别记录首个 READ/WRITE burst entry 进入 CAM 的 cycle。
        self._first_read_cam_cycle: Optional[int] = None
        self._first_write_cam_cycle: Optional[int] = None
        # 分类型性能终点：READ 取最后一个 link node 释放，WRITE 取最后一条命令发出。
        self._last_read_release_cycle: Optional[int] = None
        self._last_write_issue_cycle: Optional[int] = None
        self._performance_end_cycle: Optional[int] = None
        self._total_cols_dispatched = 0
        self._total_act_count = 0
        self._total_pre_count = 0        # RowScheduler 发的 PRE (含 autoprecharge)
        self._total_refresh_force_pre_count = 0  # RefreshScheduler 发的 force-PRE, 单列

    @staticmethod
    def _validate_inputs(read_ratio, read_cam_depth, write_cam_depth,
                         initial_batch_type) -> None:
        """校验构造参数、配置组合和地址映射，尽早报告输入错误。"""
        if not 0.0 <= read_ratio <= 1.0:
            raise ValueError(f"read_ratio 必须在 [0, 1], 当前 {read_ratio}")
        if read_cam_depth < 1 or write_cam_depth < 1:
            raise ValueError("CAM_DEPTH 必须 >= 1")
        if initial_batch_type not in ("READ", "WRITE"):
            raise ValueError("initial_batch_type 必须是 'READ' 或 'WRITE'")

    # --------------------------------------------------------
    #  公开 API
    # --------------------------------------------------------

    def simulate(self,
                 verbose_cycles: int = 200,
                 log_fp: Optional[TextIO] = None) -> float:
        """跑仿真, 返回 perf (cmds/cycle); 超 max_cycles 异常终止返回 0.0"""
        _, groups_per_sid = _compute_sid_layout(
            self._config.num_banks, self._config.banks_per_bank_group)
        reporter = SimulationReporter(
            log_fp, verbose_cycles,
            banks_per_bank_group=self._config.banks_per_bank_group,
            groups_per_sid=groups_per_sid,
        )
        reporter.print_header(self._config, len(self._all_burst_entries))
        # V15: V15 链路事件的 log 句柄在 __init__() 时已通过 link_log_fp 传给 LinkListManager.
        # 这里**不要**再用 set_log_fp(log_fp) 把主 log 注入 LinkListManager — 主 log 仅含
        # cycle 行 + summary, V15 事件 (acquire/data_ready/release/list_freed) 写到独立文件.
        return self._run_simulation_loop(verbose_cycles, reporter)

    # --------------------------------------------------------
    #  主循环
    # --------------------------------------------------------

    def _run_simulation_loop(self, verbose_cycles: int,
                             reporter: SimulationReporter) -> float:
        """执行主仿真循环，直到全部命令完成或达到最大周期数。"""
        total_cmds = self._config.total_cmds
        max_cycles = total_cmds * MAX_CYCLES_FACTOR
        current_cycle = 0

        while (not self._performance_complete()
                and current_cycle < max_cycles):
            current_cycle = self._run_one_cycle(current_cycle, reporter, verbose_cycles)

        if current_cycle >= max_cycles:
            reporter.print_lines([f"  ERROR: 超过最大cycle限制 ({max_cycles}), 仿真异常终止"])
            return 0.0

        elapsed_cycles = self._performance_elapsed_cycles()
        perf = total_cmds / elapsed_cycles if elapsed_cycles > 0 else 0.0
        reporter.print_lines(
            self._build_summary_lines(total_cmds, current_cycle, elapsed_cycles, perf))
        return perf

    def _run_one_cycle(self, current_cycle: int,
                       reporter: SimulationReporter,
                       verbose_cycles: int) -> int:
        """一个 cycle: 入 CAM → tick banks → refresh vs row → col → log.

        ref_priority 策略:
          - 优先级链: mandatory REFpb > ACT/PRE > non-mandatory REFpb.
          - mandatory (prepare_due / hard_deadline / debt ≥ max_postpone_credits):
              refresh 抢占 row bus; timing 闸不允许时退让给 row.
          - non-mandatory: row_scheduler 先尝试; row 没发 → refresh 兜底.
          - cam_busy_banks 过滤: non-mandatory REFpb 选 bank 时跳过 CAM 中已有
            对应 cmd 的 bank, 避免选了一个 "REFPB 即将发出但 col 还在等待" 的 bank.
        """
        entered_entry = self._try_admit_burst_entry(current_cycle)
        for bank in self._banks:
            bank.tick(current_cycle, self._timing)

        # 收集当前 CAM 中还有未派发 cmd 的 bank 集合, 传给 refresh_scheduler
        # 使其 non-mandatory REFpb 选 bank 时跳过已有对应 cmd 的 bank。
        cam_busy_banks = self._collect_cam_busy_banks()

        from_refresh = False
        row_cmd: Optional[RowCommand] = None

        # ===== ref_priority 策略 =====
        # 优先级: mandatory REFpb > ACT/PRE > non-mandatory REFpb
        #
        # - mandatory (prepare_due / hard_deadline / debt ≥ max_postpone_credits):
        #     refresh 抢占 row bus; 仅当 timing 闸不允许时退让给 row.
        # - non-mandatory:
        #     row_scheduler 先尝试 (PRE > ACT); row 没发 → refresh 兜底.
        #     兜底发出的非强制 REFpb 计入 _non_mandatory_fallback_issued_count.
        # - mandatory 但 row_bus 已发 ACT/PRE 的情况: 见编排器 row 之后 try_issue;
        #   此处只保证"row_bus 没被 row 占时, mandatory 优先".
        active_cams = self._col_scheduler.get_row_candidate_cams(
            self._read_cam, self._write_cam)
        # 预判 refresh 是否 mandatory 
        is_mandatory = self._refresh_scheduler.is_mandatory_needed(
            current_cycle, cam_busy_banks)
        if is_mandatory:
            # mandatory: refresh 抢占 row bus
            row_cmd, _ = self._refresh_scheduler.try_issue(
                current_cycle, cam_busy_banks, via_fallback=False)
            if row_cmd is not None:
                from_refresh = True
            else:
                # 即便 mandatory, 若 timing 闸 (tRREFD/tFAW/tRRD) 不允许 → 退让给 row,
                # 避免 mandatory 死锁.
                row_cmd = self._row_scheduler.try_issue(current_cycle, active_cams)
        else:
            # non-mandatory: ACT/PRE 优先
            row_cmd = self._row_scheduler.try_issue(current_cycle, active_cams)
            if row_cmd is None:
                # row 没发 → refresh 兜底 (non-mandatory 也允许发, 走 row_bus 空闲 path)
                row_cmd, _ = self._refresh_scheduler.try_issue(
                    current_cycle, cam_busy_banks, via_fallback=True)
                if row_cmd is not None:
                    from_refresh = True
            else:
                # row 已发 → refresh 让位. 让位次数可间接从以下关系推导:
                #   yield ≈ non_mandatory_opportunity - non_mandatory_fallback_issued
                # 无需额外调用, 避免重复 is_mandatory_needed 判定.
                pass

        if row_cmd is not None:
            if row_cmd.kind == RowCommandType.ACT:
                self._total_act_count += 1
            elif row_cmd.kind == RowCommandType.PRE:
                # 区分 refresh 触发的 force-PRE 与常规 PRE (autoprecharge 等)
                if from_refresh:
                    self._total_refresh_force_pre_count += 1
                else:
                    self._total_pre_count += 1
            # REFPB 不计入 ACT/PRE 计数 (单独归入 refresh 统计)
        # 通知 col_scheduler: 当前 cycle 的 row 事件 (供准备期统计 target bank 的 ACT/PRE)
        self._col_scheduler.record_row_event(row_cmd)

        col_cmd = self._col_scheduler.try_issue(
            current_cycle, self._read_cam, self._write_cam)
        if col_cmd is not None:
            self._total_cols_dispatched += 1
            self._simulation_end_cycle = current_cycle
            if col_cmd.is_write:
                self._last_write_issue_cycle = current_cycle
            elif self._last_read_release_cycle is None:
                # READ 终点由 link node 释放阶段确定，而不是由 RD 发出确定。
                pass
            # V15 fix: READ 真正派发时记录 tRL 起点 (issued_cycle + col_cmd.issue_cycle).
            # 必须在 _complete_dispatch 之后 (col_cmd 已在 list 中) 且在 update_data_ready
            # 之前 (否则本 cycle 就可能被误标 ready).
            # WRITE 不走 link node, 不调.
            # 路径覆盖: _try_issue_of_type + _try_drain_inflight 都会走到这里.
            if not col_cmd.is_write:
                self._link_list_mgr.mark_dispatched(col_cmd, current_cycle)

        # V15: 更新 READ link node data_ready (dispatch + tRL ≤ current), 释放已 ready 的 head 节点.
        # 每 cycle 调用一次: _run_simulation_loop 的结束条件依赖此调用让 read 数据回流.
        self._link_list_mgr.update_data_ready(current_cycle, self._config.t_rl_cycles)
        self._link_list_mgr.release_ready_nodes(current_cycle)
        link_stats = self._link_list_mgr.get_stats()
        if (self._next_r_index >= len(self._r_entries)
                and link_stats["total_nodes_requested"] > 0
                and link_stats["released_count"] >= link_stats["total_nodes_requested"]):
            self._last_read_release_cycle = link_stats["last_node_release_cycle"]
        self._update_performance_end_cycle()

        cam_remaining = (self._config.read_cam_depth - len(self._read_cam),
                         self._config.write_cam_depth - len(self._write_cam))
        line = reporter.format_cycle_line(
            current_cycle, cam_remaining, entered_entry, row_cmd, col_cmd)
        should_print = (verbose_cycles == -1) or (current_cycle < verbose_cycles)
        reporter.write_cycle_line(current_cycle, line, should_print)

        return current_cycle + 1

    def _try_admit_burst_entry(self, current_cycle: int) -> Optional[BurstCommandGroup]:
        """v6.6: R/W 独立节流 + W col 累加器 (上游真实时序)

        规则:
          - W col 累加器: 每 cycle 收 1 W col (从 _w_col_stream 按顺序拆), 跟 R 准入独立
            收齐当前预拆 entry 的全部 1~4 条才 admit (上游 "W 收满 4 col 才下发")
          - R 实时: 1 entry / cycle, 不需要累加器
          - R 节流: next_r_admit_cycle 推进 (R_ADMIT_INTERVAL_CYCLES=1)
          - W 节流: next_w_admit_cycle 推进 (admit 后 +entry 内 col 数)
          - R/W 节流独立: R 节流不阻塞 W, W 节流不阻塞 R
          - RR: 严格交替 R 和 W (primary = self._admission_rr_is_r 决定)
          - Fallback: primary 不可入 (节流 / 累加器不满 / workload 越界 / CAM 满)
            → 试 secondary, 不阻塞
          - 若两侧都不可入: 本 cycle 不 admit, RR 不前进

        跟 v6.5 区别:
          - 旧: BURST_ADMIT_INTERVAL_CYCLES=4 统一节流, W 跟 R 共享
          - 新: R/W 各自节流 (R 1, W entry col 数), W 走 col-level 累加器
        """
        # 步骤 1: W col 累加器每 cycle 收 1 col (独立运行, 跟 R 准入无关)
        self._accumulate_w_col_if_needed(current_cycle)

        # 步骤 2: RR 决定 primary
        if self._admission_rr_is_r:
            primary, secondary = RWType.READ, RWType.WRITE
        else:
            primary, secondary = RWType.WRITE, RWType.READ

        # 步骤 3: R/W 节流独立检查 (R 看 next_r, W 看 next_w + 累加器满)
        primary_blocked = self._is_admission_blocked(primary, current_cycle)
        secondary_blocked = self._is_admission_blocked(secondary, current_cycle)

        # 步骤 4: 试 primary → fallback secondary
        admitted = None
        if not primary_blocked:
            admitted = self._try_admit_specific_type(current_cycle, primary)
        if admitted is None and not secondary_blocked:
            admitted = self._try_admit_specific_type(current_cycle, secondary)

        # 步骤 5: 推进 RR + 节流
        if admitted is not None:
            self._admission_rr_is_r = not self._admission_rr_is_r
            if admitted.commands[0].is_write:
                # W 节流: 下次准入最早 cycle = current + entry col 数
                self._next_w_admit_cycle = current_cycle + len(admitted.commands)
                if self._first_write_cam_cycle is None:
                    self._first_write_cam_cycle = current_cycle
            else:
                # R 节流: 1 cycle
                self._next_r_admit_cycle = current_cycle + R_ADMIT_INTERVAL_CYCLES
                if self._first_read_cam_cycle is None:
                    self._first_read_cam_cycle = current_cycle
            if self._simulation_start_cycle is None:
                self._simulation_start_cycle = current_cycle
        return admitted

    def _collect_cam_busy_banks(self) -> set:
        """返回当前 R/W CAM 中还有未派发 cmd 的 bank 集合.

        为 RefreshScheduler.try_issue 提供 “CAM 占用 bank” 名单。
        实现: 遍历 read_cam 和 write_cam 里 next_dispatch_index < len(commands)
        的 entry, 收集其 bank_id 成 set.

        语义: 这些 bank 上的 row 调度尚未走完, 你选了它们刷新会导致
        col 调度被强制中断. non-mandatory 路径会跳过这些 bank.
        """
        cam_busy = set()
        for cam in (self._read_cam, self._write_cam):
            for entry in cam:
                if entry.next_dispatch_index < len(entry.commands):
                    cam_busy.add(entry.bank_id)
        return cam_busy

    def _is_admission_blocked(self, rw_type: 'RWType', current_cycle: int) -> bool:
        """检查指定类型准入是否被阻塞 (v6.6)

        R: 阻塞 if current_cycle < self._next_r_admit_cycle
        W: 阻塞 if current_cycle < self._next_w_admit_cycle OR 当前 entry 尚未收齐
        """
        if rw_type == RWType.READ:
            return current_cycle < self._next_r_admit_cycle
        else:  # WRITE
            if current_cycle < self._next_w_admit_cycle:
                return True
            if self._next_w_index >= len(self._w_entries):
                return True
            return len(self._w_col_buffer) < len(self._w_entries[self._next_w_index].commands)

    def _accumulate_w_col_if_needed(self, current_cycle: int) -> None:
        """每 cycle 接收当前预拆 Write entry 的一条 command，保留 partial entry 边界。"""
        if self._next_w_index >= len(self._w_entries):
            return
        target = self._w_entries[self._next_w_index]
        if len(self._w_col_buffer) >= len(target.commands):
            return
        self._w_col_buffer.append(target.commands[len(self._w_col_buffer)])

    def _try_admit_specific_type(self, current_cycle: int,
                                 rw_type: RWType) -> Optional[BurstCommandGroup]:
        """对指定类型 (R 或 W) 尝试 admit 一个 entry (v6.6).

        R: 从 _r_entries 实时取 1 entry (4 col, 不需要累加)
        W: 收齐当前预拆 entry 后直接 admit (累加器路径)

        不可入的情况:
          R: workload 越界 / R CAM 满
          W: 当前 entry 尚未收齐 / W CAM 满
        """
        if rw_type == RWType.READ:
            # R: 实时从 _r_entries 取
            entries = self._r_entries
            next_index = self._next_r_index
            cam = self._read_cam
            cam_depth = self._config.read_cam_depth

            if next_index >= len(entries):
                return None
            if len(cam) >= cam_depth:
                return None

            burst_entry = entries[next_index]
            # V15: READ burst 入 CAM 前必须成功申请 link node (空闲节点数 >= burst size
            # 且当 cycle grant 配额未用完). 失败则不入 CAM, 本 cycle 让 primary/secondary
            # fallback 尝试 WRITE. _next_r_index 不推进, 下一 cycle 重试.
            ok = self._link_list_mgr.acquire_nodes_for_burst(
                burst_entry.transaction_id, burst_entry, current_cycle)
            if not ok:
                return None

            burst_entry.entry_cycle = current_cycle
            cam.append(burst_entry)
            self._next_r_index = next_index + 1
            return burst_entry
        else:  # WRITE
            if self._next_w_index >= len(self._w_entries):
                return None
            target = self._w_entries[self._next_w_index]
            if len(self._w_col_buffer) < len(target.commands):
                return None
            if len(self._write_cam) >= self._config.write_cam_depth:
                return None

            # 直接 admit 预拆好的 entry，绝不跨 page/segment 重组。
            assert all(a is b for a, b in zip(self._w_col_buffer, target.commands))
            self._w_col_buffer.clear()
            target.entry_cycle = current_cycle
            self._write_cam.append(target)
            self._next_w_index += 1
            return target

    def _update_performance_end_cycle(self) -> None:
        """按 R/W workload 选择性能统计终点：READ 释放、WRITE 发出，混合取最大值。"""
        read_end = self._last_read_release_cycle if self._r_entries else None
        write_end = self._last_write_issue_cycle if self._w_entries else None
        ends = [cycle for cycle in (read_end, write_end) if cycle is not None]
        self._performance_end_cycle = max(ends) if ends else None

    def _performance_complete(self) -> bool:
        """判断所有存在的 R/W 性能区间是否均已闭合。"""
        if self._total_cols_dispatched < self._config.total_cmds:
            return False
        read_complete = (not self._r_entries
                         or self._last_read_release_cycle is not None)
        write_complete = (not self._w_entries
                          or self._last_write_issue_cycle is not None)
        if not (read_complete and write_complete):
            return False
        self._update_performance_end_cycle()
        return self._performance_end_cycle is not None

    def _performance_elapsed_cycles(self) -> int:
        """分别计算 R/W 区间；混合 workload 的性能分母取两个区间长度最大值。"""
        intervals = []
        if self._r_entries:
            if self._first_read_cam_cycle is None or self._last_read_release_cycle is None:
                return 0
            intervals.append(self._last_read_release_cycle - self._first_read_cam_cycle)
        if self._w_entries:
            if self._first_write_cam_cycle is None or self._last_write_issue_cycle is None:
                return 0
            intervals.append(self._last_write_issue_cycle - self._first_write_cam_cycle)
        return max(intervals) if intervals else 0

    # --------------------------------------------------------
    #  Summary
    # --------------------------------------------------------

    def _build_summary_lines(self, total_cmds: int, current_cycle: int,
                             elapsed_cycles: int, perf: float) -> List[str]:
        """汇总吞吐率、命令计数、刷新和调度统计信息。"""
        cfg = self._config
        timing = self._timing
        return [
            f"\n  {'='*72}",
            f"  addr_mode={cfg.addr_mode} (read_ratio={cfg.read_ratio}) 仿真结果",
            f"  {'='*72}",
            f"  [参数配置]",
            f"    DATA_RATE={cfg.data_rate_gbps} Gbps, "
            f"DQS={self._clock.dqs_freq_ghz} GHz, "
            f"HBM_CK={self._clock.hbm_ck_freq_ghz} GHz, "
            f"DFI_CLK={self._clock.dfi_clk_freq_ghz} GHz, "
            f"tDQS={self._clock.tdqs_ns:.5f} ns, "
            f"tCK={self._clock.tck_hbm_ns:.5f} ns, "
            f"tDFI={self._clock.tdfi_ns:.5f} ns "
            f"(1 model cycle={self._clock.HBM_CK_PER_DFI_CYCLE} HBM CK; "
            f"MC0 phase={self._clock.MC0_PHASE}, MC1 phase={self._clock.MC1_PHASE})",
            f"    NUM_BANKS={cfg.num_banks}, NUM_BANK_GROUPS={cfg.num_bank_groups}",
            f"    地址生成: config={cfg.configuration}, density={cfg.density_code if cfg.density_code is None else format(cfg.density_code, '04b')}, remap_type={cfg.sid_remap_type}, addr_mode={cfg.addr_mode}, max_system_la={cfg.max_system_la}, "
            f"effective_bits={cfg.max_system_la.bit_length()}, "
            f"max_system_la=0x{cfg.max_system_la:X}",
            f"    tRCDRD={timing.t_rcdrd_cycles} cycles ({cfg.t_rcdrd_ns} ns), "
            f"tRCDWR={timing.t_rcdwr_cycles} cycles ({cfg.t_rcdwr_ns} ns)",
            f"    tRP={timing.t_rp_cycles} cycles, "
            f"tRC={timing.t_rc_cycles} cycles, "
            f"tRAS={timing.t_ras_cycles} cycles",
            f"    tRTP={cfg.t_rtp_hbmck} HBM CK ({timing.t_rtp_cycles} cycles), "
            f"tWR={cfg.t_wr_ns} ns, "
            f"WL={cfg.wl_hbmck} HBM CK "
            f"(WRITE+AP = WL+{WL_TWTR_OFFSET}+WR = {timing.write_ap_cycles} cycles)",
            f"    tCCDs={timing.t_ccd_s_cycles}, tCCDl={timing.t_ccd_l_cycles}, "
            f"tRRDs={timing.t_rrd_s_cycles}, tRRDl={timing.t_rrd_l_cycles}, "
            f"tFAW={cfg.t_faw_hbmck} HBM CK ({timing.t_faw_cycles} cycles)",
            f"    tRTW={timing.t_rtw_cycles} cycles ({cfg.t_rtw_ns} ns, R→W, 公式推导), "
            f"tWTRL={cfg.t_wtrl_hbmck} HBM CK (W→R same bg), "
            f"tWTRS={cfg.t_wtrs_hbmck} HBM CK (W→R diff bg)",
            f"    READ_CAM_DEPTH={cfg.read_cam_depth}, "
            f"WRITE_CAM_DEPTH={cfg.write_cam_depth}",
            f"    read_ratio={cfg.read_ratio} (per-txn)",
            f"    WRITE 自动预充电: {'WRA enabled' if cfg.write_auto_precharge else 'disabled'}, "
            f"refresh_guard={cfg.wra_refresh_guard_cycles} cycles, "
            f"only_after_page_hit={cfg.wra_only_after_page_hit}",
            f"    READ 自动预充电 : {'RDA enabled' if cfg.read_auto_precharge else 'disabled'}, "
            f"refresh_guard={cfg.rda_refresh_guard_cycles} cycles, "
            f"only_after_page_hit={cfg.rda_only_after_page_hit}",
            f"    R/W 调度策略: "
            f"{'4 态机 (RD/WR/RD_WR/WR_RD)' if cfg.rw_4state_mode else ('Batch (stick-to-one-side)' if cfg.batch_scheduling else 'Alternating (try opposite first)')}, "
            f"batch_timeout={cfg.batch_timeout_cycles} cycles, "
            f"BG 交织={'ON' if cfg.bg_interleave_priority else 'OFF'}, "
            f"Age={'ON' if cfg.age_priority else 'OFF'}, "
            f"initial={cfg.initial_batch_type}",
            f"    准备期 (preparation) 参数: "
            f"min_banks={cfg.preparation_min_banks} (目标 bank ready 阈值, "
            f"snapshot<{cfg.preparation_min_banks} 时按全数算), "
            f"max_dispatches={cfg.preparation_max_dispatches} (current mode 软上限), "
            f"max_cycles={cfg.preparation_max_cycles} (准备期硬上限)",
            f"    Refresh (HBM3 REFpb per-bank): "
            f"per-bank interval={cfg.t_refi_per_bank_cycles} cycles "
            f"({cfg.t_refi_per_bank_cycles * 0.8333:.0f} ns, "
            f"注: 这是 per-bank 间隔, 不是 spec tREFIpb), "
            f"tRFCpb={timing.t_rfc_pb_cycles} cycles ({cfg.t_rfc_pb_ns} ns, "
            f"bank 阻塞时间)",
            f"  [命令统计]",
            f"    Col命令总数 : {total_cmds}",
            f"    ACT命令数   : {self._total_act_count}",
            f"    PRE命令数   : {self._total_pre_count}  (显式 PRE，不含 WRA/RDA 内部 precharge)",
            f"    refresh force-PRE 数 : {self._total_refresh_force_pre_count}  (RefreshScheduler 发, 单独计)",
            f"  [WRA/RDA 自动预充电统计]",
            f"    WRA enabled  : {self._col_scheduler.get_auto_precharge_stats()['wra_enabled']}",
            f"    RDA enabled  : {self._col_scheduler.get_auto_precharge_stats()['rda_enabled']}",
            f"    WRA 命令数   : {self._col_scheduler.get_auto_precharge_stats()['wra_count']}",
            f"    RDA 命令数   : {self._col_scheduler.get_auto_precharge_stats()['rda_count']}",
            f"    普通 WR 数   : {self._col_scheduler.get_auto_precharge_stats()['normal_write_count']}",
            f"    普通 RD 数   : {self._col_scheduler.get_auto_precharge_stats()['normal_read_count']}",
            f"    WRA 合并 PRE 数 : {self._col_scheduler.get_auto_precharge_stats()['wra_saved_pre_count']}",
            f"    RDA 合并 PRE 数 : {self._col_scheduler.get_auto_precharge_stats()['rda_saved_pre_count']}",
            f"    Write 同 page 串接次数 : {self._col_scheduler.get_auto_precharge_stats()['write_page_hit_chain_count']}",
            f"    Read 同 page 串接次数  : {self._col_scheduler.get_auto_precharge_stats()['read_page_hit_chain_count']}",
            f"    同 page 连续派发总次数 : {self._col_scheduler.get_auto_precharge_stats()['page_hit_chain_count']}",
            f"    总省去 PRE 数 : {self._col_scheduler.get_auto_precharge_stats()['saved_pre_count']}",
            f"    总省去 ACT 数 : {self._col_scheduler.get_auto_precharge_stats()['saved_act_count']}",
            f"  [准备期统计]",
            *_format_preparation_stats(self._col_scheduler.get_preparation_stats()),
            f"  [准备期明细]",
            *_format_preparation_history(self._col_scheduler.get_preparation_history()),
            f"  [SID-aware 选优统计]",
            *_format_sid_aware_stats(self._col_scheduler.get_sid_aware_stats()),
            f"  [RW 4 态机统计 (v16.3+)]",
            *_format_rw_4state_stats(self._col_scheduler.get_rw_4state_stats()),
            f"  [BG 交织 ACT 统计 (v17+)]",
            *_format_bg_interleave_stats(self._row_scheduler.get_bg_interleave_stats()),
            f"  [Age 优先级 ACT 统计 (v18+)]",
            *_format_age_priority_stats(self._row_scheduler.get_age_priority_stats()),
            f"  [Refresh 统计 (HBM3 REFpb, per-bank)]",
            *_format_refresh_stats(self._refresh_scheduler.get_stats()),
            f"  [时间统计]",
            f"    simulation_start_cycle (首个burst entry入CAM) : cycle {self._simulation_start_cycle}",
            f"    simulation_end_cycle   (末条Col命令发射)      : cycle {self._simulation_end_cycle}",
            f"    READ 区间  (首个R入CAM → 最后R节点释放)       : {self._first_read_cam_cycle} → {self._last_read_release_cycle}",
            f"    WRITE 区间 (首个W入CAM → 最后W命令发出)       : {self._first_write_cam_cycle} → {self._last_write_issue_cycle}",
            f"    性能统计终点 (仿真完成事件cycle)              : cycle {self._performance_end_cycle}",
            f"    仿真总cycles                                    : {current_cycle}",
            f"    elapsed = max(READ区间, WRITE区间)             : {elapsed_cycles}",
            f"  [性能指标]",
            f"    Perf = Col命令数 / 新性能统计区间",
            f"         = {total_cmds} / {elapsed_cycles}",
            f"         = {perf:.6f} cmds/cycle",
            f"  {'='*72}",
        ]


# ============================================================
#  主程序入口
# ============================================================

# ============================================================
#  正式版维护清单
# ============================================================
# [ ] 接入完整的 Row Remap 表。
# [ ] 接入完整的 Column Remap 表。
# [ ] 增加可配置的 Open-page / Close-page policy。
# [x] 重构 REFpb postpone debt、per-SID rolling-set、set-boundary 与 hard deadline。
# [x] v16.2: debt≤8 fail-fast 硬约束与 deadline violation 事件/周期统计。
# [x] v16.3: Non-mandatory REFpb 选 bank 时跳过 R/W CAM 中仍有未派发命令的 bank；
#      全部候选都被占用则本 cycle 暂不发。完成 8H/12H 16-case 32-run 性能对比 (几何平均 +0.49%)。
# [x] v17.1: 注释级 patch — 重定义性能统计区间。READ 终点改为最后一个 link node
#      释放 cycle, WRITE 终点不变 (末条命令发出), 混合取两类区间长度最大值,
#      仿真退出条件同步等待双侧闭合。无代码字段新增 (仅 summary 文档同步)。
#      8H/12H、txn=10000 回归: 单边 ±2%, 混合 +8.96% ~ +30.45%。
# [ ] 增加 REFpb pull-in 与自刷新策略。
# [ ] 增加更细粒度的 Bank Group 调度策略统计。
# [ ] 增加读写 turnaround 与 page-hit 的独立性能计数器。
#
# 维护原则：新增地址转换必须放在统一地址转换层；调度器只消费已经
# 解码完成的 SID/BG/BA/ROW/COL，不应自行解释逻辑地址位。


def main() -> None:
    """跑 8 个 run 做性能对比.

    输出两个独立 log 文件:
      - dram_sim_log.txt        主 log (cycle 行 + summary, 人类阅读)
      - dram_sim_link_log.txt   V15 link list/node 详细事件 (机器/调试)
    """
    verbose_cycles = 50
    seed = 42
    log_file = "dram_sim_log.txt"
    link_log_file = "dram_sim_link_log.txt"

    with open(log_file, "w", encoding="utf-8") as log_fp:
        with open(link_log_file, "w", encoding="utf-8") as link_log_fp:
            _write_log_header(log_fp)
            _write_log_header(link_log_fp)
            runs = _run_all_cases(seed, verbose_cycles, log_fp, link_log_fp)
            _write_comparison(runs, log_fp)

    print(f"\n  完整日志已保存至: {log_file}")
    print(f"  V16.2 link 事件日志: {link_log_file}")


def _write_log_header(log_fp: TextIO) -> None:
    """向日志文件写入单次测试的配置标题。"""
    log_fp.write("#" * 72 + "\n")
    log_fp.write("#  DRAM Command Scheduling Simulator "
                 "(HBM3 Spec-Faithful, Batch R/W)\n")
    log_fp.write("#" * 72 + "\n")


def _run_all_cases(seed: int, verbose_cycles: int, log_fp: TextIO, link_log_fp: TextIO
                   ) -> List[Tuple[str, float, str, float]]:
    """case ∈ {1,2} × {纯R, 纯W} (batch) + {50/50} × {batch, alternating}, 共 8 runs.

    纯 R/W 下 alternating 无"另一侧"可切, 退化为 batch, 跳过.
    """
    runs: List[Tuple[str, float, str, float]] = []
    for addr_mode in ('linear', 'random'):
        for read_ratio in (1.0, 0.0):
            runs.append(_run_one(addr_mode, read_ratio, True, seed,
                                  verbose_cycles, log_fp, link_log_fp))
        for batch in (True, False):
            runs.append(_run_one(addr_mode, 0.5, batch, seed,
                                  verbose_cycles, log_fp, link_log_fp))
    return runs


def _run_one(addr_mode: str, read_ratio: float, batch: bool,
             seed: int, verbose_cycles: int, log_fp: TextIO, link_log_fp: TextIO
             ) -> Tuple[str, float, str, float]:
    """跑单个 (addr_mode, read_ratio, mode) 组合, 返回 (case, read_ratio, mode, perf)"""
    mode = "batch" if batch else "alternating"
    header = (f"\n{'#'*72}\n"
              f"#  addr_mode={addr_mode}, read_ratio={read_ratio}, mode={mode}\n"
              f"{'#'*72}")
    print(header)
    log_fp.write(header + "\n")
    link_log_fp.write(header + "\n")

    scheduler = HBMCommandScheduler(
        addr_mode=addr_mode, seed=seed,
        cmds_per_transaction=4, read_ratio=read_ratio,
        batch_scheduling=batch,
        link_log_fp=link_log_fp,
    )
    perf = scheduler.simulate(verbose_cycles=verbose_cycles, log_fp=log_fp)
    return (addr_mode, read_ratio, mode, perf)


def _write_comparison(runs: List[Tuple[str, float, str, float]],
                      log_fp: TextIO) -> None:
    """8-run 性能对比表 + 50/50 专项 (Batch vs Alternating)"""
    lines = [
        "\n" + "#" * 72,
        "#  性能对比",
        "#" * 72,
        f"  {'addr_mode':>10} | {'read_ratio':>10} | {'mode':>12} | {'perf':>10}",
        f"  {'─'*10}─┼─{'─'*10}─┼─{'─'*12}─┼─{'─'*10}",
    ]
    for addr_mode, read_ratio, mode, perf in runs:
        lines.append(
            f"  {addr_mode:>10} | {read_ratio:>10.1f} | {mode:>12} | {perf:>10.6f}"
        )
    lines.append("#" * 72)

    lines += ["", "#  50/50 专项: Batch vs Alternating", "#" * 72]
    for addr_mode in ("linear", "random"):
        batch_perf = next(p for a, r, m, p in runs
                          if a == addr_mode and r == 0.5 and m == "batch")
        alternating_perf = next(p for a, r, m, p in runs
                                if a == addr_mode and r == 0.5 and m == "alternating")
        ratio = batch_perf / alternating_perf if alternating_perf > 0 else 0
        lines.append(
            f"  addr_mode={addr_mode} (50/50): "
            f"batch={batch_perf:.6f}, alternating={alternating_perf:.6f}, "
            f"batch/alternating={ratio:.4f} ({(ratio-1)*100:+.1f}%)"
        )
    lines.append("#" * 72)

    for line in lines:
        print(line)
        log_fp.write(line + "\n")


if __name__ == '__main__':
    main()
