
"""
Streaming SSE Proxy v2
"""

import http.server
import http.client
import json
import ssl

LISTEN_PORT = 8099
TARGET_HOST = "api.anthropic.com"
TARGET_PORT = 443
REDACT_STR = "redact-thinking"


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _forward(self, method):
        cl = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(cl) if cl > 0 else None

        hdrs = {}
        stripped = False
        for k, v in self.headers.items():
            lk = k.lower()
            if lk == 'host':
                hdrs[k] = TARGET_HOST
                continue
            if lk == 'anthropic-beta':
                parts = [p.strip() for p in v.split(',')]
                filtered = [p for p in parts if REDACT_STR not in p]
                if len(filtered) < len(parts):
                    stripped = True
                    print(f"  [STRIP] {v} -> {', '.join(filtered) if filtered else '(empty)'}")
                if filtered:
                    hdrs[k] = ', '.join(filtered)
                continue
            hdrs[k] = v

        print(f"\n[PROXY] {method} {self.path}" + (" *stripped*" if stripped else ""))

        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(TARGET_HOST, TARGET_PORT, context=ctx, timeout=300)

        try:
            conn.request(method, self.path, body=body, headers=hdrs)
            resp = conn.getresponse()

            self.send_response(resp.status)

            is_sse = False
            for k2, v2 in resp.getheaders():
                lk2 = k2.lower()
                if lk2 == 'transfer-encoding':
                    continue
                if lk2 == 'content-type' and 'text/event-stream' in v2:
                    is_sse = True
                self.send_header(k2, v2)

            if is_sse:
                self.send_header('Transfer-Encoding', 'chunked')

            self.end_headers()

            if is_sse:
                print("  [SSE] Streaming...")
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        self.wfile.write(b'0\r\n\r\n')
                        self.wfile.flush()
                        break
                    hl = format(len(chunk), 'x')
                    self.wfile.write(f"{hl}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                print("  [SSE] Stream ended")
            else:
                data = resp.read()
                self.wfile.write(data)
                self.wfile.flush()

        except Exception as e:
            print(f"  [ERR] {e}")
            try:
                self.send_response(502)
                self.end_headers()
                msg = json.dumps({"error": str(e)})
                self.wfile.write(msg.encode())
            except Exception:
                pass
        finally:
            conn.close()

    def do_POST(self):
        self._forward('POST')

    def do_GET(self):
        self._forward('GET')

    def do_OPTIONS(self):
        self._forward('OPTIONS')

    def do_DELETE(self):
        self._forward('DELETE')

    def do_PUT(self):
        self._forward('PUT')

    def do_PATCH(self):
        self._forward('PATCH')

    def log_message(self, fmt, *a):
        pass


def main():
    srv = http.server.HTTPServer(('127.0.0.1', LISTEN_PORT), Handler)
    print("=" * 55)
    print("  SSE Proxy v2")
    print("=" * 55)
    print(f"  Listen:  http://127.0.0.1:{LISTEN_PORT}")
    print(f"  Target:  https://{TARGET_HOST}")
    print(f"  Strip:   '{REDACT_STR}' from anthropic-beta")
    print()
    print("  Ctrl+C to stop")
    print("=" * 55)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        srv.shutdown()


if __name__ == '__main__':
    main()