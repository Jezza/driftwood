#!/bin/bash
# driftwood-apt-sources writes deb822 sources that apt parses, with every
# Debian suite (stable, -updates, -security, -backports) signed by Debian's
# keyring, no deb-src enabled, and an empty sources.list. Offline:
# `apt-get --print-uris update` parses the sources and lists what it would
# fetch, without fetching.
set -u
cd "$(dirname "$0")/.." || exit 1
SCRIPT=plasma/config/includes.chroot/usr/sbin/driftwood-apt-sources
fail=0
ok() { echo "PASS $1"; }
bad() { echo "FAIL $1"; fail=$((fail + 1)); }

if ! command -v apt-get >/dev/null; then
    echo "SKIP: apt-get not available"; exit 0
fi

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/etc/apt/apt.conf.d" "$T/etc/apt/preferences.d" "$T/var/lib/apt/lists" "$T/var/cache/apt"
# the old one-line file live-build leaves behind must be replaced
echo "deb http://deb.debian.org/debian/ stable main" > "$T/etc/apt/sources.list"

sh "$SCRIPT" "$T" || bad "script exited non-zero"
# twice: re-running (e.g. Calamares after the live session) is harmless
sh "$SCRIPT" "$T" || bad "second run exited non-zero"

APT=(apt-get -o Dir="$T" -o Dir::State::status=/dev/null -o Debug::NoLocking=1 -o APT::Architecture=amd64)
# 'https://deb.debian.org/debian/dists/stable/main/binary-amd64/Packages.xz' ...
#   -> "deb https://deb.debian.org/debian stable main"
targets=$("${APT[@]}" --print-uris update 2>"$T/err" \
    | sed -nE "s|^'(https?://[^ ]+)/dists/([^/]+)/([^/]+)/binary-amd64/Packages\.xz'.*|deb \1 \2 \3|p
               s|^'(https?://[^ ]+)/dists/([^/]+)/([^/]+)/source/Sources\.xz'.*|deb-src \1 \2 \3|p" | sort -u)
[ -s "$T/err" ] && { bad "apt warned:"; cat "$T/err"; } || ok "apt parses the sources without warnings"

for want in "deb https://deb.debian.org/debian stable main" \
            "deb https://deb.debian.org/debian stable-updates non-free-firmware" \
            "deb https://security.debian.org/debian-security stable-security main" \
            "deb https://deb.debian.org/debian stable-backports main"; do
    grep -qx "$want" <<<"$targets" && ok "has: $want" || bad "missing: $want"
done
grep -q '^deb-src' <<<"$targets" && bad "deb-src is enabled" || ok "deb-src disabled"
grep -q 'http://' <<<"$targets" && bad "plain http source" || ok "all sources https"

n_sources=$(grep -c '^Types:' "$T/etc/apt/sources.list.d/debian.sources")
n_signed=$(grep -c '^Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp$' "$T/etc/apt/sources.list.d/debian.sources")
[ "$n_sources" = "$n_signed" ] && ok "every stanza has Signed-By ($n_signed)" || bad "$n_signed of $n_sources stanzas signed"

grep -v '^#' "$T/etc/apt/sources.list" | grep -q . && bad "sources.list still has entries" || ok "sources.list has no entries"

echo "$fail failure(s)"
[ "$fail" = 0 ]
