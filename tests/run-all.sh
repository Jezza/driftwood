#!/bin/bash
# Run every test in tests/. Exit non-zero if any fails.
# Needs: bash, python3, cryptsetup (cryptsetup-bin); grub-script-check
# (grub-common) is used when present; kmod (modinfo) for the initramfs hook test.
cd "$(dirname "$0")" || exit 1
rc=0
for t in test_*; do
    echo "######## $t"
    case "$t" in
        *.py) python3 "$t" ;;
        *.sh) bash "$t" ;;
    esac || rc=1
done
exit $rc
