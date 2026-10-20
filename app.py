import json
from pathlib import Path

from flask import Flask, abort, redirect, render_template


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "site.json"

with DATA_FILE.open(encoding="utf-8") as file:
    site = json.load(file)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))


def render(template: str, **context):
    return render_template(template, site=site, **context)


@app.get("/")
def home():
    return render("home.html", page_title="메인")


@app.get("/guide")
@app.get("/guide/")
def guide():
    return render("guide.html", page_title="프로젝트가이드")


@app.get("/guide.html")
def guide_html():
    return redirect("/guide", code=308)


@app.get("/team/{team_id}")
def team_redirect(team_id: str):
    team = next((item for item in site["teams"] if item["id"] == team_id), None)
    if team is None:
        abort(404, description="조를 찾을 수 없습니다.")
    return redirect(team["domain"], code=307)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
