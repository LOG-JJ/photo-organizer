# 개발 안내

```text
run.py                     소스 실행
src/photo_organizer/
  app.py, version.py       시작점·버전
  paths.py                 리소스와 작업 경로
  core/                    날짜 판독, 이동 계획, RAW/JPG 비교
  ui/                      화면, 테마, 도구 전환
  windows/                 탐색기 보기·정렬, 휴지통
  diagnostics.py           EXE 자체 검사(일반 실행 시 사용 안 함)
tests/                     회귀 테스트 코드
tools/                     테스트·빌드·검증·미리보기 명령
packaging/                 PyInstaller·Inno Setup 설정
assets/fonts/, icons/     글꼴·아이콘
docs/usage/, licenses/    사용법·제3자 라이선스
.work/                    개발 산출물 전체(Git·배포 제외)
dist/                     최종 설치 파일(Git 제외, Releases 게시)
```

Windows와 Python 3.12 64비트가 필요합니다. 프로젝트 루트에서 실행합니다.

```powershell
python -B run.py
python -B tools/dev.py test --pattern test_photo_pair_cleanup.py
python -B tools/dev.py test
python -B tools/dev.py build
python -B tools/dev.py verify
```

콘솔에는 마지막 결과만 표시합니다. 전체 로그는 같은 파일을 교체합니다.

| 산출물 | 위치 |
|---|---|
| 합성 사진·임시 파일 | `.work/tmp/` |
| 테스트 결과 | `.work/reports/tests.log` |
| 빌드 로그 | `.work/reports/build.log` |
| EXE 검사 결과 | `.work/reports/package.json` |
| 미리보기·스크린샷 | `.work/previews/` |
| Python·다운로드 캐시 | `.work/cache/` |
| 중간 빌드 | `.work/build/` |
| 빌드 가상 환경·도구 | `.work/venv/`, `.work/toolchain/` |
| 최종 설치 파일 | `dist/PhotoOrganizer-Setup.exe` |

Inno Setup 6.7 이상을 설치한 뒤 `packaging/build.ps1 -InnoCompiler "ISCC.exe 경로"`를
사용하거나, 포터블 컴파일러를 `.work/toolchain/inno/ISCC.exe`에 둡니다.
빌드용 Python 패키지는 `.work/venv/`에 설치됩니다.

테스트·미리보기는 `_support.py`를 통해 TEMP·TMP와 Python 임시 경로를 `.work/tmp/`로 설정합니다.
새 보고서·이미지는 `photo_organizer.paths.artifact_path()`로 경로를 만드세요.
`tools/dev.py clean`은 `.work`의 tmp·previews·reports·cache만 비우며 도구와 설치 파일은 남깁니다.

일반 설치본에서 메타데이터 전달에 쓰는 일시적인 파일은 사용자 로컬 앱 데이터의
`PhotoOrganizer/.work/tmp/`에서 생성하고 작업 후 지웁니다. 작업 기록은 저장하지 않습니다.

PyInstaller는 실행 코드, 글꼴 3개, 아이콘 3개, 사용법·라이선스 텍스트만 포함합니다.
루트나 `.work`를 통째로 복사하지 않습니다. `verify`는 합성 파일로 세 기능을 확인하고,
빌드 결과에 `.work`, `tests`, `tools`, `packaging`, `__pycache__`가 있으면 실패합니다.
개인 사진·인증 정보·중간 결과를 커밋하지 않습니다. 기존 공개 Git 이력과 태그는 강제로 덮어쓰지 않습니다.
