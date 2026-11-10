"""Locate Android Studio's tools without importing the game or starting processes."""

from pathlib import Path
import os
import shutil
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "build/android/project"


def android_sdk():
    candidates = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(str(Path(local) / "Android/Sdk"))
    elif sys.platform == "darwin":
        candidates.append(str(Path.home() / "Library/Android/sdk"))
    else:
        candidates.append(str(Path.home() / "Android/Sdk"))
    for candidate in candidates:
        if candidate and (Path(candidate).expanduser() / "platform-tools").is_dir():
            return Path(candidate).expanduser().resolve()
    raise FileNotFoundError(
        "Android SDK not found. Complete Android Studio's SDK setup, or set ANDROID_HOME "
        "to the SDK directory shown in Android Studio's SDK Manager.")


def sdk_tool(sdk, directory, name):
    tool = sdk / directory / (name + (".exe" if os.name == "nt" else ""))
    if not tool.is_file():
        raise FileNotFoundError(f"Missing {tool}. Install {directory} in Android Studio's SDK Manager.")
    return str(tool)


def java_home():
    candidates = [os.environ.get("JAVA_HOME")]
    if sys.platform == "win32":
        candidates.extend(str(Path(base) / "Android/Android Studio/jbr")
                          for base in (os.environ.get("ProgramFiles", "C:/Program Files"),
                                       os.environ.get("LOCALAPPDATA", "")))
    elif sys.platform == "darwin":
        candidates.extend(str(base / "Android Studio.app/Contents/jbr/Contents/Home")
                          for base in (Path("/Applications"), Path.home() / "Applications"))
    else:
        candidates.append("/opt/android-studio/jbr")
    executable = "java.exe" if os.name == "nt" else "java"
    for candidate in candidates:
        if candidate and (Path(candidate).expanduser() / "bin" / executable).is_file():
            return Path(candidate).expanduser().resolve()
    java = shutil.which("java")
    if java and Path(java).resolve().with_name("javac.exe" if os.name == "nt" else "javac").is_file():
        return Path(java).resolve().parent.parent
    raise FileNotFoundError(
        "Java JDK not found. Install Android Studio or set JAVA_HOME to a JDK 17 or newer. "
        "Use Android Studio's bundled jbr directory when possible.")


def tool_environment(sdk):
    environment = os.environ.copy()
    environment["ANDROID_HOME"] = str(sdk)
    environment["ANDROID_SDK_ROOT"] = str(sdk)
    # Explicitly use the normal Android user directory, including when launched by an IDE.
    environment.setdefault("ANDROID_USER_HOME", str(Path.home() / ".android"))
    return environment
