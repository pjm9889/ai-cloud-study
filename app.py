import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "site.json"

with DATA_FILE.open(encoding="utf-8") as file:
    site = json.load(file)

app = FastAPI(title=site["site_name"])
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def render(request: Request, template: str, **context):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"site": site, **context},
    )


@app.get("/")
async def home(request: Request):
    return render(request, "home.html", page_title="메인")


@app.get("/guide")
async def guide(request: Request):
    return render(request, "guide.html", page_title="프로젝트가이드")


@app.get("/guide.html")
async def guide_html(request: Request):
    return render(request, "guide.html", page_title="프로젝트가이드")


@app.get("/team/{team_id}")
async def team_redirect(team_id: str):
    team = next((item for item in site["teams"] if item["id"] == team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail="조를 찾을 수 없습니다.")
    return RedirectResponse(url=team["domain"], status_code=307)
