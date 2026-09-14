# 面试问题追踪清单（Interview Questions Tracker）

> **用途**：承载对《DDR_Controller_Architecture.md》的评审问题全量清单。每题按编号逐个讨论，结论定稿后回写主文档，并在此登记状态。
>
> **状态枚举**：
> - `待讨论`：尚未处理
> - `讨论中`：正在展开
> - `已闭环`：讨论完成，主文档无需修改（或原文已正确，仅澄清术语）
> - `已改文档`：结论已回写主文档
> - `需补数据`：Q 类量化缺口，等待仿真 / benchmark 数据
>
> **初判取值**：`笔误` / `术语歧义` / `协议事实` / `内部矛盾` / `取舍论证` / `量化缺口` / `文档缺节`

## 总览

| 章 | P0 | P1 | P2 | I | Q | 小计 |
|---|---|---|---|---|---|---|
| 0 全局 | 4 | 5 | — | 4 | 3 | 16 |
| 1 AXI/XMU | 7 | 9 | — | 5 | 4 | 25 |
| 2 AddrMap | 5 | 7 | — | 5 | 3 | 20 |
| 3 ReqQueue | 3 | 8 | — | 5 | 4 | 20 |
| 4 CmdQueue | 4 | 6 | — | 5 | 3 | 18 |
| 5 Scheduler | 5 | 6 | — | 6 | 4 | 21 |
| 6 Timing | 4 | 6 | — | 5 | 3 | 18 |
| 7 DFI | 6 | 7 | — | 5 | 4 | 22 |
| X 跨章 | 4 | 7 | 1 | — | — | 12 |
| **合计** | **42** | **61** | **1** | **40** | **28** | **172** |

## 讨论轮次（按风险顺序）

1. **第一轮**：1-P0-01 ~ 1-P0-12 —— AXI/XMU ordering 与 response
2. **第二轮**：2-P0-01 ~ 2-P0-06 —— 地址坐标与 stride 论证
3. **第三轮**：4-P0 + 5-P0 —— Scheduler 内部自洽
4. **第四轮**：6-P0 + 7-P0 —— Timing / DFI 协议边界
5. **第五轮**：全部 P1 / I / Q —— tradeoff + 量化

---

## 第 0 章：全局架构总览

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 0-P0-01 | 协议事实 | "64B = cache line = col command = CHI 包 = sub-command"中，哪些是协议事实、哪些是内部设计选择？DDR4/5/LPDDR5/HBM3/4 是否都天然 64B/col command？ | §0.5-4 | 取舍论证 | 待讨论 | 注（来自 1-P0-01 讨论）：col command 粒度随协议变化（LPDDR5 DQ32×BL16=64B；HBM per PC DQ32×BL8=32B）——"粒度统一 64B"是本设计锚点口径而非协议事实；注（来自 1-P0-05）："CHI 包 = 64B"也是产品配置（IP 固定 size=64B），非协议上限 |
| 0-P1-02 | 协议事实 | "AXI/CHI → XMU → DRAM semantic"边界是否准确？AXI ordering/response/exclusive 语义在 XMU 之后是否仍需 RAW/WAR/WAW 继续维护？ | §1.1 | 术语歧义 | 待讨论 | 注（来自 1-P0-03）：slave 义务仅"同 ID 同方向"；XMU 之后的 RAW/WAR 拦截属数据正确性机制而非保序义务——正是本题答案素材 |
| 0-P0-03 | 内部矛盾 | §0.1 把 Timing Enforcement 画在 Command Generator 之后，§5/§6 却说 BSC counter 即 Timing Enforcement 且在 FSC issue 前。真实 RTL 数据流是哪个？ | §0.1 vs §5.1/5.3 | 内部矛盾 | 待讨论 | 预判：改 §0.1 流水线图 |
| 0-P0-04 | 内部矛盾 | PA grant / Address Mapping / Request Queue / CAM 的真实先后关系，§0.1 层级图与 §0.2-② 不一致 | §0.1 vs §0.2-② | 内部矛盾 | 待讨论 | |
| 0-P1-05 | 内部自洽 | "命令流与数据流仅以 ptr 关联"是否完整？txn ID / ECC metadata / byte mask / RMW state / retry history 等 sideband 关联是否遗漏？ | §0.2 观察2 | 术语歧义 | 待讨论 | |
| 0-P0-06 | 内部矛盾 | response 究竟是"PA grant 即返回"还是"PA grant + 写数据到达 XMU"？BRESP generation condition 的准确定义 | §0.2-② vs §1.4.2/3.5.2 | 内部矛盾 | 待讨论 | 预判：后文条件为准，§0.2 简化表述需改 |
| 0-P1-07 | 取舍论证 | 统一 64B sub-command 的理由；改 32B/128B 对 CAM utilization、WDP、mapping、scheduling、partial write、burst 拆分的影响 | §1.2 | 取舍论证 | 待讨论 | |
| 0-P1-08 | 取舍论证 | 跨时钟 FIFO=outstanding buffer 一物两用的收益与约束（FIFO ordering、HOL、depth sizing、CDC latency） | §0.3 | 取舍论证 | 待讨论 | |
| 0-P1-09 | 取舍论证 | 地址 mapping 为什么放 CAM 入口而不是 XMU 更前 / Scheduler 更后 | §0.2 观察3 | 取舍论证 | 待讨论 | |
| 0-I-01 | 面试 | 白板 2 分钟：AXI AW → DRAM WR 各阶段 accepted/committed/scheduled/issued/completed/responded 定义 | §0.2 | 文档缺节 | 待讨论 | |
| 0-I-02 | 面试 | 全链路 backpressure point 有几个？哪个最易 throughput collapse？ | 全文 | 文档缺节 | 待讨论 | 注（来自 1-P0-04）：backpressure 链新增一环"port AW ostd 满→单 port 自饿"，故障域隔离在 port（PA 不锁死，设计保证） |
| 0-I-03 | 面试 | PHY 连续 100 cycle 不收命令，上游最终在哪里停住？ | §7/DFI | 待讨论 | 待讨论 | |
| 0-I-04 | 面试 | write 的 command path latency 与 data path latency 各由哪些部分组成？ | §0.2 | 量化缺口 | 待讨论 | |
| 0-Q-01 | 量化 | 缺端到端 latency budget：T_CDC+T_PA+T_CAM+T_Sched+T_DFI+… 典型数据 | 全文 | 量化缺口 | 待讨论 | |
| 0-Q-02 | 量化 | 各 pipeline stage 的 peak command/cycle；真正的理论 throughput bottleneck | 全文 | 量化缺口 | 待讨论 | |
| 0-Q-03 | 量化 | 典型配置表：AXI outstanding / AFIFO depth / CAM depth / CCT count / WDP depth / RDP depth / DFI flight 及理由 | 全文 | 量化缺口 | 待讨论 | |

---

## 第 1 章：AXI / XMU

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 1-P0-01 | 协议事实 | "4KB = 2^13，边界只看低 13bit"是笔误还是用了非 byte address？ | §1.2.3 | 表述不完整 | 已改文档 | "低 13bit"指 transfer 起始地址计算的位宽 bit[12:0]：低 12bit 页内偏移 + bit12（4KB 位）。依赖 AXI"txn 不跨 4KB"契约，无硬件检测；进位翻转 bit12 只发生在 txn 末端，结果不再被使用，功能安全。移位量随 col command 粒度可配：LPDDR5 DQ32×BL16=64B→6bit；HBM per PC DQ32×BL8=32B→5bit。已重写 §1.2.3、§1.2.1 加移位量注记；"4KB = 2^13"等式已删除 |
| 1-P0-02 | 协议事实 | BRESP 提前返回后，同地址 read 如何保证读到该 write？机制是 RAW block / store-to-load forwarding / write buffer snoop / 强制 flush 中哪个？ | §1.4.2/§3.5 | 协议事实 | 已改文档 | 机制=RAW block（非 forwarding）：检测在 CAM 入口、ID 无关（PA grant 后命令无 txn 信息）；Pending 位于 PA→CQ 一级 buffer，单通路使后续命令全部阻塞=顺序由结构保证；放行条件=冲突 write 从 CQ 调度下发（离开 CAM），此后数据顺序由颗粒按命令序保证；同 ID 保序=同方向，反方向同地址由 master 按 response 顺序保证（§1.4.2）；WAW merge 不影响 RAW 判定（merge 后 entry 无 txn 信息，仅物理地址）。已更新 §1.4.2/§3.4.1/§3.5.1/§3.5.2 |
| 1-P0-03 | 协议事实 | 同 ID r-r / 同 ID w-w / 不同 ID / r vs w / 同地址 vs 异地址：哪些 ordering 是 AXI guarantee，哪些是 controller 额外保证？ | §1.3.1/§1.4.2 | 协议事实 | 已改文档 | 五分类：①同 ID 同方向（r-r/w-w）=AXI 要求 slave 保证（读 link list head-only 释放、写 B outstanding FIFO）；②同 ID 不同方向=slave 无义务，master 按 response 顺序自行维护；③不同 ID=双方均不保证，允许乱序交织；④地址不参与保序，slave 不维护地址序；⑤RAW/WAR 入口拦截（3.5.1）是 BRESP 提前返回架构下的数据正确性机制，非 AXI 保序义务。已修正 §1.3.1 口径（同 ID 严格保序→同 ID 同方向）、新增 §1.4.4 责任五分类表（§1.4.3 已被"不做超时防死锁"占用） |
| 1-P0-04 | 协议事实 | AW 来 W 不来时"master 一定可感知"是系统 contract 还是 AXI protocol 要求 master 有 timeout？ | §1.4.3 | 协议事实 | 已改文档 | AXI 对 AW/W 到达无任何时间约束，协议无超时概念——"master 能感知"是系统 contract（master 侧超时中断/重启复位兜底），CTRL 不处理；后果链=该 txn 卡住→该 port AW ostd 占满→单 port 自饿；PA 仲裁不会锁定无请求 port（设计保证），其他 port 与已进 core 命令不受影响；卡点随 mask write 能力不同：支持 mask write 时命令可先于数据下发（最多到当前 txn 命令发送结束），不支持时（HBM→RMW）命令必须等数据 resize 完成才能下发；不防御理由=等 W 收齐才收 AW 会损失流水重叠效率，不污染主通路。已重写 §1.4.3 |
| 1-P0-05 | 协议事实 | "AXI 与 CHI 无核心差异，仅 CHI 最大 64B"指 normalization 后 internal request 层，还是协议本身？必须二选一 | §1.6/§1.7 | 术语歧义 | 已改文档 | 二选一：协议本身差异很大（snoop filter/DVM/ordering/独立 data channel）；"无核心差异"限定于 CTRL 视野内 NoSnp 最小特性集 normalization 后。normalization：ReadNoSnp→read；PrefetchRead→LPR（当前上游不投可丢 prefetch，不丢弃）；WriteNoSnpFull/Pt→write（PtlWrite 借 datachunk 可发 mask write）；QoS 类似 AXI；包 64B=产品配置非协议上限。response：wdat 接收后才 PA grant，故 Comp/CompDB 在 PA grant 即回——与 AXI"PA grant+数据到达"同一原则，CHI 模式数据先到条件合并。已重写 §1.6、改写 §1.7 金句 4 |
| 1-P1-06 | 协议事实 | Exclusive monitor 粒度（address/cache line/ID/port）？哪些事件 invalidate monitor？ | §1.x | 取舍论证 | 待讨论 | |
| 1-P1-07 | 协议事实 | FIXED/INCR/WRAP 是否全支持？只支持部分时 XMU 如何处理？ | §1.2 | 协议事实 | 待讨论 | |
| 1-P0-08 | 内部矛盾 | XMU "page hit 判定"判的是"两条请求同 DRAM page（静态等价）"还是"hit 当前 open row（动态 BSC 状态）"？术语必须明确 | §1.2.2 | 术语歧义 | 已改文档 | 全文三个 "page hit" 分立：①XMU 信号 page_match_next（XMU→PA）=当前 sub-command 与同 txn 下一 sub-command 的静态同 page 判定，消费点=PA 提高该 port 优先级、缩短拆分延迟；②CAM burst"同 page"准入=静态等价，多条同 page 命令 merge 进 burst entry（§3.3）；③CS page hit=CCT 命令对应 bank open row 命中、可直接发 col 不发 ACT=动态 BSC 状态（FR-FCFS 的 FR）。已重写 §1.2.2（标题改 page_match_next 预判+RTL 形态/消费点/术语澄清框，"第 1 章地址映射"笔误改"第 2 章"）、改写 §1.9 金句 3 |
| 1-P1-09 | 内部自洽 | "除 col 位外全相同 = same page"依赖 col 位宽；Address Mapping 可配置时 XMU 如何得到一致的 col bit 配置？ | §1.2.2/§2 | 取舍论证 | 待讨论 | 注（来自 1-P0-08）：page_match_next 判定同样依赖 col 位宽配置，本题讨论时与 §1.2.2 连用 |
| 1-P1-10 | 内部自洽 | 同一 AXI ID 的多笔 txn 是否一定同 link list？单 ID 持续发包会不会永久占住该 list？ | §1.4.1 | 取舍论证 | 待讨论 | |
| 1-P1-11 | 内部自洽 | "空 list 优先、满则 RR"是否意味着一个 list 可混 ID=A/B？head release 与不同 ID interleave 如何避免 HOL？ | §1.4.1 | 取舍论证 | 待讨论 | |
| 1-P0-12 | 内部矛盾 | "link node 数 = reorder buffer depth"完全等价？读数据存在 link node 里还是 metadata+SRAM ptr？ | §1.4.1 | 术语歧义 | 已改文档 | 结构事实：link node 存 AXI 元数据（ID/size/len，用于颗粒数据→AXI RDATA 重组），node 索引即 reorder buffer SRAM 地址，node 与数据缓冲一一对应——"node 数 = reorder buffer 深度"在结构与容量两层同时成立。公式修正：link node 数 = CTL_CAM_DEPTH × CTL_CAM_BURST_SIZE / 2 + 补偿值（按平均每 entry 装 2 条命令折算）；大包（≥4 sub-cmd）瓶颈在 node 侧，小包（≤2）瓶颈在 CAM 侧；补偿值按配置 tune（LPDDR6 CAM32 / HBM4 CAM96 = 32，HBM3 CAM64 = 64），加大→在途更多、攒批效率↑，延迟与面积↑。交叉验证：32×4/2+32=96、96×4/2+32=224 与 6.2.3 吻合。已重写 §1.4.1 |
| 1-P1-13 | 取舍论证 | ROB 为什么用 linked-list 而非 per-ID FIFO / centralized array / sequence-number ROB？最大 PPA 优势 | §1.4.1 | 取舍论证 | 待讨论 | 注（来自 1-P0-12）：结构出发点 = node 存 AXI 元数据、node 索引即 reorder buffer SRAM 地址，node 数随 CAM 容量折算 |
| 1-P1-14 | 取舍论证 | "outstanding 太大增加 latency"是排队论推论还是实测？何时 outstanding↑ 同时 BW↑ 且 latency 不明显增？ | §1.4 | 量化缺口 | 待讨论 | |
| 1-P1-15 | 取舍论证 | read list=32 真正限制的是 ID 数 / txn interleave 数 / 返回 stream 数 / reorder freedom 中的哪个？ | §1.4.1 | 取舍论证 | 待讨论 | |
| 1-P1-16 | 取舍论证 | write response 前移的最大收益发生在 CPU pipeline / NoC credit / XMU outstanding recycling 哪一层？ | §1.4.2/§3.5.2 | 取舍论证 | 待讨论 | |
| 1-I-01 | 面试 | "BRESP 回了但 DRAM 没写，突然掉电怎么办？"标准回答 | §1.4.2 | 待讨论 | 待讨论 | |
| 1-I-02 | 面试 | "BRESP 后同地址 AR 立即进来，CAM 中 write 未执行"完整时序 | §1.4.2/§3.5 | 待讨论 | 待讨论 | 注（来自 1-P0-02）：答案素材已齐——read 被 CAM 入口 RAW 检测拦截 Pending 于 PA→CQ buffer，冲突 write 提权调度下发后 read 放行，数据序由颗粒保证 |
| 1-I-03 | 面试 | 同 ID 两笔 read，DRAM 第二笔先返回，ROB 内部发生什么？ | §1.4.1 | 待讨论 | 待讨论 | |
| 1-I-04 | 面试 | 不同 ID 允许乱序，为何不让它们完全自由返回而还需要 link list？ | §1.4.1 | 待讨论 | 待讨论 | |
| 1-I-05 | 面试 | Port QoS 与 AXI QoS 是同一概念吗？低 QoS request 来自高 priority port，谁压过谁？ | §1.x | 待讨论 | 待讨论 | |
| 1-Q-01 | 量化 | Outstanding depth → BW 曲线与 saturation point | §1.4 | 量化缺口 | 待讨论 | |
| 1-Q-02 | 量化 | Outstanding depth → Avg/P99 latency 曲线，证明"太大增加 latency" | §1.4 | 量化缺口 | 待讨论 | |
| 1-Q-03 | 量化 | link list = 8/16/32/64 对 reorder throughput / area / HOL 的影响 | §1.4.1 | 量化缺口 | 待讨论 | |
| 1-Q-04 | 量化 | BRESP 前移究竟减少多少上游 observed latency | §1.4.2 | 量化缺口 | 待讨论 | |

---

## 第 2 章：Address Mapping

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 2-P0-01 | 协议事实 | "UIF = system addr >> 6"与"col[2:0] = 8B 粒度"两套 bit numbering 坐标系分别是什么？需区分 byte address / UIF address / DRAM col address | §2.2.1 | 术语歧义 | 讨论中 | 相关原文：§2.2.1 位序图 "col[2:0]=8B 粒度 / col[5:3]=64B 命令序号 / cs=512B"；§1.2.1 UIF=system addr>>6 + 移位量注记 |
| 2-P0-02 | 协议事实 | "DDR5 sub-channel interleave 32B 粒度"依据的是 JEDEC 协议约束还是本 SoC mapping 选择？ | §2.x | 协议事实 | 待讨论 | |
| 2-P0-03 | 协议事实 | "HBM PC 位固定在最高位"是 JEDEC physical address definition 还是 controller/core topology 选择？ | §2.x | 协议事实 | 待讨论 | |
| 2-P1-04 | 协议事实 | CS 在 HBM/DDR/LPDDR 中是否始终等价 rank select？多 SID/stack/rank 命名是否混淆？ | §2.x | 术语歧义 | 待讨论 | |
| 2-P0-05 | 内部矛盾 | "任何 < page size 的 stride 都不会同 bank 换 row"考虑的是 txn 内 sequential 还是 txn base 之间的 stride？ | §2.3 | 术语歧义 | 待讨论 | |
| 2-P0-06 | 内部矛盾 | 用"AXI txn 内连续递增"证明 stride 风险不存在，但 workload 可每 txn 隔大 stride，论证是否需要重做？ | §2.3 | 内部矛盾 | 待讨论 | |
| 2-P1-07 | 内部自洽 | "256B txn 不需要 BG interleave，BG 随机分配"的"随机"具体是 hash / 固定位 / pseudo-random / scheduler routing？ | §2.x | 术语歧义 | 待讨论 | |
| 2-P1-08 | 内部自洽 | "每 bank 4~8 commands 是下限"是经验规律还是 benchmark 结果？不同 tRCD/tCCD/data rate 下是否成立？ | §2.x | 量化缺口 | 待讨论 | |
| 2-P1-09 | 取舍论证 | 为什么选 {row,cs,ba,col,bg,col} 而非 RBC/BRC/hashed？优化目标函数是 BW/Latency/P99/Energy/Fairness？ | §2.2 | 取舍论证 | 待讨论 | |
| 2-P1-10 | 取舍论证 | Row locality 与 BLP 冲突时如何找最佳点？ | §2.3 | 取舍论证 | 待讨论 | |
| 2-P1-11 | 取舍论证 | 是否考虑 XOR hashing？对 power-of-two stride 能解决哪些热点？ | §2.x | 取舍论证 | 待讨论 | |
| 2-P1-12 | 取舍论证 | CS/rank bit 放 512B 以上；若放更高（如 4KB）会怎样？ | §2.2 | 取舍论证 | 待讨论 | |
| 2-I-01 | 面试 | stride=4KB workload，不用 simulation 判断落在哪些 bank/BG | §2.3 | 待讨论 | 待讨论 | |
| 2-I-02 | 面试 | sequential traffic 一定要追求 row hit？何时 BLP 更重要、宁可牺牲 row hit？ | §2.3 | 待讨论 | 待讨论 | |
| 2-I-03 | 面试 | workload 完全 random 时地址 mapping 还重要吗？ | §2 | 待讨论 | 待讨论 | |
| 2-I-04 | 面试 | rank/channel/bank bit 放高位 vs 低位对 locality 与 parallelism 的影响 | §2.2 | 待讨论 | 待讨论 | |
| 2-I-05 | 面试 | Rank 是 capacity first，为何双 rank benchmark 有时反而比 single rank 快？ | §2.x | 待讨论 | 待讨论 | |
| 2-Q-01 | 量化 | stride sweep 64B→MB：row hit / row conflict / bank entropy / BG entropy / BW | §2.3 | 量化缺口 | 待讨论 | |
| 2-Q-02 | 量化 | 4~8 commands/bank 最优点 sweep 1/2/4/8/16/32 | §2.x | 量化缺口 | 待讨论 | |
| 2-Q-03 | 量化 | Rank switching 损失多少有效带宽？什么 traffic 下 dual-rank 反超 single-rank？ | §2.5 | 量化缺口 | 待讨论 | |

---

## 第 3 章：Request Queue

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 3-P0-01 | 协议事实 | "HBM 不支持 mask write，partial write 必须 RMW"——是 HBM 协议本身 / 特定 ECC mode / 本 IP 未实现 / 产品配置？必须精准表述 | §3.5.1 | 协议事实 | 待讨论 | 注（来自 1-P0-05）：CHI PtlWrite 借 datachunk 可发 mask write——是否 mask write 是 DRAM/系统维度而非接口协议维度，本题讨论时与此对照 |
| 3-P0-02 | 协议事实 | WAW merge 后两个原始 write 各自的 BRESP 何时产生？后者覆盖前者 byte 时前者的 architectural completion 如何定义？ | §3.5.2 | 协议事实 | 待讨论 | |
| 3-P1-03 | 协议事实 | RMW 的 read 与 write 之间如何阻止第三个同地址 request 插入破坏原子性？ | §3.5.1 | 协议事实 | 待讨论 | |
| 3-P0-04 | 内部矛盾 | "CAM64 burst 后等效 256 commands"是 storage capacity 等效还是 scheduler visibility 等效？ | §3.2.2 | 术语歧义 | 待讨论 | |
| 3-P1-05 | 内部自洽 | CAM entry 内 4 commands 独立 issue，但共享 priority/aging/credit/entry lifetime——到底有多独立？ | §3.2.2 | 取舍论证 | 待讨论 | 注（来自 1-P0-12）：link node 数按"平均每 entry 2 条命令"折算——entry 装载分布是两题共同变量 |
| 3-P1-06 | 内部自洽 | Credit 按 entry 消耗但 entry 有 1~4 command，不同 request pattern 获得的 command capacity 是否不公平？ | §3.4 | 取舍论证 | 待讨论 | |
| 3-P1-07 | 内部自洽 | "广义 outstanding = XMU ostd + CAM depth"量纲不同（txn vs entry），真正想表达的指标是什么？ | §3.x | 术语歧义 | 待讨论 | |
| 3-P1-08 | 取舍论证 | incoming conflict 为什么 Pending 在 CAM 入口阻塞后续所有 command，而不允许无冲突后续 bypass？（HOL vs complexity） | §3.x | 取舍论证 | 待讨论 | 注（来自 1-P0-02）：阻塞发生在 PA→CQ 单通路 + 入口 buffer，结构性保证后续命令顺序——"不允许 bypass"与此同源，讨论时可直接引用 |
| 3-P1-09 | 取舍论证 | WAW 选择 merge，RAW/WAR 为何不做 forwarding/merge？ | §3.5 | 取舍论证 | 待讨论 | |
| 3-P1-10 | 取舍论证 | CAM 深度增加的收益：bank parallelism / row hit opportunity / priority visibility 谁最主要？ | §3.2.2 | 取舍论证 | 待讨论 | |
| 3-P1-11 | 内部自洽 | 分拍 conflict detection 对 correctness 没问题，但对 latency/throughput 的具体影响？ | §3.x | 量化缺口 | 待讨论 | |
| 3-I-01 | 面试 | CAM64 与 CAM32 在 random traffic 下性能为何不同？ | §3.2.2 | 待讨论 | 待讨论 | |
| 3-I-02 | 面试 | CAM 64→128 何时性能几乎不再提高？ | §3.2.2 | 待讨论 | 待讨论 | |
| 3-I-03 | 面试 | 为什么不用 per-bank queue 而用 global CAM？ | §3.2 | 待讨论 | 待讨论 | |
| 3-I-04 | 面试 | CAM burst 里第 1 条 command 卡 timing，第 2~4 条能否独立 bypass？ | §3.2.2 | 待讨论 | 待讨论 | |
| 3-I-05 | 面试 | RMW 密集 workload 为什么容易性能崩？ | §3.5.1 | 待讨论 | 待讨论 | |
| 3-Q-01 | 量化 | CAM depth sweep 16/32/64/96/128 对 BW / P99 / area / timing | §3.2.2 | 量化缺口 | 待讨论 | |
| 3-Q-02 | 量化 | CAM burst packing rate 在真实 workload 中是多少？ | §3.2.2 | 量化缺口 | 待讨论 | |
| 3-Q-03 | 量化 | HOL Pending 导致多少 cycle loss？ | §3.x | 量化缺口 | 待讨论 | |
| 3-Q-04 | 量化 | RMW ratio 0%~100% 对 BW 的曲线 | §3.5.1 | 量化缺口 | 待讨论 | |

---

## 第 4 章：Command Queue / CCT

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 4-P1-01 | 协议事实 | FR-FCFS 是算法准确命名吗？已含 QoS/aging/page-hit-first/CCT admission，是否应称"FR-FCFS-derived policy"？ | §4.x | 术语歧义 | 待讨论 | |
| 4-P0-02 | 协议事实 | Refresh postpone "postpone 9 次/连续补刷 8 次"的具体协议定义、计数口径、数学关系 | §4.6 | 协议事实 | 待讨论 | |
| 4-P0-03 | 内部矛盾 | §4.2 "HPR miss > LPR hit" 与 §4.3 "page hit 全局最高"哪句是总规则？ | §4.2 vs §4.3 | 内部矛盾 | 待讨论 | 预判：两种可配置模式，表述歧义非矛盾 |
| 4-P0-04 | 内部矛盾 | CCT 上表后不可撤回 + expired GPR 有确定等待上界——bank CCT 被 timing-blocked candidate 长期占据时 expired GPR 怎么办？ | §4.4 | 内部矛盾 | 待讨论 | |
| 4-P0-05 | 内部矛盾 | §4.8 把 bank open/closed、R/W direction、refresh debt 列为 CQ 状态，但 owner 分别是 BSC/GSC/Refresh manager——CQ 是拥有还是观察？ | §4.8 | 术语歧义 | 待讨论 | |
| 4-P1-06 | 内部自洽 | "miss 在 tCCD gap 发 ACT 因此不会饿死"是 performance tendency 还是 correctness guarantee？ | §4.x | 术语歧义 | 待讨论 | |
| 4-P1-07 | 取舍论证 | 为什么每 bank 只提名 1 条 CCT candidate，不是 2 条？ | §4.x | 取舍论证 | 待讨论 | |
| 4-P1-08 | 取舍论证 | CCT 上表后不可撤回，换来 timing/area/verification 中的什么？代价是什么？ | §4.4 | 取舍论证 | 待讨论 | |
| 4-P1-09 | 取舍论证 | Page-hit-first 对平均 BW 有利，对 P99 latency 伤害多大？ | §4.3 | 量化缺口 | 待讨论 | |
| 4-P1-10 | 取舍论证 | 为何 close-page 是"多数场景"而非 adaptive page policy？ | §4.x | 取舍论证 | 待讨论 | |
| 4-I-01 | 面试 | FR-FCFS 最大的问题是什么？ | §4.3 | 待讨论 | 待讨论 | |
| 4-I-02 | 面试 | 一直有 row hit request 时，row miss 如何保证 progress？ | §4.3 | 待讨论 | 待讨论 | |
| 4-I-03 | 面试 | QoS priority 与 row-hit efficiency 冲突时如何决定？ | §4.2/4.3 | 待讨论 | 待讨论 | |
| 4-I-04 | 面试 | Open/close-page 应由 software 静态配置还是 hardware adaptive？ | §4.x | 待讨论 | 待讨论 | |
| 4-I-05 | 面试 | 为什么 scheduler 不承担长期 bandwidth guarantee？ | §4.x | 待讨论 | 待讨论 | |
| 4-Q-01 | 量化 | RowHitRate→BW 与 RowHitRate→P99 两张曲线 | §4.3 | 量化缺口 | 待讨论 | |
| 4-Q-02 | 量化 | priority-first vs page-hit-first 的 BW/avg latency/P99/starvation time 对比 | §4.2/4.3 | 量化缺口 | 待讨论 | |
| 4-Q-03 | 量化 | Refresh postpone depth 对 BW/max latency spike 的关系 | §4.6 | 量化缺口 | 待讨论 | |

---

## 第 5 章：Command Scheduler / BSC-GSC-FSC

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 5-P0-01 | 协议事实 | tRCDWR < tRCD 产生 ACTIVE_WR 的关系适用于哪些协议/速度档？能否作为通用架构描述？ | §5.x | 协议事实 | 待讨论 | |
| 5-P0-02 | 协议事实 | counter 命名如何严格区分 same BG / different BG / tCCD_L/S / tRRD_L/S？第 5、6 章是否完全一致？ | §5.3 vs §6.2.1 | 术语歧义 | 待讨论 | |
| 5-P1-03 | 协议事实 | "HBM row/col 独立可同拍发 row+col"需要哪些附加条件？是否任何 row+col 都能同拍？ | §5.x | 协议事实 | 待讨论 | |
| 5-P0-04 | 内部矛盾 | FORCE_PRE 定义"不可被业务抢占"，状态表却允许"col 下发 → WRA_RDA"。真实 RTL 行为是哪个？ | §5.3.3 | 内部矛盾 | 待讨论 | 预判：疑似状态表誊写错误，需回溯 RTL |
| 5-P0-05 | 内部矛盾 | CCT 上是所有"可以发送"的命令，但 BSC 还要判断能不能发——CCT 应叫 eligible candidate 还是 executable command？ | §5.1/5.3 | 术语歧义 | 待讨论 | |
| 5-P0-06 | 内部矛盾 | "Read 恒优先于 Write"与 GSC write critical/high watermark/expired write 触发方向切换是否冲突？应叫 default preference 还是 absolute priority？ | §5.4 | 术语歧义 | 待讨论 | |
| 5-P1-07 | 内部自洽 | "ACT > PRE 因 ACT 有真实需求"——row conflict 的 next request 需要 PRE 才能 ACT，PRE 低于别的 ACT 是否拉长 critical bank latency？ | §5.3 | 取舍论证 | 待讨论 | |
| 5-P1-08 | 取舍论证 | 渐进式 R/W switch 隐藏 tRCD 的前提（对侧早可见、bank 可提前 ACT、CA 空档、tRRD/tFAW 允许、无 row conflict）是否都满足？ | §5.4.2 | 取舍论证 | 待讨论 | |
| 5-P1-09 | 取舍论证 | "切换只剩 tWTR/tRTW"是 best case 还是 average case？ | §5.4.2 | 术语歧义 | 待讨论 | |
| 5-P1-10 | 取舍论证 | GSC 用"执行时间配额"而非 command count / byte count / queue depth 的原因 | §5.4 | 取舍论证 | 待讨论 | |
| 5-P1-11 | 内部自洽 | FSC Col > Row 是否可能过度压制 ACT，造成未来 column starvation？ | §5.x | 取舍论证 | 待讨论 | |
| 5-I-01 | 面试 | 为什么 R/W switching 是 DRAM controller 最大性能损失之一？ | §5.4 | 待讨论 | 待讨论 | |
| 5-I-02 | 面试 | read batch / write batch 长度如何确定？ | §5.4 | 待讨论 | 待讨论 | |
| 5-I-03 | 面试 | 90% read + 10% write 时如何防止 write starvation？ | §5.4 | 待讨论 | 待讨论 | |
| 5-I-04 | 面试 | Column 总是优先会不会把 ACT 饿死？ | §5.x | 待讨论 | 待讨论 | |
| 5-I-05 | 面试 | 为什么 BSC timing eligibility 与 CQ scheduling policy 要拆开？ | §5.1 | 待讨论 | 待讨论 | |
| 5-I-06 | 面试 | HBM 同拍 row+col 的收益上限是多少？ | §5.x | 量化缺口 | 待讨论 | |
| 5-Q-01 | 量化 | BW_loss,RW 到底是多少？ | §5.4 | 量化缺口 | 待讨论 | |
| 5-Q-02 | 量化 | T_switch = T_turnaround + T_unhidden-row-preparation 能否拆分？ | §5.4 | 量化缺口 | 待讨论 | |
| 5-Q-03 | 量化 | 不同 GSC threshold 对 BW / read latency / write latency / switch count/sec 的曲线 | §5.4 | 量化缺口 | 待讨论 | |
| 5-Q-04 | 量化 | FSC no-command-issued 每 cycle 原因占比：timing / wrong direction / refresh / no candidate / scheduler choice（F 类阻塞分类） | §5.x | 量化缺口 | 待讨论 | |

---

## 第 6 章：Timing Enforcement

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 6-P0-01 | 内部矛盾 | per-bank counter 清单数量与 "64×14=896" 是否一致？重新数一次（我预数 down 15 项 + inline 2 项 = 17，且 tRFCpb/tRRD 层级归属存疑） | §6.2.1 | 笔误 | 待讨论 | |
| 6-P0-02 | 协议事实 | tRRDs/tCCDs 后缀在表中写成"同 BG"，内部命名与 JEDEC _S/_L 语义是否相反？ | §6.2.1 | 术语歧义 | 待讨论 | |
| 6-P0-03 | 协议事实 | ns→cycle 一律 ceil：minimum timing / maximum timing / refresh deadline 三种约束是否都应 ceil？ | §6.x | 协议事实 | 待讨论 | |
| 6-P1-04 | 协议事实 | HBM4 的 bank/BG/SID/rank timing 层级是否全部确实存在？哪些只是统一 RTL 架构保留的抽象层？ | §6.2.1 | 协议事实 | 待讨论 | |
| 6-P0-05 | 内部矛盾 | "≈1017 counters"是 synthesis 真实 register count / timing item count / logical counter count 哪一种？ | §6.2.1/6.2.2 | 术语歧义 | 待讨论 | |
| 6-P1-06 | 内部自洽 | tFAW 4 counter 算数量时为何写成 8？除 4 counters 还有哪些状态？ | §6.2.1 | 术语歧义 | 待讨论 | |
| 6-P1-07 | 内部自洽 | BSC "检查复杂度 O(1)"指与 CAM depth 无关，还是严格算法复杂度意义？ | §6.1 | 术语歧义 | 待讨论 | |
| 6-P1-08 | 取舍论证 | 集中时间戳一定面积更大吗？bank 数极多时 distributed counter replication 是否可能反而更贵？ | §6.3 | 取舍论证 | 待讨论 | |
| 6-P1-09 | 取舍论证 | "分布式全胜"是否应改为特定 PPA 条件下的选择？ | §6.3 | 术语歧义 | 待讨论 | |
| 6-P1-10 | 取舍论证 | Counter 用 down-count 还是 elapsed-time compare？哪种更利于 DVFS / clock gating / timing update？ | §6.2.2 | 取舍论证 | 待讨论 | |
| 6-I-01 | 面试 | 为什么不用一个 global cycle counter + timestamp？ | §6.3 | 待讨论 | 待讨论 | |
| 6-I-02 | 面试 | tFAW rolling window 如何实现？边界 cycle 如何保证 off-by-one 不出错？ | §6.2.2 | 待讨论 | 待讨论 | |
| 6-I-03 | 面试 | 两个 constraint 同时限制同一 ACT（tRRD+tFAW），ready 如何生成？ | §6.2 | 待讨论 | 待讨论 | |
| 6-I-04 | 面试 | timing register 运行中被 software 修改会发生什么？ | §6.x | 待讨论 | 待讨论 | |
| 6-I-05 | 面试 | DVFS 为什么要求 idle？"idle"的严格定义？ | §6.4 | 待讨论 | 待讨论 | |
| 6-Q-01 | 量化 | "counter 占 scheduler 40% area"能否按 bank/BG/rank/SID/window 拆分？ | §6.2.2/6.2.3 | 量化缺口 | 待讨论 | |
| 6-Q-02 | 量化 | 性能损失 timing blocker Top 5（tCCD/tRCD/tRRD+tFAW/tWTR+tRTW/tRFC）各占多少 idle cycle？ | §6.x | 量化缺口 | 待讨论 | |
| 6-Q-03 | 量化 | timing-1→blocked / timing→allowed 边界验证统计 | §6.x | 量化缺口 | 待讨论 | |

---

## 第 7 章：DFI（主文档章号误写为 9）

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| 7-P0-01 | 协议事实 | ratio4/ratio8 是 DFI standard terminology 还是 IP 内部 shorthand？ | §DFI | 协议事实 | 待讨论 | |
| 7-P0-02 | 协议事实 | DFI:CK:WCK = 1:2:4 / 1:4:8 对哪些协议/模式成立？能否作通用 DFI ratio 定义？ | §DFI | 协议事实 | 待讨论 | |
| 7-P0-03 | 协议事实 | "init/training 由 PHY 主导，controller 不驱动序列"对所有 training type 成立？哪些由 PHY/MC/firmware 分别负责？ | §DFI | 协议事实 | 待讨论 | |
| 7-P1-04 | 协议事实 | CA parity 是 controller 还是 PHY 计算？DFI 接口上的责任边界？ | §DFI | 协议事实 | 待讨论 | |
| 7-P1-05 | 协议事实 | Write CRC "增加 BL 方式传输"适用于哪些协议？勿跨协议泛化 | §DFI | 协议事实 | 待讨论 | |
| 7-P0-06 | 内部矛盾 | Low power "全链路排空"定义 XMU req==resp + CAM empty，但 BRESP 提前返回——req==resp 为何能说明 backend write 已排空？ | §DFI(9.3.2) | 内部矛盾 | 待讨论 | 预判：真问题；drain 应为 CAM/WDP empty + DFI/PHY flight 空 |
| 7-P0-07 | 内部自洽 | 低功耗进入是否还需检查 CCT / PF window / WDP / RDP / DFI flight / PHY flight / bank FSM / refresh maintenance？ | §DFI(9.3.2) | 内部矛盾 | 待讨论 | |
| 7-P0-08 | 内部矛盾 | 第 4 章"DFI stall → freeze scheduler + PRE all"——DFI 已 stall，PRE all 从哪里发出去？ | §4.x vs §DFI | 内部矛盾 | 待讨论 | |
| 7-P1-09 | 协议事实 | "HBM 双 PC 奇偶 CK 分时"是协议结构还是具体 DFI packing 实现？ | §DFI | 协议事实 | 待讨论 | |
| 7-P1-10 | 取舍论证 | ratio 提高后为什么选"每拍多命令"而不是提高 controller frequency？ | §DFI | 取舍论证 | 待讨论 | |
| 7-P1-11 | 取舍论证 | PF window 为什么是 8 entries 不是 4/16？ | §DFI | 取舍论证 | 待讨论 | |
| 7-P1-12 | 取舍论证 | 为什么选 64 choose 2 → 8 choose 2 shadow window，而不是 CQ scheduler pipeline 多打一拍？ | §DFI | 取舍论证 | 待讨论 | |
| 7-P1-13 | 取舍论证 | DFI prefetch write-data buffer 增加多少 latency/area？command-data alignment 如何保证？ | §DFI | 取舍论证 | 待讨论 | |
| 7-I-01 | 面试 | 什么叫 DFI ratio？为什么 ratio 越高 controller 越难设计？ | §DFI | 待讨论 | 待讨论 | |
| 7-I-02 | 面试 | Controller 与 PHY 在 training 中各自负责什么？ | §DFI | 待讨论 | 待讨论 | |
| 7-I-03 | 面试 | 进入 self-refresh 前为什么一定要 drain？ | §DFI(9.3) | 待讨论 | 待讨论 | |
| 7-I-04 | 面试 | HBM PC 为什么能提高并行度但 command path 可能合流争用？ | §DFI | 待讨论 | 待讨论 | |
| 7-I-05 | 面试 | PF window 本质解决 throughput、critical path 还是两者兼有？ | §DFI | 待讨论 | 待讨论 | |
| 7-Q-01 | 量化 | ratio4→ratio8：controller freq / command per cycle / area / power / BW efficiency 定量比较 | §DFI | 量化缺口 | 待讨论 | |
| 7-Q-02 | 量化 | 64选2→8选2 到底改善多少 critical path？ | §DFI | 量化缺口 | 待讨论 | |
| 7-Q-03 | 量化 | PF window miss/underfill 时有效 command rate 能掉到多少？ | §DFI | 量化缺口 | 待讨论 | |
| 7-Q-04 | 量化 | low power wake-up 对 P50/P99 memory latency 的贡献 | §DFI(9.3.3) | 量化缺口 | 待讨论 | |

---

## 跨章问题（Ordering / 状态 / QoS / RAS / 验证 / PPA）

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| X-P0-01 | Ordering | write 五时刻定义：accepted / committed / BRESP / DQ transferred / DRAM architecturally complete，分别在哪里？ | 全文 | 文档缺节 | 待讨论 | 注（来自 1-P0-02）：committed 与 architecturally complete 之间的数据序由颗粒保证，controller 责任止于命令下发序；注（来自 1-P0-03）：Ordering 责任五分类表已落 §1.4.4，五时刻总表仍待补 |
| X-P0-02 | Ordering | RAW/WAR/WAW/RMW/Exclusive 统一 dependency matrix | 全文 | 文档缺节 | 待讨论 | 注（来自 1-P0-02）：RAW/WAR 行的实现锚点已确认（入口 Pending + 冲突对象提权 + 下发放行，ID 无关） |
| X-P0-03 | 状态所有权 | 每个状态唯一 owner：open row / timing / priority / aging / R-W direction / refresh debt / credit / data ready / low power，目前多 owner 交叉 | 全文 | 文档缺节 | 待讨论 | 建议：主文档新增"全局状态 owner 表" |
| X-P0-04 | Idle/Drain | 四种 idle 定义：front-end idle / scheduler idle / memory-path drained / DRAM-safe idle，目前混用 | 全文 | 文档缺节 | 待讨论 | |
| X-P1-05 | QoS | QoS 完整层级（AXI QoS → port priority → port WRR → HPR/LPR/TPW/GPR → page-hit policy → aging → FSC）冲突时谁压谁？ | 全文 | 文档缺节 | 待讨论 | |
| X-P1-06 | Performance | Efficiency 统一定义：Effective DQ BW / Peak DQ BW？ | 全文 | 术语歧义 | 待讨论 | |
| X-P1-07 | Performance | 所有 BW loss 归一成互斥类别，总和=100% lost cycles | 全文 | 量化缺口 | 待讨论 | |
| X-P1-08 | RAS | RAS 是简历核心项目但文档几乎无 RAS architecture：CA parity / CRC / ECC / retry / rollback window / poison-error response 应补入面试主文档 | 全文 | 文档缺节 | 待讨论 | |
| X-P1-09 | Verification | 除 min-gap coverage 外，如何证明 ordering / no deadlock / no starvation / credit conservation / CAM-WDP ptr consistency / low-power drain correctness？ | 全文 | 文档缺节 | 待讨论 | |
| X-P1-10 | PPA | 每模块"砍 20% area 先砍哪里？" | 全文 | 待讨论 | 待讨论 | |
| X-P1-11 | PPA | frequency 提高 20%，第一条 critical path 在哪里？ | 全文 | 待讨论 | 待讨论 | |
| X-P2-12 | 架构能力 | 重新设计而非复述：最想推翻当前架构的哪三个设计？ | 全文 | 待讨论 | 待讨论 | |

---

## 讨论中发现的新增问题（按发现顺序追加）

| ID | 类别 | 问题摘要 | 文档位置 | 初判 | 状态 | 结论/回答记录 |
|---|---|---|---|---|---|---|
| N-01 | 文档结构 | 主文档 DFI 章标题写成 "# 9"，章节编号错位（9.3.x 实为 DFI 内容） | §DFI 章 | 笔误 | 待讨论 | |
| N-02 | 文档结构 | 第 1 章内 §1.5 的两个小节号误写为 "2.5.1 / 2.5.2"（AXI QoS 映射、PA 四层仲裁） | §1.5 | 笔误 | 待讨论 | |
| N-03 | — | （预留：讨论中追加） | | | 待讨论 | |

---

## 处理流程备忘

1. 每题固定流程：**定位原文 → 判定性质（笔误/术语歧义/协议事实错误/内部矛盾/取舍论证/量化缺口/文档缺节）→ 给出回答与面试话术 → 用户确认定稿**。
2. 每轮结束批量回写主文档；事实性修正直接改并在本表标 `已改文档`。
3. Q 类缺口在主文档对应章节插入"量化待补"小节，登记公式与所需实验数据，状态标 `需补数据`。
4. 文档缺节类（X-P0-01~04、X-P1-05、X-P1-08、X-P1-09）建议直接在主文档新增体系化小节（如 §0.7 全局状态 owner 表、Ordering 语义总表、四种 idle 定义）。





