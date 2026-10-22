"""
Context Optimization Module

Handles automatic adjustment of context size for LLM requests.
Now uses an adaptive strategy based on actual token usage instead of pre-estimation.

Strategy:
- Start with a small context (2048 by default)
- After each request, check if the context was near its limit
- If truncated or near limit: increase context and retry
- Track last N successful chunks to potentially reduce context if all fit with smaller size
"""

from typing import Optional, Dict
from dataclasses import dataclass
from collections import deque

from src.config import (
    ADAPTIVE_CONTEXT_INITIAL, ADAPTIVE_CONTEXT_STEP, ADAPTIVE_CONTEXT_STABILITY_WINDOW
)

# Maximum context size limit (can be adjusted via OLLAMA_NUM_CTX in .env)
# Most modern models support at least 32K, so we use this as a safe upper bound
MAX_CONTEXT_SIZE = 131072


# =============================================================================
# ADAPTIVE CONTEXT MANAGER
# =============================================================================

# Use configuration values from config.py
CONTEXT_STEP = ADAPTIVE_CONTEXT_STEP
INITIAL_CONTEXT_SIZE = ADAPTIVE_CONTEXT_INITIAL
STABILITY_WINDOW = ADAPTIVE_CONTEXT_STABILITY_WINDOW

# Threshold for considering context as "near limit" (95% usage)
NEAR_LIMIT_THRESHOLD = 0.95


@dataclass
class ChunkTokenUsage:
    """Token usage information for a single chunk"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    context_limit: int

    @property
    def usage_ratio(self) -> float:
        """Ratio of tokens used vs context limit"""
        if self.context_limit == 0:
            return 0.0
        return self.total_tokens / self.context_limit

    @property
    def is_near_limit(self) -> bool:
        """True if usage is close to the context limit"""
        return self.usage_ratio >= NEAR_LIMIT_THRESHOLD


class AdaptiveContextManager:
    """
    Manages context size adaptively based on actual token usage.

    Strategy:
    1. Start at INITIAL_CONTEXT_SIZE (2048)
    2. After each successful request, record token usage
    3. If usage is near limit (>=95%) or truncated: increase by CONTEXT_STEP and retry
    4. Track last STABILITY_WINDOW chunks
    5. If all recent chunks could fit in a smaller context: reduce by CONTEXT_STEP

    This avoids over-allocating context (which wastes VRAM) while ensuring
    translations complete successfully.
    """

    def __init__(self,
                 initial_context: int = INITIAL_CONTEXT_SIZE,
                 context_step: int = CONTEXT_STEP,
                 stability_window: int = STABILITY_WINDOW,
                 max_context: int = MAX_CONTEXT_SIZE,
                 log_callback: Optional[callable] = None):
        """
        Initialize the adaptive context manager.

        Args:
            initial_context: Starting context size (default: 2048)
            context_step: Amount to increase/decrease context (default: 2048)
            stability_window: Number of chunks to track for stability (default: 5)
            max_context: Maximum allowed context size (default: 131072)
            log_callback: Optional callback for logging
        """
        self.current_context = initial_context
        self.min_context = initial_context  # Never reduce below the initial context
        self.context_step = context_step
        self.stability_window = stability_window
        self.max_context = max_context
        self.log_callback = log_callback

        # Track token usage for recent chunks
        self._usage_history: deque = deque(maxlen=stability_window)

        # Track retry attempts for current chunk
        self._retry_count = 0
        self._max_retries = 10  # Safety limit

    def get_context_size(self) -> int:
        """Get the current context size to use for the next request"""
        return self.current_context

    def record_success(self, prompt_tokens: int, completion_tokens: int, context_limit: int) -> None:
        """
        Record a successful translation with its token usage.

        Args:
            prompt_tokens: Number of tokens in the prompt
            completion_tokens: Number of tokens in the completion
            context_limit: Context limit that was used
        """
        usage = ChunkTokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            context_limit=context_limit
        )
        self._usage_history.append(usage)
        self._retry_count = 0  # Reset retry count on success

        # Check if we can reduce context
        self._maybe_reduce_context()

    def should_retry_with_larger_context(self, was_truncated: bool, context_used: int) -> bool:
        """
        Determine if we should retry with a larger context.

        Args:
            was_truncated: True if the response was truncated
            context_used: Total tokens used in the request

        Returns:
            True if we should increase context and retry, False otherwise
        """
        # Check if we're at max context or max retries
        if self.current_context >= self.max_context:
            if self.log_callback:
                self.log_callback("context_adaptive",
                    f"⚠️ Already at maximum context ({self.max_context}), cannot increase further")
            return False

        if self._retry_count >= self._max_retries:
            if self.log_callback:
                self.log_callback("context_adaptive",
                    f"⚠️ Maximum retry attempts ({self._max_retries}) reached")
            return False

        # Check if context was near limit or truncated
        usage_ratio = context_used / self.current_context if self.current_context > 0 else 0
        near_limit = usage_ratio >= NEAR_LIMIT_THRESHOLD

        if was_truncated or near_limit:
            return True

        return False

    def increase_context(self) -> int:
        """
        Increase the context size by one step.

        Returns:
            The new context size
        """
        old_context = self.current_context
        self.current_context = min(self.current_context + self.context_step, self.max_context)
        self._retry_count += 1

        if self.log_callback:
            self.log_callback("context_adaptive",
                f"📈 Increasing context: {old_context} → {self.current_context} "
                f"(retry {self._retry_count}/{self._max_retries})")

        return self.current_context

    def _maybe_reduce_context(self) -> None:
        """
        Check if we can safely reduce the context size.

        We only reduce if:
        1. We have enough history (stability_window chunks)
        2. ALL recent chunks could have fit in a smaller context
        3. Current context is above the minimum (initial context for this session)
        """
        if len(self._usage_history) < self.stability_window:
            return  # Not enough history yet

        if self.current_context <= self.min_context:
            return  # Already at minimum (the initial context for this model type)

        # Calculate the maximum tokens used across all recent chunks
        max_tokens_used = max(usage.total_tokens for usage in self._usage_history)

        # Check if all chunks could fit in a smaller context
        smaller_context = max(self.current_context - self.context_step, self.min_context)

        # Don't reduce if we're already at minimum
        if smaller_context >= self.current_context:
            return

        # We need some headroom (20%) to avoid oscillation
        headroom_threshold = 0.80
        if max_tokens_used <= smaller_context * headroom_threshold:
            old_context = self.current_context
            self.current_context = smaller_context

            if self.log_callback:
                self.log_callback("context_adaptive",
                    f"📉 Reducing context: {old_context} → {self.current_context} "
                    f"(max usage was {max_tokens_used} tokens over last {self.stability_window} chunks)")

            # Clear history to start fresh tracking at new context level
            self._usage_history.clear()

    def reset(self) -> None:
        """Reset the manager to initial state"""
        self.current_context = self.min_context
        self._usage_history.clear()
        self._retry_count = 0

    def get_stats(self) -> Dict:
        """Get statistics about context usage"""
        if not self._usage_history:
            return {
                "current_context": self.current_context,
                "chunks_tracked": 0,
                "avg_usage": 0,
                "max_usage": 0,
                "min_usage": 0,
            }

        usages = [u.total_tokens for u in self._usage_history]
        return {
            "current_context": self.current_context,
            "chunks_tracked": len(self._usage_history),
            "avg_usage": sum(usages) / len(usages),
            "max_usage": max(usages),
            "min_usage": min(usages),
        }
