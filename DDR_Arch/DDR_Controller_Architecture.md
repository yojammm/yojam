# DDR Memory Controller 架构文档

> **文档定位**：面向面试/技术晋升的个人架构知识库。以协议无关的通用架构为骨架，DDR4/5、LPDDR4/5、HBM3/4 的协议差异作为对比注解，核心能力目标是 **tradeoff 论证 + 量化分析**。
>
> **方法论**：每章先讨论透（提问 + 回答 + 辩论），达成共识后落笔成文。所有设计细节均来自真实 RTL 设计实战经验。

---

## 0. 全局架构总览

### 0.1 流水线架构树

```
Host / NoC
     ↓
AXI / CHI
     ↓
Transaction Layer
     ↓
Address Mapping
     ↓
Request Queue
     ↓
Command Scheduler  ← CQ：第 1 章 / CS：第 3 章
     ↓
Command Generator
     ↓
Timing Enforcement
     ↓
DFI
     ↓
PHY
     ↓
DRAM
```

> **模块边界注记（RTL 真实模块名）**：流水线中的 "Scheduler + Command Generator" 在 RTL 里对应顶层 **Command Scheduler** 模块，内部划分：
> - **CQ**（Command Queue）：CAM + 三层 filter（第 1 章内容）
> - **CS**：BSC（bank 状态机 + AC timing）/ GSC（读写切换）/ FSC（最终仲裁）（第 3 章内容）

### 0.2 一条命令的一生（开场叙事）

以 **LPDDR5 一个 512B 写事务**为例，走一遍全流水线：

```
AXI AW/W → XMU AFIFO（跨时钟域 + outstanding，一物两用）
 ① AW channel 按 64B 拆分 sub-command；W channel 按 64B resize 数据入 buffer
 ② PA grant：分配 CAM ptr + 地址映射（物理地址写入 CAM entry）
    同时 write response 推入 B outstanding FIFO（保序节点 = PA grant，见 1.4.2）
 ③ CQ 指示 WDP 从 XMU 取数 → WDP 写入 SRAM（地址与 CAM 一致）→ 写数据 ready
 ④ 命令经三层 filter 上 CCT → 无 hit → CS 生成 ACT → tRCD 满足 → 产生 WR 请求
 ⑤ FSC 调度 → 以 CS command body/type/id 发至 DFI → DFI 解析生成协议总线 → PHY
 ⑥ 临近 PhyWrLat 满足：DFI 持 ptr 向 WDP 取数 → SRAM 读出 + DBI/ECC → PHY
```

至此一条写命令的周期完成——注意 **response 在第 ② 步就已返回上游**，远早于数据真正写入 DRAM。

**读命令对照**：AR 拆分并在 reorder buffer 分配空间，link node ID 随命令下发 → 中间与写类似 → 命令在 DFI 总线发出后，DFI 收到读数据，**先入先出绑定命令信息**返回 RDP → RDP 处理 DBI/ECC → XMU 写入 SRAM → 按 ID 判断拆分/合并为 AXI RDATA → 返回上游。

**三条结构性观察（全局视角）**：
1. **保序点前移**：response ≠ 写入完成，AXI ID 承担顺序语义；
2. **命令流与数据流在 WDP/RDP 分合**：命令走窄通路（地址+属性），数据走宽通路（SRAM+DBI/ECC），仅以 ptr 关联；
3. **地址形态转换点在 CAM 入口**：上游全程 system/UIF 地址，物理地址只在 CAM entry 中存在。

### 0.3 时钟域与 CDC

| 时钟域 | 覆盖范围 |
|---|---|
| **AXI clk（= NoC clk）** | 上游接口侧 |
| **DFI clk（= Core clk）** | 控制器主体（CQ/CS/DFI） |
| **APB clk** | 寄存器配置通路 |
| PHY 内部 | 入口 DFI clk，出口 CK/WCK |

**CDC 处理**：
- AXI → DFI 的跨时钟域通常在 **XMU 的 outstanding AFIFO**——**一物两用：跨时钟域 FIFO 就是 outstanding buffer**；
- 变体场景（AXI 高频低位宽）：**写数据先在 AXI 域完成合并，再跨域**——此时 CDC 点移到 XMU-PA 之间；
- APB 为慢时钟配置域，寄存器写入用标准同步手段。

### 0.4 章节导航（阅读顺序与依赖）

| 章 | 一句话摘要 | 阅读依赖 |
|---|---|---|
| **1** AXI / XMU | 协议边界：拆分、保序返回、QoS 映射 | 入口 |
| **2** Address Mapping | 地址翻译：决定 hit 与并行的上限 | — |
| **3** Request Queue | 入队与缓冲：credit 流控、冲突处理 | 1 |
| **4** Command Queue | CAM 三层筛选：候选提名（能不能调） | 2, 3 |
| **5** Command Scheduler | BSC/GSC/FSC：时序过滤与仲裁（能不能发） | 4 |
| **6** Timing Enforcement | 五级 counter 体系：零违反保证 | 5 |
| **7** DFI | 控制器-PHY 交接面：ratio / 低功耗 / 协议差异 | 5, 6 |
| 8 / 9 / 附A | PHY（搁置）/ DRAM 颗粒 / 协议对比 | 待写 |

### 0.5 全局设计哲学（跨章反复出现的四个模式）

1. **批处理摊薄切换**：读写 batch（5.4）、refresh 见缝插针（4.6）、rank/SID 多命令再切（2.5）——切换代价是常量，batch 是唯一摊薄手段；
2. **迟滞防乒乓**：SidSwitch 空闲阈值（2.5）、水线 set/clr（3.4）、渐进式读写切换（5.4.2）——用时间迟滞换切换稳定性；
3. **结构性规避**：DVFS 保证 IDLE（6.4）、零旁路 counter 检查（6.1）、DEVMGR 退出顺序（7.3）——用系统级约束消解模块级难题；
4. **粒度统一 64B**：cache line = col command = CHI 包 = sub-command（1.2）——一条 64B 线贯穿全流水线。

### 0.6 每章统一模板（八问）

每一层必须能够回答：

1. 功能是什么？
2. 输入/输出是什么？
3. 状态是什么？
4. 性能瓶颈是什么？
5. 影响 bandwidth 的参数是什么？
6. 影响 latency 的参数是什么？
7. 和上下层怎么 backpressure？
8. 异常情况下怎么恢复？

---

# 1. AXI / XMU（协议边界与请求预处理）

## 1.1 职责与边界

**流水线位置**：Host/NoC 之后、Transaction Layer 之前。**XMU 是控制器的 AXI 协议边界**——AXI 语义在这里终结，DRAM 语义从这里开始。

**支持的协议**：
- **AXI**：完整支持；
- **CHI（可选）**：仅 **NoSnp** 命令——read / prefetch read / full write / partial write（见 1.6）。

**核心职责**：txn → sub-command 拆分、page hit 预判、读数据保序返回（reorder buffer）、outstanding 管理、QoS → 优先级映射、response 生成。

---

## 1.2 txn → sub-command 拆分

### 1.2.1 UIF 地址变换

```
System/AXI address（40bit）
        │  >> 6（64B / sub-command）
        ↓
UIF address（sub-command 地址）
```

每个 sub-command 固定 64B——**恰好与 DDR5/LPDDR5 的一条 col 命令、CHI 的一个包、一个 cache line 三者对齐**，这是全流水线粒度统一的锚点。

### 1.2.2 Page hit 判定：不需要知道 page 边界

**悖论**：CAM burst 的准入条件是"同 page"（3.3），但 page 大小要等第 1 章的地址映射才知道——而映射在 XMU 下游。

**解法**：

> 在 XMU 中只判断 **UIF address 除 col 位外是否全部相同**来判定 page hit——不需要显式计算 page 边界。

col 位宽是一个静态配置常量，"除 col 全同"与"同 page"严格等价，且比较在拆分现场即可完成。**这是把协议知识（page size）转化为位宽知识（col 位数）的典型手法。**

### 1.2.3 4KB 语义

拆分逻辑**不主动体现 4KB**；地址边界类的计算按 4KB 语义进行——例如**边界只看低 13bit**（4KB = 2^13）。

---

## 1.3 读数据返回：link list / link node 机制

### 1.3.1 机制描述（本章核心）

读方向乱序返回与保序由 **link list + link node** 两级结构实现：

```
AXI ID = A 的 sub-commands → link node 串成一条 link list（保序链）
AXI ID = B 的 sub-commands → 另一条 link list
...

分配规则：
  ① 同 AXI ID 的 link node 必须从属于同一条 link list
  ② 不同 AXI ID 优先分配空的 link list
  ③ link list 全被占用 → RR 分配一条
释放规则：
  ① 只有 link list head 的 link node 可释放（返回 AXI port）→ 同 ID 严格保序
  ② 某条 list 上所有 node 释放后，该 list 才可回收
  ③ 每个 cycle 只有一个读数据返回
```

效果：**不同 AXI ID 之间乱序交织（谁的数据先回谁先走），同 AXI ID 之间严格保序**——正是 AXI 协议要求的顺序语义。

### 1.3.2 配置公式（经验值）

| 参数 | 含义 | 典型值 |
|---|---|---|
| **link list 数** | interleave 粒度：多少个 txn 可以交织 | 32 |
| **link node 数** | 允许的 outstanding sub-command 数 = **reorder buffer 深度** | link list + CAM depth × 2 |

link list 与 link node 个数均独立可配。node 数公式里"CAM depth × 2"的含义：CAM 里在读的命令 + 飞行在 PHY/数据通路上的一半余量。

---

## 1.4 Outstanding 管理

### 1.4.1 深度定标哲学

- AR/AW/W 的 ostd 深度**相互独立**；
- 定标依据：**上游系统特征**——burst 大小、master 到 slave 的路径延迟、面积取舍；

- **"outstanding 设置过大也没有用，过大的 outstanding 会增加单个 txn 的 latency"**——并行度饱和后，更多的 ostd 只是拉长每笔命令在 buffer 里的排队。

### 1.4.2 保序节点 = PA grant（本设计的点睛之笔）

> **sub-command 被 PA grant 后即到达保序节点，这个时刻就可以回 response。**

- write response 在 **PA grant + 数据到达 XMU** 即返回（3.5.2），**不等到写进 DRAM**；
- AXI ID 的作用就是维护顺序：**上游 master 认定"不同方向、同地址的 response 顺序 = 命令执行顺序"**；
- 把保序点尽量前移，是读延迟之外的另一个端到端延迟收益来源。

### 1.4.3 明确的取舍：不做超时防死锁

AW/W 数据不同步到达的场景**没有设计超时/死锁防护**——理由：如果数据不来，**master 侧一定可以感知**（它自己的 outstanding/超时机制兜底）。controller 不重复造防护，是边界清晰的表现。

---

## 1.5 QoS 映射与 PA 分层仲裁

### 2.5.1 AXI QoS → 优先级队列

| 方向 | 机制 | 映射目标 |
|---|---|---|
| **读** | AXI QoS 0~15，**两个 regionField 寄存器分三段 + 三个 regionMap 寄存器** | LPR / GPR / HPR |
| **写** | 类似 regionField 机制，**只分两段** | TPW / GPW |

QoS 值到队列的映射是**软件可配的分段线性映射**——不是硬连线，也不是按值逐档。

### 2.5.2 PA 四层仲裁

```
第 1 层：读写方向仲裁
第 2 层：优先级仲裁        ← expired HPR / GPW、port aging
第 3 层：port priority 仲裁 ← AXI QoS 或 port aging priority
第 4 层：RR（轮询）
```

与 4.5.1 呼应：**port 仲裁是 QoS 的第一级，CAM 内 aging 是最后一级**——两级 aging（port 级 + CAM 级）分别守护"port 饥饿"和"命令饥饿"。

---

## 1.6 CHI 支持范围

- 仅 **NoSnp** 命令：read / prefetch read / full write / partial write；
- **"AXI 和 CHI 没有核心差异，只是 CHI 每个包最大只有 64B"**——恰好等于 1 个 sub-command，拆分逻辑天然对齐，无需额外适配；
- snoop/DVM 类一致性流量由上游（interconnect/代理）处理，不在 controller 视野内。

---

## 1.7 八问速答表（AXI / XMU）

| 问题 | 答案 |
|---|---|
| **功能** | AXI 协议边界：txn 拆分（UIF）、page hit 预判、读数据保序返回、outstanding 管理、QoS 映射、response 生成 |
| **输入/输出** | 入：多 port AXI AW/W/AR（或 CHI NoSnp）；出：64B sub-command 流（UIF 地址）+ 读数据返回 + response |
| **状态** | link list/node 占用、ostd 计数、regionField/regionMap 配置 |
| **性能瓶颈** | 每拍一个读数据返回；ostd/link node 深度限制并行度；同 ID 链的保序阻塞 |
| **BW 参数** | ostd 深度、link node 数（= reorder buffer 深度）、link list 数（interleave 粒度） |
| **Latency 参数** | ostd 深度（过大反增单 txn latency）、保序点位置（PA grant 前移是收益） |
| **Backpressure** | ostd 满 / link node 耗尽 → 反压 AXI ready；credit 满 → PA 停止仲裁（见 3.4） |
| **异常恢复** | link list 随 head 释放逐级回收、list 全空回收；response 错误状态通路见 RAS 章 |


---

## 1.8 Exclusive 与 RMW

- **RMW**：HBM partial write 在 XMU 转换为 RMW 命令（准入与调度语义见 3.1、3.5.3——RMW 不参与 WAW merge，只能尽快 flush 前序 write）；
- **Exclusive**：AXI exclusive 读/写的地址监视（monitor）与 EXOKAY/OKAY 响应判定在 XMU 中完成，上游缓存依此维护独占状态。

*（exclusive monitor 实现细节与 RMW 上层语义的展开：待补充）*

---

## 1.9 本章金句存档

> 1. "保序节点 = PA grant：sub-command 一被 grant 就可以回 response。"
> 2. "Outstanding 设置过大也没有用，过大的 outstanding 会增加单个 txn 的 latency。"
> 3. "Page hit 在 XMU 只判断除 col 位外 UIF address 是否相同——不需要显式计算 page 边界。"
> 4. "AXI 和 CHI 没有核心差异，只是 CHI 每个包最大只有 64B——恰好等于一个 sub-command。"

**本章术语表**：

| 术语 | 定义 |
|---|---|
| **UIF address** | sub-command 地址 = system address >> 6（64B 粒度），XMU 及下游统一使用 |
| **sub-command** | 64B 的命令切片，全流水线统一粒度（= 1 col command = 1 cache line = 1 CHI 包） |
| **link list / link node** | 读数据保序结构：每 sub-command 一个 node，同 AXI ID 同 list；head 可释放实现保序，list 间乱序实现交织 |
| **reorder buffer** | 读数据返回缓冲，深度 = link node 数 |
| **regionField / regionMap** | QoS 值分段寄存器组：读方向三段→LPR/GPR/HPR，写方向两段→TPW/GPW |
| **保序节点** | PA grant 时刻：此后命令顺序即对外承诺的执行顺序，response 可由此生成 |
| **GPW** | Guaranteed Priority Write：写侧 GPR（与 TPW 同队列，超时晋升，见 4.2） |
| **NoSnp** | CHI 无 snoop 事务类别，controller 仅支持该类（read/prefetch read/full write/partial write） |

**下一章建议**：第 1 章 Address Mapping（地址映射——sub-command 的物理地址形态由此产生），或第 1 章 Timing Enforcement（BSC 计数器体系的深挖）。


---

# 2. Address Mapping（地址映射）

## 2.1 职责与边界

**职责**：把系统物理地址翻译为 DRAM 侧的 rank/BG/BA/row/col 字段，决定"哪个请求落在哪个 bank"——**它决定了 Scheduler 的 hit rate 上限和 bank 并行度上限**（4.3 的"hit rate 是策略选择的唯一关键统计量"，源头在这里）。

**边界（三层归属）**：

| 层 | 归属 | 说明 |
|---|---|---|
| **Channel** | **SoC 系统**（不在控制器内） | 每个 channel 一个独立 CTRL core，channel 间地址分配由 SoC 完成 |
| **Rank/BG/BA/Row/Col** | 控制器（**寄存器可配置**） | 本章主体 |
| **HBM PC / DDR5 sub-channel** | 协议钉死 / 独立 core（见 2.7） | 自由度极小 |

**配置约束**：映射序虽可配，但**必须按实际颗粒容量配置**——容量决定各字段的真实位宽，配错会产生非法地址（见 2.6 空洞交换）。

---

## 2.2 整体最优映射序

### 2.2.1 推荐配置（perf 验证结论）

> **{row, cs, ba, col, bg, col}**（MSB → LSB），即 LSB 方向为：col[2:0] → bg → ba → col[5:3] → cs → row

```
地址位（LSB → MSB）：

 col[2:0] │  bg  │  ba  │ col[5:3] │  cs  │  row
──────────┴──────┴──────┴──────────┴──────┴──────
  8B 粒度   BG 交织  BA 交织  64B 命令序号  512B   page
```

- **BG/BA 交织位插在 col 中段**：顺序流访问时，连续 64B col 命令轮流落到不同 BG/BA，**每个 bank 内部保持 col 连续 → 全部 page hit**；
- **每个 BA 摊到 4 或 8 条命令**（256B/512B）——足够用 page hit 摊薄 ACT，又不至于在单 bank 排队过久；
- DDR5/LPDDR5 下 64B = 一条 col 命令（BL16/BL32），位序与 cache line 自然对齐。

### 2.2.2 鲁棒性论证（答辩要点）

**col 低位在 ba 之下、row 在最高位**，带来一个结构性保证：

- 任何 **< page size 的 stride**：落在单 bank 内形成连续 col → row hit；
- 跨越 bank 区域的 stride：自动轮转 BG/BA → bank 并行；
- **不存在"同 bank 换 row"的常规 stride 配置**——即不会出现全 row miss。

对照经典 RCB（row 放低位）映射：它优化随机负载的 row 局部性，但顺序流会在同一 bank 换 row。本设计以 **BG/BA 中段交织**同时吃到顺序流的 hit 和并行，是 random + linear 双负载下的**整体最优**（见 2.4 的验证方法）。

**遗留项确认（已关闭）**：UIF 地址低位映射为 col/ba、高位为 row；AXI txn 内地址**连续递增**——低位（col/ba）先变化，因此不会出现"col/ba 不变、仅 row 递增"的同 bank 换 row 访问形态，stride 担忧不存在。

---

## 2.3 交织粒度：并行度 vs 每 bank hit 数

**BG/BA 交织位的摆放本质是一个分配旋钮**：决定一个大 transaction 的命令如何在"更多 bank"和"单 bank 更多 hit"之间分配。

| 场景 | 策略 | 原因 |
|---|---|---|
| **256B txn**（4 条命令） | 不需要 BG 交织，BG 随机分配 | 命令数量少，拆分收益 < 管理代价 |
| **512B txn**（8 条命令） | 拆 2 个 BG，**bg 放 addr[3]** 这类中段位置 | 8 条命令足够摊两个 BG 的 ACT，且 BG 间可 tCCD_S 背靠背 |
| **BG 位放太低** | ❌ | 大 txn 被拆到太多 bank，**单 bank 内 page hit 数不足**，白付 ACT |
| **BG 位放太高** | ❌ | 退化为 bank 集中访问，BG 并行度浪费（纯 FCFS 式的串行暴露） |

**判断口诀**：每 bank 4~8 条命令（256B~512B）是 hit 摊薄 ACT 的下限——**低于它，并行度换不来收益；高于它，单 bank 排队吃掉并行优势**。


---

## 2.4 量化验证方法

改一版映射，怎么确认它更好——**两个硬指标 + 一个 pattern 纪律**：

| 指标 | 含义 | 达标特征 |
|---|---|---|
| **Page hit rate** | col 命令命中已开 row 的比例 | 顺序流接近满 hit；random 流达到该负载理论上限 |
| **tCCD_S 满足占比** | col 背靠背落在不同 BG（可用短 tCCD_S）的比例 | 越高说明 BG 交织把"BG 间便宜切换"用满了；反之大量命令被 tCCD_L 阻塞 |

**Pattern 纪律**：perf 验证必须覆盖 **random + linear 两类、64B~512B 粒度**的 pattern，且**一套映射同时服务两类负载**——只跑 linear 会选出偏科配置（比如 BG 位放太高）。{row, cs, ba, col, bg, col} 正是在这个纪律下得出的整体最优解。

> 答辩提示：面试官问"映射怎么调优"时，先报指标和 pattern 集合，再报结论——这比直接背映射序高一个层级。

---

## 2.5 Rank / SID 架构哲学

### 2.5.1 Rank：为容量而生，不为性能

> **"多 rank 的效率是低于单 rank 系统的，rank 是为了容量而不是性能。"**

- rank 间 AC timing（rank 切换开销）**大于** rank 内 → **一个 transaction 不拆到 2 个 rank**；
- 正确姿势：**在一个 rank 内连续执行多条命令，再切到下一个 rank**（与读写批处理 4.5、SID 空闲阈值同属"摊薄切换代价"思想）；
- cs 位放在 col[5:3] 之上（512B 粒度）与此一致：顺序流在 rank 内形成连续段，rank 切换频率被压到最低。

### 2.5.2 HBM SID 防乒乓（SidSwitch 寄存器）

多 stack HBM 中，跨 SID 切换的代价与 rank 切换同类。**SidSwitch 寄存器**（如设为 4）：

```
当前 SID 连续 4 cycle 无命令 → 才允许切换到另一个 SID
当前 SID 只是断了一拍 → 不切换，继续等待
```

**动机**：防止"当前 SID 断一拍 → 立刻切走 → 下一拍又切回"的乒乓切换——每次切换都付完整代价，性能被切换开销吃光。**用时间迟滞换切换稳定性**，与 write drain 的迟滞思想同构。

---

## 2.6 非 2 进制容量的空洞交换（独家细节）

**问题**：颗粒容量非 2 的幂（如 6GB）时，逻辑地址存在永不出现的组合（如 row[14:13]=11）；若这些位不在物理 row 字段最高位，位拼接后会产生**非法物理地址**。

**解法**：**地址位交换**——当 row[14:13]=11 时，与更高位交换，保证：

1. 逻辑地址空间连续（软件看到平坦的内存）；
2. 永不映射到不存在的物理位置。

> 这类"容量洞"处理是控制器映射模块容易被忽略的隐含职责——面试聊到"映射可配"时主动提这一条，能体现真实设计经验。

---

## 2.7 协议差异：钉死的位与 core 拓扑

| 协议 | 地址位自由度 | core 拓扑 |
|---|---|---|
| **HBM** | **PC 位固定在最高位**（类似 channel 位），其余字段协议 pin 定义约束大 | **1 channel = 2 PC，每 PC 一个独立 core**，仅在 **DFI-PHY 处把两 PC 命令合并到同一 DFI 总线** |
| **DDR5** | sub-channel 交织由协议定（32B 粒度） | **每 sub-channel 一个 CTRL core**（每 DIMM 双 sub-channel = 双 core） |
| **LPDDR5** | channel 间由 SoC 分配 | 每 channel 独立 core |
| **DDR4** | rank/BG/BA/row/col 全部可配 | 每 channel 独立 core |

> **架构差异总结**：越新的协议，地址位被协议"钉死"得越多（HBM PC 位、DDR5 sub-channel）——映射的自由度在向 core 拓扑转移：**老协议靠映射换性能，新协议靠多 core 并行换性能**。

---

## 2.8 八问速答表（Address Mapping）

| 问题 | 答案 |
|---|---|
| **功能** | 物理地址 → rank/BG/BA/row/col 字段翻译；决定 hit rate 与 bank 并行度的上限 |
| **输入/输出** | 入：系统物理地址、映射配置寄存器；出：DRAM 字段地址（供 CQ/CAM 使用） |
| **状态** | 无时序状态（纯组合译码）；配置寄存器即全部"状态" |
| **性能瓶颈** | 不占流水线时序瓶颈；但它决定了下游所有并行度/hit 的天花板——**瓶颈在配置错误，不在电路** |
| **BW 参数** | BG/BA 交织位摆放、每 bank 命令数（4~8）、cs 位位置、PC/sub-channel 拓扑 |
| **Latency 参数** | hit rate（决定 tRCD/tRP 暴露次数）、非 2 进制容量的交换逻辑（若做成时序级需注意） |
| **Backpressure** | 无直接反压关系（纯译码）；间接：映射差 → hit 低 → CAM 膨胀 → 反压上游 |
| **异常恢复** | 空洞交换保证非法容量组合不产生非法地址；配置错误属 DFT/验证范畴 |

---

## 2.9 本章金句存档

> 1. "ba 位以下是 col 位而不是 row 位——不会出现全 row miss 的配置。"
> 2. "多 rank 的效率低于单 rank 系统，rank 是为了容量而不是性能。"
> 3. "BG 位放太低，大 txn 被拆到很多 bank，page hit 数量不足。"
> 4. "老协议靠映射换性能，新协议靠多 core 并行换性能。"

**本章术语表**：

| 术语 | 定义 |
|---|---|
| **BG/BA 交织位** | 插在 col 中段的地址位，控制顺序流向 bank/BG 的摊开粒度 |
| **bank 区域大小** | ba 位以下决定的、单 bank 连续 col 的跨度（本配置 512B） |
| **空洞交换** | 非 2 进制容量下，非法地址位组合与高位的交换逻辑 |
| **tCCD_S 满足占比** | col 背靠背命中不同 BG（短 tCCD_S）的比例，BG 交织有效性的度量 |
| **SidSwitch** | HBM 多 stack 的 SID 切换迟滞寄存器：当前 SID 空闲 N 拍才允许切换 |
| **PC (Pseudo Channel)** | HBM 内部独立的半独立通道，地址位钉死在最高位，双 PC 独立 core、DFI 处合流 |


---

# 3. Request Queue（XMU → PA → CQ 入口）

## 3.1 拓扑与职责

命令进入 CAM 之前的完整通路：

```
AXI ports（多 master）
   ↓
XMU (AXI Manager Unit)
   ├─ outstanding buffer：满则反压 AXI（与 CAM 独立管理）
   ├─ 读方向 reorder buffer：为读数据返回预留（详见第 1 章 AXI）
   └─ 协议预处理：AW/W 数据汇聚、mask write 判断、
      HBM partial write → RMW 转换
   ↓
PA (Port 仲裁)
   ├─ 优先级 RR + per-port 权重（QoS 第一级，见 4.5.1）
   ├─ credit 检查：PA grant 即消耗 credit
   └─ 每拍只放行一个 port 的读或写之一（匹配 DDR 单向总线）
   ↓
CQ / CAM（第 1 章）
```

| 模块 | 职责 | 关键机制 |
|---|---|---|
| **XMU** | AXI 协议边界、数据汇聚、协议预处理 | outstanding buffer、reorder buffer、RMW 转换 |
| **PA** | 多 port 准入仲裁 | 加权 RR、credit 检查 |
| **CQ/CAM** | 调度窗口 | 见第 1 章 |

**广义 outstanding 模型**（量化口径）：

> 窄义 outstanding = XMU 的 outstanding buffer；广义 outstanding = XMU ostd + CAM 深度。
> 例：AW ostd 深度 16、txn 512B、写 CAM 深度 64 → 控制器总在途写数据 = 512B×16 + 64B×64。

**mask write 与 RMW 的协议分界**：
- **DDR/LPDDR**（支持 mask write）：命令可先于数据到达；
- **HBM**（不支持）：partial write 必须转为 **RMW** 命令，命令必须等待数据到达——转换在 XMU 完成。

---

## 3.2 CAM 物理设计

### 3.2.1 全相联结构

CAM 为**全相联**：每个 entry 可映射到**任意** CCT(bank)。这是 bank interleave 灵活性的物理来源——命令落哪个 bank 完全由调度决定，不受入队位置束缚。

### 3.2.2 深度 tradeoff（32 ~ 96，经验值）

| CAM 深度 ↑ 的收益 | CAM 深度 ↑ 的代价 |
|---|---|
| bank interleave 机会更多 | 面积大幅增加 |
| 调度窗口更深（hit/GPR 晋升空间大） | **冲突检测时序恶化（首要瓶颈，见 3.5）** |

实际设计：**初始 64，后续版本改过 32 和 96**——深度是经验值，不是算出来的（答辩时直说这一点比编公式更加分）。

### 3.2.3 Entry 内容与 WDP

| entry 字段 | 说明 |
|---|---|
| 物理地址 | bank/row/col（经第 1 章映射） |
| priority | 命令优先级（HPR/LPR/GPR/TPW 属性） |
| GPR 超时值 | CamAging 计数基准 |
| 写数据指针 | 指向 WDP buffer |
| 读 ID | 读数据返回时的 AXI ID |
| RMW 标志 | 该命令是否为读改写 |

**写数据不存 CAM**：存独立 **WDP（write data path）buffer**，数据位置与 CAM entry 指针**一一对应**——命令与数据解耦，CAM entry 保持窄而快。

---

## 3.3 CAM Burst：单 entry 打包 4 条命令

**动机**：DDR 的 page hit 特性下，上游一个 txn 天然拆出多条同 page 命令——为它们各占一个 CAM entry 是浪费。

**准入条件**：同 **page**、同 **txn**、同**方向**；col **不要求连续**，但为逻辑简化，**burst 内命令的 col 由逻辑地址最低 2bit 映射**（4 条 = 2bit 的 4 种取值）。

**调度语义（burst ≠ 连续下发）**：
- burst 内**同优先级**；GPR aging **从首条进入 entry 起算**；
- 上 CCT 后**各自独立下发**——同 bank 达不到 tCCD_S，本质仍是 4 条独立命令，**不挡 refresh、不影响其他调度**；
- credit 消耗 **1 个/entry**（最后一条命令释放时归还）；
- 冲突检测**逐条比较** burst 内每个命令。

> **"支持 CAM burst 后，CAM64 等效于 256 个命令，已经完全足够了。"**


---

## 3.4 Credit 制流入控制

### 3.4.1 Credit 配置与生命周期

```
LPR credit + HPR credit = 读 CAM 深度（两队列动态共享）
TPW credit              = 写 CAM 深度

消耗：PA grant 时即消耗（含 Pending 中的命令）
归还：命令离开 CAM 时归还；burst entry 由最后一条命令归还
```

- **LPR/HPR 共存时 credit 不可配 0**——否则一条优先级通路被断流（配置约束，软件须知）；
- **CamAging 只提升 CAM 内优先级，不改变优先级队列从属**——GPR 的"队列内晋升"（4.2）与 credit 从属一致；
- PA→CQ 之间还有 buffer：**PA grant 的命令先落在这里**，所以 Pending 命令也已消耗 credit，反压语义自洽。

### 3.4.2 水线与 GSC 的联动

上水线 → **critical set**；降到下水线 → **critical clr**——作为读写切换（5.4.1）的 set/clr 条件之一。水线把 CAM 占用度转译成 GSC 的切换时机，是流入控制与方向控制的耦合点。

---

## 3.5 冲突处理（RAW / WAR / WAW / RMW）

### 3.5.1 RAW 与 WAR：入口 Pending + 调度提权

发生 RAW/WAR 冲突时：

1. **incoming 命令 Pending 在 CAM 入口，并阻塞后续命令入队**（队头阻塞）；
2. **已在 CAM 的冲突对象升为最高优先级参与调度**；
3. 若冲突对象在**对侧方向**（如 read 到达、write 对象还在 buffer 未下发）→ **更早触发读写切换**（5.4.1 条件 3 的实证——冲突天然转化为 GSC 切换动机）。

Pending 命令已消耗 credit（PA grant 时消耗），不会造成 credit 泄漏。

### 3.5.2 WAW：byte-enable 合并

- 未上 CCT 的 WAW 可 **merge，按 byte enable 合并数据**（两次 partial write 拼成一份）；
- **response 条件**：txn 的**所有 sub-command 被 PA grant 且数据全部到达 XMU** 后返回（AXI 每笔 txn 独立 response，merge 只合并数据不吞 response）。

### 3.5.3 RMW：排斥 merge，只能快冲

**RMW（HBM partial write 转换而来）不参与 WAW merge**——它自身要"先读后写"，与 merge 语义冲突。唯一优化路径：**尽快 flush 掉前面的 write**，缩短 RMW 的等待链。这是 HBM partial-write 密集场景的性能特征根源。

### 3.5.4 冲突检测的时序代价

> **"冲突检测是 CAM 深度无法增加的主要时序原因。"**

- 全相联 + 全 entry 地址比较 → 比较器规模随深度线性涨，落在关键路径上；
- 深度 64 时单拍检测可收敛；后续版本改**分拍检测**：每拍只比较一部分 entry，用流水换时序（代价是冲突识别延迟 1~2 拍）。

---

## 3.6 八问速答表（Request Queue）

| 问题 | 答案 |
|---|---|
| **功能** | AXI 命令接收、协议预处理（RMW 转换/数据汇聚）、port 仲裁、credit 流控，向 CAM 供应命令 |
| **输入/输出** | 入：多 port AXI AW/W/AR + 写数据；出：PA-granted 命令流（credit 已消耗）进入 CAM，写数据进 WDP |
| **状态** | credit 计数、XMU outstanding buffer 占用、水线 critical set/clr、冲突 Pending 标记 |
| **性能瓶颈** | 冲突检测时序（限制 CAM 深度）；每拍单入队口（匹配单向总线）；队头阻塞 |
| **BW 参数** | CAM 深度、CAM burst merge 率、credit 配置、outstanding 深度 |
| **Latency 参数** | outstanding 深度、Pending 阻塞时长、RMW 附加读、分拍检测延迟 |
| **Backpressure** | credit 耗尽 → PA 停止仲裁；XMU ostd 满 → 反压 AXI ready；水线 → GSC 切换 |
| **异常恢复** | credit/ostd 随命令离开自愈；Pending 随冲突对象下发解除；协议错误在 XMU 拦截 |

---

## 3.7 本章金句存档

> 1. "支持 CAM burst 后，CAM64 等效于 256 个命令，已经完全足够了。"
> 2. "广义 outstanding = XMU ostd buffer + CAM 深度。"
> 3. "冲突检测是 CAM 深度无法增加的主要时序原因。"
> 4. "多 rank 的效率低于单 rank，rank 是为了容量而不是性能——PA 每拍一个方向入队也是同样的匹配思想。"

**本章术语表**：

| 术语 | 定义 |
|---|---|
| **XMU** | AXI Manager Unit：AXI 协议边界，含 outstanding buffer、reorder buffer、RMW 转换 |
| **PA** | Port Arbitration：多 port 准入仲裁（加权 RR + credit 检查） |
| **WDP** | Write Data Path buffer：写数据存储，与 CAM entry 指针一一对应 |
| **CAM burst** | 单 CAM entry 打包 4 条同 page/同 txn/同方向命令的机制 |
| **credit** | 入队令牌：PA grant 消耗、离开 CAM 归还；LPR+HPR=读深度、TPW=写深度 |
| **RMW** | Read-Modify-Write：HBM partial write 转换产物，不参与 WAW merge |
| **ostd buffer** | XMU 内 outstanding 缓冲，满则反压 AXI（广义 outstanding 的窄义部分） |
| **reorder buffer** | XMU 读方向为乱序返回数据预留的缓冲（详见第 1 章） |


---

# 4. Command Queue（CQ）：CAM 与命令筛选

## 4.1 定位与设计哲学

**流水线位置**：Request Queue / PA（第 3 章：XMU → PA）之后、CS（BSC/GSC/FSC，第 3 章）之前。

**核心职责**：以 CAM（命令窗口）存储全流水线的读写请求，经三层筛选生成 per-bank 候选（CCT），并实施 hit 优先、批处理倾向的调度策略——**"能不能调"在这里决定**（"现在能不能发"在 CS，见第 3 章）。

**设计哲学（效率基本原则）**：

> 高访问效率 = **page hit × BG 交织 × 批处理**

三个来源：
1. **Page hit**：命中已打开 row，省掉 tRP + tRCD（约 30+ ns 的串行代价）；
2. **BG 交织**：BG 间切换的 tCCD_S 小于同 BG 的 tCCD_L，命令在 BG 间散开可以背靠背发 column；
3. **批处理**：同方向命令连续执行，摊薄 bus turnaround 代价。

上游激励天然配合：单个命令访问 64B，上游 transaction 通常是 256B/512B 连续地址，经地址映射拆为 1~2 个 BG，**BG 内部天然 page hit**。调度器的任务是把这种结构性 locality 吃干榨净。

---

## 4.2 CAM → CCT：三层筛选流水线

这是本章的核心数据通路。命令从 CAM（全流水线请求窗口）到 CCT（候选命令表）经历三层筛选：

```
CAM ──→ ① bank filter ──→ ② priority filter ──→ ③ oldest filter ──→ CCT
         (CAM→bank 映射)    (同 bank 选高优先级)    (同优先级选最老)    (per-bank)
```

### ① bank filter
将 CAM 中**所有命中该 bank 的 entry 全部筛出**（可能不止一条）。bank filter 只做"按 bank 分组筛选"，**不做截断**；收敛到单条候选由后续 priority filter / oldest filter 逐级完成。意义：**命令选择的粒度是 bank**——一个 bank 每次只提名一条命令，bank 之间的并行性由"每 bank 一条候选"天然保证。

### ② priority filter
同一 bank 内有多条候选时，按优先级排序选出一个。

**队列与晋升结构**（GPR 是理解本设计的关键）：

| 方向 | 队列结构 | GPR 语义 |
|---|---|---|
| **读** | **HPR 队列** + **LPR/GPR 共享队列** | 未超时 GPR 与 LPR **同优先级**；**超时（expired）GPR 优先级 > HPR** |
| **写** | **单队列：TPW + GPR** | TPW = 默认优先级写（对应读侧 LPR 的角色）；超时 GPR 同样晋升 |

关键点：**GPR 的晋升发生在队列内部（CamAging 打标记），不是跨队列迁移**——超时前它就是一条普通命令，超时后压过 HPR。

**两种可配置排序模式**：

| 排序模式 | 优先序（高 → 低） | 适用场景 |
|---|---|---|
| **priority first** | expired GPR > HPR hit > HPR miss > LPR/TPW hit > LPR/TPW miss | 延迟 SLA 敏感，优先级严格压过效率 |
| **page hit first** | expired GPR > HPR hit > **LPR/TPW hit** > HPR miss > LPR/TPW miss | 吞吐优先：低优先级的 hit 也压过高优先级的 miss |

**expired GPR 在两种模式下都排第一**——防饿死的硬保障：低优先级命令只需在队列里等待 aging 超时，就必然获得最高调度权，不存在无限饥饿。

### ③ oldest filter
同优先级、同 bank 的多条命令，选 oldest（到达最早）。**在延迟确定性模式下（见 4.3），去掉多优先级后整条流水线退化为 oldest-first，延迟上界最好推。**

### CCT 特性（关键设计约束）
- **per-bank 结构**，深度取决于 bank 数，不是任意值；
- **一旦上表不可撤回**（撤回会造成命令生成器的时序问题）——这是用灵活性换时序收敛的典型决策；
- CCT 只反映"提名"，真正的命令下发还要经过 Command Generator 的 timing 检查。

---

## 4.3 命令选择策略：FR-FCFS 变体

### 4.3.1 策略描述

本设计的 FR-FCFS 是**全局 hit 优先**变体：

> **Page hit 优先级全局最高**：低优先级队列的 page hit > 高优先级队列的 page miss（效率 > 优先级，见 4.2 两种模式）。

同时有一个关键的**自愈机制**：

> Column 命令执行期间存在可下发 row 命令的间隔（tCCD gap）。Page miss 的 row 命令利用这些间隙下发（ACT），row open 完成（tRCD 满足）后，这些 miss 就变成了可调度的 hit。

这意味着：**不存在"hit 无限流饿死 miss 流"的死局**——miss 的 page 被间隙里的 ACT 打开后自动升级为 hit，系统自愈。hit 风暴最多推迟 miss 流，不会无限推迟。

### 4.3.2 为什么 FCFS（严格到达序）不行

严格 FCFS 无法利用 BG 交织：到达序里可能连续请求落在同 bank / 同 BG，而调度器重排后可以让 column 在多个 BG 间背靠背（tCCD_S < tCCD_L）。**纯 FCFS 等于主动放弃 BG 交织收益。**

### 4.3.3 失效场景与对策（答辩要点）

| 场景 | 问题 | 对策 |
|---|---|---|
| (a) hit 风暴 | miss 流被推迟，latency 方差变大 | ACT 窗口消化机制自愈；tCCD_S/L 使 BG 间 hit 本身就是效率优选，无失衡 |
| (b) 随机访问负载 | hit rate 低，hit-first 收益趋零 | 推荐 **auto precharge**（close page）；效率取决于 ACT 分散到各 bank 的程度 |
| (c) 延迟确定性要求 | 实时/等时流量要可预测的上界而非均值最优 | **确定性模式**：提高读写切换频率 + 去掉多优先级 + oldest 上 CCT |

### 4.3.4 量化直觉

- Row hit 每次省 **tRP + tRCD**（DDR4-3200 约 30+ ns），相对一次 tCCD（~1.5ns）是数量级差距——这就是 hit-first 的根本依据；
- BG 交织收益 = tCCD_L − tCCD_S；
- 代价：hit-first 打乱到达序，miss 的排队延迟上升。收益/代价比随 hit rate 上升单调变好——**hit rate 是策略选择的唯一关键统计量**。

---

## 4.4 Open Page / Close Page 策略

### 4.4.1 实现：三寄存器机制（per-bank）

| 寄存器组合 | 行为 | 等效策略 |
|---|---|---|
| ① AP enable（per-bank auto precharge） | 同 page 最后一笔 column 自动 precharge | **close page**（无感、零开销） |
| ② pre-idle 计时器 | bank 空闲超过设定时间才 precharge | **open page**（惰性关闭） |
| ① + ② 同时开 | 保持 open，达到 **tRASmax** 强制 precharge | **open page**（row 生命周期兜底） |

策略是**运行时可配的 per-bank 粒度**，不是编译期选择——软件可按负载特征逐 bank 调整。

### 4.4.2 策略选择的架构推导（面试核心）

**大多数场景适合 close page**，但有三类经典反例：

| 反例 | 为什么 open page 赢 |
|---|---|
| **GPU tile-based rendering / framebuffer 写** | 对同一 row 反复 blend/Z-test，hit rate 80%+，close page 每次白付 tRP+tRCD |
| **低 bank 并行度系统** | 可用 bank 少时，close page 的 tRCD/tRP 无法用其他 bank 并行度掩盖，带宽损失被放大 |
| **小数据高频访问**（page table walk、锁变量） | 不是流式 locality，是同一 cache line 反复访问，省的就是它的关键路径 |

**正向推导**：bank 数越多、负载越流式、standby 功耗越敏感 → 越偏 close page。这正是 **HBM 天然 close page** 的三条原因：32 banks/PC 的高并行度、LLC 下游以流式为主、open row 的 standby 电流代价高。**bank 越多，close page 越香。**

### 4.4.3 已知缺陷与缓解

- **idle-timeout 型 close 有延迟毛刺**：precharge 在 idle 计满后才发出，若此时新 ACT 恰好到来需多等 tRP；
- **CCT 内无法预测未来命令是否命中**（CCT 只看窗口内命令）→ 缓解在**前端**：AXI 前端处理时，连续 page hit 的命令流优先进入 CAM，保证窗口内 locality 可见；
- **PTW 类负载**：直接 disable auto precharge，用 pre-idle 或完全 open page 访问，idle timeout 已足够。

---

## 4.5 QoS / Priority / 防饿死

### 4.5.1 机制全景：QoS 是跨层设计，CQ 只是执行末端

| 层次 | 机制 | 解决什么问题 |
|---|---|---|
| **Port 仲裁**（AXI port ↔ CAM 之间） | 优先级 RR + **per-port 权重**；每个 port 映射到不同优先级队列，仲裁也按优先级队列组织 | 多 master 的**第一级带宽/延迟分配** |
| **Scheduler 队列** | 读：HPR 队列 + LPR/GPR 共享队列；写：单队列 TPW + GPR。高优先级**更早上 CCT** | 短期延迟优先 |
| **CCT priority filter** | priority first / page hit first 两种排序（见 4.2） | 优先级与效率的取舍 |
| **CamAging** | 低优先级命令 aging 计满 → **同队列内晋升为 expired GPR，优先级压过 HPR** | 长期饥饿防护（硬保障） |

### 4.5.2 关键设计取舍

- **CCT 上人人平等**：一旦进入 CCT，优先级信息不再区分——page hit 优先，之后 RR。优先级只影响"谁更早获得提名资格"。这大幅简化了 CCT 侧的时序。
- **明确的 tradeoff 认知（金句）**：
  > "优先级调度会降低部分命令的延迟，但会降低整体的性能。"
- **防饿死的双保险**：
  1. expired GPR 恒排第一：**晋升在队列内部完成（aging 打标记），超时后压过 HPR**——是比"提升概率"更硬的保障，等待时间有确定上界；
  2. 优先级队列参与读写切换决策——饿死防护体现在读写切换中（write 侧长期饥饿会触发切换）。

### 4.5.3 边界声明（答辩加分点）

> 本调度器实现的是**短期延迟优先级**，不是**长期带宽保障**。多 master 保底带宽（如 master A 保证 20%）由 port 仲裁权重 / NoC 层的带宽整形（令牌桶/限流器）承担。**QoS 的边界画在 port 仲裁，Scheduler 不背长期公平的锅**——这个边界本身就是一个架构决策，要能明确说出"画在哪、为什么"。

---

## 4.6 Refresh 交互

Refresh 由**独立模块**管理，与 Scheduler 的交互通过优先级动态调节实现"聚沙成塔、关键时刻插队"：

### 4.6.1 Refresh Debt 机制

```
每经过 tREFI → refresh debt 计数 +1（欠一次刷新）
     ↓
发出 ref 请求（优先级不高，见缝插针执行）
     ↓
debt 达到 postpone 阈值 → 变成 critical ref，优先级最高，强制插入
```

### 4.6.2 Postpone 上限的计算（软件可配，IP 提供计算方法）

协议规定最多 postpone **9 次**。实际配置值由下式给出：

> **最大 postpone 时间 − 连续刷新 8 次的耗时 = 最晚刷新时刻**

即保证即使攒到上限、必须连续补刷时，也不会撞破 tREFI 的协议窗口（连续刷新期间无法响应普通读写，这段突发不可调度时间要预留出来）。

### 4.6.3 与调度的交互要点

- 普通 ref：作为低优先级请求参与正常调度，利用读写切换间隙执行；
- critical ref：**最高优先级**，无视 hit/batch 逻辑直接插队——refresh 是不能无限让步的"债"；
- 答辩提示：refresh 造成的 latency 尖峰 = critical ref 触发时的**补刷连发时间**（最多 8 个 tRFC），postpone 阈值越高、尖峰越罕见但越大——典型的均值/方差取舍。

---

## 4.7 异常恢复

| 异常 | 恢复机制 |
|---|---|
| **DFI 停顿 / 下行反压** | 不影响 CCT 更新，只**反压调度模块**（暂停下发新命令）+ **precharge all banks**——调度状态不丢失，恢复后原续执行 |
| **读数据 ECC/Parity 错误** | 独立 **RAS retry 模块**处理（详见后续 RAS 章节），不反冲 Scheduler |
| **CCT 命令失效** | 不存在——上表不可撤回是设计约束（4.2），保证下行无"命令被抽走"的恢复场景 |

设计哲学：**Scheduler 不做恢复，只做冻结**。异常处理交给专门的 RAS 通路，调度器保持简单可验证。

---

## 4.8 八问速答表（Command Queue / CQ）

| 问题 | 答案 |
|---|---|
| **功能** | 以 CAM 存储全流水线请求，按三层 filter 选出每 bank 最优候选（CCT），实施 FR-FCFS、优先级与防饿死 |
| **输入/输出** | 入：CAM 中的读写命令（含优先级、bank/row/col 地址、到达时间）；出：per-bank CCT 候选提名（timing 过滤/方向切换/仲裁交给 CS，见第 3 章） |
| **状态** | bank open/closed 状态（row hit 判断）、读写方向状态、refresh debt、CamAging 计数、CCT 占用 |
| **性能瓶颈** | hit 判断与三层 filter 的关键路径；CCT 提名粒度（每拍每 bank 一条）；turnaround 间隙 |
| **BW 参数** | hit rate（地址映射决定上限）、BG 交织度、postpone 阈值、close/open page 策略 |
| **Latency 参数** | 队列深度/优先级数、CamAging 阈值、refresh postpone、CCT 深度 |
| **Backpressure** | 上行：CAM 满反压 Request Queue/port 仲裁；下行：DFI 停顿冻结调度 + precharge all，CCT 状态不丢 |
| **异常恢复** | 调度器只冻结不恢复；数据错误走 RAS retry；precharge all 保证 bank 状态确定 |

---

## 4.9 协议差异对命令调度的影响（协议 → 架构映射）

| 协议特性 | 对 Scheduler 的影响 |
|---|---|
| **HBM：32 banks/PC + 伪双通道** | 并行度极高 → close page 是唯一合理策略；hit-first 收益占比下降，BG/bank 分散度调度权重上升 |
| **HBM：独立 refresh per PC** | refresh debt 机制按 PC 独立实例化，两 PC 的 critical ref 可错峰，尖峰减半 |
| **LPDDR：bank group 少（×16 常见 4BG 甚至无 BG）** | BG 交织空间小 → hit-first 和列位置换收益缩水，tCCD_S/L 差异减小 |
| **LPDDR：DVFS/深度 sleep** | 读写切换阈值需随频率联动重配；sleep 进入/退出与 write drain 联动（drain 完才能睡） |
| **LPDDR：ODT 切换代价** | R→W turnaround 更贵 → batch 倾向更大、切换频率更低 |
| **DDR5：每 DIMM 双独立 sub-channel** | 相当于两个小 controller，各自的 CAM/CCT 独立，queue 层共享 port 仲裁 |

---

> **本章讨论金句存档**（答辩可直接引用）：
> 1. "优先级调度会降低部分命令的延迟，但会降低整体的性能。"
> 2. "高访问效率 = page hit × BG 交织 × 批处理。"

**待确认遗留项**：已全部确认 ✅（2026-09-05）

**本章术语表**（后续章节统一引用）：

| 术语 | 定义 |
|---|---|
| **CAM** | 全流水线请求窗口，保存已入队待调度的读写命令 |
| **CCT** | 候选命令表，per-bank 结构，每 bank 每次提名一条命令给 Command Generator；上表后不可撤回 |
| **HPR** | High Priority Read，高优先级读队列 |
| **LPR** | Low Priority Read，低优先级读（与 GPR 共享队列） |
| **GPR** | Guaranteed Priority Request：与 LPR/TPW 同队列，CamAging 未超时时与普通命令同优先级，**超时后优先级压过 HPR**；读写的 GPR 机制对称 |
| **TPW** | 默认优先级写命令（写队列中对应读侧 LPR 的角色） |
| **expired** | CamAging 计数超时状态，是 GPR 晋升的触发条件 |

**下一章建议**：第 3 章 Command Generator——它消费 CCT 的提名，衔接最紧。


---

# 5. Command Scheduler（CS）：BSC / GSC / FSC

## 5.1 模块划分总览

流水线下游的命令生成/调度侧，对应 RTL 顶层 **Command Scheduler** 模块：

```
CQ（第 1 章）：CCT 候选命令（通过资格筛选的提名）
     ↓
┌────────────────────────────────────────────┐
│  CS (Command Scheduler 内核)                │
│   ├─ BSC (Bank Scheduler)：                 │
│   │    bank 状态机(per-bank) + AC timing    │
│   │    三级：bank 层 / bank group 层 / rank 层│
│   │    → 「ready」：满足 AC timing 条件      │
│   ├─ GSC：读写模式切换（见 5.4）             │
│   └─ FSC (Final Scheduler)：最终仲裁         │
│                                            │
│  可执行命令 = CCT 候选 ∩ BSC ready（相与）   │
└────────────────────────────────────────────┘
     ↓
FSC 最终仲裁 → 命令下发
```

**设计精髓**：**"能不能调"（CQ 的候选资格）与"现在能不能发"（BSC 的 timing ready）是两个正交的判断，最后相与**。调度策略与时序约束解耦，各自独立演进和验证。

---

## 5.2 上游接口：来自 CQ 的候选

- **CCT 上是所有"可以发送"的命令**（通过资格筛选的候选，三层 filter 见 4.2）；
- **CCT 更新时机**：有新命令进 CAM，或老命令已发送——否则保持不变（上表不可撤回，见 4.2）；
- CS 拿到候选后，由 BSC 做 AC timing 过滤、GSC 做方向约束、FSC 做最终仲裁。

---

## 5.3 BSC：bank 状态机与三级 Forbid 计数器

### 5.3.1 AC Timing 的实现方式：分布式 Forbid 计数器

**不是查表，是计数器**。不同层级的 AC timing 各有独立计数器组：

| 层级 | 计数器示例 | 触发时机 |
|---|---|---|
| **bank 层** | tRCD 倒计时 / tRAS / tRP / tWR | bank1 发 ACT → tRCD 倒计时开始，计满状态切 *acted*，才允许 col |
| **bank group 层** | **tCCD_L forbid / tCCD_S forbid 双计数器** | bg1ba1 发 col → tCCD_L forbid 禁止同 BG 的 col，tCCD_S forbid 禁止其他 BG 的 col |
| **rank 层** | tFAW / tRFC forbid / tZQCS | REF 下发 → tRFC forbid 计数器启动，期间禁 ACT |

> "Forbid 计数器"语义：命令下发时启动反向计数，计数非零期间对应命令类的 ready 拉低——**检查复杂度 O(1)，与队列深度无关**，这是计数器方案相对时间戳记账表的核心优势（确定性时序）。

### 5.3.2 BSC Bank 状态机（per-bank，RTL 真实状态）

```
                    ACT 下发(act_executedIntl)
   ┌──────┐ ─────────────────────→ ┌─────────────┐
   │ IDLE │                        │ ACTIVTING   │ tRCD/tRCDWR 双计数并行
   └──────┘ ←───────────────────── └──────┬──────┘
      │ ↑  PRE/WRA_RDA 完成              │ tRCD 满 ↓    ↓ tRCDWR 满
      │ │                         ┌─────────┐  ┌───────────┐
      │ │                         │ ACTIVE  │  │ ACTIVE_WR │ ← 仅写窗口
      │ │                         └────┬────┘  └───────────┘
      │ │            PRE/pre_req/force│              │WRA(AP)
      │ │                ┌────────────┴──────────────┤

### 5.3.3 状态转换表

| 状态 | 含义 | 进入条件 | 退出 → 次态 |
|---|---|---|---|
| **BSC_IDLE** | bank 空闲（precharged） | 复位默认；PRECHARGE/WRA_RDA 收尾 | ACT 下发 → ACTIVTING；ref_act_mask → ACT_FORBID |
| **BSC_ACTIVTING** | ACT 已下发，tRCD 计时中 | act_executedIntl | tRCD 计满 → ACTIVE；**tRCDWR 计满 → ACTIVE_WR** |
| **BSC_ACTIVE_WR** | **仅写窗口**（tRCDWR 满足、tRCD 未满） | ACTIVTING 且 trcdwr_cnt 满 | tRCD 满 → ACTIVE；WRA(AP) 下发 → WRA_RDA |
| **BSC_ACTIVE** | row open，col 可正常调度 | tRCD 满 | RDA/WRA → WRA_RDA；PRE → PRECHARGE；force_pre_req → FORCE_PRE；fsm_pre_req → PRE_WAIT |
| **BSC_PRE_WAIT** | 有 precharge 请求**待执行**（可被业务抢占） | fsm_pre_req | PRE 下发 → PRECHARGE；**col 下发 → WRA_RDA**；force_pre_req → FORCE_PRE；请求撤销 → ACTIVE |
| **BSC_FORCE_PRE** | **强制 precharge**（不可被业务抢占） | force_pre_reqIntl | PRE 下发 → PRECHARGE；col 下发 → WRA_RDA |
| **BSC_WRA_RDA** | WRA/RDA（**auto-precharge col**）已下发，等内部 precharge | rda/wra_executedIntl | ref_act_mask 或 drfm ACT 需求 → ACT_FORBID；否则 → IDLE |
| **BSC_PRECHARGE** | PRE 已下发，等 tRP 收尾 | pre_executedIntl | ref_act_mask / drfm ACT 需求 → ACT_FORBID；否则 → IDLE |
| **BSC_ACT_FORBID** | refresh 前禁止 ACT，等 bank 回到可刷新状态 | ref_act_mask；或收尾状态中遇 refresh 需求 | ACT 下发 → ACTIVTING；mask 撤销且无 per-bank refresh 请求 → IDLE；per-bank refresh 执行完 → IDLE |

### 5.3.4 状态机里的四个设计洞察（答辩素材）

1. **tRCD/tRCDWR 双计数出口 + ACTIVE_WR 仅写窗口**：写 col 的最小 ACT→WR 间隔（tRCDWR）小于通用 tRCD，写命令可以**提前于读命令进入**——状态机显式利用了这个 timing 差，抠出写延迟。
2. **PRE_WAIT vs FORCE_PRE 两种 precharge 语义**：普通 precharge 请求（如 idle-timeout close）可被 col 命令抢占（col 下发转 WRA_RDA，业务优先）；强制 precharge（如 refresh 准备、异常处理）不可抢占。**服务性命令让位于业务，是"Col > Row"优先级在状态机层面的落实。**
3. **WRA_RDA 统一收口 auto-precharge**：WRA/RDA(AP) 之后 bank 内部自 precharge，控制器走 WRA_RDA → IDLE，**不需要显式 PRE 命令**——这解释了为什么显式 PRE 在支持 AP 的设计里很少。
4. **ACT_FORBID 从任何收尾状态可达**：refresh 的 ACT mask 优先级高于一切收尾路径——保证 critical ref 到来时 bank 能在最短路径上回到可刷新状态。

---

## 5.4 GSC：读写模式切换（Read/Write Batching 与 Write Drain）

GSC 位于 CS 内，其切换决策与 BSC 的 timing ready、FSC 的仲裁优先级协同工作——**切换不是瞬间完成的，靠 row 方向先行来隐藏 tRCD**。

### 5.4.1 触发条件（四类）

1. **CAM 水线**：某方向命令达到上水线；
2. **单侧执行时间超阈值**（**最常用**）：按读写比例静态设置执行时间配额；
3. **Critical 命令在对侧**：对侧有高优先级/过期命令；
4. **当前侧无命令**：自然切换。

> Perf 激励下命令密集、两侧 CAM 常满、水线长期高位——因此**基于时间的切换最准确、最常用**。

### 5.4.2 渐进式切换（本章最精妙的设计）

读写切换**不是直接切**，而是分两步：

```
当前侧(R)继续发 column 命令
        同时 ──→ 对对侧(W)开始发 ACT（row 命令）
                      ↓
W 侧 row open 完成（tRCD 被当前侧 column 时间隐藏）
        ↓
最后一条 R column → bus turnaround → W column 开始
```

> **"切换的代价基本上都是最小的 tWTR 和 tRTW 时间，而不会有 tRCD 在里面。"**

Row 方向先行把 tRCD 藏进了对侧的 column 执行时间里——turnaround 的纯增量代价只剩数据总线方向切换。

### 5.4.3 Turnaround 完整账单（量化答辩素材）

| 项目 | 方向 | 说明 |
|---|---|---|
| tWTR | W→R | 硬性 AC timing，不可避免 |
| tRTW | R→W | 硬性 AC timing + **ODT 阻抗切换**（LPDDR 尤其贵） |
| tWR | 隐藏成本 | write 批次最后一笔到 precharge 的间隔——drain 后紧跟 refresh/bank close 时会额外吃进来 |
| 频率放大效应 | 双向 | 频率越高，turnaround gap 占 burst 时间比例越大 |

**结论**：tWTR/tRTW 是硬性代价，只能靠**降低切换频率**（增大 batch）来摊薄——这就是"按读写比例设执行时间阈值"的理论依据。

### 5.4.4 Read 恒优先于 Write 的根因

> **"Write 的 response 在进入 CAM 时已经回了，但 read 需要等到读数据后返回，延迟会更大。"**

Write 的 AXI response 在入队时即可返回（数据已在 write buffer 里，后端何时写下去对 master 不可见）；read 的 response 要等数据返回。**端到端延迟责任不对称，所以 read 优先**——这也意味着 write drain 永远是"见缝插针"：在 read 间隙或 read 队列水位低时批量执行。

---

## 5.5 FSC：最终仲裁

### 5.5.1 仲裁优先级

```
Col 命令 > Row 命令
  ├─ Col 内部：RR（轮询）
  └─ Row 内部：critical ref > ACT > PRE > non-critical ref
```

**"Col > Row"的根因**：col 命令产生数据传输，row 只是准备工作——**保证数据总线不空转**。

**"ACT > PRE"的根因（需求驱动）**：

> "ACT 的触发源一定是 CCT 上有真实 miss 命令在等；而 PRE 之后不一定有新命令跟随。"

ACT 是有明确需求的命令，PRE 是投机性/服务性命令——**需求驱动优先于服务性操作**。加上 auto-precharge 存在时显式 PRE 本来就少，这个优先级序是自然的。

**critical ref 的例外**：常态下 Col > Row，但 critical ref 通过 **mask ACT + Col** 显式打破该序（见 5.6）——refresh 是"债"，不能无限让步。

### 5.5.2 每拍单命令的物理根源（协议 → 架构）

| 协议 | CA 总线结构 | 每拍可发命令 |
|---|---|---|
| DDR / LPDDR | **row/col 命令复用同一组 CA 线** | 1 条 |
| **HBM** | **row 线与 col 线独立** | **可同拍同时发 row + col** |

> 这是"协议差异驱动架构差异"的教科书案例：HBM 的 FSC 可以流水化 ACT 与 col，同拍双发——别的协议想学也学不了，物理引脚就不允许。

---

## 5.6 Refresh 执行路径（与 BSC/FSC 的协同）

```
critical ref 触发
  → mask 该 rank 的 ACT + Col 命令（打破 Col>Row 常态序）
  → BSC 各 bank 状态机收尾：AC timing 一满足立即发 PRE(all)
     （收尾路径遇 refresh 需求 → ACT_FORBID，见 5.3.3）
  → REF 下发，tRFC forbid 计数器启动
  → tRFC 期间该 rank 禁 ACT，bank 全程 IDLE
  → tRFC 满，forbid 撤销，调度恢复
```

普通（non-critical）ref 则不 mask，作为低优先级请求见缝插针（见 4.6）。

---

## 5.7 八问速答表（Command Scheduler）

| 问题 | 答案 |
|---|---|
| **功能** | 消费 CCT 候选，做 AC timing 过滤（BSC）与最终仲裁（FSC），下发合法命令；维护 bank 状态机 |
| **输入/输出** | 入：CCT 候选命令、GSC 读写方向、refresh 请求；出：满足时序的最终命令流（给 Timing Enforcement/DFI） |
| **状态** | per-bank FSM（9 态）、三级 forbid 计数器组（bank/BG/rank）、读写方向状态 |
| **性能瓶颈** | FSC 每拍单命令（CA 复用协议下不可逾越）；forbid 窗口期的命令空档；状态机切换的过渡拍 |
| **BW 参数** | forbid 窗口覆盖率（tCCD/tRCD/tRFC 占比）、HBM 双发的并行度增益、ACTIVE_WR 仅写窗口利用 |
| **Latency 参数** | tRCD/tRP/tRFC 计数深度、PRE_WAIT 的抢占行为、critical ref 的 mask 时机、GSC 读写切换阈值 |
| **Backpressure** | 下行反压（DFI stall）直接冻结 FSC 下发；BSC ready 拉低即天然的每 bank 反压 |
| **异常恢复** | FORCE_PRE 提供不可抢占的清场路径；ACT_FORBID 保证 refresh/异常时 bank 状态收敛到 IDLE |

---

## 5.8 本章金句存档

> 1. "ACT 的触发源一定是 CCT 上有命令，但是没有 hit（miss）——而 PRE 之后不一定有新的命令。"
> 2. "Col 优先的根因：col 才产生数据，row 只是在准备——保证数据总线不空转。"
> 3. "不同层级的 AC timing 有独立的计数器——bank/BG/rank 三套，检查复杂度 O(1)。"
> 4. "DDR/LPDDR 的 row/col 复用 CA 线每拍只能发一条；HBM row/col 线独立可以同拍双发。"
> 5. "切换的代价基本上都是最小的 tWTR 和 tRTW 时间，而不会有 tRCD 在里面。"
> 6. "Write 的 response 在进入 CAM 时已经回了，但 read 需要等到读数据后返回，延迟会更大。"

**本章术语表**：

| 术语 | 定义 |
|---|---|
| **CQ** | Command Queue，含 CAM 与三层 filter（第 1 章） |
| **CS** | Command Scheduler 内部子模块集合：BSC + GSC + FSC |
| **BSC** | Bank Scheduler：per-bank 状态机 + bank/BG/rank 三级 AC timing 计数器 |
| **GSC** | 读写模式切换控制器（详见 5.4） |
| **FSC** | Final Scheduler：最终仲裁（Col>Row；Col 内 RR；Row 内 crit ref>ACT>PRE>non-crit ref） |
| **forbid 计数器** | 命令下发时启动的反向计数器，非零期间禁止同类命令，实现 O(1) timing 检查 |
| **ACTIVE_WR** | 仅写窗口状态：tRCDWR 满足但 tRCD 未满，允许写 col 提前进入 |
| **WRA_RDA** | auto-precharge 写/读命令下发后的收尾状态，等 DRAM 内部 precharge 完成 |
| **ref_act_mask** | refresh 模块对 ACT 的 mask 信号，驱动 bank 进入 ACT_FORBID |
| **drfm** | refresh 管理模块；**drfm pb** = per-bank refresh（LPDDR4/5 特性），在状态机中有独立请求/执行路径 |

**下一章建议**：第 1 章 Timing Enforcement——BSC 的 forbid 计数器体系是它的主体，可深挖 counter 的面积/时序/功耗权衡与 SPDE 等进阶主题。

      │ │                │  PRE_WAIT ⇄ FORCE_PRE     │
      │ │                └────────────┬──────────────┘
      │ │            WRA/RDA(AP) 下发 │ PRE 下发
      │ │         ┌──────────┐  ┌─────┴─────┐
      │ └─────────│ WRA_RDA  │  │ PRECHARGE │
      │           └──────────┘  └───────────┘
      │ ref_act_mask / drfm ACT 需求（从任何收尾状态进入）
   ┌──┴──────────┐
   │ ACT_FORBID  │ ← 等待 bank 回到可刷新状态
   └─────────────┘
```


---

# 6. Timing Enforcement（timing counter 体系）

## 6.1 职责与边界

**流水线位置**：与 Command Scheduler（第 3 章）一体——BSC 的 forbid/down 计数器体系就是 Timing Enforcement 的主体，本章讲它的完整架构。

**职责边界（一条清晰的分界线）**：

| 归本章管 | 不归本章管 |
|---|---|
| **单命令间隔**：所有"命令 A 到命令 B 的最小间隔" | **命令序列的时序**：self refresh 进入/退出等序列型操作的时序由 **DFI 保证**（第 3 章） |
| 驻留型检查（tRASmax 等"最晚必须做"） | refresh debt 调度策略（第 1 章） |

**零旁路原则**：**所有命令都必须通过 counter 检查才可下发**——没有任何例外通路。timing 永不违反是**结构性保证**，不是靠事后检查或验证 luck。

---

## 6.2 计数器总账（以 HBM4 为例：总计 ≈ 1017 个）

### 6.2.1 五级分类表

| 层级 | 计数器清单 | 数量 |
|---|---|---|
| **per-bank**（64 bank） | **down**：tRCD、tRCDWr、tRRD、tRC、tRP、tRDA（rda→act）、tWRA、tRFCpb（refpb→act）、tWR2RD、tRASmin、tRD2PRE、tWR2PRE、tDRFM_act2pre、tDRFMPB、tDFRMI；**inline**：tRASmax、tDRFMmax（最大驻留） | 64×14 = **896** |
| **per-BG**（16 BG） | tRRDs（同 BG ACT↔ACT）、tCCDs（同 BG col 间隔）、tWR2RDs、tRD2WRs、rd2rd（与 wr2wr 分开） | 16×5 = **80** |
| **per-rank**（HBM 无 rank，沿用 DDR） | tRFCab、tRFCpb、tRFMab、tRFMpb、tPPD、tWR2MR、tRD2MR、tXRS（SR 退出→ACT）、tXP（PD 退出→ACT）、tRP、tRC、tSR 等 | **21** |
| **per-SID**（4 SID） | rRFCpb、tCCDR 等 | 4×3 = **12** |
| **tFAW 窗口** | 4 计数器 + 使能逻辑 | **8** |

### 6.2.2 三个机制细节

**down counter vs inline counter（对偶关系）**：
- **down counter** 管"**最早何时能做**"：命令下发时启动倒计时，非零期间该操作 ready 拉低；
- **inline counter** 管"**最晚必须做**"（驻留型）：tRASmax（row 最大驻留→强制 precharge，呼应 4.4）、tDRFMmax（DRFM ACT 最大驻留）——上行计数与阈值比较。

**tFAW 的 rolling window 实现**：

```
每次 ACT → 轮流 enable 4 个 counter 之一，各自倒计时 tFAW
4 个 counter 全部处于有效（未归零）状态 → 禁止新的 ACT
```

用 4 个错相计数器实现"窗口内最多 N 个 ACT"——**不是移位寄存器，是计数器组的复用**，与全设计的 counter 风格保持一致。

**量级与代价**：
- counter 约占**整个调度模块面积的 40%**（全模块面积实测见 6.2.3）；
- 功耗友好：**大部分 down counter 归零后不再活跃，门控时钟友好**——1017 个 counter 的平均活动率远低于表面数字。

### 6.2.3 全模块面积实测（待处理项 ② 已关闭）

**LPDDR6 @ 三星 SF4 1000MHz**（单位 μm²；配置：CAM32 / link node 96）：

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

**HBM4 @ 三星 SF4 1600MHz，双 PC 合并（PC0+PC1）**（单位 μm²；配置：CAM96 / link node 224）：

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

**三组观察（表格可直接支撑的结论）**：
1. **面积大头随协议切换**：LPDDR6 在 **CS**（23.08%，第 1 章 counter 体系所在，呼应"counter 占调度模块 40%"）；HBM4 在 **CQ + XMU**（合计 57.7%，双 PC 的 CAM96 队列 + link node 224 的在途结构）；
2. **配置实证经验区间**：CAM 深度 LPDDR6=32 / HBM4=96，印证 3.2.2 的"32~96 经验值"——**低功耗产品用浅 CAM，高带宽产品用深 CAM**；link node 数同样按带宽需求放大（96 → 224）；
3. **数据缓冲占比反映 burst 长度**：HBM4 的 WDP 仅 1.76%（BL8 短 burst、缓冲浅），LPDDR6 的 WDP 达 10.40%（BL32 长burst）。

---

## 6.3 分布式 vs 集中式：五维 tradeoff（答辩核心）

另一条路线是**中央时间戳记账**：每条命令记录 issue time，检查时做减法比较。本设计选择**分布式 per-level counter**，论证如下：

| 维度 | 分布式 counter（本设计） | 集中式时间戳记账 |
|---|---|---|
| **位宽** | 各 counter 独立小位宽（几 bit） | 必须按最大 timing 位宽统一处理 |
| **比较逻辑** | **1 bit**（归零与否） | 加减法 + 比较（算术单元） |
| **功耗** | 归零即静默，**门控时钟友好** | 全局时钟/时间戳需持续 toggle |
| **时序** | bank/BG/rank/SID 各级**完全并行**，无集中瓶颈 | 集中比较器容易成为关键路径 |
| **可扩展性** | 增删层级、兼容不同协议（DDR/LPDDR/HBM 计数器清单不同）都容易 | 记账表结构与协议耦合 |

**结论**：在"协议多样化（一套 IP 支持多协议）+ 多层级并行检查"的设计约束下，分布式全胜；集中式的优势（表项统一、免配计数器）在多协议场景反而变成负担。

---

## 6.4 参数化与频率

### 6.4.1 参数来源链路

```
DRAM 颗粒模型（datasheet/协议 timing）
   ↓  软件脚本换算（ns → 控制器时钟周期，ceil 向上取整）
寄存器配置
   ↓
各 counter 初值
```

- **ns → cycle 一律向上取整**：取整方向错了就是协议违反，ceil 是唯一安全解（多花的 1 个 cycle 是安全的代价）；
- 所有 timing 参数**寄存器可配**——放宽/收紧都在软件控制下，也给 debug/容错留了旋钮。

### 6.4.2 DVFS：结构性规避而非运行时处理

**DVFS 切换时控制器保证 IDLE**——不存在"counter 跨频率存活"的问题：换频发生时没有任何在途倒计时，新频率下用新参数重配即可。

> 这是典型的**用系统级约束消解模块级难题**的例子：不在 counter 里做频率感知，而是保证换频窗口内无状态。

---

## 6.5 零违反的保证与验证

1. **结构性保证**：所有命令无旁路地通过 counter 检查（6.1）；
2. **min gap 覆盖率收集**：验证时统计每类命令对的实际间隔最小值，与配置的 timing 值比对——**保证每条 timing 都被真实激励覆盖**，不存在"从未被检查过的 timing 条目"；
3. **寄存器可配兜底**：若发现某条 timing 约束有疑问，可通过寄存器放宽验证——但默认值必须来自颗粒模型的脚本换算。

---

## 6.6 八问速答表（Timing Enforcement）

| 问题 | 答案 |
|---|---|
| **功能** | 以五级分布式 counter（bank/BG/rank/SID/窗口）检查所有单命令间隔，结构性保证零 timing violation |
| **输入/输出** | 入：命令下发事件、timing 参数寄存器；出：per-操作 ready/forbid 状态（进 BSC 的相与逻辑） |
| **状态** | ≈1017 个 counter（HBM4）：down/inline/window 三型，五级分布 |
| **性能瓶颈** | counter 归零窗口内的命令空档（协议固有，非实现问题）；分拍冲突检测（见 3.5.4） |
| **BW 参数** | timing 参数值本身（ceil 换算）、tFAW 窗口大小、tCCD_S/L 差值 |
| **Latency 参数** | tRCD/tRP/tRFC 等 down counter 深度、inline 驻留阈值 |
| **Backpressure** | forbid 非零 → 对应命令类 ready 拉低（O(1) 检查）；无额外反压通路 |
| **异常恢复** | counter 全部自归零，无持锁状态；DVFS 在 IDLE 下换参数，无跨频率状态 |

---

## 6.7 本章金句存档

> 1. "所有命令都过 counter 检查，且用 min gap 覆盖率保证无遗留——零违反是结构性的，不是验证出来的。"
> 2. "分布式比较是 1 bit，集中式要做减法——1017 个 counter 的规模下，这个差别就是面积和功耗的差别。"
> 3. "DVFS 时控制器一定是 IDLE 的——用系统约束消解模块难题，而不是在 counter 里做频率感知。"
> 4. "ns 转 cycle 一律向上取整——多花一个 cycle 是安全的代价，取整方向错了就是协议违反。"

**本章术语表**：

| 术语 | 定义 |
|---|---|
| **down counter** | 递减计数器：命令下发启动，非零期间禁止对应操作——管"最早何时能做" |
| **inline counter** | 驻留计数器：上行计数与阈值比较——管"最晚必须做"（tRASmax/tDRFMmax） |
| **forbid 计数器** | down counter 的禁止语义视图：非零期间对应命令类 ready 拉低 |
| **tFAW 窗口** | 4 个错相计数器轮流使能，全有效时禁 ACT，实现"窗口内最多 N 个 ACT" |
| **颗粒模型** | DRAM 颗粒 timing 的来源模型；经软件脚本（ceil）换算为控制器周期后配置寄存器 |
| **min gap 覆盖率** | 验证指标：每类命令对的实际最小间隔被真实激励覆盖，保证 timing 检查无遗漏 |

**下一章建议**：第 3 章 DFI——8 章已多次把"序列时序"甩给它（self refresh 序列、init/training 握手、low power），正好接住。


---

# 7. DFI（控制器-PHY 交接面）

## 7.1 频率架构：ratio 定标

### 9.1.1 频率比配置

| 配置 | DFI : CK : WCK | DFI 实际频率 | 适用场景 |
|---|---|---|---|
| **ratio4** | 1 : 2 : 4 | LPDDR5-7200 时 **900MHz** | LPDDR5 ≤ 7200Mbps |
| **ratio8** | 1 : 4 : 8 | LPDDR5-12800 时 **800MHz** | LPDDR5 ≤ 12800Mbps |

HBM（ratio4）：CTRL 最高 **1200MHz @ 三星 SF4**，颗粒数据速率 9600，每拍一命令。

### 9.1.2 定标哲学

> **控制器频率不能太高**——某些工艺 900MHz 以上难以收敛。ratio 的本质是**用 DFI 总线位宽换控制器时序**。

- ratio4：每拍发一个命令，带宽刚好；
- **ratio8：每拍只发一个命令会浪费 2 个 CK**，控制器内部（命令打包/phase 管理）复杂度显著上升——高频不自由；
- **phase 约束**：SRE/PDE 等由 **DEVMGR** 发出的命令只在 **phase0** 发送，低频命令也要守 phase 纪律。

---

## 7.2 Init / Training

- **DRAM init 与 training 均由 PHY 主导完成**，controller 不驱动序列（通过握手信号感知进度）；
- init 握手（init_start / init_complete 类信号）期间 controller 命令通路保持关闭；
- *（待处理项）*：training 具体序列、失败重试路径、software 是否回读 delay line 结果——后续补充。

---

## 7.3 Low Power：DEVMGR 与全链路排空（本章核心）

### 9.3.1 覆盖状态与排空条件

低功耗状态：**SR（self refresh）、PD（power down）、DSME（LPDDR deep sleep）**。

进入前的**全链路排空**判定：

| 模块 | 排空判据 |
|---|---|
| XMU | **req == resp**（在途请求全部回来） |
| CQ | **CAM empty** |
| 期间 | 反压 AXI 上游 |

### 9.3.2 硬件触发流程（本章核心时序）

```
XMU 无新请求 → 告知 DEVMGR
  → DEVMGR 向 XMU 发出主动反压请求
  → XMU 反压 AXI 上游（不再收新请求）
  → 全链路排空（req==resp 且 CAM empty）
  → 进入 low power（SRE/PDE 等由 DEVMGR 在 phase0 发出）
```

**关键语义——低功耗期间的 AXI 请求**：

> 不是直接放行，而是：**先触发 DEVMGR 退出低功耗 → 撤销反压请求 → 再允许 AXI 请求进入**。

保证状态机不撕裂：请求永远在"低功耗已确定退出、反压已确定撤销"之后才被接纳。

### 9.3.3 软硬件触发的对称性

- **硬件触发**：链路空闲时自动进入，来流量自动退出；
- **软件触发**：**进入和解除都必须由软件完成**——软件发起的低功耗，硬件不擅自解除；
- 唤醒延迟（tXSR/tXP 类）的计时由 DFI 序列保证（呼应 6.1 的边界划分）。


---

## 7.4 协议差异：同一交接面的三种形态

### 7.4.1 HBM：双 PC 奇偶 CK 合流

ratio4 下 DFI:CK = 1:2（DFI 半频于 CK）：

- **命令**：col 命令占 1 个 CK，row 命令（除 ACT 外）也占 1 个 CK → **两个 PC 分奇偶 CK**（PC0 奇 / PC1 偶），**ACT 轮流仲裁**；
- **数据**：**2 倍 PC 位宽直接合并**，互不影响——类比 LPDDR5 的双 channel；
- 一句话：**命令分时、数据并行**。

**16GHz：CS prefetch window**（系统级架构迭代，量级类似 CAM burst）：HBM4 仅 BL8，ratio8 需要凑 BL16 的数据量 → 将已 ACT 的 bank 先放入 **8 个 prefetch entry**，每拍从中**选 2 条命令**发送。**完整机制见 7.8 专题。**

### 7.4.2 LPDDR5：专用信号组

- **DQS oscillator**、**WCK 控制**走独立 DFI 信号：**dfi_wck_en / dfi_wck_toggle**；
- per-bank refresh 的 drfm 信号通路已在 5.3 FSM 中体现（drfm_act_sent / drfmpb_req）；
- DSME 为 LPDDR 特有的深度睡眠，进出由 DEVMGR/软件管理（7.3）。

### 7.4.3 DDR：CRC 与 CA parity

- **Write CRC**：与数据线共用，**以增加 BL 的方式传输**（CRC 附着在 burst 之后）；
- **CA parity**：走**独立 DFI 线**，在 **dfi_address 编码时生成**（controller 侧计算，不走数据通路）。

---

## 7.5 八问速答表（DFI）

| 问题 | 答案 |
|---|---|
| **功能** | 控制器与 PHY 的标准化交接面：命令/写数据下行、读数据上行、init/training 握手、低功耗握手 |
| **输入/输出** | 入：过完 BSC/FSC 的命令流、写数据、低功耗请求；出：dfi 命令/数据（按 ratio 与 phase）、读数据+valid、握手信号 |
| **状态** | ratio 配置、phase 计数、DEVMGR 低功耗状态机、全链路排空状态 |
| **性能瓶颈** | ratio8 下每拍一命令浪费 2 CK；DEVMGR 命令的 phase0 排他；HBM 双 PC 奇偶 CK 的 ACT 仲裁 |
| **BW 参数** | ratio 选择、命令打包效率、CS prefetch window（前瞻）、数据位宽合并 |
| **Latency 参数** | 低功耗唤醒路径（退出→撤销反压→放行）、lp_ack 往返、tXSR/tXP 序列 |
| **Backpressure** | 排空期间 DEVMGR→XMU→AXI 的主动反压链；读数据 valid 驱动 XMU reorder buffer |
| **异常恢复** | 序列时序由 DFI 保证（6.1 边界）；init/training 失败路径为待处理项 |

---

## 7.6 本章金句存档

> 1. "控制器频率不能太高——ratio 的本质是用 DFI 位宽换控制器时序。"
> 2. "低功耗期间来 AXI 请求，不是直接放行——先退出低功耗、撤销反压、再放行。"
> 3. "HBM 双 PC：命令按奇偶 CK 分时，数据 2 倍位宽直接合并——命令分时、数据并行。"
> 4. "ratio8 下每拍只发一个命令会浪费 2 个 CK——高频不自由。"

**本章术语表**：

| 术语 | 定义 |
|---|---|
| **ratio4 / ratio8** | DFI:CK:WCK 频率比 1:2:4 / 1:4:8，控制器频率定标的核心配置 |
| **DEVMGR** | Device Manager：低功耗状态机与 SRE/PDE 等设备命令的所有者 |
| **phase0** | ratio8 下 DFI 拍内的子相位；DEVMGR 命令只在此相位发送 |
| **排空（drain）** | 低功耗进入前的全链路清空：XMU req==resp + CAM empty + 反压上游 |
| **DSME** | LPDDR Deep Sleep Mode Enable， deepest 低功耗状态 |
| **dfi_wck_en / dfi_wck_toggle** | LPDDR5 WCK 控制的专用 DFI 信号 |
| **CS prefetch window** | HBM4 16GHz 前瞻架构：8 个 prefetch entry 中每拍选 2 条命令（后续专题） |

---

## 7.7 全局待处理项登记（截至本章）

| # | 事项 | 来源章节 | 状态 |
|---|---|---|---|
| 1 | init/training 序列细节与失败重试路径 | 7.2 | 待讨论 |

**已关闭**：
- ✅ stride 极端（2.2）：UIF 低位 = col/ba、txn 地址连续递增，不存在同 bank 换 row 形态；
- ✅ 面积数字（6.2.3）：LPDDR6 / HBM4 双表已录入（含 CAM depth 与 link node 配置）；
- ✅ CS prefetch window（7.8）：HBM4 16GHz 专题已成文。


---

## 7.8 专题：CS prefetch window（HBM4 16GHz 架构迭代）

### 7.8.1 目标与问题

- **目标**：CTRL 1GHz 下，CS 每拍最多调度 **2 条同方向 col 命令**，实现**等效 2GHz** 的性能水平；
- **问题**：ratio8 要求命令速率匹配数据速率（每拍 2 条），而大 CAM（CAM96）下的调度选择是 **64 选 2**——选择逻辑直接撞时序墙。

### 7.8.2 结构：调度影子（shadow）

**职责划分完全不变**（这是本架构最重要的声明）：

| 模块 | 保留的控制权 |
|---|---|
| **CQ** | CAM、CCT、命令状态 |
| **CS** | bank FSM、AC timing 管理 |

PF window 本体：

- **8 个 PF window entry**，**一个 CAM entry 对应一个 PF entry**；
- entry 内仅保存**调度的影子**：CQ ptr / SID / BG 等信息——不搬命令，只搬指针；
- 进入 PF window 的命令仍留在 CCT，但**被 CS 忽略**；
- 效果：调度选择从 **64 选 2 降维成 8 选 2**——时序压力大减，且 entry 内命令能被快速排空。

### 7.8.3 进入与释放条件

| 阶段 | 条件 |
|---|---|
| **进入** | 命令上 CCT 且 miss → 触发 ACT 发送 → bank 进入 ACTING；**接近 ACTING 尾期**（col 即将可用）进入 PF window |
| **准入约束** | **同 BA 只能存在一个**；优先筛选**不同 BG** 的命令进入 |
| **释放** | entry 内命令**全部执行完成**；或被**高优先级事件打断**（如 critical refresh） |

### 7.8.4 DFI CK 映射与双发规则

ratio8 下 DFI:CK = 1:4，四个 CK 相位的 col 命令通道分配：

```
          CK0        CK1        CK2        CK3
PC0   dfi_col0              dfi_col1
PC1              dfi_col0              dfi_col1
```

- PC0：dfi_col0 → CK0、dfi_col1 → CK2；PC1：dfi_col0 → CK1、dfi_col1 → CK3；
- **两条命令的间隔恰好 = tCCD_S = 2**——CK 映射本身就是按 BG 切换的 AC timing 设计的；
- **同拍可发**：同 SID 不同 BG 的两条读命令、或不同 BG 的两条写命令；
- **不强制双发**：某拍只有一条满足 AC timing 就发一条（不空凑）。

### 7.8.5 写数据难题：SRAM 单口 vs 一拍双数据

一拍双写 = 一拍要出**两份写数据**，且两条命令不同 BG → **SRAM 地址不同**——但 SRAM 一拍只能读一个地址。

**解法：DFI 侧预取**：

```
CS 向 DFI 发出 DFI prefetch 请求
  → DFI 预取一个 burst（4 条命令的数据）缓存在内部 buffer
  → 真正下发时，两个不同 entry 的数据可同时读出
```

### 7.8.6 Entry 内排序规则

**首命令优先**：优先调度 entry 中最前面的命令——组合 0/1、0/2；若 0 不满足 AC timing，才轮到 1/2 组合。

### 7.8.7 本章金句（专题）

> 1. "PF window 仅保存调度的影子——CAM/CCT/命令状态仍在 CQ，bank FSM 与 AC timing 仍在 CS。"
> 2. "64 选 2 变 8 选 2。"
> 3. "PC0 col0→CK0 / col1→CK2，PC1 col0→CK1 / col1→CK3——双发间隔恰好就是 tCCD_S = 2。"
> 4. "一拍双写意味着一拍双数据——SRAM 单口不够，就让 DFI 预取一个 burst。"

