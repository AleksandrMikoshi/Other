#!/bin/bash
set -e

# Variables
WORKDIR="/etc/haproxy/geoip"
WHITELIST="$WORKDIR/whitelist.lst"
BLACKLIST="$WORKDIR/blacklist.lst"
TMPDIR="$WORKDIR/tmp"
MAXMIND_LICENSE="*************"
LOCATIONS="Russia Kazakhstan Poland Finland"

# Create working directories if they do not exist.
mkdir -p "$WORKDIR"
mkdir -p "$TMPDIR"

# Create whitelist and blacklist files if they don't exist
[[ ! -f "$WHITELIST" ]] && echo "[*] Create a whitelist file: $WHITELIST" && touch "$WHITELIST"
[[ ! -f "$BLACKLIST" ]] && echo "[*] Create a blacklist file: $BLACKLIST" && touch "$BLACKLIST"


# Blacklist update
echo "[*] Loading new blocklists..."
curl -s -o "$TMPDIR/firehol_proxies.netset" https://iplists.firehol.org/files/firehol_proxies.netset
curl -s -o "$TMPDIR/dm_tor.ipset" https://iplists.firehol.org/files/dm_tor.ipset

echo "[*] Cleaning and merging the blacklist..."
cat "$TMPDIR/firehol_proxies.netset" "$TMPDIR/dm_tor.ipset" \
    | grep -v '^#' | grep -v '^$' | sort -u > "$BLACKLIST"

# Updating whitelist by GeoIP
echo "[*] Updating the whitelist for countries: $LOCATIONS"

pushd "$TMPDIR" > /dev/null

# Loading GeoLite2-Country CSV
wget -qO geoip2lite.zip "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country-CSV&license_key=${MAXMIND_LICENSE}&suffix=zip"
unzip -j geoip2lite.zip || { logger -t "haproxy_geoip" "Download or unzip failed"; exit 1; }

# We create a whitelist directly in $WHITELIST
> "$WHITELIST"
for COUNTRY in $LOCATIONS; do
    echo "# $COUNTRY" >> "$WHITELIST"
    COUNTRY_CODE=$(grep -i ",${COUNTRY}," GeoLite2-Country-Locations-en.csv | awk -F "," '{print $1}')
    grep ",${COUNTRY_CODE}," GeoLite2-Country-Blocks-IPv4.csv | awk -F "," '{print $1}' >> "$WHITELIST"
done

popd > /dev/null

# Cleaning temporary files
rm -rf "$TMPDIR"

# Итог
echo "[*] Summary:"
echo " - Whitelist (GeoIP): $WHITELIST ($(wc -l < ​​"$WHITELIST") lines)"
echo " - Blacklist: $BLACKLIST ($(wc -l < ​​"$BLACKLIST") lines)"
echo "[*] Ready. Don't forget to restart HAProxy!"