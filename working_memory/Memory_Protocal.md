# Memory Protocol Evolution
## From Physical Constraint to Controller Architecture

> **定位**：Memory Controller / DRAM Controller / AI Memory System 方向的个人知识库——从 Physical Constraint → Protocol Mechanism → Controller Architecture → Evolution Tradeoff 的知识地图。
> **数据口径**：以 JEDEC 标准原文核对为准——JESD238（HBM3）、JESD270-4（HBM4）、JESD79-5B（DDR5）、JESD209-5B（LPDDR5/5X）、JESD209-6（LPDDR6）；核对日期 2026-09。厂商公开资料单独标注；仍存疑的数字就地以 ⚠️ 标记。
> **覆盖协议**：HBM3/3E/4 · DDR5 · LPDDR5/5X/6。

## 0. How to Use This Document

### 0.1 文档定位

本文回答一个核心问题：

> **一个协议 Feature 是为了修复上一代的什么瓶颈？它把复杂度从哪里转移到了哪里？Controller、PHY、Package 分别付出了什么代价？**

- **横向**：HBM / DDR / LPDDR——面对相同问题时为什么选择不同方案；
- **纵向**：DDR4→DDR5、LPDDR5→LPDDR5X→LPDDR6、HBM3→HBM3E→HBM4——同一种 Memory 为什么出现新的 Channel、Clock、Refresh、RAS、Training、Power Feature。

三个使用场景：

1. **5 分钟快速复习**：只看 §0.5 一页总览 + §8 Generation Evolution + §9 Interview Review；
2. **30~60 分钟系统复习**：按 §1 Physical Foundation → §2 Organization → §3 Interface → §4 Reliability → §5 Power/Operating State → §6 PHY Link Closure → §7 Controller/DFI Contract → §8 Generation Delta 顺序重建完整模型；
3. **面试追问**：从 §9 的问答跳转到对应章节的 Why / Controller Impact / Tradeoff / Evolution。

**§1~§8 是知识输入，§9 Interview Review 是最终验收出口**——所有重要正文主题都应能映射到至少一个 Q&A；答不出对应题目视为该主题未真正建立。

本文**不是**：DRAM analog circuit 教材、SerDes/PHY analog 设计指南、JEDEC Spec 全文摘录、SI/PI 专著、Controller RTL microarchitecture 文档（后者见 `DDR_Controller_Architecture.md`）。

### 0.2 知识组织链（八级）

每个 Feature 都沿这条链组织（章节编号即链的展开顺序）：

```text
Physical Constraint（§1）
        ↓
Protocol Mechanism（§1~§4）
        ↓
System / Interface Organization（§2~§3）
        ↓
PHY Link Closure（§6）
        ↓
Controller Requirement（§7.2）
        ↓
DFI Contract（§7.3~§7.7）
        ↓
Architecture Tradeoff（§5.5/§7.11/§8）
        ↓
Interview Answer（§9）
```

每个重要 section 读完后应能恢复：Problem → Physical Cause → Protocol Mechanism → Controller/PHY Impact → Tradeoff 五层因果链（不机械写五层标题，但链必须可重建）。

### 0.3 Source Discipline

| 标签 | 含义 |
|---|---|
| [JEDEC] | 标准明确规定 |
| [VENDOR] | 厂商 datasheet / whitepaper |
| [DFI] | DFI Specification |
| [PROJECT] | 项目真实实现 |
| [PHYSICAL-EXPLANATION] | 基于电气/阵列原理的解释（不冒充标准结论） |
| [INFERENCE] | 架构推论 |
| [UNKNOWN] | 尚未确认 |

规则：JEDEC 告诉我"必须做什么"，不一定告诉我"物理上为什么"——"为什么"若非标准原文，绝不伪装成 [JEDEC]；不确定的内容保持 [UNKNOWN] ⚠️，禁止补成"听起来合理"的答案。未确认内容就地标注 ⚠️ [UNKNOWN]。

### 0.4 Knowledge Boundary

- **PHY 深度**：不设计 analog PHY，但要打通 `Protocol Feature → Physical Problem → Training / Calibration → DFI Handshake → Controller Responsibility`。PHY 概念统一要求：Concept → 破坏了什么 margin → 需要什么训练/校准 → Controller 是否感知。无法连接回 Protocol / PHY / Controller 三角的纯 SI 理论不属于主文。
- **Controller 深度**：本文只讲"协议给 Controller 提出什么 requirement"（state / checker / sequence / 预算），不讲 CAM / Queue / 仲裁 / FSC 等 RTL microarchitecture（见 `DDR_Controller_Architecture.md`）。
- **DFI 深度**：主文只保留 architecture meaning（ratio/rolling 的架构含义已进 §7.4/§7.5 正文）；波形级时序不在本文范围。

### 0.5 一页总览

| 维度 | HBM3 | HBM3E | HBM4 | DDR5 | LPDDR5/5X | LPDDR6 |
|---|---|---|---|---|---|---|
| JEDEC 标准 | JESD238 (2022.01) | JESD238A | JESD270-4 (2025.04) | JESD79-5 系列 (2020.07 起) | JESD209-5 (2019.02) / -5B | JESD209-6 (2025.07) |
| 接口位宽 | 1024-bit | 1024-bit | 2048-bit | 64-bit/DIMM | 64-bit（多×16-bit 通道） | x24（=2×12-DQ 子通道） |
| 通道组织 | 16ch×64-bit，每 ch 2PC | 同左 | 32ch×64-bit，每 ch 2PC | 2 个独立 32-bit 子通道/DIMM | 4~8×16-bit 通道 | x24 Normal；x12 效率模式 |
| 单 pin 速率 | 6.4 Gbps | 9.6 Gbps | 8G 基线→产品 10/11/12.8G | 4.0~8.8 GT/s | 6.4 / 8.533 / 9.6 / 10.7 Gbps | 10.6~14.4 Gbps |
| 接口带宽（代表性折算口径） | 819 GB/s | 1.23 TB/s | 2.05 TB/s 基线→3.3 TB/s @12.8G | 32~70.4 GB/s | 51~86 GB/s（64-bit 等效） | 85~115 GB/s（64-bit 等效）；~230 为 x128 折算 ⚠️ 非同组织单位 |
| 突发长度 | BL8 | BL8 | BL8 | BL16 | BL16/BL32（MR 选择） | BL24/BL48 |
| 容量 | 16/24 GB | 24/36/48 GB | ≤64 GB（4~16 die） | die 16/24/32Gb | 单封装 16~32 GB+ | 16Gb die 起，CAMM2 |
| 电压 | core 1.1V / I/O 1.1V / Tx 0.4V | 同左 | core 1.05V / I/O 厂商自定 | 1.1V（+VPP） | VDD1/VDD2H/VDD2L/VDDQ | VDD2C 1.0V/VDD2D 0.875V/VDDQ 0.5V |
| CKE | 无（命令式低功耗） | 无 | 无 | 有（CKE_t/CKE_c 差分；CKE LOW 进 PD，tCKE） | 无（CA 命令进低功耗） | 无 |
| 刷新管理 | RAA+ARFM（可选） | 同左 | RFMpb/DRFMpb+BRC | REFab/REFsb + RFM/DRFM/ARFM | REFab/REFpb + RFM→ARFM | REFpb + PRAC + ABO |
| ECC | On-die ECC + 接口 ECC + SEV 上报 | 同左增强 | 同左 + ECS 多 bit | ODECC 强制（128+8 SEC） | Link ECC（可选） | 突发内嵌 tag/ECC（288=256+32） |

**一句话定位**：

- **HBM**：带宽引擎——堆叠近存、超高带宽密度、容量天花板低；AI/HPC 专属。
- **DDR5**：容量底座——插槽横向扩展、单位容量成本最低；服务器主存。
- **LPDDR5/6**：能效引擎——低功耗近端内存、多频点 DVFS、细粒度电源管理，以更复杂的训练/切频换取移动与边缘场景的能效。

## 1. DRAM Common Foundation

HBM / DDR / LPDDR 共同继承的 DRAM 物理底座。本章不谈电路设计，只为后面每个协议 Feature 建立共同的因果基础。

### 1.1 DRAM Array Mental Model

- **Cell（1T1C）**：一个访问晶体管 + 一个 fF 级电容。端子关系：**WL=栅极、BL=漏极、Cs=源极** [PHYSICAL-EXPLANATION]；存"1"=Cs 充至 VDD、存"0"=放至 0。电容会漏电（§4.1），读出是破坏性的（§1.3）。
- **Row / Wordline**：一行单元共享一根字线；同一 bank 的字线同一时刻只能驱动一行——**row 是独占资源**（tRC 的根源，§1.2）。
- **Bitline**：每根位线挂一列单元，配对一根参考位线 /BL，两者平时均衡在 VDD/2。
- **Sense Amplifier（SA）**：交叉耦合反相器正反馈，把位线上的微小差分拉到轨到轨；SA 占阵列核心面积的大头（§2.3 加 bank 的面积墙）。
- **Row Buffer**：SA 阵列即行缓冲——一行被激活后整行数据停留在 SA 中，后续列命中（row hit）只做列选通。
- **Bank**：独立的一套 WL/BL/SA 阵列 + 行/列译码，是最小的并发粒度（§2.3）。

**读出全过程（五步链）** [PHYSICAL-EXPLANATION]：① 位线预均衡到 VDD/2（均衡是电荷共享可检测的前提，残余差分会污染判决）；② 行译码选中字线；③ 字线升压到 VPP（DDR5 有独立 VPP 轨 / 片内 charge pump）——VPP > VDD+Vth 保证无论存 0 还是 VDD，pass 管都**完全导通**（半开会削掉电荷共享幅度）；④ **电荷共享**：单元电容 ~10-20fF vs 位线寄生 ~100-250fF（共享比 1:10~20）→ 位线只摆动 **~100mV 量级**——这就是必须有 SA 的原因；⑤ SA 正反馈把 ~100mV 放大到轨到轨。

### 1.2 ACT → RD/WR → PRE 生命周期

同一 bank 的 row 是**独占资源**：字线同一时刻只能驱动一行，位线同一时刻只能处于激活或预充电状态（互斥）[PHYSICAL-EXPLANATION]：

```text
ACT ──tRCD──> RD/WR ……突发…… ──PRE──> idle ──tRP──> 可再次 ACT
    |<------------- tRAS ------------>|
    |<---------------------- tRC -------------------->|
```

- 读：电荷共享**破坏**单元原值，SA 放大后的值必须在 tRAS 驻留期内回写 Cs（否则数据真丢）；
- 写：写驱动器**覆盖** SA 与 Cs（§1.4 tWR）；
- PRE：把位线与 SA 恢复到可再次激活的状态（§1.3 tRP 三件事）。

三段不可压缩：tRAS 不足 → 回写不完整；tRP 不足 → 均衡不到位（基准污染）；SA 未复位 → 残余电荷干扰下一轮判决。**逃避手段只有多 bank 交织隐藏 tRC，不能缩短它**（§1.7 / §2.3）。

### 1.3 Row Timing

每个 timing 按"限制什么资源 / 提前发会怎样 / 能否优化 / 能否隐藏"四问解释：

**tRCD（ACT → 列命令）**：限制"SA 差分建立到可安全列选通"。读侧：列选通把选通管电容挂到 SA 节点，放大未完成时挂载会拖慢/破坏放大，读到亚稳态；写侧：写驱动（强驱动电路）达到"可覆盖电平"即可强制翻转 SA，无需等放大到轨。→ **读的本质是感知、写的本质是覆盖，因此 tRCDWR < tRCDRD**（HBM3/4：tRCDWR 43CK vs tRCDRD 57CK @ 12G 档 ≈ 14.3ns vs 19.0ns [JEDEC]）。提前发 RD → 亚稳态读出；提前发 WR 伤害较小但仍受限。Controller 不能缩短，只能靠多 bank 并发隐藏。

**tRASmin（ACT → PRE 最小驻留）**：限制"修复驻留"——SA 放大后的值必须回写 Cs；tRASmin ≥ tRCD + 突发 + 回写余量，同时也是激活电流占空约束之一（§2.3 墙 1）。提前 PRE → 修复中断、数据丢失。不可优化、可被调度隐藏（让该 bank 的等待与其他 bank 的服务重叠）。

**tRASmax——现代标准不再定义独立符号，但行开放时长约束并未消失**：'tRASmax' 符号在五标准（DDR5/LPDDR5/LPDDR6/HBM3/HBM4）中均未出现 [JEDEC]；但 HBM3/4 的 AC 表在 tRAS 行 **MAX 列给出 9×tREFI**（AP 命令内部 precharge hold-off 的时钟数经 MR4 'RAS' 字段编程），tPD 行同样有 MAX=9×tREFI——"最长行开放/低功耗驻留"约束以 MAX 列 + 可编程字段的形式保留（对非 AP 流量是否强约束 ⚠️ [UNKNOWN]）。历史规范（LPDDR2/3 时代）定义 ≈9×tREFI，动机是防 open row 长期不关导致 REF 发不出去（REF 需要 bank precharged）。现代协议删除独立符号的原因：**控制器自管 REF 发送**（postpone / pull-in / per-bank 预算，§4.3），标准无需再约束行开放时长——复杂度转移到控制器。架构意义在 **refresh 与 open-row 的关系**：历史 tRASmax ≈9×tREFI 与现代 postpone 预算 9×tREFIe（§4.4）数字同源——都是"刷新调度灵活度的外边界" [INFERENCE]。

**tRP（PRE → 下一次 ACT）**：DRAM 内部完成三件事（顺序关键）[PHYSICAL-EXPLANATION]：① **关闭字线**——WL 从 VPP 放到 0；修复值在 SA 保持期间已写回 Cs，关 WL 就是"落袋"动作本身，此后电荷重新封存；② **复位 SA**——撤除使能、节点回到高阻预充态；③ **位线均衡**——EQ 把 BL 与 /BL 短接均衡到 VDD/2，为下次电荷共享准备零基准（不均衡则残余差分污染下次判决）。PRE 命令本身只有半拍/1 拍——**等的是内部过程**。提前 ACT → 基准污染、判决出错。

**tRC（ACT→ACT）与 tRAS/tRP 的关系**：tRC = 同一 bank 两次 ACT 的最小间隔；tRAS = ACT→PRE minimum；tRP = PRE→ACT minimum——物理上覆盖 active + precharge 的完整 row lifecycle，因此 **tRCmin ≥ tRASmin + tRPmin**（很多 speed bin 的表列值恰好取等号——数值巧合，不是协议代数恒等式）。**Controller 仍需独立检查 tRP、不能只查 tRC**：PRE 可能晚于 tRASmin 发出（等 tRTP/调度），若下一次 ACT 紧贴 tRC 边界，此时 ACT→ACT 的 tRC 已满足，但 PRE→ACT 的恢复过程（关字线/复位 SA/均衡，见上 tRP 三件事）尚未完成——tRC 只约束两个 ACT，不感知 PRE 的实际时刻。tRC 也是单 bank 吞吐的硬上限（row miss 密集时每次访问 ≈ tRC，§1.6 行开销算术）。
*Interview anchor: §9.1 Q2/Q4、§9.2 W25*

### 1.4 Read / Write Specific Timing

**tWR（写特有）**：读的回写由 tRAS 驻留内建覆盖；写的覆盖是**额外动作**——写驱动器在列选通后强制覆盖 SA 和 Cs，必须持续传播到 Cs。tWR 从最后一个写数据到 PRE 起算：提前 PRE → 写数据未传播到 Cs、丢失。tWR 链进 tRP（WR → PRE → ACT）。

**tRTP（读特有）**：READ 到 PRE 的最小间隔——PRE 会截断读出与回写流程。tWR > tRTP 的根源：写是对阵列状态的**对抗重建**（覆盖传播到 fF 级电容），读只是撤除放大器占用、回写已由驻留覆盖 [PHYSICAL-EXPLANATION]。

### 1.5 Shared-resource Timing

这类时序限制的不是单个 bank，而是**跨 bank 共享的资源**——所以它们决定系统吞吐而非单次访问延迟：

**tCCD（列到列间隔）**：限制共享 DQ 总线的占用。跨 bank group 背靠背 = 突发占用本身（tCCD_S）；同 bank group 必须等内部阵列列周期（tCCD_L）——完整物理图像与三家对照见 §2.4。

**tRRD（ACT 到 ACT）**：限制**激活电流的速率**。激活是全阵列最高电流操作（字线升压 / 电荷共享 / SA 级联放大恢复写回），并发激活叠加 di/dt 与 IR drop；tRRD 让 bank 间激活错峰。S/L 之分（同 BG 长、跨 BG 短）的解释见 §2.3 / §2.4。

**tFAW（Four Activate Window）**：限制**滚动窗口内的激活配额**（最多 4 次）——是"限额"而非"限速"：tFAW ≈ 4×tRRD 再加 ns 级余量。REFpb 也计入窗口（LPDDR5 滚动窗口原文把 refreshed bank 计入 [JEDEC]）。数值锚点 [JEDEC]：DDR5 tRRD_S=8nCK、tRRD_L=Max(8nCK,5ns)、tFAW(1K)=Max(32nCK,20~16ns)、tFAW(2K)=Max(40nCK,25~20ns)（**页大小进入激活预算**）；LPDDR5 8B 模式 tRRD=Max(10ns,2nCK)、tFAW=40ns。

**tWTR（写 → 读）**：写完成后到读命令的间隔——方向切换 + 写覆盖传播 / SA 稳定的叠加；BG 归属定长短（DDR5：同 BG tWTR_L=Max(16nCK,10ns) vs 跨 BG tWTR_S=Max(4nCK,2~2.5ns)，3 倍以上差距）。

**tRTW（读 → 写）**：只需方向翻转，且写命令可提前发——写数据滞后是可利用余量：不冲突条件 **tRTW ≥ CL − CWL + BL/2**（DDR5 Table 43 公式核心项，其余为 DQS 对齐 / 读写沿的电气细节 [JEDEC]）。

**W→R 比 R→W 贵的三面** [PHYSICAL-EXPLANATION]：① 电气——R→W 仅方向翻转（SA 正常），W→R = 方向翻转 + 覆盖传播 / SA 稳定；② 数值——tWTR_L(10ns) > tRTW(公式项) > tWTR_S(2ns)；③ 系统——写可缓冲解耦、读有 QoS 约束 → 调度器攒写、分组翻转，不对称被策略进一步放大（§7.2）。

### 1.6 Array-limited vs Interface-limited Timing

**判据** [PROJECT 框架]：timing 由谁决定？

- **阵列受限**：决定因素 = 工艺 / 电压 / 温度 / 模拟电路 → **绝对时间 ns 守恒**（tRCD / tRAS / tRP / tRC / tRFC / tWR / tRTP…）；频率提高后不同比下降，速率越高越逼近物理极限（高速档良率敏感点）。
- **接口受限**：决定因素 = 频率 / PCB / IO 设计 / SI → **按 nCK 缩放**（tCCD / BL 占用 / CK 域参数…）。

推论：DRAM 核心频率十年平坦、接口频率逐代翻倍 → **剪刀差逐代拉大**（Bank Group 的诞生根源，§2.4）。

**三家行时序绝对值同一量级**（阵列物理决定）[JEDEC]：

| 参数 | LPDDR5 | DDR5-8400 | HBM4-12000（CK=3GHz） |
|---|---|---|---|
| tRCD | Max(18ns, 2nCK) | 17.5ns | tRCDRD 57CK=19.0ns / tRCDWR 43CK=14.3ns |
| tRP | tRPpb Max(18ns, 2nCK) | 17.5ns | 45CK=15.0ns |
| tRAS | Max(42ns, 3nCK) | 32ns | 90CK=30ns |
| BL | 16 | 16 | 8 |

- **相对值差异巨大**——行开销 ≈ 多少个 burst：HBM4 ≈ **28.6 个 BL8**、DDR5-8400 ≈ 9.2 个 BL16、LPDDR5-6400 ≈ 7.2 个 BL16。接口越快、行开销相对越重 → HBM 最依赖 bank 并行 + 行/列并行命令接口摊薄（§3.1）；**row locality 越高，ACT/PRE 越能被多个 column access 摊薄、command amplification 趋近 1**（二者相关，但无简单倒数关系，§3.4）。
- **行开销与 bank 并行度同向排序** [JEDEC HBM3/HBM4 Table 4/5 + INFERENCE]：行开销最大的 HBM 恰好也是 bank 最多的一类——HBM3 每 PC 至多 **64 banks**（4 SID × 4 BG/SID × 4 bank/BG；Table 5 每 4 bank 一个 BG，64B 档共 16 个 BG）；HBM4 同为每 PC 至多 **64 banks 但 BG 减半**（每 SID 4→2 BG、单 BG 4→8 bank；§3.2.1 表列 2/4/6/8 BG 随 die 数 4/8/12/16）；DDR5 每子通道 **8 BG × 4 = 32 banks**；LPDDR5 每通道 **4 BG × 4 = 16 banks 起**（16B 模式无 BG 划分；bank 数随密度档 ⚠️ 以 JESD209-5B 为准）。**64 ≫ 32 > 16 的 bank 并行度与 28.6 > 9.2 > 7.2 的行开销排序一致——行开销越大，需要的并行 bank 越多来摊薄**（§1.7/§2.3 的量化印证）。
- **约束形式差异**：LPDDR5 用 Max(ns, nCK) 双约束；HBM 用纯 CK 约束——速率上升时 ns 自动收缩、逼近阵列物理极限；温度升高让 ns 侧进一步恶化（§4.5）。

### 1.7 Bank Parallelism 的第一性来源

- 单 bank 的 tRC 不可缩短（§1.2）→ **唯一出路是把时间线在多个 bank 之间交织**——用一个 bank 的服务时间隐藏另一个 bank 的行开销。
- bank 是最小并发粒度：每 bank 同时只能 open 一个 row；可同时 open 的 row 池 = bank 数 → row miss 率随 bank 数下降（收益侧）。
- 但 bank 数不能无限加：**供电（tRRD/tFAW）、面积布线、刷新窗口竞争、IO 复用封顶**四堵墙——完整分析见 §2.3。

## 2. Organization Evolution

本章回答：Memory system 为什么不断增加 Channel / Rank / Bank / BG / Sub-channel / PC / SID？三层扩展问题的分工 [INFERENCE]：

> **CS / 分时复用 → rank（容量）；并入地址高位 → bank 扩展（并行度）；独立 CA → channel（带宽）**

### 2.1 Channel：Bandwidth Expansion

【核心结论】各层扩展中**只有 Channel 层真正扩带宽**——因为它同时增加 CA 命令域与 DQ 数据引脚；rank / bank / die 只在既有接口后面堆资源。

- 加带宽的路线只有加接口：DDR5 多 DIMM / 多通道横插、HBM 多 stack、LPDDR 多通道。
- HBM 是 channel 路线的极致：HBM3 = 16ch×64-bit；HBM4 = 32ch×64-bit（2048-bit 总宽）——翻位宽而非提速率的功耗学依据见 §3.10 / §8.3。
- Channel 的定义性特征：独立 CA、独立 CK（可不同步）、独立刷新 / 时序状态。HBM 原文："each channel is independent…not necessarily synchronous" [JEDEC]。
- Controller 代价：每个 channel 一套命令译码 / 状态机 / 训练实例；channel 数 × 请求路由压力（NoC / 地址映射，§7.2）。

### 2.2 Rank / SID：Capacity Expansion

【核心结论】Rank 与 SID 都是"在同一条通道接口后面堆容量、不动带宽"——rank 用 CS 分时选择，SID 并入 bank 地址高位；代价分别是 R2R 翻转 / 错峰刷新与 bank 地址位增长。

**Rank 的定义与语义**

- 定义：同一 CS 选通、同时响应命令的一组颗粒 = 一个 rank [JEDEC]（DDR5 命令真值表 Note 8：CS_n 第二拍电平控制 non-target ranks 的 ODT——rank 即 CS 选通的目标组）。
- rank 间**共享同一组 CA 与 DQ**（引脚不随 rank 增加）[JEDEC]：DDR5 的 MRW "broadcast across all logical ranks"（命令总线共享）；LPDDR5 §7.2.1.6 "Rank to rank WCK2CK Sync"——两 rank 分时使用同一 WCK/DQ，切换需排序（tWCKPST/tWCKPRE 交接）。
- **代价 = R2R 时序约束的来源**：共享总线上的 ODT 切换、读写翻转、WCK 重同步；3DS 多 logical rank 还须**错峰刷新**限制峰值刷新电流——"tRFC_dlr / tRFC_dpr ≈ tRFC_slr/3"（JESD79-5B §4.13.5，"to limit the maximum refresh current (IDD5B1)"）[JEDEC]。
- 各家形态：DDR5 1R/2R（DIMM 承载 CS 分配与驱动，2R 的时钟/CA 负载由 RCD 缓冲 [VENDOR/INFERENCE]）；LPDDR5/6 至多 2 rank（封装内 die-stack，无 DIMM 位置 [INFERENCE]）；**HBM 无 rank**（JESD238 全文无 "Rank"）——多 stack 共享通道总线时以 SID 选择，且 HBM4 的 SID 已并入 bank 地址（§2.8），与 rank 的 CS 分时语义不同。

**为什么 rank 与 HBM4 加 die 是同一件事** [INFERENCE]：都是"同一通道接口后面堆容量、峰值带宽不变"：DDR5 1R→2R 容量翻倍（代价 R2R 翻转与错峰刷新）；HBM4 4→16 die 容量 ×4（收益 bank 数 16→64 → row hit 率提升，§2.8）。

### 2.3 Bank：Bank-Level Parallelism

【核心结论】bank 换的是可同时 open 的 row 池（row miss 率下降）；但收益有四堵墙——供电、面积布线、刷新窗口竞争、IO 复用。

**一项收益**：bank 是最小并发粒度 → bank 越多可同时 open 的 row 越多 → row miss 率下降。HBM4 加 die 把每通道 bank 从 16 拉到 64，买的正是这个（§2.8）。

**墙 1：供电——限速（tRRD）+ 限额（tFAW）**（时序语义见 §1.5）：激活是全阵列最高电流操作（字线升压 / 电荷共享 / SA 级联放大恢复写回），并发激活叠加 di/dt 与 IR drop。协议用 tRRD 限制激活速率、tFAW 限制滚动窗口配额（≈4×tRRD + ns 余量）。JEDEC 自己的 IDD 测量模式（如 DDR5 Table 311 IDD7）就按 tRRD_S/tFAW/tRCD 排 ACT——被限的正是激活电流 [JEDEC 排布 + PHYSICAL-EXPLANATION 因果]。注意职责分层：单 bank 内激活流程时长由 tRCD/tRAS/tRP 描述，tRRD 只管 bank 间错峰；而 tRRD_L > tRRD_S 的 S/L 之分，除电流外还要"同 BG 内 bank 共享阵列外设 / 局部供电子网、跨 BG 资源独立"来解释——与 §2.4 列域同 BG 惩罚同根源。HBM3/4 的 AC 表把 tRRD/tFAW 与 **RAA（激活计数）**定义在同一张表里——两者共享 ACTIVATE 触发事件、Controller 都对 activation rate 记账，但 failure mechanism 不同：tRRD/tFAW 约束供电/电流密度，RAA/RFM 约束邻行 disturb（§4.6）[JEDEC 表结构 + INFERENCE]。

**供电因果链完整版**：

- **为什么是尖峰**：ACT 在短时间内大规模改变阵列状态——WL 升压充电 + SA 级联放大 + 回写集中在 ~tRCD 窗口内完成，之后电流显著回落 [PHYSICAL-EXPLANATION]。
- **压降伤害什么**：spec 的 ns 时序（tRCD/tRAS）是在**标称供电下保证的**——droop 不是"吃掉预算"，是**作废保证的前提**；失败模式是**静默的模拟退化**（marginal sensing / 读出错误），不是可检测的协议违约。
- **两参数 = 两个物理量、两个时间尺度**：tRRD ↔ 瞬时/di/dt 限制（单尖峰斜率与高度——本地 decap 与回路电感的短时尺度响应）；tFAW ↔ **短窗口聚合激活电流密度限制**（本地 PDN 与 decap 的恢复——几十 ns 尺度；系统级热与 VRM 控制环路的时间常数远长于 tFAW，不构成其直接约束）[PHYSICAL-EXPLANATION]。
- **为什么必须滚动窗口**：分段窗口可被边界套利（4 个 ACT 压窗尾 + 4 个压下一窗头 = 8 个挤在远短于 tFAW 的跨度）；滑动窗口 enforce "任意长度 tFAW 区间内 ≤4 个 ACT"——**无边界漏洞的平均电流约束**。
- **量化锚点**：突发/持续比 = tFAW / (4×tRRD_S)——DDR5-6400：1K 页 = 20ns/(4×2.5ns) = **2.0**、2K 页 = 25ns/(4×2.5ns) = **2.5**：允许短时突发电流达持续限额 2~2.5 倍（差额由 decap 吸收）；**2K 页比值更大 = 每 ACT 电荷更大 → 持续限额相对更紧**——这是"页大小进入激活预算"（§1.5）的物理原因 [INFERENCE]。

**墙 2：面积与布线**：每 bank 一套独立的行译码 / 字线驱动 / SA 阵列（SA 占阵列核心面积大头）；bank 越多，这些电路、金属布线与 RC 延迟线性增长 [PHYSICAL-EXPLANATION]。

**墙 3：刷新与激活抢同一个窗口**：刷新总带宽占用由**容量**决定（每行 8192 次/32ms，tRFC 随密度涨：tRFCab 130ns@2Gb → 380ns@32Gb，LPDDR5 Table 235）；bank 数决定刷新的**粒度与调度形状**——REFpb 命令速率 ∝ bank 数（tREFIpb=488ns，每条只停 1~2 bank，可 postpone/pull-in ±9×tREFIe），但**刷新命令与激活共用 tRRD/tFAW 窗口**：HBM3/4 刷新表 NOTE 1 "tFAW parameter must be observed as well"、REFpb（不同 bank）走 tRRD；LPDDR5 滚动窗口原文把 REFpb 计入 [JEDEC]。bank 无限多 → 刷新与激活在窗口内无限竞争，控制器还要维护 per-bank 刷新债（§4.3）。

**墙 4：IO 复用封顶**：列到 DQ 的数据通路不随 bank 数增长——bank 的收益封顶在 row hit 率，超过后只付面积、布线与调度成本 [PHYSICAL-EXPLANATION]。

### 2.4 Bank Group：Array / IO Pipeline

【核心结论】BG 解决的是"核心频率与接口频率的剪刀差"（§1.6）——组间流水化：跨 BG 列命令背靠背（tCCD_S = 突发占用），同 BG 等阵列列周期（tCCD_L = 阵列列周期）。

**Problem**：阵列时序 ns 守恒、接口时序 nCK 缩放 → 单一数据路径下连续列命令必须等内部阵列列周期，折算成接口拍数随速率逐代增多（DDR5 tCCD_L 由 MR13 按速率档编程 **8→16 nCK**，Table 29 [JEDEC]）→ I/O 总线出现气泡，数据带宽被阵列周期钳制。

**Mechanism**：物理分组 + 每组独立数据路径与 IO 门控 → 跨 BG 列命令背靠背拼接（**tCCD_S = 突发占用，列流 100%**），同 BG 等内部周期（**tCCD_L = 阵列列周期**）——组间流水化。

**统一物理图像** [PHYSICAL-EXPLANATION]：跨 BG 短——各 BG 的阵列侧（sense amp + local I/O gating）独立，突发可背靠背拼满共享 DQ；同 BG 长——上一列操作仍占用同一 BG 的阵列通路，须等阵列列周期（速率越高越长）。**DQ 引脚永远共享，BG 独立的是阵列侧资源。**

**三家 BG 时序对照**（S=Short=跨 BG / L=Long=同 BG；DDR5/HBM4 命名统一，LPDDR5 的 BL/n 语义同方向）[JEDEC]：

| 列域命令间隔 | DDR5（BL16） | HBM4（Table 6/108，JESD270-4A） | LPDDR5（BL16，CKR 4:1，Table 330） |
|---|---|---|---|
| 跨 BG R2R | tCCD_S = 8nCK（=突发占用） | tCCDS = **2nCK**（=BL8 突发占用） | BL/n_min = 2tCK |
| 跨 BG W2W | tCCD_S_WR = 8nCK | tCCDS = 2nCK（无缝读/写同参数，NOTE 16） | — |
| 同 BG R2R | tCCD_L = 8~16nCK（MR13 按速率档编程） | tCCDL = **Max(4nCK, 2.5ns/tCK)**（@8G 档 tCK=0.5ns → 5nCK）；跨 SID 无缝连读改用 tCCDR（厂商自定，tCCDS+1~2nCK，NOTE 17） | BL/n_max = 4tCK |
| 同 BG W2W | Max(32nCK, 20ns) | tCCDL 同参数（NOTE 14：同 BG 无缝 Write/Read 均适用）——对比 DDR5 的 20ns 写惩罚 | tCCDMW = 4×BL/n |
| W→R | 同 BG Max(16nCK,10ns) / 跨 BG Max(4nCK,2ns) | tWTRS / tWTRL（表列值留白，厂商 datasheet） | — |
| ACT→ACT | tRRD_S / tRRD_L | tRRDS / tRRDL（ns，表列值留白，厂商 datasheet） | 同方向 |

（DDR5 另有 tCCD_M 中间层与 3DS _slr/_dlr 后缀分层 [JEDEC]；LPDDR5 Table 330 NOTE 1 "BL/n is minimum column to column cycle time, tCCD(min)"、NOTE 6/7 同 BG=BL/n_max、跨 BG=BL/n_min；16B Mode（无 BG）BL16 也是 2tCK——跨 BG 交织只是把同 BG 惩罚恢复到总线极限。）

**HBM4 数值口径** [JEDEC JESD270-4A Table 108]：接口侧 CCD 族被标准钉死在总线极限（tCCDS=2nCK、tCCDL=Max(4nCK, 2.5ns/tCK)、tPPD=2nCK），而阵列侧 tRRDS/tRRDL/tFAW/tWTRS/tWTRL 及 tRC/tRAS(min)/tRCDRD/tRCDWR/tRP 在表中**留白、交厂商 datasheet**（tRFCab 等刷新参数则按密度/堆叠档给出）——"**接口参数标准化、阵列参数厂商化**"正是 §1.6 阵列受限 vs 接口受限判据在 AC 表结构上的投影。另注：JESD270-4A 表列速度档为 **4.8~8.0 Gbps/pin 共 9 档**，10~12.8G 属厂商扩展档。

**Controller Impact**：BG-aware 排序（把连续请求按 BG 交织）直接抬高总线利用率；地址映射要 BG 交织防热点；timing checker 增加 S/L 双档参数（§7.2）。

### 2.5 Sub-channel / Pseudo-Channel / LPDDR6 SC

三家在"通道内部再分区"上走了三条不同的路——**不要因为数据位宽一样（都是 32-bit 级）就视为同一概念**，判据见 §2.6。

**DDR5 Sub-channel：位宽换请求数**

完整因果链：DRAM 核心频率十年平坦 → 提速率只能加大预取（DDR4 8n → DDR5 **16n**，JESD79-5B："uses a 16n prefetch architecture **to achieve high-speed operation**…a single 16n-bit wide, eight clock data transfer at the internal DRAM core"）→ 预取决定最短突发（BL16）→ 若保持 64-bit 通道，一命令 = 64bit×16 = **128B = 2 条 cache line，过取一倍** → 拆成 2×32-bit 子通道 → **32bit×BL16 = 64B 正对齐一条 cache line**，同时命令并发 ×2。[JEDEC 预取原文 + PHYSICAL-EXPLANATION 算术]

- 每 DIMM 2 个完全独立子通道：各 32-bit（ECC 模组 40-bit = 32 数据 + 8 side-band ECC）；各自 14-bit CA、CS、行列译码、时序状态机与刷新相位，可同时执行不同命令（一个在 tRFC、另一个满带宽读）。
- **术语口径**：**Sub-channel 是 DDR5 DIMM / system organization 的常用术语，而非 JESD79-5B 对单颗 DRAM device 的核心组织术语**——标准只定义单通道颗粒（x4/x8/x16，各自 CA[13:0]/CS_n）；双子通道是 **DIMM 级组织**（4 颗 x8 或 8 颗 x4 归一组、共享子通道 CA 布线，RDIMM 由 RCD 分组驱动）[JEDEC]。
- DDR5 并未完全砍掉 chop："a burst length of sixteen **or a 'chopped' burst of eight**"（BC8 OTF 保留，主粒度仍是 BL16）。
- CL 与子通道没有直接关系（CL 随频率档标定，跨代绝对时间守恒）——子通道化改变的是**最小访问粒度与并发请求数**："用位宽换请求数"。
- BG/bank：bank group 架构，16Gb 档为 8BG×4B=32 banks/子通道 ⚠️（以厂商 datasheet 为准）；BL16。

**HBM Channel + PC：两级结构**

- 层级：stack → **Channel**（64-bit 数据 I/O；HBM3 16ch / HBM4 32ch；通道间独立时钟、无需同步）→ **Pseudo-Channel**（每通道 2 个；每 PC **32-bit DQ + 4 DBI + 2 接口 ECC bit + 2 SEV bit**）→ **DWORD**（32-bit 数据切片，每 PC 1 个——de-skew / 训练 / 修复的粒度；每 DWORD 一对读写选通 RDQS/WDQS）。
- Channel 级动机：1024-bit 接口若做单通道，命令译码扇出、布线 / 凸点与调度耦合都不可行；拆成独立通道后每通道有独立 CA/CK/复位与自己的刷新状态，请求间零时序耦合、调度自由度最大 [JEDEC]。
- **PC 级动机（"pseudo" 的含义）**：通道内阵列再对半分（2×32-bit DQ），两 PC **共享通道的 CK 与行 / 列命令总线**（省掉第二套命令接口与引脚），但各有独立 bank 阵列 / 译码 / 时序状态；**刷新以 PC 为单位**——真值表中 REFab/RFMpb/RFMab 编码携带 PC 位（REFab = 刷"该 PC 的全部 bank"）[JEDEC p49 Table 30]；HBM4 阵列时序逐 PC 独立计时。
- **边界（重要修正）：电源管理是通道级，不区分 PC**——真值表中 **PDE 的 PC 位为定值 H、SRE 为定值 L**、PDX/SRX 为 H（地址位 Don't Care，Table 30 NOTE 4）；SRE 前提原文（§6.3.4.2）："only allowed when all banks in **both** pseudo channels are precharged with tRP satisfied"。架构解释 [INFERENCE]：JEDEC 事实是 refresh/timing 分区做到 PC 级、PD/SR 停在通道级（见本行前半真值表证据）；合理解释——HBM 的 clock/power-gating 基础设施是通道共享资源，把 low-power state 做到通道粒度可减少独立 clock/power state、entry/exit sequencing 与恢复复杂度；PC 的独立性主要服务于阵列时序、刷新与资源分区，而非完整 power-domain independence。
- HBM4 保持 ch-2PC 同构：通道翻倍（16→32）走位宽而非核心提速，控制器对象模型（独立 64-bit 命令域 × 各 2PC）不变 [INFERENCE]——对象模型稳定才能横向复制（§7.2）。
- 页大小 1KB/PC（HBM4）；通道密度 3~16Gb；bank 数 16/32/48/64 随密度与 die 数变化。

**LPDDR6 Sub-Channel：x24 = 2×SC**

- x24 Normal Mode = 2 个 Sub-Channel（SC0/SC1），每 SC 含 12DQ + RDQS_t/c + WCK_t/c + 4 CA + CS + CK_t/c；每 SC 4BG×4B = 16 banks（JESD209-6 §2.2.2）。
- x12 Dynamic / Static Efficiency Mode（JESD209-6 §7.8.29）重构子通道配置以提升引脚 / 容量效率，且支持 x24 die 与 SEM die 混装（Mixed Packages）→ 通道配置与容量配置解耦（§2.8）。
- **SC 自带 CS/CA/CK → §2.6 三条独立判据全过 → 性质上接近 DDR5 子通道、而非 HBM PC**。
- 命令编码代价：每条命令 2 个 CK 周期（CA[3:0] DDR + CS，Table 254 NOTE 1）；ACT/MRW 需两条命令（ACT-1→ACT-2 共 4 周期，夹在 tAAD 窗口内，NOTE 4）——CA 7→4 根的代价是命令带宽减半（§3.2）。

### 2.6 如何判断一个结构是否是真正独立的 Channel

**三判据**（按重要性排序）[INFERENCE，由真值表证据链支撑]：

1. **独立 CA / command domain**（主判据）：命令域独占决定能否有独立命令流；
2. **独立 clock / power domain**：PD/SR 能否独立进入；
3. **command bandwidth 是否共享**：同拍能否各发同类命令。

| 结构 | ①独立 CA | ②独立时钟/电源域 | ③命令带宽 | 结论 |
|---|---|---|---|---|
| DDR5 Sub-channel | ✓（各自 CA[13:0]+CS） | ✓ | ✓ 不共享 | 真通道（DIMM 级组织） |
| LPDDR6 SC | ✓（4CA+CS+CK 自带） | ✓ | ✓ 不共享 | 真通道 |
| HBM PC | ✗（共享 R[9:0]/C[7:0]/CK） | ✗（PD/SR 通道级） | ✗ 共享（列命令编码显式带 PC 位） | **管理分区**，非命令分区 |

**命令吞吐量化对照** [JEDEC Table 31/32 + NOTE 9]：

| | DDR5（2 子通道） | HBM（通道内 2 PC） |
|---|---|---|
| 命令接口 | 2× 完整 CA[13:0]+CS | 1× R[9:0] + 1× C[7:0]，两 PC 竞争 |
| 每拍命令能力 | 每子通道任意命令，互不影响 | 1 行 + 1 列（ACT 1.5 拍期间总线冻结，NOTE 9） |
| 同类命令并发 | 两子通道同拍各发一条 ✓ | 两 PC 同拍只能发一条 ✗（列命令 1 拍编码显式携带 PC+SID+BA，Table 31） |
| 跨类并发 | 天然支持 | 行+列可跨 PC 同窗并行（Table 32 "Different PC, Any Bank" 列） |
| 电源域 | 独立 SR/PD | 通道级同步 |
| 命令引脚成本 | 2×14 = 28 pin | 18 pin 服务 2 PC——"pseudo" 的引脚预算动机 |

Controller 视角：DDR5 两子通道 = 两套独立状态机 / checker 实例；HBM 通道内两 PC = 共享发射端口 + 每 cycle "发给哪个 PC" 的仲裁（§7.2）。

**通道位置三级对照** [INFERENCE]：通道在 **die 外**（DIMM 分组）→ DDR5；通道在 **die 内**（一 die 多通道）→ LPDDR6 SC、HBM4 8ch/die；通道在 **stack 内跨 die 共享总线**（TSV + SID）→ HBM3/4。**独立 CA 在哪一层出现，并发就在哪一层发生。**
*Interview anchor: §9.3 C1*

### 2.7 为什么现代 Memory 越来越 More / Narrower / More Independent

【核心结论】单宽通道三病 + 速率边际成本上升 → 拆成更多、更窄、更独立的实例——本质是"**位宽换请求数**"；主要买的是有效利用率，peak 的提升只来自"更多"且需要引脚同步增加。

**Problem（单宽通道三病）**：① 命令吞吐瓶颈——一通道一拍只能下发一条命令，多主设备的小请求全部排队；② 突发粒度与 cache line 失配——预取增大（8n→16n→24n）后，宽通道一命令过取多行；③ 单通道并发被供电限额封顶（tRRD/tFAW，§2.3 墙 1），加 bank 也救不了命令带宽。

**Physical cause**：中距离互连持续提速率的边际成本（均衡、训练时间、pJ/bit、良率）急剧上升（§3.10）；宽总线的同时翻转线数（SSO/di/dt）与 skew 匹配组随位宽增长，SI 工程难度超线性 [PHYSICAL-EXPLANATION]。

**Mechanism（三家的"拆"）**：DDR5 1×64 → 2×32（64B 对齐）；LPDDR5 单通道 16-bit → LPDDR6 2×SC×12-bit；HBM3 16ch → HBM4 32ch（通道宽 64-bit 不变、ch-2PC 同构）。共性：每实例更窄、实例更多、命令域更独立。

**Peak 还是有效利用率？三个维度分开回答** [INFERENCE]：

- **更多**：peak 与效率同时受影响，取决于**总引脚是否增加**——HBM4 16→32ch（1024→2048 pin）→ peak ×2（vs 3E 为 ×1.67，基线速率还回落 9.6→8G）；DDR5 1×64→2×32（引脚不变）→ peak 不变；LPDDR6 die 内 1×16→2×12 + 速率↑ → peak ×1.5。效率侧：命令域越多，随机负载排队越短，delivered/peak 越接近 1。
- **更窄**：不直接动 peak（总量决定），但它是**高频与细粒度的前提**——宽总线跑不了单 pin 高速率（SI/skew 随位宽恶化）；预取增大后 64B 对齐也只有拆窄才成立。
- **更独立**：纯 efficiency 侧——命令并发、刷新错峰、电源域分离；独立度不全则收益打折（HBM PC，§2.6）。
- **排队视角** [INFERENCE]：1 个命令域 = 单服务台排队（随机负载等待随负载率非线性上升）；N 个独立域 = 负载分流，同 peak 下随机负载的交付带宽与延迟显著改善——**顺序单流几乎无收益**（一条通道足够）。

**三个反向项**（避免一边倒）：① 每通道流量变稀 → open row 局部性摊薄，对 row-buffer 型负载是负项；② 协议开销不降反升——LPDDR6 命令 2 周期 / ACT 4 周期（§3.2）、288-bit 突发仅 89% 有效（§3.5）；③ 刷新与激活的窗口竞争随实例数增长（§4.3）。

**Controller / PHY 代价**：实例数翻倍 → 状态机 / 计时器 / checker / CAM 全线线性增长（§7.2）；调度算法与防热点映射（channel-first）复杂化；NoC 压力前移（§7.2）。PHY 侧：DQ 总引脚由带宽需求决定，省的是 **CA 引脚摊薄**（HBM 18 pin 服务 2 PC、LPDDR6 每 SC 4CA+2CS）与走线组规整（DDR5 RCD 分组、LPDDR PoH 可行）；代价转移到 bump 密度 / 封装布线（HBM4）。

### 2.8 Capacity / Bandwidth / Parallelism 为什么逐渐解耦

【核心结论】带宽需求与容量需求不同步增长 → 协议把三者拆成可独立配置的维度。

- **HBM4（JESD270-4）**："HBM4 requires 4 DRAM dies to support 32 channels. Additional DRAM dies beyond 4 add additional capacity, SIDs and additional banks per pseudo channel"——4 die 即满 32 通道，第 5~16 die 只增加容量、SID 与 bank 数（16/32/48/64 banks per channel）[JEDEC Figure 1]。加 die 的本质是 **bank 维度扩展**：Table 4 的 Bank Address 字段随堆叠高度从 BA[3:0]（16 banks/channel）长出 SID[0]（32）再到 SID[1:0]（48/64；Table 5 中 bank 分 A~H 八个 BG 组，48B 档 SID[1:0]=11 invalid）——**SID 不是 CS 式选择子，而是并入 bank 地址的高位**，RA[13:0]/CA[4:0]/页大小 1KB 全部不动。因此**峰值带宽不变**（32ch×速率由接口决定，4 die 与 16 die 相同），**有效性能可提升**——每通道可开 row 数最高 ×4，row miss 率靠加 die 压低。
- **LPDDR6**：x24 Normal 与 x12 Static Efficiency 混装（Mixed Package）——通道配置（带宽维度）与容量配置解耦 [JEDEC JESD209-6 §2.2.2 / §7.8.29]。
- **DDR5**：DIMM 承载解耦——通道数由平台走线决定，容量由槽数 × DIMM 密度决定（部署期可变）。
- **扩展路径对比**（确定时机）：HBM 设计期锁死（TSV+键合良率、$/GB 最高、受良率/散热/厚度限制）；DDR5 部署期灵活插拔（代价：走线长、RCD/DB/PMIC 开销）；LPDDR 制造期焊死（CAMM2 后可换）。

## 3. Interface Evolution

本章统一讲 Pin / Rate / Command Bandwidth / Burst / Clock Architecture 的 tradeoff。核心问题：**如果我要提高 bandwidth，协议到底把复杂度转移到了哪里？**

### 3.1 Command / Address Interface：三家形态

| | HBM3/4 | DDR5 | LPDDR5 / LPDDR6 |
|---|---|---|---|
| CA 引脚 | 行 R[9:0] + 列 C[7:0] = 18 根/通道 | 14 根/子通道 | LPDDR5 7 根 / LPDDR6 4 根+CS |
| 传输 | DDR | SDR（1T/2T 命令） | DDR（命令 2 CK 周期） |
| 命令拍数 | ACT 1.5 拍 / 行命令 0.5 拍 / 列命令 1 拍 | 无地址命令 1T / 带地址命令 2T（28-bit） | 每条命令 2 周期；ACT-1+ACT-2 共 4 周期 |
| 特色 | 行/列半独立双总线 | 引脚换拍数 | CA 最省、命令带宽减半 |

**HBM 双命令总线（JESD238 §3.1.3）**：行总线专管 ACT/PRE/REF/RFM/PDE，列总线专管 RD/WR/MRS——ACT/PRE 可与 RD/WR **同窗口并行下发**，行管理开销被列数据流掩盖，这是 HBM 短突发（BL8）仍能维持满带宽的调度基础（对冲 §1.6 的 28.6 个 BL8 行开销）。

- 量化论证：**tCCDS = 2 nCK = 4 WCK = BL8 突发占用**（Table 93："RD/WR bank A to RD/WR bank B command delay different bank group → tCCDS = 2"；同 BG tCCDL = Max(4, 2.5ns/tCK)）——列流背靠背正好填满列总线；行命令若共享此总线必偷列拍 [JEDEC]。精确化：分总线消除的是常规行命令（ACT/PRE）的竞争；REFab 是例外（§4.2）。
- 根因（引脚经济学换轨）：3D 堆叠 + TSV 把"增引脚"的边际成本降了一个量级，每通道养得起两条专用总线 [PHYSICAL-EXPLANATION]。

**DDR5：14-bit CA + 1T/2T**：CA 从 DDR4 的 20+ 根压到 14 根（子通道化使引脚预算减半），本质是"引脚换拍数"——无地址命令（NOP/PRE/REF(REFab/REFsb)/RFM/MPC）1T，带地址命令（ACT/RD/WR/MRS）2T 共 28-bit（第 1 拍 opcode+BG/bank+行地址高位，第 2 拍列地址/行地址余位）。

- **命令编码复用的演进终点**：SDRAM~DDR4 保留专用 RAS_n/CAS_n/WE_n（DDR4 约 20+ 根 CA/控制线 ⚠️），**DDR5 彻底删除这些专用命令线**——"CS is part of the command code"（p37）[JEDEC]。
- DFI 侧：2T 命令**原子不可拆**；训练/校准走 **MPC**（Multi-Purpose Command）承载子命令；模式寄存器 256 个 8-bit（CW 位区分 DRAM 与 RCD 寄存器组）。

**LPDDR：7-bit（LPDDR5）/ 4-bit（LPDDR6）DDR CA**："LPDDR6 commands are two clock cycles long and defined by the states of CS at the 1st and 2nd rising edge (R1, R2) of clock and CA[3:0] at the 1st rising edge (R1), the 1st falling edge (F1), the 2nd rising edge (R2) and the 2nd falling edge (F2)…some operations such as ACTIVATE and MODE REGISTER WRITE require two commands"（Table 254 NOTE 1）；ACT-1 后必须跟 ACT-2（tAAD 窗口内仅 CAS/WRITE/READ/异 bank PRE/REF 可插入，NOTE 4）；CA 为 DDR 采样、CS 为 SDR（Table 1）——**CA 7→4 根的代价是命令带宽减半** [JEDEC]。

**地址分时复用（更早的复用层）**：行/列地址分拍送上同一组引脚——自 SDRAM 第一代如此，是 DRAM 引脚经济学的起点：地址引脚数不随"行位宽+列位宽"线性增长。注意复用的两层含义演进时间不同：**地址分时复用**自 SDRAM 起就有；**命令编码复用**（控制线并入 CA）直到 DDR5 才彻底完成 [JEDEC]。

### 3.2 Pin Budget vs Command Cycle

**统一公式** [INFERENCE]：

```text
命令位宽（opcode + 地址 + bank 域）
    ≤  CA 根数 × 沿数 × 拍数
    →  根数不足时用拍数补（DDR5 2T；LPDDR6 2/4 周期）
```

- **CA pin 少的好处** [PHYSICAL-EXPLANATION]：引脚/封装成本、走线组规整、SSO-skew 随位宽超线性——LPDDR 的 PoP/PoH 封装与 DDR5 RCD 分组都依赖窄 CA；HBM 的 CA 摊薄（18 pin 服务 2 PC）同理。
- **代价**：**命令延迟与命令带宽**——同样命令速率下占用更多 CK 周期；ACT 载荷最大（行地址），所以 ACT 最先变多拍（§3.3）。
- 对照记忆：LPDDR5 是"7-bit CA 但 DDR 传输"，DDR5 是"14-bit CA 但部分命令 2T"——同一命题（引脚预算 vs 命令带宽）的两种解；LPDDR6 两头都要省 → 命令 2 周期、ACT 4 周期。
- **为什么 LPDDR 的 CA 敢用 DDR 双沿、DDR5 反而用 SDR** [PHYSICAL-EXPLANATION + INFERENCE]：LPDDR5/6 虽然数据速率不低于 DDR5，但**高速数据走 WCK、命令走低速 CK**（CKR 4:1/8:1，同 6400 下 CA 每 pin 速率约为 DDR5 CA 的 1/2）——CA 的 UI 远宽于数据 UI，有足够 margin 用双沿传 CA，并借此把 CA pin 压到极限（7→4 根）；DDR5 的 CA 则跑在高频 CK 上（每 pin 速率=数据速率一半），且要经过长距离、多负载的 DIMM 通道（fly-by 拓扑、多 rank），为保 SI margin 采用 **SDR 单沿采样**，再用 2T 补足命令/地址 bit budget——**CA 传输方式是"命令/数据时钟是否分离 + 通道长度与负载"的函数，不是协议品味**。
- Controller 代价：编码器区分 1T/2T、2T 原子性、双命令序列（ACT-1/2 + tAAD）状态机（§7.2）。

### 3.3 为什么 ACT Encoding 最复杂

【核心结论】命令编码复杂度 = 载荷宽度的函数——ACT 要装下整条行地址，载荷最大，所以最先变多拍、位预算最紧。

**HBM3 ACT 位预算定量** [JEDEC Table 30，p49]：ACT 在 R[9:0] 上占 1.5 周期（R+F+R 三个沿 × 10 bit = 30 bit 槽位）——R 拍：opcode 前缀(L,H,H) + **PC(1) + SID(2) + BA(4)**；F 拍：标记(H,H) + **RA[14:8]**；R 拍：标记(H,H) + **RA[7:0]** → **ACT 载荷 ≈ 24 bit**（对比 PRE ≈ 7 bit：PC+BA+AB；NOP = 0）。

- **1.5 拍的由来** [PHYSICAL-EXPLANATION]：1 拍（10 bit）/2 拍（20 bit）都装不下 24 bit，3 拍 = 30 bit ✓；HBM 命令以半拍为粒度发射，1.5 拍结束后总线在下一个半拍即可复用（2.0 拍会浪费半拍）——**1.5 = ceil(24/10) × 半拍粒度，无对齐浪费**。
- **三重代价**：① NOTE 9 总线冻结（"another command is not allowed during ACT command"——行/列双总线 1.5 拍内都不可用）；② 三沿锁存对齐（CA 训练须保证跨沿采样对齐）；③ 奇偶校验按 ACT 全 30 bit 计算（MR0 OP6 启用，p53）。

**跨协议对照："行地址最大"是普遍规律** [JEDEC]：DDR5 ACT 同样 2T（载荷含 **RA[17:0] 18-bit 行地址** + BG/Bank + CID，Table 311 位宽直证）；换回统一公式：DDR4 时代 18-bit 行地址走专用 A[17:0] 引脚（1T），DDR5 砍到 14 CA 后只能 2T——**ACT 复杂化是引脚复用的直接后果**；HBM 行/列分总线后列命令 1 拍就够（复杂度集中在行域）。

**演进压力**：HBM3 行地址 8/12/16Gb 用 RA[12:0] → 24/32Gb 用 RA[13:0]（地址表），**HBM4 已预留 RA15**（DEVICE_ID NOTE 2）——行地址持续增长而 CA 根数不涨，ACT 位预算持续吃紧 [JEDEC]。

### 3.4 Command Bandwidth 什么时候成为瓶颈

**总判据**：需求侧命令速率逼近/超过供给侧、且 AC timing 不是主要限制——量化形态：**时序窗口内有 ready 命令但 CA 槽位排满** [INFERENCE]。注意 ACT/PRE 既是命令又是时序负担，row miss 密集时两者同时逼近上限；"纯命令带宽瓶颈"出现在 **hit 率高、粒度小、REF/RFM 占空高**的组合（时序裕量有余而 CA 排满）。

**需求侧四因素**：

1. 访问粒度——64B 粒度下 1 TB/s = 16 G 命令/s（纯列命令基线），粒度越小命令越多；
2. **row miss 放大**——全 miss = ACT+RD/WR+PRE（≈3 条/请求）；open row 内连续 N 次列访问 = ACT + N×RD/WR + PRE，共 N+2 条 → **commands/access = 1 + 2/N**，N↑ 时 ACT/PRE 被摊薄、command amplification → 1（row locality 的命令侧收益；HBM 28.6:1 行开销正靠 locality + 并行摊薄）；
3. REF/RFM 占空——REFpb 命令速率 ∝ bank 数（tREFIpb，§2.3 墙 3）；REFab 期间整通道冻结（§4.2）；
4. ACT 编码膨胀——DDR5 2CK、LPDDR6 ACT-1/2 共 4CK（§3.3），行地址增长直接吃命令带宽。

**供给侧**（统一公式反演）：CA 根数 × 沿数 ÷ 命令位宽——DDR5 单子通道每 2T 拍 1 条（4800 档 ≈1.2 G 命令/s）；HBM3 = R[9:0]+C[7:0] **18 根、每拍 1R+1C 双槽**（列域另受 tCCDS=2CK 限速）；LPDDR6 每 SC 4 CA、命令 2 周期、ACT 4 周期——三者供给相差一个数量级。

**算例** [INFERENCE]：1 TB/s、64B 粒度、全 miss → 3 命令/64B = **48 G 命令/s**；DDR5 单子通道 ×2 子通道 ×N DIMM——需求与供给同数量级掰手腕，这就是子通道化（§2.7）与请求合并成为标配手段的原因。

**缓解手段与权衡**：① 请求合并 / 更大访问粒度（直接降需求）；② 连续 page hit（放大率降到 1+2/N）；③ 子通道独立 CA（增供给，§2.7）；④ **auto-precharge**（RDA/WRA 把 PRE 并进列命令，每次 miss 省 1 条行命令——代价是 bank 随即关闭、牺牲后续 row hit：open-page vs close-page 的策略权衡）。

### 3.5 Prefetch / BL / Access Granularity

- **预取史**：DDR4 8n → DDR5 16n → LPDDR6 24n/48n（BL16/BL24/BL48）。预取是"核心频率平坦下提速率"的唯一接口手段：内部一次读 16n-bit 宽，I/O 分 16 个半拍流出（DDR5 原文："a single 16n-bit wide, eight clock data transfer at the internal DRAM core and sixteen corresponding n-bit wide, one-half clock cycle data transfers at the I/O pins"）[JEDEC]。
- **BL 增大自身的收益**：数据/命令开销比提升（一条列命令搬更多数据）。
- **BL 增大的代价**：访问粒度↑ → cache line 失配 / 过取回归（DDR5 若不拆子通道则 128B=2 line，§2.5）+ 部分写更难（§3.9 掩码机制逐代删减）。
- **LPDDR6 的粒度账**：BL24 在 12-DQ SC 上 = 288-bit，其中仅 256-bit 为用户数据（16-bit tag/ECC 存入阵列 + 16-bit DBI/链路 ECC 不占阵列），**有效 ≈ 名义 × 89%**（JESD209-6 §2.4）[JEDEC]。SoC 侧仍组织为 32/64-bit 等效位宽——通道→地址映射是控制器设计点。BL/n（Effective Burst Length）定义不同模式的有效突发，同 BG tCCD 随 BL 取 6/8/12/24nCK。
- **HBM 反例**：BL8 最短——堆叠带宽靠位宽不靠预取；细粒度 column transaction 契合 GPU/AI sectorized traffic，代价是 ACT/PRE 相对单个 burst 的摊薄更差（§1.6 的 28.6:1）——HBM 靠 channel/bank/PC 并行 + row locality + 行/列双命令总线隐藏这笔 row overhead，而非靠 BL8 降低它。

### 3.6 Clock / Strobe Architecture

**LPDDR 三时钟域**（DDR5 单 CK 域的对照）[JEDEC]：

- **CK**：命令域低速时钟；**WCK**：数据全速时钟，per-byte 门控。**CKR = WCK:CK 频率比**：CKR=2:1 → 533~3200 Mbps；CKR=4:1 → 533~6400 Mbps（>3200 必选 4:1）；典型 LPDDR5-6400 → WCK 3200MHz、CK 800MHz。CKR 可经 MRW 动态切换（§7.6.7）。
- **WCK2CK Leveling**（§4.2.5，即 LPDDR4 write-leveling 的演化）：WCK 与 CK 异步，需锁定 DRAM/PHY 内同步 FIFO 的写读指针——进训练模式 → 施加已知 pattern → per-byte 扫 WCK 相位 → FIFO 指针锁定；**每次 DFS 后必须重做或从 training set 恢复**（§6.6/§6.8）。
- 控制器实现：CK/WCK/DFI 三异步域之间放弹性 FIFO；WCK 门控与突发对齐逻辑直接决定读写延迟（LPDDR5 读延迟比 LPDDR4 大且随 CKR 变化，QoS 需按档位建模）。
- 为什么命令走低速 CK：CA 根数少、DDR 采样，引脚与 SI 压力小（§3.2）；数据走全速 per-byte WCK 与 source-sync（§3.7）。

**家族全景**：CK（命令域定时）/ DQS（DDR 数据选通，双向）/ WCK（LPDDR 数据钟）/ RDQS（HBM 读选通、LPDDR6 SC 自带）——**谁发 data，谁提供 timing reference**：写方向控制器发 strobe、读方向 DRAM 发；CK 只保留命令域定时。

### 3.7 Source-synchronous Interface

【核心结论】高速数据不依赖 CK 采样——CK 与 DQ 路径不同，绝对误差占 UI 比例随速率变大；source-sync 让数据与选通同源、作为一个 timing group 传输，把绝对路径问题变成局部相对 skew 问题 [PHYSICAL-EXPLANATION]。

- DQ 与 DQS 同源产生 → 时序问题缩小到组内相对 timing，training 再把采样点放到眼中心（§6.4）。
- 三协议映射：LPDDR DQS/WCK、HBM WDQS/RDQS（per-byte/per-DWORD）、DDR DQS。
- **Read gate 问题**：RDQS 只在 read burst 附近被 DRAM 驱动，其他时间无效——PHY 需用内部生成的 gate window 只放行有效 RDQS；训练前传播延迟未知：gate 开太早放 preamble/噪声、开太晚丢数据 → read gate training 的目的就是校准这个窗口（§6.7）。
- **DCD（Duty Cycle Distortion）**：占空偏离 50% → DDR 双沿采样两沿间隔不等 → 一沿 setup 变大另一沿变小，窄半边预算砍半——HBM3 有专用 WDQS Duty Cycle Correction 训练流程（Figure 80）[JEDEC]。
- **Per-lane / per-bit delay**：不同 byte lane 物理路径不同 → eye center 各异——global delay 只能整体采样、补不了 lane-to-lane skew → per-lane delay；同一 byte 内还有 per-bit skew → 更高速 PHY 的 per-bit deskew（HBM4 per-pin DFE 同理，§6.3）。

### 3.8 Read / Write Turnaround

时序数值见 §1.5（tWTR/tRTW）；本节讲系统行为与调度含义：

- 根源：DQ 双向——读时 DRAM 驱动、写时控制器驱动，**方向切换必须等上一方向完成**。
- R2W 便宜（方向翻转 + 写数据滞后余量）、W2R 贵（方向翻转 + 覆盖传播/SA 稳定）；ODT 档位切换也进入 turnaround 成本（切换需时间且改变阻抗环境——切换窗口总线不可用 + 瞬态反射）。
- 调度含义：**攒写、分组翻转**——把同方向请求连续化，减少翻转次数并避开 tWTR_L 的同 BG 惩罚（§7.2 自由度 2）。
- 三协议粒度：turnaround 按子通道（DDR5）/ 通道（LPDDR、HBM）/ SID（HBM 多 stack 共享通道总线）独立优化。

### 3.9 ODT / DM / DBI / CAI

**ODT（On-Die Termination）**：端接做进 die 内，吸收入射能量、抑制反射；档位经 MR 编程（DDR5 RTT_NOM/RTT_WR/RTT_PARK；LPDDR CA ODT/DQ ODT/NT-ODT——非目标 rank 端接）。**太弱（高阻）→ 反射残留/ISI；太强（低阻）→ 直流功耗大 + 驱动器负载加重 → 摆幅压缩 + 电源噪声**；最优 ODT = 与通道阻抗环境匹配，由 ZQ 校准与 training 确定（§6.3）[PHYSICAL-EXPLANATION]。

**第一层：先分语义**——两个正交的问题：

- **DM（Data Mask）= memory semantic**：决定哪些 byte 真正写进阵列——协议语义层功能；
- **DBI / CAI = electrical / switching optimization**：决定线上 bit 用哪种编码传输更有利（减少同时翻转、降 SSO/供电扰动）——不改变语义。

**第二层：协议矩阵** [JEDEC]：

| 特性 | DDR4 | DDR5 | LPDDR5 | LPDDR6 | HBM3/4 |
|---|---|---|---|---|---|
| 独立 DM 引脚 | **复用**——DM 与 DBI 共享同一 pin，写路径两者互斥 | ✓ x8/x16（MR5:OP[5] 启用，DM_n LOW=掩码该 byte；x4 不支持） | ✗ | ✗ DMI 删除（Table 1 NOTE 2："There is no DMI in LPDDR6"） | ✗ |
| MASKED WRITE 命令 | ✗（字节掩码全靠 DM pin） | ✗（有 WR_Partial 标志配合 ODECC） | ✓（DRAM 内 RMW，同 BG tCCDMW=4×BL/n） | ✗（Table 254 仅 WR-S/WR-L；'Masked' 只剩 PASR Segment Mask=刷新分段，MR27） | ✗ |
| Write/Read DBI | ✓（与 DM 同 pin 复用，读/写 DBI 分别经 MR 使能） | ✗（DDR5 删除了 DQ-DBI；inversion 转移见下） | ✓（DMI 兼职反转） | ✓（MR3 OP[7:6]；无 DMI 故纯反转、无掩码语义） | ✓（DBI[3:0]/PC，DBI(ac)：charge count ≥4 → Inverted） |
| 字节部分写出路 | DM 掩码（使能写 DBI 后 DM 不可用，退化为整突发写） | DM 掩码 / 控制器 RMW | MASKED WRITE（写吞吐 1/4） | **控制器 RMW**（硬件不再兜底） | 无通用 DM——partial update 由上层合并/RMW |

**第三层：代际演进解释** [JEDEC 事实 / INFERENCE 归因]：速率越高，DRAM 内 RMW 越贵 → **部分写责任逐步上移到控制器**。DDR5（服务器）写以整 line/整 burst 为主、DM 刚需明确——保 DM 删 DQ-DBI，inversion 转移到 CA 侧（CAI）并配合 DFE/DCA/training 强化，构成 SI/power 复杂度的重分配（见下"重分配"段）；ODECC 另有 WR_Partial 优化 ECC 读改写；LPDDR5（移动 SoC）字节粒度更新刚需 → MASKED WRITE 把 RMW 挪进 DRAM 换 SoC 简单（代价写吞吐 1/4）；LPDDR6 速率翻倍后 4× 列周期的 RMW 串行化不可接受 → 连 DMI 与 MASKED WRITE 一起删除；HBM 不提供通用 byte-mask/DM path——目标 GPU/AI workload 中小 store 通常先由 cache / coalescer / store-combine 合并为较完整 sector/burst，残余细粒度更新由 cache/controller RMW 等上层机制处理（原生 DM 的 ROI 较低）；引脚预算全给数据/训练，DBI(ac) 仅作动态反转省电。

**DBI / DM 的取舍判据** [JEDEC/VENDOR facts + INFERENCE]：**DM 是否保留，看是否需要 native partial-write semantic；DBI 是否保留，看是否值得为 DQ encoding 保留 protocol/pin/logic complexity**。CPU/server partial-write 语义可以解释 DDR5 为什么值得保 DM，但不能单独解释 DQ-DBI 为什么删除——后者应结合 DDR5 整体 SI architecture 理解：CAI、DFE、DCA、CA/CS training、CA ODT 等重新分配了 link-closure complexity（见下“重分配”段）。HBM 偏 GPU/AI 全 sector 流式访问且接口极宽（SSO/供电扰动收益大），舍 DM 保 DBI；LPDDR6 继续保留 DBI 做能效优化、把 partial-write 责任上移 Controller——**DDR5 是几类协议中少见的“删除 DQ-DBI 而保留 DM”的设计**。

**DDR4→DDR5：从"DQ DBI"到"强化 DQ training/EQ + CA inversion"的重分配** [JEDEC facts + INFERENCE]：DDR4 的 DM/DBI 复用同一 pin、写路径互斥——**DM 与 DBI 可以同时作为协议 capability 存在**（这是"DM 取代 DBI"单因果解释的反例）。JESD79-5B 最终将该 pin 固定为 DM、删除 DQ-DBI，并把 bus-inversion 机制转移到 CA 侧的 CAI（Command/Address Inversion，JESD79-5B Appendix B ⚠️ CAI 细节待一手资料复核）。与此同时 DDR5 为 DQ 引入 DFE、DQ/DQS DCA 与更完整的 training，而 CA 侧由于 14-bit 高复用、DIMM fly-by/多负载拓扑，新增 CA ODT、CA/CS training 与 CAI。由此可把 DDR4→DDR5 理解为 **SI/power optimization complexity 的重新分配——保留 DM semantic，用 CAI + 更强的 DQ training / DFE / DCA 完成高速 link closure，而非 DBI 单纯失去价值**（委员会动机若无原文则为 [INFERENCE]）。
*Interview anchor: §9.1 Q12、§9.2 W10/W11*

### 3.10 Bandwidth Scaling：路线 × 互连阶梯

提高 bandwidth = 位宽 × 速率；四条路线各把复杂度转移到不同地方 [INFERENCE]：

| 路线 | 例子 | 复杂度转移到哪里 |
|---|---|---|
| ① 加 rate | DDR4→5 3200→8800；LPDDR 6.4→14.4G | PHY/SI margin（UI 收缩，§6.2）、均衡/训练、pJ/bit、良率 |
| ② 加 pin | HBM 1024→2048 | 封装布线/bump 密度、PHY 面积功耗（CA 摊薄的收益） |
| ③ 加 channel | DDR5 双子通道、HBM 16→32ch、LPDDR 多通道 | Controller state/NoC/实例化、地址映射（§2.7/§7.2） |
| ④ 加 burst/reuse | BL16/BL24-48、预取 8n→24n | 访问粒度/过取（§3.5）、部分写更难（§3.9） |

**HBM 的第五条路**：堆叠形态绕开整个预算——数据引脚大爆炸使 CA 占比稀释 + 行/列分总线 + TSV/中介层；CA 带宽问题不是被解决而是被**封装形态买断** [INFERENCE]。

**HBM 实证**（速率阶梯与带宽公式，详见 §8.3）：

| 代际 | 接口位宽 | 通道组织 | 速率（基线→产品） | 单 stack 带宽 | 容量 |
|---|---|---|---|---|---|
| HBM3 | 1024-bit | 16ch×64-bit | 6.4 Gbps | 819.2 GB/s | 16/24 GB（8/12-Hi，16Gb die） |
| HBM3E | 1024-bit | 16ch×64-bit | 9.6 Gbps | 1228.8 GB/s | 24/36/48 GB（10/12/16-Hi，16/24Gb） |
| HBM4 | 2048-bit | 32ch×64-bit | 8G 基线→10/11/12.8G→路线 16G | 2.048 TB/s→2.8/3.3 TB/s | ≤64 GB（4~16 die，24/32Gb） |

- HBM3→3E：**纯速率演进**（6.4→9.6G，同位宽）；3E→4：**架构性翻倍靠位宽**——JEDEC 基线速率 8G 反而低于 3E 的 9.6G，总带宽增长全部来自位宽；产品竞争力由代内速率爬坡决定（三星 HBM4 官方 3,300 GB/s ≈12.8G；美光 >11G/>2.8TB/s [VENDOR]）。
- 为什么翻位宽而不是继续提速率：中距离互连上持续提速率的边际成本（均衡、训练时间、pJ/bit、良率）急剧上升；翻位宽把压力转移到封装布线/bump 密度，换取时序裕量与能效——速率路线花 IO 功耗买带宽、位宽路线能效更好（§3.10）。衍生变化：HBM4 I/O 电压开放厂商自定（§5.1）；host-side PHY 面积/走线压力增大，先进逻辑 base die 为控制/PHY 逻辑下沉提供条件（§8.3 趋势 [INFERENCE]）。

**LPDDR 速率阶梯**：LPDDR5 3200~6400 → 5X 8533/9600(=5T)/10700 → LPDDR6 10.6~14.4G；提升倍数 vs 5X-9600 = **1.5×**、vs 5X-8533 ≈ **1.69×**、vs LPDDR5 = 2.25×——引用时必须对齐档位；LPDDR6 有效带宽再打 89% 折（§3.5）。

**结论口径** [INFERENCE]：实际协议是组合拳（LPDDR6 = ①+③+④；HBM = ②+形态）；根源是**命令位宽（行地址）与请求率随带宽一起涨，而 SI 预算不涨**。

**互连距离决定可行的 rate×width 乘积** [PHYSICAL-EXPLANATION]：HBM 超宽、相对低 per-pin rate（中介层 mm 级）；DDR 窄、高速、长距离（PCB 十 cm 级，需均衡）；LPDDR 中间（PoP/PoH）——HBM 可以用非常宽的 interface 而 DDR 不可以（上文第五条路的物理根源；3D 展望见 §10）。

**互连阶梯表**（量级 [PHYSICAL-EXPLANATION/常识]；加宽省的是 SI 预算、不省电——PHY 功耗仍随总引脚线性）：

| 互连级 | 距离量级 | 可行 per-pin rate | 加宽的边际成本 | 典型选择 |
|---|---|---|---|---|
| PCB | cm~几十 cm | 低中（需均衡） | 高（pin/走线/匹配组/连接器；skew 容差 ∝ UI，宽而快双重恶化） | DDR：窄而快 |
| Package substrate | mm~cm | 中 | 中 | — |
| Silicon interposer | mm | 高（轻 EQ、低摆幅可行） | 低（走线/bump 密度高），**但 PHY 功耗仍随总引脚线性**（§7.2 分层 4） | HBM：宽而适中 |
| TSV | 几十~几百 µm | 很高 | 堆叠内 | stack 内部 |
| Hybrid bonding | µm 级 | 极高 | 最高密度 | HBM4+/3D 方向 |

- energy/bit 维度：距离短 → 低摆幅可行（HBM Tx 0.4V、LPDDR6 Voh≈250mV）→ pJ/bit 低；PCB 长线需强驱动 + 端接 + 均衡 → pJ/bit 高——"HBM 是能效引擎"的物理根源。**加宽省的是 SI 预算，不省电**。

## 4. Refresh & Reliability Evolution

统一主题：**Correctness requirement 如何进入 Controller scheduling**。Refresh 用 Debt 模型、Row Hammer 用 Activation Debt 模型——Reliability Feature 正在越来越多地变成 Scheduler 需要管理的资源和预算。

### 4.1 为什么必须 Refresh

[PHYSICAL-EXPLANATION] 存储介质是会漏电的 1T1C 电容，四类泄漏：pass 管源极-衬底**结泄漏**、**亚阈值泄漏**（WL=0 但 Vth 有限）、**氧化层缺陷/隧穿**、相邻 WL/BL **耦合位移电流**（Row Hammer 的物理根源，§4.6）。

- **温度指数放大**（~2×/10°C，Arrhenius 泄漏）——§4.5 温度倍率的物理根源。
- 破坏性读的回写由 tRAS 驻留内建覆盖（§1.3），不属于 refresh 职责——**refresh 是"不打 DQ 的读"**：行激活 → SA 感知放大 → 自动回写满电平。
- **预算数学**：85°C 下保持 ~32ms → **tREFI = 32ms/8192 = 3.9µs（平均）**（LPDDR5 Table 235：tREFW=32ms、R=8192）；同一 bank 的 REF 间隔最大 **9×tREFI，无论 REFab or REFsb** [PROJECT]——平均可挪、上限不可破。

### 4.2 REFab → REFsb / REFpb

**为什么最早用 all-bank refresh** [PHYSICAL-EXPLANATION + INFERENCE]：① 命令开销最小——一条 REFab 刷全 bank，8192 条/32ms 与 bank 数无关（REFpb 要 ×bank 条）；② DRAM 侧实现简单——无需 per-bank 刷新地址计数器与选择逻辑；③ 深度空闲最划算——反正要停，整个阵列一起停，用最大停顿换最小命令带宽；④ 与 self-refresh 同构（SR 本质是 DRAM 自管 REFab 的长睡眠）。早期够用：2Gb 档 tRFCab=130ns → 刷新占空 ≈3.3%，全停无感。

**演进压力**：密度↑ → tRFCab↑（130ns@2Gb → 380ns@32Gb，Table 235）→ 全停 QoS 代价不可承受 → 细粒度刷新：

| 维度 | LPDDR5 REFpb | DDR5 REFsb |
|---|---|---|
| 粒度 | **单 bank（或 bank pair）** | **各 BG 中同号 bank 同时刷** |
| 其余 bank | 可继续服务 | 可继续服务 |
| 停摆时间 | tRFCpb（最短；tpbr2act / tpbR2pbR 约束间隔） | tRFCsb（约 REFab 一半量级） |
| 控制器实现 | **bank 级刷新债**：per-bank deadline + 机会式插空 | **子通道错峰**：REFsb 相位错开；REFab 只留深空闲窗口 |

- 共同哲学：把刷新从"周期性全局停机"重构为"**可调度的后台工作**"，由控制器 QoS 决定何时还债；REFab 两者都保留（深空闲 / 进 SR 前最划算）。LPDDR5 连 REFab 也允许 postponed/pull-in——"REFab 哲学"在调度层已被预算制软化；LPDDR5 还定义 Optimized Refresh 组合（如 8×REFpb 完成一轮 bank 覆盖）。
- 粒度差异根源 [INFERENCE]：LPDDR 通道窄、延迟敏感（手机）→ 单 bank 粒度；DDR5 子通道 bank 多、吞吐敏感 → BG 级批量刷新省命令带宽。HBM 把"全 bank"粒度直接定义在 PC 上（REFab 带 PC 位、REFpb 按 16-bank set 推进，p65 NOTE 3）[JEDEC]。
- **HBM 的刷新例外** [JEDEC]：HBM 行/列双总线允许普通 row/column 命令 overlap，但 refresh 是重要例外——REFab 后需垫 CNOP、tRFCab 期间该 PC 的命令受冻结（bank availability restriction 比普通列命令更长）——"行列并行"框架里刷新是第一个被牺牲的（§3.1/§3.3）。

### 4.3 Refresh Debt（统一模型）

```text
Refresh = Debt
  Soft State:     债可重排（postpone/pull-in 窗口内）——QoS 决定还债时机
  Critical State:  必须偿还（逼近 9×tREFI 边界）——deadline 语义
  Violation:      超过保持窗口 = 数据丢失 = Correctness failure
```

- 每条 REF 消除一份债；债的粒度随代际变细（REFab → REFsb → REFpb → RFMpb 定向，§4.7）。
- Controller 需要：per-bank / per-PC 债账本、deadline 跟踪、机会式插空调度——**刷新债进 QoS 模型**（§7.2）。
- Refresh 与 QoS 的天然冲突：还债占用命令窗口与阵列可用性——"可调度的后台工作"意味着调度器必须显式管理这笔债，而不是被周期性中断。

### 4.4 Postpone / Pull-in / Critical Deadline

**为什么 postpone 合法**：tREFI 是**平均值**承诺（32ms/8192）——单条刷新在时间轴上滑动不破坏平均，只要窗口约束满足。

**为什么上限是 8+1（9×tREFI）** [JEDEC]：

- 保持时间的硬要求（Table 235：tREFW=32ms 内每行 R=8192 次）——任意推迟会破坏承诺，协议必须给推迟设上限；
- LPDDR5 §7.5.1：**最多推迟 8 条，第 9 条必须执行**（Figure 136/137，窗口 = 9×tREFIe）；HBM3 §6.3.2.5 NOTE 2："**The maximum time interval between two REFRESH commands is 9 × tREFI**"——同一规则的两种写法；
- 压缩侧下界：相邻 REF 间隔 ≥ tRFC——补发不能无限压缩，与推迟上限共同夹出可行域；
- 电流侧约束：DDR5 3DS 错峰刷新（tRFC_dpr ≈ tRFC_slr/3，限 IDD5B1 峰值电流）——协议自身限制刷新的电流聚集。

**为什么必须有不可让步的 critical 边界** [协议口径]：QoS 让步牺牲的是**性能**（延迟/带宽，可协商）；刷新违约牺牲的是**正确性**（超过保持窗口 = 数据丢失，不可恢复）——正确性约束不能被性能约束无限覆盖。三家都以"最大间隔 / 强制执行"的形式内建 critical 语义；**保证最大间隔不被突破是协议强加给控制器的正确性义务**（§7.2）。

**温度改变预算**：2x 档 tREFI 减半 → 同样 8+1 规则下窗口收紧（§4.5）。
*Interview anchor: §9.2 W5/W20*

### 4.5 温度与 Refresh

- 物理根源：结泄漏 ~ exp(−Ea/kT)，**每升 10°C 泄漏 ≈ ×2**；保持时间 t_retention = Q/I_leak [PHYSICAL-EXPLANATION]。
- 协议的三层响应 [JEDEC]：① **DDR5 MR4**（Table 25）：刷新速率随温度档 1x（<80/85°C）→ 2x = tREFI/2（85°C 起，逐档 >95°C）；Wide Range 档（OP5=1）75°C 起跳、延伸 >100°C——**tREFI 倍频**形式（8192 过采样不变、保持窗口 32→16ms）；② **LPDDR 侧另有 4x 档**（移动封装温度极限与场景差异；DDR5 MR4 仅 1x/2x）；③ **HBM3 的 TEMP/CATTRIP 引脚**——温度告警的硬件级联动。
- Controller 含义：高温 → 单位时间 REF 更多；**不能被 bank 并行隐藏的 REF 变成 unhideable bubble → sustained bandwidth 下降**；刷新占空（tRFC/tREFI）随倍频翻倍；与 DVFS 联动的自洽闭环（高温→高频→更高泄漏→更多刷新）。
- **责任三分**：温度→refresh 是协议暴露给 MC 的 **correctness contract**（读到新档位必须满足新速率；热切换时 postpone 预算有协议约束——5B p306 NOTE 1 单调递减）；温度→PHY margin 归 PHY/vendor（MC 不判断 eye 好坏，只经 DFI error/alert/update 通道协调状态转换与流量安全）。**感知通道两型**：DDR5/LPDDR = 拉式（DRAM 自更新 MR 温度位，MC MRR 轮询）；HBM = 推式（TEMP/CATTRIP 硬件引脚异步告警）。REF 分布 / 是否收紧 postpone / 降频节流均属 [PROJECT] 策略。
- **量化锚点**：Refresh Duty = tRFC / tREFI——2Gb 档 1x ≈ 3.3% → 2x ≈ 6.7% → 4x（仅 LPDDR）≈ 13.4%；同步翻倍的还有 REFpb 命令率（tREFIpb 488→244ns）与 drain/低功耗窗口撞刷新概率（§7.8）。[使用 §4.1 已核锚点]

### 4.6 Row Hammer

**统一模型**：

```text
ACTIVATE
   ↓
RAA / activation debt（激活计数）
   ↓
RFM / targeted maintenance（定向刷新管理）
```

- 物理根源 [PHYSICAL-EXPLANATION]：相邻行频繁激活的耦合位移电流干扰受害行电荷（§4.1 第四类泄漏的极端化）——hammer 距离越近、次数越多，受害行保持时间越短。
- **与 tRRD/tFAW 的 event-level 关联**：HBM3 的 RAA 就定义在 tRRDS/tRRDL/tFAW 同一张 AC 表里（JESD238 p175）——两者共享 ACTIVATE 触发事件、同属 activation rate 的预算与记账；但 failure mechanism 不同：tRRD/tFAW 交给电源网络（供电/电流密度/droop），Row Hammer 交给刷新管理（邻行 disturb coupling）[JEDEC 表结构 + INFERENCE]。
- **ACT 极限两层**：单 bank hammer 受 **tRC**（行独占生命周期，§1.3）；多 bank aggregate 受 **tRRD_S/tFAW**（§2.3 墙 1）。

### 4.7 RFM / ARFM / DRFM / PRAC / ABO 演进

| 协议 | 机制 | 要点 |
|---|---|---|
| HBM3 | **RAA 计数 + ARFM（可选）** | 阈值 RAAIMT/RAAMMT/RAADEC 由厂商设定，经 IEEE 1500 DEVICE_ID WDR 可读；达阈值需刷新管理命令 |
| HBM4 | **RFMpb / DRFMpb + BRC** | ACTIVATE 带 DRFM bit 标记风险 bank → 其后对该 bank 的 RFMpb 即 DRFMpb（定向 per-bank 刷新）；**Bounded Refresh（BRC + tDRFM，Table 41）**——把行锤响应从全局长刷新改为对目标 bank 的有界定向刷新，带宽代价最小化 |
| DDR5 | **RFM / DRFM / ARFM**（MR59：DRFM/ARFM/RFM RAA Counter） | 信用制：ACT 计数 vs RFM 冲销，MR 可配 |
| LPDDR5/5X | **RFM → ARFM**（§7.7.6，MR 支持位） | ARFM 按激活速率自适应提高/恢复刷新 |
| LPDDR6 | **PRAC + ABO** | PRAC 上报风险 row/BG/BK（MR87-89）；ABO（Alert Back-Off，MR86 MRFMaACT）限定恢复期最小 RFMab 与退避期最小 ACT |

**共同骨架：activation activity 被计数或风险被显式化 → 达阈值后必须安排 targeted / extra maintenance**（计数位置、阈值归属与反馈通道随协议不同——HBM3 计数在 DRAM 侧 RAA、DDR5 为 ACT↔RFM 信用制、LPDDR6 由 PRAC 上报风险 row）。演进方向：债的粒度越来越细（全局 RFM → per-bank → 定向 bounded），背压方式越来越显式（ARFM 自适应 → PRAC+ABO 显式退避）。

**带宽税的协议口径** [PROJECT，协议组合推导]：

- 本质：ACT rate 产生 RAA debt，REF/RFM 消除 debt——防护成本 = 维持收支平衡占用的时间；
- **单 bank 带宽税 = tRFCpb / (RAAIMT × tRC + tRFCpb)**；所需 RFM 速率 = **1/(RAAIMT × tRC)**（RAAIMT 为厂商离散档位）；
- RFMpb 占用规则：目标 bank 占 **tRFCpb**（不叠加 tRREFD）；不同 bank 的 RFMpb 按 **tRREFD** 穿插（tRREFD 管 RFM 后到下一 ACT 的间隔）；
- DRFM/BRC 语义：DRFM = 用采样 address 对相关 row address **定向维护**（非黑盒全刷）；BRC = 一次 DRFM 以采样 row 为中心、向两侧最多覆盖的物理临近 row 范围；
- **诚实边界**：协议可推导 RFM demand 与 bank-unavailable duty；固定 bandwidth tax 不能只靠协议——真带宽损失 = 维护窗口中无法被其他 bank traffic 隐藏的 useful-command bubble（隐藏能力取决于负载，系统属性）。多 bank aggregate 触顶时 aggregate tax 上界为组合式（tRRD_S/tFAW 约束下轮流触顶）。

Controller Impact：per-bank 计数 / 信用表 + 刷新带宽预算进 QoS；安全场景（汽车）要验证最坏情况下刷新管理开销的上限。
*Interview anchor: §9.2 W7、§9.4 A10、§9.6 Q6*

### 4.8 ECC Error Domain

错误可以发生在链路的六个域，不同 ECC 机制覆盖不同域 [INFERENCE 框架；各行机制为 JEDEC 事实]：

| Error Domain | 错误来源 | 覆盖机制 |
|---|---|---|
| Array（阵列） | cell 缺陷 / 泄漏 / Row Hammer | On-die ECC / RFM |
| Internal datapath（片内数据通路） | 阵列到 I/O 的路径 | On-die ECC（覆盖到读出口） |
| Interface（链路） | DQ/CA 传输错误 | 接口 ECC / Link ECC / parity / DBI-ECC |
| PHY / SerDes | 采样错误、均衡失误 | 训练 margin、retry（协议外） |
| Controller | 计算 / 状态错误 | 自检、端到端保护（协议外） |
| System（链路 + 阵列全路径） | 以上全部 | Side-band ECC / scrub |

### 4.9 On-die ECC vs System ECC

**DDR5 两层纵深** [JEDEC]：

| 维度 | On-Die ECC（片上，强制） | Side-band ECC（模组级） |
|---|---|---|
| 覆盖范围 | DRAM 阵列内部（cell → 读出口） | 链路 + 阵列全路径 |
| 纠错能力 | **SEC：128 数据 + 8 校验位**（JESD79-5B §4.36） | SECDED（8bit/64B） |
| 引脚占用 | 不占（对系统透明） | 占（40-bit 子通道 = 32+8） |
| 控制器角色 | 正常读写路径透明——无逐访问 corrected-error 上报（ECS/诊断可补充遥测） | 全责：写生成/读校验、scrub/patrol、错误计数与日志 |
| 存在目的 | 支撑更高密度 die（容忍更高原始缺陷率） | 系统级 RAS |

关键推论：ODECC 在正常数据路径对 Controller 透明——无逐访问 corrected-error indication，形成相对于 system ECC 的**遥测盲区**（ECS/诊断机制可提供部分补充遥测）；系统 RAS 必须依赖 side-band 层做 scrub 与日志。两层是**纵深防御**：ODECC 显著降低暴露到系统侧的阵列错误率，side-band 兜底链路与残余阵列错误。

**HBM 的片内自治组合**（JESD238 §7.6）[JEDEC]：**symbol-based On-die ECC + 读写 meta-data（MD）位 + 错误擦洗（scrubbing）+ 错误透明协议 + 接口传输 parity + 故障隔离限**——不是主机 side-band 模式，而是片内自治的纵深组合。

### 4.10 Error Reporting / Scrubbing / Retry / Isolation

- **SEV 上报（HBM）**：每 PC 的 **SEV[1:0] 引脚**随读突发携带严重度编码（JESD270-4 Table 67/68 Severity Encodings）——HBM 的读侧 RAS 信息控制器可直接消费（对比 DDR5 ODECC 不可见）。
- **ECS**：自动错误检查与擦洗（HBM/DDR5，错误日志寄存器 MR81/82；HBM4 支持多 bit 纠正记录 MR9）。
- **Scrub**：side-band ECC 模式下控制器全责（patrol scrub 后台巡检）。
- **Retry / Isolation**：HBM 错误透明协议 + 故障隔离限；链路级 Link ECC（LPDDR5 可选）。
- Controller Impact：错误计数器、日志寄存器、告警路径（SEV/TEMP/CATTRIP）进 RAS 管理；side-band ECC 读改写对调度的占用（§7.2）；LPDDR6 把 tag/ECC 嵌入突发（288=256+32）——链路保护不占阵列但吃有效带宽（§3.5）。

---

## 5. Power / Low-Power / Frequency Management

本章只回答：**DRAM 当前处于什么 operating point / power state，Controller 如何管理状态与频率**。PHY 工作点在频点间如何保存/恢复见 §6.8；Controller 如何安全进入/退出这些状态见 §7.10；link closure 见 §6。

### 5.1 Power Domain & Supply Partition（为什么分 rail）

**供电轨对比** [JEDEC]：

| 协议 | 供电轨与典型值 | 备注 |
|---|---|---|
| HBM3 | VDDC 1.1V（core）/ VDDQ 1.1V（I/O）/ Tx driver 0.4V / VDDQL / VPP | 上电顺序 VPP → VDDC=VDDQ → VDDQL（JESD238 Power Ramp） |
| HBM4 | **VDDC 1.05V（core）/ Tx 0.4V / I/O 电压厂商自定** | 标准仅约束相对关系：VPP > VDDC+200mV、VDDC > VDDQ+VSP（JESD270-4） |
| DDR5 | VDD=VDDQ=1.1V（PMIC 在模组，平台只供 bulk 5/12V）；VPP ⚠️1.8V | 上电/管理时序依赖模组 PMIC |
| LPDDR5 | VDD1 / VDD2H / VDD2L / VDDQ | 上电顺序 VDD1≥VDD2H≥VDD2L≥VDDQ；VDD2 拆分**可选** |
| LPDDR6 | VDD1 / **VDD2C 1.0V** / **VDD2D 0.875V** / VDDQ 0.5V（默认） | 顺序 VDD1≥VDD2C≥VDD2D≥VDDQ；Voh=0.5×VDDQ≈250mV；VDD2 拆分**强制** |

演进方向相反 [INFERENCE]：HBM 把余量下放厂商（I/O 电压开放，换 PHY 工艺自由度、配合逻辑 base die）；LPDDR 把电源轨越拆越细——LPDDR6 的 VDD2C（接口侧）/VDD2D（阵列侧）强制双恒功率域：接口域与阵列域的最优电压、负载、di/dt 特性不同——拆分后独立稳压、隔离噪声、**CA 侧调频调压不再扰动阵列裕量**。

### 5.2 Low-Power State Model（低功耗状态 × 六问）

入口分野——**无 CKE 的命令式低功耗（HBM / LPDDR）vs DDR5 CKE**：HBM 低功耗经**命令**进入/退出（PDE/SRE），粒度**通道级**（PC 位定值，§2.5）；LPDDR 同为 CA 命令式；DDR5 经 CKE_t/CKE_c 电平进 PD/SR。每个状态回答六个问题 [JEDEC 5B / HBM3-4] + [PROJECT]：

| 状态 | ① 数据保留？ | ② banks | ③ refresh owner | ④ clock | ⑤ 进入前置 | ⑥ 退出成本 |
|---|---|---|---|---|---|---|
| Active PD | ✓（行开，SA 供电更高——功耗换就绪） | 可带 open row | **MC**——Controller 仍承担 external refresh 义务，但 PD 期间不能正常发 REF，**驻留被刷新债封顶**（HBM tPD MAX=9×tREFI，§1.3） | 可停/浮空（tCMDPD 后） | 读写突发完成（tWR/tRDPDE），**不要求 idle** | ≈tXP（数十 ns）；计时器照走 |
| Precharge PD | ✓（行关） | 全关 | **MC**（同上） | 可停/浮空 | 上者 + 全 bank precharged（tRP 满足） | tXP + tRCD |
| Self Refresh | ✓ | 全关 | **DRAM** | 可停/可变 | **全 bank precharged**（open row 会干扰自刷新电路）；LPDDR5 另要求 SRX↔SRE ≥1 条 extra refresh | tXS（百 ns 级）+ 刷新计时 resume |
| DSM（LPDDR5/5X） | ✓（retention） | 全关 | **DRAM** | 基本必停 | 专用 Deep Sleep 命令（深于 SR） | 深度恢复（CS toggle 退出；tDSM 数值 ⚠️） |
| DPD（LPDDR2/3 历史） | **✗ 不保留**（破坏性深睡） | — | — | — | 掉轨 | re-init + 全量重训 |

- **SRE 要求全 bank precharged 而 PDE 不要求**（进入前置分叉的物理原因）：SR 是"停时钟 + DRAM 自管刷新"，open row 会干扰自刷新；PDE 只是命令路径待命、内部过程照走，可带 open row 甚至进行中的刷新进入（HBM 显式分 active / precharge power-down 两态）。[JEDEC]
- **postpone 债与 SR 的关系** [JEDEC]：协议不要求 postpone 的 REF 补刷完——进 SR 后 DRAM 自管刷新接管外部债（tCKSR 内自启动内部刷新）；LPDDR5 SR 期间刷新计时器 freeze-and-store、退出 resume（债保持）、bank 计数退出清零。
- **DSM** [JEDEC 5B 明文]：§7.5.8 独立成节且在 7.5 Refresh operation 家族下；官方状态图四态（Idle/PD/SR/DSM）；进入 = 专用 Deep Sleep Enable 命令（真值表含 MRS OT/NT 位段）；退出 = CS toggle。**勿与旧代破坏性 DPD 混称**。
- 退出成本阶梯 = break-even 级联（idle 预测 > 阈值_PD < 阈值_SR < 阈值_DSM）——盈亏平衡模型的控制器实现 [PROJECT]；PD 是"有限驻留态"（债封顶）；SR/DSM 不再受 Controller external refresh debt 的同类驻留上限约束——实际驻留仍受平台、电源、温度与协议其他条件限制。
- Controller 责任：进低功耗前排空在飞命令（drain 判据见 §7.8）、进出时序由内部定时器管理、**唤醒延迟显式建模进 QoS**（预测空闲窗口提前唤醒——突发到达时的唤醒开销=延迟毛刺）。

### 5.3 Self-Refresh = Refresh Ownership Transfer

**全章核心 mental model**：

```text
Normal / Power-Down      Controller owns refresh
        ↓ SRE（前置：全 bank precharged）
Self Refresh             DRAM owns refresh（可停钟、可切频、驻留不受外部刷新债约束）
        ↓ SRX
Normal                   Controller owns refresh（计时器 resume）
```

- **control ownership handoff ≠ refresh ownership handoff**：PDE 只交出**命令权**（Controller 仍拥有刷新义务却发不出命令——所以驻留被债封顶）；SRE 同时交出**命令权与刷新义务**（DRAM 自管刷新——所以驻留不受外部刷新债约束、可在 SR 内停钟/切频）。这句话是理解本章与 §7.10 所有低功耗/切频时序的钥匙。
- 该模型直接解释：为什么 PD 驻留上限 9×tREFI 而 SR 没有（§5.2）；为什么 HBM/DDR 切频要借 SR 而 LPDDR 不用（§5.4）。
*Interview anchor: §9.2 W19、§9.5 O1*

### 5.4 DFS / DVFS / FSP（切频 × 刷新：REF owner 框架）

**切频 × 刷新：REF owner 框架** [INFERENCE/PROJECT 组织口径；证据 JEDEC]：

| 协议 | 切频方式 | REF owner | 约束 |
|---|---|---|---|
| LPDDR5 | **非 SR 模式直切**（三组 FSP 预存（FSP0/1/2，MR16 OP3 [JEDEC 5B 明文]），MRW 切换） | **始终在 CTRL**——postpone 债随切频保留，不清债 | §7.6.7 六条件：tCK(abs)min；"**Refresh requirements apply during clock frequency change**"；"All banks are required to be idle state or during tRFCab/pb"；MRW/MRR 完成；tRCD/tWR/tWRA/tMRW/tMRR 满足；CS LOW |
| HBM3/4 | **SR 下切频**（p97："may halt the external clock or change the external clock frequency tCKSRE **after self refresh entry**…stable tCKSRX before exit"） | 进 SR 即移交 **DRAM**（tCKSR 内自启动内部刷新；HBM3 无 LPDDR 式 postpone/pull-in feature，但 Normal mode 下 Controller 仍承担 external refresh deadline 义务（9×tREFI，§4.4），架构上仍可按 debt 建模） | SR 期间 CK 可停/可变；SRX 前 CK 稳定 tCKSRX |
| DDR5 | 同 HBM 的 SR 路线（传统 DDR 手法；细节 ⚠️ [UNKNOWN]） | 同上 | 同上 |

- 推论一：LPDDR 敢直切、HBM/DDR 要借 SR——LPDDR 有三组 FSP 预存（切频 = 寄存器组选组，快、可重入），移动场景需要频繁 DVFS；**owner 不移交才保得住 postpone 债与低延迟**。HBM/DDR 的 DRAM 侧无 FSP 预存，动时钟只能借 SR 让 DRAM 自管（顺便把刷新也移交）。
- 推论二：切频窗口的刷新义务在**时间域连续**（deadline 不因切频重置）——调度器切频前确认 banks idle（条件②）恰好等价于"刷新债此刻无冲突"。
- 切频在 tCMDPD/tFC/tZQPD 等窗口被 inhibit；PD 三态（idle/active/SR PD——SR PD 内部刷新照常）[JEDEC §7.5.7.1]。

**LPDDR6 DVFS 家族**（JESD209-6 §11 / MR19-21，每个模式绑定一条轨与一个目标区间）[JEDEC]：**DVFSC**（VDD2 core 域）/ **DVFSQ**（VDDQ 0.5→0.3V）/ **DVFSH**（VDD2C→1.025V 高速率）/ **DVFSL**（VDD2D→0.85V 低速率）/ **DVFSB**（VDD2D→0.90V 高速率）。Controller 代价：① DFS 序列变为**多轨时序编排**（各轨电压爬坡/跌落顺序与建立时间编进切换序列）；② 维护"模式 × 轨电压 × training set"三维表；③ 与 PMIC 的轨控握手时序成为软硬协同设计点。

- **HBM 到底有没有 DFS？——有频率切换能力，但不是 LPDDR 式 DFS 体系** [JEDEC]：HBM3/4 支持在 Self-Refresh 中 halt 或 change external clock（上表原文）；但没有 LPDDR 那种以频繁 DVFS 为目标的多 FSP 预存 / 非 SR 直切 / 快速 operating-point 切换体系。mental model：**LPDDR DFS = 运行中换挡（gear shift）；HBM 切频 = 停机 → SR → 改钟 → 重启**。
*Interview anchor: §9.2 W26、§9.3 C11、§9.5 O3*

### 5.5 Cross-Protocol Power Philosophy（按优化目标，不按排名）

- **LPDDR → energy proportionality**：负载突发、空闲多（手机/边缘）——频繁 DVFS + 细粒度低功耗态（PD/SR/DSM 多级低功耗态 + DVFS 族 + 温度倍率）是**核心功耗策略**；REFpb 后台债、DFS 多域、2x/4x 温度档三者叠加出最复杂的电源管理面。
- **DDR5 → capacity / RAS / platform power balance**：无 FSP 式频繁切频、频率档由平台配置管理（服务器时序确定性优先），复杂度在双子通道刷新错峰、RFM/DRFM/ARFM 配额、PMIC 模组化（平台只供 bulk）、side-band ECC RMW 占用。
- **HBM → sustained bandwidth / energy-per-bit**：AI 负载持续满带宽——降频收益小，省电靠请求分布 / PC-bank activity 调度降动态活动 + 通道级 PD/SR + 热感知节流 + 低摆幅宽接口（pJ/bit 优先）；**频率切换能力存在（§5.4 SR 路线），但不构成 LPDDR 式以 DVFS 为核心的功耗策略**。
- 功耗学补充 [VENDOR ⚠️ 建议以项目实测替换]：速率路线（3→3E）主要花 IO 功耗买带宽、pJ/bit 改善有限；位宽路线（3E→4）用更低 per-pin 速率跑更宽总线，能效更好——总功耗随带宽近线性，pJ/bit 每代降 ~20~30%。

## 6. PHY Link Closure & Training

本章只回答：**为什么高速 bit 传不过去，以及 PHY 如何把 eye 恢复到可靠工作点**——不展开 analog 电路（CTLE/DFE 实现、PLL/DLL、SI 仿真）。Controller 视角统一为一句话：**这些是 PHY 关闭 link 的内部 knob；Controller 通常只感知训练窗口、完成/失败状态与 operating-point 变化**（发起/编排/断流责任见 §7.6/§7.7）。

### 6.1 PHY Minimum Mental Model

每个概念按 **Concept → 破坏什么 margin → 需要什么训练/校准 → Controller 是否感知** 组织 [PHYSICAL-EXPLANATION]：

- **UI（Unit Interval）**：一个数据 bit 的时间窗。速率翻倍 → UI 减半，而 jitter/skew/反射是绝对时间量不随之减半 → 有效窗口收缩比例超过 UI 减半——一切高速问题的放大器（§6.2）。
- **Eye**：所有 UI 波形折叠叠加。Eye Width = 有效采样时间窗；Eye Height = 判决电压裕量。**training 的目标就是把采样点恢复到眼中心**。
- **Setup / Hold**：接收锁存器的固有要求（沿前/沿后数据稳定最小时间）。写侧 tDS/tDH（相对 DQS 中心对齐）、读侧 tDQSQ（DQS-to-DQ skew 上限）+ tQSH/tQSL——margin 的消耗者：jitter/skew/ISI/温漂。
- **Jitter**：RJ（随机、高斯、无界——热噪声/散粒噪声，只能按 BER 尾部预算）+ DJ（确定、有界——DCD/PJ(PLL 杂散、电源纹波)/DDJ(=ISI+DCD，码型相关)/BUJ(串扰的时域投影)）。总抖动（BER 级）≈ RJ_RMS×k + DJ_pp；直接吃 setup/hold。
- **Skew**：DQ-to-DQ（组内到达差 → 有效眼宽被最早/最晚线夹窄 → per-bit deskew 的理由）；DQ-to-DQS（数据相对选通 → 采样点位置 → write leveling / read training 的对象）。来源：trace 长差、via/interposer 失配、die 内 per-pin 制程偏差。
- **Reflection / ISI**：传输线有特性阻抗 Zo；驱动器输出阻抗、过孔、bump、封装转换点、连接器——每个阻抗不连续点都是反射源（Γ=(ZL−Z0)/(ZL+Z0)）→ 过冲/下冲/振铃 → 前一位的振铃污染后一位的判决窗（ISI）→ 眼闭合。
- **ODT**：die 内端接吸收入射能量；太弱反射残留、太强功耗+摆幅压缩（§3.9）。
- **Crosstalk / SSN**：相邻线容性+感性耦合（侵略线翻转在受害线感应噪声；宽总线=更多同时翻转的侵略者）；多线同时翻转 di/dt×电源/地路径电感 → 电源/地弹跳（SSN 与激活电流 di/dt 同族，但发生在 IO/电源域）——都随总线宽度/速率/同时翻转数恶化，是"宽而快"吃光 SI 预算的原因。
- **Vref**：接收判决阈值；偏移 → 眼垂直不对称收缩。误差来源：IR drop、温度漂移、码型相关偏移 → Vref training（§6.7）。
- **PVT**：训练时的最优 delay/Vref 只是当时 PVT 点的最优——温度（泄漏/迁移率）、电压（IR drop）、制程/老化（NBTI/HCI 慢漂）都会漂移 → 周期性重校（§6.8）。

### 6.2 What Closes the Eye?（速率的代价结构）

- 三段论 [PHYSICAL-EXPLANATION]：频率翻倍 → UI 减半 → 绝对时间量（反射/串扰/jitter/skew）占比翻倍 → static timing margin 不足 → 引入 per-lane deskew / Vref / equalization → PHY 完成实际 delay/Vref tuning → 训练经 DFI 的 training/update 通道协调，发起方与 sequence ownership 取决于 MC-controlled / PHY-master 模式（§7.6）。
- 伴随现象：global 补偿失效（lane 间 eye center 各异 → per-lane、per-bit）；一次训练不再长期有效（PVT 漂移 → retraining/tracking）；训练时间本身成为可用性成本（开机时间、DVFS 切换延迟）。
- 这也是"中距离互连提速率边际成本急剧上升"（§3.10）的微观解释：每翻一档速率，训练维度和重校频度都在增加。

### 6.3 PHY Compensation Toolbox（一个表回答"谁修什么"）

| Physical problem | Margin 被吃掉 | PHY mechanism | 调整对象 |
|---|---|---|---|
| lane-to-lane / per-bit skew | Eye Width | per-lane / per-bit deskew（§6.7） | delay |
| CK↔DQS/WCK 相位差 | sampling phase | Write Leveling / WCK2CK（§6.6） | phase |
| duty 失真（rise/fall 不对称） | half-UI 对称性 | DCA | rise/fall timing |
| Vref offset | Eye Height | Vref training（§6.7） | 判决阈值 |
| 阻抗失配 → 反射/振铃 | 水平 + 垂直 | ZQ 校准 + ODT（§3.9） | impedance |
| channel loss / ISI | 水平 + 垂直闭合 | CTLE / DFE | 频响 / post-cursor 响应 |
| PVT 漂移 | 工作点移动 | retraining / tracking（§6.8） | 已存工作点 |

- **ZQ**：校准对象 = **driver impedance / ODT 阻抗**（随 PVT 漂）——以外部 240Ω 精密电阻为基准，校准 DRAM 驱动器/ODT 阻抗。
- 不做 ZQ 的表现：阻抗失配 → 反射/ISI（太弱）或摆幅压缩/功耗（太强）→ 眼图劣化。
- LPDDR6 后台校准：**完全不占 DQ**；完成后有变化则置位 **ZQUF** 标志，Core 在总线空闲发 **MPC ZQCal Latch** 把新阻抗码字安全应用到引脚、等 tZQLAT 后恢复传输；**DVFS 电压切换时需 MRW 设 ZQ Stop 暂停、切完解除**。
- Controller 感知：管理后台校准窗口与 ZQ Stop 时序（切频序列的一部分，§7.10）。
- **DFE**：用已判决的历史 bit 估算并抵消 post-cursor ISI（不放大噪声）；HBM4/DDR5 高速档依赖 per-pin DFE（LPDDR5X 起），LPDDR6 低摆幅（Voh≈250mV 级）尤其依赖。
- **DCA**：修正 rise/fall 不对称导致的 duty-cycle distortion，恢复 half-UI 对称。
- **CTLE**：对通道频率响应做补偿，减轻高频损耗（仅此一句，不展开电路）。
*Interview anchor: §9.2 W17/W23/W24*

### 6.4 Unified Training Model

```text
Unknown Parameter（delay / Vref / 相位 / 阻抗）
    ↓
Known Pattern（DRAM 提供或回读已知码型）
    ↓
Sweep（扫参数找 Pass/Fail 边界）
    ↓
Pass Window（左右边界夹出可行域）
    ↓
Optimal Point（取中心，而非边界）
    ↓
Store / Restore（存 training set，按频点/电压/温度恢复）
```

- 关键区分：**1D 训练**（只扫 delay：write leveling / read gate / WCK 相位）vs **2D 训练**（voltage×timing 眼中心：read/write eye center）——**delay 决定何时采样，Vref 决定什么是 1**；多次一维 sweep 是 2D 的工程近似（省训练时间）。
- 三维视角：训练参数分三类——**Timing（delay/phase）**、**Voltage（Vref）**、**Channel response（EQ 系数）**。
- 训练失败表现：无 pass window（开路/短路/参数错）→ 需要分步隔离诊断——训练自举链（先 CA 后数据，§6.5~6.7）的意义就在于此。

**完整 training dependency example：LPDDR6**（JESD209-6 [JEDEC]）——后一步只能依赖已经验证的前一步通路：

```text
低频 command bootstrap（UI 宽、未训练 CA 仍有 margin）
    ↓
CS / CA alignment（CBT：PRBS 同种子比对、DQ 回读偏差 bit）
    ↓
ZQ 阻抗校准
    ↓
WCK2CK phase alignment
    ↓
Read path（gate → eye）
    ↓
Write path
    ↓
Vref / DFE fine tuning
    ↓
save training set（按 setpoint；DFS 后恢复）
```

- **低频进/出，高频练**：初始 MR 与 CBT 在低频 f0 完成；FSP 切高频后做眼级训练；training set 保存/恢复是 DVFS 的前提（§6.8）。
- **后一步只依赖已验证的前一步通路**——顺序不是协议品味，是可观测性自举（写训练靠读回比对：RX 未验证则 TX/RX fail 无法归因）。
*Interview anchor: §9.2 W13*

### 6.5 Command Path Training（CS / CA）

命令通路必须最先打通——后续训练的引导（低频 MRW）与结果回读都依赖命令通路可用；完整依赖链见 §6.4 末尾。

- **CS training**：多 rank 共享命令总线时 CS 的到达/眼图差异最大——LPDDR5 CBT 的第一步先训 CS（终端与采样点搜索），结果写回 FSP。
- CA 与 CK 是两条不同物理路径、**不是 source-sync**——training 解决两件事：**CA-to-CK timing + VREF(CA)**（把采样点放到 CA eye 中心）。
- **CA 错一 bit 比数据 bit 错误更严重**：改变命令或地址的语义（写错地址=破坏别的行，发错命令=状态机走错）→ CA 训练零容忍 + CA parity。
- LPDDR6 CBT：CS 拉高、CA[3:0] 发 **PRBS16**，DRAM 内**同种子 PRBS 发生器**逐比特比对，偏差比特经 DQ[7:0] 输出 1（Fail）→ SoC 据此独立调每根 CA 线的发射延迟，循环"复位 LFSR→发 PRBS→读 DQ"直到全 0。
- HBM/DDR5 的命令路径训练走专用机制（HBM 经 IEEE 1500/MISR 体系；DDR5 走 MPC/MRR）——两个协议殊途同归：**命令路径的可靠性都要专用训练机制**。

### 6.6 Clock / Strobe Alignment（Write Leveling / WCK2CK / DCA）

- 问题：控制器无法确定发出的 DQS/WCK 到达 DRAM 的相对延迟（与 CK 路径不同）——**通过 DRAM feedback 闭环测量相对 skew，调控制器侧 strobe delay**。
- LPDDR5 WCK2CK Leveling：锁 DRAM/PHY 内同步 FIFO 的写读指针（WCK 与 CK 异步）；每次 DFS 后必须重做或恢复（§3.6）。
- LPDDR6 WFF：DRAM 生成 CK 锚定、宽 2tCK 的内部脉冲 → 分频后的 WCK 对其单次采样：相位错采样 0、对齐采样 1 → SoC 微调 WCK 发射延迟直至 DQ 上观察到 0→1 翻转——修正 WCK 1/2 分频器的初始相位不确定性（0°/180°）。
- Controller 感知：DFI training handshake；切频序列中的必做步骤（§7.10）。

### 6.7 Data Eye Training（Read Gate / Read Eye / Write Eye / Vref）

- **gate training ≠ eye training（两步串行）**：gate 解决"read strobe 什么时候到、何时开启捕获窗口"；eye training 决定"在 UI 的哪里采样数据"。
- **Read eye training：利用已知 pattern 搜索 pass window 并取 eye center**——DRAM 提供已知码型（LPDDR6 RDC 命令 → DRAM 忽略 FIFO、直接从 **MR32/33/34** 输出固定码型），接收侧扫参数夹出左右边界、采样点放中心。搜索由谁编排不预设：MC-controlled 模式下由 MC 编排 sweep、PHY 执行 delay/Vref 等物理调节；PHY-master / PHY-independent 模式下可由 PHY 自主完成（两种 ownership 模式见 §7.6）。
- **per-bit deskew**：同一 byte 内 per-bit skew 让眼中心各异——高速 PHY 逐 bit 补偿（HBM4 per-pin DFE/VrefDQ 同理）。

**Vref（电压维度）**：Vref 决定判决阈值（“什么是 1”）；只扫 delay 不扫 Vref 只保证水平 margin——电压 margin 不对称时判决裕量下降。
- 找 2D 眼中心（多次一维 sweep 近似）；LPDDR6 的 VREF(CS)/VREF(CA) 写入目标 **FSP 寄存器**（存 DRAM 侧）、delay 值存 PHY 内部。
- DDR5 VrefDQ per-pin 训练（§3.5.71+）；温压漂移的眼偏移由周期性 retraining 调整 Vref 与 timing。

### 6.8 Retraining / PVT Tracking

- training 的结果 = **特定频点/电压/温度条件下的最佳工作点**——这几个之一变化就要 retrain 或恢复（FSP 切换 / ZQ Stop / 温度越档）。
- 机制组合：**training set 多频点保存**（LPDDR：低频 f0 初始化训练 → DFS 后按 setpoint 恢复，DVFSC/DVFSQ 低功耗模式依赖该机制）；ZQ 周期重校（后台）；**interval oscillator 持续追踪**（LPDDR 片内振荡器，标准名 tWCK2DQ Interval Oscillator，§7.6.14）；Vref 重训。
- 静态补偿（训练修 skew=物理常量，§6.5）+ 动态追踪（PVT 漂移）构成完整训练体系。
- Controller 成本：training set 存储（"模式×电压×频点"三维表，§5.4）、重训时机调度（空闲窗口 vs 强制）、训练期间带宽不可用进 QoS。

### 6.9 Cross-Protocol Training Mechanisms

三协议训练机制的根差异在**回读通道** [JEDEC]：

| 维度 | HBM3/4 | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 命令/CA 训练 | IEEE 1500 测试口 + AWORD MISR 签名 | MPC 捕获 CA → MR → MRR 回读 | Command Bus Training |
| 数据训练 | WDQS2CK 对齐 + DWORD 级 MISR/LFSR | MPC 模式读写均衡 + per-pin DFE/DCA/Vref | WCK2CK Leveling + Interval Oscillator 读均衡 + 写均衡 |
| 回读通道 | 独立测试访问口（不依赖功能 DQ） | 数据总线（需先打通 DQ） | CBT/DQ 通道 |
| 频率维度 | 无 multi-FSP / training-set 模型；可在 SR 中改钟（§5.4），但非频繁 DVFS 形态 | 无 FSP 式频繁切换；operating point 由平台配置管理 | **multi-FSP + per-setpoint training set save/restore** |

- 推论（复用边界口径，见 §7.11）：**训练编排的高层 skeleton 可复用，但具体 command sequence / 回读通道 / pass-fail 机制 / operating-point handling 必须协议化**——回读通道不同是训练必须分叉的根因。
- 三家共同点只有两类：**命令路径可靠性必须先建立**（专用训练机制）；**数据路径最终都要关闭 timing/voltage margin**（2D 眼）。多频点 training-set save/restore 是 **LPDDR 的额外特点**（支撑频繁 DVFS，§5.4），不属于 HBM/DDR。
## 7. Controller & DFI Contract

本章回答：**Controller 负责什么、PHY 负责什么、DFI 如何定义两者之间的 contract**。RTL microarchitecture（CAM/队列/仲裁/FSC）见 `DDR_Controller_Architecture.md`。

### 7.1 Responsibility Stack

```text
Controller   What / When——transaction→command、状态/合法性、QoS、refresh debt、sequence
    │
DFI          Contract——transport、latency、phase、handshake、ownership
    │
PHY          How Electrically——launch/capture、delay、Vref、ZQ、EQ、deskew
    │
DRAM         Protocol execution——阵列操作、反馈、内部刷新/维护
```

> **Controller 不应该判断 eye 是否够开；PHY 不应该决定 memory scheduler QoS。**——这是责任边界最重要的一句话。

DFI 承载五类握手：命令/地址、读写数据、训练控制、低功耗、频率切换。训练/更新经 DFI 协调——发起方与 sequence ownership 取决于 MC-controlled / PHY-master（PHY-independent）模式（§7.6）；MC 按 **PhyRdLat / PhyWrLat** 对齐读写时序——**读延迟由 PHY 告知 Controller**（PHY 内部捕获链路深度决定，Controller 不能假设）。

### 7.2 Protocol → Controller State

公共抽象：**bank/PC 状态表 + timing checker + 策略层（QoS/仲裁）**；差异在实例规模与策略维度 [PROJECT]。

**7.2.1 调度对象与状态机**：

| 维度 | HBM3/4 | DDR5 | LPDDR5/6 |
|---|---|---|---|
| 独立调度对象 | 32ch / 64PC（HBM4） | 2 子通道 × rank × 槽数 | 4~8 通道 / x24=2×SC |
| 命令总线 | 每通道行/列双轨（10/8-bit；1.5/0.5/1 拍） | 每子通道 14-bit CA（1T/2T） | 每通道 7-bit DDR CA / LPDDR6 4-bit×2CK |
| 并行度来源 | 通道数 + 行列并行 + PC 独立时序 | rank 并行 + BG 交织 + 双子通道 | 通道数 + BG 交织 |
| 特有维度 | per-PC 时序/刷新状态 + 刷新相位错峰 | side-band ECC 读改写、RCD/DB 链路 | REFpb 债、DFS 窗口、RFM/ARFM 配额 |

- HBM 调度器是"**横向复制 + 全局 QoS**"（对象多而轻）；DDR5/LPDDR 是"**少数深通道**"（单对象内 rank/BG/刷新/翻转策略复杂）。
- 地址映射是三家共享的设计课题，只是维度数不同：HBM 用 channel-first striping（cache line 级打散到 32 通道，防止单通道热点吃掉翻倍带宽）；DDR5/LPDDR 在子通道/通道维度的 hash 同样决定热点分布——**映射失效 = 并发收益归零**。

每个调度对象（bank/PC/子通道）的状态机至少含：open row 地址、tRCD/tRAS/tRP/tRC 计时器、刷新债 deadline、RAA/RFM 计数——寄存器成本随对象数线性增长（HBM4 64PC × 最多 64 bank 是极端值）[PROJECT + JEDEC 锚点]。

**刷新债的 postpone 预算随 bank 数收紧**：截止时间 = 9×tREFI（§4.4）；到点冲刷 owed 刷新的时间 ∝ banknum × tRFCpb（REFpb 模式每 bank 至少一条债）——bank 越多，窗口内留给普通命令的松弛越少（§2.3 墙 3 的调度器视角）。

**发射通路成本**：队列匹配与发射检查的对象数随 bank/tag/通道数增长，发射路径的功耗与时序压力线性上升（RTL 细节见 `DDR_Controller_Architecture.md`）。

**通道继续增加，瓶颈何时离开 DRAM（分层判据）** [INFERENCE]：

1. **DRAM 是默认瓶颈**：实测带宽 << peak、命令槽在等 DRAM 时序（row miss / tRRD / tFAW / 刷新占空）——此时加通道/加 bank 才有效。
2. **Controller 的增长形态取决于组织方式**：每通道独立控制器实例——单实例逻辑不随通道数增长（横向复制）；多通道共享一个控制器——仲裁/CAM/队列随通道数增长。但两种方式都保留一层不复制的**全局层**：地址映射/防热点、跨通道 QoS 与功耗预算——它才是共享瓶颈。判据：通道 ready 却无可发命令（映射/QoS 卡住）或部分通道饥饿。
3. **NoC 的并发上限**：crossbar 端口数与路由拥塞决定所有通道能否真正并行——请求方到各控制器实例的聚合带宽 ≥ N×每通道带宽才不拖后腿；映射失效时 NoC 单路径拥塞、其余通道闲置。HBM 的 near-compute 摆放（2.5D 中介层）本质就是把 NoC 瓶颈推迟/消除。
4. **PHY 的面积/功耗随总引脚线性增长**——HBM4 的 2048 DQ 使 PHY 功耗占封装预算大头；训练/漂移重训练造成可用性损失；DFI 带宽必须匹配聚合命令率。

典型转移顺序：DRAM（时序限额）→ Controller 全局层（映射/QoS）↔ NoC（crossbar/拥塞，谁先取决于拓扑与流量分布）→ PHY/封装（功耗预算）。负载类型决定卡在哪层：随机多核负载先考验 NoC/QoS，row-buffer 型负载先考验 DRAM 时序。设计含义：通道继续增加时，投资优先级从"DRAM 内部并行"转向"映射防热点 + NoC 容量 + 每通道实例化"——这也是 HBM4 通道翻倍而不动 ch-2PC 的原因之一。

**7.2.2 Scheduler 的七个自由度** [PROJECT]——协议不可改的时序墙（§1/§2）里重排时间线，把不可避免的开销移到伤害最小的位置，并用地址映射预防它们发生：

| # | 自由度 | 对应协议事实 | 层归属 |
|---|---|---|---|
| 1 | 命令聚合重排序 | row miss 放大 3:1 → 聚合降到 1+2/N（§3.4） | 每通道实例内 |
| 2 | batch 读写切换 | 攒写分组翻转，减少 tWTR/tRTW 次数与 tWTR_L 代价（§3.8） | 每通道实例内 |
| 3 | 错峰 REF | 双子通道 / per-PC / per-bank 刷新债相位错开（§4.2） | 实例间协调（全局层） |
| 4 | refresh postpone/pull-in | ±9×tREFIe 预算（§4.4） | 控制器↔DRAM 的预算协议（跨层） |
| 5 | BG/通道交织地址映射 | BG-aware 排序 + channel-first 防热点（§2.4/§7.2） | 全局函数 |
| 6 | page open / auto-precharge 策略 | open-page 换 hit 率 vs close-page 省命令（§3.4） | 每通道实例内 |
| 7 | QoS 带宽/延迟分配、防饿死 | 调度优先级骨架（下） | 全局仲裁 |

调度优先级通用骨架：**刷新（含 RFM/ARFM/PRAC 配额）> 写排空（防写饥饿）> 读 QoS > 预充电合并/激活调度**。各协议附加维度：HBM = per-PC refresh/timing 错峰 + 行列并行窗口；DDR5 = 双子通道错峰 + side-band ECC RMW 占用；LPDDR = DFS 窗口 + 温度刷新倍率（2x/4x）。

**7.2.3 Timing Checker 的协议来源**——checker 分层、每层参数都来自协议具体条款 [PROJECT + JEDEC]：

- **bank 内**：tRCD、tRAS/tRC、tRP、tRTP、tWR→tRP 链、tRFCpb、drfm2act——来源：阵列生命周期（§1.3/§1.4）+ 刷新（§4）；
- **跨 bank/BG**：tRRD_S/L、tCCD_S/L、tWTR_S/L——来源：供电预算（§2.3）+ BG 流水（§2.4）；
- **跨 SID/rank**：HBM 多 stack 共享通道总线的 turnaround；DDR5 R2R 翻转与错峰刷新——来源：共享接口（§2.2）；
- **系统级**：tFAW 滑动窗口计数器、刷新预算、ODT/总线翻转——全局计数器而非本地比较器。

bank 内 / 跨 bank 是本地比较器（随实例复制、成本低）；系统级是全局计数器（不复制、是共享瓶颈，§7.2）。**总线独立 ≠ 时序独立**（HBM 行/列双总线，跨域链 tRCD/tRTP/tRTW 照常约束行决策与列决策）。

**7.2.4 Refresh / Row Hammer 记账**（详见 §4）——协议强加给控制器的正确性义务：

- per-bank / per-PC 刷新债账本 + deadline（9×tREFI 硬边界）+ postpone/pull-in 预算管理；
- RAA/RFM 信用表（计数 vs 冲销）、RFMpb 插空规则（tRFCpb/tRREFD）、ABO 退避期最小 ACT；
- 温度档切换（MR4）改变刷新预算——热管理联动；
- 最坏情况带宽税验证（安全场景）：单 bank 税 = tRFCpb/(RAAIMT×tRC+tRFCpb)（§4.7）。

**7.2.5 Command Encoder**——三家的命令编码格式正交、无法参数化统一 [INFERENCE]：

- HBM：行/列双轨（1.5/0.5/1 拍；三沿锁存、奇偶按 30-bit 窗口计算）；
- DDR5：14-bit CA 1T/2T（2T 原子不可拆；MPC 承载训练子命令）；
- LPDDR：7/4-bit DDR CA（命令 2 CK；ACT-1/2 两条命令 + tAAD 窗口约束）。

编码器还要处理：行/列总线 pin 重映射表（HBM 每通道有 remap）、CS 时序（DDR5 2T 的 CS_n 第二拍控制 non-target rank ODT）、广播 vs 定向 MRW（DDR5 "broadcast across all logical ranks"）。

### 7.3 Why DFI Exists

- **Controller 为什么不直接驱动 DRAM pin？** MC digital timing domain ≠ PHY high-speed electrical domain——PHY 需要独立时钟域（frequency ratio，§7.4）、独立工艺（analog heavy）、独立训练状态机；直接驱动等于把三重异质性强耦合进控制器。
- **DFI 解耦什么？** MC 掌 *which command / when*；PHY 掌 *how command/data physically appears at pins*——What/When 与 How Electrically 的标准分界。
- **DFI 本身不是什么？** 不是 DRAM protocol、不是训练算法、不是 AXI、不替 Controller 做 scheduler——它是 **MC ↔ PHY digital contract**。
- 附注 [VENDOR：ddr-phy.org 官方]：**DFI 5.0** 起训练架构全面转向 PHY-independent training mode（PHY 不经 controller 完成训练），并提供 PHY-independent boot、扩展 frequency change 支持；**DFI 6.0**（2026-05）首次官方支持 HBM 与最新 LPDDR、移除 legacy 协议支持（DFI 5.2 继续服务前代系统）、增强 power-saving 与 fault identification/recovery。

### 7.4 Frequency Ratio / Gearbox / Phase

**Frequency ratio：空间换频率** [DFI]

```text
f_MC = f_CK / ratio          Width_DFI(每方向) = 2 × ratio × DQ_width（2 = DDR 双沿）
```

- ratio 是 **DFI(MC) 时钟 : PHY 高速时钟域** 的关系（DFI 5.1 明文示例为 1:1 / 1:2 / 1:4——具体档位由集成配置，DFI 不限定）。注意与 LPDDR 的 CKR（CK:WCK，DRAM 协议侧）是两个独立旋钮。
- **带宽守恒**：256-bit @800MHz（1:4）= 32-bit @6400 MT/s——吞吐不损失；代价是 DFI 总线加宽 / phase 化 / 延迟与对齐逻辑。
- 为什么 ratio 不伤命令吞吐：现代 DRAM 自然命令率本来就 sub-CK（DDR5 tCCD_S=8nCK → 列命令率 ≤ 1/8CK），1:4 每 MC cycle 4 个 phase 槽绰绰有余 [INFERENCE]。
- Timing checker 机制：**MC 域计数 + phase 子字段**——ns 级长参数（tRCD≈56CK=14 MC cyc）粗粒度足够，仅短参数（tCCD/tRRD/1T-2T 间距）需要 phase 级比较 [INFERENCE]。

把两个容易混淆的旋钮钉死：

- **DFI ratio** = MC/DFI 数字时钟 : PHY 高速时钟域——解决 "MC digital logic 跑不到 DRAM pin rate"（空间换频率）。
- **CKR** = LPDDR 协议侧 CK:WCK——解决 "命令域与数据域时钟解耦"（§3.6）。
- **两者完全不同、相互独立**：一个在 MC↔PHY 边界，一个在 PHY↔DRAM 边界。

### 7.5 Read / Write Data Contract（deadline vs arrival）

**写路径：deadline 驱动（必须提前交付）**

- DRAM 在 write command + **CWL**（nCK）处用 DQS/WCK 沿采样 DQ——数据必须在 pin-level deadline 前就位；PHY 在此之前要完成 DFI FIFO/gearbox、串化、strobe 生成。
- 写 contract = **集成期协定的常数**：tphy_wrlat（WR command → dfi_wrdata_en）+ tphy_wrdata（wrdata_en → 首个数据）[DFI 5.1 Table 12]——MC 与 PHY 双方一致编程、**静态保证**：写晚到不可恢复（PHY FIFO underrun = 总线垃圾数据，协议无 retry）。
- Write Leveling（§6.6）修的是 CK↔DQS/WCK 在 DRAM 引脚处的**亚周期** skew，不动 cycle 级 contract——两层正交。
- 写数据**升序对齐**（"aligned in ascending order"，§4.10.3）；**rolling 只在读路径存在**。

**读路径：到达驱动（事后对齐）**

- **读写所有权不对称（本节核心）**：写方向 PHY 是时序**产生者**（source-sync——"谁发 data 谁发 strobe"），deadline 驱动、必须提前备好；读方向 PHY 是时序**接受者**，被动捕获、只能事后对齐（FIFO + rolling）[INFERENCE]。
- **PhyRdLat（tphy_rdlat）**= dfi_rddata_en → dfi_rddata_valid 的 DFI cycle 数 [DFI 5.1 Table 15]。分段模型：transport(1~2) + 串化 + DRAM RL(nCK) + capture/FIFO + deser/跨时钟域。**PHY 拥有、MC 被告知**，按 (频率 setpoint × ratio) 配置且**确定性**——训练只修亚周期 margin，PhyRdLat 的变化发生在切频 / 换 setpoint，不随 setpoint 内训练结果变 [INFERENCE]。
- 主公式：**PhyRdLat ≈ (RL_nCK + PHY_pipe_nCK) / ratio**——实际值来自具体 speed bin 的 CL/RL、PHY pipeline 深度、DFI ratio 与集成配置 [INFERENCE 结构]；绝对 ns 读延迟近似与 ratio 无关（主导项是 DRAM RL），ratio 增大主要加深 PHY pipeline 与对齐复杂度。
- **rolling 只在读路径**：PhyRdLat 答"哪个 DFI cycle 数据回来"，rolling 答"cycle 内从哪个 word/phase 起始"——两者正交。写路径是 active sender：MC 主动投递、从 canonical word 起始、升序对齐；读路径是 passive receiver：arrival phase 由 DRAM RL 决定、不可强制 → rolling，MC 侧 rotator 重排。这一不对称是“为什么读可事后对齐、写必须提前备好”（§9.5 O8）的根源。
*Interview anchor: §9.4 A11、§9.5 O8/O9*

### 7.6 Training Ownership（两种模式）

DFI 只定义握手与逃生协议，**不定义训练算法**。总模型：**训练算法可以住在 MC 或 PHY，但物理调节永远属于 PHY 域能力。**

- **MC-controlled training**：MC 掌 sequence / command / state control；PHY 调 delay / Vref / EQ；DRAM 出 pattern / status / feedback——"Core 发命令，PHY 调延迟，DRAM 报结果"描述的是**这种**模式（是常见缺省，不是普适规则）。
- **PHY-master training**：PHY 暂时取得 command ownership，接管 DRAM 命令总线自主训练——**此时连命令也由 PHY 发**；接管前必须先 QOS Disconnect 断流握手（§7.7）。
- 模式选择是集成决策：MC-controlled 要求 MC 维护训练编排；PHY-master 要求断流窗口与所有权交接机制。

### 7.7 Update / Error / Ownership Handoff

```text
MC traffic running
    ↓ PHY requests update / training ownership
disconnect / quiesce（QOS Disconnect 或 Error Disconnect）
    ↓
ownership handoff（DFI 总线移交 PHY）
    ↓
PHY work（update / retrain / 修复）
    ↓
completion or error（error_pN / dfi_alert_n 透传 / Error Codes）
    ↓
ownership returned
    ↓
resume
```

- 机制族 [DFI]：ctrlupd（MC 起始更新）、PHY-initiated update（QOS Disconnect 协议）、Error Disconnect、**dfi_alert_n**（DRAM ALERT 引脚经 PHY 透传 MC、ratio 下 per-phase 对齐）、Message Interface **Error Codes**。
- **失败上报有协议、恢复策略无标准**（retry 次数 / 降频重训 / safe mode 是集成选择）。典型分层 [PROJECT]：自主训练 PHY 内部 retry → 穷尽后 error 寄存器（带中断）上抛；MC HW 只做两件事——服从断流 + 存 error codes；超时由 PHY 侧监测（DFI 无标准 timeout）；fatal 判定在 SW。

### 7.8 Drain & Quiesce（全局状态转换核心）

**统一模型**（状态机 RTL 实现见 `DDR_Controller_Architecture.md`）：

```text
Normal Traffic → Drain → Quiesce → State Transition → Restore → Validation → Resume
```

**Drain 语义**：

- 写推到 **DRAM 完成点**——commit 有两个边界：AXI 接受点（对主机不可撤销，写不能"错误完成"）与 DRAM 完成点（命令 + 突发 + tWR）；只送到 PHY/DFI 不算完 [PROJECT+JEDEC PDE 条款]；
- 读可收完或 **SLVERR 显式错误完成，不可静默丢**——写靠一致性约束（必须完成）、读靠可见性约束（必须响应）[PROJECT：AXI 响应策略]；
- drain 排的是**业务**，不是协议义务——**刷新债 deadline 照走**（必要时 drain 中插一条 REF 再继续排，而不是加速丢弃）；
- 新请求**滞留**（不置 arready/awready/wready——AXI 无"拒绝"语义），自 drain 起生效直至 Resume；
- 排空估算 [INFERENCE]：`T_drain ≈ T_last_read + 最大 burst 折算命令数 × 单命令服务 + 尾部时序`——AXI4 单 burst 最长 256 beats、总字节 = 256 × beat 宽度（64-bit 接口即 2KB [PROJECT]）→ 64B 粒度 32 条列命令 × tCCD_S 2.5ns ≈ 80ns + 末写 tWR ≈ 单流 100~150ns；常规档插不进 REF（边界 3.9µs），**高温 2x/4x 档（tREFI ≈1.95µs / 0.98µs）会撞上**。

**Quiescent 四层判据（与三轴对接）** [PROJECT 判据 + DFI]：

```text
L1 系统级：AXI 已接受事务全部完成（req/resp 收敛）—— 轴 3
L2 引擎级：发射停（CAM 空、backpressure 生效）—— 轴 3
L3 接口级：DFI 三流全空（命令 / 写数据 / 读数据）—— 轴 1（ctrlupd 的判据线）
L4 DRAM 级：尾部时序履行（末写 +tWR、末读 +tRTP）+ banks 达目标态前置 —— 轴 2
```

- ctrlupd 停在 L3；PDE 到 L4 轻（允许 open row）；SR/DSM 到 L4 重（全 precharged）+ L1/L2 全排空。CAM 空 ≠ 静止——最后一条命令完成后尾部时序还在走。
- **三轴坐标**（轴 1 接口处理：静默/移交/挂起 × 轴 2 DRAM 前置：无/有 × 轴 3 队列：保留/排空）：ctrlupd = 静默+无前置+保留（最快恢复）；PHY Master = 移交+视训练+保留；**DFS = 静默+全局前置+保留（hybrid——transient/global 二分的反例，证明三轴必要）**；SR = 挂起+全局前置+排空 [DFI 5.1 证据：TABLE 23/24/25、FIGURE 70/71/72/77、FIGURE 43 MC-Initiated Update + §4.9.2 PHY-Initiated Update；详见 §7.7]。
- 轴 3 边界 [DFI vs PROJECT]：断流/所有权移交是 DFI 义务；Controller 内部 queue 是否保留、host admission 是否继续、何时 backpressure 属实现策略——典型短 PHY update 保留排队请求无缝续跑，较长的全局状态切换（进 SR/DSM）选择 drain/backpressure。
- 低功耗状态表（PD/SR/DSM + 历史 DPD 对照：保留/owner/退出）见 §5.2。
*Interview anchor: §9.4 A13、§9.5 O2/O5/O6*

### 7.9 Initialization（依赖链）

> **每一步只能依赖前一步已验证过的通路**（自举原则）。

**Init 依赖链（自举原则：每一步只用已验证的前置通路做判据）**：

- Power 稳 → reset 才可信（轨未偏置完成时逻辑行为部分随机、reset 结果不可重复）[PHYSICAL-EXPLANATION]；**命令是第一个需要 clock 质量的消费者**（clock 可与 reset 并行启动，首命令前有最小等待 ⚠️ [UNKNOWN]）；
- 初始 MR 序列在**低频**下执行（CK 慢 = UI 宽，未训练 CA 仍有 margin）→ 低频命令进训练模式 → FSP 切高频 → CBT/眼训练——"**低频进/出、高频练**"是 MR↔CA 鸡蛋问题（进训练模式本身需要 MRW）的协议解法（§6.4）；
- 顺序的失败模式 [PHYSICAL-EXPLANATION]：ZQ 后移 → 阻抗未定、训出的是错误眼的中心；WCK2CK 未完成 → 相位不确定性未消除、眼位置漂移；读先于写 = 可观测性依赖（写训练靠读回比对，RX 未验证则 TX/RX fail 无法归因）；
- MC/PHY ready（dfi_init_complete，FIGURE 3）之前 AXI 不放行——提前放行 = hang 或 corrupt；DFI 无标准 timeout，超时由 PHY 监测经 error 寄存器反馈 [PROJECT]；
- 刷新债计时器起点随 init 完成生效（首笔 traffic 前可能需先还债）[INFERENCE；起点定义 ⚠️ [UNKNOWN]]；
- 时间预算：full boot training 显著重于已保存 training-set 的恢复——因此多频点系统尽量保存并恢复已训练 operating point，而不是每次 DFS 全量重训（量级随协议/速率档/实现而变，不锚定单一数字）。

链式总结：

```text
Power credible → Reset credible → Clock/bootstrap command credible
    → 低频 MR access → CA/command path → ZQ/impedance → strobe/phase
    → read path → write path → high-frequency operating point（FSP）
    → Controller logical state → traffic enable
```

- “低频进/出，高频练”；预存 training set、按 setpoint 恢复——init 的经济学。

### 7.10 Low-Power / Frequency Transition（怎么安全切进去）

Chapter 5 回答 state 是什么；本节只回答 Controller 如何安全切换。统一序列：

```text
Normal → stop admission → drain（§7.8 四层判据）→ satisfy tail timing
    → precharge if required → DFI/PHY state coordination → SRE / PDE / DFS
    → restore（FSP 选组 + training set 恢复）→ validate → resume
```

**切频参数失效模型**：

- **变**：① DRAM MR/timing 档——**FSP 寄存器组预存切换**（CL/CWL/ODT/Vref 各频点一套，切频 = 选组而非逐条 MRW——"直切快"的机制地基）[JEDEC]；timing 按**三分法**处理：ns 守恒类（tRCD/tRP——绝对值不变、nCK 折算变）/ nCK 类（tCCD——绝对时间随 CK 变）/ **时间域类（tREFI/债——完全不变**，六条件的核心）；② DFI contract（tphy_rdlat/wrlat 换值；**ratio 亦可能随频点变**——低频 1:2、高频 1:4 合法 [INFERENCE]）；③ PHY training operating-point + ZQ 阻抗码字（电压轨变 → ZQ Stop，§6.3）。
- **不变**：拓扑（地址映射/channel/bank）、数据内容、协议语义（命令编码/状态机）——**状态语义连续正是队列可保留（轴 3）的前提**。
- 成本阶梯 [INFERENCE]：FSP 选组 + training set 恢复 < MR 全量重写 < 全量重训——成本单调上升。
- REF owner 两路线与切频六条件见 §5.4 表；DFI 频率切换的 signal-level 手序列不在本文范围（架构排序模型见本节）。

### 7.11 Multi-Protocol Controller Reuse Boundary

**统一的是前端（事务/QoS/基础设施），分叉的是协议引擎** [PROJECT]：

- **可复用（协议无关层）**：事务层（AXI/CHI 端口、QoS/仲裁/防饥饿、地址 hash 与 interleave 框架）、基础设施（性能计数、错误注入/记录框架、寄存器与诊断架构）、**参数化引擎骨架**（bank 状态表结构、timing checker 框架、通用调度接口）。
- **必须协议化（协议相关层）**：命令编码器（§7.2.5——格式正交）；刷新/RFM 语义（RFMpb/DRFM vs REFsb/RFM vs REFpb/ARFM/PRAC——策略与命令接口都不同）；低功耗/切频序列（HBM 命令式无 CKE vs LPDDR CA 命令式+FSP vs DDR5 CKE）；**训练编排——高层 orchestration skeleton 可复用，具体 command sequence / feedback channel / pass-fail 机制 / operating-point handling 必须协议化**（回读通道差异见 §6.9）；DFI 参数化与时序参数。
- 工程结论：落地形态 = **shared transaction front end + protocol-specific memory core + shared infrastructure**。
*Interview anchor: §9.4 A4*

## 8. Generation Evolution

本章只记 **Delta**——不重教协议（机制见 §1~§7 对应章节）。每节末尾"我真正需要记住的 N 条变化"。

### 8.1 DDR4 → DDR5

| Feature | Previous（DDR4） | Current（DDR5） | Pressure（上一代为什么不够用） | Controller Cost | PHY / Package Cost | Gain |
|---|---|---|---|---|---|---|
| 通道组织 | 1×64-bit | 2×32-bit 独立子通道 | 预取 8n→16n 后 64-bit 通道 = 128B 过取、cache line 失配；命令并发不足（§2.5） | 双实例状态表 / checker / 刷新错峰 | DFI / 训练双实例 | 命令并发 ×2、64B 粒度对齐 |
| 命令接口 | 20+ CA 全 1T | 14-bit CA + 1T/2T | 子通道化后引脚预算减半——引脚换拍数（§3.2） | 编码器区分 1T/2T、2T 原子性 | CA 训练 / 眼图裕量 | 引脚省、走线规整 |
| RAS | 系统 ECC 为主 | ODECC 强制（128+8 SEC）+ side-band | die 密度↑ → 原始错误率↑（§4.9） | 透明纠错→遥测盲区，需 side-band 兜底 + RMW 占用 | DRAM 内校验逻辑 | 密度可持续 |
| 电源 | 供电简单 | PMIC 上移模组 + VPP | 服务器电源管理精细化 | 上电时序 / 侧带管理对接模组 | 模组 PMIC、VPP 轨 | 供电质量/管理 |
| 刷新 | 全 bank 为主；tRASmax 时代残留 | FGR/REFsb + RFM/DRFM/ARFM；tRASmax 删除 | 容量↑ → tRFC 变长；Row Hammer（§4） | 刷新债 / 信用账本进 QoS | 阵列管理逻辑 | QoS + 可靠性 |

**我真正需要记住的 5 条**：

1. 子通道化的因果链是 **prefetch 16n → 64B 对齐 + 命令并发 ×2**（不是"带宽翻倍"——引脚不变 peak 不变，§2.7）；
2. CA 20+→14 根，代价是 1T/2T 命令——引脚换拍数；
3. **ODECC 强制 + side-band = 纵深防御**，但 ODECC 正常路径透明纠错、遥测盲区更大（ECS 可部分补充）；
4. **PMIC 上移模组**是电源管理责任迁移（平台只供 bulk）；
5. 刷新家族（REFsb/RFM/ARFM）+ tRASmax 删除 = 刷新管理复杂度全面转移到控制器。

### 8.2 LPDDR5 → LPDDR5X → LPDDR6

| Feature | Previous | Current | Pressure | Controller Cost | PHY / Package Cost | Gain |
|---|---|---|---|---|---|---|
| 速率 | LPDDR5 3200~6400；5X 至 10.7G | LPDDR6 10.6~14.4G | 带宽需求（AI 手机/边缘） | QoS 按新档位建模 | UI 收缩 → 训练/EQ 加重（§6.2） | ×1.5~1.69 |
| 通道组织 | 16-bit 通道 | x24=2×SC（12-DQ）+ x12 效率模式 | 细粒度 + 引脚效率（§2.5） | SC 独立状态机；x12 配置管理 | per-SC 4CA+CS+CK | 粒度细 / 混装容量 |
| 命令编码 | 7-bit CA DDR | 4-bit CA、命令 2CK、ACT 4CK | 引脚预算再压缩（§3.2） | 编码器双命令序列（ACT-1/2+tAAD） | CA 眼图更紧 | 引脚最省 |
| 突发 | BL16 | BL24/BL48（288=256+32） | 预取换速率（§3.5） | 89% 有效带宽建模；部分写 RMW 上移 | — | 数据/命令开销比 |
| 电源 | VDD2H/L 可选拆分 | VDD2C/D 强制 + DVFS 族 | 能效管理精度（§5.1） | 多轨编排 + 模式×电压×训练集三维表 | 多轨 PMIC | 能效 |
| 写路径 | DMI + MASKED WRITE | 全删（DBI 保留） | RMW 串行化不可接受（§3.9） | 字节部分写 RMW 自己做 | — | 速率 |
| 可靠性 | Link ECC 可选、RFM→ARFM | 突发内嵌 tag/ECC、PRAC+ABO | 链路速率↑、行锤演进（§4.7） | PRAC 风险 row 管理 + ABO 退避 | — | RAS |

**LPDDR4 → LPDDR5：6 条核心 Delta**（LPDDR4 侧为业界常识口径 ⚠️[JESD209-4 不在库]；LPDDR5 侧均有标准原文依据）：

| Delta | Pressure（上一代瓶颈） | Mechanism | Controller / PHY Cost | Gain |
|---|---|---|---|---|
| WCK + CKR（2:1/4:1） | CK/CA 速率随数据速率一起升高，SI/引脚压力 | 命令域（低速 CK）与数据域（per-byte WCK）速率解耦 | **WCK2CK Leveling 新训练义务**（LPDDR4 write-leveling 的演化）+ 三时钟域弹性 FIFO | 数据 3200→6400 而 CA 不加速 |
| Bank 架构三模式（BG/8B/16B） | 核心/接口剪刀差下列吞吐受限（§2.4） | 按速率档选择：BG（跨 BG 2tCK/同 BG 4tCK）/ 16B（统一 2tCK）/ 8B（低速兼容） | BG-aware 排序 + S/L 双档 checker | 列吞吐 profile 可配 |
| 2 → 3 FSP | 多频点 DVFS 需求 | 三组寄存器预存，MR16 OP3 选 FSP0/1/2 [JEDEC 5B 明文] | 三套 setpoint 管理 | 直切更快、DVFS 地基 |
| BL16 / BL32 | 预取档位灵活化 | MR 选择 [JEDEC 5B 明文，BL32 46 处命中] | 粒度相关的调度/tCCD 建模 | 数据/命令开销比可调 |
| VDD2H/L 可选拆分 + DVFSQ | 能效 | 阵列/外设分轨 + VDDQ 动态调压 | 多轨电源管理 | 功耗 |
| Link ECC（可选） | 链路速率↑ | 链路级校验 | ECC 逻辑/延迟 | RAS |

**我真正需要记住的 5 条**：

1. LPDDR6 的带宽提升是"速率 ×1.5 + die 内拆双 SC"，且**有效带宽打折**（288-bit 突发仅 256-bit 有效）；
2. CA 7→4 根的代价 = 命令 2 周期、ACT 4 周期（命令带宽减半）；
3. **VDD2 强制拆成接口域/阵列域 + DVFS 五模式**——电源管理面最复杂的一代（三家哲学对比见 §5.5）；
4. 掩码路径全删：DM、DMI、MASKED WRITE 都没了——**部分写责任上移控制器**；
5. **PRAC + ABO** 是行锤背压最显式的一代（DRAM 报风险 row、控制器管退避）。

### 8.3 HBM3 → HBM3E → HBM4

| Feature | Previous | Current | Pressure | Controller Cost | PHY / Package Cost | Gain |
|---|---|---|---|---|---|---|
| 接口 | HBM3 1024-bit/16ch @6.4G；3E 同位宽 @9.6G | HBM4 2048-bit/32ch，8G 基线→12.8G+ | 继续提速率边际成本过高（均衡、训练、pJ/bit、良率）→ 翻位宽（§3.10） | 32ch/64PC 状态表翻倍；channel-first 防热点 | bump 密度 / 中介层布线；host-side PHY/shoreline 压力增大 | peak ×2（vs 3E 为 ×1.67，基线速率回落 9.6→8G） |
| 电气 | I/O 1.1V 固定 | I/O 厂商自定、VDDC 1.05V | 把余量下放厂商，换 PHY 工艺自由度（§5.1） | 电气取公约数 | PHY 工艺选择自由 | 工艺自由度 |
| 容量/组织 | 通道与容量同步增长 | 4 die 满 32ch；5~16 die 只加容量/SID/bank | 带宽需求与容量需求不同步（§2.8） | bank 数可枚举配置（16~64/ch） | die 堆叠高度 / 散热 | 容量弹性、row hit 率 |
| RAS | RAA + ARFM（可选） | RFMpb/DRFMpb + BRC、ECS 多 bit | 行锤定向化 + 带宽代价有界（§4.7） | 风险 bank 跟踪 / 有界刷新编排 | DRAM 内逻辑增加 | 定向防护 |

**我真正需要记住的 5 条**：

1. **3→3E 靠速率、3E→4 靠位宽**（基线速率反而回落 9.6→8G；产品带宽靠代内速率爬坡到 12.8G/3.3TB/s [VENDOR]）；
2. 通道翻倍但 **ch-2PC 同构不变**——控制器对象模型稳定才能横向复制；
3. **加 die = 加 bank**（SID 并入 bank 地址高位，非 CS 式 rank），峰值带宽不变、row hit 率提升；
4. **HBM3 → HBM4 保持较强的 Controller architecture continuity**——可设计 parameterized / dual-generation controller：探测代际（ID/MR）→ 重映射通道/bank → 选时序档 → 按代际使能特性、电气取两代公约数 [INFERENCE——架构连续性而非 drop-in 兼容主张；引脚/电气细节以 JESD270-4 + 厂商应用笔记为准 ⚠️]；
5. I/O 电压开放给厂商、base die 转向先进逻辑工艺 [VENDOR]——为 MC/PHY 逻辑下沉 base die 提供电气条件 [INFERENCE]（趋势口径，非标准 HBM4 既成形态，见下 custom HBM 段）。

（HBM2→HBM3：本文无一手资料，不展开该代 Delta。）

**下一步趋势：MC/PHY 下沉与 D2D 抽象（custom HBM）** [VENDOR 趋势 + INFERENCE]：

- HBM4 把接口扩到 2048-bit 后，传统 host-side HBM MC/PHY 对 GPU 的 die area、shoreline、routing 和 I/O power 压力越来越大；与此同时 HBM4 的 Base Die 开始采用先进逻辑工艺 [VENDOR]，具备了承载复杂控制逻辑的条件。
- 因此 custom HBM 可以把 MC 和 memory-specific PHY/management **下沉到 Logic Base Die**，把 stack 内的超宽 TSV/HBM interface 局部化，GPU 只通过较抽象的 **D2D transaction link** 访问内存。代价：多一级 D2D protocol/latency、Base Die 功耗与热密度、更强的系统协同设计 [INFERENCE]。
- 架构意义：这是 Controller/PHY boundary 的"**第四级搬家**"（§7）——What/When 与 How-Electrically 的分界线从 on-chip DFI 移到 D2D link 上，调度状态（§7.2 七自由度）跟着进 memory stack。复杂度没有消失：杠杆换了，账单换了收款人（SoC 内 NoC/PHY 压力 ↔ D2D 延迟 + Base Die 热密度）。

## 9. Interview Review

> 正文是知识库，本章是**检验知识是否真正建立的出口**——所有重要正文主题至少映射一个 Q&A。六类：Foundation（9.1）/ Why（9.2）/ Cross-protocol（9.3）/ Architecture（9.4）/ Operational Scenario（9.5）/ Quantitative（9.6）。每题格式：Q →【30 秒】一句话结论+最短因果链 →（重点题）【2 分钟】四层因果链 →【Follow-up】2~4 追问。数字锚点与完整推导在正文对应章节，不重复。

### 9.1 Foundation Questions

**Q1：DRAM 读出要经过哪些物理步骤？**
【30 秒】位线预均衡到 VDD/2 → 行译码选中字线 → WL 升压到 VPP → 电荷共享（单元电容 vs 位线寄生 1:10~20 → 位线只摆 ~100mV）→ SA 正反馈放大到轨。tRCD 等的就是④→⑤。（§1.1）
【Follow-up】为什么必须升压到 VPP？位线为什么要先均衡？SA 为什么占阵列面积大头？

**Q2：tRCD / tRAS / tRP / tRC 各限制什么？**
【30 秒】tRCD=SA 建立到可安全列选通；tRASmin=修复驻留（回写 Cs）；tRP=关 WL + SA 复位 + 位线均衡三件事；tRC=完整生命周期（row 独占资源）。全部 ns 守恒（阵列物理决定），不可缩短只能隐藏。（§1.3）
【Follow-up】为什么 tRCDWR < tRCDRD？tRASmax 为什么现代标准删了？

**Q3：tWR 与 tRTP 为什么不对称？**
【30 秒】写是"覆盖"——写驱动要传播到 Cs（额外动作，tWR 长且链进 tRP）；读只是撤除放大器占用、回写已由 tRAS 驻留覆盖（tRTP 短）。（§1.4）
【Follow-up】提前 PRE 分别会丢什么？

**Q4：tRRD 与 tFAW 的区别？**
【30 秒】tRRD=激活"限速"（bank 间错峰、供电 di/dt）；tFAW=滚动窗口"限额"（最多 4 次激活，≈4×tRRD+ns 余量）；REFpb 也计入 tFAW 窗口。DDR5：tRRD_S=8nCK、tFAW(1K)=Max(32nCK,20~16ns)——页大小进激活预算。（§1.5/§2.3）
【Follow-up】为什么同 BG 的 tRRD_L 更长？IDD 测量模式怎么排 ACT？为什么 tFAW 必须是滚动窗口而不是分段窗口（防边界套利——8 个 ACT 挤跨窗边界）？droop 违约为什么是静默失败？

**Q5：BG 的 tCCD_S / tCCD_L 是什么物理区别？**
【30 秒】跨 BG=突发占用本身（各 BG 阵列侧独立，背靠背拼满 DQ）；同 BG=等内部阵列列周期（共享阵列通路）。DQ 引脚永远共享，BG 独立的是阵列侧资源。DDR5 tCCD_L 由 MR13 按速率档编程 8→16nCK——剪刀差的实证。（§2.4）
【Follow-up】为什么核心/接口频率剪刀差使 BG 必然出现？

**Q6：Refresh 的预算数学？**
【30 秒】85°C 保持 ~32ms、每行 8192 次 → 平均 tREFI=3.9µs；同 bank 最大间隔 9×tREFI；tRFCab 随密度 130→380ns（占空 3.3%→~10%）。（§4.1）
【Follow-up】温度 2x 生效时哪个 deadline 先收紧？不改用 REFsb/pb 细粒度的话 sustained 带宽掉多少？（§4.5）

**Q7：REFab / REFsb / REFpb 的粒度与选择逻辑？**
【30 秒】REFab=全 bank 一条命令（命令开销最小）；REFsb=各 BG 同号 bank（DDR5）；REFpb=单 bank（LPDDR5）。共同哲学：刷新从"周期性全局停机"重构为"可调度的后台工作"，REFab 留给深空闲/进 SR 前。（§4.2）
【Follow-up】为什么 HBM 刷新做到 PC 级、电源管理却只到通道级？（refresh/timing 分区服务于阵列管理；clock/power-gating 基础设施是通道共享资源，通道粒度降低 sequencing 与恢复复杂度 [INFERENCE]）

**Q8：Rank 的定义与代价？**
【30 秒】同一 CS 选通、同时响应命令的颗粒组；rank 间共享 CA 与 DQ（引脚不增）。代价=R2R 时序（ODT 切换/读写翻转/WCK 重同步）+ 3DS 错峰刷新（tRFC_dpr≈tRFC_slr/3 限峰值电流）。HBM 无 rank——SID 并入 bank 地址。（§2.2）
【Follow-up】为什么说 rank 与 HBM4 加 die 是同一件事？

**Q9：HBM Channel / PC / DWORD 三层分工？**
【30 秒】通道管命令接口与电源状态（独立 CA/CK，PD/SR 通道级）；PC 管刷新与时序分区（共享行列总线，REFab 带 PC 位）；DWORD 管训练修复（32-bit 切片，一对读写选通）。（§2.5）
【Follow-up】为什么电源管理不做到 PC 级？（clock/power 基础设施通道共享；通道粒度省 entry/exit sequencing 与恢复复杂度 [INFERENCE]）

**Q10：Prefetch 演进史与代价？**
【30 秒】8n（DDR4）→16n（DDR5）→24n/48n（LPDDR6）：核心频率平坦下提速率的唯一接口手段。收益=数据/命令开销比；代价=访问粒度↑（DDR5 靠拆子通道保 64B；LPDDR6 打 89% 折）+ 部分写更难。（§3.5）
【Follow-up】HBM 为什么停在 BL8？

**Q11：CK / DQS / WCK / RDQS 的分工？**
【30 秒】CK=命令域定时；DQS/WCK=数据选通（source-sync：谁发 data 谁发 strobe）；WCK 是 LPDDR 的数据钟（per-byte 门控）；RDQS 是 HBM/LPDDR6 的读选通。CKR= WCK:CK 频率比（4:1 覆盖 533~6400）。（§3.6）
【Follow-up】WCK 与 CK 异步带来什么训练义务？（WCK2CK Leveling）

**Q12：DM 与 DBI 的区别？**
【30 秒】DM=写掩码（控制哪些 byte 落盘）；DBI=动态反转省电（不改变语义）。DDR5 保 DM 删 DQ-DBI、另增 CAI（W11）；LPDDR5 DMI 一线兼职两者 + MASKED WRITE；LPDDR6 全删掩码只留反转；HBM 只有反转。（§3.9）
【Follow-up】为什么 LPDDR6 敢删？（速率越高 DRAM 内 RMW 越贵，责任上移控制器）

**Q13：三家供电轨一句话？**
【30 秒】HBM：core/I/O/Tx 分轨，HBM4 I/O 电压开放厂商；DDR5：VDD=VDDQ=1.1V+VPP，PMIC 上模组；LPDDR：越拆越细——VDD2C（接口 1.0V）/VDD2D（阵列 0.875V）/VDDQ 0.5V 强制分域。（§5.1）
【Follow-up】LPDDR 为什么反向于 HBM 越拆越细？（能效管理精度 vs PHY 工艺自由度）

**Q14：ODECC 与 side-band ECC 的分工？**
【30 秒】ODECC=片内 SEC（128+8），正常读写路径对系统透明、不占引脚，显著降低暴露到系统侧的阵列错误率以支撑高密度 die（ECS/诊断可补充部分遥测）；side-band=模组级 SECDED（32+8），覆盖链路+阵列全路径，控制器全责 scrub/日志。前者遥测盲区更大，后者兜底——纵深防御。（§4.9）
【Follow-up】HBM 的 RAS 信息怎么到控制器？（SEV 引脚随读带内上报）

### 9.2 Why Questions（核心因果链）

**W1：为什么 DDR5 要拆 Sub-channel？**（模板题）
【30 秒】预取 16n 决定 BL16；若保持 64-bit 通道，一命令=128B=2 条 cache line，过取一倍 → 拆 2×32-bit：32×16=64B 正对齐一条 cache line，同时命令并发 ×2。不是带宽翻倍——引脚不变 peak 不变，买的是粒度与并发。
【2 分钟】核心频率平坦（Physical）→ 预取 16n（Mechanism）→ 双实例状态表/checker/刷新错峰、DFI 双实例（Controller）→ 通道并发 ×2、随机负载利用率↑；代价=控制器状态 ×2（Tradeoff）。"sub-channel"是 DIMM 级组织、非 JEDEC 术语。（§2.5）
【Follow-up】1）CL 和子通道有关吗？2）ECC 模组为什么是 2×40-bit？3）这提高 peak 还是利用率？（§2.7 三分法）

**W2：为什么 HBM 行/列分总线？**
【30 秒】TSV 把增引脚边际成本降一个量级，每通道养得起两条专用总线；行命令（ACT/PRE）与列流（RD/WR）同窗口并行，行开销被列流掩盖——BL8 仍满带宽的基础（对冲 28.6:1 行开销）。例外：REFab 需垫 CNOP、tRFCab 期间通道冻结。（§3.1）
【Follow-up】为什么 tCCDS=2nCK 恰好等于 BL8 占用？REFab 为什么是例外？

**W3：为什么 ACT 编码往往比 PRE/NOP 复杂？**
【30 秒】ACT 要装下整条行地址——载荷最大（HBM ≈24 bit vs PRE 7 bit），所以最先变多拍（HBM 1.5 拍三沿锁存；DDR5 2T；LPDDR6 ACT-1/2 共 4 周期）。命令编码复杂度=载荷宽度的函数；ACT 复杂化是引脚复用的直接后果。（§3.3）
【Follow-up】HBM 为什么是 1.5 拍而不是 2 拍？（ceil(24/10)×半拍粒度，无对齐浪费）

**W4：为什么 tRASmax 在现代标准中被删除？**
【30 秒】现代五标准不再定义独立 tRASmax 符号（HBM3/4 另在 tRAS MAX 列保留 9×tREFI 实质上限，见 §1.3）。历史动机 ≈9×tREFI 防 open row 阻塞 REF；现代控制器自管 REF 发送（postpone/pull-in/per-bank 预算），标准无需再约束行开放时长——复杂度转移到控制器。9×tREFI 与现代 postpone 预算 9×tREFIe 数字同源。（§1.3）

**W5：为什么 refresh postpone 上限是 8+1（9×tREFI）？**
【30 秒】tREFI 是平均值承诺——单条可滑动，但保持时间硬要求（32ms/8192）必须封顶：LPDDR5 最多推迟 8 条第 9 条强制；HBM3 直文"两 REF 最大间隔 9×tREFI"。压缩侧还有 tRFC 下界、3DS 还有错峰电流约束——四层共同夹出可行域。（§4.4）
【Follow-up】为什么这条边界不可让步？（性能可协商、正确性不可协商）

**W6：为什么温度影响刷新速率？**
【30 秒】结泄漏 Arrhenius ~2×/10°C → 保持时间=Q/I 缩短。协议响应：DDR5 MR4 1x→2x（tREFI 减半）；LPDDR 另有 4x；HBM 走 TEMP/CATTRIP 引脚。控制器后果：unhideable bubble → sustained bandwidth 下降，与 DVFS 形成闭环。（§4.5）

**W7：为什么 Row Hammer 防护走向 per-bank / targeted / bounded？**
【30 秒】模型=ACTIVATE→RAA debt→RFM。全局刷新响应的带宽代价无界；定向化（HBM4 DRFMpb 以采样 row 为中心、BRC 限定覆盖范围）把带宽税压到最小。演进：RFM→ARFM 自适应→PRAC+ABO 显式退避——债粒度变细、背压显式化。（§4.7）
【Follow-up】单 bank 带宽税怎么算？（tRFCpb/(RAAIMT×tRC+tRFCpb)）

**W8：为什么 LPDDR 命令走低速 CK、数据走全速 WCK？**
【30 秒】CA 根数少（7/4 根）+ DDR 采样——低速 CK 引脚与 SI 压力小；数据要全速，per-byte WCK source-sync。CKR 频率比（4:1 覆盖 533~6400）让命令域时钟不必跟着数据速率翻。代价：WCK 与 CK 异步 → WCK2CK Leveling + 每次 DFS 重做。（§3.6）
【Follow-up】控制器要放几个弹性 FIFO？（CK/WCK/DFI 三域）

**W9：为什么 W→R 比 R→W 贵？**
【30 秒】R→W 只需方向翻转（SA 正常）+ 写数据滞后可利用（tRTW≥CL−CWL+BL/2）；W→R = 方向翻转 + 写覆盖传播/SA 稳定（同 BG tWTR_L=Max(16nCK,10ns) vs 跨 BG 2ns）。系统侧：攒写分组翻转进一步放大不对称。（§1.5/§3.8）

**W10：为什么 LPDDR6 删除 MASKED WRITE 和 DMI？**
【30 秒】MASKED WRITE 是 DRAM 内 RMW（同 BG tCCDMW=4×列周期=写吞吐 1/4）；速率翻倍后串行化不可接受 → 连 DMI 一起删，部分写责任交回控制器（RMW 或整突发重排）。变迁主线：速率越高，DRAM 内 RMW 越贵。（§3.9）

**W11：为什么 DDR5 删 DBI 留 DM？**
【30 秒】[FACT] DDR4 的 DM/DBI 共 pin、写路径互斥；DDR5 最终保 DM、删 DQ-DBI，同时新增 CAI，并强化 DQ 侧 DFE/DCA/training。[INFERENCE] 更合理的代际理解：不是 DBI 失去价值（HBM/LPDDR 仍保留），而是 SI/power optimization complexity 重新分配——从 DQ-DBI 转向"CA inversion + 更强 DQ link closure"（演进细节 §3.9 三层结构）。
【Follow-up】为什么 DDR4 能两者兼得？（共 pin 分时复用，代价是写路径互斥）为什么 HBM/LPDDR 仍保留 DBI？（超宽接口 SSO 收益大 / 能效优先）CAI 与 DBI 区别？（对象 CA 总线 vs DQ 总线，机制同族）（§3.9）

**W12：为什么训练不能一次终身有效？**
【30 秒】训练结果=特定频点/电压/温度的最佳点；PVT 漂移（温度泄漏/迁移率、电压 IR drop、老化 NBTI/HCI）让眼中心移走。对策=training set 多频点保存 + ZQ 后台重校 + interval oscillator 追踪 + 周期 retrain。（§6.8）

**W13：只做 delay 训练为什么不够、还要 Vref？**
【30 秒】delay 决定"何时采样"、Vref 决定"什么是 1"——只扫 delay 只保证水平 margin；Vref 偏移让眼垂直不对称收缩。完整做法=2D（voltage×timing）眼中心，工程上用多次一维 sweep 近似。（§6.4/§6.7）

**W14：为什么 HBM4 翻位宽而不是继续提速率？**
【30 秒】[INFERENCE] 中距离互连提速率的边际成本（均衡/训练/pJ/bit/良率）急剧上升；翻位宽把压力转移到封装布线/bump 密度，换时序裕量与能效（位宽路线 pJ/bit 更优）。实证：JEDEC 基线 8G 反而低于 3E 9.6G，带宽增长全靠位宽。（§3.10/§8.3）

**W15：为什么不能无限加 bank？**
【30 秒】四堵墙：① 供电（tRRD 限速+tFAW 限额——激活电流 di/dt）；② 面积布线（每 bank 一套译码/驱动/SA）；③ 刷新与激活抢 tRRD/tFAW 窗口（REFpb 速率∝bank 数）；④ IO 复用封顶（DQ 通路不随 bank 增长，收益止于 row hit 率）。（§2.3）

**W16：为什么 LPDDR6 把 VDD2 强制拆成两个域？**
【30 秒】接口域（VDD2C 1.0V）与阵列域（VDD2D 0.875V）的最优电压/负载/di/dt 特性不同——拆分后独立稳压、隔离噪声、CA 调频调压不扰动阵列裕量。代价：DVFS 变多轨编排 + "模式×电压×训练集"三维表。（§5.1/§5.4）

**W17：为什么 ZQ 要后台校准 + ZQ Stop？**
【30 秒】阻抗随 PVT 漂——ZQ 以外部 240Ω 基准校准驱动器/ODT；后台化不占 DQ 总线，完成后 ZQUF 置位、空闲时 ZQCal Latch 应用新码字；电压切换期间 MRW 设 ZQ Stop 暂停（切轨瞬间阻抗基准失效）。（§6.3）

**W18：read gate training 与 read eye training 为什么是两步？**
【30 秒】gate 解决"read strobe 何时到、何时开捕获窗"（RDQS 只在 burst 附近有效，早开放噪声、晚开丢数据）；eye 决定"在 UI 的哪里采样"。先 gate 后 eye，串行依赖。（§6.7）

**W19：进 Self-Refresh 后 postpone 的刷新债要还清吗？**
【30 秒】不要求——协议规定 SR 内 DRAM 自管刷新接管外部债（tCKSR 内自启动内部刷新）；LPDDR5 SR 期间刷新计时器 freeze-and-store、退出后 resume（债保持）；但 SRX↔SRE 之间必须 ≥1 条 extra refresh。（§5.2）

**W20：为什么 refresh 必须有不可让步的 critical 边界？**
【30 秒】债有两态：soft（窗口内可重排——QoS 决定时机）与 critical（逼近 9×tREFI 必须 dead line 执行）。性能让步可协商、数据丢失不可恢复——正确性约束不能被性能约束无限覆盖，这条边界是协议强加给控制器的正确性义务。（§4.3/§4.4）

**W21：上电初始化为什么是这个顺序？**
【30 秒】自举原则——每一步只用已验证的前置通路做判据：Power 稳 → reset 才可信；命令是第一个需要 clock 质量的消费者；初始 MR 在低频执行（UI 宽，未训练 CA 仍有 margin）→ "低频进/出、高频练"（MR↔CA 鸡蛋问题的解法：进训练模式本身要 MRW）→ ZQ 先于眼训练（阻抗未定则训出错误眼的中心）→ WCK2CK 先于 DQ → 读先于写（写训练靠读回比对，RX 未验证则 fail 无法归因）→ init_complete 前 AXI 不放行。full boot training 显著重于 training-set 恢复——多频点系统保存/恢复已训练 operating point，而非每次 DFS 全量重训。（§7.9/§6.4）
【Follow-up】1）clock 和 reset 谁先？2）DSM 与旧代 DPD 差别？3）为什么训练要"低频进出"？

**W22：为什么 LPDDR5/6 的 CA 敢用 DDR 双沿，而 DDR5 的 CA 反而 SDR + 2T？**
【30 秒】不是数据速率决定 CA 采样方式——是"命令/数据时钟是否分离 + 通道长度与负载"。LPDDR：命令走低速 CK（CKR 4:1/8:1，同数据速率下 CA 每 pin 速率约为 DDR5 的一半）+ 近端短互连 → CA UI 宽、margin 足，敢用双沿换引脚（7→4 根）；DDR5：CA 跑数据速率一半的高频 CK + DIMM 长距 fly-by 多负载 → 保 SI margin 用 SDR，2T 补 bit budget。核心公式 Pin × Edge × Cycle（§3.2）。
【Follow-up】CKR 和 DFI ratio 是一回事吗？（不是——协议侧 CK:WCK vs MC/PHY 数字边界，§7.4）（§3.2/§3.6）

**W23：DFE / DCA / Vref / ZQ 分别解决什么？**
【30 秒】对着 Toolbox 表答、不背 acronym：DFE→post-cursor ISI（用已判决 bit 抵消）；DCA→rise/fall 不对称的 duty 失真；Vref→判决阈值（Eye Height）；ZQ→驱动/端接阻抗（反射/振铃）；per-bit deskew→lane 偏斜（Eye Width）；CTLE→通道高频损耗。一句话收束：**每个机制对应一种 margin 被吃掉的方式**。（§6.3）
【Follow-up】为什么这些对 Controller 只是"训练窗口/完成失败/工作点变化"三件事？（§6.3/§7.6）

**W24：Equalization 对 Controller 有什么意义？**
【30 秒】EQ 是 PHY link-closure knob：Controller 不需要知道 tap/系数电路，只需知道——训练/retraining 什么时候占用链路（可用性窗口）、什么时候完成、是否失败（error 上报路径 §7.7），以及 operating-point 改变（切频/电压）是否需要重校。EQ 参数归属 PHY 域能力（总模型 §7.6）。（§6.3/§7.6）

**W25：为什么有 tRC 还需要独立检查 tRP？**
【30 秒】tRC=ACT→ACT、tRP=PRE→ACT——两条不同时间线。PRE 可能晚于 ACT+tRASmin 发出（等 tRTP/调度），此时下一次 ACT 紧贴 tRC 边界：tRC 已满足，但 PRE→ACT 的恢复（关 WL/复位 SA/位线均衡）未完成。checker = 两个独立比较：now−last_ACT ≥ tRC **AND** now−last_PRE ≥ tRP。
【Follow-up】tRCmin 与 tRASmin+tRPmin 什么关系？（≥，很多速度档取等号——表列值常直接相加）（§1.3）

**W26：HBM 到底有没有 DFS？**
【30 秒】**有频率切换能力、无 LPDDR 式 DFS 体系**：HBM3/4 支持在 Self-Refresh 中 halt/change external clock（SRE 后 tCKSRE、SRX 前 tCKSRX 稳定）[JEDEC]；但没有多 FSP 预存、非 SR 直切、快速 operating-point 切换。mental model：LPDDR DFS=运行中换挡；HBM=停机→SR→改钟→重启。owner 视角：进 SR 即把刷新移交给 DRAM。（§5.4）
【Follow-up】为什么 SR 内切钟安全？（DRAM 自管刷新、无外部命令依赖）LPDDR 为什么能非 SR 直切？（FSP 预存+债保留，§5.4）

### 9.3 Cross-protocol Questions

**C1：HBM PC、DDR5 Sub-channel、LPDDR6 SC 是一回事吗？**
【30 秒】不是。三判据：①独立 CA 域（主判据）；②独立时钟/电源域；③命令带宽是否共享。DDR5 子通道/LPDDR6 SC 三条全过=真通道；HBM PC 共享行列总线与 CK、PD/SR 通道级=管理分区（刷新/时序分区）而非命令分区。量化：HBM 18 pin 服务 2 PC vs DDR5 2×14 pin。（§2.6）
【Follow-up】"pseudo"省了什么、付出了什么？

**C2：三协议 training 为什么不能复用？**
【30 秒】根差异在回读通道：HBM 走 IEEE 1500 独立测试口（MISR 签名，不依赖功能 DQ）；DDR5 走数据总线（MPC→MR→MRR，需先打通 DQ）；LPDDR 走 CBT/DQ + interval oscillator。反馈通道不同 → 训练编排的 skeleton 可复用，具体序列/回读通道/pass-fail 机制必须协议化。（§6.9/§7.11）

**C3：同样带宽翻倍——加 pin / 加 rate / 加 channel 各把问题转移到哪里？**
【30 秒】加 rate → PHY/SI margin、均衡/训练、pJ/bit、良率；加 pin → 封装布线/bump 密度、PHY 面积功耗；加 channel → controller 状态/NoC/地址映射；加 burst → 粒度失配、部分写更难。HBM3→3E 走 rate、3E→4 走 pin；LPDDR6 是 rate+channel+burst 组合拳。（§3.10）

**C4："LPDDR5 是 DDR5 的移动精简版"——对吗？**
【30 秒】不对。阵列语义同源，但接口/命令/电源/训练四层各自**独立演进**：三时钟域+CKR vs 单 CK；7-bit DDR CA vs 14-bit 1T/2T；多轨 DVFS 族 vs 无 FSP 的平台配置定频；interval oscillator vs MPC/MRR。各有对方没有的东西（DDR5：ODECC 强制/双子通道/PMIC 模组化；LPDDR：DFS/SR/DSM 等细粒度低功耗态——DPD 仅为 LPDDR2/3 历史）——不存在谁是谁的子集。（§5.5/§8）

**C5：同样面对 Row Hammer，为什么解法粒度不同？**
【30 秒】粒度随"带宽代价有界"的需求演进：HBM3 RAA+ARFM（计数+自适应）→ DDR5 RFM/DRFM 信用制 → HBM4 DRFMpb+BRC（定向+有界覆盖）→ LPDDR6 PRAC+ABO（上报风险 row+显式退避）。共同骨架：activation 被计数/风险被显式化 → 阈值后 targeted maintenance（计数位置与反馈通道随协议不同）；粒度越细背压越显式。（§4.7）

**C6：同样面对 refresh stall，谁更依赖 fine-grain refresh？**
【30 秒】LPDDR（单 bank REFpb）>DDR5（BG 级 REFsb）>HBM（PC 级粒度+通道多可错峰）。根源：LPDDR 通道窄、延迟敏感（手机 QoS）；DDR5 吞吐敏感、批量刷新省命令带宽；HBM 靠通道并行天然错峰。（§4.2）

**C7：三协议功耗管理的复杂度与哲学差异？**
【30 秒】按优化目标比、不按单一排名 [INFERENCE]：LPDDR=energy proportionality（PD/SR/DSM 多级低功耗态+DVFS 族+温度倍率——管理面最复杂）；DDR5=capacity/RAS/platform balance（频率基本固定，复杂在双子通道错峰/RFM 配额/PMIC 模组化）；HBM=sustained bandwidth/energy-per-bit（activity 调度+通道级 PD/SR+热节流+低摆幅宽接口——**切频能力存在但走 SR 路线、非核心功耗策略**，见 W26）。（§5.5/§5.4）

**C8：HBM 带宽这么高，为什么替代不了 DDR5 当主存？**
【30 秒】① 容量：HBM 单封装 ≤64GB 且设计期锁死，服务器要 TB 级插槽扩展；② 成本：TSV+键合+中介层良率，$/GB 远高；③ 生态：RCD/DB/PMIC/RAS/热插拔成熟度。正确关系=层级化组合：HBM 作带宽引擎/末级缓存，DDR5 作容量底座。（§5.5/§2.8）

**C9：HBM 能用超宽接口，DDR 为什么不能？**
【30 秒】互连距离决定可行的 rate×width 乘积：HBM 走中介层（mm 级典型）——超宽（2048-bit）、相对低 per-pin rate 可行；DDR 走 PCB 十 cm 级——宽总线的 skew 匹配组、SSO、走线成本超线性，只能窄而快+均衡。（§3.10/§3.10）

**C10：三协议命令带宽供给差一个数量级，各怎么缓解？**
【30 秒】供给：HBM 18 pin 双槽/拍 > DDR5 2×14 CA（2T）> LPDDR6 4 CA（2CK/ACT 4CK）。缓解：请求合并/大粒度、page hit（放大率 1+2/N）、独立 CA 子通道、auto-precharge（省 PRE 但牺牲 row hit）。（§3.4）

**C11：LPDDR 强调 DVFS、HBM 倾向固定高带宽工作点——为什么？**
【30 秒】负载模型不同 [INFERENCE]：手机负载突发、空闲多——多频点电源管理收益大（VDD2 分域+DVFS 族+training set）；AI 负载持续满带宽——降频收益小，省电靠 activity 调度降动态功耗 + 通道级低功耗态 + 热节流。切频机制也不同：LPDDR 有三组 FSP 预存可直切（保刷新债）；HBM/DDR 借 SR 移交 owner。（§5.4/§5.5）

**C12：同样翻倍带宽，HBM4 为什么不复制 scheduler 就完事？**
【30 秒】实例层可以横向复制（ch-2PC 同构）；但不复制的全局层是共享瓶颈：地址映射防热点（channel-first striping）、跨通道 QoS/功耗预算、NoC 容量——映射失效=单通道热点吃掉翻倍带宽。再往上是 PHY/封装功耗。（§7.2）

**C13：HBM 32-bit×BL8=32B 为什么重要？**
【30 秒】32B 是 HBM PC 的 natural burst granularity，与 GPU memory system 的 sector/transaction 粒度高度契合（warp 访问 sector 化后按 32B 对齐）——"GPU 友好"的量化理由。口径注意：可以论证**契合**，不能声称 JEDEC"因为 GPU 32B transaction 才这么设计"（动机归因只能是 [INFERENCE]）。
【Follow-up】DDR5 子通道 32×BL16=64B 对应什么？（CPU cache line，§9.6 Q2）（§2.5/§3.5）

**C14：CPU 64B cache line 与 GPU 128B warp footprint / 32B sector 怎么理解？**
【30 秒】CPU：64B coherence/cache line——DDR5 32-bit SC×BL16=64B 正好一条。GPU：32 threads×4B=128B warp footprint，但访存按 sector 切成 4×32B——HBM PC 32-bit×BL8=32B 正好一个 sector。粒度匹配决定过取/欠取与命令开销；**避免简单说"GPU cache line=128B"**（coherence 粒度与突发粒度是两件事）。（§3.5）

### 9.4 Architecture Follow-up Questions

**A1：DDR4→DDR5，控制器最大的架构变化是什么？**
【30 秒】不是速率，是三件结构性的事：① 子通道化（双实例命令/训练/刷新/DFI）；② ODECC 强制（RAS 分层重构+遥测盲区）；③ PMIC 上移模组（电源管理责任迁移）。次级：1T/2T、FGR/REFsb、RFM/DRFM/ARFM、DFE。（§8.1）

**A2：HBM3 → HBM4 架构连续性——双代际控制器要做什么？**
【30 秒】① 枚举探测（ID/MR+IEEE 1500 WDR 识别代际/die 数/SID/密度）；② 配置切换（16ch vs 32ch 通道映射、bank 数 16~64/PC、时序档）；③ 电气取最低公约数（I/O 电压厂商自定）；④ 特性位探测（ECS/DRFM/BRC 按代际使能）。本质="协议骨架不变、代际参数可枚举"。（§8.3）
【Follow-up】1）为什么说这是 architecture continuity 而非 drop-in 兼容？2）混合部署时“电气取公约数”指什么？

**A3：通道继续加，瓶颈何时从 DRAM 转到 NoC / Controller / PHY？**
【30 秒】分层判据按序转移：① DRAM（带宽<<peak、命令槽等时序）→ ② Controller 全局层（通道 ready 却无命令/部分饥饿——映射与 QoS 不随实例复制）→ ③ NoC（crossbar 端口/路由拥塞）→ ④ PHY/封装（功耗随总引脚线性）。负载类型决定卡层：随机多核先 NoC/QoS，row-buffer 型先 DRAM 时序。（§7.2）

**A4：统一多协议控制器，什么能复用、什么必须分叉？**
【30 秒】[PROJECT 落地口径] 可复用：事务/QoS/防饥饿/地址 hash 框架、性能计数/错误注入/寄存器 infra、参数化状态表与 checker 骨架。必须分叉：命令编码器（格式正交）、训练编排（skeleton 可复用，序列/回读通道/pass-fail 必须协议化）、刷新管理（RFM 族/REF 族策略与接口都不同）、低功耗/切频序列（命令式 vs CKE vs FSP）、DFI 参数化。落地形态=共享前端+每协议独立 MC core+统一 infra。（§7.11）

**A5：bank 数增加，控制器的成本怎么涨？**
【30 秒】四部件线性增长：状态机/计时器（open row+tRCD/tRAS/tRP/tRC+刷新债+RAA 计数）；刷新债预算随 bank 数收紧（冲刷时间∝banknum×tRFCpb）；checker 层级加深；发射通路匹配表加宽。HBM4 64PC×64bank 是极端值。（§7.2）

**A6：时序都改不了，Scheduler 还能优化什么？**
【30 秒】七个自由度：聚合重排、batch 读写切换、错峰 REF、postpone/pull-in 预算、BG/通道交织映射、open-page/AP 策略、QoS 分配——本质=在不可改的时序墙里重排时间线，把不可避免的开销移到伤害最小的位置+用映射预防发生。（§7.2）

**A7：切频时刷新债怎么办？**
【30 秒】REF owner 框架：LPDDR 非 SR 直切——owner 始终在控制器、postpone 债保留不清（六条件含"Refresh requirements apply during clock frequency change"——刷新义务时间域连续）；HBM/DDR 借 SR——owner 移交 DRAM 自管（tCKSR 内自刷新），退出后恢复。切频前确认 banks idle 恰好等价于债无冲突。（§5.4）

**A8：DFI 为什么存在？读数据为什么是 rolling 的？**
【30 秒】DFI 把 What/When（Controller）与 How Electrically（PHY）解耦为标准契约（独立时钟域/工艺/训练状态机）。读 rolling：PHY 被动捕获、突发起始相位由 RL 决定、无法对齐 w0 → 环绕推进无缝拼接；MC 侧 rotator 重排。写不 rolling（MC 主动投递、升序对齐）。rolling 只在读路径存在。（§7.3/§7.5）

**A9：训练责任在 Controller / PHY / DRAM 怎么分？**
【30 秒】总模型：**训练算法可住在 MC 或 PHY，物理调节永远属于 PHY 域能力**。MC-controlled 模式="Core 发命令，PHY 调延迟，DRAM 报结果"（MC 发起/排序/判定，PHY 调 delay/Vref/阻抗，DRAM 出反馈通道 + 存 Vref FSP 寄存器）；PHY-master 模式=PHY 接管命令总线自主训练（先 QOS Disconnect 断流）。PhyRdLat/PhyWrLat 由 PHY 告知 Controller。
【Follow-up】两模式怎么选？（MC 编排逻辑投入 vs 断流窗口+所有权交接代价的权衡）（§7.6/§7.11）

**A10：最坏情况 Row Hammer 带宽税怎么算？**
【30 秒】协议给出 RFM demand 与 unavailable duty；**真带宽损失 = 不可被其他 bank 服务隐藏的 bubble（负载相关）**——别把 unavailable duty 直接当带宽损失报。单 bank 公式与 aggregate 触顶约束见 §9.6 Q6。（§4.7）

**A11：DFI 1:4 ratio 意味着什么？MC 为什么能降频、代价是什么？**
【30 秒】f_MC=f_CK/4、Width_DFI=2×4×DQ（带宽守恒：256-bit@800MHz=32-bit@6400MT/s）——调度逻辑不必追 DRAM CK 收敛时序。代价：总线加宽/phase 化、读侧 PhyRdLat+rolling rotator、写侧 contract 双方一致编程；命令槽不紧张的根源是 DRAM 自然命令率 sub-CK（tCCD_S=8nCK）。（§7.5/§7.4）
【Follow-up】1）tphy_rdlat 配错 1 cycle 的表现？（§9.5 O9）2）写数据为什么必须提前、晚到会怎样（与读“事后对齐”的区别，§9.5 O8）？3）DFS 时 PhyRdLat 谁更新、何时生效？

**A12：训练失败时，谁发现、谁上报、MC 停不停 traffic？**
【30 秒】DFI 只定握手与逃生、不定训练算法：boot 走 dfi_init_start/complete 握手；PHY Master 模式接管 DRAM 命令总线前必须先 QOS Disconnect 断流（MC traffic 必停）；失败上报有协议——error_pN、PHY-initiated Error Disconnect、dfi_alert_n 透传、Error Codes 可读；retry/降频/safe-mode 策略非标准 [PROJECT]——典型分层：HW 服从断流 + 存寄存器（带中断），SW 做策略，超时由 PHY 监测。（§7.6/§7.7）
【Follow-up】1）MC-controlled 与 PHY-master 两模式怎么选、各自的代价？2）error_pN 与 dfi_alert_n 的语义差别？3）DFI 无标准 timeout，boot 挂死风险怎么兜底？

**A13：进低功耗/切频前，drain 到哪一层才算安全静止？**
【30 秒】四层判据：L1 系统级（AXI req/resp 收敛）→ L2 引擎级（CAM 空、backpressure 生效）→ L3 接口级（DFI 三流全空：命令/写数据/读数据——ctrlupd 的判据线）→ L4 DRAM 级（尾部时序 tWR/tRTP + banks 前置：SR 全 precharged、PDE 允许 open row）。写必须推到 DRAM 完成点（AXI 已接受不可撤销）[PROJECT：写 completion 口径]；读可收完或 SLVERR、不可静默丢 [PROJECT：读响应策略]；drain 期间刷新债照走——**PD 驻留被债封顶；SR/DSM 驻留不受外部刷新债约束**（实际驻留仍受平台/温度限制）。（§7.8/§5.2）
【Follow-up】1）ctrlupd 为什么停在 L3 就够？2）排空最坏时间怎么估（max burst→命令数×服务时间+尾部时序）？3）DFS 在三轴（接口/DRAM 前置/队列）上怎么放？

### 9.5 Operational Scenario Questions

> 这一节检验"知识能不能变成操作判断"——每题先给结论，再给判据出处。

**O1：进入 Self-Refresh 前到底要 drain 到哪？**
【30 秒】到 L4 重前置：AXI 收敛（L1）+ 引擎静止（L2）+ DFI 三流空（L3）+ **全 bank precharged、tRP 满足、尾部时序走完**（L4）——SRE 的硬前置是"全 bank precharged"（open row 干扰自刷新）。对比：PDE 只需轻前置（允许 open row，仅要求读写突发完成）。（§7.8/§5.2）

**O2：PHY 发起 training/update 时，Controller queue 留不留？**
【30 秒】分两层答。**协议层 [DFI]**：QOS Disconnect 断流 + DFI 所有权移交即可——DFI 只要求 handoff 前停止会继续进入 PHY/DRAM 的 traffic，完成/错误经握手返回。**项目层 [PROJECT]**：Controller 内部 queue 是否保留、host 是否继续 admission、何时 backpressure 属实现策略——典型短 PHY update 保留排队请求无缝续跑；较长的全局状态切换（进 SR/DSM）通常 drain/backpressure。（§7.7/§7.8）

**O3：DFS 时 refresh debt 怎么处理？**
【30 秒】REF owner 框架（完整口径见 §9.4 A7）：LPDDR 非 SR 直切——owner 不移交、债原样保留（刷新义务时间域连续）；HBM/DDR 借 SR——owner 移交 DRAM 自管、退出 resume。（§5.4）

**O4：温度突然越档、refresh multiplier 2x 生效，Controller 如何保证 deadline？**
【30 秒】tREFI 减半 = 债累积率翻倍：调度器按新速率重排 REF 插空（错峰、REFpb 化），critical 边界（同 bank 最大 9×tREFI）不可让步——正确性优先于 QoS；代价是 drain/低功耗窗口撞刷新概率上升（§4.5 量化），极端时牺牲带宽。（§4.5/§7.2.4）

**O5：最后一条 WR 已从 DFI 发出，是否已经可以进入 SR？**
【30 秒】不——DFI 发出 ≠ DRAM 完成。写要推到 **DRAM 完成点**：WR 命令 + CWL + 突发 + tWR 全部走完，且全 bank precharge + tRP 满足后才能 SRE。（§7.8）

**O6：CAM empty 是否等于 DRAM idle？**
【30 秒】不等——CAM 空只是 L2 引擎级静止；L4 协议级还差尾部时序（末写 +tWR、末读 +tRTP）与目标 bank 态。**CAM empty ≠ DRAM quiescent** 是 drain 判据的核心反例。（§7.8）

**O7：PHY training fail，谁检测、谁停 traffic、谁决定 retry/降频？**
【30 秒】PHY 检测（物理层 pass/fail）；断流由协议保证（QOS/Error Disconnect——MC HW 服从）；失败经 error_pN / dfi_alert_n / Error Codes 上报；retry/降频/safe-mode 属项目策略 [PROJECT]（分层模型同 §9.4 A12：HW 断流/存寄存器，SW 判 fatal）。（§7.7）

**O8：读数据为什么可以"晚到"，写数据为什么绝不能"晚到"？**
【30 秒】写：MC/PHY 是 timing producer，DRAM 在 deadline（WR+CWL）采样——晚到 = 采样错数据，协议无 retry、不可恢复。读：PHY 是 timing receiver——physical arrival phase 先被捕获，经 FIFO/deserialize/phase-align 事后对齐，再按**已配置的 PhyRdLat contract** 交给 MC；“可吸收”指 arrival phase 在 PHY 内部被对齐，**不等于可以任意晚——超出已配置 capture/latency contract 仍是错误**（PhyRdLat 是 setpoint 配置常数，不随训练漂移）。deadline-driven vs arrival-driven（capture-then-align）。（§7.5）

**O9：DFI PhyRdLat 配错一个 cycle 会发生什么？**
【30 秒】读数据在错误的 DFI cycle 被采样——整 burst 错位、rolling 起点也错 → 读数据 corrupt 且**稳定可复现**（PhyRdLat 是确定性常数、不随训练变）——这正是它按 (setpoint × ratio) 配置、切频必须同步换值的原因。（§7.4/§7.5）

**O10：切频后哪些表必须换、哪些东西不能变？**
【30 秒】必换三套表：① DRAM 侧 MR/timing 档（FSP 选组）；② PHY operating-point / training set / ZQ 阻抗码字；③ DFI latency / ratio / phase（tphy_rdlat/wrlat）。不能变：拓扑（地址映射/channel/bank）、数据内容、协议语义——**语义连续正是队列可保留的前提**。（§7.10）

### 9.6 Quantitative / Whiteboard Questions

**Q1：HBM 一个 PC 的 natural burst 粒度？** 32-bit × BL8 = **32B**——与 GPU sector 对齐（§2.5/§3.5、§9.3 C13）。

**Q2：DDR5 子通道一条读命令搬多少？** 32-bit × BL16 = **64B**——正对齐一条 CPU cache line（§3.5）。

**Q3：Refresh duty 怎么估？** tRFC / tREFI：2Gb 1x ≈3.3% → 2x ≈6.7% → 4x ≈13.4%；tRFCab 130→380ns 随密度（§4.1/Appendix A）。

**Q4：1TB/s @ 32B 粒度 = 多少 transactions/s？** 10^12 / 32 = **31.25G/s**——理解命令带宽压力与请求聚合的必要性（§3.4）。

**Q5：DFI 1:4 带宽守恒算例？** 256-bit @ 800MHz = 32-bit @ 6400 MT/s——rate × width 守恒（§7.4）。

**Q6：Row Hammer 最坏带宽税？** 单 bank：税 = tRFCpb / (RAAIMT × tRC + tRFCpb)，所需 RFM 速率 = 1/(RAAIMT × tRC)；RFMpb 目标 bank 占 tRFCpb、异 bank 按 tRREFD 穿插；多 bank aggregate 触顶受 tRRD_S/tFAW 组合约束。诚实边界：这是 unavailable duty，真损失 = 不可被其他 bank 隐藏的 bubble（§4.7）。

**Q7：tFAW 滚动窗口的"边界套利"示意？** 分段窗口下 8 个 ACT 可挤在跨窗边界连续发（每窗各 4 个）；滚动窗口使**任意连续 tFAW 内 ≤4 ACT**——无套利空间（§1.5）。

**Q8：LPDDR6 ACT 命令 payload 预算？** pins × edges × cycles：4 pin × 2 edge × 4 CK = 32 slot，扣 opcode/标记后装行地址——所以 ACT 拆两条命令共 4 周期（§3.2/§3.3）。

## 10. 3D Memory Outlook

> 本章只汇总前文已建立的结论，作为 forward-looking architecture conclusion；不展开 PIM / Near-Memory Compute 实现与制造工艺。

**互连距离 → 超宽接口的可行性**（§3.10 互连阶梯表）：

```text
TSV / Interposer / Hybrid Bonding（几十~几百 µm → µm 级）
    ↓ 互连距离缩短
pin density ↑ / energy-per-bit ↓（低摆幅可行）
    ↓
超宽接口的 SI / 封装代价可承受
    ↓
HBM bandwidth scaling = 位宽杠杆（§3.10：3E→4 靠 2048-bit 而非提速率）
```

**HBM4 之后的下一跳：MC / PHY 下沉**（§8.3 趋势段）：

```text
HBM4 2048-bit
    ↓ host-side PHY / die area / shoreline / routing / I/O power 压力 [INFERENCE]
advanced logic base die [VENDOR]
    ↓
custom HBM：MC / memory-specific PHY / management 下沉 Base Die，
stack 内局部化超宽接口
    ↓
GPU 经抽象 D2D transaction link 访存 —— Controller/PHY boundary 的下一跳（§7）
```

代价与边界：多一跳 D2D protocol/latency、Base Die 功耗与热密度（热是 3D 的第一约束候选，§4.5）、更强的系统协同设计 [INFERENCE]。

---

## Appendix A. Parameter Quick Reference

> 只服务查数，不解释 Why（解释见正文对应章节）。

**A.1 带宽与速率**

| 代际 | 标准 | 接口位宽 | 速率 | 带宽（64-bit 等效 / 单 stack） | 备注 |
|---|---|---|---|---|---|
| HBM3 | JESD238 | 1024-bit（16ch×64） | 6.4 Gbps | 819.2 GB/s | 16/24 GB |
| HBM3E | JESD238A | 1024-bit | 9.6 Gbps | 1228.8 GB/s | 24/36/48 GB |
| HBM4 | JESD270-4 | 2048-bit（32ch×64） | 8G 基线→12.8G（路线 16G） | 2.048→3.3 TB/s | ≤64 GB；产品 3.3TB/s≈12.8G [VENDOR] |
| DDR5 | JESD79-5 系列 | 64-bit/DIMM（2×32 SC） | 4.0~8.8 GT/s | 32~70.4 GB/s | BL16 |
| LPDDR5 | JESD209-5 | 多×16-bit | 3200~6400 | 25.6~51.2 GB/s | |
| LPDDR5X/5T | JESD209-5B/-5C | 同上 | 8533/9600/10700 | 68.3/76.8/85.6 GB/s | |
| LPDDR6 | JESD209-6 | x24（2×SC×12-DQ） | 10.6~14.4 Gbps | 84.8~115.2（64-bit 等效）/169.6~230.4（x128 折算）⚠️ | 有效 ×89%（288=256+32）；带宽为等效折算口径，非单封装物理组织值 |

**A.2 行时序锚点**（详见 §1.6 表）

| 参数 | LPDDR5 | DDR5-8400 | HBM4-12000 |
|---|---|---|---|
| tRCD | Max(18ns,2nCK) | 17.5ns | tRCDRD 57CK / tRCDWR 43CK |
| tRP | Max(18ns,2nCK) | 17.5ns | 45CK |
| tRAS | Max(42ns,3nCK) | 32ns | 90CK |
| 行开销折算 | ≈7.2 个 BL16 | ≈9.2 个 BL16 | ≈28.6 个 BL8 |

**A.3 激活/共享资源时序锚点**（详见 §1.5/§2.4）

- DDR5：tRRD_S=8nCK、tRRD_L=Max(8nCK,5ns)、tFAW(1K)=Max(32nCK,20~16ns)、tFAW(2K)=Max(40nCK,25~20ns)、tCCD_S=8nCK、tCCD_L=8~16nCK（MR13 编程）、同 BG W2W=Max(32nCK,20ns)、tWTR_L=Max(16nCK,10ns)/tWTR_S=Max(4nCK,2~2.5ns)。
- LPDDR5（8B 模式）：tRRD=Max(10ns,2nCK)、tFAW=40ns；BG 模式 Table 330：跨 BG BL/n_min=2tCK、同 BG BL/n_max=4tCK、tCCDMW=4×BL/n。
- HBM3：tCCDS=2nCK（=4WCK=BL8）、tCCDL=Max(4, 2.5ns/tCK)；tRRD/tFAW/RAA 同表（JESD238 p175）。
- HBM4（JESD270-4A Table 108）：tCCDS=2nCK、tCCDL=Max(4nCK, 2.5ns/tCK)、tPPD=2nCK、tCCDR=tCCDS+1~2nCK（厂商自定，跨 SID 无缝连读）；tRC/tRAS/tRCD/tRP/tRRD/tFAW/tWTR 表列留白（厂商 datasheet）；tRAS MAX=9×tREFI（§1.3）。
- 刷新：tREFW=32ms、R=8192、tREFI=3.906µs、tREFIpb=488ns、tRFCab=130~380ns、tRFCpb=60~190ns（随密度，LPDDR5 Table 235）；postpone/pull-in ±9×tREFIe。

**A.4 电压域**（详见 §5.1 表）——HBM3 1.1/1.1/0.4V；HBM4 1.05V+厂商自定 I/O；DDR5 1.1V+VPP ⚠️；LPDDR5 VDD1/VDD2H/VDD2L/VDDQ；LPDDR6 VDD2C 1.0/VDD2D 0.875/VDDQ 0.5V。

## Appendix B. Glossary

| 术语 | 一句话定义 |
|---|---|
| Channel | 拥有独立 CA/CK/刷新状态的命令域（判据见 §2.6） |
| Rank | 同一 CS 选通、共享 CA/DQ 分时使用的颗粒组（容量维度） |
| SID | Stack/Die ID——HBM4 中并入 bank 地址高位（非 CS 式选择子） |
| Bank | 最小并发粒度：独立 WL/BL/SA 阵列+行列译码 |
| Bank Group | 阵列侧独立数据路径的物理分组——组间流水化（tCCD_S/L） |
| Sub-Channel（SC） | DDR5 DIMM 的独立 32/40-bit 子通道；LPDDR6 自带 CS/CA/CK 的子通道 |
| Pseudo-Channel（PC） | HBM 通道内的刷新/时序分区（共享行列命令总线，电源状态通道级） |
| DWORD | HBM 32-bit 数据切片（训练/修复粒度，每 PC 一个） |
| SEV | HBM 读突发随附的错误严重度位（per-PC SEV[1:0]） |
| BL / BL/n | Burst Length；LPDDR6 有效突发长度（Effective Burst Length） |
| Prefetch (8n/16n/24n) | 内部一次读出的宽度与 I/O 拍数之比——核心频率平坦下提速率的手段 |
| UI | Unit Interval：一个数据 bit 的时间窗 |
| Eye | 所有 UI 波形折叠叠加——Width=时间裕量、Height=电压裕量 |
| SI | Signal Integrity，信号完整性：研究"这个 0/1 经过真实互连后还能不能被可靠判出来" |
| Jitter (RJ/DJ) | 随机抖动（高斯无界）/ 确定抖动（DCD/PJ/DDJ/BUJ，有界） |
| Skew | DQ-to-DQ（组内到达差）/ DQ-to-DQS（相对选通）两类 |
| ISI | 码间干扰：反射振铃/衰减污染后续 bit 判决窗 |
| SSN | 同时翻转噪声：di/dt×电源路径电感 |
| ODT | 片内端接（档位经 MR 编程，ZQ 校准） |
| DM / DBI / DMI | 写掩码 / 动态反转 / LPDDR5 兼职两者的引脚（LPDDR6 已删） |
| CAI | Command/Address Inversion，命令/地址总线反转：减少不利 bit pattern、降低切换噪声/供电扰动 |
| CKR | LPDDR 的 WCK:CK 频率比（2:1/4:1） |
| WCK2CK Leveling | WCK 与 CK 的同步 FIFO 指针对齐训练 |
| CBT | Command Bus Training（LPDDR 命令总线训练） |
| Interval Oscillator | LPDDR 片内振荡器，用于读均衡训练（标准名 tWCK2DQ Interval Oscillator） |
| MISR | 多输入签名寄存器；HBM 训练经 IEEE 1500 回读 AWORD/DWORD 签名 |
| FSP | Frequency Set Point（LPDDR 频点寄存器组；LPDDR5 起三组 FSP0/1/2，存各频点 MR/Vref 配置） |
| Training set | 多频点保存的训练参数集（DFS 后恢复） |
| REFab/REFsb/REFpb | 全 bank / 同 BG 同号 bank / 单 bank 刷新 |
| RFM/ARFM/DRFM/PRAC/ABO | 刷新管理族（§4.7） |
| RAA / RAAIMT | Row Activate Advisory 计数 / 其阈值（厂商离散档位） |
| ECS | 自动错误检查与擦洗 |
| ODECC | DDR5 片上 ECC（128 数据+8 校验 SEC） |
| BRC / tDRFM | HBM4 Bounded Refresh Configuration 及其时序 |
| DVFSC/Q/H/L/B | LPDDR6 DVFS 模式族（§5.4） |
| DCA | Duty Cycle Adjustment，占空比校正：把 CK/DQS/DQ 相关波形因上升沿/下降沿不对称造成的 50% duty distortion 修回来 |
| DFE | Decision Feedback Equalization，判决反馈均衡：用已判决过的 bit 抵消前面 bit 对当前 bit 的 ISI |
| DFI | DDR PHY Interface——Controller/PHY 标准契约 |
| tRASmax | 历史时序参数（现代五标准不再定义独立符号；HBM 以 tRAS MAX 列保留 9×tREFI 实质上限，§1.3） |

## Appendix C. JEDEC / DFI Sources

| 标准 | 内容 | 日期/备注 |
|---|---|---|
| JESD238 | HBM3 DRAM | 2022.01 |
| JESD238A | HBM3E | 9.6 Gbps |
| JESD270-4 | HBM4 DRAM | 2025.04；32ch/2048-bit；DRFM/BRC/SEV/ECS；一手复核采用修订版 JESD270-4A（2025.11，AC 表 4.8~8.0G 9 档） |
| JESD79-5 / -5A / -5B / -5C | DDR5 SDRAM | 2020.07 起；速率档至 8800 |
| JESD209-5 / -5B / -5C | LPDDR5 / LPDDR5X | 2019.02 起；8533/9600/10700 档 |
| JESD209-6 | LPDDR6 | 2025.07.09；x24/x12 效率模式；PRAC+ABO；DVFS 族 |
| DDR PHY Interface（DFI）v5.0 / v5.1 / v5.2 | MC-PHY 接口 | v5.0 起全面转向 PHY-independent training mode [VENDOR：ddr-phy.org]；v5.1 2021-05-21（163 页）/ v5.2（216 页，LPDDR6 配套；继续服务前代协议系统） |
| DFI 6.0 | MC-PHY 接口 | 2026-05-26 发布：首次官方支持 HBM + 最新 LPDDR/DDR；移除 legacy 协议支持；增强 power-saving 与 fault identification/recovery [VENDOR：ddr-phy.org 官方发布] |

**本仓库协议参考文档**（相对 `univista\protocol\` 目录）：

- `HBM\eetop.cn_JESD238_HBM3.pdf`、`HBM\JESD270-4.pdf`
- `DDR\JESD79-5B_v1-2_DDR5_SDRAM.pdf`、`DDR\JESD209-5B.pdf`
- `LPDDR6\JESD209-6_LPDDR6 Standard.pdf`
- `LPDDR6\eetop.cn_DDR_PHY_Interface_Specification_v5_2.pdf`（DFI；另备 DFI 5.1 PDF）

---

> **冻结版本（Frozen Review Version）**：本文档为稳定复习底稿。仅以下三类事件触发修改：
> 1. 新代际协议 / DFI 标准正式公开；
> 2. 面试或实际设计暴露出当前知识模型的真实缺口；
> 3. 获得能够解决正文现存 ⚠️ 的一手 JEDEC / DFI / vendor 资料。
