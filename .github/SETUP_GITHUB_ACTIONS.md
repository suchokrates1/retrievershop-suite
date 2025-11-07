# 🚀 Quick Setup: GitHub Actions Deployment

Follow these steps to enable automatic deployment to production.

## Step 1: Generate SSH Key (if needed)

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions

# You'll see:
# Generating public/private ed25519 key pair.
# Enter passphrase (empty for no passphrase): [PRESS ENTER]
# Your identification has been saved in ~/.ssh/github_actions
# Your public key has been saved in ~/.ssh/github_actions.pub
```

## Step 2: Add Public Key to Production Server

```bash
# Copy public key to clipboard
cat ~/.ssh/github_actions.pub

# SSH to production server
ssh magazyn@magazyn.retrievershop.pl

# Add key to authorized_keys
echo "PASTE_PUBLIC_KEY_HERE" >> ~/.ssh/authorized_keys

# Exit
exit
```

## Step 3: Test SSH Connection

```bash
# Test with the new key
ssh -i ~/.ssh/github_actions magazyn@magazyn.retrievershop.pl

# If it works, you'll see the server prompt
# If not, check permissions:
chmod 600 ~/.ssh/github_actions
chmod 644 ~/.ssh/github_actions.pub
```

## Step 4: Add Secrets to GitHub

1. Go to: https://github.com/suchokrates1/retrievershop-suite/settings/secrets/actions

2. Click **New repository secret** and add:

   **Secret 1: PROD_HOST**
   ```
   Value: magazyn.retrievershop.pl
   ```

   **Secret 2: PROD_USER**
   ```
   Value: magazyn
   ```

   **Secret 3: PROD_SSH_KEY**
   ```bash
   # Copy private key
   cat ~/.ssh/github_actions
   
   # Paste ENTIRE output including:
   # -----BEGIN OPENSSH PRIVATE KEY-----
   # ... (many lines) ...
   # -----END OPENSSH PRIVATE KEY-----
   ```

   **Secret 4: PROD_PORT** (optional, default: 22)
   ```
   Value: 22
   ```

## Step 5: Test Deployment

```bash
# Make a small change and push
echo "# Test" >> README.md
git add README.md
git commit -m "test: Trigger GitHub Actions deployment"
git push origin main
```

## Step 6: Monitor Deployment

1. Go to: https://github.com/suchokrates1/retrievershop-suite/actions
2. Click on the latest workflow run
3. Watch deployment progress in real-time
4. ✅ Green checkmark = deployment successful!

## Step 7: Verify Application

```bash
# Check if application is running
curl https://magazyn.retrievershop.pl/healthz

# Should return: {"status":"ok", ...}
```

## ✅ Done!

From now on, every push to `main` will automatically:
1. ✅ Run tests
2. ✅ Deploy to production
3. ✅ Verify application health
4. ✅ Show status badge on GitHub

## 🔧 Troubleshooting

### Deployment fails with "Host key verification failed"

**Solution:** Accept server fingerprint manually once:
```bash
ssh-keyscan magazyn.retrievershop.pl >> ~/.ssh/known_hosts
```

### "Permission denied (publickey)"

**Solution:** Check if key was added correctly:
```bash
# On production server
cat ~/.ssh/authorized_keys | grep "github-actions"

# Should show your public key
```

### Workflow doesn't trigger

**Solution:** Check workflow file syntax:
```bash
# Validate YAML
cat .github/workflows/deploy.yml
```

## 🎉 Next Steps

- Add more environments (staging, dev)
- Set up notifications (Slack, Discord)
- Add automated rollback on failure
- Configure deployment approvals for production

---

**Need help?** Check `.github/GITHUB_ACTIONS.md` for detailed documentation.
