#!/usr/bin/env python3
"""
Sync Beyblade X part images from the Beyblade Wiki (Fandom) into this repo.

Source pages (MediaWiki parse API):
  - List_of_Basic_Line_parts   -> BX
  - List_of_Unique_Line_parts  -> UX
  - List_of_Custom_Line_parts  -> CX

For every row in every part table it:
  1. Resolves the original file URL + SHA-1 via the imageinfo API.
  2. Builds a deterministic path using the naming convention (see README).
  3. Downloads the original (no re-encoding), verifies SHA-1, writes atomically.
  4. Writes manifest.json and CATALOG.md.

Idempotent: files whose SHA-1 already matches are skipped. Never deletes files;
orphans (files no longer referenced) are only reported.

Usage:
  python scripts/sync_parts.py                 # full sync
  python scripts/sync_parts.py --dry-run       # plan only, no downloads
  python scripts/sync_parts.py --html-dir DIR  # offline: read <Page>.html fixtures
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

API = "https://beyblade.fandom.com/api.php"
WIKI = "https://beyblade.fandom.com/wiki/"
UA = "beyblade-x-parts-sync/1.0 (+https://github.com; fan archive bot)"
ROOT = Path(__file__).resolve().parent.parent
IMG_ROOT = ROOT / "images"

LINES = {
    "List_of_Basic_Line_parts": ("bx", "bx-basic-line", "Basic Line (BX)"),
    "List_of_Unique_Line_parts": ("ux", "ux-unique-line", "Unique Line (UX)"),
    "List_of_Custom_Line_parts": ("cx", "cx-custom-line", "Custom Line (CX)"),
}

# Section heading on the wiki -> (singular slug used in filenames, folder name)
PART_TYPES = {
    "Blades": ("blade", "blades"),
    "Ratchets": ("ratchet", "ratchets"),
    "Bits": ("bit", "bits"),
    "Lock Chips": ("lock-chip", "lock-chips"),
    "Main Blades": ("main-blade", "main-blades"),
    "Assist Blades": ("assist-blade", "assist-blades"),
    "Metal Blades": ("metal-blade", "metal-blades"),
    "Over Blades": ("over-blade", "over-blades"),
    "Ratchet-Integrated Blades": ("ratchet-integrated-blade", "ratchet-integrated-blades"),
    "Ratchet-Integrated Bits": ("ratchet-integrated-bit", "ratchet-integrated-bits"),
}

# Blade sub-sections -> sub-folder
SUBSECTIONS = {
    "Hasbro Debut": "hasbro-debut",
    "Expand Blades": "expand",
    "X-Over Project": "x-over",
    "Collabs": "collab",
}

# Wiki file-name prefixes that indicate an isolated part render.
# Anything else (e.g. "Bite_Croc_3-60LF.jpeg") is a full assembled Bey photo.
PART_FILE_PREFIXES = (
    "Blade", "Ratchet", "Bit", "LockChip", "MainBlade", "AssistBlade",
    "MetalBlade", "OverBlade",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def slugify(text: str) -> str:
    """CamelCase / free text -> lowercase kebab-case ASCII."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)      # DranSword -> Dran-Sword
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)    # LDrago edge cases
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def is_na(v: str | None) -> bool:
    return not v or v.strip().upper() in {"N/A", "NA", "-", "—"}


def http_get(url: str, *, retries: int = 4, timeout: int = 60) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")


def api(params: dict) -> dict:
    params = {**params, "format": "json"}
    return json.loads(http_get(API + "?" + urllib.parse.urlencode(params)))


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def fetch_page_html(page: str, html_dir: Path | None) -> str:
    if html_dir:
        return (html_dir / f"{page}.html").read_text(encoding="utf-8")
    return api({"action": "parse", "page": page, "prop": "text"})["parse"]["text"]["*"]


def parse_page(page: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    h2 = h3 = ""
    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name == "h2":
            h2 = el.get_text(" ", strip=True).replace("[ ]", "").replace("[]", "").strip()
            h3 = ""
            continue
        if el.name in ("h3", "h4"):
            h3 = el.get_text(" ", strip=True).replace("[ ]", "").replace("[]", "").strip()
            continue
        if "wikitable" not in (el.get("class") or []):
            continue
        trs = el.find_all("tr")
        if not trs:
            continue
        header = [c.get_text(strip=True) for c in trs[0].find_all(["th", "td"])]
        group = ""
        for tr in trs[1:]:
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) == 1:                      # group row, e.g. "Marvel"
                group = cells[0].get_text(strip=True)
                continue
            rec = {"page": page, "section": h2, "subsection": h3, "group": group,
                   "images": [], "wiki_path": None}
            for i, c in enumerate(cells):
                key = header[i] if i < len(header) else f"c{i}"
                for img in c.find_all("img"):
                    k = img.get("data-image-key") or img.get("data-image-name")
                    if k:
                        rec["images"].append(urllib.parse.unquote(k).replace(" ", "_"))
                a = c.find("a", href=re.compile(r"^/wiki/(?!File:)"))
                if a and not rec["wiki_path"]:
                    rec["wiki_path"] = a["href"][len("/wiki/"):]
                txt = c.get_text(" ", strip=True)
                if txt:
                    rec[key] = txt
            rows.append(rec)
    return rows


# --------------------------------------------------------------------------- #
# Naming convention
# --------------------------------------------------------------------------- #
def part_slug(rec: dict, type_slug: str) -> str:
    abbr = rec.get("Abbr.", "")
    name = rec.get("Name", "")
    tt = rec.get("Takara Tomy Name", "")
    hb = rec.get("Hasbro Name", "")
    if abbr:
        # Ratchets: "3-60" is already the canonical id; bits/assist blades: "gf-gear-flat"
        if re.fullmatch(r"\d+-\d+", abbr):
            return slugify(abbr)
        return slugify(f"{abbr}-{name}") if name else slugify(abbr)
    if not is_na(tt):
        return slugify(re.sub(r"\(.*?\)", "", tt))
    if not is_na(hb):
        return slugify(hb)
    if name:
        return slugify(name)
    raise ValueError(f"Cannot derive slug for {rec}")


def variant_of(image_key: str) -> str | None:
    m = re.search(r"\(([^)]+)\)", image_key)
    return slugify(m.group(1)) if m else None


def build_plan(rows: list[dict], info: dict[str, dict]) -> list[dict]:
    plan = []
    for rec in rows:
        line_code, line_dir, line_label = LINES[rec["page"]]
        if rec["section"] not in PART_TYPES:
            print(f"WARN unknown section '{rec['section']}' on {rec['page']}", file=sys.stderr)
            type_slug, type_dir = slugify(rec["section"]).rstrip("s"), slugify(rec["section"])
        else:
            type_slug, type_dir = PART_TYPES[rec["section"]]
        slug = part_slug(rec, type_slug)

        sub_parts: list[str] = []
        if rec["subsection"]:
            sub = SUBSECTIONS.get(rec["subsection"], slugify(rec["subsection"]))
            sub_parts.append(sub)
            if sub == "collab" and rec["group"]:
                sub_parts.append(slugify(rec["group"]))
                slug = f"{slugify(rec['group'])}-{slug}"

        base_dir = Path(line_dir, type_dir, *sub_parts)
        entry_common = {
            "line": line_code.upper(),
            "line_name": line_label,
            "part_type": type_slug,
            "category": "/".join(sub_parts) or None,
            "takara_tomy_name": None if is_na(rec.get("Takara Tomy Name")) else rec.get("Takara Tomy Name"),
            "hasbro_name": None if is_na(rec.get("Hasbro Name")) else rec.get("Hasbro Name"),
            "abbr": rec.get("Abbr.") or None,
            "name": rec.get("Name") or None,
            "slug": slug,
            "wiki_url": WIKI + rec["wiki_path"] if rec["wiki_path"] else None,
            "source_list": WIKI + rec["page"],
        }

        if not rec["images"]:
            plan.append({**entry_common, "variant": None, "image_kind": None,
                         "path": None, "source_file": None, "source_url": None,
                         "sha1": None, "bytes": None, "status": "no-image-on-wiki"})
            continue

        multi = len(rec["images"]) > 1
        for idx, key in enumerate(rec["images"], 1):
            meta = info.get(key)
            variant = variant_of(key) or (f"v{idx}" if multi else None)
            kind = "part" if key.startswith(PART_FILE_PREFIXES) else "combo"
            ext = "jpg" if meta and meta["mime"] == "image/jpeg" else (
                meta["mime"].split("/")[-1] if meta else Path(key).suffix.lstrip(".").lower())
            stem = f"{line_code}-{type_slug}-{slug}"
            if variant:
                stem += f"--{variant}"
            if kind == "combo":
                stem += "--combo"
            plan.append({
                **entry_common,
                "variant": variant,
                "image_kind": kind,
                "path": str(Path("images") / base_dir / f"{stem}.{ext}"),
                "source_file": key,
                "source_url": meta["url"] if meta else None,
                "sha1": meta["sha1"] if meta else None,
                "bytes": meta["size"] if meta else None,
                "width": meta["width"] if meta else None,
                "height": meta["height"] if meta else None,
                "status": "ok" if meta else "file-missing-on-wiki",
            })

    # Collision check — fail loudly rather than overwrite silently
    seen: dict[str, dict] = {}
    for e in plan:
        if e["path"] and e["path"] in seen:
            raise SystemExit(f"Naming collision: {e['path']} <- {e['source_file']} vs {seen[e['path']]['source_file']}")
        if e["path"]:
            seen[e["path"]] = e
    return plan


def resolve_images(keys: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(keys), 50):
        batch = keys[i:i + 50]
        j = api({"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|sha1",
                 "titles": "|".join("File:" + k for k in batch)})
        norm = {n["to"]: n["from"] for n in j["query"].get("normalized", [])}
        for p in j["query"]["pages"].values():
            title = norm.get(p["title"], p["title"])
            key = title[len("File:"):].replace(" ", "_")
            ii = (p.get("imageinfo") or [None])[0]
            if ii:
                out[key] = {"url": ii["url"].split("?")[0], "size": ii["size"], "mime": ii["mime"],
                            "sha1": ii["sha1"], "width": ii["width"], "height": ii["height"]}
        time.sleep(0.5)
    return out


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def sha1_file(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def download(plan: list[dict]) -> dict:
    stats = {"downloaded": 0, "unchanged": 0, "failed": 0}
    for e in plan:
        if e["status"] != "ok":
            continue
        dest = ROOT / e["path"]
        if dest.exists() and sha1_file(dest) == e["sha1"]:
            stats["unchanged"] += 1
            continue
        try:
            data = http_get(e["source_url"])
            if hashlib.sha1(data).hexdigest() != e["sha1"]:
                raise ValueError("SHA-1 mismatch")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            stats["downloaded"] += 1
            time.sleep(0.25)  # be polite to the CDN
        except Exception as ex:  # noqa: BLE001
            e["status"] = f"download-failed: {ex}"
            stats["failed"] += 1
            print(f"ERROR {e['path']}: {ex}", file=sys.stderr)
    return stats


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #
def write_catalog(plan: list[dict]) -> None:
    lines = ["# Beyblade X — Parts Catalog", "",
             "_Auto-generated by `scripts/sync_parts.py`. Do not edit by hand._", ""]
    by_line: dict[str, list[dict]] = {}
    for e in plan:
        by_line.setdefault(e["line_name"], []).append(e)
    for line_name, entries in by_line.items():
        lines += [f"## {line_name}", ""]
        by_type: dict[str, list[dict]] = {}
        for e in entries:
            by_type.setdefault(e["part_type"], []).append(e)
        for t, es in by_type.items():
            lines += [f"### {t} ({len(es)})", "",
                      "| Preview | Takara Tomy | Hasbro | Abbr. | Category | File |",
                      "|---|---|---|---|---|---|"]
            for e in es:
                prev = f'<img src="{e["path"]}" width="64">' if e["path"] and e["status"] == "ok" else "—"
                f = f"[`{Path(e['path']).name}`]({e['path']})" if e["path"] else f"_{e['status']}_"
                tt = e["takara_tomy_name"] or e["name"] or "—"
                lines.append(f"| {prev} | {tt} | {e['hasbro_name'] or '—'} | {e['abbr'] or '—'} "
                             f"| {e['category'] or '—'} | {f} |")
            lines.append("")
    (ROOT / "CATALOG.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--html-dir", type=Path, help="offline HTML fixtures (testing)")
    ap.add_argument("--info-json", type=Path, help="offline imageinfo fixture (testing)")
    args = ap.parse_args()

    rows: list[dict] = []
    for page in LINES:
        rows += parse_page(page, fetch_page_html(page, args.html_dir))
    keys = sorted({k for r in rows for k in r["images"]})
    info = json.loads(args.info_json.read_text()) if args.info_json else resolve_images(keys)
    plan = build_plan(rows, info)

    stats = {"parts": len(rows), "images_planned": sum(1 for e in plan if e["path"])}
    if not args.dry_run:
        stats.update(download(plan))
        referenced = {str(ROOT / e["path"]) for e in plan if e["path"]}
        orphans = [str(p.relative_to(ROOT)) for p in IMG_ROOT.rglob("*") if p.is_file() and str(p) not in referenced]
        if orphans:
            print("Orphan files (not deleted):\n  " + "\n  ".join(orphans), file=sys.stderr)
        stats["orphans"] = len(orphans)

    manifest = {
        "source": "Beyblade Wiki (Fandom) — https://beyblade.fandom.com",
        "generated_by": "scripts/sync_parts.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stats": stats,
        "parts": plan,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_catalog(plan)
    print(json.dumps(stats, indent=2))
    return 1 if stats.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
