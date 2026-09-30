"""Minimal structured logging.

Only the whitelisted technical fields below can ever be written: there is no
free-form payload argument, so secrets, tokens and raw responses cannot leak
through this logger.
"""

import json
import logging

import frappe
from frappe.utils import now_datetime

from speakdo_erpnext.services.errors import safe_code

LOGGER_NAME = "speakdo"


def get_logger():
	logger = frappe.logger(LOGGER_NAME, allow_site=True, file_count=5)
	# Frappe defaults to ERROR outside the dev server, which would drop every
	# companion event. Only whitelisted technical fields reach this logger.
	logger.setLevel(logging.INFO)
	return logger


def log_event(operation, stage, status, error_code=None, http_status=None, latency_ms=None):
	record = {
		"operation": safe_code(operation, "unknown"),
		"stage": safe_code(stage, "unknown"),
		"status": safe_code(status, "unknown"),
		"error_code": safe_code(error_code),
		"http_status": int(http_status) if isinstance(http_status, int) else None,
		"latency_ms": int(latency_ms) if isinstance(latency_ms, int | float) else None,
		"timestamp": now_datetime().isoformat(),
	}
	line = json.dumps(record, sort_keys=True)
	logger = get_logger()
	if status == "error":
		logger.warning(line)
	else:
		logger.info(line)
	return record
