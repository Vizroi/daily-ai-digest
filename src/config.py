"""配置：信息源分档、个人相关度词表、流水线参数。

设计原则：
  - 源不再是扁平列表，而是三档权重。一手源 > 分析源 > 聚合/消费源。
  - 召回阶段求全（每源 12 篇），筛选交给 rank.py 的打分公式。
  - RELEVANT_KEYWORDS 是「能用上的」栏目的唯一机制，命中即加大额分数。
"""

# ── LLM 配置 ────────────────────────────────────────────────
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# ── 源分档权重 ──────────────────────────────────────────────
# tier1 一手源：当事人自己发布的，信息最准、时间最早
# tier2 分析源：有编辑判断和增量分析
# tier3 聚合/消费源：转述、搬运、玩家向
TIER_WEIGHT = {1: 18, 2: 8, 3: 2}

# 跨源覆盖每一档的分值。实测校准（2026-08-03）：
#   原本 coverage×8 + HN×3.0 会让单条 Show HN novelty 帖（222 分 → 32 分）
#   排在「阿里发布 2.4T 参数 Qwen3.8-Max，两家独立报道」（24 分）之上。
#   HN 热度是真信号但不该压过跨源覆盖，故上调覆盖、下调 HN。
COVERAGE_WEIGHT = 12
HN_FACTOR = 2.0

# HN 头条加成。log 曲线在高分段几乎压平（458 分和 699 分只差 0.8 分），
# 但「上到 HN 前几名」本质是一次群体投票式的跨源覆盖，值一个源的分量。
HN_FRONTPAGE = 300
HN_FRONTPAGE_BONUS = 8
HF_FACTOR = 4.0
STAR_FACTOR = 2.0

# ── RSS 源 ──────────────────────────────────────────────────
# tier 决定权威权重；lang 用于渲染标记。
# ⚠️ 全部地址已于 2026-08-03 实测返回 200 且有条目。
#    v1 的源表里有 3 个已经 404 很久了（见 DEAD_IN_V1），一直被静默吞掉。
RSS_SOURCES = [
    # ═══ tier1 一手源：AI 实验室官方 ═══
    {"name": "OpenAI", "url": "https://openai.com/news/rss.xml", "tier": 1, "lang": "en"},
    {"name": "DeepMind", "url": "https://deepmind.google/blog/rss.xml", "tier": 1, "lang": "en"},
    {"name": "Google Research", "url": "https://research.google/blog/rss/", "tier": 1, "lang": "en"},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml", "tier": 1, "lang": "en"},

    # ═══ tier1 一手源：引擎与 GPU 官方（与本职工作直接相关）═══
    {"name": "Unreal Engine", "url": "https://www.unrealengine.com/rss/news?lang=en-US", "tier": 1, "lang": "en"},
    {"name": "Unity", "url": "https://unity.com/blog/rss", "tier": 1, "lang": "en"},
    {"name": "NVIDIA Developer", "url": "https://developer.nvidia.com/blog/feed", "tier": 1, "lang": "en"},

    # ⚠️ 已移出 tier1：forums.unrealengine.com/c/announcements/9.rss
    #    实测该 feed 返回的不是官方公告，而是论坛杂帖 —— 同一条 UEFN 公告的
    #    6 种语言副本、用户提问（"多人联机方面遇到的问题"）、甚至招人贴
    #    （"Ищу UE5 блюпринтера... RevShare"）。以 tier1 权重 + "ue5" 关键词
    #    命中，它会稳定霸占「能用上的」栏目。见 REMOVED_SOURCES。

    # ═══ tier1 一手源：arXiv 图形学（每天约 10 篇，与动画/渲染直接相关）═══
    # 注意：不要加 cs.AI —— 每天 260+ 篇，会用 tier1 权重淹没整个日报。
    # 通用 AI 论文走 HuggingFace daily_papers（有社区投票做筛选）。
    # pool="graphics"：不进主流程，单独一个「图形学 / 动画」小栏。
    # 混进 main 会让 9 篇干论文占满速览区；和 HF 论文比又必输
    # （HF 有社区投票加成，cs.GR 没有任何热度信号）—— 那才是真正该看的那一栏。
    {"name": "arXiv cs.GR", "url": "https://rss.arxiv.org/rss/cs.GR", "tier": 1, "lang": "en", "pool": "graphics"},

    # ═══ tier2 分析源 ═══
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "tier": 2, "lang": "zh"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "tier": 2, "lang": "en"},
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "tier": 2, "lang": "en"},
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "tier": 2, "lang": "en"},

    # ═══ tier2 分析源：游戏「开发」而非游戏「新闻」═══
    {"name": "Game Developer", "url": "https://www.gamedeveloper.com/rss.xml", "tier": 2, "lang": "en"},
    {"name": "80.lv", "url": "https://80.lv/feed", "tier": 2, "lang": "en"},
    {"name": "GamesIndustry", "url": "https://www.gamesindustry.biz/feed", "tier": 2, "lang": "en"},

    # ═══ tier3 行业动态（降权保留，用来看大厂和市场）═══
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "tier": 3, "lang": "en"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "tier": 3, "lang": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed", "tier": 3, "lang": "en"},
    {"name": "极客公园", "url": "https://www.geekpark.net/rss", "tier": 3, "lang": "zh"},
    {"name": "游戏陀螺", "url": "https://www.youxituoluo.com/feed", "tier": 3, "lang": "zh"},
    {"name": "GameFromScratch", "url": "https://gamefromscratch.com/feed/", "tier": 3, "lang": "en"},

    # ═══ tier3 Reddit ═══
    # 实测：/top.rss?t=day 与 /top.json 从数据中心 IP 一律 403/429，
    #       只有 /.rss 配「描述性 UA」能稳定 200。所以拿不到 ups 分数。
    #       Reddit 只作为线索补充源，排序主力靠 HN points + 跨源覆盖。
    {"name": "r/unrealengine", "url": "https://www.reddit.com/r/unrealengine/.rss", "tier": 3, "lang": "en"},
    {"name": "r/gamedev", "url": "https://www.reddit.com/r/gamedev/.rss", "tier": 3, "lang": "en"},
    # 2026-08-04 加：词表里堆战斗词没用，如果源里根本没人聊战斗设计。
    # r/gamedesign 是唯一稳定产出「机制怎么设计」讨论的公开源（实测 200，25 条/次）。
    # tier3 只按标题匹配，正好过滤掉那些泛泛而谈的长贴。
    {"name": "r/gamedesign", "url": "https://www.reddit.com/r/gamedesign/.rss", "tier": 3, "lang": "en"},
    {"name": "r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss", "tier": 3, "lang": "en"},
    {"name": "r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/.rss", "tier": 3, "lang": "en"},
]

# v1 源表里已经死掉但一直静默失败的源 —— 这就是为什么需要源健康度检查
DEAD_IN_V1 = {
    "机器之心": "jiqizhixin.com/rss 已下线（302 到 data-service，0 条目）。中文 AI 改由量子位+极客公园承担",
    "The Verge AI": "旧地址 404，正确地址是 /rss/ai-artificial-intelligence/index.xml",
    "Ars Technica AI": "/arstechnica/ai 已 404，改用 /arstechnica/technology-lab",
    "OpenAI Blog": "/blog/rss.xml 已改为 /news/rss.xml",
    "Google AI Blog": "blog.research.google 已迁至 research.google/blog/rss/",
    "Unity Blog": "blog.unity.com/feed 已迁至 unity.com/blog/rss",
    "GDC News / GDC Vault": "两个 RSS 均已 404，官方不再提供",
    "极客公园": "/feed 404，正确地址是 /rss",
}

# 官方不提供 RSS、只能靠他人报道覆盖的重要源（不要再尝试加了）
NO_RSS_AVAILABLE = {
    "Anthropic": "官网无任何 RSS/Atom 端点（news/engineering 均 404）",
    "Meta AI": "ai.meta.com/blog 所有 feed 路径返回 400",
}

# 已主动移除的 v1 源及理由（避免哪天手滑又加回来）
REMOVED_SOURCES = {
    "IGN / Kotaku / Polygon / PC Gamer / Eurogamer / 游民星空": "纯消费向：发售、评测、打折，对开发者价值≈0",
    "r/gaming / r/pcgaming / r/artificial": "玩家吐槽与泛讨论，信噪比极低",
    "Wired AI / MIT Tech Review": "全站 feed 非 AI 专用，多为科普转述",
    "IndieDB": "RSS 长期不更新",
    "Hacker News (hnrss)": "改用 Algolia API，RSS 拿不到 points",
}

# ── Hacker News：改用 Algolia API，能拿到 points / 评论数 ──
HN_API = "https://hn.algolia.com/api/v1/search_by_date"
HN_MIN_POINTS = 60          # 低于此分数不召回
HN_KEYWORDS = [             # 逐个关键词检索，比 frontpage 精准
    "LLM", "GPT", "Claude", "Gemini", "AI model", "diffusion",
    "Unreal Engine", "game engine", "graphics", "shader", "netcode",
]

# ── HuggingFace 每日论文 ──
HFPAPERS_API = "https://huggingface.co/api/daily_papers"

# ── GitHub Trending ──
GITHUB_TRENDING_URLS = [
    ("daily", "https://github.com/trending?since=daily"),
]

# ── 跨界视野：固定优质池，取最高分 1 条（不再随机，修 v1 的 hash 种子 bug）──
DIVERSE_SOURCES = [
    {"name": "Quanta Magazine", "url": "https://www.quantamagazine.org/feed/", "tier": 2, "lang": "en"},
    {"name": "Aeon", "url": "https://aeon.co/feed.rss", "tier": 2, "lang": "en"},
    {"name": "Nature", "url": "https://www.nature.com/nature.rss", "tier": 1, "lang": "en"},
    {"name": "The Economist", "url": "https://www.economist.com/latest/rss.xml", "tier": 2, "lang": "en"},
]

# 需要「描述性 UA」才不被封的域名（Reddit 讨厌伪装成浏览器的爬虫）
POLITE_UA_DOMAINS = ("reddit.com",)
POLITE_UA = "DailyAIDigest/2.0 (+https://github.com/Vizroi/daily-ai-digest)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")

# ── 个人相关度词表：命中即进「能用上的」栏目 ──────────────
# 这是整个系统里唯一为使用者本人定制的部分。
# 命中一个词加一次分，命中多个不叠加（避免关键词堆砌型标题刷分）。
#
# 词表分两级：战斗策划核心词给更高的分，其余相关词给基础分。
# 因为「能用上的」栏目内部按分数排序，加权直接决定了谁排在第一条。

# ═══ 一级：战斗策划核心词（本职，2026-08-04 按使用者要求加权）═══
# 排在词表最前面还有一个副作用是好的：页面上的命中徽章显示 hits[0]，
# 所以一条既提到 unreal 又提到 hitstop 的新闻，徽章会显示战斗词而不是引擎词。
COMBAT_KEYWORDS = [
    # 手感与打击反馈
    "combat design", "combat system", "combat feel", "game feel",
    "hitstop", "hit stop", "hit pause", "hit reaction", "hit react",
    "hitbox", "hurtbox", "knockback", "screen shake", "camera shake",
    "impact frame", "hit feedback",
    # 帧数据与取消窗口（这一组是战斗设计的语法本身）
    "frame data", "startup frames", "active frames", "recovery frames",
    "cancel window", "animation cancel", "input buffer", "input queue",
    "combo system", "combo tree",
    # 攻防状态
    "super armor", "poise", "hitstun", "stagger state",
    "parry", "riposte", "guard break", "perfect block",
    "invincibility frame", "dodge roll", "dodge cancel",
    # ⚠️ 不要加 "i-frame"：视频编码里的 I-frame（关键帧）会大量误命中，
    #    NVIDIA / 编解码类文章一抓一把。要表达无敌帧就写全 invincibility frame。
    # 目标选取与位移
    "lock-on", "target lock", "aim assist", "auto aim",
    "attack tracking", "motion warping", "root motion source",
    # ⚠️ 不要加 "soft lock"：在消费向游戏媒体里指卡关 bug，不是软锁定。
    # GAS / 技能实现（他们的战斗系统就建在这套东西上）
    "gameplay ability system", "gameplay ability", "gameplay tag",
    "gameplay effect", "gameplay cue",
    "anim notify", "animation notify", "anim montage", "animation montage",
    # ⚠️ 不要加 "ability system"：字面包含在 "capability system" 里，
    #    会命中一堆能力安全模型（capability-based security）的文章。
    # ⚠️ 不要加 "gas "：命中天然气、油气、gas fee。
    # 敌人与遭遇设计
    "boss design", "boss fight design", "encounter design",
    "enemy ai", "behavior tree", "difficulty tuning",
    # 品类（同品类的战斗拆解文章值得读）
    "soulslike", "fighting game", "melee combat", "character action",
    # 中文
    "战斗设计", "战斗系统", "战斗手感", "战斗节奏", "战斗数值",
    "打击感", "受击反馈", "受击", "硬直", "僵直", "霸体", "破防",
    "格挡", "弹反", "完美防御", "闪避", "无敌帧", "判定框",
    "连招", "取消窗口", "前后摇", "输入缓存", "顿帧", "命中停顿",
    "击退", "击飞", "浮空", "倒地", "起身", "招式",
    "技能系统", "技能编辑器", "锁定目标", "自动瞄准",
    "屏幕震动", "镜头震动", "帧数据", "格斗游戏", "怪物 ai", "行为树",
]

# ═══ 二级：其余相关词（引擎 / 动画 / 网络 / 性能）═══
OTHER_KEYWORDS = [
    # 引擎 / 渲染
    "unreal engine", "unreal", "ue5", "ue 5.", "epic games", "nanite", "lumen",
    "chaos physics", "niagara", "metahuman", "world partition",
    # 动画系统
    "animation blueprint", "motion matching", "distance matching", "root motion",
    "procedural animation", "ragdoll", "foot ik", "inverse kinematics",
    "animation compression", "pose search", "control rig", "retarget",
    # 网络同步
    "netcode", "rollback", "lag compensation", "client prediction",
    "replication", "dedicated server", "state synchronization",
    # 性能
    # ⚠️ 不要加 "lod" / "optimization" / "profiling" 这类裸词：
    #    "lod" 会命中 cloud/global/flood，"optimization" 命中了一篇
    #    铁路排班的图形学论文。宽词等于把栏目变成噪音。
    "unreal insights", "gpu profiling", "frame time", "draw call",
    "shader compil", "cpu bound", "gpu bound", "hitch",
    # 中文
    "虚幻", "虚幻引擎", "动画蓝图", "动作系统", "网络同步", "帧同步",
    "性能优化", "程序化动画", "骨骼动画", "蒙太奇", "武侠", "延迟补偿",
]

RELEVANT_KEYWORDS = COMBAT_KEYWORDS + OTHER_KEYWORDS
RELEVANT_BONUS = 20         # 二级词：足够让它冒头
COMBAT_BONUS = 32           # 一级词：等于必读阈值，战斗类条目必然排在栏目首位

# ── 流水线参数 ──────────────────────────────────────────────
# 时间窗。v1 完全没有这一步，所以源把老文章顶上来就照收。
#
# ⚠️ 为什么是 72 小时而不是 24/36：实测 2026-08-03（周一）发现，
#    Ars / Game Developer / NVIDIA / OpenAI / DeepMind 等源的最新条目
#    全都是 58~62 小时前 —— 因为周末（8/1–8/2）没人发稿。
#    36 小时窗口会让每个周一的日报直接空掉。
#    宽窗口是安全的：memory.json 的 14 天事件记忆负责真正的去重，
#    所以宽窗口只意味着「补上你还没看过的」，不会重复推送。
FRESH_WINDOW_HOURS = 72
MAX_PER_SOURCE = 12         # 召回宽度（v1 是 2，只能拿到 RSS 表头）
MAX_RECALL = 400            # 召回天花板

DEEP_READ_TOP = 5           # 「今日必读」深读条数
DEEP_READ_RELEVANT = 5      # 「能用上的」深读条数上限
# 必读阈值。实测校准：单源 tier2 = 10 分，双源 tier2 = 32 分，
# 双源 tier1 = 42 分。设 32 意味着「至少两家独立源报道过」才可能进必读。
DEEP_READ_MIN_SCORE = 32    # 低于此分不进必读区 —— 宁可当天只有 2 条

MAX_PAPERS = 3              # 深水区：论文
MAX_GRAPHICS = 3            # 深水区：图形学/动画论文（arXiv cs.GR）
MAX_REPOS = 3               # 深水区：开源
MAX_DIVERSE = 1             # 跨界视野

MEMORY_DAYS = 14            # 跨天去重窗口
REPEAT_PENALTY = 30         # 14 天内报过同一事件的扣分

# ── 源健康度 ──
# 只按「连续多少天零产出」告警，不按当天零产出。
# 当天 0 条完全可能是正常的：DeepMind、Unreal Engine 官博本来就不天天发，
# 72 小时窗口里空手而归是常态。当天就报警等于每天都在喊狼来了，
# 喊几次之后这一行字就被忽略了 —— 那时候真的挂了也看不见。
HEALTH_ALERT_DAYS = 7

# ── 标题级过滤（宽召回后的第一道粗筛）──
IGNORE_KEYWORDS = [
    "deal of the day", "daily deals", "best deals", "weekend sale",
    "discount", "coupon", "black friday", "prime day",
    "review roundup", "is now available for preorder",
]
