; 自动铃声系统 Web GUI 桌面版 Inno Setup 安装脚本
; 编译：ISCC.exe installer\自动铃声系统-Web.iss

#define MyAppName "自动铃声系统"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AutoBell"
#define MyAppExeName "自动铃声系统.exe"
#define MyAppId "{{B3C2C6E7-9A41-4B7E-BD6F-2E44C1A8F3D2}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AutoBellDesktop
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-electron
OutputBaseFilename=自动铃声系统-1.0.0-安装程序
SetupIconFile=..\desktop\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion=1.0.0.0
VersionInfoDescription=自动铃声系统安装程序
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoCopyright=Copyright © 2026 AutoBell

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=安装
SetupWindowTitle=安装 - %1
UninstallAppTitle=卸载
UninstallAppFullTitle=%1 卸载
InformationTitle=提示
ConfirmTitle=确认
ErrorTitle=错误
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonNo=否(&N)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonNewFolder=新建文件夹(&M)
ClickNext=点击“下一步”继续，或点击“取消”退出安装。
WizardSelectDir=选择安装位置
SelectDirDesc=请选择 [name] 的安装位置。
WizardReady=准备安装
WizardPreparing=正在准备安装
PreparingDesc=安装程序正在准备安装 [name]...
WizardInstalling=正在安装
InstallingLabel=正在安装 [name]，请稍候...
SelectLanguageTitle=选择安装语言
SelectLanguageLabel=选择安装过程中使用的语言。
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=安装程序将把 [name/ver] 安装到您的电脑。%n%n建议继续前关闭其他应用程序。
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹。
SelectDirBrowseLabel=点击“下一步”继续。如需选择其他文件夹，请点击“浏览”。
DiskSpaceGBLabel=至少需要 [gb] GB 可用磁盘空间。
DiskSpaceMBLabel=至少需要 [mb] MB 可用磁盘空间。
WizardSelectTasks=选择附加任务
SelectTasksDesc=您希望安装程序执行哪些附加任务？
SelectTasksLabel2=请选择安装 [name] 时需要执行的附加任务，然后点击“下一步”。
ReadyLabel1=准备安装 [name]
ReadyLabel2a=点击“安装”开始安装，或点击“上一步”检查、更改设置。
FinishedHeadingLabel=[name] 安装完成
FinishedLabel=安装程序已完成 [name] 的安装。%n%n可以从开始菜单启动程序。
ClickFinish=点击“完成”退出安装程序。
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会安装。%n%n您可以在稍后重新运行安装程序。%n%n确定退出吗？
SetupAppRunningError=安装程序检测到 %1 正在运行。%n%n请关闭所有实例后点击“确定”继续，或点击“取消”退出。
UninstallAppRunningError=卸载程序检测到 %1 正在运行。%n%n请关闭所有实例后点击“确定”继续，或点击“取消”退出。
SetupAlreadyRunning=安装程序已经在运行。
ConfirmUninstall=确定要完全删除 %1 及所有组件吗？
UninstalledAll=%1 已成功卸载。
StatusExtractFiles=正在解压文件...
StatusCreateIcons=正在创建快捷方式...
StatusCreateRegistryEntries=正在写入注册表项...
StatusRollback=正在回滚更改...

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist-electron\win-unpacked\*"; DestDir: "{app}"; Excludes: "AutoBellData\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
