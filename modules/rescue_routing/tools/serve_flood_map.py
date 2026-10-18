"""Simple background HTTP server for HighWater Map and Dashboard."""
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

log_file = os.path.join(os.path.dirname(__file__), "server.log")
log_fp = open(log_file, "a", encoding="utf-8")
sys.stdout = log_fp
sys.stderr = log_fp

serve_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules", "flood_analysis"))
os.chdir(serve_dir)

print(f"Serving {serve_dir} on 0.0.0.0:8080", flush=True)

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        log_fp.write(f"{self.address_string()} - - [{self.log_date_time_string()}] {format % args}\n")
        log_fp.flush()

try:
    httpd = HTTPServer(("0.0.0.0", 8080), QuietHandler)
    httpd.serve_forever()
except BaseException as e:
    import traceback
    log_fp.write(f"Crash: {e}\n{traceback.format_exc()}\n")
    log_fp.flush()


