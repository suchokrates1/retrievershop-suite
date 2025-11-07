# 🚀 Quick Setup: GitHub Actions Deployment to RPi5

Follow these steps to enable automatic deployment to your Raspberry Pi 5.

## Prerequisites

- ✅ Raspberry Pi 5 accessible via local network or VPN
- ✅ Tailscale installed on RPi5 (for GitHub Actions access)
- ✅ Docker and docker-compose installed on RPi5
- ✅ Application running at `/home/suchokrates1/retrievershop-suite`

## Step 1: Install Tailscale on RPi5

**On your Raspberry Pi 5:**

```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Start Tailscale and authenticate
sudo tailscale up

# Get your Tailscale IP address
tailscale ip -4
# Example output: 100.x.x.x

# Note this IP - you'll need it for PROD_HOST secret
```

## Step 2: Create Tailscale OAuth Client

**For GitHub Actions to connect via Tailscale:**

1. Go to: https://login.tailscale.com/admin/settings/oauth
2. Click **Generate OAuth client**
3. Add a description: "GitHub Actions - RetrieverShop"
4. Select scopes:
   - ✅ `devices:read`
   - ✅ `devices:write`
5. Add tags: `tag:ci`
6. Click **Generate client**
7. **Save these values:**
   - OAuth Client ID: `tskey-client-...`
   - OAuth Client Secret: `tskey-...`

## Step 3: Add Secrets to GitHub

1. Go to: https://github.com/suchokrates1/retrievershop-suite/settings/secrets/actions

2. Click **New repository secret** and add:

   **Secret 1: TAILSCALE_OAUTH_CLIENT_ID**
   ```
   Value: tskey-client-xxxxxxxxxx
   ```

   **Secret 2: TAILSCALE_OAUTH_SECRET**
   ```
   Value: tskey-xxxxxxxxxx
   ```

   **Secret 3: PROD_HOST**
   ```
   Value: 100.x.x.x  (your Tailscale IP from Step 1)
   ```

   **Secret 4: PROD_USER**
   ```
   Value: suchokrates1
   ```

   **Secret 5: PROD_PASSWORD**
   ```
   Value: your_ssh_password
   ```

   **Secret 6: PROD_PORT** (optional)
   ```
   Value: 22
   ```

## Step 4: Test Tailscale Connection

**On your local machine (with Tailscale installed):**

```bash
# SSH to RPi5 via Tailscale IP
ssh suchokrates1@100.x.x.x

# Should connect successfully
# If it works, GitHub Actions will work too!
```

## Step 5: Test Deployment

```bash
# Make a small change and push
echo "# Test deployment" >> README.md
git add README.md
git commit -m "test: Trigger GitHub Actions deployment"
git push origin main
```

## Step 6: Monitor Deployment

1. Go to: https://github.com/suchokrates1/retrievershop-suite/actions
2. Click on the latest workflow run
3. Watch deployment progress:
   - Setup Tailscale ✅
   - Deploy to production server ✅
   - Verify deployment ✅
4. Green checkmark = success! 🎉

## Step 7: Verify Application

```bash
# Check if containers are running
ssh suchokrates1@100.x.x.x 'docker ps'

# Check application logs
ssh suchokrates1@100.x.x.x 'cd /home/suchokrates1/retrievershop-suite && docker compose logs web --tail=50'

# If you have public access, check health
curl https://magazyn.retrievershop.pl/healthz
```

## ✅ Done!

From now on, every push to `main` will automatically:
1. ✅ Connect to RPi5 via Tailscale
2. ✅ Run tests (optional)
3. ✅ Deploy to production
4. ✅ Verify containers are running
5. ✅ Show status badge on GitHub

## 🔧 Troubleshooting

### "Tailscale connection failed"

**Solution 1:** Check if Tailscale is running on RPi5:
```bash
ssh suchokrates1@192.168.31.167  # Local network
sudo systemctl status tailscaled
sudo tailscale up
```

**Solution 2:** Verify OAuth credentials in GitHub secrets

### "Permission denied (password)"

**Solution:** Double-check PROD_PASSWORD secret:
1. Go to GitHub repo → Settings → Secrets → Actions
2. Update PROD_PASSWORD with correct value

### "docker compose: command not found"

**Solution:** Install Docker Compose V2 on RPi5:
```bash
sudo apt-get update
sudo apt-get install docker-compose-plugin
```

### Workflow doesn't trigger

**Solution:** Check if you pushed to `main` branch:
```bash
git branch  # Should show: * main
git push origin main
```

## 🎉 Next Steps

- Add more environments (staging, dev)
- Set up notifications (Slack, Discord)
- Add automated rollback on failure
- Configure deployment approvals for production

---

**Need help?** Check `.github/GITHUB_ACTIONS.md` for detailed documentation.
