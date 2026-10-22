"""
File service for centralized file operations
"""
import os
from pathlib import Path
from typing import Optional


class FileService:
    """Handles file operations for the translation API"""

    def __init__(self, output_dir: str):
        """
        Initialize file service

        Args:
            output_dir: Base directory for file operations
        """
        self.output_dir = Path(output_dir)
        self.uploads_dir = self.output_dir / 'uploads'

    def find_file(self, filename: str) -> Optional[Path]:
        """
        Find file in main directory or uploads subdirectory

        Args:
            filename: Name of the file to find

        Returns:
            Path object if found, None otherwise
        """
        # Try main directory first
        main_path = self.output_dir / filename
        if main_path.exists() and main_path.is_file():
            return main_path

        # Try uploads subdirectory
        upload_path = self.uploads_dir / filename
        if upload_path.exists() and upload_path.is_file():
            return upload_path

        return None

    def open_file(self, filename: str) -> tuple[bool, str, Optional[str]]:
        """
        Open a file with the system's default application

        Args:
            filename: Name of the file to open

        Returns:
            Tuple of (success, message, absolute_path)
        """
        import subprocess
        import platform

        file_path = self.find_file(filename)
        if not file_path:
            return False, "File not found", None

        abs_path = str(file_path.resolve())
        system = platform.system()

        try:
            if system == 'Windows':
                os.startfile(abs_path)
            elif system == 'Darwin':  # macOS
                subprocess.run(['open', abs_path], check=True)
            else:  # Linux and others
                subprocess.run(['xdg-open', abs_path], check=True)

            return True, f"File opened: {filename}", abs_path

        except Exception as e:
            return False, f"Failed to open file: {str(e)}", abs_path

    def open_system_folder(self, folder_path) -> tuple[bool, str, Optional[str]]:
        """
        Open any arbitrary folder in the system's file explorer.

        Args:
            folder_path: Path object or string of the folder to open

        Returns:
            Tuple of (success, message, absolute_path)
        """
        import subprocess
        import platform

        folder = Path(folder_path).resolve()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"Failed to prepare folder: {str(e)}", str(folder)

        abs_path = str(folder)
        system = platform.system()

        try:
            if system == 'Windows':
                subprocess.Popen(['explorer', abs_path], close_fds=True)
            elif system == 'Darwin':
                subprocess.run(['open', abs_path], check=True)
            else:
                subprocess.run(['xdg-open', abs_path], check=True)

            return True, f"Opened folder: {abs_path}", abs_path

        except Exception as e:
            return False, f"Failed to open folder: {str(e)}", abs_path

    def reveal_file(self, filename: str) -> tuple[bool, str, Optional[str]]:
        """
        Reveal a file in the system's file explorer (selecting the file when possible)

        Args:
            filename: Name of the file to reveal

        Returns:
            Tuple of (success, message, absolute_path)
        """
        import subprocess
        import platform

        file_path = self.find_file(filename)
        if not file_path:
            return False, "File not found", None

        abs_path = str(file_path.resolve())
        parent_dir = str(file_path.parent.resolve())
        system = platform.system()

        try:
            if system == 'Windows':
                # /select, and the path must be passed as two separate arguments,
                # otherwise subprocess quotes them together and Explorer falls back
                # to opening the user's default folder.
                # Explorer returns exit code 1 even on success, so we don't check it.
                subprocess.Popen(['explorer', '/select,', abs_path], close_fds=True)
            elif system == 'Darwin':  # macOS
                subprocess.run(['open', '-R', abs_path], check=True)
            else:  # Linux and others — most file managers don't support file selection
                subprocess.run(['xdg-open', parent_dir], check=True)

            return True, f"Revealed file: {filename}", abs_path

        except Exception as e:
            return False, f"Failed to reveal file: {str(e)}", abs_path
