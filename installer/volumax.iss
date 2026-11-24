; VOLUMAX installer — compiled by tools/build_all.py (ISCC.exe), one run per build target.
; Required defines: AppVersion Flavor(modern|legacy) Arch(x64|x86) SourceDir OutputDir OutputName RepoRoot
; Compatible with Inno Setup 6.3+ and 7.

#ifndef AppVersion
  #error Compile through tools\build_all.py (missing /DAppVersion=...)
#endif
#ifndef Flavor
  #error Missing /DFlavor=modern|legacy
#endif
#ifndef Arch
  #error Missing /DArch=x64|x86
#endif
#define AppName "VOLUMAX"
#define AppExe "VOLUMAX.exe"
#define AppPublisher "Bravo Projects"

[Setup]
AppId={{B7C0E5F1-6D2A-4C1B-9F3E-5A8D2C4E7B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (C) {#AppPublisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} setup ({#Flavor}, {#Arch})
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user by default (no admin prompt); the user can choose "all users" in a dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UsedUserAreasWarning=no
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#RepoRoot}\assets\logo.ico
WizardImageFile={#RepoRoot}\installer\wizard-large.bmp
WizardSmallImageFile={#RepoRoot}\installer\wizard-small.bmp
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
#if Arch == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#else
ArchitecturesAllowed=x86compatible
#endif
#if Flavor == "modern"
; Qt 6 needs Windows 10 version 1809 or newer.
MinVersion=10.0.17763
#endif
; Legacy: Inno's default minimum (Windows 7 SP1) is kept, so Windows 8 / 8.1 / 10 / 11 all pass.

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "assoc_common"; Description: "Open .7z .tar .gz .tgz .bz2 .xz .cab .wim .iso files with {#AppName}"; GroupDescription: "File associations:"
Name: "assoc_ziprar"; Description: "Also open .zip and .rar files with {#AppName}"; GroupDescription: "File associations:"; Flags: unchecked
Name: "shellmenu"; Description: "Add {#AppName} to the right-click menu (Extract here, Add to .7z / .zip)"; GroupDescription: "Explorer integration:"

[Registry]
; ---- ProgId: how Windows launches VOLUMAX for an archive (always registered, harmless) ----
Root: HKA; Subkey: "Software\Classes\VOLUMAX.Archive"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX archive"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\VOLUMAX.Archive\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\VOLUMAX.Archive\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "VOLUMAX"
Root: HKA; Subkey: "Software\Classes\VOLUMAX.Archive\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Flags: uninsdeletekey
; ---- file associations: assoc_common ----
Root: HKA; Subkey: "Software\Classes\.7z"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.7z\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.tar"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.tar\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.gz"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.gz\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.tgz"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.tgz\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.bz2"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.bz2\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.xz"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.xz\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.cab"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.cab\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.wim"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.wim\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.iso"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
Root: HKA; Subkey: "Software\Classes\.iso\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_common
; ---- file associations: assoc_ziprar ----
Root: HKA; Subkey: "Software\Classes\.zip"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_ziprar
Root: HKA; Subkey: "Software\Classes\.zip\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_ziprar
Root: HKA; Subkey: "Software\Classes\.rar"; ValueType: string; ValueName: ""; ValueData: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_ziprar
Root: HKA; Subkey: "Software\Classes\.rar\OpenWithProgids"; ValueType: none; ValueName: "VOLUMAX.Archive"; Flags: uninsdeletevalue; Tasks: assoc_ziprar
; ---- Explorer right-click menu (task: shellmenu) ----
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.Add"; ValueType: string; ValueName: ""; ValueData: "Add to VOLUMAX archive..."; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.Add"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.Add\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --add ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.Add7z"; ValueType: string; ValueName: ""; ValueData: "Add to .7z (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.Add7z"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.Add7z\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --add-to 7z ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.AddZip"; ValueType: string; ValueName: ""; ValueData: "Add to .zip (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.AddZip"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\VOLUMAX.AddZip\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --add-to zip ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.Add"; ValueType: string; ValueName: ""; ValueData: "Add to VOLUMAX archive..."; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.Add"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.Add\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --add ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.Add7z"; ValueType: string; ValueName: ""; ValueData: "Add to .7z (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.Add7z"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.Add7z\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --add-to 7z ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.AddZip"; ValueType: string; ValueName: ""; ValueData: "Add to .zip (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.AddZip"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\VOLUMAX.AddZip\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --add-to zip ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tar\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tar\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tar\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tar\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tar\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tar\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gz\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gz\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gz\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gz\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gz\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gz\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tgz\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tgz\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tgz\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tgz\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tgz\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tgz\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bz2\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bz2\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bz2\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bz2\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bz2\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bz2\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xz\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xz\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xz\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xz\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xz\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xz\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cab\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cab\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cab\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cab\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cab\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cab\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wim\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wim\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wim\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wim\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wim\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wim\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.iso\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.iso\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.iso\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.iso\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.iso\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.iso\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: ""; ValueData: "Extract here (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\VOLUMAX.ExtractHere"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\VOLUMAX.ExtractHere\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-here ""%1"""; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: ""; ValueData: "Extract to folder (VOLUMAX)"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\VOLUMAX.ExtractFolder"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\VOLUMAX.ExtractFolder\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --extract-to-folder ""%1"""; Tasks: shellmenu

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if not UninstallSilent then
      if MsgBox('Also delete your {#AppName} settings and logs?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{userappdata}\{#AppName}'), True, True, True);
  end;
end;
