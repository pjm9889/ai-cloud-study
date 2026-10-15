# 가비아 홈

메인 프로젝트 카드와 `1조`, `2조`, `3조`, `프로젝트가이드` 탭을 제공하는 정적 홈페이지입니다.

## 중앙 관리 구조

`index.html` 안의 `centralConfig`가 중앙 관리 설정 샘플입니다. 각 조는 자기 Git 저장소를 관리하고, `프로젝트가이드`는 사용자의 별도 Git 저장소를 연결합니다.

```text
메인 홈페이지 저장소 → 가비아 메인 문서 루트 → bssbu.co.kr
team1 Git 저장소 → 중앙 배포 서버 → team1.bssbu.co.kr
team2 Git 저장소 → 중앙 배포 서버 → team2.bssbu.co.kr
team3 Git 저장소 → 중앙 배포 서버 → team3.bssbu.co.kr
관리자 Git 저장소 → 가비아 메인 문서 루트 → bssbu.co.kr/#/guide
```

## 로컬 실행

FastAPI 앱으로 실행합니다. 최초 1회 의존성을 설치하세요.

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8080
```

브라우저에서 `http://127.0.0.1:8080/`으로 접속합니다.
