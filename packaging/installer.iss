; MLab Windows 安装程序（Inno Setup 6）。由 packaging/build.py 调用：
;   ISCC /DAppVersion=0.1.0 /DEdition=base /DSourceDir=dist\MLab /DOutputDir=dist\installer /DIconFile=build\icons\mlab.ico installer.iss
; 本文件需保存为带 BOM 的 UTF-8，否则中文会乱码。

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef Edition
  #define Edition "base"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\MLab"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif
#ifndef IconFile
  #define IconFile "..\build\icons\mlab.ico"
#endif

#if Edition == "base"
  #define EditionLabel "基础版"
#elif Edition == "ai-gpu"
  #define EditionLabel "AI 版（GPU）"
#else
  #define EditionLabel "AI 版（CPU）"
#endif

[Setup]
; 各版本共用同一 AppId：安装 AI 版会直接替换基础版，反之亦然
AppId={{5B7C3E2A-6F1D-4C8B-9E4A-2D7F0A1B3C55}
AppName=MLab
AppVersion={#AppVersion}
AppVerName=MLab {#AppVersion} {#EditionLabel}
AppPublisher=MLab
AppComments=脑膜炎病灶标注工具（仅供科研使用，不用于临床诊断）
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\MLab
DefaultGroupName=MLab
DisableProgramGroupPage=yes
; 医院电脑通常没有管理员权限：默认安装到当前用户，有权限时可选择为所有用户安装
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=MLab-{#AppVersion}-{#Edition}-windows-x64-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\MLab.exe
UninstallDisplayName=MLab {#EditionLabel}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
#ifdef DiskSpanning
DiskSpanning=yes
DiskSliceSize=max
#endif

[Languages]
#define LangDir AddBackslash(CompilerPath) + "Languages\"
#if FileExists(LangDir + "ChineseSimplified.isl")
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#elif FileExists(LangDir + "Unofficial\ChineseSimplified.isl")
Name: "chs"; MessagesFile: "compiler:Languages\Unofficial\ChineseSimplified.isl"
#elif FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
Name: "chs"; MessagesFile: "ChineseSimplified.isl"
#else
  #pragma message "未找到简体中文语言文件，安装界面将使用英文"
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: "contextmenu"; Description: "在文件夹右键菜单中添加“用 MLab 打开”"; GroupDescription: "附加任务："

[InstallDelete]
; 升级或切换版本时先清除旧的运行库，避免残留不兼容的 PyTorch / Qt 文件
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MLab"; Filename: "{app}\MLab.exe"; Comment: "脑膜炎病灶标注工具"
Name: "{autodesktop}\MLab"; Filename: "{app}\MLab.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\Directory\shell\MLab"; ValueType: string; ValueName: ""; ValueData: "用 MLab 打开"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\MLab"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\MLab.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\MLab\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MLab.exe"" ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\MLab"; ValueType: string; ValueName: ""; ValueData: "用 MLab 打开此文件夹"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\MLab"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\MLab.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\MLab\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MLab.exe"" ""%V"""; Tasks: contextmenu

[Run]
Filename: "{app}\MLab.exe"; Description: "立即启动 MLab"; Flags: nowait postinstall skipifsilent
