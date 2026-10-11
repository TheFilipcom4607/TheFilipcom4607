"""Render the profile cards from content.json and write ../README.md.

    python3 render.py

Every card is rendered dark and light, at desktop size and (except buttons) at a
phone size, as WebP into ../cards/. The README picks one with <picture>: the
viewer's GitHub theme, and the -sm variant when the window is phone-narrow.
"""
import html
import io
import json
import pathlib
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CARDS = ROOT / "cards"
THEMES = ("dark", "light")
# suffix, cards.html size class, device scale, gutter between paired cards, extra px under them
VARIANTS = (
    ("", "", 2, 12, 6),
    ("-sm", "sm", 3, 6, 1),
)
NARROW = "(max-width: 600px)"


def pair_side(data):
    """0 for the left card of a pair, 1 for the right, by output name."""
    return {item["out"]: i % 2 for g in ("projects", "contribs", "minis") for i, item in enumerate(data[g])}


def save(png, path, side, scale, gutter, row_gap):
    """Bake half the gutter into paired cards so a pair is exactly 100% wide, then write WebP."""
    im = Image.open(io.BytesIO(png))
    if side is not None:
        g, b = gutter // 2 * scale, row_gap * scale
        out = Image.new("RGBA", (im.width + g, im.height + b), (0, 0, 0, 0))
        out.paste(im, (g * side, 0))
        im = out
    im.save(path, quality=90, method=6)


def render(data):
    CARDS.mkdir(exist_ok=True)
    sides = pair_side(data)
    written = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for suffix, size, scale, gutter, row_gap in VARIANTS:
            page = browser.new_page(viewport={"width": 960, "height": 900}, device_scale_factor=scale)
            page.goto((HERE / "cards.html").as_uri(), wait_until="networkidle")
            for theme in THEMES:
                page.evaluate("([d, t, s]) => build(d, t, s)", [data, theme, size])
                page.evaluate("document.fonts.ready")
                page.evaluate(
                    "Promise.all([...document.images].map(i => i.complete ? 0 :"
                    " new Promise(r => i.onload = i.onerror = r)))"
                )
                broken = page.evaluate("[...document.images].filter(i => !i.naturalWidth).map(i => i.src)")
                if broken:
                    sys.exit(f"images failed to load (try again): {broken}")
                page.evaluate("equalize()")
                for el in page.query_selector_all("[data-out]"):
                    name = el.get_attribute("data-out")
                    path = CARDS / f"{name}-{theme}{suffix}.webp"
                    save(el.screenshot(omit_background=True), path, sides.get(name), scale, gutter, row_gap)
                    written.add(path)
                print(f"rendered {theme}{suffix}")
            page.close()
        browser.close()
    for stale in set(CARDS.iterdir()) - written:
        stale.unlink()


def pic(name, alt, size, phone=True):
    """A theme-aware image. size is an <img> attribute string like 'width="50%"'.

    The phone sources write "prefers-color-scheme:dark" without the space on purpose:
    GitHub's <themed-picture> rewrites the whole media query of any source matching
    "prefers-color-scheme: dark" to follow the GitHub theme setting, which would drop
    the width check and show phone cards on desktop. Without the space it leaves them
    alone, so phone cards follow the OS theme instead.
    """
    src = lambda theme, suffix="": f"cards/{name}-{theme}{suffix}.webp"
    sources = ""
    if phone:
        sources += (
            f'<source media="{NARROW} and (prefers-color-scheme:dark)" srcset="{src("dark", "-sm")}">'
            f'<source media="{NARROW}" srcset="{src("light", "-sm")}">'
        )
    return (
        f'<picture>{sources}<source media="(prefers-color-scheme: dark)" srcset="{src("dark")}">'
        f'<img src="{src("light")}" alt="{html.escape(alt)}" {size}></picture>'
    )


def link(href, inner):
    return f'<a href="{html.escape(href)}">{inner}</a>'


def buttons(items):
    return "\n".join(link(b["link"], pic(b["out"], b["text"], 'height="40"', phone=False)) for b in items)


def pairs(cells):
    """Two cards per line. No whitespace between them: the gutter is baked into the images."""
    rows = ["".join(cells[i:i + 2]) for i in range(0, len(cells), 2)]
    return "<p>\n" + "<br>\n".join(rows) + "\n</p>"


def strip_tags(s):
    return s.replace("<code>", "").replace("</code>", "")


def readme(d):
    H, F = d["hero"], d["featured"]
    hero_alt = f'{H["title"]} {H["subtitle"]} {H["text"]}'
    heading = lambda k: pic(f"h-{k}", d["headings"][k]["title"], 'width="100%"')

    projects = [
        link(p["link"], pic(p["out"], f'{p["name"]} ({p["platform"]}): {p["desc"]}', 'width="50%"'))
        for p in d["projects"]
    ]
    contribs = [
        link(c["link"], pic(c["out"], f'{c["owner"]}/{c["repo"]}: {strip_tags(c["what"])}', 'width="50%"'))
        for c in d["contribs"]
    ]
    minis = [
        link(m["link"], pic(m["out"], f'{m["name"]}: {m["desc"]}', 'width="50%"'))
        for m in d["minis"]
    ]

    parts = [
        link(H["link"], pic("hero", hero_alt, 'width="100%"')),
        "<p>\n" + buttons(d["heroButtons"]) + "\n</p>",
        "<br>",
        heading("made"),
        link(F["link"], pic(F["out"], f'{F["name"]} ({F["platform"]}): {F["desc"]}', 'width="100%"')),
        "<p>\n" + buttons(F["buttons"]) + "\n</p>",
        pairs(projects),
        "<br>",
        heading("oss"),
        pairs(contribs),
        "<br>",
        heading("also"),
        pairs(minis),
        "<br>",
        '<p align="center">\n' + buttons([d["more"]]) + "\n</p>",
    ]
    return "<!-- Generated by build/render.py from build/content.json. Edit those, not this. -->\n\n" + "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    data = json.loads((HERE / "content.json").read_text())
    if "--readme-only" not in sys.argv:
        render(data)
    (ROOT / "README.md").write_text(readme(data))
    print("wrote README.md")
