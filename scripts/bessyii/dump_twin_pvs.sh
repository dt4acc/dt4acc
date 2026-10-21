#!/bin/bash
# Dump the PVs of a running BESSY II twin, for make_pv_list.py:
#   <out>/pvs_by_server.txt   pvlist of every PVA server ("GUID ..." line, then its PVs)
#   <out>/pvs_ca.txt          the PVs that answer over Channel Access (caget)
# Run with the twin's EPICS environment (EPICS_PVA_* / EPICS_CA_*); needs
# pvlist and caget (EPICS base) on PATH.
#
#   scripts/bessyii/dump_twin_pvs.sh /tmp/bessyii_pvs
set -euo pipefail
out="${1:-.}"
mkdir -p "$out"

: > "$out/pvs_by_server.txt"
for guid in $(pvlist | awk '/^GUID/ {print $2}'); do
  echo "GUID $guid" >> "$out/pvs_by_server.txt"
  pvlist "$guid" >> "$out/pvs_by_server.txt"
done

grep -v '^GUID' "$out/pvs_by_server.txt" | sort -u > "$out/pvs_all.txt"
# one caget per PV (given several, caget prints nothing once one of them is
# not found), in parallel; each prints only its name, once found (short lines
# do not interleave)
xargs -P 32 -I{} sh -c 'caget -w 2 "$1" > /dev/null 2>&1 && echo "$1"' _ {} < "$out/pvs_all.txt" \
  | sort -u > "$out/pvs_ca.txt" || true
echo "$(wc -l < "$out/pvs_all.txt") PVs over PVA, $(wc -l < "$out/pvs_ca.txt") over CA -> $out"
