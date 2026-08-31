"""
One-profile diagnostic.

Answers the question a failed launch cannot: *where* did it go wrong — the
session, the transport, the render, the wall detector, or the extractors. Prints
what each layer actually produced, so a failure has a location rather than a
verdict.

    python -m phantom.doctor https://www.linkedin.com/in/<slug>/
    python -m phantom.doctor <url> --no-session --save page.html
    python -m phantom.doctor <url> --headless        # more detectable; for CI

Authentication comes from the persistent browser profile, so there is nothing to
pass and no secret on the command line. Sign in first with
`python -m phantom.session login`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from . import session as browser_session
from .scraper import dom_profile, voyager
from .scraper.engine import _rejection_reason, normalise_url, parse_html
from .scraper.fetcher import authwall_reason, fetch
from .scraper.mapper import build_row

TICK, CROSS, DASH = "PASS", "FAIL", "  — "


def _line(label: str, value: object) -> None:
    print(f"  {label:<22} {value}")


def _section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _outline(soup) -> None:
    """
    Describe the DOM that actually arrived.

    When every known selector misses, there are two possibilities with opposite
    fixes: the markup changed, or nothing rendered. Guessing between them costs a
    round trip each time, so measure instead — count the containers, list the
    headings and ids the page really has, and show whether there is human text in
    there at all.
    """
    from collections import Counter

    _section("DOM outline")

    body = soup.body or soup
    tags = Counter(tag.name for tag in body.find_all(True))
    _line("total elements", sum(tags.values()))
    _line("tag histogram", ", ".join(f"{name}×{n}" for name, n in tags.most_common(12)))

    scripts = body.find_all("script")
    script_bytes = sum(len(s.get_text() or "") for s in scripts)
    _line("script bytes", f"{script_bytes:,}")

    text = body.get_text(" ", strip=True)
    _line("visible text chars", f"{len(text):,}")
    if text:
        _line("first 160 chars", text[:160])

    headings = [
        (tag.name, _clean_text(tag.get_text()))
        for tag in body.find_all(["h1", "h2", "h3"])
        if _clean_text(tag.get_text())
    ]
    _line("headings", len(headings))
    for name, value in headings[:12]:
        _line(f"  {name}", value[:80])

    ids = [node.get("id") for node in body.find_all(id=True)]
    _line("elements with id", len(ids))
    for value in ids[:20]:
        _line("  #", value[:70])

    sections = body.find_all("section")
    _line("<section> count", len(sections))
    for index, node in enumerate(sections[:8]):
        label = node.get("id") or " ".join(node.get("class") or [])[:50] or "—"
        snippet = _clean_text(node.get_text(" ", strip=True))[:60]
        _line(f"  section {index}", f"{label} :: {snippet}")

    _line("mentions shadowRoot", "shadowRoot" in str(soup)[:200_000])


def _emit_record(
    row: dict[str, object], provenance: dict[str, str], destination: Path | None
) -> None:
    """
    The complete extracted record, as JSON.

    The `*_json` columns are stored as strings so a CSV cell can hold them; here
    they are expanded back into real objects, because the point of this mode is
    to read the data rather than to round-trip it. Provenance rides alongside,
    so an empty column can be told apart from one a guess filled.
    """
    import json

    expanded: dict[str, object] = {}
    for key, value in row.items():
        if key.endswith("_json") and isinstance(value, str) and value:
            try:
                expanded[key] = json.loads(value)
                continue
            except ValueError:
                pass
        expanded[key] = value

    document = {
        "record": expanded,
        "provenance": provenance,
        "empty_columns": sorted(
            key for key, value in row.items() if value in (None, "", [], {})
        ),
    }
    text = json.dumps(document, indent=2, ensure_ascii=False, default=str)

    if destination:
        destination.write_text(text, encoding="utf-8")
        print(f"\nwrote {destination} ({len(text):,} bytes)")
    else:
        print(text)


def _clean_text(value: str | None) -> str:
    import re as _re

    return _re.sub(r"\s+", " ", value or "").strip()


def diagnose(
    raw_url: str,
    use_session: bool,
    headless: bool,
    save: Path | None,
    outline: bool = False,
    detail_sections: tuple[str, ...] = (),
    as_json: bool = False,
    json_out: Path | None = None,
    save_details: Path | None = None,
    outline_detail: str | None = None,
) -> int:
    _section("Input")
    try:
        url = normalise_url(raw_url)
    except ValueError as exc:
        print(f"  {CROSS}  {exc}")
        return 2
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    _line("canonical url", url)
    _line("slug", slug)
    state = browser_session.status()
    _line("browser profile", state.summary)

    from . import browser as browser_config

    report = browser_config.environment_report()
    _line("browser", report["summary"])
    if report["headless"]:
        _line("  note", "headless is more detectable — prefer Xvfb + headed on a server")
    if not report["xvfb_available"] and report["headless"]:
        _line("  xvfb", "not installed (apt install xvfb) — headed would need it here")

    _section("Fetch")
    try:
        page = fetch(
            url,
            use_session=use_session,
            headless=headless,
            detail_sections=detail_sections,
        )
    except Exception as exc:
        print(f"  {CROSS}  fetch raised: {exc}")
        return 2

    result = page.result
    diag = page.diagnostics

    _line("transport", result.transport)
    _line("http status", result.status)
    _line("final url", result.final_url)
    _line("bytes", f"{len(result.html):,}")
    _line("page title", diag.get("title") or "—")
    _line("first h1", diag.get("h1") or "—")
    if diag.get("networkidle"):
        _line("networkidle", diag["networkidle"])

    if save:
        save.write_text(result.html, encoding="utf-8")
        _line("saved html", save)

    _section("Session evidence")
    cookies = diag.get("cookies") or []
    _line("cookies after load", ", ".join(cookies) if cookies else "—")
    _line("signed in", diag.get("signed_in", "—"))
    _line("render wait", diag.get("render") or "—")
    _line("lazy sections seen", diag.get("lazy_sections") or "—")
    _line("profile body rendered", diag.get("rendered"))
    for probe in ("has_authwall", "has_challenge", "has_captcha", "has_perimeterx", "has_json_ld"):
        if probe in diag:
            _line(probe, diag[probe])

    if detail_sections:
        _section("Detail pages")
        notes = diag.get("details") or {}
        for name in detail_sections:
            _line(name, notes.get(name, "not fetched"))

        if save_details:
            save_details.mkdir(parents=True, exist_ok=True)
            for name, detail_html in page.details.items():
                target = save_details / f"{name.replace(' ', '-').replace('&', 'and')}.html"
                target.write_text(detail_html, encoding="utf-8")
                _line(f"  saved {name}", target)

    if outline_detail:
        detail_html = page.details.get(outline_detail)
        if detail_html is None:
            _section(f"Detail outline: {outline_detail}")
            print(f"  {CROSS}  that page was not fetched")
        else:
            _section(f"Detail outline: {outline_detail}")
            _outline(BeautifulSoup(detail_html, "lxml"))

    _section("Wall detection")
    legacy = result.blocked
    verdict = authwall_reason(result, slug, diag.get("rendered"))
    _line("marker sniff (legacy)", "blocked" if legacy else "clean")
    _line("evidence check", verdict or "clean")
    if legacy and not verdict:
        print(
            f"  {DASH}the page contains authwall marker strings but is a real "
            "signed-in render.\n     This is exactly the false positive the "
            "evidence check exists to stop."
        )
    if verdict:
        print(f"  {CROSS}  {verdict}")

    _section("Rendered DOM")
    soup = BeautifulSoup(result.html, "lxml")
    _line("looks rendered", dom_profile.looks_rendered(soup))
    for anchor in ("about", "experience", "education", "skills"):
        node = soup.find(id=anchor)
        _line(f"  #{anchor} section", "present" if node is not None else "absent")
    legacy_entities = voyager.collect_entities(soup)
    _line("embedded model store", f"{len(legacy_entities)} entities (legacy shape)")

    headings = dom_profile.sections_by_heading(soup)
    _line("sections by heading", len(headings))
    for name in ("about", "experience", "education", "skills", "activity"):
        section = headings.get(name)
        if section is None:
            _line(f"  {name}", "not found")
            continue
        rows = [li for li in section.select("li") if li.find_parent("li") is None]
        _line(f"  {name}", f"found, {len(rows)} row(s)")
    other = [key for key in headings if key not in
             {"about", "experience", "education", "skills", "activity"}]
    if other:
        _line("  other headings", ", ".join(sorted(other)[:10]))

    if outline:
        _outline(soup)

    _section("Extraction")
    profile, voyager_fields = parse_html(url, result.html, slug)
    for name, detail_html in page.details.items():
        try:
            voyager_fields.update(dom_profile.parse_detail(detail_html, name))
        except Exception as exc:
            _line(f"  {name} parse failed", type(exc).__name__)
    _line("dom fields", len(voyager_fields))
    _line("public name", profile.name or "—")
    _line("public headline", (profile.headline or "—")[:60])

    row, provenance = build_row(input_url=url, profile=profile, voyager=voyager_fields)
    filled = {k: v for k, v in row.items() if v not in (None, "", [], {})}
    _line("columns filled", f"{len(filled)} / {len(row)}")

    if as_json or json_out:
        _emit_record(row, provenance, json_out)
        if as_json and not json_out:
            return 0 if not _rejection_reason(result, row, diag.get("rendered")) else 1

    by_layer: dict[str, int] = {}
    for source in provenance.values():
        by_layer[source] = by_layer.get(source, 0) + 1
    for layer, count in sorted(by_layer.items(), key=lambda kv: -kv[1]):
        _line(f"  from {layer}", count)

    _section("Verdict")
    reason = _rejection_reason(result, row, diag.get("rendered"))
    if reason:
        print(f"  {CROSS}  rejected: {reason}")
        return 1

    print(f"  {TICK}  usable profile")
    for key in (
        "scraper_full_name",
        "linkedin_headline",
        "company_name",
        "linkedin_job_title",
        "location",
        "linkedin_connections_count",
        "connection_degree",
        "linkedin_profile_image_url",
        "linkedin_background_image_url",
        "linkedin_top_skills",
    ):
        value = row.get(key)
        _line(key, (str(value)[:100] if value else "—"))

    about = row.get("linkedin_about")
    _line("linkedin_about", f"{len(about)} chars" if about else "—")

    _section("Sections captured")
    import json as _json

    for label, column in (
        ("experience", "linkedin_experience_json"),
        ("education", "linkedin_education_json"),
        ("certifications", "linkedin_certifications_json"),
        ("projects", "linkedin_projects_json"),
        ("languages", "linkedin_languages_json"),
        ("skills", "linkedin_skills_json"),
    ):
        raw = row.get(column)
        if not raw:
            _line(label, "—")
            continue
        try:
            entries = _json.loads(raw)
        except ValueError:
            _line(label, "unparseable")
            continue
        first = entries[0] if entries else None
        if isinstance(first, dict):
            summary = first.get("title") or first.get("name") or first.get("school") or ""
        else:
            summary = str(first or "")
        _line(label, f"{len(entries)} entry(s)  e.g. {summary[:60]}")

    claimed = row.get("linkedin_skills_count")
    if claimed:
        try:
            read = len(_json.loads(row.get("linkedin_skills_json") or "[]"))
        except ValueError:
            read = 0
        note = "" if read >= claimed else "  <- incomplete; try --deep"
        _line("skills claimed/read", f"{claimed} / {read}{note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m phantom.doctor",
        description="Diagnose a single profile scrape, layer by layer.",
    )
    parser.add_argument("url", help="LinkedIn profile URL or bare slug")
    parser.add_argument(
        "--no-session",
        action="store_true",
        help="ignore the stored browser profile and run the logged-out path",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run the session browser headless (more detectable; default is headed)",
    )
    parser.add_argument("--save", type=Path, help="write the fetched HTML to this file")
    parser.add_argument(
        "--outline",
        action="store_true",
        help="describe the DOM that actually arrived: tags, headings, ids, text volume",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help=(
            "also visit each section's 'Show all' page — the only way to get every "
            "skill, role, and certificate. Costs one extra page view per section"
        ),
    )
    parser.add_argument(
        "--sections",
        default="skills,experience,education,licenses & certifications,projects,languages",
        help="comma-separated sections for --deep",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="print the complete extracted record as JSON instead of the summary",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="write the complete record to a file (implies --json)",
    )
    parser.add_argument(
        "--save-details",
        type=Path,
        help="write each fetched detail page's HTML into this directory",
    )
    parser.add_argument(
        "--outline-detail",
        metavar="SECTION",
        help="print the DOM outline of one detail page, e.g. --outline-detail skills",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
    )

    use_session = not args.no_session
    if use_session and not browser_session.can_authenticate():
        print(
            "No signed-in session yet. Either:\n"
            "    python -m phantom.session login        (a machine with a screen)\n"
            "    paste a cookie set in the UI           (Connect to LinkedIn)\n"
            "Or pass --no-session to test the logged-out path.",
            file=sys.stderr,
        )
        return 2

    sections: tuple[str, ...] = ()
    if args.deep:
        sections = tuple(
            part.strip().lower() for part in args.sections.split(",") if part.strip()
        )
    if args.outline_detail:
        section = args.outline_detail.strip().lower()
        if section not in sections:
            sections = sections + (section,)

    return diagnose(
        args.url,
        use_session,
        headless=args.headless,
        save=args.save,
        outline=args.outline,
        detail_sections=sections,
        as_json=args.as_json or bool(args.json_out),
        json_out=args.json_out,
        save_details=args.save_details,
        outline_detail=args.outline_detail,
    )


if __name__ == "__main__":
    raise SystemExit(main())
