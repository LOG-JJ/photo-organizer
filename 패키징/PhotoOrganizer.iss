#ifndef AppVersion
  #define AppVersion "1.0.5"
#endif
#ifndef BundleDir
  #define BundleDir SourcePath + "..\.build\dist\PhotoOrganizer"
#endif
#ifndef ReleaseDir
  #define ReleaseDir SourcePath + "..\배포"
#endif

[Setup]
AppId={{F890C39E-4096-48D1-BE29-FDDDF570579A}
AppName=사진 정리
AppVersion={#AppVersion}
AppVerName=사진 정리 {#AppVersion}
DefaultDirName={localappdata}\Programs\PhotoOrganizer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
WizardStyle=modern
UninstallDisplayName=사진 정리
UninstallDisplayIcon={app}\PhotoOrganizer.exe
SetupIconFile=..\아이콘\file_sort.ico
OutputDir={#ReleaseDir}
OutputBaseFilename=PhotoOrganizer-Setup
Compression=lzma2
SolidCompression=yes
AppMutex=PhotoOrganizer.Desktop
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no
ChangesEnvironment=no
VersionInfoDescription=사진 정리 설치 프로그램
VersionInfoProductName=사진 정리
VersionInfoVersion={#AppVersion}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"; Flags: checkedonce

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\사진 정리"; Filename: "{app}\PhotoOrganizer.exe"; WorkingDir: "{app}"; AppUserModelID: "PhotoOrganizer.Desktop"
Name: "{autodesktop}\사진 정리"; Filename: "{app}\PhotoOrganizer.exe"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "PhotoOrganizer.Desktop"

[Run]
Filename: "{app}\PhotoOrganizer.exe"; Description: "사진 정리 실행"; Flags: nowait postinstall skipifsilent
