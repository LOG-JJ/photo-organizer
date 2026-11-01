# 사진 정리 · Photo Organizer

사진 날짜별 정리, 파일 분류, RAW·JPG 짝 없는 파일 정리를 하나로 모은 Windows 프로그램입니다.

## 다운로드 및 설치

**[최신 설치 파일 다운로드](https://github.com/LOG-JJ/photo-organizer/releases/latest/download/PhotoOrganizer-Setup.exe)**

1. `PhotoOrganizer-Setup.exe`를 내려받아 실행합니다.
2. 설치가 끝나면 시작 메뉴 또는 바로가기의 **사진 정리**를 실행합니다.
3. 왼쪽에서 기능을 고르고 폴더를 선택합니다.
4. 목록을 확인한 뒤 실행 버튼을 누릅니다.

- Windows 10 / 11, 64비트 환경에서 사용할 수 있습니다.
- Python을 따로 설치할 필요가 없습니다.
- 업데이트는 프로그램을 종료한 뒤 새 설치 파일을 실행하면 됩니다. 기존 프로그램을 먼저 삭제할 필요는 없습니다.
- 현재 설치 파일에는 코드 서명이 적용되어 있지 않습니다.

## 주요 기능

| 기능 | 동작 |
|---|---|
| 날짜별 정리 | 사진과 동영상을 `YYYY-MM-DD` 폴더로 정리합니다. 하위 폴더 포함 여부와 탐색기 보기·정렬을 설정할 수 있습니다. |
| 파일 분류 | 선택한 폴더 바로 안의 JPG·NEF·MOV를 각각의 폴더로 옮깁니다. 같은 이름이 있으면 원본을 남깁니다. |
| RAW·JPG 정리 | RAW와 JPG 양쪽을 비교하고 짝이 없는 파일을 보여줍니다. 선택한 파일은 최종 확인 후 Windows 휴지통으로 보냅니다. |

### 보기·정렬

파일 분류 후 JPG·NEF·MOV 폴더는 기본적으로 **아주 큰 아이콘 / 날짜 오름차순**을 사용합니다.
자동 정렬 기준은 JPG는 **찍은 날짜**, NEF·MOV는 **수정한 날짜**입니다.
**보기·정렬**에서 직접 변경하거나 정리 후 자동 적용을 끌 수 있습니다.
파일 분류는 상위 폴더의 보기·정렬을 변경하지 않습니다.

### RAW·JPG 비교

이 기능은 확장자를 제외한 파일명을 비교합니다. 이미지 내용을 분석하거나 이전 삭제 이력을 추적하지 않습니다.

- RAW와 JPG를 포함한 행사·여행 폴더를 선택하세요.
- 형식별 폴더와 그 아래 날짜 폴더를 함께 비교합니다.
- 상위·하위 폴더에 같은 이름의 반대 형식이 있으면 정리 대상에서 제외합니다.
- 다른 날짜·행사에 있는 동명 파일은 자동으로 짝으로 연결하지 않습니다.
- 처음부터 한 형식으로만 촬영한 사진도 목록에 포함될 수 있으니 실행 전 확인하세요.

별도의 CSV·엑셀 작업 기록 파일은 생성하지 않습니다.

## 자세한 사용법

- [날짜별 정리](docs/usage/사진_날짜별_정리_사용법.txt)
- [파일 분류](docs/usage/파일_분류_사용법.txt)
- [RAW·JPG 정리](docs/usage/RAW_JPG_짝없는파일_정리_사용법.txt)

## 소스 실행

Windows와 Python 3.12 64비트가 필요합니다. 프로젝트 폴더에서 실행하세요.

```powershell
py -3.12 -m pip install Pillow==12.1.1
py -3.12 -B run.py
```

## 설치 파일 빌드

Python 3.12 64비트와 Inno Setup 6.7 이상을 준비한 뒤 실행합니다.

```powershell
.\packaging\build.ps1 -InnoCompiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

결과는 `dist/PhotoOrganizer-Setup.exe`에 저장됩니다. 수정 시 같은 파일을 교체합니다.
글꼴·아이콘·사용법·제3자 라이선스도 패키지에 포함됩니다.

검증은 실제 사진 대신 임시 파일로 실행합니다.

```powershell
py -3.12 -B tools/dev.py test
py -3.12 -B tools/dev.py verify
```

## 제3자 구성 요소

Python, Tcl/Tk, Pillow, PyInstaller, Inno Setup, Noto Sans KR를 사용합니다.
관련 고지와 라이선스는 [라이선스 폴더](licenses/THIRD-PARTY-NOTICES.txt)에 있습니다.

개발 코드 위치와 명령은 [개발 안내](docs/DEVELOPMENT.md)를 참고하세요.
임시 산출물·검증 결과·빌드 캐시는 `.work/` 한 곳에 생성되며 Git과 배포에서 제외됩니다.
