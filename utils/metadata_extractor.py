import logging
import os

logger = logging.getLogger(__name__)

def extract_file_metrics(file_path: str, language: str) -> dict:
    """Computes lines, comment lines, blank lines, character count, and token estimates.
    
    Processes text files locally and deterministically.
    """
    metrics = {
        "line_count": 0,
        "non_empty_lines": 0,
        "blank_lines": 0,
        "comment_lines": 0,
        "char_count": 0,
        "token_estimate": 0
    }

    if not os.path.exists(file_path):
        return metrics

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        metrics["char_count"] = len(content)
        # Approximate 1 token = 4 characters
        metrics["token_estimate"] = int(len(content) / 4)

        lines = content.splitlines()
        metrics["line_count"] = len(lines)

        # Identify comment syntax based on language
        lang_lower = language.lower()

        is_python_or_ruby = any(x in lang_lower for x in ["python", "ruby"])
        is_c_style = any(x in lang_lower for x in ["c", "c++", "java", "javascript", "typescript", "c#", "go", "php"])
        is_html_or_xml = any(x in lang_lower for x in ["html", "xml"])

        in_multiline_comment = False

        for line in lines:
            trimmed = line.strip()

            if not trimmed:
                metrics["blank_lines"] += 1
                continue

            metrics["non_empty_lines"] += 1

            # Check comments
            if is_python_or_ruby:
                if trimmed.startswith("#"):
                    metrics["comment_lines"] += 1
                elif '"""' in trimmed or "'''" in trimmed:
                    # Basic shebang/docstring heuristic
                    metrics["comment_lines"] += 1
            elif is_c_style:
                # Handle multiline C comments /* ... */
                if in_multiline_comment:
                    metrics["comment_lines"] += 1
                    if "*/" in trimmed:
                        in_multiline_comment = False
                else:
                    if trimmed.startswith("//"):
                        metrics["comment_lines"] += 1
                    elif trimmed.startswith("/*"):
                        metrics["comment_lines"] += 1
                        if "*/" not in trimmed:
                            in_multiline_comment = True
            elif is_html_or_xml:
                if in_multiline_comment:
                    metrics["comment_lines"] += 1
                    if "-->" in trimmed:
                        in_multiline_comment = False
                else:
                    if trimmed.startswith("<!--"):
                        metrics["comment_lines"] += 1
                        if "-->" not in trimmed:
                            in_multiline_comment = True
            else:
                # Default fallback
                if trimmed.startswith("#") or trimmed.startswith("//"):
                    metrics["comment_lines"] += 1

        return metrics
    except Exception as e:
        logger.error(f"Failed to extract metrics from {file_path}: {e}")
        return metrics
