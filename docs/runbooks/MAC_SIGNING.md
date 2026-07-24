# Mac Signing Runbook

This runbook covers code-signing and notarization for the VTV macOS client built with Tauri.

---

## Prerequisites

- Active Apple Developer Program membership (individual or organization)
- Xcode command-line tools installed: `xcode-select --install`
- The `tauri.conf.json` at `apps/mac-client/src-tauri/tauri.conf.json` already contains the
  `bundle.macOS` signing block — update `signingIdentity` when you have a certificate

---

## Step 1: Obtain an Apple Developer Certificate

1. Sign in to [https://developer.apple.com/account](https://developer.apple.com/account)
2. Navigate to Certificates, Identifiers & Profiles
3. Create a new certificate of type "Developer ID Application" (for distribution outside the
   Mac App Store) or "Mac App Distribution" (for App Store)
4. Download the `.cer` file and double-click to install it in Keychain Access
5. Export the certificate + private key as a `.p12` file:
   - Open Keychain Access > My Certificates
   - Right-click the "Developer ID Application: <Your Name>" entry
   - Export as Personal Information Exchange (.p12)
   - Set a strong export password — you will need it as `APPLE_CERTIFICATE_PASSWORD`

---

## Step 2: Base64-encode the Certificate

GitHub Actions secrets must be plain text. Encode the `.p12` file:

```bash
base64 -i certificate.p12 | pbcopy   # macOS: copies to clipboard
# or write to a file:
base64 -i certificate.p12 > certificate.p12.b64
```

The base64 string becomes the value of the `APPLE_CERTIFICATE` secret.

---

## Step 3: Find Your Signing Identity String

```bash
security find-identity -v -p codesigning
```

The output looks like:

```
1) ABCDEF1234567890ABCDEF1234567890ABCDEF12 "Developer ID Application: Acme Corp (TEAM1234AB)"
```

The string in quotes — `Developer ID Application: Acme Corp (TEAM1234AB)` — is your
`APPLE_SIGNING_IDENTITY` value. Set this in `tauri.conf.json` `bundle.macOS.signingIdentity`
for local builds, or pass it via the environment variable in CI.

---

## Step 4: Required Environment Variables

| Variable | Description | Where to get it |
|---|---|---|
| `APPLE_CERTIFICATE` | Base64-encoded `.p12` certificate | Step 2 above |
| `APPLE_CERTIFICATE_PASSWORD` | Password set when exporting `.p12` | Step 1 above |
| `APPLE_SIGNING_IDENTITY` | Full identity string from `security find-identity` | Step 3 above |
| `APPLE_ID` | Apple ID email used for the Developer account | developer.apple.com account email |
| `APPLE_PASSWORD` | App-specific password for notarization | [appleid.apple.com](https://appleid.apple.com) > Security > App-Specific Passwords |
| `APPLE_TEAM_ID` | 10-character team identifier | developer.apple.com > Membership |

### Generate an App-Specific Password

1. Go to [https://appleid.apple.com](https://appleid.apple.com)
2. Sign in > Security > App-Specific Passwords > Generate
3. Label it "VTV Tauri CI Notarization"
4. Copy the generated password — this is `APPLE_PASSWORD`

---

## Step 5: Add Secrets to GitHub Actions

In the GitHub repository:

1. Settings > Secrets and variables > Actions > New repository secret
2. Add each variable from the table above as a separate secret

```
APPLE_CERTIFICATE
APPLE_CERTIFICATE_PASSWORD
APPLE_SIGNING_IDENTITY
APPLE_ID
APPLE_PASSWORD
APPLE_TEAM_ID
```

---

## Step 6: Tauri Action Configuration in CI

Add the following job to `.github/workflows/ci.yml` (replace the placeholder `mac-client-web`
build job when you are ready for real macOS builds):

```yaml
mac-client-build:
  runs-on: macos-latest
  if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')
  steps:
    - uses: actions/checkout@v4

    - uses: actions/setup-node@v4
      with:
        node-version: 22
        cache: npm

    - name: Install Node dependencies
      run: npm ci

    - name: Build frontend
      run: npm run build:mac

    - uses: dtolnay/rust-toolchain@stable

    - name: Install Tauri CLI
      run: cargo install tauri-cli --version "^2.0" --locked

    - name: Build and sign macOS app
      uses: tauri-apps/tauri-action@v0
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
        APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
        APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
        APPLE_ID: ${{ secrets.APPLE_ID }}
        APPLE_PASSWORD: ${{ secrets.APPLE_PASSWORD }}
        APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
      with:
        projectPath: apps/mac-client
        tagName: ${{ github.ref_name }}
        releaseName: "VTV ${{ github.ref_name }}"
        releaseBody: "See CHANGELOG for details."
        releaseDraft: true
        includeUpdaterJson: false
```

### What the action does

1. Imports the `.p12` certificate into a temporary keychain on the runner
2. Runs `cargo tauri build` which produces `VTV.app` and `VTV.dmg`
3. Signs the app bundle with the Developer ID certificate
4. Submits the DMG to Apple's notarization service using `notarytool`
5. Staples the notarization ticket to the DMG
6. Uploads the signed, notarized DMG as a GitHub Release asset

---

## Local Signing (Development)

For local test builds with signing:

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Acme Corp (TEAM1234AB)"
cd apps/mac-client
cargo tauri build
```

To build without signing (faster iteration):

```bash
cd apps/mac-client
cargo tauri build --no-bundle   # or set signingIdentity: null in tauri.conf.json
```

---

## Troubleshooting

**"No signing identity found"**
- Run `security find-identity -v -p codesigning` and verify the certificate is installed
- Check that Keychain Access shows the certificate under "My Certificates" with a private key

**"The certificate has expired"**
- Developer ID Application certificates are valid for 5 years
- Renew at developer.apple.com and repeat Steps 1-5

**Notarization rejected: "The executable does not have the hardened runtime enabled"**
- Add `--options=runtime` to codesign flags, or set `bundle.macOS.hardenedRuntime: true`
  in `tauri.conf.json`

**Notarization rejected: "A required entitlement is missing"**
- Create an entitlements file at `apps/mac-client/src-tauri/entitlements.plist`
- Set `bundle.macOS.entitlements: "entitlements.plist"` in `tauri.conf.json`
