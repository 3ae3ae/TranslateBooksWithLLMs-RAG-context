"""Model connection CRUD and connectivity checks."""

import httpx
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from src.core.llm import connections


def create_connections_blueprint():
    bp = Blueprint("connections", __name__)

    @bp.after_request
    def error_shape(response):
        data = response.get_json(silent=True)
        if response.status_code >= 400 and isinstance(data, dict) and isinstance(data.get("error"), str):
            response.set_data(jsonify(error={"code": data.get("code", "request_failed"), "message": data["error"]}).get_data())
        return response

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    @bp.errorhandler(ValueError)
    @bp.errorhandler(BadRequest)
    @bp.errorhandler(UnsupportedMediaType)
    def invalid_request(error):
        message = str(error) if isinstance(error, ValueError) else "Request body must be a JSON object"
        return jsonify(error={"code": "invalid_request", "message": message}), 400

    @bp.errorhandler(connections.ConnectionNotFound)
    def not_found(error):
        return jsonify(error={"code": "connection_not_found", "message": str(error)}), 404

    @bp.errorhandler(httpx.HTTPStatusError)
    def provider_error(error):
        return jsonify(error={"code": "provider_http_error", "message": f"Provider returned HTTP {error.response.status_code}"}), 502

    @bp.errorhandler(httpx.RequestError)
    def request_error(error):
        return jsonify(error={"code": "connection_failed", "message": "Could not connect to the provider"}), 502

    @bp.errorhandler(OSError)
    def storage_error(error):
        return jsonify(error={"code": "storage_error", "message": "Could not read or save model connections"}), 500

    @bp.get("/api/connection-types")
    def types():
        return jsonify(types=connections.connection_types())

    @bp.get("/api/connections")
    def index():
        return jsonify(connections=connections.list_connections(), default=connections.get_default())

    @bp.post("/api/connections")
    def create():
        return jsonify(connection=connections.create_connection(body())), 201

    @bp.patch("/api/connections/<connection_id>")
    def update(connection_id):
        return jsonify(connection=connections.update_connection(connection_id, body()))

    @bp.delete("/api/connections/<connection_id>")
    def delete(connection_id):
        connections.delete_connection(connection_id)
        return jsonify(ok=True)

    @bp.post("/api/connections/<connection_id>/default")
    def make_default(connection_id):
        data = body() if request.data else {}
        if data.keys() - {"model"}:
            raise ValueError("Unknown default fields")
        return jsonify(connections.set_default(connection_id, data.get("model")))

    @bp.post("/api/connections/test")
    def test():
        return jsonify(connections.test_connection(body()))

    @bp.get("/api/connections/<connection_id>/models")
    def models(connection_id):
        return jsonify(models=connections.list_models(connection_id))

    return bp
