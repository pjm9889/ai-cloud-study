import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "public"

with (BASE_DIR / "data" / "site.json").open(encoding="utf-8") as file:
    site = json.load(file)

env = Environment(loader=FileSystemLoader(BASE_DIR / "templates"))
env.globals["url_for"] = lambda endpoint, **kwargs: "/static/css/site.css"
css = (BASE_DIR / "static" / "css" / "site.css").read_text(encoding="utf-8")

OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "static" / "css").mkdir(parents=True, exist_ok=True)
shutil.copy2(BASE_DIR / "static" / "css" / "site.css", OUTPUT_DIR / "static" / "css" / "site.css")

home_html = env.get_template("home.html").render(site=site, page_title="메인")
guide_html = env.get_template("guide.html").render(site=site, page_title="프로젝트가이드")
home_html = home_html.replace('href="/guide"', 'href="guide.html"')
home_html = home_html.replace('<link rel="stylesheet" href="/static/css/site.css" />', f"<style>\n{css}\n</style>")
(OUTPUT_DIR / "index.html").write_text(home_html, encoding="utf-8")
(OUTPUT_DIR / "guide.html").write_text(guide_html.replace('<link rel="stylesheet" href="/static/css/site.css" />', f"<style>\n{css}\n</style>"), encoding="utf-8")

