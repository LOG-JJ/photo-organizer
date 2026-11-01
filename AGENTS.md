# 개발 지도

실행 코드는 `src/photo_organizer/` 안에 있다. 폴더 전체를 읽지 말고 관련 모듈과 테스트부터 확인한다.

| 수정할 기능 | 코드 | 테스트 패턴 |
|---|---|---|
| 날짜 판독·이동 계획 | `core/dates.py`, `core/jobs.py` | `test_photo_organizer_jobs.py` |
| RAW/JPG 비교·삭제 전 검증 | `core/pairs.py` | `test_photo_pair_cleanup.py` |
| 날짜/파일 분류 화면 | `ui/organizer.py` | `test_photo_organizer_gui.py` |
| RAW/JPG 화면 | `ui/pairs.py` | `test_photo_pair_gui.py` |
| 테마·폰트·도구 전환 | `ui/common.py` | `test_photo_workspace.py` |
| 탐색기 보기·정렬 | `windows/folder_views.py` | `test_photo_folder_views.py` |
| 휴지통 COM | `windows/recycle_bin.py` | `test_photo_pair_recycle_native.py` |

- 시작점: `app.py`; 버전: `version.py`; 리소스·임시 경로: `paths.py`.
- 먼저 `rg -n`으로 함수·참조를 찾고 필요한 줄만 읽는다.
- 좁은 검증: `python -B tools/dev.py test --pattern 테스트파일명`.
- 전체 검증: `python -B tools/dev.py test`; 로그는 `.work/reports/tests.log`에서 실패 부분만 읽는다.
- 빌드: `python -B tools/dev.py build`; EXE 검사: `python -B tools/dev.py verify`.
- 테스트는 `_support.py`를 사용한다. 실제 사진으로 이동·삭제를 검증하지 않는다.
- 모든 임시 파일·보고서·이미지·캐시·중간 빌드는 `.work/` 아래에만 만든다.
- `.work/`와 `dist/`는 Git 제외. 최종 설치 파일만 `dist/PhotoOrganizer-Setup.exe`로 교체한다.
- 설치본은 실행 코드와 허용된 리소스만 포함한다. 일반 실행에서 작업 기록 파일을 만들지 않는다.

상세한 구조와 명령은 `docs/DEVELOPMENT.md`에 있다.
