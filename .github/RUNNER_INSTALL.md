# 🚀 GitHub Actions Self-Hosted Runner - Instalacja na RPi5

## Krok 1: Pobierz komendy instalacyjne

1. **Otwórz w przeglądarce:**
   ```
   https://github.com/suchokrates1/retrievershop-suite/settings/actions/runners/new
   ```

2. **Wybierz:**
   - **Runner image:** Linux
   - **Architecture:** ARM64

3. **GitHub pokaże Ci dokładne komendy** - skopiuj je!

---

## Krok 2: Zainstaluj runner na RPi5

**SSH do RPi5:**
```bash
ssh suchokrates1@192.168.31.167
```

**Utwórz folder dla runnera:**
```bash
mkdir ~/actions-runner && cd ~/actions-runner
```

**Pobierz runner** (ARM64 dla RPi5):
```bash
# UWAGA: Użyj dokładnej wersji z GitHub (krok 1), przykład:
curl -o actions-runner-linux-arm64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-arm64-2.311.0.tar.gz

# Weryfikuj checksum (opcjonalnie)
echo "CHECKSUM_FROM_GITHUB  actions-runner-linux-arm64-2.311.0.tar.gz" | shasum -a 256 -c

# Rozpakuj
tar xzf ./actions-runner-linux-arm64-2.311.0.tar.gz
```

---

## Krok 3: Skonfiguruj runner

**Uruchom konfigurację** (użyj tokenu z GitHub):
```bash
./config.sh --url https://github.com/suchokrates1/retrievershop-suite --token YOUR_REGISTRATION_TOKEN
```

**Odpowiedz na pytania:**
```
Enter the name of the runner group: [ENTER] (domyślnie: Default)
Enter the name of runner: [ENTER] (domyślnie: hostname RPi5)
Enter any additional labels: [ENTER] (zostaw puste)
Enter name of work folder: [ENTER] (domyślnie: _work)
```

**Powinnaś zobaczyć:**
```
✓ Runner successfully added
✓ Runner connection is good
```

---

## Krok 4: Uruchom runner jako service

**Zainstaluj jako systemd service:**
```bash
sudo ./svc.sh install suchokrates1
```

**Uruchom service:**
```bash
sudo ./svc.sh start
```

**Sprawdź status:**
```bash
sudo ./svc.sh status
```

**Powinnaś zobaczyć:**
```
● actions.runner.suchokrates1-retrievershop-suite.HOSTNAME.service - GitHub Actions Runner
     Loaded: loaded
     Active: active (running)
```

---

## Krok 5: Weryfikacja

**Na GitHubie:**
1. Wejdź: https://github.com/suchokrates1/retrievershop-suite/settings/actions/runners
2. Powinnaś zobaczyć **zielony znacznik** obok swojego runnera: `✓ Idle`

**Test deployment:**
```bash
# Na swoim PC
cd C:\Users\sucho\retrievershop-suite
echo "# Test" >> README.md
git add README.md
git commit -m "test: Verify self-hosted runner deployment"
git push origin main
```

**Sprawdź Actions:**
- https://github.com/suchokrates1/retrievershop-suite/actions
- Workflow powinien się uruchomić **natychmiastowo** i pokazać: ✓ Success

---

## Krok 6: Monitoruj logi (opcjonalnie)

**Na RPi5 możesz śledzić logi runnera:**
```bash
sudo journalctl -u actions.runner.* -f
```

**Lub logi deployment:**
```bash
cd ~/actions-runner/_work/retrievershop-suite/retrievershop-suite
docker compose logs -f web
```

---

## ✅ Gotowe!

Od teraz każdy push do `main` automatycznie:
1. ✅ Uruchomi się na Twoim RPi5
2. ✅ Zaktualizuje kod (`git pull`)
3. ✅ Zrestartuje Docker containers
4. ✅ Pokaże logi i status

---

## 🔧 Przydatne komendy

```bash
# Status runnera
sudo ./svc.sh status

# Restart runnera
sudo ./svc.sh restart

# Stop runnera
sudo ./svc.sh stop

# Usuń runner
cd ~/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh uninstall
./config.sh remove --token YOUR_REMOVE_TOKEN

# Zobacz logi
sudo journalctl -u actions.runner.* -n 50
```

---

## 🐛 Troubleshooting

### Runner nie uruchamia się

**Sprawdź logi:**
```bash
sudo journalctl -u actions.runner.* -n 100
```

**Najczęstsze problemy:**
- Docker nie jest zainstalowany: `sudo apt install docker.io docker-compose-plugin`
- Brak uprawnień: `sudo usermod -aG docker suchokrates1` (wyloguj i zaloguj ponownie)
- Runner już istnieje: usuń starą instalację przed dodaniem nowej

### "git pull" fails with permission denied

**Rozwiązanie:**
```bash
cd /home/suchokrates1/retrievershop-suite
sudo chown -R suchokrates1:suchokrates1 .
```

### Docker nie działa w runnerze

**Dodaj użytkownika do grupy docker:**
```bash
sudo usermod -aG docker suchokrates1
# Restart runnera
sudo ./svc.sh restart
```

---

## 🎉 Więcej informacji

- **GitHub Docs:** https://docs.github.com/en/actions/hosting-your-own-runners
- **Runner Releases:** https://github.com/actions/runner/releases
- **Repo Settings:** https://github.com/suchokrates1/retrievershop-suite/settings/actions/runners

---

**Wszystko jasne? Gotowy do instalacji!** 🚀
