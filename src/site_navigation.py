"""Shared page navigation, separate from each page's contents links."""
from html import escape


SITE_NAV_CSS = r'''
.site-header{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:18px 0 0;border-bottom:1px solid #d1d0c1;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.site-home{flex-shrink:0;padding-bottom:17px;font-size:16px;font-weight:700;letter-spacing:.03em;color:#292d27;text-decoration:none!important}
.site-nav{display:flex;align-items:stretch;gap:24px;margin:0;padding:0;white-space:nowrap;flex-wrap:wrap}
.site-nav a{display:block;padding:9px 2px 15px;border-bottom:3px solid transparent;color:#5e635a;font-size:14px;font-weight:500;line-height:1.5;text-decoration:none!important}
.site-nav a:hover{color:#292d27;border-bottom-color:#b4bcae}.site-nav a[aria-current]{color:#3f5847;border-bottom-color:#4c6152;font-weight:700}
.site-header a:focus-visible{outline:3px solid #9b493b;outline-offset:4px}
@media(max-width:760px){.site-header{display:block;padding-top:15px}.site-home{display:inline-block;font-size:14px;padding-bottom:8px}.site-nav{gap:0 20px}.site-nav a{font-size:13px;padding:7px 1px 11px}}
@media(max-width:400px){.site-nav{gap:0 14px}.site-nav a{font-size:12px}}
@media print{.site-header{display:none!important}}
'''


def render_site_navigation(current, prefix="", *, archive_page=False):
    links = []
    for key, filename, label in (
        ("daily", "index.html", "日报"),
        ("market", "market.html", "Steam 市场"),
        ("indie", "indie.html", "小游戏榜"),
        ("ai", "ai.html", "AI"),
        ("sources", "sources.html", "信息来源"),
    ):
        marker = (' aria-current="true"' if archive_page else ' aria-current="page"') if key == current else ''
        links.append(f'<a href="{escape(prefix + filename, quote=True)}"{marker}>{label}</a>')
    home = escape(prefix + "index.html", quote=True)
    return (f'<div class="site-header"><a class="site-home" href="{home}">策划日报</a>'
            '<nav class="site-nav" aria-label="站点导航">' + ''.join(links) + '</nav></div>')
