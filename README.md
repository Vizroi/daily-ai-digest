# daily-ai-digest

每天一期的 AI 与游戏开发内参。给一个做 UE5 战斗系统的策划看，不是给流量看。

页面：<https://vizroi.github.io/daily-ai-digest> · RSS：`docs/feed.xml`（只推深读区）

---

## 它和普通 RSS 聚合器的区别

聚合器的默认失败方式是「什么都收进来，然后按时间排」。这样产出的东西，进不进日报取决于发得早不早，而不是值不值得看；摘要因为只拿到 RSS 里那两百个字符，只能同义改写标题。

v2 的做法是**把钱和注意力集中花在少数几条上**：召回四百条，但只有分数过线的七八条会被抓正文、单条调用大模型深读，其余一百多条压成一行放进折叠区。宁缺毋滥——某天只有两条够格，那天就只放两条。

排序不交给大模型。它没有全局视野，也不可复现。用一条纯 Python 的可解释公式，并且**把分数和评分依据直接印在页面上**：排序逻辑可见，才可被质疑和调整。

---

## 五阶段流水线

```
① 宽召回     26 个 RSS 源 + HN Algolia + HF Papers + GitHub Trending
                每源 12 篇、72 小时窗口，顺带带回社区热度信号
      ↓ ~400 条
② 事件聚类   一次 LLM 调用，跨语言把讲同一件事的条目合并成 event
                「OpenAI 发布 X」和「OpenAI unveils X」字面重叠为零，
                字符串相似度在这里必然失效，所以用模型
      ↓ ~190 个 event
③ 打分排序   纯 Python 可解释公式，见下
      ↓
④ 分级精读   过线的抓正文全文 → 每条单独一次 LLM 调用 → 三段式
                其余批量一句话 / 只翻译标题
      ↓
⑤ 分层渲染   六个区块 + RSS 输出 + 按日归档
```

| 文件 | 职责 |
|---|---|
| `src/config.py` | 源分档、权重、阈值、关键词表——所有可调参数都在这里 |
| `src/fetch_sources.py` | 宽召回 + 社区信号 + 源健康度统计 |
| `src/cluster.py` | LLM 跨语言事件聚类，失败则降级为「每条各自成组」 |
| `src/rank.py` | 打分、分区、配额池、跨天新颖度惩罚 |
| `src/readfull.py` | 只对深读区抓正文（trafilatura，线程池并发） |
| `src/summarize.py` | 分级摘要 + 禁用词校验重试 + 降级 |
| `src/render.py` | 页面渲染（少年漫分镜版式）+ 归档 |
| `src/feed.py` | `docs/feed.xml` |
| `src/commit_memory.py` | 按最终发布结果写 14 天记忆（必须在降级筛选之后） |

---

## 打分公式

```python
score  = min(coverage, 5) * 12                   # 跨源覆盖，最强信号
       + max(TIER_WEIGHT[s] for s in sources)    # 源权威 1/2/3 档 = 18/8/2
       + log1p(hn_points)   * 2.0                # HN 是唯一可靠的公开分数源
       + 8 if hn_points >= 300 else 0            # HN 头条 ≈ 一次群体投票
       + log1p(hf_upvotes)  * 4.0
       + log1p(stars_today) * 2.0
       + 32 if 命中 COMBAT_KEYWORDS else         # 战斗策划核心词（103 个）
         20 if 命中 OTHER_KEYWORDS  else 0       # 引擎/动画/网络/性能（50 个）
       - 30 if 14 天内报过 else 0                # 并标记为「线索追踪」
```

`DEEP_READ_MIN_SCORE = 32`。这套取值让**「至少两家独立源报道过」成为进必读区的实际门槛**。

> 权重是用真实数据校准的，不是拍的。初版 `coverage×8 + log1p(hn)×3.0` 会让一条 222 分的 Show HN 玩具帖压过「阿里发布 2.4 万亿参数模型，三家独立源报道」——排序目标整个反了；同时 45 分的必读阈值在那套权重下数学上不可达（上限约 43）。**改权重之后一定要用真实数据重跑一遍再看排序**，单元测试抓不到这类缺陷。

关键词匹配范围按源分档区别对待：tier1/tier2 匹配标题 + 摘要（官方与媒体标题常是市场化措辞），**tier3 社区源只匹配标题**——标题是发帖人自己的主题声明，用正文匹配等于让「提到过」冒充「讲的是」。抓不到正文的条目一律退回速览区。

### 改关键词表时的裸词陷阱

都是真会命中的，别加回来：

| 裸词 | 会误命中 |
|---|---|
| `i-frame` | 视频编码的关键帧，NVIDIA / 编解码类文章一抓一把 |
| `ability system` | 字面包含在 `capability system` 里，拉进一堆能力安全模型文章 |
| `gas ` | 天然气、油气、gas fee |
| `soft lock` | 消费向媒体里指卡关 bug，不是软锁定 |
| `stagger` | 分批灰度发布 |
| `lod` | cloud / global / flood |
| `optimization` | 命中过一篇铁路排班论文 |

另外，**词表堆得再厚也变不出源里没有的东西**。2026-08-04 实测：193 条召回里战斗词命中数为 0——词表本身是对的（13 条合成样例全部正确分级），是当天的源里确实没人聊战斗设计。缺内容要从源那头补，不是从词表这头补。

---

## 页面

版式取自少年漫的分镜页：黑墨粗框 + 硬投影分格、集中線、伤害数字、对话气泡。选它不是因为好看，是因为**它天生就是一套优先级语言**——一页漫画里哪一格重要，读者不用被告知。

签名元素是标题右上角那个歪着的伤害数字：它就是 rank.py 算出的分数，底下压一条分段覆盖条（几家独立源报道了）。

克制的地方：集中線只给必读区第一条，伤害数字只出现在深读的分格里，圆角全页只有「对你而言」那个气泡有。一页上五个爆点等于没有爆点。饱和度整体压过一档（朱红 `#A8423A`、旧纸黄 `#D8BF74`、报纸灰底 `#EDEAE1`），原色四色印刷适合封面，不适合每天读二十条。

| 区块 | 规则 |
|---|---|
| 今日必读 | 阈值制，宁可只有 2 条；为空则显示留白说明，不凑数 |
| 能用上的 | 命中相关词就冒头，战斗词排前面；**为空则整块隐藏** |
| 线索追踪 | 14 天内报过、今天又有新报道的 |
| 深水区 | 3 图形学论文 + 3 AI 论文 + 3 开源，独立配额池不参与主排序竞争 |
| 跨界视野 | 固定优质池取最高分，不随机 |
| 一行速览 | 其余全部，`<details>` 折叠 |

---

## 本地跑

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-...

python src/fetch_sources.py     # → data/raw.json, data/health.json
python src/cluster.py           # → data/events.json      （用 API）
python src/rank.py              # → data/ranked.json
python src/readfull.py          # → 就地补 body 字段
python src/summarize.py         # → data/digest.json      （用 API）
python src/render.py            # → docs/index.html + docs/archive/
python src/feed.py              # → docs/feed.xml
python src/commit_memory.py     # → data/memory.json
```

只调版式不想烧 API：留着 `data/digest.json`，反复跑 `render.py` 就行。

`data/memory.json` 是跨天去重和「线索追踪」的唯一状态，**必须提交进仓库**，否则每天都是第一天。调试时如果被 −30 的重复惩罚干扰，把它清成 `{}` 再跑。

---

## 配置

仓库 Settings → Secrets → Actions 里加 `DEEPSEEK_API_KEY`。只有聚类和摘要两步用到它，别的步骤不需要。

Settings → Pages → Source 选默认分支（`main`）的 `/docs` 目录。

Actions 每天 UTC 00:30（北京 08:30）跑一次，产物提交 `docs/` 和 `data/`。

## 成本

13 次调用、约 8 万 input token / 天。DeepSeek 现价下大约 ¥0.1–0.2 一天，一年不到 70 块。运行 4–6 分钟。

## 已知会慢性衰退的地方

RSS 源静默失效是这类项目最常见的死法：路径改了、站点关了，`_safe_fetch` 只打一行 WARN，日报悄悄变薄。所以 `data/health.json` 记录每个源的产出条数和**连续零产出天数**，连续超过 `HEALTH_ALERT_DAYS`（默认 7 天）才在页面底部告警。

不按当天零产出告警，是因为当天 0 条完全可能是正常的：DeepMind、Unreal Engine 官博本来就不天天发，72 小时窗口里空手而归是常态。当天就报警等于每天喊狼来了，喊几次之后这行字会被彻底忽略——那时候真挂了也看不见。
