# 🌐 Tailscale Setup for RPi5

Tailscale creates a secure VPN that allows GitHub Actions to SSH into your RPi5 even though it's behind your home router.

## Why Tailscale?

- ✅ **No port forwarding needed** - works behind NAT/firewall
- ✅ **Secure** - WireGuard-based encryption
- ✅ **Free** - for personal use (up to 100 devices)
- ✅ **Easy** - 5-minute setup
- ✅ **GitHub Actions compatible** - official action available

## Quick Install on RPi5

```bash
# SSH to your RPi5 locally first
ssh suchokrates1@192.168.31.167

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Start and authenticate
sudo tailscale up

# You'll see a URL like: https://login.tailscale.com/a/xxxxxxxxx
# Open it in a browser and login with your account

# Get your Tailscale IP
tailscale ip -4
```

**Example output:**
```
100.101.102.103
```

☝️ **This is your Tailscale IP** - save it for `PROD_HOST` secret!

## Test Connection

**From your Windows PC (install Tailscale first):**

1. **Download Tailscale:** https://tailscale.com/download/windows
2. **Install and login** (use same account as RPi5)
3. **Test SSH:**
   ```powershell
   ssh suchokrates1@100.101.102.103
   ```

✅ If it works, GitHub Actions will work too!

## Create OAuth Client for GitHub Actions

1. **Go to:** https://login.tailscale.com/admin/settings/oauth
2. **Generate OAuth client**
3. **Description:** `GitHub Actions - RetrieverShop`
4. **Tags:** `tag:ci`
5. **Scopes:** `devices:read`, `devices:write`
6. **Save:**
   - `OAuth Client ID` → GitHub secret `TAILSCALE_OAUTH_CLIENT_ID`
   - `OAuth Client Secret` → GitHub secret `TAILSCALE_OAUTH_SECRET`

## Alternative: Self-Hosted Runner (No Tailscale Needed!)

If you don't want to use Tailscale, you can run GitHub Actions **directly on your RPi5**:

```bash
# On RPi5
mkdir ~/actions-runner && cd ~/actions-runner

# Download runner for ARM64
wget https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-arm64-2.311.0.tar.gz
tar xzf ./actions-runner-linux-arm64-2.311.0.tar.gz

# Configure (get token from GitHub Settings > Actions > Runners > New self-hosted runner)
./config.sh --url https://github.com/suchokrates1/retrievershop-suite --token YOUR_GITHUB_TOKEN

# Install as service
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

**Then update `.github/workflows/deploy.yml`:**

```yaml
jobs:
  deploy:
    runs-on: self-hosted  # ← Runs on your RPi5!
    steps:
      - name: Deploy
        run: |
          cd /home/suchokrates1/retrievershop-suite
          git pull origin main
          docker compose down
          docker compose up -d --build
```

## Which Option to Choose?

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Tailscale** | ✅ Secure VPN<br>✅ Works from anywhere<br>✅ Easy setup | ⚠️ Requires Tailscale account<br>⚠️ Extra dependency | 👍 **Best for multiple devices** |
| **Self-hosted Runner** | ✅ No external services<br>✅ Fastest deployment<br>✅ Full local control | ⚠️ RPi5 must be always on<br>⚠️ Runner uses resources | 👍 **Best for home servers** |

## My Recommendation: Self-Hosted Runner! 🎯

For your case (RPi5 at home), **self-hosted runner is simpler**:

**Advantages:**
- ✅ No Tailscale needed
- ✅ No OAuth setup
- ✅ No extra network configuration
- ✅ Deployment happens instantly (no SSH overhead)
- ✅ Can access local resources directly

**Setup in 3 minutes:**

1. Go to: https://github.com/suchokrates1/retrievershop-suite/settings/actions/runners/new
2. Copy the commands shown
3. Run them on your RPi5
4. Done! ✅

Would you like me to update the workflow for self-hosted runner instead? 🚀
