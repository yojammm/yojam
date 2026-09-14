# Transformer 到 HBM：面向 IC / HBM 控制器工程师的基础复习笔记

## 0. 总体目标

从 HBM / Memory Controller 工程师的视角理解 Transformer，不需要一开始深入算法推导，而是建立如下映射关系：

$$
\text{Transformer 算法}
\rightarrow
\text{Tensor Shape}
\rightarrow
\text{Compute}
\rightarrow
\text{Memory Traffic}
\rightarrow
\text{HBM Bandwidth / Capacity}
$$

学习过程中始终问四个问题：

1. 当前正在计算什么 Tensor？
2. Tensor 的 shape 是什么？
3. Weight / Activation / KV Cache 分别存在哪里？
4. 这一步需要从 HBM 搬多少 Byte？

---

# 1. 整个 LLM 推理流程

以 GPT / Llama 类 Decoder-only Transformer 为例：

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
Transformer Layer 0
 ↓
x^(1)
 ↓
Transformer Layer 1
 ↓
...
 ↓
Transformer Layer N
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

其中真正负责“预测下一个 token”的位置是：

```text
Final Hidden State
        ↓
      LM Head
        ↓
      Logits
        ↓
Softmax / Sampling
        ↓
   Next Token ID
```

Transformer 前面的几十层，本质上是在不断加工当前 token 的 hidden state。

---

# 2. Tokenizer、Embedding 与 Hidden State

## 2.1 Tokenizer

Tokenizer 把文本转换成整数 Token ID。

例如：

```text
"The cat"
 ↓
Tokenizer
 ↓
[123, 456]
```

Tokenizer 通常由 CPU / 软件 runtime 完成，不是 HBM workload 的主要关注点。

它内部需要访问 vocabulary、tokenization rule 等数据，但对 AI accelerator 的 HBM 带宽压力通常很小。

---

## 2.2 Embedding

Token ID 本身只是一个整数，需要通过 Embedding Table 转换成向量。

假设：

$$
VocabSize=32000
$$

$$
HiddenSize=4096
$$

Embedding Table：

$$
[32000,4096]
$$

对于某个 token：

$$
x_t^{(0)}=Embedding[tokenID_t]
$$

所以：

```text
Token ID
   ↓
Embedding Table lookup
   ↓
x_t^(0)
```

---

## 2.3 Hidden State

$$
x_t^{(L)}
$$

表示：

> 第 \(t\) 个 token 在第 \(L\) 层 Transformer 中的内部向量表示。

例如：

$$
H=4096
$$

则：

$$
x_t:[1,4096]
$$

如果 FP16：

$$
4096\times2B=8KiB
$$

因此：

$$
\boxed{
单 token hidden state 大小
=
H\times bytes/element
}
$$

Hidden State 可以理解成：

> Transformer 主 datapath 上，层与层之间传递的核心 activation。

---

# 3. Activation、Weight、KV Cache 的区别

这是理解 AI Memory System 最重要的三个数据类型。

## Weight

模型训练后固定不变的参数，例如：

```text
WQ
WK
WV
WO
MLP W1/W2
LM Head Weight
```

特点：

* 容量大
* 推理阶段只读
* 一般主要存 HBM
* Decode 时大量读取

---

## Activation

一次 inference 运行过程中产生的动态中间数据。

例如：

```text
hidden state x
Q
K
V
Attention output
MLP intermediate
MLP output
```

特点：

* 动态产生
* 生命周期相对短
* 尽量保存在 SRAM / local buffer
* 不是所有 activation 都要写 HBM

因此：

$$
\text{Hidden State 是 Activation 的一种}
$$

但不是所有 Activation 都是 Hidden State。

---

## KV Cache

每个历史 token、每一层 Transformer 产生的：

$$
K_t,V_t
$$

需要长期保存，因为未来 token 的 Attention 还会继续使用。

特点：

* Runtime 数据
* Read + Write
* 随 sequence length 增长
* 随 batch 增长
* 通常需要放 HBM

---

# 4. 一个 Transformer Layer 做什么？

可以简化成：

```text
x
│
├─ Norm
│
├─ Attention
│
│   ├─ QKV Projection
│   ├─ QK^T
│   ├─ Softmax
│   ├─ ×V
│   └─ Output Projection
│
├─ Residual
│
├─ Norm
│
├─ MLP
│
└─ Residual
 ↓
next layer x
```

所以一个 Layer 最重要的两部分：

$$
\boxed{Attention + MLP}
$$

直觉上：

$$
\boxed{
Attention = token 之间交换信息
}
$$

$$
\boxed{
MLP = 对当前 token 的 feature 做进一步加工
}
$$

---

# 5. Q、K、V 的直觉

对一个 token：

$$
Q=xW_Q
$$

$$
K=xW_K
$$

$$
V=xW_V
$$

可以粗略理解为：

* Q：我在找什么？
* K：我有什么特征可以被别人匹配？
* V：如果别人关注我，我真正提供什么信息？

因此：

$$
QK^T
$$

决定：

> 应该关注谁。

而：

$$
Softmax(QK^T)V
$$

决定：

> 从被关注的 token 中真正取回什么信息。

一句话：

$$
\boxed{
Q/K 决定看谁，V 决定看到什么
}
$$

---

# 6. Multi-Head Attention

假设：

$$
H=8
$$

$$
N_{head}=2
$$

那么：

$$
HeadDim=\frac{H}{N_{head}}=4
$$

所以：

```text
hidden size = 8

Head 0 : 4 elements
Head 1 : 4 elements
```

逻辑上不同 Head 独立计算：

$$
Q_0K_0^T
$$

$$
Q_1K_1^T
$$

最后把各 Head output concat 回：

$$
H
$$

再做：

$$
OW_O
$$

即 Output Projection。

重要结论：

当 H 固定时，标准 MHA 分成多少 Head，核心 Attention MAC 数量大体不变。

因为：

$$
N_h\times D=H
$$

例如：

$$
Compute_{QK}
\sim
N_hS^2D
=
S^2H
$$

---

# 7. Softmax 的作用

Attention Score：

$$
Score=QK^T
$$

只是原始分数。

Softmax 把它变成：

$$
P_i=
\frac{e^{score_i}}
{\sum_j e^{score_j}}
$$

满足：

$$
\sum_i P_i=1
$$

可以理解为：

> 当前 token 对不同历史 token 的关注比例。

例如：

```text
Token A  10%
Token B  20%
Token C  70%
```

之后：

$$
Output=\sum_i P_iV_i
$$

---

# 8. Output Projection

Multi-Head Attention 每个 Head 都得到一个输出。

例如：

```text
Head0 output [D]
Head1 output [D]
...
```

Concat：

$$
[D\times N_h]=H
$$

然后：

$$
Output'=Output\times W_O
$$

其中：

$$
W_O:[H,H]
$$

作用可以暂时理解为：

1. 混合不同 Attention Head 的结果；
2. 把结果重新映射到标准 hidden size；
3. 使其能继续作为 Transformer 主 datapath 的 hidden state。

---

# 9. MLP 是什么？

简化 MLP：

$$
xW_1
\rightarrow
ActivationFunction
\rightarrow
W_2
$$

如果 expansion ratio = 4：

$$
H
\rightarrow
4H
\rightarrow
H
$$

例如：

$$
4096
\rightarrow
16384
\rightarrow
4096
$$

所以：

$$
W_1:[H,4H]
$$

$$
W_2:[4H,H]
$$

MLP 输入通常来自 Attention 后的 activation。

Attention → MLP 的 activation 可以尽量保存在片上 SRAM，不必回 HBM。

但 MLP 本身仍然需要读取：

$$
W_1,W_2
$$

所以：

> MLP activation traffic 可以较小，但 MLP Weight traffic 很大。

---

# 10. Prefill 与 Decode

这是 LLM inference 最重要的两个阶段。

## Prefill

输入 prompt 假设有：

$$
S=4096
$$

个 token。

一次处理：

$$
X:[4096,H]
$$

例如 Q projection：

$$
[4096,H]\times[H,H]
$$

一份 Weight 可以同时服务 4096 个 token。

因此：

> Weight reuse 高。

---

## Decode

Prefill 完成后，一个 token 一个 token 地生成。

每轮通常处理：

$$
x:[1,H]
$$

例如：

$$
[1,H]\times[H,H]
$$

Weight 大小和 Prefill 完全一样，但只服务一个 token。

因此：

> Weight reuse 很差。

与此同时 Decode 还需要读取历史 KV Cache。

所以：

$$
\boxed{
Prefill:
高 Weight reuse，偏 Compute Intensive
}
$$

$$
\boxed{
Decode:
低 Weight reuse + KV Read，偏 Memory Bandwidth Intensive
}
$$

---

# 11. KV Cache 为什么存在？

假设已经有：

```text
Token 1
Token 2
...
Token 1000
```

生成当前 token 时：

$$
Q_{new}
$$

需要和：

$$
K_1...K_{1000}
$$

计算 Attention。

然后还需要：

$$
V_1...V_{1000}
$$

如果不保存历史 K/V，则每生成一个 token 都必须重新计算所有历史 token 的 K/V。

所以：

```text
历史 token
   ↓
计算 K/V 一次
   ↓
保存到 KV Cache
   ↓
未来重复读取
```

KV Cache 的本质：

$$
\boxed{
用 Memory Capacity 换 Compute
}
$$

Q 不需要保存，因为 Q 只服务当前 token。

---

# 12. LM Head

所有 Transformer Layer 完成后得到：

$$
x_t^{final}:[1,H]
$$

假设：

$$
H=4096
$$

$$
Vocab=32000
$$

LM Head Weight：

$$
W_{LM}:[4096,32000]
$$

计算：

$$
[1,4096]\times[4096,32000]
$$

得到：

$$
Logits:[1,32000]
$$

Logit 表示：

> 每个候选 token 的原始分数。

LM Head 本质上仍然是：

$$
\boxed{
Activation\times Weight
}
$$

所以它也是一次较大的 Matrix Compute，并可能产生明显 HBM Weight traffic。

---

# 13. Sampling

LM Head 得到：

```text
token A score
token B score
token C score
...
```

然后可以进行：

```text
Temperature
 ↓
Softmax
 ↓
Top-K / Top-P
 ↓
Sampling
 ↓
Next Token
```

Temperature 控制概率分布尖锐程度。

Temperature 小：

> 更偏向最高概率结果。

Temperature 大：

> 更随机、更多样。

Top-K：

> 只从概率最高的 K 个 token 中选择。

Top-P：

> 保留累计概率达到 P 的候选集合。

Sampling 本身的数据规模远小于 Transformer GEMM 和 KV Cache，一般不是 HBM 主瓶颈。

---

# 14. 一次完整 Decode Step

```text
当前 token
   ↓
Embedding
   ↓
x_t^(0)
   ↓
Layer 0
   ├─ Attention
   └─ MLP
   ↓
Layer 1
   ↓
...
   ↓
Layer 31
   ↓
Final Norm
   ↓
LM Head
   ↓
Logits
   ↓
Sampling
   ↓
token_(t+1)
```

然后：

```text
token_(t+1)
   ↓
Embedding
   ↓
重新经过全部 Layer
   ↓
预测 token_(t+2)
```

所以：

$$
\boxed{
一个 Decode Step
=
生成一个新 token
}
$$

---

# 15. 一个标准 MHA FP16 模型的参数

用于性能分析：

$$
H=4096
$$

$$
L=32
$$

$$
S=4096
$$

$$
Heads=32
$$

$$
HeadDim=128
$$

因为：

$$
32\times128=4096
$$

MLP：

$$
Intermediate=4H=16384
$$

FP16：

$$
2B/element
$$

---

# 16. Model Weight 公式推导

一个 Layer：

Attention：

$$
W_Q:H^2
$$

$$
W_K:H^2
$$

$$
W_V:H^2
$$

$$
W_O:H^2
$$

所以：

$$
AttentionWeight=4H^2
$$

MLP：

$$
W_1:H\times4H=4H^2
$$

$$
W_2:4H\times H=4H^2
$$

所以：

$$
MLPWeight=8H^2
$$

总计：

$$
\boxed{
Weight/layer=12H^2
}
$$

L 层：

$$
Parameters=L\times12H^2
$$

FP16：

$$
\boxed{
ModelWeight
=
L\times12H^2\times2B
}
$$

代入：

$$
H=4096,L=32
$$

得到：

$$
\boxed{
12GiB
}
$$

这里忽略 Embedding、LM Head、Norm 等。

---

# 17. KV Cache / token 公式推导

一个 token、一个 Layer：

$$
K:[H]
$$

$$
V:[H]
$$

所以：

$$
K+V=2H
$$

FP16：

$$
2H\times2B
$$

L 层：

$$
\boxed{
KV/token
=
L\times2H\times2B
}
$$

代入：

$$
L=32,H=4096
$$

得到：

$$
\boxed{
512KiB/token
}
$$

---

# 18. KV Capacity

一条 sequence 有 S 个 token：

$$
KV=S\times KV/token
$$

如果 Batch = B：

$$
\boxed{
KVCapacity
=
B\times S\times KV/token
}
$$

例如：

$$
B=1,S=4096
$$

：

$$
4096\times512KiB
=
\boxed{2GiB}
$$

所以：

```text
S=4096  → 2 GiB
S=8192  → 4 GiB
S=16384 → 8 GiB
```

标准 MHA 下 KV Capacity 与 sequence length 线性增长。

---

# 19. Decode 每 token 的 HBM Traffic

Batch=1 Decode 时，整个 token 要走所有 Layer。

如果模型 Weight 无法长期驻留在 SRAM，则近似：

$$
WeightRead/token
\approx
ModelWeight
$$

所以：

$$
\approx12GiB
$$

同时需要读取全部历史 KV：

$$
HistoricalKV
=
S\times KV/token
$$

S=4096：

$$
=2GiB
$$

新 token 还会产生：

$$
512KiB
$$

KV Write。

因此：

$$
Bytes/token
\approx
12GiB+2GiB+512KiB
$$

可以近似：

$$
\boxed{
Bytes/token
\approx14GiB
}
$$

---

# 20. Decode 的统一公式

Model Weight：

$$
12LH^2b
$$

Historical KV：

$$
2LSHb
$$

所以：

$$
\boxed{
Bytes/token
\approx
12LH^2b
+
2LSHb
}
$$

提取公共项：

$$
\boxed{
Bytes/token
\approx
2LHb(6H+S)
}
$$

其中：

* L = Layer 数
* H = hidden size
* S = context length
* b = bytes/element

---

# 21. Weight Traffic 和 KV Traffic 什么时候相同？

令：

$$
12LH^2b
=
2LSHb
$$

约掉：

$$
2LHb
$$

得到：

$$
6H=S
$$

所以：

$$
\boxed{
S=6H
}
$$

对于：

$$
H=4096
$$

：

$$
S=24576
$$

约：

$$
24K
$$

因此在这个简化标准 MHA 模型下：

> Context 到约 24K 时，KV Read Traffic 已经和 Model Weight Traffic 同量级。

继续增加 context 后：

> KV traffic 会逐渐超过 Weight traffic。

---

# 22. HBM Bandwidth Requirement

如果：

$$
Bytes/token=14GiB
$$

目标：

$$
TokenRate=50token/s
$$

则：

$$
RequiredEffectiveBW
=
14GiB/token
\times
50token/s
$$

得到：

$$
\boxed{
700GiB/s
}
$$

通用公式：

$$
\boxed{
RequiredBW
=
Bytes/token\times Tokens/s
}
$$

---

# 23. 再考虑 Memory Efficiency

HBM Peak BW 不等于实际可用 BW。

如果：

$$
Efficiency=70\%
$$

则：

$$
PeakBW
\geq
\frac{RequiredEffectiveBW}{Efficiency}
$$

例如：

$$
\frac{700GiB/s}{0.7}
=
1000GiB/s
$$

约：

$$
\boxed{1TiB/s}
$$

所以：

$$
\boxed{
PeakHBMBW
\geq
\frac{Bytes/token\times Tokens/s}
{\eta_{memory}}
}
$$

这一步开始真正进入 Memory Controller / HBM Performance Analysis。

---

# 24. Weight 与 KV 对 HBM 的访问特点

## Weight Traffic

特点：

```text
Read-only
大块连续读取
模式规则
容易 prefetch
生命周期固定
Decode 时反复 streaming
```

因此适合重点考虑：

* Sequential bandwidth
* Prefetch
* Burst efficiency
* Channel striping
* Weight placement

---

## KV Cache Traffic

特点：

```text
Read + Write
容量随 sequence 增长
容量随 batch 增长
地址与 layer/head/token 有关
Long Context 下流量很大
```

因此适合考虑：

* KV layout
* Address mapping
* Channel / PC balancing
* Bank parallelism
* Read/write arbitration
* Locality
* Prefetch
* Cache policy

---

# 25. 一个重要的 Batch 结论

Batch=1：

$$
12GiB
$$

Weight 只服务一个 token。

Batch=8 时，如果可以一起执行：

$$
12GiB
$$

Weight 可以服务 8 个 sequence 当前的 token。

因此平均：

$$
WeightTraffic/token
=
\frac{12GiB}{8}
=
1.5GiB
$$

所以：

$$
\boxed{
Batch 主要提高 Weight Reuse
}
$$

这也是 Continuous Batching 对 LLM Serving 很重要的原因之一。

---

# 26. 当前阶段最重要的核心认知

第一：

$$
\boxed{
Transformer 本质上大量执行
Activation\times Weight
}
$$

第二：

$$
\boxed{
Activation 尽量片上流动，
Weight 和 KV 是 HBM 主流量
}
$$

第三：

$$
\boxed{
Prefill 的优势是 Weight Reuse
}
$$

第四：

$$
\boxed{
Decode 的问题是 Weight Reuse 差 + Historical KV Read
}
$$

第五：

$$
\boxed{
Long Context 主要放大 KV Capacity 和 KV Bandwidth
}
$$

第六：

$$
\boxed{
Batch 主要改善 Weight Bytes/token
}
$$

---

# 27. 复习问题

## 基础概念

1. Token ID 和 Hidden State 有什么区别？
2. Embedding 做了什么？
3. Hidden State 和 Activation 是什么关系？
4. Weight 和 Activation 在 inference 中最大的区别是什么？
5. 为什么 Q 不需要进入 KV Cache，而 K/V 需要？

## Attention

6. Q、K、V 分别代表什么直觉？
7. \(QK^T\) 在计算什么？
8. Softmax 为什么需要存在？
9. \(Softmax(QK^T)V\) 的物理含义是什么？
10. 为什么需要 Multi-Head Attention？
11. H 固定时，增加 Head 数是否显著增加 QK 的总 MAC 数？
12. Output Projection \(W_O\) 做什么？

## MLP

13. MLP 在 Transformer Layer 哪个位置？
14. 为什么说 MLP 输入 activation 可以留 SRAM，但 MLP 仍然需要大量 HBM 访问？
15. 为什么一个简单 \(4H\) expansion MLP 的 Weight 大约是 \(8H^2\)？

## Prefill / Decode

16. Prefill 是 Transformer 模块还是 inference 阶段？
17. Prefill 为什么 Weight reuse 高？
18. Decode 为什么 Weight reuse 低？
19. 为什么 Decode 通常更 Memory-Bound？
20. Context 越长，Decode 的哪个 Traffic 会持续增加？

## KV Cache

21. KV Cache 的本质是用什么换什么？
22. 为什么每个 Layer 都需要独立 KV Cache？
23. KV Cache 为什么与 Batch 线性相关？
24. KV Cache 为什么与 Sequence Length 线性相关？
25. 标准 MHA 下，每 token KV Cache 如何从 H、L 推导？

## LM Head

26. LM Head 的输入是什么？
27. LM Head 的输出是什么？
28. 为什么 LM Head 仍然可以理解成一次 Activation × Weight？
29. Logits 和 Probability 有什么区别？
30. Sampling 在整个 Decode 流程的哪个位置？

## HBM / 性能

31. 为什么 Batch=1 Decode 可以近似认为每生成一个 token 要流过整个 Model Weight？
32. 为什么 Prefill 不能简单按 Model Weight/token 来计算？
33. \(12H^2\) 是怎样从 Transformer Layer 的 Weight 构成推出来的？
34. 为什么 Historical KV Read 为 \(2LSHb\)？
35. 为什么标准 MHA 下 Weight Traffic 与 KV Traffic 相等时有：

$$
S=6H
$$

36. 如何从 Bytes/token 推导 Required HBM BW？
37. 为什么还需要除以 Memory Efficiency？
38. Weight Traffic 和 KV Traffic 在 HBM access pattern 上最大的区别是什么？
39. 对 HBM Controller 来说，KV layout 为什么会影响 PC / Bank utilization？
40. 为什么 Continuous Batching 可以显著改善 Decode 的 Weight efficiency？

---

# 28. 最终建议记住的四条公式

简化标准 MHA、MLP expansion=4：

## Model Weight

$$
\boxed{
ModelWeight
\approx
L\times12H^2\times b
}
$$

## KV Cache / token

$$
\boxed{
KV/token
=
L\times2H\times b
}
$$

## KV Capacity

$$
\boxed{
KVCapacity
=
Batch\times S\times KV/token
}
$$

## Decode Traffic

$$
\boxed{
Bytes/token
\approx
ModelWeight
+
HistoricalKV
}
$$

进一步：

$$
\boxed{
Bytes/token
\approx
12LH^2b+2LSHb
}
$$

最后：

$$
\boxed{
RequiredHBMBW
=
Bytes/token\times TokenRate
}
$$

若考虑 Memory Efficiency：

$$
\boxed{
PeakHBMBW
\geq
\frac{Bytes/token\times TokenRate}
{\eta_{memory}}
}
$$

---

# 29. 最终脑图

```text
Text
 ↓
Tokenizer
 ↓
Token ID
 ↓
Embedding
 ↓
Hidden State
 ↓
┌──────────────────────┐
│ Transformer Layer    │
│                      │
│ Attention            │
│ QKV → QK → Softmax   │
│ → V → Output Proj    │
│                      │
│ MLP                  │
│ H → 4H → H           │
└──────────────────────┘
 ↓
重复 N Layers
 ↓
Final Hidden State
 ↓
LM Head
 ↓
Logits
 ↓
Sampling
 ↓
Next Token
```

对应 Memory：

```text
                  HBM
                   │
        ┌──────────┴──────────┐
        │                     │
     Weight                KV Cache
        │                     │
        ▼                     ▼
             SRAM / Buffer
                  │
                  ▼
             Tensor Compute
                  │
                  ▼
              Activation
                  │
            尽量片上流动
```

最终需要形成的工程思维是：

$$
\boxed{
Model
\rightarrow
Tensor
\rightarrow
Bytes
\rightarrow
Traffic
\rightarrow
HBM
\rightarrow
Performance
}
$$
