"""LLM-based parsing module for document confirmation.

This module provides LLM integration for automatically determining whether
discovered documents match the requirements (summary, vote record, etc.)
without requiring human intervention.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Literal
from dataclasses import dataclass

import requests  # type: ignore


@dataclass
class LLMConfig:
    """Configuration for LLM integration."""
    enabled: bool
    host: str
    port: int
    model: str
    prompt: str
    timeout: int
    audit_log: dict


class LLMParser:
    """LLM-based parser for document confirmation decisions."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = f"http://{config.host}:{config.port}"
        self._setup_audit_logging()

    def _setup_audit_logging(self):
        """Set up audit logging if enabled."""
        self.audit_enabled = self.config.audit_log.get("enabled", False)
        if not self.audit_enabled:
            return
        # Set up file logging
        log_file = self.config.audit_log.get("file", "llm_audit.log")
        self.audit_logger = logging.getLogger("llm_audit")
        self.audit_logger.setLevel(logging.INFO)
        # Remove existing handlers to avoid duplicates
        for handler in self.audit_logger.handlers[:]:
            self.audit_logger.removeHandler(handler)
        # Create file handler
        file_handler = logging.FileHandler(
            log_file, mode='a', encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        self.audit_logger.addHandler(file_handler)
        self.audit_logger.propagate = False  # Prevent duplicate logs

    def is_available(self) -> bool:
        """Check if the LLM service is available."""
        if not self.config.enabled:
            return False
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            return response.status_code == 200
        # pylint: disable=broad-exception-caught
        except Exception:
            return False

    # pylint: disable=too-many-locals, too-many-branches
    def make_decision(
        self,
        content: str,
        doc_type: str,
        bill_id: str
    ) -> Optional[Literal["yes", "no", "unsure"]]:
        """
        Ask the LLM to make a decision about document matching.

        Args:
            content: The content string to analyze (e.g., "Found
            'H104 Summary' in hearing Documents for H104")
            doc_type: Type of document (e.g., "summary", "vote record")
            bill_id: The bill ID (e.g., "H104")

        Returns:
            "yes", "no", "unsure", or None if LLM is unavailable
        """
        # Always log the attempt, even if LLM is disabled or unavailable
        if not self.config.enabled:
            limited_content = self._truncate_content(content)
            self._log_audit_entry(
                content, doc_type, bill_id, None, "disabled", limited_content
            )
            return None

        if not self.is_available():
            limited_content = self._truncate_content(content)
            self._log_audit_entry(
                content,
                doc_type,
                bill_id,
                None,
                "unavailable",
                limited_content
            )
            return None

        # Limit content to reduce token usage and prevent timeouts
        # Strategy: Try sentence-based truncation first, then word-based, then
        # character-based
        limited_content = self._truncate_content(content)

        # Format the prompt with the provided variables
        formatted_prompt = self.config.prompt.format(
            content=limited_content,
            doc_type=doc_type,
            bill_id=bill_id
        )

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": formatted_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temperature for consistency
                        "top_p": 0.9
                    }
                },
                timeout=self.config.timeout
            )

            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()
                raw_response = response_text

                # Parse the response to extract yes/no/unsure
                # Look for the final decision at the end of the response,
                # after any reasoning
                response_lower = response_text.lower().strip()
                # Split by lines and look for the final decision
                lines = response_text.strip().split('\n')
                final_line = lines[-1].strip().lower() if lines else ""
                # Check the final line for a clear decision
                if final_line == "yes":
                    decision = "yes"
                elif final_line == "no":
                    decision = "no"
                elif final_line == "unsure":
                    decision = "unsure"
                else:
                    # Fallback: look for the decision anywhere in the response
                    # but prioritize the last occurrence
                    if "yes" in response_lower:
                        # Check if "yes" appears after any "no" or "unsure"
                        yes_pos = response_lower.rfind("yes")
                        no_pos = response_lower.rfind("no")
                        unsure_pos = response_lower.rfind("unsure")
                        if yes_pos > no_pos and yes_pos > unsure_pos:
                            decision = "yes"
                        else:
                            decision = "unsure"
                    elif "no" in response_lower:
                        decision = "no"
                    elif "unsure" in response_lower:
                        decision = "unsure"
                    else:
                        decision = "unsure"

                # Log the audit entry
                self._log_audit_entry(
                    content,
                    doc_type,
                    bill_id,
                    decision,
                    raw_response,
                    limited_content
                )
                return decision  # type: ignore
            else:
                self._log_audit_entry(
                    content,
                    doc_type,
                    bill_id,
                    None,
                    f"http_error_{response.status_code}",
                    limited_content
                )
                return None
        # pylint: disable=broad-exception-caught
        except Exception as e:
            self._log_audit_entry(
                content,
                doc_type,
                bill_id,
                None,
                f"exception_{str(e)}",
                limited_content
            )
            return None

    def _truncate_content(self, content: str) -> str:
        """
        Aggressively truncate content to prevent LLM timeouts.

        Strategy:
        1. Try to keep first 1-2 sentences (most important info is usually at
            the start)
        2. If that's still too long, fall back to first 15 words
        3. If still too long, use strict character limit as final fallback

        Args:
            content: The content string to truncate

        Returns:
            Truncated content string
        """
        if not content or len(content.strip()) == 0:
            return content

        # Remove excessive whitespace
        content = ' '.join(content.split())

        # Special handling for boilerplate content (detect common patterns)
        boilerplate_indicators = [
            "The information contained in this website is for general "
            "information purposes only",
            "Update Testimony Either add testimony in the text field",
            "Register for MyLegislature",
            "Sign in to MyLegislature",
            "Copyright © 2025 The General Court of the Commonwealth of "
            "Massachusetts"
        ]

        # If content contains boilerplate, try to extract the meaningful part
        for indicator in boilerplate_indicators:
            if indicator in content:
                # Find the position of the boilerplate and truncate before it
                boilerplate_pos = content.find(indicator)
                if boilerplate_pos > 0 and boilerplate_pos < len(content) // 2:
                    content = content[:boilerplate_pos].strip()
                    break

        # Strategy 1: Try sentence-based truncation (first 1-2 sentences)
        sentences = content.split('. ')
        if len(sentences) > 1:
            # Take first 1-2 sentences, but ensure we don't exceed length
            limited_sentences = sentences[:2]
            sentence_content = '. '.join(limited_sentences)

            # If we cut off mid-sentence, add the period back
            if not sentence_content.endswith('.'):
                sentence_content += '.'

            # If sentence-based truncation is reasonable length, use it
            if len(sentence_content) <= 200:  # Much more aggressive: 200 max
                return sentence_content

        # Strategy 2: Fall back to word-based truncation (first 15 words)
        words = content.split()
        if len(words) > 15:  # Reduced from 20 to 15 words
            word_content = ' '.join(words[:15])
            if len(word_content) <= 200:  # Much more aggressive: 200 chars max
                return word_content + "..."

        # Strategy 3: Character-based truncation as final fallback
        if len(content) > 200:  # Much more aggressive: 200 chars max
            return content[:200] + "..."

        return content

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def _log_audit_entry(
        self,
        content: str,
        doc_type: str,
        bill_id: str,
        decision: Optional[str],
        raw_response: str,
        limited_content: Optional[str] = None
    ) -> None:
        """Log an audit entry for the LLM interaction."""
        if not self.audit_enabled:
            return

        # Create audit log entry
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "bill_id": bill_id,
            "doc_type": doc_type,
            "content": content,
            "limited_content": limited_content,
            "decision": decision,
            "raw_response": raw_response,
        }
        # Add model info if configured
        if self.config.audit_log.get("include_model_info", True):
            audit_entry.update({
                "model": self.config.model,
                "host": self.config.host,
                "port": self.config.port  # type: ignore
            })
        # Log as JSON for easy parsing
        self.audit_logger.info(json.dumps(audit_entry, ensure_ascii=False))


def create_llm_parser(config_dict: dict) -> Optional[LLMParser]:
    """Create an LLM parser from configuration dictionary."""
    try:
        llm_config = LLMConfig(
            enabled=config_dict.get("enabled", False),
            host=config_dict.get("host", "localhost"),
            port=config_dict.get("port", 11434),
            model=config_dict.get("model", "llama3.2"),
            prompt=config_dict.get(
                "prompt", "Given the string \"{content}\", "
                "does it appear that this system discovered the {doc_type} "
                "for {bill_id}? Answer with one word, \"yes\", \"no\", or "
                "\"unsure\"."
            ),
            timeout=config_dict.get("timeout", 30),
            audit_log=config_dict.get("audit_log", {})
        )
        return LLMParser(llm_config)
        # pylint: disable=broad-exception-caught
    except Exception:
        return None
