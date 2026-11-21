"""Collecteur de la veille de Luke.

Lit les flux RSS/Atom et les flux des chaînes YouTube listés dans sources.json,
garde uniquement ce qui est nouveau depuis le dernier passage, et écrit un
digest compact (digest/latest.md) que la veille Claude lit chaque matin.
Tourne dans une GitHub Action : aucun token Claude n'est consommé ici.
"""
import datetime as dt
import html
import json
import re
import time
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).parent
STATE = ROOT / "state"
DIGEST = ROOT / "digest"
UA = "Mozilla/5.0 (veille-feeds; +https://github.com) feedparser"
NOW = dt.datetime.now(dt.timezone.utc)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def clean(text, limit):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def entry_date(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
    return None


def resolve_channel(handle, cache):
    """@handle -> (channel_id, titre). Résultat mis en cache dans state/channels.json."""
    if handle in cache:
        return cache[handle]
    r = requests.get(f"https://www.youtube.com/{handle}", headers={"User-Agent": UA,
                     "Accept-Language": "en"}, cookies={"CONSENT": "YES+1"}, timeout=20)
    r.raise_for_status()
    m = (re.search(r'"externalId":"(UC[\w-]{22})"', r.text)
         or re.search(r'youtube\.com/channel/(UC[\w-]{22})', r.text))
    if not m:
        raise ValueError("channel_id introuvable sur la page")
    t = re.search(r'<meta property="og:title" content="([^"]*)"', r.text)
    cache[handle] = [m.group(1), html.unescape(t.group(1)) if t else handle]
    return cache[handle]


def fetch(url, tries=3):
    for attempt in range(tries):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
            time.sleep(10 * (attempt + 1))  # erreur temporaire : on réessaie
            continue
        break
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"flux illisible : {feed.bozo_exception}")
    return feed


def main():
    cfg = load_json(ROOT / "sources.json", {})
    lim = cfg.get("limits", {})
    max_items = lim.get("max_items_per_feed", 8)
    sum_chars = lim.get("summary_chars", 220)
    keep_days = lim.get("seen_keep_days", 90)

    seen = load_json(STATE / "seen.json", {})
    channels = load_json(STATE / "channels.json", {})
    last = load_json(STATE / "last_run.json", {}).get("at")
    since = dt.datetime.fromisoformat(last) if last else NOW - dt.timedelta(hours=48)

    jobs = [dict(s, type="rss") for s in cfg.get("rss", [])]
    jobs += [dict(s, type="youtube", kind="fait") for s in cfg.get("youtube", [])]

    items, status = [], []
    for s in jobs:
        label = s["name"] + (" (YouTube)" if s["type"] == "youtube" else "")
        try:
            if s["type"] == "youtube":
                cid, title = resolve_channel(s["handle"], channels)
                label = f"{s['name']} (YouTube : {title})"
                url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
            else:
                url = s["url"]
            feed = fetch(url)
            new = 0
            for e in feed.entries:
                key = e.get("id") or e.get("link")
                d = entry_date(e)
                if not key or key in seen or (d and d < since):
                    continue
                kw = s.get("keywords")
                if kw:  # gros sites d'actu : on ne garde que ce qui touche le domaine
                    blob = (e.get("title", "") + " " + (e.get("summary") or "")).lower()
                    if not any(k.lower() in blob for k in kw):
                        seen[key] = NOW.isoformat()
                        continue
                seen[key] = NOW.isoformat()
                if new >= max_items:
                    continue  # marqué vu, mais pas affiché : évite d'inonder le digest
                new += 1
                summary = e.get("summary") or (e.get("media_description") if s["type"] == "youtube" else "")
                items.append({
                    "cat": s["cat"], "kind": s.get("kind", "fait"), "src": label,
                    "date": d.strftime("%Y-%m-%d") if d else "?",
                    "title": clean(e.get("title"), 160), "link": e.get("link", ""),
                    "summary": clean(summary, sum_chars),
                })
            status.append((label, "OK", len(feed.entries), new))
        except Exception as exc:  # un flux cassé ne doit pas bloquer les autres
            status.append((label, f"ERREUR : {clean(str(exc), 120)}", 0, 0))

    # Purge des anciens identifiants vus
    cutoff = NOW - dt.timedelta(days=keep_days)
    seen = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v) >= cutoff}

    # Digest compact, groupé par catégorie
    ok = sum(1 for s in status if s[1] == "OK")
    lines = [f"# Digest veille — {NOW:%Y-%m-%d %H:%M} UTC (nouveautés depuis {since:%Y-%m-%d %H:%M} UTC)",
             f"{len(items)} nouveaux éléments · {ok}/{len(status)} flux OK (détail : digest/status.md)", ""]
    for cat in sorted({i["cat"] for i in items}):
        lines.append(f"## {cat}")
        for i in sorted((i for i in items if i["cat"] == cat), key=lambda i: i["date"], reverse=True):
            lines.append(f"- [{i['kind']}] {i['src']} · {i['date']} · **{i['title']}** — {i['summary']} <{i['link']}>")
        lines.append("")
    if not items:
        lines.append("Aucune nouveauté dans les flux.")
    DIGEST.mkdir(exist_ok=True)
    text = "\n".join(lines) + "\n"
    (DIGEST / "latest.md").write_text(text, encoding="utf-8")
    archive = DIGEST / "archive"
    archive.mkdir(exist_ok=True)
    (archive / f"{NOW:%Y-%m-%d}.md").write_text(text, encoding="utf-8")
    for old in sorted(archive.glob("*.md"))[:-14]:
        old.unlink()

    st = ["# État des flux", f"Run : {NOW:%Y-%m-%d %H:%M} UTC", "",
          "| Flux | État | Entrées dans le flux | Nouveaux |", "| --- | --- | --- | --- |"]
    st += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in status]
    (DIGEST / "status.md").write_text("\n".join(st) + "\n", encoding="utf-8")

    save_json(STATE / "seen.json", seen)
    save_json(STATE / "channels.json", channels)
    save_json(STATE / "last_run.json", {"at": NOW.isoformat()})
    print(text)
    print("\n".join(st))


if __name__ == "__main__":
    main()
