"""Full project snapshot hardlinked against an existing complete backup.

AGENTS.md requires a full copy of the project on R:/ before changes. The R:
disk is full, so unchanged files are hard-linked from the reference backup
(same volume) and only new/changed files are copied. The snapshot keeps every
file of the project; rollback remains read-only copy usage.
"""
import os
import shutil
import stat
import sys
from pathlib import Path

SRC = Path(r"C:\Work\Projects\Prj_16_OCR")
REF = Path(r"R:\Backups\Prj_16_OCR_backup_20261029_pre_1c_invoice")
DST = Path(r"R:\Backups\Prj_16_OCR_backup_20261029_pre_training_pairs")

REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT


def snapshot():
    linked = copied = skipped_refs = 0
    copied_bytes = 0
    missing_refs = 0
    for root, dirs, files in os.walk(SRC, topdown=True):
        keep = []
        for name in dirs:
            full = os.path.join(root, name)
            try:
                info = os.lstat(full)
            except OSError:
                continue
            if info.st_file_attributes & REPARSE:
                continue
            keep.append(name)
        dirs[:] = keep
        for name in files:
            source = full_path = Path(root) / name
            relative = source.relative_to(SRC)
            target = DST / relative
            reference = REF / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            link = False
            if reference.is_file():
                s_info = source.stat()
                r_info = reference.stat()
                if s_info.st_size == r_info.st_size and abs(s_info.st_mtime - r_info.st_mtime) <= 1.5:
                    try:
                        os.link(reference, target)
                        linked += 1
                        link = True
                    except OSError:
                        link = False
                else:
                    skipped_refs += 1
            if not reference.is_file():
                missing_refs += 1
            if not link:
                shutil.copy2(source, target)
                copied += 1
                copied_bytes += source.stat().st_size
    return linked, copied, skipped_refs, missing_refs, copied_bytes


def count_files(root: Path, skip_reparse=True) -> int:
    total = 0
    for base, dirs, files in os.walk(root, topdown=True):
        if skip_reparse:
            keep = []
            for name in dirs:
                info = os.lstat(os.path.join(base, name))
                if not info.st_file_attributes & REPARSE:
                    keep.append(name)
            dirs[:] = keep
        total += len(files)
    return int(total)


if __name__ == "__main__":
    if not REF.is_dir():
        print("NO_REFERENCE_BACKUP", REF)
        sys.exit(2)
    linked, copied, changed, missing, volume = snapshot()
    source_total = count_files(SRC)
    snap_total = count_files(DST)
    print(f"hardlinked_files={linked}")
    print(f"copied_files={copied} volume={volume / 1024 / 1024:.1f}MB")
    print(f"ref_changed={changed} ref_missing={missing}")
    print(f"src_files={source_total} snapshot_files={snap_total}")
    ok = source_total == snap_total and snap_total > 0
    print("SNAPSHOT_OK" if ok else "SNAPSHOT_MISMATCH")
    sys.exit(0 if ok else 1)
