# Gymak mobile

Expo-managed React Native app (`expo-router`), talking to the FastAPI backend documented in
[`../backend/README.md`](../backend/README.md). This README covers a fresh clone to a running
app on an Android device: the JDK, the Android SDK, the signing-certificate check that Google
sign-in depends on, the disk a local native build actually needs, and when to stop building
locally and use `eas build` instead.

## Task scope rules

Each task in the spec's task pack (§12) names the exact files it may touch. One standing
amendment, in force for every task even when its file list doesn't name them:
`mobile/src/i18n/ar.json`, `mobile/src/i18n/en.json` and `mobile/app/(app)/_dev-gallery.tsx`
are always in scope. Everything else needs an explicit name in the task's file list.

Non-negotiable mobile rules: no hex literal in a component, no bare user-visible string,
`start`/`end` never `left`/`right`, every touchable ≥ 48 dp with a translated
`accessibilityLabel`, and `ar.json` / `en.json` keep identical key sets.

## Prerequisites

- **Node.js 20 or newer** and npm. Developed here on v24.17.0.
- **A JDK 17 or newer** — see the trap below.
- **Android Studio**, for the SDK and an emulator image.

### The JDK trap

`java -version` on your PATH is **not** necessarily the JDK Gradle uses. On this machine they
disagree:

```
$ java -version
java version "1.8.0_51"          # PATH — far too old, Gradle will not build with it

$ "$JAVA_HOME/bin/java" -version
openjdk version "21.0.10"        # JAVA_HOME — Android Studio's bundled JBR, what actually builds
```

Gradle follows `JAVA_HOME`, so a stale Java 8 on PATH is harmless *until* something invokes
`java` directly and reports a version that sends you debugging the wrong thing. Set
`JAVA_HOME` and confirm through it, not through PATH:

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"   # Windows, Android Studio's JBR
```

The spec calls for JDK 17; anything from 17 up works. The Android Studio JBR is the path of
least resistance because it ships with `keytool` (needed below) and is kept in step with the
Android Gradle Plugin.

## Android SDK

Set `ANDROID_HOME` to the SDK location — on Windows this defaults to:

```
C:\Users\<you>\AppData\Local\Android\Sdk
```

`local.properties` is **not** in the repository and must not be: it hardcodes an absolute SDK
path that is wrong on every other machine. `expo prebuild` writes it for you, which is the
recommended route. To create `android/local.properties` by hand, forward slashes are valid and
avoid the escaping trap entirely:

```properties
sdk.dir=C:/Users/<you>/AppData/Local/Android/Sdk
```

It is a Java properties file, not a shell path: a literal Windows backslash has to be doubled
(`C:\\Users\\...`), which is why the forward-slash form is less
error-prone.

## `android/` is generated, not committed

`android/` is gitignored (§11 carry-over 3 / §13.1 decision 2). `app.json` is the source of
truth; `expo prebuild` regenerates the native project deterministically from it, so a hand-edit
to `android/` is silently discarded on the next prebuild. Regenerate when you need a native
build:

```bash
cd mobile
npx expo prebuild --platform android
```

## Fresh clone to a running app

```bash
cd mobile
npm install
npm run typecheck     # tsc --noEmit
npm run test          # vitest run
```

Then either attach to a running dev client:

```bash
npm start             # expo start
```

or build and install the native app on a connected device or emulator:

```bash
npm run android       # expo run:android
```

`npm run android` is the one that needs the JDK, the SDK, `local.properties` and the disk
budget below. `npm start` alone needs none of them.

## Pointing the app at the backend

`EXPO_PUBLIC_API_BASE_URL` in `mobile/.env` decides which host the app calls. `EXPO_PUBLIC_*`
values are inlined into the JS bundle at build time, so **changing it requires restarting Metro**
— a Fast Refresh will not pick it up.

The correct value depends on where the app is running, and the two are not interchangeable:

| Running on | `EXPO_PUBLIC_API_BASE_URL` | Why |
| --- | --- | --- |
| Android emulator | `http://10.0.2.2:8000/api/v1` | `10.0.2.2` is the emulator's alias for the host loopback. `localhost` inside the emulator is the *emulator*, not your machine. |
| Physical phone (USB/Wi-Fi) | `http://<your-LAN-IP>:8000/api/v1` | The phone is a separate device; it needs a routable address. `10.0.2.2` means nothing to it. |

Find the LAN IP of the machine running `uvicorn` — the Wi-Fi adapter's address, not a WSL,
Hyper-V or VirtualBox virtual adapter, which are not reachable from the phone:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.PrefixOrigin -eq 'Dhcp' } |
  Select-Object IPAddress, InterfaceAlias
```

On this machine that is `192.168.1.7` (`Wi-Fi 2`); `172.31.0.1`, `172.21.144.1` and the
`192.168.56.x`/`192.168.88.x`/`192.168.93.x` addresses are virtual adapters and will time out
from a phone. The phone must also be on the same network — a phone on cellular data cannot
reach a private LAN address.

Start `uvicorn` bound to all interfaces, not just loopback, or nothing outside the machine can
connect at all:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### The Windows firewall rule the phone path needs

`--host 0.0.0.0` makes uvicorn *listen* on the LAN, but Windows Defender Firewall blocks the
inbound connection by default, and the failure looks exactly like a wrong IP: the request hangs
and then times out, with nothing logged server-side because the packet never arrives. The
emulator path never hits this — `10.0.2.2` is loopback, which the firewall does not filter —
so this only bites when you switch to a physical device.

Add an inbound rule once, from an **elevated** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Gymak backend (dev)" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

`-Profile Private` deliberately excludes public networks — do not open port 8000 on a café
Wi-Fi. If it still times out, confirm the active network is actually classified Private
(`Get-NetConnectionProfile`); Windows silently treats an unidentified network as Public, and the
rule above will not apply to it.

Remove it when you are done:

```powershell
Remove-NetFirewallRule -DisplayName "Gymak backend (dev)"
```

## Theme preference

The light/dark control in Settings (`system` | `light` | `dark`, default `system`) is stored
**on the device**, not on the profile:

| | |
| --- | --- |
| Where | `expo-secure-store`, key `gymak.theme.preference` |
| Values | `system` (default), `light`, `dark` |
| Code | `src/theme/themePreference.ts` (pure rules), `src/theme/useTheme.ts` (storage + provider) |

It is deliberately not a profile field. `language` and `unit_system` live on the profile because
they are account-level — the same person wants the same language on every device. A theme is
conventionally per-device: the same account on a phone at night and a tablet in daylight wants
different answers. A profile field would also mean a migration plus a network round trip before
the theme could resolve, which shows up as a flash of the wrong theme on every cold start.

Two consequences worth knowing:

- **It survives logout.** The key is namespaced `gymak.theme.*`, not `gymak.session.*`, and only
  the latter is cleared on sign-out.
- **It does not sync between devices**, by design. Reinstalling the app resets it to `system`.

SecureStore is nominally for secrets and a theme is not one. It is used anyway because §A.2
forbids adding a dependency and it is the only key-value store installed — AsyncStorage is not.
`src/auth/storage.ts` remains the only module allowed to touch SecureStore *for tokens*. If a
plain key-value store is ever added to the dependency list, this should move to it.

The stored value is read **synchronously** (`SecureStore.getItem`, available since SDK 50) in
`ThemeProvider`'s `useState` initialiser, so it is known before the first render and the app
never paints the wrong theme first. Do not convert that read to `getItemAsync` — an async read
reintroduces the flash and would force the splash to be held for a tick to hide it.

## Google sign-in: check the signing certificate first

Google sign-in fails with an opaque `DEVELOPER_ERROR` when the certificate signing your build
is not registered in `google-services.json`. That is a signing mismatch, not a code bug, and no
amount of reading `firebase.ts` will show it. Check it before debugging anything else.

There are **two different debug keystores** on a typical machine, with **different** SHA-1s.
This project pins the first one explicitly (`android/app/build.gradle`, `signingConfigs.debug`
→ `storeFile file('debug.keystore')`), so a local build is signed with it and never with the
Android default:

| Keystore | SHA-1 | Used by |
| --- | --- | --- |
| `mobile/android/app/debug.keystore` | `5e8f1606…cabf625` | this project's builds, incl. `expo run:android` |
| `~/.android/debug.keystore` | `8b4810c1…6d2bcc32` | the Android-wide default — other projects, Android Studio |

`google-services.json` carries four fingerprints: these two, plus the EAS build keystores added
in `ee4883b`. Both debug keystores are registered, so either signs a working build. List the one
you are actually using:

```bash
keytool -list -v -keystore ~/.android/debug.keystore \
        -alias androiddebugkey -storepass android -keypass android
```

Take the `SHA1:` line, lowercase it and strip the colons, then confirm it appears in
`mobile/google-services.json`:

```bash
grep certificate_hash mobile/google-services.json
```

If it does not, add that SHA-1 to the Firebase console for package `com.gymak.app` and
re-download `google-services.json` — do not edit the file by hand.

One more trap in the generated project: `release` reuses `signingConfigs.debug`
(`android/app/build.gradle`), the React Native template default. A local "release" build is
therefore still debug-signed and is not shippable — use `eas build`, which holds the real
release keystore.

A keystore is a signing key: `*.jks` and `*.keystore` are gitignored and must stay that way.

## Disk space for a local build

A local native build is not small, and most of the weight is tooling shared across projects
rather than the clone itself. Measured on a working machine:

| | | |
| --- | --- | --- |
| Android SDK (platforms 34-37.1, build-tools, 2 NDKs) | 19.2 GB | one-time, shared |
| Gradle caches (`~/.gradle`) | 9.5 GB | one-time, shared, grows |
| `mobile/node_modules` | 3.6 GB | per clone |
| `android/` build output | 1.3 GB | per clone, regenerated |

**From a machine with no Android tooling, budget 35 GB.** With the SDK and Gradle caches
already present, a fresh clone needs about **5 GB**.

A build that runs out of disk part-way fails deep inside Gradle with an error that never
mentions disk, so check free space first rather than reading the stack trace. The two NDKs are
the largest single item and are only pulled in by native modules.

## When to use `eas build` instead

Build locally when you are iterating on native config, need a debugger attached, or are
offline. Use `eas build` when:

- you do not have the 35 GB above, or want the SDK and NDKs off your machine entirely;
- you need a build signed with the **release** keystore — EAS holds it, and it is deliberately
  not in this repository;
- you are producing something for a tester to install — the `development` and `preview` profiles
  in [`eas.json`](eas.json) are `distribution: internal`, which gives an install URL rather than
  a store submission;
- CI needs a reproducible build independent of one developer's SDK layout.

```bash
npx eas build --platform android --profile development
```

The three profiles each pin `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`; `production` also sets
`autoIncrement`, and `appVersionSource` is `remote`, so EAS owns the build number rather than
`app.json`.

## Device verification: the offline check needs a non-dev build

§10.2's offline check ("wifi off, log two sets, wifi on → both show unsent, then send on retry;
Finish blocked until they do") **cannot be run literally on a development build.**

Turning the radio off also severs the dev client's Metro websocket (`10.0.2.2:8081`). React
Native's dev support then reloads the JS bundle, and P2-ADR-08's unsent-set queue is in-memory —
so it dies with the JS context and the sets you just queued disappear before you can retry them.
That is the documented design working correctly, not a defect, but it makes the check
unobservable. The symptom in `adb logcat` is:

```
ReactNativeJNI: Error occurred, shutting down websocket connection:
WebSocket exception Failed to connect to /10.0.2.2:8081
```

Two ways to verify it:

- **Preview or release build — do it the literal way.** There is no Metro websocket to sever, so
  airplane mode behaves exactly as a user's would. This is the one that counts for pre-release
  verification: run it on `eas build --profile preview`, not on a dev client.
- **Development build — stop `uvicorn` instead** of touching the radio. The API becomes
  unreachable while the dev channel stays up, which exercises the queue, the per-row retry and
  the Finish block.

The substitution is close but **not identical**, and the difference is worth knowing: stopping
uvicorn produces a connection **refused** (immediate), while turning the radio off produces a
**timeout** (slow). Those are different paths through axios's error handling — code that queues
correctly on `ECONNREFUSED` can still hang on a timeout without ever showing an unsent marker.
The dev-build substitution therefore does **not** cover timeout behaviour; only the preview/release
run does.

## Gate before every commit

```bash
npm run typecheck
npm run test
```

Both must exit 0. A green suite is not evidence the app runs — reach the change on a device
before committing.
