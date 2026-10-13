# Transformer → HBM：HBM Controller Engineer 的 AI Workload Memory System Model

> **文档身份**：HBM Controller / Memory System 工程师的 AI workload memory system model（技术笔记；不是教材，不是论文，不是百科）。
>
> **本文回答三个问题**：
> 1. 一个 LLM workload 为什么产生这样的 HBM request stream？
> 2. 哪些优化改变了 request stream？
> 3. Memory Controller 有哪些机制决定最终 HBM efficiency？

---

## 0. 文档定位

### 0.1 这是什么 / 这不是什么

* **不是** Transformer 教材：算法只学到能解释 memory 行为为止（不覆盖 training / optimizer / loss / 收敛理论）；
* **不是** kernel optimization 教程：kernel 只作为 traffic 的来源被描述；
* **是** AI workload → memory system 的翻译层：回答“Transformer workload 为什么产生这样的 memory traffic，这些 traffic 如何最终影响 HBM controller”。

### 0.2 唯一主线（authoritative chain）

```text
Model
↓
Operator
↓
Tensor
↓
Shape / Precision
↓
Compute
↓
Logical Data Movement
↓
Tile / Layout
↓
Cache / Memory Hierarchy
↓
NoC / VM / Coherency
↓
MC-visible Request Stream
↓
Memory Controller
↓
HBM Transaction
↓
Performance
```

任何新增 / 保留内容必须回答：**它改变了这条链中的哪一环？** 无法影响 Tensor / Data Movement / Request Stream / MC behavior / HBM Performance 的知识，降低优先级或移入附录。

### 0.3 全文核心原则

```text
Logical Bytes
≠ MC-visible Request Bytes
≠ Physical HBM Transaction Bytes
```

`HBM Traffic` 一类 DRAM 层量词只允许出现在 MC 之后；MC 之前的输入一律称 `MC-visible Request Stream`。

### 0.4 分析方法

* **Feature / optimization 统一五段模板**（§4 全部按此展开）：

```text
1. 解决什么问题               （compute / capacity / bandwidth / locality / request pattern？）
2. 改变哪个 memory 行为
3. Tensor / Data Movement 如何变化
4. Request Stream 如何变化
5. HBM Controller 看到什么变化
```

* **知识优先级**：概念理解 > Memory 影响 > Controller 视角 > 数量级验证；计算推导统一存放附录 A.5，正文只留机制公式与结论。
* 标记体系 [ALGO] [FORMULA] [ASSUMPTION] [MODEL-SPECIFIC] [SYSTEM] [SYSTEM-DEPENDENT] [TODO]：定义见 A.1。
* 符号与定量基线 [BASELINE-0]：见 A.2（正文机制公式使用 H / L / S / B / Nq / Nkv / D / r / I / b_w / b_kv / b_a）。

---

## 1. Transformer Memory Mental Model

建立最小 AI workload 知识：只看 Tensor 对象与生命周期。

### 1.1 一次推理的全局数据流

```text
Text → Tokenizer → Token IDs → Embedding → [Transformer Layer × L] → Final Norm → LM Head → Logits → Sampling → Next Token
```

* **一个 Decode Step = 生成一个新 token**：当前 token 过全部 L 层 + LM Head + Sampling，循环往复；
* prompt 的 S 个 token 一次性并行过网络 = **Prefill**；之后逐 token 生成 = **Decode**（第 3 章）；
* Tokenizer / Sampling 数据规模远小于 GEMM 与 KV，一般不是 HBM 主瓶颈；LM Head 是一次 [1,H]×[H,V] GEMM，decode 时其 weight read 不可忽略（≈250 MiB，A.5.3）；
* Embedding 是 [V,H] 表的行查找（weight 只读）。

### 1.2 四类 Tensor 对象与生命周期

| 对象 | 生命周期 | 理想驻留 | 对 HBM 的意义 |
|---|---|---|---|
| **Weight**（WQ/WK/WV/WO、W1/W2、Embedding、LM Head、Norm scale）| static / inference 只读 | HBM 常驻（容量决定必须 streaming） | 反复 streaming read——decode 的第一流量 |
| **Activation**（Q/K/V、attention 输出、MLP intermediate）| 单 step 内、短命 | SRAM / RF，理想不落 HBM | 理想接近零 HBM；spill 才产生额外 R/W |
| **KV Cache** | 跨 token、随序列增长 | HBM（backing store），hot tile 可在 SRAM/L2 | capacity + bandwidth 双重压力 |
| **Hidden State** | 层间传递的核心 activation | 同 Activation | 8 KiB/token 量级（baseline，A.5.3）|

KV Cache 要点 [ALGO]：

* **为什么缓存 K/V**：生成 token t 需要与全部历史 K/V 做 attention；不存则每步重算全部历史——本质是**用 capacity 换 compute**；
* **为什么不缓存 Q**：Q_t 只服务当前 token，历史 Q 无复用价值；
* **每层独立**：各层 K/V 语义不同，互不可替代；
* 容量随 B、S 线性增长：`KV capacity ∝ B × S × L × H`（数字 → A.5.3）。

### 1.3 三个必须区分的量

```text
Tensor Size                          算法视角的数据体量
≠ Algorithmic Memory Bytes           含读写放大前的逻辑搬运量
≠ Physical HBM Transaction Bytes     经 cache / fusion / 映射后的实际事务量
```

> **面试一句话总结（§1）**：LLM 推理的 HBM 压力来自三类生命周期完全不同的数据——只读常驻的 Weight（streaming）、短命的 Activation（应尽量不落 HBM）、跨 token 增长的 KV Cache（capacity + bandwidth 双压力）；理解 workload 先看数据生命周期。

---

## 2. Operator → Memory Behavior

Transformer 的主要计算形式是 **Activation × Weight 的 GEMM**。分析 operator 不关心矩阵数学，只关心两件事：**M 维（多少 token 一起算）** 与 **数据搬运**。

### 2.1 GEMM：M 维决定一切

```text
X[M,K] × W[K,N] → Y[M,N]
FLOPs ≈ 2MKN          Weight read = K·N·b_w
Weight reuse ≈ M      AI_weight ≈ 2M / b_w   （FP16 下 ≈ M FLOP/B）
```

* **M 大（Prefill / 大 batch）**：一份 Weight 服务 M 个 token → reuse 高 → AI 高 → compute-bound 倾向；
* **M = 1（Decode B=1）**：一份 Weight 服务 1 个 token → Weight read 成为绝对主导 → memory-bound 倾向；
* AI 数值对比（decode ≈1 vs prefill ≈4096 FLOP/B）与 Roofline 定位 → A.5.3。

[ASSUMPTION] 只计 Weight traffic 的简化式，完整 AI 低于此值。**M 是 workload 侧唯一需要时刻盯住的参数。**

### 2.2 Attention：为什么它影响 HBM

数据流（每层）：

```text
X → QKV Projection → Head reshape → RoPE(Q, K) → QK^T → Softmax → P×V → Output Projection
```

Memory 相关要点：

* QKV projection + output projection 是 4 个 [H,H] Weight GEMM（机制式 `4H²/layer`）；
* **Q/K/V 一句话** [ALGO]：Q 在找什么、K 提供可匹配特征、V 提供被加权的信息；Q+K 决定“看谁”，V 决定“看到什么”；multi-head 不要求 projection 前物理拆 head；
* RoPE 只作用于 Q/K（位置信息编入），element-wise、O(S·H) 级，片上完成，通常不是 HBM 主 traffic；
* QK^T 与 PV 各 S²H MAC，attention core 合计 **2S²H**——Prefill 时唯一随 S² 增长的 compute 项；
* **对 HBM 的真正冲击来自中间结果，不是 FLOPs**：naive 实现把 Score:[Nq,S,S] 与 P 完整写 HBM 再读回 → 与 Model Weight 同量级的额外 traffic（§4.1 / A.5.1）；fused / FlashAttention 类实现使其不落 HBM；
* **Causal Mask**：Prefill 有真实三角 mask 区（score 置 -∞，softmax 后为 0）；Decode 每步只有 1 个新 query，**不存在 [S,S] 规模 mask 区——不能把 HBM 上的大量 zero write 归因于 Decode 的 causal mask**（zero write 的真实来源见 §4.5 备注 / A.3）；
* head 之间无依赖、可完全并行（head split → §5.2）；head 维也是 GQA（§4.2）的作用点。

### 2.3 MLP：Weight 主导

```text
[S,H] × W1[H,I] → [S,I] → × W2[I,H] → [S,H]        baseline I = 4H
```

* MLP Weight = 2H·I（机制式；baseline 8H²/层，占单层 weight 的 2/3）——**MLP 是 HBM Weight 压力的主力**；
* attention 输出的 activation 可留片上进入 MLP，但 **activation 留片上 ≠ MLP 不吃 HBM**——MLP 的 HBM 压力来自 Weight streaming；
* MLP intermediate 是单 token 最大 activation（[1,4H]），Prefill 时 [S,4H] 远超典型 buffer，**必须 tile**（§5.2）。

[MODEL-SPECIFIC] gated MLP / SwiGLU 的 projection 数与 I 与两矩阵 baseline 不同，Weight / FLOPs 按实际矩阵重算（A.3）。

### 2.4 Norm / Residual：fusion 的首要对象

* **Norm**：per-token 归一化 + [H] 量级 scale（KiB 级 weight 可忽略）；compute 不重，性能受 activation 搬运支配 → **常与相邻算子 fusion，避免 activation 落 HBM 一个来回**；
* **Residual**：`out = x + block(x)`，原 hidden state 必须保留到相加；理想留在 SRAM 不经 HBM；容量不足 spill 才产生一次写 + 一次读。

> **面试一句话总结（§2）**：Operator 层面只需盯三个 memory 事实——GEMM 的 M 维决定 Weight reuse 与 AI；Attention 的 HBM 冲击来自 Score/P materialization 与 KV，而非 FLOPs；MLP 是 Weight streaming 主力，Norm / Residual 是 fusion 首要对象。

---

## 3. Workload Phase：Prefill vs Decode

同一模型，两种 memory workload。**分水岭是 GEMM 的 M 维**——先讲机制，数字只是 baseline（A.5.3）。

### 3.1 Prefill：S 维提高 reuse

```text
输入 [S,H]，S 个 token 并行过网络
M = S → Weight reuse ≈ S → AI 高 → compute-bound 倾向
```

* 一份 Weight 服务 S 个 token，weight traffic 被 S 摊薄；
* attention core 出现唯一随 S² 增长的 compute 项；
* [BASELINE-0] 下 read 侧只有 Weight（理想 fusion，score 不 materialize）；write 侧是 KV append（R:W ≈ 6:1，A.5.3）。

### 3.2 Decode：M=1 的 streaming 世界

```text
输入 [1,H]，逐 token 生成
M = 1 → Weight reuse ≈ 1 → GEMM 退化为 GEMV → memory bandwidth pressure
```

每步 traffic 机制式：

```text
Decode bytes/token ≈ Weight Read（≈ 全量 Model Weight，12LH²·b_w）
                    + Historical KV Read（2LSH·b_kv）
                    + New KV Write（2LH·b_kv，小但存在）
```

* Weight streaming 是第一流量：每 step 几乎重读一遍全部 Weight（[BASELINE-0] 假设 weight 不跨 step 驻留；一般架构下 cache 可提供跨 step 复用，属 [SYSTEM-DEPENDENT]）；
* 每步读全部历史 KV——context 越长流量越大；
* 每步追加写新 KV——写占比极小但存在于 R/W mixing（§7.5）。

[SYSTEM-DEPENDENT] “Prefill compute-bound / Decode memory-bound” 是典型趋势不是定律：取决于 batch、context、quantization、硬件 compute:BW 比、kernel fusion。长 context 的 prefill 也可能被 KV traffic 拉向 memory-bound。

### 3.3 Weight / KV 主导权交换（crossover）

```text
S_c = 6H · (b_w / b_kv)          （MHA；GQA 须重推 → A.5.3）
S < S_c：Weight read 主导；S > S_c：KV read 主导
```

机制：Weight 项随 H² 不随 S，KV 项随 S 线性——**context 拉长必然把主导权交给 KV**。precision 只在 b_w ≠ b_kv 时影响 crossover。

### 3.4 Batch：摊薄 Weight，不摊薄 KV

```text
Weight traffic/token ≈ Model Weight / B      前提：B 个 token 真的拼成一次 M=B 的 GEMM（时间对齐、无 padding）
Total KV read = Σ 2LS_i·rH·b_kv              各 sequence 的 KV 属于自己，不被 batch 摊薄
```

* 请求异步到达 / 结束会打破时间对齐 → **Continuous Batching 的存在动机**：sequence 结束立即补入，维持有效 M；
* batch 内 **long-tail sequence 主导 KV bandwidth**（KV read 与各自 S 成正比；数字例 → A.5.3）；continuous batching 补入的新 sequence S 小：对它 weight 是全额成本、KV 几乎免费；
* batch 提高 aggregate throughput / Weight reuse / utilization，**不意味着单 sequence TPOT 降 B 倍**（T_step 往往随 B 增大）；
* serving 指标归属：TTFT → Prefill、TPOT → Decode、Throughput → aggregate；serving scheduler 完整机制 [TODO]（A.3）。

> **面试一句话总结（§3）**：Prefill 与 Decode 是同一模型的两种 workload：Prefill 用 M=S 摊薄 Weight、AI 高、偏 compute；Decode 的 M=1 使 Weight 退化为纯 streaming、叠加每 token 全量历史 KV read，偏 bandwidth——12 GiB / 2 GiB 这类数字只是 baseline，“M 维决定 Weight reuse”的机制才是通用结论。

---

## 4. Optimization Impact

所有 optimization 按五段模板描述（§0.4）。本章只回答：**它改变了链上哪一环、MC 看到什么变化。**

### 4.1 FlashAttention

**1. 解决什么问题**

Bandwidth / locality 问题，不是 compute 问题——attention 的中间结果 Score/P 若 materialize，其 memory movement 与 Model Weight 同量级。

**2. 原始实现的问题**

naive 数据流：写 Score → 读 → softmax → 写 P → 读 → PV；完整 [Nq,S,S] 的两个矩阵各写、读一次（baseline 下 ≈10× Model Weight，A.5.1）；causal mask 三角区通常仍被写出，量级不变。

**3. 核心思想**

以 Tile 为单位在片上完成 Score / Softmax / Output 累积：

```text
Outer Loop (i)：遍历 Q Tile    → 决定计算哪些 token 的 Output
Inner Loop (j)：遍历 KV Tile   → K_j 产生 Score；V_j 提供被加权的数据
Online Softmax                 → running max / running sum 使各 tile 贡献逐步正确累积（数学等价）
O Tile 输出                    → Q_i 的全部合法 KV 处理完后输出
```

* **关键判据**：完整 [S,S] 的 Score/P 在任何时刻、任何层级（SRAM 或 HBM）都不存在；
* **Tile size 张力**：增大 → working set↑ / SRAM↑ / KV reuse↑ / HBM 重读可能↓——受 SRAM/L2 容量限制（定量 → A.5.2）；
* **残余项**：inner loop 对每个 Q tile 重扫 K/V → K/V 读取放大 S/Br 倍；是否落 HBM 取决于片上吸收（逐 head 处理时通常被 L2 吸收）[SYSTEM-DEPENDENT]。

**4. Tensor / Data Movement 如何变化**

| 环节 | 变化 |
|---|---|
| FLOPs | 不变：仍 2S²H MAC（rescale 仅微增）——**省的是 memory，不是 compute** |
| 算法输出 | 不变：online softmax 与标准 softmax 数学等价 |
| Logical Data Movement | **变：Score/P 的 L/S 字节消失** |
| Cache / NoC / MC / HBM | Score/P 支路整体消失；新增 K/V 重读放大 |

**5. MC 看到什么变化**

* 消失：Score/P 的 write / read request——原 attention 阶段 request 数与 bytes 的大头；
* 保留：Q/K/V/O + Weight streaming（QK^T/PV 计算照常发生）；
* 影响：request 数量下降、traffic mix 简化（更接近纯 Weight/KV streaming）、bandwidth pressure 下降；
* 收益在 Bytes 层面，不必然改善剩余 request 的 size / run / stride（仍由 layout、loop order、映射、coalescing 决定，§5.1）；**Tile ≠ Request Size**。

### 4.2 GQA / MQA

**1. 解决什么问题**

KV capacity 与 KV bandwidth 压力——**KV cost ∝ Nkv**，减少 KV head 是直接手段（MHA → MQA 极端 → GQA 组共享折中；projection 阶段就只生成 Nkv 组 K/V）。

**2. 改变哪个 memory 行为**

```text
Nkv ↓（r = Nkv/Nq）
↓
KV capacity ∝ r ↓            KV/token = 2LrH·b_kv
↓
KV write ∝ r ↓（正常实现下）
KV read ↓？——取决于 shared KV 是否被片上复用
```

**3. Tensor / Data Movement 如何变化**

* KV footprint 与 unique KV write bytes 按 r 下降（baseline 每层每 token 16 KiB → 4 KiB）；
* physical HBM write 仍受 padding / alignment / granularity / layout 影响，非严格 r 倍下降；
* projection weight 变为机制式 2(1+r)H²/层（A.5.3）；attention core FLOPs **不变**（QK^T/PV 由 Nq 决定，与 Nkv 无关）。

**4. Request Stream 如何变化**

KV 区域变小 → 单次 burst 覆盖的地址范围变小；address mapping 仍须保证 channel / PC 并行度（§5.1 / §7.2）。

**5. MC 看到什么变化**

capacity 下降确定；write 下降近似确定；**read 不确定**——

```text
组内复用（同一份 KV 服务组内多个 Q head）：HBM 只 read 1 次 → read 下降
各 Q head 独立扫 KV：MC 看到同样的 read 量，只是分布在更小地址范围 → read 不降
```

**Capacity saving ≠ Physical read saving——Memory Architect 视角最重要结论。**

### 4.3 Quantization（memory 角度）

**解决什么问题**：bytes/element 缩放——b_w / b_kv 分别进入一切 Byte 公式（A.2）。

* **Weight-only**（FP16→FP8/INT8/INT4）：Weight streaming 按比例直接下降 → **decode 收益最大**（weight 是第一流量）；KV 不变时 crossover 左移（S_c ∝ b_w/b_kv，§3.3）——KV 更早成为主导；
* **KV quant**：historical KV read 与 capacity 同步下降；dequant metadata（scale / zero-point）是额外小流量；
* [TODO] FP8/INT8/INT4 完整定量与 metadata 开销（A.3）。

### 4.4 PagedAttention（memory 角度）

**解决什么问题**：KV capacity 的碎片与预留浪费（按 max length 预留连续空间 → 内/外部碎片）。

**Memory 行为变化**：逻辑连续 KV → block table 间接映射的物理分段——

* **KV block 内 sequential、block 间 irregular**：prefetch 看 block 内 run，mapping 看 block 间离散；
* request stream：sequential run length 截断到 block 粒度、stride 不规则、row locality / channel 分布由 block 物理落点决定 [SYSTEM-DEPENDENT]；
* runtime block mapping 与 VA→PA translation 是两个不同层级（§5.3）；
* [TODO] block size 与 burst 粒度匹配的定量破坏程度（A.3）。

### 4.5 MoE（memory 角度）

**解决什么问题**：capacity 换质量——expert weight 总量大、每 token 只激活少数 expert。

* Memory 行为：token routing 决定 expert weight 的读取集合 → **连续访问被打散成 expert 粒度的随机集合**；hot expert 成为 channel/bank hotspot [SYSTEM-DEPENDENT]；
* [TODO] expert placement / routing 对 request stream 的定量（A.3）。

**备注——HBM zero write 的真实来源**：buffer initialization / page clear / padding / sparse activation 写回 / unfused attention materialization；**不归因 causal mask**（§2.2）。

> **面试一句话总结（§4）**：优化的共同语法是“改变链上某一环”——FlashAttention 消灭中间结果的 request；GQA 缩小 KV footprint（read 是否兑现看片上复用）；Quantization 缩放 bytes；PagedAttention 用物理离散换 capacity；MoE 用 capacity 换 compute 但打散连续性。

---

## 5. Tensor → Request Stream

字节会计到此结束。进入 MC 分析前，必须把 bytes 翻译成 **request 属性**。

### 5.1 Layout：layout → address sequence → coalescing → request size

* Tensor 逻辑布局决定地址序列。KV 两个基本布局：

```text
[token][head][D]   token 维连续        —— append 写 burst 友好
[head][token][D]   head 内 token 连续  —— historical scan 读友好
```

* layout + 多 source 交织 + 线程地址连续性 + cache line 粒度 + 对齐 → coalescing degree → **request size 与 request 数**；
* layout 与 channel interleave 粒度不匹配 → channel hotspot；
* **逻辑连续 ≠ 物理连续**：sequential run length 还受 VA→PA 与 runtime block mapping 影响（§5.3）。

### 5.2 Tile：计算粒度 ≠ 访问粒度

* **Tile ≠ Request Size**：tile 是 kernel 的计算/驻留粒度；request 是 MC 看到的访问粒度——两者隔着线程地址连续性、cache line/sector 粒度、对齐与合并机制；
* **Tile split**（沿 S / KV 维）：解决 working set 太大 → 决定 SRAM 容量需求、reuse 窗口、K/V 重读（A.5.2）；
* **Head split**（沿 Nq / batch 维）：解决并行度 → head 间无依赖、多份独立小 attention；GQA 让多 Q head 共享 K/V，把 head split 变成 reuse 来源（§4.2）；
* loop order / tile 遍历顺序决定访问时序（burstiness、相位、多 source 交织）。

### 5.3 Cache / TLB / NoC / Coherency：最小影响模型

只回答一件事：**它们如何改变 Logical Bytes → MC-visible Request Stream。**

**Cache**：

```text
hit        → HBM request 消失（temporal reuse：weight tile 服务多 token；shared KV 服务组内 head）
miss       → 产生 line 粒度 fill request（line = 最小取回粒度 → over-fetch 可能）
write-back → HBM write 延迟到 evict，与 compute 时序解耦 → write 更 bursty
MSHR       → 聚合全部 source 的 miss 并发，是 MC outstanding 供给的上限之一
```

capacity miss → working set 问题（tile / 容量解决，非 mapping 解决）；容量不足时：weight 退化纯 streaming、activation spill（额外写+读）、KV 接近全量 HBM read。

**VM / TLB**：

```text
VA → page table → PA；TLB miss → page table walk（额外 memory 活动 + latency）
逻辑连续 ≠ 物理连续：物理页落点决定 channel/bank/row 命中与 sequential run
runtime block mapping（Paged KV）与 VA→PA translation 是两个不同层级
```

**NoC**：

```text
congestion → requests 在到达 MC 前被延迟 → MC 看到 arrival rate 低 / queue 浅 / outstanding 不足
MC queue/CAM full 只是 symptom（arrival > retirement）——根因可能在 DRAM timing / row conflict / R/W turnaround / refresh / write data 供给；Observable ≠ Root Cause
credit-based flow control → backpressure 逐级回传 source；仲裁策略整形 arrival（burstiness / fairness）
```

**Coherency（三条保留事实）**：

* 最新数据可能只在某 cache（dirty line 不在 HBM），直到 writeback 才落 HBM；
* cache-to-cache 传输可完全不碰 HBM；
* coherency 逻辑必须有，但是否在 MC RTL 内取决于 SoC partition；order / barrier 限制整个 memory subsystem 的重排自由度——无论 partition 如何，MC 都可能牺牲 row-hit 与并行度，但机制不同。

诊断链（→ §7.6）：

```text
Workload → Cache Miss Stream → NoC Arrival Stream → MC Visible Stream → DRAM Scheduling
```

### 5.4 Request Stream Schema（performance-model 接口）

```text
基础属性：Read/Write · Request Size · Burst Length · Stride · Sequential Run Length
        · Outstanding · Temporal/Spatial Locality · Address Distribution
系统层属性：Source/Traffic Class · Arrival Time/Inter-arrival Gap · Cacheable/Non-cacheable
        · Physical Page/Region · Coalescing Degree · Prefetch/Demand · Criticality/QoS · Dependency/Ordering
```

分析示例——从 byte 会计到 request 会计：

```text
KV Read = 2 GiB
→ KV Read = 2 GiB；request size = ?；request 数 = ?；stride = ?；outstanding = ?；channel 分布 = ?；row locality = ?
```

未知值一律标 [TODO]，不编造。这些是分析属性，不等同具体 bus protocol 的 signal field。[SYSTEM-DEPENDENT]

> **面试一句话总结（§5）**：同一份 logical bytes，经 layout / coalescing / cache / TLB / NoC 之后，MC 看到的 request stream 在数量、大小、时序、地址分布上都已不同——bytes 会计到 request 会计的翻译，是 Controller 分析的前置步骤。

---

## 6. AI Traffic Classification

**全文连接 AI 与 MC 的接口章**：三类主 traffic 的画像与 MC 关注点。

| Traffic | 模式 | Capacity | BW | Latency sensitivity | MC 关注点 |
|---|---|---|---|---|---|
| **Weight Streaming** | read-only、大块 sequential、每 step 反复 | 高（常驻） | 高 | 中/高，取决于 prefetch [SYSTEM-DEPENDENT] | burst 长度、channel striping、mapping 配合、prefetch 友好 |
| **KV Traffic** | historical read + append write 混合、layout 敏感、随 S/B 增长 | 随 S、B 线性 | 高 | historical read 在当前 attention critical path | stride、bank distribution、row locality、R/W mixing |
| **Activation Traffic** | 理想 on-chip；spill 才落 HBM | — | 理想 ≈0 | 不希望出现 | spill 时的额外 R/W |

分类的意义：

* Weight → **规则**：好 striping、好 prefetch、mapping 配合时 row locality 好；
* KV → **善变**：layout / paging / kernel traversal / mapping 共同决定形态（§5.1 / §7.2）；
* Activation → **异常信号**：MC 看到 activation 型 traffic 通常意味着 spill 或未 fusion。

机制式画像（baseline）：

```text
Decode:  Weight 12LH²·b_w  +  KV read 2LSH·b_kv  +  KV write 2LH·b_kv
Prefill: Weight 12LH²·b_w  +  KV write 2LSH·b_kv   （理想 fusion 下 read 只有 Weight）
```

（数字代入与 R:W → A.5.3）

New KV append 特性：write 型、可被 write-back / 写聚合延迟合并、token 连续布局利于写合并、新 page 分配可能引入不连续。[SYSTEM-DEPENDENT]

---

## 7. Request Stream → HBM Controller

从 `MC-visible Request Stream` 开始——这是 MC 能调度的全部输入。

### 7.1 Outstanding：并行度是否够

* 足够的 outstanding 才能暴露 bank / channel parallelism——PC 与 bank 同时忙碌是打满带宽的前提；
* Decode B=1 的 compute 侧并发天然低，但 MC 可见 outstanding 还取决于 kernel 切分 / cache MSHR / NoC / prefetch [SYSTEM-DEPENDENT]；
* 问题不是“decode 天然 request 少”，而是：**这个 workload 能给 MC 提供多少 scheduler-visible outstanding，是否足以暴露 channel / PC / bank parallelism？**[TODO 定量]

### 7.2 Address Mapping：layout → physical address → channel/bank

* Tensor 连续维到 channel/PC interleave bits 的映射决定并行度；KV burst 粒度由 layout 与 D 维长度决定，burst 短则难铺满 channel；
* **Sequential Access ≠ High Row-hit Rate**：sequential 给出 favorable burst / spatial 行为；row locality 由 physical address mapping + request ordering + layout 共同决定——不要从“顺序流”直接推出“row hit 高”；
* KV locality = layout + paging + kernel traversal + mapping 的合取，可能频繁跨 row；
* mapping 设计空间（channel/BG/bank/row bits 取法）与 tensor layout 的共同优化 [TODO]（A.3）。

### 7.3 Row Locality 的代价

* row hit 高 → 少 ACT → 高 effective BW；row conflict → tRCD / tRAS 开销直接吃带宽；
* scheduler 的 row-hit 优先（FR-FCFS 类）收益完全取决于 arrival stream 的 row locality——**供给不好，scheduler 无力回天**（§5.3 / §7.6）。

### 7.4 Scheduler：MC 的自由度

（与 `DDR_Controller_Architecture.md` 衔接；此处只列 workload 视角）

* **FR-FCFS / row-hit 优先**：收益取决于 §7.2 的 arrival locality；
* **Read / Write batching**：R/W turnaround 有直接带宽代价。decode 写占比极小 → 写聚合几乎免费；prefill 写占比高 → 聚合收益与 WDB 压力都更大（数字 → A.5.3）；[SYSTEM-DEPENDENT] 具体收益取决于 scheduler 设计与 workload 相位；
* **Starvation / fairness / QoS**：Weight read 在 compute critical path；KV read 决定当前 token 完成时间（criticality 高）；KV write 的可延迟性取决于 runtime buffer 与 ordering 约束，**非算法保证** [SYSTEM-DEPENDENT]；
* **Refresh / RAS**：满带宽 workload 下的固定带宽税 [TODO 定量]。

### 7.5 R/W Mixing（baseline 画像）

```text
Decode:  R:W ≈ 28000:1（写聚合几乎无成本地减少切换）
Prefill: R:W ≈ 6:1（聚合收益与 WDB 压力都更大）
```

（推导 → A.5.3）

### 7.6 Performance Loss Attribution

HBM BW 利用率低时，**不要直接归因 MC**：

```text
MC queue shallow
→ 查 request supply：workload arrival / cache MSHR / NoC / prefetch

MC queue deep but no command issued
→ 查 MC / DRAM：dependency / timing / direction / refresh / write data / credit
```

* CAM full 只是 symptom（arrival > retirement），**Observable ≠ Root Cause**；
* NoC credit stall 与 DRAM tRCD stall 症状可能相同——看 stall 在哪一级 queue、对应哪一级 occupancy。

诊断层级：

```text
Application / Kernel → Cache / MSHR → NoC → MC Admission → MC Scheduler Visibility → DRAM Timing / Resource
```

> **面试一句话总结（§7）**：MC 的输出效率 = request stream 与 DRAM 资源的匹配度——outstanding 决定并行度是否暴露，mapping 与 layout 决定 row locality，R/W mix 决定 turnaround 代价，refresh 是固定税；利用率低先查供给侧，再查 MC 自身。

---

## 8. Case Study

### Case 1：为什么 Decode 性能差？

```text
Decode → M=1 GEMM（GEMV）→ Weight reuse ≈ 1 → 每 step 重读全量 Weight（streaming）
→ 叠加每 token 全量历史 KV read → memory bandwidth 压力 → memory-bound
```

* 回答要点：不是 compute 不够，是 **AI 太低**（AI_weight ≈ 1 FLOP/B，§2.1）；缓解方向全在 memory 侧——batch 摊薄（reuse ≈ B，§3.4）、quantization 缩 b_w（§4.3）、weight 驻留复用 [SYSTEM-DEPENDENT]；
* 边界：长 context 时 KV read 反超 weight（S_c，§3.3 / A.5.3）。

### Case 2：GQA 为什么提升 Inference？

```text
Nkv ↓（r）→ KV footprint ∝ r ↓ → KV capacity ↓ 且 KV write ∝ r ↓
→ KV read 是否 ↓ 取决于 shared KV 是否被片上复用（kernel reuse / cache behavior）
→ FLOPs 基本不变（attention core 由 Nq 决定）
```

* 回答要点：GQA 是 **memory 优化不是 compute 优化**；capacity / write 收益确定，read 收益是条件命题（§4.2）；KV 区域变小后 mapping 仍须保住 channel 并行度（§7.2）。

### Case 3：FlashAttention 为什么提升性能？

```text
Naive：Score/P 完整 materialize → 写+读与 Model Weight 同量级的 HBM traffic
FlashAttention：tiling + online softmax → Score/P 只以 tile 形式瞬态存在于 SRAM
→ Logical Data Movement 消失 → Score/P request 消失
→ FLOPs 不变、HBM traffic 大幅下降
```

* 回答要点：省的是 memory movement 不是 compute；MC 视角 = request 数量下降 + traffic mix 简化（§4.1）；残余 K/V 重读是否落 HBM 取决于 SRAM/L2 吸收（A.5.2）。

---

## 9. 当前结论汇总

1. Transformer 的主要计算形式是 Activation × Weight（§2）。
2. Weight、Activation、KV Cache 生命周期不同：只读常驻 / step 内短命 / 跨 token 增长（§1.2）。
3. Activation 尽量片上流动；Weight 与 KV 是 HBM 主流量（§1.2）。
4. Decode 的主要 HBM traffic 通常来自 Weight streaming + Historical KV read（baseline：12 + 2 GiB/token，§3.2 / A.5.3）。
5. Prefill 通过 S 维提高 Weight reuse（≈S），典型偏 compute-intensive（§3.1）。
6. Batch 通过 B 维提高 Decode Weight reuse（≈B），前提是 B 个 token 真的组成一次 GEMM——Continuous Batching 的意义（§3.4）。
7. Long Context 主要放大 KV Capacity 与 KV Read，且 batch 内由 long-tail sequence 主导 KV 带宽（§3.4 / A.5.3）。
8. GQA/MQA 主要解决 KV Memory Cost：算法上 KV capacity 与 unique KV write bytes 按 r 下降（§4.2），而非同比减少 attention core FLOPs。
9. 算法级 Byte reduction ≠ 物理 HBM transaction reduction——GQA read 是否兑现取决于片上复用；attention 实现方式可完全改写 traffic 结论（§4.1 / §4.2：省的是 materialization 的 memory，不是 compute）。
10. Tensor layout + accelerator tiling + controller mapping 共同决定最终 HBM efficiency（§5.1 / §7.2）。
11. Prefill 的高 Weight reuse 可用 Arithmetic Intensity 定量表达（FP16 下 AI_weight ≈ M FLOP/B，§2.1）。
12. Decode B=1 的 Weight AI 极低，按 Roofline 强烈倾向 memory-bound；最终 operational point 取决于完整 traffic accounting 与真实硬件 Peak Compute / HBM BW，不能仅由 M=1 判定（§2.1 / §3.2 / A.5.3）。
13. Batch 提高 aggregate throughput 与 Weight reuse，但不意味着单 sequence TPOT 按 B 下降（§3.4）。
14. Weight / KV precision 可以不同：所有 Byte 与 crossover 公式分别使用 b_w、b_kv（A.2 / A.5.3）。
15. `S_c = 6H` 只适用于 MHA 且 b_w = b_kv 的 baseline；一般式 `S_c = 6H·(b_w/b_kv)`（§3.3 / A.5.3）。
16. RoPE 修改 Q/K 的位置表示，通常不是 HBM 主 traffic（§2.2）。
17. KV Cache 主体驻留 HBM，但 consumer 可从 SRAM/L2 命中——logical KV read ≠ physical HBM read（§5.3）。
18. MC-visible request stream 需以 request size / stride / outstanding / locality 等属性描述后，才能进入 Controller 分析；HBM transaction 是 MC 的输出而非输入（§5.4 / §7）。
19. Logical Bytes ≠ Compute L/S Bytes ≠ Cache Miss Bytes ≠ NoC Bytes ≠ MC Request Bytes ≠ Physical HBM Bytes——层间因 reuse / cache hit / writeback / prefetch / coalescing / padding / fragmentation / coherence / retry 变化（§0.3 / §5.3）。Transformer 给出的 logical bytes 不会一比一成为 HBM traffic。
20. Cache write policy、cache line size、MSHR 深度、prefetch 策略、page/TLB 行为、NoC 仲裁与 coherency partition 均为 [SYSTEM-DEPENDENT]，任何相关结论都不能写成 universal fact（§5.3）。
21. MC 只能调度它“看得见”的请求：HBM 利用率低可能是上游供给不足（MSHR / NoC / prefetch 缺失）而非 MC 调度器问题；瓶颈定位沿 `Cache Miss Stream → NoC Arrival Stream → MC Visible Stream` 逐层查看 outstanding / queue occupancy（§7.6）。
22. Coherency 使 `load → HBM read / store → HBM write` 的简单模型失效：load 可能命中他 cache（不读 HBM）、store 可能延迟到 writeback 才写 HBM；coherency 逻辑是否在 MC RTL 内取决于 SoC partition（§5.3）。

---

## 10. 附录

### A.1 标记体系

| 标记 | 含义 |
|---|---|
| [ALGO] | 算法定义 |
| [FORMULA] | 本文档推导 |
| [ASSUMPTION] | 简化假设 |
| [MODEL-SPECIFIC] | 特定模型特有 |
| [SYSTEM] | runtime / accelerator 行为 |
| [SYSTEM-DEPENDENT] | 结论依赖具体系统实现 |
| [TODO] | 尚未理解 / 待补 |

### A.2 符号表与定量基线

| Symbol | Meaning |
|---|---|
| B | Batch Size |
| S | Sequence / Context Length（token 数）|
| H | Hidden Size |
| L | Transformer Layer 数 |
| Nq | Query Head 数 |
| Nkv | KV Head 数（MHA: Nkv=Nq；GQA: Nkv<Nq；MQA: Nkv=1）|
| D | Head Dimension |
| r | Nkv / Nq |
| I | MLP Intermediate Size（baseline 取 4H）|
| V | Vocabulary Size |
| b_w | Weight bytes per element |
| b_kv | KV Cache bytes per element |
| b_a | Activation bytes per element |
| WQ/WK/WV/WO | Attention Projection Weight |
| W1/W2 | MLP Up / Down Projection Weight |
| ηmemory | Memory Efficiency（有效带宽 / 峰值带宽）|

b_w / b_kv / b_a 的区分使 Weight / KV / Activation 可取不同 precision 而无需重写公式体系。

```text
[BASELINE-0]
Architecture       = Decoder-only
Attention          = MHA
H = 4096, L = 32, Nq = Nkv = 32, D = 128, S = 4096, B = 1
MLP                = H → 4H → H
Precision          = FP16（b_w = b_kv = b_a = 2 B）
Weight residency   = cannot persist across decode steps
Activation spill   = ignored unless noted
Attention traffic  = ideal fused assumption unless noted（即 FlashAttention 类行为，§4.1）
LM Head            = excluded from main 12H² formula unless stated
```

单位约定：正式推导统一 KiB / MiB / GiB（2^10 进制）；decimal 只在括号补充。更换任一假设（GQA、其他 L/H/I、Weight 与 KV 不同 precision）必须重新推导，公式不可直接移植。

### A.3 待学习 / 待验证

* [TODO] PagedAttention 定量：block size 与 burst 粒度、block table 间接寻址对 sequential run / stride / row locality 的破坏程度（§4.4 / §5.1）
* [TODO] Continuous Batching 完整 workload：与 serving scheduler 的耦合（§3.4）
* [TODO] Quantization 定量：FP8/INT8/INT4 的 Weight/KV/BW 结论与 dequant metadata 开销（§4.3）
* [TODO] SwiGLU / Gated MLP：对 Weight / FLOPs / HBM traffic 的影响（§2.3）
* [TODO] MoE：expert placement、token routing 对连续访问的破坏、hot expert hotspot 定量（§4.5）
* [TODO] Tensor / Pipeline / Expert Parallel：单卡 HBM traffic 与 scale-up fabric 的替代关系
* [TODO] Roofline：用真实 accelerator 的 Peak Compute / HBM BW 确定 operational point（§2.1 / A.5.3）
* [TODO] Prefill / Decode request stream 定量：request size / stride / outstanding / channel 分布 / row locality（§5.4 / §6）
* [TODO] KV / Weight locality ← layout + paging + kernel traversal + physical address mapping 的定量关系（§5.1 / §7.2）
* [TODO] HBM Channel / PC mapping 与 tensor layout 的共同设计空间（§7.2 / §7.3）
* [TODO] Memory hierarchy 定量：SRAM 约束下的 tiling 分配（§5.2；attention kernel 实例已入 A.5.2）
* [TODO] Norm / Residual 的 traffic 定量（§2.4）
* [TODO] Controller 机制定量：outstanding 深度、scheduler 可见性、refresh loss（§7）
* [TODO] Cache line / coalescing → HBM request size 的定量关系；Cache hit rate → physical HBM bytes 的定量映射（§5.3）
* [TODO] aggregated cache-miss concurrency / NoC deliverable outstanding → MC admitted / scheduler-visible outstanding 的定量关系（§5.3 / §7.1）
* [TODO] Prefetch accuracy / coverage → useful vs wasted HBM BW（§5.3）
* [TODO] TLB / page size / fragmentation → KV access pattern；PagedAttention block mapping + VM/TLB → final physical address pattern（§5.3 / §4.4）
* [TODO] NoC congestion / credit → MC arrival process 的定量刻画；NoC QoS ↔ MC QoS 的交互与一致性（§5.3 / §7.4）
* [TODO] Coherency resolution → physical HBM traffic 的定量影响（§5.3）
* [TODO] AI workload 的真实 request arrival distribution（跨 §5–§7，需实测数据）

---
### A.4 结论修订记录

> 注：以下条目中的章节号为各条目编写时的文档版本编号；现行章节结构见 §0–§10。

* **GQA Weight/KV crossover**：早期版本按"weight 维持 12H² 不变"推得 ≈96K，与 5.3-2 的 weight 公式 (10+2r)H² 不一致；统一重推为 `S_c(r) = [(10+2r)/(2r)]·H·(b_w/b_kv)`，r=1/4、b_w=b_kv → ≈86K（7.13）。
* **"crossover 与 precision 无关"补全限定条件**：仅 b_w = b_kv 时成立；一般式含因子 b_w/b_kv（7.13）。
* **Prefill R:W 由 7:1 修正为 6:1**：旧值把 decode 口径的 historical KV read 误计入 prefill read 侧；[BASELINE-0] 下 prefill 的 read 项只有 Weight 12 GiB，write 项为 KV append 2LSHb_kv = 2 GiB（10.5）。
* **"GQA capacity/write 无条件按 r 降"表述收紧**：算法量（capacity、unique KV write bytes）按 r 下降；physical HBM transaction bytes 仍受 padding / alignment / granularity / replication / layout 影响（5.3-4）。
* **"KV Cache 必须落 HBM"弱化**：backing store 通常是 HBM，当前消费的 KV tile / shared KV 可在 SRAM/L2 形成 reuse（第 8 章）。
* **"KV write 天然有 S 长 slack"已撤回**：KV write 能否延迟/合并取决于系统实现（10.8），非算法保证。
* **"Prefill = compute bound / Decode = memory bound"弱化**为典型趋势，并由 6.3 Roofline 定量支撑（6.2）。
* **问答/题库式章节已撤并**：复习问题、问答沉淀等章节的确认知识已迁移进正文，修订痕迹集中于本节。
* **新增系统层（Cache / MSHR / Prefetch / Coalescing / VM-TLB / NoC / Coherency）**：全部收入 §8（8.2–8.10），主链扩展为 `Tensor → Tile/Layout → Cache/Memory Hierarchy → NoC/Coherency → MC-visible Request Stream`；§9 增补 9.0 系统层连接段与跨层不等式，§9.1 Request Stream schema 增加 8 个分析属性。结论标 [SYSTEM-DEPENDENT]，密集保留 [TODO] 学习框架而非填入 textbook 内容（8 章 / 9.0 / 9.1 / 11-19~22）。
* **Technical Correction / Convergence Pass（§8 结构冻结）**：① 文档头统一为唯一 authoritative chain，`HBM Traffic` 不再出现在 MC-visible request 之前；② Cache miss 方向改为 lower-level / downstream，不称 NoC/HN 为 cache"上游"；③ MSHR vs CAM 改为 aggregated outstanding supply 口径，禁止单 slice MSHR depth 与 MC CAM depth 直接比数字；④ MSHR full 行为收紧为"限制需新增 miss state 的请求"，四个是否继续均 [SYSTEM-DEPENDENT]；⑤ Capacity/Conflict miss 分别改为"固定前提下不能仅靠 mapping 消除但可缩小 working set"与"可缓解非必然消除"；⑥ Prefetch Weight/KV 二分保留趋势、补 Paged KV "page 间离散 ≠ page 内随机"；⑦ Coalescing 后果拆为 direct / possible-secondary 两层，与 row hit / channel balance 解耦；⑧ VC/VN 表述去绝对化，deadlock freedom 补 routing/dependency 条件；⑨ NoC congestion vs CAM full 改为 arrival-side vs admission/retirement-side，补 `Observable ≠ Root Cause`；⑩ Ordering 影响改为 subsystem 级并区分 Partition A/B，明确"MC 实现 coherency"≠"coherency 影响 MC performance"；⑪ §8.9 表删除"通常较高优先级"、解除 sequential = high row hit 默认定律；⑫ §8.7 增加诊断层级 boundary diagram；⑬ §8.10 Learning Check 更新为含 MSHR 聚合、Paged KV 双重性、HN/MC ordering partition 等 8 题；⑭ §9.1 标注为 §9.0 的 performance-model abstraction；⑮ A.3 的 MSHR TODO 收紧为 aggregated cache-miss concurrency / NoC deliverable outstanding → MC admitted / scheduler-visible outstanding。**No new knowledge areas added. Section 8 scope frozen.**
* **Final Consistency Pass**：§10 标题与分析链对齐 authoritative chain（输入改为 MC-visible Request Stream，删除模糊 `Traffic`）；删除 sequential = high-row-hit 残留（§10.4），确立 `Sequential Access ≠ High Row-hit Rate`；收紧 Decode outstanding（§10.1）与 memory-bound（§6.3 / §11-12）的过度绝对表述；§8.6 区分通用 VM 机制与 system-dependent 参数；§8.1 区分 General Weight Cache Reuse 与 [BASELINE-0] no-cross-step-residency 假设；A.3 locality TODO 措辞与正文同步。**Section 8 scope frozen——后续转向 §9 request-stream quantification 与 §10 RTL / Model performance evidence。**
* **Section 8 Freeze Final Pass**：removed residual "Decode request stream is naturally sparse" wording（§8.4 与 §10.1 对齐）；separated PagedAttention KV block/page from OS/MMU virtual-memory page（§8.6）；clarified runtime block mapping 与 VA→PA translation 为两个不同层级。**Section 8 frozen.**
* **FlashAttention 收编（4.10.1，A.3 首项完成）**：① 4.10 表 FlashAttention 行由"附录 A.3 TODO"改为结论并标 4.10.1；② FORMULA 行扩写 P-materialize 口径（单层 4 GiB、32 层 128 GiB ≈ 10.7× Model Weight）；③ 新增 4.10.1：naive 浪费定位（Score/P 存储往返，causal mask 三角区通常仍写出）、tiling 循环结构与 SRAM 常驻集合（Q tile + O 累加器 + running (m,l)；K/V tile 仅当次驻留）、online softmax rescale 机制、关键判据"完整 [S,S] 任何时刻不存在于任何层级"、改写环节定位（FLOPs 与算法值域不变，Logical Data Movement 及下游消失）、残余项 K/V 重读放大 S/Br 倍（是否落 HBM 取决于 SRAM/L2，[SYSTEM-DEPENDENT]）、request stream 视角（收益在 Bytes 层面，不必然改善 Request Size / Sequential Run / Stride；Tile Size ≠ Request Size）；④ 结论 9 补 4.10.1 指针；⑤ A.3 移除 FlashAttention TODO。
* **4.10.1 补充循环模型**：按 Q_i × (K_j, V_j) 双重循环抽象补入 Loop 骨架图（Outer Loop 选 Q Tile / Inner Loop 选 KV Tile，K_j 产 Score、V_j 供加权数据 / Online Softmax 使各 tile 的 Score 与 Output Contribution 逐步正确累积 / Q_i 的全部合法 KV 处理完后输出 O Tile），置于"两个机制"之前；"合法"即 causal mask 语义与 4.6 衔接。
* **FlashAttention 定量收尾（4.10.1，FQ1/FQ2 闭环）**：新增"tile 尺寸 × SRAM 预算 × 重读"定量块——working set / 重读倍数 / 潜在重读 / 净收益四个公式；Br=64/128/256 三档表（Br=64 且重读全落 HBM 时净收益归零的临界点）；SRAM 预算→最大对称 tile 公式（256 KiB→T≈187，1 MiB→T=512）与余量来源；落 HBM 判据三条（per-head working set 2·S·D·b_a、H_p 并行膨胀、long context 线性放大 per-head working set）；A.3 的 Memory hierarchy TODO 加 attention 实例指针。
* **Feature-Template Re-architecture Pass（知识优先级重排：概念理解 > Memory 影响 > Controller 视角 > 数量级验证）**：① 0.4 增补 Feature 五段模板与优先级声明（计算推导统一归 A.5）；② §4.10 表与结论行改为结论式，GiB 推导移出正文；③ 4.10.1 重构为五段模板（解决什么问题 / 原始实现的问题 / 核心思想 / Memory 影响 / Controller 视角），循环模型与关键判据保留，Tile-size 张力改为概念陈述（增大 → working set↑ / SRAM↑ / KV reuse↑ / HBM 重读可能↓，受 SRAM/L2 限制）；④ 新增 4.11 Head split vs Tile split（含 Tile ≠ Request Size）；⑤ 5.3 重排为 Capacity / Write / Read 优先、FLOPs / Model Weight 降为不改变项与定量验证，新增 5.4 HBM Controller 视角；⑥ §3 / §4 / §5 / §6 / §8 / §9 / §10 各增"面试一句话总结"；⑦ 6.3 增"数量级验证工具"定位声明；⑧ 新增 A.5 Quantitative Examples（A.5.1 naive attention 完整账；A.5.2 FlashAttention tile × SRAM × 重读：四公式、三档表、SRAM 预算解、落 HBM 判据三条），正文相应处改为指针。公式与结论全部保留，无知识删除；Section 8 仍冻结（§8 仅增总结行，无新知识区）。

* **Architectural Restructure Pass（重构为 workload → traffic → controller 三段式）**：文档身份由“Transformer 学习笔记”重定位为“AI Workload Memory System Model”；章节重构为 §0 定位 / §1 Memory Mental Model / §2 Operator→Memory Behavior / §3 Workload Phase / §4 Optimization Impact（五段模板：FlashAttention、GQA/MQA、Quantization、PagedAttention、MoE）/ §5 Tensor→Request Stream（Layout / Tile / Cache-TLB-NoC 最小影响模型 / Request Stream Schema）/ §6 AI Traffic Classification（新增：Weight Streaming / KV / Activation 画像与 MC 关注点）/ §7 Request Stream→HBM Controller（Outstanding / Mapping / Row Locality / Scheduler / R-W Mixing / Performance Loss Attribution）/ §8 Case Study（新增 3 个面试案例）/ §9 结论汇总（22 条，引用更新）/ §10 附录。原 §8（Cache/TLB/NoC/Coherency）蒸馏为 §5.3 最小影响模型——删除 set/way/tag/replacement、RN/HN/SN/CHI、packet/flit/VC 等教材细节，冻结知识以影响结论形式存活；原 §7 定量推导（12 GiB / 2 GiB / S_c=24K/86K / AI 对比 / R:W）移入 A.5.3；4.10/4.10.1 合并为 §4.1。标记体系、符号表、[BASELINE-0]、22 条结论、A.3 TODO、A.4 修订记录全部保留；核心不等式 `Logical Bytes ≠ MC-visible Request Bytes ≠ Physical HBM Transaction Bytes` 保持为全文核心原则。

### A.5 Quantitative Examples（数量级验证集）

> 定位：正文 [FORMULA] 结论的计算过程存放处。公式用于建立数量级直觉与验证结论，不是学习目标；正文只保留结论与指针。

#### A.5.1 naive attention materialization 的完整账（§4.1 结论的推导）

* Score:[Nq,S,S] = 32×4096×4096×2 B = 1 GiB/层；P 同尺寸，额外一份；
* 数据流：写 Score(1 GiB) → 读 Score(1) → softmax → 写 P(1) → 读 P(1) → PV：写 2 GiB + 读 2 GiB = 4 GiB/层；
* 32 层累计：score-only ≥ 64 GiB ≈ 5× Model Weight；含 P：128 GiB ≈ 10.7× Model Weight；
* causal mask 三角区在 naive 中通常仍被写出（masked 位填 -∞/0），专门优化才减半，量级不变。

#### A.5.2 FlashAttention：tile × SRAM × 重读（§4.1 残余项的推导）

```text
SRAM working set ≈ (2Br + 2Bc)·D·b_a（Q/O/K/V 四 buffer）+ Br·Bc·b_a（score tile，瞬态）
K/V 重读倍数     = S/Br
潜在重读 bytes/层 = (S/Br) × 2 × [S,H]·b_a
净收益/层        = 4 GiB（Score/P 消失）− max(0, 未被片上吸收的重读)
```

baseline（S=4096, D=128, b_a=2 B，对称 tile T=Br=Bc）：

| T | 主 working set（4·T·D·b_a）| K/V 重读倍数 | 潜在重读/层 | 重读全落 HBM 时净收益 |
|---|---|---|---|---|
| 64 | 64 KiB | 64× | 4 GiB | ≈ 0（收益被重读吃光）|
| 128 | 128 KiB | 32× | 2 GiB | −2 GiB |
| 256 | 256 KiB | 16× | 1 GiB | −3 GiB |

SRAM 预算 → 最大对称 tile（解 `2T² + 4·D·b_a·T ≤ SRAM budget`，含 score tile）：256 KiB → T≈187；1 MiB → T=512（精确解）。实际实现取更小：double buffering、FP32 累加（O/统计量 FP32 时 O buffer 翻倍）与 epilogue 都要余量。[SYSTEM-DEPENDENT]

重读是否落 HBM 的判据 [SYSTEM-DEPENDENT]：

* **逐 head 顺序**：per-head K/V working set = 2·S·D·b_a（baseline 2 MiB）；该 head 的 S/Br 次 Q-tile 迭代间反复访问同一 K/V → 大概率 L2 常驻 → 重读多数被吸收；
* **H_p 个 head/batch 并行**：aggregate working set ≈ H_p × 2·S·D·b_a；几十 MiB 量级 L2 下约十几~几十个 head 到顶，且 L2 同时被 Weight streaming / activation 争夺，实际余量更低；
* **Long context 放大**：per-head working set 随 S 线性增长（S=16384 → 8 MiB/head；S=65536 → 32 MiB/head）——重读吸收能力随 context 增长而下降，长 context 下重读更可能真正落 HBM。

#### A.5.3 Baseline 定量数字（[BASELINE-0] 代入结果）

**容量与 traffic：**

* Model Weight = L × (4H² + 2HI) × b_w = 12 × 4096² × 32 × 2 = **12 GiB**（≈12.9 GB decimal）；LM Head [H,V]·b_w ≈ 250 MiB（约 Weight 的 2%）与 Norm / Embedding 不计入主公式；
* Hidden State = H·b_a = 8 KiB/token；Prefill hidden [S,H]·b_a = 32 MiB；最大中间 activation 为 MLP intermediate [S,4H]·b_a = 128 MiB；
* KV/token = 2LH·b_kv = **512 KiB**；KV Capacity（B=1, S=4096）= B×S×2LH·b_kv = **2 GiB**（随 B、S 线性增长，serving 的 capacity 主导项）；
* Decode bytes/token ≈ 12 + 2 = **14 GiB**（Weight 占 ~86%；KV write 512 KiB 可忽略但存在于 R/W mixing，§7.5）；
* Attention core MAC = 2S²H / 层——Prefill 时唯一随 S² 增长的 compute 项；naive attention 的 Score/P 完整账 → A.5.1。

**Arithmetic Intensity（简化式，[ASSUMPTION] 只计 Weight traffic）：**

* AI_weight ≈ M FLOP/B（FP16）：Decode B=1 → ≈1；Prefill S=4096 → ≈4096——约三个数量级，决定两者 roofline 落点（§2.1 / §3）；真实 AI 低于此值，operational point 依赖真实硬件 Peak Compute / HBM BW。[TODO]

**Crossover（Weight read = Historical KV read）：**

```text
MHA、b_w = b_kv：S_c = 6H = 24576 ≈ 24K
一般式：S_c = 6H·(b_w / b_kv)；例：weight-only FP8 + KV FP16 → S_c = 3H = 12K
GQA（两边都变，须重推）：S_c(r) = [(10+2r)/(2r)]·H·(b_w/b_kv)
r = 1/4、b_w = b_kv → 21H ≈ 86K
```

（历史版本曾按“weight 维持 12H² 不变”推得 ≈96K，与 weight 公式 (10+2r)H² 不一致，已修正；见 A.4。）

**R:W（R/W mixing，§7.5）：**

* Decode：14 GiB : 512 KiB ≈ **28000 : 1**（写占比极小，写聚合几乎无成本）；
* Prefill（read 项只有 Weight）：12 : 2 = **6 : 1**（写聚合收益与 WDB 压力都更大）。（历史版本 7:1 系误计 decode 口径 KV read，已修正；见 A.4。）

**Batch 示例（前提与机制见 §3.4）：**

* B=8：Weight traffic/token = 12 GiB / 8 = 1.5 GiB；
* 4×(S=512) + 4×(S=8192) 的 batch：总 KV read = 512 KiB × (4×512 + 4×8192) = **17 GiB**，其中 S=8192 的 4 条占 ~94%——long-tail sequence 主导 KV bandwidth；weight 摊薄与各 sequence 的 S 无关。

**Required BW 例：**

* EffectiveBW = 14 GiB/token × 20 token/s = 280 GiB/s（有效值）；PeakBW ≥ EffectiveBW / ηmemory（η 由 access pattern 与 controller 机制共同决定，是结果不是常数）。
