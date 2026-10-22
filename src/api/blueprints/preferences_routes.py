"""Defaults API."""
from flask import Blueprint, jsonify, request

from src.utils.preferences import SCHEMA, PreferenceValidationError, get_preferences, patch_preferences


def create_preferences_blueprint():
    bp = Blueprint("preferences", __name__)

    @bp.route("/api/preferences", methods=["GET", "PATCH"])
    def preferences():
        try:
            values = patch_preferences(request.get_json(silent=True)) if request.method == "PATCH" else get_preferences()
            return jsonify(values=values, schema=SCHEMA)
        except PreferenceValidationError as exc:
            return jsonify(error={"code": "validation_error", "message": str(exc), "details": exc.errors}), 400

    return bp
