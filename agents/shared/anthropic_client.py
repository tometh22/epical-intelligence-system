"""Shared Claude API client wrapper for Epical Intelligence System."""

import os
import logging
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8000


class AnthropicClient:
    """Wrapper around the Anthropic API client."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found. Set it in the environment or pass it explicitly."
            )
        self.client = Anthropic(api_key=self.api_key)
        logger.info("AnthropicClient initialized with model %s", MODEL)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt to Claude and return the text response.

        Args:
            system_prompt: The system-level instruction for Claude.
            user_prompt: The user-level content/question.

        Returns:
            The generated text response.
        """
        try:
            logger.debug("Sending request to Claude (system prompt length=%d, user prompt length=%d)",
                         len(system_prompt), len(user_prompt))
            message = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
            )
            response_text = message.content[0].text
            logger.info("Received response from Claude (%d chars)", len(response_text))
            return response_text
        except Exception as e:
            logger.error("Error calling Anthropic API: %s", e)
            raise
