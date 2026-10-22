"""Estimate the same request shape accepted by job creation."""
from pathlib import Path
import zipfile
from flask import Blueprint, jsonify, request

from src.core.pricing.job_estimator import estimate_job


def create_estimate_blueprint(output_dir):
    bp = Blueprint("estimate", __name__)

    @bp.post("/api/estimate")
    def estimate():
        from src.core.llm.connections import ConnectionNotFound
        try:
            return jsonify(estimate_job(request.get_json(silent=True), Path(output_dir) / "uploads"))
        except ConnectionNotFound:
            return jsonify(error={"code": "connection_not_found", "message": "Connection not found"}), 404
        except FileNotFoundError:
            return jsonify(error={"code": "not_found", "message": "Resource not found"}), 404
        except (zipfile.BadZipFile, KeyError):
            return jsonify(error={"code": "invalid_document", "message": "Invalid source document"}), 400
        except (ValueError, TypeError) as exc:
            return jsonify(error={"code": "validation_error", "message": str(exc)}), 400

    return bp
