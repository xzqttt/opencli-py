#!/usr/bin/env python3
"""Baidu Scholar scraper using opencli-py."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

# Add parent directory to path for opencli_py import
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from opencli_py import OpenCLI

BASE_URL = "https://xueshu.baidu.com"
BAIDU_PAGE_SIZE = 10
SECURITY_PAGE_TITLE = "百度安全验证"

# JavaScript to extract search results
SEARCH_EXTRACT_JS = r"""
(() => {
  const normalize = (value) => String(value || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{2,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();

  const normalizeInline = (value) => normalize(value).replace(/\n+/g, ' ').trim();

  const results = [];
  const items = document.querySelectorAll('.sc_content, .result, [class*="result"]');

  for (const item of Array.from(items).slice(0, 20)) {
    try {
      const titleEl = item.querySelector('h3 a, .sc_title a, [class*="title"] a');
      if (!titleEl) continue;

      const title = normalizeInline(titleEl.textContent);
      const url = titleEl.href;

      const authors = [];
      const authorEls = item.querySelectorAll('.sc_authors a, [class*="author"] a');
      for (const a of authorEls) {
        authors.push(normalizeInline(a.textContent));
      }

      const abstractEl = item.querySelector('.c_abstract, .sc_abstract, [class*="abstract"]');
      const abstract = abstractEl ? normalize(abstractEl.textContent) : '';

      const yearEl = item.querySelector('.sc_year, [class*="year"]');
      const year = yearEl ? normalizeInline(yearEl.textContent) : '';

      const sourceEl = item.querySelector('.sc_source, [class*="source"]');
      const source = sourceEl ? normalizeInline(sourceEl.textContent) : '';

      const citeEl = item.querySelector('.sc_cite a, [class*="cite"]');
      let citations = '';
      if (citeEl) {
        const citeText = normalizeInline(citeEl.textContent);
        const match = citeText.match(/(\d+)/);
        citations = match ? match[1] : '';
      }

      results.push({
        title,
        url,
        authors,
        abstract,
        year,
        source,
        citations,
      });
    } catch (e) {
      continue;
    }
  }

  return results;
})()
"""

# JavaScript to extract detail page
DETAIL_EXTRACT_JS = r"""
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (value) => String(value || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{2,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();

  const normalizeLine = (value) => normalize(value).replace(/\n+/g, ' ').trim();

  // Try to click "展开" for abstract
  const tryExpand = () => {
    const candidates = Array.from(
      document.querySelectorAll('#dtl_l a, #dtl_l button, #dtl_l span, #dtl_l div, a, button')
    );
    for (const el of candidates) {
      const text = normalizeLine(el.textContent);
      if (text.includes('展开') || text.includes('更多')) {
        try { el.click(); } catch {}
        return true;
      }
    }
    return false;
  };

  tryExpand();
  await sleep(300);

  const result: Record<string, any> = {
    title: '',
    authors: [],
    abstract: '',
    keywords: [],
    year: '',
    doi: '',
    source: '',
  };

  // Title
  const titleEl = document.querySelector('.dtl_main-title, h1, [class*="title"]');
  if (titleEl) result.title = normalizeLine(titleEl.textContent);

  // Authors
  const authorEls = document.querySelectorAll('.dtl_author a, .author a, [class*="author"] a');
  for (const a of authorEls) {
    result.authors.push(normalizeLine(a.textContent));
  }

  // Abstract
  const abstractEl = document.querySelector('#dtl_abstract, .abstract, [class*="abstract"]');
  if (abstractEl) result.abstract = normalize(abstractEl.textContent);

  // Keywords
  const keywordEls = document.querySelectorAll('.dtl_keywords a, .keyword a, [class*="keyword"] a');
  for (const a of keywordEls) {
    result.keywords.push(normalizeLine(a.textContent));
  }

  // Year, source, DOI from metadata
  const metaEls = document.querySelectorAll('.dtl_content-row, .dtl-row, [class*="row"]');
  for (const row of metaEls) {
    const text = normalizeLine(row.textContent);
    if (text.includes('年份') || text.includes('年')) {
      const match = text.match(/(\d{4})/);
      if (match) result.year = match[1];
    }
    if (text.includes('DOI') || text.includes('doi')) {
      const parts = text.split(/[:：]/);
      if (parts.length > 1) result.doi = normalizeLine(parts[1]);
    }
    if (text.includes('来源') || text.includes('期刊') || text.includes('会议')) {
      const parts = text.split(/[:：]/);
      if (parts.length > 1) result.source = normalizeLine(parts[1]);
    }
  }

  return result;
})()
"""


def console(msg: str, end: str = "\n"):
    """Print to console."""
    print(msg, end=end)


def write_json(data: Any, path: Path):
    """Write data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_keyword_list(s: str) -> list[str]:
    """Clean and split keyword list."""
    if not s:
        return []
    return [k.strip() for k in re.split(r"[,，;；\n]+", s) if k.strip()]


def dedupe_items(items: list[dict], key: str = "url") -> list[dict]:
    """Deduplicate items by key."""
    seen = set()
    result = []
    for item in items:
        k = item.get(key, "")
        if k and k not in seen:
            seen.add(k)
            result.append(item)
    return result


def normalize_inline_text(s: str) -> str:
    """Normalize inline text."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def build_search_url(keyword: str, page: int = 0) -> str:
    """Build Baidu Scholar search URL."""
    params = {
        "wd": keyword,
        "pn": str(page * BAIDU_PAGE_SIZE),
    }
    return f"{BASE_URL}/s?{urlencode(params)}"


def is_security_page(page_title: str, page_url: str) -> bool:
    """Check if page is security verification."""
    if SECURITY_PAGE_TITLE in page_title:
        return True
    if "verify" in page_url.lower() or "security" in page_url.lower():
        return True
    return False


def search_baidu_scholar(
    page,
    keyword: str,
    max_pages: int = 3,
) -> list[dict]:
    """Search Baidu Scholar and return results."""
    all_results = []

    for page_num in range(max_pages):
        console(f"  搜索第 {page_num + 1} 页...")
        url = build_search_url(keyword, page_num)

        page.goto(url)
        time.sleep(2)  # Wait for page to load

        # Check for security page
        title = page.evaluate("document.title")
        current_url = page.evaluate("location.href")

        if is_security_page(title, current_url):
            console(f"  ⚠️  遇到安全验证页面，请在浏览器中完成验证")
            console(f"     URL: {current_url}")
            console(f"     完成验证后按回车继续...", end="")
            input()
            time.sleep(2)

        # Extract results
        results = page.evaluate(SEARCH_EXTRACT_JS)
        if not results:
            console(f"  第 {page_num + 1} 页未找到结果，停止搜索")
            break

        console(f"  第 {page_num + 1} 页找到 {len(results)} 条结果")
        all_results.extend(results)

        if len(results) < BAIDU_PAGE_SIZE:
            console(f"  已到最后一页")
            break

    return dedupe_items(all_results)


def get_detail(page, url: str) -> dict:
    """Get detail information from a paper page."""
    page.goto(url)
    time.sleep(2)
    return page.evaluate(DETAIL_EXTRACT_JS)


def main():
    parser = argparse.ArgumentParser(description="Baidu Scholar Scraper")
    parser.add_argument("keyword", help="Search keyword")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON file path")
    parser.add_argument("-p", "--pages", type=int, default=3, help="Max pages to scrape")
    parser.add_argument("-d", "--detail", action="store_true", help="Fetch detail for each result")
    args = parser.parse_args()

    console("=" * 60)
    console("百度学术搜索 (opencli-py 版本)")
    console("=" * 60)
    console()

    console(f"关键词: {args.keyword}")
    console(f"最大页数: {args.pages}")
    console()

    with OpenCLI() as cli:
        page = cli.page()

        console("开始搜索...")
        results = search_baidu_scholar(page, args.keyword, max_pages=args.pages)
        console()

        if args.detail and results:
            console(f"获取 {len(results)} 条结果的详细信息...")
            for i, item in enumerate(results):
                console(f"  {i + 1}/{len(results)}: {item.get('title', '')[:50]}...")
                if item.get("url"):
                    try:
                        detail = get_detail(page, item["url"])
                        item.update(detail)
                    except Exception as e:
                        console(f"    失败: {e}")
            console()

        console(f"总共找到 {len(results)} 条结果")
        console()

        if args.output:
            write_json(results, args.output)
            console(f"结果已保存到: {args.output}")
        else:
            console("结果:")
            print(json.dumps(results, ensure_ascii=False, indent=2))

    console()
    console("=" * 60)
    console("完成!")
    console("=" * 60)


if __name__ == "__main__":
    main()
