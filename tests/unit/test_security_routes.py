from flask import Flask, request
import pytest

from src.utils.security import get_client_ip


@pytest.mark.parametrize("headers", [
    {},
    {"X-Forwarded-For": "198.51.100.10"},
    {"X-Real-IP": "198.51.100.10"},
    {"X-Forwarded-For": "198.51.100.10", "X-Real-IP": "198.51.100.11"},
])
def test_client_ip_uses_connection_address(headers):
    app = Flask(__name__)
    with app.test_request_context(headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.2"}):
        assert get_client_ip(request) == "127.0.0.2"

