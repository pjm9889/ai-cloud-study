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

OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "static" / "css").mkdir(parents=True, exist_ok=True)
shutil.copy2(BASE_DIR / "static" / "css" / "site.css", OUTPUT_DIR / "static" / "css" / "site.css")

for template_name, output_name, page_title in (
    ("home.html", "index.html", "메인"),
    ("guide.html", "guide.html", "프로젝트가이드"),
):
    html = env.get_template(template_name).render(site=site, page_title=page_title)
    html = html.replace('href="/guide"', 'href="guide.html"')
    (OUTPUT_DIR / output_name).write_text(html, encoding="utf-8")

