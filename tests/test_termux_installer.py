from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_termux_installer_has_valid_bash_syntax():
    bash = shutil.which("bash")
    if not bash:
        return
    script = ROOT / "scripts" / "termux_one_command.sh"
    result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_hindi_readme_points_to_canonical_one_command_installer():
    readme = (ROOT / "README_HI.md").read_text(encoding="utf-8")
    assert "scripts/termux_one_command.sh" in readme
    assert "START_SINTU_TERMUX.sh" not in readme.split("## Complete video-format groups", 1)[0]
