"""
stall_attribution.py
====================

HBM3 调度仿真器的 stall attribution / 阻塞归因模块 (v1.0)
========================================================

本模块**只读**地分析每个没有派发列命令的 cycle 的阻塞原因,
对 model.py 的调度行为**完全无影响**. 集成后用户可通过 CLI flag
``--stall-attribution`` 在 ``python model.py`` 一键启用.

----------------------------------------------------------------
1. 设计目标 (5 条不变量)
----------------------------------------------------------------
  1. 零侵入: 不修改 model.py 的任何调度逻辑;
  2. 零副作用: 所有 probe / query 方法纯函数式, 不修改任何 scheduler 状态;
  3. 可关闭: enabled=False 时几乎零开销 (10000 cycle < 100ms);
  4. 可对账: 与 ColEligibilityChecker.check() 保持语义一致;
  5. 自包含: 不 import model.py, 通过 dataclass snapshot 传状态, 避免循环依赖.

----------------------------------------------------------------
2. CLI 用法 (model.py 集成后)
----------------------------------------------------------------
默认 (向后兼容, 不启用 stall attribution):
    $ python model.py

启用 stall 统计 (输出 3 个聚合文件 + 控制台 summary 表):
    $ python model.py --stall-attribution

启用 + 逐 cycle 详 trace (额外输出 stall_cycles.csv):
    $ python model.py --stall-attribution --stall-cycle-trace

自定义输出路径:
    $ python model.py --stall-attribution \
        --stall-summary  my_summary.json \
        --stall-episode  my_episodes.csv \
        --stall-switch   my_switch.csv

5 个参数详细说明:
    --stall-attribution    flag (默认 False)  总开关. 不传 = 仿真行为与原版完全一致.
    --stall-cycle-trace    flag (默认 False)  是否写 stall_cycles.csv (每 cycle 一行, 文件较大).
    --stall-summary PATH   str  (默认 stall_summary.json)   summary JSON 路径.
    --stall-episode PATH   str  (默认 stall_episodes.csv)   episode CSV 路径.
    --stall-switch  PATH   str  (默认 stall_switch_effects.csv)  切换效果 CSV 路径.

依赖关系:
    - 3 个 PATH 参数必须在 --stall-attribution=True 时才有效 (否则 enabled=False, 文件为空);
    - --stall-cycle-trace 必须与 --stall-attribution 一起用 (默认写 stall_cycles.csv);
    - 5 个参数相互独立, 可任意组合.

默认启用时会在当前目录生成:
    - stall_summary.json
    - stall_episodes.csv
    - stall_switch_effects.csv
加 --stall-cycle-trace 还会多:
    - stall_cycles.csv

----------------------------------------------------------------
3. 在代码中直接传参 (绕过 CLI)
----------------------------------------------------------------
from model import HBMCommandScheduler
sched = HBMCommandScheduler(
    addr_mode="linear", seed=42, num_transactions=1000,
    stall_attribution_enabled=True,        # 总开关
    stall_record_cycle_trace=True,         # 逐 cycle 记录
    stall_summary_output_path="out/summary.json",
    stall_episode_output_path="out/episodes.csv",
    stall_switch_effect_output_path="out/switch.csv",
    stall_cycle_trace_output_path="out/cycles.csv",
)
perf = sched.simulate(verbose_cycles=0)
# 仿真结束时, 4 个文件自动生成, 控制台打印 summary 表.

----------------------------------------------------------------
4. 输出文件 schema
----------------------------------------------------------------
stall_summary.json (顶层 key):
    metadata: {version, enabled, attribution_runtime_seconds, attribution_cycles_observed}
    global: {elapsed_cycles, column_issue_cycles, read/write_issue_cycles,
             no_demand_cycles, true_stall_cycles, column/demand_utilization}
    stall_reason_breakdown: {STALL_REASON_NAME: cycle_count, ...}
    policy_reason_breakdown: {POLICY_REASON_NAME: cycle_count, ...}
    dual_side: {both_modes_blocked_cycles, ...}
    mode_policy: {other_mode_could_issue_cycles, avoidable_switch_stall_cycles,
                  wrong_mode_residency_cycles}
    read_block_reasons / write_block_reasons / drain_block_reasons: dict
    episodes: {episode_count, mean_duration, p50/p90/p99/max_duration}
    switch_effects: {switch_count, by_path: {path: {count, mean_cold_start, mean_post_16_issue}}}
    max_consecutive_stall_cycles: int

stall_episodes.csv (每行一个连续 stall episode):
    start_cycle, end_cycle, duration, main_reason, reason_counts,
    scheduling_mode, starting_mode, ending_mode,
    other_mode_ready_cycles, max_other_eligible,
    preparation_cycles, refresh_interference_cycles, ended_by

stall_switch_effects.csv (每行一次 Batch 切模式):
    switch_cycle, path (atomic_timeout_ready / empty_fallback / stuck_fallback / prep_exit),
    from_type, to_type, prep_exit_reason,
    pre_window_issue_count, pre_window_stall_count, pre_window_mode_policy_stall_count,
    target_eligible_at_switch, source_eligible_at_switch,
    first_target_issue_cycle, switch_cold_start_cycles,
    post_issue_w{8/16/32}, post_stall_w{8/16/32},
    post_ta_w{8/16/32}, post_bnr_w{8/16/32}, post_mp_w{8/16/32}

stall_cycles.csv (每行一个 cycle, --stall-cycle-trace 时才生成):
    cycle, mode, current_mode, prep, issued_col, issued_type,
    read_candidates, read_eligible, read_reason, read_min_wait,
    write_candidates, write_eligible, write_reason, write_min_wait,
    drain_candidates, drain_eligible, drain_reason, drain_min_wait,
    channel_reason, policy_reason,
    other_mode_could_issue, avoidable_by_switch,
    refresh_cmd, row_cmd,
    switch_occurred, switch_path

----------------------------------------------------------------
5. 验证结果 (回归一致性)
----------------------------------------------------------------
8 case × on/off 测试 PASS (test_stall_attribution.py::TestBaselineRegression):
    - perf 完全一致 (1e-6 精度)
    - 派发命令序列完全一致
      (cycle, is_write, bank_id, sid_id, bg_id, ba_id, row_id,
       col_index, dispatch_id, transaction_id, segment_id)
    - _switch_trace 长度与内容完全一致
    - refresh 统计完全一致
    - 不影响任何 RR pointer / batch mode / preparation state / stuck counter
    - 不影响 CAM / bank / bus / refresh / link 状态
    - 所有 probe/query 方法**无副作用** (TestNoSideEffects 验证)

----------------------------------------------------------------
6. 模块导出清单
----------------------------------------------------------------
枚举 (Enums):
    StallReason              阻塞原因 (28 种)
    PolicyStallReason        策略子原因 (10 种)

Frozen snapshot dataclasses (跨模块只读传状态):
    BankSnapshot             单 bank 只读快照
    BusSnapshot              Col 通道 (_ColBusState) 快照
    ResourceSnapshot         准入节流 + link 节点 快照
    TimingSnapshot           TimingParameters 快照
    CmdSnapshot              单 ColumnCommand 快照
    CamSnapshot              单 CAM 快照
    ColPreDispatchSnapshot   完整 pre-dispatch 状态
    SchedulerCycleContext    每 cycle 调度上下文

结果 dataclasses:
    ColCheckResult           单 cmd eligibility 诊断
    TypeProbeResult          R 或 W 单侧 probe 结果
    DrainProbeResult         in-flight drain probe 结果
    StallCycleRecord         逐 cycle 记录 (CSV 输出)
    StallEpisode             连续 stall 合并的 episode
    SwitchEffectRecord       每次 Batch 切模式效果

Config:
    StallAttributionConfig   全部配置项

纯函数 (无副作用, 可独立测试):
    explain_col_eligibility(cmd, bank, bus, timing, current_cycle, [resource])
    probe_type(cmd_type, cam, banks_by_id, bus, timing, resource, current_cycle)
    probe_drain(read_cam, write_cam, banks_by_id, bus, timing, current_cycle)
    classify_cycle(context, read_probe, write_probe, drain_probe)
    _pick_primary_reason(reasons_with_ready, current_cycle)
    _policy_reason_from_str(s)  字符串 -> PolicyStallReason
    _percentile(values, pct)   自实现百分位

主类:
    StallAttribution         observe_cycle / build_summary_dict / format_summary /
                              write_outputs / feed_external_switch_entry

----------------------------------------------------------------
7. 关键不变量 (与 model.py 集成时必须遵守)
----------------------------------------------------------------
  A. Stall Attribution 是只读诊断, **绝不**修改:
       - RR pointer (read/write/drain)
       - batch type / dispatch count / stuck counter
       - preparation state
       - bank state / bus state / refresh state
       - CAM 内容 / link 池
       - 任何 _complete_dispatch 副作用
  B. probe 必须用 pre-dispatch snapshot, 派发后状态已改写, 不能用.
  C. _last_policy_hold_reason 只在 ColScheduler._try_issue_batch 分支**末尾**赋值,
     从不参与 if/elif 条件.
  D. enabled=False 时:
       - observe_cycle 立即 return, 不构造 snapshot
       - write_outputs 直接 return, 不写任何文件
       - 主仿真代码路径上**完全无开销** (除 1 个 bool 字段)
  E. 异常隔离: _observe_stall_attribution 内部 try/except, 任何 stall attribution
     自身的异常**不会**传播到主仿真.
"""

from __future__ import annotations

import csv
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
#  枚举
# ============================================================

class StallReason(Enum):
    """列命令无法派发的阻塞原因 (28 种).

    分类速查:
      1. NONE / CAM_EMPTY / NO_CURRENT_COMMAND     - 需求或状态本身没有可发命令
      2. BANK_* / ROW_MISMATCH                    - 银行/行 状态不符
      3. TRCD_RD / TRCD_WR                        - tRCD 时序
      4. WRONG_DISPATCH_ID / WRONG_COL_INDEX      - txn/col 顺序
      5. TCCD_S / TCCD_L / TCCDR                  - 列命令间隔
      6. RTW / WTR_S / WTR_L                      - 读写切换
      7. LINK_NODE_EMPTY / LINK_LIST_EMPTY / LINK_RESOURCE_BLOCK - 链路资源
      8. REFRESH_INTERFERENCE                     - refresh 干扰
      9. MODE_POLICY / PREPARATION_POLICY / DRAIN_POLICY / ROW_MODE_VISIBILITY - 调度策略
      10. MIXED_TIMING_BLOCK / UNKNOWN            - 多约束/未知
    """
    NONE = auto()  # 默认占位, 无阻塞

    # 没有需求
    CAM_EMPTY = auto()            # R+W CAM + drain 三侧均无 candidate
    NO_CURRENT_COMMAND = auto()    # CAM 有 entry 但 next_dispatch_index 已超 segment_cmd_count

    # Bank / row 状态
    BANK_IDLE_WAIT_ACT = auto()    # 银行 IDLE, 等 RowScheduler 发 ACT 才能派发 col
    BANK_ACT_WAIT = auto()         # ACT_WAIT 态, 等 tRCDRD/tRCDWR
    BANK_PRE_WAIT = auto()         # PRE_WAIT 态, 等 tRP
    BANK_AUTO_PRE_WAIT = auto()    # AUTO_PRE_WAIT 态, 等 WRA/RDA 内部 precharge 完成
    BANK_REFRESHING = auto()       # REFRESHING 态, 等 tRFCpb
    ROW_MISMATCH = auto()          # bank.open_row 与 cmd.row_id 不一致 (同 bank 复用场景)

    # tRCD
    TRCD_RD = auto()              # READ 还差 tRCDRD cycles (bank.ACT_WAIT/ACTING + time 不够)
    TRCD_WR = auto()              # WRITE 还差 tRCDWR cycles

    # transaction / column ordering
    WRONG_DISPATCH_ID = auto()   # cmd.dispatch_id != bank.serving_dispatch_id (其他 txn 持有此 bank)
    WRONG_COL_INDEX = auto()      # cmd.segment_col_index != bank.cols_dispatched (segment 顺序错)

    # column timing
    TCCD_S = auto()              # bus-wide tCCDS 不满足 (上次 col 距今 < tCCD_S)
    TCCD_L = auto()              # per-bg tCCDL 不满足 (同 bg 上次 col 距今 < tCCD_L)
    TCCDR = auto()              # HBM3 inter-SID tCCDR 不满足 (仅 READ 跨 SID)

    # read/write turnaround
    RTW = auto()                 # R->W tRTW 不满足
    WTR_S = auto()               # W->R 异 BG tWTRS (= WL+2+tWTRS) 不满足
    WTR_L = auto()               # W->R 同 BG tWTRL (= WL+2+tWTRL) 不满足

    # 资源限制
    LINK_NODE_EMPTY = auto()      # 链路节点池已空, READ burst 无节点可用
    LINK_LIST_EMPTY = auto()      # 所有链表都被占用 (理论上不应单独出现)
    LINK_RESOURCE_BLOCK = auto()  # 准入节流 (R/W 节流) 未到或 burst 长度超 grant_per_cycle

    # refresh
    REFRESH_INTERFERENCE = auto()  # refresh 干扰 (projected_idle_cycle 撞 next_refresh_cycle)

    # scheduler policy
    MODE_POLICY = auto()          # Batch 模式保持 current_type, 对向能发 (avoidable_by_switch=True)
    PREPARATION_POLICY = auto()    # 准备期内 R/W/drain 都不能发 (preparation 阻塞)
    DRAIN_POLICY = auto()          # drain 路径也无 eligible (防御性, 通常与其它合并)
    ROW_MODE_VISIBILITY = auto()  # 对向 CAM 有活, 但目标 bank 全 IDLE, RowScheduler 按 mode 通道化看不到

    # 多约束共同决定
    MIXED_TIMING_BLOCK = auto()  # 多约束 ready_cycle 接近 (±1), 选不出唯一主因

    UNKNOWN = auto()              # 兜底, 当前不应出现


class PolicyStallReason(Enum):
    """Batch 调度策略层面的阻塞子原因 (10 种).

    与 StallReason.MODE_POLICY / PREPARATION_POLICY / DRAIN_POLICY / ROW_MODE_VISIBILITY 配合使用,
    由 ColScheduler._last_policy_hold_reason 字符串映射得到.
    """
    NONE = auto()

    BATCH_TIMEOUT_NOT_REACHED = auto()              # 对向已 starving 但未到 batch_timeout_cycles
    BATCH_A2_GUARD = auto()                          # A2 防抖: 同一 batch 内必须先发 1 条 current
    BATCH_PREPARATION_ACTIVE = auto()                # 准备期内每 cycle 都计
    BATCH_TARGET_NOT_READY = auto()                  # 准备期内 target 还没满足 readiness
    BATCH_STUCK_THRESHOLD_NOT_REACHED = auto()       # 卡死 cycle < STUCK_FALLBACK_CYCLES 阈值
    BATCH_STICKINESS = auto()                       # 正常发 current 的路径, 没切换

    ROW_TARGET_NOT_VISIBLE = auto()

    ALTERNATING_SELECTION = auto()

    DRAIN_NOT_DISPATCHABLE = auto()

    UNKNOWN = auto()


# ============================================================
#  Frozen snapshot dataclasses (跨模块传只读状态)
# ============================================================

@dataclass(frozen=True)
class BankSnapshot:
    """单个 bank 的只读快照. 必须由调用方在 bank.tick 之前构造.

    为什么 frozen=True:
        防止 probe 误改任何字段. 一旦构造, 全 cycle 内不可变.
        任何需要修改的场景 (例如更新 last_act_at) 应该建新对象.

    字段分组:
        - 身份: bank_id, bank_group_id, sid_id
        - 状态: state (BankState.name)
        - 时间戳: last_act_at / last_col_at / last_pre_at / refresh_start_cycle /
                 auto_precharge_complete_cycle
        - READ/WRITE 状态: last_col_rw_type (RWType.name), write_timing_satisfied
        - 业务: serving_dispatch_id, cols_dispatched, open_row
        - 标志: precharge_pending, page_hit_chain_active
    """
    bank_id: int
    bank_group_id: int
    sid_id: int
    state: str                   # BankState.name
    last_act_at: int
    last_col_at: int
    last_pre_at: int
    last_col_rw_type: str        # RWType.name
    write_timing_satisfied: bool
    serving_dispatch_id: int
    cols_dispatched: int
    precharge_pending: bool
    page_hit_chain_active: bool
    open_row: int
    refresh_start_cycle: int
    auto_precharge_complete_cycle: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bank_id": self.bank_id,
            "bg_id": self.bank_group_id,
            "sid_id": self.sid_id,
            "state": self.state,
            "last_act_at": self.last_act_at,
            "last_col_at": self.last_col_at,
            "last_pre_at": self.last_pre_at,
            "last_col_rw_type": self.last_col_rw_type,
            "write_timing_satisfied": self.write_timing_satisfied,
            "serving_dispatch_id": self.serving_dispatch_id,
            "cols_dispatched": self.cols_dispatched,
            "precharge_pending": self.precharge_pending,
            "page_hit_chain_active": self.page_hit_chain_active,
            "open_row": self.open_row,
            "refresh_start_cycle": self.refresh_start_cycle,
            "auto_precharge_complete_cycle": self.auto_precharge_complete_cycle,
        }


@dataclass(frozen=True)
class BusSnapshot:
    """Col bus (_ColBusState) 的只读快照."""
    last_dispatch_cycle: int
    last_dispatch_cycle_per_bg: Tuple[int, ...]
    last_dispatch_cycle_per_sid: Tuple[int, ...]
    last_rw_type: str            # RWType.name
    last_bank_group: int
    last_dispatch_sid: int
    num_bank_groups: int
    num_sid: int


@dataclass(frozen=True)
class ResourceSnapshot:
    """准入 / 链路 资源快照. 用于判定 LINK_RESOURCE_BLOCK.

    next_r_admit_cycle / next_w_admit_cycle: 由 _admit_specific_type 维护,
        未到时该 type 被 block.
    available_link_nodes: LinkListManager.available_node_count(),
        0 时 READ burst 申请失败.
    """
    next_r_admit_cycle: int
    next_w_admit_cycle: int
    r_cam_depth: int
    w_cam_depth: int
    r_cam_len: int
    w_cam_len: int
    available_link_nodes: int    # LinkListManager.available_node_count()


@dataclass(frozen=True)
class TimingSnapshot:
    """TimingParameters 的只读快照 (只装本模块需要的 cycles).

    注意: 本快照**不**复制 tRFCab / tRREFD / tFAW 等 refresh 内部 timing,
    因为 stall attribution 只关心**列命令派发**的约束. refresh 决策在
    RefreshScheduler 内部完成, 与本模块无关.
    """
    t_rcdrd_cycles: int
    t_rcdwr_cycles: int
    t_rp_cycles: int
    t_rfc_pb_cycles: int
    t_rtp_cycles: int
    write_ap_cycles: int
    t_ccd_s_cycles: int
    t_ccd_l_cycles: int
    t_ccdr_cycles: int
    t_rtw_cycles: int
    write_to_read_same_bg_cycles: int
    write_to_read_diff_bg_cycles: int


@dataclass(frozen=True)
class CmdSnapshot:
    """ColumnCommand 的只读快照 (最小子集, 用于 probe).

    cmd_ref 保留原 ColumnCommand 对象引用, 便于事后定位 (例如写入
    to_dict() 字段). **不要**通过 cmd_ref 修改原对象, 会破坏 frozen
    语义.
    """
    cmd_ref: Any                 # 保留原对象引用, 方便事后定位
    bank_id: int
    bg_id: int
    sid_id: int
    row_id: int
    col_index: int
    segment_col_index: int
    segment_cmd_count: int
    dispatch_id: int
    transaction_id: int
    segment_id: int
    is_write: bool
    page_key: Tuple[int, int, int, int]


@dataclass(frozen=True)
class CamSnapshot:
    """单个 CAM 的只读快照.

    entries: (CmdSnapshot, next_dispatch_index) 元组列表.
        next_dispatch_index 来自 BurstCommandGroup 字段, 决定本 entry
        当前**可派发**的 cmd 是 commands[next_dispatch_index].

    空 entries 表示 CAM 为空 (NoneType length 0, 不是 None).
    """
    entries: Tuple[Tuple[CmdSnapshot, int], ...]  # (cmd, next_dispatch_index) 列表


@dataclass(frozen=True)
class ColPreDispatchSnapshot:
    """col_scheduler.try_issue() 调用前的完整快照.

    StallAttribution 仅依赖本 snapshot 解释 stall, 不再读 model 内部状态.
    关键不变量: **派发后不能读** bus / bank 状态, 它们已被 col_scheduler
    改写 (_complete_dispatch), 必须用此 pre-dispatch snapshot.

    banks_by_id() 方法返回 {bank_id: BankSnapshot} dict, 方便 probe
    按 cmd.bank_id 查表.
    """
    cycle: int
    banks: Tuple[BankSnapshot, ...]
    bus: BusSnapshot
    timing: TimingSnapshot
    resource: ResourceSnapshot
    read_cam: CamSnapshot
    write_cam: CamSnapshot

    def banks_by_id(self) -> Dict[int, BankSnapshot]:
        return {b.bank_id: b for b in self.banks}


@dataclass(frozen=True)
class SchedulerCycleContext:
    """每周期调度上下文. 由 model.py 在派发后构造.

    包含 4 类信息:
      1. 调度模式 (scheduling_mode / current_batch_type / preparation_*)
      2. 计数器 (batch_dispatch_count / current_stuck_cycles / *_timeout_cycles)
      3. 已发命令 (refresh / row / col cmd 的元数据)
      4. Stall Attribution 诊断字段 (last_policy_hold_reason /
         target_act_hidden_by_mode) — 由 ColScheduler 在决策时设置,
         model.py 透传, 不参与分类逻辑.

    所有字段都通过 model.py 的 _build_cycle_context() 构造, 不需要用户手填.
    """
    cycle: int

    scheduling_mode: str                       # "batch" / "alternating"
    current_batch_type: Optional[str]         # "READ" / "WRITE" / None
    preparation_active: bool
    preparation_target_type: Optional[str]
    batch_dispatch_count: int
    current_stuck_cycles: int
    batch_timeout_cycles: int
    stuck_fallback_cycles: int

    refresh_cmd_issued: bool
    refresh_cmd_name: Optional[str]
    refresh_bank_id: Optional[int]
    force_pre_issued: bool

    row_cmd_issued: bool
    row_cmd_name: Optional[str]
    row_cmd_bank_id: Optional[int]

    col_cmd_issued: bool
    col_cmd_type: Optional[str]
    col_cmd_bank_id: Optional[int]

    switch_occurred: bool
    switch_path: Optional[str]

    # 由 ColScheduler 在决策时设置, 只读诊断用
    last_policy_hold_reason: Optional[str] = None
    target_act_hidden_by_mode: bool = False


# ============================================================
#  结果 dataclasses
# ============================================================

@dataclass(frozen=True)
class ColCheckResult:
    """单条 col cmd 的 eligibility 诊断结果.

    字段分组:
      - 结论: eligible, primary_reason, all_reasons
      - ready cycle: ready_cycle, wait_cycles
        + 各类约束单独的 ready_cycle (bank / order / tccd / tccdr /
          turnaround / resource). order 不可预测 (依赖外部), 设 None.
      - cmd 元信息: bank_id, bg_id, sid_id, dispatch_id, transaction_id,
        segment_col_index, expected_dispatch_id, expected_col_index

    与 ColEligibilityChecker.check() 关系:
        本类**只读**地复现 check() 的判定, 但额外输出 ready_cycle,
        便于主因选择. 在 debug 模式下可与 check() 对账, 两者必须一致.
    """
    eligible: bool
    primary_reason: StallReason
    all_reasons: Tuple[StallReason, ...] = ()

    ready_cycle: Optional[int] = None
    wait_cycles: Optional[int] = None

    bank_ready_cycle: Optional[int] = None
    order_ready_cycle: Optional[int] = None
    tccd_ready_cycle: Optional[int] = None
    tccdr_ready_cycle: Optional[int] = None
    turnaround_ready_cycle: Optional[int] = None
    resource_ready_cycle: Optional[int] = None

    bank_id: Optional[int] = None
    bg_id: Optional[int] = None
    sid_id: Optional[int] = None

    dispatch_id: Optional[int] = None
    transaction_id: Optional[int] = None
    segment_col_index: Optional[int] = None
    expected_dispatch_id: Optional[int] = None
    expected_col_index: Optional[int] = None

    def reasons_str(self) -> str:
        return ",".join(r.name for r in self.all_reasons) if self.all_reasons else ""


@dataclass
class TypeProbeResult:
    """R 或 W 单侧 probe 结果 (由 probe_type 返回).

    字段分组:
      - 统计: cam_entries, unprocessed_entries, candidate_commands, eligible_commands
      - 引用: eligible_command_refs (Tuple of ColumnCommand, 供后续 lookup)
      - 原因: reason_counts (每个 primary_reason 的 cmd 数)
      - 选优: primary_reason, min_ready_cycle, min_wait_cycles,
              nearest_blocked_reason, nearest_blocked_bank_id
      - 维度: distinct_*_banks / bgs / sids (候选 vs 可派的分布)

    注意: min_ready_cycle 选**最接近可派发**的 cmd, 反映"再等多久
    至少能派一条". nearest_blocked_* 反映"近在咫尺但被卡死的主因".
    """
    cmd_type: str                               # "READ" / "WRITE"

    cam_entries: int = 0
    unprocessed_entries: int = 0
    candidate_commands: int = 0
    eligible_commands: int = 0

    eligible_command_refs: Tuple[Any, ...] = ()

    reason_counts: Dict[StallReason, int] = field(default_factory=dict)

    primary_reason: StallReason = StallReason.NONE
    min_ready_cycle: Optional[int] = None
    min_wait_cycles: Optional[int] = None

    nearest_blocked_reason: StallReason = StallReason.NONE
    nearest_blocked_bank_id: Optional[int] = None

    distinct_candidate_banks: int = 0
    distinct_eligible_banks: int = 0
    distinct_candidate_bgs: int = 0
    distinct_eligible_bgs: int = 0
    distinct_candidate_sids: int = 0
    distinct_eligible_sids: int = 0


@dataclass
class DrainProbeResult:
    """in-flight drain probe 结果 (由 probe_drain 返回).

    字段同 TypeProbeResult 的子集, 但定义不同:
      - candidate_commands: bank 已 ACTING/ACT_WAIT 且 serving_dispatch_id
        匹配的 cmd 数. 注意: 这里**不**要求 bank open_row 与 cmd row_id 相同
        (drain 续发, 假设 row 已正确)
      - eligible_commands: candidate 中通过 explain_col_eligibility 的数

    关键不变量: probe_drain **不**对 cmd 做 page_key 检查, 因为
    in-flight drain 续发的 cmd 已经是被 ColScheduler _complete_dispatch
    接受过的, 必然与 bank 当前 row 一致 (serving_dispatch_id 守门).
    """
    candidate_commands: int = 0
    eligible_commands: int = 0
    primary_reason: StallReason = StallReason.NONE
    min_ready_cycle: Optional[int] = None
    min_wait_cycles: Optional[int] = None
    eligible_command_refs: Tuple[Any, ...] = ()
    reason_counts: Dict[StallReason, int] = field(default_factory=dict)


@dataclass
class StallCycleRecord:
    """逐 cycle 记录 (仅 record_cycle_trace=True 时保留).

    字段分组 (与 stall_cycles.csv schema 一一对应):
      - 基础: cycle, scheduling_mode, current_mode, preparation_active
      - 派发: issued_col, issued_type
      - 三侧: read/write/drain 的 candidates / eligible / primary_reason / min_wait
      - 分类: channel_reason (StallReason), policy_reason (PolicyStallReason)
      - 机会: other_mode_could_issue, avoidable_by_switch
      - 上下文: refresh_cmd, row_cmd
      - 切换: switch_occurred, switch_path

    内存占用: 每条 ~400 字节 (含字符串). 10000 cycle ≈ 4 MB.
    可通过 max_trace_records 限制 FIFO 长度.
    """
    cycle: int

    scheduling_mode: str
    current_mode: Optional[str]
    preparation_active: bool

    issued_col: bool
    issued_type: Optional[str]

    read_candidates: int
    read_eligible: int
    read_primary_reason: StallReason
    read_min_wait: Optional[int]

    write_candidates: int
    write_eligible: int
    write_primary_reason: StallReason
    write_min_wait: Optional[int]

    drain_candidates: int
    drain_eligible: int
    drain_primary_reason: StallReason
    drain_min_wait: Optional[int]

    channel_reason: StallReason
    policy_reason: PolicyStallReason

    other_mode_could_issue: bool
    avoidable_by_switch: bool

    refresh_cmd: Optional[str]
    row_cmd: Optional[str]

    switch_occurred: bool
    switch_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle": self.cycle,
            "mode": self.scheduling_mode,
            "current_mode": self.current_mode or "",
            "prep": int(self.preparation_active),
            "issued_col": int(self.issued_col),
            "issued_type": self.issued_type or "",
            "read_candidates": self.read_candidates,
            "read_eligible": self.read_eligible,
            "read_reason": self.read_primary_reason.name,
            "read_min_wait": "" if self.read_min_wait is None else self.read_min_wait,
            "write_candidates": self.write_candidates,
            "write_eligible": self.write_eligible,
            "write_reason": self.write_primary_reason.name,
            "write_min_wait": "" if self.write_min_wait is None else self.write_min_wait,
            "drain_candidates": self.drain_candidates,
            "drain_eligible": self.drain_eligible,
            "drain_reason": self.drain_primary_reason.name,
            "drain_min_wait": "" if self.drain_min_wait is None else self.drain_min_wait,
            "channel_reason": self.channel_reason.name,
            "policy_reason": self.policy_reason.name,
            "other_mode_could_issue": int(self.other_mode_could_issue),
            "avoidable_by_switch": int(self.avoidable_by_switch),
            "refresh_cmd": self.refresh_cmd or "",
            "row_cmd": self.row_cmd or "",
            "switch_occurred": int(self.switch_occurred),
            "switch_path": self.switch_path or "",
        }


@dataclass
class StallEpisode:
    """连续 true stall 合并成的 episode.

    episode 规则:
      - 连续 true_stall cycle (非 CAM_EMPTY, 非 issued_col) 合并
      - issued_col 出现时立即关闭 episode
      - mode switch 本身**不**立即结束, 除非下一 cycle 成功派发
      - main_reason: episode 内 cycle 数最多的 StallReason
      - 同票时保留上一个 (避免 main_reason 在 episode 中段跳动)
      - 关闭后 push 到 _episodes, started_cycle 后续不再修改

    ended_by 取值:
      COLUMN_ISSUED: 下一 cycle 派发成功
      CAM_DRAINED:   下一 cycle CAM 全空
      REFRESH_RELEASED: refresh 路径释放了 bank
      SIMULATION_END: 仿真结束, 走 _finalize_episode()
      UNKNOWN:       兜底
    """
    start_cycle: int
    end_cycle: int
    duration: int
    main_reason: StallReason
    reason_counts: Dict[StallReason, int]
    scheduling_mode: str
    starting_mode: Optional[str]
    ending_mode: Optional[str]
    other_mode_ready_cycles: int
    max_other_eligible: int
    preparation_cycles: int
    refresh_interference_cycles: int
    ended_by: str                               # COLUMN_ISSUED / MODE_SWITCH / CAM_DRAINED / SIMULATION_END / REFRESH_RELEASED / UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_cycle": self.start_cycle,
            "end_cycle": self.end_cycle,
            "duration": self.duration,
            "main_reason": self.main_reason.name,
            "reason_counts": ";".join(f"{k.name}:{v}" for k, v in sorted(self.reason_counts.items(), key=lambda x: -x[1])),
            "scheduling_mode": self.scheduling_mode,
            "starting_mode": self.starting_mode or "",
            "ending_mode": self.ending_mode or "",
            "other_mode_ready_cycles": self.other_mode_ready_cycles,
            "max_other_eligible": self.max_other_eligible,
            "preparation_cycles": self.preparation_cycles,
            "refresh_interference_cycles": self.refresh_interference_cycles,
            "ended_by": self.ended_by,
        }


@dataclass
class SwitchEffectRecord:
    """每次 Batch 切换的 pre/post window 分析.

    字段分组:
      - 基础: switch_cycle, path, from_type, to_type, prep_exit_reason
      - pre-window (switch 前 16 cycle):
        * pre_window_issue_count / pre_window_stall_count
        * pre_window_mode_policy_stall_count (其中 mode policy 类的)
      - 切换瞬间: target_eligible_at_switch, source_eligible_at_switch
      - cold start: first_target_issue_cycle, switch_cold_start_cycles
        (首条 target 派发 cycle - 切换 cycle)
      - post-window (switch 后 8/16/32 cycle):
        * post_issue_counts / post_stall_counts (issue/stall 数)
        * post_turnaround_stalls (RTW/WTR 子分类)
        * post_bank_not_ready_stalls (BANK_*_WAIT/TRCD 子分类)
        * post_mode_policy_stalls (policy 子分类)

    _pending_switch_windows 维护: 切换时 push 一个新 record, 每个后续
    cycle 对所有未关闭 record 累计 post_* 计数, 直到 max(8,16,32) window
    全部耗尽才 append 到 _switch_records.
    """
    switch_cycle: int
    path: str
    from_type: str
    to_type: str
    prep_exit_reason: Optional[str]

    pre_window_issue_count: int
    pre_window_stall_count: int
    pre_window_mode_policy_stall_count: int

    target_eligible_at_switch: int
    source_eligible_at_switch: int

    first_target_issue_cycle: Optional[int]
    switch_cold_start_cycles: Optional[int]

    post_issue_counts: Dict[int, int] = field(default_factory=dict)
    post_stall_counts: Dict[int, int] = field(default_factory=dict)
    post_turnaround_stalls: Dict[int, int] = field(default_factory=dict)
    post_bank_not_ready_stalls: Dict[int, int] = field(default_factory=dict)
    post_mode_policy_stalls: Dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "switch_cycle": self.switch_cycle,
            "path": self.path,
            "from_type": self.from_type,
            "to_type": self.to_type,
            "prep_exit_reason": self.prep_exit_reason or "",
            "pre_window_issue_count": self.pre_window_issue_count,
            "pre_window_stall_count": self.pre_window_stall_count,
            "pre_window_mode_policy_stall_count": self.pre_window_mode_policy_stall_count,
            "target_eligible_at_switch": self.target_eligible_at_switch,
            "source_eligible_at_switch": self.source_eligible_at_switch,
            "first_target_issue_cycle": "" if self.first_target_issue_cycle is None else self.first_target_issue_cycle,
            "switch_cold_start_cycles": "" if self.switch_cold_start_cycles is None else self.switch_cold_start_cycles,
        }
        for w in sorted(self.post_issue_counts.keys()):
            d[f"post_issue_w{w}"] = self.post_issue_counts.get(w, 0)
            d[f"post_stall_w{w}"] = self.post_stall_counts.get(w, 0)
            d[f"post_ta_w{w}"] = self.post_turnaround_stalls.get(w, 0)
            d[f"post_bnr_w{w}"] = self.post_bank_not_ready_stalls.get(w, 0)
            d[f"post_mp_w{w}"] = self.post_mode_policy_stalls.get(w, 0)
        return d


# ============================================================
#  Config
# ============================================================

@dataclass
class StallAttributionConfig:
    """StallAttribution 配置项.

    关键字段:
      enabled: 总开关. False 时 observe_cycle / write_outputs 全部短路.
      record_cycle_trace: 是否保留每 cycle 详细记录 (StallCycleRecord).
        False 时不构造 record 对象, 只更新聚合 Counter, 节省内存.
      record_command_rejects: 是否记录每条 cmd 的 reject 信息. 暂未实现
        per-cmd log, 保留接口.
      summary_output_path: stall_summary.json 路径. None 不写.
      cycle_trace_output_path: stall_cycles.csv 路径. None 不写.
      episode_output_path: stall_episodes.csv 路径. None 不写.
      switch_effect_output_path: stall_switch_effects.csv 路径. None 不写.
      switch_pre_window: 切换前 16 cycle 内的 issue/stall 统计窗口.
      switch_post_windows: 切换后 8/16/32 cycle 的 issue/stall 统计窗口.
      max_trace_records: StallCycleRecord 列表最大长度 (FIFO). None 无限.
      assert_consistency: True 时在 probe 后 assert 与原 check() 一致.
        仅 debug 用, 生产环境保持 False.
    """
    enabled: bool = False

    record_cycle_trace: bool = False
    record_command_rejects: bool = False
    record_episodes: bool = True
    record_switch_effects: bool = True

    summary_output_path: Optional[str] = None
    cycle_trace_output_path: Optional[str] = None
    episode_output_path: Optional[str] = None
    switch_effect_output_path: Optional[str] = None

    switch_pre_window: int = 16
    switch_post_windows: Tuple[int, ...] = (8, 16, 32)

    max_trace_records: Optional[int] = None

    # 调试用: 与原 ColEligibilityChecker.check() 强制一致
    assert_consistency: bool = False


# ============================================================
#  纯函数: explain_col_eligibility / probe_type / probe_drain
# ============================================================

# StallReason 优先顺序 (用于主因 fallback)
_REASON_PRIORITY = [
    StallReason.LINK_RESOURCE_BLOCK,
    StallReason.WRONG_DISPATCH_ID,
    StallReason.WRONG_COL_INDEX,
    StallReason.BANK_REFRESHING,
    StallReason.BANK_AUTO_PRE_WAIT,
    StallReason.BANK_PRE_WAIT,
    StallReason.BANK_ACT_WAIT,
    StallReason.BANK_IDLE_WAIT_ACT,
    StallReason.ROW_MISMATCH,
    StallReason.TRCD_WR,
    StallReason.TRCD_RD,
    StallReason.TCCDR,
    StallReason.TCCD_L,
    StallReason.TCCD_S,
    StallReason.RTW,
    StallReason.WTR_L,
    StallReason.WTR_S,
    StallReason.REFRESH_INTERFERENCE,
]


def _pick_primary_reason(reasons_with_ready: Dict[StallReason, int],
                         current_cycle: int) -> StallReason:
    """从 all_reasons 中选 primary. 优先选决定 max(ready_cycle) 的约束.

    选择算法:
      1. 优先: 选 ready_cycle 最大的 (决定 effective_ready_cycle 的)
      2. 同 ready (max 唯一): 直接返回
      3. 同票 (max 有多个): 按 _REASON_PRIORITY 优先级排序, 选最前者.
         优先级 (高→低):
           LINK_RESOURCE_BLOCK > WRONG_DISPATCH_ID > WRONG_COL_INDEX
           > BANK_REFRESHING > BANK_AUTO_PRE_WAIT > BANK_PRE_WAIT
           > BANK_ACT_WAIT > BANK_IDLE_WAIT_ACT > ROW_MISMATCH
           > TRCD_WR > TRCD_RD > TCCDR > TCCD_L > TCCD_S
           > RTW > WTR_L > WTR_S > REFRESH_INTERFERENCE

    为什么按这个顺序: 资源/顺序类是最"绝对"的阻塞 (无法靠时间自动解决),
    bank 状态次之 (auto-precharge/tRP 等待, 但持续时间短),
    timing 类 (tRCD/tCCD) 是常见但非永久阻塞, 放最后.

    返回值: 选出的 StallReason; 若 reasons_with_ready 为空, 返回 NONE.
    """
    if not reasons_with_ready:
        return StallReason.NONE
    # 1) 选 ready cycle 最大的 (决定 effective_ready)
    max_ready = max(reasons_with_ready.values())
    candidates = [r for r, v in reasons_with_ready.items() if v == max_ready]
    if len(candidates) == 1:
        return candidates[0]
    # 2) 多约束同 ready: 按 _REASON_PRIORITY 选最前者
    for r in _REASON_PRIORITY:
        if r in candidates:
            return r
    return candidates[0]


def explain_col_eligibility(
    *,
    cmd: CmdSnapshot,
    bank: BankSnapshot,
    bus: BusSnapshot,
    timing: TimingSnapshot,
    current_cycle: int,
    resource: Optional[ResourceSnapshot] = None,
) -> ColCheckResult:
    """诊断单条 col cmd 的派发合法性. 纯函数, 无副作用.

    与 ColEligibilityChecker.check() 语义完全一致, 但**不读**任何 model 内部
    状态, 只读 snapshot. 返回的 ColCheckResult.eligible 必须与 check() 一致.

    判定顺序 (与原 ColEligibilityChecker 一致):
      1. bank 状态 + tRCD
         - IDLE / PRE_WAIT / AUTO_PRE_WAIT / REFRESHING → 拒绝
         - ACT_WAIT: 需 tRCDRD (READ) / tRCDWR (WRITE)
         - ACTING: 同上
         - ready_cycle = bank.last_act_at + tRCD
      2. dispatch_id / segment_col_index
         - 不匹配 → 拒绝, 顺序 ready 不可预测, 记 None
      3. tCCD-S / tCCD-L / tCCDR
         - 跨 SID READ 走 tCCDR (HBM3 inter-SID)
         - 其它 (同 SID R/W 或同 bg col) 走 tCCDL (per-bg 3 cycles)
         - 任意 col 最小间隔 tCCDS (1 cycle)
      4. R↔W turnaround
         - R→W: tRTW
         - W→R: WL + 2 + tWTR (same/diff bg 不同)
      5. resource (仅当传入)
         - READ: next_r_admit_cycle / available_link_nodes
         - WRITE: next_w_admit_cycle

    关键: 收集所有约束的 ready_cycle, effective_ready = max(ready).
    primary_reason 由 _pick_primary_reason 选出 (决定 effective_ready 的).
    """
    reasons: List[StallReason] = []
    ready_cycles: Dict[StallReason, int] = {}

    is_write = cmd.is_write
    rw_type = "WRITE" if is_write else "READ"

    # ===== 1. bank 状态 + tRCD =====
    bank_ready_cycle = current_cycle
    if bank.state == "IDLE":
        reasons.append(StallReason.BANK_IDLE_WAIT_ACT)
        # 估计: 需 ACT, ready_cycle 不可预测, 用 current_cycle 占位
        bank_ready_cycle = current_cycle + 1   # 占位
    elif bank.state == "ACT_WAIT":
        # 还没到 tRCD: 需等 tRCDRD (READ) 或 tRCDWR (WRITE)
        required = timing.t_rcdwr_cycles if is_write else timing.t_rcdrd_cycles
        if current_cycle < bank.last_act_at + required:
            reasons.append(StallReason.TRCD_WR if is_write else StallReason.TRCD_RD)
            bank_ready_cycle = bank.last_act_at + required
            # ACT_WAIT 本身也算一种状态阻塞 (degraded 原因)
            if StallReason.BANK_ACT_WAIT not in reasons:
                reasons.append(StallReason.BANK_ACT_WAIT)
        else:
            bank_ready_cycle = current_cycle
    elif bank.state == "ACTING":
        required = timing.t_rcdwr_cycles if is_write else timing.t_rcdrd_cycles
        if current_cycle < bank.last_act_at + required:
            reasons.append(StallReason.TRCD_WR if is_write else StallReason.TRCD_RD)
            bank_ready_cycle = bank.last_act_at + required
        else:
            bank_ready_cycle = current_cycle
    elif bank.state == "PRE_WAIT":
        reasons.append(StallReason.BANK_PRE_WAIT)
        bank_ready_cycle = bank.last_pre_at + timing.t_rp_cycles
    elif bank.state == "AUTO_PRE_WAIT":
        reasons.append(StallReason.BANK_AUTO_PRE_WAIT)
        bank_ready_cycle = bank.auto_precharge_complete_cycle
    elif bank.state == "REFRESHING":
        reasons.append(StallReason.BANK_REFRESHING)
        bank_ready_cycle = bank.refresh_start_cycle + timing.t_rfc_pb_cycles
    else:
        bank_ready_cycle = current_cycle

    ready_cycles[StallReason.BANK_IDLE_WAIT_ACT] = bank_ready_cycle
    ready_cycles[StallReason.BANK_ACT_WAIT] = bank_ready_cycle
    ready_cycles[StallReason.BANK_PRE_WAIT] = bank_ready_cycle
    ready_cycles[StallReason.BANK_AUTO_PRE_WAIT] = bank_ready_cycle
    ready_cycles[StallReason.BANK_REFRESHING] = bank_ready_cycle
    ready_cycles[StallReason.TRCD_RD] = bank_ready_cycle
    ready_cycles[StallReason.TRCD_WR] = bank_ready_cycle

    # ===== 2. dispatch_id / segment_col_index =====
    if cmd.dispatch_id != bank.serving_dispatch_id:
        reasons.append(StallReason.WRONG_DISPATCH_ID)
    if cmd.segment_col_index != bank.cols_dispatched:
        reasons.append(StallReason.WRONG_COL_INDEX)
    # 顺序类无 ready_cycle: 不可预测
    order_ready_cycle = None

    # ===== 3. tCCD =====
    tccd_s_ready = bus.last_dispatch_cycle + timing.t_ccd_s_cycles
    tccd_l_ready = bus.last_dispatch_cycle_per_bg[cmd.bg_id] + timing.t_ccd_l_cycles
    if current_cycle < tccd_s_ready:
        reasons.append(StallReason.TCCD_S)
    if current_cycle < tccd_l_ready:
        reasons.append(StallReason.TCCD_L)
    tccdr_ready_cycle: Optional[int] = None
    tccdr_block = False
    if (not is_write
            and bus.last_dispatch_sid >= 0
            and cmd.sid_id != bus.last_dispatch_sid
            and current_cycle < bus.last_dispatch_cycle + timing.t_ccdr_cycles):
        reasons.append(StallReason.TCCDR)
        tccdr_ready_cycle = bus.last_dispatch_cycle + timing.t_ccdr_cycles
        tccdr_block = True

    # ===== 4. turnaround =====
    turnaround_ready_cycle = current_cycle
    turnaround_blocked = False
    if bus.last_rw_type not in ("NONE", rw_type):
        if rw_type == "WRITE":   # R -> W: tRTW
            ta_ready = bus.last_dispatch_cycle + timing.t_rtw_cycles
            if current_cycle < ta_ready:
                reasons.append(StallReason.RTW)
                turnaround_ready_cycle = ta_ready
                turnaround_blocked = True
        else:                    # W -> R: WL+2+tWTR same/diff bg
            same_bg = (cmd.bg_id == bus.last_bank_group)
            if same_bg:
                ta_ready = bus.last_dispatch_cycle + timing.write_to_read_same_bg_cycles
                if current_cycle < ta_ready:
                    reasons.append(StallReason.WTR_L)
                    turnaround_ready_cycle = ta_ready
                    turnaround_blocked = True
            else:
                ta_ready = bus.last_dispatch_cycle + timing.write_to_read_diff_bg_cycles
                if current_cycle < ta_ready:
                    reasons.append(StallReason.WTR_S)
                    turnaround_ready_cycle = ta_ready
                    turnaround_blocked = True
    # 收集各 timing 类 ready_cycle (供 primary 选择)
    if StallReason.TCCD_S in reasons:
        ready_cycles[StallReason.TCCD_S] = tccd_s_ready
    if StallReason.TCCD_L in reasons:
        ready_cycles[StallReason.TCCD_L] = tccd_l_ready
    if tccdr_block:
        ready_cycles[StallReason.TCCDR] = tccdr_ready_cycle   # type: ignore
    if turnaround_blocked:
        if StallReason.RTW in reasons:
            ready_cycles[StallReason.RTW] = turnaround_ready_cycle
        if StallReason.WTR_L in reasons:
            ready_cycles[StallReason.WTR_L] = turnaround_ready_cycle
        if StallReason.WTR_S in reasons:
            ready_cycles[StallReason.WTR_S] = turnaround_ready_cycle

    # ===== 5. resource (仅在传入 resource 时判定) =====
    resource_ready_cycle: Optional[int] = None
    if resource is not None:
        # READ: 准入节流 + link 节点
        if not is_write:
            if current_cycle < resource.next_r_admit_cycle:
                reasons.append(StallReason.LINK_RESOURCE_BLOCK)
                resource_ready_cycle = resource.next_r_admit_cycle
            elif resource.available_link_nodes <= 0:
                reasons.append(StallReason.LINK_NODE_EMPTY)
                resource_ready_cycle = current_cycle + 1
        else:
            if current_cycle < resource.next_w_admit_cycle:
                reasons.append(StallReason.LINK_RESOURCE_BLOCK)
                resource_ready_cycle = resource.next_w_admit_cycle
        if resource_ready_cycle is not None:
            ready_cycles[StallReason.LINK_RESOURCE_BLOCK] = resource_ready_cycle

    # ===== 汇总 =====
    eligible = len(reasons) == 0
    if eligible:
        return ColCheckResult(
            eligible=True,
            primary_reason=StallReason.NONE,
            all_reasons=(),
            ready_cycle=current_cycle,
            wait_cycles=0,
            bank_id=cmd.bank_id, bg_id=cmd.bg_id, sid_id=cmd.sid_id,
            dispatch_id=cmd.dispatch_id, transaction_id=cmd.transaction_id,
            segment_col_index=cmd.segment_col_index,
            expected_dispatch_id=bank.serving_dispatch_id,
            expected_col_index=bank.cols_dispatched,
        )

    # 计算 effective_ready
    finite_ready = [v for v in ready_cycles.values() if v is not None]
    if finite_ready:
        effective_ready = max(finite_ready)
    else:
        effective_ready = None
    wait_cycles = (effective_ready - current_cycle) if effective_ready is not None else None

    primary = _pick_primary_reason(ready_cycles, current_cycle)

    return ColCheckResult(
        eligible=False,
        primary_reason=primary,
        all_reasons=tuple(reasons),
        ready_cycle=effective_ready,
        wait_cycles=wait_cycles,
        bank_ready_cycle=bank_ready_cycle,
        order_ready_cycle=order_ready_cycle,
        tccd_ready_cycle=tccd_l_ready if StallReason.TCCD_L in reasons else (
            tccd_s_ready if StallReason.TCCD_S in reasons else current_cycle),
        tccdr_ready_cycle=tccdr_ready_cycle,
        turnaround_ready_cycle=turnaround_ready_cycle if turnaround_blocked else None,
        resource_ready_cycle=resource_ready_cycle,
        bank_id=cmd.bank_id, bg_id=cmd.bg_id, sid_id=cmd.sid_id,
        dispatch_id=cmd.dispatch_id, transaction_id=cmd.transaction_id,
        segment_col_index=cmd.segment_col_index,
        expected_dispatch_id=bank.serving_dispatch_id,
        expected_col_index=bank.cols_dispatched,
    )


def _build_cmd_snapshot(cmd: Any) -> CmdSnapshot:
    """从 ColumnCommand 对象构造只读 CmdSnapshot. 不修改 cmd 任何字段.

    cmd_ref 字段保留原对象引用, 便于事后定位 (例如日志输出 cmd.bank_id
    等). 调用方**不要**通过 cmd_ref 改原对象, 否则破坏 frozen 语义.

    字段映射:
        bank_id  ← cmd.bank_id
        bg_id    ← cmd.bank_group_id
        sid_id   ← cmd.sid_id
        row_id   ← cmd.row_id
        col_index / segment_col_index / segment_cmd_count ← cmd.*_index/_count
        dispatch_id / transaction_id / segment_id ← cmd.*
        is_write ← bool(cmd.is_write)
        page_key ← tuple(cmd.page_key)  # (SID, BG, BA, ROW)
    """
    return CmdSnapshot(
        cmd_ref=cmd,
        bank_id=cmd.bank_id,
        bg_id=cmd.bank_group_id,
        sid_id=cmd.sid_id,
        row_id=cmd.row_id,
        col_index=cmd.col_index,
        segment_col_index=cmd.segment_col_index,
        segment_cmd_count=cmd.segment_cmd_count,
        dispatch_id=cmd.dispatch_id,
        transaction_id=cmd.transaction_id,
        segment_id=cmd.segment_id,
        is_write=bool(cmd.is_write),
        page_key=tuple(cmd.page_key),
    )


def probe_type(
    *,
    cmd_type: str,                                # "READ" / "WRITE"
    cam: CamSnapshot,
    banks_by_id: Dict[int, BankSnapshot],
    bus: BusSnapshot,
    timing: TimingSnapshot,
    resource: ResourceSnapshot,
    current_cycle: int,
) -> TypeProbeResult:
    """R 或 W 单侧 probe. 纯函数, 不修改任何状态.

    步骤:
      1. 遍历 cam.entries, 过滤 cmd.is_write 匹配 cmd_type
      2. 累加 cam_entries / unprocessed_entries / candidate_commands
      3. 对每个 candidate 调 explain_col_eligibility
      4. 收集 eligible_command_refs, 统计 reason_counts
      5. 跟踪 min_ready_cycle (最接近可派的 cmd) + nearest_blocked_*

    返回 TypeProbeResult, 含候选/可派/原因分布等多维度统计.
    probe_type 不会触碰任何 model 状态, 可在 observe_cycle 之前任意调用.
    """
    is_write = (cmd_type == "WRITE")
    candidates: List[CmdSnapshot] = []
    eligible_refs: List[Any] = []
    reason_counts: Counter = Counter()
    min_ready: Optional[int] = None
    nearest_blocked_reason = StallReason.NONE
    nearest_blocked_bank: Optional[int] = None
    distinct_cand_banks: set = set()
    distinct_elig_banks: set = set()
    distinct_cand_bgs: set = set()
    distinct_elig_bgs: set = set()
    distinct_cand_sids: set = set()
    distinct_elig_sids: set = set()
    unprocessed = 0
    cam_entries = 0

    for entry in cam.entries:
        cam_entries += 1
        cmd_snap, next_idx = entry
        if next_idx >= cmd_snap.segment_cmd_count:
            continue
        unprocessed += 1
        if cmd_snap.is_write != is_write:
            continue
        candidates.append(cmd_snap)
        distinct_cand_banks.add(cmd_snap.bank_id)
        distinct_cand_bgs.add(cmd_snap.bg_id)
        distinct_cand_sids.add(cmd_snap.sid_id)
        bank = banks_by_id.get(cmd_snap.bank_id)
        if bank is None:
            continue
        result = explain_col_eligibility(
            cmd=cmd_snap, bank=bank, bus=bus, timing=timing,
            current_cycle=current_cycle, resource=resource)
        if result.eligible:
            eligible_refs.append(cmd_snap.cmd_ref)
            distinct_elig_banks.add(cmd_snap.bank_id)
            distinct_elig_bgs.add(cmd_snap.bg_id)
            distinct_elig_sids.add(cmd_snap.sid_id)
        else:
            reason_counts[result.primary_reason] += 1
            if result.ready_cycle is not None:
                if min_ready is None or result.ready_cycle < min_ready:
                    min_ready = result.ready_cycle
                    nearest_blocked_reason = result.primary_reason
                    nearest_blocked_bank = cmd_snap.bank_id

    min_wait = (min_ready - current_cycle) if min_ready is not None else None

    return TypeProbeResult(
        cmd_type=cmd_type,
        cam_entries=cam_entries,
        unprocessed_entries=unprocessed,
        candidate_commands=len(candidates),
        eligible_commands=len(eligible_refs),
        eligible_command_refs=tuple(eligible_refs),
        reason_counts=dict(reason_counts),
        primary_reason=(StallReason.NONE if eligible_refs else nearest_blocked_reason),
        min_ready_cycle=min_ready,
        min_wait_cycles=min_wait,
        nearest_blocked_reason=nearest_blocked_reason,
        nearest_blocked_bank_id=nearest_blocked_bank,
        distinct_candidate_banks=len(distinct_cand_banks),
        distinct_eligible_banks=len(distinct_elig_banks),
        distinct_candidate_bgs=len(distinct_cand_bgs),
        distinct_eligible_bgs=len(distinct_elig_bgs),
        distinct_candidate_sids=len(distinct_cand_sids),
        distinct_eligible_sids=len(distinct_elig_sids),
    )


def probe_drain(
    *,
    read_cam: CamSnapshot,
    write_cam: CamSnapshot,
    banks_by_id: Dict[int, BankSnapshot],
    bus: BusSnapshot,
    timing: TimingSnapshot,
    current_cycle: int,
) -> DrainProbeResult:
    """in-flight drain probe. 纯函数, 只把 bank 已打开且 serving_dispatch_id 匹配的 cmd 当候选.

    步骤:
      1. 遍历 R + W 两个 cam.entries
      2. 过滤条件: bank.state in (ACTING, ACT_WAIT)
                    AND bank.serving_dispatch_id == cmd.dispatch_id
      3. 调 explain_col_eligibility 判定
      4. 收集 eligible_command_refs

    关键不变量: probe_drain **不**检查 bank.open_row vs cmd.row_id
    (drain 续发的 cmd 已经被 ColScheduler _complete_dispatch 接受过,
    必然与 bank 当前 row 一致).

    用于 classify_cycle 判断: 如果 probe_drain.eligible > 0 但 probe_type
    都没 eligible, 则该 cycle 不是真 stall (drain 能发).
    """
    candidates = 0
    eligible_refs: List[Any] = []
    reason_counts: Counter = Counter()
    min_ready: Optional[int] = None
    nearest_blocked_reason = StallReason.NONE

    for cam in (read_cam, write_cam):
        for entry in cam.entries:
            cmd_snap, next_idx = entry
            if next_idx >= cmd_snap.segment_cmd_count:
                continue
            bank = banks_by_id.get(cmd_snap.bank_id)
            if bank is None:
                continue
            # drain 候选定义: bank 已打开 (ACTING/ACT_WAIT) 且 serving_dispatch_id 匹配
            if bank.state not in ("ACTING", "ACT_WAIT"):
                continue
            if bank.serving_dispatch_id != cmd_snap.dispatch_id:
                continue
            candidates += 1
            result = explain_col_eligibility(
                cmd=cmd_snap, bank=bank, bus=bus, timing=timing,
                current_cycle=current_cycle, resource=None)
            if result.eligible:
                eligible_refs.append(cmd_snap.cmd_ref)
            else:
                reason_counts[result.primary_reason] += 1
                if result.ready_cycle is not None:
                    if min_ready is None or result.ready_cycle < min_ready:
                        min_ready = result.ready_cycle
                        nearest_blocked_reason = result.primary_reason

    min_wait = (min_ready - current_cycle) if min_ready is not None else None

    return DrainProbeResult(
        candidate_commands=candidates,
        eligible_commands=len(eligible_refs),
        primary_reason=(StallReason.NONE if eligible_refs else nearest_blocked_reason),
        min_ready_cycle=min_ready,
        min_wait_cycles=min_wait,
        eligible_command_refs=tuple(eligible_refs),
    )


# ============================================================
#  classify_cycle: 5 条规则
# ============================================================

def _policy_reason_from_str(s: Optional[str]) -> PolicyStallReason:
    """把 ColScheduler._last_policy_hold_reason 字符串映射到 PolicyStallReason.

    字符串定义在 model.py ColScheduler._try_issue_batch 各分支末尾:
        BATCH_TIMEOUT_NOT_REACHED / BATCH_A2_GUARD / BATCH_PREPARATION_ACTIVE
        / BATCH_TARGET_NOT_READY / BATCH_STUCK_THRESHOLD_NOT_REACHED
        / BATCH_STICKINESS / ALTERNATING_SELECTION / DRAIN_NOT_DISPATCHABLE
        / ROW_TARGET_NOT_VISIBLE
    未知字符串返回 PolicyStallReason.UNKNOWN.
    空字符串/None 返回 PolicyStallReason.NONE.
    """
    if not s:
        return PolicyStallReason.NONE
    m = {
        "BATCH_TIMEOUT_NOT_REACHED": PolicyStallReason.BATCH_TIMEOUT_NOT_REACHED,
        "BATCH_A2_GUARD": PolicyStallReason.BATCH_A2_GUARD,
        "BATCH_PREPARATION_ACTIVE": PolicyStallReason.BATCH_PREPARATION_ACTIVE,
        "BATCH_TARGET_NOT_READY": PolicyStallReason.BATCH_TARGET_NOT_READY,
        "BATCH_STUCK_THRESHOLD_NOT_REACHED": PolicyStallReason.BATCH_STUCK_THRESHOLD_NOT_REACHED,
        "BATCH_STICKINESS": PolicyStallReason.BATCH_STICKINESS,
        "ALTERNATING_SELECTION": PolicyStallReason.ALTERNATING_SELECTION,
        "DRAIN_NOT_DISPATCHABLE": PolicyStallReason.DRAIN_NOT_DISPATCHABLE,
        "ROW_TARGET_NOT_VISIBLE": PolicyStallReason.ROW_TARGET_NOT_VISIBLE,
    }
    return m.get(s, PolicyStallReason.UNKNOWN)


def classify_cycle(
    *,
    context: SchedulerCycleContext,
    read_probe: TypeProbeResult,
    write_probe: TypeProbeResult,
    drain_probe: DrainProbeResult,
) -> StallCycleRecord:
    """5 条规则分类. 纯函数.

    规则优先级 (从高到低):
      1. issued_col → StallReason.NONE (有 issue, 不计 stall)
      2. R + W + drain 全无 candidate → CAM_EMPTY (no-demand cycle, 不计 true stall)
      3. preparation_active 且 R + W + drain 全无 eligible → PREPARATION_POLICY
      4. current 不能发 AND drain 不能发 AND other 能发 → MODE_POLICY
         (如果 target_act_hidden_by_mode 标记, 升级为 ROW_MODE_VISIBILITY)
      5. 三侧都不能发 → 选 ready_cycle 最近的 blocked command
         (若多个 ready 接近 ±1, 升级为 MIXED_TIMING_BLOCK)
      6. 兜底: 不会到这里

    关键: **current 探测基于 context.current_batch_type**, 不是固定 R.
    Batch READ 模式时 current=read_probe, other=write_probe.
    """
    # 1. 已派发
    if context.col_cmd_issued:
        return StallCycleRecord(
            cycle=context.cycle,
            scheduling_mode=context.scheduling_mode,
            current_mode=context.current_batch_type,
            preparation_active=context.preparation_active,
            issued_col=True,
            issued_type=context.col_cmd_type,
            read_candidates=read_probe.candidate_commands,
            read_eligible=read_probe.eligible_commands,
            read_primary_reason=read_probe.primary_reason,
            read_min_wait=read_probe.min_wait_cycles,
            write_candidates=write_probe.candidate_commands,
            write_eligible=write_probe.eligible_commands,
            write_primary_reason=write_probe.primary_reason,
            write_min_wait=write_probe.min_wait_cycles,
            drain_candidates=drain_probe.candidate_commands,
            drain_eligible=drain_probe.eligible_commands,
            drain_primary_reason=drain_probe.primary_reason,
            drain_min_wait=drain_probe.min_wait_cycles,
            channel_reason=StallReason.NONE,
            policy_reason=PolicyStallReason.NONE,
            other_mode_could_issue=False,
            avoidable_by_switch=False,
            refresh_cmd=context.refresh_cmd_name,
            row_cmd=context.row_cmd_name,
            switch_occurred=context.switch_occurred,
            switch_path=context.switch_path,
        )

    # 2. CAM_EMPTY (两侧 + drain 都没候选)
    if (read_probe.candidate_commands == 0
            and write_probe.candidate_commands == 0
            and drain_probe.candidate_commands == 0):
        return StallCycleRecord(
            cycle=context.cycle,
            scheduling_mode=context.scheduling_mode,
            current_mode=context.current_batch_type,
            preparation_active=context.preparation_active,
            issued_col=False,
            issued_type=None,
            read_candidates=0, read_eligible=0,
            read_primary_reason=StallReason.CAM_EMPTY, read_min_wait=None,
            write_candidates=0, write_eligible=0,
            write_primary_reason=StallReason.CAM_EMPTY, write_min_wait=None,
            drain_candidates=0, drain_eligible=0,
            drain_primary_reason=StallReason.CAM_EMPTY, drain_min_wait=None,
            channel_reason=StallReason.CAM_EMPTY,
            policy_reason=PolicyStallReason.NONE,
            other_mode_could_issue=False,
            avoidable_by_switch=False,
            refresh_cmd=context.refresh_cmd_name,
            row_cmd=context.row_cmd_name,
            switch_occurred=context.switch_occurred,
            switch_path=context.switch_path,
        )

    # 准备期强制视为 MODE_POLICY / PREPARATION_POLICY
    if context.preparation_active:
        # 准备期: 当前 side 已发出的 dispatches 都被计入 prep
        # 若 READ/WRITE/drain 都没 eligible, 归 PREPARATION_POLICY
        if (read_probe.eligible_commands == 0
                and write_probe.eligible_commands == 0
                and drain_probe.eligible_commands == 0):
            other_ready = (read_probe.eligible_commands + write_probe.eligible_commands) > 0
            return StallCycleRecord(
                cycle=context.cycle,
                scheduling_mode=context.scheduling_mode,
                current_mode=context.current_batch_type,
                preparation_active=True,
                issued_col=False, issued_type=None,
                read_candidates=read_probe.candidate_commands,
                read_eligible=read_probe.eligible_commands,
                read_primary_reason=read_probe.primary_reason,
                read_min_wait=read_probe.min_wait_cycles,
                write_candidates=write_probe.candidate_commands,
                write_eligible=write_probe.eligible_commands,
                write_primary_reason=write_probe.primary_reason,
                write_min_wait=write_probe.min_wait_cycles,
                drain_candidates=drain_probe.candidate_commands,
                drain_eligible=drain_probe.eligible_commands,
                drain_primary_reason=drain_probe.primary_reason,
                drain_min_wait=drain_probe.min_wait_cycles,
                channel_reason=StallReason.PREPARATION_POLICY,
                policy_reason=PolicyStallReason.BATCH_PREPARATION_ACTIVE,
                other_mode_could_issue=other_ready,
                avoidable_by_switch=False,
                refresh_cmd=context.refresh_cmd_name,
                row_cmd=context.row_cmd_name,
                switch_occurred=context.switch_occurred,
                switch_path=context.switch_path,
            )

    # 3. 决定 current_type / other_type
    current_type = context.current_batch_type
    if current_type == "READ":
        current_probe = read_probe
        other_probe = write_probe
    elif current_type == "WRITE":
        current_probe = write_probe
        other_probe = read_probe
    else:    # alternating
        current_probe = read_probe
        other_probe = write_probe

    other_mode_could_issue = (other_probe.eligible_commands > 0)
    drain_could_issue = (drain_probe.eligible_commands > 0)
    current_could_issue = (current_probe.eligible_commands > 0)

    # 4. current 不能发 + drain 不能发 + other 能发 → MODE_POLICY
    if (not current_could_issue
            and not drain_could_issue
            and other_mode_could_issue):
        pol = _policy_reason_from_str(context.last_policy_hold_reason)
        # ROW_MODE_VISIBILITY 优先: 即使是策略阻塞, 若对向 bank 被 mode 通道化隐藏, 算 visibility
        if context.target_act_hidden_by_mode and pol == PolicyStallReason.NONE:
            pol = PolicyStallReason.ROW_TARGET_NOT_VISIBLE
            ch = StallReason.ROW_MODE_VISIBILITY
        else:
            ch = StallReason.MODE_POLICY
        return StallCycleRecord(
            cycle=context.cycle,
            scheduling_mode=context.scheduling_mode,
            current_mode=current_type,
            preparation_active=context.preparation_active,
            issued_col=False, issued_type=None,
            read_candidates=read_probe.candidate_commands,
            read_eligible=read_probe.eligible_commands,
            read_primary_reason=read_probe.primary_reason,
            read_min_wait=read_probe.min_wait_cycles,
            write_candidates=write_probe.candidate_commands,
            write_eligible=write_probe.eligible_commands,
            write_primary_reason=write_probe.primary_reason,
            write_min_wait=write_probe.min_wait_cycles,
            drain_candidates=drain_probe.candidate_commands,
            drain_eligible=drain_probe.eligible_commands,
            drain_primary_reason=drain_probe.primary_reason,
            drain_min_wait=drain_probe.min_wait_cycles,
            channel_reason=ch,
            policy_reason=pol,
            other_mode_could_issue=True,
            avoidable_by_switch=True,
            refresh_cmd=context.refresh_cmd_name,
            row_cmd=context.row_cmd_name,
            switch_occurred=context.switch_occurred,
            switch_path=context.switch_path,
        )

    # 5. 三侧都不能发 → 选 ready cycle 最近的 blocked command
    if (not current_could_issue
            and not drain_could_issue
            and not other_mode_could_issue):
        # 收集所有 probe 的 primary reason 与 ready_cycle, 选 ready 最小者
        cands: List[Tuple[int, StallReason, int]] = []   # (ready_cycle, primary_reason, bank_id)
        for p in (read_probe, write_probe, drain_probe):
            if p.min_ready_cycle is not None and p.primary_reason != StallReason.NONE:
                bid = p.nearest_blocked_bank_id or -1
                cands.append((p.min_ready_cycle, p.primary_reason, bid))
        if cands:
            cands.sort()
            chosen_ready, chosen_reason, chosen_bank = cands[0]
            # 若多种 reason 都接近, 用 MIXED_TIMING_BLOCK
            same_window = [c for c in cands if abs(c[0] - chosen_ready) <= 1]
            if len(same_window) > 1:
                ch = StallReason.MIXED_TIMING_BLOCK
            else:
                ch = chosen_reason
        else:
            ch = StallReason.UNKNOWN
        # 准备期抑制
        if context.preparation_active:
            ch = StallReason.PREPARATION_POLICY
        return StallCycleRecord(
            cycle=context.cycle,
            scheduling_mode=context.scheduling_mode,
            current_mode=current_type,
            preparation_active=context.preparation_active,
            issued_col=False, issued_type=None,
            read_candidates=read_probe.candidate_commands,
            read_eligible=read_probe.eligible_commands,
            read_primary_reason=read_probe.primary_reason,
            read_min_wait=read_probe.min_wait_cycles,
            write_candidates=write_probe.candidate_commands,
            write_eligible=write_probe.eligible_commands,
            write_primary_reason=write_probe.primary_reason,
            write_min_wait=write_probe.min_wait_cycles,
            drain_candidates=drain_probe.candidate_commands,
            drain_eligible=drain_probe.eligible_commands,
            drain_primary_reason=drain_probe.primary_reason,
            drain_min_wait=drain_probe.min_wait_cycles,
            channel_reason=ch,
            policy_reason=(_policy_reason_from_str(context.last_policy_hold_reason)
                           if context.preparation_active else PolicyStallReason.NONE),
            other_mode_could_issue=False,
            avoidable_by_switch=False,
            refresh_cmd=context.refresh_cmd_name,
            row_cmd=context.row_cmd_name,
            switch_occurred=context.switch_occurred,
            switch_path=context.switch_path,
        )

    # 6. 兜底: 不应到这
    return StallCycleRecord(
        cycle=context.cycle,
        scheduling_mode=context.scheduling_mode,
        current_mode=current_type,
        preparation_active=context.preparation_active,
        issued_col=False, issued_type=None,
        read_candidates=read_probe.candidate_commands,
        read_eligible=read_probe.eligible_commands,
        read_primary_reason=read_probe.primary_reason,
        read_min_wait=read_probe.min_wait_cycles,
        write_candidates=write_probe.candidate_commands,
        write_eligible=write_probe.eligible_commands,
        write_primary_reason=write_probe.primary_reason,
        write_min_wait=write_probe.min_wait_cycles,
        drain_candidates=drain_probe.candidate_commands,
        drain_eligible=drain_probe.eligible_commands,
        drain_primary_reason=drain_probe.primary_reason,
        drain_min_wait=drain_probe.min_wait_cycles,
        channel_reason=StallReason.UNKNOWN,
        policy_reason=PolicyStallReason.UNKNOWN,
        other_mode_could_issue=other_mode_could_issue,
        avoidable_by_switch=False,
        refresh_cmd=context.refresh_cmd_name,
        row_cmd=context.row_cmd_name,
        switch_occurred=context.switch_occurred,
        switch_path=context.switch_path,
    )


# ============================================================
#  辅助: 百分位
# ============================================================

def _percentile(values: List[int], pct: float) -> float:
    """自实现百分位 (避免 numpy 依赖).

    使用线性插值: k = (n-1) * pct, f = int(k), c = min(f+1, n-1).
    result = sorted[f] + (sorted[c] - sorted[f]) * (k - f)

    示例: percentile([1,2,3,4,5], 0.5) = 3.0; percentile([1,2,3,4,5], 0.9) = 4.6

    Args:
        values: 整数列表 (e.g. episode durations). 允许空.
        pct: [0.0, 1.0] 之间的百分位 (0.5 = 中位数, 0.9 = P90).

    Returns:
        插值后的浮点百分位; 空列表返回 0.0.
    """
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return s[f] + (s[c] - s[f]) * (k - f)


# ============================================================
#  主类: StallAttribution
# ============================================================

class StallAttribution:
    """stall 归因主类. 接受 model.py 通过 observe_cycle 传入的 snapshot + probe.

    内部维护 4 类状态:
      1. 聚合 Counter: stall_cycles_by_reason, policy_stall_cycles_by_reason,
         read/write/drain_block_reason_counts, max_consecutive_stall_cycles
      2. Episode 跟踪: _current_episode (open 中) + _episodes (closed 列表)
      3. Switch 关联: _pending_switch_windows (open 中的 post window) +
         _switch_records (closed 列表) + _pre_window ring buffer (size=16)
      4. cycle trace: _cycle_records 列表 (仅 record_cycle_trace=True 时使用)

    公开方法:
      observe_cycle: 每个 cycle 入口, 必须先调用
      build_summary_dict: 生成完整聚合 dict (供 JSON 序列化)
      format_summary: 生成对齐的人类可读表格
      write_outputs: 仿真结束时调用, 收尾 + 写所有输出文件
      feed_external_switch_entry: 由 model.py 调用, 把 ColScheduler
        _switch_trace 条目喂进来, 用于反推 from_type

    enabled=False 时:
      - observe_cycle 立即 return (零开销)
      - write_outputs 立即 return (不写任何文件)
    """

    def __init__(self, config: StallAttributionConfig) -> None:
        self.config = config
        self.enabled = config.enabled

        # 聚合
        self.elapsed_cycles = 0
        self.column_issue_cycles = 0
        self.read_issue_cycles = 0
        self.write_issue_cycles = 0
        self.no_demand_cycles = 0
        self.true_stall_cycles = 0
        self.stall_cycles_by_reason: Counter = Counter()
        self.policy_stall_cycles_by_reason: Counter = Counter()
        self.avoidable_switch_stall_cycles = 0
        self.other_mode_could_issue_cycles = 0
        self.both_modes_blocked_cycles = 0
        self.wrong_mode_residency_cycles = 0
        self.read_block_reason_counts: Counter = Counter()
        self.write_block_reason_counts: Counter = Counter()
        self.drain_block_reason_counts: Counter = Counter()
        self.read_wait_cycles_by_reason: Counter = Counter()  # 累加 wait
        self.write_wait_cycles_by_reason: Counter = Counter()
        self.max_consecutive_stall_cycles = 0

        # episode 跟踪
        self._current_episode: Optional[StallEpisode] = None
        self._episodes: List[StallEpisode] = []

        # switch 关联
        self._pending_switch_windows: List[Dict[str, Any]] = []   # 待补齐的 post window 缓冲
        self._switch_records: List[SwitchEffectRecord] = []
        # pre_window 历史 ring buffer (cycle, issued_col, channel_reason)
        self._pre_window: List[Tuple[int, bool, StallReason]] = []

        # cycle trace
        self._cycle_records: List[StallCycleRecord] = []

        # 性能统计
        self._t_start = time.perf_counter()
        self.attribution_runtime_seconds = 0.0
        self.attribution_cycles_observed = 0

    # ---- 入口 ----

    def observe_cycle(
        self,
        *,
        context: SchedulerCycleContext,
        read_probe: TypeProbeResult,
        write_probe: TypeProbeResult,
        drain_probe: DrainProbeResult,
    ) -> None:
        """每个 cycle 由 model.py 调用一次. **必须在 col dispatch 之后调用**.

        Args:
            context: SchedulerCycleContext (含 mode / 计数 / refresh / row / col)
            read_probe: probe_type(cmd_type="READ") 的结果
            write_probe: probe_type(cmd_type="WRITE") 的结果
            drain_probe: probe_drain() 的结果

        流程:
          1. enabled=False 立即 return
          2. attribution_cycles_observed += 1; elapsed_cycles += 1
          3. classify_cycle(context, read/write/drain probe) → rec
          4. 聚合: 区分 issue / no_demand / true_stall, 累加各类 Counter
          5. probe reason 聚合 (read/write/drain block reason 分布)
          6. _update_episode (若 enabled)
          7. _update_switch_effects (若 enabled) + 维护 pre_window ring buffer
          8. _cycle_records.append (若 record_cycle_trace=True)

        异常隔离: model.py 侧 try/except 包裹, 任何异常不传播到主仿真.
        """
        if not self.enabled:
            return
        self.attribution_cycles_observed += 1
        self.elapsed_cycles += 1

        # 分类
        rec = classify_cycle(
            context=context,
            read_probe=read_probe,
            write_probe=write_probe,
            drain_probe=drain_probe,
        )

        # 聚合
        if rec.issued_col:
            self.column_issue_cycles += 1
            if rec.issued_type == "READ":
                self.read_issue_cycles += 1
            elif rec.issued_type == "WRITE":
                self.write_issue_cycles += 1
        else:
            if rec.channel_reason == StallReason.CAM_EMPTY:
                self.no_demand_cycles += 1
            else:
                self.true_stall_cycles += 1
                self.stall_cycles_by_reason[rec.channel_reason] += 1
                if rec.policy_reason != PolicyStallReason.NONE:
                    self.policy_stall_cycles_by_reason[rec.policy_reason] += 1
                if rec.avoidable_by_switch:
                    self.avoidable_switch_stall_cycles += 1
                if rec.other_mode_could_issue:
                    self.other_mode_could_issue_cycles += 1
                if (read_probe.eligible_commands == 0
                        and write_probe.eligible_commands == 0
                        and drain_probe.eligible_commands == 0
                        and (read_probe.candidate_commands > 0
                             or write_probe.candidate_commands > 0
                             or drain_probe.candidate_commands > 0)):
                    self.both_modes_blocked_cycles += 1
                # wrong_mode_residency
                if (not rec.issued_col
                        and ((context.current_batch_type == "READ"
                              and read_probe.eligible_commands == 0
                              and write_probe.eligible_commands > 0
                              and drain_probe.eligible_commands == 0)
                             or (context.current_batch_type == "WRITE"
                                 and write_probe.eligible_commands == 0
                                 and read_probe.eligible_commands > 0
                                 and drain_probe.eligible_commands == 0))):
                    self.wrong_mode_residency_cycles += 1

        # probe reason 聚合
        for r, c in read_probe.reason_counts.items():
            self.read_block_reason_counts[r] += c
            if read_probe.min_wait_cycles is not None and r == read_probe.primary_reason:
                self.read_wait_cycles_by_reason[r] += read_probe.min_wait_cycles
        for r, c in write_probe.reason_counts.items():
            self.write_block_reason_counts[r] += c
            if write_probe.min_wait_cycles is not None and r == write_probe.primary_reason:
                self.write_wait_cycles_by_reason[r] += write_probe.min_wait_cycles
        for r, c in drain_probe.reason_counts.items():
            self.drain_block_reason_counts[r] += c

        # episode
        if self.config.record_episodes:
            self._update_episode(rec)

        # switch 关联
        if self.config.record_switch_effects:
            self._update_switch_effects(rec, context, read_probe, write_probe)
            self._pre_window.append((rec.cycle, rec.issued_col, rec.channel_reason))
            if len(self._pre_window) > self.config.switch_pre_window:
                self._pre_window.pop(0)

        # cycle trace
        if self.config.record_cycle_trace:
            self._cycle_records.append(rec)
            if (self.config.max_trace_records is not None
                    and len(self._cycle_records) > self.config.max_trace_records):
                self._cycle_records.pop(0)

    # ---- episode ----

    def _update_episode(self, rec: StallCycleRecord) -> None:
        true_stall = (not rec.issued_col
                      and rec.channel_reason != StallReason.CAM_EMPTY
                      and rec.channel_reason != StallReason.NONE)
        if not true_stall:
            # 关闭 _episodes 末尾的 in-progress episode (如有)
            if self._episodes and self._episodes[-1].ended_by == "OPEN":
                ep = self._episodes[-1]
                ep.end_cycle = rec.cycle - 1
                ep.duration = ep.end_cycle - ep.start_cycle + 1
                ep.ended_by = (
                    "COLUMN_ISSUED" if rec.issued_col else
                    "CAM_DRAINED" if rec.channel_reason == StallReason.CAM_EMPTY else
                    "REFRESH_RELEASED" if rec.refresh_cmd else
                    "UNKNOWN")
                self.max_consecutive_stall_cycles = max(
                    self.max_consecutive_stall_cycles, ep.duration)
            return

        # 末尾 episode 还在 in-progress 且相邻: 续接
        if (self._episodes
                and self._episodes[-1].ended_by == "OPEN"
                and self._episodes[-1].end_cycle == rec.cycle - 1):
            ep = self._episodes[-1]
            ep.end_cycle = rec.cycle
            ep.duration += 1
            ep.ending_mode = rec.current_mode
            rc = ep.reason_counts
            rc[rec.channel_reason] = rc.get(rec.channel_reason, 0) + 1
            if rec.preparation_active:
                ep.preparation_cycles += 1
            if rec.channel_reason == StallReason.REFRESH_INTERFERENCE:
                ep.refresh_interference_cycles += 1
            if rec.other_mode_could_issue:
                ep.other_mode_ready_cycles += 1
            max_count = max(rc.values())
            top = [r for r, v in rc.items() if v == max_count]
            if len(top) == 1:
                ep.main_reason = top[0]
            self.max_consecutive_stall_cycles = max(
                self.max_consecutive_stall_cycles, ep.duration)
        else:
            # 新建 episode, 直接 append 到 _episodes
            ep = StallEpisode(
                start_cycle=rec.cycle,
                end_cycle=rec.cycle,
                duration=1,
                main_reason=rec.channel_reason,
                reason_counts={rec.channel_reason: 1},
                scheduling_mode=rec.scheduling_mode,
                starting_mode=rec.current_mode,
                ending_mode=rec.current_mode,
                other_mode_ready_cycles=0,
                max_other_eligible=0,
                preparation_cycles=0,
                refresh_interference_cycles=0,
                ended_by="OPEN",
            )
            self._episodes.append(ep)
            self.max_consecutive_stall_cycles = max(
                self.max_consecutive_stall_cycles, 1)

    def _finalize_episode(self, reason: str = "SIMULATION_END") -> None:
        if self._current_episode is not None:
            self._current_episode.ended_by = reason
            self._episodes.append(self._current_episode)
            self._current_episode = None

    # ---- switch 关联 ----

    def _update_switch_effects(
        self,
        rec: StallCycleRecord,
        context: SchedulerCycleContext,
        read_probe: TypeProbeResult,
        write_probe: TypeProbeResult,
    ) -> None:
        # 先消化老的 pending switch windows
        new_pending: List[Dict[str, Any]] = []
        for p in self._pending_switch_windows:
            w_left = {w: p["w_left"][w] - 1 for w in p["w_left"]}
            # 累计 post 指标
            w_max = max(p["w_left"].keys())
            for w in p["w_left"]:
                if p["w_left"][w] > 0 and p["w_left"][w] - w_left[w] == 1:
                    # 上一 cycle 刚进入这个 window
                    pass
            # 简化: 每个 cycle 算入所有仍 opened 的 window
            for w in p["w_left"]:
                if w_left[w] >= 0:
                    p["record"].post_issue_counts[w] = p["record"].post_issue_counts.get(w, 0) + (1 if rec.issued_col else 0)
                    p["record"].post_stall_counts[w] = p["record"].post_stall_counts.get(w, 0) + (0 if rec.issued_col else 1)
                    if (not rec.issued_col
                            and rec.channel_reason in (StallReason.RTW,
                                                       StallReason.WTR_L,
                                                       StallReason.WTR_S)):
                        p["record"].post_turnaround_stalls[w] = p["record"].post_turnaround_stalls.get(w, 0) + 1
                    if (not rec.issued_col
                            and rec.channel_reason in (StallReason.BANK_IDLE_WAIT_ACT,
                                                       StallReason.BANK_ACT_WAIT,
                                                       StallReason.BANK_PRE_WAIT,
                                                       StallReason.BANK_AUTO_PRE_WAIT,
                                                       StallReason.BANK_REFRESHING,
                                                       StallReason.TRCD_RD,
                                                       StallReason.TRCD_WR)):
                        p["record"].post_bank_not_ready_stalls[w] = p["record"].post_bank_not_ready_stalls.get(w, 0) + 1
                    if (not rec.issued_col
                            and rec.channel_reason == StallReason.MODE_POLICY):
                        p["record"].post_mode_policy_stalls[w] = p["record"].post_mode_policy_stalls.get(w, 0) + 1
            # first target issue
            if (rec.issued_col
                    and rec.issued_type == p["to_type"]
                    and p["record"].first_target_issue_cycle is None):
                p["record"].first_target_issue_cycle = rec.cycle
                p["record"].switch_cold_start_cycles = rec.cycle - p["record"].switch_cycle
            # 保留未关闭的
            if any(w_left[w] >= 0 for w in w_left):
                p["w_left"] = w_left
                new_pending.append(p)
            else:
                self._switch_records.append(p["record"])
        self._pending_switch_windows = new_pending

        # 新切换
        if context.switch_occurred and context.switch_path:
            # pre window 聚合
            pre_issue = sum(1 for _, ic, _ in self._pre_window if ic)
            pre_stall = sum(1 for _, ic, ch in self._pre_window if not ic and ch not in (StallReason.CAM_EMPTY,))
            pre_mp = sum(1 for _, ic, ch in self._pre_window
                         if not ic and ch == StallReason.MODE_POLICY)
            # 当前 cycle 的 target/source eligible
            to_type = context.current_batch_type  # 切完之后 current_type = target
            # 从 switch_path 反推 from_type: 不直接拿到, 用 _switch_trace 的 from 字段
            from_type = ""
            for entry in getattr(self, "_external_switch_entries", []):
                if entry.get("cycle") == rec.cycle and entry.get("path") == context.switch_path:
                    from_type = entry.get("from", "")
                    break
            if to_type == "READ":
                target_probe = read_probe
            else:
                target_probe = write_probe
            target_eligible = target_probe.eligible_commands
            # source probe: 反向
            if from_type == "READ":
                source_probe = read_probe
            elif from_type == "WRITE":
                source_probe = write_probe
            else:
                source_probe = target_probe
            source_eligible = source_probe.eligible_commands

            rec_obj = SwitchEffectRecord(
                switch_cycle=rec.cycle,
                path=context.switch_path,
                from_type=from_type or "?",
                to_type=to_type or "?",
                prep_exit_reason=(context.last_policy_hold_reason
                                  if context.switch_path == "prep_exit" else None),
                pre_window_issue_count=pre_issue,
                pre_window_stall_count=pre_stall,
                pre_window_mode_policy_stall_count=pre_mp,
                target_eligible_at_switch=target_eligible,
                source_eligible_at_switch=source_eligible,
                first_target_issue_cycle=None,
                switch_cold_start_cycles=None,
            )
            self._pending_switch_windows.append({
                "record": rec_obj,
                "w_left": {w: w for w in self.config.switch_post_windows},
            })

    def feed_external_switch_entry(self, entry: Dict[str, Any]) -> None:
        """由 model.py 在每 cycle 把 ColScheduler 的 switch trace 条目喂进来.
        用于反推 from_type.

        字段格式: dict with keys cycle / path / from / to / ...
        SwitchEffectRecord 需要 from_type 字段, 但 ColScheduler 本身在
        切模式时不记录 from_type (只知道 to_type). 通过把 _switch_trace
        整条喂进来, StallAttribution 自己按 cycle + path 查找 from_type.
        """
        if not self.enabled or not self.config.record_switch_effects:
            return
        if not self.enabled or not self.config.record_switch_effects:
            return
        if not hasattr(self, "_external_switch_entries"):
            self._external_switch_entries = []
        self._external_switch_entries.append(entry)

    def _finalize_pending_switches(self) -> None:
        for p in self._pending_switch_windows:
            self._switch_records.append(p["record"])
        self._pending_switch_windows = []

    # ---- merge (用于 8 case 聚合) ----

    def merge_from(self, other, case_name: str = "") -> None:
        """把另一个 StallAttribution 的所有数据合并到 self (用于 aggregate 模式).

        合并规则:
          - 所有 Counter 累加 (elapsed, issue, stall_cycles_by_reason 等)
          - 列表类扩展 (_episodes / _switch_records / _cycle_records)
          - max_consecutive_stall_cycles 取较大值
          - attribution_runtime_seconds / cycles_observed 累加
          - _current_episode / _pending_switch_windows 不合并 (case 间无连续性)

        Args:
            other: 另一个 case 的 StallAttribution (must be enabled)
            case_name: 来源 case 名 (保留参数, 当前未注入到 record)
        """
        if not self.enabled or not other.enabled:
            return
        # Counter 累加
        self.elapsed_cycles += other.elapsed_cycles
        self.column_issue_cycles += other.column_issue_cycles
        self.read_issue_cycles += other.read_issue_cycles
        self.write_issue_cycles += other.write_issue_cycles
        self.no_demand_cycles += other.no_demand_cycles
        self.true_stall_cycles += other.true_stall_cycles
        for r, c2 in other.stall_cycles_by_reason.items():
            self.stall_cycles_by_reason[r] += c2
        for r, c2 in other.policy_stall_cycles_by_reason.items():
            self.policy_stall_cycles_by_reason[r] += c2
        for r, c2 in other.read_block_reason_counts.items():
            self.read_block_reason_counts[r] += c2
        for r, c2 in other.write_block_reason_counts.items():
            self.write_block_reason_counts[r] += c2
        for r, c2 in other.drain_block_reason_counts.items():
            self.drain_block_reason_counts[r] += c2
        for r, c2 in other.read_wait_cycles_by_reason.items():
            self.read_wait_cycles_by_reason[r] += c2
        for r, c2 in other.write_wait_cycles_by_reason.items():
            self.write_wait_cycles_by_reason[r] += c2
        self.avoidable_switch_stall_cycles += other.avoidable_switch_stall_cycles
        self.other_mode_could_issue_cycles += other.other_mode_could_issue_cycles
        self.both_modes_blocked_cycles += other.both_modes_blocked_cycles
        self.wrong_mode_residency_cycles += other.wrong_mode_residency_cycles
        # 列表扩展
        self._episodes.extend(other._episodes)
        self._switch_records.extend(other._switch_records)
        self._cycle_records.extend(other._cycle_records)
        # max
        if other.max_consecutive_stall_cycles > self.max_consecutive_stall_cycles:
            self.max_consecutive_stall_cycles = other.max_consecutive_stall_cycles
        # runtime
        self.attribution_runtime_seconds += other.attribution_runtime_seconds
        self.attribution_cycles_observed += other.attribution_cycles_observed

    # ---- 汇总 ----

    def build_summary_dict(self) -> Dict[str, Any]:
        """生成完整聚合 dict (供 JSON 序列化). 纯计算, 不写文件.

        返回 dict 顶层 key:
            metadata, global, stall_reason_breakdown, policy_reason_breakdown,
            dual_side, mode_policy, read/write/drain_block_reasons,
            episodes, switch_effects, max_consecutive_stall_cycles

        性能: O(N_episodes + N_switches + N_cycle_records), 单次 < 10ms.
        """
        # episode 统计
        durations = [e.duration for e in self._episodes]
        ep_count = len(self._episodes)
        ep_stats: Dict[str, float] = {
            "episode_count": ep_count,
            "mean_duration": (sum(durations) / ep_count) if ep_count else 0.0,
            "p50_duration": _percentile(durations, 0.5),
            "p90_duration": _percentile(durations, 0.9),
            "p99_duration": _percentile(durations, 0.99),
            "max_duration": max(durations) if durations else 0,
        }

        # switch 统计
        by_path: Dict[str, List[SwitchEffectRecord]] = {}
        for s in self._switch_records:
            by_path.setdefault(s.path, []).append(s)
        switch_stats: Dict[str, Any] = {"switch_count": len(self._switch_records),
                                        "by_path": {}}
        for path, recs in by_path.items():
            colds = [r.switch_cold_start_cycles for r in recs if r.switch_cold_start_cycles is not None]
            post16_issues = [r.post_issue_counts.get(16, 0) for r in recs]
            switch_stats["by_path"][path] = {
                "count": len(recs),
                "mean_cold_start": (sum(colds) / len(colds)) if colds else None,
                "mean_post_16_issue": (sum(post16_issues) / len(post16_issues)) if post16_issues else 0.0,
            }

        # 百分位 utilization
        denom = max(self.elapsed_cycles, 1)
        return {
            "metadata": {
                "version": "stall_attribution_v1.0",
                "enabled": self.enabled,
                "attribution_runtime_seconds": round(self.attribution_runtime_seconds, 4),
                "attribution_cycles_observed": self.attribution_cycles_observed,
            },
            "global": {
                "elapsed_cycles": self.elapsed_cycles,
                "column_issue_cycles": self.column_issue_cycles,
                "read_issue_cycles": self.read_issue_cycles,
                "write_issue_cycles": self.write_issue_cycles,
                "no_demand_cycles": self.no_demand_cycles,
                "true_stall_cycles": self.true_stall_cycles,
                "column_utilization": round(self.column_issue_cycles / denom, 6),
                "demand_utilization": round(self.column_issue_cycles / max(denom - self.no_demand_cycles, 1), 6),
            },
            "stall_reason_breakdown": {
                r.name: c for r, c in sorted(self.stall_cycles_by_reason.items(),
                                              key=lambda x: -x[1])
            },
            "policy_reason_breakdown": {
                r.name: c for r, c in sorted(self.policy_stall_cycles_by_reason.items(),
                                              key=lambda x: -x[1])
            },
            "dual_side": {
                "both_modes_blocked_cycles": self.both_modes_blocked_cycles,
                "read_only_blocked_cycles": sum(1 for _ in []),  # 占位
                "write_only_blocked_cycles": sum(1 for _ in []),
            },
            "mode_policy": {
                "other_mode_could_issue_cycles": self.other_mode_could_issue_cycles,
                "avoidable_switch_stall_cycles": self.avoidable_switch_stall_cycles,
                "wrong_mode_residency_cycles": self.wrong_mode_residency_cycles,
            },
            "read_block_reasons": {
                r.name: c for r, c in sorted(self.read_block_reason_counts.items(),
                                              key=lambda x: -x[1])
            },
            "write_block_reasons": {
                r.name: c for r, c in sorted(self.write_block_reason_counts.items(),
                                              key=lambda x: -x[1])
            },
            "drain_block_reasons": {
                r.name: c for r, c in sorted(self.drain_block_reason_counts.items(),
                                              key=lambda x: -x[1])
            },
            "episodes": ep_stats,
            "switch_effects": switch_stats,
            "max_consecutive_stall_cycles": self.max_consecutive_stall_cycles,
        }

    def format_summary(self) -> str:
        """生成对齐的人类可读 summary 表 (含 %).

        输出章节:
          - Global counters
          - True stall breakdown (按 StallReason 分布 + 占比)
          - Mode policy detail (other_mode_could_issue / avoidable / wrong_mode_residency)
          - Policy reason breakdown (按 PolicyStallReason 分布)
          - Dual-side status (both / read-only / write-only blocked)
          - Stall episodes (count / mean / p50 / p90 / p99 / max)
          - Switch effects (count / mean cold-start / mean post-16 issues by path)

        控制台打印: write_outputs() 末尾自动调用 print(self.format_summary()).
        """
        d = self.build_summary_dict()
        g = d["global"]
        breakdown = d["stall_reason_breakdown"]
        policy = d["policy_reason_breakdown"]
        ep = d["episodes"]
        sw = d["switch_effects"]
        dual = d["dual_side"]
        mp = d["mode_policy"]

        def _fmt_pct(num: int, denom: int) -> str:
            return f"{(100.0 * num / denom):.2f}%" if denom else "0.00%"

        lines: List[str] = []
        lines.append("Stall Attribution Summary")
        lines.append("─" * 60)
        lines.append(f"elapsed cycles                              {g['elapsed_cycles']}")
        lines.append(f"column issue cycles                          {g['column_issue_cycles']}")
        lines.append(f"read issue cycles                            {g['read_issue_cycles']}")
        lines.append(f"write issue cycles                           {g['write_issue_cycles']}")
        lines.append(f"")
        lines.append(f"no-demand cycles                              {g['no_demand_cycles']}")
        lines.append(f"true stall cycles                             {g['true_stall_cycles']}")
        lines.append(f"column utilization                           {g['column_utilization']:.6f}")
        lines.append(f"demand utilization                           {g['demand_utilization']:.6f}")

        lines.append("")
        lines.append("True stall breakdown")
        lines.append("─" * 60)
        denom = max(g["true_stall_cycles"], 1)
        for r, c in breakdown.items():
            lines.append(f"{r:<35}{c:>8}    {_fmt_pct(c, denom):>7}")
        if not breakdown:
            lines.append("(none)")

        lines.append("")
        lines.append("Mode policy detail")
        lines.append("─" * 60)
        lines.append(f"other mode could issue cycles                 {mp['other_mode_could_issue_cycles']}")
        lines.append(f"avoidable switch stall cycles                 {mp['avoidable_switch_stall_cycles']}")
        lines.append(f"wrong mode residency cycles                   {mp['wrong_mode_residency_cycles']}")
        for r, c in policy.items():
            lines.append(f"{r:<40}{c:>8}")

        lines.append("")
        lines.append("Dual-side status")
        lines.append("─" * 60)
        lines.append(f"both modes blocked cycles                     {dual['both_modes_blocked_cycles']}")

        lines.append("")
        lines.append("Stall episodes")
        lines.append("─" * 60)
        lines.append(f"episode count                                 {ep['episode_count']}")
        lines.append(f"mean duration                                 {ep['mean_duration']:.2f}")
        lines.append(f"p50 duration                                  {ep['p50_duration']:.2f}")
        lines.append(f"p90 duration                                  {ep['p90_duration']:.2f}")
        lines.append(f"p99 duration                                  {ep['p99_duration']:.2f}")
        lines.append(f"max duration                                  {ep['max_duration']}")

        lines.append("")
        lines.append("Switch effects")
        lines.append("─" * 60)
        lines.append(f"switch count                                  {sw['switch_count']}")
        for path, ps in sw.get("by_path", {}).items():
            mc = ps.get("mean_cold_start")
            mc_s = f"{mc:.2f}" if mc is not None else "n/a"
            lines.append(f"{path:<40}count={ps['count']:>4}  mean_cold_start={mc_s:>6}  mean_post_16_issue={ps['mean_post_16_issue']:.2f}")
        if not sw.get("by_path"):
            lines.append("(none)")

        lines.append("")
        lines.append("─" * 60)
        lines.append(f"attribution runtime seconds                   {d['metadata']['attribution_runtime_seconds']:.4f}")
        lines.append(f"attribution cycles observed                   {d['metadata']['attribution_cycles_observed']}")
        return "\n".join(lines)

    def write_outputs(self) -> None:
        """仿真结束时调用. enabled=False 时直接 return.

        步骤:
          1. _finalize_episode() 关闭最后一个 open episode
          2. _finalize_pending_switches() 关闭未耗尽 window 的 switch record
          3. 累计 attribution_runtime_seconds
          4. 按 config.path 写 summary JSON / cycle CSV / episode CSV / switch CSV
          5. 控制台 print format_summary()

        异常隔离: 写文件失败 (权限/磁盘满) 不抛异常, 只是不写对应文件.
        """
        if not self.enabled:
            return
        if not self.enabled:
            return
        # 收尾
        self._finalize_episode()
        self._finalize_pending_switches()
        self.attribution_runtime_seconds = time.perf_counter() - self._t_start

        # summary JSON
        if self.config.summary_output_path:
            d = self.build_summary_dict()
            with open(self.config.summary_output_path, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)

        # cycle CSV
        if self.config.cycle_trace_output_path and self._cycle_records:
            fields = list(self._cycle_records[0].to_dict().keys())
            with open(self.config.cycle_trace_output_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for r in self._cycle_records:
                    w.writerow(r.to_dict())

        # episode CSV
        if self.config.episode_output_path and self._episodes:
            fields = list(self._episodes[0].to_dict().keys())
            with open(self.config.episode_output_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for e in self._episodes:
                    w.writerow(e.to_dict())

        # switch effect CSV
        if self.config.switch_effect_output_path and self._switch_records:
            # 字段集取所有 record 的并集
            all_keys: List[str] = []
            seen = set()
            for r in self._switch_records:
                for k in r.to_dict().keys():
                    if k not in seen:
                        all_keys.append(k)
                        seen.add(k)
            with open(self.config.switch_effect_output_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=all_keys)
                w.writeheader()
                for r in self._switch_records:
                    w.writerow(r.to_dict())

        # 控制台 summary
        print()
        print(self.format_summary())
