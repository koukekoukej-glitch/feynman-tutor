#!/usr/bin/env python3
"""
嵌入式环境启动器 - 自动管理 venv 并运行 extract_content.py。

首次运行时自动创建 venv 并安装依赖，后续直接复用。
所有参数原样透传给 extract_content.py。

用法（和 extract_content.py 完全一致）:
    py -3 run.py <URL> [--lang zh-Hans,en] [--segment-minutes 5]
"""

import subprocess
import sys
import os
from pathlib import Path

# Windows UTF-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPT_DIR / '.venv'
REQUIREMENTS = [
    'youtube-transcript-api',
    'yt-dlp',
    'trafilatura',
    'lxml_html_clean',
    'bilibili-api-python',
    'httpx',
    'playwright',
    'playwright-stealth',
    'pymupdf4llm',
    'camoufox',
]
# 标记文件：记录依赖已安装完成
INSTALLED_MARKER = VENV_DIR / '.installed'
PLAYWRIGHT_MARKER = VENV_DIR / '.playwright_installed'
CAMOUFOX_MARKER = VENV_DIR / '.camoufox_installed'


def get_venv_python() -> Path:
    """获取 venv 中 Python 可执行文件的路径。"""
    if sys.platform == 'win32':
        return VENV_DIR / 'Scripts' / 'python.exe'
    return VENV_DIR / 'bin' / 'python'


def ensure_venv():
    """确保 venv 存在且依赖已安装。"""
    venv_python = get_venv_python()

    if INSTALLED_MARKER.exists() and venv_python.exists():
        return  # 已就绪

    if not venv_python.exists():
        print('正在创建隔离的 Python 环境...', file=sys.stderr)
        subprocess.run(
            [sys.executable, '-m', 'venv', str(VENV_DIR)],
            check=True,
        )

    print('正在安装依赖（仅首次运行需要）...', file=sys.stderr)
    subprocess.run(
        [str(venv_python), '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'],
        check=True,
    )
    subprocess.run(
        [str(venv_python), '-m', 'pip', 'install', '--quiet'] + REQUIREMENTS,
        check=True,
    )

    # 写入标记
    INSTALLED_MARKER.write_text('ok')
    print('环境就绪。\n', file=sys.stderr)


def ensure_playwright_browsers():
    """确保 Playwright Chromium 浏览器已安装（网页提取的 JS 渲染回退需要）。"""
    venv_python = get_venv_python()

    if PLAYWRIGHT_MARKER.exists() and venv_python.exists():
        return

    print('正在安装 Playwright 浏览器引擎（仅首次需要，约 1-2 分钟）...', file=sys.stderr)
    # 确保 playwright 包已安装（pip 会自动跳过已安装的）
    subprocess.run(
        [str(venv_python), '-m', 'pip', 'install', '--quiet', 'playwright'],
        check=True,
    )
    # 仅安装 Chromium（~200MB），不装 Firefox/WebKit
    subprocess.run(
        [str(venv_python), '-m', 'playwright', 'install', 'chromium'],
        check=True,
    )

    PLAYWRIGHT_MARKER.write_text('ok')
    print('Playwright 浏览器引擎就绪。\n', file=sys.stderr)


def ensure_camoufox_browser():
    """确保 Camoufox 浏览器已下载（微信公众号提取需要）。"""
    venv_python = get_venv_python()

    if CAMOUFOX_MARKER.exists() and venv_python.exists():
        return

    print('正在下载 Camoufox 浏览器引擎（仅首次需要，约 1-2 分钟）...', file=sys.stderr)
    try:
        subprocess.run(
            [str(venv_python), '-m', 'camoufox', 'fetch'],
            check=True,
        )
        CAMOUFOX_MARKER.write_text('ok')
        print('Camoufox 浏览器引擎就绪。\n', file=sys.stderr)
    except Exception as e:
        print(f'Camoufox 浏览器下载失败（非致命，微信渠道将回退到 Playwright）: {e}', file=sys.stderr)


def ensure_deno_in_path():
    """确保 deno（yt-dlp 的 JS 运行时）在 PATH 中。"""
    if sys.platform == 'win32':
        # winget 安装的 deno 路径
        deno_dirs = [
            Path.home() / '.deno' / 'bin',
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Links',
        ]
        # 搜索 winget packages 目录
        winget_pkgs = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages'
        if winget_pkgs.exists():
            for pkg_dir in winget_pkgs.iterdir():
                if 'Deno' in pkg_dir.name:
                    deno_dirs.append(pkg_dir)

        for d in deno_dirs:
            if d.exists() and str(d) not in os.environ.get('PATH', ''):
                os.environ['PATH'] = os.environ.get('PATH', '') + os.pathsep + str(d)


def main():
    ensure_venv()
    ensure_playwright_browsers()
    ensure_camoufox_browser()
    ensure_deno_in_path()

    extract_script = SCRIPT_DIR / 'extract_content.py'
    venv_python = get_venv_python()

    # 透传所有命令行参数给 extract_content.py
    result = subprocess.run(
        [str(venv_python), str(extract_script)] + sys.argv[1:],
    )
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
