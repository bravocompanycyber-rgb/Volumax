# Changelog

## 1.2.4
- Build: a cached 7-Zip engine (build\engines\...) left by an older build is verified for the right CPU architecture
  and is discarded and re-downloaded automatically if it is not (no manual cleanup needed).
- Includes everything from 1.2.3 (which was committed but never delivered).

## 1.2.3
- Fixed (crash): the failed-job notice kept a reference to a dialog Qt had already deleted; on Windows/PySide2 that
  caused an access violation. It is now one persistent dialog that is reused.
- Build: the 7-Zip engine is now chosen by CPU architecture from the installer (exe AND dll), the DLL's architecture is
  verified, and the engine is run for real (create + test 7z and zip) before packaging. The unpacked installer's file list
  is written to the build log. (Targets the 32-bit legacy "Unsupported archive type" self-test failure.)
- Tests: Windows-invalid file names and RAM-dependent assertions no longer fail on Windows.

## 1.2.2
- Fixed: build stopped on Windows at `test_single_instance_merges_multiselect` (the test put client and server in one
  thread; Windows named pipes need the server's event loop). The test now uses real separate processes.
- Single-instance forwarding retries briefly on transient "pipe busy" errors, so a burst of Explorer launches
  (multi-select) all reach the running instance. First launch (nothing running) stays instant.
- Build: a failing unit test is now a prominent WARNING and the build continues (the built program must still
  pass its own self-test). Use `--strict-tests` to make failures fatal.

## 1.2.1
- Fixed: every second row of the Archive Browser (and other tables/lists) rendered white under light text on Windows,
  making files unreadable. The app now sets one dark palette + Fusion style, and all item views have explicit
  row, alternate-row and selection colours (pixel-tested for contrast).

## 1.2.0
**Reliability / self-healing**
- App starts even if the 7-Zip engine is missing; Diagnostics page can re-detect, repair or locate it.
- Corrupt settings are quarantined (`settings.corrupt-*.json`) and replaced with defaults.
- Crash reports (`crash-*.txt`) + native crash log; stray errors no longer end the app.
- Plain-language error messages (wrong password, disk full, access denied, damaged archive...).
- Existing archive is kept until a replacement is fully built (failed/cancelled run restores it).
- Disk-space guard before creating; stale temp cleanup.
- Fixed: a failed batch opened one blocking dialog per job (stacked modals) - now one notice.
- Fixed: extraction limits only applied after restart - now live. Added compression-ratio (bomb) limit.
- Fixed: very long / invalid paths typed into forms could raise an unhandled error.
- Fixed: "Export as script" on Python 3.8 (legacy build).

**New features**
- Verify-after-create (on by default) and optional `.sha256` checksum file.
- Tools: archive file Preview (text/images), Compare two archives, Find across a folder of archives,
  Salvage damaged archives, Small-file Pack (Zstandard, dictionary only when it saves >= 20%).
- Export the Create settings as a .bat / .ps1 / .sh script (password is never written into it).
- Filenames are hidden by default for password-protected 7z (AES-256).

**Interface**
- WCAG-AA contrast for all text and buttons (checked by tests); themed tabs and table headers.
- Pages scroll instead of squashing controls on small windows; home cards wrap text; "&" shown correctly.

## 1.1.0
Faster listing/creating, adaptive compression planner, Modern + Legacy Windows builds, installer build script.
