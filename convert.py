"""note.com WXR XML を記事単位の Markdown ファイルに変換するスクリプト。

Usage:
    python convert.py
"""

import os
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime


INPUT_XML = "note-workhack20-1.xml"
OUTPUT_DIR = "articles"
INDEX_FILE = "index.md"

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wp": "http://wordpress.org/export/1.2/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class HTMLToMarkdown(HTMLParser):
    """Simple HTML-to-Markdown converter tailored for note.com export."""

    def __init__(self):
        super().__init__()
        self.output = []
        self.list_depth = 0
        self.in_li = False
        self.li_has_content = False
        self.in_a = False
        self.href = ""
        self.in_strong = False
        self.in_blockquote = False
        self.in_figcaption = False
        self.in_pre = False
        self.in_code = False
        self.in_s = False
        self.heading_level = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_level = int(tag[1])
            self.output.append("\n" + "#" * self.heading_level + " ")
        elif tag == "p":
            # Suppress <p> inside <li> to avoid extra newlines in list items
            if not self.in_li:
                self.output.append("\n")
        elif tag == "br":
            self.output.append("\n")
        elif tag == "ul":
            self.list_depth += 1
        elif tag == "li":
            self.in_li = True
            self.li_has_content = False
            indent = "  " * (self.list_depth - 1)
            self.output.append(f"\n{indent}- ")
        elif tag == "a":
            self.in_a = True
            self.href = attrs_dict.get("href", "")
            self.output.append("[")
        elif tag == "strong":
            self.in_strong = True
            self.output.append("**")
        elif tag == "blockquote":
            self.in_blockquote = True
            self.output.append("\n> ")
        elif tag == "figure":
            pass
        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "")
            if src:
                self.output.append(f"\n![{alt}]({src})\n")
        elif tag == "figcaption":
            self.in_figcaption = True
            self.output.append("*")
        elif tag == "pre":
            self.in_pre = True
            self.output.append("\n```\n")
        elif tag == "code":
            if not self.in_pre:
                self.output.append("`")
            self.in_code = True
        elif tag == "s":
            self.in_s = True
            self.output.append("~~")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.output.append("\n")
            self.heading_level = 0
        elif tag == "p":
            if not self.in_li:
                self.output.append("\n")
        elif tag == "li":
            self.in_li = False
        elif tag == "ul":
            self.list_depth = max(0, self.list_depth - 1)
            if self.list_depth == 0:
                self.output.append("\n")
        elif tag == "a":
            self.in_a = False
            self.output.append(f"]({self.href})")
            self.href = ""
        elif tag == "strong":
            self.in_strong = False
            self.output.append("**")
        elif tag == "blockquote":
            self.in_blockquote = False
            self.output.append("\n")
        elif tag == "figcaption":
            self.in_figcaption = False
            self.output.append("*\n")
        elif tag == "pre":
            self.in_pre = False
            self.output.append("\n```\n")
        elif tag == "code":
            self.in_code = False
            if not self.in_pre:
                self.output.append("`")
        elif tag == "s":
            self.in_s = False
            self.output.append("~~")

    def handle_data(self, data):
        if self.in_blockquote:
            data = data.replace("\n", "\n> ")
        self.output.append(data)

    def get_markdown(self):
        text = "".join(self.output)
        # Clean up excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html_text):
    if not html_text:
        return ""
    parser = HTMLToMarkdown()
    parser.feed(html_text)
    return parser.get_markdown()


def extract_slug(link):
    """Extract note ID from URL like https://note.com/workhack20/n/n15fd69d626b1."""
    if link:
        m = re.search(r"/n/(\w+)$", link)
        if m:
            return m.group(1)
    return None


def parse_date(date_str):
    """Parse WXR date string like 'Sat, 14 Sep 2024 06:48:52 +0900'."""
    if not date_str:
        return None
    try:
        # Remove timezone for simplicity
        clean = re.sub(r"\s+[+-]\d{4}$", "", date_str)
        return datetime.strptime(clean, "%a, %d %b %Y %H:%M:%S")
    except ValueError:
        return None


def main():
    tree = ET.parse(INPUT_XML)
    root = tree.getroot()
    channel = root.find("channel")
    items = channel.findall("item")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # First pass: build slug-to-(filename, title) mapping
    article_map = {}  # note_id -> (filename, title)
    articles = []
    for i, item in enumerate(items):
        title = item.find("title").text or "(無題)"
        link = item.find("link").text or ""
        pub_date_str = item.find("pubDate").text or ""
        content_el = item.find("content:encoded", NS)
        html_content = content_el.text if content_el is not None else ""

        dt = parse_date(pub_date_str)
        date_str = dt.strftime("%Y-%m-%d") if dt else ""

        num = str(i + 1).zfill(3)
        slug = extract_slug(link) or f"article{num}"
        filename = f"{num}_{slug}.md"

        if slug:
            article_map[slug] = (filename, title)

        articles.append((title, link, date_str, html_content, filename))

    index_entries = []

    for title, link, date_str, html_content, filename in articles:
        markdown_body = html_to_markdown(html_content)

        # Replace internal note.com links with local file links
        def replace_internal_link(m):
            note_id = m.group(1)
            if note_id in article_map:
                local_filename, local_title = article_map[note_id]
                return f"[{local_title}]({local_filename})"
            return m.group(0)

        markdown_body = re.sub(
            r"\[(?:[^\]]*)\]\(https://note\.com/workhack20/n/(\w+)\)",
            replace_internal_link,
            markdown_body,
        )

        # Build frontmatter
        safe_title = title.replace('"', '\\"')
        frontmatter = f'---\ntitle: "{safe_title}"\nurl: {link}\ndate: {date_str}\n---\n'

        full_content = frontmatter + "\n" + markdown_body + "\n"

        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_content)

        num = filename[:3]
        index_entries.append((num, title, date_str, filename))

    # Write index file
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write("# 仕事術2.0 記事一覧\n\n")
        f.write(f"全 {len(index_entries)} 記事\n\n")
        f.write("| # | タイトル | 日付 |\n")
        f.write("|---|---------|------|\n")
        for num, title, date_str, filename in index_entries:
            f.write(f"| {num} | [{title}](articles/{filename}) | {date_str} |\n")

    print(f"Converted {len(index_entries)} articles to {OUTPUT_DIR}/")
    print(f"Index written to {INDEX_FILE}")


if __name__ == "__main__":
    main()
