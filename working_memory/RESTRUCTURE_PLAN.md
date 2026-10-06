# RESTRUCTURE PLAN（HISTORICAL ARCHIVE）

> **⚠️ THIS FILE IS HISTORICAL — DO NOT UPDATE.**
> 本文件是 Phase 1~5 重构过程的历史存档。重构已完成（FINAL-FROZEN）；
> authoritative 内容一律以 `DDR_Controller_Architecture.md` 为准。
>
> **[reconstructed—verify against chat history]**：本文件在 Phase 5 会话丢失后于 recovery 分支重建。
> Phase 叙述与 Appendix B 分章结构按主文档最终态与遗留引用反向重构；原始 plan 工作文件
> （_plan_p1~p5.md）与对话历史逐字稿未保留在当前工作区，个别行无法逐字核对——以本标注为准。
> 原始 50KB 版本若需要，请从 git 历史或对话存档恢复。

---

## 1. Phase 总览（reconstructed）

| Phase | 内容 | 结果 |
|---|---|---|
| Phase 1 | 主文档骨架重组：Ch0（Architecture Map）+ Ch1（Interview Navigation / RQ1~RQ15）+ Part I（Ch2~Ch8 Performance）/ Part II（Ch9~Ch11 Correctness）/ Part III（Ch12~Ch18 RTL Reference）+ 附录 A/C | 完成 |
| Phase 2 | Legacy Zone 迁移：旧文档全部章节内容按 Appendix B 映射拆入新章；Legacy 原文删除 | 完成 |
| Phase 3 | Part III RTL Reference 补全（Ch12 XMU / Ch13 CAM/CQ / Ch14 CS / Ch15 Timing / Ch16 WDP-RDP / Ch17 DFI / Ch18 Observability） | 完成 |
| Phase 4 | Legacy Cleanup + 术语/schema 定稿（7-P1-04/05、RC-1、XMU-P1-01、DP2-P1-01 等 Registry 项） | 完成 |
| Phase 5 | Final Audit（23 项）+ FINAL-FROZEN 头 + INTERVIEW_QUESTIONS.md 退役（tombstone） | 完成 |
| Post-5（recovery 重放） | Engineering-Language / RQ1 Cleanup / CS-RTL Integration / HBM RTL Evidence / Readability 六 patch | 见 git recovery-branch |

## 2. Freeze 记录（reconstructed）

- **Part I / Part II = FROZEN**（authoritative Performance / Correctness Architecture）
- **Part III = STRUCTURALLY COMPLETE**（Ch15 CONTENT PARTIAL 登记）
- **Ch0~Ch1 = 面试导航层**，随 Registry 更新同步
- **附录 A = living backlog**（唯一 authoritative Open Question Registry）
- **附录 C = authoritative Global State Owner Table**
- FINAL-FROZEN 语义：结构 / terminology / evidence labels / navigation / RTL mapping 稳定自洽；**不等于** ALL QUESTIONS CLOSED

## 3. Appendix B — 分章映射表（reconstructed from 主文档最终态）

> 旧文档章节号已随 Legacy Zone 删除而不可考；本表按"新文档章节 → 内容来源域"方向给出映射。
> 每章详细映射行如需逐字核对，请对照对话历史（本表行级精度标 [reconstructed]）。

| 新文档章 | 内容域 | 来源 |
|---|---|---|
| Ch0 | Architecture Map：核心使命 / Data Plane 主轴 / Control Plane / BW Efficiency & Attribution / blocked reason / Ownership Map / 设计方法 / 纪律 / 证据标签 | 原总览 + 性能口径章 |
| Ch1 | Interview Navigation：RQ1~RQ15 + 四段式 + 90s 回答结构 + 追问引导 + 总表 | 原面试问题追踪清单（→INTERVIEW_QUESTIONS.md RETIRED） |
| Ch2 | V1 Demand / V2 Visibility / V3 Admission-Credit | 原 request/queue 域 |
| Ch3 | L1 Row Hit / L2 BLP / L3 Channel·SID / L4 Page Policy（宿主 Ch4）/ L5 Mapping | 原 locality/mapping 域 |
| Ch4 | S1 CCT 提名 / S2 GSC selection / S3 QoS-Aging / L4 Page Policy | 原 scheduler 域 |
| Ch5 | T1 Timing Supply 总纲 / T2 ACT 类 / T3 col 类 | 原 timing 域 |
| Ch6 | D1 R/W switching / D2 rank·SID switching | 原 direction 域 |
| Ch7 | M1 refresh debt / M2 refresh scheduling / M3 deadline watchdog / M4 RFM-RAA / M5 DRFM | 原 maintenance 域 |
| Ch8 | DP1 write data ready / DP2 read return / DP3 DFI-PHY delivery | 原 data path 域 |
| Ch9 | C1 Ordering / C2 Dependency / C3 Commit-PNR | 原 correctness 域 |
| Ch10 | R1 RAS-Retry-Recovery | 原 RAS 域 |
| Ch11 | G1 Global State Transition / Quiesce（LP/DVFS/init/training） | 原 device mgmt 域 |
| Ch12 | XMU RTL Reference | 原 XMU 素材 |
| Ch13 | CAM/CQ RTL Reference | 原 CAM 素材 |
| Ch14 | BSC/GSC/FSC RTL Reference（三层 CS + BSC FSM 表 + Executed Feedback） | 原 CS 素材 |
| Ch15 | Timing Counter RTL Reference（五级 counter / tFAW / inline / DVFS CSR bank） | 原 timing counter 素材 |
| Ch16 | WDP/RDP RTL Reference | 原 data buffer 素材 |
| Ch17 | DFI RTL Reference（ratio / phase0 / rolling / PF window / csrRdDataEn chain） | 原 DFI 素材 |
| Ch18 | Performance Observability RTL Reference（Table A/B/C + 能推/不能推） | 原 observability 素材 |
| 附录 A | Open Question Registry（P0/P1 分级 + Node-scoped schema） | 原开放问题清单 |
| 附录 C | Global State Owner Table | 原 ownership 表 |

## 4. Invariants（19 项说法的历史注）

Phase 2~5 期间维护过一组"重构不变量"清单（如：blocked taxonomy 12 类不增删、Node 11 字段模板、
6+1 RTL 模板、owner 唯一性、Registry 对应规则等）。原文逐条未保留；现行有效版本以主文档
0.7~0.9 / 1.19 / 附录 A 头部 / Ch14/Ch15 模板段为准——那里是 authoritative 表述。

---

*End of historical archive. 后续修订不进入本文件。*
