#!/usr/bin/env python3
"""
统一内容提取脚本 - 从 YouTube、B站、网页等来源提取文本内容。

用法:
    python extract_content.py <URL> [--lang zh-Hans,en] [--segment-minutes 5]

输出:
    JSON 格式到 stdout，包含 source、title、segments[]、metadata
"""

import argparse
import json
import re
import sys
import subprocess
import tempfile
import os
from pathlib import Path

# Windows 环境下确保 UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


# ---------------------------------------------------------------------------
# URL 类型检测
# ---------------------------------------------------------------------------

def detect_source(url: str) -> str:
    """根据 URL 判断内容来源类型。"""
    # PDF：URL 以 .pdf 结尾、已知 PDF 服务域名、或本地文件路径以 .pdf 结尾
    if (re.search(r'\.pdf(\?.*)?$', url, re.I)
            or re.search(r'arxiv\.org/pdf/', url, re.I)
            or _is_local_pdf(url)):
        return 'pdf'
    if re.search(r'(youtube\.com|youtu\.be)', url, re.I):
        return 'youtube'
    if re.search(r'(bilibili\.com|b23\.tv)', url, re.I):
        return 'bilibili'
    if re.search(r'(x\.com|twitter\.com)/\w+/status/\d+', url, re.I):
        return 'twitter'
    if re.search(r'mp\.weixin\.qq\.com/', url, re.I):
        return 'wechat'
    if re.search(r'(xiaohongshu\.com|xhslink\.com)', url, re.I):
        return 'xiaohongshu'
    return 'webpage'


def _is_local_pdf(path: str) -> bool:
    """判断是否为本地 PDF 文件路径。"""
    if not path.lower().endswith('.pdf'):
        return False
    # 绝对路径（Windows: C:\..., D:\...  Unix: /...）或 ~ 开头
    return bool(re.match(r'^([A-Za-z]:[/\\]|/|~)', path))


def extract_youtube_video_id(url: str) -> str | None:
    """从 YouTube URL 中提取 video ID。"""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# YouTube 提取 (youtube-transcript-api)
# ---------------------------------------------------------------------------

COOKIE_FILE = Path(__file__).resolve().parent / 'youtube_cookies.txt'


def extract_youtube(url: str, languages: list[str]) -> dict:
    """提取 YouTube 转录文本。依次尝试: 直连 API → yt-dlp 带 cookie → 引导设置。"""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return _error(f"无法从 URL 中提取 YouTube video ID: {url}")

    # 方案 1: youtube-transcript-api 直连（无 cookie，部分网络环境可行）
    transcript = _try_transcript_api(video_id, languages)

    # 方案 2: youtube-transcript-api + cookie（应对 IP 封锁）
    if transcript is None and COOKIE_FILE.exists():
        transcript = _try_transcript_api_with_cookies(video_id, languages)

    # 方案 3: yt-dlp + cookie（回退方案）
    if transcript is None:
        transcript = _try_ytdlp_subtitles(url, languages)

    if transcript is None:
        # 区分原因：有没有 cookie 文件
        if not COOKIE_FILE.exists():
            return _error(
                "YouTube 要求身份验证才能获取字幕（当前 IP 被识别为自动请求）。\n\n"
                "需要一次性设置（约 2 分钟）：\n"
                "1. 在 Chrome 中安装扩展「Get cookies.txt LOCALLY」\n"
                "   https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                "2. 打开 YouTube 并确保已登录\n"
                "3. 点击扩展图标 → 「Export」→ 保存文件\n"
                "4. 将文件移动到：\n"
                f"   {COOKIE_FILE}\n\n"
                "设置完成后重新运行即可。Cookie 文件只需导出一次，长期有效。"
            )
        else:
            return _error(
                "即使使用了 cookie 文件，仍无法获取 YouTube 字幕。\n"
                "可能原因: cookie 已过期、视频无字幕、或地区限制。\n"
                "建议: 1) 重新导出 cookie 文件；2) 手动从视频页面复制字幕文本粘贴给我。"
            )

    # 获取视频标题和元信息
    title, duration = _get_youtube_info(url, video_id)

    # 计算总时长
    if transcript and not duration:
        last = transcript[-1]
        duration = last['start'] + last.get('duration', 0)

    return {
        'source': 'youtube',
        'url': url,
        'title': title,
        'total_duration_seconds': round(duration),
        'transcript_entries': transcript,
        'full_text': ' '.join(entry['text'] for entry in transcript),
        'error': None,
    }


def _try_transcript_api(video_id: str, languages: list[str]) -> list | None:
    """尝试用 youtube-transcript-api 直连获取转录（无 cookie）。"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None

    try:
        api = YouTubeTranscriptApi()
        result = api.fetch(video_id, languages=languages)
        return [
            {'text': snippet.text, 'start': snippet.start, 'duration': snippet.duration}
            for snippet in result
        ]
    except Exception:
        return None


def _try_transcript_api_with_cookies(video_id: str, languages: list[str]) -> list | None:
    """用 youtube-transcript-api + cookie 文件获取转录。"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        import requests
    except ImportError:
        return None

    try:
        # 从 Netscape cookie 文件加载 cookie 到 requests session
        session = requests.Session()
        cookie_jar = _load_netscape_cookies(COOKIE_FILE)
        session.cookies = cookie_jar

        api = YouTubeTranscriptApi(http_client=session)
        result = api.fetch(video_id, languages=languages)
        return [
            {'text': snippet.text, 'start': snippet.start, 'duration': snippet.duration}
            for snippet in result
        ]
    except Exception:
        return None


def _load_netscape_cookies(cookie_path: Path):
    """解析 Netscape 格式的 cookie 文件，返回 requests 兼容的 CookieJar。"""
    import http.cookiejar
    jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return jar


def _try_ytdlp_subtitles(url: str, languages: list[str]) -> list | None:
    """尝试用 yt-dlp 下载字幕（自动使用 cookie 文件如果存在）。"""
    try:
        import yt_dlp
    except ImportError:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, '%(id)s')
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': languages,
            'subtitlesformat': 'vtt/srt/best',
            'outtmpl': output_template,
            # 避免因视频格式问题导致字幕下载中断
            'format': 'best',
            'ignore_no_formats_error': True,
        }

        # 如果有 cookie 文件，使用它
        if COOKIE_FILE.exists():
            ydl_opts['cookiefile'] = str(COOKIE_FILE)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            return None

        # 查找字幕文件并解析
        for f in Path(tmpdir).iterdir():
            if f.suffix in ('.vtt', '.srt'):
                text = _parse_subtitle_file(f)
                if text:
                    return [{'text': text, 'start': 0, 'duration': 0}]

    return None


def _get_youtube_info(url: str, video_id: str) -> tuple[str, float]:
    """获取 YouTube 视频标题和时长。返回 (title, duration_seconds)。"""
    try:
        import yt_dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'ignore_no_formats_error': True,
        }
        if COOKIE_FILE.exists():
            ydl_opts['cookiefile'] = str(COOKIE_FILE)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('title', f'YouTube Video {video_id}'), info.get('duration', 0)
    except Exception:
        pass

    return f'YouTube Video {video_id}', 0


# ---------------------------------------------------------------------------
# B站提取 (bilibili-api + yt-dlp)
# ---------------------------------------------------------------------------

BILIBILI_COOKIE_FILE = Path(__file__).resolve().parent / 'bilibili_cookies.txt'


def _extract_bvid(url: str) -> str | None:
    """从 B站 URL 提取 BV 号。"""
    match = re.search(r'(BV[a-zA-Z0-9]+)', url)
    return match.group(1) if match else None


def extract_bilibili(url: str, languages: list[str]) -> dict:
    """提取 B站视频字幕。优先用 bilibili-api（支持 AI 字幕），回退到 yt-dlp。"""
    bvid = _extract_bvid(url)

    # 方案 1: bilibili-api + cookie（可获取 AI 字幕）
    result = _try_bilibili_api(bvid, url)
    if result:
        return result

    # 方案 2: yt-dlp（获取 CC 字幕）
    result = _try_bilibili_ytdlp(url, languages)
    if result:
        return result

    # 两种方案都失败
    if not BILIBILI_COOKIE_FILE.exists():
        return _error(
            "无法获取 B 站视频字幕。B 站的 AI 字幕需要登录态才能访问。\n\n"
            "需要一次性设置：\n"
            "1. 在 Chrome 中打开 bilibili.com 并确保已登录\n"
            "2. 用「Get cookies.txt LOCALLY」扩展导出 cookie\n"
            "3. 将文件保存到：\n"
            f"   {BILIBILI_COOKIE_FILE}\n\n"
            "设置完成后重新运行即可。"
        )
    else:
        return _error(
            "该 B 站视频无可提取的字幕。\n"
            "可能原因: 视频无 AI 字幕、cookie 已过期、或视频不存在。\n"
            "建议: 手动粘贴视频内容，或提供其他来源。"
        )


def _try_bilibili_api(bvid: str | None, url: str) -> dict | None:
    """用 bilibili-api 获取 AI 字幕（需要 cookie）。"""
    if not bvid or not BILIBILI_COOKIE_FILE.exists():
        return None

    try:
        import asyncio
        from bilibili_api import video, Credential
        import http.cookiejar
        import httpx
    except ImportError:
        return None

    # 从 cookie 文件读取凭证
    try:
        jar = http.cookiejar.MozillaCookieJar(str(BILIBILI_COOKIE_FILE))
        jar.load(ignore_discard=True, ignore_expires=True)
        sessdata = bili_jct = buvid3 = ''
        for c in jar:
            if c.name == 'SESSDATA': sessdata = c.value
            if c.name == 'bili_jct': bili_jct = c.value
            if c.name == 'buvid3': buvid3 = c.value
        if not sessdata:
            return None
    except Exception:
        return None

    async def _fetch():
        credential = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)
        v = video.Video(bvid=bvid, credential=credential)
        info = await v.get_info()
        title = info.get('title', 'B站视频')
        duration = info.get('duration', 0)

        # 通过 player API 获取字幕（包含 AI 字幕的完整 URL）
        pages = info.get('pages', [])
        cid = pages[0]['cid'] if pages else info.get('cid')
        player_info = await v.get_player_info(cid=cid)
        subtitles = player_info.get('subtitle', {}).get('subtitles', [])

        if not subtitles:
            return None

        # 下载第一个字幕
        sub_url = subtitles[0].get('subtitle_url', '')
        if not sub_url:
            return None
        if sub_url.startswith('//'):
            sub_url = 'https:' + sub_url

        async with httpx.AsyncClient() as client:
            resp = await client.get(sub_url)
            data = resp.json()
            body = data.get('body', [])

        if not body:
            return None

        # 构建带时间戳的转录条目
        transcript = [
            {
                'text': item.get('content', ''),
                'start': item.get('from', 0),
                'duration': item.get('to', 0) - item.get('from', 0),
            }
            for item in body
        ]
        full_text = ' '.join(item.get('content', '') for item in body)

        return {
            'source': 'bilibili',
            'url': url,
            'title': title,
            'total_duration_seconds': duration or 0,
            'transcript_entries': transcript,
            'full_text': full_text,
            'error': None,
        }

    try:
        return asyncio.run(_fetch())
    except Exception:
        return None


def _try_bilibili_ytdlp(url: str, languages: list[str]) -> dict | None:
    """用 yt-dlp 获取 B 站 CC 字幕（回退方案）。"""
    try:
        import yt_dlp
    except ImportError:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': languages + ['zh-CN', 'zh', 'ai-zh'],
            'subtitlesformat': 'vtt/srt/best',
            'outtmpl': os.path.join(tmpdir, '%(id)s'),
        }
        if BILIBILI_COOKIE_FILE.exists():
            ydl_opts['cookiefile'] = str(BILIBILI_COOKIE_FILE)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'B站视频')
                duration = info.get('duration', 0)
                ydl.download([url])
        except Exception:
            return None

        for f in Path(tmpdir).iterdir():
            if f.suffix in ('.vtt', '.srt'):
                text = _parse_subtitle_file(f)
                if text:
                    return {
                        'source': 'bilibili',
                        'url': url,
                        'title': title,
                        'total_duration_seconds': duration or 0,
                        'transcript_entries': [],
                        'full_text': text,
                        'error': None,
                    }

    return None


def _parse_subtitle_file(filepath: Path) -> str:
    """解析 VTT/SRT 字幕文件，提取纯文本。"""
    content = filepath.read_text(encoding='utf-8', errors='replace')
    lines = content.splitlines()
    text_lines = []

    for line in lines:
        line = line.strip()
        # 跳过 VTT 头部、时间码行、序号行、空行
        if not line:
            continue
        if line.startswith('WEBVTT'):
            continue
        if line.startswith('NOTE'):
            continue
        if '-->' in line:
            continue
        if re.match(r'^\d+$', line):
            continue
        # 移除 VTT 标签
        line = re.sub(r'<[^>]+>', '', line)
        if line and line not in text_lines[-1:]:  # 去重连续重复行
            text_lines.append(line)

    return ' '.join(text_lines)


# ---------------------------------------------------------------------------
# PDF 提取 (pymupdf4llm — 轻量、无 GPU、原生数字 PDF 最快)
# ---------------------------------------------------------------------------


def _generate_pdf_material_id(url_or_path: str) -> str:
    """为 PDF 材料生成 material-id：pdf-<SHA256[:8]>。"""
    import hashlib
    return 'pdf-' + hashlib.sha256(url_or_path.encode()).hexdigest()[:8]


def extract_pdf(url_or_path: str) -> dict:
    """提取 PDF 内容为结构化 Markdown。支持 URL（自动下载）和本地文件路径。"""
    try:
        import pymupdf4llm
        import pymupdf
    except ImportError:
        return _error("缺少依赖: pymupdf4llm\n安装: pip install pymupdf4llm")

    local_path = None
    is_temp = False

    try:
        # 判断是 URL 还是本地路径
        if re.match(r'^https?://', url_or_path, re.I):
            # URL：下载到临时文件
            local_path, download_err = _download_pdf(url_or_path)
            if download_err:
                return _error(download_err)
            is_temp = True
        else:
            # 本地文件路径
            expanded = os.path.expanduser(url_or_path)
            if not os.path.isfile(expanded):
                return _error(f"PDF 文件不存在: {expanded}")
            local_path = expanded

        # 提取元数据
        doc = pymupdf.open(local_path)
        meta = doc.metadata or {}
        title = meta.get('title', '') or Path(local_path).stem
        author = meta.get('author', '')
        creation_date = meta.get('creationDate', '')
        page_count = len(doc)
        doc.close()

        # 用 pymupdf4llm 提取为 Markdown（保留标题层级、表格、图片占位）
        md_text = pymupdf4llm.to_markdown(
            local_path,
            show_progress=False,
            page_chunks=False,
        )

        if not md_text or len(md_text.strip()) < 50:
            return _error(
                "PDF 内容提取为空或过少——可能是扫描件（纯图片 PDF）。\n"
                "pymupdf4llm 仅处理含文本层的数字 PDF。\n"
                "扫描件请考虑安装 docling（pip install docling）后手动处理。"
            )

        # 估算字数
        word_count = len(md_text.split())

        return {
            'source': 'pdf',
            'url': url_or_path,
            'title': title.strip(),
            'author': author.strip(),
            'date': creation_date,
            'total_duration_seconds': 0,
            'page_count': page_count,
            'word_count': word_count,
            'transcript_entries': [],
            'full_text': md_text,
            'error': None,
        }

    except Exception as e:
        return _error(f"PDF 提取失败: {e}")
    finally:
        # 清理临时下载文件
        if is_temp and local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass


def _download_pdf(url: str) -> tuple[str | None, str | None]:
    """下载 PDF URL 到临时文件。返回 (local_path, error_message)。"""
    try:
        import httpx
    except ImportError:
        return None, "缺少依赖: httpx\n安装: pip install httpx"

    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            resp = client.get(url)
            resp.raise_for_status()

            # 验证内容类型（宽松匹配：有些服务器返回 application/octet-stream）
            content_type = resp.headers.get('content-type', '')
            if 'html' in content_type.lower() and 'pdf' not in url.lower():
                return None, (
                    f"URL 返回的不是 PDF（Content-Type: {content_type}）。\n"
                    "请确认 URL 直接指向 PDF 文件。"
                )

            # 写入临时文件
            tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name, None

    except httpx.HTTPStatusError as e:
        return None, f"PDF 下载失败（HTTP {e.response.status_code}）: {url}"
    except httpx.TimeoutException:
        return None, f"PDF 下载超时（60 秒）: {url}"
    except Exception as e:
        return None, f"PDF 下载失败: {e}"


# ---------------------------------------------------------------------------
# 网页提取 (trafilatura + Playwright 回退)
# ---------------------------------------------------------------------------

# 需要登录态 cookie 的网站（域名 → cookie 文件路径）
WEBPAGE_COOKIE_FILES = {
    'zhihu.com': Path(__file__).resolve().parent / 'zhihu_cookies.txt',
}


def _get_cookie_file_for_url(url: str) -> Path | None:
    """根据 URL 域名查找对应的 cookie 文件路径。"""
    for domain, path in WEBPAGE_COOKIE_FILES.items():
        if domain in url:
            return path
    return None

def extract_webpage(url: str) -> dict:
    """使用 trafilatura 提取网页正文。对 JS 重型网站自动回退到 Playwright 渲染。"""
    try:
        import trafilatura
    except ImportError:
        return _error("缺少依赖: trafilatura\n安装: py -3 -m pip install trafilatura")

    try:
        # 第 1 层：trafilatura 直接 HTTP 抓取（快，适用于大多数静态网页）
        downloaded = trafilatura.fetch_url(url)
        text = None
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                output_format='markdown',
                include_comments=False,
                include_tables=True,
                include_links=True,
            )

        # 如果直接抓取成功且内容充实，直接返回
        if text and len(text.strip()) > 100:
            title, author, date = _extract_webpage_metadata(downloaded)
            return {
                'source': 'webpage',
                'url': url,
                'title': title,
                'author': author,
                'date': date,
                'total_duration_seconds': 0,
                'transcript_entries': [],
                'full_text': text,
                'error': None,
            }

        # 第 2 层：Playwright 浏览器渲染（慢，但能处理 JS 重型站点如知乎、微博等）
        print(f'[Playwright] 直接抓取未获取到有效内容，尝试浏览器渲染...', file=sys.stderr)
        rendered_html = _fetch_with_playwright(url)
        if rendered_html:
            text = trafilatura.extract(
                rendered_html,
                output_format='markdown',
                include_comments=False,
                include_tables=True,
                include_links=True,
            )
            if text and len(text.strip()) > 100:
                title, author, date = _extract_webpage_metadata(rendered_html)
                return {
                    'source': 'webpage',
                    'url': url,
                    'title': title,
                    'author': author,
                    'date': date,
                    'total_duration_seconds': 0,
                    'transcript_entries': [],
                    'full_text': text,
                    'error': None,
                }

        # 如果 Playwright 也失败，判断是否需要 cookie
        cookie_file = _get_cookie_file_for_url(url)
        if cookie_file is not None and not cookie_file.exists():
            # 从 URL 提取域名用于提示
            domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
            domain = domain_match.group(1) if domain_match else url
            return _error(
                f"该网页需要登录才能访问内容。\n\n"
                f"需要一次性设置（约 1 分钟）：\n"
                f"1. 在 Chrome 中安装扩展「Get cookies.txt LOCALLY」\n"
                f"   https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                f"2. 打开 {domain} 并确保已登录\n"
                f"3. 点击扩展图标 → 「Export」→ 保存文件\n"
                f"4. 将文件移动到：\n"
                f"   {cookie_file}\n\n"
                f"设置完成后重新运行即可。Cookie 文件只需导出一次，长期有效。"
            )

        return _error(f"无法提取网页内容（已尝试直接抓取和浏览器渲染）: {url}")

    except Exception as e:
        return _error(f"网页提取失败: {e}")


def _fetch_with_playwright(url: str) -> str | None:
    """使用 Playwright 无头浏览器渲染页面，返回完整 HTML。

    用于处理 JavaScript 重型网站（如知乎、微博等 SPA 应用），
    作为 trafilatura 直接 HTTP 抓取的回退方案。
    支持 stealth 模式绕过基础反爬，支持从 cookie 文件注入登录态。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[Playwright] 未安装，跳过浏览器渲染回退', file=sys.stderr)
        return None

    # 尝试加载 stealth 插件
    stealth = None
    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
    except ImportError:
        pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/131.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1920, 'height': 1080},
            )

            # 注入 cookie（如果有对应站点的 cookie 文件）
            cookie_file = _get_cookie_file_for_url(url)
            if cookie_file and cookie_file.exists():
                cookies = _load_cookies_for_playwright(cookie_file, url)
                if cookies:
                    context.add_cookies(cookies)
                    print(f'[Playwright] 已加载 {len(cookies)} 条 cookie', file=sys.stderr)

            page = context.new_page()

            # 应用 stealth（绕过 navigator.webdriver 等检测）
            if stealth:
                stealth.apply_stealth_sync(page)

            page.goto(url, wait_until='networkidle', timeout=30000)
            # 额外等待，确保 JS 挑战完成 + 动态内容渲染
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f'[Playwright] 浏览器渲染失败: {e}', file=sys.stderr)
        return None


def _load_cookies_for_playwright(cookie_path: Path, url: str) -> list[dict]:
    """从 Netscape 格式 cookie 文件加载 cookie，转换为 Playwright 格式。"""
    import http.cookiejar
    try:
        jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        cookies = []
        for c in jar:
            cookie = {
                'name': c.name,
                'value': c.value,
                'domain': c.domain,
                'path': c.path,
            }
            if c.secure:
                cookie['secure'] = True
            if c.expires:
                cookie['expires'] = c.expires
            cookies.append(cookie)
        return cookies
    except Exception as e:
        print(f'[Playwright] 加载 cookie 文件失败: {e}', file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# X/Twitter 提取 (bird-search GraphQL)
# ---------------------------------------------------------------------------

# bird-search CLI 搜索路径（来自 last30days skill 的不同安装位置）
BIRD_SEARCH_PATHS = [
    Path.home() / '.agents' / 'skills' / 'last30days' / 'scripts' / 'lib' / 'vendor' / 'bird-search' / 'bird-search.mjs',
    Path.home() / '.claude' / 'skills' / 'last30days' / 'scripts' / 'lib' / 'vendor' / 'bird-search' / 'bird-search.mjs',
]

# X/Twitter 凭证来源（复用 last30days 的配置）
X_CONFIG_FILE = Path.home() / '.config' / 'last30days' / '.env'


def _find_bird_search() -> Path | None:
    """查找 bird-search.mjs 的安装路径。"""
    for p in BIRD_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _load_x_credentials() -> tuple[str, str] | None:
    """从 last30days 配置中加载 X/Twitter 凭证 (AUTH_TOKEN, CT0)。"""
    if not X_CONFIG_FILE.exists():
        return None

    auth_token = ct0 = ''
    for line in X_CONFIG_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line.startswith('AUTH_TOKEN='):
            auth_token = line.split('=', 1)[1]
        elif line.startswith('CT0='):
            ct0 = line.split('=', 1)[1]

    if auth_token and ct0:
        return auth_token, ct0
    return None


def _extract_tweet_info(url: str) -> tuple[str, str] | None:
    """从 X/Twitter URL 提取 (handle, tweet_id)。"""
    match = re.search(r'(?:x\.com|twitter\.com)/(\w+)/status/(\d+)', url)
    if match:
        return match.group(1), match.group(2)
    return None


def _tweet_id_to_date(tweet_id: str) -> str:
    """从 Twitter Snowflake ID 推算推文日期 (YYYY-MM-DD)。

    Snowflake: timestamp_ms = (id >> 22) + 1288834974657
    """
    from datetime import datetime, timezone
    ts_ms = (int(tweet_id) >> 22) + 1288834974657
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime('%Y-%m-%d')


def _search_bird(bird_search: Path, query: str, count: int,
                 auth_token: str, ct0: str) -> list[dict]:
    """调用 bird-search.mjs 执行搜索，返回推文列表。"""
    env = {
        **os.environ,
        'AUTH_TOKEN': auth_token,
        'CT0': ct0,
        'BIRD_DISABLE_BROWSER_COOKIES': '1',
    }

    result = subprocess.run(
        ['node', str(bird_search), query, '--count', str(count), '--json'],
        capture_output=True,
        text=True,
        timeout=45,
        env=env,
        encoding='utf-8',
    )

    data = json.loads(result.stdout)

    # bird-search 错误时返回 {"error": "...", "items": []}
    if isinstance(data, dict):
        error = data.get('error')
        if error:
            raise RuntimeError(error)
        return data.get('items', [])

    # 正常时返回推文数组
    return data


def _assemble_tweet_document(target: dict, thread: list[dict],
                             handle: str) -> str:
    """将推文、引用推文、线程组装为结构化 Markdown 文档。"""
    parts = []

    # — 主推文 —
    author_name = target.get('author', {}).get('name', handle)
    parts.append(f'## @{handle} ({author_name})\n')
    parts.append(target['text'])

    engagement = (
        f"❤️ {target.get('likeCount', 0):,} | "
        f"🔁 {target.get('retweetCount', 0):,} | "
        f"💬 {target.get('replyCount', 0):,}"
    )
    parts.append(f'\n*{engagement}*')

    # — 引用推文 —
    quoted = target.get('quotedTweet')
    if quoted:
        q_handle = quoted.get('author', {}).get('username', 'unknown')
        q_name = quoted.get('author', {}).get('name', q_handle)
        parts.append(f'\n---\n\n## 引用: @{q_handle} ({q_name})\n')
        parts.append(quoted['text'])

        article = quoted.get('article')
        if article:
            parts.append(f"\n### 附文: {article.get('title', '')}\n")
            if article.get('previewText'):
                parts.append(article['previewText'])

        q_engagement = (
            f"❤️ {quoted.get('likeCount', 0):,} | "
            f"🔁 {quoted.get('retweetCount', 0):,} | "
            f"💬 {quoted.get('replyCount', 0):,}"
        )
        parts.append(f'\n*{q_engagement}*')

    # — 线程续文 —
    if thread:
        parts.append(f'\n---\n\n## 线程续文 ({len(thread)} 条)\n')
        for t in thread:
            parts.append(f'**@{handle}:**')
            parts.append(t['text'] + '\n')

    return '\n\n'.join(parts)


def extract_twitter(url: str) -> dict:
    """提取 X/Twitter 推文内容（含引用推文和线程）。

    通过 bird-search.mjs (last30days skill) 调用 Twitter GraphQL API。
    凭证复用 ~/.config/last30days/.env 的 AUTH_TOKEN 和 CT0。
    """
    tweet_info = _extract_tweet_info(url)
    if not tweet_info:
        return _error(f'无法从 URL 中解析推文信息: {url}')

    handle, tweet_id = tweet_info

    bird_search = _find_bird_search()
    if not bird_search:
        return _error(
            '需要 bird-search 工具来提取 X/Twitter 内容。\n'
            '请确保已安装 last30days skill（~/.agents/skills/last30days/）。'
        )

    credentials = _load_x_credentials()
    if not credentials:
        return _error(
            '需要 X/Twitter 登录凭证才能获取推文内容。\n\n'
            '设置方法：\n'
            '1. 运行 /last30days 的 auto setup\n'
            '2. 或手动在 ~/.config/last30days/.env 中配置 AUTH_TOKEN 和 CT0\n'
            '   （从浏览器 x.com 的 Cookie 中获取）'
        )

    auth_token, ct0 = credentials

    # 搜索该用户的推文（用 Snowflake ID 推算日期以缩小范围）
    from datetime import datetime, timedelta
    tweet_date = _tweet_id_to_date(tweet_id)
    dt = datetime.strptime(tweet_date, '%Y-%m-%d')
    since_date = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
    until_date = (dt + timedelta(days=2)).strftime('%Y-%m-%d')

    try:
        # 第一轮：用日期范围精确搜索
        query = f'from:{handle} since:{since_date} until:{until_date}'
        tweets = _search_bird(bird_search, query, 30, auth_token, ct0)

        target = None
        for t in tweets:
            if t.get('id') == tweet_id:
                target = t
                break

        # 第二轮回退：不限日期，加大搜索量
        if not target:
            tweets = _search_bird(bird_search, f'from:{handle}', 50,
                                  auth_token, ct0)
            for t in tweets:
                if t.get('id') == tweet_id:
                    target = t
                    break

    except subprocess.TimeoutExpired:
        return _error('X 搜索超时（45 秒），请稍后重试。')
    except RuntimeError as e:
        return _error(f'X 搜索失败: {e}')
    except (json.JSONDecodeError, Exception) as e:
        return _error(f'X 搜索结果解析失败: {e}')

    if not target:
        return _error(
            f'在 @{handle} 的推文中未找到目标 (ID: {tweet_id})。\n'
            '可能原因: 推文已删除、账号已锁定、或搜索 API 未覆盖。'
        )

    # 收集同一线程中该作者的其他推文
    conv_id = target.get('conversationId')
    thread_tweets = []
    if conv_id:
        thread_tweets = sorted(
            [t for t in tweets
             if t.get('conversationId') == conv_id
             and t['id'] != tweet_id
             and t.get('author', {}).get('username') == handle],
            key=lambda t: int(t['id']),
        )

    # 组装文档
    full_text = _assemble_tweet_document(target, thread_tweets, handle)
    title_preview = target['text'][:60].replace('\n', ' ')
    title = f'@{handle}: {title_preview}...'

    return {
        'source': 'twitter',
        'url': url,
        'title': title,
        'author': f'@{handle}',
        'date': target.get('createdAt', ''),
        'total_duration_seconds': 0,
        'transcript_entries': [],
        'full_text': full_text,
        'error': None,
    }


# ---------------------------------------------------------------------------
# 微信公众号提取 (Camoufox 反检测浏览器 + trafilatura)
# ---------------------------------------------------------------------------

WECHAT_COOKIE_FILE = Path(__file__).resolve().parent / 'wechat_cookies.txt'


def _generate_wechat_material_id(url: str) -> str:
    """为微信公众号材料生成 material-id：wechat-<SHA256[:8]>。"""
    import hashlib
    return 'wechat-' + hashlib.sha256(url.encode()).hexdigest()[:8]


def extract_wechat(url: str) -> dict:
    """提取微信公众号文章内容。使用 Camoufox 反检测浏览器绕过微信反爬机制。

    策略:
      1. trafilatura 直接 HTTP 抓取（快，成功率低）
      2. Camoufox 隐身浏览器渲染 → trafilatura 提取正文
    """
    try:
        import trafilatura
    except ImportError:
        return _error("缺少依赖: trafilatura\n安装: pip install trafilatura")

    # --- 第 1 层：trafilatura 直接抓取（大多数情况会失败，但值得一试）---
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                output_format='markdown',
                include_comments=False,
                include_tables=True,
                include_links=True,
            )
            if text and len(text.strip()) > 200:
                title, author, date = _extract_wechat_metadata(downloaded)
                return {
                    'source': 'wechat',
                    'url': url,
                    'title': title,
                    'author': author,
                    'date': date,
                    'total_duration_seconds': 0,
                    'transcript_entries': [],
                    'full_text': text,
                    'error': None,
                }
    except Exception:
        pass

    # --- 第 2 层：Camoufox 反检测浏览器渲染 ---
    print('[Camoufox] 直接抓取未获取有效内容，启动反检测浏览器...', file=sys.stderr)
    browser_result = _fetch_wechat_with_browser(url)

    if browser_result:
        title, author, date, text = browser_result
        if text and len(text.strip()) > 200:
            return {
                'source': 'wechat',
                'url': url,
                'title': title,
                'author': author,
                'date': date,
                'total_duration_seconds': 0,
                'transcript_entries': [],
                'full_text': text,
                'error': None,
            }

    return _error(
        "无法提取微信公众号文章内容。\n\n"
        "可能原因:\n"
        "  - 文章链接已失效或被删除\n"
        "  - 微信反爬机制拦截（触发验证码）\n"
        "  - 网络环境异常\n\n"
        "替代方案:\n"
        "  1. 在微信/浏览器中打开文章 → 全选复制 → 直接粘贴给我\n"
        "  2. 使用浏览器的「阅读模式」后复制纯文本"
    )


def _fetch_wechat_with_browser(url: str) -> tuple[str, str, str, str] | None:
    """使用浏览器渲染微信公众号页面，直接从 DOM 提取结构化内容。

    返回 (title, author, date, markdown_text) 或 None。
    优先 Camoufox（反检测更强），回退 Playwright。
    """
    # 选择浏览器引擎
    page = None
    browser = None
    engine_name = None

    # 尝试 Camoufox
    try:
        from camoufox.sync_api import Camoufox
        ctx_manager = Camoufox(headless=True)
        browser = ctx_manager.__enter__()
        engine_name = 'Camoufox'
    except (ImportError, Exception) as e:
        print(f'[Camoufox] 不可用 ({e})，回退到 Playwright...', file=sys.stderr)
        browser = None

    # 回退 Playwright
    pw_instance = None
    if browser is None:
        try:
            from playwright.sync_api import sync_playwright
            pw_instance = sync_playwright().start()
            browser = pw_instance.chromium.launch(headless=True)
            engine_name = 'Playwright'
        except (ImportError, Exception) as e:
            print(f'[Playwright] 也不可用 ({e})，放弃浏览器渲染', file=sys.stderr)
            return None

    try:
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
        )

        # 注入 cookie（如果有）
        if WECHAT_COOKIE_FILE.exists():
            cookies = _load_cookies_for_camoufox(WECHAT_COOKIE_FILE)
            if cookies:
                context.add_cookies(cookies)
                print(f'[{engine_name}] 已加载 {len(cookies)} 条微信 cookie', file=sys.stderr)

        page = context.new_page()

        # Playwright 模式下应用 stealth
        if engine_name == 'Playwright':
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(page)
            except ImportError:
                pass

        page.goto(url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(4000)

        # --- 直接从 DOM 提取结构化内容 ---
        # 微信文章的固定 DOM 结构：
        #   标题: h1.rich_media_title 或 #activity-name
        #   作者/公众号: #js_name
        #   日期: #publish_time
        #   正文: #js_content

        title = _safe_text(page, 'h1.rich_media_title, #activity-name') or '未知标题'
        author = _safe_text(page, '#js_name') or ''
        date = _safe_text(page, '#publish_time') or ''

        # 提取正文 HTML，转 Markdown
        content_el = page.query_selector('#js_content')
        if not content_el:
            print(f'[{engine_name}] 未找到 #js_content，文章可能未加载或链接无效', file=sys.stderr)
            # 回退：用 trafilatura 从整页 HTML 提取
            full_html = page.content()
            return _fallback_trafilatura_extract(full_html, title, author, date)

        content_html = content_el.inner_html()
        text = _wechat_html_to_markdown(content_html)

        if not text or len(text.strip()) < 100:
            print(f'[{engine_name}] #js_content 内容过短，尝试 trafilatura 回退', file=sys.stderr)
            full_html = page.content()
            return _fallback_trafilatura_extract(full_html, title, author, date)

        print(f'[{engine_name}] 提取成功: {title[:40]}... ({len(text)} 字)', file=sys.stderr)
        return title, author, date, text

    except Exception as e:
        print(f'[{engine_name}] 渲染失败: {e}', file=sys.stderr)
        return None
    finally:
        try:
            browser.close()
        except Exception:
            pass
        if pw_instance:
            try:
                pw_instance.stop()
            except Exception:
                pass


def _safe_text(page, selector: str) -> str:
    """安全地从页面元素获取文本，失败返回空字符串。"""
    try:
        el = page.query_selector(selector)
        if el:
            return el.inner_text().strip()
    except Exception:
        pass
    return ''


def _wechat_html_to_markdown(html: str) -> str:
    """将微信文章正文 HTML 转换为 Markdown。

    优先用 trafilatura（保留结构），回退到纯文本提取。
    """
    # 方案 1: trafilatura（最佳 Markdown 质量）
    try:
        import trafilatura
        text = trafilatura.extract(
            f'<html><body>{html}</body></html>',
            output_format='markdown',
            include_comments=False,
            include_tables=True,
            include_links=True,
        )
        if text and len(text.strip()) > 100:
            return text
    except Exception:
        pass

    # 方案 2: 正则清洗 HTML 标签，保留基本结构
    import html as html_lib
    # 保留段落换行
    text = re.sub(r'<br\s*/?>', '\n', html)
    text = re.sub(r'</p>', '\n\n', text)
    text = re.sub(r'</div>', '\n', text)
    text = re.sub(r'<h([1-6])[^>]*>(.*?)</h\1>', lambda m: '#' * int(m.group(1)) + ' ' + m.group(2) + '\n\n', text)
    # 粗体/斜体
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text)
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text)
    # 移除剩余标签
    text = re.sub(r'<[^>]+>', '', text)
    text = html_lib.unescape(text)
    # 整理空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _fallback_trafilatura_extract(full_html: str, title: str, author: str, date: str) -> tuple[str, str, str, str] | None:
    """当 DOM 直接提取失败时，用 trafilatura 从完整页面 HTML 提取。"""
    try:
        import trafilatura
        text = trafilatura.extract(
            full_html,
            output_format='markdown',
            include_comments=False,
            include_tables=True,
            include_links=True,
        )
        if text and len(text.strip()) > 200:
            # 如果之前没拿到元数据，从 HTML 补提
            if title == '未知标题':
                t, a, d = _extract_wechat_metadata(full_html)
                title = t
                author = author or a
                date = date or d
            return title, author, date, text
    except Exception:
        pass
    return None


def _load_cookies_for_camoufox(cookie_path: Path) -> list[dict]:
    """从 Netscape 格式 cookie 文件加载 cookie，转换为 Camoufox/Playwright 格式。"""
    import http.cookiejar
    try:
        jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        cookies = []
        for c in jar:
            cookie = {
                'name': c.name,
                'value': c.value,
                'domain': c.domain,
                'path': c.path,
            }
            if c.secure:
                cookie['secure'] = True
            if c.expires:
                cookie['expires'] = c.expires
            cookies.append(cookie)
        return cookies
    except Exception as e:
        print(f'[Camoufox] 加载 cookie 文件失败: {e}', file=sys.stderr)
        return []


def _extract_wechat_metadata(html: str) -> tuple[str, str, str]:
    """从微信公众号文章 HTML 中提取标题、作者（公众号名）、发布日期。"""
    title = '未知标题'
    author = ''
    date = ''

    # 标题: og:title → rich_media_title → <title>
    m = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)', html)
    if m:
        title = m.group(1).strip()
    else:
        m = re.search(r'class=["\']rich_media_title["\'][^>]*>([^<]+)', html)
        if m:
            title = m.group(1).strip()

    # 公众号名称: js_name → og:article:author
    m = re.search(r'id=["\']js_name["\'][^>]*>([^<]+)', html)
    if m:
        author = m.group(1).strip()
    else:
        m = re.search(r'<meta\s+property=["\']og:article:author["\']\s+content=["\']([^"\']+)', html)
        if m:
            author = m.group(1).strip()

    # 发布日期: publish_time
    m = re.search(r'id=["\']publish_time["\'][^>]*>([^<]+)', html)
    if m:
        date = m.group(1).strip()

    # 回退到 trafilatura 元数据提取
    if title == '未知标题':
        try:
            t, a, d = _extract_webpage_metadata(html)
            title = t if t != '未知标题' else title
            author = author or a
            date = date or d
        except Exception:
            pass

    return title, author, date


# ---------------------------------------------------------------------------
# 小红书提取 (Playwright/Camoufox + dots.ocr)
# ---------------------------------------------------------------------------

XHS_COOKIE_FILE = Path(__file__).resolve().parent / 'xiaohongshu_cookies.txt'

# OCR 子系统路径
OCR_VENV_DIR = Path(__file__).resolve().parent / '.venv-ocr'
OCR_SCRIPT = Path(__file__).resolve().parent / 'ocr_image.py'


def _resolve_xhs_short_url(url: str) -> str:
    """解析小红书短链接（xhslink.com）到完整 URL。"""
    if 'xhslink.com' not in url:
        return url
    try:
        import httpx
        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(url)
            if resp.status_code in (301, 302):
                return resp.headers.get('location', url)
    except Exception:
        pass
    return url


def _extract_xhs_note_id(url: str) -> str | None:
    """从小红书 URL 中提取 note_id（24 位十六进制）。"""
    match = re.search(r'(?:discovery/item|explore)/([a-f0-9]{24})', url, re.I)
    return match.group(1) if match else None


def extract_xiaohongshu(url: str) -> dict:
    """提取小红书笔记内容（文字 + 图片 OCR + 评论）。

    策略:
      1. 解析短链接 → 完整 URL
      2. Playwright/Camoufox + cookie 渲染页面
      3. DOM 提取笔记文字、图片 URL、评论
      4. 对图片做 OCR（dots.ocr），提取图中文字
      5. 合并去重：笔记文字 + OCR 文字 + 筛选后评论
    """
    # 解析短链接
    resolved_url = _resolve_xhs_short_url(url)
    note_id = _extract_xhs_note_id(resolved_url)

    if not note_id:
        return _error(
            f"无法从 URL 中提取小红书笔记 ID: {url}\n"
            "支持的格式:\n"
            "  - https://www.xiaohongshu.com/explore/<note_id>\n"
            "  - https://www.xiaohongshu.com/discovery/item/<note_id>\n"
            "  - http://xhslink.com/<短码>"
        )

    # 浏览器渲染 + DOM 提取
    browser_result = _fetch_xhs_with_browser(resolved_url)
    if not browser_result:
        if not XHS_COOKIE_FILE.exists():
            return _error(
                "无法提取小红书笔记内容。小红书需要登录态才能查看完整内容。\n\n"
                "需要一次性设置（约 1 分钟）：\n"
                "1. 在 Chrome 中安装扩展「Get cookies.txt LOCALLY」\n"
                "   https://chromewebstore.google.com/detail/get-cookiestxt-locally/"
                "cclelndahbckbenkjhflpdbgdldlbecc\n"
                "2. 打开 xiaohongshu.com 并确保已登录\n"
                "3. 点击扩展图标 → 「Export」→ 保存文件\n"
                "4. 将文件移动到：\n"
                f"   {XHS_COOKIE_FILE}\n\n"
                "设置完成后重新运行即可。Cookie 文件只需导出一次，长期有效。"
            )
        return _error(
            "无法提取小红书笔记内容。\n"
            "可能原因: 笔记已删除、cookie 已过期、或被反爬拦截。\n"
            "建议: 1) 重新导出 cookie 文件；"
            "2) 在小红书 App 中打开笔记 → 复制文字 → 直接粘贴给我。"
        )

    title, author, note_text, image_urls, comments, tags, engagement = browser_result

    # OCR 图片中的文字
    ocr_texts = _ocr_xhs_images(image_urls) if image_urls else []

    # 合并去重：笔记文字 + OCR 文字 + 评论
    full_text = _merge_xhs_content(
        title, author, note_text, ocr_texts, comments, tags, engagement,
    )

    return {
        'source': 'xiaohongshu',
        'url': url,
        'title': title,
        'author': author,
        'date': '',
        'total_duration_seconds': 0,
        'image_count': len(image_urls),
        'comment_count': len(comments),
        'transcript_entries': [],
        'full_text': full_text,
        'error': None,
    }


def _fetch_xhs_with_browser(
    url: str,
) -> tuple[str, str, str, list[str], list[dict], list[str], dict] | None:
    """使用浏览器渲染小红书页面，从 DOM 提取笔记内容。

    返回 (title, author, note_text, image_urls, comments, tags, engagement) 或 None。
    """
    browser = None
    engine_name = None
    pw_instance = None
    ctx_manager = None

    # 尝试 Camoufox（反检测更强）
    try:
        from camoufox.sync_api import Camoufox
        ctx_manager = Camoufox(headless=True)
        browser = ctx_manager.__enter__()
        engine_name = 'Camoufox'
    except (ImportError, Exception) as e:
        print(f'[XHS] Camoufox 不可用 ({e})，回退到 Playwright...', file=sys.stderr)

    # 回退 Playwright
    if browser is None:
        try:
            from playwright.sync_api import sync_playwright
            pw_instance = sync_playwright().start()
            browser = pw_instance.chromium.launch(headless=True)
            engine_name = 'Playwright'
        except (ImportError, Exception) as e:
            print(f'[XHS] Playwright 也不可用 ({e})', file=sys.stderr)
            return None

    try:
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
        )

        # 注入 cookie
        if XHS_COOKIE_FILE.exists():
            cookies = _load_cookies_for_playwright(XHS_COOKIE_FILE, url)
            if cookies:
                context.add_cookies(cookies)
                print(f'[XHS][{engine_name}] 已加载 {len(cookies)} 条 cookie',
                      file=sys.stderr)

        page = context.new_page()

        # Playwright 模式下应用 stealth
        if engine_name == 'Playwright':
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(page)
            except ImportError:
                pass

        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        # 小红书 JS 渲染较重，等待主要内容加载
        page.wait_for_timeout(8000)

        # 等待核心元素出现
        try:
            page.wait_for_selector('#detail-title', timeout=5000)
        except Exception:
            print(f'[XHS][{engine_name}] #detail-title 未出现，'
                  '页面可能未加载或需要登录', file=sys.stderr)

        # --- DOM 提取 ---
        title = _safe_text(page, '#detail-title') or '未知标题'

        author = (_safe_text(page, '.author-wrapper .username')
                  or _safe_text(page, '.author-wrapper .name')
                  or '')

        # 正文：提取 #detail-desc .note-text 的纯文本（排除标签链接）
        note_text = _extract_xhs_note_text(page)

        # 标签
        tags = _extract_xhs_tags(page)

        # 图片 URL
        image_urls = _extract_xhs_images(page)

        # 互动数据
        engagement = _extract_xhs_engagement(page)

        # 评论（需要先滚动到评论区）
        comments = _extract_xhs_comments(page)

        if not title or title == '未知标题':
            # 最后回退：用 trafilatura 从完整页面提取
            print(f'[XHS][{engine_name}] DOM 提取失败，尝试 trafilatura 回退',
                  file=sys.stderr)
            try:
                import trafilatura
                html = page.content()
                text = trafilatura.extract(
                    html, output_format='markdown',
                    include_comments=False, include_tables=True,
                )
                if text and len(text.strip()) > 100:
                    return ('小红书笔记', '', text, [], [], [], {})
            except Exception:
                pass
            return None

        print(f'[XHS][{engine_name}] 提取成功: {title[:40]}... '
              f'({len(image_urls)} 图, {len(comments)} 评论)',
              file=sys.stderr)
        return title, author, note_text, image_urls, comments, tags, engagement

    except Exception as e:
        print(f'[XHS][{engine_name}] 渲染失败: {e}', file=sys.stderr)
        return None
    finally:
        try:
            browser.close()
        except Exception:
            pass
        if ctx_manager and engine_name == 'Camoufox':
            try:
                ctx_manager.__exit__(None, None, None)
            except Exception:
                pass
        if pw_instance:
            try:
                pw_instance.stop()
            except Exception:
                pass


def _extract_xhs_note_text(page) -> str:
    """从小红书笔记页面提取正文纯文本（排除标签链接）。"""
    try:
        content_el = page.query_selector('#detail-desc .note-text')
        if not content_el:
            content_el = page.query_selector('#detail-desc')
        if not content_el:
            return ''
        # 用 JS 提取纯文本，排除 <a> 标签（标签链接）
        text = page.evaluate('''(el) => {
            let text = '';
            el.childNodes.forEach(node => {
                if (node.nodeType === Node.TEXT_NODE) {
                    text += node.textContent;
                } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName !== 'A') {
                    text += node.textContent;
                }
            });
            return text.trim();
        }''', content_el)
        return text or ''
    except Exception:
        return _safe_text(page, '#detail-desc') or ''


def _extract_xhs_tags(page) -> list[str]:
    """从小红书笔记页面提取标签列表。"""
    try:
        elements = page.query_selector_all('#detail-desc .tag')
        return [el.inner_text().strip() for el in elements if el.inner_text().strip()]
    except Exception:
        return []


def _extract_xhs_images(page) -> list[str]:
    """从小红书笔记页面提取所有图片 URL。"""
    urls = []
    try:
        # 按优先级尝试多组选择器，直到找到有效 URL
        selector_groups = [
            '.swiper-slide img',
            '.note-slider-img',
            '[class*="slider"] img',
            '[class*="slide"] img',
        ]
        for selector in selector_groups:
            elements = page.query_selector_all(selector)
            for el in elements:
                src = el.get_attribute('src') or el.get_attribute('data-src') or ''
                if src and src.startswith('http') and 'avatar' not in src.lower():
                    # 去掉 CDN 尺寸/签名参数，获取原图
                    clean = re.sub(r'\?imageView2/\d/.*$', '', src)
                    clean = re.sub(r'\?x-oss-process=.*$', '', clean)
                    if clean not in urls:
                        urls.append(clean)
            if urls:
                break  # 找到有效 URL 后停止尝试其他选择器
    except Exception as e:
        print(f'[XHS] 图片提取失败: {e}', file=sys.stderr)
    return urls


def _extract_xhs_engagement(page) -> dict:
    """从小红书笔记页面提取互动数据（赞/藏/评论数）。"""
    result = {'likes': 0, 'collects': 0, 'comments': 0}
    try:
        counts = page.query_selector_all('.engage-bar-style .count')
        if len(counts) >= 3:
            for i, key in enumerate(['likes', 'collects', 'comments']):
                text = counts[i].inner_text().strip()
                # "赞"/"收藏"/"评论" 表示数量为 0
                if text.isdigit():
                    result[key] = int(text)
                else:
                    # 处理 "1.2万" 等中文数字格式
                    m = re.match(r'([\d.]+)\s*万', text)
                    if m:
                        result[key] = int(float(m.group(1)) * 10000)
    except Exception:
        pass
    return result


def _extract_xhs_comments(page) -> list[dict]:
    """从小红书笔记页面提取评论。

    先滚动到评论区触发加载，然后提取带点赞数的评论列表。
    """
    comments = []
    try:
        # 滚动到评论区触发加载
        page.evaluate('window.scrollTo(0, document.body.scrollHeight * 0.6)')
        page.wait_for_timeout(2000)
        page.evaluate('window.scrollTo(0, document.body.scrollHeight * 0.8)')
        page.wait_for_timeout(2000)

        # rednote-mcp 确认的选择器：.parent-comment .comment-item
        items = page.query_selector_all('.parent-comment .comment-item')
        if not items:
            items = page.query_selector_all('[class*="comment-item"]')

        for el in items[:30]:  # 最多取 30 条
            try:
                author_el = el.query_selector('.author .name')
                content_el = el.query_selector('.content .note-text')
                likes_el = el.query_selector('.like .count')

                author_name = author_el.inner_text().strip() if author_el else ''
                content = content_el.inner_text().strip() if content_el else ''
                likes_text = likes_el.inner_text().strip() if likes_el else '0'

                # 解析点赞数
                likes = 0
                if likes_text.isdigit():
                    likes = int(likes_text)
                elif likes_text not in ('赞', ''):
                    m = re.match(r'([\d.]+)', likes_text)
                    if m:
                        likes = int(float(m.group(1)))

                if content and len(content) > 2:
                    comments.append({
                        'author': author_name,
                        'text': content,
                        'likes': likes,
                    })
            except Exception:
                continue

        # 按点赞数降序排列
        comments.sort(key=lambda c: c['likes'], reverse=True)

    except Exception as e:
        print(f'[XHS] 评论提取失败: {e}', file=sys.stderr)
    return comments


# ---------------------------------------------------------------------------
# 小红书：OCR 桥接
# ---------------------------------------------------------------------------

def _get_ocr_python() -> Path | None:
    """获取 OCR venv 的 Python 路径（如果已安装）。"""
    if sys.platform == 'win32':
        p = OCR_VENV_DIR / 'Scripts' / 'python.exe'
    else:
        p = OCR_VENV_DIR / 'bin' / 'python'
    return p if p.exists() else None


def _ocr_xhs_images(image_urls: list[str]) -> list[str]:
    """对小红书笔记图片做 OCR，返回每张图片的文字列表。

    通过 subprocess 调用独立的 ocr_image.py 脚本（在 .venv-ocr 中运行）。
    如果 OCR 环境未安装或不可用，静默跳过。
    """
    if not image_urls:
        return []

    ocr_python = _get_ocr_python()
    if not ocr_python or not OCR_SCRIPT.exists():
        print('[XHS] OCR 环境未就绪，跳过图片文字提取。'
              '运行 `py -3 run.py --setup-ocr` 安装 OCR 环境。',
              file=sys.stderr)
        return []

    try:
        print(f'[XHS] 正在对 {len(image_urls)} 张图片做 OCR...',
              file=sys.stderr)
        result = subprocess.run(
            [str(ocr_python), str(OCR_SCRIPT)] + image_urls,
            capture_output=True, text=True,
            timeout=900,  # 15 分钟超时（GPU 上约 15-20 秒/张，含下载）
            encoding='utf-8',
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            texts = [item['text'] for item in data
                     if item.get('text') and not item.get('error')]
            print(f'[XHS] OCR 完成，{len(texts)}/{len(image_urls)} 张图片提取到文字',
                  file=sys.stderr)
            return texts
        elif result.stderr:
            print(f'[XHS] OCR 警告: {result.stderr[:200]}', file=sys.stderr)
    except subprocess.TimeoutExpired:
        print('[XHS] OCR 超时（15 分钟），跳过', file=sys.stderr)
    except (json.JSONDecodeError, Exception) as e:
        print(f'[XHS] OCR 失败: {e}', file=sys.stderr)

    return []


# ---------------------------------------------------------------------------
# 小红书：内容合并与去重
# ---------------------------------------------------------------------------

def _merge_xhs_content(
    title: str, author: str, note_text: str, ocr_texts: list[str],
    comments: list[dict], tags: list[str], engagement: dict,
) -> str:
    """将小红书笔记文字 + OCR 文字 + 评论合并为结构化 Markdown。"""
    parts = []

    # 标题和元信息
    parts.append(f'# {title}\n')
    meta_items = []
    if author:
        meta_items.append(f'**作者**: {author}')
    if engagement:
        eng_parts = []
        if engagement.get('likes'):
            eng_parts.append(f"❤️ {engagement['likes']:,}")
        if engagement.get('collects'):
            eng_parts.append(f"⭐ {engagement['collects']:,}")
        if engagement.get('comments'):
            eng_parts.append(f"💬 {engagement['comments']:,}")
        if eng_parts:
            meta_items.append(' | '.join(eng_parts))
    if tags:
        meta_items.append('**标签**: ' + '、'.join(tags))
    if meta_items:
        parts.append('\n'.join(meta_items))

    # 笔记正文
    if note_text:
        parts.append('## 笔记正文\n')
        parts.append(note_text)

    # OCR 文字（去重后）
    if ocr_texts:
        unique_ocr = _deduplicate_ocr(note_text, ocr_texts)
        if unique_ocr:
            parts.append('## 图片文字内容\n')
            for i, text in enumerate(unique_ocr, 1):
                parts.append(f'### 图片 {i}\n')
                parts.append(text)

    # 筛选后的评论
    if comments:
        valuable = _filter_valuable_comments(comments)
        if valuable:
            parts.append('## 评论区精选\n')
            for c in valuable:
                likes_str = f" ({c['likes']} 赞)" if c.get('likes') else ''
                author_str = f"**{c['author']}**" if c.get('author') else ''
                prefix = f'{author_str}{likes_str}: ' if author_str else ''
                parts.append(f'- {prefix}{c["text"]}')

    return '\n\n'.join(parts)


def _deduplicate_ocr(note_text: str, ocr_texts: list[str]) -> list[str]:
    """将 OCR 文字与笔记正文去重。

    按句子级别比较，用字符集 Jaccard 相似度 > 0.7 判定为重复并去除。
    """
    if not note_text:
        return [t for t in ocr_texts if t.strip()]

    # 将笔记正文拆为句子集合
    note_sentences = set()
    for s in re.split(r'[。！？\n.!?\r]', note_text):
        s = s.strip()
        if len(s) > 3:
            note_sentences.add(s)

    unique = []
    for ocr_text in ocr_texts:
        if not ocr_text.strip():
            continue
        unique_sentences = []
        for s in re.split(r'[。！？\n.!?\r]', ocr_text):
            s = s.strip()
            if len(s) <= 3:
                continue
            # 检查与笔记文字的 Jaccard 相似度
            is_dup = False
            s_chars = set(s)
            for ns in note_sentences:
                ns_chars = set(ns)
                union = len(s_chars | ns_chars)
                if union == 0:
                    continue
                jaccard = len(s_chars & ns_chars) / union
                if jaccard > 0.7:
                    is_dup = True
                    break
            if not is_dup:
                unique_sentences.append(s)
        if unique_sentences:
            unique.append('。'.join(unique_sentences))

    return unique


def _filter_valuable_comments(comments: list[dict]) -> list[dict]:
    """筛选有信息价值的评论。

    保留标准: 长度 > 15 字 + 排除纯情绪/闲聊。最多返回 10 条。
    """
    noise_patterns = [
        r'^(太[棒好赞强厉害]了|好[棒赞强厉害]|收藏了|感谢分享|说得对|确实|'
        r'哈哈|真的|关注了|学到了|马了|赞|谢谢|厉害|牛|绝了|爱了|冲|yyds)',
        r'^(求|蹲|同问|mark|码住|想知道|在哪|多少钱|链接|求链接)',
        r'^[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff'
        r'\U0001f900-\U0001f9ff\u2600-\u26ff\u2700-\u27bf\s]{0,10}$',
    ]

    valuable = []
    for c in comments:
        text = c.get('text', '')
        if len(text) < 15:
            continue
        if any(re.match(p, text, re.I) for p in noise_patterns):
            continue
        valuable.append(c)

    return valuable[:10]


# ---------------------------------------------------------------------------
# 内容切分
# ---------------------------------------------------------------------------

def segment_content(result: dict, segment_minutes: int = 5) -> dict:
    """将提取的内容切分为段落。

    - 视频内容: 按时间戳切分，每 segment_minutes 分钟一段
    - 网页/文章: 按 Markdown 标题或自然段落分组
    """
    if result.get('error'):
        return result

    segments = []

    if result['source'] in ('youtube',) and result.get('transcript_entries'):
        # YouTube 有精确时间戳，按时间切分
        segment_seconds = segment_minutes * 60
        current_segment_texts = []
        current_start = 0
        segment_index = 0

        for entry in result['transcript_entries']:
            start = entry['start']
            text = entry['text']

            # 如果超过段落时长，保存当前段落并开始新段落
            if start - current_start >= segment_seconds and current_segment_texts:
                segments.append({
                    'index': segment_index,
                    'start_seconds': round(current_start),
                    'end_seconds': round(start),
                    'time_range': f"{_format_time(current_start)} - {_format_time(start)}",
                    'text': ' '.join(current_segment_texts),
                })
                segment_index += 1
                current_segment_texts = []
                current_start = start

            current_segment_texts.append(text)

        # 最后一段
        if current_segment_texts:
            end_time = result.get('total_duration_seconds', current_start)
            segments.append({
                'index': segment_index,
                'start_seconds': round(current_start),
                'end_seconds': round(end_time),
                'time_range': f"{_format_time(current_start)} - {_format_time(end_time)}",
                'text': ' '.join(current_segment_texts),
            })

    else:
        # 网页/文章/无时间戳视频: 按自然段落或标题切分
        text = result['full_text']
        # 优先按 Markdown 标题切分
        sections = re.split(r'\n(?=#{1,3}\s)', text)
        if len(sections) <= 1:
            # 没有标题结构，按双换行切分段落，然后每 3-5 段合并
            paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
            group_size = 4
            for i in range(0, len(paragraphs), group_size):
                group = paragraphs[i:i + group_size]
                segments.append({
                    'index': len(segments),
                    'text': '\n\n'.join(group),
                })
        else:
            for section in sections:
                section = section.strip()
                if section:
                    # 提取标题作为段落标签
                    title_match = re.match(r'^(#{1,3})\s+(.+)', section)
                    segments.append({
                        'index': len(segments),
                        'heading': title_match.group(2) if title_match else None,
                        'text': section,
                    })

    result['segments'] = segments
    result['segment_count'] = len(segments)
    return result


def _format_time(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS 或 MM:SS。"""
    seconds = int(seconds)
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _extract_webpage_metadata(html: str) -> tuple[str, str, str]:
    """从 HTML 中提取标题、作者、日期。"""
    try:
        from trafilatura.metadata import extract_metadata
        from lxml import html as lxml_html
        tree = lxml_html.fromstring(html)
        meta = extract_metadata(tree)
        if meta is None:
            return '未知标题', '', ''
        title = getattr(meta, 'title', None) or '未知标题'
        author = getattr(meta, 'author', None) or ''
        date = getattr(meta, 'date', None) or ''
        return str(title), str(author), str(date)
    except Exception:
        return '未知标题', '', ''


def _error(message: str) -> dict:
    return {
        'source': 'unknown',
        'url': '',
        'title': '',
        'full_text': '',
        'segments': [],
        'error': message,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='统一内容提取工具')
    parser.add_argument('url', help='要提取的 URL')
    parser.add_argument(
        '--lang', default='zh-Hans,en,zh,zh-CN',
        help='字幕语言优先级，逗号分隔 (默认: zh-Hans,en,zh,zh-CN)'
    )
    parser.add_argument(
        '--segment-minutes', type=int, default=5,
        help='视频内容切分间隔（分钟），默认 5'
    )

    args = parser.parse_args()
    languages = [lang.strip() for lang in args.lang.split(',')]

    source = detect_source(args.url)

    if source == 'pdf':
        result = extract_pdf(args.url)
    elif source == 'youtube':
        result = extract_youtube(args.url, languages)
    elif source == 'bilibili':
        result = extract_bilibili(args.url, languages)
    elif source == 'twitter':
        result = extract_twitter(args.url)
    elif source == 'wechat':
        result = extract_wechat(args.url)
    elif source == 'xiaohongshu':
        result = extract_xiaohongshu(args.url)
    else:
        result = extract_webpage(args.url)

    # 切分段落
    if not result.get('error'):
        result = segment_content(result, args.segment_minutes)

    # 输出 JSON（移除原始 transcript_entries 以减小体积）
    output = {
        'source': result.get('source', 'unknown'),
        'url': result.get('url', args.url),
        'title': result.get('title', ''),
        'author': result.get('author', ''),
        'date': result.get('date', ''),
        'total_duration_seconds': result.get('total_duration_seconds', 0),
        'page_count': result.get('page_count', 0),
        'word_count': result.get('word_count', 0),
        'image_count': result.get('image_count', 0),
        'comment_count': result.get('comment_count', 0),
        'segment_count': result.get('segment_count', 0),
        'segments': result.get('segments', []),
        'full_text': result.get('full_text', ''),
        'error': result.get('error'),
    }

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
