# 多协议内存对比：HBM3/3E/4 · DDR5 · LPDDR5/5X/6

> **定位**：Memory Controller 方向的日常查阅速查手册 + 核心考点手册。
> **数据口径**：以 JEDEC 标准原文核对为准 —— JESD238（HBM3）、JESD270-4（HBM4）、JESD79-5B（DDR5）、JESD209-5B（LPDDR5/5X）、JESD209-6（LPDDR6）；核对日期 2026-09。厂商公开资料单独标注。仍存疑的数字以 ⚠️ 标记（见附录 D）。
> **约定**：每节末尾的【核心速答】为 30 秒口径的高频问题答案；题目编号（A1/B1…）对应原始问题清单，便于回溯。

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

### 1.1 带宽与速率（A1 / A3）

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

### 1.2 容量与扩展路径（A2 / A4）

| 维度 | HBM | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 扩展方向 | 纵向：封装内堆 die（4~16） | 横向：槽数 × DIMM 容量 | 封装贴片：die 数 × 封装数 |
| 确定时机 | SoC 设计期锁死 | 部署期灵活插拔 | 制造期焊死（CAMM2 后可换） |
| 天花板 | 单 stack ≤64GB；受良率/散热/厚度限制 | 模组密度最高 | 单封装 ≤32~64GB |
| 代价 | TSV+键合良率、$/GB 最高 | 走线长、RCD/DB/PMIC 开销 | 不可升级（传统 PoH） |

- **DDR5 子通道与访问粒度（A2）**：每 DIMM 两个独立 32-bit 子通道（ECC 模组 2×40-bit = 32 数据 + 8 side-band ECC）；每子通道 BL16×32-bit = 64B —— 一个 cache line 完整落在单个子通道内。**CL 与子通道没有直接关系**（CL 随频率档标定，跨代绝对时间守恒）；子通道化改变的是最小访问粒度与并发请求数："用位宽换请求数"。
- **LPDDR6 窄通道与容量（A4）**：x24 Normal Mode 与 x12 Dynamic/Static Efficiency Mode（JESD209-6 §2.2.2 / §7.8.29），并支持 **Mixed Package**（x24 die 与 Static Efficiency die 混装）——通道配置与容量配置解耦。⚠️ 原问题清单中"x6"的说法在 JESD209-6 中不存在（x6 / 6-DQ 全文 0 命中），标准口径为 x24/x12。
- **HBM4 的解耦（B2 预告）**：4 die 即满 32 通道，第 5~16 die 只增加容量、SID 与 bank 数（16/32/48/64 banks per channel）——通道数与容量/bank 并行度解耦。

### 1.3 应用定位

- **HBM**：AI 加速器/GPU 的片旁带宽引擎（near-compute），2.5D 中介层互装；持续满带宽型负载。
- **DDR5**：服务器/PC 主存；容量、单位成本与系统 RAS（side-band ECC、刷新管理族、模组生态）优先。
- **LPDDR5/6**：手机/边缘 AI/汽车主存；带宽/功耗比与多频点电源管理优先；LPDDR6 CAMM2 补上可换装性。

【核心速答】三种容量路线本质是 带宽密度 / 容量天花板 / 灵活性 的取舍：HBM 设计期锁死但带宽密度最高；DDR5 灵活且最便宜，但速率与延迟为可插拔买单；LPDDR 焊死容量小，LPDDR6 用 x24/x12 通道配置解耦容量与带宽。

## 2. 架构与通道组织

### 2.1 HBM3/4：stack → channel → pseudo-channel → DWORD（B1 / B2）

**层级结构（JESD238 §3.1 / JESD270-4 §2）**

- **Channel（通道）**：64-bit 数据 I/O；HBM3 16 通道/stack；通道间独立时钟、无需同步。
- **Pseudo-Channel（PC，伪通道）**：每通道 2 个 PC；每 PC **32-bit DQ + 4 DBI + 2 接口 ECC bit + 2 SEV bit**（PC0=DQ[31:0]+DBI[3:0]+ECC[1:0]，PC1=DQ[63:32]+...）；PC 是**刷新/功耗/阵列时序状态的独立管理分区**（HBM4：阵列时序逐 PC 独立计时）。
- **DWORD**：32-bit 数据切片（每 PC 1 个 DWORD）——de-skew/训练/修复的粒度；每 DWORD 一对读写选通（RDQS/WDQS）。
- **命令接口**：行/列**半独立**两条总线 —— 行总线 R[9:0]（10-bit）、列总线 C[7:0]（8-bit），可同时下发行与列命令（详见 3.1）。
- 页大小 1KB/PC（HBM4）；通道密度 3~16Gb；bank 数 16/32/48/64 随密度与 die 数变化。

**HBM4 的关键变化（B2）**

1. 通道 16→32：每 die 8ch×2PC，**4 die 凑满 32 通道**；stack 高度 4/8/12/16-die。
2. **通道数与容量/bank 并行度解耦**：第 5~16 die 只增加容量、SID 与 bank 数（16→64 banks/channel）——同样 32 通道下，16-die stack 的 per-PC bank 数是 4-die 的 4 倍，row miss 率可以靠加 die 压低。
3. 对调度器：64 个 PC 的状态表/队列/训练状态机实例翻倍；channel-first 地址映射把相邻 cache line 打散到 32 通道，防止单通道热点吃掉翻倍的带宽。

【核心速答】HBM 记三层：**通道管命令并发、伪通道管电源/刷新/时序分区、DWORD 管训练修复**。每 PC 数据出 32-bit 时还带 DBI、接口 ECC 和 SEV 严重度位。HBM4 通道翻倍到 32 且通道与容量解耦——调度器横向复制扩状态表，地址映射要防通道热点。

### 2.2 DDR5：DIMM → 子通道 → Bank Group（B3）

- 每 DIMM **2 个完全独立子通道**：各 32-bit（ECC 模组 40-bit = 32 数据 + 8 side-band ECC）；各自 14-bit CA、CS、行列译码器、时序状态机与刷新相位，可同时执行不同命令（一个在 tRFC、另一个满带宽读）。
- BG/bank：bank group 架构，16Gb 档为 8BG×4B=32 banks/子通道 ⚠️（以厂商 datasheet 为准）；BL16。
- 控制器利用：① cache line 级子通道交错，命令级并行 ×2；② **刷新错峰**（两子通道 tRFC 相位错开，避免整条 DIMM 同时不可用）；③ 读写翻转（bus turnaround）按子通道独立优化；④ DFI/训练均为双实例。

### 2.3 LPDDR5/6：BG 架构与 x24/x12 效率模式（B4）

- **LPDDR5**：16 banks / 4BG×4B，BL16；调度上区分跨 BG（短时序）与同 BG（长时序）的列命令间隔，BG-aware 排序（把连续请求按 BG 交织）直接抬高总线利用率；per-byte WCK/RDQS。
- **LPDDR6（JESD209-6 §2.2.2）**：x24 Normal Mode = **2 个 Sub-Channel（SC0/SC1）**，每 SC 含 12DQ+RDQS_t/c + WCK_t/c + 4 CA + CS + CK_t/c；每 SC 4BG×4B = 16 banks；**x12 Dynamic / Static Efficiency Mode**（§7.8.29）重构子通道配置以提升引脚/容量效率，且支持 x24 die 与 SEM die **混装**（Mixed Packages）。
- 突发：BL24/BL48（12n/24n prefetch）；BL24 在 12-DQ SC 上 = 288-bit（256 数据 + 32 非数据），I/O 侧为 12 个 12-bit 半 WCK 周期传输；**BL/n（Effective Burst Length）** 定义不同模式的有效突发，同 BG tCCD 随 BL 取 6/8/12/24nCK。

### 2.4 对比小结：调度粒度与并行度

| 协议 | 独立命令流 | 电源/刷新管理粒度 | 训练/修复粒度 |
|---|---|---|---|
| HBM3/4 | 16/32 通道（行/列双总线） | PC（HBM4 达 64 个） | DWORD（32-bit） |
| DDR5 | 2 子通道/DIMM × 槽数 × rank | 子通道/rank | per-pin/per-DQ（DFE/DCA/Vref） |
| LPDDR5/6 | 4~8×16-bit 通道 / x24=2×SC | 通道 | per-byte |

【核心速答】判别"独立通道"的标准是**有没有独立 CA**：DDR5 子通道有（两个命令流）；HBM PC 没有（共享行列总线，只分电源/刷新/时序状态）；LPDDR6 SC 自带 CS/CA/CK，性质更像 DDR5 子通道。

## 3. 命令与时序

### 3.1 HBM3/4：双命令接口与无 CKE（C1 / C2）

**双命令接口（JESD238 §3.1.3，HBM3/3E/4 通用）**

- 每通道两条半独立总线：**行总线 R[9:0]（10-bit）+ 列总线 C[7:0]（8-bit）**，DDR 传输。
- 编码：**ACT = 1.5 cycle**（R[9:0]，CK 双沿锁存）；其它行命令 half-cycle（PDE/SRE 为 1 cycle）；**列命令 1 cycle**（C[7:0]，bank/PC/SID/列地址同拍携带）。
- 效果：ACT/PRE 可与 RD/WR **同窗口并行下发**——行管理开销被列数据流掩盖，这是 HBM 短突发（BL8）仍能维持满带宽的调度基础。
- 细节：REFRESH 需在列总线上垫 CNOP（除非列命令发给另一 PC）；行/列总线各有重映射表（§6.7.1）。

**无 CKE 的低功耗（HBM3/3E/4 与 LPDDR5/6 同为无 CKE 设计）**

- HBM：低功耗状态经**命令 + 模式寄存器**进入/退出（命令触发 power-down、MR 配置深睡），粒度到 **per-PC**。
- 控制器责任：进低功耗前排空在飞命令、进出时序由内部定时器管理、**唤醒延迟显式建模进 QoS**（突发到达时的唤醒开销 = 延迟毛刺，需预测空闲窗口提前唤醒）。
- 训练影响：CA 无 CKE 门控可用，命令路径训练走独立机制（HBM 经 IEEE 1500/MISR 体系；LPDDR 走 CBT/CA Training）——两个协议殊途同归：**命令路径的可靠性都要专用训练机制**。

【核心速答】HBM3 起每通道行 10-bit/列 8-bit 两条总线，ACT 1.5 拍、列命令 1 拍，行/列同窗口并行——行开销被列流吃掉。CKE 删除后低功耗全靠命令+MR，控制器要自己做排空、定时和唤醒预测。

### 3.2 DDR5：CA 总线与 DFI 命令编排（C3）

- 每子通道 **14-bit CA**。**1T（单周期）**：NOP / PRE / REF(REFab/REFsb) / RFM / MPC 等无地址承载命令；**2T（双周期）**：ACT / RD / WR / MRS 等带地址命令——两拍共 28-bit（第 1 拍 opcode+BG/bank+行地址高位，第 2 拍列地址/行地址余位）。
- 动机：CA 位宽从 DDR4 的 20+ 根压到 14 根（子通道化使引脚预算减半），本质是"引脚换拍数"；列命令第 2 拍带列地址，保持 BL16 粒度。
- DFI 侧：2T 命令**原子不可拆**；相邻命令 CA 编码无位冲突；训练/校准走 **MPC**（Multi-Purpose Command）承载子命令；模式寄存器为 256 个 8-bit（CW 位区分 DRAM 与 RCD 寄存器组）。
- 对照记忆：LPDDR5 是"7-bit CA 但 DDR 传输"，DDR5 是"14-bit CA 但部分命令 2T"——同一命题（引脚预算 vs 命令带宽）的两种解。

【核心速答】DDR5 每子通道 14-bit CA：无地址命令单拍，ACT/RD/WR/MRS 双拍共 28-bit；DFI 里 2T 是原子操作，训练命令走 MPC。

### 3.3 LPDDR5/6：三时钟域与 CKR（C4）

- 时钟域：**CK**（低频命令时钟，CA 7-bit DDR）+ **WCK**（写数据时钟）+ **RDQS**（读选通，per-byte）。数据速率 = 2×WCK 频率。
- **CKR = WCK:CK 分频比**（JESD209-5B）：
  - **CKR=2:1 → 533~3200 Mbps**；
  - **CKR=4:1 → 533~6400 Mbps**（>3200 必选 4:1）；CKR 可经 MRW 动态切换（§7.6.7）。
- 典型值：LPDDR5-6400 → WCK 1600MHz、CK 400MHz（4:1）。
- **WCK2CK Leveling**（§4.2.5，即 LPDDR4 write-leveling 的演化）：WCK 与 CK 异步，需锁定 DRAM/PHY 内同步 FIFO 的写读指针——进训练模式 → 施加已知 pattern → per-byte 扫 WCK 相位 → FIFO 指针锁定；**每次 DFS 后必须重做或从 training set 恢复**。
- 控制器实现：CK/WCK/DFI 三异步域之间放弹性 FIFO；WCK 门控与突发对齐逻辑直接决定读写延迟（LPDDR5 读延迟比 LPDDR4 大且随 CKR 变化，QoS 需按档位建模）。

【核心速答】LPDDR 是三时钟域：命令走低速 CK（CKR 4:1 覆盖 533~6400，2:1 只到 3200），数据走全速 WCK 按 byte 门控。WCK 与 CK 异步，开机靠 WCK2CK Leveling 锁 FIFO 指针，每次变频都要重做——这是 LPDDR 控制器比 DDR 多出来的核心机制。

### 3.4 关键时序参数对比（C5）

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

## 4. 训练与校准（LPDDR5/6 重点）

### 4.1 LPDDR5/6 训练流程（D3）

顺序由自举依赖决定（后一步依赖前一步打通的通路）：

1. **CA 训练（Command Bus Training）**：进入训练模式后经 CA 施加/回传训练 pattern（JESD209-5B Fig25-27，覆盖 WCK 频变与固定 WCK 两种场景）；调 CA delay + VREF(CA)。
2. **WCK2CK Leveling**（§4.2.5）：锁 WCK↔CK 的 FIFO 指针（见 3.3）。
3. **读均衡**：基于 **tWCK2DQ Interval Oscillator**（§7.6.14，业界俗称 DQS 振荡器；标准名为 interval oscillator，含 WCK2DQI 匹配误差与读出时序定义）校准 DQ/RDQS 采样相位。
4. **写均衡**：per-byte 校准 DQ 相对 WCK 的相位。
5. **VREF(DQ) 训练** + LPDDR5X 起的 **per-pin DFE**（§7.7.7）。
6. 频率维度：低频 f0 初始化训练 → DFS 后用 **training set 保存/恢复**（多 frequency setpoint）；DVFSC/DVFSQ 等低功耗模式依赖该机制（见 5.3）。

### 4.2 三协议训练机制一览

| 维度 | HBM3/4 | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 命令/CA 训练 | IEEE 1500 测试口 + AWORD MISR 签名 | MPC 捕获 CA → MR → MRR 回读 | Command Bus Training + CBT |
| 数据训练 | WDQS2CK 对齐 + DWORD 级 MISR/LFSR | MPC 模式读写均衡 + per-pin DFE/DCA/Vref | WCK2CK Leveling + Interval Oscillator 读均衡 + 写均衡 |
| 回读通道 | 独立测试访问口（不依赖功能 DQ） | 数据总线（需先打通 DQ） | CBT/DQ 通道 |
| 频率维度 | 单频点（设计期定） | 单频点 | **多 setpoint training set** |

> 注：按约定本手册不展开 HBM/DDR5 训练细节（JESD238 §6.8、JESD79-5B §4.x 需要时另查），仅列对照。

【核心速答】LPDDR 训练是一条自举链：CA 训练 → WCK2CK 锁 FIFO → 基于 interval oscillator 的读均衡 → 写均衡 → Vref/DFE；每个频点一套 training set，DVFSC/DVFSQ 的地基就是它。三协议训练的根差异在**回读通道**：HBM 走独立测试口、DDR5 走数据总线、LPDDR 走 CBT/DQ。

## 5. 功耗与电压域

### 5.1 供电轨对比（E2）

| 协议 | 供电轨与典型值 | 备注 |
|---|---|---|
| HBM3 | VDDC 1.1V（core）/ VDDQ 1.1V（I/O）/ Tx driver 0.4V / VDDQL / VPP | 上电顺序 VPP → VDDC=VDDQ → VDDQL（JESD238 Power Ramp） |
| HBM4 | **VDDC 1.05V（core）/ Tx 0.4V / I/O 电压厂商自定** | 标准仅约束相对关系：VPP > VDDC+200mV、VDDC > VDDQ+VSP（JESD270-4） |
| DDR5 | VDD=VDDQ=1.1V（PMIC 在模组，平台只供 bulk 5/12V）；VPP ⚠️1.8V | 上电/管理时序依赖模组 PMIC |
| LPDDR5 | VDD1 / VDD2H / VDD2L / VDDQ | 上电顺序 VDD1≥VDD2H≥VDD2L≥VDDQ；VDD2 拆分在 LPDDR5 已是**可选** |
| LPDDR6 | VDD1 / **VDD2C 1.0V** / **VDD2D 0.875V** / VDDQ 0.5V（默认） | 顺序 VDD1≥VDD2C≥VDD2D≥VDDQ；I/O 按 VDDQ=0.5V nominal、Voh=0.5×VDDQ≈250mV 设计；VDD2 拆分为**强制** |

要点：HBM3→HBM4 的电气演进方向是"**把余量下放厂商**"（I/O 电压开放），换取 PHY 工艺自由度（配合逻辑 base die）；LPDDR 的方向相反——**标准把电源轨越拆越细**，换取能效管理精度。

### 5.2 功耗与 pJ/bit（E1）

| 代际 | 单 stack 功耗（满负载量级）⚠️ 建议以项目实测/厂商 datasheet 替换 | pJ/bit 趋势 |
|---|---|---|
| HBM3 | ~5~8 W（8-Hi@6.4G） | 基准 ~5 pJ/bit 量级 |
| HBM3E | ~6~10 W（12-Hi@9.6G） | 每代降 ~20~30% |
| HBM4 | ~10~15 W（16-Hi@12.8G） | 带宽翻倍但 pJ/bit 继续下探（~3~4） |

- 规律：**总功耗随带宽近线性上涨，pJ/bit 随代际下降**。速率路线（3→3E）主要花 IO 功耗买带宽，pJ/bit 改善有限；位宽路线（3E→4）用更低 per-pin 速率跑更宽总线，能效更好——这是 HBM4"降速翻宽"的功耗学解释（呼应 1.1）。
- 控制器视角：HBM 无 DFS，功耗管理收敛为 per-PC 降活 + 热感知节流；与 LPDDR 的精细 DVFS 成两极（见 5.3）。

### 5.3 控制器侧功耗管理机制（E3 / E4）

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

### 6.1 DDR5：片上 ECC vs Side-band ECC（F1）

| 维度 | On-Die ECC（片上，强制） | Side-band ECC（模组级） |
|---|---|---|
| 覆盖范围 | DRAM 阵列内部（cell → 读出口） | 链路 + 阵列全路径 |
| 纠错能力 | **SEC：128 数据 + 8 校验位**（JESD79-5B §4.36） | SECDED（8bit/64B） |
| 引脚占用 | 不占（对系统透明） | 占（40-bit 子通道 = 32+8） |
| 控制器角色 | **无感知**——看不到已纠错误 | 全责：写生成/读校验、scrub/patrol、错误计数与日志 |
| 存在目的 | 支撑更高密度 die（容忍更高原始缺陷率） | 系统级 RAS |

- 关键推论：ODECC 透明纠错造成**可靠性遥测盲区**（已纠错不可见，只能从未纠错错误率间接推断）；系统 RAS 必须依赖 side-band 层做 scrub 与日志。两层是**纵深防御**：ODECC 把原始错误率压低 1~2 个量级，side-band 兜底链路与残余阵列错误。

### 6.2 HBM：On-die ECC + SEV 上报 + DRFM（F2）

- **HBM3（JESD238 §6.9）**：**symbol-based On-die ECC + 读写 meta-data（MD）位 + 错误擦洗（scrubbing）+ 错误透明协议 + 接口传输 parity + 故障隔离限**——片内自治的纵深组合（不是主机 side-band 模式）。
- **错误上报**：每 PC 的 **SEV[1:0] 引脚**随读突发携带严重度编码（JESD270-4 Table 67/68 Severity Encodings）；ECS（自动纠错擦洗）错误日志寄存器（MR81/82；HBM4 支持多 bit 纠正记录，MR9）。
- **HBM4 刷新管理增强（行锤 + RAS 合流）**：**RFMpb / DRFMpb**——ACTIVATE 可携带 DRFM bit 标记风险 bank，其后对该 bank 的 RFMpb 即 **DRFMpb**（定向 per-bank 刷新）；**Bounded Refresh（BRC + tDRFM，Table 41）**——把行锤响应从全局长刷新改为**对目标 bank 的有界定向刷新**，带宽代价最小化。
- 对照 DDR5：ODECC 纠错不可见 vs HBM SEV 随读"带内"上报——HBM 的读侧 RAS 信息控制器可直接消费。

【核心速答】HBM 的 ECC 是片内自治（symbol-based on-die + scrub + 接口 parity），纠错严重度经 SEV 引脚随读数据带内上报、ECS 记日志；HBM4 再加 DRFM/BRC 有界定向刷新。控制器读侧直接收 SEV，不用猜。

### 6.3 刷新粒度：REFpb vs REFsb（F3）

| 维度 | LPDDR5 REFpb | DDR5 REFsb |
|---|---|---|
| 粒度 | **单 bank（或 bank pair）** | **各 BG 中同号 bank 同时刷** |
| 其余 bank | 可继续服务 | 可继续服务 |
| 停摆时间 | tRFCpb（最短；tpbr2act / tpbR2pbR 约束 REFpb 之间与到 ACT 的间隔） | tRFCsb（约为 REFab 的一半量级） |
| 控制器实现 | **bank 级刷新债**：per-bank deadline 跟踪 + 机会式插空 | **子通道错峰**：REFsb 相位错开；REFab 只留深空闲窗口 |

- 共同哲学：把刷新从"周期性全局停机"重构为"**可调度的后台工作**"，由控制器 QoS 决定何时还债；REFab 在两者中都保留（深度空闲/进自刷新前最划算）。
- 粒度差异根源：LPDDR 通道窄、延迟敏感（手机），要单 bank 粒度；DDR5 子通道 bank 多、吞吐敏感，BG 级批量刷新更省命令带宽。LPDDR5 还定义了 Optimized Refresh 组合（示例：8×REFpb 完成一轮 bank 覆盖）。

### 6.4 Row Hammer：RAA/激活计数 + 刷新管理族（F4）

| 协议 | 机制 | 要点 |
|---|---|---|
| HBM3 | **RAA 计数 + ARFM（可选）** | 阈值 RAAIMT/RAAMMT/RAADEC 由厂商设定，经 IEEE 1500 DEVICE_ID WDR 可读；达阈值需刷新管理命令 |
| HBM4 | **RFMpb / DRFMpb + BRC** | ACTIVATE 带 DRFM bit 标记风险 bank → 定向、有界（tDRFM）刷新 |
| DDR5 | **RFM / DRFM / ARFM**（MR59：DRFM/ARFM/RFM RAA Counter） | 信用制：ACT 计数 vs RFM 冲销，MR 可配 |
| LPDDR5/5X | **RFM → ARFM**（§7.7.6，MR 支持位） | ARFM 按激活速率自适应提高/恢复刷新 |
| LPDDR6 | **PRAC + ABO** | PRAC 上报风险 row/BG/BK（MR87-89）；ABO（Alert Back-Off，MR86 MRFMaACT）限定恢复期最小 RFMab 与退避期最小 ACT |

- 共同骨架：**DRAM 报计数、控制器还刷新债**。演进方向：债的粒度越来越细（全局 RFM → per-bank → 定向 bounded），背压方式越来越显式（ARFM 自适应 → PRAC+ABO 显式退避）。
- 控制器实现：per-bank 计数/信用表 + 刷新带宽预算进 QoS 模型；安全场景（汽车）要验证最坏情况下刷新管理开销的上限。

【核心速答】行锤防护已全线"激活感知化"：HBM3 RAA+ARFM、HBM4 DRFM 有界定向刷新、DDR5 RFM 信用制、LPDDR5X ARFM 自适应、LPDDR6 PRAC+ABO 显式背压。控制器都要维护计数和刷新预算——行锤从 DRAM 的事变成了调度器的事。

## 7. Memory Controller 设计差异

### 7.1 调度器架构分叉点（G1）

公共抽象：**bank/PC 状态表 + 时序检查器（timing checker）+ 策略层（QoS/仲裁）**；差异在实例规模与策略维度：

| 维度 | HBM3/4 | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 独立调度对象 | 32ch / 64PC（HBM4） | 2 子通道 × rank × 槽数 | 4~8 通道 / x24=2×SC |
| 命令总线 | 每通道行/列双轨（10/8-bit；1.5/0.5/1 拍） | 每子通道 14-bit CA（1T/2T） | 每通道 7-bit DDR CA |
| 并行度来源 | 通道数 + 行列并行 + PC 独立时序 | rank 并行 + BG 交织 + 双子通道 | 通道数 + BG 交织 |
| 特有维度 | per-PC 功耗/刷新相位错峰 | side-band ECC 读改写、RCD/DB 链路 | REFpb 债、DFS 窗口、RFM/ARFM 配额 |

- HBM 调度器是"**横向复制 + 全局 QoS**"：对象多而轻；DDR5/LPDDR 是"**少数深通道**"：单对象内 rank/BG/刷新/翻转策略复杂。
- 地址映射：HBM 用 channel-first striping（cache line 级打散到 32 通道）；DDR5/LPDDR 在子通道/通道维度的 hash 同样决定热点分布——**映射策略是三协议共享的设计课题，只是维度数不同**。

### 7.2 DFS vs 固定频率（G2）

LPDDR DFS/DVFS 对调度器的额外要求：

1. **多频点 training set** 的存储与恢复（每个 setpoint 一套完整训练值）；
2. **DFI frequency change 手序列** + WCK2CK 重对齐；
3. **多轨电压协同**（LPDDR6 的 DVFSH/L/B/Q 各绑一轨，见 5.3）；
4. 切换窗口内的流量排空与延迟抖动进入 QoS 模型；带宽承诺按频点建模。

DDR5 固定频率：初始化训练一次 + 温漂重校（ZQ/Vref 类），调度简单；代价是能效不可调。HBM 同为固定频率，但对象数最多（见 7.1）。

【核心速答】调度器公共骨架 = 状态表 + 时序检查 + QoS 策略；HBM 横向复制（对象多而轻），DDR5/LPDDR 纵向加深（rank/BG/刷新策略复杂）。LPDDR 独有的一整块是 DFS：训练集、DFI 手序列、多轨电压、抖动建模。

### 7.3 统一控制器前端：复用与分叉边界（G3）

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

### 7.4 高频问题：HBM 带宽这么高，为什么不能替代 DDR5 当主存？（G4）

1. **容量**：HBM 单封装 ≤64GB 且设计期锁死；服务器主存需要 TB 级横向扩展，只有 DIMM 插槽路线能做到。
2. **成本**：TSV + 堆叠键合 + 中介层的良率代价，HBM $/GB 远高于 RDIMM。
3. **延迟与系统复杂度**：HBM 延迟并不占优（RL + 阵列访问与 DDR 同量级），数十通道带来的调度/训练/测试开销大；DDR 生态（RCD/DB/PMIC/RAS/热插拔）成熟度无可替代。
- 正确关系：**HBM 是带宽引擎，DDR5 是容量底座**；层级化组合（HBM 作大容量末级缓存覆盖 DDR5）才是 AI 平台的主流形态。

【核心速答】统一控制器分两层：事务/QoS/基础设施可复用；命令编码、训练、刷新管理、低功耗必须分叉——根因是"命令格式、回读通道、刷新哲学、电源架构"四个正交维度全都不同。HBM 替代不了 DDR5 是容量与成本问题，不是带宽问题。

### 7.5 高频对比题（H1~H4）

**H1："LPDDR5 是 DDR5 的移动精简版"——对吗？**

不完全对。**相同点**：SDRAM 阵列语义同源（bank/BG/BL/刷新的底层时序概念）。**独立演进（不是简化）**：时钟架构（LPDDR5 三时钟域 + CKR vs DDR5 单 CK）；命令编码（7-bit DDR CA vs 14-bit 1T/2T）；电源（VDD2H/L 多轨 + DFS/DVFSQ + 更深低功耗态 vs DDR5 无频率切换）；训练（interval oscillator / WCK2CK vs MPC/MRR）；并行度设计（多窄通道 vs 双子通道）。**各有对方没有的东西**：DDR5 有 ODECC 强制、双子通道、PMIC 模组化；LPDDR5 有 DFS、DPD、更细的低功耗态。

【核心速答】阵列语义同源，接口/命令/电源/训练四层各自演进——两者不存在谁是谁的子集；说"精简版"会漏掉 LPDDR 更复杂的多频点电源管理。

**H2：HBM4 向后兼容 HBM3 控制器——混合部署时控制器要做什么？**

JEDEC 口径：HBM4 向后兼容 HBM3 控制器（同一主机设计可支持两代 stack）。控制器需要：

1. **枚举探测**：读 ID/MR（含 IEEE 1500 WDR 通道）识别代际、die 数（4/8/12/16）、SID、密度；
2. **配置切换**：通道映射（16ch vs 32ch 模式）、bank 数/PC（16~64，随 die 数）、时序档（tRCDRD/tRCDWR 等随速率 bin）；
3. **电气取最低公约数**（HBM4 I/O 电压厂商自定，见 5.1）；
4. **特性位探测**：ECS/DRFM/BRC 等按代际使能。

⚠️ 兼容的引脚级机制细节以 JESD270-4 与厂商应用笔记为准。

【核心速答】兼容的本质是"协议骨架不变、代际参数可枚举"：探测代际 → 重映射通道与 bank → 选时序档 → 按代际使能特性，PHY 电气取两代公约数。

**H3：DDR4→DDR5，控制器最大的架构变化是什么？**

不是速率，是三件结构性的事：

1. **子通道化**：1×64 → 2×32 独立子通道——命令/训练/刷新全双份，DFI 双实例；
2. **ODECC 强制**：RAS 分层重构（片上透明 SEC + side-band 全路径），带来遥测盲区；
3. **PMIC 上移模组**：电源管理重心迁移（上电时序、侧带管理、告警走模组）。

次级变化：1T/2T 命令编码、FGR 刷新、REFsb、RFM/DRFM/ARFM、DFE、32Gb die。

【核心速答】记住"子通道化 + 片上 ECC + PMIC 上移"三件套——都是架构级迁移，速率只是顺带。

**H4：HBM 伪通道和 DDR5 子通道是一回事吗？**

不是。判据是**有没有独立命令通路**：

- DDR5 子通道：有独立 CA/CS，是系统可见的两个独立命令流；
- HBM PC：**共享通道的行列命令总线与 CK**，只是 bank 阵列、刷新、电源、时序状态半独立——是"管理分区"而非"命令分区"；
- LPDDR6 的 Sub-Channel（自带 CS/CA/CK）性质上反而更接近 DDR5 子通道；
- 另注意粒度：DDR5 子通道 32-bit 数据；HBM PC 32-bit 数据，但上面还有一层 64-bit 通道。

【核心速答】子通道 = 独立命令流；伪通道 = 共享命令流的电源/刷新/时序分区。看 CA 归属一眼判别。

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

（另有 `LPDDR6\eetop.cn_DDR_PHY_Interface_Specification_v5_2.pdf`（DFI）等可后续补充展开 I 组问题：DFI 手序列、刷新开销定量、地址映射、QoS 调度、验证视角。）

### D. 数据出处与核实状态

**✅ 已对标准原文核对（2026-09，PDF 关键词提取）**

- HBM3：行/列总线 R[9:0]/C[7:0]、ACT 1.5 拍/行 half-cycle/列 1 拍、无 CKE 引脚、BL8、电压 core 1.1V/I-O 1.1V/Tx 0.4V、供电轨 VDDC/VDDQ/VDDQL/VPP、§3.1.3 双命令接口、§6.9 On-die ECC、SEV 引脚、RAA/ARFM（RAAIMT/RAAMMT/RAADEC）、MISR/IEEE 1500（§6.8）
- HBM4：32ch/64PC（4 die 满配）、bank 16~64/channel、1KB page/PC、BL8、VDDC 1.05V/I-O 厂商自定、tRCDRD/tRCDWR/tRAS/tRP、RFMpb/DRFMpb/BRC/tDRFM、ECS 多 bit、SEV Table 67/68
- DDR5：ODECC 128+8 SEC（§4.36）、REFsb/tRFCsb 语义、FGR/刷新推迟、RFM/DRFM/ARFM（MR59）、DFE/DCA/VrefDQ（§3.5.71+）、MPC（§4.15）、子通道 2×32/40-bit、14-bit CA 1T/2T、VPP 引脚存在
- LPDDR5/5X：VDD1/VDD2H/VDD2L/VDDQ 四轨与上电顺序、REFpb/tRFCpb/tpbr2act/tpbR2pbR、Optimized Refresh、RFM（Table 311-316）/ARFM（§7.7.6）、DFE（§7.7.7）、WCK2CK Leveling（§4.2.5）、Interval Oscillator（§7.6.14）、CA Training（Fig25-27）、CKR 变更（§7.6.7）、DVFSQ/VRCG
- LPDDR6：x24 Normal / x12 Dynamic-Static Efficiency、Mixed Packages、SC 结构（12DQ+RDQS+4CA+CS+CK，4BG×4B）、BL24/BL48 与 288=256+32、BL/n 与同 BG tCCD、四轨电压默认值与容差、DVFS 族（DVFSC/Q/H/L/B）、PRAC/ABO（MR86-89）、Meta 寄存器
- 厂商/公开资料：HBM4 产品速率（三星 3.3TB/s≈12.8G、美光 >11G/>2.8TB/s）、LPDDR5X 8533/9600/10700 档、HBM4 兼容 HBM3 控制器（JEDEC/Tom's Hardware）

**⚠️ 仍待确认（修订时更新本表）**

1. E1 的功耗/pJ/bit 数字——建议用项目实测或厂商 datasheet 替换；
2. DDR5 VPP 数值（暂标 1.8V，以 JESD79-5C 表为准）；
3. DDR5 16Gb 档 bank/BG 数（暂按厂商口径 8BG×4B）；
4. LPDDR5X 各速率档对应的 JESD209-5B/5C 条目编号；
5. HBM4 向后兼容的引脚级机制细节（以 JESD270-4 + 厂商应用笔记为准）。

---

> **维护说明**：本文档由问题清单（A1~H4 + 分批讨论）整理而成；每节末【核心速答】为高频问题 30 秒口径。修订任何数字时，请同步更新附录 D 的核实状态。
















