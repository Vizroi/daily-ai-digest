# DeepSeek API 配置
# 使用环境变量 DEEPSEEK_API_KEY 传入 Key，GitHub Actions 中通过 Secrets 设置
DEEPSEEK_API_KEY = None  # 从环境变量读取
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# RSS 信息源列表
RSS_SOURCES = [
    # === AI 科技媒体 ===
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "lang": "en"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "lang": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "lang": "en"},
    {"name": "Ars Technica AI", "url": "https://feeds.arstechnica.com/arstechnica/ai", "lang": "en"},
    {"name": "MIT Tech Review AI", "url": "https://www.technologyreview.com/feed/", "lang": "en"},

    # === AI 研究 ===
    {"name": "HuggingFace Daily", "url": "https://huggingface.co/papers/feed.xml", "lang": "en"},
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "lang": "en"},

    # === AI 公司 ===
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "lang": "en"},
    {"name": "Google AI Blog", "url": "https://blog.research.google/feeds/posts/default", "lang": "en"},
    {"name": "Meta AI Blog", "url": "https://ai.meta.com/blog/feed/", "lang": "en"},
    {"name": "Anthropic Blog", "url": "https://www.anthropic.com/feed", "lang": "en"},

    # === AI 社区 ===
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage?q=ai+OR+ml+OR+llm+OR+gpt+OR+model", "lang": "en"},

    # === 游戏行业 ===
    {"name": "GamesIndustry.biz", "url": "https://www.gamesindustry.biz/feed", "lang": "en"},
    {"name": "Game Developer", "url": "https://www.gamedeveloper.com/rss.xml", "lang": "en"},
    {"name": "IGN", "url": "https://feeds.feedburner.com/ign/all", "lang": "en"},
]

# 文章过滤：忽略标题中包含以下关键词的文章
IGNORE_KEYWORDS = [
    "deal of the day", "daily deals", "best buy",
    "review roundup", "weekend sale", "discount",
]

# 单次处理文章数上限（按时间排序后取最新的 N 篇）
MAX_ARTICLES = 60
