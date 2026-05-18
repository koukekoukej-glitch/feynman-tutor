# 把可视化交给 grimoire

## 什么时候交

你和他在某个抽象内容上文字讲了一两遍他还没看清——就该让另一个工具来画。常见触发：

- 公式里某个符号怎么从 Σ 内提到 Σ 外
- 矩阵 / 向量运算到底是按行配列、还是按列配行
- 一层链式法则套下去之后中间的哪一项约掉了
- 注意力分数到底是怎么打出来的
- 一段公式的具体变换过程（比如分配律展开 DPLR、提取公因子、定义新符号）
- 多种算法 / 系统的对比（时序图 / 复杂度趋势 / benchmark 表 / 状态机 / 模型结构）

## grimoire 能做什么

它的工具箱有 5 类：

| 想讲清楚什么 | 它会用什么 |
|---|---|
| 公式怎么一步步变换 | MathDeriveCard + 12 个 templates（元素级 morph 动画） |
| 矩阵 / 向量运算怎么算 | 8 个 matrix-ops 原子组件 |
| 单个符号在公式里是什么意思 | HoverFormula 字典（hover 弹注释） |
| 整页叙事骨架 | page-template.html（古卷夜书房视觉系统） |
| 时序对比图 / 复杂度图 / benchmark 表 / 状态机 / 模型结构图 | 自由 SVG 叙事图块（5 条约束保证视觉一致 + 信息保真） |

你给它任务时不用挑工具——它自己按工具箱表选。但你**必须给清楚要讲的内容**——它没法替你判断要讲什么。

## brief 它的时候 · 输入契约

下面这份是 grimoire SKILL.md 里写好的输入期望——你不按这个传、它会缺信息脑补、产出失准。

### 必填

- **要讲清楚的核心概念（一句话提炼）**——例：「KDA 的 chunk-wise 训练算法、为什么需要它 + DPLR 数学结构怎么让 chunk 内并行变可能」。grimoire 看不见你和他的对话、必须由你完整翻译给它。
- **输出 HTML 文件的绝对路径**——按 Windows 正斜杠写、放在当前话题笔记旁边的 `examples/` 子目录。例：`C:/Users/User/.claude/skills/feynman-tutor/notes/domains/ai-deep-learning/examples/kda-dplr-chunkwise.html`

### 推荐

- **学习者状态**——「他已经懂 X / Y / Z、现在卡在 A」。决定 grimoire 选切入密度（已经懂的快带过、卡的地方多展开）。原话：「他懂线性 attention 完整推导和 KDA 公式、卡在 chunk-wise 训练算法为什么需要 DPLR 这种数学结构」。
- **段落规划**——你已经想清楚要分成几段、每段讲什么、按 §I-§N 列出来。例：
  - §I T_t vs S_t 角色区分（T 结构化、S 稠密）
  - §II T_t 的 DPLR 结构展开
  - §III 简化情况（纯对角）的 chunk-wise
  - §IV DPLR 累乘的展开
  - §V wallclock 收益对比
  
  没传的话 grimoire 会自己拆——但你拆的判断通常更准（你知道他卡在哪）、传过去更稳。

### 可选

- **数据示例**——具体的 d / N / chunk size 数字、让 grimoire 直接用而不是自己编。原则上 d 取小（3 或 4）方便可视化。
- **必用工具的硬约束**——「这一段必须用 MathDeriveCard 而不是静态 KaTeX」、「这一段必须用 matrix-ops 组件」、「最后一段画叙事图块对比 wall time」。
- **风格偏好**——颜色映射、强调哪些角色色之类。

## 默认行为 · 你没传时它怎么办

- 你没传**段落规划**——grimoire 自己把核心概念拆段
- 你没传**学习者状态**——grimoire 按白板假设、密度均匀铺开
- 你漏了**核心概念**或**输出路径**——grimoire 应该回问你、不要让它自己脑补；如果它直接产出了、说明它脑补了、得审一遍

## 怎么 spawn

开一个独立 subagent 去跑 grimoire skill、让 subagent 自己读 grimoire 的 SKILL.md 决定怎么画——它会按统一工作流：理解 brief → 为每段挑工具 → 拼起来 → 自检。

subagent 写完文件、把绝对路径返回给你。

## 怎么呈现给他

用 `file:///` 协议把路径贴给他、让他自己点开。一行就够：

> 图在这里：`file:///C:/Users/User/.claude/skills/feynman-tutor/notes/linear-attention/numerator-extract.html`

不要展开解释 grimoire 内部做了什么——他要看的是图、不是工具说明。

## 他看完之后

回到这场对话继续聊。他想问「为什么这一步要这么换」、你照样在文字里和他讨论、不要把他推回去看图。

## 反例 · 一次踩过的坑

2026-05-12 KDA chunk-wise 那次产出之所以出问题（公式没解释、矩阵格式错位、整页 CSS 手搓不基于 page-template）——根因之一是 brief 不够规范：

- 给了「要画的对象」但没明确说「公式变换段必须用 MathDeriveCard」「整页必须基于 page-template.html」
- subagent 自己判断「这是复合需求」、走了「快路径 + 自己手搓」、错过了 MathDeriveCard 那条路径

这次 grimoire SKILL.md 已经统一成一条工作流、subagent 不再有「快路径 vs 主工作流」的二分困扰、但**你的 brief 仍然要清楚**——尤其是必填字段、漏了 grimoire 就要脑补。
