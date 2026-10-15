# 가비아 홈

메인 프로젝트 카드와 `1조`, `2조`, `3조`, `프로젝트가이드` 탭을 제공하는 정적 홈페이지입니다.

## 중앙 관리 구조

`index.html` 안의 `centralConfig`가 중앙 관리 설정 샘플입니다. 각 조는 자기 Git 저장소를 관리하고, `프로젝트가이드`는 사용자의 별도 Git 저장소를 연결합니다.

```text
team1 Git 저장소 → 중앙 배포 서버 → team1.example.com
team2 Git 저장소 → 중앙 배포 서버 → team2.example.com
team3 Git 저장소 → 중앙 배포 서버 → team3.example.com
프로젝트가이드 Git 저장소 → 중앙 배포 서버 → guide.example.com
```

## 로컬 실행

프로젝트 루트에서 간단한 정적 서버를 실행하면 됩니다.

```powershell
python -m http.server 5173 --directory C:\bssbu-ai-studio
```
