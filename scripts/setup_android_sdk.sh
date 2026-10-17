#!/usr/bin/env bash
# Set up Android build toolchain on this Windows machine (Git Bash).
# Idempotent: each step is skipped if already done.
set -x

SDK_DIR="/c/Users/yang2/Android/Sdk"
TOOLS_ZIP="/tmp/cmdtools.zip"

# --- 1) JDK 17 ---
JAVA_BIN=""
for d in "/c/Program Files/Microsoft"/jdk-17*; do
  [ -x "$d/bin/java.exe" ] && JAVA_BIN="$d"
done
if [ -z "$JAVA_BIN" ]; then
  winget install --id Microsoft.OpenJDK.17 --silent \
    --accept-source-agreements --accept-package-agreements
  for d in "/c/Program Files/Microsoft"/jdk-17*; do
    [ -x "$d/bin/java.exe" ] && JAVA_BIN="$d"
  done
fi
export JAVA_HOME="$(cygpath -w "$JAVA_BIN")"
export PATH="$JAVA_BIN/bin:$PATH"
echo "JAVA_HOME=$JAVA_HOME"
java -version || exit 1

# --- 2) Android command-line tools ---
if [ ! -x "$SDK_DIR/cmdline-tools/latest/bin/sdkmanager.bat" ]; then
  mkdir -p "$SDK_DIR/cmdline-tools"
  curl -fL -o "$TOOLS_ZIP" \
    https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip || exit 1
  rm -rf "$SDK_DIR/cmdline-tools/latest" /tmp/cmdtools-extract
  mkdir -p /tmp/cmdtools-extract
  unzip -q -o "$TOOLS_ZIP" -d /tmp/cmdtools-extract || exit 1
  mv /tmp/cmdtools-extract/cmdline-tools "$SDK_DIR/cmdline-tools/latest"
fi

SDKMGR="$SDK_DIR/cmdline-tools/latest/bin/sdkmanager.bat"
export ANDROID_HOME="$(cygpath -w "$SDK_DIR")"
export ANDROID_SDK_ROOT="$ANDROID_HOME"

# --- 3) SDK packages ---
yes | "$SDKMGR" --licenses
"$SDKMGR" "platform-tools" "platforms;android-34" "build-tools;34.0.0" || exit 1

# --- 4) Gradle (standalone; generates the project wrapper later) ---
if [ ! -x "/c/Users/yang2/gradle/gradle-8.9/bin/gradle.bat" ]; then
  mkdir -p /c/Users/yang2/gradle
  curl -fL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-8.9-bin.zip || exit 1
  unzip -q -o /tmp/gradle.zip -d /c/Users/yang2/gradle || exit 1
fi
export PATH="/c/Users/yang2/gradle/gradle-8.9/bin:$PATH"
gradle --version || exit 1

echo "ANDROID SETUP COMPLETE"
