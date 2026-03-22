#!/usr/bin/env python3
"""
setup.py — Interactive first-time setup for the Congressional Trading Tracker.

Run this once after cloning the repo:
    python3 setup.py

It will:
  1. Check your Python version
  2. Create a virtual environment and install dependencies
  3. Ask for your Gmail credentials and create a .env file
  4. Create the data/ directory
  5. Set up daily automation (macOS LaunchAgent / Linux cron / Windows Task Scheduler)
  6. Offer a test run of the full pipeline
"""

import os
import sys
import subprocess
import platform
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

VENV_DIR = os.path.join(PROJECT_DIR, "venv")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
ENV_FILE = os.path.join(PROJECT_DIR, ".env")
REQUIREMENTS = os.path.join(PROJECT_DIR, "requirements.txt")


def print_header(text):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_step(n, text):
    print(f"\n--- Step {n}: {text} ---\n")


def ask_yes_no(prompt, default="y"):
    suffix = "[Y/n]" if default == "y" else "[y/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default == "y"
    return answer in ("y", "yes")


# ─── STEP 1: CHECK PYTHON ───

def check_python():
    print_step(1, "Checking Python")

    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("ERROR: Python 3.8 or higher is required.")
        print("Download it from https://www.python.org/downloads/")
        sys.exit(1)

    print("Python version is OK.")


# ─── STEP 2: VIRTUAL ENVIRONMENT + DEPENDENCIES ───

def setup_venv():
    print_step(2, "Setting up virtual environment and dependencies")

    if os.path.exists(VENV_DIR):
        print(f"Virtual environment already exists at {VENV_DIR}")
    else:
        print("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)
        print("Virtual environment created.")

    # Determine pip path
    if platform.system() == "Windows":
        pip = os.path.join(VENV_DIR, "Scripts", "pip")
        python = os.path.join(VENV_DIR, "Scripts", "python")
    else:
        pip = os.path.join(VENV_DIR, "bin", "pip")
        python = os.path.join(VENV_DIR, "bin", "python")

    print("\nInstalling dependencies from requirements.txt...")
    subprocess.run([pip, "install", "-r", REQUIREMENTS], check=True)
    print("\nAll dependencies installed.")

    return python


# ─── STEP 3: GMAIL CREDENTIALS ───

def setup_env():
    print_step(3, "Configuring email credentials")

    if os.path.exists(ENV_FILE):
        print(f"Found existing .env file.")
        if not ask_yes_no("Overwrite it with new credentials?", default="n"):
            print("Keeping existing .env file.")
            return

    print("The tracker sends you a daily email report via Gmail.")
    print("You'll need a Gmail address and an App Password.\n")
    print("To create an App Password:")
    print("  1. Go to https://myaccount.google.com/security")
    print("  2. Make sure 2-Step Verification is ON")
    print("  3. Go to https://myaccount.google.com/apppasswords")
    print("  4. Create a new App Password for 'Mail'")
    print("  5. Copy the 16-character password\n")

    email = input("Your Gmail address: ").strip()
    if not email:
        print("Skipping — you can set this later in the .env file.")
        shutil.copy(os.path.join(PROJECT_DIR, ".env.example"), ENV_FILE)
        return

    app_password = input("Your Gmail App Password: ").strip()
    if not app_password:
        print("Skipping — you can set this later in the .env file.")
        shutil.copy(os.path.join(PROJECT_DIR, ".env.example"), ENV_FILE)
        return

    with open(ENV_FILE, "w") as f:
        f.write(f"# Gmail SMTP credentials\n")
        f.write(f"GMAIL_ADDRESS={email}\n")
        f.write(f"GMAIL_APP_PASSWORD={app_password}\n")

    print(f"\nCredentials saved to .env")
    print("(This file is in .gitignore and will NOT be committed.)")


# ─── STEP 4: DATA DIRECTORY ───

def setup_data_dir():
    print_step(4, "Creating data directory")

    if os.path.exists(DATA_DIR):
        print(f"data/ directory already exists.")
    else:
        os.makedirs(DATA_DIR)
        print(f"Created data/ directory.")

    print("(This directory stores run logs, cached trades, and is in .gitignore.)")


# ─── STEP 5: DAILY AUTOMATION ───

def setup_automation(python_path):
    print_step(5, "Setting up daily automation")

    system = platform.system()
    print(f"Detected OS: {system}\n")

    if not ask_yes_no("Set up automatic daily runs?"):
        print("Skipped. You can run the pipeline manually anytime with:")
        print(f"  {python_path} run_on_wake.py")
        return

    if system == "Darwin":
        setup_macos_launchagent(python_path)
    elif system == "Linux":
        setup_linux_cron(python_path)
    elif system == "Windows":
        setup_windows_task(python_path)
    else:
        print(f"Automatic setup not available for {system}.")
        print(f"Run manually: {python_path} run_on_wake.py")


def setup_macos_launchagent(python_path):
    """Create and install a macOS LaunchAgent that runs on login."""
    label = "com.congressional.tradingtracker"
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_path = os.path.join(plist_dir, f"{label}.plist")
    script_path = os.path.join(PROJECT_DIR, "run_on_wake.py")
    stdout_log = os.path.join(DATA_DIR, "launchagent_stdout.log")
    stderr_log = os.path.join(DATA_DIR, "launchagent_stderr.log")

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{stdout_log}</string>

    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
</dict>
</plist>
"""

    os.makedirs(plist_dir, exist_ok=True)

    # Unload old version if it exists
    if os.path.exists(plist_path):
        subprocess.run(["launchctl", "unload", plist_path],
                        capture_output=True)

    with open(plist_path, "w") as f:
        f.write(plist_content)

    subprocess.run(["launchctl", "load", plist_path], check=True)

    print(f"LaunchAgent installed at:")
    print(f"  {plist_path}")
    print(f"\nThe pipeline will run automatically each time you log in.")
    print(f"It only runs once per day — subsequent logins are skipped.")
    print(f"\nTo disable later:")
    print(f"  launchctl unload {plist_path}")


def setup_linux_cron(python_path):
    """Add a daily cron job that runs at 8 AM."""
    script_path = os.path.join(PROJECT_DIR, "run_on_wake.py")
    cron_line = f"0 8 * * * cd {PROJECT_DIR} && {python_path} {script_path} >> {DATA_DIR}/cron.log 2>&1"

    # Check if already installed
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    if "run_on_wake.py" in existing:
        print("Cron job already installed.")
        return

    new_crontab = existing.rstrip("\n") + "\n" + cron_line + "\n"
    process = subprocess.run(["crontab", "-"], input=new_crontab, text=True,
                              capture_output=True)

    if process.returncode == 0:
        print("Cron job installed. The pipeline will run daily at 8:00 AM.")
        print(f"\nTo view:    crontab -l")
        print(f"To remove:  crontab -e  (then delete the trading tracker line)")
    else:
        print(f"Failed to install cron job: {process.stderr}")
        print(f"\nAdd this line manually with 'crontab -e':")
        print(f"  {cron_line}")


def setup_windows_task(python_path):
    """Create a Windows Task Scheduler task that runs at logon."""
    script_path = os.path.join(PROJECT_DIR, "run_on_wake.py")
    task_name = "CongressionalTradingTracker"

    result = subprocess.run([
        "schtasks", "/create",
        "/tn", task_name,
        "/tr", f'"{python_path}" "{script_path}"',
        "/sc", "onlogon",
        "/rl", "limited",
        "/f",
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print(f"Windows Task '{task_name}' created successfully.")
        print("The pipeline will run each time you log in.")
        print(f"\nTo disable later:")
        print(f'  schtasks /delete /tn "{task_name}" /f')
    else:
        print(f"Failed to create scheduled task: {result.stderr}")
        print(f"\nYou can create it manually in Task Scheduler:")
        print(f"  Program: {python_path}")
        print(f"  Arguments: {script_path}")
        print(f"  Trigger: At log on")


# ─── STEP 6: TEST RUN ───

def offer_test_run(python_path):
    print_step(6, "Test run")

    print("Everything is set up! Want to do a test run now?")
    print("This will scrape current filings, score them, and send you an email.\n")

    if not ask_yes_no("Run the pipeline now?"):
        print("Setup complete! Run it anytime with:")
        print(f"  {python_path} run_on_wake.py --test")
        return

    print("\nStarting pipeline...\n")
    subprocess.run([python_path, "run_on_wake.py", "--test"])


# ─── MAIN ───

def main():
    print_header("Congressional Trading Tracker — Setup")
    print("This script will walk you through first-time setup.")
    print("It takes about 2 minutes.\n")

    check_python()
    python_path = setup_venv()
    setup_env()
    setup_data_dir()
    setup_automation(python_path)
    offer_test_run(python_path)

    print_header("Setup Complete!")
    print("Useful commands:")
    print(f"  python run_on_wake.py --test   Run the pipeline now")
    print(f"  python check_status.py         Check pipeline health")
    print(f"  python main.py                 Run pipeline (always)")
    print()


if __name__ == "__main__":
    main()
