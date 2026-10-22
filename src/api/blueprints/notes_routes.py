"""Story notes CRUD; the server owns the on-disk format."""
from flask import Blueprint, jsonify, request

from src.utils import notes_store as store


def create_notes_blueprint():
    bp = Blueprint("notes", __name__)

    @bp.errorhandler(ValueError)
    def invalid(exc):
        if isinstance(exc, store.NotesInUseError):
            return jsonify(error={"code": "notes_in_use", "message": str(exc), "details": {"used_by": exc.jobs}}), 409
        return jsonify(error={"code": "validation_error", "message": str(exc)}), 400

    @bp.errorhandler(FileNotFoundError)
    def missing(exc):
        return jsonify(error={"code": "not_found", "message": "Notes not found"}), 404

    @bp.errorhandler(FileExistsError)
    def exists(exc):
        return jsonify(error={"code": "already_exists", "message": "Notes already exist"}), 409

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object")
        return data

    @bp.route("/api/notes", methods=["GET", "POST"])
    def collection():
        if request.method == "GET":
            return jsonify(notes=store.list_notes())
        data = body()
        return jsonify(store.create_notes(data.get("name"), data.get("from"))), 201

    @bp.route("/api/notes/<name>", methods=["GET", "PUT", "DELETE"])
    def note(name):
        if request.method == "GET":
            return jsonify(store.get_notes(name))
        if request.method == "DELETE":
            store.delete_notes(name)
            return jsonify(deleted=True)
        data = body()
        return jsonify(store.put_notes(name, data.get("sections"), dry_run=request.args.get("dry_run") == "1"))

    @bp.post("/api/notes/<name>/rename")
    def rename(name):
        return jsonify(store.rename_notes(name, body().get("name")))

    return bp
