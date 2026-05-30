import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def assemble_html_files():
    """
    Assembles HTML files by resolving <!-- INCLUDE path --> statements
    from htdocs/index.template.html into htdocs/index.html.
    Runs automatically on FastAPI backend startup.
    """
    try:
        # Resolve paths
        # backend/app/html_assembler.py:
        # parent = app
        # parent.parent = backend
        # parent.parent.parent = project root
        base_dir = Path(__file__).resolve().parent.parent.parent
        htdocs_dir = base_dir / "htdocs"
        template_path = htdocs_dir / "index.template.html"
        output_path = htdocs_dir / "index.html"

        if not template_path.exists():
            logger.warning(
                f"HTML assembler skipped: template file not found at {template_path}"
            )
            return False

        logger.info("HTML Assembler: Assembling htdocs/index.html from template...")
        content = template_path.read_text(encoding="utf-8")

        # Regex for matching <!-- INCLUDE path -->
        # Supports paths like 'static/templates/post-reader-split.html'
        include_pattern = re.compile(r"<!--\s*INCLUDE\s+(.*?)\s*-->")

        # Track loaded files to avoid infinite loops/recursion
        loaded_files = set()

        def replacer(match):
            rel_path = match.group(1).strip()
            # Normalize and safeguard path against directory traversal
            include_file = (htdocs_dir / rel_path).resolve()

            if not include_file.is_relative_to(htdocs_dir):
                logger.error(
                    f"HTML Assembler: Directory traversal blocked for path '{rel_path}'"
                )
                return f"<!-- ERROR: Traversal blocked for {rel_path} -->"

            if str(include_file) in loaded_files:
                logger.error(
                    f"HTML Assembler: Circular dependency for '{rel_path}'"
                )
                return f"<!-- ERROR: Circular dependency for {rel_path} -->"

            if not include_file.exists():
                logger.error(
                    f"HTML Assembler: Include file not found at '{include_file}'"
                )
                return f"<!-- ERROR: Include file {rel_path} not found -->"

            logger.info(f"HTML Assembler: Including '{rel_path}'")
            loaded_files.add(str(include_file))

            # Read nested template file and recursively assemble if it contains includes
            include_content = include_file.read_text(encoding="utf-8")
            return include_pattern.sub(replacer, include_content)

        assembled_content = include_pattern.sub(replacer, content)

        # Replace {{APP_VERSION}} with the version from the script tag
        version_match = re.search(
            r"var APP_VERSION\s*=\s*'([^']+)'", assembled_content
        )
        if version_match:
            version = version_match.group(1)
            assembled_content = assembled_content.replace(
                "{{APP_VERSION}}", version
            )
            logger.info(f"HTML Assembler: APP_VERSION = {version}")

            # Also update htdocs/manifest.json icons with cache-busting version params
            manifest_path = htdocs_dir / "manifest.json"
            if manifest_path.exists():
                manifest_content = manifest_path.read_text(encoding="utf-8")
                manifest_content = re.sub(
                    r'("src"\s*:\s*"/static/icons/[^"?]+)(?:\?v=[^"]*)?"',
                    rf'\1?v={version}"',
                    manifest_content
                )
                manifest_path.write_text(manifest_content, encoding="utf-8")
                logger.info(
                    "HTML Assembler: Updated htdocs/manifest.json icons "
                    f"to v={version}"
                )

        # Write to final htdocs/index.html
        output_path.write_text(assembled_content, encoding="utf-8")
        logger.info("HTML Assembler: Successfully compiled htdocs/index.html")
        return True

    except Exception as e:
        logger.error(f"HTML Assembler failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    assemble_html_files()

