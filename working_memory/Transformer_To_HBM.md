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
Data Movement
↓
Logical Bytes
↓
HBM Traffic
↓
Access Pattern
↓
Memory Controller
↓
DRAM Efficiency
↓
Application Performance
```

即：`Transformer → Workload → Tensor → Bytes → Traffic → HBM → Controller → Performance`

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

由此把 6.1 / 6.2 的倾向描述定量化：Prefill 的 M=S 使 AI 比 Decode 高约 3 个数量级，通常落在 compute-bound 一侧；Decode 的 M=1 使 AI 极低，几乎必然落在 memory-bound 一侧。operational point 需要真实 accelerator 的 Peak Compute / HBM BW 数值（附录 A.3 TODO）。

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
* **Cache**：L2 对 weight 的跨 step 复用、对 KV 的 hot tile 复用（含 GQA shared KV，5.3-5）；
* **Fusion**：相邻算子间 activation 不落 HBM（3.1 / 3.2 / 4.10 的 fusion opportunity）；
* **Spill**：SRAM 不足时 activation 回写 HBM，产生额外写 + 读。

[TODO] 各级容量/带宽的定量分配（tile 多大、SRAM 在 weight/KV/activation 间如何划分）尚未展开，见附录 A.3。

---

## 9. Tensor → HBM Traffic

### 9.1 接口：Logical Bytes → Request Stream

```text
Logical Tensor Bytes
↓
Tile / Layout
↓
Memory Request Stream
↓
HBM Controller
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

## 10. HBM Traffic → Controller Behavior

分析链：

```text
Traffic
↓
Outstanding
↓
Queue visibility
↓
Channel / PC / Bank distribution
↓
Row locality
↓
R/W switching
↓
Scheduler
↓
Effective BW / Latency
↓
Tokens/s
```

### 10.1 Outstanding

请求并行度是否足以填满所有 PC / bank。Decode 单 token 的请求流天然偏稀，outstanding 深度与 B、请求拆分粒度共同决定能否压满 HBM。[TODO] 定量分析。

### 10.2 Channel / PC / Bank Parallelism

* Weight：大块连续，天然可 striping 到多 channel；
* KV：burst 粒度由 layout 与 D 维长度决定，burst 越短越难铺满 channel。

### 10.3 Address Mapping

Tensor 连续维到 channel/PC interleave bits 的映射决定并行度；KV layout（9.4）与 mapping 不匹配时出现 channel hotspot。[TODO] 定量。

### 10.4 Row Hit / Locality

Weight streaming 为顺序读，row hit 率高；KV historical read 的 stride 由 layout 决定，可能频繁跨 row。[TODO] 定量。

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
12. Decode 的 M=1 使 Weight AI 极低，按 Roofline 更容易成为 Memory Bound（6.3）。
13. Batch 提高 aggregate throughput 与 Weight reuse，但不意味着单 sequence TPOT 按 B 下降（6.6）。
14. Weight / KV precision 可以不同：所有 Byte 与 crossover 公式分别使用 b_w、b_kv（0.3 / 7.13）。
15. `S_c = 6H` 只适用于 MHA 且 b_w = b_kv 的 baseline；一般式 `S_c = 6H·(b_w/b_kv)`（7.13）。
16. RoPE 修改 Q/K 的位置表示，通常不是 HBM 主 traffic（4.3）。
17. KV Cache 主体驻留 HBM，但 consumer 可从 SRAM/L2 命中——logical KV read ≠ physical HBM read（第 8 章）。
18. Physical HBM traffic 需转换为 request size / stride / outstanding / locality 后，才能真正进入 Controller 分析（9.1）。

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
* [TODO] PagedAttention / KV Paging：page 粒度、逻辑连续 → 物理离散对 access pattern 的破坏
* [TODO] Continuous Batching 更完整 workload（与 serving scheduler 的耦合，6.6）
* [TODO] Quantization：FP8/INT8/INT4 的 Weight/KV/BW 结论与 dequant metadata 定量
* [TODO] SwiGLU / Gated MLP：对 Weight / FLOPs / HBM traffic 的影响（3.4 / 7.3）
* [TODO] MoE：expert weight 放置、token routing 对连续访问的破坏、hot expert hotspot
* [TODO] Tensor / Pipeline / Expert Parallel：单卡 HBM traffic 与 scale-up fabric 的替代关系
* [TODO] Roofline：用真实 accelerator 的 Peak Compute / HBM BW 确定 operational point（6.3）
* [TODO] Prefill / Decode request stream 定量：request size / stride / outstanding / channel 分布 / row locality（9.1）
* [TODO] KV physical layout 与 address mapping 的定量匹配（9.4）
* [TODO] HBM Channel / PC mapping 与 tensor layout 的共同设计空间（10.3）
* [TODO] Memory hierarchy 定量：SRAM 约束下的 tiling 分配（第 8 章）
* [TODO] Norm / Residual 的 traffic 定量（第 3 章目前定性）
* [TODO] Controller 机制定量：outstanding 深度、scheduler 可见性、refresh loss（第 10 章）

### A.4 结论修订记录

* **GQA Weight/KV crossover**：早期版本按"weight 维持 12H² 不变"推得 ≈96K，与 5.3-2 的 weight 公式 (10+2r)H² 不一致；统一重推为 `S_c(r) = [(10+2r)/(2r)]·H·(b_w/b_kv)`，r=1/4、b_w=b_kv → ≈86K（7.13）。
* **"crossover 与 precision 无关"补全限定条件**：仅 b_w = b_kv 时成立；一般式含因子 b_w/b_kv（7.13）。
* **Prefill R:W 由 7:1 修正为 6:1**：旧值把 decode 口径的 historical KV read 误计入 prefill read 侧；[BASELINE-0] 下 prefill 的 read 项只有 Weight 12 GiB，write 项为 KV append 2LSHb_kv = 2 GiB（10.5）。
* **"GQA capacity/write 无条件按 r 降"表述收紧**：算法量（capacity、unique KV write bytes）按 r 下降；physical HBM transaction bytes 仍受 padding / alignment / granularity / replication / layout 影响（5.3-4）。
* **"KV Cache 必须落 HBM"弱化**：backing store 通常是 HBM，当前消费的 KV tile / shared KV 可在 SRAM/L2 形成 reuse（第 8 章）。
* **"KV write 天然有 S 长 slack"已撤回**：KV write 能否延迟/合并取决于系统实现（10.8），非算法保证。
* **"Prefill = compute bound / Decode = memory bound"弱化**为典型趋势，并由 6.3 Roofline 定量支撑（6.2）。
* **问答/题库式章节已撤并**：复习问题、问答沉淀等章节的确认知识已迁移进正文，修订痕迹集中于本节。
