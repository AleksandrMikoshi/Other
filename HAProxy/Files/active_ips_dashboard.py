#!/usr/bin/env python3
import ipaddress
import subprocess
import time
from datetime import datetime
import os
import re
import geoip2.database

# Configuration
SOCKET = "/run/haproxy/admin.sock"
OUTPUT = "/var/lib/haproxy/active_ips.html"
FRONTEND = "VPN"
WHITELIST_FILE = "/etc/haproxy/geoip/whitelist.lst"
BLACKLIST_FILE = "/etc/haproxy/geoip/blacklist.lst"
REFRESH = 300
SLEEP = 5
MAX_ROWS = 100
GEOIP_DB = "/var/lib/GeoIP/GeoLite2-Country.mmdb"

# Loading GeoIP database
reader = geoip2.database.Reader(GEOIP_DB)

def get_country_flag(ip):
    try:
        response = reader.country(ip)
        country_code = response.country.iso_code.lower()
        return f'<img src="https://flagcdn.com/16x12/{country_code}.png" alt="{country_code}" title="{country_code.upper()}"> '
    except Exception:
        return ""

def load_networks(file_path):
    networks = []
    try:
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        networks.append(ipaddress.IPv4Network(line))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return networks

WHITELIST = load_networks(WHITELIST_FILE)
BLACKLIST = load_networks(BLACKLIST_FILE)

HTML_TEMPLATE = f"""<html>
<head><title>Connection statistics</title>
<meta http-equiv='refresh' content='{REFRESH}'>
<style>
body {{ font-family: Arial; }}
table {{ border-collapse: collapse; margin-top: 10px; margin-bottom: 20px; }}
th, td {{ border: 1px solid #333; padding: 6px 10px; text-align: center; }}
th {{ background: #eee; }}
.low {{ background-color: #d4edda; }}
.medium {{ background-color: #fff3cd; }}
.high {{ background-color: #f8d7da; }}
.blocked {{ background-color: #f5c6cb; font-weight: bold; }}
</style>
</head>
<body>
<h1>Connection statistics</h1>

<h2>Allowed active connections</h2>
<table id="allowed">
<tr><th>Date</th><th>IP</th><th>Frontend</th><th>Current connections</th><th>Total connections</th></tr>
</table>

<h2>Blocked connection attempts</h2>
<table id="blocked">
<tr><th>Date</th><th>IP</th><th>Frontend</th><th>Current connections</th><th>Total connections</th></tr>
</table>
</body>
</html>"""

def get_haproxy_table():
    try:
        output = subprocess.check_output(
            ["socat", "STDIO", SOCKET],
            input=b"show table vpn\n",
            timeout=10
        )
        lines = output.decode().splitlines()
        table = []
        for line in lines[1:]:
            if "key=" in line:
                ip_match = re.search(r'key=([\d\.]+)', line)
                cnt_match = re.search(r'conn_cnt=(\d+)', line)
                cur_match = re.search(r'conn_cur=(\d+)', line)
                if ip_match and cnt_match and cur_match:
                    table.append({
                        "ip": ip_match.group(1),
                        "cnt": int(cnt_match.group(1)),
                        "cur": int(cur_match.group(1))
                    })
        return table
    except Exception as e:
        print(f"Error getting HAProxy table: {e}")
        return []

def is_allowed(ip):
    try:
        addr = ipaddress.IPv4Address(ip)
        for net in BLACKLIST:
            if addr in net:
                return False
        for net in WHITELIST:
            if addr in net:
                return True
        return False
    except:
        return False

def get_class(cur):
    if cur > 5:
        return "high"
    elif cur >= 2:
        return "medium"
    else:
        return "low"

def ensure_html():
    if not os.path.exists(OUTPUT):
        with open(OUTPUT, "w") as f:
            f.write(HTML_TEMPLATE)

def update_table(table_id, ip, now, cur, cnt):
    try:
        with open(OUTPUT, "r") as f:
            html = f.read()

        table_pattern = f'<table id="{table_id}">(.*?)</table>'
        match = re.search(table_pattern, html, re.DOTALL)
        if not match:
            return

        table_content = match.group(1)
        rows = re.findall(r'<tr[^>]*>.*?</tr>', table_content, re.DOTALL)

        header = rows[0] if rows else ""
        other_rows = rows[1:] if len(rows) > 1 else []

        flag = get_country_flag(ip)

        updated = False
        new_rows = [header]

        for row in other_rows:
            if ip in row:  # we search for the IP directly in the line
                # get all <td> in the line
                cols = re.findall(r'<td>(.*?)</td>', row, re.DOTALL)
                new_cnt = cnt

                if table_id == "allowed":
                    row_class = get_class(cur)
                    new_row = f'<tr class="{row_class}"><td>{now}</td><td>{flag}{ip}</td><td>{FRONTEND}</td><td>{cur}</td><td>{new_cnt}</td></tr>'
                else:
                    new_row = f'<tr class="blocked"><td>{now}</td><td>{flag}{ip}</td><td>{FRONTEND}</td><td>{cur}</td><td>{new_cnt}</td></tr>'

                new_rows.append(new_row)
                updated = True
            else:
                new_rows.append(row)

        if not updated:
            if table_id == "allowed":
                row_class = get_class(cur)
                new_row = f'<tr class="{row_class}"><td>{now}</td><td>{flag}{ip}</td><td>{FRONTEND}</td><td>{cur}</td><td>{cnt}</td></tr>'
            else:
                new_row = f'<tr class="blocked"><td>{now}</td><td>{flag}{ip}</td><td>{FRONTEND}</td><td>{cur}</td><td>{cnt}</td></tr>'
            new_rows.append(new_row)

        if len(new_rows) > MAX_ROWS + 1:
            new_rows = new_rows[:MAX_ROWS + 1]

        new_table_content = f'<table id="{table_id}">\n' + "\n".join(new_rows) + "\n</table>"
        new_html = html.replace(match.group(0), new_table_content)

        with open(OUTPUT, "w") as f:
            f.write(new_html)

    except Exception as e:
        print(f"Error updating table: {e}")

def main():
    ensure_html()
    last_update = {}

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        table = get_haproxy_table()

        for entry in table:
            ip, cur, cnt = entry["ip"], entry["cur"], entry["cnt"]

            current_time = time.time()
            if ip in last_update and current_time - last_update[ip] < 5:
                continue
            last_update[ip] = current_time

            if is_allowed(ip):
                update_table("allowed", ip, now, cur, cnt)
            else:
                update_table("blocked", ip, now, cur, cnt)

        time.sleep(SLEEP)

if __name__ == "__main__":
    main()