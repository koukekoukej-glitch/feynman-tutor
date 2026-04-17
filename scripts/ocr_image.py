#!/usr/bin/env python3
"""
图片文字识别脚本（RapidOCR）— 运行在独立 venv (.venv-ocr/) 中。

被 extract_content.py 通过 subprocess 调用，用于对小红书笔记图片做 OCR。

用法:
    python ocr_image.py <image_url_or_path> [<image_url_or_path> ...]

输出:
    JSON 数组到 stdout: [{"path": "...", "text": "...", "error": null}, ...]

环境安装:
    py -3 run.py --setup-ocr
"""

import json
import sys
import io
from pathlib import Path

# Windows UTF-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


# ---------------------------------------------------------------------------
# OCR 引擎（全局单例）
# ---------------------------------------------------------------------------

_engine = None


def _ensure_engine():
    """初始化 RapidOCR 引擎（懒加载单例）。"""
    global _engine
    if _engine is not None:
        return

    from rapidocr_onnxruntime import RapidOCR
    _engine = RapidOCR()
    print('[OCR] RapidOCR 引擎就绪', file=sys.stderr)


# ---------------------------------------------------------------------------
# 单张图片 OCR
# ---------------------------------------------------------------------------

def ocr_single(path_or_url: str) -> dict:
    """对单张图片进行 OCR，返回 {"path": ..., "text": ..., "error": ...}。"""
    try:
        from PIL import Image

        _ensure_engine()

        # 加载图片
        if path_or_url.startswith('http'):
            img = _download_image(path_or_url)
            if img is None:
                return {'path': path_or_url, 'text': '', 'error': '图片加载失败'}
        else:
            img = Image.open(path_or_url)

        img = img.convert('RGB')

        # RapidOCR 接受 PIL Image 或 numpy array
        import numpy as np
        img_array = np.array(img)

        result, _ = _engine(img_array)

        if not result:
            return {'path': path_or_url, 'text': '', 'error': None}

        # result 是 list of [bbox, text, confidence]
        lines = [item[1] for item in result if item[1].strip()]
        text = '\n'.join(lines)

        return {'path': path_or_url, 'text': text.strip(), 'error': None}

    except Exception as e:
        return {'path': path_or_url, 'text': '', 'error': str(e)}


def _download_image(url: str):
    """下载图片 URL，返回 PIL Image。"""
    try:
        import httpx
        from PIL import Image

        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.xiaohongshu.com/',
        }
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content))
    except Exception as e:
        print(f'[OCR] 图片下载失败 ({url[:60]}...): {e}', file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print('用法: python ocr_image.py <image_url_or_path> ...', file=sys.stderr)
        sys.exit(1)

    results = []
    for arg in sys.argv[1:]:
        print(f'[OCR] 处理: {arg[:60]}...', file=sys.stderr)
        result = ocr_single(arg)
        results.append(result)
        if result.get('text'):
            print(f'[OCR] ✓ {len(result["text"])} 字符', file=sys.stderr)
        elif result.get('error'):
            print(f'[OCR] ✗ {result["error"]}', file=sys.stderr)

    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
