# GitHub Actions Configuration

This repository uses GitHub Actions for automated testing and deployment.

## Workflows

### 1. `deploy.yml` - Automatic Deployment
- **Trigger:** Push to `main` branch or manual dispatch
- **Purpose:** Deploys code to production server
- **Steps:**
  1. Checkout code
  2. SSH to production server
  3. Pull latest changes
  4. Restart Docker containers
  5. Verify application health

### 2. `test.yml` - Automated Testing
- **Trigger:** Push to `main`, pull requests, or manual dispatch
- **Purpose:** Run test suite and code quality checks
- **Matrix:** Python 3.10, 3.11, 3.12
- **Steps:**
  1. Run pytest with coverage
  2. Upload coverage to Codecov
  3. Run flake8 linting
  4. Check code formatting (black)
  5. Check import sorting (isort)

## Required Secrets

To enable deployment, configure these secrets in GitHub repository settings:

**Settings → Secrets and variables → Actions → New repository secret**

### Production Server Secrets

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `PROD_HOST` | Production server hostname | `magazyn.retrievershop.pl` |
| `PROD_USER` | SSH username | `magazyn` |
| `PROD_SSH_KEY` | Private SSH key for authentication | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `PROD_PORT` | SSH port (optional, default: 22) | `22` |

### How to Generate SSH Key

If you don't have an SSH key for GitHub Actions:

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions@retrievershop" -f ~/.ssh/github_actions_ed25519

# Copy PUBLIC key to production server
ssh-copy-id -i ~/.ssh/github_actions_ed25519.pub magazyn@magazyn.retrievershop.pl

# Or manually add to server:
cat ~/.ssh/github_actions_ed25519.pub
# Then on server: echo "PUBLIC_KEY_CONTENT" >> ~/.ssh/authorized_keys

# Copy PRIVATE key content to GitHub secret PROD_SSH_KEY
cat ~/.ssh/github_actions_ed25519
# Copy entire output including BEGIN/END lines
```

### Alternative: Use Existing SSH Key

If you already have SSH access configured:

```bash
# On your local machine, display your private key
cat ~/.ssh/id_ed25519
# or
cat ~/.ssh/id_rsa

# Copy the entire output (including BEGIN/END lines) to PROD_SSH_KEY secret
```

## Manual Deployment

You can trigger deployment manually from GitHub:

1. Go to **Actions** tab
2. Select **Deploy to Production** workflow
3. Click **Run workflow** button
4. Choose `main` branch
5. Click **Run workflow**

## Monitoring

### View Deployment Logs

1. Go to **Actions** tab
2. Click on the latest workflow run
3. Expand deployment steps to see output

### Check Deployment Status

- ✅ **Success:** Green checkmark on commit/PR
- ❌ **Failure:** Red X - check logs for details
- 🟡 **Running:** Yellow dot - deployment in progress

## Troubleshooting

### Deployment Fails with "Permission denied"

**Solution:** Check if SSH key is correctly configured:
```bash
# Test SSH connection manually
ssh -i ~/.ssh/github_actions_ed25519 magazyn@magazyn.retrievershop.pl

# If it works, the key is correct
# If not, regenerate and reconfigure
```

### Tests Fail on GitHub but Pass Locally

**Solution:** Check Python version compatibility
```bash
# Test with specific Python version locally
python3.12 -m pytest magazyn/tests/
```

### Deployment Succeeds but App is Broken

**Solution:** Check application logs
```bash
ssh magazyn@magazyn.retrievershop.pl
cd /app
docker-compose logs web --tail=100
```

## Disabling Automatic Deployment

If you want to deploy manually only:

1. Edit `.github/workflows/deploy.yml`
2. Remove the `push:` trigger section
3. Keep only `workflow_dispatch:` trigger
4. Commit and push

## Security Best Practices

- ✅ **Never commit secrets** to the repository
- ✅ **Use SSH keys** instead of passwords
- ✅ **Rotate keys** periodically
- ✅ **Limit key permissions** on the server (add to specific user only)
- ✅ **Use separate keys** for different environments
- ✅ **Enable 2FA** on your GitHub account

## Next Steps

After configuring secrets:

1. ✅ Push a commit to `main` branch
2. ✅ Go to **Actions** tab on GitHub
3. ✅ Watch deployment workflow run
4. ✅ Verify application is working: https://magazyn.retrievershop.pl/healthz

## Support

If you encounter issues, check:
- GitHub Actions documentation: https://docs.github.com/en/actions
- SSH Action documentation: https://github.com/appleboy/ssh-action
- Repository: `.github/AGENT_INSTRUCTIONS.md`
