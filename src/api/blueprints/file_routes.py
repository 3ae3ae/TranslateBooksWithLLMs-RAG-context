"""
File management routes (list, download, delete, batch operations)
"""
from flask import Blueprint, jsonify, send_from_directory, current_app

from src.api.services import FileService, PathValidator


def create_file_blueprint(output_dir):
    """
    Create and configure the file management blueprint

    Args:
        output_dir: Base directory for file operations
    """
    bp = Blueprint('files', __name__)
    file_service = FileService(output_dir)

    @bp.route('/api/files/<path:filename>', methods=['GET'])
    def download_file_by_name(filename):
        """Download a specific file by name"""
        try:
            # Validate filename
            is_valid, error = PathValidator.validate_filename(filename)
            if not is_valid:
                return jsonify({"error": error}), 400

            # Find file
            file_path = file_service.find_file(filename)
            if not file_path:
                return jsonify({"error": "File not found"}), 404

            # Determine directory for send_from_directory
            if file_path.parent == file_service.uploads_dir:
                return send_from_directory(str(file_service.uploads_dir), filename, as_attachment=True)
            else:
                return send_from_directory(output_dir, filename, as_attachment=True)

        except Exception as e:
            current_app.logger.error(f"Error downloading file {filename}: {str(e)}")
            return jsonify({"error": "Download failed", "details": str(e)}), 500

    @bp.route('/api/folders/output/open', methods=['POST'])
    def open_output_folder():
        """Open the translations output folder in the system's file explorer."""
        try:
            success, message, abs_path = file_service.open_system_folder(output_dir)
            if success:
                current_app.logger.info(f"Opened output folder: {abs_path}")
                return jsonify({"success": True, "message": message, "folder_path": abs_path})
            current_app.logger.error(f"Error opening output folder: {message}")
            return jsonify({"error": message, "folder_path": abs_path}), 500
        except Exception as e:
            current_app.logger.error(f"Error in open_output_folder: {str(e)}")
            return jsonify({"error": "Failed to open output folder", "details": str(e)}), 500

    @bp.route('/api/folders/<kind>/open', methods=['POST'])
    def open_resource_folder(kind):
        from src.config import NOVEL_CONTEXTS_DIR
        from src.utils.custom_instructions import runtime_directory
        directories = {"notes": NOVEL_CONTEXTS_DIR, "styles": runtime_directory()}
        if kind not in directories:
            return jsonify(error={"code": "not_found", "message": "Unknown folder"}), 404
        try:
            success, message, abs_path = file_service.open_system_folder(directories[kind])
            if success:
                return jsonify(success=True, message=message, folder_path=abs_path)
            return jsonify(error={"code": "open_failed", "message": message}), 500
        except OSError:
            return jsonify(error={"code": "open_failed", "message": "Failed to open folder"}), 500

    return bp
