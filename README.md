# 策划日报 · Game Design Daily

面向游戏策划的中英文游戏日报，附策划精选与少量 AI 精华。每天快速了解游戏动态，再选择值得深入阅读的设计文章。

## 内容与版面

- **今日游戏日报**：近 72 小时尚未报道的游戏、新版本、产品观察、开发与行业动态，最多 16 条。日期缺失、未来日期不进入日报。
- **策划精选**：最多 3 篇机制、战斗、系统、关卡、玩家体验与开发复盘。允许较早文章，保留原始日期；深读需要实际取得正文。
- **AI 精华**：最多 2 条，且不超过每 6 条游戏内容配 1 条 AI。没有合适内容可以为空。
- 中文摘要与英文原标题并列，保留来源、发布日期、类型、原文入口。新闻可按主题、语言筛选和搜索。
- 选源并不等于证明每篇文章优质；先按来源、类型与时间筛选，再依据正文判断相关性和信息量。
- 同一事件的中英文报道尝试合并。语义去重失败时降级为 URL/同语言标题去重，并在运行日志记录限制。

## Steam 市场观察

同一站点新增 `market.html`，日报首页展示最多三条市场观察入口。市场页支持全局样本与动作方向、1/7/30 天窗口、搜索和分类筛选，展开游戏可以查看公开评价与官方事件。文章和游戏均提供原始来源链接，收藏由读者使用自己的浏览器管理。

- **边界**：这是明确列出覆盖范围的观察样本，并非 Steam 全市场统计。动作之外也覆盖其他游戏类型；热门发现入口与编辑选取的长期样本共同构成观察池。
- **时间**：统一使用北京时间。每日计划采样四次（01:15、07:15、13:15、19:15），08:30 日报生成时也尝试更新；GitHub Actions 排队可能延迟。
- **指标**：当前在线是采样时刻的在线人数。历史窗口比较最近完整 1/7/30 天与此前等长窗口的采样在线均值，显示基数、绝对变化与百分比。它不等于销量、日活或留存。
- **历史不足**：首日即可浏览真实快照、评价和官方事件；未达到采样覆盖要求的窗口显示待积累，失败数据不补零。首次没有历史时，30 天与此前 30 天的比较需要至少 60 个完整日。
- **分析**：官方事件与数值变化分别展示，时间相近不等于因果。玩家声音是有限评论样本，不代表全体玩家；设计观察问题是阅读提示，不冒充实际试玩结论。
- **保存**：`data/market.json` 保存可展示的最新状态；`data/market_history.json` 保存真实采样。首次创建日报归档时保留当次市场摘要，既有归档不回填未来数据。

只更新市场（不调用模型，不重新生成日报内容、RSS 或记忆）：

```sh
python src/steam_market.py
python src/market_render.py
python src/render.py --no-archive
```

来源和采集限制见市场页的“数据与方法”。接口出现问题时保留已有数据并展示状态与观测时间。

## 正式版与本地预览

正式刊期保存在 data/digest.json，生成 docs/index.html、docs/feed.xml 与按日归档。首期使用已经人工查阅和审核的内容；后续刊期由每日管线生成。是否已上线以 GitHub Actions 的部署结果和线上页面为准。

data/preview_digest.json 保留审核时的试刊样本，与正式成稿、发布记忆和历史归档分开。预览页面显示“试刊”。

无模型密钥也可生成这份预览：

    python src/build_preview.py docs/preview-site
    python -m http.server 8765 --bind 127.0.0.1 --directory docs/preview-site

打开 http://127.0.0.1:8765/，即可查看完整试刊、来源目录和试刊 RSS。这个构建只使用已审核的试刊内容，不需要模型密钥，也不改正式刊期或发布记忆。

只更新仓库里的单页预览时：

    python src/render.py data/preview_digest.json docs/preview.html
    python src/feed.py data/preview_digest.json docs/preview-feed.xml

试刊不会写入正式按日归档或发布记忆。

## 来源

主要入口包括 GameRes、机核、触乐、indienova、Game Developer、GamesIndustry、80.lv、Dan Felder、Unreal Engine 与 Unity。
少量 AI 来源为官方博客与实践型作者。源配置详见 src/config.py。

多平台来源现在单独登记，采集上限扩大到每源通常20条、合并后最多1200条；日报仍最多16条、精选3篇、AI至多2条。新增目录：

- data/public_sources.json：10款不同类型游戏的 Steam 官方公告、Factorio Friday Facts、Riot 开发文章、itch.io 项目日志。
- data/creator_sources.json：YouTube / B站创作者、中文作者文章、公众号及知乎线索。
- data/community_sources.json：r/gamedesign、r/gamedev、r/leveldesign；Unity、Godot、Unreal Source 的 Discord 入口。
- docs/sources.html：来源目录、本轮采集数量、空窗、访问失败、待授权和手动收录状态。空窗不等于连接失败；登记也不等于已经采到内容。

Steam 单期至多4条、Reddit至多2条，同一来源通常至多3条；热度不作为可信度。扩充候选不扩大日报版面。来源配额不会强迫填满栏目。

视频标题/简介保留为待看线索，无字幕时不生成视频分析；缺日期不冒充今天。社区完整的公开文章或自述还需通过正文相关性检查；提问、只有外链、上下文不全的聊天保留在 ranked.json 的 review_queue，不进入成稿。跨语言去重以120条一批执行，跨批次仍可能有同事件重报，URL/完全相同标题会先全局去重。

**可选社区连接**：Reddit使用经平台批准的OAuth access token（REDDIT_ACCESS_TOKEN，可选REDDIT_USER_AGENT）。目前不自动刷新短期token。Discord使用获准Bot的DISCORD_BOT_TOKEN与明确的DISCORD_CHANNELS_JSON，例如 {"discord_unity":["频道ID"]}；只读指定服务器频道，不加入服务器、不发送消息。凭据通过环境变量或GitHub Actions Secrets配置，不写入仓库或聊天。

Discord消息默认restricted：只计数，不写入抓取JSON、不发给模型、不公开发布。阅读权限与发布授权分别设置；只有频道配置同时声明publication_scope为public且public_publication_authorized为true，才进入公开线索审阅队列。频道列表为空或凭据缺失就跳过。B站等遇平台限制只报告状态，不绕过验证。

**手动补充线索**：复制 data/source_inbox.example.json 为 data/source_inbox.json（已忽略提交），填写公开链接对象列表，可含url、title、source、source_id、platform、published、lang。文件仅收集线索，标题或日期不会被当作已核验正文；review_queue中再核验。私密消息不要放进公共来源列表。

RSS 和公开文章列表分开处理；不会猜测不存在的 feed。设计源可使用 30 天窗口，新闻默认 72 小时。
data/reading_library.json 保存从收藏与研究中挑选的常青备选：GDKeys、Game Design Skills、The Level Design Book 等。
经典文章只有在近期精选不足、取得正文且未近期报道时才可能入选。演讲如果只有简介、没有字幕，不能冒充完整精读。

## 管线

    python -m venv .venv
    pip install -r requirements.txt

设置 DEEPSEEK_API_KEY 后依次运行：

    python src/fetch_sources.py
    python src/cluster.py
    python src/rank.py
    python src/readfull.py
    python src/summarize.py
    python src/render.py
    python src/source_directory.py data/source_report.json docs/sources.html
    python src/feed.py
    python src/commit_memory.py

模型用于跨语言去重、标题翻译、摘要与正文相关性检查。排序和栏目配额由代码控制。
没有密钥时，可以显式运行 summarize.py --offline 验证管线；只保留来源摘要，不生成翻译/深读，不写正式发布记忆。

## GitHub Pages 发布

现有地址保持不变：[策划日报](https://vizroi.github.io/daily-ai-digest/)。工作流有以下入口：

- **推送到 main**：运行测试，然后直接上传并部署仓库中的 docs。首次推送不会重新抓取或调用模型，因此保留已审核的首期内容。
- **每日定时或手动 daily**：只在 main 运行抓取、筛选、摘要、市场采集、渲染、RSS 和记忆更新，提交生成结果后，直接上传并部署同一份 docs。每日计划为北京时间 08:30；GitHub 排队可能导致延迟。
- **市场定时或手动 market**：只采集市场、保存历史并更新市场页与首页市场摘要，不改日报文章、RSS、发布记忆或历史刊期。
- **手动 publish**：发布仓库已生成的 docs，不重新采集。手动运行请选 main，并按用途选择 mode。

各入口共用同一并发组，避免同时发布。写入任务从最新 main 检出，推送前 rebase；冲突会阻止发布，不强制覆盖。生成任务取得 contents:write；独立部署任务只取得 pages:write 和 id-token:write。工作流直接部署 Pages 产物，不依赖机器人提交再次触发构建。

仓库需要启用 GitHub Pages。建议在 Settings → Pages → Build and deployment 中将 Source 设为 GitHub Actions；若保留分支发布，来源分支必须为 main，目录为 /docs，且 github-pages 环境规则允许 main 部署。详情见 [GitHub 官方部署说明](https://github.com/actions/deploy-pages#security-considerations)。仓库 Actions Secrets 需配置 DEEPSEEK_API_KEY；Reddit 和 Discord 凭据仍为可选。

工作流文件通过本地检查不代表部署已经完成。发布后应查看 Actions 的 deploy 结果，再核对线上首页、来源目录和 RSS；新内容管线也需要一次实际运行验证。

## 证据边界

- 原始发布日期和 updated 分开；抓取时间不是发布日期。
- RSS 摘要、RSS 内容字段、网页正文分别保存，不按摘要长度冒充全文。
- 取得正文失败的近期精选退回日报简述；旧文不会被补成当天新闻。
- 只依据实际材料归纳。作者观点与编辑阅读角度明确区分；缺失事实不补写。
- 转载数量不自动证明独立验证；页面不展示伪精确的质量分数。
- 30 天发布记忆记录事件 key 与原文链接；同一天重跑不重复计数。
- 没有合适内容就展示真实空状态，不用热门仓库、泛 AI 论文或求助帖填满版面。

## 验证

    python -m unittest discover -s tests -v

测试覆盖时间窗口、来源解析、分类隔离、AI 配额、去重、发布记忆、摘要降级，以及 HTML/RSS 输出。
更换源或权重后，还应抓取一轮真实数据检查；固定样例不能证明所有站点一直可用。
