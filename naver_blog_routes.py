from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DRAFTS_PATH = BASE / "data" / "naver_blog_drafts.json"
MCP_PASSWORD = os.getenv("MCP_PASSWORD", "4321")
router = APIRouter(prefix="/api/mcp/naver-blog", tags=["naver-blog-mcp"])


class ProductInput(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="", max_length=80)
    price: str = Field(default="", max_length=80)
    condition: str = Field(default="", max_length=80)
    features: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list)
    target_customer: str = Field(default="", max_length=200)
    usage: str = Field(default="", max_length=500)
    shipping_or_location: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=200)


def _read() -> list[dict]:
    if not DRAFTS_PATH.exists():
        return []
    try:
        return json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write(items: list[dict]) -> None:
    DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRAFTS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def standardize(product: ProductInput) -> dict[str, str]:
    p = product.model_dump()
    name = _clean(p["product_name"])
    title = f"{name} | {p['category']} 상품소개" if p["category"] else f"{name} 상품소개"
    lines = [f"안녕하세요. 오늘 소개해드릴 상품은 {name}입니다.", ""]
    if p["target_customer"]:
        lines += [f"이런 분께 추천드립니다: {_clean(p['target_customer'])}", ""]
    if p["selling_points"]:
        lines += ["주요 특징", *[f"- {_clean(x)}" for x in p["selling_points"] if _clean(x)], ""]
    if p["features"]:
        lines += ["상세 정보", *[f"- {_clean(x)}" for x in p["features"] if _clean(x)], ""]
    for label, key in (("가격", "price"), ("상태", "condition"), ("사용 방법", "usage"), ("거래/배송", "shipping_or_location")):
        if p[key]:
            lines.append(f"{label}: {_clean(p[key])}")
    lines += ["", "궁금한 점은 편하게 문의해주세요.", "감사합니다."]
    if p["contact"]:
        lines += ["", f"문의: {_clean(p['contact'])}"]
    return {"title": title, "body": "\n".join(lines)}


def guard(request: Request) -> None:
    if request.headers.get("x-mcp-password", "") != MCP_PASSWORD:
        raise HTTPException(status_code=401, detail="MCP 비밀번호가 올바르지 않습니다.")


@router.post("/login")
def login(request: Request) -> dict[str, bool]:
    guard(request)
    return {"ok": True}


@router.post("/standardize")
def standardize_product(product: ProductInput, request: Request) -> dict[str, str]:
    guard(request)
    return standardize(product)


@router.post("/drafts")
def create_draft(product: ProductInput, request: Request) -> dict:
    guard(request)
    content = standardize(product)
    draft = {
        **product.model_dump(),
        **content,
        "draft_id": uuid.uuid4().hex[:12],
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _read()
    items.append(draft)
    _write(items)
    return draft


@router.get("/drafts")
def list_drafts(request: Request) -> list[dict]:
    guard(request)
    return _read()


@router.post("/publish-ready/{draft_id}")
def mark_publish_ready(draft_id: str, request: Request) -> dict:
    guard(request)
    items = _read()
    for item in items:
        if item["draft_id"] == draft_id:
            item["status"] = "ready_for_naver_publisher"
            _write(items)
            return item
    raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다.")
