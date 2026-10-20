# 가비아 홈

FastAPI 기반의 관리자 홈페이지입니다. 메인 홈페이지와 프로젝트가이드를 관리하고, 조별 Git과 조별 사이트는 각 조가 직접 운영합니다.

## 중앙 관리 구조

이 저장소는 관리자용 메인 홈페이지와 프로젝트가이드만 관리합니다. 조별 작업 내용과 조별 Git 저장소는 중앙 저장소에 넣지 않으며, 각 조가 자기 저장소와 서브도메인을 직접 관리합니다.

## 코드 구조

```text
app.py                 FastAPI 라우팅
templates/base.html    공통 레이아웃
templates/home.html    메인 홈페이지
templates/guide.html   프로젝트가이드
static/css/site.css    외부 CSS
data/site.json         관리자 페이지용 설정과 조별 서브도메인 링크
```

조별 작업 내용은 `data/site.json`에 넣지 않습니다. 중앙 홈페이지는 조별 서브도메인으로 연결만 제공합니다.

```text
관리자 Git 저장소 → 가비아 메인 서버 → bssbu.co.kr
관리자 Git 저장소 → 메인 홈페이지의 프로젝트가이드
1조 Git 저장소 → 1조의 배포 서버 → team1.bssbu.co.kr
2조 Git 저장소 → 2조의 배포 서버 → team2.bssbu.co.kr
3조 Git 저장소 → 3조의 배포 서버 → team3.bssbu.co.kr
```

## 로컬 실행

FastAPI 앱으로 실행합니다. 최초 1회 의존성을 설치하세요.

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8080
```

브라우저에서 `http://127.0.0.1:8080/` 또는 `http://127.0.0.1:8080/guide`로 접속합니다.
