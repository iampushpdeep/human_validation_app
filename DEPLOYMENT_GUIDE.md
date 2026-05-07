# Streamlit Cloud Deployment Guide

Quick reference for deploying the human validation app to Streamlit Cloud with multi-user support.

## Quick Start (TL;DR)

```bash
# 1. Ensure repo is on GitHub (iampushpdeep/human_validation_app)
git remote -v

# 2. Push latest changes
git push origin main

# 3. Go to https://share.streamlit.io
# 4. Click "New app" → Select your repo, branch (main), script (streamlit_app.py)
# 5. Wait for deployment
# 6. Go to Settings → Secrets, add OIDC config (see OIDC_SETUP.md)
# 7. App auto-redeploys
# 8. Done! Share link with users
```

---

## Prerequisites

- ✅ GitHub account with [iampushpdeep/human_validation_app](https://github.com/iampushpdeep/human_validation_app) repo
- ✅ Streamlit Cloud account (free tier works)
- ✅ Google Cloud Project with OAuth2 credentials (see [OIDC_SETUP.md](OIDC_SETUP.md))

---

## Full Deployment Steps

### Step 1: Prepare GitHub Repository

**Verify remote is set:**
```bash
cd human_validation_app
git remote -v
# Should show: origin	https://github.com/iampushpdeep/human_validation_app.git
```

**Push latest changes:**
```bash
git add -A
git commit -m "Deployment ready"
git push origin main
```

### Step 2: Deploy to Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Sign in with GitHub
3. Click **"New app"**
4. Select repository: **iampushpdeep/human_validation_app**
5. Select branch: **main**
6. Select main file: **streamlit_app.py**
7. Click **"Deploy"**

*Deployment takes 1-2 minutes. You'll see logs in real-time.*

### Step 3: Configure OIDC Authentication

**After deployment completes:**

1. Click the **hamburger menu** (☰) → **Settings**
2. Click **Secrets** tab
3. Paste OIDC configuration:
   ```toml
   [auth]
   redirect_uri = "https://share.streamlit.io/iampushpdeep/human_validation_app/oauth2callback"
   cookie_secret = "YOUR_SECRET_HERE"
   client_id = "YOUR_CLIENT_ID.apps.googleusercontent.com"
   client_secret = "YOUR_CLIENT_SECRET"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
4. Click **"Save"**
5. App auto-redeploys (watch logs)

### Step 4: Test & Share

1. **Refresh the app** - should show login button
2. **Test login** with your Google account
3. **Create test annotation** to verify saving works
4. **Share link** with users: `https://share.streamlit.io/iampushpdeep/human_validation_app`

---

## Dependencies

The `requirements.txt` includes all needed packages:

```
streamlit>=1.40.0
Pillow>=10.2.0
opencv-python>=4.9.0
numpy>=1.26.0
jsonlines>=4.0.0
gdown>=5.0.0
```

✅ All compatible with Streamlit Cloud Python 3.14 runtime

---

## Data Management

### Option A: Local Data (for testing)

Place data in workspace before deployment:
```
human_validation_samples/
└── intolerant/
    ├── cluster_0/
    ├── cluster_1/
    └── metadata.json
```

**Limitation:** Data lost on container restart (Streamlit Cloud rebuilds weekly)

### Option B: Google Drive (Recommended)

Data auto-downloads from Google Drive folder:
- Folder ID: `1ALgCnMWeFumIE9_9O9-MkwojgirYY4Fp`
- App downloads on first run
- Persists in app cache directory

**Advantage:** Data survives container restarts

---

## File Structure on Streamlit Cloud

```
/app/
├── streamlit_app.py          # Main app (runs on deployment)
├── requirements.txt          # Dependencies (auto-installed)
├── .streamlit/
│   └── secrets.toml          # OIDC config (in Settings → Secrets UI)
└── human_validation_samples/ # Downloaded from Google Drive or local
    └── intolerant/
        ├── annotations_user1_gmail_com.json  # Auto-created
        ├── annotations_user2_company_org.json
        ├── cluster_0/
        │   ├── images/
        │   ├── videos/
        │   ├── metadata.json
        │   └── samples.jsonl
        └── ...
```

---

## Environment Variables

Currently not needed (all config via `secrets.toml`).

Optional for future use:
```bash
# Not currently implemented
STREAMLIT_SERVER_HEADLESS = "true"
STREAMLIT_SERVER_PORT = "8501"
```

---

## Troubleshooting Deployments

### ❌ "Build failed"

**Check app logs:**
1. Go to app
2. Click hamburger (☰) → **Settings** → **Advanced settings**
3. Watch build logs at bottom

**Common causes:**
- Invalid Python syntax in `streamlit_app.py`
- Missing package in `requirements.txt`
- Incompatible package version

**Fix:**
1. Fix issue locally
2. Test: `streamlit run streamlit_app.py`
3. Push: `git push origin main`
4. Redeploy manually or wait for auto-sync

### ❌ App crashes immediately

**Check logs:**
1. Click **Settings** → **Advanced settings** → scroll to app output logs
2. Search for `ERROR` or `Traceback`

**Common causes:**
- Import error (missing package)
- File not found (`human_validation_samples/` doesn't exist)
- Google Drive download failed

**Fix:**
1. Ensure data exists locally or is downloadable from Google Drive
2. Check `requirements.txt` has all imports
3. Add error handling in code

### ❌ Users can't save annotations

**Symptoms:**
- "Error saving annotations" message
- `annotations_*.json` files not created

**Check:**
1. Is user logged in? (email shown in sidebar)
2. Are they a test user in Google OAuth consent screen?
3. Do directory permissions allow writes?

**Fix:**
1. Add more test users to Google OAuth
2. Manually create `human_validation_samples/intolerant/` directory
3. Check Streamlit logs for permission errors

---

## Monitoring

### View App Logs

1. Go to app → hamburger (☰)
2. **Settings** → **Advanced settings**
3. Scroll to **App logs** section

### View Deployment Logs

1. On app home page
2. Look at deployment history (right sidebar)
3. Click deployment to see build logs

### Check per-user progress

**Via admin interface (local):**
```python
import json
from pathlib import Path

# Count annotations per user
intolerant_dir = Path("human_validation_samples/intolerant")
for json_file in sorted(intolerant_dir.glob("annotations_*.json")):
    data = json.load(open(json_file))
    count = len([v for v in data["annotations"].values() if v])
    print(f"{data['user_email']}: {count} annotations")
```

---

## Maintenance

### Updating Code

```bash
# 1. Make changes locally
code streamlit_app.py

# 2. Test
streamlit run streamlit_app.py

# 3. Commit
git add streamlit_app.py
git commit -m "Fix: description of change"

# 4. Push (auto-triggers deployment)
git push origin main

# 5. Watch deploy progress
# Go to app → Settings → Logs
```

### Updating Dependencies

```bash
# 1. Update requirements.txt
# code requirements.txt

# 2. Test locally
pip install -r requirements.txt
streamlit run streamlit_app.py

# 3. Commit and push
git add requirements.txt
git commit -m "Update dependencies"
git push origin main
```

### Backing Up Annotations

**Download all user annotations:**

```bash
# Via Streamlit Cloud web terminal (if available)
# Or download manually via settings

# Option: Download files locally
scp user@streamlit:/app/human_validation_samples/intolerant/*.json ./backups/
```

### Clearing Cached Data

If you need to force re-download Google Drive folder:

```bash
# In Streamlit Cloud terminal (if available)
rm -rf human_validation_samples/

# Or via app code - add to streamlit_app.py:
# if st.button("🗑️ Clear Cache"):
#     import shutil
#     shutil.rmtree("human_validation_samples")
```

---

## Performance Tips

✅ **Good:**
- Images already blurred/processed
- Videos served as MP4 (native browser support)
- Per-user files are small JSON (~50KB each)
- Streamlit caches cluster data in session state

⚠️ **Potential issues:**
- Large videos (>100MB) may have playback issues
- Google Drive download on first run takes 30-60 seconds
- Concurrent users (10+) may slow down cluster loads

---

## Scaling Considerations

**Current limits:**
- Streamlit Cloud free tier: 1 concurrent app instance
- Storage: 1GB container (ephemeral)
- Monthly restart: Full data re-download

**To handle more users:**
1. Upgrade to Streamlit Cloud paid tier (multiple workers)
2. Use persistent storage (Google Drive stays)
3. Consider S3 or database for annotations (currently just JSON)

---

## Rollback

If deployment breaks, revert to previous version:

```bash
# 1. Check git log
git log --oneline -5

# 2. Revert to known-good commit
git revert COMMIT_HASH

# 3. Push
git push origin main

# 4. Streamlit Cloud auto-redeploys
```

---

## Support

- **Streamlit Docs:** [docs.streamlit.io](https://docs.streamlit.io)
- **Streamlit Cloud Help:** [share.streamlit.io/settings/help](https://share.streamlit.io/settings/help)
- **GitHub Issues:** [iampushpdeep/human_validation_app/issues](https://github.com/iampushpdeep/human_validation_app/issues)

---

## Google Sheets Backend Setup (NEW: Autosave + Resume)

The app now supports Google Sheets for persistent annotation storage with automatic saving and resume functionality. This replaces the local JSON-per-user approach.

### What's New?

✨ **Autosave**: Annotations automatically save to Google Sheets after each rating  
✨ **Resume**: Return to the app and continue where you left off  
✨ **Retry Logic**: Automatic retry on network failures (3 attempts with backoff)  
✨ **Auditability**: All annotations stored in a shared Google Sheet (easier for exports)

### Setup Instructions

#### 1. Create Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com)
2. Click **"+ Blank spreadsheet"**
3. Rename to: `cluster_validator_annotations`
4. Add column headers in **Row 1**:
   ```
   A: user_name
   B: cluster_cid
   C: appropriateness_rating
   D: follow_up_answers
   E: suggested_name
   F: notes
   G: timestamp
   ```

#### 2. Set Up Google Apps Script

1. In your Google Sheet, go to **Extensions** → **Apps Script**
2. Delete default code, replace with code from `GOOGLE_APPS_SCRIPT_TEMPLATE.gs` (in this repo)
3. Save the script (Ctrl+S or Cmd+S)
4. Click **"Deploy"** → **"New deployment"**
   - Type: Select **"Web app"**
   - Execute as: **Your account**
   - Who has access: **"Anyone"**
5. Click **"Deploy"** and copy the deployment URL
   - It looks like: `https://script.google.com/macros/d/{DEPLOYMENT_ID}/usercurrent/do?userAccessType=ANYONE`

#### 3. Configure Secrets

**Locally (for testing):**
1. Create or edit `.streamlit/secrets.toml`
2. Add:
   ```toml
   GOOGLE_APPS_SCRIPT_URL = "https://script.google.com/macros/d/{DEPLOYMENT_ID}/usercurrent/do?userAccessType=ANYONE"
   GOOGLE_SHEET_READ_URL = "https://script.google.com/macros/d/{DEPLOYMENT_ID}/usercurrent/do?userAccessType=ANYONE"
   ```
3. Replace `{DEPLOYMENT_ID}` with your deployment ID from step 2
4. Save and test: `streamlit run streamlit_app.py`

**On Streamlit Cloud:**
1. Go to your deployed app
2. Click hamburger (☰) → **Settings** → **Secrets**
3. Paste the same secrets as above
4. Click **"Save"** - app auto-redeploys

#### 4. Test the Setup

1. **Locally**: `streamlit run streamlit_app.py`
2. Log in with a test user
3. Rate one cluster
4. ✅ Check your Google Sheet - should see one new row with the annotation
5. Refresh the app and log in again - should show **"✅ Resumed — 1 annotation already saved"**
6. Click a different cluster - should skip the previously-rated one

### Troubleshooting Google Sheets Setup

#### ❌ "GOOGLE_APPS_SCRIPT_URL not configured in secrets"

**Problem:** Secrets not set up correctly

**Fix:**
- Locally: Check `.streamlit/secrets.toml` exists and has the URL
- Streamlit Cloud: Go to Settings → Secrets and verify the URL is there
- Restart the app

#### ❌ "Save failed (retried multiple times)"

**Problem:** Google Apps Script endpoint not responding

**Check:**
1. Is the deployment URL correct? (You copied it from Apps Script?)
2. Is the Apps Script deployed as "Web app" with "Anyone" access?
3. Try accessing the URL directly in browser - should show script error (that's OK)

**Fix:**
1. Redeploy the Apps Script (Deploy → New deployment)
2. Copy new URL to secrets
3. Restart Streamlit

#### ❌ Annotations save to Google Sheets but app doesn't show resume message

**Problem:** Fetch is failing silently

**Check:**
- Is `GOOGLE_SHEET_READ_URL` set in secrets?
- Does it have the same deployment URL as `GOOGLE_APPS_SCRIPT_URL`?

**Fix:**
1. Add `GOOGLE_SHEET_READ_URL` to secrets if missing
2. Test manually by accessing the URL with `?user_name=testuser` query param

#### ❌ Multiple deployments of same Apps Script

**Problem:** You deployed multiple times and lost track of the URL

**Fix:**
1. Go to your Google Sheet
2. Extensions → Apps Script
3. Click the clock icon (Deployments)
4. You should see all deployments
5. Use the most recent one (or delete old ones)

### Migrating from Local JSON to Google Sheets

If you already have annotations saved in local `annotations_*.json` files:

1. Manually export data from JSON files
2. In Google Sheet, create rows with the data:
   - Column A: user_name
   - Column B: cluster_cid (e.g., "intolerant_cluster_5")
   - Column C: appropriateness_rating
   - etc.
3. Once data is in Google Sheet, the app will auto-resume from it

Alternatively, keep local files as backup and gradually transition to Google Sheets.

### Data Privacy & Security

- **Google Sheet is visible to**: Anyone with the sheet link (keep it private!)
- **Annotations are queried by**: User name only (no authentication on script level)
- **Recommended**: Share Google Sheet only with team leads/admins, not with annotators
- **Future enhancement**: Add row-level permissions or API authentication

---

## Next Checklist (Updated)

- [ ] GitHub repo ready (`git push origin main`)
- [ ] App deployed to Streamlit Cloud
- [ ] OIDC secrets configured (see OIDC_SETUP.md)
- [ ] **Google Sheets setup complete** (see above)
- [ ] Login button working
- [ ] Test user can save annotations → appear in Google Sheet
- [ ] Test resume: log in again → see "✅ Resumed" message
- [ ] Share link with team
