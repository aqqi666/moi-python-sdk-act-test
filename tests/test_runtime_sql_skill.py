import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import moi_product_sdk as sdk
from loopback_http import loopback_proxy_environment


class RuntimeSQLSkillTest(unittest.TestCase):
    def test_inline_sql_and_frozen_skill_download_keep_runtime_identity(self):
        self.enterContext(loopback_proxy_environment())
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, dict(self.headers), data))
                body = json.dumps({"code": "OK", "data": {"query_id": "query-1", "status": "success", "rows_affected": 2,
                    "columns": [{"name": "note", "type": "VARCHAR"}], "result": [[{"String": "", "Valid": False}]], "truncated": True}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                requests.append((self.path, dict(self.headers), None))
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("X-MOI-Skill-Version", "7")
                self.end_headers()
                self.wfile.write(b"archive bytes")

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = sdk.Client(f"http://127.0.0.1:{server.server_port}/newmoi", sdk.with_api_key("user-key"), sdk.with_runtime_authorization("Bearer task-proof"))
            result = client.sql("workspace").run_query("SELECT NULL", sdk.with_sql_query_limit(1))
            self.assertEqual(2, result.rows_affected)
            self.assertTrue(result.truncated)
            self.assertFalse(result.result[0].values[0].struct_value.fields["Valid"].bool_value)
            stream = client.agents("workspace").download_skill_files("skill-1")
            try:
                self.assertEqual(b"archive bytes", stream.read())
            finally:
                stream.close()
            self.assertEqual(["/newmoi/query/run", "/newmoi/workspaces/workspace/skills/skill-1/runtime-files"], [item[0] for item in requests])
            for _, headers, _ in requests:
                self.assertEqual("workspace", headers["X-Workspace-Id"])
                self.assertEqual("Bearer task-proof", headers["X-Moi-Runtime-Authorization"])
                self.assertNotIn("X-Moi-Role-Id", headers)
            self.assertEqual("SELECT NULL", requests[0][2]["query"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
