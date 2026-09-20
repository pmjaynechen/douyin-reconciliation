import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


MAX_JSON_BODY_BYTES = 1024 * 1024
MAX_FILE_BODY_BYTES = 50 * 1024 * 1024


def is_file_upload_path(path):
    return (
        path.endswith("/files")
        or path.endswith("/platform-balance-files")
        or path.endswith("/pending-settlement-files")
        or path.endswith("/test") and "/api/configuration/templates/" in path
    )


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, api, web_dir):
        super().__init__(server_address, handler_class)
        self.api = api
        self.web_dir = Path(web_dir)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "DouyinReconciliation/0.21"

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self._handle_api("GET", self.path, b"")
            return
        self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self._send_bytes(404, {"Content-Type": "text/plain; charset=utf-8"}, "没有找到页面".encode("utf-8"))
            return
        length = self._content_length(path)
        if length is None:
            return
        body = self.rfile.read(length)
        self._handle_api("POST", path, body)

    def log_message(self, format_string, *args):
        print("{} - {}".format(self.address_string(), format_string % args))

    def _content_length(self, path):
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._send_api_error(411, "请求缺少内容长度")
            return None
        try:
            length = int(raw_length)
        except ValueError:
            self._send_api_error(400, "内容长度无效")
            return None
        is_file_upload = is_file_upload_path(path)
        max_bytes = MAX_FILE_BODY_BYTES if is_file_upload else MAX_JSON_BODY_BYTES
        if length < 0 or length > max_bytes:
            message = "Excel文件不能超过50MB" if is_file_upload else "请求内容过大"
            self._send_api_error(413, message)
            return None
        return length

    def _send_api_error(self, status, message):
        payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, {"Content-Type": "application/json; charset=utf-8"}, payload)

    def _handle_api(self, method, path, body):
        request_headers = {key: value for key, value in self.headers.items()}
        status, headers, payload = self.server.api.handle(
            method, path, body, request_headers
        )
        self._send_bytes(status, headers, payload)

    def _serve_static(self, path):
        static_map = {
            "/": "index.html",
            "/index.html": "index.html",
            "/assets/app.js": "app.js",
            "/assets/styles.css": "styles.css",
        }
        relative = static_map.get(path)
        if relative is None:
            self._send_bytes(404, {"Content-Type": "text/plain; charset=utf-8"}, "没有找到页面".encode("utf-8"))
            return
        file_path = self.server.web_dir / relative
        try:
            content = file_path.read_bytes()
        except OSError:
            self._send_bytes(500, {"Content-Type": "text/plain; charset=utf-8"}, "页面文件读取失败".encode("utf-8"))
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self._send_bytes(200, {"Content-Type": content_type, "Cache-Control": "no-store"}, content)

    def _send_bytes(self, status, headers, payload):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(payload)


def run_server(host, port, api, web_dir):
    server = AppServer((host, port), RequestHandler, api, web_dir)
    print("抖店对账已启动：http://{}:{}".format(host, port))
    print("按 Control+C 停止。数据保存在本机 var 目录。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止抖店对账……")
    finally:
        server.server_close()
