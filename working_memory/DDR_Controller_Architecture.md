# DDR Memory Controller Architecture —— Interview Reasoning System

> **文档定位**：Memory Controller Architecture Interview Reasoning System。以 architecture problem 为入口（Level 1）、以 Architecture Node 为唯一知识实体（Level 2）、以真实 RTL 为实现证据（Level 3）。基于本人真实 RTL / Architecture 工作经验；能力目标：面对任意 workload、performance symptom、design choice 或 interviewer question，都能沿统一 architecture model 推导到 request visibility、mapping、queue、scheduler、timing、maintenance、data path、correctness 与 PPA，并能主动把追问引导到熟悉方向。
>
> **第一性问题**：Memory Controller 如何在 correctness / liveness 约束下，把不规则、并发、乱序的 system transaction stream 转化成尽可能连续的 useful DRAM data transfer？
>
> **Final Status（2026-10）**
>
> Ch0~Ch18 restructuring **COMPLETE**；
> **Part I Performance Foundations = FROZEN**；
> **Part II Correctness Constraints = FROZEN**；
> **Part III RTL Implementation Reference = STRUCTURALLY COMPLETE**（Ch15 CONTENT PARTIAL；所有 evidence gap 由 Appendix A 管理）；
> **Phase 4 Legacy Cleanup = COMPLETE**；
> **Phase 5 Final Audit = COMPLETE**；
> **DDR_Controller_Architecture.md = FINAL-FROZEN / AUTHORITATIVE**；
> Open Question Registry = **附录 A（living backlog）**；
> INTERVIEW_QUESTIONS.md = **RETIRED**；
> RESTRUCTURE_PLAN.md = **historical restructuring / mapping record**。
>
> 注：FINAL-FROZEN = 文档结构、terminology、evidence labels、interview navigation、RTL mapping 稳定且自洽；**不等于** ALL QUESTIONS CLOSED——OPEN/PARTIAL 诚实保留于附录 A。
>
> **价值排序（长期固定）**：真实 Architecture > 真实 RTL > 真实数据 > 可靠 protocol fact > 有标记的 architecture inference > generic textbook completeness。不得用泛化知识稀释项目实测数据（CAM 32/64/96、link node 96/224、面积表、Fmax 等），也不得为"结构完整"自动补写不存在的 RTL。

---

# 0. Controller Architecture Map（面试前 10 分钟）

> 本章短、密度高：只给地图、统一语言与全局纪律，不展开 module implementation。展开位置：Ch1（面试导航）→ Part I/II（Architecture Node 正文）→ Part III（RTL Reference）。

## 0.1 唯一核心使命

**在 correctness / liveness 约束下，把不规则、并发、乱序的 system transaction stream，转化为尽可能连续的 useful DRAM data transfer。**

全文一切章节最终回到同一个性能问题：

> **为什么这一拍 DQ 没有传 useful data？**

"零 timing violation" 只是 correctness baseline，不是 performance achievement。真正有架构价值的问题是：**DRAM 本来 legal-to-issue，为什么 architecture / policy 没有 issue useful command？**

## 0.2 Data Plane 主轴

```
Host/NoC → AXI/CHI → XMU → PA(含 Address Mapping @ grant 点) → Command Window(CAM→CCT)
        → Scheduling(FSC) → Timing Enforcement(BSC, issue 前) → DFI → PHY → DRAM
```

**四条结构性注记 [RTL]**：
1. **Timing Enforcement 不是独立流水级**：BSC 的 forbid/down counter 在 FSC 仲裁**前**给出 timing ready（可执行命令 = CCT 候选 ∩ BSC ready ∩ GSC direction-legal，六层口径见 Ch14.3），命令**下发拍**装载 counter；counter 不关心下发后 DFI 侧延迟（同批命令延迟一致，不改变间隔语义）。
2. **Address Mapping 不是独立流水级**：读、写在 PA 前走独立通道，PA 后合流二选一；**PA grant 点**执行物理映射，物理地址写入 CAM entry，逻辑地址此后弃用。
3. **命令流与数据流在 WDP/RDP 分合**：命令走窄通路（地址+属性），数据走宽通路（SRAM+DBI/ECC），仅以 ptr 关联。
4. **保序点前移**：write response 在 PA grant 即返回上游，远早于数据写入 DRAM；这段窗口的顺序安全由 CAM 入口 RAW/WAR 拦截维持（→ Ch9 C2）。

**一条命令的一生（LPDDR5 512B write，开场叙事）[RTL]**：
① AW 按 64B 拆 sub-command，W channel 按 64B resize 入 XMU buffer（AFIFO 一物两用：跨时钟域 + outstanding）；
② PA grant：分配 CAM ptr + 物理地址映射；同时 BRESP 推入 outstanding FIFO（保序节点 = PA grant；数据收齐是送 PA 的前置条件）；
③ CQ 指示 WDP 从 XMU 取数入 SRAM（地址与 CAM 一致，BE 存寄存器堆）→ write data ready；
④ 命令经三层 filter 上 CCT → 无 hit → CS 生成 ACT → tRCD 满足 → 产生 WR 请求；
⑤ FSC 调度 → 命令以 body/type/id 发至 DFI → PHY；
⑥ 临近 PhyWrLat：DFI 持 ptr 向 WDP 取数 → 读出侧 ECC/DBI/CRC 编码 → PHY；取走后 WDP entry 释放。

**读对照 [RTL]**：AR 拆分并在 reorder buffer（link node）分配空间，node ID 随命令下发 → 中间与写类似 → DFI 收到读数据，先入先出绑定命令信息返回 RDP → DBI/ECC 处理 → XMU 写 SRAM → 按 ID 重组 RDATA 返回上游。

**时钟域 [RTL]**：AXI clk（=NoC）/ DFI clk（=Core，控制器主体）/ APB clk（配置）/ PHY 内部。AXI→DFI CDC 在 XMU outstanding AFIFO；变体场景（AXI 高频低位宽）写数据先在 AXI 域合并再跨域，CDC 点移到 XMU-PA 之间。

## 0.3 Control Plane（横向）

| Plane | 内容 | Node（宿主章） |
|---|---|---|
| Refresh / Maintenance | REFab/pb/sb · RFM · DRFM（双账本/critical/执行粒度） | M1~M5（Ch7） |
| Device Management | init / training ownership / LP / DVFS / quiesce（arbiter+worker） | G1（Ch11） |
| RAS | ECC / CRC / parity / retry / poison / PNR | R1（Ch10） |
| QoS | port / class / aging / arbitration | S3（Ch4；admission 接口 Ch2） |
| Power / DVFS | low power / DFS / clock gate | G1（Ch11） |

横向 plane 的共同形态是"正常 traffic 如何**停、让、恢复**"——**admission / issue hold 是 transition-specific 的**（DFS/clock gate 停 front-end；LP 只 hold CS/command issue、XMU 照常接受 host request，新请求可成为唤醒源；ctrlupd/phyupd 只阻塞命令侧）：traffic control → drain required in-flight state → transition-safe quiesce → ownership/device transition → restore → validate → resume（详见 G1/Ch11）。

## 0.4 Performance Loss Model（全文统一语言）

**定义**：Peak DQ BW（协议 × 位宽理论上限）；Effective BW（useful data / 时间）；**Efficiency = Effective / Peak**。分析单位 = **useful issue slot / lost issue slot**——只统计"本来有 useful work、唯一因某原因没有 issue"的 cycle。

**统一机会链（Design View，RQ1 主链）**：
Demand → Visibility → Locality/Parallelism → Candidate → Timing → Direction → Maintenance → Data Delivery → **Useful DQ Transfer**。每一环断掉都表现为同一症状：这一拍 DQ 空转。

**Blocked reason taxonomy（v2，12 类）**：

```
total cycles = issued_useful
             + idle_no_request        （真 idle：无 pending request）
             + blocked_admission      （有 request 但 credit/反压进不来）
             + blocked_visibility     （入队瓶颈 / Pending 队头阻塞）
             + blocked_dependency     （RAW/WAR/WAW/RMW/exclusive）
             + blocked_no_candidate   （CCT 空——CAM 分布 / mapping）
             + blocked_timing         （BSC / counter 未 ready）
             + blocked_direction      （GSC 在对侧 / 切换中）
             + blocked_maintenance    （REF / RFM / DRFM / tRFC 期间）
             + blocked_policy         （eligible 且 timing-ready 但仲裁未选）
             + blocked_data           （WDP fetch 等待 / link node 未就绪）
             + blocked_DFI_PHY        （DFI / PHY 不可用）
```

**归因原则**：目标是 **mutually-exclusive attribution**（互斥归因、避免重复计数）。**但 taxonomy ≠ closed accounting**：同一 cycle 同时满足多个 blocker 时如何归因（precedence / ownership rule）尚未定义 = **X-P1-08 [TODO-DESIGN]**（候选：earliest causal blocker / closest-to-issue / hierarchical attribution，均未定稿）；该规则定义并验证前，不宣称上述恒等式已实现严格 cycle-level 闭合（Audit Invariant 18），Performance Attribution 保持 **PARTIAL**。

**Issue loss ≠ 全部 BW loss**：blocked-cycle taxonomy 当前主要刻画 **issue opportunity loss**（为什么这一拍没有 useful issue）；**payload / transfer efficiency loss**（已有命令 / DQ activity 但 useful bytes < raw transferred bytes——如 partial write、RMW amplification、burst utilization、无效 byte、协议/数据粒度放大）仍需单独闭环（**O2-P1-01 [TODO-DESIGN]**）。Peak → Effective 的完整 loss model 不等同于 Σ lost issue slots。

**Observable ≠ Attributable**：有 counter ≠ 能直接证明唯一 root cause（互斥归因须另行成立）；无 RTL counter ≠ 不能归因（trace / performance model 可补齐）。RTL 落地形态 [RTL]：互斥归因不进 RTL——RTL 只提供命令计数 / 水位电平 / 状态观测（dbg_obv），归因在模型 / 验证环境侧完成；能推 / 不能推边界 → Ch18（O1）。

**BW drop 定位链与 65% 案例 → Ch1 RQ2（O2 Playbook，本节不展开）。**

## 0.5 四个 Architecture View

| 视角 | 问题 |
|---|---|
| **Request View** | request 现在在哪里？ |
| **Resource View** | 占了哪些 CAM / buffer / bank / credit？ |
| **State View** | 哪些 FSM / counter / ownership 在变化？ |
| **Time View** | 为什么现在能发 / 不能发？什么时候解除？ |

只能从一个视角解释的 feature，通常还没真正理解透（四视角与因果链范例 → 1.17）。

## 0.6 Correctness Baseline

六条全局纪律：

1. **Ordering**：AXI ID 只承担**同 ID 同方向**保序；不同 ID 允许乱序交织、地址不参与保序（五分类 → Ch9 C1）；
2. **Timing**：零违反是 baseline——min 约束 ceil、max 驻留与 refresh deadline floor（6-P0-03 [RTL]）；
3. **Refresh deadline**：对当前采用该 postpone / deadline rule 的协议与 refresh mode，**hard deadline = 9×tREFI [SPEC, protocol/mode scoped]**；controller early-warning threshold（本 RTL 取 8×tREFI）[RTL] 是实现裕度、不是协议要求，目的是给 drain / PRE / REF issue 留完成余量（协议适用范围确认 → RF-P1-09 [TODO-SPEC]；→ Ch7 M3）；
4. **Dependency**：冲突检测全部在 **CAM 入口、ID 无关**；单通路阻塞 + 结构保证顺序，不靠 forwarding（→ Ch9 C2）；
5. **Ownership**：one state → one owner → multiple consumers（跨模块一律只读映射）；
6. **Recovery**：每个不可回滚点（PNR）必须回答"之后出错还能不能撤销？谁收敛？"（→ Ch10 R1；全链 PNR 模型 → Ch9 C3 / Ch10 R1）。

**Global Ownership Map（精简版；完整表 → 附录 C）**：

| 状态 | 唯一 owner |
|---|---|
| bank open/closed（row 状态） | BSC（per-bank FSM） |
| AC timing ready | Timing counter（与 BSC 相与） |
| 读写方向 | GSC |
| refresh debt/credit/档位/ab-pb 模式 | 独立 refresh 模块 |
| RFM 激活债（per-bank ACT 计数） | refresh/RFM 模块 |
| credit | PA ↔ CQ（grant 消耗、离开 CAM 归还） |
| write data ready | XMU / WDP |
| CCT 占用 | CQ（RD/WR 两张 per-bank 单槽） |
| 读返回保序 | XMU link list / reorder buffer |
| 全局转换 | DEVMGR（arbiter + worker） |

## 0.7 关键设计哲学

1. **批处理摊薄切换**：读写 batch、refresh 见缝插针、rank/SID 多命令再切——切换代价是常量，batch 是唯一摊薄手段；
2. **迟滞防乒乓**：SidSwitch 空闲阈值、水线 set/clr、渐进式读写切换、refresh critical 退出 LowTh——用时间迟滞换切换稳定性；
3. **结构性规避**：DVFS 保证 IDLE、零旁路 counter 检查、DEVMGR 退出顺序——用系统级约束消解模块级难题；
4. **one-state-one-owner**：一个状态一个 owner，跨模块只读映射；
5. **protocol constraint → architecture consequence**：协议差异只研究到"改变 MC 设计"为止（例：HBM row/col bus 独立 → FSC 可同拍 row+col；DDR/LPDDR CA shared → 单拍单 command；HBM 无 DM → XMU 转 RMW）；
6. **visibility × locality × timing supply 三角**：性能机会 = 三者之积，单一维度加强会遇饱和（→ RQ1/RQ3）；
7. **useful issue slot**：一切机制价值的统一度量单位；
8. **粒度统一 64B 是设计锚点口径，非协议事实**：cache line 64B = SoC 常态假设；CHI 64B = 产品配置；sub-command 64B = 内部设计选择；col command = 协议 × 位宽推导（DDR4/5、LPDDR5 = 64B [SPEC]；HBM per PC DQ32×BL8 = 32B [SPEC]，由 burst 合并/双发吸收）。

## 0.8 本文使用方式

**三层阅读法**：
A 面试快复习 = Ch0 + Ch1（地图 / RQ / 回答套路 / Hook / 关键 model）；
B 深入某设计问题 = Part I/II 对应 Architecture Node（11 字段模板）；
C 查真实 RTL = Part III Implementation Reference（6+1 字段模板）。

**可信度标签**：事实类 **[RTL] / [SPEC] / [MEASURED] / [MODEL] / [INFERENCE]**；未关闭类 **[TODO-SPEC] / [TODO-RTL] / [TODO-MEASURE] / [TODO-DESIGN] / [BOUNDARY]**。**Registry Scope Rule（Phase 5 定稿）**：每个 **architecture-relevant** unresolved question 必须登记附录 A（正文标记与登记簿一一对应）——即影响 architecture model / correctness boundary / performance conclusion / protocol interpretation / PPA conclusion / evidence validity / interview conclusion 的问题；**pure implementation-detail TODO**（exact signal name / bit width / pipeline cycle / lane realization / debug wiring 等无 architecture consequence 项）可标 **[TODO-RTL-local]** 留在 Part III Known RTL Limitation，**不要求 Registry 登记**，且不得影响 architecture / correctness / performance conclusion。Agent 禁止：把 [INFERENCE] 改 [SPEC]；把 TODO 自动补成合理答案；把业界 typical 写成本项目 RTL；"A 比 B 好"必须落到数字。

**Evidence Discipline（长期硬规则：Evidence Before Completeness）**：任何 Architecture Claim 写成确定结论前，必须至少属于 [RTL] / [SPEC] / [MEASURED] / [MODEL] / [INFERENCE] 之一，否则进入 [TODO-SPEC] / [TODO-RTL] / [TODO-MEASURE] / [TODO-DESIGN] 或 [BOUNDARY]。三条禁令：
① **严禁为填模板而创造内容**——11 字段模板是问题清单不是答案清单；某字段无可靠依据时写 OPEN / PARTIAL / TODO，不补 generic textbook answer；
② **严禁虚构项目经历**——"我们发现 / 实测证明 / sweep 后选择"类表述必须有真实证据；仅为展示方法构造的案例标 [MODEL EXAMPLE] / [HYPOTHETICAL EXAMPLE]；
③ **严格区分"建议怎么验证"与"已经验证过"**——验证方法合理 ≠ 数据存在（[TODO-MEASURE] ≠ [MEASURED]）。
推论：**absence of evidence ≠ evidence of absence**——"目前没看到"不能写成"RTL 一定没有"（应标 [TODO-RTL]）。**UNKNOWN + Closure Method = Architecture Knowledge Backlog**，不是文档缺陷；没有标记的 UNKNOWN 才是问题。

**研究边界（相邻模块研究到"会改变 MC 设计"为止）**：NoC/AXI/CHI → transaction semantics / ordering / QoS / backpressure / error contract；PHY → DFI ratio、PhyRd/WrLat、rolling、training ownership、频率切换、error/status 上报（PLL/DLL/CTLE/DFE 等 [BOUNDARY]）；SoC → channel selection / 地址交错 / reset / power policy；DRAM → 一切会变成 MC state / command sequence / timing constraint / maintenance obligation 的协议行为。协议 why（JEDEC 设计动机、feature 历史、SI 原理）归 `Memory_Protocal.md`；本文只写 **Protocol Fact → Controller Consequence** 两行。

**因果链七层（Node 模板 Model 字段的方法论）**：
Physical/System Problem → Protocol Constraint → MC Requirement → Architecture Mechanism → RTL State → Performance/PPA Cost → Observed Counter。

**完成标准（CLOSED 11 条，缺任一保持 OPEN/PARTIAL，不假装完成）**：白板画出结构；说清 request/state 生命周期；知道 state owner；分清 protocol requirement 与 project choice；说出 ≥1 alternative；说出当前方案 tradeoff；知道一个 corner case；知道 failure/recovery；能预测 workload 改变后的行为；能提出量化验证方法；能回答 ≥2 层 follow-up；能从四视角解释。

**当前导航（最终）**：Ch0 / Ch1 = interview navigation / methodology ✅；**Part I（Ch2~Ch8）= authoritative Performance Architecture（FROZEN）**✅；**Part II（Ch9~Ch11）= authoritative Correctness Architecture（FROZEN）**✅；**Part III（Ch12~Ch18）= authoritative RTL Implementation Reference（STRUCTURALLY COMPLETE；Ch15 CONTENT PARTIAL）**✅；**附录 A = authoritative Open Knowledge Backlog（living）**；**附录 C = authoritative Global State Owner Table**；Legacy Zone = 已删除（Phase 4，映射存档《RESTRUCTURE_PLAN.md》Appendix B）；INTERVIEW_QUESTIONS.md = **RETIRED**（historical tracker）。

---

# 1. Interview Question Graph & Answer Playbook（Navigation Layer）

## 1.1 How to Use the Question Graph

- **Root Question = interview entry；Architecture Node = 唯一知识实体；RTL Reference = 实现证据。** 32 个 Node（22 CORE / 7 LEAF / 2 CROSS-CUTTING / 1 PLAYBOOK），清单见《RESTRUCTURE_PLAN.md》Node Map 与 Part I 各章。
- **RQ1 = Design View**（如何制造 useful issue opportunity）；**RQ2 = Diagnosis View**（opportunity 在哪一级丢掉）。两者共享同一张 Node 图：设计高性能 MC = 尽量减少各类 blocked opportunity；调试低性能 MC = 定位哪类 opportunity 被浪费。
- **NO TECHNICAL DUPLICATION IN CH1**：同一 Architecture Conclusion——Ch1 只许摘要/导航；Part I 是唯一 architecture reasoning 正文；Part III 只有 implementation。
- 每个 RQ 固定四段式：**① 20s Answer**（Conclusion → 一层因果 → 一个 Hook，然后停下）；**② 90s Answer Skeleton**（C-M-T-P-H，模板见 1.17）；**③ Deep-Dive Node Links**（Node → Part I 正文 → Part III RTL → 协议 / corner / PPA / measurement）；**④ Steering Hooks**（Preferred / Secondary / Do-not-volunteer）。

## 1.2 RQ1 — 如何设计一个高性能 Memory Controller？（Design View）

**20s**：MC 性能问题只有一个统一形式——这一拍 DQ 为什么没传 useful data。我的方法是把 Peak 到 Effective 之间每一类 lost issue slot 逐一封堵：request 供给、scheduler 可见性、locality/并行度、timing 供给、方向切换、maintenance、data path。归因上我区分 observable 和 attributable：RTL counter 直接支撑的用 counter，其余用 trace / performance model 补齐。

**90s Skeleton**：
- **C**：Efficiency = Effective/Peak，由 lost issue slot 结构决定；高性能 MC = 机会链每一环都不空转。
- **M**：Demand→Visibility→Locality/Parallelism→Candidate→Timing→Direction→Maintenance→Data Delivery 十级机会链（Ch0.4），每环对应一个或多个 Architecture Node，并使用 RTL counter / trace / model 中当前可获得的证据（并非每环已有直接 counter）。
- **T**：每个机制都有代价——CAM 深 ↔ compare 面积/时序（非线性）；batch 大 ↔ write latency；hit-first ↔ P99；refresh postpone ↔ latency spike。
- **P**：12 类 blocked taxonomy 是统一性能分类框架，目标是形成 mutually-exclusive attribution；precedence / ownership rule 尚未关闭（X-P1-08），因此当前 Performance Attribution 仍为 PARTIAL；observable vs attributable 分层证明（X-P1-07）。
- **H**："具体哪类损失最大，我用一个 65% 案例演示定位过程（→RQ2）。"

**Deep-Dive Node Links**：V1/V2/V3（Ch2）→ L1~L5（Ch3/Ch4）→ S1/S2（Ch4）→ T1~T3（Ch5）→ D1/D2（Ch6）→ M1~M5（Ch7）→ DP1~DP3（Ch8）→ O1（Ch18）。

**Steering**：Preferred = Measurement / blocked-cycle attribution；Secondary = CAM visibility（V2）；Do-not-volunteer = PHY analog implementation。

## 1.3 RQ2 — Bandwidth 为什么没跑满？如何系统定位？（Diagnosis View · O2 Playbook）

**20s**：BW 不达标我不猜 scheduler，先跑固定因果链：no request → admission → visibility → dependency → candidate → timing → direction → maintenance → policy → data ready → DFI/PHY → issued-but-inefficient，逐层排除，每层对应 taxonomy 中的一类候选 blocker（cycle-level 互斥归属规则仍为 [TODO-DESIGN]）——先证明"不缺 request"，再定位是哪一类 opportunity 被浪费。

**诊断链（diagnostic traversal order，用于系统排查；≠ mutually-exclusive attribution precedence——X-P1-08 关闭前两者严格分离）**：

```
No useful request?（上游 / ostd）→ Admission / backpressure?（credit、XMU 反压）
→ No scheduler visibility?（入队瓶颈、Pending 队头阻塞）→ Dependency blocked?（RAW/WAR/WAW/RMW）
→ No eligible candidate?（CCT 空——CAM 分布 / mapping）→ Timing blocked?（BSC / counter——哪条 timing？）
→ Direction blocked?（GSC 批量 / 切换阈值）→ Maintenance blocked?（REF / RFM / DRFM）
→ Scheduler policy bubble?（eligible 且 ready 但未选）→ Data not ready?（WDP / link node）
→ DFI / PHY unavailable?（ratio / phase / training）→ Issued but DQ inefficient?（BL / burst 合并 / turnaround）
```

**九步推理模板（每个 Performance Node 都必须能走通，走不通 = PARTIAL）**：
Symptom → Observable → Bottleneck Hypothesis → Architecture Cause → Design Knob → Expected Effect → Side Effect → Experiment → Conclusion。

**示例案例 [MODEL EXAMPLE]：假设 BW = 65% Peak（演示推理模板，非项目实录；唯一宿主）**：
- **Symptom**：streaming 为主的 workload，BW 只有 65%。
- **Observable**：CAM occupancy 高（cam_outnum 电平持续 ≥ 阈值）＋ FSC 无命令输出拍多。
- **Hypothesis 排除**：CAM occupancy 高 → V1 Demand shortage 不像首要原因（scheduler 已看到较多 request）；但 **V3 Admission 不能仅凭 CAM 高排除**——可能存在 credit 耗尽 + upstream 持续被 backpressure（那是下游堵塞的传播结果，未必 root cause），需继续确认 credit / fifo_full / backpressure 状态；继续分叉：candidate? / timing? / direction? / maintenance? / policy? / data?
- **假设定位 A**：ACT 计数 / col 比偏高、tRRD/tFAW blocked cycles 占主导 → random 成分 / ACT supply 受限（L1 miss → T2）→ **Knob** = mapping（L5）/ page policy（L4）→ 预期 hit rate↑、ACT↓；副作用 = BLP 分布变化；**Experiment** = stride sweep + ACT/col 计数 + lost-slot Top5。
- **假设定位 B**：turnaround lost cycles 占主导 → 方向切换（D1）→ **Knob** = 水线 / 批量阈值；预期 switch/sec↓；副作用 = write queue latency↑（用 R/W latency 观测验证）。
- **Conclusion**：按 blocked 占比排序逐项修；observable 缺口（hit rate、P99 无 RTL counter）用 trace / performance model 补齐，并声明 attributable 边界（Ch18 能推/不能推表）。

**Deep-Dive Node Links**：O2（本节，方法学）→ O1（Ch18，证据边界）→ 各 blocked reason 对应 Node（V1~DP3）。

**Steering**：Preferred = 65% 案例完整走一遍；Secondary = counter 能推/不能推的诚实边界；Do-not-volunteer = SoC / NoC 内部实现。

## 1.4 RQ3 — 为什么 Controller 需要深 outstanding / CAM？

**20s**：CAM 深度买的不是存储，是 scheduler visibility——可见请求越多，row-hit 与 BLP 机会越多；但 conflict compare 在关键路径上，depth 增加会扩大 compare / reduction / routing 规模，面积随 entry 增加持续增长、critical path / routing closure 越来越困难（Fmax 变化不是简单线性）。[RTL] 项目实际采用过 CAM 32/64/96（随协议/bank 配置）；甜点应由 depth sweep 验证 [MODEL][TODO-MEASURE→X-P1-07]。

**90s（完整 C-M-T-P-H 范例——1.17 模板的示范）**：
- **C**：CAM 深度 = scheduler 在单位时间能看到的请求窗口，决定 row-hit opportunity、BLP opportunity 与 reorder freedom 的上限。
- **M**：可见 entry ↑ → 不同 bank 命中概率 ↑（BLP）、同 row 命中 ↑（hit）、可挑选余地 ↑（policy）；边际收益何时饱和取决于 workload（bank entropy / row locality / burst packing / dependency(HOL) / available BLP / timing supply / scheduler policy），当前无 depth sweep 数据、不预判 [TODO-MEASURE]；机制差异 [MODEL]：streaming 可能天然具备较强 locality/burst packing（较浅窗口即够），random 的 row locality 低、但更深窗口可能继续增加 bank-level opportunity。同时入口 conflict compare（RAW/WAR 检测）+ hit 判断规模随 entry 增长 → 面积 / 时序收敛代价递增；queueing latency 随深度上升（排队论直觉 [MODEL]，实测缺口 X-P1-07）。
- **T**：获得 visibility / BLP / hit / reorder freedom；付出 area、compare critical path、queueing latency、HOL 影响范围。Alternatives：global CAM（本项目 [RTL]）vs per-bank queue（静态划分，bank 倾斜时一侧满一侧空）；加深 CAM vs 加深上游 outstanding（visibility 不前移无效）。
- **P**：depth sweep（16/32/64/96/128）× workload → BW / P99 / area / timing [TODO-MEASURE→X-P1-07]；运行时 cam_outnum 水位电平 + bank-ready 分布交叉验证；synthesis 面积 / Fmax 对比。
- **H**："CAM depth 的甜点高度 workload-dependent：streaming 主要看 locality/burst 是否已经够，random 主要看 deeper window 是否还能增加 BLP——谁先饱和不能靠直觉，我会用 depth×workload sweep 判断（→RQ4/RQ5）。"

**Deep-Dive Node Links**：V2（Ch2）→ Ch13 CAM/CQ Reference；HOL → C2（Ch9）；burst 双口径（storage 等效 256 vs scheduler visibility 64 entry）→ V2。

**Steering**：Preferred = depth sweep proof 方法；Secondary = burst 双口径 + compare critical path；Do-not-volunteer = link list RTL 细节（留待追问）。

## 1.5 RQ4 — Address Mapping 怎么做性能调优？

**20s**：mapping 是 workload geometry 与 DRAM 几何的耦合器——它同时决定 row locality 与 bank/BG 并行度的上限。本项目推荐序 {row, cs, ba, col, bg, col}（bg0/ba/bg1 交织），用 stride 通式（stride=2^k×64B：k<7 时 bank 字段滚动、k≥7 时单 bank 纯换 row）可以现场推出任何 workload 的落点。

**90s Skeleton**：C=mapping 决定地址 entropy 如何散到 bank/BG/rank/row；M=stride 通式 + bank entropy + H 区间；T=rank 位放高是为避免 bus/ODT 切换（cs=[10] 被 col/ba/bg 位宽钉死）、XOR hashing 不采用（本 workload 无 power-of-two 大 stride 热点）；P=bank entropy / hit rate / ACT-per-col sweep [X-P1-07]。

**Deep-Dive Node Links**：L5（Ch3）→ D2（cs 位 → Ch6）；AMAP 单一 source of truth [RTL]。

**Steering**：Preferred = stride 通式现场推导；Secondary = rank 的 capacity vs parallelism/switching tradeoff（当前设计以 capacity/topology 为主维度，独立 bank state 仍可能带来并行机会）；Do-not-volunteer = DDR5 sub-channel 业内惯例（OPEN 调研，2-P0-02）。

## 1.6 RQ5 — Row Locality 与 Bank/BG Parallelism 怎么权衡？

**20s**：两者冲突没有闭式解——四约束公式（tCAS / tACT / tRC / tRCD）给出每 bank 命令数 H 的可行区间 [H_min, H_max]，区间内按负载取向摆位；冲突时先保 locality 下限（经验值每 bank ≥4 条，H=tACT/tCAS 解析支撑）再给 BLP。

**90s Skeleton**：C=H 区间模型；M=bank 数隐藏 tRC（N_bank×H×tCAS≥tRC）、Q bank 轮转隐藏 tRCD；T=BG interleave 粒度 vs 每 bank hit 数；P=H sweep（1/2/4/8/16/32）+ hit rate/BLP utilization [X-P1-07]。

**Deep-Dive Node Links**：L1/L2/L3（Ch3）→ L4 page policy（Ch4）→ T2（ACT supply）。

**Steering**：Preferred = H 区间四约束模型；Secondary = streaming vs random 反例；Do-not-volunteer = —。

## 1.7 RQ6 — Scheduler 如何选择下一条 command？

**20s**：我把"能不能调"和"发不发"拆成一条六级链——CCT 提名 **Eligible**（三层 filter、per-bank 单槽、上表不可撤回）→ **BSC-ready**（bank FSM ∩ timing counter）→ **Direction-legal**（GSC）→ **Executable** → FSC **Selected**（Col>Row）→ **Issued**。policy 是可配置的 priority-first / page-hit-first 双模式 + GPR aging 兜底；aging / expired GPR 是防 starvation 的核心机制，真正的 worst-case service bound 还依赖 CCT slot release、direction progress、timing legality 等条件——无形式化 bound 时不宣称严格 cycle 上界（S3-P1-01 [TODO-DESIGN]）。

**90s Skeleton**：C=eligible vs executable 二分是调度正确语言；M=为什么 FCFS 不行（head-of-line miss 拖死后续 hit）、hit-first 的收益来源（省 tRCD+tRP）；T=hit-first 的 P99 / 公平代价、CCT 单槽换简单与不可撤回（timing/area/verification）；P=policy A/B 对比（BW/avg latency/P99/starvation time）[X-P1-07]。

**Deep-Dive Node Links**：S1/S2/S3（Ch4）→ T1（timing ready）→ Ch14 BSC/GSC/FSC Reference。

**Steering**：Preferred = eligible vs executable 二分；Secondary = hit-first 的 P99 反例；Do-not-volunteer = 三层 filter RTL。

## 1.8 RQ7 — 为什么 R/W switching 是主要性能损失？batch 怎么定？

**20s**：切换代价 = 总线 turnaround（tWTR/tRTW）+ 对侧行准备暴露（unhidden tRCD），两者都是常量，唯一摊薄手段是 batch——水线 / 时间配额 / critical / expired 四类触发；渐进式切换在对侧 column 执行期提前开行——best case 下若对侧 ACT 能足够提前完成，tRCD 被当前方向 column traffic 隐藏，切换暴露成本主要剩 bus turnaround；若 ACT opportunity 不足 / bank conflict / tRRD·tFAW block / CAM visibility 不足，仍会暴露部分 row preparation。

**90s Skeleton**：C=batch 长度=摊薄分母；M=turnaround 完整账单（turnaround + unhidden row preparation 可拆分验证）；T=batch 不能无限大——write latency（read 默认优先的根因是端到端延迟责任不对称）、starvation；P=switch count/sec + turnaround lost cycles + hidden tRCD ratio [X-P1-07]。

**Deep-Dive Node Links**：D1（Ch6）→ D2（rank/SID 对照）→ T2/T3（unhidden tRCD / tWTR）→ Ch14 GSC Reference。

**Steering**：Preferred = turnaround 账单 + hidden tRCD；Secondary = 90R+10W 的 write starvation；Do-not-volunteer = —。

## 1.9 RQ8 — Timing constraint 如何形成真实 bandwidth ceiling？

**20s**：每类 workload 被不同 timing 卡住——streaming hit → tCCD；random row miss → tRCD/tRC/ACT supply（tRRD/tFAW）；高 bank 并行 → tRRD/tFAW；R/W mixed → turnaround；refresh → tRFC。我用 Supply/Demand 模型统计 lost issue slot：只算"唯一因该约束无法发出的 useful command"，零 timing violation 只是 baseline。

**90s Skeleton**：C=timing supply 决定每拍合法命令供给率；M=workload→limiting-timing 映射 + 分布式 forbid/down counter（min 约束 ceil、max 驻留 floor [RTL]）；T=分布式 counter vs 集中 timestamp（面积/时序/DVFS 五维）；P=timing blocker Top5 lost-slot sweep + min-gap 断言 [X-P1-07]。

**Deep-Dive Node Links**：T1/T2/T3（Ch5）→ Ch15 Timing Counter Reference（含 ≈1017 口径声明）。

**Steering**：Preferred = workload→limiting-timing 映射表；Secondary = lost issue slot 口径；Do-not-volunteer = counter 逐项清单（1017 为近似口径）。

## 1.10 RQ9 — Controller 如何在不可延期 maintenance obligation 与 normal traffic 之间做调度？

**20s**：刷新是"不可延期义务"与 traffic 共享同一个 scheduler——我的统一模型是 obligation → debt → deadline tracking → postpone → pressure → critical escalation → bank drain → maintenance issue → unavailable interval → recovery；REF 是时间债、RFM 是激活债，两本账只在 FSC 优先级序汇合。

**90s Skeleton**：C=双账本 + critical 迟滞 + 两档执行粒度；M=debt 单位是"欠一次刷新"（与 tREFI 解耦）、postpone 上界 9×tREFI−8×tRFC [SPEC, protocol/mode scoped——适用范围 → RF-P1-09]、REFab 抵本轮全部 pb 债；T=postpone depth ↔ latency spike / BW、Normal REFab 压过 critical REFpb 的性价比逻辑；P=blocked_maintenance 互斥归因 + postpone depth sweep [X-P1-07]。

**高价值展示题（Steering 首选 Hook）——M3 Odd/Even watchdog 三档**：
- **20s**："在当前适用的 protocol/mode 下，REFpb 的硬期限是 same-bank consecutive refresh interval 不超过 9×tREFI（适用范围确认 → RF-P1-09 [TODO-SPEC]）。由于同一 bank 的连续两次 refresh 只跨相邻两个 round，可以用 Odd/Even 两个交错 watchdog 覆盖所有 adjacent round-pair；到项目设置的 early-warning threshold（例如 8×tREFI [RTL]）提前拉 critical，给 drain/PRE/REF 留余量。它本质上是把 N_bank 个 per-bank age tracking 压缩成两个 global watchdog，是一个 conservative sufficient condition。"
- **90s**：＋Δt_bank=(Tn−xn)+x(n+1) ≤ Tn+T(n+1) 推导 [MODEL]；round 定义；**round-complete invariant 前提**（watchdog 不是无条件正确，依赖"每 bank 每 round 必完成一次 REFpb"）；固定 bank 顺序的 margin（OPEN）；8×/9× = early warning vs hard deadline 两层（hard deadline 为 protocol/mode scoped，→ RF-P1-09）；conservative vs exact。
- **Deep-Dive**：→ M3（Ch7）→ Ch15（计数起点 = REFab 拍或本轮最后 REFpb 拍 [RTL]、哪轮清哪个 counter、round_complete 定义）→ round-complete invariant 断言 → PPA。
- **展示链**：Protocol Requirement → Mathematical Sufficient Bound → Scheduler Invariant → RTL State Compression → PPA / Performance Tradeoff。

**Deep-Dive Node Links**：M1~M5（Ch7）→ S2（FSC 维护优先级序）→ T2（禁 ACT）→ G1（进 LP 强制 AB）。

**Steering**：Preferred = Odd/Even watchdog 展示题；Secondary = 双账本；Do-not-volunteer = PRAC/ABO 未实现细节。

## 1.11 RQ10 — Throughput / Latency / QoS / Fairness 怎么权衡？

**20s**：QoS 是跨层设计不是单点——AXI QoS → port 优先级 → port WRR → HPR/LPR/TPW/GPR 四分类 → 提名 policy → aging → FSC；冲突时高层压低层；aging / expired GPR 恒第一是防 starvation 的核心机制，严格 worst-case bound 见 S3-P1-01。

**90s Skeleton**：C=延迟责任不对称（read 等 data、write BRESP 可提前）决定了 read 默认优先与 write batch 的共存；M=优先级注入的是 ordering，代价是 hit rate 与 P99（hit-first 让 miss 流排队）；T=QoS 与最大 BW 冲突时保 QoS 底线 + aging 上界；P=QoS 流量分布 / 饥饿健康度 counter（exp_gpr 应 ≈0）[RTL O1]、P99 为 [MODEL only] 诚实边界。

**Deep-Dive Node Links**：S3（Ch4）→ S2 → V3（admission 接口）→ D1（write 提权）。

**Steering**：Preferred = 全层级冲突谁压谁的结构答案；Secondary = expired GPR 上界；Do-not-volunteer = P99 具体数值（无 RTL 观测，诚实边界）。

## 1.12 RQ11 — random / sequential / stride workload 分别怎么分析？

**20s**：三类几何——sequential = page hit + tCCD 主导（供给型天花板）；random 通常带来 row locality 降低与 ACT pressure 增加（tRRD/tFAW/tRCD/tRC），仅在 HBM partial-write 等特定场景额外叠加 RMW amplification；stride = 用通式精确预测（stride=2^k×64B：k<7 bank 字段滚动，k≥7 单 bank 纯换 row），不需要 simulation 就能说出落点。

**90s Skeleton**：C=workload geometry 经 mapping 变成 bank/row 访问模式，决定 limiting timing；M=三类各自的机会链断点与对应 Node；T=同一设计在三类下最优点不同（mapping/H 区间/batch 长度）；P=stride sweep + 三类对照的 blocked 分布 [X-P1-07]。

**Deep-Dive Node Links**：L5/L1/L2（Ch3）→ T2/T3（Ch5）→ C2（RMW）→ M4（ACT 债）。

**Steering**：Preferred = 三类 workload 对照推导；Secondary = stride 通式现场演算；Do-not-volunteer = —。

## 1.13 RQ12 — HBM / DDR / LPDDR 架构差异如何改变 controller？

**20s**：协议差异改变 controller 的三个位置——粒度（64B vs 32B per col → 拆分与 burst 合并）、partial write 路径（DDR5 DM → native masked write；HBM 无 DM → XMU 转 RMW，占读写 CAM 各一）、命令通路（HBM row/col 独立 bus 可同拍 row+col、DDR/LPDDR CA shared 单拍单命令；DFI ratio / 双 PC / SID 分时）。

**90s Skeleton**：C=同一 Architecture Node 在不同协议下的约束不同、机制随之变形；M=cross-protocol 对比只服务于 architecture（Protocol Fact → Controller Consequence 两行）；T=多协议共存的 RTL 代价（参数化 counter / FSM 分支）；P=cross-protocol 对比表 + per-protocol 命令 mix。

**Deep-Dive Node Links**：DP3（Ch8）→ L5（粒度）→ C2（mask write vs RMW）→ D2（PC/SID）→ G1（切频分族）。

**Steering**：Preferred = mask write → RMW 决策链；Secondary = HBM 同拍 row+col 与双 PC；Do-not-volunteer = 协议历史细节（归 `Memory_Protocal.md`）。

## 1.14 RQ13 — CAM / counter / scheduler 如何做 PPA tradeoff？

**20s**：我用三张实测表回答——timing counter ≈1017 个（逻辑口径）占 scheduler 面积约 40%；WDP 占 LPDDR6 面积 10.40%；CAM/面积随 depth 持续增长且 compare/reduction/routing 让 closure 越来越难（Fmax 非线性变差）。scaling 推理放在每个 Node 的 Tradeoff 字段，数字唯一来源是 Part III synthesis / measurement——P1 只是统一索引。

**90s Skeleton**：C=PPA 是横切轴不是模块；M=每类资源的 scaling 规律（CAM×entry、counter×bank/BG、mux×choose-2）；T=分布式 counter vs 集中、shadow window（64 选 2 → 8 选 2）压 critical path；P=synthesis 面积表 + Fmax + depth sweep [X-P1-07 / 6-P0-05 FF 回填]。

**Deep-Dive Node Links**：P1（索引）→ V2 / S2 / T1 / DP3 各 Node Tradeoff 字段 → Ch13~Ch17 实测表。

**Steering**：Preferred = 面积/counter 实测数字；Secondary = 64 选 2→8 选 2 shadow window；Do-not-volunteer = 工艺库细节。

## 1.15 RQ14 — 如果重新设计一版 MC，你会改什么？

**20s**：这是开放题，我有候选清单但不当场拍板——adaptive page policy（当前 close-page 为多数场景的静态选择）、mapping 可配置化增强、观测缺口补齐（hit rate / latency 无 RTL counter）、以及 burst 内命令独立性（第 1 条卡 timing 时第 2~4 条不能 bypass）。每一条我都能说出当前方案的失败 workload、改法与代价。

**90s Skeleton**：C=redesign 的判断框架 = 每个 Node 的 Alternatives/Saturation 字段汇总；M=先问哪个 Node 在目标 workload 已饱和；T=改动按"证据强度"排序（有实测支撑的优先）；P=逐项用 sweep/counter 验证。

**Deep-Dive Node Links**：导航型 RQ——汇总全部 Node 的 Alternatives 字段（X-P2-12 OPEN）。

**Steering**：Preferred = 三推翻候选 + 失败 workload；Secondary = 各 Node Alternatives 汇总；Do-not-volunteer = —。

## 1.16 RQ15 — Controller 如何保证 correctness 同时仍允许 aggressive reorder？

**20s**：边界 = commit 分层 + 入口检测 + PNR 分域——**master-visible completion 在 BRESP（PA grant 即回）**；**command-domain PNR 在 col issue**；**read 的 recovery-domain PNR 在 RDP→XMU**（write 的数据所有权移交在 DFI 取数）。同址安全由 CAM 入口 RAW/WAR/WAW/RMW 拦截保证（ID 无关、单通路阻塞、不靠 forwarding）；WAW 用 byte-enable merge、RMW 用 flush 提权——统一模型 → Ch9 C3。

**90s Skeleton**：C=reorder 自由度以"入口检测 + 单通路结构"换正确性；M=五分类保序责任表 + 依赖矩阵 + PNR 全链；T=不允许 bypass 的 HOL 代价 vs forwarding 复杂度；P=dependency sequence 断言 + min-gap + 入口检测覆盖。

**Deep-Dive Node Links**：C1/C2/C3（Ch9）→ R1（Ch10）→ M1（refresh deadline）→ G1（drain 判据）。

**Steering**：Preferred = commit 双视角 + 入口检测；Secondary = WAW merge 但不做 forwarding 的原因；Do-not-volunteer = —。

## 1.17 Answer Playbook — C-M-T-P-H（服务 90s Answer）

| 段 | 内容 | 纪律 |
|---|---|---|
| **C**onclusion | 先给架构结论 | 不从 RTL 细节讲起 |
| **M**odel | 因果模型：为什么影响 BW / Latency / PPA | 尽量公式或链条 |
| **T**radeoff | 得到什么、牺牲什么、alternatives | 至少一个 alternative |
| **P**roof | counter / simulation / synthesis / sweep | 区分 observable vs attributable；无 Proof 方法则该结论 PARTIAL |
| **H**ook | 主动留下一个值得追问的接口 | 优先引向自己熟悉方向 |

完整范例见 1.4（RQ3/CAM=64）。旧文档的"金句"各章就地保留，作为 Hook 素材。

**因果链七层 + 范例（[MODEL 范例]）**：read 默认偏向的由来——read latency sensitive（AXI read 必须等数据）→ write BRESP 可提前（端到端延迟责任不对称）→ GSC 默认偏 read、write 见缝插针 batch drain → turnaround 摊薄但 write queue latency ↑ → 用 R/W latency + turnaround cycles 验证。七层落位：Physical Problem（**shared bidirectional / half-duplex DQ** + read/write 端到端延迟责任不对称）→ Protocol Constraint（AXI response 语义）→ MC Requirement（延迟责任划分）→ Architecture Mechanism（GSC 默认 read + write drain）→ RTL State（方向态/配额计数）→ Performance Cost（write latency↑ 换 turnaround↓）→ Observed Counter（R/W latency 分向统计）。

## 1.18 Answer Depth — 20s / 90s / Deep Dive 三档规范

- **20s**：Conclusion + 一层因果 + 一个 Hook，**然后停下**——不主动倒出所有细节；
- **90s**：C-M-T-P-H 完整骨架（1.17）；
- **Deep Dive**：仅当 interviewer 继续追问时，沿 Node Link 进入：Architecture Node（Part I）→ Current Design → RTL Reference（Part III）→ Protocol Detail → Corner Case → PPA → Measurement。
- 三档答案共用同一套事实，差异只在展开深度——禁止三档之间相互矛盾。

## 1.19 Hook Strategy

三类 Hook：
- **A. Tradeoff Hook**："这个方案 BW 更高，但 P99 / latency 会变差。"
- **B. Counterexample Hook**："这个结论对 streaming 成立，random 下完全不同。"
- **C. Measurement Hook**（本人重点）："这个问题最后不是靠直觉，而是靠 blocked-cycle attribution / counter 才定位出来的。"

**逐 RQ Steering 总表**：

| RQ | Preferred Hook | Secondary | Do-not-volunteer |
|---|---|---|---|
| RQ1 | blocked-cycle attribution | CAM visibility | PHY analog |
| RQ2 | 65% 案例全流程 | counter 能推/不能推边界 | SoC/NoC 内部 |
| RQ3 | depth sweep proof | burst 双口径+compare path | link list RTL |
| RQ4 | stride 通式现场推导 | rank 哲学 | DDR5 sub-channel 惯例（OPEN） |
| RQ5 | H 区间四约束 | streaming vs random 反例 | — |
| RQ6 | eligible vs executable | hit-first P99 反例 | filter RTL |
| RQ7 | turnaround 账单+hidden tRCD | 90R+10W starvation | — |
| RQ8 | workload→limiting-timing 表 | lost issue slot 口径 | counter 逐项清单 |
| RQ9 | Odd/Even watchdog 展示题 | 双账本 | PRAC/ABO 未实现细节 |
| RQ10 | 全层级冲突结构 | expired GPR 上界 | P99 数值 |
| RQ11 | 三类 workload 对照 | stride 通式 | — |
| RQ12 | mask write→RMW 决策链 | HBM 同拍 row+col / 双 PC | 协议历史 |
| RQ13 | 面积/counter 实测数字 | shadow window 64→8 选 2 | 工艺库细节 |
| RQ14 | 三推翻候选+失败 workload | Alternatives 汇总 | — |
| RQ15 | commit 双视角+入口检测 | WAW merge 不 forwarding | — |


---

# Part I — Performance Foundations

> 每个 Architecture Node 按 **11 字段模板**展开：① Interview Entry ② Core Conclusion ③ Problem ④ Performance & Correctness Model ⑤ Current Design ⑥ Interaction（≥3 Node，真实因果边）⑦ Alternatives ⑧ Tradeoff & Saturation Point ⑨ Proof（含九步诊断闭环，走不通 = PARTIAL）⑩ Interview Follow-up Graph（≥2 层）⑪ Interview Hook。RTL 细节一律指向 Part III（生成后互链）。**模板是问题清单不是答案清单**：某字段无可靠依据时写 OPEN / PARTIAL + closure path，不补 generic answer（Evidence Discipline，见 0.8）。

# 2. Demand, Outstanding & Visibility（V1 / V2 / V3）

> **本章核心问题：Controller 要看到多少 request 才能喂满 DRAM？**
> 供给侧三 Node：V1 上游能供给多少并发（Demand）；V2 scheduler 能看见多少（Visibility）；V3 以什么速率/代价进入（Admission / Credit / Backpressure）。重点不是介绍 XMU/CAM 模块，而是回答：outstanding 为什么有 saturation point？deeper CAM 买到的是 BLP、row hit 还是 reorder freedom？什么情况下继续加深已经无效？

## 2.1 V1 — Demand / Outstanding（CORE）

#### ① Interview Entry
- outstanding 多大才够？"太大增加 latency"是排队论推论还是实测？
- AFIFO 为什么能一物两用（跨时钟域 FIFO = outstanding buffer）？
- link node 数 96/224 怎么来的？
- write response 前移到 PA grant，收益发生在哪一层？

#### ② Core Conclusion
[MODEL] outstanding 是 Demand 侧的并发供给窗口：DRAM 的长延迟（tRC/tRFC/tRCD）必须靠其他 bank 的并发命令填充。
[口径] 上游没有提供足够 work → scheduler 再好也落入 **idle_no_request**（V1 的症状）；"有 request 但进不来"属于 **V3 Admission**（blocked_admission），不是 V1 Demand。
[RTL] 本项目：XMU AFIFO 一物两用（CDC + outstanding）；读侧 link list/link node 即 reorder buffer（node 索引 = SRAM 地址，node 存 AXI 元数据）；写侧 BRESP 在 PA grant 即回（数据收齐是送 PA 的前置条件）。

#### ③ Problem
供给并发不足 → 机会链第一环（Demand）断掉；供给过剩 → queueing latency 上升无 BW 收益。需要回答"多大才够"与"在哪里停"。

#### ④ Performance & Correctness Model
- 需求侧并发直觉 [MODEL]（first-order sizing，非项目精确定标公式）：**N_outstanding ≈ λ_req × L**（λ_req = request throughput，L = average request latency）；带宽形式 ≈ BW × Latency / Bytes_per_request。Bytes_per_request / burst distribution / service latency 变化大时须用 workload-specific simulation / measurement（定量缺口 X-P1-07）；
- **link node 容量公式 [RTL]**：node 数 = CTL_CAM_DEPTH × CTL_CAM_BURST_SIZE / 2 + 补偿值（按平均每 entry 装 2 条命令折算；LPDDR6 CAM32 / HBM4 CAM96 → 补偿 32，HBM3 CAM64 → 补偿 64；交叉验证 32×4/2+32=96、96×4/2+32=224）；
- **包型瓶颈 [RTL]**：大包（≥4 sub-cmd）瓶颈在 node 侧，小包（≤2）瓶颈在 CAM 侧；补偿值加大 → 在途更多、攒批效率↑，latency 与面积↑；
- Correctness 侧：同 ID 必同链（刚性）；outstanding 计数是 AXI 反压的依据。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- XMU ostd buffer 满则反压；AFIFO 兼 CDC；
- 读 link list 32 条：同 ID 必同链；list 不够时允许混挂（换容量，避免加链的面积/时序代价）——混挂代价 = head-only 释放的 HOL，发生条件 = 在途 ID 数 > 32；
- AW 来 W 不来：AXI 无时间约束，协议无超时——系统 contract 兜底；后果 = 该 port AW ostd 占满 → **单 port 自饿**（PA 仲裁不锁定无请求 port，其他 port 不受影响）；不防御的理由 = 等 W 收齐才收 AW 会损失流水重叠；
- BRESP 前移 + outstanding FIFO 保序。

#### ⑥ Interaction
→ **V2**（供给决定可见性）；→ **DP2**（node 容量 = 读返回 reorder 深度）；→ **C1**（同 ID 同方向保序语义）；→ **O1**（fifo_full / ostd 观测）；← Host/NoC 流量形态 [INFERENCE]。

#### ⑦ Alternatives
- per-ID FIFO vs **link list**（选 link list：node 存元数据、索引即 SRAM 地址，容量随 CAM 折算，无需独立 ID 表）；
- BRESP 在写入完成后回（牺牲上游流水重叠，收益是掉电语义简单 → 1-I-01）；
- 硬件超时防死锁（不做：系统 contract 兜底 + 不污染主通路）。

#### ⑧ Tradeoff & Saturation Point
outstanding 加深收益递减为 [MODEL] 推断：demand 充足、NoC latency 可隐藏时，加深的边际收益趋于下降、queueing latency 上升；具体饱和点与 BW/latency 曲线无项目数据（1-P1-14 / 1-Q-02 [TODO-MEASURE]）；失败场景：单 ID 独占 list（list 不可复用但 head 持续推进，不阻塞自身）。

#### ⑨ Proof（含诊断闭环）
- sweep：outstanding depth → BW / P99 曲线 [TODO-MEASURE→X-P1-07]；
- 运行时 [RTL O1]：ostd 计数（dbg_obv，V1 侧）；lpr/tpw fifo_full 电平（V3 侧证据，交叉引用）；
- 诊断闭环（V1 只管 Demand；Admission 证据归 V3）：Symptom（idle_no_request 高）→ Observable（**Ch18 authoritative inventory 已确认 request-arrival / queue-empty / demand-occupancy 无 direct RTL observable** [TODO-MEASURE→X-P1-07]；可用证据 = ostd 间接证据 + arrival/occupancy trace/model）→ Hypothesis（上游 supply 不足 / outstanding depth 不足）→ Knob（ostd depth / upstream concurrency）→ Experiment（outstanding sweep + arrival/occupancy trace）→ Conclusion（Demand 是否为瓶颈）。
- 边界注记：fifo_full / credit==0 是 V3（Admission）证据，不得作为 V1 判据。

#### ⑩ Interview Follow-up Graph
- why：为什么 AFIFO 能兼任 outstanding buffer？（CDC 与缓冲都是"深度换时序"）
- double：outstanding 翻倍 → 饱和点判断？
- workload：大包/小包 mix 下 node 与 CAM 谁先满？（→V2 burst packing）
- protocol：HBM 双 PC 对 outstanding 的拆分？（→RQ12）
- failure：AW/W 悬挂的自饿边界？（→Ch9 liveness）
- redesign：BRESP 点后移的代价？（→C3）

#### ⑪ Interview Hook
**Concept Hook**："我会先区分'真的没有 work'和'有 work 但进不来'：前者是 V1 Demand（idle_no_request），后者才是 V3 Admission（blocked_admission，证据是 fifo_full / credit）。这两类混在一起，很容易误判 controller 的瓶颈。"


## 2.2 V2 — Scheduler Visibility（CORE）

#### ① Interview Entry
- 为什么 CAM 是 32/64/96，不是 16 / 256？
- 为什么 global CAM，不用 per-bank queue？
- burst=4 买到什么？"等效 256 commands"是什么口径？
- 入口冲突为什么 Pending 阻塞所有后续、不允许 bypass？
- CAM 已经很深，为什么 BW 还是上不去？

#### ② Core Conclusion
[MODEL] CAM 深度 = scheduler visibility 窗口，决定 row-hit opportunity、BLP opportunity 与 reorder freedom 的上限——mapping/scheduler/policy 只能在看得见的请求里工作。
[RTL] 本项目 global 全相联 CAM，深度 32/64/96（随协议/bank 配置）；每 entry burst 打包 4 条同 page 命令。
[RTL·口径] **双口径**：等效 256 = storage capacity 口径（64 entry × 4）；调度可见性（priority/aging/credit/提名）以 entry 为单位——加深买到的首先是可见 entry 数，不是命令数。

#### ③ Problem
scheduler 每拍只能从 CAM 内容里提名候选——visibility 不足时，L5 mapping 再好、S2 policy 再聪明也没有素材；visibility 过剩时，加深只买 queueing latency 与 compare 代价。要回答"多深才够、何时饱和"。

#### ④ Performance & Correctness Model
- 机会模型 [MODEL]：可见 entry ↑ → 覆盖不同 bank 概率 ↑（**BLP**）、同 row 命中 ↑（**L1 hit**）、可挑选余地 ↑（**S2 reorder freedom**）。收益大小取决于 bank entropy / row locality / burst packing / dependency(HOL) / available BLP / timing supply saturation / scheduler policy——不同 workload 的 saturation point 不同，当前无 depth sweep 数据，不预判 random / streaming 谁更早饱和 [TODO-MEASURE]；机制差异 [MODEL]：streaming 可能天然具备较强 locality / burst packing（较浅窗口即够）；random 的 row locality 低，但更深窗口可能继续增加 bank-level opportunity；
- 代价模型：入口 conflict compare（RAW/WAR，ID 无关）+ hit 判断规模随 entry 增长 → compare / reduction / routing 变大——面积持续增长、critical path / closure 越来越困难（**Fmax 非线性**）[RTL 经验 + P1]；queueing latency 随深度 ↑；
- HOL 模型：入口冲突 Pending（IPROC）阻塞后续**全部**入队命令——这是"单通路结构保序"的代价，换来不需要 forwarding；
- Correctness 侧：冲突检测在 CAM 入口完成是依赖模型（C2）的结构前提。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 全相联 CAM；深度按协议配置（LPDDR6 CAM32 / HBM3 CAM64 / HBM4 CAM96）；
- burst：同 page（静态等价判定）命令 merge 进单 entry（最多 4 条），共享 priority / CamAging / credit / entry lifetime；CCT 上表以 entry 整体、entry 内固定顺序逐条下发；
- 冲突检测分拍进行（时序代价：compare 不在一拍内完成 [RTL]，对 latency/throughput 影响 [TODO-MEASURE 3-P1-11]）；
- 调度可见性 = entry 粒度（3-P0-04 定稿）。

#### ⑥ Interaction
← **V1/V3**（供给与流入速率）；→ **L1/L2**（hit / BLP opportunity）；→ **S1/S2**（候选质量与选择自由度）；→ **T1**（timing-ready 命中率）；↔ **C2**（入口检测 / HOL）；→ **P1**（compare 面积/时序）；← **L5**（burst packing 质量）。

#### ⑦ Alternatives
- **per-bank queue**：静态划分——bank 倾斜 workload 一侧满一侧空、跨 bank hit 聚类能力差、每队列独立 aging 复杂；global CAM 用一个共享池换利用率 [RTL 取 global]；
- 更浅 CAM + 更深上游 outstanding：visibility 不前移到 scheduler 可见位置无效；
- 允许无冲突 bypass（缓解 HOL）：破坏单通路结构保序，复杂度换局部延迟 [OPEN：3-P1-08]。

#### ⑧ Tradeoff & Saturation Point
- 饱和判据：cam_outnum 高位驻留 ∧ bank-ready 候选数不再增加 ∧ hit rate 不再升 → 再深无效；
- 失效场景 [MODEL]：mapping（L5）不变、entropy 不降时，加深主要买 queueing latency 与 compare 代价；机会收益是否仍存在取决于上述七因素；
- 饱和点对比（random vs streaming 谁先饱和）：无项目数据，OPEN [TODO-MEASURE]（closure = depth×workload sweep 16/32/64/96/128）。

#### ⑨ Proof（含诊断闭环）
- sweep：CAM depth 16/32/64/96/128 × {random, streaming, stride} → BW / P99 / area / timing [TODO-MEASURE→X-P1-07]；
- 运行时 [RTL O1]：cam_outnum16/24/32 占用电平（top 侧累计）；burst packing rate [TODO-MEASURE 3-Q-02]；HOL Pending cycle loss [TODO-MEASURE 3-Q-03]；
- 诊断闭环：Symptom（blocked_no_candidate 高）→ Observable（CAM 占用低 = 入队瓶颈 / 占用高但 CCT 空 = 分布问题）→ Hypothesis（L5 mapping vs V3 admission）→ Knob → Experiment（stride sweep + bank-ready 分布）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- CAM64→128 何时几乎不再提高？（→ 饱和判据）
- 为什么不用 per-bank queue？（→ ⑦）
- CCT 单槽如何消费 visibility？（→ S1）
- burst 内第 1 条卡 timing，第 2~4 条能否独立 bypass？（[OPEN：3-I-04]——当前 entry 内固定顺序）
- HBM bank 很多，为什么仍可能跑不满？（→ T2 ACT supply / L2 消化能力，不是 visibility）
- 深度 × 面积 × Fmax 怎么折？（→ P1，非线性）

#### ⑪ Interview Hook
**Measurement Hook**："CAM depth 的甜点高度 workload-dependent：streaming 主要看 locality/burst 是否已经够，random 主要看 deeper window 是否还能增加 BLP——谁先饱和不能靠直觉，我会用 depth×workload sweep 判断。"


## 2.3 V3 — Admission / Credit / Backpressure（CORE）

#### ① Interview Entry
- credit 如何工作？grant 与归还的精确时点？
- 全链路 backpressure point 有几个？哪个最容易 throughput collapse？
- 水线为什么和 GSC 读写切换联动？
- credit 按 entry 还是按 command？有什么公平性问题？

#### ② Core Conclusion
[RTL] credit = PA↔CQ 之间按 entry 的流入控制：PA grant 消耗 credit，命令离开 CAM（调度下发）归还 credit；CAM 水线 set/clr 与 GSC 联动（write 攒批触发源之一）；反压链逐级传导且故障域隔离在 port（单 port 自饿不锁死 PA）。

#### ③ Problem
无限流入会撑爆 CAM / WDP 等共享缓冲；无水线则 write batch 无法形成（D1 失去触发条件）；流控粒度更细则计数 / 仲裁代价增加（幅度未量化，OPEN [TODO-DESIGN]）。

#### ④ Performance & Correctness Model
- blocked_admission 与 idle_no_request 必须分开归因：**有 request 但进不来**（credit 不足 / fifo 满）≠ 没有 request——这是 taxonomy v2 拆分 admission 的原因；
- 反压链模型：port AW ostd 满 → 单 port 自饿（故障域 = port）→ XMU 反压 → 上游；DFS / clock gate 是唯二反压 XMU 的全局场景（→G1）；
- collapse 候选来源 [MODEL]：shared resource saturation 是 throughput collapse 的候选来源；哪一级真正最敏感取决于 resource lifetime / release point / backpressure fan-out / workload——需 [TODO-MEASURE] 与后续 Node cross-check（候选：CAM / WDP / link node；单 port 资源自饿不扩散 [RTL]）；
- credit 粒度模型：entry = 1~4 command，小 request 占 entry 少 → 单位 time 获得更多 entry 容量（command capacity 不均）[RTL 已知，量化 OPEN：3-P1-06]。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- credit 生命周期：grant 消耗 → 命令离开 CAM 归还；配置随 CAM 深度；
- 水线：CAM 占用 set/clr 阈值触发 GSC 方向切换（迟滞防乒乓）；
- 观测：PA credit 进 dbg_obv [RTL]；lpr/tpw fifo_full 电平/计数 [RTL]。

#### ⑥ Interaction
← **V2**（CAM 剩余空间决定 credit 供给）；→ **V1**（反压链终点）；→ **D1**（水线 = write batch 触发）；↔ **S3**（QoS 决定谁获得 admission）；→ **DP1**（WDP fetch FIFO 节奏，满则 head-block）。

#### ⑦ Alternatives
- **credit per command** [MODEL]：可能提供更精细的容量 / 公平控制；其 RTL complexity / counter width / compare cost / PPA impact 当前未量化——OPEN [TODO-DESIGN]（必要时 [TODO-MEASURE]），不预设"代价翻倍"；对照 **per entry**（本项目 [RTL]，已知代价 = ⑧ 的容量不均 [OPEN：3-P1-06]）；
- **pure ready/valid handshake（无 credit）**：合法 alternative，是否适合当前 PA↔CQ 接口尚未完成系统分析——OPEN [TODO-DESIGN]；
- 多套独立 credit（per-class）：与 QoS 交叉后的复杂度影响 [MODEL]；当前用共享 credit + QoS 提名序解决 [RTL]。

#### ⑧ Tradeoff & Saturation Point
- credit 粒度 vs 计数代价；水线阈值 = write latency 与 switch 频率的折中（→D1 的 sweep 复用）；
- 失效场景：credit 数 ≠ CAM 深度配合失当 → 永久少量空转或假满；clock gate 场景的反压边界 [TODO-RTL：DM-P2-02 联动]。

#### ⑨ Proof（含诊断闭环）
- 运行时 [RTL O1]：credit（dbg_obv）、fifo_full 电平、exp_gpr/gpw 饥饿健康度（应 ≈0）；
- sweep：水线阈值 × GSC 参数联合 sweep（→D1 复用）[TODO-MEASURE→X-P1-07]；
- 断言：credit 守恒（grant 消耗 + 归还 = 常数；conservation 检查 → 各 Node Proof）；
- 诊断闭环：Symptom（admission 类 blocked 高）→ Observable（credit 0 / fifo_full）→ Hypothesis（下游不放行 → V2 出口堵塞 or WDP 满）→ Knob → Experiment → Conclusion。

#### ⑩ Interview Follow-up Graph
- credit 翻倍会怎样？（→ ⑧ 失配场景）
- entry vs command 粒度的公平性量化？（[OPEN：3-P1-06]）
- 水线阈值 sweep 与 GSC 参数谁主导？（→ D1）
- clock gate / DFS 时反压链如何收敛？（→ G1）
- 低 QoS 请求来自高优先 port，谁压谁？（→ S3 / RQ10）

#### ⑪ Interview Hook
**Concept Hook**："把 no-request 与 blocked-admission 分开后，诊断时才能区分'没有 work'（V1）和'有 work 但进不来'（V3）——这是 taxonomy v2 必须拆 admission 的原因。"


---

# 3. Locality & Parallelism（L5 / L1 / L2 / L3）

> **本章核心问题：如何在 Row Locality、Bank Parallelism、BG Parallelism 之间找到最优点？**
> 推导主线：workload → address entropy → bank/BG 分布 → row hit → ACT/timing 压力 → BW——不是描述 mapping bit，而是从负载几何推出性能形态。L4 Page Policy 归 Ch4（Scheduling 侧）。

## 3.1 L5 — Address Mapping / Workload Geometry（CORE）

#### ① Interview Entry
- mapping 怎么调优？你先报什么——位图还是指标？
- 为什么是 {row, cs, ba, col, bg, col}？换 RBC / XOR hashing 会怎样？
- stride=4KB 的 workload 落在哪些 bank？不用 simulation 能判断吗？
- mapping 为什么放在 PA grant 点（CAM 入口），不放更前 / 更后？
- 非 2^n 容量（如 6GB）怎么处理？

#### ② Core Conclusion
[RTL] 当前实配位图 **{row, cs, ba, col, bg, col}**：col[2:0]=[2:0] / bg0=[3] / ba[1:0]=[5:4] / bg1=[6] / col[5:3]=[9:7] / cs=[10] / row=[11+]（UIF 坐标，1 LSB = 64B）；核心形态 = **BG 两位拆开夹住 BA 的中段交织**。
[MODEL] 该配置的选择目标 = **random + linear 双负载下的整体 BW**（两硬指标 + pattern 纪律，见 ⑨）；"整体最优"只有取舍依据、无 sweep 实测支持——最优性 OPEN [TODO-MEASURE]（不继承 legacy "overall optimal" 断言）。

#### ③ Problem
mapping 是 workload geometry 与 DRAM 几何的耦合器：它同时决定 row-hit 上限（L1）与 bank/BG 并行度上限（L2/L3），且自由度受三重约束——颗粒容量位宽、协议钉死位、AMAP 单一配置。配错不是慢，是非法地址。

#### ④ Performance & Correctness Model
- [RTL] **page 大小 = 2^(col 总位数) × 每 col command 数据包大小，与 row[0] 位置无关**（例：DQ16/BL16 → 32B/包 × 64 包 = 2KB/page）；row[0] 之下的 bg/ba/cs 是独立 bank/rank 选择字段——顺序流以"每 bank 8 连发"方式扫描整页；
- [MODEL] **stride 通式**（stride = 2^k × 64B，冻结低 k 位）：k≤3 → bg0/ba/bg1 仍在滚动（bank 并行照常）；k=6 → 仅 bg1 滚动（BG0/BG2 的 ba0 两 bank 交替 + 每 bank col 顺序推进）；k≥7 → 全部 bank 字段冻结 → **单 bank 纯换 row（H≈1，退化为 ACT supply 受限）**；
- [降级口径] "k≥7 任何映射都救不了"→ 这是**当前固定位图下的几何性质** [MODEL]；是否存在 hashing / alternative mapping 能改变该 bank entropy，未做分析——OPEN [TODO-DESIGN]；
- [RTL] 本项目 workload 粒度 / stride 实际范围 **64B~512B（k≤3）**——全部落在 bank 并行照常区间；
- [MODEL] 推导链：workload entropy → 经位图 → bank 分布熵 / row 局部性 → ACT 频率与 BLP 可用度 → T2/T3 消化 → BW。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 实配位图见 ②；**AMAP 单一 source of truth**：col 位宽与映射位图共用同一组寄存器（1-P1-09 定稿）；映射运行中不可修改（改 = 排空 + 重配）；
- **映射点 = PA grant**：读写在 PA 前独立通道、PA 后合流，grant 点执行物理映射，物理地址写入 CAM entry 后逻辑地址弃用；
- **空洞交换**：非 2^n 容量（如 6GB 的 row[14:13]=11 组合）与更高位交换——保证逻辑地址连续 + 永不产生非法物理地址；
- **协议钉死位 / core 拓扑**：HBM PC 位在系统地址最高位、分流在 XMU 之前完成且被选中 PC 位被剥离（core 内不可见，2-P0-03 [RTL]）；DDR5 控制器视野内无 channel/sub-channel 位（交错由 SoC 决定；业内惯例 OPEN [TODO-SPEC：2-P0-02]）；
- channel 层归 SoC；rank/BG/BA/row/col 寄存器可配（DDR4 全可配 → 越新协议钉死越多）。

#### ⑥ Interaction
→ **L1**（决定 row-hit 机会上限）；→ **L2/L3**（决定 bank/BG 分布）；→ **D2**（cs 位位置 → rank 切换频率）；→ **T2**（ACT 供给需求由 miss 率决定）；→ **C2**（RMW 命中地址）；← **V2**（可见窗口内的 entropy 才能被利用）。Cross-check：O2 stride sweep / bank entropy 仿真；O1 ACT/col 命令计数。

#### ⑦ Alternatives
- **RBC（row 放低位）** [MODEL]：优化随机负载的 row 局部性，但顺序流在同一 bank 换 row——作为"单指标最优"的反例保留，不采用；
- **XOR / row hashing** [RTL 决策记录]：未采用——它解决 power-of-two 大 stride 的 bank 冲突热点，本项目 workload k≤3 不产生该热点；代价 = XOR 网络面积/时序 + 地址不可读的调试难度 + 与空洞交换逻辑叠加。开放分支：k≥7 热点真实存在的场景能否用 hashing 救 → OPEN [TODO-DESIGN]；
- **拓扑替代映射** [MODEL]：越新的协议地址位被钉死越多（HBM PC / DDR5 sub-channel），自由度向多 core 并行转移——"老协议靠映射换性能，新协议靠多 core 换性能"。

#### ⑧ Tradeoff & Saturation Point
- [MODEL] BG 位放太低 → 大 txn 拆到太多 bank、单 bank page hit 不足、白付 ACT；放太高 → BG 并行度浪费（串行暴露）；
- [RTL + MODEL] cs 位放高省 rank-to-rank 切换开销（data-bus / ODT / DQS），但浪费跨 rank 独立 bank state 的并行度；**cs 位置被 col/bg/ba 总位宽钉死在 [10]，不能单独调高**——要更大 rank 连续段只能加伪交织位或换更大 page 颗粒 [RTL]；
- [MODEL] 改映射的收益上限受 workload entropy 支配：entropy 不降、access pattern 不变时，单纯重排位图的收益有限。

#### ⑨ Proof（含诊断闭环）
- 验证框架：**两硬指标 + pattern 纪律**——① page hit rate（col 命中已开 row 比例；顺序流接近满 hit，random 达该负载理论上限）；② tCCD_S 满足占比（col 背靠背跨 BG 的比例）；纪律 = random + linear 两类、64B~512B 粒度、**一套映射同时服务两类负载**（只跑 linear 会选出偏科配置）；
- [口径·RTL] hit rate 与 tCCD_S 占比均需 per-command row/BG 状态——**RTL counter 推不出**（命令计数只有 mix），靠 trace / 模型统计（证据边界 → Ch18）；
- Closure：stride sweep 64B→MB → hit rate / row conflict / bank entropy / BG entropy / BW [TODO-MEASURE→X-P1-07]；"当前位图在双负载下最优"同一 sweep 关闭；
- 诊断闭环：Symptom（blocked_no_candidate 高 / ACT 供给受限）→ Observable（ACT/col 比、命令 mix [RTL O1]）→ Hypothesis（mapping entropy / stride 形态）→ Knob（位图）→ Expected（hit↑ / ACT↓）→ Side effect（BLP 分布变化）→ Experiment（stride sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 BG 两位拆开夹 BA？（顺序流滚动次序：同 bank 滚 col[2:0] 8 连发 → 翻 bg0 → 滚 ba → 翻 bg1）
- double：bg1 从 [6] 移到 [7] 会怎样？（每 BA 段从 16 条变 32 条，H 区间移动 → 3.3）
- workload：stride=4KB 落在哪？（BG0/BG2 的 ba0 两 bank 交替，每 bank col 每 2 拍 +1——k=6 行）
- protocol：HBM PC 位为什么 core 内不可见？（XMU 前置分流 + 位剥离 [RTL]）
- failure：非 2^n 容量配置错误会怎样？（非法物理地址——空洞交换的职责）
- redesign：什么时候值得引入 hashing？（k≥7 大 stride 热点真实存在时 [TODO-DESIGN]）

#### ⑪ Interview Hook
**Measurement Hook**："mapping 调优我先报指标和 pattern 集合，再报结论——一套映射必须同时服务 random 和 linear，只跑 linear 会选出偏科配置。"


## 3.2 L1 — Row Locality（CORE）

#### ① Interview Entry
- 什么叫 page hit？你的设计里有几个"page hit"概念？
- hit rate 在策略选择里扮演什么角色？它是唯一的决定因素吗？
- sequential traffic 一定要追求 row hit 吗？什么时候宁可牺牲？
- hit rate 怎么测？RTL counter 能给出吗？

#### ② Core Conclusion
[术语框·RTL 定稿（1-P0-08）] 全文三个 "page hit" 必须分立：① **page_match_next**（XMU→PA 信号）= 同 txn 相邻 sub-command 的**静态同 page 判定**，消费点 = PA 提升该 port 优先级、缩短拆分延迟；② **CAM burst 准入的"同 page"** = **静态等价**判定（多条同 page 命令 merge 进单 entry）；③ **CS page hit** = CCT 候选 bank 的 open row **动态命中**（BSC 状态）——FR-FCFS 里 FR 的本体。
[MODEL] row locality 的价值 = 用 col 命令摊薄 ACT 成本（tRCD+tRP）：hit rate 决定 miss 流量、进而决定 T2 的 ACT 供给压力。

#### ③ Problem
DRAM 的行缓冲语义使"先开行再连发"远优于"开行即关"——row locality 是把 DRAM bank 内部结构变成带宽的核心杠杆；但它与 BLP 存在摆位竞争（L5 的交织旋钮）。

#### ④ Performance & Correctness Model
- [MODEL] H_act = tACT / tCAS：一个 ACT 的代价需要 ≥H_act 条 col 命令摊薄（例 tCAS=2、tACT=8 → H≥4）——row locality 的量化下限与 3.3 的 H 模型共用了这一条；
- [MODEL] hit rate 是 locality / page-policy / hit-first policy 的**核心统计量之一**（策略只改变 hit/miss 的到达结构，不改变单次代价）；全局最优策略不能脱离 BLP / timing supply / QoS / direction 单独由 hit rate 决定；
- [口径] hit rate 无 RTL 直接观测（需 per-col row 状态）——trace / 模型统计；direct observable 边界 → Ch18 Table A/B [TODO-MEASURE→X-P1-07]。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- page_match_next 预判在 XMU（静态、同 txn 内），依赖与映射一致的 col 位宽配置（AMAP 单源）；
- burst 准入"同 page"为静态等价判定（不查 BSC）；
- 动态 hit 判定在 CQ/CCT 提名与 BSC 状态相与处（hit-first policy 的输入，→Ch4 S2）；
- page policy（open/close）是 locality 的调度侧执行器（→Ch4 L4）。

#### ⑥ Interaction
← **L5**（mapping 决定 hit 机会）；↔ **L4**（page policy 决定机会是否保留）；→ **T2**（miss → ACT 压力）；→ **S2**（hit-first 提名）；↔ **V2**（可见窗口内的 hit 才能用）；cross-check：O1 col/ACT 命令计数（hit 的命令面近似）、O2 hit rate 仿真。

#### ⑦ Alternatives
- **prefetch / read-ahead**：把 locality 换成带宽预取（受限于 V2 可见性与污染风险，本项目未采用为主手段 [INFERENCE]——具体 prefetch 行为 → Ch8 DP3 PF window）；
- **强制 open-page**（最大化 hit）vs **close-page**（最大化并行）→ 归 L4（Ch4）展开。

#### ⑧ Tradeoff & Saturation Point
[MODEL] hit rate 提升的收益在 ACT 供给不再是瓶颈时饱和（此后 T3/tCCD 接管）；random 负载下 hit 率有该负载理论上限（再调 mapping/policy 无益）；hit-first 提名的 P99 代价 → Ch4 S2。

#### ⑨ Proof（含诊断闭环）
- Closure：RowHitRate→BW 与 RowHitRate→P99 两张曲线 [TODO-MEASURE→X-P1-07]；hit rate 用 trace/模型统计（RTL counter 只给 ACT/col 近似）；
- 诊断闭环：Symptom（ACT/col 偏高、tRRD/tFAW blocked 占主导）→ Observable（ACT 计数/col 计数 [RTL O1]）→ Hypothesis（hit rate 低：mapping entropy / page policy / 可见窗口不足）→ Knob（L5 位图 / L4 策略 / V2 深度）→ Experiment（stride sweep + hit 统计）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么静态判定（①②）与动态判定（③）要分开？（时序位置与信息量不同：入口无 BSC 状态）
- double：hit rate 翻倍 BW 一定翻倍吗？（否——ACT 供给退出瓶颈后由 T3 接管）
- workload：random 的 hit 上限是多少？（由 entropy 决定，2.4 指标定义）
- failure：page_match_next 与映射配置不一致会怎样？（AMAP 单源消除该可能 [RTL]）
- redesign：hit 判定前移到 PA？（信息不足——PA 点无 BSC 状态）

#### ⑪ Interview Hook
**Counterexample Hook**："顺序流不一定追求 row hit——HBM bank 多到并行能掩盖 ACT 时，把位图偏向 BLP 反而更优；hit 与并行谁值钱由 H 区间决定（→3.3）。"


## 3.3 L2 — Bank-Level Parallelism（CORE）

#### ① Interview Entry
- locality 和 BLP 冲突时怎么找最佳点？
- 为什么"每 bank 4~8 条命令"是下限？
- HBM bank 那么多，为什么还是可能跑不满？
- bank 数怎么同时隐藏 tRC 和 tRCD？

#### ② Core Conclusion
[MODEL] **H 区间模型**：H = 切换到下一个 bank 前当前 bank 连续发送的 command 数。四条约束共同给出 H 的可行区间 [H_min, H_max]：H 太小 → 开太多 bank、ACT 压力大；H 太大 → BG 内命令占比过高（吃 tCCD_L）且无插队机会。**冲突时取舍原则：先保 locality 下限（每 bank ≥4 条），剩余位给 BLP** [定性规则，配合 2-P1-10 定稿推导]。
[RTL+经验] "每 bank 4~8 条（256B~512B）"为经验值 + H_act 解析支撑（tCAS=2 / tACT=8 → H≥4 吻合）——非 benchmark 定量结论。

#### ③ Problem
单个 bank 的服务能力被 tRC/tRCD/tCCD 钉死；BLP 用多个 bank 的流水重叠掩盖单 bank 长延迟——但 bank 数是有限资源，且使用它的代价是 ACT 供给（T2）与 hit 摊薄（L1）。

#### ④ Performance & Correctness Model（H 四约束 [MODEL·推导，2-P1-09/10 定稿素材]）
1. **BG 数隐藏 tCCD_L**：BGreq = tCCD_L / tCCD_S（通常 2）→ 每 command 平均间隔 tCAS = max(tCCD_S, tCCD_L / BGactive)；
2. **ACT 供给满足 column 消耗**：tACT = max(tRRD_S, tRRD_L/BGactive, tFAW/4) → **H × tCAS ≥ tACT，即 H_act = tACT / tCAS**；
3. **bank 数隐藏 tRC**：N_bank × H × tCAS ≥ tRC → **H_bank = tRC / (N_bank × tCAS)**——bank 越多，bank 位越可往低放；
4. **bank 数隐藏 tRCD**：Q × H × tCAS ≥ tRCD → Q = tRCD / (H × tCAS)。
最佳摆位 = 先算 [H_min, H_max]，区间内按负载取向选位。bank entropy 决定并行度的实际可用率（可见窗口 V2 内的不同 bank 数才是有效 BLP）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- N_bank / BG / BA 划分由协议与颗粒配置决定（32 banks/PC 与 64-bank 配置 [RTL]，见 Ch15 面积表）；
- 交织形态 = L5 位图（BG 两位夹 BA）；256B txn 整笔落单 bank 全 hit（4 或 8 条），BG 归属由 txn 基地址经固定位图自然决定、跨 txn 随机（非 hash/routing，2-P1-07 定稿）；512B txn 拆 2 个 BG（bg 放 addr[3] 类中段位）；
- BLP 的消费端：CCT per-bank 单槽提名（→S1）+ BSC per-bank FSM（→T1）。

#### ⑥ Interaction
← **L5**（bank 分布）；← **V2**（可见 bank 数 = 有效 BLP）；→ **T2**（tRRD/tFAW 消化 ACT 压力）；→ **T3**（多 bank col 交错）；→ **M3/M4**（REFpb/RFM 占用 bank）；cross-check：O1 bank active 分布 / ACT 计数（[MODEL only] 细分）。

#### ⑦ Alternatives
- **bank interleaving 深度加大**（位图把更多位给 bank）vs **保留 locality**——即 H 区间的两端 [MODEL]；
- **per-bank queue**（消费 BLP 的另一架构）→ 已在 V2 ⑦ 讨论为 not adopted [RTL]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] BLP 饱和点：当 T2 的 ACT 供给（tRRD/tFAW）先于 DQ 饱和时，再加 bank 并行无收益（HBM bank 多仍可能跑不满的两个原因之一；另一个是 V2 可见性不足）；Q/H 摆位失衡时单侧浪费。

#### ⑨ Proof（含诊断闭环）
- Closure：4~8 commands/bank 最优点 sweep（1/2/4/8/16/32）[TODO-MEASURE→X-P1-07]；H 区间用真实 timing 参数代入验证；
- 诊断闭环：Symptom（BLP 利用不足 / ACT blocked 高）→ Observable（ACT/col、命令 mix、bank-ready 分布 [MODEL]）→ Hypothesis（H 摆位 / 可见性 / ACT 供给谁先饱和）→ Knob（L5 位图 / V2 深度）→ Experiment（H sweep × workload）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 tRC 由 N_bank 隐藏而不是靠更深队列？（tRC 是 bank 物理时间，只能用别的 bank 填）
- double：bank 数翻倍 H_bank 减半意味着什么？（bank 位可更低 / 更倾向 BLP）
- workload：random 下有效 BLP 怎么算？（可见窗口内不同 bank 期望数）
- protocol：HBM 双 PC 对 BLP 的拆分？（每 PC 独立 core → BLP 计数域变化 → RQ12）
- failure：全部请求落同一 bank 会怎样？（T2 ACT 链 + 单 bank tRC 直接暴露）
- redesign：CCT 每拍提名多 bank？（S1 单槽的消费瓶颈讨论）

#### ⑪ Interview Hook
**Tradeoff Hook**："BLP 和 locality 用的是同一批地址位——H 区间就是这两位的租约合同；先保 locality 下限，剩下的位全租给并行。"


## 3.4 L3 — Bank-Group Parallelism（CORE）

#### ① Interview Entry
- BG 交织为什么能"白吃"带宽？
- bg0 和 bg1 两位为什么拆开放、还要夹住 BA？
- tCCD_S / tCCD_L 怎么影响调度？
- REFsb 和 BG 是什么关系？

#### ② Core Conclusion
[RTL] 当前形态：**bg0=[3] 与 bg1=[6] 拆开、中间夹 ba[1:0]**——顺序流滚动次序 = 同 bank 滚 col[2:0]（8 连发）→ 翻 bg0 → 滚 ba → 翻 bg1；每 bank 连续段 8 条（512B）、每 BA 段 16 条。
[MODEL] BG 并行的价值 = 跨 BG 命令适用 tCCD_S（短）而同 BG 适用 tCCD_L（长）——BG 交织把"便宜的背靠背"用满，是 DQ 连续性的重要供给（streaming 下 tCCD 主导时的关键并行度）。

#### ③ Problem
tCCD_L/tRRD_L 表明同 BG 的 bank 共享资源（局部命令/激活路径）；BG 交织把命令流分散到 BG 边界上，是零面积换取 timing 余量的纯映射手段——但过度拆分牺牲 L1。

#### ④ Performance & Correctness Model
- [MODEL] tCAS = max(tCCD_S, tCCD_L / BGactive)：BGactive 个 ready BG 可摊薄 tCCD_L；
- [MODEL] BG 位放太低 → 大 txn 拆到太多 bank（hit 不足）；放太高 → BG 并行浪费（2.3 判断口诀）；
- [SPEC→接口] REFsb = pb 路径的跨 BG 变体（DDR5）：目标 = 所有 BG 的同 index bank（→M2）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 交织形态见 ②；256B txn 不拆 BG（整笔单 bank 全 hit）、512B txn 拆 2 BG 且 BG 间可 tCCD_S 背靠背；
- BG 归属由 txn 基地址经固定位图自然决定（跨 txn 随机，非 hash）；
- BG 间 / BG 内 timing 由 per-BG 计数器的 s / l 两系列承载（→T1/T2；s=跨 BG、l=同 BG，与 JEDEC _S/_L 语义一致，5-P0-02 定稿）。

#### ⑥ Interaction
← **L5**（bg 位位置）；→ **T3**（tCCD_S/L 供给）；→ **T2**（tRRD_S/L）；→ **M2**（REFsb 跨 BG 同 index）；↔ **L2**（同属 bank 维度并行）；cross-check：O1 命令 mix 的 BG 面分布（[MODEL only] 细分）。

#### ⑦ Alternatives
- BG 位集中低位（纯 BG 优先）vs 集中高位（纯 bank 优先）vs **拆开夹 BA**（当前 [RTL]）——三者即 L2/L3 权衡的三种摆位；
- 更深 BG 交织依赖更大 txn（管理代价上升 [MODEL]）。

#### ⑧ Tradeoff & Saturation Point
[MODEL] BG 并行的收益在 BGactive 数足够摊平 tCCD_L 后饱和；BG 数少的协议（部分 DDR4 无 BG）此 Node 退化——L3 为协议相关 Node。

#### ⑨ Proof（含诊断闭环）
- 指标：tCCD_S 满足占比（跨 BG 背靠背比例；RTL counter 推不出，trace/模型 [口径]；direct observable 边界 → Ch18 Table A/B）；Closure：交织位摆位 sweep × {random, linear} [TODO-MEASURE→X-P1-07]；
- 诊断闭环：Symptom（tCCD_L blocked 占比高）→ Observable（命令 mix / BG 面分布 [MODEL]）→ Hypothesis（BG 交织不足）→ Knob（bg 位摆位）→ Experiment（sweep + tCCD_S 占比）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么拆开两位而不是集中？（滚动次序让 8 连发 → BG 翻转 → BA 滚动形成层次化并行）
- double：BG 数翻倍会怎样？（H 区间整体移动；tCCD_L 摊薄上限变化）
- workload：stride=4KB 时 BG 表现？（k=6：仅 bg1 滚动，BG0/BG2 交替——L5 通式表）
- protocol：哪些协议有 BG？（DDR4（2BG 起）/ DDR5 / HBM3/4；LPDDR 视代际——[SPEC]，具体 per-protocol 布局 → Memory_Protocal.md）
- failure：BG 位与容量空洞交换冲突？（空洞交换在 row 高位，不干扰 BG [RTL]）

#### ⑪ Interview Hook
**Tradeoff Hook**："BG 交织几乎是零硬件面积的并行度旋钮——它只是把同一条命令流换到更便宜的 timing 类别（tCCD_S）。"

# 4. Command Opportunity & Reordering（S1 / S2 / S3 + L4）

> **本章核心问题：当大量 request 已经可见时，如何挑出"最值得现在执行"的 command？**
> 判定语言：**Eligible**（CCT 上表候选）→ **BSC-ready**（bank FSM ∩ timing counter）→ **Direction-legal**（GSC）→ **Executable**（三者齐备，进入 final arbitration）→ **Selected**（FSC winner）→ **Issued**（下发 + state/counter update）——"能不能调"（CQ）与"能不能发"（BSC+GSC legality）是正交判断，串联后相与 [RTL·六层口径，权威定义 → Ch14.3]。

## 4.1 S1 — Command Eligibility（CORE）

#### ① Interview Entry
- 什么叫 eligible？什么叫 executable？为什么必须分两个词？
- 为什么每 bank 只提名一条（CCT 单槽），不是两条？
- CCT 上表后为什么不可撤回？换来了什么？
- CCT 空意味着什么 blocked reason？

#### ② Core Conclusion
[RTL] 命令从 CAM 到 CCT 经**三层筛选**：① bank filter（CAM→bank 分组，不截断）→ ② priority filter（同 bank 内选高优先级）→ ③ oldest filter（同优先级选最老）。CCT 为 **per-bank 单槽**（RD/WR 各一张，读方向只见 RD CCT），**上表后不可撤回、直到发送**——用灵活性换时序收敛的典型决策。
[口径] CCT 只反映"提名"（eligible），命令下发还需 BSC timing 检查（executable 判定在 Ch5 T1）。

#### ③ Problem
每拍最终只能发有限命令（DDR/LPDDR 单条、HBM row+col 双发），必须从可见集合收敛到 per-bank 候选——S1 是 visibility（V2）到 selection（S2）之间的"提名"层：粒度是 bank（bank 间并行天然保证），bank 内收敛到单条。

#### ④ Performance & Correctness Model
- [MODEL] 提名层的时序位置决定它是 hit 判断的消费端（动态 BSC 状态相与，→L1 术语③）；
- [RTL] CCT 更新时机 = 新命令进 CAM 或老命令已发送，否则保持不变（不可撤回的直接后果）；
- [MODEL] 单槽的机会成本：bank 内第二优先命令需等在位候选发送——expired GPR 由此产生"等在位候选发送 + 方向解锁"的两级等待（→S3、S3-P1-01）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 三层 filter 流水线（①②③如 ②）；
- CCT per-bank、深度随 bank 数（不是任意值）；进入 CCT 的候选不再带优先级语义（提名竞争只发生在 priority filter——CCT 层无新旧竞争，4-P0-03/04 定稿）；
- CS 侧口径 [RC-1 六层]：Eligible（CCT 上表）→ BSC-ready（bank FSM ∩ counter）→ Direction-legal（GSC）→ Executable（三者齐备）→ Selected（FSC）→ Issued（下发 + counter load + FSM update + CCT release）——authoritative 定义见 Ch14.3 / Ch9 C3。

#### ⑥ Interaction
← **V2**（CAM 内容与 burst entry 粒度决定可提名集）；← **C2**（依赖拦截后的可见集）；↔ **T1**（BSC ready 相与）；→ **S2**（FSC 仲裁的输入）；→ **T3**（col 密度）；cross-check：O2 no-candidate 归因（CCT 空 = blocked_no_candidate）。

#### ⑦ Alternatives
- **CCT 双槽 / 多槽**（bank 内同时持两条候选）：缓解在位阻塞，代价 = 命令生成器时序与 CCT 面积——当前不做 [RTL 决策记录]；量化对比 OPEN [TODO-DESIGN]；
- **CCT 可撤回**（新更高优先候选可替换在位者）：撤回造成命令生成器时序问题 [RTL]——未采用；
- per-bank queue 直连（无全局 CAM）→ V2 ⑦ 已析。

#### ⑧ Tradeoff & Saturation Point
[RTL+MODEL] 单槽 + 不可撤回 = 时序收敛与验证简单的代价是在位阻塞；[MODEL] 饱和判据：CCT 空且 CAM 非空 = 提名层问题（V2 分布 / mapping），CCT 非空但 FSC 无输出 = 下游问题（T1/S2/D1）——两者是 RQ2 诊断链的分界证据。

#### ⑨ Proof（含诊断闭环）
- Closure：CCT 单槽 vs 双槽的 BW/时序/面积对比 [TODO-DESIGN→必要时 MEASURE]；CCT 占用分布 trace；
- 诊断闭环：Symptom（blocked_no_candidate 高）→ Observable（CCT 空率、CAM 占用 cam_outnum [RTL O1]）→ Hypothesis（可见性不足 / mapping 集中 / 依赖拦截）→ Knob（V2 深度 / L5 位图）→ Experiment（occupancy trace + stride sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么单槽不可撤回能换时序？（命令生成器对稳定输入的流水化）
- double：双槽会怎样？（在位阻塞缓解 vs 时序/面积代价 [TODO-DESIGN]）
- workload：全部命令集中一个 bank？（CCT 成为该 bank 串行点）
- protocol：HBM 每拍 row+col 双发对 CCT 的要求？（row/col 候选通道独立 [SPEC]→RQ12）
- failure：expired GPR 撞上 timing-blocked 在位候选？（等在位发送 + GSC 方向解锁两级保证 [RTL]，严格 bound → S3-P1-01）
- redesign：提名与 timing 判定合并成一层？（正交性丧失，各自演进/验证困难 [RTL 设计理由]）

#### ⑪ Interview Hook
**Concept Hook**："eligible 和 executable 是两个正交判断——CQ 决定能不能调，BSC 决定能不能发，相与之后才是可执行命令。这两个词分开，调度器的验证都能少一半。"


## 4.2 S2 — Command Selection / Reordering（CORE）

#### ① Interview Entry
- 为什么必须 reorder？FCFS 到底差在哪？
- hit-first 一定最好吗？它的 P99 代价多大？
- hit 流会不会饿死 miss 流？
- FSC 为什么 Col > Row？ACT 为什么压过 PRE？
- 什么叫确定性模式？什么时候用？

#### ② Core Conclusion
[RTL] 策略 = **可配排序的 hit 优先（FR-FCFS-derived）**：两种模式——**priority first**（expired GPR > HPR hit > HPR miss > LPR/TPW hit > LPR/TPW miss）与 **page hit first**（expired GPR > HPR hit > **LPR/TPW hit** > HPR miss > LPR/TPW miss）；expired GPR 两模式恒第一。"page hit 全局最高"不是无条件规则，是 page hit first 模式的提名序（4-P0-03 定稿）。FSC 仲裁序：**Col > Row；Col 内 RR；Row 内 critical ref > ACT > PRE > non-critical ref**。
[命名] "FR-FCFS"作为学术名不完全精确（已含 QoS/aging/双模式/CCT admission），更准确是 **FR-FCFS-derived policy**（legacy 4-P1-01 口径）。

#### ③ Problem
到达序与 DRAM 效率序天然不相关：严格 FCFS 放弃 BG 交织收益（连续到达可能同 bank/同 BG，重排后可 tCCD_S 背靠背）；reorder 的收益来源 = page hit（省 tRP+tRCD）× BG 交织（tCCD_L−tCCD_S）× 批处理（摊薄 turnaround），代价 = 到达序被打乱带来的延迟方差与公平性。

#### ④ Performance & Correctness Model
- [SPEC 数例·量级] DDR4-3200：一次 row hit 省约 30+ns（tRP+tRCD），一次 tCCD 约 1.5ns——数量级差距是 hit-first 的根本依据；
- [MODEL·条件式] 其他因素相近时，hit rate 越高、hit-first 可利用的 locality opportunity 越多；全局收益仍受 BLP / timing supply / fairness / workload distribution 影响——不宣称无条件单调；
- **hit 风暴与 miss 自愈（降级口径）** [INFERENCE]：column 执行期间存在可下发 row 命令的 tCCD gap，miss 的 ACT 可用间隙下发、row open 后升级为 hit——**这是缓解倾向，不是 correctness guarantee**：能否发 ACT 还依赖 tRRD/tFAW、bank state、CCT occupancy、direction、candidate availability；真正的 anti-starvation 依赖 aging/expired GPR + critical + direction progress（→S3，严格 bound = S3-P1-01 OPEN）；
- [MODEL] hit-first 的 P99 / 公平代价（miss 流排队延迟上升）；确定性模式（提高切换频率 + 去多优先级 + oldest-first）用平均性能换可预测上界。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 双模式可配（② 的两个优先序）；oldest filter 在延迟确定性模式下使全链退化为 oldest-first；
- FSC：Col > Row（根因：col 产生数据传输，保证 DQ 不空转）；ACT > PRE（需求驱动优先于服务性操作——ACT 的触发源是 CCT 上真实 miss，PRE 之后不一定有跟随）；critical ref 经 mask ACT+Col 打破常态序（→M2）；
- 每拍命令数由协议钉死：DDR/LPDDR CA 复用 → 单条；HBM row/col 线独立 → 可同拍 row+col（FSC 可流水化双发）[SPEC→架构]。

#### ⑥ Interaction
← **S1**（eligible 候选）+ **T1**（BSC ready）；← **L1**（hit 判定）；← **S3**（优先级注入）+ ← **D1**（方向合法）；→ **T3/DQ 连续性**；→ O2 blocked_policy 归因；↔ **M2**（维护命令插队）。

#### ⑦ Alternatives
- **严格 FCFS**：放弃 BG 交织——反例保留 [MODEL]；
- **纯 priority（无 hit-first 模式）**：延迟 SLA 敏感场景（priority first 即此形态）；
- **确定性模式**（oldest-first + 高切换频率）：实时/等时流量的可预测上界 [RTL 可配]；
- **adaptive policy 切换**：按负载动态选模式——未实现，OPEN [TODO-DESIGN]（legacy 4-I-04 的 open 分支）。

#### ⑧ Tradeoff & Saturation Point
[MODEL] hit-first 收益在 hit rate 趋零（纯 random）时消失，此时 close page + ACT 分散（→L4）更优；policy bubble（eligible 且 ready 但未选）是本 Node 的专属损失类（taxonomy blocked_policy）。

#### ⑨ Proof（含诊断闭环）
- Closure：priority-first vs page-hit-first 的 BW / avg latency / P99 / starvation time 对比 [TODO-MEASURE→X-P1-07]；RowHitRate→BW 与 →P99 两张曲线同 sweep；
- 诊断闭环：Symptom（blocked_policy 占比高）→ Observable（命令 mix、方向状态 [RTL O1]）→ Hypothesis（双模式配置 / 提名序与到达结构不匹配）→ Knob（模式切换）→ Experiment（A/B + P99 统计）→ Conclusion（P99 为 [MODEL only] 观测，声明边界）。

#### ⑩ Interview Follow-up Graph
- why：为什么 expired GPR 在 priority filter 恒第一而不是迁队列？（晋升 = 队列内打标记，避免跨队列迁移的时序代价）
- double：两个模式间动态切换会怎样？（hysteresis 需求 + 抖动风险 [TODO-DESIGN]）
- workload：random 下还 reorder 吗？（收益转移：hit-first 无效，但 BG 交织/批处理仍有效）
- protocol：HBM 同拍 row+col 对 policy 的改变？（row 准备不再与 col 竞争拍 [SPEC]→RQ12）
- failure：hit 风暴 + ACT 供给不足？（自愈失效场景——回落到 aging 保底 [INFERENCE→S3]）
- redesign：把 policy 做成 per-bank？（配置维度上升，收益未知 [TODO-DESIGN]）

#### ⑪ Interview Hook
**Counterexample Hook**："hit-first 不是永远正确——random 下它免费也无用；而 delay-SLA 流量要的甚至不是快，是可预测。所以我把它做成两模式可配。"


## 4.3 S3 — QoS / Aging / Fairness（CORE）

#### ① Interview Entry
- QoS 的完整层级是什么？冲突时谁压谁？
- 低优先级请求怎么保证不被饿死？
- "优先级调度会降低整体性能"——怎么理解？
- QoS 和最大 BW 冲突时怎么办？
- Scheduler 管不管长期带宽保障？

#### ② Core Conclusion
[RTL] QoS 是**跨层设计，CQ 只是执行末端**：AXI QoS → Port 仲裁（优先级 RR + per-port 权重，第一级带宽/延迟分配）→ 队列结构（读：HPR + LPR/GPR 共享；写：单队列 TPW+GPR）→ CCT priority filter（双模式，→S2）→ CamAging → FSC。
[RTL] anti-starvation / liveness 机制 = **CamAging / expired GPR + CCT progress + direction progress**：低优先级命令 aging 计满 → **同队列内打标记晋升**（不迁队列），优先级压过 HPR，两模式恒第一；expired GPR 的推进依赖"在位候选发送 + direction 解锁"两级接力（4-P0-04 [RTL]）。
[MODEL] 这些机制提供 **progress path**；能否推出严格 worst-case cycle bound 取决于 timing legality / slot release / direction progress 的联合条件——strict bound 未证明（S3-P1-01 OPEN）。**不宣称"严格等待上界已经保证"。**
[RTL·边界声明] 本调度器实现**短期延迟优先级，不是长期带宽保障**——多 master 保底带宽由 port 仲裁权重 / NoC 带宽整形承担；**QoS 的边界画在 port 仲裁，Scheduler 不背长期公平的锅**（边界本身是架构决策）。

#### ③ Problem
多个 master、多类流量（延迟敏感 / 吞吐 / 实时）共享一个 DQ：优先级注入 ordering 收益，但任何优先级机制都可能制造饥饿——需要跨层分工：谁负责短期延迟、谁负责长期公平、谁负责兜底防饿死。

#### ④ Performance & Correctness Model
- [MODEL·金句] "优先级调度会降低部分命令的延迟，但会降低整体的性能"——优先级与效率（hit-first）在提名序上直接竞争（S2 双模式即为此存在）；
- [RTL] expired GPR 语义：超时前 GPR 与 LPR 同优先级；超时后压过 HPR（晋升在队列内部完成）；
- [MODEL] 防饿死双保险：① expired GPR 恒第一（确定性等待上界的主要来源）；② 优先级参与读写切换决策（write 长期饥饿触发 D1 切换）；
- [观测口径] P50/P99 无 RTL 直接观测（[MODEL only]，trace 后处理）——S3 的量化是诚实边界。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 四类队列属性 HPR / LPR / TPW / GPR；读侧 HPR 队列 + LPR/GPR 共享队列、写侧 TPW+GPR 单队列；
- CamAging 以 entry 为单位计时（burst entry 从首条进入起算 [RTL]，其公平性影响 OPEN：3-P1-06）；
- Port 仲裁：优先级 RR + per-port 权重；UIF 侧 hpr/lpr/gpr/tpw *_accepted 计数 + CQ 侧 exp_gpr/gpw_executed（饥饿健康度，应 ≈0）[RTL O1]。

#### ⑥ Interaction
← 上游 AXI QoS / port 结构（C1 侧）；→ **S2**（提名序）；→ **D1**（write 饥饿触发切换 / expired write）；↔ **V3**（admission 的 QoS 分配）；→ O1（QoS 分布计数、exp 健康度）；→ RQ10（Ch1 导航）；cross-check：S3-P1-01。

#### ⑦ Alternatives
- **跨队列迁移式晋升**（expired 后搬到专用高优队列）：语义清晰但跨队列迁移有时序代价——当前用队列内打标记 [RTL 决策记录]；
- **Scheduler 内做长期带宽保障**（加权公平队列类）：被明确否决——职责上移到 port 仲裁 / NoC 整形（边界声明）；
- **per-class credit**（与 V3 交叉）→ V3 ⑦ OPEN [TODO-DESIGN]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] aging 阈值过短 → GPR 频繁晋升、优先级语义被稀释（接近无 QoS）；过长 → 饥饿窗口拉大；[口径] 最优阈值无项目数据——OPEN [TODO-MEASURE]。S3 与 S2 的冲突（QoS vs hit-first）即 RQ10 的核心问题，无闭式解，靠双模式配置 + 观测。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] hpr/lpr/gpr/tpw accepted 分布、exp_gpr/gpw（≈0 健康度）、fifo_full（V3 侧）；
- Closure：P50/P99 latency 与 starvation time（trace/模型 [MODEL only]）；aging 阈值 sweep [TODO-MEASURE→X-P1-07]；starvation bound 形式化 [S3-P1-01 TODO-DESIGN]；
- 诊断闭环：Symptom（某类流量 latency 异常 / exp_gpr 非零）→ Observable（accepted 分布、方向状态）→ Hypothesis（优先级配置 / D1 方向压制）→ Knob（队列映射 / aging / 水线）→ Experiment（分布统计 + A/B）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么晋升不迁队列？（时序代价 vs 语义清晰 [RTL 决策]）
- double：aging 阈值减半会怎样？（晋升频率↑，QoS 稀释 [MODEL]）
- workload：10% 实时流 + 90% bulk？（确定性模式 + port 权重的组合）
- protocol：QoS 结构跨协议一致吗？（协议无关层——差异在 DFI 侧 [INFERENCE]）
- failure：exp_gpr 持续非零说明什么？（防饿死机制被压制的健康度报警）
- redesign：Scheduler 背长期公平的锅会怎样？（复杂度爆炸 + 与 port/NoC 职责重复——边界声明）

#### ⑪ Interview Hook
**Tradeoff Hook**："我能明确说出 QoS 的边界画在哪：Scheduler 只管短期延迟优先级，长期带宽保障画在 port 仲裁和 NoC——这个边界本身就是架构决策，不是缺功能。"


## 4.4 L4 — Page Policy（CORE；宿主 Scheduling 章，属 Locality 域）

#### ① Interview Entry
- open page 还是 close page？怎么选？
- HBM 类负载为什么常配 close page？"天然 close"这个说法准确吗？
- 三寄存器机制怎么工作？
- close page 的延迟毛刺怎么缓解？
- page policy 该静态配置还是 adaptive？

#### ② Core Conclusion
[RTL] 实现是 **per-bank 三寄存器机制、运行时可配**：① AP enable（同 page 最后一笔 col 自动 precharge = 无感 close）② pre-idle 计时器（空闲超时才 precharge = 惰性 open）③ 两者同开 = 保持 open、tRASmax 强制兜底。策略不是编译期选择，软件可按负载逐 bank 调整。
[MODEL·条件式] 取向推导：bank 数越多、负载越流式、standby/open-row 功耗代价越敏感 → 越偏 close page。**HBM 类高 bank-count + streaming-dominant 负载往往偏向 close-page**（可能原因：bank parallelism 高、ACT/PRE 易被其他 bank 隐藏、workload locality 较弱、open-row standby 代价）——**这不是 HBM 协议要求 close-page，也不是所有 HBM workload 的最优策略**；GPU revisit / PTW / small-hot-set 等 open-page 反例保留。

#### ③ Problem
row open/close 是把 L1 的 hit 机会转换成实际收益的执行器：open 保留重访机会但占用 bank + standby 功耗 + tRASmax 义务；close 释放 bank 但重访要重付 tRP+tRCD。它是 L1 与 L2 竞争的调度侧裁决点。

#### ④ Performance & Correctness Model
- [MODEL] 三类 open-page 反例：GPU tile rendering / framebuffer（同 row 反复 blend，hit 80%+）；低 bank 并行系统（tRCD/tRP 无法被掩盖）；小数据高频访问（PTW / 锁变量）；
- [RTL] tRASmax 是 correctness 约束不是性能选择（row 最大驻留 → FORCE_PRE 触发源 [RTL]，inline counter 上行计数，→Ch5/Ch7）；
- [MODEL] 与 workload 的映射：流式 + 高 BLP → close；重访 + 低并行 → open；混合 → per-bank 配置的用武之地。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 三寄存器机制如 ②（per-bank 粒度）；
- AP 命令路径：RDA/WRA（col+precharge 复合，AP 使用率 = (RDA+WRA)/col，[RTL O1] 命令面观测）；
- CCT 只看窗口内命令、无法预测未来命中——locality 的可见性保障在前端（连续 hit 流优先入 CAM）[RTL 设计注记]。

#### ⑥ Interaction
← **L1**（locality 形态）+ **L5**（bank 几何）；→ **T2**（ACT/PRE 频率、tRASmax）；→ **M2**（critical 的 FORCE_PRE 交互）；↔ **S2**（hit-first 的收益前提）；cross-check：O1 AP 使用率（RDA+WRA/col）。

#### ⑦ Alternatives
- 全局静态 close / 全局静态 open：配置最简、负载适应差 [MODEL]；
- **adaptive page policy**（按 per-bank hit 统计动态切换）：未实现——需要 per-bank 统计与切换判据，OPEN [TODO-DESIGN]（legacy 4-I-04/4-P1-10 开放分支）；
- idle-timeout close（pre-idle 单独用）：介于两者，已有毛刺问题（⑧）。

#### ⑧ Tradeoff & Saturation Point
[RTL·已知缺陷] idle-timeout 型 close 有延迟毛刺（idle 计满才发 PRE，恰逢新 ACT 需多等 tRP）；PTW 类负载直接 disable AP、用 pre-idle 或完全 open。饱和：bank 数高到 ACT 可被完全并行掩盖时，open page 的边际收益趋零（HBM 情形 [MODEL]）。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] AP 使用率（RDA+WRA / col 计数）是 page policy 行为的命令面观测；
- Closure：close vs open × {streaming, GPU-revisit, random} 的 BW / latency 对比、per-bank 配置收益 [TODO-MEASURE→X-P1-07]；adaptive 判据研究 [TODO-DESIGN]；
- 诊断闭环：Symptom（ACT/col 偏高且 hit 低）→ Observable（AP 使用率、ACT 计数）→ Hypothesis（page policy 与负载失配）→ Knob（三寄存器逐 bank 配置）→ Experiment（配置 sweep + AP 使用率）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 AP 是"无感 close"？（precharge 搭在最后一笔 col 的总线上，零额外命令拍）
- double：tRASmax 到期前的窗口多大？（协议参数 [SPEC]，scope 类问题）
- workload：GPU blend 流怎么配？（disable AP / open page）
- protocol：各协议 tRASmax 语义一致吗？（HBM4 已删除 tRASmax 约束——协议差异点，[SPEC] 细节 → Memory_Protocal.md）
- failure：pre-idle 毛刺场景？（新 ACT 恰在 PRE 后 → 多等 tRP）
- redesign：adaptive policy 值得做吗？（判据 + 统计代价 [TODO-DESIGN]）

#### ⑪ Interview Hook
**Tradeoff Hook**："page policy 不是二选一，是三寄存器的连续旋钮——bank 越多 close 越香，但 GPU 重访流一行配置就能反例给你看。"

# 5. Timing Supply（T1 / T2 / T3）

> **本章核心问题：即使 scheduler 想发，DRAM 到底能提供多少合法 command opportunity？**
> 核心表达不是"有多少 counter"，而是"**哪类 workload 会被哪类 timing limit 卡住**"。counter 体系（≈1017，五级分布式）是约束的**执行者**（RTL 细节 → Ch15）；Supply/Demand 模型是约束如何变成带宽上限的**归因口径** [MODEL]。

## 5.1 T1 — Timing Supply 总纲（CORE）

#### ① Interview Entry
- timing constraint 为什么是真实带宽 ceiling？
- random / streaming / mixed workload 分别被什么 timing 卡住？
- 为什么不用一个 global cycle counter + timestamp？
- DVFS 切频时 counter 怎么办？
- "零 timing violation"算不算性能成就？

#### ② Core Conclusion
[RTL] 执行层：**五级分布式 counter**（bank / BG / rank / SID / window 三型：down / inline / window）——**所有命令无旁路地通过 counter 检查**才可下发，timing 永不违反是**结构性保证**（非验证 luck）。归 Ch15 的资源事实：≈1017 逻辑 counter（HBM4，近似口径），占调度模块面积 ~40% [MEASURED]。
[MODEL] 归因层：**Supply/Demand 模型**——持续带宽上限 = min(DQ peak, Column Supply, Row Supply)；tCCD 限制已开 row 的 col 发射速度（Column Supply），tRRD/tFAW/tRC 限制新 row 打开速度（Row Supply）。谁的供给最低，谁就是 sustained BW 瓶颈。
[口径] "零 timing violation" 只是 **correctness baseline**，不是性能成就；性能问题 = DRAM 本来 legal-to-issue，architecture/policy 没有 issue（lost issue slot 口径，对齐 Ch0.4）。

#### ③ Problem
DRAM 的 timing constraint（tCCD / tRRD / tFAW / tRC / tRFC）本身是**协议 / device 给定**；architecture 的性能价值在于：能否通过 locality / parallelism / interleaving / scheduling / maintenance scheduling 把这些 timing window **隐藏、错峰或摊薄**。因此 **timing constraint ≠ implementation defect，但 exposed blocked_timing cycles 也绝不是固定的 protocol tax**——供给不足时 blocked_timing 是机会链第五环断点。

#### ④ Performance & Correctness Model
- [MODEL] 持续带宽一级近似（H = 单 ACT 服务的 col 数，D = 每 col 传输 bytes，B_eff = 有效轮转 bank 数）：

```
BW_sustained ≤ min( BW_DQ_peak,
                    D / tCCD_eff,          ← Column Supply
                    D·H / tRRD_eff,        ← Row Supply（tRRD）
                    4·D·H / tFAW,          ← Row Supply（tFAW）
                    D·H·B_eff / tRC )      ← Row Supply（单 bank recycle）
```
- [MODEL] **H 两种 regime**：高 hit（H 大）→ tRRD/tFAW 被隐藏，卡在 tCCD 或 DQ；低 hit（H≈1）→ Row Supply 跟不上，DQ 出 bubble；
- **workload → limiting-timing 映射** [MODEL]：streaming hit → tCCD（T3）；random miss → tRCD/tRC/ACT supply（tRRD/tFAW，T2）；高 BLP → tRRD/tFAW；R/W mixed → turnaround（tWTR/tRTW，D1）；refresh → tRFC（M2，[SPEC scope→RF-P1-09]）；
- [RTL] **取整方向**：min 约束 ceil（多等一拍是安全代价）、max 驻留与 refresh deadline floor（放宽一拍即违反）——方向相反，"一律 ceil"是错误口径（6-P0-03 定稿；legacy 6.4.1 旧口径按此修正）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- [RTL·approximate inventory] 当前 HBM4 配置约有 **1k 量级 distributed timing items**（historical inventory ≈1017）——**逻辑 timing-item 近似口径**，非 synthesis FF count（FF 按位宽加权更大，回填 [TODO-MEASURE：6-P0-05]）；**inventory needs recount**：per-BG l 系列清单未补齐、item 清单与乘法口径不完全一致——不人工凑数（6-P0-01/02 [TODO-RTL]）；per-bank item 清单 / per-BG s·l / per-rank / per-SID / tFAW 精确计数 → Ch15 + [TODO-RTL]；
- down counter 管"最早何时能做"（下发启动倒计时，非零期间 ready 拉低）；inline counter 管"最晚必须做"（tRASmax/tDRFMmax 驻留上行计数）；
- 参数化链路：颗粒模型 → 软件脚本（按上述取整方向）→ 寄存器 → counter 初值，全寄存器可配；
- 零违反验证：零旁路 + **min-gap 覆盖率**（每类命令对实际最小间隔被真实激励覆盖，timing 检查无遗漏）；
- O(1) 语义：检查 = 归零判断的固定常数比较，**与 CAM/队列深度无关** [RTL]；"严格算法复杂度 O(1)"的表述边界 OPEN（6-P1-07）。

#### ⑥ Interaction
← **S1**（Eligible→BSC-ready→Direction-legal→Executable 六层口径，RC-1 已收口——见 Ch14.3）；→ **T2/T3**（本总纲的两个子供给）；← **L1/L2**（H 区间与 hit 决定各供给项的富裕度）；→ **M2/M4**（tRFC forbid / RFM 禁 ACT 占用供给窗口）；→ **D1**（tWTR/tRTW 窗口）；→ **G1**（DVFS 结构性规避的前提是 IDLE，0.13.4 分档）；cross-check：O2 lost-slot Top5 sweep、min-gap 断言（L 域）。

#### ⑦ Alternatives
- **集中时间戳记账**（每命令记 issue time，检查做减法）[MODEL·五维对照]：位宽统一大、比较需算术单元、持续 toggle 耗电、集中比较易成关键路径、记账表与协议耦合 vs 分布式（小位宽/1bit 归零比较/归零静默门控友好/各级并行/增删层级容易）。本设计在"多协议一套 IP + 多层级并行检查"约束下选分布式 [RTL 决策记录]；
- [OPEN] bank/BG 数极多时分布式 replication 是否反而更贵——未推导（6-P1-08 [TODO-DESIGN]）；"分布式全胜"表述已条件化为约束下选择（6-P1-09）；
- [OPEN] down-count vs elapsed-time compare（对 DVFS / clock gating / timing update 的友好性分析）——6-P1-10 [TODO-DESIGN]。

#### ⑧ Tradeoff & Saturation Point
[MEASURED] counter 面积占调度模块 ~40%（LPDDR6 表）；[RTL] 门控时钟友好——down counter 归零即静默，1017 的平均活动率远低于表面数字。[MODEL] timing constraint 的**存在**是协议固有；**暴露成多少 timing loss 由 workload 与 architecture 是否成功隐藏 / 错峰决定**——优化不是消灭 timing requirement，而是降低它在 useful-issue timeline 上的暴露比例（cross-check：L1 / L2 / L3 / D1 / M2）。

#### ⑨ Proof（含诊断闭环）
- [MEASURED] 面积双表（LPDDR6 @SF4 1GHz / HBM4 @SF4 1.6GHz 双 PC 合并——全表见 Ch15）；
- Closure：timing blocker **Top 5（tCCD / tRCD / tRRD+tFAW / tWTR+tRTW / tRFC）各 lost issue slot 占比 sweep** [TODO-MEASURE→X-P1-07（原 6-Q-02）]；timing-1→blocked / timing→allowed 边界统计（6-Q-03）；counter FF 数回填 [TODO-MEASURE：6-P0-05]；
- 诊断闭环：Symptom（blocked_timing 占比高）→ Observable（命令 mix + 方向状态 [RTL O1]，细分归因 [MODEL]）→ Hypothesis（按映射表对号入座：hit 结构 / miss 率 / mixed 度）→ Knob（上游 L1/L5/V2）→ Experiment（workload sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么不用 timestamp？（⑦ 五维；追问"bank 极多呢"→ OPEN 6-P1-08）
- double：tFAW 窗口大小变化的 BW 影响？（公式第 3 项）
- workload：50/50 R/W mixed 的瓶颈在哪？（turnaround 窗口 → D1 账单 + tWTR/tRTW）
- protocol：HBM4 的 bank/BG/SID timing 层级全部真实存在吗？（统一 RTL 架构保留抽象层 vs 协议要求——[TODO-SPEC：6-P1-04]）
- failure：timing 寄存器运行中被 SW 修改？（配置一致性风险——[OPEN 6-I-04，TODO-DESIGN]）
- redesign：counter 做成频率感知？（DVFS 结构性规避后无必要 [RTL 设计理由]）

#### ⑪ Interview Hook
**Measurement Hook**："timing 的学习不是背 1017 个 counter，是背'哪类 workload 被哪条 timing 卡'的映射——Top5 lost-slot sweep 一跑，瓶颈自动排序，优化顺序不用吵。"


## 5.2 T2 — ACT Supply（CORE）

#### ① Interview Entry
- ACT 为什么是稀缺资源？它的约束全集是什么？
- tRCDWR / ACTIVE_WR 是什么？为什么写能提前进？
- tFAW 的 rolling window 怎么实现？边界 off-by-one 怎么保证？
- ACT 和 PRE 谁优先？为什么？
- refresh 期间 ACT 怎么被禁？

#### ② Core Conclusion
[MODEL] ACT 是 **Row Supply 的最小单元**——每个 ACT 购买 H 条 col 的服务权（H = row-hit 摊薄因子）；miss 流的每个 ACT 都要同时满足 tRCD/tRC/tRRD/tFAW/tRAS 五类约束，供给不足直接限制 Row Supply（T1 公式后三项）。
[RTL] 约束承载 = per-bank 分布式 counter（down：tRCD / tRCDWr / tRRD / tRC / tRP / tRASmin 等 + inline：tRASmax）；**tFAW = 4 个错相 counter 轮流使能、全有效禁 ACT**（counter 组复用，非移位寄存器）；**ACTIVE_WR 仅写窗口**利用 tRCDWR < tRCD 的 timing 差让写提前进入（5-P0-01 [RTL]：LPDDR5/HBM3/4 有独立 tRCDWR；未定义协议配置 tRCDWR=tRCD → 窗口宽 0、状态跳过，退化无害）。

#### ③ Problem
Column Demand 无限、Row Supply 有限：打开新 row 的速度被四层 timing（bank/BG/rank/window）+ 驻留义务（tRASmax/tRASmin）钉死；ACT 供给不足时 ready 的 RD/WR 不足，DQ 出 bubble（T1 低 hit regime）。

#### ④ Performance & Correctness Model
- [MODEL] ACT 间隔下界：tACT = max(tRRD_S, tRRD_L / BGactive, tFAW / 4)；H_act = tACT / tCAS（→3.3 H 区间第 2 条）；
- [RTL] bank FSM 的 ACT 路径：IDLE → ACTIVTING（tRCD/tRCDWR 双计数并行）→ ACTIVE（col 可调度）/ ACTIVE_WR（仅写窗口）；tRASmax 驻留超时 → FORCE_PRE（inline 上行）；
- [MODEL] ACT > PRE 的需求驱动逻辑：ACT 的触发源是 CCT 上真实 miss 在等；PRE 之后不一定有命令跟随——需求驱动优先于服务性操作（auto-precharge 普及后显式 PRE 本来就少）；
- [RTL] refresh 路径：ref_act_mask / RFM 达限禁 ACT——maintenance 对 ACT 供给的强占（→M2/M4）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- per-bank down 清单中 ACT 相关：tRCD / tRCDWr / tRRD / tRC / tRP / tRDA（rda→act）/ tRASmin（清单为近似口径 [TODO-RTL：l 系列、总数待重算]）；inline：tRASmax；
- tFAW：4 counter + 使能逻辑（总账记 8 的口径差异——[TODO-RTL：6-P1-06]）；边界 off-by-one 由错相归零设计保证（细节 →Ch15）；
- multi-constraint ready 生成：同 bank 多条 forbid 对同一 ACT 的**与逻辑**（全部归零才 ready）[RTL]（6-I-03 素材已闭合）；
- HBM4 的 bank/BG/SID/rank timing 层级是否全部协议要求（还是统一架构保留抽象）——[TODO-SPEC：6-P1-04]；
- 本 RTL 只实现 Precharge PD，不支持 Active PD（带 open row 换进入速度的组合不做——与 SR 共用 drain 路径 [RTL，12.3]）。

#### ⑥ Interaction
← **L1/L2**（miss 率与 H 决定 ACT 需求）；→ **T3**（tRCD 满后的 col 窗口）；← **S2**（FSC ACT>PRE 序）；← **M2/M4**（critical ref 禁 ACT → 强制 PRE 两步；RFM 达限禁 ACT）；→ **D1**（渐进式切换的对侧提前 ACT——把 tRCD 藏进对侧执行时间，best case 口径见 Ch1 RQ7）；→ **P1**（counter 面积/FF 数）；cross-check：O2 tRRD/tFAW blocked cycles。

#### ⑦ Alternatives
- **集中 ACT 记账**（单点管理全 bank ACT 窗口）：与 T1 集中式同源否决 [MODEL·RTL]；
- **ACT 提前量调度**（对侧方向切换前预 ACT）：已实现形态 = 渐进式 R/W 切换的对侧提前开行 [RTL→Ch6 D1]；其前提与失效条件 → RQ7 best-case 口径。

#### ⑧ Tradeoff & Saturation Point
[MODEL] tFAW / tRRD 是协议级安全义务（防止 wordline 应力），不可优化只可"错峰消化"；ACT 供给饱和判据：tRRD/tFAW blocked cycles 持续占主导且 DQ 有 idle → Row Supply 是瓶颈（T1 公式第 2~4 项最小）。

#### ⑨ Proof（含诊断闭环）
- Closure：tRRD/tFAW blocked cycles 量化（Top5 sweep 的一部分）[TODO-MEASURE→X-P1-07]；tFAW min-gap 断言（L 域）；
- 诊断闭环：Symptom（ACT 类 blocked 高）→ Observable（ACT 计数、命令 mix [RTL O1]）→ Hypothesis（miss 率高：L1/L5？还是纯供给限制：tRRD/tFAW 窗口）→ Knob（mapping/page policy）→ Experiment（stride sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 ACTIVE_WR 只有写窗口？（tRCDWR<tRCD 是协议给写的 timing 优惠 [SPEC]）
- double：tFAW=4 的窗口如果放宽？（公式第 3 项放松，random BW ↑）
- workload：多少 miss 率会打到 tFAW？（tACT/tCAS 与窗口的函数 [MODEL]）
- protocol：没有 tRCDWR 的协议怎么办？（等值配置 → 窗口 0，退化无害 [RTL]）
- failure：tRASmax 与 page policy 冲突？（tRASmax 是兜底不是策略——FORCE_PRE 优先级高于业务 col [RTL]）
- redesign：把 tRRD/tFAW 检查做成预测式？（预判下一 ACT 时刻 vs 现在禁止——复杂度换提前量 [TODO-DESIGN]）

#### ⑪ Interview Hook
**Tradeoff Hook**："ACT 是全场最贵的命令——它买的是 H 条 col 的服务权；所以所有调度优化最后都在回答同一个问题：怎么让每个 ACT 被更多的 col 摊薄。"


## 5.3 T3 — Column Supply（CORE）

#### ① Interview Entry
- streaming workload 为什么卡在 tCCD？
- 一拍能发几条命令？为什么 HBM 可以两条？
- BG 交织怎么"白吃"带宽？
- tWTR / tRTW 归谁管？
- AP（auto precharge）col 在 supply 里是什么角色？

#### ② Core Conclusion
[MODEL] tCCD 限制**已开 row** 上 RD/WR 的发射速度 → 直接限制 Column Supply（T1 公式第 1 项）；**BG 交织把背靠背 col 换到 tCCD_S 类别**是零硬件面积的供给放大器（每 command 平均间隔 tCAS = max(tCCD_S, tCCD_L / BGactive) [MODEL·与 3.3 共用]）。
[SPEC→架构] 每拍命令数协议钉死：DDR/LPDDR row/col 复用同一组 CA → 单条；HBM row/col 线独立 → 可同拍 row+col（5-P0-03 定稿口径的架构推论，附加条件 → OPEN 5-P1-03 [TODO-SPEC]）。
[边界] tWTR / tRTW（读→写 / 写→读的总线方向间隔）的本体归 **D1 Direction Switching**（Ch6 turnaround 账单）；T3 管同方向 col 密度。

#### ③ Problem
DQ 连续性由 col 流的供给密度决定：col 序列 timing（tCCD_S/L、tWR2RD、tRD2WR、tWR2PRE）+ BG 类别（s/l）决定每拍"还有没有合法 col 可发"；供给断流即 DQ bubble。

#### ④ Performance & Correctness Model
- [MODEL] T1 公式第 1 项 D/tCCD_eff：tCCD_eff 随 BG 交织质量在 tCCD_L 与 tCCD_S 间移动——tCCD_S 满足占比是交织质量指标（→L3 ⑨）；
- [MODEL] 高 hit regime（H 大）下 Column Supply 先于 Row Supply 饱和：此时优化方向是 tCCD 类（BG 交织/更短 burst 间隔）而非 ACT 类；
- [RTL] AP col（RDA/WRA）把 precharge 搭载在最后一笔 col 上——零额外命令拍的 close 手段（→L4），其代价是 bank 立即进入回收（下一条 miss 需完整 tRCD）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- per-BG **tCCD_L forbid / tCCD_S forbid 双计数器**（bg1ba1 发 col → tCCD_L forbid 禁同 BG col、tCCD_S forbid 禁其他 BG col）；s/l 系列清单中 col 相关：tCCDs / tWR2RDs / tRD2WRs / rd2rd / wr2wr（**l 系列 [TODO-RTL]**）；
- per-bank col 相关：tWR2RD / tRD2PRE / tWR2PRE（col 尾部回收时序）；
- 每拍单命令（DDR/LPDDR）；HBM 双发形态（→Ch14/Ch17 RTL）；
- AP 使用率观测：(RDA+WRA) / col 计数 [RTL O1]。

#### ⑥ Interaction
← **L3**（BG 交织供给 tCCD_S 类别）；← **L1**（hit 供给已开 row 的合法 col）；→ **D1**（方向翻转时的 tWTR/tRTW 窗口——T3 供给归零的来源之一）；← **S2**（FSC Col>Row 保证 col 优先消费供给）；→ **DP3**（PF window 预取 col 流，HBM 场景）；cross-check：O1 命令 mix / tCCD blocked cycles [TODO-MEASURE]。

#### ⑦ Alternatives
- **HBM 双发流水化**：row+col 同拍（协议专属 [SPEC]；收益上限量化 → 5-I-06 [TODO-MEASURE]）；
- **PF window**（调度影子，提前锁 col 流）：HBM4 场景方案（→DP3 / Ch8）；
- **更深 BG 交织**：见 L3 ⑦（受 txn 大小管理代价约束 [MODEL]）。

#### ⑧ Tradeoff & Saturation Point
[MODEL] tCCD_S 与 tCCD_L 的差值就是 BG 交织收益的上限；Column Supply 饱和判据：DQ 打满且 tCCD blocked 主导、ACT 供给富裕 → 优化对象转向 burst 结构（DP3）而非并行度。

#### ⑨ Proof（含诊断闭环）
- Closure：tCCD blocked cycles 占比、timing-1→blocked 边界统计 [TODO-MEASURE→X-P1-07]；tCCD_S 满足占比（trace/模型 [口径]）；
- 诊断闭环：Symptom（DQ 未打满 + tCCD blocked 主导）→ Observable（命令 mix [RTL O1]）→ Hypothesis（BG 交织不足 / hit 供给不足 / 方向切换过频）→ Knob（L3 位图 / L1 / D1 水线）→ Experiment（对照 sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么同 BG 是 tCCD_L？（BG 内 bank 共享局部命令路径 [SPEC·协议 why → Memory_Protocal.md]）
- double：tCCD_S=L 的协议（无 BG）怎么办？（L3 退化，供给只剩 L1/L2）
- workload：纯 streaming 的理论上限怎么算？（T1 公式第 1 项代数）
- protocol：HBM 同拍 row+col 的附加条件？（不是任意 row+col 都能同拍——[TODO-SPEC：5-P1-03]）
- failure：tCCD 计数器与容量空洞交换冲突？（不同层无交叠 [RTL]）
- redesign：col 命令合包（多条 col 打包一次 CA）？（协议 CA 编码限制 [SPEC]→RQ12）

#### ⑪ Interview Hook
**Measurement Hook**："判断一个 controller 的 col 供给健康度，我只看一个数：tCCD_S 满足占比——它直接告诉你 BG 交织有没有把便宜的 timing 类别用满。"

# 6. Transition Amortization（D1 / D2）

> **本章核心问题：MC 如何摊薄那些无法完全消除的切换开销？**
> 统一思想：**切换代价是常量，batch 长度是核心摊薄手段（分母）**——覆盖 R/W 方向切换、rank/SID 切换（row 开关的开销由 L1/T2/L4 承载）。核心张力：BW ↔ latency ↔ starvation ↔ QoS——batch 不能无限大。

## 6.1 D1 — Direction Switching（CORE）

#### ① Interview Entry
- 为什么 R/W switching 是最大性能损失之一？
- read/write batch 长度怎么定？
- 90% read + 10% write 时 write 饿死怎么办？
- "read 恒优先"对吗？精确边界在哪？
- 渐进式切换怎么把 tRCD 藏掉？什么情况下藏不掉？

#### ② Core Conclusion
[RTL] 触发条件四类：① CAM 水线（某方向到上水线）② **单侧执行时间超阈值（最常用**——perf 激励下两侧常满、水线长期高位，基于时间的配额最准确）③ 对侧 critical / 过期命令 ④ 当前侧无命令（自然切换）。
[RTL] **渐进式切换**：当前侧继续发 col 的同时**对侧先发 ACT**——row open 完成（tRCD）被当前侧 column 时间隐藏后，最后一条 col → bus turnaround → 对侧 col 开始。
[MODEL·best case 口径] 该机制**生效时**切换暴露成本主要剩 bus turnaround（tWTR/tRTW）；若对侧 ACT opportunity 不足 / bank conflict / tRRD·tFAW block / CAM visibility 不足，仍会暴露部分 row preparation（不宣称无条件只剩 turnaround）。
[RTL] **read 默认优先**的根因 = 端到端延迟责任不对称：write 的 response 入队即回（数据已在 buffer，后端何时落盘对 master 不可见），read 要等数据返回——write drain 永远"见缝插针"。两个显式例外（承接 ①③）：对侧 critical/过期 write 触发切换；读侧无命令/水线到限——read 优先是**无 critical 情况下的默认策略，不是绝对规则**（5-P0-06 定稿）。

#### ③ Problem
DQ 是**共享的双向（half-duplex）数据总线**——同一时间窗口只能服务一个传输方向，因此 Read↔Write direction switching 需要支付 tWTR / tRTW + ODT / DQS / bus-turnaround + 可能未隐藏的 row preparation，且打断 col 供给（T3 归零窗口）。翻转频率与方向公平性直接对偶。

#### ④ Performance & Correctness Model
- [RTL·账单] turnaround 完整账单：**tWTR**（W→R，硬性 AC timing）/ **tRTW**（R→W，硬性 + ODT 切换）/ **tWR 隐藏成本**（write 末笔到 precharge——drain 后紧跟 refresh/close 时额外吃进）/ **频率放大**（频率越高，gap 占 burst 比例越大）；
- [MODEL] batch 权衡：增大 batch → switch/sec ↓、turnaround 摊薄 ↔ write queue latency ↑（read 优先下的 write 等待）↔ 公平性；上限由 latency SLA 与 starvation 约束决定，不是 BW 最优（RQ10 交叉）；
- [MODEL] 配额选型：执行时间配额 vs command count vs byte count——时间配额对 burst 长度混合最稳健 [RTL 决策记录]；系统性对比 OPEN（5-P1-10 [TODO-DESIGN]）；
- [MODEL·账单口径] tWTR/tRTW 是 best case 暴露；完整账单 = turnaround + 未隐藏 row preparation（渐进前提失效时）——"T_switch = turnaround + unhidden preparation"可拆分验证 [TODO-MEASURE→X-P1-07]。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 四类触发 + 水线 set/clr 迟滞（防乒乓，与 V3 水线联动）；
- 渐进式切换（col 继续发 + 对侧 ACT 提前）；
- read 默认优先 + 两例外；expired write 参与切换决策（与 S3 aging 联动）；
- 确定性模式：提高切换频率（牺牲批量换延迟可预测，→S2）。

#### ⑥ Interaction
← **V3**（水线）；← **S3**（critical/expired write）；→ **T3**（tWTR/tRTW 供给窗口）；→ **T2**（对侧提前 ACT 的 tRRD/tFAW 消耗）；↔ **DP1**（write ready 决定 drain 可持续性）；→ O2（switch count/sec、turnaround lost cycles、hidden tRCD ratio [TODO-MEASURE]）。

#### ⑦ Alternatives
- **双总线/全双工**（HBM 类独立读写——非本协议族选项）[SPEC 边界]；
- **command count 切换** vs **时间配额**：当前用时间配额 [RTL]；系统性对比 [TODO-DESIGN：5-P1-10]；
- **动态 batch 上限**（随 R/W 比例自适应）：未实现，OPEN [TODO-DESIGN]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] batch 收益饱和：R/W 比例极偏（90/10）时 write starvation 压过摊薄收益——配额/critical 兜底接管；[RTL·已知代价] write queue latency 随 batch 增大上升（read 优先的直接后果，需分方向 latency 观测验证 [TODO-MEASURE]）。

#### ⑨ Proof（含诊断闭环）
- Closure：不同 GSC 阈值（配额/水线）的 BW / read latency / write latency / switch count/sec 曲线 [TODO-MEASURE→X-P1-07（原 5-Q-03）]；BW_loss,RW 量化与 T_switch 拆分（5-Q-01/02）；
- 诊断闭环：Symptom（turnaround lost cycles 高）→ Observable（命令 mix、方向状态 [RTL O1]）→ Hypothesis（配额过小 / 水线过灵敏 / R/W 比例抖动）→ Knob（配额/水线）→ Expected（switch/sec↓）→ Side effect（write latency↑）→ Experiment（阈值 sweep + 分方向 latency）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么时间配额比 command count 稳？（burst 长度混合下 count 失真 [RTL 决策]；系统性论证 TODO）
- double：batch 翻倍 write latency 变多少？（分方向 latency 曲线 [TODO-MEASURE]）
- workload：50/50 均匀混合的最优 batch？（turnaround 与 latency 的交点）
- protocol：LPDDR 为什么比 DDR 更怕切换？（ODT 阻抗切换叠加 [SPEC/RTL 经验]）
- failure：critical write 撞上 read 配额未满？（例外③接管——防饿死优先于摊薄 [RTL]）
- redesign：GSC 决策做成自适应？（判据与抖动风险 [TODO-DESIGN]）

#### ⑪ Interview Hook
**Measurement Hook**："判断方向管理健康度我看三个数：switch count/sec、turnaround lost cycles、hidden tRCD ratio——第三个为 0 说明渐进切换在 best case 工作，不为 0 就要查对侧 ACT opportunity。"


## 6.2 D2 — Rank / SID Switching（LEAF）

#### ① Interview Entry
- rank 是为容量还是性能？"多 rank 一定低效"对吗？
- 为什么一个 transaction 不拆到两个 rank？
- cs 位为什么钉死在 [10]？
- HBM 多 stack 的 SID 乒乓怎么防？
- 双 rank 什么时候反而比单 rank 快？

#### ② Core Conclusion
[ARCHITECTURE CONTEXT / MODEL] 当前设计主要把多 rank 作为 **capacity expansion / address-topology** 维度；同时多 rank 的独立 bank state 也可能提供 parallelism opportunity——capacity ↔ independent bank state ↔ rank switching ↔ ODT/DQS/bus turnaround 的 tradeoff 保留（2-I-05 / 2-Q-03 [TODO-MEASURE]）。cs 位放高与两个机制配套：① **一个 txn 不拆 2 rank**——rank 内连续执行多条命令再切（摊薄切换）② SidSwitch 迟滞（HBM 多 stack：当前 SID 空闲 N 拍才允许切换，防"断一拍→切走→切回"乒乓）。
[MODEL·降级口径] "rank-to-rank 切换比 rank 内贵"的机制 = 多 rank 共享同一套 channel DQ/CA → 切 rank 产生 **data-bus / ODT / DQS 切换开销** [SPEC/RTL 经验]——但"**多 rank 效率必然低于单 rank**"是未量化的 tradeoff 断言，不写 universal：**双 rank 反超单 rank 的场景存在**（并行 bank state / 容量换页策略），需 benchmark（2-I-05 / 2-Q-03 [TODO-MEASURE]）。
[RTL] cs 位被 col/bg/ba 总位宽钉死（col 6 + bg 2 + ba 2 = 10 → cs=[10]），不能单独调高；HBM core 内无 cs/rank 概念——PC 在 XMU 前置分流、多 stack SID 在 core 外分时。

#### ③ Problem
rank/SID 切换与 R/W 切换同类（共享总线的方向/驱动切换），但触发源不同（地址分布而非队列方向）；控制手段不是"更聪明地切"，而是"让切得少"——位图（L5）+ 迟滞（D2）双管。

#### ④ Performance & Correctness Model
- [MODEL] rank 位高度收益 = 顺序流在 rank 内形成长连续段、切换频率最低；代价 = 跨 rank 独立 bank state 并行度不可用（位图两端权衡，L5 ⑧ 同源）；
- [RTL] SidSwitch=4 例：当前 SID 连续 4 cycle 无命令才允许切换——时间迟滞换切换稳定性（与 write drain 迟滞同构，0.7-2）；
- [MODEL] 双 rank 反超单 rank 的候选场景：负载并行需求超出单 rank bank 数、容量驱动的页分散——需数据支撑 [TODO-MEASURE]。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- cs=[10]（实配位图，→L5）；HBM：PC 前置分流（XMU 之前剥离位）、SID 分时 + SidSwitch 迟滞寄存器（GSC 执行）；
- rank/SID 多命令再切策略：与 R/W batch 同属"摊薄切换代价"族。

#### ⑥ Interaction
← **L5**（cs 位位置 / HBM PC 剥离）；↔ **D1**（同族切换摊薄思想）；→ **T1**（rank 层 timing counter：tRFCab/tXRS/tXP 等 [RTL 近似清单]）；→ **M2**（HBM critical 补刷的 SID 顺序）；cross-check：O1 命令 mix 的 rank 面。

#### ⑦ Alternatives
- cs 位放更高（更大 rank 连续段）：被位宽钉死 [RTL]；替代 = 加伪交织位或更大 page 颗粒（→L5）；
- 更激进 SidSwitch（阈值 0 = 无迟滞）：乒乓风险 [MODEL]；阈值 sweep 无数据 [TODO-MEASURE]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] rank 并行饱和：单 rank bank 数已足够掩盖 tRC/tRCD 时，跨 rank 并行边际收益趋零、只剩切换开销——"rank 为容量"的定量版本；反之（bank 少 + 重访流）双 rank 可反超。

#### ⑨ Proof（含诊断闭环）
- Closure：rank switching 损失量化 + dual-rank vs single-rank 反超场景 [TODO-MEASURE（2-Q-03）→X-P1-07]；SidSwitch 阈值 sweep；
- 诊断闭环：Symptom（rank 面 turnaround 高）→ Observable（命令 mix 的 rank 分布 [MODEL]）→ Hypothesis（地址散布 / SidSwitch 过松）→ Knob（L5 cs 位 / SidSwitch 阈值）→ Experiment（sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 rank 切换贵在 ODT/DQS 而不是"rank 访问慢"？（共享总线物理切换 [SPEC/RTL]；"rank 访问慢"是错误直觉）
- double：4 rank 呢？（切换频率与并行度进一步权衡）
- workload：重访流 + 双 rank？（独立 bank state 反超场景 [TODO-MEASURE]）
- protocol：HBM 为什么没有 rank 概念？（PC 前置分流 + SID core 外分时 [RTL]）
- failure：SidSwitch=0 的乒乓场景？（断续流量切换开销爆炸 [MODEL]）
- redesign：SID 分时改并行 core？（core 面积 / DFI 合流复杂度 → RQ12）

#### ⑪ Interview Hook
**Tradeoff Hook**："rank 的每一点性能收益都是借的——借 bank state 并行，还的是 bus/ODT/DQS 切换；cs 位钉死在 [10] 就是这笔借贷的合同条款。"

# 7. Refresh / Activation Maintenance（M1 ~ M5）

> **本章核心问题：Controller 如何在不可延期 maintenance obligation 与 normal traffic performance 之间做调度？**
> 主干链：obligation → debt → deadline tracking → postpone → pressure → critical escalation → bank drain → maintenance issue → unavailable interval → recovery；分支 REF（M1/M2/M3）/ RFM（M4）/ DRFM（M5）。与 PA/QoS 无交集（纯 CQ/GSC/DEVMGR 侧 [RTL]）；与 Device Management 接口 = 进 LP/DFS 前 ab 折算（→G1）。

## 7.1 M1 — Refresh Obligation / Debt（CORE）

#### ① Interview Entry
- tREFI 到底是什么义务？debt/credit 怎么记账？
- 为什么不能无限 postpone？上限怎么算？
- "debt 单位与 tREFI 解耦"是什么意思？
- 温度升高对刷新调度的影响路径？
- pull-in 是主动探测还是被动发生？

#### ② Core Conclusion
[MODEL] 双账本总纲：**REF 是时间债，RFM 是激活债——两本账，只在 FSC 优先级序汇合**（M4 交叉）。
[RTL] 记账流程：每经 tREFI → 先扣 pull-in credit，无 credit 则 debt+1（单位 = **"欠一次刷新"，次数而非时间**——温度升高只是 tREFI 变短、记账变快）；REF 完成：debt>0 → debt−1；debt==0 → credit+1（**被动攒 pull-in**，上限 csrMaxPullin 档位）——无 scheduler-idle 探测、非 SW 触发（R/W > refresh，刷新在读写间隙自然发生）。
[SPEC, scope→RF-P1-09] 协议两条约束（当前口径按 DDR/LPDDR 一致记载）：① 两次 REF 最大间隔 ≤ 9×tREFI；② 最多 postpone 8 个。联立 postpone 阈值配置上界 = **9×tREFI − 8×tRFC**（最坏攒欠 8 个、末窗口连发，8×tRFC 的不可调度时间需预留）。

#### ③ Problem
刷新是**不能无限让步的义务**：电容漏电决定了"迟早要刷"，但何时刷、刷多大粒度、怎么与 traffic 共存全部是 controller 的调度问题——postpone 换来性能平滑，代价是 critical 突发的方差。

#### ④ Performance & Correctness Model
- [RTL] 温度档位双维 CSR：csrMaxPostpone / csrMaxPullin 按 **1x / 0p5x / 0p25x × 频点** 预配置，RTL 只做档位选择（软件预写全表、硬件选择）；采样按 csrMr4RdInter 周期发 MR4 读取（HBM 用 DRAM 内部 TEMP sideband 上报）；切换档位：debt 换算新档 + pull-in 清零；
- [RTL] 高温强制放弃 REFpb（csrRmPb2AbTh）；
- [MODEL] latency spike 形态：critical 触发 = 补刷连发（最多 8×tRFC 不可调度突发）——**postpone 阈值越高、尖峰越罕见但越大**，典型均值/方差取舍。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- csrMaxPostpone / csrMaxPullin / csrRefPostEn / LowTh / csrRmPb2AbTh / csrMr4RdInter / csrRefabEn 全套 CSR；
- debt/credit 计数、Odd/Even watchdog（→M3）、critical 进入/退出（→M2）；
- 档位切换时的债务换算与 credit 清零。

#### ⑥ Interaction
← [SPEC] tREFI/温度采样；→ **M2**（critical 触发）；← **M3**（deadline watchdog 反压）；→ **G1**（进 LP/DFS 前强制 AB 折算、SR 期 debt 冻结）；cross-check：O1 REFpb/REFab 计数 vs 应发数（记账健康度）。

#### ⑦ Alternatives
- **主动 pull-in**（scheduler-idle 探测提前还债）：未采用——被动溢出式已覆盖典型流 [RTL 决策记录]；idle 密集型负载差异 [TODO-MEASURE]；
- **按时间记账**（debt 单位 = 时间）：与温度换算耦合——当前次数制 + 档位换算 [RTL]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] postpone 深度 ↔ latency spike 的均值/方差曲线（4-Q-03 [TODO-MEASURE→X-P1-07]）；debt 上限受 9×tREFI−8×tRFC 硬顶——超过即 correctness 风险，不是性能选择。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] REFpb/REFab executed 计数；CSR 档位状态（dbg_obv）；
- Closure：per-workload "blocked only by refresh" cycles + postpone depth sweep [TODO-MEASURE→X-P1-07（原 4-Q-03）]；
- 诊断闭环：Symptom（blocked_maintenance 尖峰）→ Observable（REF 计数、critical 事件）→ Hypothesis（debt 积压 > 消化：tREFI 档位 vs 流量密度）→ Knob（档位/阈值）→ Experiment（depth sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 debt 单位用次数？（与 tREFI/温度解耦）
- double：postpone 阈值翻倍？（撞 9×tREFI 硬顶——公式封死）
- workload：idle 密集型负载被动 pull-in 够吗？（间隙自然发生 ✓；极端差异 [TODO-MEASURE]）
- protocol：HBM 的 tREFI/温度一致吗？（TEMP sideband vs MR4 [RTL]；9×tREFI scope → RF-P1-09）
- failure：档位切换瞬间 debt 超新档阈值？（立即 critical 兜底 [RTL]）
- redesign：refresh 做成 QoS 流量？（与 PA/QoS 无交集是当前架构决策 [RTL]）

#### ⑪ Interview Hook
**Tradeoff Hook**："postpone 是把 refresh 的代价从'高频小额'换成'低频大额'——上界 9×tREFI−8×tRFC 封死了换汇率的自由度，剩下的全是均值/方差偏好。"


## 7.2 M2 — Refresh Scheduling（CORE）

#### ① Interview Entry
- REFab / REFpb / REFsb 怎么选？互相怎么折算？
- critical refresh 的完整执行序列？
- Normal REFpb 为什么只能选 bank empty？
- FSC 里 refresh 优先级序怎么排？为什么 Normal REFab 压过 critical REFpb？
- refresh 的带宽损失怎么量化才科学？

#### ② Core Conclusion
[RTL] **粒度层**：REFab（全 bank，一条抵消本轮剩余全部 pb 债——"性价比单"）/ REFpb（per-bank）/ REFsb（pb 的跨 BG 同 index 变体，DDR5——需各 BG 同 index bank 均 close 且满足时序）。**模式层（ab↔pb）**：PB→AB 三触发（①温度恶化 ②进 PHY-master/PD/SR/DFS 前强制 ③debt ≥ csrRefPostPb2AbThr）；AB→PB 唯一路径（csrRefabEn==0 ∧ 无 pb2ab 条件 ∧ debt 在 PB 预算内）；折算时点 = PRE_SRE 拍。
[RTL] **critical 两步执行**（5-P0-04 定稿）：先全 bank 禁 ACT（ACT_FORBID 打破 Col>Row 常态序）→ 再对 open bank 逐个 RR 强制 PRE（FORCE_PRE）→ REF 下发 → tRFC forbid 计满恢复——**压制与强制 PRE 是先后两步**。close 粒度按模式：REFpb 只 close 目标 bank / REFsb close 跨 BG 同 index 排 / REFab 全部。
[RTL] **Normal REFpb 准入 = bank empty**（CAM 无对应命令），三层 tier 为 RTL 真实：tier1 IDLE+CAM 空 / tier2 IDLE+CAM 命中 / tier3 force-PRE 降级。
[RTL] **FSC 维护优先级序**：critical REFab > Normal REFab > critical REFpb > critical RFMpb > critical DRFMpb > Normal REFpb——**Normal REFab 压过 critical REFpb：一条 REFab 还掉全部债，性价比决定序**。
[RTL] **HBM critical 补刷**：一次只推进一个 SID 的 rolling-set（SID 内未完成锁定），完成后按 SID0→1→2→3 固定顺序切换；双 PC 从不同初始值倒计时错峰。

#### ③ Problem
maintenance 与 traffic 争抢 bank、CA 槽、tRFC 窗口：插队太狠伤 traffic、让步太多撞 deadline——escalation + 执行粒度 + 优先级序三层协同。

#### ④ Performance & Correctness Model
- [MODEL·归因口径] refresh 损失**不能用比值**（tRFCpb/tREFIpb）估算——tRFCpb 期间只有目标 bank unavailable；正确指标 = **Refresh-induced unhideable bubble**：存在 pending traffic + 目标 bank 不可访问 + scheduler 无法从其他 bank 找到 timing-ready useful command 的 cycle 才计入（互斥归因，对齐 Ch0.4 blocked_maintenance）；
- [MODEL] REFpb vs REFsb 取舍：粒度细 → 单次可隐藏性好、scheduling 压力大；tRFCpb 不一定比 tRFCsb 短——HBM 目标是把长 latency **限制在单 bank 内**而非缩短；
- [口径修正] AP-as-bank-drain（REFpb 前 AP 排空）为探索概念 **[MODEL≠RTL]**——真实 RTL 无 prepare-deadline/AP-drain 层，用三层 tier + critical 两步。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- critical 四步序列、三层 tier、FSC 序、HBM rolling-set/双 PC 错峰（②）；
- 与 BSC 协同：ref_act_mask → 各收尾状态可达 ACT_FORBID（bank FSM 最短回刷路径）；
- ref critical 打破 Col>Row = mask ACT + Col（债不能无限让步）。

#### ⑥ Interaction
← **M1**（debt/档位）；← **M3**（watchdog 拉响）；→ **T2**（禁 ACT / tRFC forbid）；→ **S2**（FSC 插队）；→ **L4**（FORCE_PRE 与 page policy）；→ **G1**（进 LP 前强制 AB + REF_CHECK 握手）；cross-check：O2 blocked_maintenance、O1 REF 计数、13.3 refresh 归因三维 [MODEL only]。

#### ⑦ Alternatives
- **更细粒度刷新**（FGR 类）：协议侧演进 [SPEC→Memory_Protocal.md]；
- **AP-drain 提前排空** [MODEL≠RTL 探索性]：与 per-bank AP 同旋钮、过早 AP 牺牲 locality——未实现；
- **REFpb 多 bank 并发**：协议一次一条 [SPEC 边界]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] 三层 tier 的含义：tier1/2 免费（无打扰/仅等待）、tier3（force-PRE）有真实代价——调度压力集中在 tier3 触发率；critical 突发不可调度窗口 = 连发 REF + 全禁 ACT（互斥归因对象）。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] REFpb/REFab/RFMpb 计数、ref critical 状态（dbg_obv）；
- Closure：per-workload blocked-only-by-refresh + postpone depth sweep [TODO-MEASURE→X-P1-07]；13.3 refresh 归因三维校准 [MODEL only]；
- 诊断闭环：Symptom（refresh spike）→ Observable（REF 计数、tier 分布 [MODEL]）→ Hypothesis（tier3 触发率高：流量覆盖全 bank / postpone 过深）→ Knob（档位/postpone/ab-pb）→ Experiment（depth sweep + tier 统计）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 Normal REFab 压过 critical REFpb？（一条还全部债 vs 只还一条）
- double：tier3 占比 50% 说明什么？（流量覆盖全 bank，REFpb 粒度收益消失）
- workload：什么负载下 REFpb 优于 REFab？（bank 覆盖稀疏、其他 bank 可隐藏）
- protocol：REFsb 为什么是"同 index"？（协议刷写组织 → Memory_Protocal.md）
- failure：进 SR 时还有 critical？（drain 判据 = bank 全关 ∧ critical 刷完 [RTL]→G1）
- redesign：REFpb 真并行（多 bank 同时）？（协议编码限制 [SPEC]）

#### ⑪ Interview Hook
**Tradeoff Hook**："refresh 调度的一切技巧都在回答'怎么让 tier3 少发生'——三层准入 + 两步 critical + 性价比优先级序，全部服务这一个目标。"


## 7.3 M3 — Refresh Deadline Tracking（LEAF · 高价值展示题）

#### ① Interview Entry
- 为什么不用 per-bank refresh timer？
- 9×tREFI 和 8×tREFI 分别是什么？
- Odd/Even 两个 counter 怎么覆盖所有情况？
- 这个机制的 correctness 前提是什么？
- 它是 exact tracking 还是保守估计？

#### ② Core Conclusion
[MODEL] 泛化结论：Odd/Even watchdog 的本质，是利用"**每 bank 每 round 必完成一次 REFpb**"的 scheduler invariant，把原本需要 **N_bank 个 per-bank age/timestamp tracking** 的问题，压缩成**两个 overlapping round watchdog**——conservative sufficient condition。
[RTL] 本配置事实：当前 HBM4 64-bank 配置下，相当于 64 个 per-bank tracking state → 2 个 global watchdog（6.2.1 per-bank 64 bank；13.2 refpb_req[63:0]）。**通用结论不带数字**；bank 数随协议/配置变化。
[标签分层] Δt 推导 [MODEL]；max interval [SPEC, scope→RF-P1-09]；counter 机制（计数/复位/threshold/round_complete/起点）[RTL]。

#### ③ Problem
REFpb 模式的协议义务是 per-bank 间隔：同一 bank 相邻两次 refresh 的间隔有上限。为每个 bank 各挂 age counter 代价大；需要结构性压缩且不破坏正确性。

#### ④ Performance & Correctness Model
- **round 定义** [RTL]：refresh round = 全部 bank 各完成一次 REFpb；同一 bank 相邻两次刷新的最大间隔 < 两个 round（前一次在 round 头、后一次在 round 尾）；
- [MODEL] 推导：Δt_bank = (Tn − xn) + x(n+1) ≤ Tn + T(n+1)——**只需任意相邻两个 round 的累计时长不超限**；
- [SPEC·scope→RF-P1-09] hard deadline：Tn + T(n+1) ≤ 9×tREFI（在当前适用的 protocol/mode 下）；
- [RTL] early-warning：本项目 critical threshold 取 **8×tREFI**（对协议 9× 留裕度——给 drain/PRE/REF issue 留完成余量）；**8× 是实现裕度，不是协议要求**；
- **Correctness Invariant**：round_complete ⇒ 本 round 的所有 target bank 已实际完成 REFpb。若允许某 bank 被跳过整个 round，Tn+T(n+1) bound 不再保证 per-bank 间隔——watchdog **不是无条件正确**，它依赖该 scheduler invariant（其 RTL 保障 = RF-P1-06 [TODO-RTL]：tier 准入下是否存在整 round 跳过场景、critical 是否唯一兜底）；
- [口径] conservative vs exact：8× 对 9× 留裕度 + round-pair 上界 = 保守充分条件，非精确追踪。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- Odd 计数器覆盖 Round0+1 / 2+3 / 4+5…；Even 覆盖 Round1+2 / 3+4 / 5+6…（错相配对覆盖全部相邻 round 对）；Odd round 结束清 Odd、Even round 结束清 Even；
- 任一计数器 ≥ 8×tREFI → critical（对协议 9× 留裕度）；
- 计数起点 = REFab 发出拍或本轮最后一个 REFpb 发出拍；
- 与 tFAW 的 4 错相计数器同族——"计数器组复用"设计哲学的另一实例（0.7）。

#### ⑥ Interaction
← **M2**（round 推进事件）；→ **M1**（critical 拉响）；→ **P1**（N_bank→2 的状态压缩收益）；cross-check：round-complete invariant 断言（L 域）；tier 分布统计（invariant 的运行时健康度 [MODEL]）。

#### ⑦ Alternatives
- **per-bank age counter**（N_bank 个）：精确、直白；代价 = 计数器面积/布线随 bank 数线性增长 [MODEL]；
- **单 counter**：不够——round 配对存在奇偶两种相位，单 counter 有盲区 [MODEL]；
- 固定 bank 递增顺序是否带来额外 safety margin；固定 order vs 固定 phase 的区别——OPEN [TODO-RTL：RF-P1-07]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] 收益：O(N_bank)→O(1) 状态压缩 + 结构性保证；代价：conservative（提前拉 critical 的性能余量）+ 对 invariant 的依赖（invariant 破坏 = bound 失效——不是渐进退化而是保护消失）。

#### ⑨ Proof（含诊断闭环）
- [RTL] counter 值/阈值比较（ref critical 经 dbg_obv 可观测）；验证 = min-gap 同族的 round 间隔覆盖 + round-complete invariant 断言；
- Closure：RF-P1-06（invariant 保障）[TODO-RTL]；RF-P1-07（固定顺序 margin）[TODO-RTL]；
- 诊断闭环：Symptom（critical 频发但 debt 低）→ Observable（Odd/Even 计数值）→ Hypothesis（round 拉长：tier3 阻塞 / REFpb 供给不足）→ Knob（→M2）→ Experiment（round 时长分布 trace）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么检查相邻两个 round 就够？（同 bank 相邻 REF 只跨相邻 round——几何事实）
- double：bank 数翻倍，压缩率怎么变？（N_bank→2 收益随 N_bank 增大）
- workload：什么流量会破坏 invariant？（特定 bank 长期被 CAM 占住 → tier 全堵 → RF-P1-06 结论）
- protocol：其他协议 refresh interval 语义一致吗？（9×tREFI scope → RF-P1-09）
- failure：counter 被错误清零会怎样？（bound 失效——保护依赖错相清零时机正确 [RTL]）
- redesign：exact tracking 什么时候值得？（N_bank 小到 counter 便宜 / 需要精确 deadline 的场景）

#### ⑪ Interview Hook
**Measurement Hook（展示链）**："这是一道完整的 Protocol Requirement → Mathematical Sufficient Bound → Scheduler Invariant → RTL State Compression → PPA/Performance Tradeoff 链条题——20 秒讲结论，或从 Δt 推导讲起，取决于你想往哪层走。"


## 7.4 M4 — Activation Maintenance / RFM（LEAF）

#### ① Interview Entry
- RFM 和 REF 有什么本质区别？
- RAA / RAAIMT / RAAMMT / RAAMULT 各是什么？
- ACT 怎么"欠债"？RFM 怎么"还债"？
- bank FSM 状态和 activation debt 是一回事吗？
- Need_RFM / Can_RFM_now / Issue_RFM 为什么分三层？

#### ② Core Conclusion
[RTL] 实现事实：MC 侧 **per-bank ACT 计数 = activation debt**；阈值 **RAAMMT = RAAIMT × RAAMULT**（RAAIMT 为厂商离散档位）；达限动作 = **该 bank 禁 ACT**（兜底，不是首选调度动作）；清账 = 发 RFM（优先级序见 M2）；DRFM 是其定向变体（→M5）。
[MODEL·双状态轴] **Bank State Axis**（open/closed/activating/precharging——PRE/AP 等操作主要改变 row-open/close 状态）∥ **Activation Maintenance Axis**（activation history / RAA / maintenance pressure）是两条不同的状态轴；**RFM 明确作用于 activation-maintenance state**；**REF/REFab 是否以及如何改变 activation debt，保持 [TODO-SPEC]/[TODO-RTL]（RF-P1-02），双状态轴模型不预先下结论**。
[MODEL·三层抽象] **Need_RFM**（maintenance pressure）/ **Can_RFM_now**（bank state + timing legality）/ **Issue_RFM**（scheduler arbitration）——抽象本身 [MODEL]；对应真实机制（RAA threshold→ACT forbid、BSC/timing ready、FSC arbitration）已分别有 [RTL] 证据。

#### ③ Problem
RowHammer 使 ACT 本身成为风险行为：高频激活同一 row 需要对相邻 row 做定向维护——controller 必须把"激活活动"变成可记账、可限制、可清偿的义务，与时间债（M1）并行管理。

#### ④ Performance & Correctness Model
- [MODEL·引用 Protocol 文档] 单 bank 带宽税 = tRFCpb / (RAAIMT × tRC + tRFCpb)；所需 RFM 速率 = 1/(RAAIMT × tRC)——RAAIMT 是厂商离散档位，非连续可调；
- [OPEN·RF-P1-02] REF / REFab 是否以及如何降低 activation debt——未确认，不在模型中预下结论；
- [OPEN·RF-P1-03] RAADEC（协议侧 HBM3 厂商阈值，IEEE 1500 WDR 可读）在本 RTL 如何映射——[TODO-SPEC]；
- [OPEN·RF-P1-04] PRE / RDA / WRA 对 RAA 的精确影响（RDA/WRA 含 PRE 语义但仍属激活活动）——[TODO-SPEC]；
- [OPEN·RF-P1-05] DDR / LPDDR / HBM 的 activation-debt 记账语义是否一致——[TODO-SPEC]；
- 原则：**聊天中讨论过 ≠ 当前项目 RTL 已确认；某一个协议成立 ≠ 所有协议成立。**

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- per-bank ACT 计数（owner = refresh/RFM 模块）；RAAMMT 达限 → 禁 ACT（FSC 感知）；
- RFMpb 在 FSC 维护优先级序中的位置（critical RFMpb > Normal REFpb）；
- 与 REF 共享执行路径资源（tRFCpb counter 等 →Ch15）。

#### ⑥ Interaction
← **T2**（ACT 事件计数）；→ **T2**（达限禁 ACT）；→ **M2**（RFM 优先级插入）；→ **M5**（定向升级）；cross-check：O1 RFMpb/ACT 计数；带宽税模型校准 [TODO-MEASURE]。

#### ⑦ Alternatives
- **ARFM（自适应阈值）**：协议侧可选演进 [SPEC→Memory_Protocal.md §4.7]；本 RTL 未实现 [BOUNDARY]；
- **PRAC + ABO**（LPDDR6 显式上报+退避）：未涉及 [BOUNDARY]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] RAAIMT 档位选择 = 维护频率 vs 风险覆盖（离散档位 → 防护粒度阶梯化）；禁 ACT 兜底意味着 activation debt 处理不当时性能骤降——是 safety net 不是调度策略。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] RFMpb executed 计数、ACT 计数（debt 增速）；禁 ACT 事件直接 counter 缺口 [TODO-RTL] 待确认；
- Closure：带宽税模型校准（per-workload RFM 频率实测）[TODO-MEASURE]；四个 OPEN（RF-P1-02~05）逐项关闭；
- 诊断闭环：Symptom（禁 ACT 频发 / RFM 计数异常）→ Observable（ACT/RFM 计数）→ Hypothesis（RAAIMT 档位过低 / hammer 型流量）→ Knob（档位——若可配）/ 上游限流 → Experiment（流量重放）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么禁 ACT 是兜底而不是调度策略？（safety 优先——性能让位风险控制）
- double：RAAIMT 档位降一半会怎样？（RFM 频率↑、带宽税↑ [MODEL 公式]）
- workload：hammer 型流量画像？（同 row 高频激活——计数集中少数 bank）
- protocol：HBM3/DDR5/LPDDR6 的 RAA 语义一致吗？（[TODO-SPEC：RF-P1-05]；演进链 → Memory_Protocal.md）
- failure：REF 能顺便还激活债吗？（RF-P1-02 OPEN——当前不假设）
- redesign：debt 记账放 DRAM 侧？（PRAC 演进方向 [SPEC→BOUNDARY]）

#### ⑪ Interview Hook
**Concept Hook**："bank FSM 管的是 row 开没开，activation debt 管的是 row 被打了多少下——两条状态轴、两个 owner，混在一起讨论 RowHammer 是最常见的概念错误。"


## 7.5 M5 — DRFM / Directed Maintenance（LEAF）

#### ① Interview Entry
- DRFM 和 RFM 的区别？"directed"定向的是什么？
- target row 怎么指定？controller 还是 DRAM 决定？
- 为什么 DRFM 序列是 maintenance state machine 而不是普通 REF？
- controller 和 DRAM 在 RowHammer 防护上怎么分工？

#### ② Core Conclusion
[双层拆分] **A. Controller-side Target Selection [RTL]**：csrBakNDrmRowAddr——controller 内部选择哪个 problem/aggressor row 作为 directed-maintenance 操作对象（回答"MC 想处理哪个 row"）。**B. Protocol-side Target Handoff [TODO-SPEC/RTL]**：ACT → PRE/AP sampling → DRAM 内部 DRFM target register → DRFMpb 的交接序列（回答"这个 row 信息最终如何交给 DRAM"）——**不写"DRFM command 直接携带完整地址"，除非协议明确确认**。
[RTL] **DRFM 由 DEVMGR 生成**（非 refresh 模块）；**序列是 maintenance state machine**：三寄存器管生命周期——csrtDrfmpb（DRFMpb 后 tDRFMpb 禁 ACT）/ csrtDrfm2pre（ACT-with-DRFM 后最早关行）/ csrtDrm2preMax（到点强制关行）；配套 tDRFM_act2pre / tDRFMPB / tDFRMI / tDRFMmax counter 在册（→Ch15）。
[职责边界·两行 Protocol Fact→Consequence] Controller 指出 problem/aggressor row；DRAM 基于内部 physical mapping/remap 决定实际维护的 neighboring victim rows（BRC 有界覆盖语义）。**不展开 DRAM 内部 RowHammer implementation**。

#### ③ Problem
[MODEL] non-directed RFM 只携带 activation-maintenance obligation，**缺少 aggressor-row 邻域的 target information**（RFMab / RFMpb 的实际作用粒度取决于具体 protocol/mode，此处不泛化为"全 bank"）；DRFM 增加 directed target handoff，使维护动作聚焦风险 row / neighborhood——带宽代价有界化的演进方向（RFM→ARFM→DRFM/BRC→PRAC/ABO 链）。

#### ④ Performance & Correctness Model
- [MODEL·引用 Protocol 文档] DRFM = 用采样 address 对相关 row 定向维护（非黑盒全刷）；BRC = 一次 DRFM 以采样 row 为中心、向两侧最多覆盖的物理临近 row 范围——把行锤响应从全局长刷新改为目标 bank 的有界定向刷新，带宽代价最小化；
- [RTL] 时序义务：DRFM ACT 的驻留/关行/禁 ACT 生命周期由三寄存器 + counter 家族管理（correctness 约束非性能选择）；
- [SPEC·演进定位] HBM4：ACTIVATE 带 DRFM bit 标记风险 bank → 其后对该 bank 的 RFMpb 即 DRFMpb；DDR5：MR59 RAA counter 信用制——演进对比 → Memory_Protocal.md §4.7。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 生成方 = DEVMGR（定向维护 worker 语义，地址 = csrBakNDrmRowAddr）；
- FSC 优先级序位置：critical DRFMpb（介于 critical RFMpb 与 Normal REFpb 之间）；
- PRAC / ABO：本 RTL 未涉及 [BOUNDARY]；
- **观测缺口**：CS 侧 14 种命令 executed 计数不含 DRFM——cross-check 缺抓手（X-P1-09 [TODO-RTL]）。

#### ⑥ Interaction
← **M4**（风险定位/计数来源）；← **G1**（DEVMGR 生成方）；→ **T2**（tDRFM counter 家族：禁 ACT/关行时序）；→ **M2**（优先级序）；cross-check：O1（当前缺口：无 DRFM 计数 → X-P1-09）。

#### ⑦ Alternatives
- **non-directed RFM** [MODEL]：缺少具体 row-level target information，maintenance granularity 可能更粗，在部分 workload / protocol mode 下可能暴露更大的 maintenance cost——实际代价取决于 RFMab/RFMpb 粒度、protocol/mode、workload activation distribution、target localization ability；**不宣称"带宽代价无界"**；
- PRAC + ABO（显式上报+退避）：LPDDR6 方向，本 RTL 未涉及 [BOUNDARY]；
- controller 侧不管理（全交 DRAM 自刷新防护）：与 RAA 计数职责划分冲突 [SPEC 边界讨论→Protocol 文档]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] DRFM 的收益上限 = 风险 row 的聚集度（越集中越省）；采样/标记机制的精度（BRC 覆盖范围）决定防护完备性——协议侧参数。

#### ⑨ Proof（含诊断闭环）
- [RTL] DRFM 命令下发路径存在（DEVMGR→FSC）；**executed 计数缺失**（X-P1-09 [TODO-RTL]——补计数或确认已有未列出）；
- Closure：handoff 序列确认 [TODO-SPEC/RTL：RF-P1-08]；DRFM 频率与 hammer 流量关联 [TODO-MEASURE，依赖 X-P1-09 关闭]；
- 诊断闭环（受限）：当前 DRFM 频发只能经 csr 状态间接推断——观测补齐后走标准九步。

#### ⑩ Interview Follow-up Graph
- why：为什么由 DEVMGR 而不是 refresh 模块生成？（定向维护是"设备管理事件"语义——与 M2 优先级序汇合但生成源不同 [RTL]）
- double：BRC 覆盖范围翻倍会怎样？（防护↑、单次 DRFM 代价↑ [MODEL]）
- workload：aggressor row 分散 vs 集中的代价曲线？（DRFM 收益上限，→⑧）
- protocol：DRFM command 到底携带什么？（RF-P1-08 [TODO-SPEC]——含 sampling 时序）
- failure：target register 未被正确 sampling？（handoff 断链——协议序列待确认项）
- redesign：controller 侧做 victim row 跟踪？（DRAM 内部 remap 不可见——[SPEC 边界]）

#### ⑪ Interview Hook
**Boundary Hook**："聊 DRFM 我会先切两层：controller 选哪个 row（我做过），DRAM 怎么用这个信息（协议定义）——混在一起答最容易把 spec 义务说成自己的实现。"


---

**章尾小结**：M1~M5 构成完整的 maintenance control plane——两本账（M1/M4）、一个 deadline 机制（M3）、一套调度与执行（M2）、一个定向演进（M5）。性能侧统一归因口径 = blocked_maintenance（Ch0.4）；协议适用范围类 OPEN 集中在 RF-P1-09。
# 8. Data Delivery & DFI Contract（DP1 / DP2 / DP3）

> **本章核心问题：当 command-side 已经制造出执行机会后，Data Path / DFI 为什么仍可能让 useful DQ transfer 断流？**
> 命令流与数据流在 WDP/RDP 分合、仅以 ptr 关联（Ch0.2 注记 3）。三个 Node 覆盖三段瓶颈：**DP1 = pre-issue write-data readiness**（data ready 晚 → FSC 发不了 WR → blocked_data，发生在 issue **之前**）；**DP2 = post-issue read-return / reorder / recovery**；**DP3 = controller↔DFI/PHY delivery contract**。WAW/RMW 数据面 → Ch9 C2；错误/重试 → Ch10 R1；内部 RTL 细节 → Ch16/Ch17。

## 8.1 DP1 — Write Data Availability（CORE）

#### ① Interview Entry
- 写数据什么时候必须 ready？谁在等它？
- WDP 满了会阻塞 admission 吗？
- credit 什么时候还、WDP entry 什么时候释放——为什么是两个时刻？
- 一拍双写为什么需要 DFI 预取？
- partial write / RMW 的数据怎么拼？

#### ② Core Conclusion
[RTL] 八段生命周期（DP-P0-01 定稿）：① W beats resize 64B 入 XMU buffer，**数据收齐 = 送 PA 的前置条件**（无条件规则）→ ② PA grant：CAM entry 与 WDP ptr 绑定 + BRESP（末 sub-command grant 拍）→ ③ CQ 发 fetch 请求经 FIFO → **WDP 有空 entry 才向 XMU 取数** → ④ 写 SRAM（XMU→WDP 1 cycle，burst 4 数据分放 4 SRAM）+ BE 入寄存器堆 → **data ready** → ⑤ CS 下发（col issued，不可回收）→ credit 即还、CAM entry 释放（**WDP entry 不释放**）→ ⑥ DFI 按 tphy_wrlat 持 ptr 取数（多 cycle）→ 读出侧编码 ECC/DBI/CRC → PHY → ⑦ DFI 取走 → **WDP entry 释放（数据所有权移交点）** → ⑧ DQ transferred；随后满足 tWR 等 **DRAM-side recovery obligation**（completion 三层见下）。
[RTL·本章核心结论] **两个生命周期解耦：credit 在 CS 调度拍归还，WDP entry 在 DFI 取走后才释放**——中间隔 tphy_wrlat 飞行窗口。**WDP 是独立于 CAM 的第二资源：WDP entry lifetime 从 WDP allocation/fetch 开始，覆盖 pre-issue overlap window → WR issue → post-issue DFI flight window——与 CAM lifetime 只有部分重叠，不覆盖完整 CAM residence**（"已下发未取数"的 ptr 由 DFI 侧跟踪）。
[口径·write completion 三层（terminology 本轮建立；authoritative 定义 → Ch9 C3）]
- **A. Master-visible completion** [RTL]：BRESP 已返回（末 sub-command PA grant）——master 视角 write 已获得 response；**≠ 数据已写入 DRAM**；
- **B. Controller command PNR** [RTL]：WR col issue 后该 DRAM 操作不可简单撤销（command-domain point of no return）；
- **C. DRAM-side physical / timing completion** [SPEC/MODEL]：DQ transfer 完成并满足 tWR 等 recovery obligation（device-side / recovery-safe timing point）。
三个时间点不得混用；统一模型由 Ch9 C3 收口。

#### ③ Problem
写方向的数据不是"跟着命令走"：命令窄通路已调度，数据宽通路可能还没取——ready 晚了 FSC 不能发（blocked_data），取数晚了占用膨胀。WDP 满的正确语义（不挡 admission、只挡 fetch）必须与容量模型一致。

#### ④ Performance & Correctness Model
- [RTL] **WDP 满不阻塞命令入 CAM**：admission 只看 credit 与 CAM 深度；WDP 无空位时 fetch 请求在 FIFO head-block 等待——写侧 blocked_data 的来源；[MODEL↔RTL 对齐] perf 模型将 WDB 与 WRITE CAM 建为独立资源、head-block 承担——同构；
- [MODEL] 容量模型（**时间轴修正**）：**CAM lifetime**（PA grant → 命令离开 CAM）与 **WDP lifetime**（WDP allocation/fetch → WR issue → DFI 取数/所有权移交）只是**部分 overlap**——WDP 并不覆盖完整 CAM residence。WDP occupancy ≈ **pre-issue overlap window**（自 WDP allocation/fetch 起，**非 PA grant**）+ **post-issue DFI flight window**；无完整 timing 数据，不给更精确公式——occupancy histogram / fetch wait / post-issue flight occupancy [TODO-MEASURE]；不足伤害 data-ready 延迟（调度可见性推迟），不是 admission；
- [RTL] WAW merge = 写口按 BE 拼接（后写者胜，纯数据操作）；RMW merge = 反向 BE 填充（→Ch9 C2）；**编码全部在读出侧**（merge 保持纯数据操作、编码只做一次 [RTL 设计理由]）；
- [MEASURED] 面积旁证：WDP 占 LPDDR6 10.40%（BL32 长 burst）vs HBM4 1.76%（BL8 短 burst）——缓冲代价随 burst 长度放大。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 存储组织：4×SRAM per CAM entry 粒度（burst 4 数据分放 4 SRAM）；**SRAM 单口**——两 entry 数据可能落同一 SRAM，同拍双读无结构性保证（HBM 一拍双写需 DFI 预取，→DP3）；
- BE/DM 存 WDP 寄存器堆（不占 SRAM；容量 ≈ CAM 深度 × 数据量/8）；
- 编码引擎（读出侧）：inline/sideband/link ECC、DBI、Write CRC（DDR，每 4bit DQ × BL16 覆盖 [RTL]）；
- HBM16G：DFI 预取一个 burst（4 条命令数据）缓存，支持一拍双写（→DP3）。

#### ⑥ Interaction
← **V3**（fetch FIFO 反压节奏）；← **C2**（WAW/RMW merge 数据面）；→ **S2/T3**（data ready 是 FSC 发 WR 的前提——blocked_data 归因）；→ **DP3**（tphy_wrlat 取数节奏 / prefetch）；→ **C3**（⑦ = 写数据所有权 PNR）；cross-check：O1（WDP 无直接 counter——观测缺口 [TODO-MEASURE]，blocked_data 靠 Ch0.4 恒等式反推）。

#### ⑦ Alternatives
- **WDP 满即反压 admission**：语义简单但会把后置资源变成前置门——与 credit 模型冲突，未采用 [RTL 决策记录]；
- **编码随写入口**（checkbit 落 SRAM）：merge 需重算编码——读出侧方案胜出 [RTL 设计理由]；
- **WDP entry 调度拍释放**：飞行期数据无处安放，不可行 [MODEL]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] WDP 深度不足 → fetch head-block → data ready 推迟 → write batch（D1）被截断；过深 → SRAM 面积（10.40% 已是 LPDDR6 第四大模块）；饱和判据 = fetch FIFO 非空率与 data-ready 推迟量的联合观测 [TODO-MEASURE：当前无直接 counter]。

#### ⑨ Proof（含诊断闭环）
- Closure：WDP 深度 sweep × 写密集负载 → blocked_data / write latency [TODO-MEASURE→X-P1-07]；fetch FIFO 非空率 trace；
- 诊断闭环：Symptom（write 侧 blocked_data 高）→ Observable（当前无 WDP 直接 counter——经 Ch0.4 恒等式 + fetch FIFO trace 反推 [TODO-MEASURE]）→ Hypothesis（WDP 容量 / tphy_wrlat 窗口 / 写突发）→ Knob（WDP 深度 / DFI prefetch）→ Experiment → Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 WAW merge 选"后写者胜"而不是读改写？（BE 拼接零读开销；checkbit 读出侧编码的配套设计）
- double：WDP 深度减半会怎样？（fetch head-block 提前、write batch 截断）
- workload：写突发 + 长 tphy_wrlat？（飞行期占用峰值——容量模型第一项）
- protocol：HBM BL8 为什么 WDP 便宜？（短 burst 数据浅 [MEASURED 面积]）
- failure：DFI 一直不来取数？（所有权在 ⑦ 才移交——⑦ 前错误可拦、⑦ 后只能中断 →C3）
- redesign：SRAM 双口化？（面积代价 vs 取消 DFI prefetch [TODO-DESIGN]）

#### ⑪ Interview Hook
**Concept Hook**："写通路最容易被误解的一点：WDP 满了 admission 照样放行——它堵的是取数不是进门。credit 和 WDP entry 是两个独立资源、两个独立释放点。"


## 8.2 DP2 — Read Return / Reorder（CORE）

#### ① Interview Entry
- DFI 没有 AXI ID，读数据怎么和命令对上？
- PhyRdLat 配错了会怎样？rolling 是什么？
- 读方向的不可回滚点是命令下发还是数据进 XMU？
- 同 ID 两笔 read，第二笔数据先回来，内部发生什么？
- retry 重发的命令怎么回到调度链？

#### ② Core Conclusion
[RTL] 七段生命周期（DP-P0-02 定稿）：① AR 拆分 + link node 分配（**node 索引 = reorder SRAM 地址**；读侧流控 = 前置资源，node 耗尽 → 不向 PA 发读请求）→ ② RD col 下发（命令不可回收），node index 随命令进入 DFI rddata path（命令信息 FIFO）→ ③ DRAM RL + capture（arrival-driven）；dfi_rddata_en 按 PhyRdLat 定时，data 由 valid 确认；**rolling ptr 在 DFI（起点 0，ctrlUpd/phyUpd 复位）**，rotator 输出完整数据 → ④ RDP：DBI 去除 / ECC·CRC 检查——CE 就地纠正上送；**UE 数据丢弃不上送、原 node/读 ID 保留 → retry** → ⑤ 按 node index 写 XMU reorder SRAM（每 core 每 DFI 拍一个完整 op）→ ⑥ link list **head-only**：node 在 sub-data→RDATA 转换时释放 → ⑦ RDATA 重组返回（同 ID 保序、异 ID 乱序 interleave）。
[RTL·分层保序口径] **DFI 域内命令↔数据保序**（FIFO 绑定前提只在 DFI 成立）；**XMU 视角的乱序来自 scheduler 乱序调度，由 link list 收敛**——谈保序先说清是哪个域。双 PC = 双 core，各自独立通路。
[RTL·读 PNR 按 domain 拆分] 存在**两个不同的 rollback domain**：
- **Read Command PNR**：RD col 已 issue——此后不能假装该 DRAM read 没发生，命令已进入 device execution path（**command-domain**）；
- **Read Response / Recovery PNR**：在当前 RTL 中，读数据穿过 **RDP→XMU 边界**前仍可检测 UE / 丢弃当前返回 / 保留 node·读 ID / retry；跨过该边界后 response 收敛向 master-visible delivery（**response/recovery-domain**）。
两者不是"谁才是真正 PNR"的关系——**必须先声明 PNR 所属 domain**，否则"不可回滚点"一词没有意义。统一模型 → Ch9 C3（authoritative）。

#### ③ Problem
scheduler 的乱序收益（BLP/hit）制造了"返回序 ≠ 请求序"——需要保序收敛结构；读侧完整性检查（DBI/ECC/CRC）与 retry 需要明确边界；读写流控天然不对称（读 = 前置资源、写 = 后置资源）。

#### ④ Performance & Correctness Model
- [RTL·部分已知] PhyRdLat 相关事实：存在多频点 PhyRdLat 配置、dfi_rddata_en 定时、data_valid 确认、read data path FIFO 与 rolling path。**PhyRdLat 的精确语义边界尚未闭合**——它到底决定 capture enable / expected arrival window / metadata alignment / command-info FIFO pop timing / read-data FIFO sizing / rotator phase 中的哪些？data valid 与 PhyRdLat 各自承担什么责任？——**DP2-P1-01 [TODO-RTL + TODO-SPEC]**。PhyRdLat 配置错误会破坏 expected command/data alignment；精确 failure mode（valid miss / latency shift / metadata mismatch / burst alignment error）待 DP2-P1-01 关闭，不预设；
- [RTL] 返回带宽：每 core 每 DFI 拍一个完整 op（1 cycle）；HBM4 双发 → link node 每拍 2 个（[MODEL↔RTL 对齐] hbm4_model LINK_NODE_FREE_PER_CYCLE=2）；
- **retry count bound ≠ strict latency bound**：[RTL] retry 次数有界（≤15）→ [MODEL] retry amplification 的"次数"有限；但同 ID 后续 request 的**严格 HOL cycle upper bound** 还依赖每次 retry 的 worst-case service time / scheduler progress / timing legality / direction switching / maintenance interference / admission·queue availability——strict HOL time bound OPEN（**DP2-P1-02**）；
- [MODEL] 读写流控不对称：读 = 前置资源（node 耗尽反压 admission）；写 = 后置资源（WDP 只挡 fetch，→DP1）；

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- RDP = 完整性引擎（非大缓冲——读缓冲在 XMU reorder SRAM；面积反差：RDP LPDDR6 5.46% / HBM4 0.06% [MEASURED]）；
- CE/UE 判定都在 RDP；UE 处理链：retry 模块（流程控制/命令收集/命令确定/窗口控制）→ UIF 注入重发（消耗 credit 重走调度链、读 ID 原样复用）→ 上限 15 次（寄存器可配）→ 超限带 UE 标记返回 + 中断；
- **retry 只在 DDR 实现**（sideband ECC 配套）；LPDDR/HBM 无 retry——UE 首现即带标记上送 + 中断；
- UE→RRESP 通路：UE 标志存 link node 元数据信息表，RDATA resize 时转 SLVERR（normal/exclusive 同路）；
- 中断模型：UE/CE 分类、汇聚为一个总中断，软件查具体源（一级聚合+二级 CSR）；无坏 region 隔离 [BOUNDARY]。

#### ⑥ Interaction
← **V1**（link node = reorder 深度，容量公式 96/224）；← **DP3**（PhyRdLat/rolling/返回节奏）；→ **C1**（link list head-only 保序）；→ **R1**（UE 拦截/retry/PNR 边界）；→ O2（latency 无 RTL 观测 [MODEL only] 缺口；HOL cycles [TODO-MEASURE]）。

#### ⑦ Alternatives
- per-ID FIFO / centralized ROB → V1 ⑦ 已析（link list 胜出 [RTL]）；
- retry 通路放 RDP 内 vs **独立 retry 模块 + UIF 注入**（当前 [RTL]——重走调度链、复用全部既有机制）；
- 读数据缓冲放大（RDP 侧）：与"检查引擎非缓冲"定位冲突 [RTL 定位]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] head-only 保序的代价 = 同 ID 流水的 HOL（混挂场景在途 ID>32 时显现 [RTL]）；返回带宽饱和 = 每 core 每拍 1 op（HBM4=2）——重放型负载先撞 link node（前置资源）。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] 无读延迟/返回带宽直接观测——[MODEL only]（trace 后处理）声明边界；
- Closure：link list 8/16/32/64 对 reorder/area/HOL 影响（1-Q-03）[TODO-MEASURE→X-P1-07]；HOL cycles 统计；
- 诊断闭环：Symptom（读 latency 异常 / 同 ID 流卡顿）→ Observable（trace：node 占用、head 等待）→ Hypothesis（node 耗尽 / HOL / retry 窗口）→ Knob（node 数 / 流量整形）→ Experiment（trace sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 node 索引能直接当 SRAM 地址？（元数据与数据同址——link node 设计的核心省法 [RTL]）
- double：node 数翻倍 vs FIFO 加深？（前置资源 vs 弹性吸收的不同作用点）
- workload：多 ID 乱序 interleave 的收益？（返回带宽利用率）
- protocol：PhyRdLat 跨频点怎么配？（多频点寄存器表 [RTL]；rolling 协议背景 → Memory_Protocal.md）
- failure：UE 恰好在 exclusive read？（monitor 独立模块、同路 SLVERR [RTL]）
- redesign：retry ≤15 次数有界，能否推出同 ID HOL 的严格 cycle bound？（次数有界 ≠ 时间有界——依赖 service bound 前提，**DP2-P1-02 [TODO-DESIGN]**）

#### ⑪ Interview Hook
**Concept Hook**："读通路两句话：① 乱序发生在 XMU 视角，DFI 域内命令与数据是 FIFO 保序——谈保序先说清哪个域；② read 有两个 PNR——command PNR 在 RD issue，recovery PNR 在 RDP→XMU——不说明 domain，'不可回滚'这个词没有意义。"


## 8.3 DP3 — DFI Command/Data Contract（CORE）

#### ① Interview Entry
- DFI ratio 是什么？ratio 越高为什么 controller 越难设计？
- DFI 有流控吗？PHY 不收命令会怎样？
- HBM 双 PC 怎么合流？命令分时、数据并行是什么意思？
- PF window（shadow）解决什么问题？为什么是 8 选 2？
- CA parity 和 Write CRC 分别谁算、走哪条通路？

#### ② Core Conclusion
[RTL] **ratio 术语与定标**：DFI 规范（v5.1）定义 command frequency ratio 与 data frequency ratio；ratio4/ratio8 是 IP 对 **DFI 数据频率比**的 shorthand；DDR 无 WCK（退化为 DFI:CK 两段），三段比 DFI:CK:WCK 仅限有 WCK 协议。ratio 的本质 = **用 DFI 总线位宽换控制器时序**（ratio8 每拍 2 条命令、命令打包/phase 管理复杂度显著上升——"高频不自由"）。
[RTL·scope：normal command issue path] **normal command issue path 不提供 per-command ready/valid backpressure**——controller 把 normal DRAM command 交给该 issue path 后，不存在"PHY 对这一条命令返回 accept/reject"的普通调度握手；因此 **timing / phase / mode / PHY state 的合法性必须由 controller 在 issue 前自行保证**（CS 停发即冻结 [RTL]）。**这不等于"整个 DFI 协议没有 handshake / flow-control 类机制"**——training / update / low-power / ownership transition 属另一类 contract（→G1 / Ch17）；exact DFI version semantics 未逐条核实 [TODO-SPEC]。phase 纪律：SRE/PDE 等低频命令只在 phase0 发送（DEVMGR 侧）。
[RTL] **协议三形态**：HBM = 双 PC 奇偶 CK 合流（**命令分时、数据并行**——col 占 1 CK、row 除 ACT 外占 1 CK，PC0 奇/PC1 偶、ACT 轮流仲裁；数据 2 倍位宽直接合并）；LPDDR5 = 专用信号组（dfi_wck_en/toggle 等）；DDR = Write CRC（数据线、加 BL 传输、每 4bit DQ × BL16 覆盖 [RTL]）+ CA parity（独立 DFI 线、dfi_address 编码时 controller 侧生成）。
[RTL·HBM4 PF window] **调度影子（shadow）**：8 个 entry（一 CAM entry 对应一个），只存调度影子（CQ ptr/SID/BG），不搬命令——CQ/CCT/命令状态仍在 CQ、bank FSM/AC timing 仍在 CS（职责划分不变）；效果 = **64 选 2 → 8 选 2**（时序墙解法）。准入约束：同 BA 只一个 entry、优先不同 BG；释放 = entry 全执行完或被 critical refresh 打断；首命令优先排序。

#### ③ Problem
控制器频率上不去（工艺收敛）→ 用 ratio 换带宽 → 每拍要发多条命令 → 选择逻辑撞时序墙（64 选 2）→ 需要 shadow 降维；同时 **normal command issue path 不提供 per-command backpressure**——command/data alignment、phase、mode、issue legality 全部由 controller 在 issue 前保证（training / update / low-power / ownership transition 属另一类 DFI contract）。

#### ④ Performance & Correctness Model
- [RTL] **CK 映射即 AC timing 设计**：ratio8 下四相位 col 通道分配（PC0 col0→CK0 / col1→CK2；PC1 col0→CK1 / col1→CK3）——双发间隔恰好 = tCCD_S = 2；同拍可发 = 同 SID 不同 BG 的两条读或写；不强制双发（单条满足即发，不空凑）；
- [RTL] **一拍双写的 SRAM 难题**：双发两命令不同 BG → WDP 数据在不同 SRAM → 单口同拍双读无保证 → 解法 = **DFI 侧预取一个 burst（4 条命令数据）缓存**（→DP1）；
- [MODEL] ratio8 的代价清单：命令打包/phase 管理、选择降维（shadow）、写数据预取——**ratio 提高的全部复杂度都落在 controller 侧**；
- [口径·OPEN] CA parity 责任边界（controller vs PHY 计算）7-P1-04 [TODO-SPEC]；Write CRC"增加 BL"的协议适用范围 7-P1-05 [TODO-SPEC·部分已确认 DDR]；HBM 双 PC 奇偶 CK 为协议结构 vs DFI packing 实现 7-P1-09 [TODO-SPEC]。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- ratio4（LPDDR5-7200 @900MHz；HBM 1200MHz @SF4）/ ratio8（LPDDR5-12800 @800MHz；HBM4 16G 场景）；
- PF window：8 entry、准入/释放规则如 ②、双发规则如 ④；FSM 归 CS（RTL →Ch14，packing →Ch17）；
- init/training 归 PHY（MC 不可见 [BOUNDARY]）、init_complete 四计时器统一起点 → G1；
- Open 项：ratio 提高选"每拍多命令"而非提频的系统性论证（7-P1-10 [TODO-DESIGN]）；PF window 收益量化（PF-P1-01 [TODO-MEASURE]）。

#### ⑥ Interaction
→ **T3**（每拍命令数上限、tCCD_S 对齐的双发）；← **DP1**（写数据预取）；← **DP2**（PhyRdLat/rolling/返回节奏）；← **V2/S2**（shadow 的命令来源与释放回 CQ）；→ **G1**（phase0 纪律 / training 边界）；cross-check：O1 命令 mix；PF-P1-01 收益数据。

#### ⑦ Alternatives
- **提高 controller 频率**替代 ratio8：工艺收敛墙 [RTL 决策背景]；系统性对比（面积/功耗/BW 效率）OPEN [TODO-DESIGN：7-P1-10]；
- **shadow 更深**（16 entry）：选择空间 vs 比较时序再平衡 [TODO-DESIGN]；
- **CQ 侧多打一拍**替代 shadow：流水级增加 vs 降维的取舍（7-P1-12 [TODO-DESIGN]）。

#### ⑧ Tradeoff & Saturation Point
[MODEL] ratio 提高的收益/复杂度曲线：ratio4→8 带宽翻倍但打包/shadow/预取三件套成本上身——16GHz 是当前迭代的工程答案；PF window 饱和 = entry 内命令全部可执行且双发不空凑时的收益峰值。

#### ⑨ Proof（含诊断闭环）
- Closure：PF window miss/underfill 时的有效 command rate（7-Q-03 / PF-P1-01）[TODO-MEASURE→X-P1-07]；ratio4→ratio8 的 freq/命令每拍/面积/功耗/BW 效率定量比较（7-Q-01）；64 选 2→8 选 2 的 critical path 改善量（7-Q-02 / synthesis）；
- 诊断闭环：Symptom（每拍发不满 2 条）→ Observable（PF entry 占用、双发率 [MODEL/trace]）→ Hypothesis（准入约束过滤 / AC timing 不满足 / shadow 空）→ Knob（准入策略 / entry 数）→ Experiment（双发率 trace）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 shadow 不搬命令？（职责不变是架构声明——CQ/CS 控制权保留，只降选择维度）
- double：8 entry → 16 会怎样？（时序再平衡 [TODO-DESIGN]）
- workload：双发不空凑什么时候发生？（同 BA 冲突 / AC timing）
- protocol：LPDDR5 有 shadow 需求吗？（ratio8 场景差异 [TODO-DESIGN]）
- failure：critical refresh 打断 PF entry？（释放条件之一——高优先级事件打断 [RTL]）
- redesign：DFI 加流控？（协议契约不支持——controller 侧自限 [SPEC 边界]）

#### ⑪ Interview Hook
**Tradeoff Hook**："ratio8 的三件套——命令打包、shadow 降维、写数据预取——是同一个决策的三张账单：用控制器复杂度买工艺频率。"


---

**Part I 章尾小结**：机会链（Demand→Visibility→Locality→Candidate→Timing→Direction→Maintenance→Data Delivery）至此全部展开——每环一个或多个 Architecture Node、每 Node 一个九步诊断闭环；所有量化缺口统一挂 X-P1-07 数据包。Correctness 约束（Part II）与 RTL 实现（Part III）见后续批次。
# Part II — Correctness Constraints

> **Part II 核心问题：为了 performance reorder 到什么程度仍然正确？错误发生后哪些 state 还能回滚、哪些已越过不可回滚点、谁负责收敛？**
> 每章仍按 11 字段模板；correctness 结论以 [RTL] 定稿为主、协议边界 [SPEC]/[BOUNDARY] 标注。**Ch9 C3 是全文 correctness terminology anchor**——Part I 的 completion/PNR 术语（DP1 三层、DP2 双 domain）在此收口。

# 9. Ordering / Dependency / Commit（C3 / C2 / C1）

> **章内顺序说明**：C3 先行（全局 terminology anchor），再展开 C2 Dependency、C1 Ordering——后两者的边界描述全部引用 C3 词汇。

## 9.1 C3 — Commit / PNR（LEAF · 全局 correctness terminology anchor）

#### ① Interview Entry
- write 的 commit 到底发生在哪一刻？为什么说不设单一 committed？
- read 的"不可回滚点"为什么有两个？
- RMW 中途出错，数据会坏在 DRAM 里吗？
- refresh / 低功耗 / DVFS 有没有 PNR？
- 已 BRESP 的 write 出错了怎么办？

#### ② Core Conclusion
[RTL·六术语统一（X-P0-01/05 定稿；吸收 Part I DP1/DP2 术语，本节为 authoritative 收口）] **不设单一 committed——commit 取决于视角**；六术语如下（write/read 对照）：

| 术语 | write | read |
|---|---|---|
| **Request accepted** | XMU 接收（ostd 分配；W 数据收齐 = 送 PA 前置） | AR 接收（link node 分配；node 耀尽 → 不向 PA 发读请求） |
| **Master-visible completion** | **BRESP @ 末 sub-command PA grant** | **RDATA 返回**（sub-data → AXI resize 完成） |
| **Command PNR**（command-domain） | WR col issue | RD col issue |
| **Data ownership transfer** | DFI 取数（⑦，→DP1） | —（capture 起数据即流动，无 MC 侧所有权点） |
| **Recovery PNR**（response/recovery-domain） | —（BRESP 后零回滚，无 retry 域） | **RDP→XMU 边界**（此前 UE 可拦截 retry） |
| **DRAM-side physical completion** | DQ transfer + tWR 等 recovery obligation [SPEC/MODEL] | DQ transfer（读无 tWR 义务） |

[RTL] **五链的 irreversible / transition boundary 与收敛责任均已定位（X-P0-05 CLOSED）**：write / read / RMW / refresh 使用明确的 **command-domain / recovery-domain PNR**；LP / DVFS 使用 **transition-entry / device-state transition point**（不把所有 irreversible transition 泛化为 PNR——PNR 是 domain-specific point）——见 ⑤ 矩阵。

#### ③ Problem
性能机制（BRESP 前移、乱序调度、retry）各自制造了"对外承诺"与"内部状态"的时间差——如果不建立统一 terminology，每个模块对"completed / 不可回滚"各说各话，RAS 与 drain 的边界就无法定义。

#### ④ Performance & Correctness Model
- [RTL] ②→③（BRESP→col issue）间隙 = "response 早于写入"现象窗口，长度 = CAM 驻留 + 调度延迟——窗口内同址安全由入口拦截维持（→C2）；
- [MODEL] PNR 前移的性能逻辑：BRESP 越早，master 的 outstanding 周转越快（→V1）；代价 = PNR 后错误只能 containment（→R1）；
- [Correctness] 每个 PNR 回答两问：**之后出错还能不能撤销？谁负责收敛？**

#### ⑤ Current Design
[RTL]（以下为五链矩阵；**rollback / irreversible 一律带 domain**——A = Master/Architectural Obligation，B = Command-domain，C = Recovery-domain；PNR 是 point 不是 interval）

| 链 | 撤销能力（按 domain） | PNR（point） | retry | 只能中断 / report | 收敛责任 |
|---|---|---|---|---|---|
| **write（普通）** | **A**：BRESP 后 master-visible obligation 已成立，不能通过 response 撤销成功；**B**：WR col issue 前尚未进入 command PNR（是否存在内部 cancel path 未确认——C3-P1-01 [TODO-RTL]，不假设支持 arbitrary cancel/replay） | **WR col issue**（command-domain）；**DFI fetch** = data ownership transfer | 无 write retry | DFI 取数后的数据错误 → containment / interrupt（无 write response rollback） | 中断 → SW |
| **read** | **B**：RD issue 后 command 不可撤；**C**：在存在 retry path 的 protocol/configuration（DDR）下，recovery PNR 前错误数据可被拦截不暴露给 master（LPDDR/HBM 无 retry path——首现即上送） | **RD col issue**（command-domain）；**RDP→XMU**（recovery-domain） | UE 拦截 → retry ≤15 次（仅 DDR） | 超限 → SLVERR + 中断（poison 出上游）；无 retry 配置首现即上送 + 中断 | RAS retry 模块 → SW |
| **RMW** | **B×2——RMW 没有单一 PNR**：RMW-RD issue = read command-domain 不可撤；RMW-WR issue = 最终 memory update 进入 write command-domain 不可撤 | **RMW-RD issue** 与 **RMW-WR issue** 两个 command-domain irreversible point | 无 | UE 读回 → 翻转低 2 位 checkbit 注入 poison、照常落盘、下次读出报 UE | poison 机制 + 中断 |
| **refresh** | **B**：REF command issue = irreversible maintenance transition **point**；其后 tRFC forbid window 是**resulting unavailable interval**（窗口本身不是 PNR） | **REF issue** | — | —（无数据路径风险） | M2 序列自恢复 |
| **LP / DVFS** | transition-entry 前可中止（drain/quiesce 未满足）；进入后按 worker sequence 收敛退出（device-state transition point——**不类比 RD/WR command PNR**） | **transition-entry / device-state transition point** | — | 无数据路径 PNR | G1 序列 + SW 轮询 CSR |

#### ⑥ Interaction
→ **DP1/DP2**（write 三层 / read 双 domain 的 authoritative 回指）；→ **R1**（PNR 后的 retry / 中断 / poison 边界）；→ **G1**（drain 判据 = bank 全关 ∧ critical 刷完）；↔ **C2**（窗口内安全机制）；cross-check：C3 六术语/五链矩阵 [RTL]、DP1⑦/DP2②、Ch10 R1。

#### ⑦ Alternatives
- **统一"单一 committed"概念**：否决——master/controller/device 三视角时间点客观不同 [RTL]；
- **PNR 前 rollback buffer**（写数据保留可撤销副本）：面积/复杂度代价大、且 BRESP 前移的设计前提即"PNR 后 containment"——未采用 [RTL 决策记录]；
- **read 无 recovery domain**（col issue 即终点）：retry 机制不存在的基础——与 10.5 冲突，否决。

#### ⑧ Tradeoff & Saturation Point
[MODEL] 六术语的粒度已覆盖当前全部五链；若未来引入新链（如加密路径），需按"撤销/PNR/retry/中断/收敛"五问重新入表——矩阵是该 Node 的扩展点。

#### ⑨ Proof（含诊断闭环）
- [RTL] C3 六术语与 DP1 八段/DP2 七段生命周期逐段对齐；五链矩阵与 Ch10/Ch11 [RTL] 记载一一对应；
- 验证：BRESP↔grant 拍对齐断言、col issued 后无撤回路径断言、retry 窗口边界断言（L 域）；
- 诊断闭环（correctness 版）：Symptom（数据不一致报告）→ Observable（UE/中断源、poison 标记）→ Hypothesis（越界写 / PNR 后错误路径）→ 定位（哪条链哪个 domain）→ 收敛（retry/中断/poison）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 BRESP 敢在写入前返回？（入口拦截 + 颗粒命令序的结构保证 →C2）
- double：BRESP 后掉电怎么办？（master 已认为成功，数据可能丢失——系统级风险，非 controller 契约 [RTL 口径]）
- workload：RMW 密集流的 poison 行为？（坏行带 checkbit 持久化、读出报 UE）
- protocol：tRFC 窗口内 DQ 真的完全空闲吗？（本 bank 不可访问、其他 bank 可继续 [SPEC]→M2）
- failure：retry 第 16 次仍 UE？（SLVERR + 中断——次数有界 ≠ 时间有界，DP2-P1-02）
- redesign：给 write 加 rollback？（推翻 PNR 前移设计——代价见 ⑦）

#### ⑪ Interview Hook
**Concept Hook**："谈 write completion 我必须反问一句：你问的是哪个 completion——master 看到的、controller 的命令 PNR、还是 DRAM 侧的物理完成？三个时间点差着整个调度深度。"


## 9.2 C2 — Dependency（CORE）

#### ① Interview Entry
- BRESP 提前返回后，同地址 read 立刻进来，怎么保证读到该 write？
- RAW/WAR/WAW/RMW 分别怎么处理？为什么只有 WAW 做 merge？
- 冲突检测为什么放 CAM 入口、为什么与 AXI ID 无关？
- 为什么不允许无冲突命令 bypass？
- RMW 读写窗口内的第三方同址请求怎么防护？

#### ② Core Conclusion
[RTL·统一原则（X-P0-02 定稿）] 冲突检测**全部在 CAM 入口**（PA grant 后命令已无 txn 信息，仅剩物理地址+属性）、**与 AXI ID 无关**、**单通路阻塞 + 结构保证顺序、不靠 forwarding**——AXI ID 只承担同方向保序（→C1 五分类第 5 行：入口拦截是数据正确性机制，不是 AXI 保序义务）。
[RTL] 五类处置：
- **RAW / WAR**：incoming Pending 在 CAM 入口（缓存于 **IPROC**——CQ 前入口处理级），**阻塞后续全部入队**（单通路结构天然保序）；已在 CAM 的冲突对象**提权至最高优先级**；冲突对象在对侧方向 → 更早触发读写切换（D1 触发③的实证）；**放行条件 = 冲突对象离开 CAM**（调度下发），此后数据顺序由颗粒保证；Pending 命令已消耗 credit、无泄漏；
- **WAW**：未上 CCT 的可 **byte-enable merge**（重叠字节后写者胜）；两笔 txn 的 BRESP 各在自己 grant 拍产生、**逐拍出现不同拍双发**（PA 每拍一条，3-P0-02 [RTL]）；merge 只合数据不吞 response；merge 后 entry 无 txn 信息、对冲突检测无影响；
- **RMW**：排斥 merge（自身先读后写）；**窗口防护 [3-P1-03 闭环 RTL]**：RMW-RD 下发后至 RMW-WR 离开写 CAM 前，同址 incoming 由通用入口检测拦截 Pending + **触发 RMW flush（提权尽快调度）**；离开后放行、靠 DRAM 命令序——窗口无死角；
- **Exclusive**：XMU monitor（1~16 个、EXOKAY/OKAY 判定、失败两路径）[RTL]；粒度与完整失效事件集 [OPEN：1-P1-06 TODO-RTL]。

#### ③ Problem
BRESP 提前返回制造"response 已回、命令未执行"窗口（→C3 的 master-visible 与 col issue 间隙）——同址安全必须由 controller 结构保证，而 forwarding / snoop 类方案被否决，剩下的手段只有入口拦截 + 阻塞。

#### ④ Performance & Correctness Model
- [RTL] 窗口模型：安全窗口 = grant → col issued（→C3）；窗口内 = 入口拦截；窗口后 = 颗粒命令序；
- [MODEL] HOL 代价 = Pending 阻塞的后续命令数 × 各自等待（3-Q-03 [TODO-MEASURE→X-P1-07]）；[RTL] 分拍冲突检测：深度 64 单拍可收敛、后续版本分拍（识别延迟 1~2 拍，量化影响 3-P1-11 [TODO-MEASURE]）；
- [RTL] "冲突检测是 CAM 深度无法增加的主要时序原因"（全相联全 entry 地址比较，比较器规模随深度线性涨）。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- IPROC 入口 Pending 级；冲突对象提权；对侧冲突 → GSC 切换动机；
- WAW merge 在 PA grant 之后（WDP 写口按 BE 拼接，→DP1）；merge 后 RAW/WAR 判定仅按物理地址；
- RMW：读写 CAM 各占一（credit 进 CQ 前确认）、RMW-RD 携写 CAM ptr（→DP2 绑定实证）、flush 提权；
- Exclusive monitor 独立模块（→RQ15 SLVERR 同路）。

#### ⑥ Interaction
← **L5**（物理地址是检测键）；→ **V2**（Pending/HOL = visibility 损耗）；→ **S1**（可提名集排除 Pending）；→ **D1**（对侧冲突触发切换）；↔ **C3**（窗口边界 = grant→col issue）；→ **DP1**（WAW/RMW 数据面）；cross-check：O2 blocked_dependency 归因、HOL cycles [TODO-MEASURE]。

#### ⑦ Alternatives
- **store-to-load forwarding / write buffer snoop**：否决 [RTL 决策记录]——单通路阻塞方案以 HOL 换结构性正确，无需比较数据通路；
- **per-bank 独立检测**（放 bank 侧）：破坏全局可见性前提（V2 global CAM 的配套）[MODEL]；
- **RAW/WAR 也做 merge**：方向不同无法 BE 拼接，语义不成立 [MODEL]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] 入口阻塞的代价随冲突率上升（RMW 密集 / 乒乓同址流）；flush 提权是缓解不是取消；分拍检测的 1~2 拍识别延迟在高冲突流下放大 HOL。

#### ⑨ Proof（含诊断闭环）
- [RTL] 冲突注入序列断言（RAW/WAR/WAW/RMW 各覆盖）；放行时机断言（离开 CAM 拍）；
- Closure：HOL Pending cycle loss（3-Q-03）、分拍检测 latency/throughput 影响（3-P1-11）、RMW ratio 0~100% 曲线（3-Q-04）[TODO-MEASURE→X-P1-07]；
- 诊断闭环：Symptom（blocked_dependency 高）→ Observable（命令 mix 的同址度、RMW 占比）→ Hypothesis（真依赖 / 伪共享 / RMW 窗口）→ Knob（上游分配 / 粒度）→ Experiment（地址分布重放）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 RAW 不做 forwarding？（转发需要数据通路旁路 + 冲突数据比较——单通路阻塞以结构换正确 [RTL 决策]）
- double：冲突率翻倍吞吐掉多少？（HOL 模型 [TODO-MEASURE]）
- workload：什么流量触发对侧切换例外？（read-after-write 乒乓）
- protocol：DDR mask write 的 partial 无 RMW 代价？（→协议差异，C2 只承担 HBM 形态 [SPEC]）
- failure：merge entry 与新 incoming 冲突？（merge 后仍按物理地址检测 [RTL]）
- redesign：入口检测放 XMU（更早）？（txn 信息在、但物理地址未映射——位置不可行 [RTL 结构]）

#### ⑪ Interview Hook
**Concept Hook**："RAW/WAR 入口拦截是数据正确性机制，不是 AXI 保序义务——协议里 slave 根本不维护地址序。把这两件事分开，ordering 的讨论能省十分钟。"


## 9.3 C1 — Ordering（CORE）

#### ① Interview Entry
- AXI 的保序义务到底有哪些？哪些是 controller 额外保证的？
- 同 ID 两笔 read，第二笔数据先回来，内部发生什么？
- 不同 ID 允许乱序，为什么还需要 link list？
- 为什么不做 AW/W 超时防死锁？
- BRESP 回了但 DRAM 没写，突然掉电怎么办？

#### ② Core Conclusion
[RTL·五分类（1.4.4 定稿）] Ordering 责任分五类：① **同 ID 同方向 read→read**：AXI 要求 slave 保证 → link list head-only 释放；② **同 ID 同方向 write→write**：同上 → B outstanding FIFO 顺序；③ **同 ID 不同方向**：AXI slave ordering obligation 不覆盖此组合（无保序义务）；在当前 system/controller contract 下，master 若以 BRESP 作为 write completion 观察点，后续同地址 read 的正确性由 **master sequencing + controller C2 address dependency protection 共同保证**（BRESP @ 末 sub-command PA grant）——address dependency protection 是 controller 额外 correctness mechanism，非 AXI 协议义务；④ **不同 ID 任意方向**：双方均不保证 → 乱序交织（link list + RR 分配）；⑤ **地址维度**：**地址不参与 AXI 保序**——RAW/WAR 入口拦截是自加的数据正确性机制（→C2），不是履行协议义务。
[RTL] **保序节点 = PA grant**：sub-command 被 grant 即到达保序节点；BRESP 生成条件 = txn 最后一个 write sub-command 被 grant（数据收齐是送 PA 的构造性前置，grant 时数据必已就绪）；提前返回的可见性不靠 ID——靠 CAM 入口 RAW/WAR 拦截 + 单通路阻塞（→C2）。
[RTL·明确取舍] **不做 AW/W 超时防死锁**：AXI 对 AW/W 到达无时间约束、协议无超时概念；后果 = 该 port AW ostd 占满 → **单 port 自饿**（PA 不锁死无请求 port、其他 port 与已入 core 命令不受影响——故障域隔离）；本 RTL 一律"数据收齐才送 PA"（不随 mask 能力改变），W 不来时差异仅在卡住的具体子步骤（HBM/RMW 卡在 resize）；责任边界在 master 侧系统兜底。

#### ③ Problem
BRESP 前移把"顺序承诺"从数据完成时刻提前到 grant 时刻——ordering 的五类责任必须逐一重新划界：哪些是 AXI 义务、哪些是自加保险、哪些交还 master；同时 link list/reorder 结构要在乱序收益与保序成本间平衡。

#### ④ Performance & Correctness Model
- [MODEL] 同 ID 保序成本 = head-only 释放的 HOL（混挂场景在途 ID > 32 时显现 [RTL]）；异 ID 乱序 = 返回带宽利用率收益（→DP2）；
- [MODEL] link list 设计的出发点：node 存 AXI 元数据、node 索引即 reorder SRAM 地址——容量随 CAM 折算（96/224 [RTL]，→V1④）；
- [Correctness] ③ 类（同 ID 异方向）的可见性 = master 侧约定 + controller 端 C2 拦截配合——两者缺一不可。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- link list 32 条：同 ID 必同链（刚性）；list 不足时允许混 ID 挂链（混挂换容量、不因此反压）——代价 = head-only HOL；
- BRESP：末 write sub-command PA grant 拍返回（构造性数据就绪）；
- AW/W 不同步：无超时防护（见 ②），单 port 自饿边界；
- CHI NoSnp：Comp/CompDB 在 PA grant 即回（与 AXI 同原则，数据先到条件合并）[RTL]。

#### ⑥ Interaction
→ **V1**（ostd/ROB 结构、node 容量）；→ **DP2**（返回收敛、head-only 释放点）；↔ **C2**（第 5 行拦截机制）；← **S2**（乱序来源——ordering 收敛的对象）；→ **C3**（master-visible completion 定义）。

#### ⑦ Alternatives
- **per-ID FIFO**：ID 数受限时面积线性涨、无混挂弹性——link list 胜出 [RTL 决策，1-P1-13 讨论保留 OPEN 分支]；
- **超时防死锁**：协议无超时概念 + 污染主通路——不做 [RTL 决策]；
- **延迟 BRESP**（数据落盘后回）：消除 C2 窗口但牺牲上游 outstanding 周转——与本设计前提相反 [MODEL]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] 混挂 HOL 饱和：在途 ID ≤ 32 时混挂零代价；[RTL] 单 ID 持续发包占住 list——head 持续推进、不阻塞自身，代价仅该 list 不可复用。

#### ⑨ Proof（含诊断闭环）
- [RTL] 同 ID 顺序断言（link list 序）、异 ID 交织断言、BRESP-grant 对齐断言；
- Closure：link list 8/16/32/64 sweep（1-Q-03）、BRESP 前移的上游 observed latency 收益（1-Q-04）[TODO-MEASURE→X-P1-07]；
- 诊断闭环：Symptom（同 ID 流卡顿）→ Observable（trace：list 占用、head 等待）→ Hypothesis（混挂 HOL / 单 ID 独占）→ Knob（ID 分配 / list 数）→ Experiment（trace sweep）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么同 ID 必同链？（head-only 释放的保序结构前提 [RTL]）
- double：list 32→64？（混挂 HOL 窗口缩小、面积↑）
- workload：单 ID 持续大流？（list 独占但 head 推进——不饿死自身）
- protocol：CHI 的 ordering 差异？（NoSnp 最小集内与 AXI 同 [RTL]；完整 CHI →Memory_Protocal.md）
- failure：异方向同地址 + 无 C2 拦截会怎样？（读旧数据——C2 是 ③ 类可见性的控制器半边）
- redesign：ordering 全交 NoC？（slave 义务仍在——协议不允许 [SPEC]）

#### ⑪ Interview Hook
**Concept Hook**："被问'ordering 靠什么'，我先反问：你问的是协议义务还是正确性保险？前者只有同 ID 同方向，后者是我自加的入口拦截——一句话划清边界。"

# 10. RAS / Recovery（R1）

> scope：**DDR read path 存在 recovery opportunity（retry ≤15）**；当前 write path 无 rollback（BRESP 后 containment）；Scheduler 只冻结不恢复。（LPDDR / HBM 无 read retry path——详见 10.1 ②。）

> **本章核心问题：错误发生在 PNR 之前还是之后，决定了"还能不能救"——检测在哪级、CE/UE 怎么分、retry 的边界、以及哪些场景只能 poison + 中断。**
> 术语全部引用 C3（command-domain / recovery-domain PNR、master-visible completion）；RAS 的设计哲学 = **read 可救、write 零回滚、Scheduler 只冻结不恢复**。

## 10.1 R1 — RAS / Retry / Recovery（LEAF）

#### ① Interview Entry
- ECC / CRC / CA parity 分别在哪一级检测？
- 读 UE 为什么能 retry？写 UE 为什么只能中断？
- BRESP 之后写数据坏了怎么办？
- retry 会打乱调度器吗？
- 坏 bank / 坏 region 怎么隔离？

#### ② Core Conclusion
[RTL·检测分层] **写侧**：编码全部在 WDP 读出侧（inline/sideband/link ECC + DBI + Write CRC——merge 保持纯数据操作 [RTL]，→DP1）；**CA parity** 在 dfi_address 编码时由 controller 侧生成（独立 DFI 线）[RTL]；责任边界 [OPEN：7-P1-04 TODO-SPEC]。**读侧**：DFI rotator 输出完整数据 → RDP 做 DBI 去除 / ECC·CRC 检查，**CE/UE 判定都在 RDP** [RTL]。
[RTL·R/W 不对称] **read 可救**：UE 数据在 RDP→XMU 边界（recovery PNR）前被拦截、不上送 → RAS retry 模块（流程控制/命令收集/命令确定/窗口控制）经 **UIF 注入重发**（消耗 credit 重走调度链、读 ID 原样复用、数据沿原 node 返回）、上限寄存器可配 **≤15 次**；超限 → 数据带 UE 标记返回 XMU、resize 时转 **SLVERR**（normal/exclusive 同路）+ 中断——**poison 沿读通路出上游**。**write 零回滚**：BRESP 后错误只中断上报（无 retry、无 response 通路）；RMW 读回 UE → 翻转低 2 位 checkbit 注入 poison、带病照常落盘、**下次读出判 UE**（merge 无法洗白 poison）。
[RTL·仅 DDR retry] retry 只在 DDR 实现（sideband ECC 配套）；LPDDR/HBM 无 retry——UE 首现即带标记上送 + 中断（等价 0 次重试）。
[RTL·Scheduler 冻结哲学] **下行停顿不存在 DFI 反压**——调度器停发即为冻结（CCT/CAM 状态不丢，恢复后原序执行）；读错误处理走独立 RAS 通路、**不反冲 Scheduler**；CCT 不存在"命令失效被抽走"场景（上表不可撤回）。**Scheduler 不做恢复，只做冻结**——异常交给专门 RAS 通路，调度器保持简单可验证。
[边界] 无坏 bank/rank/channel region 隔离机制——隔离责任归上层 [BOUNDARY]；中断模型 = UE/CE 分类汇聚为一个总中断 + 软件 CSR 查源（一级聚合二级查询）[RTL]。

#### ③ Problem
RAS 的本质约束来自 C3：**PNR 之后错误只能 containment**——所以 RAS 的全部设计问题是：检测点放在 recovery PNR 之前的哪里、retry 的资源与边界怎么管、poison 如何保证不被洗白、以及 Scheduler 如何做到"冻结即可"。

#### ④ Performance & Correctness Model
- [RTL] retry 资源流：UE 拦截 → node/读 ID 保留 → 重发消耗 credit → 重走 CQ/CCT/CS → 数据沿原 node 返回——**重试期间原 node 占用 → 同 ID HOL**；次数有界（≤15）≠ 时间有界（DP2-P1-02 OPEN）；
- [MODEL·引用 Protocol] 单 bank 带宽税与 RAA 义务 → M4（RFM 与 RAS 的交叉仅在维护语义，检测/恢复通路独立）；
- [Correctness] poison 不变量：坏数据 + 坏 checkbit 一起落盘 → 任何后续 merge/编码都不会把它变成合法数据 [RTL]；
- [SPEC·边界] Write CRC 覆盖 = 每 4bit DQ × BL16 [RTL 确认 DDR]；协议适用范围 [TODO-SPEC：7-P1-05]；CA parity 责任边界 [TODO-SPEC：7-P1-04]；
- **Detection domain ≠ root-cause domain**：检测点回答"错误在哪里被观察到"，不是"错误一定在哪里产生"。RDP 检出 UE 只确定错误在 controller read-data integrity check point 被发现——候选 root cause 包括 DRAM cell/array、DQ transfer、PHY、sampling/alignment、controller upstream data path 等，需 syndrome / link diagnostics 才能归因 DRAM；CA parity error 可**更强地指向** command/address transmission path（strongly narrows the failure domain toward CA path），仍非自动等同物理根因。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- 检测点：WDP 读出侧编码（写完整性）、RDP 检查（读完整性）、CA parity @dfi_address 编码、Write CRC；
- CE：RDP 就地纠正、正常上送（无 retry）；UE：拦截→retry（DDR）→SLVERR+中断（超限或 LPDDR/HBM 首现）；
- RMW poison：checkbit 翻转注入（9.5）；写侧普通错误：中断上报；
- RAS retry 独立模块 + UIF 注入；Scheduler 冻结语义（4.7）；exclusive monitor 独立模块（SLVERR 同路）。

#### ⑥ Interaction
← **DP2**（recovery PNR / node 保留）；← **DP1**（写编码点 / RMW 数据面）；↔ **C3**（PNR 决定可救性）；→ **V3/S1**（retry 注入消耗 credit 重走链）；→ **SW**（中断/CSR）；cross-check：O1 中断源查询；poison 传播 trace。

#### ⑦ Alternatives
- **写 retry**：[RTL] 当前实现未采用——BRESP 后无 write retry、无 response rollback path，后端 write error 经 containment / interrupt 收敛；[MODEL] transparent internal write replay 在架构上并非理论不可能，但至少要求 write data retention / failure detection / replay-safe state / duplicate suppression·idempotence reasoning / ordering·dependency preservation——当前设计未采用；若未来增加，将显著改变 data retention / PNR / ordering / recovery model（**不把 current implementation choice 写成 architectural impossibility**）；
- **读 UE 立即上送（无 retry）**：即 LPDDR/HBM 形态 [RTL 现状]；DDR 加 retry = sideband ECC 的配套收益；
- **Scheduler 内嵌恢复**：否决——"冻结哲学"（4.7）[RTL 决策记录]。

#### ⑧ Tradeoff & Saturation Point
[MODEL] retry 的性能代价 = node 占用 HOL + 重走调度链的带宽消耗；上限 15 是工程值（寄存器可配），无形式化最优——DP2-P1-02 关联；[RTL] 无隔离机制意味着单点坏 region 的影响面由 SW 管理（坦承边界 = 答辩加分）。

#### ⑨ Proof（含诊断闭环）
- [RTL] UE 注入测试（记忆库错误注入→SLVERR/中断/poison 链路）、retry 计数边界断言、poison 持久化断言；
- Closure：retry 窗口的性能代价 trace [TODO-MEASURE→X-P1-07]；中断聚合模型 SW 侧验证；
- 诊断闭环（correctness 版引用 C3 模板）：Symptom（SLVERR/UE 中断）→ Observable（中断源 CSR、retry 计数）→ Hypothesis（单 bit 漂移 / hammer / 电源）→ **Detection Point**（RDP UE / CA parity / WDP 编码侧）→ **Candidate Failure Domain**（检测点仅给观察位置：RDP UE 候选含 DRAM/DQ/PHY/sampling/upstream；CA parity 强指向 CA path）→ **Corroborating Evidence**（syndrome / link diagnostics / 错误注入重放）→ Root Cause / Containment（retry / 隔离上报）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 write 不做 retry？（BRESP 已回——C3 master-visible 不可撤 [RTL]）
- double：retry 上限 15→30？（HOL 时间上限变化——DP2-P1-02）
- workload：hammer 场景 RAS 行为？（RFM 兜底 + poison 累积 →M4）
- protocol：LPDDR 为什么没有 retry？（inline/link ECC 配套差异 [SPEC]→Memory_Protocal.md）
- failure：RMW 读回双 bit 错？（poison 落盘——数据不静默损坏 [RTL]）
- redesign：region 隔离进 controller？（quarantine 表 + 访问拦截——当前归 SW [BOUNDARY→TODO-DESIGN 候选]）

#### ⑪ Interview Hook
**Concept Hook（scoped）**："在本 DDR retry path 中，read UE 如果在 recovery PNR（RDP→XMU）前被发现，还有 retry 机会；一旦跨过 recovery PNR、或当前 protocol/configuration 根本没有 retry path（LPDDR/HBM），就只能向上游暴露错误 / 中断。write 则因为 master-visible completion 很早（BRESP），当前 RTL 在其后只做 containment。retry、poison、中断都是这套 domain 边界的推论。"

# 11. Global State Transition（G1）

> **本章核心问题：低功耗 / 切频 / PHY 协调必须"全局排空 + 互斥转换"——谁能发起、排空到哪才算安全、转换期间谁被 hold、失败怎么收敛？**
> 术语引用 C3：LP/DVFS 全程在排空后操作、无数据路径 PNR；drain 判据 = bank 全关 ∧ critical 刷完（同时要求）。实现主体 = DEVMGR（RTL →Ch17）。

## 11.1 G1 — Global State Transition / Quiesce（LEAF）

#### ① Interview Entry
- 低功耗进入前为什么要全链路排空？排空到哪一层？
- 七种全局转换（六 worker 类 + DSME 分支归属 OPEN）怎么保证互斥？"arbiter 是 mutex 不是 sequencer"什么意思？
- SR 进入的判据是什么？SR 期间 refresh 债怎么办？
- DVFS 为什么一定要在 SR 内切频？
- 转换卡死了怎么办？有看门狗吗？

#### ② Core Conclusion
[RTL] **组织形态 = 一台互斥准许 FSM（arbiter）+ 六台 worker 序列机（HW_LP / SW_LP / CTRLUPD / PHYUPD / PHYMSTR / DFS；DSME 为 LP worker 的 LPDDR 参数分支——是否独立 worker [TODO-RTL→DM-P2-02]）+ 独立 refresh 域 + 纯 CSR 接口（无固件序列器）**。arbiter 七态（IDLE / CTRLUPD / PHYUPD / PHYMSTR / DFS / SW_LP / HW_LP）、固定优先级 **DFS > PHYMSTR > CTRLUPD > PHYUPD > SW_LP > HW_LP**——**arbiter 是 mutex 不是 sequencer**：只做互斥 + 优先级 + grant/done 生命周期，转换序列知识零保留（新增转换只加 worker，arbiter 不动）。
[RTL] **drain 判据 = bank 全关 ∧ critical ref 补完**（同时要求、无先后）。**排空要求（drain requirements）与准入 / hold 策略（admission policy）分开——不同 transition 形态不同**：**DFS / clock gate** [RTL]：front-end 被 hold（XMU 反压）→ 在途请求排空（req==resp）→ CAM empty → bank 全 close → transition；**HW/SW LP** [RTL]：CS / command issue 被 hold 进入 LP sequence，**XMU 可继续接受 host request**（驻留期新到请求 = HW 唤醒源）→ 后端收敛至 bank close + critical settled → enter LP。逐层确认口径（hold XMU → req==resp → CAM empty → bank close）是 **DFS / clock-gate 类 front-end-stop transition** 的完整 drain sequence 表现；**HW/SW LP 不要求停止 XMU acceptance**——LP 的要求是 backend 收敛到对应 transition-safe quiesce，驻留期新到 host request 可作为 wake-up source。**drain requirements 与 admission / hold policy 是两个维度**。
[口径·归一] **全协议统一 = memory-path drained + SR 内切频**（DVFS 复用 DFI init 通道、多频点表 SW 预编程 + hw_freq_sel 选择）；LPDDR 的"非 SR 直切"是协议能力、本 RTL 未走 [RTL，C2 定稿]。

#### ③ Problem
多种全局转换（LP/PD/SR/DSME/DFS/PHY 训练协调/ctrlupd）若各自为政会状态爆炸且互相踩踏；它们共同的先决条件是"链路安静"，共同的后置义务是"refresh 债务与 PHY 状态不失续"——必须集中互斥、参数化序列。

#### ④ Performance & Correctness Model
- [RTL·idle/quiesce 分层（原 0.13.4，三层重构）]：**A. Memory-path drained**——当前 transition 所需的 data/command path 已达 drain condition（front-end idle = XMU 入口无请求、scheduler idle = CCT∩BSC ready 空，为其中间态）；**B. Transition-safe quiesce**——当前 transition 所要求的 bank state、critical maintenance、DFI/PHY handshake、timing legality 已满足，可安全进入 device/global transition（**SR entry 使用此层**：non-critical refresh debt 可合法带入 SR 并冻结——**debt==0 不是本 RTL 的 SR-entry invariant**）；**C. Debt-free idle**——refresh debt == 0（更强状态，非所有 transition 的必要条件）。legacy 术语"DRAM-safe idle"（drained + debt 清零 + 无 REF/timing）**退役**——其 debt==0 要件与 RTL 的 SR-entry 行为冲突；
- [RTL] 转换期反压分工：**LP 只 hold CS（不反压 XMU）**——host 请求可继续进入、驻留期到达的请求 = 硬件唤醒源（SRX 三来源之一）；**XMU 反压只存在于 DFS 和 clock gate**；ctrlupd/phyupd 只阻塞 CS 不动 host；
- [RTL] **SR 期 debt 冻结**：PRE_SRE 拍做 REFpb→REFab 折算，残存非 critical debt 带入 SR，SRX 后 IDLE 切回 REFpb、无强制立刻补刷（自然还账）；refresh 域并行、轻转换经 REF_CHECK 握手让路、重转换（PD/SR）mask refresh + 强制 AB；
- [Correctness·C3 对齐] 转换全程无数据路径 PNR——drain 保证无在途数据，转换中错误无数据一致性后果。

#### ⑤ Current Design
[RTL]（以下各条均为当前项目实现事实）
- **worker 全景**：HW_LP（csrIdleForSr 硬件触发，无 WCK_CHECK，只 hold CS）/ SW_LP（软件 CSR，进入与解除都由软件）**两台 LP worker 共参数分支（PD/SR 同 worker；PD 多 tCSPD 检查；本 RTL 仅 Precharge PD）** / CTRLUPD（间隔定时 + 超时兜底 + **SRX 后必做** + SW，WCK_CHECK，L3 静默口径）/ PHYUPD（PHY 按 type 发起：长 >8×tREFI 进 SR、短 REF/PRE 排空；PD 中 critical 先 PDX）/ PHYMSTR（dfi_phymstr_req，IDLE/SR 两分支，**MC 在 ack 后停发命令——总线驱动权移交 PHY，PHY 撤 req 后 MC 撤 ack 交还**）/ DFS（SW 触发、复用 DFI init 通道：DRAIN_QUEUE→SRE→DFS（assert dfi_init_start + 更新 dfi_freq_fsp/ratio）→等 init_complete→释放）；DSME 为 LP worker 的 LPDDR 参数分支（是否独立 worker [TODO-RTL→DM-P2-02]）；
- **SRE 公共段**（多 worker 复用）：触发源 = DFS / phyupd / phymstr / 软件 SRE / 硬件 SRE；命令从 DFI phase0 发出；**DFI LP 握手在 SRE 之后**；
- **驻留语义**：LP 是驻留状态、没有 done——worker 报 done 表示**退出**完成；
- **SRX 三来源**：SW / HW 流量唤醒 / PHY 触发（如撤 phyMSTR）——统一走 LP worker 的 PRE_SRX 退出序列；
- **恢复与 init 边界**：无 validate（MC 不做 MRR 回读校验，责任在 SW/PHY）；**MC 对训练不可见**（init 期 MRW 归 PHY、init 后 SW MRW、PHY retry 不可见）——init 完全在 arbiter 状态表之外（仅 DFS FSM 等待 INIT），init 窗口 DEVMGR 预载频点表 + 超时计数；**init_complete fan-out = arb 解锁 + 刷新计时 + ctrlupd 计时 + ZQ 计时四起点**；BIST 不在 init 流程（SW 触发）；
- **失败收敛**：[RTL/MODEL] 在 DFI / PHY / SW handshake contract 正常履行的前提下，worker sequence 设计为具有 **progress path**；由于没有 hardware watchdog，对 peer 永久不响应不存在 controller-local 的有限时间收敛保证——当前 failure handling = **CSR observability（csrDdrLpState / csrArbState）+ SW detection / intervention**（fatal 判定在 SW）。

#### ⑥ Interaction
← **M1/M2**（PRE_SRE 折算 / SR 期冻结 / mask refresh 握手）；→ **V3/V1**（hold CS / DFS·clock gate 反压 XMU）；→ **T1**（切频窗口 = IDLE 保证）；← **DP3**（DFI init/LP/phymstr 握手契约）；→ **C3**（转换无数据 PNR）；→ **M5**（DRFM 生成方 = DEVMGR）；cross-check：O1（SRE/SRX/PDE/PDX 计数、csrDdrLpState/csrArbState、dbg_obv 全套 FSM 状态）。

#### ⑦ Alternatives
- **序列逻辑分散在各模块**（LP 逻辑在 CS、DVFS 逻辑在 clock管理）：状态爆炸、互斥靠约定——否决 [RTL 决策记录]；
- **固件序列器**（SW 逐步驱动）：实时性/可靠性差——纯 CSR + 硬件序列 [RTL]；
- **中央 sequencer**（arbiter 直接控制序列）：加转换要改 arbiter——mutex+worker 架构胜出 [RTL]。

#### ⑧ Tradeoff & Saturation Point
[RTL] 互斥 = 转换串行化（不能并发低功耗+训练——按优先级排队）；[RTL·已知边界] 无看门狗 → 依赖 SW 轮询；DSME 序列细节与 clock gate 转换未展开（DM-P2-02 [TODO-RTL]）。

#### ⑨ Proof（含诊断闭环）
- [RTL O1] LP 进出计数（SRE/SRX/PDE/PDX）、双状态 CSR、dbg_obv FSM 全景；
- 断言：drain 判据（SRE 拍 bank 全 IDLE ∧ critical 完）、折算时点（PRE_SRE）、互斥（无并发 grant）；
- 诊断闭环：Symptom（LP 后首命令异常 / 转换卡住）→ Observable（csrArbState、worker 阶段）→ Hypothesis（drain 未完成即进 / SRX 序列未走完）→ Knob（idle 阈值 csrIdleForSr / SW 流程）→ Experiment（进出压力重放）→ Conclusion。

#### ⑩ Interview Follow-up Graph
- why：为什么 arbiter 不保留序列知识？（新增转换只加 worker——扩展性 [RTL 设计理由]）
- double：两种低功耗同时请求？（优先级 SW_LP > HW_LP 排队）
- workload：驻留期来流量怎么办？（XMU 接纳 = 唤醒源，序列不撕裂 [RTL]）
- protocol：LPDDR FSP 直切为什么不用？（协议能力 vs 本 RTL 统一 SR 路径 [RTL 决策]）
- failure：drain 中 critical ref 到来？（critical 补完是 drain 判据一部分——顺序内解决 [RTL]）
- redesign：把 done 语义改成进入完成？（驻留态无"完成"——退出才可验证 [RTL 语义]）

#### ⑪ Interview Hook
**Concept Hook**："全局转换我一句话：**arbiter 是 mutex 不是 sequencer**——互斥、优先级、grant/done 三件事，序列全在 worker；所以支持新协议转换时，arbiter 一行不改。"

# Part III — RTL Implementation Reference

> **Part III = Implementation Evidence, NOT new Architecture Reasoning。** Part I/II 已回答 why / model / tradeoff / correctness；Part III 只回答：**Architecture Claim → 真实 RTL 中由哪个 module / state / pipeline / resource / handshake / counter 实现**。
>
> **6+1 模板**：① Module Boundary（输入/输出/时钟域/协议接口/sideband/负责与不负责——防止 ownership 混乱）② Owned State（FSM/counter/FIFO ptr/credit/metadata——owner 是谁、consumer 是谁、谁能改、谁只读；one state → one owner → multiple consumers，与附录 C 交叉核对）③ Key Data Structures（depth/width/granularity/allocation/update/release/indexing/sharing/协议依赖；宽度未知标 [TODO-RTL] 不猜）④ Critical Pipeline（input event → stage → state update → decision → output event；标 allocation / compare / arbitration / issue / free / PNR·ownership / backpressure point；cycle 数无证据只画 logical pipeline 标 [TODO-RTL: cycle count]）⑤ Resource / Backpressure Lifetime（Acquire Event → Hold Condition → Release Event → Backpressure Consequence）⑥ Architecture Node Mapping（机制 → Node ID 回指，不重写 model）+1 Known RTL Limitation（真实 limitation 才写；无证据写 "No additional confirmed limitation"）。
>
> **纪律**：禁止重复 architecture reasoning（→回 Part I/II）；[RTL] claim 找不到 evidence → 回 Node 降 [TODO-RTL]；新 implementation fact 不自动升级为 architecture conclusion；数字分类 [RTL]/[MEASURED]/[APPROXIMATE]/[TODO-*]，不凑数；不做 signal dump。发现 RTL reality ≠ Part I/II claim → Summary 列 "RTL Evidence Conflict" 等用户裁决。
# 12. XMU / PA — RTL Implementation Reference

> Implements：**V1**（outstanding/AFIFO/link node）、**V3**（XMU 反压链）、**L5**（mapping @ PA grant）、**C1**（保序节点/BRESP/link list/五分类）、**C3**（Request accepted / Master-visible completion 定义点）、**C2**（exclusive monitor；RMW 转换）。

## 12.1 Module Boundary

- **输入**：多 master AXI ports（AW/W/AR；CHI NoSnp 经 normalization 等效 AW/W/AR）；时钟域 = **AXI clk（=NoC）**，经 XMU outstanding AFIFO 跨至 DFI clk（一物两用，→V1）；
- **输出**：读请求 + link node index → PA；写命令（数据收齐后）→ PA；BRESP → 上游（write response 生成点 = 末 sub-command PA grant 拍 [RTL]）；RDATA 重组输出（→DP2 返回链）；
- **sideband**：page_match_next（同 txn 静态同 page 预判 → PA 提权/缩短拆分）；AxQoS → region 映射；exclusive monitor EXOKAY/OKAY；
- **负责**：txn→64B sub-command 拆分、outstanding 管理、读 reorder/保序返回、写数据汇聚（收齐=送 PA 前置）、QoS→队列映射、BRESP 生成、exclusive monitor、RMW 转换（HBM）、burst type（INCR/WRAP；FIXED→SLVERR）；
- **不负责**：物理地址映射计算（AMAP 译码在 PA grant 点执行——物理地址写入 CAM 后逻辑地址弃用）、CAM 冲突检测（→Ch13 入口）、命令调度（→Ch4/5）、数据存储（→WDP/DP1）。

## 12.2 Owned State

| State | Owner | Consumer | 谁能改 |
|---|---|---|---|
| **XMU outstanding entry / ostd 计数** | XMU | PA（读请求携带）、AXI 反压 | XMU 分配/释放；只增减计数 |
| **read link list ×32 + link node** | XMU（node 索引 = reorder SRAM 地址） | DFI rddata path（index 随命令下行）、DP2 返回链 | XMU 分配/回收；DFI 只携带 |
| **write B outstanding FIFO** | XMU | AXI B 通道 | 按 grant 序 push/pop |
| **exclusive monitor ×1~16** | XMU（独立模块） | BRESP EXOKAY/OKAY 判定 | monitor 模块 |
| **AW/W 汇聚 + resize 状态** | XMU | PA | XMU |
| **PA credit 检查点** | PA（credit 本体 owner = PA↔CQ 协议，→Ch13） | PA 仲裁 | grant 消耗/CAM 归还 |

## 12.3 Key Data Structures

- **link node**：存 AXI 元数据（ID / size / len——sub-data→RDATA 重组用）；**node 索引即 reorder SRAM 地址**（元数据与数据同址——核心省法）；总数 = CAM_DEPTH × BURST / 2 + 补偿（LPDDR6 CAM32→96、HBM3 CAM64→224 补 64、HBM4 CAM96→224 补 32）[RTL]；burst 一次分配 4 个；
- **system address 假设 [RTL]**：40bit 系统地址入口；AXI"txn 不跨 4KB"契约下，4KB 边界计算用低 13bit（bit12 为 4KB 位；无硬件检测，依赖 AXI 契约）；burst type 支持 INCR/WRAP，FIXED → SLVERR [RTL]；
- **ostd entry**：txn 级（AW/W 汇聚 + resize 后 64B 数据）；深度 = 寄存器可配（AW 读/写分计）[TODO-RTL: 精确深度档]；
- **AFIFO**：深度与 ostd 配套 [TODO-RTL: depth]；CDC + buffer 一物两用；
- **exclusive monitor**：1~16 个（=port 数量级）[RTL]；**粒度与完整失效事件集 [OPEN：1-P1-06 TODO-RTL]**；
- **QoS region 寄存器**：读 2×regionField（三段→LPR/GPR/HPR）+ 3×regionMap；写两段→TPW/GPW [RTL]——分段线性映射，非硬连线。

## 12.4 Critical Pipeline

**写**：AW/W 到达 → resize 64B → ostd 分配【allocation point】→ 数据收齐（RMW 另加 resize/BE 处理）→ 送 PA → **PA grant【BRESP 生成点 = master-visible completion；mapping 执行点；credit consume 点】** → BRESP 入 FIFO 按序发出 → ostd 释放【free point】。
**读**：AR → burst 判定 → link node 分配【allocation point；node 耗尽 = 读流控点（不向 PA 发请求）】→ PA grant → 命令+node index 下行 → （→DP2 返回：head-only【free point】→ RDATA 组装）。
**PA 四层仲裁** [RTL]：①读写方向 → ②优先级（expired HPR/GPW、port aging）→ ③port priority（AXI QoS / port aging）→ ④RR；**每拍只 grant 一个 read/write request——这是本 controller 的 ingress/arbitration policy**（DDR/LPDDR DQ 为共享双向 half-duplex bus，单 grant 是 controller 侧策略而非总线物理属性）；**PA grant 拍 = mapping + credit consume + BRESP（写）三事件同拍**。

## 12.5 Resource / Backpressure Lifetime

| 资源 | Acquire | Hold while | Release | Backpressure 后果 |
|---|---|---|---|---|
| **XMU ostd（protocol/accounting tracking）** | txn accepted | 汇聚→grant→BRESP 发出 | **BRESP 发出** [RTL]（accounting release） | 满 → AXI 反压该 port（单 port 自饿边界；PA 不锁死） |
| **XMU write-data retention buffer** | W 数据写入（resize 后） | **直到 WDP fetch**（grant 后 CQ 才发 fetch 请求 [RTL：9.2-③]） | **WDP fetch = 所有权移交 WDP** | buffer 占满 → 新写数据等待（与 ostd 的关系 [TODO-RTL：XMU-P1-01]） |
| link node | AR accepted | 数据 pending/retry/head 等待 | head eligible 且 RDATA 消费 | 耗尽 → 不向 PA 发读请求（前置流控，→DP2） |
| PA↔CQ credit | PA grant | CAM 驻留 | 命令离开 CAM | 无 credit → PA 停 grant（→Ch13/V3） |
| link list | 首 node 分配 | 链上任 node 存在 | 全链释放 | 混挂 HOL（在途 ID>32）[RTL] |
| B FIFO slot | grant 拍 | 按 FIFO 序等发出 | B 发出 | FIFO 满 → 停 grant 写（推论 [TODO-RTL: 深度]） |
| XMU 前端（hold） | DFS/clock-gate 触发 | transition 期间 | 转换完成 | 反压 AXI（→G1；LP 不反压） |

> **protocol/accounting lifetime ≠ data retention lifetime**：BRESP 发出只释放 tracking/accounting；write data 在 XMU 侧 buffer 保活到 WDP fetch（[RTL：9.2-③]；tracking entry 与 data storage 的对应关系 [TODO-RTL：XMU-P1-01]）。

## 12.6 Architecture Node Mapping

ostd/AFIFO → **V1**；link node 公式 → **V1④**；XMU 反压/fifo_full → **V3/O1**；mapping@grant/AMAP → **L5**；BRESP/link list/五分类 → **C1**；Request accepted / Master-visible completion → **C3**；exclusive → **C2**；RMW 转换 → **C2**（HBM 形态）；region QoS 映射 → **S3**（接口）。

## 12.7 Known RTL Limitation

- exclusive monitor 粒度 / 完整失效事件集未确认 [TODO-RTL：1-P1-06]；
- WR col issue 前内部 cancel/replay path 未见证据——**C3-P1-01 保持 OPEN**（迁移证据中无 cancel/replay 结构 [TODO-RTL 维持]）；
- **demand-side observability**：当前 Ch12 已整理的 XMU/PA evidence 中，已确认存在 ostd 计数 / fifo_full 等部分观测；request-arrival / queue-empty / demand-side occupancy 是否存在直接 RTL counter——**尚未完成完整 inventory [TODO-RTL]**（closure → Ch18；确认不存在再转 [TODO-MEASURE]，由 trace / model 补齐）；
- **XMU ostd（accounting）与 write-data retention buffer 的 lifetime 拆分**：BRESP 发出 = accounting release；write data 在 XMU 侧 buffer 保活至 WDP fetch——两者是否同一物理结构 [TODO-RTL：**XMU-P1-01**]；
- AW/W 无超时防护为设计决策（非 limitation，→C1 ⑦）；
- ostd/AFIFO/B FIFO 精确深度档 [TODO-RTL]。

# 13. CAM / CQ — RTL Implementation Reference

> Implements：**V2**（global CAM / burst 双口径 / HOL）、**V3**（credit / 水线）、**S1**（三层 filter / CCT 单槽）、**S3**（CamAging / expired GPR 执行端）、**C2**（入口冲突检测 / WAW merge 命令面 / RMW flush）、**L5**（AMAP 单源消费端）。

## 13.1 Module Boundary

- **输入**：PA grant 后命令（**物理地址 + 属性；AXI txn 信息已在 grant 点剥离**——冲突检测与 ID 无关的结构前提）；credit 状态（PA↔CQ 协议）；
- **输出**：CCT 候选（per-bank，RD/WR 各一张）→ CS；fetch 请求 → WDP（写数据搬运）；水线 → GSC；
- **时钟域**：DFI clk（core）；**负责**：CAM 存储、burst packing、入口冲突检测（RAW/WAR/WAW/RMW/exclusive-RMW 防护）、三层提名 filter、CCT 维护、CamAging、credit 归还、IPROC Pending；
- **不负责**：timing legality（BSC，→Ch14/15）、最终仲裁（FSC，→Ch14）、policy 设计决策（→S2，本层只执行双模式）、数据存储与编码（→WDP/DP1）、AXI 保序（→C1/XMU）。

## 13.2 Owned State

| State | Owner | Consumer | 谁能改 |
|---|---|---|---|
| **CAM entry**（地址/优先级属性/GPR 超时基准/WDP ptr/读 ID/RMW 标志） | CQ | 三层 filter、CS、DFI（ptr 取数） | 入队写入/逐条下发状态更新 |
| **burst entry 合并态**（4 条共享 priority/aging/credit/lifetime） | CQ | CCT 提名 | CQ |
| **CamAging 计数**（burst 从首条进入起算） | CQ | priority filter（expired GPR 晋升标记） | CQ 递减/打标 |
| **CCT（RD/WR per-bank 单槽）** | CQ | CS（BSC 相与 → FSC） | 上表写入；发送后由 CS 回报释放 |
| **credit 计数** | PA↔CQ 协议（owner=信用机制本身，→V3） | PA | grant 消耗 / 离开 CAM 归还 |
| **IPROC Pending** | CQ 入口 | 后续入队阻塞 / RMW flush 提权 | 入口检测写 / 放行清 |
| **水线 set/clr** | CQ | GSC | 占用越线 |

## 13.3 Key Data Structures

- **CAM entry**：全相联；深度 32/64/96（协议配置 [RTL]）；字段 = 物理 addr（经 AMAP）/priority 属性/GPR timeout 基准/WDP ptr/读 ID/RMW 标志；**burst entry = 单 entry 打包 4 条同 page 同 txn 同方向命令**（col 由逻辑地址低 2bit 映射、固定顺序）；**burst merge key [RTL：3.3 准入条件]** = 同 page + 同 txn + 同方向三个比较域（另受剩余 burst 容量 ≤4 约束）；col 不要求连续；**双口径 [RTL]**：等效 256 = storage capacity（64×4），调度可见性（priority/aging/credit/提名）以 entry 为单位；
- **CCT**：per-bank 单槽 ×2（RD/WR），深度随 bank 数 [RTL]；上表不可撤回、发送后释放；
- **credit**：读（LPR+HPR 共享 = 读 CAM 深度）/ 写（TPW+GPW = 写 CAM 深度）；burst 按 entry 计（1 credit，末条归还）；
- **CamAging**：entry 粒度递减计数 + expired 晋升标记（不迁队列）。

## 13.4 Critical Pipeline

```
PA grant（credit consume【allocation point】；mapping 后物理地址）
→ 入口冲突检测【compare point——分拍：深度 64 单拍可收敛，后续版本分拍、识别延迟 1~2 拍 [RTL]】
   ├─ 冲突 → IPROC Pending【backpressure point：阻塞全部后续入队】
   │          + 冲突对象提权 / 对侧 → GSC 切换动机 / RMW → flush 提权
   │          → 放行条件 = 冲突对象离开 CAM
   └─ 无冲突 → burst 判定（同 page 同 txn 同方向 → merge 入 entry / 新 entry）
→ CAM 驻留（WDP fetch：写命令 grant 后 CQ 发 fetch 请求 → WDP 有空 entry 才取数【fetch 反压点】）
→ ① bank filter（全 entry 按 bank 筛出，不截断）
→ ② priority filter（双模式排序；expired GPR 恒第一【arbitration point】）
→ ③ oldest filter
→ CCT 上表【不可撤回；每拍每 bank 一条提名】
→ CS 发送（逐条；entry 内固定顺序）【issue point——**非末条 issue：更新 entry 内进度，entry 与 credit 均保留**】
→ **末条 issue / 离开 CAM / credit return / entry free = 同一事件**【free point，[RTL：3.4.1 burst entry 由最后一条命令归还]】
```

## 13.5 Resource / Backpressure Lifetime

**credit 与 physical entry 是两个 lifetime**（credit 在 IPROC 阶段已被 reservation，physical entry 可能在 conflict resolve 后才 allocation，merge 情况不产生新 entry）：

| 资源 | Acquire | Hold while | Release | Backpressure 后果 |
|---|---|---|---|---|
| **A. Credit reservation** | PA grant（Pending 已消耗） | IPROC Pending **或** CAM residence | 对应 entry/request 离开 credit ownership domain（entry 级 = burst 末条离开 CAM；精确拍 [TODO-RTL]） | credit==0 → PA 停 grant（→V3） |
| **B. Physical CAM entry** | conflict resolve 后 new-entry allocation，或 **merge into existing entry（不产生新 entry）** | entry residence + 逐条下发进度 | burst 末条离开 CAM（与末条 issue / credit return 同拍 [RTL：3.4.1]；独立 free 信号确认 [TODO-RTL]） | entry 耗尽 → 反压上游（间接，经 credit） |
| **IPROC Pending（独立 lifetime）** | 入口冲突检出 | 冲突对象在 CAM | 冲突对象离开 CAM | 阻塞全部后续入队（HOL，→C2） |
| CCT slot | 上表 | 到命令发送 | 发送 | 单槽占用 = bank 内第二候选等待（→S1） |
| WDP fetch FIFO | CQ 发 fetch 请求 | WDP 无空 entry | WDP 有空 entry | head-block（不挡 admission，→DP1） |
| 水线 | 占用越上水线 | 至 clr 阈值 | GSC 切换完成 | 触发 D1（write batch 形成机制） |

## 13.6 Architecture Node Mapping

CAM 深度/双口径/HOL → **V2**；credit 生命周期/水线 → **V3**；三层 filter/CCT 单槽不可撤回 → **S1**；CamAging/expired GPR → **S3**；入口检测/WAW merge 命令面/RMW flush → **C2**；AMAP 消费 → **L5**；cam_outnum16/24/32 电平 + exp_gpr/gpw + credit → **O1**。

## 13.7 Known RTL Limitation

- burst entry 内 4 条共享 priority/aging/credit——公平性/延迟代价未量化（3-P1-06 [TODO-MEASURE]）；
- burst 内固定顺序、第 1 条卡 timing 时 2~4 条不可独立 bypass（3-I-04 [OPEN]）；
- 分拍冲突检测识别延迟 1~2 拍（3-P1-11 [TODO-MEASURE]）；检测级数/stage 划分 [TODO-RTL]；
- WAW merge 后 entry 不携带 txn 信息（设计使然，非缺陷）；
- **no additional confirmed limitation**（C3-P1-01 cancel path 证据：XMU/PA 侧未发现 cancel/replay 结构——保持 OPEN，见 Ch12.7）。


> **Ch12 / Ch13 = FROZEN**（Part III Batch 1 Final Freeze Patch 已执行：ostd accounting vs write-data retention 拆分、credit reservation vs physical entry 拆分、credit return 末条同拍语义、DQ half-duplex、merge key [RTL 确认]、demand-side observability 回归"尚未确认"口径。reopen 条件同 Part I/II。）

# 14. BSC / GSC / FSC — RTL Implementation Reference

> Implements：**S1/S2**（提名→选择链）、**T1/T2/T3**（timing ready 组合）、**D1**（方向所有权/渐进切换）、**D2**（SID/rank 切换执行）、**M2**（维护优先级序与 mask/force-PRE 执行）、**M3**（watchdog critical 触发消费端）。
> **本章只写实现**：Eligible→Executable→Selected→Issued 四层事件在 RTL 的落点；architecture reasoning（为什么 hit-first/为什么 batching）→ Ch4/Ch5/Ch6。

## 14.1 Module Boundary

| 模块 | 负责 | 不负责 |
|---|---|---|
| **BSC** | per-bank FSM（IDLE/ACTIVTING/ACTIVE_WR/ACTIVE/PRE_WAIT/FORCE_PRE/WRA_RDA/PRECHARGE/ACT_FORBID）、row open/close 状态、ACT/PRE/REF 状态迁移、bank 侧 legality 组合（与 timing counter 相与） | 最终 policy 仲裁（FSC）；timing counter 的独立清单归属（logical owner = Timing Enforcement，物理位置嵌 BSC 侧——→Ch15 口径） |
| **GSC** | R/W direction ownership、四类切换触发、执行时间配额、渐进式切换、read 默认优先 + 两例外、SID 切换迟滞执行（SidSwitch） | bank FSM 状态；timing counter；FSC 最终选择 |
| **FSC** | 从 executable 集合选最终命令（Col>Row、Col 内 RR、Row 内 critical ref>ACT>PRE>non-critical ref）、维护插队执行、协议每拍单/双命令下发（HBM row+col） | 创造 timing legality；改写 C2 依赖判定结果 |

## 14.2 Owned State

- **BSC**：per-bank FSM 状态（9 态 [RTL]）、open-row 地址、tRCDWR/tRCD 双计数出口逻辑、FORCE_PRE / ACT_FORBID / PRE_WAIT 请求态、ref_act_mask / drfm 需求输入锁存；open-row 归 BSC 独占（owner 表）；
- **GSC**：当前读写方向态、切换阶段态（渐进式中）、执行时间配额计数、水线/critical/expired 反应逻辑、SidSwitch 迟滞计数 [RTL]；
- **FSC**：仲裁轮询态（Col 内 RR 指针）、维护 vs 业务仲裁态、协议双发 lane 状态（HBM）[RTL]；
- **不硬塞**：timing counter 明细 → Ch15；refresh debt → M1 域。

## 14.2.1 BSC Bank FSM — 完整状态转换表（[RTL]）

```
ACT 下发（act_executedIntl）：IDLE → ACTIVTING（tRCD/tRCDWR 双计数并行）
```

| 状态 | 含义 | 进入条件 | 退出 → 次态 |
|---|---|---|---|
| **BSC_IDLE** | bank 空闲（precharged） | 复位默认；PRECHARGE/WRA_RDA 收尾 | ACT 下发 → ACTIVTING；ref_act_mask → ACT_FORBID |
| **BSC_ACTIVTING** | ACT 已下发，tRCD 计时中 | act_executedIntl | tRCD 计满 → ACTIVE；**tRCDWR 计满 → ACTIVE_WR** |
| **BSC_ACTIVE_WR** | **仅写窗口**（tRCDWR 满足、tRCD 未满） | ACTIVTING 且 trcdwr_cnt 满 | tRCD 满 → ACTIVE；WRA(AP) 下发 → WRA_RDA |
| **BSC_ACTIVE** | row open，col 可正常调度 | tRCD 满 | RDA/WRA → WRA_RDA；PRE → PRECHARGE；force_pre_req → FORCE_PRE；fsm_pre_req → PRE_WAIT |
| **BSC_PRE_WAIT** | precharge 请求**待执行**（可被业务抢占） | fsm_pre_req | PRE 下发 → PRECHARGE；**col 下发 → WRA_RDA**；force_pre_req → FORCE_PRE；请求撤销 → ACTIVE |
| **BSC_FORCE_PRE** | **强制 precharge**（不可被业务抢占）；触发源 = tRASmax 驻留超时 + ref critical 的 RR 强制 PRE（5-P0-04 定稿 [RTL]） | force_pre_reqIntl | PRE 下发 → PRECHARGE；col 下发 → WRA_RDA（按"断言前已提交管线的 page-last（AP）col 走完收口、不接受新业务 col"理解 [INFERENCE]） |
| **BSC_WRA_RDA** | WRA/RDA（**auto-precharge col**）已下发，等内部 precharge | rda/wra_executedIntl | ref_act_mask 或 drfm ACT 需求 → ACT_FORBID；否则 → IDLE |
| **BSC_PRECHARGE** | PRE 已下发，等 tRP 收尾 | pre_executedIntl | ref_act_mask / drfm ACT 需求 → ACT_FORBID；否则 → IDLE |
| **BSC_ACT_FORBID** | refresh 前禁 ACT，等 bank 回可刷新状态 | ref_act_mask；或收尾状态中遇 refresh 需求 | ACT 下发 → ACTIVTING；mask 撤销且无 per-bank refresh 请求 → IDLE；per-bank refresh 执行完 → IDLE |

四设计洞察 [RTL]：① tRCD/tRCDWR 双计数出口 + ACTIVE_WR 仅写窗口（tRCDWR<tRCD 写提前进入；无 tRCDWR 协议等值配置、窗口 0 退化无害）；② PRE_WAIT 可抢占 vs FORCE_PRE 不可抢占（服务让位业务 = Col>Row 在状态机层的落实）；**AP 与 FORCE_PRE 是两个独立机制**（AP 属性来自 page-last 判定、收口走 WRA_RDA；FORCE_PRE 收口 = 显式 PRE → PRECHARGE）；③ WRA_RDA 统一收口 AP（无需显式 PRE——显式 PRE 在支持 AP 的设计里很少的原因）；④ ACT_FORBID 从任何收尾状态可达（refresh mask 优先级最高，保证最短回刷路径）。

## 14.3 Critical Pipeline（四层事件链，回答 §十 关键问题）

```
CCT 上表【Eligible point——candidate 已提名并持有，owner = CQ/CCT；上表后不可撤回，直到发送】
→ BSC legality【BSC-ready point：bank FSM 态 legality ∩ timing-counter legality（AND [RTL 5.1]）；fail → blocked_timing/bank-state block】
→ GSC direction legality【Direction-legal point：当前方向 / switching-phase / SID·rank 约束过滤（BSC 之后、FSC 之前串联 [RTL 5.1]）；fail → blocked_direction】
→ Executable point【= Eligible ∩ BSC-ready ∩ Direction-legal——具备进入 final selection 的完整资格】
→ FSC arbitration【Col>Row；Col 内 RR；Row 内 critical ref > ACT > PRE > non-critical ref [RTL 5.5.1]】【Selected point；fail → blocked_policy】
→ command issue【Issued point = 驱动 DFI + counter load + bank FSM update + CCT release feedback 同源 [RTL：counter"命令下发时启动倒计时"、FSM 触发 = act/pre/rda_executed 类事件 → state/counter update 在 actual issue 拍]】
→ CCT release feedback → CQ 重新筛选【feedback signal 细节 [TODO-RTL]】
```

> **RC-1 RESOLVED（Part III Batch 2 Freeze Patch）**：RTL evidence wins——executable 的 authoritative 口径 = **Eligible ∩ BSC-ready ∩ Direction-legal**；Part I 原"executable = CCT∩BSC ready"为过窄表述，已做 terminology-only correction（architecture reasoning 不变）。六层各自对应唯一 blocked 类：BSC-ready fail→blocked_timing；Direction-legal fail→blocked_direction；Executable 未选→blocked_policy。

关键问题逐答（以 RTL 为准）：
1. **Eligible→Executable（六层）**：Eligible（上表）→ BSC-ready（bank FSM ∩ counter AND）→ Direction-legal（GSC 过滤）→ Executable（三者齐备、进入 final arbitration 的完整资格）——Executable 生成拍 = Direction-legal 输出拍（概念级 [RTL]；精确 cycle [TODO-RTL]）；
2. **bank-state-ready vs counter-ready**：**AND**（相与）[RTL 5.1]；
3. **GSC 参与级**：BSC 之后、FSC 之前（串联过滤 [RTL 5.1]）——**与 Part I S1"CCT∩BSC ready"的窄口径存在表述差**（见 Summary RTL Evidence Conflict RC-1）；
4. **FSC 序**：Col>Row / critical ref>ACT>PRE>non-critical ref [RTL 5.5.1 确认，非照抄]；
5. **critical ref mask 实现位置**：禁 ACT = ref_act_mask → BSC FSM 收尾态转 ACT_FORBID [RTL]；mask RD/WR = 待 PRE bank 不接业务 [RTL]；force PRE = BSC FORCE_PRE 态（触发源②）[RTL]；打破 Col>Row = FSC 序对 critical ref 的例外 [RTL]；
6. **渐进式对侧 ACT**：GSC 渐进阶段放宽对侧 ACT 合法性（当前侧 col 继续）[RTL 行为]；具体允许/禁止信号 [TODO-RTL]；
7. **HBM row+col 同拍**：row/col 线独立 → 可同拍 [SPEC→RTL 能力]；FSC 内部是双 lane 还是同拍两类 winner——[TODO-RTL]（素材未明确，不推断）；
8. **CCT release feedback**：issue 后释放、CQ 重筛 [RTL 行为]；信号名 [TODO-RTL]。

## 14.4 Resource / Backpressure Lifetime

| 资源 | Acquire/Load | Hold while | Release/Reset | Consumer / 阻塞后果 |
|---|---|---|---|---|
| CCT slot | CQ 上表 | 至命令发送 | issue 反馈释放 | bank 内第二候选等待（→S1） |
| bank FSM row 态 | ACT issue | tRCD→ACTIVE→col 期→PRE | PRECHARGE 收尾/WRA_RDA 内部收口 | 决定 col 合法性（→T3） |
| direction ownership | GSC 切换完成 | 配额期内 | 配额满/critical/expired/自然切 | 对侧全阻塞（→D1 账单） |
| switch quota（时间配额） | 方向切换时启动 | 计时中 | 配额满触发切换 | 过小→switch 频繁；过大→对侧 latency |
| FORCE_PRE 态 | tRASmax/critical 触发 | PRE 下发前 | PRECHARGE | 不可被业务抢占（vs PRE_WAIT 可抢占 [RTL]） |
| maintenance reservation | ref_act_mask | critical 序列期 | tRFC 满 forbid 撤销 | 全 bank 禁 ACT（→T2/M2） |

## 14.5 Architecture Node Mapping

三层 filter 产物 → S1；FSC 序 → S2；双模式执行 → S2/S3；BSC ready 组合 → T1；tRCD/tRCDWR/tRRD/tFAW 消费 → T2；tCCD → T3；GSC/渐进式/SidSwitch → D1/D2；critical mask/force PRE → M2；watchdog 触发消费 → M3。

## 14.6 Known RTL Limitation

> **Ch14 = FROZEN**（Part III Batch 2 Final Freeze Patch：RC-1 RESOLVED 六层口径；本节 limitation 为冻结时登记项，reopen 条件同全局。）

- GSC 渐进切换的允许/禁止具体信号 [TODO-RTL]；
- HBM FSC 双发内部结构（双 lane vs 同拍双 winner）[TODO-RTL]；
- CCT release feedback 信号名 [TODO-RTL]；
- executable 组合的精确 cycle 拍点 [TODO-RTL]。
# 15. Timing Counter — RTL Implementation Reference

> Implements：**T1/T2/T3**（五级 counter 的 ready/forbid 生成）、**M2**（tRFC forbid）、**M3**（Odd/Even watchdog 的 RTL 侧）、**M4**（tDRFM 家族）、**P1**（面积/数量口径）。
> **logical owner vs physical placement**：timing enforcement 的 logical owner = Timing Enforcement 域（L6）；物理上 forbid/down counter 嵌于 BSC 侧（5.3.1）——本章按 logical hierarchy 组织，物理位置如实标注，不为章节统一改写 hierarchy。

## 15.1 Module Boundary

- **输入**：issued command events（act/pre/rd/wr/rda/wra/ref/rfm 类 executed 脉冲）、bank/BG/rank/SID identity、timing CSR 值（颗粒模型→脚本→寄存器）、DVFS/reset/mode 状态；
- **输出**：per-command legality·ready（→BSC 相与）、per-level forbid（bank/BG/rank）、tFAW ready、tRASmax/tDRFMmax 驻留事件（→FORCE_PRE）、Odd/Even ≥阈值 critical 事件（→M1/M2）；
- **负责**：timing enforcement state（单命令间隔 + 驻留 + 窗口 + refresh watchdog 触发）；**不负责**：final scheduling policy、refresh debt 记账（M1）、bank FSM（BSC）。
- 零旁路原则：所有命令无例外过 counter 检查 [RTL]。

## 15.2 Owned State（按层级；**width 未确认项 [TODO-RTL]**，不猜）

| 层级/scope | counter（[RTL·近似清单]） | load event | 方向 | ready/事件条件 | consumer |
|---|---|---|---|---|---|
| per-bank down（64 bank） | tRCD / tRCDWr（双计数并行）/ tRRD / tRC / tRP / tRDA（rda→act）/ tWRA / tRFCpb / tWR2RD / tRASmin / tRD2PRE / tWR2PRE / tDRFM_act2pre / tDRFMPB / tDFRMI——清单为**近似口径**（6-P0-01） | 对应命令 issue 拍 | down | 归零 → 对应操作 ready | BSC |
| per-bank inline | tRASmax / tDRFMmax（最大驻留） | ACT/DRFM-ACT issue 起 | **up** | **threshold event**：达 max-residency 阈值 → event asserted（FORCE_PRE / 强制关行）[RTL]；**reset / disable / release 点 [TODO-RTL]**（候选：threshold hit / PRE issue / PRE completion / bank state exit / next ACT / explicit FSM clear——不推） | BSC |
| per-BG s 系列（跨 BG） | tRRDs / tCCDs / tWR2RDs / tRD2WRs / rd2rd（与 wr2wr 分开）×16 BG——**load event 按 source command 拆分**：tRRD_S ← ACT issue；tCCD_S ← RD/WR col issue；WR2RD_S ← WR issue；RD2WR_S ← RD issue；rd2rd/wr2wr ← 对应 col issue（逐项以 RTL 为准 [TODO-RTL 补全]）；l 系列（同 BG）同构 [TODO-RTL：6-P0-01/02] | 对应 source-command issue（见左） | down | 归零 → 对应类别 col ready | BSC |
| per-BG l 系列（同 BG） | **清单未闭合 [TODO-RTL：6-P0-01/02——tCCDl/tRRDl/tWR2RDl/tRD2WRl 等是否存在及数量逐项待查，不按协议名推断]** | 同上 | down | 同上 | BSC |
| per-rank | tRFCab / tRFCpb / tRFMab / tRFMpb / tPPD / tWR2MR / tRD2MR / tXRS（SRX→ACT）/ tXP（PD 退出→ACT）/ tRP / tRC / tSR 等 ×21 [近似] | 对应事件 | down | 归零 | BSC |
| per-SID | rRFCpb / tCCDR 等 ×4 SID×3 [近似] | 对应事件 | down | 归零 | BSC |
| rolling window | **tFAW：4 个错相 counter 轮流使能**（ACT issue load 对应 slot；4 slot 全有效 → 禁 ACT）[RTL 6.2.2]；historical inventory 记“8”的口径差异 **[OPEN：6-P1-06——物理 counter 数 vs logical timing item 数 vs 使能逻辑未拆分，不猜]** | ACT issue 轮流 load | down | 有 slot 归零 → ACT ready | BSC |
| refresh watchdog | Odd/Even 两个 round-pair counter（≥8×tREFI → critical）[RTL]；计数起点 = REFab 拍或本轮最后 REFpb 拍；**round_complete 生成逻辑（bitmap reduction / pointer wrap / 最后 bank issue）[OPEN：RF-P1-06 TODO-RTL]**；fixed bank order / phase margin [OPEN：RF-P1-07] | round 推进 | up | ≥8×tREFI → critical | M1/M2 |
| DVFS/reset 语义 | DVFS：结构性规避——切频窗口 IDLE、无在途倒计时、新频率重配 [RTL 6.4.2]；LP/SR 期间 counter 状态（freeze/continue）[TODO-RTL]；**timing CSR 运行中被改的语义 [TODO-RTL/OPEN]** | — | — | — | G1 |

> ns→cycle 取整：min 约束 ceil；max 驻留与 refresh deadline floor（6-P0-03 [RTL]）。

## 15.3 Critical Pipeline

```
command issue event（act/pre/rd/wr/rda/wra/ref/rfm…）
→ counter class 匹配（per bank/BG/rank/SID/window 定位）
→ counter load（value = CSR 配置；方向 = down/up）
→ counting（非零期间 forbid 对应命令类 ready 拉低【backpressure point】；
   归零后静默【门控时钟友好】）
→ ready 输出 → BSC 相与 → executable（→Ch14）
inline 分支：上行计数 → 阈值比较 → 事件（FORCE_PRE 等）
window 分支：错相 slot 轮流 load → 全有效 → forbid（tFAW）
watchdog 分支：round-pair 累计 → 阈值 → critical 事件（→M2）
```

**Command Type → Counter Class 映射（素材明示项）**：ACT issue → tRCD/tRCDWr/tRRD/tRC/tRASmin load + tFAW slot load + tRASmax inline 启动；RD → tWR2RD（及 col 类 s/l）；WR → tWRA/tWR2RD 方向项；RDA/WRA（AP）→ tRD2PRE/tWR2PRE + 内部 precharge 序列；PRE → tRP；REFpb → tRFCpb；REFab → tRFCab（rank）；RFMpb → tRFMpb；SRX → tXRS；PD 退出 → tXP；DRFM → tDRFM_act2pre/tDRFMPB/tDFRMI + tDRFMmax inline。**其余细粒度映射 [TODO-RTL]**——不按协议 timing 名自动生成不存在的 counter。

## 15.4 Resource / Backpressure Lifetime

| 资源 | Acquire/Load | Hold | Release/Reset | 阻塞后果 |
|---|---|---|---|---|
| down counter | 命令 issue 拍 load CSR 值 | 非零期间 | 归零（自动，无 SW 释放） | 对应类 ready 拉低（blocked_timing） |
| inline counter | ACT/DRFM-ACT issue 启动 | row / DRFM residence | **Threshold Event**：达阈值 → event asserted；**Release/Reset：[TODO-RTL: exact clear/disable point]**（threshold event ≠ reset event） | 触发 FORCE_PRE（tRASmax）/ 强制关行 |
| tFAW slot | ACT 轮流 load | 计时中 | 归零 | 4 slot 全有效 → 禁 ACT |
| Odd/Even watchdog | round 推进累计 | 累计中 | 本 round 结束清本相位 | ≥8×tREFI → critical（依赖 round-complete invariant → RF-P1-06 OPEN） |
| refresh debt（M1 域，交叉） | tREFI 到期 | — | REF 完成 | critical escalation（→M1） |

## 15.5 Architecture Node Mapping

五级分布/ready 组合 → **T1**；tRCD/tRRD/tFAW/tRC/tRP/tRAS → **T2**；tCCD_S/L → **T3**；tRFC → **M2**；Odd/Even → **M3**；tDRFM 家族 → **M5**；≈1017/40% 面积 → **P1**；min-gap 覆盖率 → O1/验证。

## 15.6 Measured PPA / Synthesis Evidence [MEASURED]

> **四口径区分**：A. logical timing-item count（≈1017，近似历史口径）≠ B. physical counter/register count ≠ C. weighted FF count（按位宽加权远大于 A，待回填 [TODO-MEASURE：6-P0-05]）≠ D. synthesis area（下两表）。**不互相换算、不凑数。**

**LPDDR6 @ 三星 SF4 1000MHz**（配置：CAM32 / link node 96）：

| 模块 | 面积 (μm²) | 占比 |
|---|---|---|
| CS（命令调度） | 30,284.3 | 23.08% |
| CQ（命令队列） | 18,970.2 | 14.46% |
| DFI（DFI 接口） | 17,080.8 | 13.02% |
| XMU（跨时钟域） | 15,067.8 | 11.48% |
| WDP（写数据通路） | 13,642.3 | 10.40% |
| REGBANK（寄存器组） | 11,222.4 | 8.55% |
| IPROC（内部处理） | 8,115.9 | 6.18% |
| RDP（读数据通路） | 7,166.2 | 5.46% |
| DEVMGR（设备管理） | 5,063.1 | 3.86% |
| BIST（内建自测试） | 2,226.1 | 1.70% |
| PA（端口仲裁） | 41.4 | 0.03% |
| **11 模块合计** | **128,880.4** | **98.21%** |
| 其他（BPE / BIST_CMD_MUX / UIF 等） | 2,350.2 | 1.79% |
| **总面积** | **131,230.7** | **100%** |

**HBM4 @ 三星 SF4 1600MHz，双 PC 合并（PC0+PC1）**（配置：CAM96 / link node 224）：

| 模块 | 面积 (μm²) | 占比 |
|---|---|---|
| CQ | 171,674.1 | 35.12% |
| XMU | 110,307.1 | 22.56% |
| CS | 53,530.9 | 10.95% |
| DEVMGR | 30,709.9 | 6.28% |
| DFI | 13,063.4 | 2.67% |
| WDP | 8,611.3 | 1.76% |
| REGBANK | 7,713.9 | 1.58% |
| BIST | 6,283.5 | 1.29% |
| IPROC | 2,841.5 | 0.58% |
| RDP | 311.8 | 0.06% |
| PA | 92.7 | 0.02% |
| **合计** | **405,140.1** | **82.87%** |
| 剩余（inst_core_0/1 内其他子模块 + 顶层其他） | 83,748.5 | 17.13% |
| **总面积** | **488,888.7** | **100%** |

**三组观察**：① 面积大头随协议切换——LPDDR6 在 CS（counter 体系），HBM4 在 CQ+XMU（CAM96 队列 + link node 224 在途结构）；② 配置实证经验区间：CAM LPDDR6=32 / HBM4=96（低功耗浅 CAM、高带宽深 CAM），link node 96→224；③ 数据缓冲占比反映 burst 长度：HBM4 WDP 1.76%（BL8 短 burst）vs LPDDR6 10.40%（BL32 长 burst）。

## 15.7 Known RTL Limitation

> **Ch15 = STRUCTURE FROZEN / CONTENT PARTIAL**（structure 与已知 [RTL] 事实冻结；inventory/invariant 缺口显式 OPEN——见上与 Registry。）

- per-BG l 系列清单未闭合（6-P0-01/02 **PARTIAL**：s 系列确认 16×5、l 系列 [TODO-RTL]）；
- tFAW 物理计数 vs logical item vs FF 数三种口径未拆分（6-P1-06 **OPEN**）；
- round_complete 生成逻辑未确认（RF-P1-06 **OPEN**——M3 数学证明的 scheduler invariant 缺 RTL proof，**M3 保持 PARTIAL**）；
- 固定 bank order / phase margin（RF-P1-07 **OPEN**）；
- counter 位宽未逐项确认 [TODO-RTL]；timing CSR 运行中改值语义 [TODO-RTL]；LP/SR 期 counter 状态 [TODO-RTL]；
- ≈1017 维持 **[RTL·approximate historical inventory]**，不人工凑数；四口径（logical item / physical counter / weighted FF / area）中现有 A 与 D（面积表），B/C 待 recount。
# 16. WDP / RDP — RTL Implementation Reference

> Implements：**DP1**（写数据可用性/生命周期）、**DP2**（读返回/保序）、**C3**（数据所有权移交点、recovery PNR 的物理落点）、**R1**（CE/UE 检测与 retry 执行端）、**C2**（WAW merge / RMW 数据面）。
> **本章核心**：command lifetime 与 data lifetime 彻底分开——命令被调度后，数据由谁拥有、何时取、何时放、错误时哪个 state 保留。

## 16.1 WDP — Module Boundary

- **输入**：CQ fetch 请求（持 CAM ptr）、XMU write data（resize 后 64B/burst 4 数据）、BE（byte enable）、写 metadata、DFI 取数请求（tphy_wrlat 定时）；
- **输出**：write-data-ready（→FSC 发 WR 前提）、encoded write data（ECC/DBI/CRC 读出侧）→ DFI wrdata、ptr/metadata 应答、entry 空位信息；
- **时钟域**：DFI clk；协议接口：DFI write data（含 CRC 附加传输形态）；
- **负责**：write data fetch（自 XMU buffer）、WDP 存储（4×SRAM）、BE 关联与寄存、WAW merge 数据面（写口 BE 拼接）、RMW merge 数据面（反向 BE + poison 注入）、读出侧编码（inline/sideband/link ECC、DBI、Write CRC）、**data ownership transfer（DFI 取数）**、entry free lifecycle；
- **不负责**：write command 调度（→CS）、BRESP（→XMU/PA grant 拍，早于本模块生命周期）、DRAM command timing、AXI 侧 resize（→XMU）。

## 16.2 WDP — Owned State

| State | Owner | Consumer | 写权 |
|---|---|---|---|
| WDP entry（4×SRAM raw data） | WDP | DFI 取数 | XMU 写入（fetch 时）/ 读出侧读 |
| free list / valid bitmap | WDP | CQ fetch 判定 | WDP |
| fetch request FIFO | CQ→WDP 通路 | WDP | CQ push / WDP pop |
| BE 寄存器堆（CAM 深度×数据量/8） | WDP | merge、DM 生成、编码 | XMU 写入段/merge 更新 |
| data-ready 态 | WDP | FSC（WR 可发前提） | 全数据到位置位 / merge 更新 |
| post-issue flight 态（已调度未取数 ptr） | DFI 侧跟踪（WDP entry 不释放） | DFI 取数 | DFI |

## 16.3 WDP — Key Data Structures

- **entry array**：4×SRAM，per CAM entry 粒度（非 burst=1 数据、burst=4 数据分放 4 SRAM）；**SRAM 单口**——两 entry 同拍双读无结构性保证（HBM 双发需 DFI 预取的物理根源 [RTL]）；
- **BE 寄存器堆**：≈CAM 深度 × 数据量/8 [RTL]（1bit/byte）；
- **编码引擎**：读出侧 inline/sideband/link ECC + DBI + Write CRC（每 4bit DQ × BL16，DDR [RTL]）；
- 宽度/深度精确档 [TODO-RTL]（部分随协议配置）。

## 16.4 WDP — Critical Pipeline（八段对齐 DP1；标注七类 point）

```
CQ fetch 请求（持 ptr）【fetch request point】
→ WDP 有空 entry → 向 XMU 取数【fetch point = data ownership：XMU buffer → WDP（XMU-P1-01 关联）】
→ 写 4×SRAM + BE 入寄存器堆（XMU→WDP 1 cycle）
→ data-ready 置位【ready point = FSC 发 WR 前提；WR issue = command PNR（C3-B，早于本模块事件）】
→ WR issue → credit 已还 / CAM entry 已释放（WDP entry 保留）
→ tphy_wrlat 到临近 → DFI 持 ptr 取数【data-ownership-transfer point（C3）；多 cycle 逐数据】
→ 读出侧编码 ECC/DBI/CRC → wrdata → PHY【**Controller→DFI data handoff**（C3 data ownership handoff——区别于前段 XMU→WDP 的 internal buffer ownership transfer）】
→ DFI 取走 → WDP entry 释放【free point】
```
[TODO-RTL: tphy_wrlat 值 / 提前量拍数 / DFI 取数请求信号名]

## 16.5 WDP — Resource / Backpressure Lifetime

| 资源 | Acquire | Hold while | Release | Backpressure 后果 |
|---|---|---|---|---|
| WDP entry | CQ fetch 被受理（有空 entry） | pre-issue wait + post-issue DFI flight | DFI 取走（ownership transfer） | 无空 entry → fetch FIFO head-block（不挡 admission，→DP1） |
| fetch FIFO slot | CQ 发请求 | WDP 无空 entry | fetch 受理 | FIFO 满 → 后续写命令 fetch 排队（blocked_data 源） |
| write-data-ready 态 | 数据全到位 | 至 WR issue 后数据被消费 | ownership transfer | 无 ready → FSC 不发 WR（blocked_data） |
| BE/ECC metadata | 数据写入时 | 与 entry 同生命周期 | entry 释放 | — |

## 16.6 WDP — Architecture Node Mapping

entry/ready/lifetime → **DP1**；WAW merge 数据面/RMW 反向 BE → **C2**；poison 注入 → **R1**；ownership transfer → **C3**；编码 → 协议差异（→DP3 CRC 口径）；面积 10.40%/1.76% → **P1**。

## 16.7 WDP — Known RTL Limitation

- SRAM 单口（双发需 DFI 预取——设计已知，非缺陷）；
- WDP 占用无直接 counter（blocked_data 靠恒等式反推）[TODO-MEASURE]；
- entry free 与 DFI 取数同拍 [RTL]；独立 free 信号名 [TODO-RTL]。

## 16.8 RDP — Module Boundary

- **输入**：DFI 完整读数据（rotator 后）、命令信息（node index 随命令下行、FIFO 先入先出绑定）、data_valid、错误状态；
- **输出**：检查后数据 → XMU reorder SRAM（按 node index 写入）、CE 上送 / UE 拦截决策、retry 触发（→RAS 模块）、SLVERR 标记路径；
- **时钟域**：DFI clk；**负责**：DBI 去除 / ECC·CRC 检查、CE/UE 分类、recovery PNR 边界执行（RDP→XMU）、retry 触发；**不负责**：AXI reorder policy（XMU link list）、读命令调度、rolling ptr（DFI 侧实现）、训练状态（PHY）。

## 16.9 RDP — Owned State

| State | Owner | Consumer | 写权 |
|---|---|---|---|
| 命令信息 FIFO（node index 先入先出） | DFI rddata path（→DP2） | RDP 弹出对齐 | DFI push / RDP pop |
| read data path FIFO（深度 ∝ PhyRdLat） | DFI（→DP2-P1-01） | RDP | DFI |
| CE/UE 判定态 | RDP | retry 模块 / 上送路径 | RDP |
| UE→SLVERR 标记（link node 元数据信息表） | XMU link node 域（写入由 retry 流程触发） | RDATA resize | retry 流程 |
| retry 计数/窗口（≤15，寄存器可配） | RAS retry 模块 | UIF 注入 | retry 模块 |

## 16.10 RDP — Key Data Structures

- 检查引擎：DBI 去除 / ECC syndrome·纠正 / CRC 校验（每 core 每 DFI 拍一个完整 op 的吞吐 [RTL]；HBM4 双发 = 每拍 2 node 返回）；
- syndrome/纠正态、UE 标志写入 link node 信息表 [RTL]；
- **RDP 不做大缓冲**（读缓冲在 XMU reorder SRAM——面积反差 5.46%/0.06% [MEASURED]）；
- 深度/位宽精确值 [TODO-RTL]。

## 16.11 RDP — Critical Pipeline

```
RD col issue【Read Command PNR（command-domain，→C3）】
→ node index 入 DFI 命令信息 FIFO【return-tracking point】
→ dfi_rddata_en 定时到 / data_valid 到达（弹性由 FIFO 吸收——精确语义 DP2-P1-01）
→ capture → rotate/align（DFI 侧完成，输出完整数据）
→ DBI 去除 → ECC·CRC 检查【Detection Point】
→ CE / UE 分类【recovery-domain decision】
   ├─ CE：就地纠正 → 正常上送
   └─ UE：数据丢弃不上送、原 node/读 ID 保留【recovery PNR 未越界 → retry 决策】
→ retry（≤15、仅 DDR）或 UE 标记 + SLVERR + 中断【超限 / 无 retry path】
→ 正常数据按 node index 写 XMU reorder SRAM【Recovery PNR 越界 = RDP→XMU】
→ link node head-only 释放 → RDATA 组装返回
```

## 16.12 RDP — Resource / Backpressure Lifetime

| 资源 | Acquire | Hold while | Release | 后果 |
|---|---|---|---|---|
| link node | AR accepted | 数据 pending/retry/head 等待 | head eligible + RDATA 消费 | 耗尽 → 读 admission 反压（前置资源） |
| 命令信息 FIFO slot | RD issue | 数据未返回 | 返回消费 | FIFO 满 = 到达快于消费（[TODO-RTL] 深度） |
| read data FIFO slot | data_valid 到达 | 未被 RDP 消费 | 消费 | 深度 ∝ PhyRdLat 配置 [RTL·部分，语义边界 →DP2-P1-01] |
| retry 窗口 | UE 检出 | ≤15 次内重试 | 成功上送 / 超限 SLVERR | 原 node 占用 → 同 ID HOL（次数有界 ≠ 时间有界，DP2-P1-02 OPEN） |

## 16.13 RDP — Architecture Node Mapping

检查/CE·UE/recovery PNR → **R1/C3**；node 绑定/head-only → **C1/DP2**；返回带宽 → **DP2**；DBI/ECC → 协议差异（→DP3）；面积 → **P1**。

## 16.14 RDP — Known RTL Limitation

- 读延迟 / 返回带宽无 RTL 直接观测 [MODEL only]（trace 后处理）[TODO-MEASURE]；
- FIFO 深度/位宽精确值 [TODO-RTL]；
- per-retry service bound 无证据（DP2-P1-02 OPEN）。

# 17. DFI / Device Management — RTL Implementation Reference

> Implements：**DP3**（normal command/data contract：ratio/phase/PF window/无 per-command 流控）、**G1**（DEVMGR arbiter+worker 物理 RTL）、**C3**（LP/DVFS transition-entry point 的执行端）、**DP1/DP2**（PhyWrLat 取数 / PhyRdLat·rolling·valid 契约）。
> **章内拆分**：**17A = Normal DFI Command/Data Contract**；**17B = Device Management / Ownership Transition**（共享 module reference，语义分开——normal issue path 的"无 per-command 握手"不外推到 training/update/LP/ownership handshake）。

## 17.1 (17A) Module Boundary

- **输入（PHY → Controller）**：dfi_rddata（读数据）、dfi_rddata_valid、dfi_init_start·complete（DFS 复用握手通道）、dfi_phymstr_req（PHY 主权请求）、phyupd_req、dfi_lp 唤醒侧、dfi_cs/_cke 类低频命令返回状态 [部分方向/信号全集 TODO-RTL]；timing/模式 CSR 为 controller 侧配置（非接口输入）；
- **输出（Controller → PHY）**：dfi_address/bank/cs/row/col 命令编码（CA parity 同拍生成 [RTL]）、**dfi_wrdata**（+CRC 附加传输形态 [RTL·DDR]）、**dfi_rddata_en**（读使能定时）、dfi_cs/_cke 低频命令（phase0 纪律）、dfi_phymstr_ack、dfi_lp 进入侧、DFI 状态输出；
- 方向注记：CS 命令与 WDP 写数据均为 **Controller → PHY** 方向；PHY → Controller 方向仅读数据 / 状态 / 握手类——**同一信号不得同时出现在两组**（dfi_wrdata 归 Controller→PHY [RTL]）。
- **时钟域**：DFI clk ↔ PHY 侧 CK/WCK 分频关系（ratio4 = DFI:CK:WCK 1:2:4；ratio8 = 1:4:8；DDR 无 WCK [RTL·7-P0-01/02 定稿]）；
- **负责**：命令解析与协议总线生成（不做流控——normal path）、写数据接收与定时呈现（tphy_wrlat）、读数据 capture/en 定时与 rolling（ptr 在 DFI、起点 0、ctrlUpd/phyUpd 复位 [RTL]）、PF window（HBM4 shadow，→DP3）、phase 打包（HBM 双 PC 奇偶 CK）；
- **不负责**：命令调度决策（→CS）、训练序列（PHY 主导 [BOUNDARY]）、refresh 债务记账（→M1）、全局转换仲裁（→DEVMGR 17.2）。

## 17.2 (17A) Owned State

| State | Owner | Consumer |
|---|---|---|
| rolling ptr（读数据对齐，起点 0） | DFI | rotator/RDP |
| read data path FIFO（深度 ∝ PhyRdLat 配置） | DFI | RDP |
| PF window 8 entry（shadow：CQ ptr/SID/BG） | CS/DFI 边界结构 | CS 双发选择 |
| phase 打包状态（HBM PC0/PC1 奇偶 CK） | DFI | 命令呈现 |
| 写数据预取 buffer（HBM16G 一拍双写） | DFI | WR 呈现 |
| init 超时计数（CSR 轮询） | DEVMGR | SW |

## 17.3 (17A) Key Data Structures

- ratio 配置（ratio4/8 [RTL]）；多频点表（PhyRdLat 等参数 SW 预编程 + hw_freq_sel [RTL]）；
- PF window entry：仅调度影子（CQ ptr/SID/BG），准入约束同 BA 唯一 + 优先不同 BG；CK 映射 PC0 col0→CK0/col1→CK2、PC1 col0→CK1/col1→CK3（双发间隔恰 = tCCD_S=2）[RTL]；
- 命令打包：ratio8 每拍 2 条（16G 场景）[RTL]；写数据预取 buffer（4 条/burst）[RTL]；
- PhyWrLat/PhyRdLat 数值档 [TODO-RTL: 各频点值]；DFI-P1-01 = **PARTIAL**（ratio/phase0/rolling 复位/PF 结构已确认 [RTL]；latency 数值/rolling 全语义/低功耗握手全集 [TODO-SPEC+RTL]）。

## 17.4 (17A) Critical Pipeline

**写**：WR issue【C3 command PNR】→ tphy_wrlat 定时 → DFI 持 WDP ptr 取数【data ownership transfer → DP1⑦】→ 编码已备 → dfi_wrdata 呈现（HBM 预取 buffer 支持一拍双份）→ DQ transfer。
**读**：RD issue【command PNR】→ node index 入命令信息 FIFO → PhyRdLat 定时产生 dfi_rddata_en【expected-return window】→ data_valid 到达【实际到达，FIFO 吸收弹性】→ rolling 对齐 → 完整数据 → RDP（→DP2-P1-01 六职责精确划分 OPEN）。
**normal issue**：CS 发命令 → DFI 解析 → 协议总线——**无 per-command accept/reject**（scope 见 Ch8 DP3；training/update/LP/ownership 为独立 handshake [TODO-SPEC: DFI 版本逐条]）。

## 17.5 (17A) Resource / Backpressure Lifetime

| 资源 | Acquire | Hold | Release | 后果 |
|---|---|---|---|---|
| DFI 命令呈现槽（每拍，HBM 双槽） | CS 发命令 | 呈现拍 | 呈现完成 | CS 自限速（无反压回传） |
| 写数据预取 buffer | DFI 预取请求 | 至对应 WR 呈现 | 呈现完成 | 支撑一拍双写（→DP1） |
| 读 data FIFO | data_valid 到达 | RDP 未消费 | RDP 消费 | 深度不足 = 配置错误（→DP2-P1-01） |
| rolling ptr | 复位（ctrlUpd/phyUpd/起点 0） | 持续滚动 | — | 配错 → alignment 破坏（failure mode →DP2-P1-01） |

## 17.6 (17A) Architecture Node Mapping

normal issue/无流控 scope → **DP3**；PF window → **DP3/T3**；tphy_wrlat 取数 → **DP1/C3**；en/valid/rolling → **DP2-P1-01**；CRC/CA parity 生成 → **R1 检测链上游**；ratio → **DP3/RQ12**。

## 17.7 (17A) Known RTL Limitation

- PhyWrLat 提前量拍数/取数请求信号名 [TODO-RTL]；
- PhyRdLat 六职责精确划分 [OPEN：DP2-P1-01]；
- CA parity 检测/latch/report 归属 [OPEN：7-P1-04 TODO-SPEC/RTL——已知：生成在 controller 侧 dfi_address 编码时 [RTL]，检测/报告侧未记载，**不把 PHY logic 搬进 controller**]；
- Write CRC error feedback 通路是否存在 [TODO-SPEC/RTL：7-P1-05]（已知：生成 WDP 读出侧、传输=增加 BL [RTL]）。

## 17.8 (17B) DEVMGR — Module Boundary

- **输入**：软件 CSR（进入/解除/频点表/hw_freq_sel）、硬件 idle 判据（csrIdleForSr）、DFI 握手（init_start·complete / phymstr_req·ack / lp / phyupd / ctrlupd）、流量唤醒（驻留期 XMU 新请求）、refresh 域握手（ref_rdy_* / REF_CHECK）；
- **输出**：grant/done（互斥准许）、SRE/PDE/DSME/SRX 设备命令（phase0）、hold CS、反压 XMU（仅 DFS/clock gate）、频点表切换、mask refresh + 强制 AB；
- **负责**：六类 worker 转换的互斥准许与序列执行、drain 判据维护、SR 期 debt 冻结语义联动、init 窗口超时计数；
- **不负责**：refresh 记账（→M1/M2）、训练序列（PHY [BOUNDARY]）、命令调度、数据路径（无数据 PNR，→C3）。

## 17.9 (17B) Owned State

| State | Owner | Consumer |
|---|---|---|
| arbiter 七态 + grant/done | DEVMGR arbiter | 全 worker/SW（csrArbState 可观测） |
| 六台 worker FSM（HW_LP/SW_LP/CTRLUPD/PHYUPD/PHYMSTR/DFS；DSME 为 LP worker LPDDR 参数分支 [TODO-RTL→DM-P2-02]） | DEVMGR | 各自 hold/命令/握手 |
| 驻留态（LP 无 done——done=退出完成） | DEVMGR/LP worker | SW（csrDdrLpState） |
| 频点表 + hw_freq_sel | SW 预编程/DEVMGR 选择 | DFS/DFI |
| init 超时计数 | DEVMGR | SW 轮询 |

## 17.10 (17B) Key Data Structures

- arbiter 状态寄存器 + 各 worker 阶段寄存器 [RTL；位宽/编码 TODO-RTL]；
- drain 判据输入：bank FSM 全 IDLE（BSC 只读）+ critical ref 完成（refresh 域只读）——**两条件同时要求** [RTL]；
- 转换形态差异 [RTL]：**DFS/clock gate** = front-end hold（XMU 反压）→ req==resp → CAM empty → bank close → transition；**HW/SW LP** = CS/command issue hold（XMU 继续接受 host request，新到请求 = HW 唤醒源）→ backend 收敛至 transition-safe quiesce → enter LP。

## 17.11 (17B) Critical Pipeline（四类 transition）

**LP（HW/SW）**：request → arbiter grant → backend 收敛（bank close + critical settled）→ SRE/PDE（phase0）→ DFI LP 握手（SRE 之后）→ 驻留（hold CS；XMU 照常收请求=唤醒源）→ wake（PRE_SRX 序列）→ restore → done（退出完成）。
**DFS**：SW request → grant → front-end hold/XMU 反压 → req==resp drain → CAM/backend drain → transition-safe quiesce → SRE（PRE_SRE 拍 pb→ab 折算）→ DFS 序列（dfi_init_start + 频点/参数更新）→ init_complete → 释放 hold。
**CTRLUPD/PHYUPD**：request → grant → WCK_CHECK → REF_CHECK（refresh 让路握手）→ PRE_CHECK → 命令/握手 → done（PHYUPD 长 >8×tREFI 进 SR；PD 中 critical 先 PDX）。
**PHYMSTR**：PHY req → traffic quiesce（IDLE/SR 两分支）→ MC ack 后停发（总线驱动权移交 PHY）→ PHY 撤 req → MC 撤 ack（交还）→ done。

## 17.12 (17B) Resource / Backpressure Lifetime

| 资源 | Acquire | Hold | Release | 后果 |
|---|---|---|---|---|
| DEVMGR owner token | arbiter grant | worker 序列活跃 | worker done | 六类转换互斥串行（DSME 独立性 OPEN，DM-P2-02） |
| front-end hold | DFS/clock-gate grant | transition 期 | 转换完成 | 反压 XMU→AXI（LP 无此动作） |
| CS hold | LP grant | 驻留期 | 唤醒+退出序列完成 | 命令停止（XMU 照常） |
| PHY ownership | PHYMSTR ack | PHY master 期 | PHY 撤 req→MC 撤 ack | MC 停发 |
| LP residence | LP entry 握手完成 | 驻留 | wake+退出完成 | SR 期 debt 冻结、计时器语义→M1 |
| DFS ownership | DFS 序列 accepted | 切频+重配 | 新 timing/config valid | 全程不可用窗口（→G1 性能口径） |

## 17.13 (17B) Architecture Node Mapping

arbiter+worker/四 idle/drain → **G1**；transition-entry point 执行端 → **C3**；PRE_SRE 折算/debt 冻结 → **M1**；mask refresh → **M2**；DFI init 通道复用 → **DP3**；双 CSR 观测 → **O1**。

## 17.14 (17B) Known RTL Limitation

- DSME 序列细节 / 是否独立 worker [OPEN：DM-P2-02 TODO-RTL]；
- clock gate 转换细节 [OPEN：DM-P2-02]；
- 无 watchdog——progress path 语义（→G1⑤），peer 不响应无 local 收敛保证 [RTL/MODEL]；
- 无 validate（MRR 回读校验归 SW/PHY [RTL]）。

# 18. Performance Observability — RTL Implementation Reference

> Implements：**O1**（Observable Inventory 的 authoritative 落点）、**O2**（证据能力输入——诊断推理本体在 Ch1 RQ2）、**X-P1-07/08/09、O2-P1-01**（证据状态）。
> **本章定位**：Observable → What it proves → What it does NOT prove → Alternative evidence。**不做 counter dictionary dump**；诊断流程在 Ch1 RQ2，归因 precedence 设计在 X-P1-08（不在此章）。
> **Negative claim 纪律**：以下 absent 判定基于**本章 Table A——authoritative migrated RTL Observable Inventory [RTL]**——"confirmed absent in current inventory" 的证据等级成立；inventory 未来扩充时允许推翻 absent 结论。

## 18.1 Table A — RTL Observable Inventory

| Observable | Owner | Type | Scope | Read/Clear 语义 |
|---|---|---|---|---|
| **CS 14 种命令 executed**（ACT/SRE/SRX/PDE/PDX/RD/RDA/WR/WRA/PRE/REFpb/REFab/RFMpb/MRW） | CS | counter（CSR） | 全局累计 | 只增；SW 读 |
| UIF *_accepted（hpr/lpr/gpr/tpw/gpw） | UIF | counter | 分类准入计数 | 只增 |
| CQ exp_gpr / gpw_executed | CQ | counter | 饥饿触发健康度（应≈0） | 只增 |
| XMU lpr/tpw **fifo_full** | XMU | counter | admission 侧反压观测 | 只增 |
| **cam_outnum 16/24/32** | CQ | **电平**（非寄存器） | CAM 占用 ≥阈值 | top 侧累计计数 |
| **30bit 固定槽位时间向量**（每 PC） | top | 逐拍并排 bit 流 | always-on 观测点 | trace 采样 |
| **ctl_dbg_obv_pc0/1 + 双 mux**（XMU 队列计数、PA credit、CAM vld、CS 仲裁状态、DEVMGR 全套 FSM、REF 请求 refab_req/refpb_req[63:0]/ref_critical） | 各域→top | 实时状态总线 | SW 选源 | 实时电平/状态 |
| **csrDdrLpState / csrArbState** | DEVMGR | CSR 状态 | LP/arbiter 状态 | 轮询 |
| 档位/mode/debt 相关 CSR | refresh 域 | CSR | 档位选择与状态 | 轮询 |

## 18.2 能推 / 不能推（能力边界 [RTL]）

✅ 可推：命令 mix；QoS 准入分布；饥饿健康度（exp_gpr≈0）；AP 使用率（RDA+WRA/col）；LP 进出频率（SRE/SRX/PDE/PDX 计数）；maintenance 开销占比（REF+RFM/总命令）；H 因子命令面近似（col/ACT）。
❌ 不可推（无观测）：**hit rate**（需 per-col row 状态）；**latency P50/P99**；**cycle 级 blocked 归因**（含 per-timing blocker 细分、blocked_policy、HOL cycles）；**DRFM executed**（不在 14 种内——X-P1-09）；**WDP 占用**；**payload 效率**（bytes/BE/RMW 放大）——全部 trace / performance model 侧（[MODEL only] / [TODO-MEASURE]）。

## 18.3 Table B — Architecture Evidence Matrix（Observable → Node → Supports / Cannot prove）

| Observable | Node | Supports | Cannot prove |
|---|---|---|---|
| 14 种命令 executed | S2/T2/T3/M2 | 命令 mix、ACT/col 比（hit 命令面近似）、maintenance 占比、AP 使用率 | per-timing 细分归因；hit rate 本身；payload 效率 |
| hpr/lpr/gpr/tpw accepted | S3/V3 | QoS 准入分布 | 各类 latency（无观测） |
| exp_gpr/gpw | S3 | 饥饿机制健康度（≈0） | starvation 实际时长 |
| fifo_full | V3 | admission 侧反压事件 | 是 CAM 满还是下游释放慢（≠attributable） |
| cam_outnum 电平 | V2 | occupancy 高位驻留 | 分布/entropy；CCT 空时=入队瓶颈仅可间接推 |
| CS 仲裁状态 / CAM vld（dbg_obv） | S1/S2 | CCT 空 vs FSC 无输出的分界证据 | policy bubble 的逐拍归因（组合推断） |
| PA credit（dbg_obv） | V3 | credit==0 事件 | 上游根因（下游 release 慢同象） |
| DEVMGR FSM / csr 双态 | G1 | 转换进度/驻留 | peer 不响应时长 bound |
| REF 计数 + ref_critical | M1/M2 | 刷新节奏 vs 应发 | blocked-only-by-refresh（模型互斥归因） |
| refpb_req[63:0] | M2/M3 | per-bank 刷新请求分布 | tier3 触发率（需组合） |
| refab/refpb 计数差 | M1 | ab/pb 模式健康度 | debt 动态（debt 无 counter） |

## 18.4 Table C — Performance Taxonomy Coverage（blocked reason → 证据等级）

| blocked reason | direct observable | indirect（组合推断） | trace/model only | gap 结论 |
|---|---|---|---|---|
| idle_no_request | — | ostd 计数低+fifo_full 静默 | arrival/occupancy trace | **demand-side direct counter absent**→[TODO-MEASURE] |
| blocked_admission | fifo_full / credit(dbg_obv) | +命令 mix | 归因需下游 release 分析 | credit==0 ≠ CAM 容量根因（Observable≠Attributable） |
| blocked_visibility | cam_outnum 电平 | +CCT 状态 | entropy/分布 | 分布级不可见 |
| blocked_dependency | — | Pending 态(dbg_obv)+同址命令 mix | HOL cycles | 无冲突 counter |
| blocked_no_candidate | — | CAM 占用+FSC 无输出 | CCT 空 trace | CCT 无直接计数 |
| blocked_timing | —（无 per-timing blocker counter） | ready 态(dbg_obv)+命令 mix | **Top5 lost-slot sweep**（6-Q-02 口径） | 细分归因 model-only |
| blocked_direction | —（无 switch/sec counter） | 方向态+命令 mix | switch count/turnaround/hidden tRCD | 三项全 model |
| blocked_maintenance | **REFpb/REFab/RFMpb 计数 + ref_critical** | +tier 分布 [MODEL] | blocked-only-by-refresh / postpone sweep | **DRFM absent（X-P1-09）** |
| blocked_policy | —（无 eligible-but-not-selected counter） | executable 态+selected 对比（模型） | 归因序列 | X-P1-08 的直接输入缺口 |
| blocked_data | —（无 WDP counter） | fetch FIFO/恒等式反推 | WDP histogram | **absent→[TODO-MEASURE]** |
| blocked_DFI_PHY | —（无 global unavailable counter） | DEVMGR FSM+CS 停发 | 握手 trace | normal path 无握手信号可观测 |
| issued-but-inefficient | 命令 mix（部分） | — | bytes/BE/RMW/AP 效率 | **payload 侧 absent**→O2-P1-01 证据现状 |

## 18.5 TODO 证据状态（本章结论）

- **X-P1-07**：observability inventory 完成（Table A 全集）→ demand/dependency/candidate/timing 细分/direction/data/policy/inefficient **确认 direct observable 缺失** → 转 [TODO-MEASURE]（trace/model）+ SoC 侧电平累计实现 [BOUNDARY 待确认]；状态保持 OPEN（缺口已具体化）；
- **X-P1-09**：**CLOSED（confirmed absent）**——evidence = **Ch18 Table A（authoritative inventory）**：14 种命令计数不含 DRFM；增强需求（补 DRFM executed 计数）登记为 [TODO-RTL enhancement]；
- **O2-P1-01**：证据现状 = issue 侧可观测（命令 mix/恒等式）、payload 侧 absent（bytes/BE/RMW 无观测）——**issue loss 与 payload loss 当前无法分别量化** → 维持 [TODO-DESIGN]+[TODO-MEASURE]；
- **X-P1-08**：**保持 [TODO-DESIGN] OPEN**——本章提供 precedence 设计输入：direct observable（fifo_full/credit/cam_outnum/REF 计数/方向态）、组合推断（dependency/policy/timing 细分）、不可区分项（同拍多 blocker）—— precedence 规则不得在本章产生。

## 18.6 Architecture Node Mapping

三层观测体系/counter 全集/dbg_obv → **O1**；证据能力输入 → **O2/X-P1-08**；校准闭环（命令 mix↔模型）建议 → X-P1-07；soC 侧电平累计 → [BOUNDARY]。

## 18.7 Known RTL Limitation

- hit rate / P99 / row-hit / queue-empty / blocked_timing 细分 / blocked_policy / DRFM / switch count / WDP 占用：**confirmed absent in current inventory**（各转 [TODO-MEASURE] 或 enhancement）；
- 电平信号 top 侧累计的 SoC 实现归属 [BOUNDARY 待确认]；
- latency histogram 是否需要（当前 trace 后处理）[TODO-DESIGN]。

# 附录 A：Open Question Registry（全文档开放问题登记簿）

> **定位**：全文档开放问题的**唯一权威清单**——0.10 未关闭类标签（[TODO-SPEC] / [TODO-RTL] / [TODO-MEASURE] / [TODO-DESIGN] / [BOUNDARY]）的登记处；正文历史散落的"追踪清单 / 待处理项"引用自此收敛到这里。
> **Registry Scope Rule（Phase 5）**：仅登记 architecture-relevant unresolved questions；pure implementation-detail TODO 以 [TODO-RTL-local] 留在 Part III Known RTL Limitation（登记豁免，见 Ch0.8 Registry Scope Rule）。
> **Affected 编号说明**：OPEN/PARTIAL 条目的 Affected 均指向当前 authoritative 位置（Ch0~Ch18/Appendix）；**CLOSED 历史条目**保留 closure-era 旧编号（historical legacy source），不代表当前章节结构。
>
> **条目格式**：ID / Question / Why it matters to MC / Known（当前理解）/ Unknown（缺失证据）/ Need（需要哪类证据）/ Affected（章节）/ Priority / Status。
>
> **优先级定义**：**P0** = 不知道会导致 architecture model 错误，必须优先关闭；**P1** = 影响 tradeoff / corner-case，重要但不阻塞主模型；**P2** = 实现细节 / 数值优化。投入纪律：P0 > P1 >> P2。
>
> **Status**：OPEN / PARTIAL / CLOSED（关闭标准见 0.12）。关闭必须写明证据类型（[RTL] / [SPEC] / [MEASURED]），回填正文后条目保留并改标 CLOSED（A.4）。
>
> **ID 规则**：正文既有历史编号不改（优先级按新定义复核，标"残留"）；新增按域前缀 DP（Data Path）/ RF（Refresh）/ DM（Device Mgmt）/ RAS / X（跨章）/ DOC（文档维护）。

## A.1 P0：architecture model 级

**DP-P0-01 · Write data path 完整模型**（域 G）
- Question：AW/W 如何结合？写数据什么时候必须 ready？resize 在哪里？byte enable 什么粒度？WDP 如何分配、ptr 与 CAM 如何绑定？partial write / RMW 数据面怎么处理？DBI / ECC / CRC 在哪里？DFI 何时取数、PhyWrLat 如何约束？buffer 何时释放？write error 怎么处理？
- Why：WDP 占 LPDDR6 面积 10.40%（6.2.3）；write commit 链（0.13.1）目前只有命令面、没有数据面。
- Known：数据收齐才送 PA（1.4.2）；WDP 与 CAM ptr 一一对应（3.2.3）；DFI 持 ptr 取数 + DBI/ECC（0.3 ⑥）；一拍双数据靠 DFI 预取（7.8.5）；WAW merge 在 PA grant 后按 byte-enable 拼接（3.5.2）。
- Unknown：已全部由作者逐问确认（2026-10）——正文第 9 章。
- Need：作者确认 [RTL]（2026-10） | Affected：**第 9 章** / 3.2.3 | Status: **CLOSED（结构模型；量化项拆入 X-P1-07）**

**DP-P0-02 · Read return pipeline 完整模型**（域 G）
- Question：RD issue 后保存什么 metadata？DFI 无 AXI ID，返回数据如何绑定 command？PhyRdLat 的 contract？rolling / phase 如何影响 data alignment？RDP 具体做什么？DBI/ECC 位置？retry 怎么重新进入？reorder entry 何时释放？RDATA 如何重组？
- Why：读返回链跨 XMU / DFI / RDP 多段，是 reorder、保序、延迟归因与 RAS retry 模型的基础。
- Known：link list/node 机制与容量公式（1.3）；DFI 返回先入先出绑定命令信息（0.3）；RDP 处理 DBI/ECC（0.3）；每 cycle 一个读数据返回（1.3.1）；RMW-RD 携带写 CAM ptr 存入 DFI rddata path 完成读回绑定（9.5，读返回绑定机制的实证）。
- Unknown：已全部由作者逐问确认（2026-10）——正文第 10 章。
- Need：作者确认 [RTL]（2026-10） | Affected：**第 10 章** / 1.3 | Status: **CLOSED（结构模型；量化项拆入 X-P1-07）**

**RAS-P0-01 · Error 检测、分类与恢复边界全集**（域 J）
- Question：ECC / CRC / parity 分别在哪一级发现？读 / 写 error 可否 retry？**已 BRESP 的 write 出错怎么办**（0.16 PNR 核心 case）？命令是否还在 CAM？bank state / read metadata / reorder entry 如何恢复？retry 是否重新进 scheduler、是否提权？CE / UE / poison 如何向上游传播？坏 bank / rank / channel 如何隔离？
- Why：0.13.1 双视角 commit 决定了"response 已回、后端出错"必须有无声收敛路径——这是 RAS 域的骨架问题。
- Known：读数据 ECC/parity error 由独立 RAS retry 模块处理、不反冲 Scheduler（4.7）；Scheduler 只冻结不恢复（4.7）；**写侧已关闭（2026-10 [RTL]，9.6）**：BRESP 后写错误只中断、无 retry；RMW 读回 UE → 翻转低 2 位 checkbit 注入 poison，照常落盘、下次读出报 UE；**读侧主模型已关闭（2026-10 [RTL]，10.4/10.5）**：CE 在 RDP 纠正上送；UE 在 RDP 拦截（数据不上送 XMU、原 node/读 ID 保留）→ retry 模块（流程控制/命令收集/命令确定/窗口控制）经 UIF 注入重发、上限寄存器配置 ≤15 次、仅 DDR 实现；超限带 UE 标记返回 XMU + 中断；**收尾定稿（2026-10 [RTL]，10.5）**：UE 标志存入 link node 信息表、RDATA resize 时转 SLVERR（normal/exclusive 同路，monitor 独立模块）；LPDDR/HBM UE 首现即带标记上送+中断；无坏 region 隔离 [BOUNDARY]；中断分 UE/CE 汇为一个总中断、软件查具体源。
- Unknown：——（全部定稿，J 域关闭）。
- Need：作者确认 [RTL]（2026-10） | Affected：9.5 / 9.6 / 10.4 / 10.5 / 4.7 | Status: **CLOSED（J 域全关）**

**DM-P0-01 · Init / training 所有权与失败路径**（域 I，原 7.7 项 1）
- Question：training 类型清单？MRW 数据来源？失败重试路径？software 是否回读 delay line？
- Why：training ownership 是 PHY-MC 边界核心，决定 init 期间命令通路何时打开。
- Known：DRAM init 与 training 均由 PHY 主导，controller 经握手感知（7.2）。
- Unknown：已定稿（2026-10 [RTL]/[BOUNDARY]，12.5）——MC 对训练不可见：init 期 MRW 归 PHY、init 后 SW MRW、PHY retry 不可见、MC 仅 init 超时标志（CSR 轮询、无中断）。
- Need：作者确认 [RTL]（2026-10） | Affected：7.2 / 12.5 | Status: **CLOSED（[BOUNDARY]）**

**DM-P0-02 · 全局状态转换模型**（域 I）
- Question：对 SR / PD / DSME / DVFS / retraining 每种转换统一回答：谁发起？owner？进入条件？drain 到哪？bank 状态？refresh owner？PHY ownership 变不变？哪些寄存器 / 状态要保存换新？失败怎么收敛？
- Why：0.13.4 idle 分档与 7.3 排空链是素材，尚未形成统一 transition 表——这是横向 control plane 的骨架（0.2.1）。
- Known：低功耗五步排空链（7.3.1）；软硬件触发对称性（7.3.3）；DVFS 分族策略（0.13.4）；**RF↔DM 接口**：进 PHY-master / PD / SR / DFS 前强制 REFab（11.3）。
- Unknown：已全部由作者逐问确认（2026-10）——正文第 12 章（arbiter+worker 组织、worker 序列全集、drain 判据 bank∧critical、PD=Precharge only、DFS 复用 init 通道+SR 切频、SRX 三来源统一退出、SR 期 debt 冻结、无看门狗+双 CSR 观测）。
- Need：作者确认 [RTL]（2026-10） | Affected：**第 12 章** / 7.3 / 0.13.4 | Status: **CLOSED（结构模型）**

**RF-P0-01 · Refresh / Activation Maintenance control plane**（域 H）
- Question：REFab / REFpb / REFsb 覆盖路径？postpone / pull-in 决策细节？温度倍率？deadline 分布与 phase staggering？refresh QoS？RFM / ARFM / DRFM / PRAC / ABO 如何纳入统一 Activation Maintenance 模型（obligation → debt → scheduling → bank drain → maintenance command → unavailable interval → recovery）？
- Why：refresh 目前是"scheduler 里一个特殊 request"的视角（4.6），需升级为完整 control plane；不可延期 obligation 是调度收敛性的硬约束。
- Known：debt 机制与 postpone 上界 9×tREFI − 8×tRFC（4.6.1/4.6.2）；critical ref 执行路径（5.6）；REFpb vs REFsb 归因口径（4.6.4）；ref_act_mask / drfm 的 FSM 路径（5.3.3）；tRFCpb / tDRFM* counter 在册（6.2.1）。
- Unknown：已全部由作者逐问确认（2026-10）——正文第 11 章（双账本 / pull-in credit / Odd-Even round 计数器 / 温度档位双维 CSR / ab↔pb 模式切换 / REFsb=pb 跨 BG 变体 / RFM per-bank ACT 信用 / DRFM 归 DEVMGR / 优先级序）。
- Need：作者确认 [RTL]（2026-10） | Affected：**第 11 章** / 4.6 / 5.6 | Status: **CLOSED（结构模型；量化 → X-P1-07）**

**5-P0-04 · FORCE_PRE 与 critical ref 收口语义**（历史编号，P0 维持）
- Question：FORCE_PRE 断言后，已提交管线的 page-last（AP）col 如何收口？critical ref 是否存在触发 precharge 的路径？
- Why：决定 bank FSM 在 maintenance 打断下的正确性模型。
- Known：FORCE_PRE 触发源 = tRASmax [RTL]；**定稿（2026-10 [RTL]，11.7）**：critical 序列 = 先压制 ACT（ACT_FORBID）、后对 open bank 逐个 RR 强制 PRE——压制与强制 PRE 是先后两步。
- Unknown：仅剩 FORCE_PRE 断言后已提交 page-last col 的收口细节（按 5.3.3 现理解：AP col 走完收口、不接受新业务 col）。
- Need：作者确认 [RTL]（2026-10） | Affected：5.3.3 / 5.3.4 / 11.7 | Status: **CLOSED（2026-10）**

**X-P0-05 · 不可回滚点全链模型**
- Question：read / RMW / refresh / DVFS / retry 路径各自的 Point of No Return 在哪？每个点之后出错能否撤销、谁收敛？
- Why：0.16 框架已立，write 链已定稿（0.13.1），其余路径未标定。
- Known：write 五时刻双视角（0.13.1）；write 数据所有权移交点 = DFI 取数（9.2）；read PNR = RDP→XMU 边界（10.4）；retry 路径 PNR 已随读侧定稿（10.5）；refresh：REF 下发后 tRFC 窗口为不可撤销的 unavailable interval（11.7，无数据路径风险）；low power / DVFS：全程在排空后操作、无数据路径 PNR（12.3/12.4）。
- Unknown：——（全线定稿：write / read / retry / refresh / low power / DVFS / RMW 窗口）。
- Need：作者确认 [RTL]（2026-10） | Affected：0.16 / 9.2 / 10.4 / 11.7 / 12.3 | Status: **CLOSED**

## A.2 P1：tradeoff / corner-case 级

**3-P1-03 · RMW 两段窗口的第三方防护**
- Question：RMW read→write 之间，第三个同地址 request 如何防护？
- Why：若窗口无防护则是数据正确性 hole（将升级 P0）；预期由 CAM 入口检测覆盖，但 RMW 双段占用读写 CAM 的交互未推导完。
- Known：RMW 占读写 CAM 各一（3.1）；冲突检测在 CAM 入口、ID 无关（3.5.1）；数据面已定稿（9.5）——RMW-WR 驻留写 CAM 期间其地址对入口检测可见 [INFERENCE：防护或为结构性，待验证窗口 = RMW-RD 下发后至 RMW-WR 离开写 CAM 前]。
- Unknown：已定稿（2026-10 [RTL]，3.5.3）——入口检测命中 RMW entry → incoming Pending 于 IPROC + RMW flush 提权；RMW-WR 离开 CAM 后放行，之后靠 DRAM 命令序。
- Need：作者确认 [RTL]（2026-10） | Affected：3.5.3 / 0.13.2 / 9.5 | Status: **CLOSED**

**3-P1-06 · CAM burst entry 共享 priority/aging/credit 的性能后果**
- Question：4 条命令共享一个提名单位的延迟 / 公平代价多大？
- Why：3.3 口径注（3-P0-04）的量化延伸，决定 burst=4 参数依据。
- Known：调度可见性以 entry 为单位（3-P0-04 定稿）。
- Unknown：量化影响。
- Need：[TODO-MEASURE] | Affected：Ch2 V2 + Ch13 CAM/CQ（CAM burst entry 共享 priority/aging/credit 的性能后果） | Status: OPEN

**1-P1-06 残留 · exclusive monitor 粒度与失效事件全集**
- Question：monitor 监视的地址粒度？失效事件清单是否穷尽？（0.13.2 注记与 1.8 定稿需对齐——内部自洽检查）
- Known：机制 / 两条失败路径 / 个数 1~16（1.8 定稿 [RTL]）。
- Unknown：粒度与完整失效事件集。
- Need：[TODO-RTL] | Affected：Ch9 C2（exclusive 为正确性机制）+ Ch12 XMU（monitor RTL）+ 附录 C | Status: PARTIAL

**2-P0-02 残留 · DDR5 sub-channel 系统地址交错（业内调研）**（优先级复核 P1）
- Question：业内 DDR5 双 sub-channel 的系统地址交错惯例？
- Why：2.7 边界行——归属 SoC，但影响 mapping 章完整性叙事。
- Known：控制器视野内无 channel 位，交错由 SoC 决定 [RTL]（2.7）。
- Unknown：业内惯例。
- Need：[TODO-SPEC]（调研）| Affected：Ch3 L5（协议钉死位）+ RQ4/RQ12 | Status: OPEN

**6-P0-01/02 残留 · per-BG l 系列计数器清单**（优先级复核 P1）
- Question：同 BG（l 系列）AC timing 计数器完整清单与数量？
- Why：6.2.1 总账口径完整性（"分层 vs 全局"结论不受影响）。
- Known：s 系列 16×5；1017 为近似口径（6-P0-01 定稿声明）。
- Unknown：l 系列逐项清单与重算总数。
- Need：[TODO-RTL] | Affected：Ch5 T1/T2/T3 + Ch15 Timing Counter | Status: OPEN
- Ch15 batch 2 结论：**PARTIAL**——s 系列确认（tRRDs/tCCDs/tWR2RDs/tRD2WRs/rd2rd ×16 [RTL 近似]）；l 系列清单仍 [TODO-RTL]（tCCDl/tRRDl/tWR2RDl/tRD2WRl 等是否逐项存在以 RTL inventory 为准，不按协议名推断）

**DFI-P1-01 · DFI contract 深挖**
- Question：PhyRdLat / PhyWrLat 数值与配置？读数据返回 latency？DFI rolling / phase 对 data alignment 的精确约束？低功耗握手信号全集？
- Why：0.11 P1 方向；Data Path 章（域 G）的数据侧 contract 依赖它。
- Known：ratio / phase0 / 命令打包（7.1、7.4）；DFI 无流控（7-P0-08，4.7）；Write CRC 覆盖口径已确认（每 4bit DQ × BL16，9.3）。
- Unknown：latency 类参数与 rolling 细节。
- **Ch17 batch 3 结论：PARTIAL**——已确认 [RTL]：ratio 术语与定标、phase0 纪律、rolling ptr 在 DFI（起点 0/ctrlUpd·phyUpd 复位）、PhyWrLat 取数节奏（tphy_wrlat·多 cycle）、dfi_rddata_en 定时 vs data_valid 分离、PF window 结构、normal path 无 per-command 握手（scope 已收窄）；仍 OPEN：latency 数值档 / rolling 全语义 / 低功耗握手全集。
- Need：[TODO-SPEC]（DFI v5.x）+ [TODO-RTL] | Affected：Ch8 DP3 / Ch17 | Status: **PARTIAL**

**7-P1-04 · CA parity responsibility boundary**（Part III batch 3 更新）
- Question：谁生成 parity？谁检测？谁 latch/report？error 后 normal path 是否继续？是否 retry/retrain？
- Ch17 结论：**generation = controller 侧**（dfi_address 编码时生成 [RTL]）；detection / latch / report / reset-retrain 语义未确认 [TODO-SPEC/RTL]；Detection domain ≠ root-cause domain 原则适用（CA parity error 强指向 CA path，非自动物理根因）。
- Status: **PARTIAL**

**7-P1-05 · Write CRC protocol scope**（Part III batch 3 更新）
- Question：哪些 protocol enable？generation 所在 module？覆盖粒度？controller vs PHY 责任？error feedback？
- Ch17 结论：generation = WDP 读出侧 [RTL]；传输 = 增加 BL 方式；覆盖 = 每 4bit DQ × BL16 [RTL·DDR]；协议适用范围 / error feedback 通路 [TODO-SPEC]。
- Status: **PARTIAL**

**PF-P1-01 · CS prefetch window 收益量化**
- Question：8 个 PF entry 的覆盖行为？等效 2GHz 实测达成度？
- Why：7.8 是重大架构迭代但缺 Proof（0.9 第 8 问缺位——视为尚未完成）。
- Known：机制全貌（7.8）。
- Unknown：性能数据。
- Need：[TODO-MEASURE] | Affected：7.8 | Status: OPEN

**X-P1-07 · Perf 归因数据包（umbrella）**
- Question：timing blocker Top 5 lost-slot sweep（6.8）；per-workload "blocked only by refresh" cycles + postpone depth sweep（4.6.4）；0.17 blocked reason 全集的 counter 落地与 total-cycles 恒等式验证。
- Why：0.17 口径的数据兑现——workload → blocker → BW loss 闭环。
- Known：口径与公式（4.6.4 / 6.8 / 0.17→Ch0.4 v2）；RTL 观测全集与归因职责分工已定稿（第 13 章：计数/电平/dbg_obv 双通路；互斥归因在模型侧、当前无校准闭环）。
- **Demand vs Admission observability（Ch18 inventory 已完成，分层结论）**：已确认存在 ostd / fifo_full / PA credit / cam_outnum / 命令计数 / dbg_obv / DEVMGR·REF 观测等；**已确认缺失的 direct observable**：request-arrival / queue-empty / demand occupancy / dependency·candidate / per-timing blocker / direction switch·lost-cycle / WDP occupancy / blocked_policy / payload efficiency → [TODO-MEASURE]（trace / model 补齐）；Unknown 不再是"inventory 是否完成"，而是 measurement 与归因数据本身。
- Unknown：全部实测数据。
- Need：[TODO-MEASURE] | Affected：0.17 / 4.6.4 / 6.8 | Status: OPEN

**X-P1-08 · Performance Taxonomy Attribution Precedence**（Freeze Patch 新增）
- Question：同一 cycle 同时满足多个 blocked condition（如 visibility 不足 ∧ 无 eligible candidate；timing not ready ∧ 方向不匹配）时，如何定义 mutually-exclusive attribution precedence / ownership rule，使 total cycles = issued_useful + Σ 互斥 lost-cycle 类别真正闭合？
- Why：taxonomy v2（12 类）只是分类语言；无 precedence 规则则恒等式不能宣称 cycle-level 闭合（Audit Invariant 18）。
- Known：候选方向 A earliest causal blocker / B closest-to-issue blocker / C hierarchical attribution（no work → no visibility → no eligible → not legal → policy not selected 逐层细分）——仅登记未定稿，禁止预设 "timing > direction > refresh > policy"。
- Need：[TODO-DESIGN]（Phase 3 结合实际 pipeline / causal ordering 设计并验证；此前 Performance Attribution 保持 PARTIAL）| Affected：Ch0.4 / Ch1 RQ2 / Ch18 | Status: OPEN

**X-P1-09 · DRFM executed 命令计数缺失**（域 K）
- Question：CS 侧 14 种命令 executed 计数不含 DRFM——M5 的 cross-check 缺观测抓手。
- **Ch18 batch 3 结论：CLOSED（confirmed absent in current inventory）**——evidence = Ch18 Table A（authoritative inventory，原 L13-13.2 迁入）确认 14 种命令计数不含 DRFM；增强需求（补 DRFM executed 计数）转 **[TODO-RTL enhancement]**，性能关联分析 [TODO-MEASURE]。
- Need：[TODO-RTL enhancement] | Affected：Ch7 M5 / Ch18 Table A | Status: CLOSED（absent 确认；enhancement 另计）

**S3-P1-01 · Starvation worst-case service bound**（Node-scoped 新 ID：S3 = QoS / Aging / Fairness；不占用 legacy ID）
- Question：expired GPR 之外，CCT slot release、direction progress、timing legality 等条件共同作用时，是否存在可形式化的 worst-case service bound？如果存在，上界如何建立？如果不存在，目前只能证明什么层级的 liveness / anti-starvation property？
- Why：RQ6 / RQ10 的 20s 答案收紧后，"aging 防 starvation"需要明确的证据边界与 closure path。
- Known：aging / expired GPR 恒第一为防 starvation 核心机制 [RTL]（Ch1 RQ6/RQ10 已按此收紧措辞）。
- Unknown：形式化 cycle 上界是否存在；可证明的 liveness 层级。
- Need：[TODO-DESIGN] + [TODO-MEASURE]（starvation time 观测）| Affected：Ch4 S3 / Ch1 RQ6 / Ch1 RQ10 | Status: OPEN

**O2-P1-01 · Issue Efficiency vs Payload Efficiency**（Micro Patch 新增；Node-scoped：O2 = Performance Diagnosis Playbook）
- Question：Effective BW / Peak BW 的完整 loss model 是否需要同时包含 ① opportunity / issue loss（idle / blocked / unavailable）与 ② issued-but-inefficient payload loss（partial write / RMW amplification / burst utilization / 无效 byte / 协议·数据粒度放大）？blocked-cycle taxonomy 当前覆盖到哪一层？issued-but-inefficient 应如何与 cycle attribution 对接？
- Current Understanding：Ch0.4 blocked taxonomy 主要解释"为什么没有 useful issue opportunity"；RQ2 诊断链已存在 issued-but-inefficient 分支；两者尚未形成统一闭环。
- Missing Evidence：双层 loss 统一模型设计；payload 侧量化手段。
- Need：[TODO-DESIGN]，后续可能 [TODO-MEASURE] | Affected：Ch0.4 / Ch1 RQ1·RQ2 / Ch8 DP / Ch18 O1 | Status: OPEN

**RF-P1-02 · REF/REFab 是否以及如何降低 activation debt**（M4 OPEN-1）
- Question：REF（尤其 REFab 全 bank 刷新）是否冲销 RFM 激活债？冲销多少？
- 原则：聊天讨论过 ≠ 当前项目 RTL 已确认。Need：[TODO-SPEC]+[TODO-RTL] | Affected：Ch7 M4 | Status: OPEN

**RF-P1-03 · RAADEC 协议定义与当前 RTL 映射**（M4 OPEN-2）
- Question：RAADEC（协议侧=HBM3 厂商设定阈值，IEEE 1500 WDR 可读）在本 RTL 如何使用/映射？
- Need：[TODO-SPEC] | Affected：Ch7 M4 | Status: OPEN

**RF-P1-04 · PRE / RDA / WRA 对 RAA 的精确影响**（M4 OPEN-3）
- Question：RDA/WRA 含 PRE 语义但仍属激活活动——是否计入 RAA？PRE 呢？
- Need：[TODO-SPEC] | Affected：Ch7 M4 | Status: OPEN

**RF-P1-05 · 跨协议 activation-debt 语义一致性**（M4 OPEN-4）
- Question：DDR / LPDDR / HBM 各协议的 activation-debt 记账语义是否一致？
- 原则：某一个协议成立 ≠ 所有协议成立。Need：[TODO-SPEC] | Affected：Ch7 M4 | Status: OPEN

**RF-P1-06 · round-complete invariant 的 RTL 保障**（M3-INV-01）
- Question：Normal REFpb 三层 tier 准入下，是否存在某 bank 整个 round 不满足准入而被跳过、从而破坏 Tn+T(n+1) bound 的场景？critical 是否为唯一兜底？
- Why：Odd/Even watchdog 的正确性前提 = "每 bank 每 round 必完成一次 REFpb"；该前提本身需要 RTL 保障证据。
- Need：[TODO-RTL] | Affected：Ch7 M3 | Status: OPEN
- Ch15 batch 2 结论：素材（11.6 / L6）中无 round_complete 生成逻辑记载（bitmap/pointer/最后 bank 均未确认）——**保持 OPEN；M3 = PARTIAL**（缺口 = scheduler invariant 缺 RTL proof，数学本身无误）

**RF-P1-07 · 固定 bank 顺序 vs 固定 phase 的 safety margin**（M3）
- Question：REFpb 始终按 bank 递增时是否存在额外 safety margin？固定 order 与固定 phase 的区别？
- Need：[TODO-RTL]（round 内顺序语义确认）| Affected：Ch7 M3 | Status: OPEN
- Ch15 batch 2 结论：素材无 fixed order / phase / RR起点 的 RTL 记载——**保持 OPEN**（Odd/Even correctness 只依赖 each-bank-once-per-round invariant，fixed order 疑似仅 margin 增益——该推断本身 [MODEL] 待证）

**RF-P1-08 · DRFM protocol-side target handoff 序列**（M5-B）
- Question：ACT → PRE/AP sampling → DRAM 内部 DRFM target register → DRFMpb 的交接协议序列；row 信息如何交给 DRAM？DRFM command 是否携带完整地址？
- Known：controller 侧 target selection = csrBakNDrmRowAddr [RTL]（11.8）；协议侧语义见 `Memory_Protocal.md` §4.7。
- Need：[TODO-SPEC]+[TODO-RTL] | Affected：Ch7 M5 | Status: OPEN

**DP2-P1-01 · PhyRdLat semantic boundary**（Micro Patch 新增；Node-scoped：DP2）
- Question：当前 RTL 中 PhyRdLat 精确决定什么——capture enable？expected arrival window？metadata alignment？command-info FIFO pop timing？read-data FIFO sizing？rotator phase？data_valid 与 PhyRdLat 分别承担什么责任？
- Current Understanding [RTL·部分]：存在 PhyRdLat 多频点配置、dfi_rddata_en、data_valid、read data FIFO / rolling path；精确 ownership / alignment contract 未确认。
- Missing Evidence：RTL 信号级确认 + DFI normative semantics。
- Need：[TODO-RTL] + [TODO-SPEC] | Affected：Ch8 DP2 / Ch17 | Status: OPEN

**XMU-P1-01 · Write tracking lifetime vs write-data retention lifetime**（Part III Batch 1 新增；Node-scoped：XMU）
- Question：write transaction 在 PA grant / BRESP 后、WDP fetch 前，write data 由哪个 structure/state 保活？XMU outstanding tracking lifetime 与 physical write-data retention lifetime 是否为同一 lifetime？
- Current Understanding [RTL·部分]：write data 物理驻留 XMU 侧 buffer 至 WDP fetch（9.2-③ [RTL]）；BRESP/accounting 在 grant 拍完成（1.4.2 [RTL]）——两个 release 点不同。
- Need：[TODO-RTL]（tracking entry 与 data storage 的结构对应关系）| Affected：Ch12 / Ch8 DP1 / Ch9 C3 | Status: OPEN

**DP2-P1-02 · Retry-induced HOL worst-case bound**（Freeze Patch 新增；Node-scoped：DP2）
- Question：retry count ≤15 是否足以推出同 ID HOL 的严格 cycle upper bound？若不能，还缺哪些 service-bound 前提（每次 retry 的 worst-case service time / scheduler progress / timing legality / direction switching / maintenance interference / admission availability）？
- Current Understanding：[RTL] 次数有界（≤15，寄存器可配）；[MODEL] 次数有界 ≠ 时间有界。
- Need：[TODO-DESIGN] + 可能 [TODO-MEASURE] | Affected：Ch8 DP2 / Ch9 C3 / S3-P1-01（关联）| Status: OPEN

**C3-P1-01 · Write command cancel path existence**（Part II Freeze Patch 新增；Node-scoped：C3）
- Question：当前 RTL 在 WR col issue 之前（command PNR 之前）是否存在内部 cancel / replay path？
- Current Understanding：C3 五链矩阵按"未确认"处理——pre-PNR 的撤销能力不假设支持 arbitrary cancel/replay。
- Need：[TODO-RTL] | Affected：Ch9 C3 / Ch8 DP1 | Status: OPEN

**RF-P1-09 · 9×tREFI / 8-postpone / 9×tREFI−8×tRFC 的协议适用范围**（Micro Patch 新增）
- Question：9×tREFI 间隔上限、最多 8 次 postpone、上界 9×tREFI−8×tRFC 分别适用于哪些 protocol（DDR4/5、LPDDR4/5/6、HBM3/4）与 refresh mode（ab/pb/sb）？
- Current Understanding：正文按 DDR/LPDDR 一致口径记载（legacy 4-P0-02 定稿 [SPEC]）；未逐协议 / 逐 mode 复核，不假设 HBM 一致。
- Missing Evidence：逐 protocol / mode 的 SPEC 条款定位。
- Need：[TODO-SPEC] | Affected：Ch0.6 / Ch7 M1·M3 / L11 | Status: OPEN

## A.3 P2：细节 / 数值

**6-P0-05 残留 · counter FF 数回填**（优先级复核 P2）
- Question：1017 逻辑 counter 对应的 synthesis FF 数（按位宽加权）？
- Need：[TODO-MEASURE] | Affected：Ch5 P1（scaling）+ Ch15 面积口径 | Status: OPEN

**DM-P2-02 · DSME 序列与 clock gate 转换细节**
- Question：DSME（LPDDR 族第三分支）的进入/退出序列逐项细节；clock gate 转换（XMU 反压的另一个场景）未展开。
- Need：[TODO-RTL] | Affected：Ch11 G1 + Ch17 DEVMGR | Status: OPEN

**DOC-P2-01 · 八问速答表退役**（原 7.7 项 2；Freeze 定稿改判：迁移 → 退役）
- Question：原"7 张速答表迁移到新版八问结构"改判**退役**——信息去向：为什么存在→Part I Node Problem；输入输出→Part III Module Boundary；状态→Owned State；数据流→Critical Pipeline；瓶颈/参数→Node Model/Tradeoff；backpressure→Resource Lifetime；异常收敛→G1/R1+Lifetime。
- **Phase 5 关闭证据 [DOC]**：Legacy Zone 已删除（Phase 4）；速答表信息去向全部由 Part I Node 字段 + Part III 6+1 模板接管（Ch12~Ch18 已按模板落地）；final audit 无残留速答表引用。
- Need：— | Affected：—（历史） | Status: **CLOSED（Phase 5）**

**DOC-P2-02 · blocked reason taxonomy v1→v2 升级**（DOC-CAL-01，Freeze Patch 新增）
- Question：0.17 的 8 类保留集（blocked_refresh / blocked_data_not_ready 等）升级为 12 类（新拆 blocked_admission / blocked_visibility；更名 blocked_maintenance / blocked_data）——新 Ch0.4 已按 v2 落地；Legacy 各处（4.6.4 / 6.8 / 0.17 残引）随 Ch3~Ch8 迁移同步。
- **Phase 5 关闭证据 [DOC]**：Legacy Zone 已删除（Phase 4）；final audit 扫描确认正文无 blocked_refresh / blocked_data_not_ready / 8 类残留（仅本条作为历史说明保留旧类名）；taxonomy v2 为全文唯一口径（Ch0.4，X-P1-08 未关闭前不宣称 cycle-level closed accounting）。
- Need：— | Affected：—（历史） | Status: **CLOSED（Phase 5）**

## A.4 关闭规则

关闭条目时在此保留并注明证据与日期，例：`X-P0-01 write 时刻表 —— 0.13.1，[RTL]，CLOSED`。正文已标"定稿"的历史条目以正文标注为准，不在此重复登记；新增问题必须先登记再研究，防止"问题从文档里消失"（0.1）。

# 附录 C：Global State Owner Table（完整版 / authoritative）

> 来源：X-P0-03 定稿 [RTL]，原 0.13.3 迁入（Phase 4 恢复 + 与 Ch0.6 / Part III Owned State cross-check 后定稿）；与 Ch0.6 精简版、Part III 各章 Owned State 字段互链；本表为唯一完整权威版。原则：**one state → one owner → multiple consumers**；跨模块使用一律只读映射（4-P0-05 定稿）。

| State / Resource | Unique Owner | Consumers | Mutation Event | Release / Reset | Evidence |
|---|---|---|---|---|---|
| bank open/closed（row 状态，含 open-row 地址） | BSC（per-bank FSM，Ch14） | CQ hit 判断（只读） | ACT/PRE issue | PRE 收尾/WRA_RDA 内部收口 → IDLE | [RTL] |
| AC timing ready | Timing Enforcement counter（Ch15）——与 BSC 相与 | BSC/FSC | 命令 issue load | 归零自动 | [RTL] |
| 读写方向 | GSC（Ch14/Ch6 D1） | BSC/FSC | 切换完成 | 切换反转 | [RTL] |
| refresh debt/credit/档位/ab-pb 模式/critical 态 | 独立 refresh 模块（Ch7 M1/M2） | CQ/GSC（优先级调节） | tREFI 到期/REF 完成/档位切换 | REF 完成清账；SR 期冻结 | [RTL] |
| RFM 激活债（per-bank ACT 计数） | refresh/RFM 模块（Ch7 M4） | FSC（达限禁 ACT） | ACT 计数 | RFM 清账（REF 冲销语义 OPEN→RF-P1-02） | [RTL] |
| DRFM 命令生成 | DEVMGR（地址 = csrBakNDrmRowAddr，Ch7 M5） | FSC / timing counter | DEVMGR 触发生成 | tDRFM 生命周期（三寄存器） | [RTL] |
| credit（PA↔CQ） | credit 机制（PA grant 消耗） | PA 仲裁 | PA grant | 命令离开 CAM（burst 末条） | [RTL] |
| write data ready | XMU/WDP（数据收齐才送 PA，→C1/DP1） | PA/FSC | WDP 数据到位 | 数据被消费/所有权移交 | [RTL] |
| WDP entry 生命周期 | WDP（→DP1） | DFI 取数 | fetch 受理 | DFI 取走（ownership transfer） | [RTL] |
| write BE/DM | WDP 寄存器堆（→DP1） | WAW/RMW merge、DM 生成、编码 | 数据写入/merge | entry 释放 | [RTL] |
| WDP fetch FIFO | CQ→WDP 通路（→DP1） | WDP | CQ push | WDP 有位受理 | [RTL] |
| RMW 读回绑定 ptr | DFI rddata path（RMW-RD 发出时存入，→DP2/Ch16） | WDP merge 路由 | RMW-RD issue | 读回路由完成 | [RTL] |
| 读返回命令信息 FIFO | DFI rddata path（→DP2/Ch16） | RDP/XMU | RD col 下发 push | 返回按序 pop | [RTL] |
| rolling ptr / read data FIFO | DFI（→DP2-P1-01 关联） | RDP | ctrlUpd/phyUpd 复位；起点 0 | —（持续滚动） | [RTL] |
| 读 retry 状态（计数/窗口） | RAS retry 模块（→Ch10 R1） | CQ/DFI | UE 检出触发 | 成功上送/超限 SLVERR | [RTL] |
| 读返回保序（link list/reorder buffer） | XMU（→V1/C1/DP2） | XMU→AXI | node 分配 | head-only 释放 | [RTL] |
| outstanding 计数（protocol/accounting） | XMU ostd buffer（→V1） | AXI 反压 | txn accepted | BRESP 发出（**data retention 另计→XMU-P1-01**） | [RTL] |
| write-data retention buffer | XMU 侧 buffer（→DP1/XMU-P1-01） | WDP fetch | W 数据写入 | WDP fetch（所有权移交） | [RTL] |
| CAM entry / burst 合并态 | CQ（→Ch13） | 三层 filter/CS | PA grant 后 allocation/merge | burst 末条离开 CAM | [RTL] |
| IPROC Pending | CQ 入口（→C2/Ch13） | 后续入队 | 冲突检出 | 冲突对象离开 CAM | [RTL] |
| CCT 占用（RD/WR per-bank 单槽） | CQ（→S1/Ch13） | CS | 上表 | 命令发送 | [RTL] |
| 提名优先级 / CamAging | CQ priority filter + CamAging（→S3/Ch13） | CCT 提名 | aging 计满打标 | entry 释放 | [RTL] |
| 全局转换（arbiter + 六 worker） | DEVMGR（→G1/Ch17） | XMU（仅 DFS/clock gate 反压）/ DFI / refresh | arbiter grant | worker done | [RTL] |
| SID 切换迟滞 | CS 内 GSC（SidSwitch，→D2） | CS 切换决策 | 迟滞计数 | 阈值满足可切 | [RTL] |
| Odd/Even watchdog | refresh 域（→M3/Ch15） | M1 critical 拉响 | round 推进累计 | round 结束清本相位 | [RTL] |
| tFAW rolling window（4 错相 slot） | Timing Enforcement（→T2/Ch15） | BSC ACT ready | ACT 轮流 load | 归零 | [RTL] |
| exclusive monitor ×1~16 | XMU 独立模块（→C2/Ch12） | BRESP EXOKAY/OKAY | exclusive read grant | 失效事件（粒度 OPEN→1-P1-06） | [RTL] |

## Appendix C cross-check 结论（Phase 5）

抽样 12 项（bank row / timing legality / GSC direction / refresh debt / activation debt / PA-CQ credit / CAM·CCT / XMU outstanding / WDP ownership / RDP·reorder / DEVMGR transition / Odd-Even watchdog）与 Ch0.6 精简版、Part III Owned State 逐项比对——**无双 owner、无 owner 缺失**；新增行（write-data retention buffer、CAM entry、IPROC、exclusive monitor、tFAW window、Odd/Even）均来自 Part III Owned State [RTL] 声明。**PASS**。

