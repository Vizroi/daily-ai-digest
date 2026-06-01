# DeepSeek API 配置
# 使用环境变量 DEEPSEEK_API_KEY 传入 Key，GitHub Actions 中通过 Secrets 设置
DEEPSEEK_API_KEY = None  # 从环境变量读取
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# RSS 信息源列表
RSS_SOURCES = [
    # === 中文 AI 媒体 ===
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "lang": "zh"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "lang": "zh"},
    {"name": "极客公园", "url": "https://www.geekpark.net/feed", "lang": "zh"},

    # === 英文 AI 科技媒体 ===
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "lang": "en"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "lang": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "lang": "en"},
    {"name": "Ars Technica AI", "url": "https://feeds.arstechnica.com/arstechnica/ai", "lang": "en"},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "lang": "en"},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "lang": "en"},

    # === AI 研究 ===
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "lang": "en"},

    # === AI 公司博客 ===
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "lang": "en"},
    {"name": "Google AI Blog", "url": "https://blog.research.google/feeds/posts/default", "lang": "en"},
    {"name": "Meta AI Blog", "url": "https://ai.meta.com/blog/feed/", "lang": "en"},
    {"name": "Anthropic Blog", "url": "https://www.anthropic.com/feed", "lang": "en"},
    {"name": "DeepMind Blog", "url": "https://deepmind.google/blog/feed/", "lang": "en"},

    # === AI 社区 ===
    {"name": "Hacker News AI", "url": "https://hnrss.org/frontpage?q=ai+OR+ml+OR+llm+OR+gpt+OR+model", "lang": "en"},
    {"name": "Reddit ML", "url": "https://www.reddit.com/r/MachineLearning/.rss", "lang": "en"},
    {"name": "Reddit AI", "url": "https://www.reddit.com/r/artificial/.rss", "lang": "en"},

    # === 中文游戏媒体 ===
    {"name": "游民星空", "url": "https://www.gamersky.com/feed/", "lang": "zh"},
    {"name": "游戏陀螺", "url": "https://www.youxituoluo.com/feed", "lang": "zh"},

    # === 英文游戏媒体 ===
    {"name": "GamesIndustry", "url": "https://www.gamesindustry.biz/feed", "lang": "en"},
    {"name": "Game Developer", "url": "https://www.gamedeveloper.com/rss.xml", "lang": "en"},
    {"name": "Kotaku", "url": "https://kotaku.com/rss", "lang": "en"},
    {"name": "Polygon", "url": "https://www.polygon.com/rss/index.xml", "lang": "en"},
    {"name": "Eurogamer", "url": "https://www.eurogamer.net/feed", "lang": "en"},
    {"name": "IGN", "url": "https://corp.ign.com/feed", "lang": "en"},
    {"name": "PC Gamer", "url": "https://www.pcgamer.com/rss/", "lang": "en"},

    # === Reddit 游戏热帖 ===
    {"name": "Reddit Gaming", "url": "https://www.reddit.com/r/gaming/.rss", "lang": "en"},
    {"name": "Reddit Games", "url": "https://www.reddit.com/r/Games/.rss", "lang": "en"},
    {"name": "Reddit gamedev", "url": "https://www.reddit.com/r/gamedev/.rss", "lang": "en"},
    {"name": "Reddit pcgaming", "url": "https://www.reddit.com/r/pcgaming/.rss", "lang": "en"},
    {"name": "GDC News", "url": "https://gdconf.com/rss.xml", "lang": "en"},
    {"name": "GDC Vault", "url": "https://www.gdcvault.com/rss.xml", "lang": "en"},

    # === 游戏开发 ===
    {"name": "80.lv", "url": "https://80.lv/feed/", "lang": "en"},
    {"name": "Unreal Engine Blog", "url": "https://www.unrealengine.com/en-US/blog/feed.xml", "lang": "en"},
    {"name": "Unity Blog", "url": "https://blog.unity.com/feed", "lang": "en"},
    {"name": "IndieDB News", "url": "https://rss.indiedb.com/news/feed.xml", "lang": "en"},
]

# HuggingFace 每日论文 API（按社区投票排序）—— 论文速递专栏
HFPAPERS_API = "https://huggingface.co/api/daily_papers"

# 跨界视野 — 随机池，每天抽 5 个源各取 1 篇，打破信息茧房
DIVERSE_SOURCES = [
    {"name": "Nature Briefing", "url": "https://www.nature.com/nature.rss", "lang": "en"},
    {"name": "Science Daily", "url": "https://www.sciencedaily.com/rss/top.xml", "lang": "en"},
    {"name": "NASA News", "url": "https://www.nasa.gov/feed/", "lang": "en"},
    {"name": "Space.com", "url": "https://www.space.com/feeds/all", "lang": "en"},
    {"name": "The Economist", "url": "https://www.economist.com/feed/latest", "lang": "en"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "lang": "en"},
    {"name": "Dezeen", "url": "https://www.dezeen.com/feed/", "lang": "en"},
    {"name": "Pitchfork", "url": "https://pitchfork.com/feed/", "lang": "en"},
    {"name": "EdSurge", "url": "https://www.edsurge.com/feed", "lang": "en"},
    {"name": "STAT News", "url": "https://www.statnews.com/feed/", "lang": "en"},
    {"name": "Grist", "url": "https://grist.org/feed/", "lang": "en"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "lang": "en"},
    {"name": "Smithsonian", "url": "https://www.smithsonianmag.com/rss/latest_articles/", "lang": "en"},
    {"name": "Aeon", "url": "https://aeon.co/feed.rss", "lang": "en"},
    {"name": "Quanta Magazine", "url": "https://www.quantamagazine.org/feed/", "lang": "en"},
]

# 非 RSS 的自定义数据源
CUSTOM_SOURCES = [
    {"type": "github_trending", "name": "GitHub Trending"},
]

# 文章过滤：忽略标题中包含以下关键词的文章
IGNORE_KEYWORDS = [
    "deal of the day", "daily deals", "best buy",
    "review roundup", "weekend sale", "discount",
]

# 每个 RSS 源最多取几篇
MAX_PER_SOURCE = 2

# 论文速递篇数
MAX_PAPERS = 3

# 跨界视野篇数
MAX_DIVERSE = 5

# 单次处理文章数上限
MAX_ARTICLES = 100
