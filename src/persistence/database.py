"""
SQLite database manager for translation job persistence.
"""

import sqlite3
import json
import os
import time
from typing import Optional, Dict, List, Any
import threading


def sanitize_config_secrets(config: Any) -> Any:
    """Copy job data without API keys, including nested connection snapshots."""
    if isinstance(config, dict):
        return {
            k: sanitize_config_secrets(v) for k, v in config.items()
            if not (k == 'api_key' or k.endswith('_api_key'))
        }
    if isinstance(config, list):
        return [sanitize_config_secrets(v) for v in config]
    return config


class Database:
    """
    Manages SQLite database for translation job checkpoints.
    Thread-safe for concurrent access.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to database. If None, uses default path from config.
        """
        if db_path is None:
            from src.config import DATA_DIR
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(DATA_DIR / "jobs.db")

        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.RLock()

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Initialize schema
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.connection = conn
        return self._local.connection

    def _initialize_schema(self):
        """Create database tables if they don't exist."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Translation jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS translation_jobs (
                    translation_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    config JSON NOT NULL,
                    progress JSON NOT NULL,
                    translation_context JSON,
                    server_session_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paused_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)

            # Checkpoint chunks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS checkpoint_chunks (
                    translation_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    original_text TEXT NOT NULL,
                    translated_text TEXT,
                    chunk_data JSON,
                    status TEXT NOT NULL,
                    completed_at TIMESTAMP,
                    PRIMARY KEY (translation_id, chunk_index),
                    FOREIGN KEY (translation_id) REFERENCES translation_jobs(translation_id)
                        ON DELETE CASCADE
                )
            """)

            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_status
                ON translation_jobs(status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_translation
                ON checkpoint_chunks(translation_id)
            """)

            cursor.execute("DELETE FROM checkpoint_chunks WHERE translation_id NOT IN (SELECT translation_id FROM translation_jobs)")
            cursor.execute("CREATE TABLE IF NOT EXISTS job_queue (translation_id TEXT PRIMARY KEY REFERENCES translation_jobs(translation_id) ON DELETE CASCADE, position INTEGER NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS queue_state (id INTEGER PRIMARY KEY CHECK(id = 1), paused INTEGER NOT NULL, reason TEXT)")
            cursor.execute("INSERT OR IGNORE INTO queue_state VALUES (1, 0, NULL)")
            conn.commit()

    def list_jobs(self):
        with self._lock:
            ids = self._get_connection().execute("SELECT translation_id FROM translation_jobs ORDER BY created_at, rowid").fetchall()
            return [self.get_job(row[0]) for row in ids]

    def queue_state(self):
        with self._lock:
            conn = self._get_connection()
            row = conn.execute("SELECT paused, reason FROM queue_state WHERE id = 1").fetchone()
            order = [r[0] for r in conn.execute("SELECT translation_id FROM job_queue ORDER BY position, rowid")]
            return {"paused": bool(row[0]), "reason": row[1], "order": order}

    def set_queue_paused(self, paused, reason=None):
        with self._lock:
            conn = self._get_connection()
            conn.execute("UPDATE queue_state SET paused = ?, reason = ? WHERE id = 1", (bool(paused), reason))
            conn.commit()

    def set_queue_order(self, order):
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM job_queue")
                conn.executemany("INSERT INTO job_queue VALUES (?, ?)", [(tid, i) for i, tid in enumerate(order)])

    def create_job(
        self,
        translation_id: str,
        file_type: str,
        config: Dict[str, Any],
        server_session_id: Optional[str] = None
    ) -> bool:
        """
        Create a new translation job record.

        Args:
            translation_id: Unique job identifier
            file_type: Type of file (txt, srt, epub)
            config: Full translation configuration
            server_session_id: Unique identifier for the current server session

        Returns:
            True if created successfully
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                progress = {
                    'current_chunk_index': -1,
                    'total_chunks': 0,
                    'completed_chunks': 0,
                    'failed_chunks': 0,
                    'start_time': time.time(),  # Use timestamp for compatibility with existing code
                    # Marks the uniform checkpoint convention: current_chunk_index
                    # is the LAST COMPLETED unit for every format (resume = +1).
                    'resume_index_semantics': 'completed',
                }

                cursor.execute("""
                    INSERT INTO translation_jobs
                    (translation_id, status, file_type, config, progress, server_session_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    translation_id,
                    'running',
                    file_type,
                    json.dumps(sanitize_config_secrets(config)),
                    json.dumps(progress),
                    server_session_id
                ))

                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Job already exists
                return False
            except Exception as e:
                print(f"Error creating job: {e}")
                return False

    def update_job_progress(
        self,
        translation_id: str,
        current_chunk_index: Optional[int] = None,
        total_chunks: Optional[int] = None,
        completed_chunks: Optional[int] = None,
        failed_chunks: Optional[int] = None,
        status: Optional[str] = None,
        epub_accumulated_stats: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update job progress information.

        Args:
            translation_id: Job identifier
            current_chunk_index: Current chunk being processed
            total_chunks: Total number of chunks
            completed_chunks: Number of completed chunks
            failed_chunks: Number of failed chunks
            status: Job status (running, paused, completed, error)
            epub_accumulated_stats: Snapshot of cross-file accumulated EPUB
                fallback counters. Stored verbatim in the progress JSON so the
                resume path can rehydrate counters that live above the
                per-file checkpoint (token_alignment_used, fallback_used, ...).

        Returns:
            True if updated successfully
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # Get current progress
                cursor.execute(
                    "SELECT progress FROM translation_jobs WHERE translation_id = ?",
                    (translation_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False

                progress = json.loads(row['progress'])

                # Update fields
                if current_chunk_index is not None:
                    progress['current_chunk_index'] = current_chunk_index
                if total_chunks is not None:
                    progress['total_chunks'] = total_chunks
                if completed_chunks is not None:
                    progress['completed_chunks'] = completed_chunks
                if failed_chunks is not None:
                    progress['failed_chunks'] = failed_chunks
                if epub_accumulated_stats is not None:
                    progress['epub_accumulated_stats'] = epub_accumulated_stats

                # Build update query
                updates = ["progress = ?", "updated_at = CURRENT_TIMESTAMP"]
                params = [json.dumps(progress)]

                if status:
                    updates.append("status = ?")
                    params.append(status)

                    if status == 'paused':
                        updates.append("paused_at = CURRENT_TIMESTAMP")
                    elif status == 'completed':
                        updates.append("completed_at = CURRENT_TIMESTAMP")

                params.append(translation_id)

                cursor.execute(
                    f"UPDATE translation_jobs SET {', '.join(updates)} WHERE translation_id = ?",
                    params
                )

                conn.commit()
                return True
            except Exception as e:
                print(f"Error updating job progress: {e}")
                return False

    def save_chunk(
        self,
        translation_id: str,
        chunk_index: int,
        original_text: str,
        translated_text: Optional[str] = None,
        chunk_data: Optional[Dict[str, Any]] = None,
        status: str = 'completed'
    ) -> bool:
        """
        Save a translated chunk to database.

        Args:
            translation_id: Job identifier
            chunk_index: Index of the chunk
            original_text: Original text
            translated_text: Translated text (if completed)
            chunk_data: Additional chunk metadata (context_before, context_after, etc.)
            status: Chunk status (completed, failed)

        Returns:
            True if saved successfully
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT OR REPLACE INTO checkpoint_chunks
                    (translation_id, chunk_index, original_text, translated_text,
                     chunk_data, status, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    translation_id,
                    chunk_index,
                    original_text,
                    translated_text,
                    json.dumps(chunk_data) if chunk_data else None,
                    status
                ))

                conn.commit()
                callback = getattr(self, 'passage_callback', None)
                if callback and status == 'completed':
                    callback(translation_id, chunk_index, original_text, translated_text)
                return True
            except Exception as e:
                print(f"Error saving chunk: {e}")
                return False

    def get_job(self, translation_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve job information.

        Args:
            translation_id: Job identifier

        Returns:
            Job data dictionary or None if not found
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT * FROM translation_jobs WHERE translation_id = ?",
                    (translation_id,)
                )
                row = cursor.fetchone()

                if not row:
                    return None

                return {
                    'translation_id': row['translation_id'],
                    'status': row['status'],
                    'file_type': row['file_type'],
                    'config': json.loads(row['config']),
                    'progress': json.loads(row['progress']),
                    'translation_context': json.loads(row['translation_context']) if row['translation_context'] else None,
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                    'paused_at': row['paused_at'],
                    'completed_at': row['completed_at']
                }
            except Exception as e:
                print(f"Error getting job: {e}")
                return None

    def update_job_config(self, translation_id: str, config: Dict[str, Any]) -> bool:
        """
        Update the configuration of an existing job.

        Args:
            translation_id: Job identifier
            config: New configuration dictionary

        Returns:
            True if updated successfully
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute(
                    "UPDATE translation_jobs SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE translation_id = ?",
                    (json.dumps(sanitize_config_secrets(config)), translation_id)
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                print(f"Error updating job config: {e}")
                return False

    def get_chunks(self, translation_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all chunks for a job.

        Args:
            translation_id: Job identifier

        Returns:
            List of chunk dictionaries ordered by chunk_index
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT * FROM checkpoint_chunks
                    WHERE translation_id = ?
                    ORDER BY chunk_index
                """, (translation_id,))

                chunks = []
                for row in cursor.fetchall():
                    chunks.append({
                        'chunk_index': row['chunk_index'],
                        'original_text': row['original_text'],
                        'translated_text': row['translated_text'],
                        'chunk_data': json.loads(row['chunk_data']) if row['chunk_data'] else None,
                        'status': row['status'],
                        'completed_at': row['completed_at']
                    })

                return chunks
            except Exception as e:
                print(f"Error getting chunks: {e}")
                return []

    def get_chunk_status_counts(self, translation_id: str) -> Dict[str, int]:
        """Return checkpoint chunk counts grouped by current row status."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT status, COUNT(*) AS count
                    FROM checkpoint_chunks
                    WHERE translation_id = ?
                    GROUP BY status
                """, (translation_id,))
                return {
                    row['status']: row['count']
                    for row in cursor.fetchall()
                    if row['status']
                }
            except Exception as e:
                print(f"Error getting chunk status counts: {e}")
                return {}

    def get_resumable_jobs(self, max_age_days: int = 30) -> List[Dict[str, Any]]:
        """
        Get all jobs that can resume or seed an Add New Content job.

        Args:
            max_age_days: Maximum age in days for resumable jobs (default 30)

        Returns:
            List of job dictionaries
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # Only return jobs created within max_age_days
                cursor.execute("""
                    SELECT * FROM translation_jobs
                    WHERE status IN (
                        'paused', 'interrupted', 'error', 'partial', 'completed'
                    )
                    AND created_at > datetime('now', ? || ' days')
                    ORDER BY updated_at DESC
                """, (f'-{max_age_days}',))

                jobs = []
                for row in cursor.fetchall():
                    jobs.append({
                        'translation_id': row['translation_id'],
                        'status': row['status'],
                        'file_type': row['file_type'],
                        'config': json.loads(row['config']),
                        'progress': json.loads(row['progress']),
                        'created_at': row['created_at'],
                        'updated_at': row['updated_at'],
                        'paused_at': row['paused_at']
                    })

                return jobs
            except Exception as e:
                print(f"Error getting resumable jobs: {e}")
                return []

    def cleanup_old_jobs(self, max_age_days: int = 30) -> int:
        """
        Delete old jobs that are no longer relevant.

        Removes jobs older than max_age_days that are in resumable states
        (paused, interrupted, error) to prevent database bloat.

        Args:
            max_age_days: Maximum age in days for jobs to keep (default 30)

        Returns:
            Number of jobs deleted
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # Get IDs of jobs to delete (for logging and file cleanup)
                cursor.execute("""
                    SELECT translation_id FROM translation_jobs
                    WHERE status IN ('paused', 'interrupted', 'error', 'partial', 'completed')
                    AND created_at <= datetime('now', ? || ' days')
                """, (f'-{max_age_days}',))

                job_ids = [row['translation_id'] for row in cursor.fetchall()]

                if not job_ids:
                    return 0

                # Delete old jobs (chunks deleted via CASCADE)
                cursor.execute("""
                    DELETE FROM translation_jobs
                    WHERE status IN ('paused', 'interrupted', 'error', 'partial', 'completed')
                    AND created_at <= datetime('now', ? || ' days')
                """, (f'-{max_age_days}',))

                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count
            except Exception as e:
                print(f"Error cleaning up old jobs: {e}")
                return 0

    def reset_running_jobs(self, current_session_id: str) -> int:
        """
        Reset jobs with 'running' status from previous server sessions to 'interrupted'.

        Only resets jobs that have a different server_session_id than the current one,
        preserving jobs that are actually running in the current session.

        This should be called on server startup to handle jobs that were
        interrupted by a server crash or restart.

        Args:
            current_session_id: The current server's session ID

        Returns:
            Number of jobs reset
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # Reset jobs that are 'running' but from a different session
                # (or have no session_id, meaning they're from before this feature)
                cursor.execute("""
                    UPDATE translation_jobs
                    SET status = 'interrupted',
                        updated_at = CURRENT_TIMESTAMP,
                        paused_at = CURRENT_TIMESTAMP
                    WHERE status = 'running'
                    AND (server_session_id IS NULL OR server_session_id != ?)
                """, (current_session_id,))

                affected_rows = cursor.rowcount
                conn.commit()
                return affected_rows
            except Exception as e:
                print(f"Error resetting running jobs: {e}")
                return 0

    def update_translation_context(
        self,
        translation_id: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Update translation context for continuity.

        Args:
            translation_id: Job identifier
            context: Context data (last_llm_context, context_accumulator, etc.)

        Returns:
            True if updated successfully
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE translation_jobs
                    SET translation_context = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE translation_id = ?
                """, (json.dumps(context), translation_id))

                conn.commit()
                return True
            except Exception as e:
                print(f"Error updating translation context: {e}")
                return False

    def delete_job(self, translation_id: str) -> bool:
        """
        Delete a job and all its chunks (CASCADE).

        Args:
            translation_id: Job identifier

        Returns:
            True if deleted successfully
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute(
                    "DELETE FROM translation_jobs WHERE translation_id = ?",
                    (translation_id,)
                )

                conn.commit()
                return True
            except Exception as e:
                print(f"Error deleting job: {e}")
                return False

    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
