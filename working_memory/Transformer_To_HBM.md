# Transformer → HBM：HBM Controller 工程师的 Transformer Workload 系统模型

> **文档身份**：一名 HBM Controller / Memory System 工程师，为理解 AI workload、分析 HBM 性能而建立的 Transformer workload 系统模型。
>
> **主线**：全文沿同一条认知链展开；新概念进入本文前，先检验它改变这条链的哪一环。

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
Tile / Layout / Coalescing
↓
Cache / SRAM / TLB
↓
NoC / Coherency
↓
MC-visible Physical Request Stream
↓
Memory Controller
↓
DRAM Commands / HBM Transactions
↓
Effective BW / Latency
↓
Application Performance
```

即：`Transformer → Tensor → Logical Data Movement → Tile/Layout → Cache/TLB → NoC/Coherency → MC-visible Request → MC → HBM Transaction → Performance`

这是全文**唯一 authoritative chain**（不保留第二套链）。明确区分：

```text
Logical Bytes
≠ MC-visible Request Bytes
≠ Physical HBM Transaction Bytes
```

`HBM Traffic` 一类的 DRAM 层量词只出现在 MC 之后（DRAM Commands / HBM Transactions），不再出现在 `MC-visible request` 之前造成层级歧义。

**系统层扩展（第 8 章）**——§8 在 `Logical Data Movement` 与 `MC-visible Physical Request Stream` 之间补入 Cache / VM / NoC / Coherency，回答本文核心问题：

> Transformer 算法告诉我有多少 logical bytes，但这些 bytes 为什么并不会一比一成为 HBM traffic？

本文新增内容只负责解释这条中间层：**algorithmic bytes 如何经过 Cache / VM / NoC / Coherency，变成 MC 真正看到的 physical request stream**；不重写 Transformer 算法、DRAM protocol、MC microarchitecture（分别由正文 / `Memory_Protocal.md` / `DDR_Controller_Architecture.md` 管理）。

---

## 0. 文档定位、符号与分析方法

### 0.1 文档目标

本文不是 Transformer 算法教材。目标是把 Transformer workload 翻译成 Memory System workload，最终能够回答：

> 一个 AI workload 为什么需要这么多 HBM Capacity / Bandwidth？这些 Byte 以什么模式访问 HBM？Controller 的哪些机制决定这些 Byte 以多高效率被服务？

### 0.2 分析边界

算法知识只学习到足以解释以下要素的程度：

```text
Tensor / Compute / Capacity / Traffic / Locality / Reuse / Parallelism / HBM Behavior
```

不覆盖 optimizer、loss、训练收敛理论。判断一项 AI 知识是否进入本文的唯一标准：**它是否改变 Tensor、Compute、Capacity、Traffic、Locality 或 Parallelism。**

### 0.3 符号表

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

b_w / b_kv / b_a 的区分使 Weight / KV / Activation 可以取不同 precision（如 Weight INT8 + KV FP16）而无需重写公式体系。

Baseline 数值见第 7 章 [BASELINE-0]：H=4096, L=32, Nq=Nkv=32, D=128, I=4H, V=32000, b_w=b_kv=b_a=2 B（FP16）。

单位约定：正式推导统一使用 KiB / MiB / GiB（2^10 进制）；decimal（kB/MB/GB）只在括号中补充，不与二进制单位混用。

### 0.4 统一分析框架

每个 Operator / Feature 按以下角度分析：

```text
1.  解决什么问题
2.  Input / Output Tensor
3.  Shape
4.  FLOPs / MAC
5.  Weight
6.  Activation
7.  Capacity
8.  Logical read/write bytes
9.  Physical HBM traffic
10. Access pattern
11. Reuse opportunity
12. 对 HBM / Controller 的影响
```

三个必须始终区分的量：

```text
Tensor Size                        算法视角的数据体量
≠ Algorithmic Memory Bytes         含读写放大前的逻辑搬运量
≠ Physical HBM Transaction Bytes   经 cache/prefetch/fusion/映射后的实际事务量
```

标记体系（[ALGO] [FORMULA] [ASSUMPTION] [MODEL-SPECIFIC] [SYSTEM] [SYSTEM-DEPENDENT] [TODO]）定义见附录 A.1，只在易误解处使用。

---

## 1. LLM Inference 全局数据流

```text
Text
 ↓
Tokenizer
 ↓
Token IDs
 ↓
Embedding
 ↓
x^(0)
 ↓
Transformer Layer 0 .. L-1
 ↓
Final Norm
 ↓
LM Head
 ↓
Logits
 ↓
Softmax / Sampling
 ↓
Next Token
```

各环节的 Memory 定位：

* **Tokenizer**：文本 → Token ID 整数序列。由 CPU/runtime 完成，对 accelerator 的 HBM 压力通常可忽略。
* **Embedding**：Token ID 到 [V,H] 表的行查找，取出该 token 的初始 hidden state [1,H]。Embedding Table 本身是 Weight（只读）。
* **Hidden State**：token 在第 l 层的内部表示 x^[l] ∈ [1,H]，是层间传递的核心 Activation。
* **Transformer Layers**：反复执行 Attention + MLP（第 3、4 章），是 Weight 与 KV Cache 的主要消费者。
* **LM Head**：final hidden state × [H,V] Weight → Logits [1,V]。仍是一次 Activation × Weight；Decode 时其 Weight read 不可忽略（baseline [H,V]b_w = 4096×32000×2 B = 262,144,000 B ≈ 250 MiB）。
* **Logits → Sampling**：Temperature / Top-K / Top-P → Next Token ID。数据规模远小于 GEMM 与 KV Cache，一般不是 HBM 主瓶颈。

**一个 Decode Step = 生成一个新 token**：当前 token 经全部 L 层 + LM Head + Sampling 得到下一个 token，再进入下一轮，逐 token 循环。

**Prefill 与 Decode 的生命周期位置**：prompt 的 S 个 token 一次性并行过网络 = Prefill；之后逐 token 生成 = Decode。两者对 Memory System 的压力完全不同（第 6 章）。

---

## 2. Transformer 中的数据对象

### 2.1 Token ID

vocab 内的整数索引。自身几乎不占存储与带宽，是 Embedding 查找的行号和 LM Head 输出的下标。

### 2.2 Hidden State

x^[l] : [B,S,H]（Prefill）/ [B,1,H]（Decode）。FP16 下单个 token 为 H·b_a = 8 KiB（baseline）。是层间传递的核心 Activation。

### 2.3 Activation

一次 inference 中动态产生的中间数据：hidden state、Q/K/V、attention 输出、MLP intermediate 等。

特点：动态产生、生命周期短、应尽量保存在 SRAM / local buffer、不是所有 activation 都需要写 HBM。

关系：`Hidden State ⊂ Activation`。

### 2.4 Weight

训练后固定的参数：WQ/WK/WV/WO、W1/W2、Embedding Table、LM Head Weight、Norm scale。

特点：容量大（baseline Model Weight ≈ 12 GiB）、inference 阶段只读、常驻 HBM、Decode 时被反复 streaming 读取。

### 2.5 KV Cache

需要跨 token 生命周期保存的特殊 Activation。

* **K/V 缓存的原因**：生成 token t 时，Q_t 需与全部历史 token 的 K/V 计算 attention；若不保存，每生成一个 token 都要重算所有历史 K/V。本质：**用 Memory Capacity 换 Compute**。
* **Q 不缓存的原因**：Q_t 只服务当前 token 的计算；t+1 步的 Q 是全新向量，历史 Q 无复用价值。
* **每 layer 独立 KV Cache**：各层 K/V 语义不同，互不可替代。
* **容量随 B、S 线性增长**（7.6）。

### 2.6 Tensor Shape / Precision / Byte

`Bytes = element 数 × b`，Precision 直接缩放一切 Byte 结论；Weight / KV / Activation 可分别取 b_w / b_kv / b_a。

| 数据对象 | Shape（单 sequence）| Baseline Byte |
|---|---|---|
| Hidden State / token | [1,H] | H·b_a = 8 KiB |
| MLP intermediate / token | [1,4H] | 4H·b_a = 32 KiB |
| KV / token / layer（MHA）| K,V 各 [Nq,D] | 2H·b_kv = 16 KiB |
| KV / token（L 层合计）| — | 2LH·b_kv = 512 KiB |
| Model Weight | — | 12LH²·b_w ≈ 12 GiB |

三类对象在 HBM 行为上的差异：

| | Weight | Activation | KV Cache |
|---|---|---|---|
| 生命周期 | 永久（inference 只读）| 单 step 内 | 跨 token、随序列增长 |
| 理想驻留 | HBM（容量决定必须 streaming）| SRAM / RF | 主体 HBM（backing store），hot tile 可驻留 SRAM/L2 |
| 主要流量 | Decode 反复读 | 理想接近零 HBM | 读历史 + 追加写 |

---

## 3. Transformer Layer 完整数据流

一个 Layer 的执行顺序（通用排布；Norm 位置随模型存在变体）：

```text
x
│
├─ Norm
│
├─ Attention
│
├─ Residual
│
├─ Norm
│
├─ MLP
│
└─ Residual
 ↓
next layer
```

### 3.1 Norm

作用：对 hidden state 做 per-token 归一化，稳定各层分布，使后续 GEMM 输入 scale 可控。

Memory Behavior 视角：

* 计算形态：reduction（均值/方差）+ element-wise 缩放；
* 自带 weight（scale/shift）为 [H] 量级，KiB 级，可忽略；
* compute 强度不高，性能上更受 activation 搬运（读入/写回）影响；
* 常与相邻算子 fusion，避免 activation 落 HBM 一个来回。

### 3.2 Residual

```text
output = input + block(input)
```

* block 的输入（原 hidden state）必须保留到 block 输出返回后相加；
* 最理想情况：原 hidden state 留在 SRAM/Buffer，addition 不经过 HBM；
* 容量不足 spill 到 HBM 时，才产生额外一次写 + 一次读 traffic。

### 3.3 Attention（overview）

token 之间交换信息的模块：每个 token 从其他 token 收集信息。内部数据流在第 4 章完整展开。

### 3.4 MLP

```text
H → I → H（baseline：I = 4H）
[S,H] × W1[H,I] → [S,I] → × W2[I,H] → [S,H]
```

* 两次 GEMM（Activation × Weight），中间经非线性；
* Attention 输出的 activation 可留片上进入 MLP；但 MLP 自身需要读取大量 Weight（baseline 8H²/layer，7.3）——**activation 留片上不等于 MLP 不吃 HBM**；
* MLP Weight 是模型参数的主要组成部分（baseline 单层 12H² 中的 8H²）；
* MLP intermediate 是单 token 最大的 activation：baseline [1,4H] = 32 KiB；Prefill 时 [S,4H] = 128 MiB，能否留片上取决于 buffer 容量（第 8 章）。

[MODEL-SPECIFIC] 现代 LLM 常采用 gated MLP / SwiGLU 等结构，其 projection 数量和 intermediate size 与本 baseline 的两矩阵 H→4H→H 不同，因此 Model Weight / FLOPs 必须根据实际矩阵重新计算。

---

## 4. Attention 完整数据流

按执行顺序：

```text
Hidden State X
↓
QKV Projection
↓
Head reshape
↓
RoPE(Q, K)
↓
QK^T
↓
Causal Mask
↓
Softmax
↓
P × V
↓
Concat
↓
Output Projection
```

### 4.1 Q / K / V 的含义

直觉定义：

```text
Q：当前 token 在找什么
K：当前 token 提供什么可被匹配的特征
V：被关注后提供什么信息
```

Q + K 决定"看谁"，V 决定"看到什么"。

### 4.2 QKV Projection

```text
X_Q = X × WQ    WQ : [H,H]
X_K = X × WK    WK : [H,H]
X_V = X × WV    WV : [H,H]
```

* 三个 projection 均为 Activation × Weight GEMM；可 fused 为 [H,3H] 大 GEMM 一次完成（减少 activation 读次数）；
* Multi-head 不要求 projection 前物理拆 head：先产出 [·,H]，再 reshape 为 [·,Nq,D]；
* Weight 合计 3H²（7.2 的组成部分）。

### 4.3 Positional Encoding / RoPE

**为什么需要位置编码**：Token ID / Embedding 只表达"是什么"，不表达 token 位于 sequence 的哪个位置、与其他 token 的相对位置。Attention 本身对输入集合是置换不变的，需要额外注入 positional information。

**在数据流中的位置**（典型逻辑）：

```text
QKV Projection → Head reshape → RoPE(Q, K) → QK^T → Softmax → P × V
```

RoPE 通过旋转操作把位置（尤其相对位置）信息编入 Q/K，使 score 依赖 token 间的相对距离。RoPE 作用在 **Q 与 K** 上，**不作用于 V**。

**Memory Behavior**：

* element-wise / rotation 类 compute，没有 H² 级大 Weight；
* 数据量与计算量均为 O(S·H) 级，应尽量片上完成（紧接 QKV projection / reshape 之后）；
* 通常不是 HBM 主流量。

[MODEL-SPECIFIC] KV Cache 中保存的是供未来 attention 使用的 K 表示；位置变换发生在 projection 后、入 cache 前，还是读取后应用，依具体模型 / runtime 实现而定，不作为所有模型的统一假设。

### 4.4 Multi-Head

```text
H = Nq × D        baseline: 32 × 128 = 4096
```

projection 输出 [S,H] reshape 为 [S,Nq,D]：

* **token 视角**：每个 token 有 Nq 个 head，每个 head 在 D 维子空间做匹配；
* **head 视角**：每个 head 独立做一遍小 attention（[S,D] 级），head 之间无依赖，可完全并行。

### 4.5 QK^T

单个 head：

```text
Q_h:[S,D] × K_hᵀ:[D,S] → score:[S,S]
MAC = S²D
```

Nq 个 head：

```text
Nq × S²D = S²H MAC
```

MAC 与 FLOPs：1 MAC = 2 FLOPs（乘 + 加）。本文按 MAC 计量并注明。

### 4.6 Causal Mask

Prefill 与 Decode 的 mask 需求完全不同，不能混为一谈。

**Prefill**：同时处理 S 个 Query：

```text
Q:[S,D] × K:[D,S] → Score:[S,S]
```

必须阻止 token i 访问未来 token j>i，存在真实的三角 masked region：

```text
✓ × × ×
✓ ✓ × ×
✓ ✓ ✓ ×
✓ ✓ ✓ ✓
```

处理方式：masked 位置的 score 置 -∞（或大负值），softmax 后对应 probability = 0；高性能实现不会把完整 causal probability matrix 写 HBM。

**Decode**：每步只有一个新 Query：

```text
Q_new:[1,D] × K_history:[D,S] → Score:[1,S]
```

KV Cache 中的位置全部是已生成的历史合法位置，**通常不存在 Prefill 那种 [S,S] 规模的上三角 masked region**。

因此：**不能把 HBM 上的大量 zero write 简单归因于 Decode 的 causal mask**（9.6）。

### 4.7 Softmax

```text
P_i = e^{score_i} / Σ_j e^{score_j}
```

作用：把每行 score 归一化为和为 1 的 attention weight——"每个位置分到多少注意力"。数值实现细节（max 减除等）不影响 memory 行为。

### 4.8 P × V

单个 head：

```text
P_h:[S,S] × V_h:[S,D] → out_h:[S,D]
MAC = S²D
```

Nq 个 head 合计 S²H MAC。Attention core 合计：

```text
QK^T + PV ≈ 2S²H MAC
```

Prefill 时这是唯一随 S² 增长的 compute 项，是 prefill compute 倾向的主要来源（6.1）。

### 4.9 Output Projection

各 head 输出 concat 回 [S,H]，再过 WO：

```text
[S,H] × WO[H,H] → [S,H]
```

WO 是 attention 的第 4 个 H² Weight（7.2）。

### 4.10 Attention 中 Activation 是否写 HBM

同一算法，三种实现档次：

| 实现 | score/P 矩阵去向 | Prefill 额外 traffic（baseline，每层）|
|---|---|---|
| naive（无 fusion）| 完整写 HBM、读回 | score [32,4096,4096]×2 B = 1 GiB 写 + 读回 ≥ 2 GiB（若 P 也 materialize 可达 ~4 GiB）|
| fused（算子级）| 留片上 | ≈ 0 |
| FlashAttention 类 | 不 materialize（附录 A.3 TODO）| ≈ 0 |

[FORMULA] baseline 下 naive 实现 32 层累计 score 相关 traffic ≥ 64 GiB ≈ 5× Model Weight——**attention 实现方式能完全改写 HBM 结论**。

Decode 时 score 仅 [Nq,1,S] = 256 KiB/层，无论实现方式都不构成 traffic 大项。

---

## 5. MHA / GQA / MQA

### 5.1 问题：KV 的 Memory Cost

MHA 下 KV/token = 2LNqD·b_kv（7.5），随 L、S、B 线性增长。Long context 与大 batch serving 中，KV capacity 与 KV read 成为第一压力源。减少 KV head 数（Nkv < Nq）是直接手段。

### 5.2 三种结构

统一记号：`r = Nkv / Nq`。

```text
MHA : Nkv = Nq        baseline 32 Q / 32 KV
GQA : 0 < Nkv < Nq    例如 32 Q / 8 KV，group = Nq/Nkv = 4
MQA : Nkv = 1         32 Q / 1 KV
```

**关键实现语义 [ALGO]**：MQA 不是从 32 个 KV head 中"选中 K0/V0 复用"，而是 projection 阶段就只放 `W_K:[H,D]`、`W_V:[H,D]`，直接只产生一组 shared K/V。GQA 同理：projection 阶段只生成 Nkv 组 K/V，每组分给 Nq/Nkv 个 query head 共用。

结构演化逻辑：

```text
MHA（KV 成本高）
↓ 为什么成本高：KV/token 与 Nq 成正比
MQA（Nkv=1，KV 成本最低）
↓ 为什么过度共享可能影响表达能力：不同 head 的 K/V 语义被强制合并 [ALGO]
GQA（Nkv 居中）
↓ 质量 / Memory 折中：以组为单位共享
```

### 5.3 五方面对比

#### 1. FLOPs

* QK^T 与 PV 的 MAC 由 Nq 决定（4.5 / 4.8 的 S²H），与 Nkv 无关——**KV head 减少不会同比减少 attention core FLOPs**；
* 下降的是 K/V projection FLOPs：WK/WV 从 [H,H] 缩为 [H,Nkv·D]。

#### 2. Model Weight

per layer attention weight：

```text
MHA : WQ+WK+WV+WO = 4H²
GQA : WQ+WO = 2H²；WK+WV = 2·H·Nkv·D = 2rH²
      合计 2(1+r)H²
```

加 MLP（baseline I=4H 时为 8H²，一般式 2HI 见 7.3）：

```text
Total/layer ≈ (10 + 2r)H² elements      [FORMULA，baseline 假设下；× b_w 为 Byte]
```

r=1 → 12H²（退化为 MHA）；r=1/4 → 10.5H²。

#### 3. KV Capacity

```text
每层每 token：K:[Nkv,D] + V:[Nkv,D] = 2NkvD elements
KV/token = 2·L·Nkv·D·b_kv = 2LrH·b_kv
```

r=1/4 时为 MHA 的 1/4（baseline 512 KiB → 128 KiB）。

#### 4. KV Write

```text
KV Capacity, Unique KV Write Bytes ∝ r      [FORMULA]
```

* **算法上**：unique KV 数据从 projection 源头就减少，KV capacity 与 unique KV write bytes 均按 r = Nkv/Nq 下降（baseline：每层每 token 16 KiB → 4 KiB）；
* **正常不做冗余复制的实现中**：HBM write traffic 近似按 r 下降；
* 但 **physical HBM transaction bytes 仍可能受 padding、alignment、transaction granularity、replication、layout 等影响**，不能写成严格的物理 r 倍下降。

#### 5. KV Read

**Capacity saving ≠ Physical HBM read saving。**

理论期望：HBM read once → serve 组内多个 Q head：

```text
Q0 ↘
Q1  → 同一份 KV（片上复用）→ HBM 只 read 1 次
Q2 ↗
Q3 ↗
```

若实现为每个 Q head 独立扫 KV 且片上无复用：

```text
Q0 → read KV
Q1 → read same KV
Q2 → read same KV
Q3 → read same KV
```

则 capacity 降至 r，但 physical HBM read 不降。KV read 是否兑现 r 倍节省取决于 accelerator 的 kernel tiling 与 L2 行为（9.5）——这是 HBM Controller 工程师视角必须保留的区分。

---

## 6. Prefill vs Decode Workload

### 6.1 Prefill

输入 `X:[S,H]`，S 个 token 并行过网络。

* 所有 GEMM 的 M 维 = S：`[S,H]×[H,H]`，一份 Weight 服务 S 个 token；
* Weight reuse 高（6.4），Arithmetic Intensity 高（6.3）；
* attention core 出现唯一随 S² 增长的项（4.8），S 增大时 compute 增长快于 traffic；
* 典型倾向：**compute-intensive**（定量依据见 6.3）。

### 6.2 Decode

输入 `X:[1,H]`，逐 token 生成。

* GEMM 退化为 GEMV：`[1,H]×[H,H]`，一份 Weight 只服务 1 个 token；
* Weight reuse 差 → Weight streaming 成为第一流量（7.7）；
* 每个 token 读全部历史 KV（7.8），context 越长流量越大；
* 每步追加写新 KV（7.9）；
* 典型倾向：**memory-bandwidth-intensive**（定量依据见 6.3）。

[SYSTEM-DEPENDENT] `Prefill = compute bound / Decode = memory bound` 是典型趋势，不是定律。实际瓶颈取决于 Batch、Context、Quantization、硬件 compute:BW 比、kernel 实现（含 fusion）。长 context 的 prefill 也可能被 KV/score traffic 拉向 memory-bound。

### 6.3 Arithmetic Intensity / Roofline

把 Compute 与 HBM BW 连接起来的核心量：

```text
Arithmetic Intensity (AI) = FLOPs / Bytes
```

以最简单 GEMM `X[M,K] × W[K,N]` 为例：

```text
FLOPs ≈ 2MKN
只计 Weight HBM read：WeightBytes = KN·b_w
AI_weight = 2MKN / (KN·b_w) = 2M / b_w
```

FP16 Weight（b_w = 2 B）：

```text
AI_weight ≈ M FLOP/B
```

* Decode B=1：M = 1 → AI_weight ≈ 1 FLOP/B
* Prefill S=4096：M ≈ 4096 → AI_weight ≈ 4096 FLOP/B

[ASSUMPTION] 这是只计 Weight traffic 的简化直觉公式；完整 AI 还须计入 activation、KV、output 等 Bytes，真实 AI 低于此值。

Roofline：

```text
Performance ≤ min( PeakCompute, MemoryBW × AI )
```

* AI 低 → 性能更容易被 Memory BW 限制（memory-bound）；
* AI 高 → 性能更容易被 Compute Peak 限制（compute-bound）。

由此把 6.1 / 6.2 的倾向描述定量化：Prefill 的 M=S 使 AI 比 Decode 高约 3 个数量级，通常落在 compute-bound 一侧；Decode B=1 的 Weight arithmetic intensity 极低，因此在现代高 compute:bandwidth 比的 accelerator 上**通常强烈倾向 memory-bound**——但实际 operational point 仍取决于完整 traffic accounting、batch、context length、quantization、kernel fusion、cache reuse 以及硬件 Peak Compute / HBM BW，**不能仅由 M=1 判定**（附录 A.3 TODO）。

### 6.4 Weight Reuse 的精确定义

> 一个从 HBM 读出的 Weight Byte 能服务多少 token 的计算。

| 场景 | Reuse |
|---|---|
| Prefill | ≈ S |
| Decode, B=1 | ≈ 1 |
| Decode, B=B | ≈ B |

实现前提：B 个 token 必须真的组成一次 M=B 的 GEMM 同时执行；各 sequence 步调不一、串行执行时 reuse 不成立（6.5）。

per-step 的 weight HBM 读量本身几乎相同（≈ 一遍 Model Weight），差别在于 per-token 被多少 token 摊薄——prefill 与 decode 的 per-token weight traffic 相差 S 倍。Reuse 与 6.3 的 AI 是同一件事的两个侧面：AI_weight = 2 × Reuse / b_w。

### 6.5 Batch / Continuous Batching

结论 [FORMULA，前提见下]：Batch=8 时 Weight traffic/token = 12 GiB / 8 = 1.5 GiB。

成立的全部前提：

1. **时间对齐**：B 个 sequence 的当前 token 拼成一次 M=B 的 GEMM；
2. **Weight 跨 step 不驻留缓存**：每 step 从 HBM 重读（12 GiB ≫ L2，物理上近似成立，仍属假设）；
3. **Batch 只摊薄 Weight，不摊薄 KV**：总 KV read = Σ 2LS_i·rH·b_kv，各 sequence 的 KV 属于自己；
4. 单一模型一份 weight（无 multi-adapter 干扰）；
5. GEMM M 维无 padding 浪费。

最先被打破的是 1：请求异步到达/结束，静态 batch 内出现空位。**Continuous Batching** 的存在动机即维持前提 1：sequence 结束立即补入新 sequence，维持有效 M。

补充结论：

* 不同 sequence context length 不同：`4×(S=512) + 4×(S=8192)` 的 batch，总 KV read = 512 KiB × (4×512 + 4×8192) = **17 GiB**，其中 S=8192 的 4 条占 ~94%——**long-tail sequence 主导 KV bandwidth**，而 weight 摊薄与各 sequence 的 S 无关。
* Continuous Batching 补入的新 sequence S 小、KV read 贡献小：对新客，weight 是全额成本、KV 几乎免费。

### 6.6 Throughput vs Latency

6.5 的 `Weight bytes/token ≈ ModelWeight/B` 是 aggregate throughput accounting，它**不意味着单 sequence 的 TPOT 自动降 B 倍**。

设一个 Decode Step 耗时 T_step。Batch=B 时该 step 同时产出 B 个 output token：

```text
AggregateTokenThroughput = B / T_step
TPOT（batch 内单条 sequence）≈ T_step
```

Batch 的收益是：

```text
提高 aggregate throughput
提高 Weight reuse
提高 accelerator utilization
```

而不是"单请求 latency 无条件降低 B 倍"（T_step 往往还随 B 增大，TPOT 甚至可能变差）。[SYSTEM-DEPENDENT]

三个 serving 指标的归属：

```text
TTFT       = Time To First Token    → 主要关联 Prefill
TPOT       = Time Per Output Token  → 主要关联 Decode
Throughput = aggregate output tokens / s
```

serving scheduler 与 Continuous Batching 的完整机制保留为 TODO（附录 A.3）。

---

## 7. Baseline Model：定量推导

```text
[BASELINE-0]
Architecture       = Decoder-only
Attention          = MHA
H                  = 4096
L                  = 32
Nq = Nkv           = 32
D                  = 128
S                  = 4096
B                  = 1
MLP                = H → 4H → H
Precision          = FP16（b_w = b_kv = b_a = 2 B）
Weight residency   = cannot persist across decode steps
Activation spill   = ignored unless noted
Attention traffic  = ideal fused assumption unless noted
LM Head            = excluded from main 12H² formula unless stated
```

更换任一假设（GQA、其他 L/H/I、Weight 与 KV 不同 precision）必须重新推导，公式不可直接移植。

### 7.1 Hidden State Bytes

```text
x:[1,H] → Bytes = H·b_a = 4096×2 = 8 KiB / token
```

Prefill 整体 hidden activation：[S,H]·b_a = 32 MiB；最大中间 activation 为 MLP intermediate [S,4H]·b_a = 128 MiB。

### 7.2 Attention Weight

```text
WQ + WK + WV + WO = 4 × H² = 4H² elements = 4H²·b_w Byte
```

### 7.3 MLP Weight

```text
baseline（I = 4H）：W1:[H,4H] + W2:[4H,H] = 8H² elements
一般式：W1:[H,I] + W2:[I,H] → MLP Parameters = 2HI elements
```

只有 I = 4H 时才有 8H²。I 不同的模型（含 gated MLP / SwiGLU，3.4）必须按实际 I 重算。

### 7.4 Model Weight

```text
ModelWeight = L × (Attention 4H² + MLP 2HI) × b_w
baseline I = 4H：
            = L × 12H² × b_w = 12 × 4096² × 32 × 2 = 12 GiB（≈ 12.9 GB，decimal）
```

**12H² / 12LH²b_w 是 [BASELINE-0]（I=4H、两矩阵 MLP）的结果，不是所有 Transformer / LLM 的通用公式。**

主公式不含 LM Head（[H,V]·b_w = 262,144,000 B ≈ 250 MiB，约 Weight 的 2%）与 Norm/Embedding（量级更小）——引用 12 GiB 时注意这是近似。

### 7.5 KV / token

```text
每层每 token：K:[Nq,D] + V:[Nq,D] = 2·Nq·D = 2H elements（MHA：Nkv×D = H）
KV/token = 2LH·b_kv = 2×32×4096×2 = 512 KiB
```

### 7.6 KV Capacity

```text
KVCapacity = B × S × KV/token = B × S × 2LH·b_kv
B=1, S=4096 → 4096 × 512 KiB = 2 GiB
```

随 B、S 线性增长。Weight（12 GiB）固定，KV 随负载增长——serving 的 capacity 主导项。

### 7.7 Decode Weight Read

```text
每个 decode step 读一遍全部 Weight ≈ ModelWeight = 12 GiB / token
```

前提：weight 不跨 step 驻留（[BASELINE-0]）；batch 摊薄见 6.5。

### 7.8 Decode Historical KV Read

当前 token 与全部 S 个历史 token 做 attention，每层读入全量历史 K/V：

```text
HistoricalKVRead = S × KV/token = S × 2LH·b_kv = 2LSH·b_kv
S=4096 → 4096 × 512 KiB = 2 GiB / token
```

### 7.9 New KV Write

当前 token 计算出的 K/V 追加入 cache：

```text
NewKVWrite = KV/token = 2LH·b_kv = 512 KiB / token（MHA）
GQA：2LNkvD·b_kv = 2LrH·b_kv
```

### 7.10 Decode Bytes / token

```text
Bytes/token ≈ WeightRead + HistoricalKVRead（+ NewKVWrite）
            ≈ 12LH²·b_w + 2LSH·b_kv
S=4096 → 12 + 2 = 14 GiB（Weight 占 ~86%）
```

Write 项 512 KiB 相对可忽略，但存在于 R/W mixing（第 10 章）。

### 7.11 Required Effective HBM BW

```text
EffectiveBW = Bytes/token × tokens/s
例：14 GiB/token × 20 token/s = 280 GiB/s（有效值）
```

### 7.12 Peak BW

```text
PeakBW ≥ EffectiveBW / ηmemory
```

ηmemory < 1 的来源：access pattern 效率（row hit 率、R/W 切换、bank 并行度利用）、refresh 开销等（第 10 章）。η 是**结果**不是常数：由 workload access pattern 与 controller 机制共同决定。

### 7.13 Weight / KV Crossover

令 Decode Weight Read（7.7）= Historical KV Read（7.8），MHA：

```text
12LH²·b_w = 2LSH·b_kv
S_c = 6H · (b_w / b_kv)
```

baseline（b_w = b_kv）退化为 `S_c = 6H = 24576 ≈ 24K`。含义：S < S_c 时 weight read 主导；S > S_c 时 KV read 主导。

**Precision 是否影响 crossover，取决于 Weight 和 KV 是否采用相同 precision**：

* b_w = b_kv：约去，crossover 与 precision 无关；
* b_w ≠ b_kv：按 b_w/b_kv 缩放。例：weight-only 量化到 FP8、KV 保持 FP16，b_w/b_kv = 1/2 → S_c = 3H = 12K（weight 减半使 KV 更早反超）。

GQA：等式两边都变，**必须重推**：

```text
L·(10+2r)·H²·b_w = 2L·S·r·H·b_kv
S_c(r) = [(10+2r) / (2r)] · H · (b_w / b_kv)

r = 1,   b_w = b_kv → 6H           （退化回 MHA baseline）
r = 1/4, b_w = b_kv → 21H ≈ 86K
```

GQA 把 crossover 从 24K 推到约 86K：KV read 更难成为主导项。（历史版本曾按"weight 维持 12H² 不变"推得 ≈96K，与 5.3-2 不一致，已修正；precision 维度的修正见附录 A.4。）

---

## 8. Memory Hierarchy 与数据驻留

### 8.1 片上层级与三类数据的驻留

```text
Register / RF
↓
SRAM / Local Buffer
↓
L2 / LLC
↓
HBM
```

三类数据对象的典型驻留路径：

```text
Weight    : HBM → SRAM → Compute          （容量决定必须 streaming）
Activation: Compute → SRAM → Compute      （理想不回 HBM）
KV Cache  : Compute → HBM（backing store）→ SRAM/L2 → Compute
```

KV Cache 的长期 backing store 通常是 HBM——其总容量远大于片上 SRAM/L2。但这 **≠ 每一次 KV consumer 都直接访问 HBM**：当前正在消费的 KV tile、hot working set、shared KV 可以暂存在 SRAM/L2/Register 中形成 temporal reuse：

```text
HBM KV Cache
     ↓
L2 / SRAM / Local Buffer
     ↓
Attention Compute
```

对于新产生的 KV：

```text
Compute ─┬→ 当前 attention / local reuse
         └→ append 到 HBM KV Cache
```

核心意识：

```text
Compute ≠ HBM Traffic
Tensor Size ≠ HBM Traffic
```

决定"算法 Tensor"与"HBM Transaction"差距的机制：

* **Tiling**：把大 tensor 切成 SRAM 可容纳的 tile 逐块计算（Prefill MLP intermediate 128 MiB 远超典型 buffer，必须 tile）；
* **Reuse**：一个数据 tile 驻留期间被尽可能多的计算消费（weight 驻留服务 tile 内全部 token/batch）；
* **Cache**：对 KV 的 hot tile 复用（含 GQA shared KV，5.3-5）；对 Weight，cache/SRAM 在具体 accelerator 中**可能**提供跨 tile / 跨 operator 甚至跨 decode step 的复用，取决于 cache capacity、replacement、partition 与模型大小 [SYSTEM-DEPENDENT]——**但 [BASELINE-0] 明确假设 Weight 无法跨 Decode Step 持久驻留**，故 baseline 的 Decode Weight Read 仍按每 step 重读一遍 Model Weight 计算（General Architecture Possibility ≠ Baseline Modeling Assumption）；
* **Fusion**：相邻算子间 activation 不落 HBM（3.1 / 3.2 / 4.10 的 fusion opportunity）；
* **Spill**：SRAM 不足时 activation 回写 HBM，产生额外写 + 读。

[TODO] 各级容量/带宽的定量分配（tile 多大、SRAM 在 weight/KV/activation 间如何划分）尚未展开，见附录 A.3。

---

### 8.2 Cache Minimum Mental Model

本节只建立"足以解释 request stream 变化"的最小 cache 概念，不做 cache 教材。

| 概念 | 一句话 |
|---|---|
| Cache Line | 最小搬运 / 管理粒度（典型 32–128 B）[SYSTEM-DEPENDENT] |
| Set / Way | cache 被组织为 set × way 二维结构 |
| Tag | 地址高位，判断目标 line 是否在本 cache |
| Hit / Miss | tag 匹配且 valid → hit；否则 miss |
| Compulsory Miss | 首次访问该 line，cache 从未有过 |
| Capacity Miss | cache 太小，line 被容量挤出后再次访问 |
| Conflict Miss | set 映射冲突，line 被同 set 其他地址挤出 |
| Replacement | miss 后选哪条 line 被替换（LRU / 随机等）[SYSTEM-DEPENDENT] |
| Read Allocate | read miss 时是否把 line 填入 cache |
| Write Allocate / No-Write-Allocate | write miss 时是否先取回 line 再写 |
| Write-through | write 同时更新 cache 与下层 |
| Write-back | 只在 evict 时才把 dirty line 写回下层 |
| Dirty Eviction | 脏 line 被逐出 → 必然产生下层 write |

**关键意识**：cache 是"算法访问量"与"HBM 事务量"之间的第一道放大器/衰减器。下述问题都只用 1–3 句回答；不确定处标 [TODO]。

必答问题：

1. **为什么 `Tensor Bytes ≠ HBM Read Bytes`？**
   Tensor Bytes 是最上层逻辑量；其与 HBM 事务量之间夹着 cache 复用、coalescing、over-fetch、spill、writeback 多重变换，二者无固定比例。
2. **一个 Weight/KV byte 从 HBM 读回后，什么时候可以服务多次 compute？**
   当它在 cache/SRAM 驻留期间被多次访问（temporal reuse）：weight 服务 tile 内多 token → 多 head / batch；shared KV 服务组内多个 Q head。[SYSTEM-DEPENDENT]
3. **Cache line size 如何影响 request granularity / over-fetch / spatial locality / HBM burst？**
   line 决定最小取回粒度；只用一个元素却拉回整条 line → over-fetch；spatial locality 好时 line 能被一次填满并按长 burst 高效传输。[SYSTEM-DEPENDENT]
4. **Cache miss 最终如何变成 HBM read？**
   Cache miss 触发向 **lower memory hierarchy** 的 line-fill request（lower-level / downstream memory request）→ 经 NoC / Home Node / memory subsystem → 成为 MC-visible request → MC 发 HBM read command。本文统一用 lower-level / downstream 表述；**不把 NoC/HN 称为 cache 的"上游"**。[SYSTEM-DEPENDENT]
5. **Dirty eviction 如何变成 HBM write？**
   evict 时若 line 为 dirty，则写回下层 → 形成 HBM write（可能被 write buffer 合并后写）。
6. **为什么 write-back cache 会使 HBM write traffic 在时间上更 bursty？**
   write 先在 cache 累积、延迟到 evict 才集中落下，时间上与产生它的 compute 解耦；evict 又受替换压力触发，因此呈现阵发。[SYSTEM-DEPENDENT]
7. **Cache capacity 不够时，Weight / Activation / KV 各自会发生什么？**
   Weight：反复 miss，退化为每 step 纯 streaming；Activation：本应留片上却 spill，产生额外 write + read；KV：hot tile 命中率下降，历史 KV read 更接近全量 HBM read。[TODO：定量]
8. **Capacity miss 与 conflict miss 对 HBM traffic 有什么不同的表现？**
   **Capacity miss**：在固定 cache capacity、固定 access trace 的前提下，不能仅靠 set mapping 消除；但可通过 tiling / loop scheduling / fusion / working-set reduction 缩小 active working set，降低实际 capacity pressure。**Conflict miss**：可通过 layout / index-hash mapping / associativity / padding 等**缓解**（不是必然"消除"）。前者约束的是 working-set 规模，后者约束的是地址映射方式——优化手段不同。
9. **为什么"logical read 2 GiB"不能直接推成"HBM read 2 GiB"？**
   因为可能 L2 hit（< 2 GiB）、可能 line over-fetch（> 2 GiB）、可能被 prefetch/merge 改变——三者方向相反，净结果需具体分析。

> **Learning Check**：
> - 若 L2 hit rate 从 50% 提到 90%，HBM read bytes 一定降 80% 吗？为什么？
> - 同一 Weight tile，行优先 vs 列优先 layout 对 line 利用率的影响方向？
> - 为什么"cache 命中"能同时减少 HBM read，却可能推迟 HBM write 的时间分布？

---

### 8.3 Non-blocking Cache / MSHR / Memory-Level Parallelism

路径：

```text
Compute request
↓
Cache miss
↓
MSHR allocation
↓
Outstanding memory request
↓
NoC
↓
Memory Controller
```

概念：

* **Blocking cache**：一次只允许一个 outstanding miss，miss 未返回则后续访问 stall。
* **Non-blocking cache（lockup-free）**：允许多个 outstanding miss 并行存在。
* **MSHR（Miss Status Holding Register）**：记录"正在等待 fill 的 outstanding miss"的表项（含 line 地址、等待它的 requester）。
* **outstanding cache miss**：已发射、数据未回的 miss 数。
* **miss merging**：多个指向同一 line 的 miss 合并为一个 fill，只发一次下层请求。

必答问题：

1. **MSHR 是什么？** 记录 outstanding miss 的小型表；每条目对应一个未完成的 line fill。
2. **为什么 cache-miss outstanding 可能在 MC CAM 之前被限制？** 每个 miss 占一个 MSHR；某一级 cache/slice 的 MSHR 满则不能再发新 miss。但**单个 cache/slice 的 MSHR depth 不能直接与整个 MC CAM depth 一一比较**——实际系统是多 source（多 core / SM / L2 slice）各自持有 MSHR，聚合后送向 MC。应比较 **aggregated outstanding supply**（所有 source 聚合后可维持的 cache-miss 并发）与 MC scheduler visibility capacity。[SYSTEM-DEPENDENT]
3. **`MC CAM depth = 96` 是否意味着系统一定可以给 MC 96 个有效 request？** 不一定。实际供给受各级 MSHR 聚合、NoC 反压、request 生成速率共同限制；96 只是 MC 侧**上限**。[SYSTEM-DEPENDENT]
4. **若单个 cache slice MSHR=16、MC CAM=96，能直接判断 MSHR 是 bottleneck 吗？** 不能直接判断。只有当**所有 request source 聚合后**可维持的 cache-miss outstanding 上限明显低于 MC CAM depth 时，上游 memory-level parallelism 才可能先成为瓶颈；多 core / 多 L2 slice 系统中 aggregate 远大于单 slice 的 16。判断对象是 aggregated cache-miss concurrency，而非单个 MSHR depth 与 CAM depth 的数字对比。[SYSTEM-DEPENDENT]
5. **miss merging 为什么能减少 physical HBM traffic？** 同一 line 的多个 miss 合成一次 fill，多个 consumer 共享同一次 HBM read，物理请求数下降。
6. **同一 cache line 被多个 consumer miss 时，是否一定形成多个 HBM request？** 不一定：若并发且可合并 → 1 个；若时间错开或分属不同结构 → 可能多次。[SYSTEM-DEPENDENT]
7. **MSHR full 时上游发生什么？** MSHR full 直接限制的是"需要**新增** outstanding miss state 的请求"：新的 independent cache miss 无法分配 MSHR → 相关 memory-side 请求 stall / backpressure → **可能**进一步 stall 依赖它的 compute。以下均 implementation-dependent [SYSTEM-DEPENDENT]：cache hit 是否还能继续；可 merge 到已有 MSHR 的 miss 是否还能继续；store path 是否共享同一资源；independent compute 是否继续。MSHR full 不是无条件让整个 core 停止。
8. **MSHR 深度增加的收益与代价？** 收益：更高 memory-level parallelism（MLP）、更易填满 HBM；代价：面积、tag 比较逻辑、可能过度并发导致 queue 抖动与平均延迟变差。[SYSTEM-DEPENDENT]

连接到 MC：

```text
Aggregate cache-miss concurrency
↓
NoC-deliverable outstanding
↓
MC admitted outstanding
↓
MC scheduler-visible requests
↓
BLP / Row-hit opportunity
↓
HBM Efficiency
```

这是后续 performance model 的重要边界：比较任何"深度"都必须先对齐层级与聚合口径。

> **Learning Check**：
> - MSHR 从 16 增加到 128，为什么 HBM bandwidth 可能完全不变？
> - "MSHR 大 = 性能好"在什么条件下不成立？
> - 为什么 missed-line merging 的收益与 cache line size 相关？

---

### 8.4 Prefetch

只学习 memory-system consequence，不学具体 prefetch algorithm。

必答问题：

1. **Prefetch 解决什么问题？** 提前把"未来可能用到"的 line 取回，把 latency 隐藏成 outstanding，缩短后续 load 的可见延迟。
2. **Prefetch 如何把 latency hidden 成 outstanding？** 在需求真正到来**之前**发射请求，使 memory 并行度被提前填满，需求到达时数据已在 cache。
3. **什么情况下 prefetch 能提高 HBM utilization？** 访问模式可预测（sequential / 固定 stride）且 prefetch 准确，提前把 bank / PC 并行度拉开。
4. **什么是 useless prefetch？** 预测错误，或过早/过晚：取回的数据无人使用，或已被驱逐。
5. **useless prefetch 如何占 HBM BW / Cache capacity / MSHR / NoC / MC queue？** 它消耗真实资源却不产 compute 收益：占 HBM 带宽、污染 cache、占 MSHR（挤掉有效 miss 的 MLP）、占 NoC 带宽与 MC queue。[SYSTEM-DEPENDENT]
6. **Weight streaming 为什么通常比 KV access 更容易 prefetch？** Weight streaming 通常拥有更长、更稳定的 sequential run，对 stream/stride prefetch 更友好。Historical KV 是否容易 prefetch 取决于 **KV layout、block/page scheduling、runtime paging 与 kernel traversal order**。尤其注意 Paged KV 可能表现为：**KV block-to-block irregular、KV block-internal sequential**——即 KV block 间离散不等于 block 内也随机，不应把 PagedAttention 简化为"KV 地址随机"；这与 VM page 是否连续是另一层问题。[SYSTEM-DEPENDENT]
7. **Prefetch distance 太短 / 太长分别有什么问题？** 太短：数据到达时仍 miss，latency 未真正隐藏；太长：过早取回被驱逐（退化为 useless prefetch），并占用上面第 5 条的资源。
8. **Prefetch 对 latency 与 bandwidth 的影响为什么不能混为一谈？** 同一 prefetch 可能同时隐藏 latency（单请求更快）又浪费 bandwidth（多取无效数据）；降低 prefetch 可省带宽但暴露延迟。二者是不同指标，需分开度量。

> **Learning Check**：
> - Prefetch 覆盖率上升，HBM useful bandwidth 一定上升吗？wasted bandwidth 怎么看？
> - Decode B=1 相比 Prefill 通常具有更低的 batch-level concurrency opportunity，但为什么不能直接说 MC-visible request stream 一定稀疏？Prefetch 在 Decode 与 Prefill 中的作用又可能有什么不同？（Hint：B=1 只描述 batch 维度；实际 MC-visible outstanding 还受 kernel tiling、MSHR、L2 slice、prefetch、NoC 与 request generation implementation 影响。）

---

### 8.5 Coalescing / Request Merging

面向 GPU/NPU memory system 的合并行为。

必答问题：

1. **多个细粒度 load/store 如何合并成更大的 memory request？** 同 warp / 同并发组内落在同一 cache line（或 sector）的地址，被合并成一个 memory request。
2. **coalescing 如何改变 request count / size / burst length / address continuity？** 请求数减少、单请求变大、burst 变长、地址更连续。
3. **Tensor layout 为什么会影响 coalescing？** layout 决定"同一时刻并发访问的地址是否相邻"——相邻则易合并；strided / transposed / head-major 等布局会造成碎片化。
4. **为什么 logical bytes 相同，physical transaction 数可以完全不同？** 布局、对齐、tile 顺序改变合并度与 line 利用率，同样的逻辑字节数对应不同物理事务数。
5. **GQA / KV layout / quantization 如何可能改变 request packing？** GQA 缩小 KV footprint 并改变组内 head 的并发访问关系；KV layout 改变连续性；quantization 改变每元素字节与对齐——三者都可能改善或破坏合并度。[TODO：定量]
6. **coalescing 不好时，Memory Controller 会看到什么症状？** 分两层。**Direct consequence**（直接导致）：request count ↑、average useful bytes/request ↓、transaction overhead ↑、burst utilization ↓。**Possible secondary consequence**（非必然）：row hit ↓、ACT/column ↑、channel hotspot、bank imbalance——是否出现取决于 **Tensor Layout + Physical Address Mapping + Request Ordering** 的组合。Coalescing efficiency 与 row locality / channel balance 是**相关但不同的维度，不能直接划等号**（与 9.0"不能跨层直接等号"的方法论一致）。

连接：

```text
Tensor Layout
→ Access Granularity
→ Coalescing
→ Request Size / Count
→ HBM Burst Efficiency
```

> **Learning Check**：
> - 为什么"logical bytes 相同"不能推出"physical transaction 相同"？
> - KV layout 从 token-major 换到 head-major，会怎样改变 historical scan 的 coalescing？
> - 一个 128 B request 与两个 64 B request，对 MC 调度自由度有何差别？

---

### 8.6 Virtual Memory / TLB / Paging

放在 §8，作为 HBM physical address 之前的重要系统层。

```text
Virtual Address
↓
TLB
↓ miss
Page Table Walk
↓
Physical Address
↓
Cache / NoC
↓
Memory Controller
```

概念：

* **Virtual Address / Physical Address**：程序/逻辑视角地址 vs 内存物理地址。
* **Page / Page Size**：VA-PA 映射的粒度（4 KiB / 2 MiB / 1 GiB 等）。
* **TLB**：VA→PA 的地址转换缓存。
* **TLB Hit / Miss**：命中直接得到 PA；miss 需 page table walk。
* **Page Table Walk**：沿多级页表读 PTE，得到 PA（本身产生额外 memory access）。
* **TLB Reach** = entries × page size：TLB 一次可覆盖的地址范围。
* **Huge Page**：较大 page size，提高 reach、减少 TLB 压力。
* **Physical fragmentation**：物理内存分配碎片化，破坏逻辑连续性。

必答问题：

1. **为什么 MC 最终处理的是 physical address，而不是 Tensor logical index？** MC 面对的是经 layout/MMU 多层映射后的物理地址；logical index 要经过 tile/layout、VA→PA 才可能到达 MC。[SYSTEM-DEPENDENT]
2. **TLB miss 为什么可能增加额外 memory traffic？** page table walk 需读多级 PTE，本身是额外 memory request，且高延迟会阻塞后续访问。
3. **`TLB Reach = entries × page size` 的架构含义是什么？** 它是 TLB 一次能覆盖的地址范围；reach 小于 working set → 频繁 TLB miss。
4. **page size 大为什么能提高 TLB reach？** entries 相同时，每项覆盖更大地址区间，总覆盖范围线性放大。
5. **large page 的代价是什么？** 分配粒度粗、内部碎片浪费容量、迁移 / 压缩成本高。[SYSTEM-DEPENDENT]
6. **Physical fragmentation 如何破坏原本逻辑连续的数据？** 逻辑连续的 KV 可能被分到物理不相邻的 page，物理地址在 page 边界跳变，破坏 sequential run 与 burst。
7. **为什么这件事对 KV Cache / PagedAttention 特别重要？** PagedAttention 将逻辑连续的 KV sequence 切分为固定粒度的 **KV block/page**，并通过 runtime block table / allocator 映射到可能不连续的 KV storage blocks。这里的 KV block/page 属于 **serving/runtime 层**，不等同于 OS/MMU virtual-memory page。[SYSTEM-DEPENDENT]

**两层机制严格区分**（不要把 PagedAttention page 与 VM page 混淆）：

```text
PagedAttention / KV Runtime Layer
logical KV block/page
↓
runtime block table / allocator
↓
KV storage block

        ≠ necessarily

Virtual Memory Layer
Virtual Address
↓
TLB / Page Table
↓
Physical Address
```

> PagedAttention 中所谓 block/page，首先是 runtime 对 KV Cache 的管理粒度；它不必与 OS/MMU 的 virtual-memory page size、TLB entry 粒度相同。[SYSTEM-DEPENDENT]

两级映射的完整链（`if applicable`：并非所有实现都经过完整 OS-style virtual memory path）：

```text
Logical KV token / sequence
↓
PagedAttention block indexing
↓
Runtime KV block mapping
↓
KV storage address
↓
Virtual Address（if applicable）
↓
TLB / Page Table
↓
Physical Address
↓
NoC
↓
Memory Controller
```

若 accelerator / runtime 使用虚拟地址，KV storage blocks 对应的地址还可能进一步经 `VA → TLB / Page Table → PA` 后才成为最终进入 NoC / Memory Controller 的 physical address——**runtime block mapping 与 VA→PA translation 是两个不同层级**。映射的物理离散性直接决定 HBM access pattern。[SYSTEM-DEPENDENT]
8. **Logical contiguous KV 是否意味着 HBM physical contiguous？** 不一定；取决于 page size、分配器与 fragmentation。[SYSTEM-DEPENDENT]
9. **Page allocation 怎样可能改变 channel distribution / row locality / sequential run length？** 物理页落点决定地址映射后命中哪些 channel/bank、是否 row 连续；分配越碎，并行度与 row hit 越难保证。[TODO：定量]
10. **哪些属于通用机制、哪些属于 implementation dependent？** 需区分两个层面：
    * **通用 architecture mechanisms**（本身不是 system-dependent）：VA / PA、Page、TLB、TLB hit/miss、Page Table Walk、TLB Reach。
    * **system-dependent 参数与性能行为**：page size、TLB entry count / organization、page-table format / walk implementation、huge-page support、allocator policy、physical fragmentation、page placement，以及它们对 HBM traffic / latency 的最终影响。[SYSTEM-DEPENDENT]

> **Learning Check**：
> - 为什么"逻辑连续"不能保证"HBM physical 连续"？
> - KV block/page（runtime 管理粒度）与 VM page size（地址转换粒度）分别影响什么？把两者混用同一个"page"会掩盖哪些差别？
> - 一个 2 GiB 的 KV 逻辑读，为什么最终 MC 可能既看到少于、也可能看到多于 2 GiB 的物理访问？

---

### 8.7 NoC Minimum Mental Model

路径：

```text
Compute / DMA / Cache
↓
NoC Request
↓
Router / Arbitration
↓
Memory Controller Port
↓
XMU
↓
HBM Controller
```

概念（只回答其对 MC request stream 的影响，不写 router RTL）：

* **Packet / Flit**：网络传输单元（包 / 流控片）。
* **Routing / Arbitration**：选路与共享资源仲裁。
* **Buffer / Credit-based flow control**：缓冲与基于信用的流控。
* **Virtual Channel / Virtual Network**：虚拟通道 / 虚拟网络，隔离不同流量。
* **Head-of-Line Blocking**：队头阻塞。
* **Backpressure**：反压。
* **QoS / Priority**：服务质量 / 优先级。
* **Bisection Bandwidth**：对半切口带宽。

必答问题：

1. **为什么 HBM efficiency 低不一定是 Memory Controller 的问题？** MC 只能调度它"看得见"的请求；若上游供给稀疏、乱序或阵发，MC 再优也无法凭空提高利用率。
2. **NoC bandwidth 不足时，MC 会看到什么？** arrival rate 低、MC queue 长期偏浅、outstanding 不足 → 带宽利用率上不去。
3. **NoC congestion 与 MC CAM full 分别是什么现象？** NoC congestion：requests are delayed **before reaching MC** → MC 可能观察到低 arrival rate / shallow queue。MC CAM full：requests **have reached MC** → MC-side admission / retirement capacity 受压。CAM full 只说明 **arrival rate > retirement/service rate**；根因可能是 DRAM timing、row conflict、R/W turnaround、refresh、dependency、scheduler policy、write-data availability、downstream credit/resource 等——不能仅凭 CAM full 判断为"DRAM downstream blocking"。**Observable ≠ Root Cause**：CAM full 是 symptom / pressure signal，需要进一步 attribution。
4. **Credit-based flow control 是什么？** 发送方持有 credit，每发一个 flit 消耗一个；接收方 buffer 腾出后返还 credit。
5. **credit 用尽为什么会产生 backpressure？** 无 credit 即不能发数据 → 上游停顿，反压逐级回传到 source。
6. **HOL blocking 是什么？** 队头请求被阻塞时，队内后续请求（即便其目的地可用）也无法前进。
7. **为什么一个拥堵 destination 可能阻塞本来可以去其他 destination 的 request？** 共享队列 / 通道被队头占用（HOL），或共享 buffer 被填满。
8. **VC / VN 为什么可以缓解 HOL 或协议死锁问题？** Virtual Channel 提供独立的逻辑 queue / flow-control state，可**缓解部分** HOL blocking——但不同 VC 仍可能共享 physical link / crossbar / arbitration / shared buffer pool，**不等于互不影响**。Virtual Network 用于隔离不同 protocol traffic / dependency class，是构造 deadlock-free protocol/network dependency 的**常用手段之一**——deadlock freedom 还取决于 routing、channel dependency、resource allocation 与 protocol dependency，不能写成"VN 本身就能防止 deadlock"。
9. **QoS / priority 在 NoC 与 MC 两级分别可能存在，二者怎样互动？** NoC 决定请求的 arrival 优先级与时序，MC 决定 service 顺序；两级策略不一致时，高优先级请求可能在 MC 排队或被 NoC 降级。[SYSTEM-DEPENDENT]
10. **NoC arbitration 如何改变 request arrival timing / burstiness / outstanding / source fairness？** 按 credit / round-robin / priority 调度会"整形"arrival：或更平滑、或更阵发，并改变各 source 的公平性。
11. **Bisection bandwidth 的直觉意义是什么？** 把网络对半切开，跨越切口的最大总带宽——决定全局 all-to-all / 远距通信能力上限。
12. **若 MC bandwidth utilization 只有 60%，怎样判断是 MC 自己发不出来还是 NoC 没喂够？** 看 MC queue occupancy 与 outstanding：长期偏低 → 上游供给不足（MSHR / NoC）；长期偏高但效率仍低 → MC 自身调度问题。

最终建立：

```text
Workload
↓
Cache Miss Stream
→ NoC Arrival Stream
→ MC Visible Stream
→ DRAM Scheduling
```

明确区分：

> **Application request stream ≠ NoC request stream ≠ MC visible request stream。**

**诊断层级（performance attribution 的 system boundary，与 `DDR_Controller_Architecture.md` 的 attribution 思路衔接）**：

```text
Application / Kernel
↓
Cache / MSHR
↓
NoC
↓
MC Admission
↓
MC Scheduler Visibility
↓
DRAM Timing / Resource
```

当 HBM utilization 低时，不要直接归因 scheduler：

```text
MC queue shallow
→ investigate request supply:
   cache / MSHR / NoC / workload arrival

MC queue deep
but no command issued
→ investigate MC / DRAM:
   dependency / timing / direction / refresh / policy / data
```

此处只建立 system boundary，不展开新的 blocked-reason taxonomy。

> **Learning Check**：
> - NoC credit stall 与 DRAM tRCD stall 在最终 bandwidth symptom 上可能相同，怎样定位？
> - MC CAM full 与 NoC congestion 在"MC queue occupancy"指标上的表现为何不同？
> - 为什么"MC 利用率低"既可能是上游问题也可能是下游问题？

---

### 8.8 Coherency Minimum Mental Model

本节只学到 **Memory Controller-facing boundary**，不做完整 CHI/ACE 协议教材。对具体协议只说明 architecture meaning，不背 opcode。

概念：

* **Coherent vs Non-coherent**：是否维护多副本一致性。
* **Cache line state / ownership（直觉）**：谁持有最新数据、谁有权写。
* **Request Node (RN)**：发起请求的节点（cache/agent）。
* **Home Node (HN)**：某地址的"家"，负责一致性裁决与合并。
* **Subordinate / Memory Node (SN)**：最终连到 DRAM 的从节点。
* **Snoop**：查询其他 cache 的持有与状态。
* **Directory / Snoop Filter**：跟踪 line 归属，避免广播 snoop。
* **Req / Resp / Data / Snoop channels**：协议通道类别。
* **Ordering / Barrier**：顺序与屏障要求。
* **DVM**：分布式虚拟内存维护（如 TLB invalidate）。
* **Credit**：协议层流控信用。

必答问题：

1. **为什么有 Cache 后会出现 coherency 问题？** 同一物理地址可能在多个 cache 存在副本，需保证任何时刻读到的都是一致的最新值。
2. **什么叫"一个 cache line 的最新数据可能不在 HBM"？** dirty line 只存在于某个 cache，HBM 仍是旧值，直到 writeback 才更新。
3. **CPU/GPU/NPU 共享内存时，为什么不能把所有 load 都直接送 Memory Controller？** 因为最新数据可能在别的 cache，直接读 HBM 会拿到 stale 值。
4. **Home Node 的核心职责是什么？** 作为地址的"家"，负责一致性裁决：snoop 拥有者、合并请求，并产生真正需要访问 memory 的最终请求。
5. **Snoop 的目的是什么？** 查询其他 cache 是否持有该 line 及其状态，决定是否需要 cache-to-cache 传输或 invalidation。
6. **Directory / Snoop Filter 为什么存在？** 跟踪哪些 cache 持有哪些 line，避免向所有 cache 广播 snoop（省带宽、降低 snoop 风暴）。
7. **Snoop Filter 是否必然属于 DRAM Controller？** 否——它属 coherency 逻辑，可独立于 MC 存在。[SYSTEM-DEPENDENT]
8. **Memory Controller 是否必须自己实现 CHI coherency？** 否——取决于 SoC partition，MC 可能只接收已被解决好的最终 memory 请求。[SYSTEM-DEPENDENT]
9. 应建立结论：

```text
Coherent Memory System 必须有人承担：
ownership / snoop / directory / filter / ordering / coherence resolution

但这些逻辑是否位于 DRAM Controller RTL 内，
取决于 SoC partition。
```
   [SYSTEM-DEPENDENT]

10. 在一种典型 partition 下：

```text
RN
↓
NoC / HN / Coherency Resolution
↓
final memory request
↓
Memory Controller
↓
DRAM
```
   MC 只看到真正需要访问 memory 的 request。[SYSTEM-DEPENDENT]

11. **Dirty cache line writeback 如何形成 HBM write？** evict dirty line → writeback 到 HN → 最终转为 HBM write。
12. **Cache-to-cache transfer 为什么可能完全不访问 HBM？** 若数据在另一 cache 且有效，可直接 cache-to-cache 传输，HBM 不参与。
13. **coherency traffic 本身是否都会进入 HBM？** 不是——snoop、cache-to-cache、cache 命中解决的 coherency 请求都可能不碰 HBM。[SYSTEM-DEPENDENT]
14. **Ordering / Barrier 如何影响 MC？** Ordering / Barrier 限制的是**整个 memory subsystem** 的可重排自由度；对 MC 的具体影响取决于 partition [SYSTEM-DEPENDENT]：
    * **Partition A**：RN → HN resolves ordering → 只释放满足顺序约束的 request → MC。MC 不直接维护 barrier state，但 ordering 通过 **request release timing / allowed arrival order** 间接减少 MC 可见的 reorder opportunity。
    * **Partition B**：部分 ordering / dependency contract 进入 MC subsystem，MC 内部直接维护相关顺序约束。
    两种情况下 MC 都可能牺牲 row-hit 与并行度，但机制不同。**MC 是否"实现"coherency/ordering 逻辑，与 coherency/ordering 是否"影响 MC performance"，是两个不同问题。**
15. **DVM 与普通 data request 有什么本质区别？** DVM 是控制 / 维护语义（如 TLB invalidation），不搬运数据 payload，但可能触发额外 memory 活动与 ordering 约束。[SYSTEM-DEPENDENT]
16. **Coherency 如何改变 `load → HBM read / store → HBM write` 模型？** load 可能命中其他 cache（不读 HBM）；store 可能只更新 cache（延迟到 writeback 才写 HBM）；读写数量与时序都被 coherency 中介，简单一一对应不再成立。

> **Learning Check**：
> - 如果最新 cache line 在另一个 coherent agent 中，为什么 HBM 不一定发生 read？
> - 为什么 coherency 逻辑"必须有"，但"未必在 MC 里面"？
> - store 落 cache 与落 HBM 之间被 coherency 拉开了哪些环节？

---

### 8.9 AI Traffic → 系统层映射

把第 8 章系统层重新映射到 §9 的 AI traffic。**不自动填满 TODO**；明确结论给短答，依赖实现的保留 `[SYSTEM-DEPENDENT]` 或 `[TODO]`。

| AI Traffic | Cache 特征 | Prefetch | Coalescing | TLB / Paging | NoC | MC / HBM consequence |
|---|---|---|---|---|---|---|
| Weight streaming | 容量远不足，近似每 step 纯流式；reuse 靠 SRAM tile | 易（长而稳定的 sequential run） | 好（连续大块） | 可用 huge page 降 TLB miss [SYSTEM-DEPENDENT] | 稳定的大 read stream；priority/QoS 取决于 accelerator criticality policy [SYSTEM-DEPENDENT] | sequential physical stream 通常有利于 burst/coalescing；最终 row locality / ACT-per-COL 取决于 physical address mapping 与 channel/bank/row interleave [SYSTEM-DEPENDENT] |
| Historical KV read | hot tile 可命中（含 GQA shared KV）；长 context 易 capacity miss | layout / paging / kernel traversal dependent；Paged KV 可能 KV block 间离散、block 内顺序 [SYSTEM-DEPENDENT] | 取决于 KV layout [TODO] | PagedAttention 物理离散 → 破坏连续 [SYSTEM-DEPENDENT] | 大流量、可能阵发 | stride 与 row hit 取决于 layout + paging + address mapping [SYSTEM-DEPENDENT] |
| New KV append | write 型，可 write-back 延迟合并 | 写预取少见 | token-连续布局利于写合并 [SYSTEM-DEPENDENT] | 新 page 分配可引入不连续 [SYSTEM-DEPENDENT] | 相对小流量 | append write，写聚合后可能阵发 |
| Activation | 理想片上；spill 才落 HBM | 通常不需要 | 取决于 kernel 实现 | [TODO] | 理想接近零 | 理想近零 HBM 流量；spill 时额外 R/W |

---

### 8.10 综合 Learning Check / Open Questions

（回答留白，后续自行补充；可只写 Hint。）

1. **L2 hit rate 从 50% 提到 90%，为什么 HBM bandwidth demand 不一定同比下降 80%？**（Hint：考虑最终 miss 的绝对量、over-fetch、write 侧流量不随 read hit 变化。）
2. **单个 cache slice MSHR=16，MC CAM=96，是否可以直接判断 MSHR bottleneck？为什么？**（Hint：source 聚合——比较的是 aggregated cache-miss concurrency 与 MC scheduler visibility capacity，不是单个 MSHR depth vs CAM depth。）
3. **MC CAM occupancy 长期只有 12/96，怎样逐层区分 workload supply / MSHR / NoC / MC admission 谁在限制请求供给？**（Hint：沿诊断层级逐层看 outstanding 与 queue occupancy，CAM full 是 symptom 不是 root cause。）
4. **为什么 poor coalescing 不一定意味着 poor row hit？**（Hint：coalescing 决定 request count/size；row locality 还取决于 physical address mapping 与 request ordering——相关但不同维度。）
5. **为什么 Paged KV 可以同时表现为 KV block-to-block irregular、KV block-internal sequential？这对 prefetch 与 HBM mapping 分别有什么影响？**（Hint：prefetch 看 block 内 run；mapping 看 block 间离散。）
6. **Ordering constraint 如果已经由 HN 处理，与 ordering state 直接进入 MC，两种架构对 MC scheduler 有什么不同？**（Hint：release timing / arrival order vs MC 内部顺序约束。）
7. **对于一个 logical KV read = 2 GiB：构造一个 Physical HBM Read < 2 GiB 的情况；再构造一个 Physical HBM Transaction Bytes > 2 GiB 的情况。**（Hint：变小——cache hit / miss merging；变大——over-fetch / fragmentation / replication / padding。）
8. **NoC credit stall 与 DRAM tRCD stall 在最终 bandwidth symptom 上可能相同，怎样定位？**（Hint：看 stall 发生在哪个 queue、对应哪一级 occupancy；Observable ≠ Root Cause。）

---

## 9. Tensor → HBM Traffic

### 9.0 系统层连接：Logical Bytes → MC-visible Request Stream

第 8 章的系统层插入后，本章原有的三级链升级为：

```text
Logical Tensor Bytes
↓
Tile / Layout
↓
Compute-side Load / Store
↓
Coalescing
↓
Cache Hit / Miss
↓
TLB / Physical Address
↓
NoC Transport
↓
Coherency Resolution（若适用）
↓
MC-visible Physical Request Stream
↓
HBM Controller
```

**核心不等式**——每一层都可能因 reuse / cache hit / writeback / prefetch / coalescing / padding / fragmentation / coherence / retry 而变化，不能跨层直接等号：

```text
Logical Tensor Bytes
≠ Compute Load / Store Bytes
≠ Cache Miss Bytes
≠ NoC Traffic Bytes
≠ MC Request Bytes
≠ Physical HBM Transaction Bytes
```

本文后续一切 Byte 会计，只有走到**最右端的 Physical HBM Transaction Bytes**，才真正对应 MC 需要服务的请求量。中间各层的比值均为 `[SYSTEM-DEPENDENT]`，需按具体 accelerator / runtime 确定（附录 A.3）。

### 9.1 接口：Logical Bytes → Request Stream（performance-model abstraction）

```text
Logical Tensor Bytes
↓
Tile / Layout
↓
Memory Request Stream
↓
HBM Controller
```

> **§9.1 是对 §9.0 完整 system path 的 performance-model abstraction / interface abstraction，不是新的物理层级链**，两个 diagram 不冲突：

```text
完整路径（§9.0）：
Logical Tensor → … → MC-visible Physical Request Stream → Memory Controller

性能模型接口抽象（§9.1）：
Logical / Workload Description → Request Stream Description → Memory Controller Model
```

Request Stream 至少包含以下属性：

```text
Read / Write
Request Size
Burst Length
Stride
Sequential Run Length
Outstanding
Temporal Locality
Spatial Locality
Address Distribution
```

补入系统层后，Request Stream schema 增加以下分析属性（对应第 8 章新增层）：

```text
Source / Traffic Class
Arrival Time / Inter-arrival Gap
Cacheable / Non-cacheable（若适用）
Physical Page / Region
Coalescing Degree
Prefetch / Demand
Criticality / QoS
Dependency / Ordering Requirement
```

> 这些是 **performance model 的分析属性**，不等同于某个具体 bus protocol 的真实 signal field；不同系统的字段集合与命名不同，不假设每个 MC 都显式携带全部字段。[SYSTEM-DEPENDENT]

本章及后续任何 workload 分析都必须逐步从 Byte 会计走向 request 会计，例如从：

```text
KV Read = 2 GiB
```

发展为：

```text
KV Read = 2 GiB；request size = ?；request 数 = ?；stride = ?；outstanding = ?；channel 分布 = ?；row locality = ?
```

当前未知的值一律标 [TODO]，不编造（见附录 A.3）。

### 9.2 Weight Traffic

```text
Read-only
大块连续
模式规则
Decode 时反复 streaming
容易 prefetch
```

分析重点：burst 长度、sequential 程度、channel striping（weight 地址如何交织到 channel）、weight placement（排布与映射的配合）。

### 9.3 KV Traffic

```text
Read + Write 混合
容量随 S、B 增长
地址与 layer / head / token / layout 有关
Long context 下流量与容量同步膨胀
```

### 9.4 KV Layout

两个基本逻辑布局：

```text
[token][head][D]   —— token 维连续
[head][token][D]   —— head 内 token 连续
```

分析维度（结论 [TODO]，附录 A.3）：

* append（新 token KV 写）是否连续：token-连续布局利于写 burst；
* historical scan（读全部历史）是否连续、stride 多大：两种布局给出不同 stride；
* 由此决定 burst 长度、locality，以及与 address mapping（channel interleave 粒度）的匹配。

### 9.5 GQA 对 Access Pattern 的影响

* KV 区域整体缩小 r 倍 → footprint 变化；
* 组内 temporal reuse：同一份 KV 被多个 Q head 消费，kernel 安排得当时 L2 命中率上升；
* read 是否真正减少取决于 accelerator 的复用实现（5.3-5）；
* Nkv 变少后单次 KV burst 覆盖的地址范围变小，address mapping 仍需保证 Channel / PC 并行度——KV 区域缩小不能以牺牲 channel 利用为代价。

### 9.6 Zero Write / Padding

HBM 上全零 write transaction 的可能来源：

```text
buffer initialization / memset
KV / workspace page clear
padding / alignment
sparse activation（含大量零值的 activation 常规写回）
unfused attention materialization（masked 区域被显式写出，见 4.6）
```

causal mask 会使部分 probability 为 0，但 Decode 的 score 只有 [1,S]，Prefill 的完整 causal matrix 通常不写 HBM（4.6 / 4.10）——**causal mask 不应被直接等同于大量 HBM zero write**。[SYSTEM] 实际是否出现 zero write 取决于 runtime 的清零与分配行为。

---

## 10. MC-visible Request Stream → Memory Controller → HBM Performance

分析链（与文档头 authoritative chain 一致；MC 之前的输入一律称 MC-visible Request Stream，不再使用模糊的 `Traffic`）：

```text
MC-visible Request Stream
↓
Outstanding
↓
Queue / Scheduler Visibility
↓
Channel / PC / Bank Distribution
↓
Row Locality
↓
R/W Direction
↓
Scheduler / Timing / Maintenance
↓
DRAM Commands / HBM Transactions
↓
Effective BW / Latency
↓
Tokens/s
```

### 10.1 Outstanding

请求并行度是否足以填满所有 PC / bank。Decode B=1 相比 Prefill / large-batch workload 通常具有更低的 compute-side reuse 与 batch-level concurrency opportunity，但 MC 实际可见的 outstanding request 数**不能仅由 B=1 推出**，而取决于 kernel 切分、cache/MSHR、NoC、prefetch 与 request generation implementation。[SYSTEM-DEPENDENT]

因此本节的定量问题不是"Decode 是否天然 request 少"，而是：

> **这个 workload 最终能够给 MC 提供多少 scheduler-visible outstanding，并是否足以暴露 Channel / PC / Bank parallelism？**

[TODO] 定量分析。

### 10.2 Channel / PC / Bank Parallelism

* Weight：大块连续，天然可 striping 到多 channel；
* KV：burst 粒度由 layout 与 D 维长度决定，burst 越短越难铺满 channel。

### 10.3 Address Mapping

Tensor 连续维到 channel/PC interleave bits 的映射决定并行度；KV layout（9.4）与 mapping 不匹配时出现 channel hotspot。[TODO] 定量。

### 10.4 Row Hit / Locality

* **Weight**：若 physical request stream 保持较长 sequential run，通常有利于 burst / coalescing；但实际 row locality / ACT-per-COL 取决于 channel / PC / BG / bank / row address mapping。
* **KV**：historical KV 的 locality 由 layout + paging + kernel traversal + physical address mapping 共同决定，可能频繁跨 row。

全文重要原则：

```text
Sequential Access ≠ High Row-hit Rate
```

Sequential → favorable burst / spatial behavior；Row locality ← physical address mapping + ordering + layout。不要直接从"顺序流"推出"row hit 高"。[TODO] 定量。

### 10.5 Weight Read + KV Read + KV Write Mixing

baseline decode 每 token 流量构成：

```text
Weight read   12 GiB（纯读、规则）
KV read       2 GiB @S=4096（layout 相关）
KV write      512 KiB（小但必然存在）
R:W ≈ 14 GiB : 512 KiB ≈ 28000 : 1    [FORMULA]
```

Prefill（[BASELINE-0] 下：score 不 materialize、activation 不 spill，read 项只有 Weight）：

```text
Weight read   12 GiB
New KV write  2LSH·b_kv = 2 GiB
R:W = 12 : 2 = 6 : 1    [FORMULA]
```

若实现未 fuse（score/P materialize，4.10），prefill 会出现额外的大额写项，R:W 需重新计算。

### 10.6 Read / Write Turnaround

R/W 切换有直接带宽代价。batch-W 与交替两种策略的机制分析见《HBM读写切换策略》。对 LLM workload 的映射：

* decode 写占比极小（R:W ≈ 28000:1），写聚合几乎无成本地减少切换次数；
* prefill 写占比高（R:W ≈ 6:1），聚合收益与 WDB 压力都更大。

[SYSTEM-DEPENDENT] 具体收益取决于 scheduler 设计、WDB 容量与 workload 相位。

### 10.7 Traffic 分类：Capacity / BW / Latency

不同 AI traffic 不能只用"需要带宽"描述：

| Traffic | Capacity | BW | Latency sensitivity | Pattern |
|---|---|---|---|---|
| Weight | 高 | 高 | 中/高，取决于 prefetch [SYSTEM-DEPENDENT] | sequential read |
| Historical KV | 随 S 增长 | 高 | 当前 attention critical path | read |
| New KV Write | 随 B/S 增长 | 较低 | [SYSTEM-DEPENDENT] | append write |
| Activation spill | implementation-dependent | 可能高 | 通常不希望出现 | R/W |

此表为后续 QoS / scheduler / critical request 分析建立接口（10.8）。

### 10.8 QoS / Criticality

* Weight read 在 compute critical path 上（下层 GEMM 等待）；
* KV read 以 bandwidth 属性为主，同时决定当前 token 完成时间；
* KV write 的可延迟性：**取决于 accelerator/runtime buffer、与下一 decode step 的依赖关系和 memory ordering，属于系统实现问题**。[SYSTEM-DEPENDENT]

### 10.9 Refresh / RAS

长时间满带宽 workload 下 refresh 造成带宽损失。[TODO] 定量。

---

## 11. 当前结论汇总

当前文档经推导得到的系统结论：

1. Transformer 的主要计算形式是 Activation × Weight。
2. Weight、Activation、KV Cache 生命周期不同：只读常驻 / step 内短命 / 跨 token 增长。
3. Activation 尽量片上流动；Weight 与 KV 是 HBM 主流量。
4. Decode 的主要 HBM traffic 通常来自 Weight streaming + Historical KV read（baseline：12 + 2 GiB/token）。
5. Prefill 通过 S 维提高 Weight reuse（≈S），典型偏 compute-intensive。
6. Batch 通过 B 维提高 Decode Weight reuse（≈B），前提是 B 个 token 真的组成一次 GEMM（Continuous Batching 的意义）。
7. Long Context 主要放大 KV Capacity 与 KV Read，且 batch 内由 long-tail sequence 主导 KV 带宽。
8. GQA/MQA 主要解决 KV Memory Cost：算法上 KV capacity 与 unique KV write bytes 按 r 下降（5.3-4），而非同比减少 Attention Core FLOPs。
9. 算法级 Byte reduction ≠ 物理 HBM transaction reduction——GQA read 是否兑现取决于片上复用；attention 实现方式可完全改写 traffic 结论。
10. Tensor layout + accelerator tiling + controller mapping 共同决定最终 HBM efficiency。
11. Prefill 的高 Weight reuse 可用 Arithmetic Intensity 定量表达（FP16 下 AI_weight ≈ M FLOP/B，6.3）。
12. Decode B=1 的 Weight AI 极低，按 Roofline **强烈倾向** memory-bound；最终 operational point 取决于完整 traffic accounting 与真实硬件 Peak Compute / HBM BW，不能仅由 M=1 判定（6.3）。
13. Batch 提高 aggregate throughput 与 Weight reuse，但不意味着单 sequence TPOT 按 B 下降（6.6）。
14. Weight / KV precision 可以不同：所有 Byte 与 crossover 公式分别使用 b_w、b_kv（0.3 / 7.13）。
15. `S_c = 6H` 只适用于 MHA 且 b_w = b_kv 的 baseline；一般式 `S_c = 6H·(b_w/b_kv)`（7.13）。
16. RoPE 修改 Q/K 的位置表示，通常不是 HBM 主 traffic（4.3）。
17. KV Cache 主体驻留 HBM，但 consumer 可从 SRAM/L2 命中——logical KV read ≠ physical HBM read（第 8 章）。
18. MC-visible request stream 需以 request size / stride / outstanding / locality 等属性描述后，才能进入 Controller 分析；HBM transaction 是 MC 的输出而非输入，方向恒为 `MC-visible request → Memory Controller → HBM transaction`（9.1 / 10）。
19. 从 logical tensor bytes 到 physical HBM transaction bytes 之间存在多层系统变换：`Logical Bytes ≠ Compute L/S Bytes ≠ Cache Miss Bytes ≠ NoC Bytes ≠ MC Request Bytes ≠ Physical HBM Bytes`，层间因 reuse / cache hit / writeback / prefetch / coalescing / padding / fragmentation / coherence / retry 变化（9.0）。这直接回答本文核心问题：Transformer 算法给出的 logical bytes **不会一比一**成为 HBM traffic。
20. Cache write policy、cache line size、MSHR 深度、prefetch 策略、page/TLB 行为、NoC 仲裁与 coherency partition 均为 [SYSTEM-DEPENDENT]，任何相关结论都不能写成 universal fact（第 8 章）。
21. MC 只能调度它"看得见"的请求：HBM 利用率低可能是**上游供给不足**（MSHR / NoC / prefetch 缺失）而非 MC 调度器问题（8.3 / 8.7）。真正的瓶颈定位需沿 `Cache Miss Stream → NoC Arrival Stream → MC Visible Stream` 逐层查看 outstanding / queue occupancy（8.7 / 8.10）。
22. Coherency 使 `load → HBM read / store → HBM write` 的简单模型失效：load 可能命中他 cache（不读 HBM）、store 可能延迟到 writeback 才写 HBM。但 coherency 逻辑是否在 MC RTL 内取决于 SoC partition（8.8）。

---

## 12. 附录：Assumption / TODO / 待验证问题

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

### A.2 基线

全部定量结论基于第 7 章 [BASELINE-0]（Decoder-only / MHA / 4H MLP / FP16：b_w=b_kv=b_a=2 B / B=1 / weight 不跨 step 驻留 / 无 activation spill / attention 理想 fusion / LM Head 不计入 12H²）。更换任一假设都必须重新推导。

### A.3 待学习 / 待验证

* [TODO] FlashAttention：tile 粒度、online softmax 与 HBM traffic 的定量关系（4.10 仅定性）
* [TODO] PagedAttention / KV Paging：KV block/page（runtime 管理粒度，≠ VM page）、逻辑连续 → 物理离散对 access pattern 的破坏
* [TODO] Continuous Batching 更完整 workload（与 serving scheduler 的耦合，6.6）
* [TODO] Quantization：FP8/INT8/INT4 的 Weight/KV/BW 结论与 dequant metadata 定量
* [TODO] SwiGLU / Gated MLP：对 Weight / FLOPs / HBM traffic 的影响（3.4 / 7.3）
* [TODO] MoE：expert weight 放置、token routing 对连续访问的破坏、hot expert hotspot
* [TODO] Tensor / Pipeline / Expert Parallel：单卡 HBM traffic 与 scale-up fabric 的替代关系
* [TODO] Roofline：用真实 accelerator 的 Peak Compute / HBM BW 确定 operational point（6.3）
* [TODO] Prefill / Decode request stream 定量：request size / stride / outstanding / channel 分布 / row locality（9.1）
* [TODO] KV / Weight locality ← layout + paging + kernel traversal + physical address mapping 的定量关系（9.4 / 10.4）
* [TODO] HBM Channel / PC mapping 与 tensor layout 的共同设计空间（10.3）
* [TODO] Memory hierarchy 定量：SRAM 约束下的 tiling 分配（第 8 章）
* [TODO] Norm / Residual 的 traffic 定量（第 3 章目前定性）
* [TODO] Controller 机制定量：outstanding 深度、scheduler 可见性、refresh loss（第 10 章）

第 8 章新增系统层带来的待学习 / 待验证问题（对应 8.2–8.8）：

* [TODO] Cache line / coalescing → HBM request size 的定量关系（8.2 / 8.5）
* [TODO] aggregated cache-miss concurrency / NoC deliverable outstanding → MC admitted / scheduler-visible outstanding 的定量关系（8.3）
* [TODO] Cache hit rate → physical HBM bytes 的定量映射（8.2）
* [TODO] Prefetch accuracy / coverage → useful vs wasted HBM BW（8.4）
* [TODO] TLB / page size / fragmentation → KV access pattern（8.6）
* [TODO] PagedAttention runtime block mapping + VM/TLB translation（if applicable）→ final physical HBM address pattern 的定量破坏程度（8.6）
* [TODO] NoC congestion / credit → MC arrival process 的定量刻画（8.7）
* [TODO] NoC QoS ↔ MC QoS 的交互与一致性（8.7）
* [TODO] Coherency resolution → physical HBM traffic 的定量影响（8.8）
* [TODO] AI workload 的真实 request arrival distribution（跨 8.3–8.8，需实测数据）

### A.4 结论修订记录

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
