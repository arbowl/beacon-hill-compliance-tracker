"""LLM-based parsing module for document confirmation.

This module provides LLM integration for automatically determining whether
discovered documents match the requirements (summary, vote record, etc.)
without requiring human intervention.
"""

import requests
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass


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
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
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
        except Exception:
            return False
    
    def make_decision(
        self, 
        content: str, 
        doc_type: str, 
        bill_id: str
    ) -> Optional[Literal["yes", "no", "unsure"]]:
        """
        Ask the LLM to make a decision about document matching.
        
        Args:
            content: The content string to analyze (e.g., "Found 'H104 Summary' in hearing Documents for H104")
            doc_type: Type of document (e.g., "summary", "vote record")
            bill_id: The bill ID (e.g., "H104")
            
        Returns:
            "yes", "no", "unsure", or None if LLM is unavailable
        """
        # Always log the attempt, even if LLM is disabled or unavailable
        if not self.config.enabled:
            self._log_audit_entry(content, doc_type, bill_id, None, "disabled")
            return None
        
        if not self.is_available():
            self._log_audit_entry(content, doc_type, bill_id, None, "unavailable")
            return None
        
        # Limit content to first 20 words to reduce token usage
        content_words = content.split()
        limited_content = ' '.join(content_words[:20])
        if len(content_words) > 20:
            limited_content += "..."
        
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
                        "temperature": 0.1,  # Low temperature for consistent responses
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
                response_lower = response_text.lower()
                if "yes" in response_lower and "no" not in response_lower and "unsure" not in response_lower:
                    decision = "yes"
                elif "no" in response_lower and "yes" not in response_lower and "unsure" not in response_lower:
                    decision = "no"
                elif "unsure" in response_lower:
                    decision = "unsure"
                else:
                    # If we can't parse the response clearly, return unsure
                    decision = "unsure"
                
                # Log the audit entry
                self._log_audit_entry(content, doc_type, bill_id, decision, raw_response, limited_content)
                return decision
            else:
                self._log_audit_entry(content, doc_type, bill_id, None, f"http_error_{response.status_code}")
                return None
                
        except Exception as e:
            self._log_audit_entry(content, doc_type, bill_id, None, f"exception_{str(e)}")
            return None
    
    def _log_audit_entry(self, content: str, doc_type: str, bill_id: str, 
                        decision: Optional[str], raw_response: str, limited_content: Optional[str] = None):
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
                "port": self.config.port
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
            prompt=config_dict.get("prompt", "Given the string \"{content}\", does it appear that this system discovered the {doc_type} for {bill_id}? Answer with one word, \"yes\", \"no\", or \"unsure\"."),
            timeout=config_dict.get("timeout", 30),
            audit_log=config_dict.get("audit_log", {})
        )
        return LLMParser(llm_config)
    except Exception:
        return None
