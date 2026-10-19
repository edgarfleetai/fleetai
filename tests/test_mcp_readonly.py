"""Security regression tests for staging MCP; no database or production writes."""
import os
import unittest
from unittest.mock import patch
from flask import Flask
from fleetai.mcp_readonly import bp_mcp

class MCPTransportSecurityTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(bp_mcp)
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer " + "x" * 48}
        self.env = patch.dict(os.environ, {
            "FLEETAI_STAGING_LOCKDOWN": "1",
            "FLEETAI_MCP_BEARER_TOKEN": "x" * 48,
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def call(self, method, headers=None, params=None):
        return self.client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": method,
            "params": params if params is not None else {},
        }, headers=headers or {})

    def test_oauth_discovery_fails_closed_without_issuer(self):
        with patch.dict(os.environ, {"FLEETAI_MCP_OAUTH_ISSUER": ""}):
            response = self.client.get("/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(response.status_code, 503)

    def test_oauth_discovery_rejects_insecure_issuer(self):
        with patch.dict(os.environ, {"FLEETAI_MCP_OAUTH_ISSUER": "http://unsafe.example"}):
            response = self.client.get("/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(response.status_code, 503)

    def test_oauth_discovery_advertises_configured_issuer(self):
        with patch.dict(os.environ, {
            "FLEETAI_MCP_OAUTH_ISSUER": "https://auth.example.test",
            "FLEETAI_MCP_OAUTH_JWKS_URI": "https://auth.example.test/keys",
            "FLEETAI_MCP_OAUTH_AUDIENCE": "https://fleetai-security-staging.onrender.com/mcp",
        }):
            response = self.client.get("/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["authorization_servers"], ["https://auth.example.test"])
            self.assertEqual(response.json["scopes_supported"], ["fleetai:read"])

    def test_anonymous_cannot_list_tools(self):
        response = self.call("tools/list")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Bearer", response.headers["WWW-Authenticate"])

    def test_wrong_token_cannot_call_tools(self):
        response = self.call("tools/call", {"Authorization": "Bearer invalid"},
                             {"name": "fleet_cars"})
        self.assertEqual(response.status_code, 401)

    def test_no_secret_configured_fails_closed(self):
        with patch.dict(os.environ, {"FLEETAI_MCP_BEARER_TOKEN": ""}):
            self.assertEqual(self.call("tools/list", self.headers).status_code, 401)

    def test_production_mode_disabled_even_with_token(self):
        with patch.dict(os.environ, {"FLEETAI_STAGING_LOCKDOWN": "0"}):
            self.assertEqual(self.call("tools/list", self.headers).status_code, 404)

    def test_authenticated_tool_discovery(self):
        response = self.call("tools/list", self.headers)
        self.assertEqual(response.status_code, 200)
        names = {x["name"] for x in response.json["result"]["tools"]}
        self.assertEqual(names, {"fleet_cars", "fleet_repairs", "fleet_finance_summary"})

    def test_unknown_tool_never_queries_database(self):
        with patch("fleetai.mcp_readonly._read") as reader:
            response = self.call("tools/call", self.headers, {"name": "fleet_delete_all"})
            self.assertEqual(response.json["error"]["code"], -32602)
            reader.assert_not_called()

    def test_rejects_cross_origin(self):
        headers = dict(self.headers, Origin="https://untrusted.example")
        self.assertEqual(self.call("tools/list", headers).status_code, 403)

    def test_streamable_http_json_response(self):
        headers = dict(self.headers, Accept="application/json, text/event-stream",
                       **{"MCP-Protocol-Version": "2025-03-26"})
        response = self.call("initialize", headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.headers["MCP-Protocol-Version"], "2025-03-26")
        self.assertEqual(response.json["result"]["protocolVersion"], "2025-03-26")

    def test_rejects_unsupported_protocol_version(self):
        headers = dict(self.headers, **{"MCP-Protocol-Version": "invalid"})
        self.assertEqual(self.call("ping", headers).status_code, 400)

    def test_rejects_unsupported_accept_header(self):
        headers = dict(self.headers, Accept="image/png")
        self.assertEqual(self.call("ping", headers).status_code, 406)

    def test_oauth_challenge_includes_resource_metadata(self):
        with patch.dict(os.environ, {
            "FLEETAI_MCP_OAUTH_ISSUER": "https://issuer.example",
            "FLEETAI_MCP_OAUTH_JWKS_URI": "https://issuer.example/keys",
            "FLEETAI_MCP_OAUTH_AUDIENCE": "fleetai-api",
        }):
            response = self.call("ping")
            self.assertEqual(response.status_code, 401)
            self.assertIn('resource_metadata="http://localhost/.well-known/oauth-protected-resource/mcp"',
                          response.headers["WWW-Authenticate"])

    def test_ping(self):
        response = self.call("ping", self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["result"], {})

    def test_repair_code_must_be_short_string(self):
        with patch("fleetai.mcp_readonly._read") as reader:
            response = self.call("tools/call", self.headers, {
                "name": "fleet_repairs", "arguments": {"car_code": ["404"]}
            })
            self.assertEqual(response.json["error"]["code"], -32602)
            reader.assert_not_called()

    def test_oauth_mode_disables_static_token(self):
        with patch.dict(os.environ, {
            "FLEETAI_MCP_OAUTH_ISSUER": "https://issuer.example",
            "FLEETAI_MCP_OAUTH_JWKS_URI": "https://issuer.example/keys",
            "FLEETAI_MCP_OAUTH_AUDIENCE": "https://fleetai-security-staging.onrender.com/mcp",
        }):
            with patch("fleetai.mcp_readonly.validate_access_token", return_value=False) as verifier:
                response = self.call("tools/list", self.headers)
                self.assertEqual(response.status_code, 401)
                verifier.assert_called_once_with("x" * 48)

    def test_oauth_mode_accepts_verified_token(self):
        with patch.dict(os.environ, {
            "FLEETAI_MCP_OAUTH_ISSUER": "https://issuer.example",
            "FLEETAI_MCP_OAUTH_JWKS_URI": "https://issuer.example/keys",
            "FLEETAI_MCP_OAUTH_AUDIENCE": "https://fleetai-security-staging.onrender.com/mcp",
        }):
            with patch("fleetai.mcp_readonly.validate_access_token", return_value=True):
                response = self.call("tools/list", self.headers)
                self.assertEqual(response.status_code, 200)

    def test_tools_are_read_only(self):
        with patch("fleetai.mcp_readonly._read", return_value=[{"code": "404"}]) as reader:
            response = self.call("tools/call", self.headers, {"name": "fleet_cars", "arguments": {}})
            self.assertFalse(response.json["result"]["isError"])
            reader.assert_called_once_with("fleet_cars", {})

if __name__ == "__main__":
    unittest.main()
