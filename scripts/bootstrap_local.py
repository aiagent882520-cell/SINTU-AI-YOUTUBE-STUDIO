"""Create a safe local .env without requiring any API keys."""
from pathlib import Path
import secrets
import shutil

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def replace_or_add(content: str, key: str, value: str) -> str:
    import re
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(lambda _: line, content, count=1)
    return content.rstrip() + "\n" + line + "\n"


def main() -> None:
    if not ENV_FILE.exists():
        shutil.copyfile(EXAMPLE_FILE, ENV_FILE)
    content = ENV_FILE.read_text(encoding="utf-8")
    generated = []
    if not any(line.startswith("SINTU_ADMIN_USERNAME=") and line.split("=", 1)[1].strip()
               for line in content.splitlines()):
        content = replace_or_add(content, "SINTU_ADMIN_USERNAME", "admin")
    password_line = next((line.split("=", 1)[1].strip() for line in content.splitlines()
                          if line.startswith("SINTU_ADMIN_PASSWORD=")), "")
    if not password_line or password_line.startswith("CHANGE-THIS") or len(password_line) < 12:
        password = secrets.token_urlsafe(24)
        content = replace_or_add(content, "SINTU_ADMIN_PASSWORD", password)
        generated.append(("Admin password", password))
    secret_line = next((line.split("=", 1)[1].strip() for line in content.splitlines()
                        if line.startswith("SINTU_SESSION_SECRET=")), "")
    if not secret_line or secret_line.startswith("CHANGE-THIS") or len(secret_line) < 32:
        secret = secrets.token_hex(32)
        content = replace_or_add(content, "SINTU_SESSION_SECRET", secret)
        generated.append(("Session secret", secret))
    content = replace_or_add(content, "SINTU_AUTH_REQUIRED", "true")
    if not any(line.startswith("SINTU_COOKIE_SECURE=") for line in content.splitlines()):
        content = replace_or_add(content, "SINTU_COOKIE_SECURE", "false")
    ENV_FILE.write_text(content, encoding="utf-8")
    print("SINTU AI STUDIO local configuration is ready.")
    if generated:
        print("\nSave these local login details securely; the password is stored only in your ignored .env file:")
        print("Admin username: " + next((line.split("=", 1)[1] for line in content.splitlines()
                                       if line.startswith("SINTU_ADMIN_USERNAME=")), "admin"))
        for label, value in generated:
            if label == "Admin password":
                print(label + ": " + value)
    print("\nAI and social API keys are optional. Add them to .env later when ready.")
    print("Never upload or commit .env.")


if __name__ == "__main__":
    main()
