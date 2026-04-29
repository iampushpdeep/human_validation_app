# Google OIDC Authentication Setup

This app uses **Streamlit's native OIDC authentication** to securely log in users with Google accounts and maintain per-user annotation files.

## Why OIDC?

✅ **Each user has their own account** - No shared credentials  
✅ **Email-based identification** - Uniquely identify annotators  
✅ **Per-user annotation files** - `annotations_user@example_com.json`  
✅ **Automatic refresh handling** - Browser session preserved  
✅ **Production-grade security** - Uses Google's OAuth2 protocol  

---

## Prerequisites

You need:
- A **Google Cloud Project** with OAuth2 credentials
- Access to **Streamlit Cloud app settings**
- The app deployed to Streamlit Cloud

---

## Step 1: Create Google OAuth2 Credentials

### 1.1 Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **"Create Project"**
3. Enter project name (e.g., "human-validation-app")
4. Click **"Create"**

### 1.2 Enable Google+ API

1. In the search bar, type **"Google+ API"**
2. Click on it and click **"Enable"**

### 1.3 Create OAuth2 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **"+ Create Credentials"** → **"OAuth client ID"**
3. If prompted, configure the OAuth consent screen:
   - User type: **External**
   - Fill in app name (e.g., "Cluster Validator")
   - Add your email as test user
   - Add scopes: `openid`, `email`, `profile`
4. Back to credentials, create OAuth client ID:
   - Application type: **Web application**
   - Name: "Streamlit App"
   - Authorized redirect URIs: Add both:
     ```
     https://share.streamlit.io/iampushpdeep/human_validation_app/oauth2callback
     http://localhost:3000/oauth2callback
     ```
     *(Replace `iampushpdeep` with your GitHub username)*
5. Click **"Create"**
6. Copy **Client ID** and **Client Secret** (you'll need these)

---

## Step 2: Generate Cookie Secret

Create a strong random string for cookie encryption:

**Option A: Using Python**
```python
import secrets
print(secrets.token_urlsafe(32))
```

**Option B: Using OpenSSL**
```bash
openssl rand -hex 32
```

Copy the generated string.

---

## Step 3: Configure Streamlit Cloud Secrets

### 3.1 Go to App Settings

1. Open your Streamlit Cloud app: `https://share.streamlit.io/iampushpdeep/human_validation_app`
2. Click the **hamburger menu** (☰) in top right
3. Select **Settings**
4. Click **Secrets** tab

### 3.2 Add OIDC Configuration

Paste this configuration (replace placeholders):

```toml
[auth]
redirect_uri = "https://share.streamlit.io/iampushpdeep/human_validation_app/oauth2callback"
cookie_secret = "YOUR_GENERATED_SECRET_HERE"
client_id = "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com"
client_secret = "YOUR_GOOGLE_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

**Example:**
```toml
[auth]
redirect_uri = "https://share.streamlit.io/iampushpdeep/human_validation_app/oauth2callback"
cookie_secret = "mK3x9pL2qR8vN6jT1hF5sD4wB7cZ0aY9e"
client_id = "1234567890-abc123def456.apps.googleusercontent.com"
client_secret = "GOCSPX-xyz123"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

### 3.3 Save

Click **"Save"** - Streamlit will auto-redeploy the app.

---

## Step 4: Test the App

1. **Refresh** your app page: `https://share.streamlit.io/iampushpdeep/human_validation_app`
2. You should see **"🔐 Log in with Google"** button
3. Click it and authenticate with your Google account
4. You'll be redirected back to the app
5. Your email should display in the sidebar

---

## Step 5: Verify Multi-User Support

### Test with Multiple Browsers/Devices

1. **User 1:** Log in with `user1@gmail.com`
   - Add some annotations
   - They save to `annotations_user1_gmail_com.json`

2. **User 2:** Log in with `user2@gmail.com` (new browser/incognito)
   - Add different annotations
   - They save to `annotations_user2_gmail_com.json`

3. **User 1 Returns:** Log back in with `user1@gmail.com`
   - Their previous annotations should load automatically

---

## How Emails Map to Files

Emails are converted to safe filenames:

| Email | Filename |
|-------|----------|
| `alice@gmail.com` | `annotations_alice_gmail_com.json` |
| `bob.smith@company.org` | `annotations_bob_smith_company_org.json` |
| `charlie+tag@email.co.uk` | `annotations_charlie+tag_email_co_uk.json` |

All files stored in: `human_validation_samples/intolerant/`

---

## Troubleshooting

### ❌ "Login not available" Error

**Problem:** OIDC configuration not recognized

**Solution:**
1. Verify secrets.toml has exactly this format:
   ```toml
   [auth]
   redirect_uri = "..."
   ```
   (Section header `[auth]` is required)
2. Check all fields are filled (no empty values)
3. Wait 2-3 minutes for app to redeploy
4. Do a hard refresh (`Cmd+Shift+R` or `Ctrl+Shift+R`)

### ❌ "Could not retrieve email from authentication"

**Problem:** Google returned user object without email

**Solution:**
1. In Google Cloud Console → APIs & Services → OAuth consent screen
2. Make sure `email` scope is added
3. Re-create OAuth credentials with correct scopes
4. Update Streamlit secrets with new credentials

### ❌ Redirect URI Mismatch

**Problem:** `Error 400: redirect_uri_mismatch`

**Solution:**
1. Check redirect_uri in secrets exactly matches Google Cloud configuration
2. Make sure it includes the username: `iampushpdeep` (not placeholder)
3. Should be: `https://share.streamlit.io/iampushpdeep/human_validation_app/oauth2callback`

### ❌ File Permissions Error on Save

**Problem:** Can't save annotations

**Solution:**
1. Check `human_validation_samples/intolerant/` directory exists and is writable
2. May need to initialize directory from local repo:
   ```bash
   mkdir -p human_validation_samples/intolerant
   git add human_validation_samples/.gitkeep  # if needed
   ```
3. Or trigger download from Google Drive to create structure

---

## Local Testing (Development)

To test locally with OIDC:

1. Update redirect_uri in `secrets.toml`:
   ```toml
   redirect_uri = "http://localhost:3000/oauth2callback"
   ```

2. Run Streamlit:
   ```bash
   streamlit run streamlit_app.py --logger.level=debug
   ```

3. Open `http://localhost:3000`
4. Login should work (uses same Google OAuth credentials)

---

## Security Notes

🔒 **Never commit secrets to GitHub**
- `secrets.toml` is in `.gitignore`
- Only stored in Streamlit Cloud

🔒 **Cookie secret is for encryption**
- Invalidate cookies if cookie_secret exposed
- Regenerate new secret immediately

🔒 **OAuth scopes limited**
- Only requests `email`, `profile`, `openid`
- No access to Google Drive, Gmail, etc.

---

## User Annotations Storage

Each user's annotations stored as:

```json
{
  "user_email": "user@gmail.com",
  "timestamp": "2024-01-15T10:30:45.123456",
  "annotations": {
    "cluster_0": {
      "label": "Pride flags",
      "rating": 5,
      "feedback": "Clear and consistent"
    },
    "cluster_1": {
      "label": "Rainbow symbols",
      "rating": 4,
      "feedback": "Some false positives"
    }
  }
}
```

Files never overlap between users due to email-based naming.

---

## Admin: Viewing All Annotations

All annotation files are in one directory:

```
human_validation_samples/intolerant/
├── annotations_user1_gmail_com.json
├── annotations_user2_company_org.json
├── cluster_0/
│   ├── images/
│   ├── videos/
│   ├── metadata.json
│   └── samples.jsonl
└── ...
```

You can combine annotations using:

```python
import json
from pathlib import Path

annotations_dir = Path("human_validation_samples/intolerant")
all_annotations = {}

for json_file in annotations_dir.glob("annotations_*.json"):
    with open(json_file) as f:
        data = json.load(f)
    all_annotations[data["user_email"]] = data["annotations"]

print(all_annotations)
```

---

## Next Steps

✅ Complete this guide  
✅ Test login with multiple users  
✅ Verify per-user annotation files  
✅ Deploy to team/stakeholders  

For issues, check app logs in Streamlit Cloud dashboard.
