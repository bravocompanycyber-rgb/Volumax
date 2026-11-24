# VOLUMAX performance notes

Measured on a 2-core Linux box with 7-Zip 23 (the bundled engine is 7-Zip 26.06).

## Browsing
| Archive | First open | Re-open (cached) |
|---|---|---|
| 7z, 200,000 entries | ~0.6 s | 3 ms |
| ZIP, 200,000 entries | ~0.7 s | 3 ms |

Why: compact `7z l` listing parsed by column (not `-slt`), listing runs off the GUI
thread, the table is a virtual `QAbstractTableModel` (only visible rows are painted),
and results are cached by (path, mtime, size, password).

## Compression (48.7 MB mixed corpus: source, binaries, one incompressible JPEG)
| Preset | Size | Time |
|---|---|---|
| Old default (level 5) | 12.26 MB | 7.8 s |
| **Maximum** (new default) | **10.30 MB (-16%)** | 7.8 s |
| Ultra (big dictionary, fb=273) | 10.28 MB (-16.2%) | 10.1 s |

Planner rules (see `src/volumax/compression.py`): text-dominated input uses PPMd;
mostly-already-compressed input drops to a fast level; dictionary sized to the data
and the machine's free RAM; `-ms=e` is never used (measured ~40% worse).

## Correctness fixes found on the way
- 7-Zip output pipes were never drained: listing/extracting large archives hung forever.
- `.tar.gz/.bz2/.xz` creation failed for folders and listing showed only the inner `.tar`.
- Symlinks were followed when archiving (a link to `/etc` pulled in all of `/etc`).
- Resources/settings resolved wrongly in the PyInstaller build and under Program Files.
- Encrypted archives made 7-Zip wait for console input instead of failing fast.
