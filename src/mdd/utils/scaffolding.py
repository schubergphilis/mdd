"""Utilities for scaffolding new Quarto projects from templates."""

import os
from pathlib import Path

from mdd.utils.logging import get_logger

log = get_logger(__name__)


def validate_directory_name(dir_name: str) -> bool:
    """Return True if dir_name is non-empty and does not start with a dash."""
    return bool(dir_name and not dir_name.startswith("-"))


def get_templates_dir() -> Path:
    """Return the path to the bundled templates directory."""
    return Path(__file__).parent.parent / "templates"


def get_template_path(template_name: str) -> Path:
    """Return the full path to a bundled template file."""
    return get_templates_dir() / template_name


def verify_template_exists(template_path: Path, template_type: str) -> bool:
    """Return True if template_path exists; print an error and return False otherwise."""
    if not template_path.exists():
        log.error("%s not found at %s", template_type, template_path)
        return False
    return True


def create_directory(target_dir: Path) -> bool:
    """Create target_dir (and parents). Return False on OSError."""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        log.exception("Could not create directory '%s'", target_dir)
        return False


def create_qmd_file(qmd_file: Path, template_qmd: Path, base_name: str) -> bool:
    """Create a QMD file from template, substituting {{TITLE}} with base_name."""
    if qmd_file.exists():
        log.error("File already exists: %s", qmd_file)
        return False

    try:
        content = template_qmd.read_text().replace("{{TITLE}}", base_name)
        qmd_file.write_text(content)
        return True
    except OSError:
        log.exception("Could not create '%s'", qmd_file)
        return False


def create_render_script(render_script: Path, template_render: Path, base_name: str) -> bool:
    """Create render.sh from template, substituting {{FILE_NAME}} with base_name."""
    try:
        content = template_render.read_text().replace("{{FILE_NAME}}", base_name)
        render_script.write_text(content)
        render_script.chmod(0o755)
        return True
    except OSError:
        log.exception("Could not create render script '%s'", render_script)
        return False


def create_template_symlink(symlink_target: Path, template_path: Path, target_dir: Path) -> bool:
    """Create a relative symlink from symlink_target to template_path."""
    try:
        rel_path = os.path.relpath(template_path, target_dir)
        symlink_target.symlink_to(rel_path)
        return True
    except OSError:
        log.exception("Could not create symlink")
        log.warning("You may need to manually copy or link to %s", template_path)
        return False


def create_quarto_project(  # noqa: PLR0911
    dir_name: str,
    qmd_template_name: str,
    output_type: str,
    templates: dict[str, str],
) -> int:
    """Create a new Quarto project with specified templates.

    Returns 0 on success, 1 on error.
    """
    if not validate_directory_name(dir_name):
        log.error("Invalid directory name '%s'", dir_name)
        return 1

    target_dir = Path(dir_name)
    base_name = target_dir.name
    qmd_file = target_dir / f"{base_name}.qmd"
    render_script = target_dir / "render.sh"

    template_qmd = get_template_path(qmd_template_name)
    template_render = get_template_path("render.sh.template")

    if not verify_template_exists(template_qmd, "QMD template"):
        return 1
    if not verify_template_exists(template_render, "Render script template"):
        return 1

    template_paths: dict[str, Path] = {}
    for symlink_name, template_name in templates.items():
        template_path = get_template_path(template_name)
        if not verify_template_exists(template_path, f"Template {template_name}"):
            return 1
        template_paths[symlink_name] = template_path

    if not create_directory(target_dir):
        return 1
    if not create_qmd_file(qmd_file, template_qmd, base_name):
        return 1
    if not create_render_script(render_script, template_render, base_name):
        return 1

    for symlink_name, template_path in template_paths.items():
        create_template_symlink(target_dir / symlink_name, template_path, target_dir)

    log.info("Created: %s", qmd_file)
    log.info("Output: %s", output_type)
    log.info("Hint: Run 'cd %s && ./render.sh' to generate the output", target_dir)

    return 0
