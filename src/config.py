"""游戏日报配置：游戏动态为主，策划精选与少量 AI 为辅。

category 是内容入口而非质量证明；tier 区分一手实践、编辑分析和社区。
慢更新设计站使用 30 天窗口，旧文精选由显式阅读库负责，不伪装成新闻。
"""

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
TIER_WEIGHT = {1: 18, 2: 8, 3: 2}
COVERAGE_WEIGHT = 12

NEWS_MAX = 16
FEATURES_MAX = 3
AI_MAX = 2
FRESH_WINDOW_HOURS = 72
DESIGN_WINDOW_HOURS = 30 * 24
MAX_PER_SOURCE = 20
MAX_RECALL = 1200
# 多个平台扩大候选；最终版面仍保持原有栏目配额。
PLATFORM_CAPS = {"steam": 4, "reddit": 2, "discord": 1, "开发者社区": 2}

# 新增中文源、作者站使用站内声明的 feed；媒体内容仍需筛选宣发和转载。
RSS_SOURCES = [
    {"name": "Game Developer", "url": "https://www.gamedeveloper.com/rss.xml", "tier": 2, "lang": "en", "category": "games"},
    {"name": "GamesIndustry", "url": "https://www.gamesindustry.biz/feed", "tier": 2, "lang": "en", "category": "games"},
    {"name": "80.lv", "url": "https://80.lv/feed", "tier": 2, "lang": "en", "category": "development"},
    {"name": "Unreal Engine", "url": "https://www.unrealengine.com/rss/news?lang=en-US", "tier": 1, "lang": "en", "category": "development"},
    {"name": "Unity", "url": "https://unity.com/blog/rss", "tier": 1, "lang": "en", "category": "development"},
    {"name": "GameRes", "url": "https://www.gameres.com/rss.xml", "tier": 2, "lang": "zh", "category": "games"},
    {"name": "机核", "url": "https://www.gcores.com/rss", "tier": 2, "lang": "zh", "category": "games"},
    {"name": "触乐", "url": "https://www.chuapp.com/feed", "tier": 2, "lang": "zh", "category": "games"},
    {"name": "Dan Felder", "url": "https://danfelder.net/feed/", "tier": 1, "lang": "en", "category": "design", "window_hours": DESIGN_WINDOW_HOURS},
    {"name": "GDKeys", "url": "https://gdkeys.com/feed/", "tier": 1, "lang": "en", "category": "design", "window_hours": DESIGN_WINDOW_HOURS},
    {"name": "OpenAI", "url": "https://openai.com/news/rss.xml", "tier": 1, "lang": "en", "category": "ai"},
    {"name": "DeepMind", "url": "https://deepmind.google/blog/rss.xml", "tier": 1, "lang": "en", "category": "ai"},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml", "tier": 1, "lang": "en", "category": "ai"},
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "tier": 2, "lang": "en", "category": "ai"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "tier": 2, "lang": "zh", "category": "ai"},
]

# indienova 未发现站内声明的 feed：读公开列表与详情页，不猜测 RSS 路径。
# GameRes 策划页补足总体 RSS 漏掉的慢更新分析；URL 去重优先 design 分类。
PAGE_SOURCES = [
    {"name": "GameRes 策划", "url": "https://www.gameres.com/list/25", "tier": 2, "lang": "zh", "category": "design", "window_hours": DESIGN_WINDOW_HOURS, "adapter": "gameres", "link_pattern": r"^/\d+\.html$", "max_per_source": 8},
    {"name": "indienova 开发", "url": "https://indienova.com/indie-game-development/", "tier": 2, "lang": "zh", "category": "design", "window_hours": DESIGN_WINDOW_HOURS, "adapter": "indienova", "link_pattern": r"^/indie-game-development/[^/]+/?$", "max_per_source": 8},
    {"name": "indienova 新游", "url": "https://indienova.com/indie-game-news/", "tier": 2, "lang": "zh", "category": "games", "adapter": "indienova", "link_pattern": r"^/indie-game-(?:news|review)/[^/]+/?$", "max_per_source": 8},
]

OPTIONAL_SOURCES = {
    "游戏葡萄": {"url": "https://youxiputao.com/", "category": "games", "lang": "zh", "tier": 2,
                 "reason": "当前首页为公众号等渠道入口，未核验可持续采集的文章列表或 RSS"},
}

DESIGN_KEYWORDS = [
    "game design", "systems design", "system design", "level design", "quest design",
    "narrative design", "world design", "economy design", "progression", "onboarding",
    "tutorial design", "player motivation", "player psychology", "player experience",
    "game balance", "difficulty design", "difficulty tuning", "core loop", "game loop",
    "game mechanic", "mechanics", "procedural generation", "emergent gameplay",
    "accessibility", "monetization", "retention", "playtest", "game feel",
    "游戏设计", "玩法设计", "系统设计", "关卡设计", "任务设计", "叙事设计", "世界观",
    "数值设计", "经济系统", "成长系统", "核心循环", "游戏机制", "构筑", "build",
    "新手引导", "玩家动机", "玩家心理", "玩家体验", "难度设计", "平衡性",
    "涌现", "可访问性", "无障碍", "商业化", "留存", "试玩测试", "策划",
]
ANALYSIS_KEYWORDS = [
    "postmortem", "post-mortem", "retrospective", "case study", "design breakdown",
    "design analysis", "lessons learned", "interview", "how we", "behind the design",
    "制作人", "开发者访谈", "专访", "复盘", "拆解", "分析", "设计笔记", "开发日志",
    "设计思路", "设计取舍", "经验分享", "机制", "评测", "简评",
]

# 兼容旧模块；战斗只是设计主题之一，不再独占个人相关性。
COMBAT_KEYWORDS = [
    "combat design", "combat system", "combat feel", "hitstop", "hit reaction",
    "hitbox", "hurtbox", "frame data", "input buffer", "boss design", "encounter design",
    "gameplay ability system", "melee combat", "战斗设计", "战斗系统", "打击感", "受击反馈",
    "连招", "取消窗口", "敌人设计", "格斗游戏",
]
OTHER_KEYWORDS = [
    "unreal engine", "ue5", "unity", "godot", "animation", "netcode", "rollback",
    "game performance", "游戏开发", "虚幻引擎", "动画系统", "网络同步", "性能优化",
]
RELEVANT_KEYWORDS = DESIGN_KEYWORDS + ANALYSIS_KEYWORDS + COMBAT_KEYWORDS + OTHER_KEYWORDS
RELEVANT_BONUS = 12
COMBAT_BONUS = 12

# 默认关闭广泛热榜；常量/函数仅为兼容和未来显式研究保留。
ENABLE_HN = False
ENABLE_HF_PAPERS = False
ENABLE_GITHUB_TRENDING = False
DIVERSE_SOURCES = []
HN_API = "https://hn.algolia.com/api/v1/search_by_date"
HN_MIN_POINTS = 60
HN_KEYWORDS = []
HFPAPERS_API = "https://huggingface.co/api/daily_papers"
GITHUB_TRENDING_URLS = []
HN_FACTOR = 2.0
HN_FRONTPAGE = 300
HN_FRONTPAGE_BONUS = 8
HF_FACTOR = 4.0
STAR_FACTOR = 2.0

DEEP_READ_TOP = FEATURES_MAX
DEEP_READ_RELEVANT = 0
DEEP_READ_MIN_SCORE = 20
MAX_PAPERS = 0
MAX_GRAPHICS = 0
MAX_REPOS = 0
MAX_DIVERSE = 0
MEMORY_DAYS = 30
REPEAT_PENALTY = 30
HEALTH_ALERT_DAYS = 7

POLITE_UA_DOMAINS = ("reddit.com",)
POLITE_UA = "DailyGameDigest/3.0 (+https://github.com/Vizroi/daily-ai-digest)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
IGNORE_KEYWORDS = [
    "deal of the day", "daily deals", "best deals", "weekend sale", "coupon",
    "black friday", "prime day", "会员抽奖", "免费领取", "喜加一", "喜加二",
]
DEAD_IN_V1 = {}
NO_RSS_AVAILABLE = {"indienova": "未发现站内声明的 RSS，使用公开文章列表适配器"}
REMOVED_SOURCES = {
    "broad Hacker News": "默认关闭泛讨论和热度噪声；Reddit 由定向社区适配器处理",
    "HuggingFace Papers / GitHub Trending / arXiv": "不以论文和仓库热榜占据游戏日报主体",
    "跨界视野": "默认关闭，阅读重点回到游戏与设计",
}
