# Gmail Connector Setup & Architecture Guide

CogniOS integrates with Gmail using the Google OAuth 2.0 Authorization Code flow with offline access. This allows CogniOS to read, search, draft, and send emails with automatic access-token refreshes and encrypted credential storage at rest.

---

## 1. Google Cloud Setup

To connect Gmail to your local CogniOS instance:

### Step 1: Create a Project in Google Cloud Console
1. Navigate to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `CogniOS-Gmail`) or select an existing project.

### Step 2: Enable the Gmail API
1. In the navigation menu, go to **APIs & Services → Enabled APIs & Services**.
2. Click **+ ENABLE APIS AND SERVICES**.
3. Search for **Gmail API** and click **Enable**.

### Step 3: Configure the OAuth Consent Screen
1. Go to **APIs & Services → OAuth consent screen**.
2. Select User Type:
   - **External**: For personal Google accounts (`@gmail.com`) or testing.
   - **Internal**: If you are using Google Workspace within an organization.
3. Fill in required application info (App name: `CogniOS`, User support email, Developer contact).
4. Under **Scopes**, add the minimum scopes required:
   - `https://www.googleapis.com/auth/gmail.readonly` (Read and search messages)
   - `https://www.googleapis.com/auth/gmail.send` (Send emails on your behalf)
   - `https://www.googleapis.com/auth/userinfo.email` (Identify account address)
   - `openid`
5. If in **Testing** publishing status:
   - Add your Google account email under **Test users**.
   - *Note on Testing Mode*: Google expires refresh tokens for apps in "Testing" status after 7 days. When expired, CogniOS surfaces a `Reconnect Gmail` prompt. Publishing your app removes the 7-day limit.

### Step 4: Create Desktop OAuth Client Credentials
1. Go to **APIs & Services → Credentials**.
2. Click **+ CREATE CREDENTIALS → OAuth client ID**.
3. Application type: Select **Desktop app**.
4. Name: `CogniOS Desktop Client`.
5. Click **Create**.
6. Click **DOWNLOAD JSON** on the created credential and save it as `credentials.json`.

---

## 2. Connecting Gmail in CogniOS

1. Open CogniOS and navigate to **Connectors → Gmail**.
2. Click **Connect** (or **＋ Add account**).
3. Click **Choose credentials.json** and select the downloaded OAuth client JSON file.
4. Click **Connect with Google**.
5. CogniOS automatically:
   - Validates the OAuth client configuration.
   - Starts an authorization code flow requesting offline access (`access_type=offline`, `prompt=consent`).
   - Launches your system browser to Google's sign-in screen.
   - Captures the redirect callback on the local loopback server (`http://localhost:8765/oauth/callback`).
   - Exchanges the authorization code for access and refresh tokens.
   - Encrypts the refresh token and client secret using local Fernet authenticated encryption before storing on disk.
   - Verifies the account email address and marks the account as **Connected**.

---

## 3. Architecture & Security

```
CogniOS UI (GmailDetail / ConnectModal)
    ↓ (credentials.json)
OAuth Manager (cogniwork/connectors/gmail/oauth.py)
    ↓ (Exchange code → refresh_token)
Credential Manager (cogniwork/connectors/gmail/credentials.py)
    ↓ (AES-128-CBC + HMAC-SHA256 Encryption at rest)
SecretStore (secrets.json with 0600 user ACL)
    ↓ (On-demand automatic token refresh)
Gmail Client (cogniwork/connectors/gmail/client.py)
    ↓ (Injected Bearer token)
Gmail Tools (Search, Read, Send with Approval & Privacy Filters)
    ↓ (Silent omission of filtered senders/labels)
Agent / LLM
```

### Key Security Guarantees:
- **No Hardcoded Credentials**: Client secrets and tokens are never embedded in source code.
- **Encrypted at Rest**: Refresh tokens are stored encrypted using Fernet (AES-128-CBC + HMAC-SHA256) with restricted OS-level file permissions.
- **Token Isolation**: LLM agents and frontend UI never see OAuth tokens or credentials.
- **Approval Checkpoint**: Outbound emails strictly require user confirmation before execution.
- **Privacy Filters**: Senders and labels matching "Never show agents" filters are silently excluded on this machine before reaching agent context.

---

## 4. Multi-Account & Lifecycle Management

- **Multiple Mailboxes**: Multiple Google accounts can be linked side-by-side. Each account maintains its own encrypted refresh token and isolated API client.
- **Automatic Refresh**: CogniOS refreshes access tokens on demand before expiration without prompting the user.
- **Reauthorization (`REAUTH_REQUIRED`)**: If a refresh token is revoked or expired in Google Cloud, CogniOS marks the account as `REAUTH_REQUIRED` and provides a **Reconnect Gmail** button.
- **Disconnect**: Disconnecting a mailbox securely purges its encrypted tokens and credentials from local storage.
