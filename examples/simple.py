#!/usr/bin/env python3
"""Simple example for opencli-py."""

from opencli_py import OpenCLI


def main():
    print("opencli-py example")
    print("=" * 40)

    with OpenCLI() as cli:
        page = cli.page()

        print("\n1. Navigating to https://example.com...")
        page.goto("https://example.com")
        print("   ✓ Done")

        print("\n2. Getting page title via JavaScript...")
        title = page.evaluate("document.title")
        print(f"   Title: {title}")

        print("\n3. Getting cookies...")
        cookies = page.cookies(domain="example.com")
        print(f"   Found {len(cookies)} cookies")
        for cookie in cookies:
            print(f"   - {cookie['name']}: {cookie['value']}")

        print("\n" + "=" * 40)
        print("Example complete!")


if __name__ == "__main__":
    main()
