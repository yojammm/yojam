# 多协议内存对比：HBM3/3E/4 · DDR5 · LPDDR5/5X/6

> **定位**：Memory Controller 方向的日常查阅速查手册 + 核心考点手册；以《研究纲领》为纲——横向对比（HBM/DDR/LPDDR/3D DRAM）+ 纵向演进（每代新 Feature 的六层追问），覆盖状态见"问题路线图"一节。
> **数据口径**：以 JEDEC 标准原文核对为准 —— JESD238（HBM3）、JESD270-4（HBM4）、JESD79-5B（DDR5）、JESD209-5B（LPDDR5/5X）、JESD209-6（LPDDR6）；核对日期 2026-09。厂商公开资料单独标注。仍存疑的数字以 ⚠️ 标记（见附录 D）。
> **约定**：每节末尾的【核心速答】为 30 秒口径的高频问题答案；正文小节标题中的题号已统一迁移为《研究纲领》Part I~XII 问题编号（A1~O10 等），完整清单与覆盖状态见"问题路线图"；旧清单（A1~H4）编号作废，映射见维护说明。

## 研究纲领（本文方法论）

> 本节回答"这份手册怎么用、往哪里长"：正文速查提供 [JEDEC] 层的"是什么"；"问题路线图"追踪每个纲领问题的回答状态；六层追问框架负责"为什么"。当前正文覆盖 HBM / DDR5 / LPDDR 三族，横向纲领中的 3D DRAM 专题待扩展。

### 纲 0.1 文档目标：横向与纵向

- **横向**：HBM / DDR / LPDDR / 3D DRAM——面对相同问题时为什么选择不同方案。
- **纵向**：DDR4→DDR5、LPDDR4→LPDDR5→LPDDR6、HBM2→HBM3→HBM4——同一种 Memory 为什么会出现新的 Channel、Clock、Refresh、RAS、Training、Power Feature。
- 终极问题：**一个协议 Feature 是为了修复上一代的什么瓶颈？它把复杂度从哪里转移到了哪里？Controller、PHY、Package 分别付出了什么代价？**

### 纲 0.2 一个 Feature 必须追六层

| 层 | 追问 | 关注度 |
|---|---|---|
| 1. Problem | 上一代遇到了什么问题？ | 入口 |
| 2. Protocol Mechanism | 协议具体增加或改变了什么？ | 入口 |
| 3. Physical Cause | 为什么物理上需要这样做？ | ★ 核心 |
| 4. Controller Cost | Controller 需要新增什么状态机、counter、queue、sequence？ | ★ 核心 |
| 5. PHY / Package Cost | PHY、信号、电源、封装需要新增什么？ | ★ 核心 |
| 6. Tradeoff / Evolution | 获得了什么？付出了什么？下一代往哪个方向继续？ | ★ 核心 |

本文真正关心第 3～6 层。

### 纲 0.3 信息来源纪律

| 标签 | 含义 |
|---|---|
| [JEDEC] | 标准明确规定 |
| [VENDOR] | 厂商 datasheet / whitepaper |
| [DFI] | DFI Specification |
| [PROJECT] | 项目真实实现 |
| [PHYSICAL-EXPLANATION] | 基于电气/阵列原理的解释 |
| [INFERENCE] | 本人架构推论 |
| [UNKNOWN] | 尚未理解 |

- **JEDEC 通常告诉我"必须做什么"，但不一定告诉我"物理上为什么这样做"**——"为什么"若非标准原文，不得伪装成标准结论。
- 执行方式：新内容落笔必须带标签；既有正文的标签映射见文末维护说明与附录 D（✅=[JEDEC]、厂商口径=[VENDOR]、⚠️=[UNKNOWN]）。

### 纲 0.4 PHY 学习深度边界

不要求设计 analog PHY，要求打通：

```text
Protocol Feature
      ↓
Physical Problem
      ↓
Training / Calibration
      ↓
DFI Handshake
      ↓
Controller Responsibility
```

示例（应能完整复述）：Data rate 增加 → UI 变窄 → jitter/skew 占比增加 → static timing margin 不足 → 引入 per-lane deskew / Vref / equalization → PHY 完成实际 delay/Vref tuning → Controller 通过 DFI 发起并管理 training sequence。

### 纲 0.5 最终完成标准

看到任何一个新协议 Feature，不再满足于"Spec 规定如此"，而是能回答：**上一代哪里不够？物理根因是什么？协议怎么解决？Controller 要增加什么？PHY/Package 要付出什么？性能、功耗、面积和可靠性最终交换了什么？**

## 0. 速查表（一页纸）

### 0.1 核心参数对比

| 维度 | HBM3 | HBM3E | HBM4 | DDR5 | LPDDR5/5X | LPDDR6 |
|---|---|---|---|---|---|---|
| JEDEC 标准 | JESD238 (2022.01) | JESD238A | JESD270-4 (2025.04) | JESD79-5 系列 (2020.07 起) | JESD209-5 (2019.02) / -5B | JESD209-6 (2025.07) |
| 接口位宽 | 1024-bit | 1024-bit | 2048-bit | 64-bit/DIMM | 64-bit（多×16-bit 通道） | x24（=2×12-DQ 子通道） |
| 通道组织 | 16ch×64-bit，每 ch 2PC | 同左 | 32ch×64-bit，每 ch 2PC | 2 个独立 32-bit 子通道/DIMM | 4~8×16-bit 通道 | x24 Normal；x12 效率模式 |
| 单 pin 速率 | 6.4 Gbps | 9.6 Gbps | 8G 基线→产品 10/11/12.8G | 4.0~8.8 GT/s | 6.4 / 8.533 / 9.6 / 10.7 Gbps | 10.6~14.4 Gbps |
| 单 stack/DIMM 带宽 | 819 GB/s | 1.23 TB/s | 2.05 TB/s 基线→3.3 TB/s @12.8G | 32~70.4 GB/s | 51~86 GB/s（64-bit 折算） | 名义 ~230 GB/s（x128 折算）⚠️ |
| 突发长度 | BL8 | BL8 | BL8 | BL16 | BL16 | BL24/BL48 |
| 容量 | 16/24 GB | 24/36/48 GB | ≤64 GB（4~16 die） | die 16/24/32Gb | 单封装 16~32 GB+ | 16Gb die 起，CAMM2 |
| 电压 | core 1.1V / I/O 1.1V / Tx 0.4V | 同左 | core 1.05V / I/O 厂商自定 | 1.1V（+VPP） | VDD1/VDD2H/VDD2L/VDDQ | VDD1/VDD2C 1.0V/VDD2D 0.875V/VDDQ 0.5V |
| CKE | 无（命令式低功耗） | 无 | 无 | 有 | 无（CA 命令进低功耗） | 无 |
| 刷新管理 | RAA+ARFM（可选） | 同左 | RFMpb/DRFMpb+BRC | REFab/REFsb + RFM/DRFM/ARFM | REFab/REFpb + RFM→ARFM | REFpb + PRAC + ABO |
| ECC | On-die ECC + 接口 ECC + SEV 上报 | 同左增强 | 同左 + ECS 多 bit | ODECC 强制（128+8 SEC） | Link ECC（可选） | 突发内嵌 tag/ECC（288=256+32） |

### 0.2 一句话定位

- **HBM**：带宽引擎 —— 堆叠近存、超高带宽密度、容量天花板低；AI/HPC 专属。
- **DDR5**：容量底座 —— 插槽横向扩展、单位容量成本最低；服务器主存。
- **LPDDR5/6**：功耗效率 —— 多频点电源管理、焊装低功耗；移动/边缘 AI 主存。

## 1. 顶层指标对比

### 1.1 带宽与速率（纲领 O10 / L3 / A8~A9）

**HBM：带宽翻倍的两种姿势**

| 代际 | 接口位宽 | 通道组织 | 速率（基线→产品） | 单 stack 带宽 | 容量 |
|---|---|---|---|---|---|
| HBM3 | 1024-bit | 16ch×64-bit | 6.4 Gbps | 819.2 GB/s | 16/24 GB（8/12-Hi，16Gb die） |
| HBM3E | 1024-bit | 16ch×64-bit | 9.6 Gbps | 1228.8 GB/s | 24/36/48 GB（10/12/16-Hi，16/24Gb） |
| HBM4 | 2048-bit | 32ch×64-bit | 8G 基线 → 产品 10/11/12.8G → 路线 16G | 2.048 TB/s → 2.8/3.3 TB/s → ≈4.1 TB/s | ≤64 GB（4~16 die，24/32Gb） |

- HBM3→3E：**纯速率演进**（6.4→9.6G，同位宽）。
- 3E→4：**架构性翻倍靠位宽**（1024→2048，16→32 通道）；JEDEC 基线速率 8G 反而低于 3E 的 9.6G，总带宽增长全部来自位宽；产品竞争力由代内速率爬坡（8→12.8→16G）决定（三星 HBM4 官方 3,300 GB/s ≈12.8G；美光 >11G/>2.8TB/s）。
- 为什么翻位宽而不是继续提速率：中距离互连上持续提速率的边际成本（均衡、训练时间、pJ/bit、良率）急剧上升；翻位宽把压力转移到封装布线/bump 密度，换取时序裕量与能效。衍生变化：PHY 向逻辑 base die / SoC 侧迁移、HBM4 I/O 电压开放厂商自定（见 5.1）。

**LPDDR：速率阶梯与有效带宽**

| 代际 | 标准 | 单 pin 速率 | 64-bit 等效带宽 |
|---|---|---|---|
| LPDDR5 | JESD209-5 | 3200~6400 Mbps | 25.6~51.2 GB/s |
| LPDDR5X | JESD209-5B | 8533 / 9600(=LPDDR5T) / 10700 Mbps | 68.3 / 76.8 / 85.6 GB/s |
| LPDDR6 | JESD209-6 | 10.6~14.4 Gbps | 名义 84.8~115.2（64-bit 等效）/ 169.6~230.4（x128 折算）⚠️ 口径需注明 |

- LPDDR6 提升倍数：vs 5X-9600 = **1.5×**；vs 5X-8533 ≈ **1.69×**；vs LPDDR5 = 2.25×。引用时必须对齐档位。
- LPDDR6 **有效带宽打折**：BL24 一次访问 = 288-bit，其中仅 256-bit 为用户数据（16-bit tag/ECC 存入阵列 + 16-bit DBI/链路 ECC 不占阵列），有效 ≈ 名义 × 89%（JESD209-6 §2.4）。SoC 侧仍组织为 32/64-bit 等效位宽，通道→地址映射是控制器设计点。

【核心速答】HBM 三代的公式都是 位宽×速率：3→3E 靠速率，3E→4 靠位宽翻倍（基线速率还回落到 8G），产品带宽靠代内速率爬坡到 12.8G/3.3TB/s。LPDDR5→5X→6 是速率阶梯（6.4→10.7→14.4G）；LPDDR6 注意 288-bit 突发里只有 256-bit 是有效数据。

### 1.2 容量与扩展路径（纲领 A4 / A12 / O5）

| 维度 | HBM | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 扩展方向 | 纵向：封装内堆 die（4~16） | 横向：槽数 × DIMM 容量 | 封装贴片：die 数 × 封装数 |
| 确定时机 | SoC 设计期锁死 | 部署期灵活插拔 | 制造期焊死（CAMM2 后可换） |
| 天花板 | 单 stack ≤64GB；受良率/散热/厚度限制 | 模组密度最高 | 单封装 ≤32~64GB |
| 代价 | TSV+键合良率、$/GB 最高 | 走线长、RCD/DB/PMIC 开销 | 不可升级（传统 PoH） |

- **DDR5 子通道与访问粒度（A2）**：每 DIMM 两个独立 32-bit 子通道（ECC 模组 2×40-bit = 32 数据 + 8 side-band ECC）；每子通道 BL16×32-bit = 64B —— 一个 cache line 完整落在单个子通道内。**CL 与子通道没有直接关系**（CL 随频率档标定，跨代绝对时间守恒）；子通道化改变的是最小访问粒度与并发请求数："用位宽换请求数"。
- **LPDDR6 窄通道与容量（A4）**：x24 Normal Mode 与 x12 Dynamic/Static Efficiency Mode（JESD209-6 §2.2.2 / §7.8.29），并支持 **Mixed Package**（x24 die 与 Static Efficiency die 混装）——通道配置与容量配置解耦。⚠️ 原问题清单中"x6"的说法在 JESD209-6 中不存在（x6 / 6-DQ 全文 0 命中），标准口径为 x24/x12。
- **HBM4 的解耦（B2 预告）**：4 die 即满 32 通道，第 5~16 die 只增加容量、SID 与 bank 数（16/32/48/64 banks per channel）——通道数与容量/bank 并行度解耦。

**A8 综合：为什么并行结构越来越"更多、更窄、更独立"——六层成文**

- **Problem**：单宽通道三病——① 命令吞吐瓶颈：一通道一拍只能下发一条命令，多主设备的小请求全部排队；② 突发粒度与 cache line 失配：预取增大（8n→16n→24n）后，宽通道一命令过取多行；③ 单通道并发被供电限额封顶（tRRD/tFAW，§2.2 墙 1），加 bank 也救不了命令带宽。
- **Physical cause**：速率边际成本上升——中距离互连继续提速率的均衡/训练/pJ/bit/良率代价急剧上升（§1.1）；宽总线的同时翻转线数（SSO/di/dt）与 skew 匹配组随位宽增长，SI 工程难度超线性 [PHYSICAL-EXPLANATION]。
- **Mechanism（三家的"拆"）**：DDR5 1×64 → 2×32（64B 对齐，§2.2 A4）；LPDDR5 单通道 16-bit → LPDDR6 2×SC×12-bit（§2.3）；HBM3 16ch → HBM4 32ch（通道宽 64-bit 不变、ch-2PC 同构，§2.1 A5）。共性：**位宽换请求数**——每实例更窄、实例更多、命令域更独立。
- **Controller cost**：实例数翻倍 → 状态机/计时器/checker/CAM 全线线性增长（§7.1 A3 四部件）；命令编码代价：窄 CA 要多周期发命令——LPDDR6 每条命令 2 周期、ACT 需 ACT-1+ACT-2 共 4 周期（Table 254 NOTE 1/4），CA 7→4 根的代价是命令带宽减半；调度算法与防热点映射（channel-first）复杂化；NoC 压力前移（A10）。
- **PHY/Package cost**：DQ 总引脚不变（带宽需求决定），省的是 **CA 引脚摊薄**（HBM 18 pin 服务 2 PC、LPDDR6 每 SC 4CA+2CS）与走线组规整（DDR5 RCD 分组、LPDDR PoH 可行）；代价转移到 bump 密度/封装布线（HBM4）。
- **Tradeoff（A9 入口）**：peak 是否提升取决于总引脚是否增加——拆分（DDR5 子通道）不动 peak、增设（HBM4/LPDDR6）抬 peak，见 A9。并发请求数↑、随机访问延迟↓、有效利用率↑；粒度变细 vs 每 bit 协议开销（LPDDR6 288-bit 突发仅 256-bit 有效，§1.1）。"更独立"的收益边界由 A7 三判据划定——真收益来自刷新错峰、命令并发与电源域分离，而非"看起来独立"。

**A9 展开：提高的是 peak 还是有效利用率？——三个维度分开回答**

- **"更多"**：peak 与效率**同时**受影响，取决于总引脚是否增加——HBM4 16→32 通道（引脚 1024→2048）→ peak ×2（vs 3E 为 ×1.67，基线速率还回落 9.6→8G）；DDR5 1×64→2×32（引脚不变）→ peak 不变；LPDDR6 die 内 1×16→2×12 + 速率↑ → peak ×1.5。效率侧：命令域越多，随机负载排队越短，delivered/peak 越接近 1。
- **"更窄"**：不直接动 peak（总量决定），但它是**高频与细粒度的前提**——宽总线跑不了单 pin 高速率（SI/skew 随位宽恶化，§1.1），拆窄后才敢推 12.8~14.4G；预取增大后 64B 对齐也只有拆窄才成立（A4）。
- **"更独立"**：纯 efficiency 侧——命令并发（A6）、刷新错峰、电源域分离（A5/A7）；独立度不全则收益打折（HBM PC，A5/A6）。
- **排队视角** [INFERENCE]：1 个命令域 = 单服务台排队（随机负载等待随负载率非线性上升）；N 个独立域 = 负载分流，同 peak 下随机负载的交付带宽与延迟显著改善——**顺序单流几乎无收益**（一条通道足够）。
- **三个反向项**（避免一边倒）：① 每通道流量变稀 → open row 局部性摊薄，对 row-buffer 型负载是负项；② 协议开销不降反升：LPDDR6 命令 2 周期/ACT 4 周期（A8）、288-bit 突发仅 89% 有效（§1.1）；③ 刷新与激活的窗口竞争随实例数增长（A2 墙 3 / A3 postpone 预算）。
- **结论口径**：这一代演进**主要买的是有效利用率（并发/随机负载），peak 的提升只来自"更多"且需要引脚同步增加**；单流顺序负载基本无收益，热点映射不当甚至倒退（A11 伏笔）。

### 1.3 应用定位（纲领 O5）

- **HBM**：AI 加速器/GPU 的片旁带宽引擎（near-compute），2.5D 中介层互装；持续满带宽型负载。
- **DDR5**：服务器/PC 主存；容量、单位成本与系统 RAS（side-band ECC、刷新管理族、模组生态）优先。
- **LPDDR5/6**：手机/边缘 AI/汽车主存；带宽/功耗比与多频点电源管理优先；LPDDR6 CAMM2 补上可换装性。

【核心速答】三种容量路线本质是 带宽密度 / 容量天花板 / 灵活性 的取舍：HBM 设计期锁死但带宽密度最高；DDR5 灵活且最便宜，但速率与延迟为可插拔买单；LPDDR 焊死容量小，LPDDR6 用 x24/x12 通道配置解耦容量与带宽。

## 2. 架构与通道组织

### 2.1 HBM3/4：stack → channel → pseudo-channel → DWORD（纲领 A5~A7 / A11~A12）

**层级结构（JESD238 §3.1 / JESD270-4 §2）**

- **Channel（通道）**：64-bit 数据 I/O；HBM3 16 通道/stack；通道间独立时钟、无需同步。
- **Pseudo-Channel（PC，伪通道）**：每通道 2 个 PC；每 PC **32-bit DQ + 4 DBI + 2 接口 ECC bit + 2 SEV bit**（PC0=DQ[31:0]+DBI[3:0]+ECC[1:0]，PC1=DQ[63:32]+...）；PC 是**刷新/阵列时序状态的独立管理分区**（REFab/RFM 编码携带 PC 位——刷新以 PC 为单位；HBM4：阵列时序逐 PC 独立计时）。但**电源状态（PD/SR）是通道级**，不区分 PC——见下 A5 边界。
- **DWORD**：32-bit 数据切片（每 PC 1 个 DWORD）——de-skew/训练/修复的粒度；每 DWORD 一对读写选通（RDQS/WDQS）。
- **命令接口**：行/列**半独立**两条总线 —— 行总线 R[9:0]（10-bit）、列总线 C[7:0]（8-bit），可同时下发行与列命令（详见 3.1）。
- 页大小 1KB/PC（HBM4）；通道密度 3~16Gb；bank 数 16/32/48/64 随密度与 die 数变化。

**A5 重新确认：Channel + PC 两级的动机与边界**

- **Channel 级动机**：1024-bit 接口若做单通道，命令译码扇出、布线/凸点与调度耦合都不可行；拆成独立通道后每通道有独立 CA/CK/复位与自己的刷新状态（"each channel is independent… not necessarily synchronous"），请求间零时序耦合、调度自由度最大 [JEDEC]。
- **PC 级动机（"pseudo" 的含义）**：通道内阵列再对半分（2×32-bit DQ），两 PC **共享通道的 CK 与行/列命令总线**（省掉第二套命令接口与引脚），但各有独立 bank 阵列/译码/时序状态；**刷新以 PC 为单位**——真值表中 REFab/RFMpb/RFMab 编码携带 PC 位（REFab = 刷"该 PC 的全部 bank"）[JEDEC p49 Table 30]。
- **边界（重要修正）：电源管理是通道级，不区分 PC**——真值表中 **PDE 的 PC 位为定值 H、SRE 为定值 L、PDX/SRX 为 H**（地址位 Don't Care，Table 30 NOTE 4）；SRE 前提原文（§6.3.4.2）："only allowed when all banks in **both** pseudo channels are precharged with tRP satisfied"。物理因果 [PHYSICAL-EXPLANATION]：PC 的独立性止步于"**有时钟的域**"（阵列/译码/刷新/时序状态）；PD 期间 CK 可停止、SR 无外部时钟——时钟都没了的领域，独立 PC 状态机无处安放，只能通道级同步。这也是"刷新做到 PC 级（逐 bank 打命令必须有时钟）、而省电态做成通道级"的原因。
- **HBM4 保持 ch-2PC 同构**：通道翻倍（16→32）走位宽而非核心提速，控制器对象模型（独立 64-bit 命令域 × 各 2PC）不变 [INFERENCE]。对照 A4 通道位置三级对照：HBM 两级结构 = die 内命令域 + 阵列分区；DIMM 分组（DDR5）与 die 内多通道（LPDDR6 SC）各有取舍。

**HBM4 的关键变化（B2）**

1. 通道 16→32：每 die 8ch×2PC，**4 die 凑满 32 通道**；stack 高度 4/8/12/16-die。
2. **通道数与容量/bank 并行度解耦**：JESD270-4 原文——"HBM4 requires 4 DRAM dies to support 32 channels. Additional DRAM dies beyond 4 add additional capacity, SIDs and additional banks per pseudo channel"（每 die 8ch×2PC，4 die 凑满 32 通道，Figure 1）。加 die 的本质是 **bank 维度扩展**：Table 4 的 Bank Address 字段随堆叠高度从 BA[3:0]（16 banks/channel）长出 SID[0]（32）再到 SID[1:0]（48/64；Table 5 中 bank 分 A~H 八个 BG 组，48B 档 SID[1:0]=11 invalid）——**SID 不是 CS 式选择子，而是并入 bank 地址的高位**，RA[13:0]/CA[4:0]/页大小 1KB 全部不动。因此：**峰值带宽不变**（32ch×速率由接口决定，4 die 与 16 die 相同），**有效性能可提升**——每通道可开 row 数最高 ×4，row miss 率靠加 die 压低。
3. 对调度器：64 个 PC 的状态表/队列/训练状态机实例翻倍；channel-first 地址映射把相邻 cache line 打散到 32 通道，防止单通道热点吃掉翻倍的带宽。

【核心速答】HBM 记三层：**通道管命令接口与电源状态（命令并发；PD/SR 通道级同步、不区分 PC）、伪通道管刷新与时序分区（REFab 带 PC 位）、DWORD 管训练修复**。每 PC 数据出 32-bit 时还带 DBI、接口 ECC 和 SEV 严重度位。HBM4 通道翻倍到 32 且通道与容量解耦——调度器横向复制扩状态表，地址映射要防通道热点；加 die = 加 bank（SID 并入 bank 地址），峰值带宽不变、row hit 率提升。

### 2.2 DDR5：DIMM → 子通道 → Bank Group（纲领 A4）

- 每 DIMM **2 个完全独立子通道**：各 32-bit（ECC 模组 40-bit = 32 数据 + 8 side-band ECC）；各自 14-bit CA、CS、行列译码器、时序状态机与刷新相位，可同时执行不同命令（一个在 tRFC、另一个满带宽读）。
- BG/bank：bank group 架构，16Gb 档为 8BG×4B=32 banks/子通道 ⚠️（以厂商 datasheet 为准）；BL16。
- 激活侧 BG 时序（A2 锚点，JESD79-5B §4.6 原文）：ACT→ACT 间隔分两档——"**tRRD_S (short) is used for timing between banks located in different bank groups. tRRD_L (long) is used for timing between banks located in the same bank group**"；连续 ACT 另受 **tFAW（four activate window）**约束——"Consecutive ACTIVATE commands … restricted to a maximum of four within the time period tFAW"。列侧三家对照见 §2.3。
- 控制器利用：① cache line 级子通道交错，命令级并行 ×2；② **刷新错峰**（两子通道 tRFC 相位错开，避免整条 DIMM 同时不可用）；③ 读写翻转（bus turnaround）按子通道独立优化；④ DFI/训练均为双实例。

**A4 重新确认：为什么拆成 2×32-bit 子通道——完整因果链**

> DRAM 核心频率十年平坦 → 提速率只能加大预取（DDR4 8n → DDR5 **16n**，JESD79-5B："uses a 16n prefetch architecture **to achieve high-speed operation**… a single 16n-bit wide, eight clock data transfer at the internal DRAM core"）→ 预取决定最短突发（BL16）→ 若保持 64-bit 通道，一命令 = 64bit×16 = **128B = 2 条 cache line，过取一倍** → 拆成 2×32-bit 子通道 → **32bit×BL16 = 64B 正对齐一条 cache line**，同时命令并发 ×2。BL 增大本身的收益：数据/命令开销比提升。[JEDEC 预取原文 + PHYSICAL-EXPLANATION 算术]

- **精确化两点**：① DDR5 并未完全砍掉 chop——"a burst length of sixteen **or a 'chopped' burst of eight**"（BC8 OTF 保留，主粒度仍是 BL16）；② **"sub-channel" 在 JESD79-5B 正文 0 命中**——标准只定义单通道颗粒（x4/x8/x16，各自 CA[13:0]/CS_n），双子通道是 **DIMM 级组织**（4 颗 x8 或 8 颗 x4 归一组、共享子通道 CA 布线，RDIMM 由 RCD 分组驱动）。引用时注明：说"子通道"是系统组织，不是标准术语。
- **通道位置三级对照**（强化 §2.4 判据）：通道在 **die 外**（DIMM 分组）→ DDR5；通道在 **die 内**（一 die 多通道）→ LPDDR6 SC、HBM4 8ch/die；通道在 **stack 内跨 die 共享总线**（TSV + SID）→ HBM3/4。判据不变：**独立 CA 在哪一层出现，并发就在哪一层发生**。

**为什么不能无限加 Bank——一项收益与四堵墙（纲领 A2 / D3~D6 落点）**

- **收益**：bank 是最小并发粒度（每 bank 只能 open 一个 row）→ bank 越多，可同时 open 的 row 池越大 → row miss 率下降。HBM4 加 die 把每通道 bank 从 16 拉到 64，买的正是这个（§2.1）。
- **墙 1：供电——限速（tRRD）+ 限额（tFAW）**。激活是全阵列最高电流操作：字线升压（如 DDR5 的 VPP 轨）、位线与单元电容电荷共享、SA 级联放大并恢复写回；并发激活叠加 di/dt 与 IR drop。协议用 tRRD 限制"激活速率"（bank 间错峰），用 tFAW 限制"滚动窗口内最多 4 次激活"的配额——**限额 ≈ 4×限速再加 ns 余量**。JEDEC 自己的 IDD 测量模式（如 Table 311 IDD7）就是按 tRRD_S/tFAW/tRCD 排 ACT 的——被限的正是激活电流 [JEDEC 排布 + PHYSICAL-EXPLANATION 因果]。注意职责分层：单 bank 内激活流程时长由 tRCD/tRAS/tRP 描述，tRRD 只管 bank 间错峰；而 tRRD_L > tRRD_S 的 S/L 之分，除电流外还要"同 BG 内 bank 共享阵列外设/局部供电子网、跨 BG 资源独立"来解释——与 §2.3 列域同 BG 惩罚同根源。
- **墙 2：面积与布线**。每 bank 一套独立的行译码/字线驱动/SA 阵列（SA 占阵列核心面积大头），bank 越多，这些电路、金属布线与 RC 延迟线性增长 [PHYSICAL-EXPLANATION]。
- **墙 3：刷新与激活抢同一个窗口**。刷新总带宽占用由**容量**决定（每行 8192 次/32ms，tRFC 随密度涨，LPDDR5 Table 235：tREFW=32ms、R=8192、tREFI=3.906µs、tRFCab=130~380ns）；bank 数决定刷新的**粒度与调度形状**——REFpb 命令速率 ∝ bank 数（tREFIpb=488ns，每条只停 1~2 bank，可 postpone/pull-in ±9×tREFIe），但**刷新命令与激活共用 tRRD/tFAW 窗口**：HBM3/4 刷新表 NOTE 1 "tFAW parameter must be observed as well"、REFpb（不同 bank）走 tRRD；LPDDR5 滚动窗口原文把 REFpb 计入。bank 无限多 → 刷新命令与激活在窗口内无限竞争，控制器还要维护 per-bank 刷新债 [JEDEC]。
- **墙 4：IO 复用封顶**。列到 DQ 的数据通路不随 bank 数增长——bank 多的收益封顶在 row hit 率，超过后只付面积、布线与调度成本 [PHYSICAL-EXPLANATION]。
- 数值锚点：DDR5 tRRD_S = 8nCK、tRRD_L = Max(8nCK, 5ns)、tFAW(1K) = Max(32nCK, 20~16ns)、tFAW(2K) = Max(40nCK, 25~20ns)（Table 318；2K 页窗口更宽——页大小进激活预算）；LPDDR5 tRRD = max(10ns, 2nCK)、tFAW = 40ns；HBM3/4 的 ACT 与 PER BANK REFRESH 共用 tRRDS/tRRDL 一张表，且同表紧挨着定义 **RAA（Rolling Accumulated ACTIVATE count）**——限流（供电）与防行锤（激活计数）同源，见 §6.4。

### 2.3 LPDDR5/6：BG 架构与 x24/x12 效率模式（纲领 A1 / A8 / O8）

- **LPDDR5**：16 banks / 4BG×4B，BL16；调度上区分跨 BG（短时序）与同 BG（长时序）的列命令间隔，BG-aware 排序（把连续请求按 BG 交织）直接抬高总线利用率；per-byte WCK/RDQS。
- **LPDDR6（JESD209-6 §2.2.2）**：x24 Normal Mode = **2 个 Sub-Channel（SC0/SC1）**，每 SC 含 12DQ+RDQS_t/c + WCK_t/c + 4 CA + CS + CK_t/c；每 SC 4BG×4B = 16 banks；**x12 Dynamic / Static Efficiency Mode**（§7.8.29）重构子通道配置以提升引脚/容量效率，且支持 x24 die 与 SEM die **混装**（Mixed Packages）。**命令编码代价**：每条命令 **2 个 CK 周期**（CA[3:0] DDR + CS，Table 254 NOTE 1）；ACT/MRW 需两条命令（ACT-1→ACT-2，共 **4 周期**，夹在 tAAD 窗口内，NOTE 4）——CA 7→4 根的代价是命令带宽减半。
- 突发：BL24/BL48（12n/24n prefetch）；BL24 在 12-DQ SC 上 = 288-bit（256 数据 + 32 非数据），I/O 侧为 12 个 12-bit 半 WCK 周期传输；**BL/n（Effective Burst Length）** 定义不同模式的有效突发，同 BG tCCD 随 BL 取 6/8/12/24nCK。

**三家 BG 时序对照（S=Short=跨 BG / L=Long=同 BG；DDR5/HBM4 命名统一，LPDDR5 的 BL/n 语义同方向）** [JEDEC]

| 列域命令间隔 | DDR5（BL16） | HBM4（Table 6） | LPDDR5（BL16，CKR 4:1，Table 330） |
|---|---|---|---|
| 跨 BG R2R | tCCD_S = 8nCK（=突发占用） | tCCDS | BL/n_min = 2tCK |
| 跨 BG W2W | tCCD_S_WR = 8nCK | tCCDS | — |
| 同 BG R2R | tCCD_L = 8~16nCK（MR13 Table 29 按速率档编程） | tCCDL（R2R 亦可标 tCCDR） | BL/n_max = 4tCK |
| 同 BG W2W | Max(32nCK, 20ns) | — | tCCDMW = 4×BL/n |
| W→R | 同 BG Max(16nCK,10ns) / 跨 BG Max(4nCK,2ns) | tWTRS / tWTRL | — |
| ACT→ACT | tRRD_S / tRRD_L（§4.6） | tRRDS / tRRDL | 同方向 |

- 统一物理图像 [PHYSICAL-EXPLANATION]：**跨 BG 短**——各 BG 的阵列侧（sense amp + local I/O gating）独立，突发可背靠背拼满共享 DQ；**同 BG 长**——上一列操作仍占用同一 BG 的阵列通路，须等阵列列周期（速率越高越长）。**DQ 引脚永远共享，BG 独立的是阵列侧资源。**
- DDR5 tCCD_M（同 BG 跨 bank）只存在于 §13.3 速度档表：3200~4000 档 =tCCD_L（三级合一，此时 S=M=L=8nCK）；高速档展开为中间层 max(8nCK, ~4ns)——构成 跨BG < 同BG跨bank < 同BG同bank 三级。3DS 表同族参数带 _slr/_dlr 后缀（如 tCCD_S_slr = 跨 BG 同 logical rank = 8nCK）。
- LPDDR5 Table 330：NOTE 1 "BL/n is minimum column to column cycle time, tCCD(min)"；NOTE 6/7：同 BG=BL/n_max、跨 BG=BL/n_min。16B Mode（无 BG）BL16 也是 2tCK——跨 BG 交织只是把同 BG 惩罚恢复到总线极限。
- 【引用警示】JESD79-5B 的 From/To 多列表（如 p173-175）PDF 文本提取后行会错位，参数与 BG 归属的对齐以**图注散文**（Figure 52："back to back BL16 writes to same bank group using a timing of tCCD_L_WR"）与**速度档定义行**为权威。

**D1 块：为什么出现 Bank Group**

- **前提（C12 判据承接）**：阵列时序 ns 守恒、接口时序 nCK 缩放 → **DRAM 核心频率与接口频率的剪刀差逐代拉大**。
- **瓶颈的诞生**：单一数据路径下，连续列命令必须等内部阵列列周期（ns 守恒）——折算成接口拍数随每代速率**越来越多**（DDR5 实证：tCCD_L 由 MR13 按速率档编程 **8→16 nCK**，Table 29）→ I/O 总线出现气泡，数据带宽被阵列周期钳制。
- **BG 的解法**：**物理分组 + 每组独立数据路径与 IO 门控** → 跨 BG 的列命令可背靠背拼接（**tCCDS = 突发占用**，列流 100%），同 BG 必须等内部周期（**tCCDL = 阵列列周期**）——**组间流水化**。证据链：LPDDR5 Table 330（同 BG BL/n_max=4tCK vs 跨 BG BL/n_min=2tCK）+ DDR5 Table 29 + HBM4 Table 6（三家同构，D2 已核）。

### 2.4 对比小结：调度粒度与并行度（纲领 A6 / A7 / O1）

| 协议 | 独立命令流 | 电源/刷新管理粒度 | 训练/修复粒度 |
|---|---|---|---|
| HBM3/4 | 16/32 通道（行/列双总线） | PC（HBM4 达 64 个） | DWORD（32-bit） |
| DDR5 | 2 子通道/DIMM × 槽数 × rank | 子通道/rank | per-pin/per-DQ（DFE/DCA/Vref） |
| LPDDR5/6 | 4~8×16-bit 通道 / x24=2×SC | 通道 | per-byte |

【核心速答】判别"独立通道"的标准是**有没有独立 CA**：DDR5 子通道有（两个命令流）；HBM PC 没有（共享行列总线，只分刷新/时序状态——电源状态是通道级，见 A5）；LPDDR6 SC 自带 CS/CA/CK，性质更像 DDR5 子通道。判据升级为三条（CA 归属 / 时钟电源域 / 命令带宽共享），见 §7.5 对比题 4。**A7 主判据：独立 CA 归属**是最重要的一条——命令域独占决定能否有独立命令流；时钟/电源域与命令带宽共享是辅助判据（HBM PC：数据总线独立但 CA 共享 → 非真通道；LPDDR6 SC 三条全过 → 真通道）。

### 2.5 Rank 与 SID：同一扩展问题的两种答案（纲领 A1）

**Rank 的定义与语义**

- **定义**：同一 CS 选通、同时响应命令的一组颗粒 = 一个 rank [JEDEC]（DDR5 命令真值表 Note 8：CS_n 第二拍电平控制 "non-target ranks" 的 ODT——rank 即 CS 选通的目标组）。
- **rank 间共享同一组 CA 与 DQ**（引脚不随 rank 增加）[JEDEC]：DDR5 的 MRW "broadcast across all logical ranks"（命令总线共享，§3.4.2）；LPDDR5 §7.2.1.6 "Rank to rank WCK2CK Sync"——两 rank 分时使用同一 WCK/DQ，切换需排序（tWCKPST/tWCKPRE 交接）。
- **代价 = R2R 时序约束的来源**：共享总线上的 ODT 切换、读写翻转、WCK 重同步；3DS 多 logical rank 还须**错峰刷新**限制峰值刷新电流——"tRFC_dlr / tRFC_dpr ≈ tRFC_slr/3"（JESD79-5B §4.13.5）[JEDEC]。
- **各家形态**：DDR5 1R/2R（DIMM 承载 CS 分配与驱动，2R 的时钟/CA 负载由 RCD 缓冲 [VENDOR/INFERENCE]）；LPDDR5/6 至多 2 rank（封装内 die-stack，无 DIMM 位置 [INFERENCE]）；**HBM 无 rank**（JESD238 全文无 "Rank"）——多 stack 共享通道总线时以 SID 选择，且 HBM4 的 SID 已并入 bank 地址（§2.1 Table 4），与 rank 的 CS 分时语义不同。

**为什么 rank 与 HBM4 加 die 是同一件事**

- 都是"**在同一条通道接口后面堆容量、不动带宽**"：DDR5 1R→2R 容量翻倍、峰值带宽不变（代价是 R2R 翻转与错峰刷新）；HBM4 4→16 die 容量 ×4、峰值带宽不变（收益是 bank 数 16→64 → row hit 率提升）。[INFERENCE]
- 加带宽的路线只有加接口：DDR5 多 DIMM/多通道横插、HBM 多 stack、LPDDR 多通道——A1 各层中**只有 Channel 层真正扩带宽**。

【核心速答】Rank = CS 维度的容量扩展：共享 CA/DQ、分时使用，代价是 R2R 翻转与错峰刷新；HBM 不需要 rank（通道已并行），HBM4 的 SID 是 bank 地址高位而非 rank。判据三分：**CS/分时复用 → rank；并入地址高位 → bank 扩展；独立 CA → channel**。

## 3. 命令与时序

### 3.1 HBM3/4：双命令接口与无 CKE（纲领 B5~B7）

**双命令接口（JESD238 §3.1.3，HBM3/3E/4 通用）**

- 每通道两条半独立总线：**行总线 R[9:0]（10-bit）+ 列总线 C[7:0]（8-bit）**，DDR 传输。
- 编码：**ACT = 1.5 cycle**（R[9:0]，CK 双沿锁存）；其它行命令 half-cycle（PDE/SRE 为 1 cycle）；**列命令 1 cycle**（C[7:0]，bank/PC/SID/列地址同拍携带）。
- 效果：ACT/PRE 可与 RD/WR **同窗口并行下发**——行管理开销被列数据流掩盖，这是 HBM 短突发（BL8）仍能维持满带宽的调度基础。
- 细节：REFRESH 需在列总线上垫 CNOP（除非列命令发给另一 PC）；行/列总线各有重映射表（§6.7.1）。

**无 CKE 的低功耗（HBM3/3E/4 与 LPDDR5/6 同为无 CKE 设计）**

- HBM：低功耗状态经**命令**进入/退出（PDE/SRE），**粒度是通道级**——真值表中 PDE/SRE 的 PC 位为定值、不区分 PC（§2.1 A5）；PC 级独立的是刷新与时序状态。
- 控制器责任：进低功耗前排空在飞命令、进出时序由内部定时器管理、**唤醒延迟显式建模进 QoS**（突发到达时的唤醒开销 = 延迟毛刺，需预测空闲窗口提前唤醒）。
- 训练影响：CA 无 CKE 门控可用，命令路径训练走独立机制（HBM 经 IEEE 1500/MISR 体系；LPDDR 走 CBT/CA Training）——两个协议殊途同归：**命令路径的可靠性都要专用训练机制**。

【核心速答】HBM3 起每通道行 10-bit/列 8-bit 两条总线，ACT 1.5 拍、列命令 1 拍，行/列同窗口并行——行开销被列流吃掉。CKE 删除后低功耗全靠命令+MR，控制器要自己做排空、定时和唤醒预测。

**B5/B6 重新确认：为什么行/列分总线、调度器怎么变**

- **B5 根因（引脚经济学换轨）**：3D 堆叠 + TSV 把"增引脚"的边际成本降了一个量级（B1 对照路线），每通道养得起两条专用总线——行总线 R[9:0] 专管 ACT/PRE/REF/RFM/PDE，列总线 C[7:0] 专管 RD/WR/MRS。
- **量化论证（列效率为什么能到 100%）**：**tCCDS = 2 nCK = 4 WCK = BL8 突发占用**（Table 93："RD/WR bank A to RD/WR bank B command delay different bank group → **tCCDS = 2**"；同 BG tCCDL = Max(4, 2.5 ns/tCK)）——列流背靠背正好填满列总线；行命令若共享此总线必偷列拍。**精确化**：分总线消除的是常规行命令（ACT/PRE）的竞争；REFab 是例外（见下）。
- **REFab 的例外规则（§6.3.2.5 p60/页46 + NOTE 1 p61/页47）**：REF 命令拍列域必须垫 CNOP——"The REFRESH command also requires a CNOP command on the column command inputs C[7:0], unless the column command is for the other pseudo channel"；且 **NOTE 1："Only RNOP and CNOP commands are allowed after a REFRESH command until tRFCab has expired"**——REFab 造成整个通道的停顿窗口（NOTE 1 未按 PC 限定，字面为通道级；REFab 编码带 PC 位与该冻结的关系待深挖）。CNOP 的作用：让冻结拍显式为空、防译码误触发、保校验合法。**双 PC 的隐藏价值**：细粒度路径（REFpb/RFMpb，异 bank 走 tRREFD）与错峰调度才能填回这些空洞（连 O9）。
- **B6 调度器变化**：发射端口从"每拍 1 命令"变为"**每拍 1 行 + 1 列**"双端口（§7.1 A3 发射端口定义）；行命令树（ACT/PRE/REF/RFM/PDE）与列流（RD/WR）独立排队、无需行/列优先级仲裁；但 **timing checker 的跨域链照常约束**——tRCD/tRTP/tRTW 连接行决策与列决策，**总线独立 ≠ 时序独立**（A3 checker 分层的 B 组版本）；发射合法性由 Table 32 同拍配对规则约束（含 "Different PC, Any Bank" 列）。

**B7 重新确认：为什么 ACT encoding 往往比 PRE/NOP 复杂**

- **位预算定量表（JESD238 Table 30，p49）**：ACT 在 R[9:0] 上占 1.5 周期（R+F+R 三个沿，每沿 10 bit = 30 bit 槽位）——R 拍：opcode 前缀(L,H,H) + **PC(1) + SID(2) + BA(4)**；F 拍：标记(H,H) + **RA[14:8]**；R 拍：标记(H,H) + **RA[7:0]**。**ACT 载荷 ≈ 24 bit**；对比 PRE ≈ 7 bit（PC+BA+AB）、NOP = 0。**命令编码复杂度 = 载荷宽度的函数**——PRE/NOP 半拍命令，ACT 三拍命令。
- **1.5 拍的由来** [PHYSICAL-EXPLANATION]：1 拍（10 bit）/2 拍（20 bit）都装不下 24 bit，3 拍 = 30 bit ✓；HBM 命令以半拍为粒度发射，1.5 拍 ACT 结束后总线在下一个半拍即可复用（2.0 拍会浪费半拍）——**1.5 = ceil(24/10) × 半拍粒度，无对齐浪费**。
- **复杂度的三重代价**：① NOTE 9 总线冻结（"another command is not allowed during ACT command"——行/列双总线 1.5 拍内都不可用）；② 三沿锁存对齐（CA 训练须保证跨沿采样对齐，连 I 组 MISR 回读验证）；③ 奇偶校验按 ACT 全 30 bit 计算（MR0 OP6 启用，p53）。
- **跨协议对照："行地址最大"是普遍规律**——DDR5 ACT 同样 2T（两拍 28-bit，载荷含 **RA[17:0] 18-bit 行地址** + BG/Bank，Table 311 位宽直证）；换算回 B1 统一公式：DDR4 时代 18-bit 行地址走专用 A[17:0] 引脚（1T），DDR5 砍到 14 CA 后只能 2T——**ACT 复杂化是引脚复用的直接后果**；HBM 行/列分总线后列命令 1 拍就够（复杂度集中在行域）。
- **密度演进 → B10 伏笔**：HBM3 行地址 8/12/16Gb 用 RA[12:0] → 24/32Gb 用 RA[13:0]（p20 地址表），**HBM4 已预留 RA15**（p254 DEVICE_ID NOTE 2）——行地址持续增长而 CA 根数不涨，ACT 位预算持续吃紧 → B10。

**B8 重新确认：Command bandwidth 何时成为真实 bottleneck**

- **总判据**：需求侧命令速率逼近/超过供给侧、且 AC timing 不是主要限制时，命令带宽即真瓶颈——量化形态：**时序窗口内有 ready 命令但 CA 槽位排满**（A10 的 Controller/CA 层瓶颈形态）。注意 ACT/PRE 既是命令又是时序负担，row miss 密集时两者同时逼近上限；"纯命令带宽瓶颈"出现在 **hit 率高、粒度小、REF/RFM 占空高**的组合（时序裕量有余而 CA 排满）。
- **需求侧（什么推高命令速率）**：① 访问粒度——64B 粒度下 1 TB/s = 16 G 命令/s（纯列命令基线），粒度越小命令越多；② **row miss 放大**——全 miss = ACT+RD/WR+PRE（≈3 条/请求），hit 多 = ACT+N×RD/WR+PRE（摊薄为 2+1/N 条）——**row hit 率就是命令放大率的倒数**（连 B9 的 28.6:1）；③ REF/RFM 占空——REFpb 命令速率 ∝ bank 数（tREFIpb，A2 墙 3），REFab 期间整通道冻结（B5 NOTE 1）；④ ACT 编码膨胀——DDR5 2CK、LPDDR6 ACT-1/2 共 4CK（B7），行地址增长直接吃命令带宽。
- **供给侧（CA 根数×沿数÷命令位宽，B1 公式反演）**：DDR5 14 CA / 每子通道每 2T 拍 1 条命令；HBM3 = R[9:0]+C[7:0] **18 根、每拍 1R+1C 双槽**（列域另受 tCCDS=2CK 限速）；LPDDR6 每 SC 4 CA、命令 2 周期、ACT 4 周期——三者供给相差一个数量级。
- **算例** [INFERENCE]：1 TB/s、64B 粒度、全 miss → 3 命令/64B = **48 G 命令/s**；DDR5 单子通道 ≈ 1.2 G 命令/s（4800 档 2T）×2 子通道×N DIMM——需求与供给同数量级掰手腕，这就是子通道化（A9）与请求合并成为标配手段的原因。
- **缓解手段与权衡**：① 请求合并/更大访问粒度（直接降需求）；② 连续 page hit（放大率降到 2+1/N）；③ 子通道独立 CA（增供给，A9）；④ **auto-precharge**（RDA/WRA 把 PRE 并进列命令，每次 miss 省 1 条行命令——代价是 bank 随即关闭、牺牲后续 row hit：open-page vs close-page 的策略权衡，D10 伏笔）。

### 3.2 DDR5：CA 总线与 DFI 命令编排（纲领 B1~B4 / B8）

- 每子通道 **14-bit CA**。**1T（单周期）**：NOP / PRE / REF(REFab/REFsb) / RFM / MPC 等无地址承载命令；**2T（双周期）**：ACT / RD / WR / MRS 等带地址命令——两拍共 28-bit（第 1 拍 opcode+BG/bank+行地址高位，第 2 拍列地址/行地址余位）。
- 动机：CA 位宽从 DDR4 的 20+ 根压到 14 根（子通道化使引脚预算减半），本质是"引脚换拍数"；列命令第 2 拍带列地址，保持 BL16 粒度。
- DFI 侧：2T 命令**原子不可拆**；相邻命令 CA 编码无位冲突；训练/校准走 **MPC**（Multi-Purpose Command）承载子命令；模式寄存器为 256 个 8-bit（CW 位区分 DRAM 与 RCD 寄存器组）。
- 对照记忆：LPDDR5 是"7-bit CA 但 DDR 传输"，DDR5 是"14-bit CA 但部分命令 2T"——同一命题（引脚预算 vs 命令带宽）的两种解。

【核心速答】DDR5 每子通道 14-bit CA：无地址命令单拍，ACT/RD/WR/MRS 双拍共 28-bit；DFI 里 2T 是原子操作，训练命令走 MPC。

**B1 重新确认：DDR 为什么长期复用 Command/Address 总线**

- **复用的两层含义（演进时间不同）**：① **地址分时复用**（行/列地址分拍送上同一组引脚）——自 SDRAM 第一代如此，是 DRAM 引脚经济学的起点：地址引脚数不随"行位宽+列位宽"线性增长；② **命令编码复用**（控制线并入 CA）——演进很晚：SDRAM~DDR4 保留专用 RAS_n/CAS_n/WE_n（DDR4 约 20+ 根 CA/控制线 ⚠️），**DDR5 才彻底删除——'RAS_n'/'CAS_n'/'WE_n' 在 JESD79-5B 全文 0 命中**，CS_n 也成为命令编码的一部分（"CS is part of the command code"，p37）[JEDEC 0 命中考据 + ⚠️ DDR4 结构待核]。
- **为什么能长期复用（引脚换拍数）**：引脚是成本与 SI 的硬约束；密度/带宽每代翻倍而 CA 引脚近似恒定甚至减少（DDR4 ~20+ → DDR5 14），代价转移到命令周期数（2T，B3/B4）——并行转串行。
- **两条不复用的对照路线**：HBM 行/列**分总线**（并行度高、延迟低），引脚爆炸由 TSV/3D 堆叠/中介层形态"买断"（B5 根差异）；LPDDR6 CA 4 根、命令 2 周期/ACT 4 周期——极致引脚效率（A8）。
- **统一公式**：CA 引脚预算 ≈ 命令带宽需求 × 命令周期数。各代工作点：DDR4（20+ / 1T）⚠️ → DDR5（14 / 2T）→ LPDDR5（7 / 1T）→ LPDDR6（4 / 2T + 双命令 ACT）；HBM 不在此预算内（分总线 + 堆叠形态）。
- **B2 收口（CA pin 少的三条好处）**：① 引脚成本与封装走线简化（统一公式左侧直接变小）；② SI 难度下降——同时翻转的 CA 线数减少，SSO/di/dt 与 skew 匹配组变小（A8 Physical cause 层）；③ CA 摊薄效率——更多通道/PC 共享更少的命令引脚（HBM 18 pin 服务 2 PC）。
- **B3 收口（pin 少 → 命令周期多）**：每拍可承载的命令+地址位 = CA 根数 × 沿数；根数减少后，同一条命令的位流必须拆到更多拍才能凑齐位宽——DDR5 2T（两拍共 28-bit 承载 ACT 的行/列地址），LPDDR6 16-bit 命令 / 2 周期、ACT 两命令共 4 周期（Table 254）。**引脚数 × 拍数的乘积必须 ≥ 命令位宽**，这是统一公式的直接推论。
- **B4 收口（多周期命令在交换什么资源）**：交换的是**恒定的引脚/SI 预算 ↔ 命令延迟与命令带宽**——把一次性的引脚成本转成每次访问的时间成本；DFI 侧 2T 原子不可拆，编码复杂度（1T/2T 区分、相邻命令位冲突避免）转移给控制器命令编码器——四部件之外的第五项软成本。

### 3.3 LPDDR5/6：三时钟域与 CKR（纲领 H1~H7）

- 时钟域：**CK**（低频命令时钟，CA 7-bit DDR）+ **WCK**（写数据时钟）+ **RDQS**（读选通，per-byte）。数据速率 = 2×WCK 频率。
- **CKR = WCK:CK 分频比**（JESD209-5B）：
  - **CKR=2:1 → 533~3200 Mbps**；
  - **CKR=4:1 → 533~6400 Mbps**（>3200 必选 4:1）；CKR 可经 MRW 动态切换（§7.6.7）。
- 典型值：LPDDR5-6400 → WCK 1600MHz、CK 400MHz（4:1）。
- **WCK2CK Leveling**（§4.2.5，即 LPDDR4 write-leveling 的演化）：WCK 与 CK 异步，需锁定 DRAM/PHY 内同步 FIFO 的写读指针——进训练模式 → 施加已知 pattern → per-byte 扫 WCK 相位 → FIFO 指针锁定；**每次 DFS 后必须重做或从 training set 恢复**。
- 控制器实现：CK/WCK/DFI 三异步域之间放弹性 FIFO；WCK 门控与突发对齐逻辑直接决定读写延迟（LPDDR5 读延迟比 LPDDR4 大且随 CKR 变化，QoS 需按档位建模）。

【核心速答】LPDDR 是三时钟域：命令走低速 CK（CKR 4:1 覆盖 533~6400，2:1 只到 3200），数据走全速 WCK 按 byte 门控。WCK 与 CK 异步，开机靠 WCK2CK Leveling 锁 FIFO 指针，每次变频都要重做——这是 LPDDR 控制器比 DDR 多出来的核心机制。

### 3.4 关键时序参数对比（纲领 C1 / C5~C12 / B9）

| 参数 | LPDDR5 | DDR5-8400 | HBM4-12000（CK=3GHz = rate/4） |
|---|---|---|---|
| tRCD | max(18ns, 2nCK) | 17.5ns | **tRCDRD 57CK = 19.0ns / tRCDWR 43CK = 14.3ns** |
| tRP | tRPpb max(18ns, 2nCK) | 17.5ns | 45CK = 15.0ns |
| tRAS | max(42ns, 3nCK) | 32ns | 90CK = 30ns |
| BL | 16 | 16 | 8 |

- **绝对值同一量级**（都由阵列物理决定：wordline 驱动 + sense amp 建立/恢复）；**相对值差异巨大**——折算"行开销 ≈ 多少个 burst"：HBM4 ≈ **28.6 个 BL8**、DDR5-8400 ≈ 9.2 个 BL16、LPDDR5-6400 ≈ 7.2 个 BL16。HBM 接口越快，行开销相对越重 → 越依赖 bank 并行 + 行/列并行命令接口（3.1）摊薄。
- **tRCD 拆分 RD/WR 从 HBM3 即有**（tRCDRD/tRCDWR，HBM3/4 时序组同名），写路径更短（43CK vs 57CK）。
- **约束形式差异**：LPDDR5 用 max(ns, nCK) 双约束；HBM 用纯 CK 约束——速率上升时 ns 自动收缩、逼近阵列物理极限，这是高速产品档的良率敏感点。
- **调度优先级通用骨架**：刷新（含 RFM/ARFM/PRAC 配额）> 写排空（防写饥饿）> 读 QoS > 预充电合并/激活调度。各协议附加维度：HBM = per-PC 状态错峰 + 行列并行窗口；DDR5 = 双子通道错峰 + side-band ECC 读改写占用；LPDDR = DFS 窗口 + 温度刷新倍率（2x/4x）。

【核心速答】tRCD/tRP/tRAS 绝对值三家都在 14~19 / 15~18 / 30~42ns，由阵列物理决定；但 HBM 突发最短，行开销相对占比最大（≈29 个 BL8），所以 HBM 最依赖 bank 并行。注意 tRCDRD/tRCDWR 拆分从 HBM3 就有，且 HBM 用纯 CK 约束、LPDDR 用 max(ns, nCK)。

**C1/C2 展开：tRCD 的物理过程——感知 vs 覆盖** [PHYSICAL-EXPLANATION]

- **五步链**：① 位线预均衡到 VDD/2（PRE 的遗产——均衡是电荷共享可检测的前提，残余差分会污染判决，连 C5）；② 行译码选中字线；③ 字线升压到 VPP（高于阵列电平，DDR5 独立 VPP 轨/片内 charge pump）——确保 fF 级单元晶体管**完全导通**而非半开；④ **电荷共享**：单元电容 ~10-20fF vs 位线寄生 ~100-250fF（共享比 1:10~20）→ 位线只摆动 **~100mV 量级**（这就是必须要有 SA 的原因）；⑤ SA（交叉耦合反相器正反馈）把 ~100mV 拉到轨到轨。
- **C2 答案——读的本质是感知，写的本质是覆盖**：tRCDRD = ACT 到"SA 差分建立到可安全列选通"——列选通会把选通管电容挂到 SA 节点，**放大未完成时挂载会拖慢/破坏放大过程**，读到未定态（亚稳态）；tRCDWR = 写驱动（强驱动电路）达到"可覆盖电平"即可强制翻转 SA，无需放大到轨 → **tRCDWR < tRCDRD**（HBM3 43CK vs 57CK，写早 ~25%，§3.4/C9 已核）。
- **伏笔（连 C3~C6）**：电荷共享是**破坏性读**——读即摧毁单元原值，SA 必须回写修复；修复驻留与关闭时序就是 tRAS/tRP 存在的根源。

**C5 + C3/C4 展开：tRP 三件事、tRASmin 修复驻留、tRASmax 的存亡**

- **C1 的晶体管级精化**：单元晶体管端子——**WL=栅极、BL=漏极、Cs=源极**；"字线升压到 VPP"的理由 = VPP > VDD+Vth，保证**无论存 0 还是 VDD** pass transistor 都完全导通（半开会削掉电荷共享幅度）。**差分参考结构**：SA 检测 BL 与 /BL 的差分（每根 BL 配对参考位线），两条位线都均衡到 VDD/2，电荷共享只发生在 open bitline、/BL 保持 VDD/2 作参考 → 差分 = ±ΔV/2。**写路径**：写 1 → BL 驱到 VDD → Cs 充至 VDD；写 0 → BL 驱到 0 → Cs 放至 0（经导通 pass 管）——"覆盖"的电路本质。
- **C5：tRP 的三件事（顺序关键）**：① **关闭字线**——WL 从 VPP 放到 0：修复值在 WL 关闭前已由 SA 保持期间写回 Cs，**关 WL 就是"落袋"动作本身**，此后 Cs 与 BL 断开、电荷重新封存；② **复位 SA**——交叉耦合反相器使能撤除、节点回到高阻预充态（释放破坏性读的占位）；③ **位线均衡**——EQ 把 BL 与 /BL 短接均衡到 VDD/2，为下一次电荷共享准备零基准（不均衡则残余差分污染下次判决）。tRP = 三件事全部完成的时间；PRE 命令只有半拍，**等的是内部过程**。
- **C3：tRASmin = 修复驻留**——SA 放大后的值必须回写 Cs（电荷共享已破坏原始电荷，不回写就真丢）；tRASmin ≥ tRCD（放大建立）+ 突发 + 回写余量，同时也是激活电流占空约束之一（A2 墙 1 延伸）。[PHYSICAL-EXPLANATION]
- **C4：tRASmax——现行标准已不定义**：**'tRASmax' 在 DDR5/LPDDR5/LPDDR6/HBM3/HBM4 五标准中全部 0 命中**。历史规范（LPDDR2/3 时代厂商 datasheet）定义 **≈9×tREFI** [PROJECT/⚠️ 旧标准待核]，动机：**防 open row 长期不关导致 REF 发不出去**（REF 需 bank precharge，HBM3 NOTE 2 同款要求）。**呼应观察** [INFERENCE]：tRASmax 的"9×tREFI"与现代刷新 postpone 预算的"9×tREFIe"（Figure 136/137，推迟 8 条第 9 条必执行）数字同源——都是"刷新调度灵活度外边界"的两种表述（一个约束行开放、一个约束刷新挪动）。现代协议删除它的原因：**控制器自管 REF 发送**（postponed/pull-in/FGR/per-bank 预算），标准层面无需 tRASmax——复杂度转移到控制器的又一实例（与 O11 同向）。

**C6/C7/C8 展开：tRC 生命周期与写/读特有的时序** [PHYSICAL-EXPLANATION]

- **C6：tRC = tRAS + tRP，由完整生命周期决定**——同一 bank 的 row 是**独占资源**：字线同一时刻只能驱动一行，位线同一时刻只能处于激活或预充电状态（互斥）。三段不可压缩：tRAS 不足 → 数据不能完全写回 Cs（修复中断）；tRP 不足 → 位线均衡不到 VDD/2（基准污染）；SA 未复位 → 残余电荷干扰下一轮判决。**逃避手段：多 bank 交织隐藏 tRC**（不缩短它）——bank 并行存在的第一性理由（连 A1/A2）。
- **C7：tWR 为什么是 write 特有**——读的回写（SA 放大 + 写回 Cs）由 **tRAS 驻留期内建覆盖**；写的覆盖是**额外动作**：写驱动器在列选通后强制覆盖 SA 和 Cs，必须持续传播到 Cs——需要 **tWR 从 WR 命令单独起算**保证（连 B8 的 auto-precharge 权衡：AP 合并 PRE 的前提是 DRAM 内部自 satisfy tRTP/tWR）。
- **C8：tRTP 为什么是 read 特有 + 为什么一般 tWR > tRTP**——列选通打开期间 SA 被挂载、数据正流向输出锁存，**PRE 会复位 SA 截断正在读出的数据** → tRTP = 数据从 SA 传到输出锁存 + 完成回写的最小间隔。**不对称的物理根源**：tWR 是"写驱动强制覆盖 SA"的**电流对抗重建过程**（外部强驱动 vs SA 正反馈对抗），tRTP 只是"数据飞行到锁存器"——故一般 **tWR > tRTP**（DDR5：tWR ≈ 30ns 量级 vs tRTP ≈ 7.5ns 量级）。→ 预答 D8（读写 turnaround 不对称）的一半。

**C12 收口：哪些 timing 受阵列物理限制、哪些受接口限制**

- **判据（决定因素，而非单位）**：**阵列物理限制**——受工艺、电压、温度、模拟电路决定，**单位 ns、基本不随频率变化**；**接口总线限制**——受频率、PCB、IO 设计、信号完整性决定，**单位 nCK、随频率变化**。
- **阵列物理清单（ns 级、跨代守恒）**：tRCD/tRCDRD/tRCDWR（C1/C2 电荷共享 + SA 建立）、tRAS（C3 修复驻留）、tRP（C5 关 WL/SA 复位/均衡）、tRC（C6 生命周期）、tWR/tRTP 的 ns 底（C7 覆盖传播 / C8 数据飞行+回写）、tRFC（全阵列行遍历，密度决定）、tREFI 的物理基底（~32ms 保持）。
- **接口清单（nCK 级、随速率缩放）**：tCCD_S/tRRD 的 nCK 部分（总线占用/激活配额）、tFAW 的 nCK 部分、BL 与突发占用、命令编码拍数（DDR5 2T、LPDDR6 2/4 周期，B 组）、tDQSCK/tDQSS 等 PHY 对齐量。
- **混合形式 max(ns, nCK)**：LPDDR 全家 tRCD/tRP/tRAS（如 max(18ns, 2nCK)——物理给下限、总线给对齐）、DDR5 tCCD_L/tFAW。**双保险语义**：ns 项保证"物理不许快"，nCK 项保证"总线不许省"（C10 呼应）。

**B9 收口（连 B8）**：行开销 28.6 : 9.2 : 7.2 的本质是 B8"row miss 放大"的极端形态——HBM 的短突发（BL8 = 32B/PC）使命令放大率对 miss 最敏感：行开销折算的 burst 数最多，row hit 率的边际收益也最大——这就是 HBM 调度器最重 bank 并行与行/列并行命令接口的量化原因。

**B10 重新确认：数据带宽↑而 CA bandwidth 不变——问题与出路**

- **问题面**：① B1 公式失衡——需求（请求数/s = 数据带宽÷粒度）线性↑，供给（CA 根数×沿数÷命令位宽）冻结 → **有效带宽上限 = min(数据带宽, 命令带宽×粒度)**，命令带宽成为钳制项（B8 判据触发）；② 行地址持续增长（HBM4 预留 RA15，B7）→ ACT 位预算再吃紧；③ 与粒度矛盾闭环——出路④的更长 burst 加重过取与部分写困境（O11 掩码已删）。
- **四条出路与代价**：

| 出路 | 实例 | 代价 |
|---|---|---|
| ① 延长命令周期 | LPDDR6：命令 2 周期、ACT 4 周期（Table 254） | 命令延迟↑、命令带宽进一步↓——恶性循环起点 |
| ② 伪通道共享 CA | HBM PC：18 pin 服务 2 PC | 牺牲独立性（共享命令槽、电源域通道级，A5/A6/A7）——"更窄更独立"的局部倒退 |
| ③ 提升 CA 频率 | 各代 CK 整体提速（CA 跟 CK 走，无独立倍频实例） | **CA 根数与 CA 频率是 SI 预算内的二维 trade**：根数少才能跑高频（LPDDR6 4 根 DDR），根数多则频率受限、用多拍补（DDR5 14 根 2T） |
| ④ 更长 burst | DDR5 BL16 / LPDDR6 BL24/48（8n→16n→24n 预取史） | 粒度↑ → cache line 失配/过取回归（A4 反面）+ 部分写更难（O11 掩码已删）——矛盾闭环 |

- **HBM 对照（第五条路）**：堆叠形态绕开整个预算——数据引脚大爆炸（1024→2048）使 CA 占比稀释 + 行/列分总线 + TSV/中介层；CA 带宽问题不是被解决而是被**封装形态买断**（B1/B5 对照路线，§2.1 A5）。
- **结论口径** [INFERENCE]：四条出路分别付出 命令延迟 / 独立性 / 整域 SI / 粒度失配 的代价，实际协议是组合拳（LPDDR6 = ①+③+④；HBM = ②+形态）；根源是**命令位宽（行地址）与请求率随带宽一起涨，而 SI 预算不涨**。

**D7/D8 块：总线 turnaround——tWTR / tRTW 为什么存在、为什么不对称**

- **根源**：DQ 双向——读时 DRAM 驱动、写时控制器驱动，**方向切换必须等上一方向完成**。
- **tRTW（读→写）：只需方向翻转，且写命令可提前发**——读不破坏 SA（放大后保持轨到轨，无 SA 恢复等待）；写数据滞后是可利用余量：不冲突条件 `t0 + tRTW + CWL ≥ t0 + CL + BL/2` → **tRTW ≥ CL − CWL + BL/2**——正是 Table 43 公式核心项（其余为 DQS 对齐/读后沿/写前导的电气细节）[JEDEC 已核]。
- **tWTR（写→读）：方向转换上叠加 SA 恢复**——写驱动强行覆盖了 SA 与位线，覆盖传播完成后读通路才能接管；BG 归属照旧定长短（Table 43 + p483 已核）：**同 BG = tWTR_L = CWL+WBL/2+Max(16nCK,10ns)**；**跨 BG = tWTR_S = …+Max(4nCK, 2~2.5ns)**——3 倍以上差距。
- **D8 不对称的三面**：① 电气——R→W 仅方向翻转（SA 正常），W→R = 方向翻转 + 覆盖传播/SA 稳定（C8 对抗重建根源）；② 数值——tWTR_L(10ns) > tRTW(公式项) > tWTR_S(2ns)；③ 系统——写可缓冲解耦、读有 QoS/延迟约束 → 调度器攒写、分组翻转，不对称被策略进一步放大（D10 伏笔）。

## 4. 训练与校准（LPDDR5/6 重点）

### 4.1 LPDDR5/6 训练流程（纲领 I 组自举链：CA→WCK2CK→读均衡→写均衡→Vref/DFE→频点 training set）

顺序由自举依赖决定（后一步依赖前一步打通的通路）：

1. **CA 训练（Command Bus Training）**：进入训练模式后经 CA 施加/回传训练 pattern（JESD209-5B Fig25-27，覆盖 WCK 频变与固定 WCK 两种场景）；调 CA delay + VREF(CA)。
2. **WCK2CK Leveling**（§4.2.5）：锁 WCK↔CK 的 FIFO 指针（见 3.3）。
3. **读均衡**：基于 **tWCK2DQ Interval Oscillator**（§7.6.14，业界俗称 DQS 振荡器；标准名为 interval oscillator，含 WCK2DQI 匹配误差与读出时序定义）校准 DQ/RDQS 采样相位。
4. **写均衡**：per-byte 校准 DQ 相对 WCK 的相位。
5. **VREF(DQ) 训练** + LPDDR5X 起的 **per-pin DFE**（§7.7.7）。
6. 频率维度：低频 f0 初始化训练 → DFS 后用 **training set 保存/恢复**（多 frequency setpoint）；DVFSC/DVFSQ 等低功耗模式依赖该机制（见 5.3）。

**LPDDR6 Training 全流程——六阶段**（用户口径 [PROJECT]；与 JESD209-6 §4.2.1.7 / Table 254 / MR30-34 交叉验证一致）

- **① CS Training（CSTM）——片选对齐**：低频进 CSTM 模式 → DQ[11] 拉高触发 FSP 切高频 → CS 线发 1010 翻转波形，DRAM 用 CK 采样 CS 脉宽、采样 32 CK 周期 → 高/低脉宽 Pass/Fail 经 **DQ[7:6] 异步反馈** → SoC 逐步微调 CS 发射延迟直至全 Pass → 低频退出、**VREF(CS) 写入目标 FSP 寄存器**。核心目标：让 DRAM 在正确时刻抓到 CS 上升沿，作为命令解析起点。
- **② ZQ Calibration——阻抗匹配**：LPDDR6 采用**后台校准**（完全不占 DQ）；完成后有变化则置位 **ZQUF** 标志，Core 在总线空闲发 **MPC ZQCal Latch** 把新阻抗码字安全应用到引脚、等 tZQLAT 后恢复传输；**DVFS 电压切换时需 MRW 设 ZQ Stop 暂停、切完解除**。核心目标：以外部 240Ω 精密电阻为基准，校准 DRAM 驱动器/ODT 阻抗。
- **③ CBT（Command Bus Training）——命令总线对齐**：高频下拉高 CS、CA[3:0] 发 **PRBS16**，DRAM 内**同种子 PRBS 发生器**逐比特比对，偏差比特在 DQ[7:0] 输出 1（Fail）→ SoC 据此**独立调每根 CA 线的发射延迟**；循环"复位 LFSR → 发 PRBS → 读 DQ"直到 DQ[7:0] 全 0（4 根 CA 双沿完美对齐）。核心目标：CA 时序 + VREF(CA) 阈值逐比特对齐。
- **④ WCK2CK Leveling——写时钟相位对齐**：修正 DRAM 内部 WCK **1/2 分频器的初始相位不确定性**（0°/180°）。Core 发 **WFF** 命令 → DRAM 生成 CK 锚定、宽 2tCK 的内部脉冲 → 分频后的 WCK 对其单次采样：相位错采样 0、对齐采样 1 → SoC 微调 WCK 发射延迟直至 DQ 上观察到 0→1 翻转。
- **⑤ WCK-DQ Training——数据眼图对齐（读先写后）**：**读训练**：RDC 命令 → DRAM 忽略 FIFO、直接从 **MR32/33/34** 输出固定已知 pattern → SoC 比对并调**接收端每根 DQ 延迟**找眼中心；**写训练**：WFF 写自定义 pattern 进 FIFO + RFF 读出比对 → 调**发射端 WCK-to-DQ 延迟**，循环至无损；最后可再跑 RDC 对读路径精细复扫。
- **全局总结**："**低频进/出，高频练**" + "**Core 发命令，PHY 调延迟，DRAM 报结果**"；**VREF 值存 DRAM 的 FSP 寄存器、delay 值存 PHY 内部**；流程 = CS 粗对齐 → CA 精对齐 → WCK 相位锁定 → DQ 眼图居中，层层递进打通高频信号闭环。

### 4.2 三协议训练机制一览（纲领 O2）

| 维度 | HBM3/4 | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 命令/CA 训练 | IEEE 1500 测试口 + AWORD MISR 签名 | MPC 捕获 CA → MR → MRR 回读 | Command Bus Training + CBT |
| 数据训练 | WDQS2CK 对齐 + DWORD 级 MISR/LFSR | MPC 模式读写均衡 + per-pin DFE/DCA/Vref | WCK2CK Leveling + Interval Oscillator 读均衡 + 写均衡 |
| 回读通道 | 独立测试访问口（不依赖功能 DQ） | 数据总线（需先打通 DQ） | CBT/DQ 通道 |
| 频率维度 | 单频点（设计期定） | 单频点 | **多 setpoint training set** |

> 注：按约定本手册不展开 HBM/DDR5 训练细节（JESD238 §6.8、JESD79-5B §4.x 需要时另查），仅列对照。

【核心速答】LPDDR 训练是一条自举链：CA 训练 → WCK2CK 锁 FIFO → 基于 interval oscillator 的读均衡 → 写均衡 → Vref/DFE；每个频点一套 training set，DVFSC/DVFSQ 的地基就是它。三协议训练的根差异在**回读通道**：HBM 走独立测试口、DDR5 走数据总线、LPDDR 走 CBT/DQ。

## 5. 功耗与电压域

### 5.1 供电轨对比（纲领 M8 / L9~L10 / O6）

| 协议 | 供电轨与典型值 | 备注 |
|---|---|---|
| HBM3 | VDDC 1.1V（core）/ VDDQ 1.1V（I/O）/ Tx driver 0.4V / VDDQL / VPP | 上电顺序 VPP → VDDC=VDDQ → VDDQL（JESD238 Power Ramp） |
| HBM4 | **VDDC 1.05V（core）/ Tx 0.4V / I/O 电压厂商自定** | 标准仅约束相对关系：VPP > VDDC+200mV、VDDC > VDDQ+VSP（JESD270-4） |
| DDR5 | VDD=VDDQ=1.1V（PMIC 在模组，平台只供 bulk 5/12V）；VPP ⚠️1.8V | 上电/管理时序依赖模组 PMIC |
| LPDDR5 | VDD1 / VDD2H / VDD2L / VDDQ | 上电顺序 VDD1≥VDD2H≥VDD2L≥VDDQ；VDD2 拆分在 LPDDR5 已是**可选** |
| LPDDR6 | VDD1 / **VDD2C 1.0V** / **VDD2D 0.875V** / VDDQ 0.5V（默认） | 顺序 VDD1≥VDD2C≥VDD2D≥VDDQ；I/O 按 VDDQ=0.5V nominal、Voh=0.5×VDDQ≈250mV 设计；VDD2 拆分为**强制** |

要点：HBM3→HBM4 的电气演进方向是"**把余量下放厂商**"（I/O 电压开放），换取 PHY 工艺自由度（配合逻辑 base die）；LPDDR 的方向相反——**标准把电源轨越拆越细**，换取能效管理精度。

### 5.2 功耗与 pJ/bit（纲领 M7 / O10）

| 代际 | 单 stack 功耗（满负载量级）⚠️ 建议以项目实测/厂商 datasheet 替换 | pJ/bit 趋势 |
|---|---|---|
| HBM3 | ~5~8 W（8-Hi@6.4G） | 基准 ~5 pJ/bit 量级 |
| HBM3E | ~6~10 W（12-Hi@9.6G） | 每代降 ~20~30% |
| HBM4 | ~10~15 W（16-Hi@12.8G） | 带宽翻倍但 pJ/bit 继续下探（~3~4） |

- 规律：**总功耗随带宽近线性上涨，pJ/bit 随代际下降**。速率路线（3→3E）主要花 IO 功耗买带宽，pJ/bit 改善有限；位宽路线（3E→4）用更低 per-pin 速率跑更宽总线，能效更好——这是 HBM4"降速翻宽"的功耗学解释（呼应 1.1）。
- 控制器视角：HBM 无 DFS，功耗管理收敛为 per-PC 降活 + 热感知节流；与 LPDDR 的精细 DVFS 成两极（见 5.3）。

### 5.3 控制器侧功耗管理机制（纲领 O3 / O6 / M10）

**LPDDR6 的 VDD2 强制拆分与 DVFS 家族**

- LPDDR5 的 VDD2H/L 是**可选**拆分；LPDDR6 的 **VDD2C（接口侧 1.0V）/ VDD2D（阵列侧 0.875V）** 是**强制**双恒功率域。动机：接口域与阵列域的最优电压、负载、di/dt 特性不同——拆分后独立稳压、隔离噪声、**CA 侧调频调压不再扰动阵列裕量**。
- DVFS 家族（JESD209-6 §11 / MR19-21），每个模式绑定一条轨与一个目标区间：
  - **DVFSC**：VDD2 core 域；
  - **DVFSQ**：VDDQ 0.5V → 0.3V；
  - **DVFSH**：VDD2C → 1.025V（高速率）；
  - **DVFSL**：VDD2D → 0.85V（低速率）；
  - **DVFSB**：VDD2D → 0.90V（高速率）。
- 控制器代价：① DFS 序列变为**多轨时序编排**（各轨电压爬坡/跌落顺序与建立时间编进切换序列）；② 维护**"模式 × 轨电压 × training set"三维表**；③ 与 PMIC 的轨控握手时序成为软硬协同设计点。

**三协议功耗管理复杂度排序：LPDDR > DDR5 > HBM**

- **LPDDR（最复杂）**：REFpb 把刷新变成逐 bank 后台债 + DFS/DVFS 多域切换 + 温度刷新倍率（2x/4x）三者叠加。
- **DDR5（中等）**：频率电压固定；复杂度在双子通道刷新错峰、RFM/DRFM/ARFM 配额、side-band ECC 读改写对调度的占用。
- **HBM（最简）**：无 DFS、无 CKE，频率与电压设计期锁死；只有 per-PC 降活与热节流。定位使然：AI 场景要持续满带宽，省电靠降活不靠降频。

【核心速答】功耗管理复杂度 LPDDR > DDR5 > HBM。LPDDR6 把 VDD2 强制拆成接口域/阵列域两个恒功率域，DVFS 是绑定各轨的五个模式家族（DVFSC/Q/H/L/B），控制器要编排多轨时序并维护"模式×电压×训练集"三维表；HBM 反向走极端——锁死频率电压，只做降活。

## 6. 可靠性与 RAS

### 6.1 DDR5：片上 ECC vs Side-band ECC（纲领 F1~F4 / F6）

| 维度 | On-Die ECC（片上，强制） | Side-band ECC（模组级） |
|---|---|---|
| 覆盖范围 | DRAM 阵列内部（cell → 读出口） | 链路 + 阵列全路径 |
| 纠错能力 | **SEC：128 数据 + 8 校验位**（JESD79-5B §4.36） | SECDED（8bit/64B） |
| 引脚占用 | 不占（对系统透明） | 占（40-bit 子通道 = 32+8） |
| 控制器角色 | **无感知**——看不到已纠错误 | 全责：写生成/读校验、scrub/patrol、错误计数与日志 |
| 存在目的 | 支撑更高密度 die（容忍更高原始缺陷率） | 系统级 RAS |

- 关键推论：ODECC 透明纠错造成**可靠性遥测盲区**（已纠错不可见，只能从未纠错错误率间接推断）；系统 RAS 必须依赖 side-band 层做 scrub 与日志。两层是**纵深防御**：ODECC 把原始错误率压低 1~2 个量级，side-band 兜底链路与残余阵列错误。

### 6.2 HBM：On-die ECC + SEV 上报 + DRFM（纲领 F5 / F7~F10）

- **HBM3（JESD238 §6.9）**：**symbol-based On-die ECC + 读写 meta-data（MD）位 + 错误擦洗（scrubbing）+ 错误透明协议 + 接口传输 parity + 故障隔离限**——片内自治的纵深组合（不是主机 side-band 模式）。
- **错误上报**：每 PC 的 **SEV[1:0] 引脚**随读突发携带严重度编码（JESD270-4 Table 67/68 Severity Encodings）；ECS（自动纠错擦洗）错误日志寄存器（MR81/82；HBM4 支持多 bit 纠正记录，MR9）。
- **HBM4 刷新管理增强（行锤 + RAS 合流）**：**RFMpb / DRFMpb**——ACTIVATE 可携带 DRFM bit 标记风险 bank，其后对该 bank 的 RFMpb 即 **DRFMpb**（定向 per-bank 刷新）；**Bounded Refresh（BRC + tDRFM，Table 41）**——把行锤响应从全局长刷新改为**对目标 bank 的有界定向刷新**，带宽代价最小化。
- 对照 DDR5：ODECC 纠错不可见 vs HBM SEV 随读"带内"上报——HBM 的读侧 RAS 信息控制器可直接消费。

【核心速答】HBM 的 ECC 是片内自治（symbol-based on-die + scrub + 接口 parity），纠错严重度经 SEV 引脚随读数据带内上报、ECS 记日志；HBM4 再加 DRFM/BRC 有界定向刷新。控制器读侧直接收 SEV，不用猜。

### 6.3 刷新粒度：REFpb vs REFsb（纲领 E2~E5 / E8~E9 / O9）

| 维度 | LPDDR5 REFpb | DDR5 REFsb |
|---|---|---|
| 粒度 | **单 bank（或 bank pair）** | **各 BG 中同号 bank 同时刷** |
| 其余 bank | 可继续服务 | 可继续服务 |
| 停摆时间 | tRFCpb（最短；tpbr2act / tpbR2pbR 约束 REFpb 之间与到 ACT 的间隔） | tRFCsb（约为 REFab 的一半量级） |
| 控制器实现 | **bank 级刷新债**：per-bank deadline 跟踪 + 机会式插空 | **子通道错峰**：REFsb 相位错开；REFab 只留深空闲窗口 |

- 共同哲学：把刷新从"周期性全局停机"重构为"**可调度的后台工作**"，由控制器 QoS 决定何时还债；REFab 在两者中都保留（深度空闲/进自刷新前最划算）。
- 粒度差异根源：LPDDR 通道窄、延迟敏感（手机），要单 bank 粒度；DDR5 子通道 bank 多、吞吐敏感，BG 级批量刷新更省命令带宽。LPDDR5 还定义了 Optimized Refresh 组合（示例：8×REFpb 完成一轮 bank 覆盖）。

**E1 块：DRAM 为什么必须 refresh** [PHYSICAL-EXPLANATION]

- 存储介质是会漏电的电容（1T1C），四类泄漏：pass transistor 源极-衬底**结泄漏**、**亚阈值泄漏**（WL=0 但 Vth 有限）、**氧化层缺陷/隧穿**、相邻 WL/BL **耦合位移电流**（Row Hammer 伏笔，E10）。
- **温度指数放大**（~2×/10°C）——E7 温度倍率与 DDR5 MR4 温度档的同一物理根源。
- **破坏性读的回写由 tRAS 驻留内建覆盖**（C1/C2/C3），不属于 refresh 职责——refresh 是"不打 DQ 的读"：行激活 → SA 感知放大 → 自动回写满电平。
- **预算数学**：85°C 下保持 ~32ms → **tREFI = 32ms/8192 = 3.9µs（平均值）**；同一 bank 的 REF 间隔最大 **9×tREFI，无论 REFab or REFsb** [PROJECT]——平均可挪、上限不可破（E5 postpone 预算同源）。

**E2 块：为什么最早使用 all-bank refresh** [PHYSICAL-EXPLANATION + INFERENCE]

- 四个理由：① 命令开销最小——一条 REFab 刷全 bank，8192 条/32ms 与 bank 数无关（REFpb 要 ×bank 条）；② DRAM 侧实现简单——无需 per-bank 刷新地址计数器与选择逻辑；③ 深度空闲最划算——反正要停，整个阵列一起停，用最大停顿换最小命令带宽（§6.3 共同哲学的保留理由）；④ 与 self-refresh 同构（SR 本质是 DRAM 自管 REFab 的长睡眠）。
- 早期够用：tRFCab 短（Table 235：130ns@2Gb → 380ns@32Gb）——2Gb 档刷新占空 ≈ 130ns/3.9µs ≈ 3.3%，全停无感。
- 演进压力（→ E3/E4）：密度↑ → tRFCab↑ → 全停 QoS 代价不可承受 → REFsb/REFpb/FGR；HBM 把"全 bank"粒度直接定义在 PC 上（REFab 带 PC 位、REFpb 16-bank set，p65 NOTE 3）。
- 调度软化：LPDDR5 连 REFab 也允许 postponed/pulled-in（§7.5.1，E5 证据）——"REFab 哲学"在调度层已被预算制软化。

**E6 块：postpone 预算为什么是 8+1（9×tREFI），而不是任意推迟**

- **保持时间的硬要求（Table 235）**：tREFW = 32ms 内每行必须 **R = 8192 次**——任意推迟会让平均间隔超标、破坏该承诺 → 协议必须给推迟设上限，而不是允许无限挪。
- **上限的直接形式**：LPDDR5 §7.5.1：**最多推迟 8 条，第 9 条必须执行**（Figure 136/137，窗口 = 9×tREFIe）；HBM3 §6.3.2.5 **NOTE 2**（p61）："**The maximum time interval between two REFRESH commands is 9 × tREFI**"——协议直接定义"两条 REF 的最大间隔"，而不只是平均值。
- **压缩侧约束**：相邻 REF 间隔 ≥ **tRFC**（tRFCab/tRFCpb）——补发不能无限压缩，下界与推迟上限共同夹出可行域。
- **电流侧约束**：DDR5 3DS 要求**错峰刷新**（§4.13.5：tRFC_dpr ≈ tRFC_slr/3，"to limit the maximum refresh current (IDD5B1)"）——协议自身限制刷新的电流聚集。
- **温度改变预算（MR4 / Table 235）**：2x 模式 tREFI 减半——同样的 8+1 规则下窗口收紧，协议把温度对预算的修改纳入自身。
- **结论**：postpone 预算（8+1 / 9×tREFI）是协议在**调度灵活度 ↔ 保持时间下界 ↔ 电流上限**之间的平衡点。"不能全部用满"的协议含义 = 用满即达 9×tREFI 边界，再推迟就违反保持承诺——HBM3 以"最大间隔"直文写出，LPDDR5 以"推迟条数 + 第 9 条强制"写出，同一规则的两个形式。

**E7 块：Temperature 为什么影响 refresh rate** [PHYSICAL-EXPLANATION + JEDEC 事实]

- **物理根源（Arrhenius 泄漏）**：结泄漏电流 ~ exp(−Ea/kT)——**温度每升 10°C 泄漏 ≈ ×2**（业界经验系数）；保持时间 **t_retention = Q/I_leak**——温度越高泄漏电流越大、保持时间越短。
- **协议的三层响应（事实均已核）**：① **DDR5 MR4**（p67，Table 25）：刷新速率随温度档编码——普通档 **1x（<80/85°C）→ 2x = tREFI/2**（85°C 起，逐档 >95°C）；Wide Range 档（OP5=1）75°C 起跳、延伸 >100°C——**tREFI 倍频**形式（8192 过采样不变、保持窗口减半 32→16ms）；② **LPDDR5 Table 235**：tREFW=32ms 标注为 1x Refresh（温度条件在 NOTE），LPDDR 侧另有 **4x 档**（§5.3 已有）——**4x 只在 LPDDR 侧**（DDR5 MR4 仅 1x/2x：移动封装温度极限与场景差异）；③ **HBM3 的 TEMP/CATTRIP 引脚**（§6.3.4.1 pin 表）——温度告警的硬件级联动。
- **对 Memory Controller 的含义**：高温 → 单位时间 REF 命令更多；**不能被 Bank-Level Parallelism 隐藏的 REF 变成 unhideable bubble → sustained bandwidth 下降**；刷新占空（tRFC/tREFI）随倍频翻倍 → E8 QoS 挤压加剧；与 DVFS 联动的自洽闭环（高温→高频→更高泄漏→更多刷新，§7.2/§5.3）。

**E9 块：为什么 refresh 必须有"不可继续让步"的 critical 边界** [协议口径]

- **刷新债的两态**：窗口内可 postpone（软态——QoS 决定还债时机，E8"可调度的后台工作"）→ 逼近 9×tREFI 边界（硬态/critical——不可让步）。
- **为什么协议必须画出这条硬边界**：QoS 让步牺牲的是**性能**（延迟/带宽，可协商）；刷新违约牺牲的是**正确性**（超过保持窗口 = 数据丢失，不可恢复）——正确性约束不能被性能约束无限覆盖，所以 postpone 自由度必须有终点。
- **协议的 critical 表达形式**：LPDDR5 §7.5.1"**第 9 条必须执行**"（推迟条数上限即 critical 边界）；HBM3 §6.3.2.5 NOTE 2"**最大间隔 9×tREFI**"（最大间隔直文即 critical 线）；HBM3 刷新还需 bank idle（NOTE 2 p65）——三家都以"最大间隔/强制执行"的形式内建了 critical 语义。
- **与 E6 一体两面**：E6 说预算不能全用满（别频繁触碰边界），E9 说边界必须存在且不可让步（触碰即强制执行）——postpone 自由度与 critical 边界共同构成完整的刷新调度契约。
- **控制器责任（协议要求）**：保证最大间隔不被突破（deadline 语义），这是协议强加给控制器的正确性义务（A3 债结构）；E5 的 postpone/pull-in 则是协议给控制器的履约工具。

### 6.4 Row Hammer：RAA/激活计数 + 刷新管理族（纲领 E10~E14 / O7）

| 协议 | 机制 | 要点 |
|---|---|---|
| HBM3 | **RAA 计数 + ARFM（可选）** | 阈值 RAAIMT/RAAMMT/RAADEC 由厂商设定，经 IEEE 1500 DEVICE_ID WDR 可读；达阈值需刷新管理命令 |
| HBM4 | **RFMpb / DRFMpb + BRC** | ACTIVATE 带 DRFM bit 标记风险 bank → 定向、有界（tDRFM）刷新 |
| DDR5 | **RFM / DRFM / ARFM**（MR59：DRFM/ARFM/RFM RAA Counter） | 信用制：ACT 计数 vs RFM 冲销，MR 可配 |
| LPDDR5/5X | **RFM → ARFM**（§7.7.6，MR 支持位） | ARFM 按激活速率自适应提高/恢复刷新 |
| LPDDR6 | **PRAC + ABO** | PRAC 上报风险 row/BG/BK（MR87-89）；ABO（Alert Back-Off，MR86 MRFMaACT）限定恢复期最小 RFMab 与退避期最小 ACT |

- 与 A2 同源：HBM3 的 **RAA 就定义在 tRRDS/tRRDL/tFAW 同一张 AC 表里**（JESD238 p175）——限流（供电预算）与防行锤（激活计数）物理上同源，都是"激活次数的预算与记账"，一个交给电源网络、一个交给刷新管理 [JEDEC 表结构 + INFERENCE]。

**E14 块：RowHammer 协议性能成本与带宽税（纯协议口径）** [公式为协议推导 + 用户口径]

- **本质**：ACT rate 产生 **RAA debt**，REF/RFM 消除 debt——RowHammer 防护的性能成本 = 维持 debt 收支平衡所占用的时间。
- **ACT 极限两层**：单 bank hammer 受 **tRC**（行独占生命周期，C6）；多 bank aggregate 受 **tRRD_S/tFAW**（A2 墙 1）。
- **单 bank 带宽税**：假设 ACT 连续发、RAA 只增不减（无 REF 抵扣）——**税 = tRFCpb / (RAAIMT × tRC + tRFCpb)**；所需 RFM 速率 = **1/(RAAIMT × tRC)**。RAAIMT 非任意值——vendor 提供离散档位。
- **RFMpb 占用规则**：目标 bank 占 **tRFCpb**（不叠加 tRREFD）；不同 bank 的 RFMpb 按 **tRREFD** 穿插（tRREFD 管 RFM 后到下一 ACT 的间隔）。
- **DRFM/BRC 语义**：DRFM = 用采样 address 对相关 row address **定向维护**（非黑盒全刷）；**BRC**（bounded refresh configuration）= 一次 DRFM 以采样 row 为中心、向两侧最多覆盖的物理临近 row 范围。
- **诚实边界**：协议可推导 **RFM demand** 与 **bank-unavailable duty**；固定 bandwidth tax 不能只靠协议——真带宽损失 = 维护窗口中无法被其他 bank traffic 隐藏的 useful-command bubble（隐藏能力取决于负载，系统属性）。多 bank aggregate 触顶时 aggregate tax 上界为组合式（tRRD_S/tFAW 约束下轮流触顶）。
- 共同骨架：**DRAM 报计数、控制器还刷新债**。演进方向：债的粒度越来越细（全局 RFM → per-bank → 定向 bounded），背压方式越来越显式（ARFM 自适应 → PRAC+ABO 显式退避）。
- 控制器实现：per-bank 计数/信用表 + 刷新带宽预算进 QoS 模型；安全场景（汽车）要验证最坏情况下刷新管理开销的上限。

【核心速答】行锤防护已全线"激活感知化"：HBM3 RAA+ARFM、HBM4 DRFM 有界定向刷新、DDR5 RFM 信用制、LPDDR5X ARFM 自适应、LPDDR6 PRAC+ABO 显式背压。控制器都要维护计数和刷新预算——行锤从 DRAM 的事变成了调度器的事。

## 7. Memory Controller 设计差异

### 7.1 调度器架构分叉点（纲领 A3 / B6 / D10）

公共抽象：**bank/PC 状态表 + 时序检查器（timing checker）+ 策略层（QoS/仲裁）**；差异在实例规模与策略维度：

| 维度 | HBM3/4 | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 独立调度对象 | 32ch / 64PC（HBM4） | 2 子通道 × rank × 槽数 | 4~8 通道 / x24=2×SC |
| 命令总线 | 每通道行/列双轨（10/8-bit；1.5/0.5/1 拍） | 每子通道 14-bit CA（1T/2T） | 每通道 7-bit DDR CA |
| 并行度来源 | 通道数 + 行列并行 + PC 独立时序 | rank 并行 + BG 交织 + 双子通道 | 通道数 + BG 交织 |
| 特有维度 | per-PC 功耗/刷新相位错峰 | side-band ECC 读改写、RCD/DB 链路 | REFpb 债、DFS 窗口、RFM/ARFM 配额 |

- HBM 调度器是"**横向复制 + 全局 QoS**"：对象多而轻；DDR5/LPDDR 是"**少数深通道**"：单对象内 rank/BG/刷新/翻转策略复杂。
- 地址映射：HBM 用 channel-first striping（cache line 级打散到 32 通道）；DDR5/LPDDR 在子通道/通道维度的 hash 同样决定热点分布——**映射策略是三协议共享的设计课题，只是维度数不同**。

**A3 重新确认：Bank 数在控制器四个部件上的成本** [PROJECT + JEDEC 锚点]

- **状态表 / 计时器**：每 bank 一套状态机，字段至少含 open row 地址、tRCD/tRAS/tRP/tRC 计时器、刷新债 deadline、RAA/RFM 计数——寄存器成本随 bank 数线性增长（HBM4 64PC × 最多 64 bank 是极端值）。
- **刷新债的 postpone 预算随 bank 数收紧**：截止时间 = 9×tREFI（JEDEC：最多 postpone/pull-in 8 条，第 9 条必须执行——JESD209-5B Figure 136/137）；到点冲刷 owed 刷新的时间 ∝ banknum × tRFCpb（REFpb 模式，每 bank 至少一条债）。bank 越多，窗口内留给普通命令的松弛越少，命令排程灵活度下降——A2 墙 3 的调度器视角。
- **timing checker 分层**：bank 内（tRCD、tRAS/act2pre、tRC、tRP、tRTP/rd2act、tWR→tRP 链、tRFCpb、drfm2act）→ 跨 bank/BG（tRRD_S/L、tCCD_S/L、tWTR_S/L）→ 跨 SID（HBM 多 stack 共享通道总线的 turnaround）→ 系统级（tFAW 滑动窗口计数器、刷新预算、ODT/总线翻转）。层级越深越是本地比较器，系统级的是全局计数器。
- **命令发射通路**：队列 CAM 按 bank/tag 匹配 → bank filter → QoS filter → timing check——bank 数增加直接加宽 CAM 表项与比较器阵列，发射路径的功耗与时序压力上升。

**A10：通道继续增加——瓶颈何时从 DRAM 转到 NoC / Controller / PHY**

- **分层判据（按顺序转移）**：
  1. **DRAM 是默认瓶颈**：实测带宽 << peak、命令槽在等 DRAM 时序（row miss/tRRD/tFAW/刷新占空，A2 墙 1/墙 3）——此时加通道/加 bank 才有效。
  2. **Controller 的增长形态取决于组织方式**：**每通道独立控制器实例——单实例逻辑不随通道数增长**（横向复制，§7.1）；**多通道共享一个控制器——仲裁/CAM/队列随通道数增长**（A3 四部件）。但两种方式都保留一层不复制的**全局层**：地址映射/防热点（A11）、跨通道 QoS 与功耗预算——它才是共享瓶颈。判据：通道 ready 却无可发命令（映射/QoS 卡住）或部分通道饥饿。
  3. **NoC 的并发上限**：**Crossbar 端口数与路由拥塞决定所有通道能否真正并行**——请求方到各控制器实例的聚合带宽 ≥ N×每通道带宽才不拖后腿；映射失效时 NoC 单路径拥塞、其余通道闲置。HBM 的 near-compute 摆放（2.5D 中介层，§1.3）本质就是把 NoC 瓶颈推迟/消除。
  4. **PHY 的面积/功耗随通道数（严格说随总引脚）线性增长**——HBM4 的 2048 DQ 使 PHY 功耗占封装预算大头；训练/漂移重训练造成可用性损失（I 组）；DFI 带宽必须匹配聚合命令率（J 组）。
- **典型转移顺序**：DRAM（时序限额）→ Controller 全局层（映射/QoS）↔ NoC（crossbar/拥塞，谁先取决于拓扑与流量分布）→ PHY/封装（功耗预算）。负载类型决定卡在哪层：随机多核负载先考验 NoC/QoS，row-buffer 型负载先考验 DRAM 时序。
- **设计含义**：通道继续增加时，投资优先级从"DRAM 内部并行"转向"映射防热点 + NoC 容量 + 每通道实例化"——这也是 HBM4 通道翻倍而不动 ch-2PC 的原因之一：对象模型稳定才能横向复制（§2.1 A5）。

**D10 块：Scheduler 的自由度系统化** [PROJECT]

| # | 自由度 | 证据映射 | 层归属 |
|---|---|---|---|
| 1 | 命令聚合重排序 | B8（row miss 放大 3:1 → 聚合降到 2+1/N）、B9（28.6:1）、A3 CAM | 每通道实例内 |
| 2 | batch 读写切换 | D7/D8（turnaround 成本：攒写分组翻转，减少 tWTR/tRTW 次数与 tWTR_L 代价） | 每通道实例内 |
| 3 | 错峰 REF | §2.2（双子通道错峰）、§3.4 骨架（per-PC/per-bank 刷新债错峰） | 实例间协调（全局层） |
| 4 | refresh postpone/pull-in | LPDDR5 Figure 136/137（±9×tREFIe，A3 postpone 预算） | 控制器↔DRAM 的预算协议（跨层） |
| 5 | BG 交织地址映射 | A11 防热点、§2.3 BG-aware 排序、channel-first | 全局函数 |
| 6 | page open / autopre 策略 | B8 AP 权衡（open-page 换 hit 率 vs close-page 换命令省） | 每通道实例内 |
| 7 | QoS 带宽/延迟分配、防饿死 | §3.4 骨架（刷新>写排空>读 QoS>预充电合并）、A10 全局层 | 全局仲裁 |

- **本质**：Scheduler = 在不可改的时序约束（A2/C/D 组的 ns/nCK 墙）里**重排时间线**——把不可避免的开销（turnaround、刷新、激活）移动到性能伤害最小的位置，并用地址映射预防它们发生。1/2/6 是每通道实例的横向复制资产（A10），3/7 在全局层（A10 的共享瓶颈），5 是全局函数，4 是与 DRAM 的预算协议——分层直接对应 A10 的瓶颈归属（§3.4 调度骨架为本表的优先级参数化）。

### 7.2 DFS vs 固定频率（纲领 O3 / J10 / K5 / I19~I21）

LPDDR DFS/DVFS 对调度器的额外要求：

1. **多频点 training set** 的存储与恢复（每个 setpoint 一套完整训练值）；
2. **DFI frequency change 手序列** + WCK2CK 重对齐；
3. **多轨电压协同**（LPDDR6 的 DVFSH/L/B/Q 各绑一轨，见 5.3）；
4. 切换窗口内的流量排空与延迟抖动进入 QoS 模型；带宽承诺按频点建模。

DDR5 固定频率：初始化训练一次 + 温漂重校（ZQ/Vref 类），调度简单；代价是能效不可调。HBM 同为固定频率，但对象数最多（见 7.1）。

【核心速答】调度器公共骨架 = 状态表 + 时序检查 + QoS 策略；HBM 横向复制（对象多而轻），DDR5/LPDDR 纵向加深（rank/BG/刷新策略复杂）。LPDDR 独有的一整块是 DFS：训练集、DFI 手序列、多轨电压、抖动建模。

### 7.3 统一控制器前端：复用与分叉边界（纲领 O1~O10 / J8~J9）

**可复用（协议无关层）**

- 事务层：AXI/CHI 端口、QoS/仲裁/防饥饿、地址 hash 与 interleave 框架；
- 基础设施：性能计数、错误注入/记录框架、寄存器与诊断架构；
- 参数化引擎骨架：bank 状态表、时序检查器框架（当时序参数 fully parameterized 时）。

**必须分叉（协议相关层）**

- **命令编码器**：HBM 行/列双轨（1.5/0.5/1 拍）vs DDR5 14-bit CA（1T/2T）vs LPDDR 7-bit DDR CA——格式正交，无法参数化统一；
- **训练状态机**：三者回读通道不同（独立测试口 / 数据总线 / CBT+DQ），骨架不可复用（见 4.2）；
- **刷新管理**：RFMpb/DRFM（HBM）vs REFsb/RFM（DDR5）vs REFpb/ARFM/PRAC（LPDDR）——策略与命令接口都不同；
- **低功耗**：HBM 命令式无 CKE vs LPDDR CA 命令式 + DPD/DFS vs DDR5 CKE；
- **PHY/DFI 时序参数与手序列**。

**工程结论**：统一的是**前端（事务/QoS/基础设施）**，分叉的是**协议引擎（编码/训练/刷新/低功耗）**；常见落地形态 = 共享前端 + 每协议独立 MC core + 统一 infra（性能计数/RAS/寄存器）。

### 7.4 高频问题：HBM 带宽这么高，为什么不能替代 DDR5 当主存？（纲领 O5）

1. **容量**：HBM 单封装 ≤64GB 且设计期锁死；服务器主存需要 TB 级横向扩展，只有 DIMM 插槽路线能做到。
2. **成本**：TSV + 堆叠键合 + 中介层的良率代价，HBM $/GB 远高于 RDIMM。
3. **延迟与系统复杂度**：HBM 延迟并不占优（RL + 阵列访问与 DDR 同量级），数十通道带来的调度/训练/测试开销大；DDR 生态（RCD/DB/PMIC/RAS/热插拔）成熟度无可替代。
- 正确关系：**HBM 是带宽引擎，DDR5 是容量底座**；层级化组合（HBM 作大容量末级缓存覆盖 DDR5）才是 AI 平台的主流形态。

【核心速答】统一控制器分两层：事务/QoS/基础设施可复用；命令编码、训练、刷新管理、低功耗必须分叉——根因是"命令格式、回读通道、刷新哲学、电源架构"四个正交维度全都不同。HBM 替代不了 DDR5 是容量与成本问题，不是带宽问题。

### 7.5 高频对比题（对比题 1~4；纲领锚点：题1→O 组综合、题2→Part XII、题3→Part XII 样例一、题4→A6 / A7）

**对比题 1（旧 H1）："LPDDR5 是 DDR5 的移动精简版"——对吗？**

不完全对。**相同点**：SDRAM 阵列语义同源（bank/BG/BL/刷新的底层时序概念）。**独立演进（不是简化）**：时钟架构（LPDDR5 三时钟域 + CKR vs DDR5 单 CK）；命令编码（7-bit DDR CA vs 14-bit 1T/2T）；电源（VDD2H/L 多轨 + DFS/DVFSQ + 更深低功耗态 vs DDR5 无频率切换）；训练（interval oscillator / WCK2CK vs MPC/MRR）；并行度设计（多窄通道 vs 双子通道）。**各有对方没有的东西**：DDR5 有 ODECC 强制、双子通道、PMIC 模组化；LPDDR5 有 DFS、DPD、更细的低功耗态。

【核心速答】阵列语义同源，接口/命令/电源/训练四层各自演进——两者不存在谁是谁的子集；说"精简版"会漏掉 LPDDR 更复杂的多频点电源管理。

**对比题 2（旧 H2）：HBM4 向后兼容 HBM3 控制器——混合部署时控制器要做什么？**

JEDEC 口径：HBM4 向后兼容 HBM3 控制器（同一主机设计可支持两代 stack）。控制器需要：

1. **枚举探测**：读 ID/MR（含 IEEE 1500 WDR 通道）识别代际、die 数（4/8/12/16）、SID、密度；
2. **配置切换**：通道映射（16ch vs 32ch 模式）、bank 数/PC（16~64，随 die 数）、时序档（tRCDRD/tRCDWR 等随速率 bin）；
3. **电气取最低公约数**（HBM4 I/O 电压厂商自定，见 5.1）；
4. **特性位探测**：ECS/DRFM/BRC 等按代际使能。

⚠️ 兼容的引脚级机制细节以 JESD270-4 与厂商应用笔记为准。

【核心速答】兼容的本质是"协议骨架不变、代际参数可枚举"：探测代际 → 重映射通道与 bank → 选时序档 → 按代际使能特性，PHY 电气取两代公约数。

**对比题 3（旧 H3）：DDR4→DDR5，控制器最大的架构变化是什么？**

不是速率，是三件结构性的事：

1. **子通道化**：1×64 → 2×32 独立子通道——命令/训练/刷新全双份，DFI 双实例；
2. **ODECC 强制**：RAS 分层重构（片上透明 SEC + side-band 全路径），带来遥测盲区；
3. **PMIC 上移模组**：电源管理重心迁移（上电时序、侧带管理、告警走模组）。

次级变化：1T/2T 命令编码、FGR 刷新、REFsb、RFM/DRFM/ARFM、DFE、32Gb die。

【核心速答】记住"子通道化 + 片上 ECC + PMIC 上移"三件套——都是架构级迁移，速率只是顺带。

**对比题 4（旧 H4 / A6）：HBM 伪通道和 DDR5 子通道是一回事吗？**

不是。判据是**有没有独立命令通路**：

- DDR5 子通道：有独立 CA/CS，是系统可见的两个独立命令流；
- HBM PC：**共享通道的行列命令总线与 CK**，只是 bank 阵列、刷新、时序状态半独立（电源状态 PD/SR 是通道级，见 §2.1 A5）——是"管理分区"而非"命令分区"；
- LPDDR6 的 Sub-Channel（自带 CS/CA/CK）性质上反而更接近 DDR5 子通道；
- 另注意粒度：DDR5 子通道 32-bit 数据；HBM PC 32-bit 数据，但上面还有一层 64-bit 通道。

**A6 重新确认：命令吞吐的量化对照** [JEDEC Table 31/32 + NOTE 9]

| | DDR5（2 子通道） | HBM（通道内 2 PC） |
|---|---|---|
| 命令接口 | 2× 完整 CA[13:0]+CS | 1× R[9:0] + 1× C[7:0]，两 PC 竞争 |
| 每拍命令能力 | 每子通道任意命令，互不影响 | 1 行 + 1 列（ACT 1.5 拍期间总线冻结，NOTE 9） |
| 同类命令并发 | 两子通道同拍各发一条 ✓ | 两 PC 同拍只能发一条 ✗（列命令 1 拍编码显式携带 PC+SID+BA，Table 31） |
| 跨类并发 | 天然支持 | 行+列可跨 PC 同窗并行（Table 32 "Different PC, Any Bank" 列） |
| 电源域 | 独立 SR/PD | 通道级同步（A5 真值表证据） |
| 命令引脚成本 | 2×14 = 28 pin | 18 pin 服务 2 PC——"pseudo" 的引脚预算动机 |

- 判据升级为三条：① **CA/命令域归属**；② **时钟/电源域**（PD/SR 能否独立进入）；③ **命令带宽是否共享**（同拍能否各发同类命令）。LPDDR6 SC 三条全独立 → 归 DDR5 类。
- Controller 视角：DDR5 两子通道 = 两套独立状态机/checker 实例；HBM 通道内两 PC = 共享发射端口 + 每 cycle "发给哪个 PC" 的仲裁（连 A3 四部件成本）。

【核心速答】子通道 = 独立命令流；伪通道 = 共享命令流的刷新/时序分区（电源状态通道级）。三条判据：CA 归属、时钟/电源域、命令带宽共享——看一眼编码就知道。

**对比题 5（O11）：写路径的字节粒度——Masked Write / DM / DMI / DBI 支持矩阵**

| 特性 | DDR5 | LPDDR5 | LPDDR6 | HBM3/4 |
|---|---|---|---|---|
| 独立 DM 引脚 | ✓ x8/x16（MR5:OP[5] 启用，DM_n LOW=掩码该 byte；x4 不支持） | ✗ | ✗ **DMI 删除**（Table 1 NOTE 2："There is no DMI in LPDDR6"） | ✗ |
| MASKED WRITE 命令 | ✗（有 WR_Partial 标志配合 ODECC） | ✓（DRAM 内 RMW，同 BG tCCDMW=4×BL/n） | ✗（Table 254 仅 WR-S/WR-L；'Masked' 只剩 PASR Segment Mask=刷新分段，MR27） | ✗ |
| Write DBI（反转省电） | ✗（'DBI' 全文 0 命中——DDR5 删除了 DBI） | ✓（DMI 兼职反转模式） | ✓（MR3 OP[7:6] Write & Read DBI；无 DMI 故纯反转、无掩码语义） | ✓（DBI[3:0]/PC，Table 29 DBI(ac)：charge count ≥4 → Inverted） |
| Read DBI | ✗ | ✓（DMI） | ✓ | ✓ |
| 字节部分写的出路 | DM 掩码 / 控制器 RMW | MASKED WRITE（DRAM 内 RMW，写吞吐 1/4） | **控制器 RMW**（硬件不再兜底） | 无此需求（全突发流式写） |

为什么变化（事实 [JEDEC] / 归因 [INFERENCE]）：
- **DDR5（服务器）**：写以整 line/整 burst 为主，引脚预算下 DBI 的省电收益让位给 DM 的字节掩码刚需（分散写/ECC 场景）；ODECC 引入 WR_Partial 标志优化 ECC 读改写。
- **LPDDR5（移动 SoC）**：字节粒度更新刚需 → MASKED WRITE 把 RMW 挪进 DRAM，代价是写吞吐 1/4（tCCDMW=4×列周期）。
- **LPDDR6（速率翻倍）**：4× 列周期的 RMW 串行化不可接受 → 连 DMI 与 MASKED WRITE 一起删除，**部分写责任交回控制器**（控制器 RMW 或全突发写）；DBI 保留（反转省电、不占新引脚）。
- **HBM（AI/图形全突发流式写）**：字节部分写需求不存在，引脚全给数据/训练；DBI(ac) 仅作动态反转省电。
- Controller 含义：LPDDR6 的控制器必须自己处理字节部分写（RMW 或整突发重排）——**写路径复杂度从 DRAM 转移回控制器**，与 A8 的复杂度转移方向一致。

【核心速答】DM（掩码）与 DBI（反转）是两件事：DDR5 只要掩码、删了反转；LPDDR5 用 DMI 一根线兼职两者 + 独立 MASKED WRITE 命令；LPDDR6 全删掩码只留反转；HBM 只有反转。变迁主线：**速率越高，DRAM 内 RMW 越贵，部分写责任逐步上移到控制器**。

## 问题路线图（纲领 Part I~XII）

> 每条问题标注覆盖状态：✅ 正文已答 / 🔶 部分覆盖（"是什么"有了，六层框架的物理根因～代价层未答全）/ ⬜ 待展开。补答流程：按纲 0.3 打来源标签 → 正文落锚点小节 → 回写本表状态。正文小节标题中的"纲领 X~Y"题号即本表编号。

### Part I：组织结构——Channel / Bank / Rank / PC / Sub-channel（A1~A12）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| A1 | Channel、Rank、BG、Bank、Row、Column 分别解决什么扩展问题？ | ✅ | §2.2 / §2.3 / §2.5（Rank/SID 判据、三家 BG 时序统一约定、HBM4 加 die=加 bank） |
| A2 | 为什么不能简单无限增加 Bank 提高并行度？ | ✅ | §2.2（一项收益+四堵墙：供电限速限额 / SA 面积布线 / 刷新窗口竞争 / IO 复用封顶；三家 tRRD/tFAW 数值） |
| A3 | Bank 越多，Scheduler、状态表、刷新、timing checker 增加什么成本？ | ✅ | §7.1（四部件成本：状态机/计时器、postpone 预算 9×tREFI、checker 四层、CAM 发射通路） |
| A4 | DDR5 为什么从 64-bit Channel 走向两个更窄 Sub-channel？ | ✅ | §1.2 / §2.2（16n prefetch 原文、64B 对齐算术、sub-channel=DIMM 组织考据、通道位置三级对照） |
| A5 | HBM 为什么需要 Channel + PC 两级结构？ | ✅ | §2.1（两级动机、PDE/SRE 通道级 vs REFab PC 级真值表证据、有时钟域 vs 无时钟域） |
| A6 | HBM PC 与 DDR5 Sub-channel 哪里相同、哪里不同？ | ✅ | §7.5 对比题 4（命令吞吐量化对照 + Table 31/32/NOTE 9 + 三条判据）/ §2.1 A5 |
| A7 | 判断"真正独立 Channel"最重要的判据？ | ✅ | §2.4（主判据 = 独立 CA 归属；辅助 = 时钟/电源域、命令带宽共享，见对比题 4 三判据） |
| A8 | 为什么并行结构越来越"更多、更窄、更独立"？ | ✅ | §1.2 A8 六层综合块（SI/SSO、命令并发、64B 对齐、CA 摊薄、LPDDR6 命令 2/4 周期代价） |
| A9 | 这种演进提高的是 peak bandwidth 还是有效利用率？ | ✅ | §1.2 A9 块（三分法：更多=peak+效率（看引脚）/更窄=高频细粒度前提/更独立=效率；排队视角+三个反向项） |
| A10 | 通道继续增加，瓶颈何时从 DRAM 转到 NoC / Controller / PHY？ | ✅ | §7.1 A10 块（分层转移判据：DRAM→Controller 全局层↔NoC→PHY/封装；组织方式决定增长形态） |
| A11 | HBM4 增加通道后，Controller 为什么不能仅复制 Scheduler？ | ✅ | §2.1（状态表翻倍 + channel-first 防热点）/ §7.1 |
| A12 | Bank 数、Channel 数、die 数、容量为什么开始解耦？ | ✅ | §1.2 / §2.1（HBM4）/ §2.3（LPDDR6 Mixed Package） |

### Part II：CA / Row / Column 命令接口（B1~B10）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| B1 | DDR 为什么长期复用 Command/Address 总线？ | ✅ | §3.2 B1 块（两层复用：地址分时自 SDRAM/命令编码自 DDR5（RAS_n 等 0 命中）；统一公式 + 两条对照路线；DDR4 结构 ⚠️） |
| B2 | CA pin 越少有什么好处？ | ✅ | §3.2 B1 块 B2 收口（成本走线 / SSO-skew / CA 摊薄三条） |
| B3 | pin 减少后为什么经常需要更多 command cycle？ | ✅ | §3.2 B3 收口（根数×拍数 ≥ 命令位宽；DDR5 2T / LPDDR6 2~4 周期例） |
| B4 | DDR5 多周期命令本质上在交换什么资源？ | ✅ | §3.2 B4 收口（恒定引脚/SI 预算 ↔ 命令延迟带宽 + DFI 2T 原子性的控制器编码成本） |
| B5 | HBM 为什么可以采用相对独立的 row / column command path？ | ✅ | §3.1 B5 块（TSV 降引脚成本 + tCCDS=2CK=4WCK=BL8 量化论证 + REFab CNOP/tRFCab 例外） |
| B6 | row/column 可重叠后，Scheduler 应如何变化？ | ✅ | §3.1 B6 块（双发射端口 1R+1C、行/列独立排队、跨域时序链照常、Table 32 配对规则）/ §7.1 |
| B7 | 为什么 ACT encoding 往往比 PRE/NOP 复杂？ | ✅ | §3.1 B7 块（ACT 24-bit 载荷位预算、1.5=ceil(24/10)×半拍、三重代价、RA[17:0] 跨协议对照、RA15 演进伏笔） |
| B8 | Command bandwidth 什么情况下成为真实 bottleneck？ | ✅ | §3.1 B8 块（总判据 + 需求 4 点 + 供给精确化 + 1TB/s 算例 + 缓解手段含 AP 权衡） |
| B9 | BL 越短，为什么 command overhead 越重要？ | ✅ | §3.4 B9 收口（28.6 : 9.2 : 7.2 = miss 放大的量化形态，连 B8） |
| B10 | 数据带宽继续增加而 CA bandwidth 不变，会出现什么问题？ | ✅ | §3.4 B10 块（问题面 + 四条出路代价矩阵 + HBM 形态对照——B 组收官） |

### Part III：Timing 从哪里来——阵列时序（C1~C12）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| C1 | tRCD 的物理过程是什么？ | ✅ | §3.4 C1/C2 块（五步链：均衡→译码→VPP 升压→电荷共享→SA 放大） |
| C2 | 为什么 ACT 之后不能立即 READ？ | ✅ | 同 C1（列选通挂载会破坏未完成放大——读等感知、写等可覆盖，故 tRCDWR<tRCDRD） |
| C3 | tRASmin 为什么存在？ | ✅ | §3.4 C3 块（破坏性读的修复驻留：不回写就真丢） |
| C4 | tRASmax 又为什么存在？ | ✅ | §3.4 C4 块（现行五标准 0 命中——历史 ≈9×tREFI 防 open row 阻塞 REF，现代控制器自管 REF 故删除） |
| C5 | tRP 实际上在 DRAM 内部完成了什么？ | ✅ | §3.4 C5 块（关 WL→SA 复位→BL 均衡 VDD/2；落袋=关 WL 本身） |
| C6 | tRC 为什么大体由 ACT→PRE→下一次 ACT 完整生命周期决定？ | ✅ | §3.4 C6 块（row 独占、三段不可压缩：回写/均衡/SA 复位；多 bank 交织隐藏 tRC） |
| C7 | tWR 为什么是 write 特有的？ | ✅ | §3.4 C7 块（读的回写由 tRAS 内建覆盖；写的覆盖是额外动作需 tWR 单独起算） |
| C8 | tRTP 为什么是 read 特有的？ | ✅ | §3.4 C8 块（PRE 截断读出/回写；tWR>tRTP 的对抗重建 vs 数据飞行根源，预答 D8 一半） |
| C9 | 为什么某些协议区分 tRCDRD / tRCDWR？ | ✅ | §3.4（HBM3 即有；写路径 43CK vs 57CK） |
| C10 | 为什么有些 timing 按 ns 固定、有些按 nCK 固定？ | ✅ | §3.4（max(ns,nCK) vs 纯 CK） |
| C11 | 频率大幅提高后，tRCD 绝对 ns 为什么不同比下降？ | ✅ | §3.4（阵列物理决定） |
| C12 | 哪些 timing 受阵列物理限制、哪些受接口限制？ | ✅ | §3.4 C12 收口（判据=决定因素：工艺/电压/温度/模拟 vs 频率/PCB/IO/SI；ns 守恒 vs nCK 缩放；三清单） |

### Part III+：Bank Group / 总线时序（D1~D10）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| D1 | 为什么出现 Bank Group？ | ✅ | §2.3 D1 块（剪刀差→单一数据路径气泡→物理分组+独立路径→tCCDS/tCCDL 诞生） |
| D2 | 为什么同 BG 与跨 BG 的 tCCD 不一样？ | ✅ | §2.3 对照表（跨BG=总线占用 / 同BG=阵列周期，三家数值已核原文） |
| D3 | tRRD_S / tRRD_L 背后的物理原因？ | ✅ | §2.2 墙 1（错峰=大电流激活限速；S/L 之分=BG 内外设/供电子网共享，与列域同根源） |
| D4 | tFAW 为什么不能理解为"又一个固定间隔"？ | ✅ | §2.2 墙 1（限额 vs 限速：滚动窗口配额 ≈4×tRRD_S+ns 余量；REFpb 计入窗口） |
| D5 | tFAW 限制的真正资源是什么？ | ✅ | §2.2 墙 1（激活电流预算：di/dt + IR drop；IDD 模式按 tFAW 排 ACT）；M 组延伸 |
| D6 | 提高 Bank Parallelism 为什么最终撞功耗 / current delivery？ | ✅ | §2.2（墙 1 供电 + 墙 4 IO 封顶）；M 组延伸 |
| D7 | tWTR / tRTW 为什么存在？ | ✅ | §3.4 D7/D8 块（DQ 双向：tRTW=方向翻转+写数据滞后余量；tWTR=方向转换+覆盖传播叠加，BG 定长短） |
| D8 | Read→Write 与 Write→Read 为什么通常不对称？ | ✅ | §3.4 D7/D8 块（三面不对称：电气/数值/系统；另一半见 C8 对抗重建） |
| D9 | ODT 切换为什么进入 read/write turnaround 成本？ | ⬜ | 待展开（依赖 Part VI G 组） |
| D10 | Controller 改不了这些 timing，Scheduler 还能优化什么？ | ✅ | §7.1 D10 块（七自由度：聚合重排/batch 切换/错峰 REF/postpone/映射/page 策略/QoS；分层归属 + 本质句） |

### Part IV：Refresh 为什么越来越复杂（E1~E14）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| E1 | DRAM 为什么必须 refresh？ | ✅ | §6.3 E1 块（1T1C 泄漏四类 + 温度指数 + 32ms/8192=3.9µs 平均、同 bank 上限 9×tREFI） |
| E2 | 为什么最早使用 all-bank refresh？ | ✅ | §6.3 E2 块（四理由 + 早期占空 3.3% 无感 + 密度演进压力 + HBM PC 级对照） |
| E3 | 为什么出现 per-bank / same-bank / finer-grain refresh？ | ✅ | §6.3 |
| E4 | 更细粒度 refresh 减少 stall 的同时增加什么 Controller 状态？ | ✅ | §6.3（bank 级刷新债 + per-bank deadline） |
| E5 | postpone / pull-in 为什么是合法的？ | ✅ | §6.3 + JESD209-5B §7.5.1（Figure 136/137：8×postpone/pull-in 窗口） |
| E6 | 最大 postpone 为什么不能直接全部用满？ | ✅ | §6.3 E6 块（保持硬要求 + 8+1/9×tREFI 上限 + tRFC 压缩下界 + 3DS 错峰电流约束 + MR4 温度预算） |
| E7 | Temperature 为什么影响 refresh rate？ | ✅ | §6.3 E7 块（Arrhenius 泄漏 + t_retention=Q/I + MR4 1x/2x + LPDDR 4x + 控制器 unhideable bubble 后果） |
| E8 | Refresh 与 QoS 为什么天然冲突？ | ✅ | §6.3（可调度的后台工作 + QoS 决定还债时机） |
| E9 | 为什么 refresh 必须有"不可继续让步"的 critical 状态？ | ✅ | §6.3 E9 块（软/硬两态：性能可协商 vs 正确性不可协商；LPDDR5 第 9 条强制/HBM3 max interval 即协议级 critical） |
| E10 | Row Hammer 为什么让 refresh 从周期行为变成 activation-aware？ | ✅ | §6.4 |
| E11 | RFM / ARFM / DRFM / PRAC 之间的演进逻辑？ | ✅ | §6.4（债粒度变细 + 背压显式化） |
| E12 | 为什么防护越来越 per-bank、targeted、bounded？ | ✅ | §6.4（HBM4 BRC / tDRFM） |
| E13 | 更安全的防护为什么一定吃掉一部分 bandwidth？ | ✅ | §6.4（带宽代价最小化命题） |
| E14 | Controller 如何计算最坏情况 Row Hammer bandwidth tax？ | ✅ | §6.4 E14 块（debt 收支框架 + 单 bank 税 = tRFCpb/(RAAIMT×tRC+tRFCpb) + RFMpb 占用规则 + DRFM/BRC 语义 + 协议边界）——E 组收官 |

### Part V：RAS 为什么越来越靠近 Memory（F1~F10）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| F1 | On-die ECC 解决什么问题？ | ✅ | §6.1（支撑更高密度 die） |
| F2 | 为什么 On-die ECC 不能完全替代系统 ECC？ | ✅ | §6.1（纵深防御） |
| F3 | ECC 放在 DRAM 内 / PHY / Controller / System 各覆盖哪些 error domain？ | 🔶 | §6.1（DRAM 内 vs 模组级）；PHY / 链路段待补 |
| F4 | 透明纠错为什么产生 observability blind spot？ | ✅ | §6.1（遥测盲区） |
| F5 | Interface parity / CRC 与 array ECC 的责任边界？ | 🔶 | §6.2（接口传输 parity 列举），边界待展开 |
| F6 | Correctable Error 为什么仍然值得统计？ | 🔶 | §6.1（从未纠错率间接推断），方法论待展开 |
| F7 | Scrubbing 的作用是什么？ | ✅ | §6.2（ECS / 错误擦洗） |
| F8 | Error retry 与 ECC 有什么区别？ | ⬜ | 待展开 |
| F9 | 错误随 data 返回 vs 单独 interrupt 上报，优缺点？ | ✅ | §6.2（SEV 带内 vs 侧带对照） |
| F10 | HBM 为什么特别重视 fault isolation？ | 🔶 | §6.2（故障隔离限列举），动机待展开 |

### Part VI：PHY 基础——"数字信号"为什么会失败（G1~G15）

> 本组为数字侧与协议侧的分界面，全组待展开（部分依赖：§3.3 时钟域、§4 训练）。**本组验收**：为什么协议速度提高以后不能单纯把 clock 加快，而必须不断加入 training、Vref、equalization、deskew 和更复杂的 package？

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| G1~G3 | ①数字 0/1 在 package trace 上为什么不是理想方波 ②rise/fall time 是什么 ③data rate 提高后有效 timing window 为什么变小 | ⬜ | 待展开 |
| G4~G5 | ④setup / hold margin ⑤eye diagram（Eye Width 与 Eye Height 各代表什么） | ⬜ | 待展开 |
| G6~G7 | ⑥jitter（Random vs Deterministic 的直觉区别）⑦skew（DQ-to-DQ 与 DQ-to-DQS 为何都重要） | ⬜ | 待展开 |
| G8~G11 | ⑧impedance mismatch ⑨信号为什么反射 ⑩termination / ODT ⑪ODT 太强或太弱的后果 | ⬜ | 待展开 |
| G12~G14 | ⑫crosstalk（高速宽总线为何尤其敏感）⑬simultaneous switching noise ⑭Vref 为什么影响判决 margin | ⬜ | 待展开 |
| G15 | PVT 为什么会让训练结果漂移？ | 🔶 | §4.1⑥（频变重训）/ §7.2（温漂重校 ZQ / Vref）；机理待展开 |

### Part VII：Clock / Strobe——CK / DQS / WCK / RDQS（H1~H12）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| H1~H2 | ①data 为什么不能只依赖全局 CK 采样 ②source-synchronous interface 是什么 | 🔶 | §3.3 事实层有（三时钟域）；概念定义待展开 |
| H3~H4 | ③DQS 的存在解决什么 ④为什么 write strobe 由 Controller/PHY 发、read strobe 由 DRAM 返回 | 🔶 | §3.3（WCK 写 / RDQS 读 per-byte 事实）；"为什么"待答 |
| H5 | LPDDR 为什么进一步分离 CK 与 WCK？ | ✅ | §3.3 |
| H6 | 降低 Command Clock、提高 Data Clock 解决什么问题？ | ✅ | §3.3（CKR：命令低速、数据全速） |
| H7 | CK 与 WCK 不同频为什么需要额外 synchronization？ | ✅ | §3.3（WCK2CK Leveling 锁 FIFO 指针） |
| H8 | Read DQS gating 的问题是什么？ | ⬜ | 待展开 |
| H9 | duty-cycle distortion 为什么在高速接口中重要？ | ⬜ | 待展开 |
| H10 | Clock jitter 最终如何转化为 eye loss？ | ⬜ | 与 G6 / G10 衔接 |
| H11 | 为什么不同 byte lane 需要独立 delay？ | 🔶 | §4.2（per-byte / per-pin 事实） |
| H12 | package / routing skew 为什么最终变成 PHY training 的工作？ | 🔶 | §4 组（训练即补偿 package 差异），待显式 |

### Part VIII：Training / Calibration（I1~I21）

> 每种 training 固定四问：**为什么需要？调什么参数？如何找到 pass window / optimal point？训练失败系统表现是什么？** 现状：LPDDR 主链流程已答（§4.1），四问法的后两问普遍未答全。

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| I1~I3 | CA Training：①CA 为什么也要 training ②找 timing 还是 voltage margin ③CA 错一 bit 为什么比 data bit 错误更严重 | 🔶 | §4.1①（调 CA delay + VREF(CA)）+ LPDDR6 六阶段③ CBT（PRBS16+LFSR 逐比特反馈、per-line delay）；③待展开（关联 §3.1 命令路径专用训练机制） |
| I4~I6 | Write Leveling：①Controller 为什么不知道 DRAM 实际看到的 CK/DQS 相位 ②补偿哪段 path mismatch ③多 rank / 多 die 为什么更复杂 | 🔶 | §3.3（WCK2CK Leveling = write-leveling 演化）+ LPDDR6 六阶段④（WFF 生成 2tCK 脉冲、分频采样 0/1 判相位）；四问未套 |
| I7~I9 | Read Training：①eye 中心如何得知 ②read gate training 与 read eye training 是否一回事 ③为什么 per-bit deskew | 🔶 | §4.1③（interval oscillator 读均衡）+ LPDDR6 六阶段⑤读训练（RDC/MR32-34 pattern、per-DQ delay）；②③待展开 |
| I10~I12 | Vref Training：①只扫 delay 为什么不够 ②2D voltage×timing eye 为什么更完整 ③optimal 为什么不一定是几何中心 | 🔶 | §4.1⑤（Vref(DQ) + per-pin DFE 事实）+ LPDDR6 六阶段①③（VREF(CS)/VREF(CA) 入 FSP）；2D 方法论待展开 |
| I13~I15 | Equalization：①CTLE / DFE 各解决什么 channel loss ②DFE 为什么依赖已判决 bit ③越高速越需要 EQ | 🔶 | §4.2（DFE 对照列举）；原理待展开 |
| I16~I18 | ZQ Calibration：①实际校准什么 ②driver impedance / ODT 为什么随 PVT 漂 ③不做 ZQ 在 eye 上什么表现 | ✅ | §4.1 LPDDR6 六阶段②（后台校准/ZQUF/ZQCal Latch/tZQLAT/ZQ Stop；240Ω 基准校准驱动+ODT） |
| I19~I21 | Re-training：①开机训练成功为何数小时后失效 ②frequency / temperature / voltage 哪些触发 ③full retrain vs 恢复 training set 的取舍 | 🔶 | §4.1⑥ / §7.2（training set 保存恢复 + 温漂重校）+ LPDDR6 六阶段①②（FSP 切换、ZQ Stop/DVFS 联动）；①待展开 |

### Part IX：DFI——Controller / PHY 责任边界（J1~J10、K1~K10）

> 全组为当前最大空白；附录 C 已备 DFI v5.2 PDF，展开时按 [DFI] 标签引用。

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| J1~J3 | ①为什么需要 DFI 而不是 Controller 直接驱动 pin ②一个 command 从 Controller 到 pin 中间经历什么 ③DFI frequency ratio 的本质 | ⬜ | 待展开；N3 / N4 与之衔接 |
| J4~J5 | ④同一 command 在不同 ratio 下为什么变成不同 phase placement ⑤PhyRdLat / PhyWrLat 为什么必须告知 Controller | ⬜ | 待展开 |
| J6~J7 | ⑥write data 为什么必须提前交付 PHY ⑦read data 返回后如何对回 command | ⬜ | 待展开 |
| J8~J9 | ⑧training interface 到底归 Controller 还是 PHY ⑨algorithm / sequence / delay cell control 各属于谁 | 🔶 | §4.2（三协议回读通道差异 → 训练状态机不可复用）；责任划分待按 [DFI] 展开 |
| J10 | frequency change 的 DFI / PHY handshake 为什么必须严格排序？ | 🔶 | §7.2（DFI 手序列事实）；排序细节待展开 |
| K1~K3 | ①self refresh 为什么不能当普通 command 下发 ②low-power sequence 前为什么 drain traffic ③Controller 如何确认 PHY 安全进入新状态 | 🔶 | K2 🔶 §3.1（进低功耗前排空在飞命令）；①③待展开 |
| K4~K5 | ④PHY 可以自己决定降频吗 ⑤frequency change 时哪些状态必须重新 training | 🔶 | K5 🔶 §3.3 / §7.2（DFS 后 WCK2CK 重对齐 / training set 恢复） |
| K6~K7 | ⑥DVFS 时 memory controller 为什么希望先进 IDLE ⑦初始化哪些步骤必须 Controller 主导、哪些只能 PHY 执行 | ⬜ | 待展开 |
| K8~K10 | ⑧DFI stall 时 Scheduler 冻结什么状态 ⑨PHY training failed 如何恢复 / 上报 ⑩协议 timing 与 PHY sequence timing 为什么分治 | ⬜ | 待展开；K9 关联 §6.2 错误上报 |

### Part X：Package / Physical Design（L1~L10、M1~M10、N1~N10）

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| L1~L2 | ①PCB / substrate / interposer / TSV / hybrid bonding 的互连距离量级 ②距离缩短为什么允许更宽、更低速接口 | ⬜ | 待展开（L3 是其推论） |
| L3 | HBM 为什么适合"超宽、相对低 per-pin rate"？ | ✅ | §1.1（3E→4 翻位宽的功耗学解释） |
| L4 | DDR 为什么更依赖长距离 channel equalization？ | 🔶 | §1.1（中距离互连提速率的边际成本）；机制待展开 |
| L5~L8 | ①interposer congestion 如何限制 channel 数 ②bump pitch 变小的收益与挑战 ③TSV 的 R/C 影响 ④hybrid bonding 与 TSV 是否同一问题 | ⬜ | 待展开 |
| L9~L10 | ①PHY 放 base die / logic die / SoC die 的优缺点 ②HBM4 为什么让 base die 重要性增加 | 🔶 | §1.1（PHY 向 base die / SoC 迁移）/ §5.1（I/O 电压开放配合逻辑 base die） |
| M1~M2 | ①大量 ACT 为什么造成电流峰值 ②tFAW / tRRD 的 power delivery 解读 | ⬜ | 与 D4~D6 同源，待展开 |
| M3~M6 | ③IR drop ④voltage droop 如何变成 timing failure ⑤多 DQ 同翻对 supply / ground 的影响 ⑥decap 解决什么 | ⬜ | 待展开 |
| M7 | 数据速率提高 vs 总线加宽，哪个对 power delivery 压力更大？ | ✅ | §5.2（速率路线花 IO 功耗、位宽路线能效更好） |
| M8 | HBM stack 的 power delivery 为什么比 DIMM 更困难？ | 🔶 | §1.2（TSV / 键合代价）/ §5.1（多供电轨） |
| M9 | Thermal gradient 为什么导致不同 die 的 timing margin 不同？ | ⬜ | 待展开 |
| M10 | Controller throttling 如何与 thermal / power limit 联动？ | 🔶 | §5.3（HBM 热感知节流）；联动机制待展开 |
| N1~N2 | ①PHY 周围为什么是 timing closure 最难区域 ②Controller→PHY 宽 data bus 的 routing 压力 | ⬜ | 待展开 |
| N3~N5 | ③DFI ratio 增大为什么能降 controller core frequency ④ratio 增大的代价（latency / bus width / phase logic）⑤multi-cycle / source-synchronous path vs 同步 path | ⬜ | 待展开；N3~N4 与 J3~J4 衔接 |
| N6~N8 | ⑥CDC 为什么在 memory subsystem 大量存在 ⑦async FIFO metastability 的结构性控制 ⑧clock / power gating 对 DFI / PHY 状态保持的影响 | ⬜ | 待展开 |
| N9~N10 | ⑨PHY hard macro 对 floorplan 的约束 ⑩HBM PHY 靠近 die edge / bump array 对 NoC 与 Controller placement 的影响 | ⬜ | 待展开 |

### Part XI：横向比较——相同问题，不同答案（O1~O11）

> 以后不要只比较 HBM BL8 / DDR BL16 / LPDDR BLxx，而要问以下十一问。

| # | 问题 | 状态 | 锚点 / 备注 |
|---|---|---|---|
| O1 | 都需要 bank parallelism，为什么组织方式不同？ | ✅ | §2.4 / §7.1 |
| O2 | 都需要 training，为什么 training 方法不同？ | ✅ | §4.2（回读通道根差异） |
| O3 | LPDDR 强调 DVFS，HBM 为什么倾向固定高带宽工作点？ | ✅ | §5.3 / §7.2 |
| O4 | HBM 可以用非常宽的 interface，DDR 为什么不可以？ | ✅ | §1.1（+L3） |
| O5 | DDR 重视 capacity / DIMM 生态，HBM 重视 bandwidth density？ | ✅ | §1.3 / §7.4 |
| O6 | LPDDR 为什么愿意接受更复杂的 clock / power management？ | ✅ | §5.3 |
| O7 | 同样面对 Row Hammer，为什么采用不同粒度的解法？ | ✅ | §6.4 |
| O8 | 同样面对 pin 限制，三者如何做 pin↔frequency↔command bandwidth 交换？ | 🔶 | §3.2（DDR5 引脚换拍数）/ §3.3（LPDDR CKR）；HBM 视角待补 |
| O9 | 同样面对 refresh stall，谁更依赖 fine-grain refresh，为什么？ | ✅ | §6.3（粒度差异根源段） |
| O10 | 同样翻倍带宽：加 pin / 加 rate / 加 channel，各把问题转移到哪里？ | ✅ | §1.1（3→3E 靠速率、3E→4 靠位宽） |
| O11 | 写路径字节粒度：Masked Write / DM / DMI / DBI 各协议支持矩阵与演进原因？ | ✅ | §7.5 对比题 5（DDR5 删 DBI 留 DM；LPDDR5 MASKED WRITE → LPDDR6 删 DMI/MASKED WRITE；HBM 仅反转 DBI） |

### Part XII：纵向演进表（模板 + 样例）

每研究一代协议，固定做一张六列表，并回答七问：上一代最大的三个瓶颈是什么？这一代新增哪些 Feature？每个 Feature 对应哪个瓶颈？有没有只为容量 / 功耗 / RAS 服务的 Feature？复杂度转移到了 Controller、PHY 还是反过来？

**模板**

| 项目 | 上一代 | 当前代 | 为什么变 | Controller 代价 | PHY/Package 代价 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

**样例一：DDR4 → DDR5**（素材：§2.2 / §3.2 / §6.1 / §6.4 / §7.5 对比题 3；"为什么变"列属 [PHYSICAL-EXPLANATION] / [INFERENCE]）

| 项目 | DDR4 | DDR5 | 为什么变 | Controller 代价 | PHY/Package 代价 |
|---|---|---|---|---|---|
| 通道组织 | 1×64-bit | 2×32-bit 独立子通道 | cache line（64B）完整落入单子通道；命令并发 ×2 | 双实例状态表 / 时序检查 / 刷新错峰 | DFI / 训练双实例 |
| 命令接口 | 20+ CA 全 1T | 14-bit CA + 1T/2T | 子通道化后引脚预算减半——引脚换拍数 | 编码器区分 1T/2T、2T 原子性 | CA 训练 / 眼图裕量 |
| RAS | 系统 ECC 为主 | ODECC 强制（128+8 SEC）+ side-band | die 密度↑ → 原始错误率↑ | 透明纠错→遥测盲区，需 side-band 兜底 | DRAM 内校验逻辑 |
| 电源 | 供电简单 | PMIC 上移模组 + VPP | 服务器电源管理精细化 | 上电时序 / 侧带管理对接模组 | 模组 PMIC、VPP 轨 |
| 刷新 | 全 bank 为主 | FGR / REFsb + RFM/DRFM/ARFM | 容量↑ → tRFC 变长；Row Hammer | 刷新债 / 信用账本进 QoS | 阵列管理逻辑 |

**样例二：HBM3 → HBM4**（素材：§1.1 / §2.1 / §5.1 / §6.2；"为什么变"列属 [PHYSICAL-EXPLANATION] / [INFERENCE]）

| 项目 | HBM3/3E | HBM4 | 为什么变 | Controller 代价 | PHY/Package 代价 |
|---|---|---|---|---|---|
| 接口 | 1024-bit / 16ch | 2048-bit / 32ch | 继续提速率边际成本（均衡、训练、pJ/bit、良率）过高 → 翻位宽 | 32ch / 64PC 状态表翻倍；channel-first 防热点 | bump 密度 / 中介层布线；PHY 迁向 base die |
| 电气 | I/O 1.1V 固定 | I/O 厂商自定、VDDC 1.05V | 把余量下放厂商，换 PHY 工艺自由度 | 电气取公约数 | PHY 工艺选择自由 |
| RAS | RAA + ARFM | RFMpb / DRFMpb + BRC、ECS 多 bit | 行锤定向化 + 带宽代价有界 | 风险 bank 跟踪 / 有界刷新编排 | DRAM 内逻辑增加 |
| 容量 | 通道与容量同步增长 | 4 die 满 32ch；5~16 die 只加容量 / SID / bank | 带宽需求与容量需求不同步 | bank 数可枚举配置（16~64/ch） | die 堆叠高度 / 散热 |

**待补样例三：LPDDR5 → LPDDR6**（素材已备：§1.1 速率阶梯、§2.3 x24/x12 与 BL24/BL48、§5.3 VDD2 强制拆分 + DVFS 族、§6.4 PRAC + ABO），⬜ 待按模板成表。

## 附录

### A. 术语表

| 术语 | 含义 |
|---|---|
| Channel / PC（Pseudo-Channel） | 通道；HBM 通道内的伪通道（电源/刷新/阵列时序半独立分区，共享行列命令总线） |
| Sub-Channel（SC） | DDR5 DIMM 的独立 32/40-bit 子通道；LPDDR6 的子通道（自带 CS/CA/CK） |
| DWORD | HBM 32-bit 数据切片（训练/修复粒度，每 PC 一个） |
| SEV | HBM 读突发随附的错误严重度位（per-PC SEV[1:0]） |
| CKR | LPDDR 的 WCK:CK 频率比（4:1 → 533~6400；2:1 → 533~3200 Mbps） |
| BL/n | LPDDR6 有效突发长度（Effective Burst Length） |
| Interval Oscillator（DQS 振荡器） | LPDDR 片内振荡器，用于读均衡训练（标准名 tWCK2DQ Interval Oscillator） |
| WCK2CK Leveling | LPDDR5 中 WCK 与 CK 的同步 FIFO 指针对齐训练 |
| CBT | Command Bus Training（LPDDR 命令总线训练） |
| MISR | 多输入签名寄存器；HBM 训练经 IEEE 1500 回读 AWORD/DWORD MISR 签名 |
| DVFSC / Q / H / L / B | LPDDR6 DVFS 模式族：VDD2 core / VDDQ / VDD2C 高 / VDD2D 低 / VDD2D 高 |
| REFab / REFsb / REFpb | 全 bank 刷新 / 同 BG 同号 bank 刷新 / 单 bank（或 bank pair）刷新 |
| RFM / ARFM / DRFM / PRAC / ABO | 刷新管理族：刷新管理 / 自适应刷新管理 / 定向刷新管理（含 per-bank）/ 可编程行激活计数 / 告警退避 |
| RAA | Row Activate Advisory：行激活计数（HBM3 阈值 RAAIMT/RAAMMT/RAADEC；DDR5 计数器在 MR59） |
| ECS | 自动错误检查与擦洗（HBM/DDR5，含错误日志 MR） |
| ODECC | DDR5 片上 ECC（128 数据 + 8 校验 SEC，对系统透明） |
| BRC / tDRFM | HBM4 Bounded Refresh Configuration 及其时序 |

### B. JEDEC 标准号

| 标准 | 内容 | 备注 |
|---|---|---|
| JESD238 | HBM3 DRAM | 2022.01 |
| JESD238A | HBM3E | 9.6 Gbps |
| JESD270-4 | HBM4 DRAM | 2025.04；32ch / 2048-bit；DRFM/BRC/SEV/ECS |
| JESD79-5 / -5A / -5B / -5C | DDR5 SDRAM | 2020.07 起；速率档至 8800 |
| JESD209-5 / -5B / -5C | LPDDR5 / LPDDR5X | 2019.02 起；8533/9600/10700 档 |
| JESD209-6 | LPDDR6 | 2025.07.09；x24/x12 效率模式；PRAC+ABO；DVFS 族 |
| DDR PHY Interface（DFI）v5.x | MC-PHY 接口 | 频率切换/训练/低功耗手序列 |

### C. 本仓库协议参考文档（本手册核对所据）

相对 `univista\protocol\` 目录：

- `HBM\eetop.cn_JESD238_HBM3.pdf`、`HBM\JESD270-4.pdf`
- `DDR\JESD79-5B_v1-2_DDR5_SDRAM.pdf`、`DDR\JESD209-5B.pdf`
- `LPDDR6\JESD209-6_LPDDR6 Standard.pdf`

（另有 `LPDDR6\eetop.cn_DDR_PHY_Interface_Specification_v5_2.pdf`（DFI）等可后续补充展开纲领 J/K 组（DFI 手序列 / 初始化 / 低功耗）、E14（刷新开销定量）、D 组（总线时序）与验证视角问题。）

### D. 数据出处与核实状态

**✅ 已对标准原文核对（2026-09，PDF 关键词提取）**

- HBM3：行/列总线 R[9:0]/C[7:0]、ACT 1.5 拍/行 half-cycle/列 1 拍、无 CKE 引脚、BL8、电压 core 1.1V/I-O 1.1V/Tx 0.4V、供电轨 VDDC/VDDQ/VDDQL/VPP、§3.1.3 双命令接口、§6.9 On-die ECC、SEV 引脚、RAA/ARFM（RAAIMT/RAAMMT/RAADEC）、MISR/IEEE 1500（§6.8）
- HBM4：32ch/64PC（4 die 满配）、bank 16~64/channel、1KB page/PC、BL8、VDDC 1.05V/I-O 厂商自定、tRCDRD/tRCDWR/tRAS/tRP、RFMpb/DRFMpb/BRC/tDRFM、ECS 多 bit、SEV Table 67/68
- DDR5：ODECC 128+8 SEC（§4.36）、REFsb/tRFCsb 语义、FGR/刷新推迟、RFM/DRFM/ARFM（MR59）、DFE/DCA/VrefDQ（§3.5.71+）、MPC（§4.15）、子通道 2×32/40-bit、14-bit CA 1T/2T、VPP 引脚存在
- LPDDR5/5X：VDD1/VDD2H/VDD2L/VDDQ 四轨与上电顺序、REFpb/tRFCpb/tpbr2act/tpbR2pbR、Optimized Refresh、RFM（Table 311-316）/ARFM（§7.7.6）、DFE（§7.7.7）、WCK2CK Leveling（§4.2.5）、Interval Oscillator（§7.6.14）、CA Training（Fig25-27）、CKR 变更（§7.6.7）、DVFSQ/VRCG
- LPDDR6：x24 Normal / x12 Dynamic-Static Efficiency、Mixed Packages、SC 结构（12DQ+RDQS+4CA+CS+CK，4BG×4B）、BL24/BL48 与 288=256+32、BL/n 与同 BG tCCD、四轨电压默认值与容差、DVFS 族（DVFSC/Q/H/L/B）、PRAC/ABO（MR86-89）、Meta 寄存器
- 厂商/公开资料：HBM4 产品速率（三星 3.3TB/s≈12.8G、美光 >11G/>2.8TB/s）、LPDDR5X 8533/9600/10700 档、HBM4 兼容 HBM3 控制器（JEDEC/Tom's Hardware）

**✅ 2026-09 A1 批次（第二轮逐条原文核对）**

- DDR5（JESD79-5B）：tRRD_S=跨BG / tRRD_L=同BG + tFAW 四激活窗口（§4.6）；列域 S=Short=跨BG——tCCD_S=8nCK、tCCD_S_WR=8nCK（速度档定义行）、同 BG tCCD_L=8~16nCK（MR13 Table 29 按速率档编程）、同 BG W→W Max(32nCK,20ns)（Figure 52 图注 + 3DS 表 tCCD_L_WR_slr）、W→R 同BG Max(16nCK,10ns) / 跨BG Max(4nCK,2ns)；tCCD_M（同BG跨bank）仅存于 §13.3 速度档表（Table 318：3200~4000 档=tCCD_L，此时 S=M=L=8；高速档 max(8nCK,~4ns)）；3DS 族 _slr/_dlr 后缀（tCCD_S_slr=8，p483）与错峰刷新 tRFC_dpr≈tRFC_slr/3（§4.13.5）
- HBM4（JESD270-4）：§1/§2 "requires 4 DRAM dies to support 32 channels; dies beyond 4 add capacity/SIDs/banks per pseudo channel"；Table 4 Bank Address = BA[3:0] → SID[0]+BA[3:0] → SID[1:0]+BA[3:0]（16/32/48/64 banks）；Table 5 BG 分组 A~H（48B 时 SID[1:0]=11 invalid）；Table 6 tRRDS/tRRDL、tCCDS/tCCDL（R2R 或 tCCDR）；Figure 1 每 die 8ch
- LPDDR5（JESD209-5B）：Table 330 BL/n 定义（CKR 4:1 BG 模式 BL16：跨 BG BL/n_min=2tCK、同 BG BL/n_max=4tCK；NOTE 1 BL/n=tCCD(min)；NOTE 6/7）；§2.2.3 三种 bank 架构（BG/8B/16B Mode，5X 仅 BG+16B）；§7.2.1.6 Rank to rank WCK2CK Sync（two rank）
- HBM3（JESD238）：§1/§2 "each channel is independent…all accesses within a single channel must have the same latency"；全文无 "Rank"；Table 30 ACT 编码含 SID[1:0]+BA[3:0]；地址表 Column CA[4:0]、Prefetch 256-bit/PC、页 1KB/PC（BL 内列位不对外）
- **核对方法教训**：5B 的 From/To 多列表（p173-175）PDF 提取后行错位，曾致 tCCD_S/L 的 BG 归属误读（tCCD_S 实为跨 BG）；对齐以**图注散文**（Figure 51/52）与**速度档定义行**（"…delay for different bank group"）为权威。

**✅ 2026-09 A2 批次**

- DDR5（JESD79-5B Table 318，3200~4000 档）：tRRD_S(1K/2K)=8nCK；tRRD_L(1K/2K)=Max(8nCK,5ns)；tFAW(1K)=Max(32nCK,20→16ns)、tFAW(2K)=Max(40nCK,25→20ns)——页大小进入激活窗口；IDD 测量模式（Table 311 IDD7 等）按 tRRD_S/tFAW/tRCD 排 ACT；MR4 刷新速率随温度 1x/2x（tREFI/2，85°C 起档）
- LPDDR5（JESD209-5B）：tFAW 滚动窗口原文 "No more than 4 Banks may be activated (or refreshed, in the case of REFpb) in a rolling tFAW window"（§8.1.2 起）；8B 模式 tRRD=max(10ns,2nCK)、tFAW=40ns；Table 235：tREFW=32ms、R=8192、REFab tREFI=3.906µs、REFpb tREFIpb=488ns、tRFCab=130~380ns、tRFCpb=60~190ns（随密度）；刷新 postpone/pull-in ±9×tREFIe（§7.5.1 Figure 136/137）
- HBM3（JESD238）：AC 表同段定义 tRRDL/tRRDS（"ACTIVATE to ACTIVATE or PER BANK REFRESH bank B command delay"）+ tFAW + RAA 同一张表（p175）；刷新命令表 NOTE 1 "tFAW parameter must be observed as well"、REFpb（不同 bank）走 tRRD、REFpb 按 16-bank set 推进（NOTE 3）；HBM4（JESD270-4 p73）同构

**✅ 2026-09 A4 批次**

- DDR5（JESD79-5B p42 "Functionality"）："uses a **16n prefetch architecture** to achieve high-speed operation… a single 16n-bit wide, eight clock data transfer at the internal DRAM core and sixteen corresponding n-bit wide, one-half clock cycle data transfers at the I/O pins"；突发 "a burst length of sixteen or a 'chopped' burst of eight"（BC8 OTF 保留，主粒度 BL16）；8Gb 起始 16B/8BG×2（x4/x8），≥16Gb 翻倍为 32B/8BG×4
- **术语考据**：'sub-channel' 在 JESD79-5B 全文 0 命中（independent channel / two channels / 32-bit channel 亦均 0 命中）——双子通道是 DIMM 级组织（颗粒本身单通道、各自 CA[13:0]/CS_n），非标准术语

**✅ 2026-09 A5 批次**

- HBM3（JESD238）命令真值表（p49 Table 30）：REFab/RFMpb/RFMab 编码携带 PC 位（刷新以 PC 为单位，REFab = 刷该 PC 全部 bank）；**PDE 的 PC 位为定值 H、SRE 为定值 L、PDX/SRX 为 H**——电源管理命令不区分 PC（NOTE 4：地址位 Don't Care）；SRE 前提原文（p97 §6.3.4.2）"only allowed when all banks in both pseudo channels are precharged with tRP satisfied"；PD 期间 CK 可停止（NOTE 6）、SR 无外部时钟
- HBM4（JESD270-4 p104 §6.3.4.1）：PDE/SRE 同构（通道级）

**✅ 2026-09 A6 批次**

- HBM3（JESD238）Table 31（列命令真值表，p50）：RD/RDA/WR/WRA 为 1 拍（DDR 双沿 2 beat × C[7:0] = 16 bit），编码显式携带 PC + SID + BA[2:0] + CA[4:0]——列命令选定 PC；NOTE 9（p49）："ACT is a 1.5 cycle command and another command is not allowed during ACT command"；Table 32（p51）：行命令上升/下降沿配对表含 "Different PC, Any Bank" 列——跨 PC 行/列配对合法

**✅ 2026-09 A7 批次**

- 无新协议考据：主判据"独立 CA 归属"由 A4~A6 批次证据链支撑（HBM PC 列命令显式带 PC 但共享 C[7:0] → 非独立命令域；LPDDR6 SC 自带 CS/CA/CK → 独立命令域；PDE/SRE PC 位定值 → 电源域通道级）

**✅ 2026-09 A8 批次**

- LPDDR6（JESD209-6）Table 254 NOTE 1（p217）："LPDDR6 commands are two clock cycles long and defined by the states of CS at the 1st and 2nd rising edge (R1, R2) of clock and CA[3:0] at the 1st rising edge (R1), the 1st falling edge (F1), the 2nd rising edge (R2) and the 2nd falling edge (F2)… some operations such as ACTIVATE and MODE REGISTER WRITE require two commands"；NOTE 4：ACT-1 后必须跟 ACT-2（tAAD 窗口内仅 CAS/WRITE/READ/异 bank PRE/REF 可插入）；Table 1（p36）：CA 为 DDR 采样（双沿）、CS 为 SDR（单沿）

**✅ 2026-09 A9 批次**

- 无新协议考据：综合 A2/A4/A6/A8 既有证据成文（§1.2 A9 块）；A8 Tradeoff 的"peak 不变"过度概括已修正为"取决于总引脚是否增加"

**✅ 2026-09 O11 批次（新题：写路径字节粒度）**

- DDR5（JESD79-5B）：DM_n/DMU_n/DML_n 引脚定义（p37："Input Data Mask… masked when DM_n sampled LOW… enabled by MR5:OP[5]=1. DM is not supported for x4 device"）；§4.8.1 Write Data Mask（p179，x8/x16 各 byte 一根 DM）；**'DBI' 全文 0 命中**（DDR5 删除 DBI）；WR_Partial（p151/179/500，配合 ODECC 的部分写标志）
- LPDDR6（JESD209-6）：Table 1 NOTE 2（p36）："**There is no DMI in LPDDR6**"；Table 254 命令表无 MASKED WRITE（仅 WR-S/WR-L）；'Masked' 仅 PASR Segment Mask（MR27，p171——刷新分段，非数据掩码）；MR3 OP[7:6] = Write & Read DBI（Table 16 默认禁用）
- LPDDR5（JESD209-5B）：MASKED WRITE + tCCDMW（Table 226，同 BG=4×BL/n、异 BG=BL/n，DRAM 内 RMW）；"One Data Mask-Invert (DMI) pin is provided per byte lane"（§7.4.9）
- HBM3（JESD238）：Table 29 DBI(ac)（p45）："DQ Charge Count 0 to 3 → Not inverted / 4 → Inverted"（纯反转、动态状态机）；'Data Mask' 0 命中；HBM4（JESD270-4）同构（'mask' 仅为 DQ Receiver Mask，p181）

**✅ 2026-09 A10 批次**

- 无新协议考据：系统级综合题，成文于 §7.1 A10 块（用户三点 + 分层转移判据），串联 A2/A3/A9/A11 与 §1.3/§2.1

**✅ 2026-09 B1 批次**

- DDR5（JESD79-5B）：**'RAS_n'/'CAS_n'/'WE_n' 全文 0 命中**（专用控制线已删除）；"CS is part of the command code"（p37）；§1 血统声明（"created based on the DDR4 standards (JESD79-4) and some aspects of the DDR, DDR2, DDR3, and LPDDR4 standards"，p33）
- LPDDR5（JESD209-5B）：CA[6:0] 引脚定义（p31："CA signals provide the Command and Address input according to the Command Truth Table"）+ "CS is part of the command code"
- LPDDR6/HBM 对照引用 A8/A5 批次既有证据（Table 254 NOTE 1/4；§3.1 行列分总线）

**✅ 2026-09 B2 批次**

- 无新协议考据：B2 收口综合 B1 统一公式 + A8 Physical cause 层（SSO/skew）+ A6 CA 摊薄证据

**✅ 2026-09 B3/B4 批次**

- 无新协议考据：B3/B4 收口为 B1 统一公式的直接推论（DDR5 2T=28bit；LPDDR6 命令 2 周期/ACT 4 周期证据见 A8 批次）

**✅ 2026-09 B5/B6 批次**

- HBM3（JESD238）Table 93（p175，spec 页 162）：**tCCDS = 2 nCK**（"RD/WR bank A to RD/WR bank B command delay different bank group"）、tCCDL = Max(4, 2.5 ns/tCK)、tCCDR = "RD SID A to RD SID B command delay"——tCCDS=2CK=4WCK=BL8 占用（WCK=2×CK 由速率算术导出 [INFERENCE]）
- HBM3 §6.3.2.5（p60，页 46）：REF 命令拍列域 CNOP 原文（"The REFRESH command also requires a CNOP command on the column command inputs C[7:0], unless the column command is for the other pseudo channel"）+ 行下降沿 RNOP/PRE（须另一 PC）；**NOTE 1（p61，页 47）**："Only RNOP and CNOP commands are allowed after a REFRESH command until tRFCab has expired"（tRFCab 期间通道级冻结，字面未按 PC 限定——范围解释待深挖）；NOTE 2：两条 REF 最大间隔 9×tREFI
- HBM3 §6.3.3（p70，页 56）：CNOP 定义（1-cycle，"prevents unwanted column commands from being registered"）；SRE 同样要求 CNOP（p97）

**✅ 2026-09 B7 批次**

- HBM3（JESD238）Table 30（p49）：ACT 三拍位分配（R 拍 opcode+PC+SID+BA[3:0]；F 拍 RA[14:8]；R 拍 RA[7:0]，各拍带 H,H 前缀标记）——ACT 载荷 ≈24 bit / 30 slot
- HBM3 p20 地址表：RA[12:0]（8/12/16Gb）→ RA[13:0]（24/32Gb）；HBM4（JESD270-4 p254 DEVICE_ID NOTE 2）："if additions to the addressing table increase the row address to include RA15"（RA15 预留）
- DDR5（JESD79-5B）Table 311（p466）：Row Address [17:0]、Column Address [10:0]、BA[1:0]、BG[2:0]、CID[2:0]（IDD 模式位宽直证 18-bit 行地址）
- HBM3 p53：ACT 奇偶校验（"Parity is evaluated with the ACTIVATE command when the parity calculation is enabled in MR0 OP6"）

**✅ 2026-09 B8 批次**

- 无新协议考据：B8 块综合 B1 统一公式 / B5（tCCDS、CNOP）/ B7（ACT 周期）/ A2 墙 3（REF 占空）成文；1TB/s 算例为 [INFERENCE]

**✅ 2026-09 B9/B10 批次（B 组收官）**

- 无新协议考据：B9 收口引用既有 28.6 : 9.2 : 7.2（§3.4 既有折算）；B10 块综合 B1/B4/B7/B8/A8/O11 成文（四条出路代价矩阵；"CA 根数×频率二维 trade"与"HBM 形态买断"为 [INFERENCE]）

**✅ 2026-09 C1/C2 批次**

- 无新协议考据：器件物理综合（五步链 + 感知 vs 覆盖），全 [PHYSICAL-EXPLANATION]；~100mV/fF 量级为业界常识估计；tRCDWR/tRCDRD 引用 §3.4 既有数值（43/57CK）

**✅ 2026-09 C3/C4/C5 批次**

- **'tRASmax' 五标准 0 命中考据**：JESD79-5B / JESD209-5B / JESD209-6 / JESD238 / JESD270-4 全部 0 命中——现行协议族不定义 tRASmax；历史动机 ≈9×tREFI（防 open row 阻塞 REF）标 [PROJECT/⚠️ 旧标准待核]
- "9×tREFI" 与 LPDDR5 postpone 预算"9×tREFIe"（Figure 136/137）数字同源的观察为 [INFERENCE]
- HBM3 NOTE 2（p65，页 51）："A bank must be in the idle state with tRP satisfied before it is refreshed"（引用既有提取）

**✅ 2026-09 C12 批次（C 组收官）**

- 无新协议考据：C12 判据（阵列=工艺/电压/温度/模拟电路、ns 守恒；接口=频率/PCB/IO 设计/SI、nCK 缩放）为用户框架；三清单综合 C 组/B 组既有证据

**✅ 2026-09 D1 批次**

- 无新协议考据：D1 块为用户框架（核心/接口频率剪刀差 → 单一数据路径气泡 → BG 物理分组+独立路径 → tCCDS/tCCDL 诞生），证据引用 D2 已核的 Table 29/330/Table 6

**✅ 2026-09 D7/D8 批次**

- 引用既有提取：DDR5 Table 43（p173，页 141）tRTW 公式（"CL - CWL + RBL/2 + 2tCK - (Read DQS offset) + (tRPST - 0.5tCK) + tWPRE"）与 tWTR_L/tWTR_S 分 BG 行；p483 3DS 表 tWTR_L=Max(16nCK,10ns)/tWTR_S=Max(4nCK,2~2.5ns)；其余为用户推导与 C8 框架延伸

**✅ 2026-09 D10 批次（D 组收官，D9 留 G 组）**

- 无新协议考据：D10 七自由度为 [PROJECT] 系统化，交叉引用 §3.4 调度骨架 / A2/A3/A9/A11 / B8 / D7·D8

**✅ 2026-09 E1/E2 批次**

- 物理链为 [PHYSICAL-EXPLANATION]（泄漏四类、~2×/10°C、~32ms/8192=3.9µs）；"同 bank REF 间隔最大 9×tREFI（REFab/REFsb 皆然）"为 [PROJECT]
- E2 引用既有提取：Table 235 tRFCab=130→380ns（密度演进压力）；HBM3 REFpb 16-bank set（p65 NOTE 3）；LPDDR5 REFab 可 postpone（§7.5.1）

**✅ 2026-09 E6 批次**

- 引用既有提取：LPDDR5 §7.5.1 Figure 136/137（推迟 8 条/第 9 条强制/9×tREFIe）；HBM3 §6.3.2.5 NOTE 2（p61）"maximum time interval between two REFRESH commands is 9 × tREFI"；Table 235 R=8192/tREFW=32ms；DDR5 §4.13.5 错峰刷新 tRFC_dpr≈tRFC_slr/3（p206，IDD5B1 电流限制）；MR4 温度 1x/2x
- "catch-up"等控制器实现视角术语按用户意见移除，E6 保持纯协议口径

**✅ 2026-09 E7 批次**

- 无新协议考据：E7 块物理链为 [PHYSICAL-EXPLANATION]（Arrhenius、t_retention=Q/I、×2/10°C 经验系数）；MR4 温度编码（p67 Table 25）与 Table 235 tREFW=32ms(1x) 引用既有提取；LPDDR 4x 档引用 §5.3 既有事实

**✅ 2026-09 E9 批次**

- 无新协议考据：E9 块为协议口径（LPDDR5 第 9 条强制 / HBM3 max interval 9×tREFI 引用既有提取）；按用户纪律剔除控制器实现视角

**✅ 2026-09 E14 批次（E 组收官）**

- 公式（tRFCpb/(RAAIMT×tRC+tRFCpb)、RFMpb 目标 bank 占 tRFCpb 不叠加 tRREFD、异 bank 按 tRREFD 穿插）为用户推导的协议组合 [PROJECT]；引用既有术语表 RAAIMT/RAAMMT/RAADEC 与 p65 刷新约束表（tRFCpb/tRREFD/tRC）；DRFM/BRC 语义引用 §6.4 既有

**✅ 2026-09 Training 全流程批次（LPDDR6 六阶段，I 组事实层闭环）**

- 用户口径 [PROJECT]：六阶段（CS Training/CBT/WCK2CK/WCK-DQ/ZQ 后台校准/Re-train）+ 全局总结（低频进出高频练；VREF 存 FSP、delay 存 PHY）；与已提取标准片段交叉验证一致——JESD209-6 §4.2.1.7（p69-70：CS toggle/32nCK/VREF CS MR15）、Table 254（WFF/RFF/RDC）、MR30-34 DQ Calibration pattern（p173）

**⚠️ 仍待确认（修订时更新本表）**

1. E1 的功耗/pJ/bit 数字——建议用项目实测或厂商 datasheet 替换；
2. DDR5 VPP 数值（暂标 1.8V，以 JESD79-5C 表为准）；
3. DDR5 16Gb 档 bank/BG 数（暂按厂商口径 8BG×4B）；
4. LPDDR5X 各速率档对应的 JESD209-5B/5C 条目编号；
5. HBM4 向后兼容的引脚级机制细节（以 JESD270-4 + 厂商应用笔记为准）；
6. DDR4 列地址是否包含 BL 内部位（A1 用户口径"DDR4 col 地址含 BL 部分"；仓库无 JESD79-4，待取得后核对）；
7. DDR4 及更早代际的 CA/控制线结构（专用 RAS_n/CAS_n/WE_n、约 20+ 根 CA/控制线——B1 代际梳理口径；仓库无 JESD79-4，待取得后核对）。

---

> **标签映射（纲 0.3）**：附录 D 的 ✅ 条目 = [JEDEC]；厂商/公开资料 = [VENDOR]；⚠️ 条目 = [UNKNOWN]；正文与演进表中的"为什么"叙述（如 §1.1 翻位宽的功耗学解释、§6.3 粒度差异根源）属 [PHYSICAL-EXPLANATION] / [INFERENCE]，引用时注意与标准原文区分。

> **维护说明**：本文档由问题清单（旧编号 A1~H4 + 分批讨论）整理而成，2026-09 并入《研究纲领》：正文题号统一迁移为纲领 Part I~XII 编号（A~O；旧编号与新编号含义不同，勿混用），新增"研究纲领"与"问题路线图"两节。后续补答路线图 🔶 / ⬜ 问题时：按纲 0.3 打标签 → 正文落锚点 → 更新路线图状态；修订任何数字时同步更新附录 D 的核实状态。
















