; 小鲸鱼 电脑版安装包（干净新用户版）
; 用 Inno Setup 6 编译：ISCC.exe installer.iss

#define MyAppName "小鲸鱼"
#define MyAppVersion "9.10"
#define MyAppPublisher "BrainN"
#define MyAppExeName "小鲸鱼.exe"
#define PkgDir "F:\BrainN\build_desktop\package\小鲸鱼"

[Setup]
AppId={{8F2A5C63-4D1E-4B7A-9C3E-2A6B7D8E9F01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion=9.10.0.0
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=F:\BrainN\dist_desktop
OutputBaseFilename=小鲸鱼-Setup-新用户版-v9.10
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=F:\BrainN\desktop_runtime\xiaojingyu.ico
UninstallDisplayIcon={app}\desktop_runtime\xiaojingyu.ico
UninstallDisplayName={#MyAppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AllowNoIcons=yes

[Messages]
SetupAppTitle=安装 小鲸鱼
SetupWindowTitle=安装 小鲸鱼
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=现在会把你电脑上的小鲸鱼装好，装完可以直接运行。%n%n安装前建议先关掉其他正在运行的程序。
WizardSelectDir=选择安装位置
WizardSelectTasks=选择附加任务
WizardReady=准备安装
WizardPreparing=正在准备
WizardInstalling=正在安装
WizardUninstalling=正在卸载
SelectDirDesc=小鲸鱼要装到哪个文件夹？
SelectDirBrowseLabel=点“下一步”继续；要换文件夹就点“浏览…”。
ButtonBrowse=浏览…
ButtonWizardBrowse=浏览…
ButtonNext=下一步
ButtonBack=上一步
ButtonCancel=取消
ButtonInstall=安装
ButtonFinish=完成
ButtonYes=是
ButtonNo=否
SelectDirLabel3=安装程序会把小鲸鱼装到下面这个文件夹，点“浏览”可以换位置。
DiskSpaceMBLabel=至少需要 [mb] MB 空间。
ReadyLabel1=安装程序已经准备好，点“安装”开始。
ReadyLabel2a=点“安装”写入文件；想改设置就点“上一步”。
PreparingDesc=正在准备安装…
InstallingLabel=正在安装小鲸鱼，请稍等…
FinishedHeadingLabel=小鲸鱼装好了
FinishedLabel=点“完成”关闭安装程序。
FinishedLabelNoIcons=点“完成”关闭安装程序。
ClickNext=点“下一步”继续。
ClickFinish=点“完成”退出安装程序。
ConfirmUninstall=确定要卸载 小鲸鱼 吗？聊天记录和记忆不会被删除。
UninstallStatusLabel=正在卸载，请稍等…
StatusUninstalling=正在卸载 %1…
UninstalledAll=小鲸鱼已卸载。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[InstallDelete]
Type: files; Name: "{app}\BrainN.exe"

[Files]
Source: "{#PkgDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\desktop_runtime\xiaojingyu.ico"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\desktop_runtime\xiaojingyu.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--reset-persona"; Flags: runhidden waituntilterminated skipifdoesntexist; StatusMsg: "准备随机初始人设…"
Filename: "{app}\{#MyAppExeName}"; Parameters: "--reset-splash-identity"; Flags: runhidden waituntilterminated skipifdoesntexist; StatusMsg: "初始化开屏身份…"
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动小鲸鱼"; Flags: nowait postinstall skipifsilent
