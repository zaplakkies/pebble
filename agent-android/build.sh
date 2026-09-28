#!/usr/bin/env bash
# Test and build the signed release APK into dist/pebble-agent.apk.
# Needs the JDK, Android SDK and signing key set up as in README.md.
set -euo pipefail
cd "$(dirname "$0")"
export JAVA_HOME=${JAVA_HOME:-$HOME/android-dev/jdk}
export ANDROID_HOME=${ANDROID_HOME:-$HOME/Android/Sdk}
[ -f local.properties ] || echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew -q testDebugUnitTest lintDebug assembleRelease
mkdir -p dist
cp app/build/outputs/apk/release/app-release.apk dist/pebble-agent.apk
echo "Built $(pwd)/dist/pebble-agent.apk"
