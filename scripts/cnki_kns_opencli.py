#!/usr/bin/env python3
"""CNKI (China National Knowledge Infrastructure) scraper using opencli-py."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

# Add parent directory to path for opencli_py import
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from opencli_py import OpenCLI

# Try to import helper functions from baidu_scholar_opencli
try:
    from baidu_scholar_opencli import (
        clean_keyword_list,
        console,
        dedupe_items,
        normalize_inline_text,
        write_json,
    )
except ModuleNotFoundError:
    from scripts.baidu_scholar_opencli import (
        clean_keyword_list,
        console,
        dedupe_items,
        normalize_inline_text,
        write_json,
    )

BASE_URL = "https://kns.cnki.net/kns8s/defaultresult/index"
DEFAULT_CROSSIDS = (
    "YSTT4HG0,LSTPFY1C,JUP3MUPD,MPMFIG1A,WQ0UVIAA,BLZOG7CK,"
    "PWFIRAGL,EMRPGLPA,NLBO1Z6R,NN3FJMUV"
)
GENERIC_DETAIL_TITLES = {"自动登录", "登录", "机构登录"}
SORT_FIELD = "CF"
SORT_TYPE = "DESC"
DEFAULT_PAGE_SIZE = 20
TOPIC_GROUP_KEY = "ZYZT|||CYZT"
TOPIC_FIELD_MAIN = "ZYZT"

# JavaScript to extract search results
SEARCH_EXTRACT_JS = r"""
(() => {
  const normalize = (value) => String(value || '')
    .replace(/\u00a0/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const results = [];
  const items = document.querySelectorAll('.result-table-list tbody tr, .result-item, [class*="result"]');

  for (const item of Array.from(items).slice(0, 30)) {
    try {
      // Skip header rows
      if (item.querySelector('th')) continue;

      const titleEl = item.querySelector('a.fc-blue, a[class*="title"], .title a, h3 a');
      if (!titleEl) continue;

      const title = normalize(titleEl.textContent);
      const url = titleEl.href;

      // Authors
      const authors = [];
      const authorEls = item.querySelectorAll('.author a, [class*="author"] a');
      for (const a of authorEls) {
        authors.push(normalize(a.textContent));
      }

      // Source / Journal
      const sourceEl = item.querySelector('.source a, [class*="source"] a, .journal a');
      const source = sourceEl ? normalize(sourceEl.textContent) : '';

      // Year
      let year = '';
      const yearEl = item.querySelector('.date, .year, [class*="date"], [class*="year"]');
      if (yearEl) {
        const yearText = normalize(yearEl.textContent);
        const match = yearText.match(/(\d{4})/);
        if (match) year = match[1];
      }

      // Database / Type
      const dbEl = item.querySelector('.database, .type, [class*="database"], [class*="type"]');
      const db = dbEl ? normalize(dbEl.textContent) : '';

      // Citation count
      let citations = '';
      const citeEl = item.querySelector('.count, .cite, [class*="count"], [class*="cite"]');
      if (citeEl) {
        const citeText = normalize(citeEl.textContent);
        const match = citeText.match(/(\d+)/);
        if (match) citations = match[1];
      }

      results.push({
        title,
        url,
        authors,
        source,
        year,
        db,
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

  const result: Record<string, any> = {
    title: '',
    authors: [],
    abstract: '',
    keywords: [],
    year: '',
    source: '',
    doi: '',
    fund: '',
    classification: '',
  };

  // Title
  const titleEl = document.querySelector('h1, .title, [class*="title"]');
  if (titleEl) result.title = normalizeLine(titleEl.textContent);

  // Authors
  const authorEls = document.querySelectorAll('.author a, .authors a, [class*="author"] a');
  for (const a of authorEls) {
    const text = normalizeLine(a.textContent);
    if (text) result.authors.push(text);
  }

  // Abstract
  const abstractEl = document.querySelector('#ChDivSummary, .abstract, .summary, [class*="abstract"], [class*="summary"]');
  if (abstractEl) result.abstract = normalize(abstractEl.textContent);

  // Keywords
  const keywordEls = document.querySelectorAll('.keywords a, .keyword a, [class*="keyword"] a');
  for (const a of keywordEls) {
    const text = normalizeLine(a.textContent);
    if (text) result.keywords.push(text);
  }

  // Source / Journal
  const sourceEl = document.querySelector('.journal a, .source a, .periodical a, [class*="journal"] a, [class*="source"] a');
  if (sourceEl) result.source = normalizeLine(sourceEl.textContent);

  // Year
  const yearEl = document.querySelector('.publish-date, .year, .date, [class*="date"]');
  if (yearEl) {
    const text = normalizeLine(yearEl.textContent);
    const match = text.match(/(\d{4})/);
    if (match) result.year = match[1];
  }

  // DOI
  const doiEl = document.querySelector('.doi, [class*="doi"]');
  if (doiEl) result.doi = normalizeLine(doiEl.textContent);

  // Fund
  const fundEl = document.querySelector('.fund, [class*="fund"]');
  if (fundEl) result.fund = normalizeLine(fundEl.textContent);

  // Classification
  const classEl = document.querySelector('.classification, .class, [class*="class"]');
  if (classEl) result.classification = normalizeLine(classEl.textContent);

  // Parse meta info table
  const rows = document.querySelectorAll('.row, [class*="row"], .info-item, tr');
  for (const row of rows) {
    const text = normalizeLine(row.textContent);
    if (!text) continue;

    if (text.includes('年') && text.match(/\d{4}/) && !result.year) {
      const match = text.match(/(\d{4})/);
      if (match) result.year = match[1];
    }
    if ((text.includes('DOI') || text.includes('doi')) && !result.doi) {
      const parts = text.split(/[:：]/);
      if (parts.length > 1) result.doi = normalizeLine(parts[1]);
    }
    if ((text.includes('期刊') || text.includes('来源')) && !result.source) {
      const parts = text.split(/[:：]/);
      if (parts.length > 1) result.source = normalizeLine(parts[1]);
    }
    if ((text.includes('基金') || text.includes('资助')) && !result.fund) {
      const parts = text.split(/[:：]/);
      if (parts.length > 1) result.fund = normalizeLine(parts[1]);
    }
  }

  return result;
})()
"""


def looks_like_cnki_security(body_text: str, title_text: str, current_url: str) -> bool:
    """Check if page is CNKI security verification."""
    if not title_text:
        return False
    if any(t in title_text for t in GENERIC_DETAIL_TITLES):
        return True
    if "验证码" in title_text or "验证" in title_text:
        return True
    if "login" in current_url.lower() or "auth" in current_url.lower():
        return True
    return False


def build_search_url(
    keyword: str,
    page: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> str:
    """Build CNKI search URL."""
    query = {
        "kw": keyword,
        "crossids": DEFAULT_CROSSIDS,
        "p": str(page + 1),
        "pageSize": str(page_size),
        "sortfield": SORT_FIELD,
        "sorttype": SORT_TYPE,
    }
    return f"{BASE_URL}?{urlencode(query)}"


def search_cnki(
    page,
    keyword: str,
    max_pages: int = 3,
) -> list[dict]:
    """Search CNKI and return results."""
    all_results = []

    for page_num in range(max_pages):
        console(f"  搜索第 {page_num + 1} 页...")
        url = build_search_url(keyword, page_num)

        page.goto(url)
        time.sleep(3)  # Wait for page to load

        # Check for security/login page
        title = page.evaluate("document.title")
        current_url = page.evaluate("location.href")
        body_text = page.evaluate("document.body?.textContent || ''")

        if looks_like_cnki_security(body_text, title, current_url):
            console(f"  ⚠️  遇到登录/验证页面")
            console(f"     URL: {current_url}")
            console(f"     请在浏览器中登录/验证后按回车继续...", end="")
            input()
            time.sleep(2)

        # Extract results
        results = page.evaluate(SEARCH_EXTRACT_JS)
        if not results:
            console(f"  第 {page_num + 1} 页未找到结果，停止搜索")
            break

        console(f"  第 {page_num + 1} 页找到 {len(results)} 条结果")
        all_results.extend(results)

        if len(results) < DEFAULT_PAGE_SIZE:
            console(f"  已到最后一页")
            break

    return dedupe_items(all_results)


def get_detail(page, url: str) -> dict:
    """Get detail information from a CNKI paper page."""
    page.goto(url)
    time.sleep(2)
    return page.evaluate(DETAIL_EXTRACT_JS)


def main():
    parser = argparse.ArgumentParser(description="CNKI KNS Scraper")
    parser.add_argument("keyword", help="Search keyword")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON file path")
    parser.add_argument("-p", "--pages", type=int, default=3, help="Max pages to scrape")
    parser.add_argument("-d", "--detail", action="store_true", help="Fetch detail for each result")
    args = parser.parse_args()

    console("=" * 60)
    console("知网搜索 (opencli-py 版本)")
    console("=" * 60)
    console()

    console(f"关键词: {args.keyword}")
    console(f"最大页数: {args.pages}")
    console()

    with OpenCLI() as cli:
        page = cli.page()

        console("开始搜索...")
        results = search_cnki(page, args.keyword, max_pages=args.pages)
        console()

        if args.detail and results:
            console(f"获取 {len(results)} 条结果的详细信息...")
            for i, item in enumerate(results):
                title_snippet = item.get("title", "")[:50]
                console(f"  {i + 1}/{len(results)}: {title_snippet}...")
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
