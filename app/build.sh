#!/bin/sh
# Bouwt Controlekamer.app zonder Xcode-project. Daarna: open build/Controlekamer.app
set -eu
cd "$(dirname "$0")"
APP=build/Controlekamer.app
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
swiftc -O -parse-as-library -target arm64-apple-macos14 \
  -framework SwiftUI -framework WebKit \
  ControlRoomApp.swift -o "$APP/Contents/MacOS/ControlRoom"
cp Info.plist "$APP/Contents/"
codesign --force --sign - "$APP" >/dev/null 2>&1 || true   # ad hoc, lokaal
echo "gebouwd: $APP"
