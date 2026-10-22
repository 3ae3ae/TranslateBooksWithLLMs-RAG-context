"""Style guides use the same runtime directory as the translation pipeline."""
from flask import Blueprint, jsonify, request
import yaml

from src.utils import custom_instructions as styles


def create_styles_blueprint():
    bp = Blueprint("styles", __name__)

    @bp.errorhandler(ValueError)
    @bp.errorhandler(yaml.YAMLError)
    def invalid(exc):
        return jsonify(error={"code": "validation_error", "message": "Invalid style name or content"}), 400

    @bp.errorhandler(FileNotFoundError)
    def missing(exc):
        return jsonify(error={"code": "not_found", "message": "Style not found"}), 404

    @bp.errorhandler(FileExistsError)
    def exists(exc):
        return jsonify(error={"code": "already_exists", "message": str(exc)}), 409

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object")
        return data

    @bp.route("/api/styles", methods=["GET", "POST"])
    def collection():
        if request.method == "GET":
            return jsonify(styles=[{**item, "name": item["filename"]} for item in styles.list_custom_instructions(styles.runtime_directory())])
        data = body()
        return jsonify(styles.save_style(data.get("name"), data, create=True)), 201

    @bp.route("/api/styles/<name>", methods=["GET", "PUT", "DELETE"])
    def style(name):
        if request.method == "GET":
            return jsonify(styles.get_style(name))
        if request.method == "PUT":
            return jsonify(styles.save_style(name, body()))
        styles.delete_style(name)
        return jsonify(deleted=True)

    @bp.post("/api/styles/<name>/duplicate")
    def duplicate(name):
        content = styles.get_style(name)
        content.pop("name")
        return jsonify(styles.save_style(body().get("name"), content, create=True)), 201

    return bp
