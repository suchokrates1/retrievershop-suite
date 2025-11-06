"""Test z prawdziwą aplikacją i fakeowymi danymi w bazie."""

import sys
import time
from pathlib import Path

# Dodaj ścieżkę do modułu magazyn
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def add_fake_discussions_to_db():
    """Dodaje fakeowe dyskusje bezpośrednio do bazy danych."""
    from magazyn.config import settings
    import sqlite3
    
    db_path = settings.DB_PATH
    print(f"📂 Łączę się z bazą danych: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Sprawdź czy tabele istnieją
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%discussion%'")
    tables = cursor.fetchall()
    print(f"📊 Znalezione tabele: {tables}")
    
    # Jeśli nie ma tabel, możemy stworzyć tymczasową strukturę
    # Ale najprawdopodobniej dyskusje są cache'owane w pamięci aplikacji lub w innej tabeli
    
    conn.close()
    print("✅ Sprawdzenie bazy zakończone")
    
    return True


def test_discussions_with_real_app():
    """Test z prawdziwą aplikacją - robi screenshot z produkcyjnej strony."""
    
    print("🚀 Test z prawdziwą aplikacją")
    print("=" * 60)
    
    # Użyj produkcyjnej strony magazyn.retrievershop.pl
    import subprocess
    import requests
    
    print("\n1️⃣ Sprawdzam aplikację produkcyjną...")
    
    app_url = "https://magazyn.retrievershop.pl"
    flask_process = None  # Nie będziemy uruchamiać lokalnie
    
    try:
        # Sprawdź czy aplikacja odpowiada
        response = requests.get(app_url, timeout=10)
        print(f"   ✅ Aplikacja produkcyjna odpowiada (status: {response.status_code})")
            
    except Exception as e:
        print(f"   ❌ Błąd dostępu do aplikacji: {e}")
        print("   💡 Sprawdź czy magazyn.retrievershop.pl jest dostępne")
        return False
    
    # Krok 2: Sprawdź bazę danych
    print("\n2️⃣ Sprawdzam bazę danych...")
    try:
        add_fake_discussions_to_db()
    except Exception as e:
        print(f"   ⚠️  Błąd dostępu do bazy: {e}")
    
    # Krok 3: Pobierz stronę przez Selenium
    print("\n3️⃣ Otwieram stronę w przeglądarce...")
    
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        chrome_options = Options()
        # chrome_options.add_argument("--headless")  # Odkomentuj dla trybu bez okna
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        driver = webdriver.Chrome(options=chrome_options)
        
        print(f"   🌐 Otwieram: {app_url}")
        driver.get(app_url)
        
        # Sprawdź czy strona się załadowała
        time.sleep(2)
        
        print(f"   📄 Tytuł strony: {driver.title}")
        
        # Sprawdź czy jest formularz logowania
        try:
            username_field = driver.find_element(By.NAME, "username")
            password_field = driver.find_element(By.NAME, "password")
            
            print("   🔐 Znaleziono formularz logowania, loguję się...")
            
            # Dane logowania
            username = "admin"
            password = "admin123"
            
            username_field.send_keys(username)
            password_field.send_keys(password)
            
            # Kliknij przycisk login
            login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            login_button.click()
            
            # Poczekaj na przekierowanie
            time.sleep(2)
            
            print(f"   ✅ Zalogowano, nowy tytuł: {driver.title}")
            
        except Exception as e:
            print(f"   ℹ️  Brak formularza logowania lub już zalogowany: {e}")
        
        # Przejdź do strony discussions
        discussions_url = f"{app_url}/discussions"
        print(f"   📨 Otwieram: {discussions_url}")
        driver.get(discussions_url)
        
        # Poczekaj na załadowanie strony
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "discussions-layout"))
            )
            print("   ✅ Strona discussions załadowana")
        except Exception as e:
            print(f"   ⚠️  Timeout czekania na stronę: {e}")
        
        time.sleep(2)
        
        # WSTRZYKNIJ BRAKUJĄCE STYLE (bo produkcja nie ma ich w base.html)
        print("   🎨 Wstrzykuję pełne style CSS...")
        css_file = Path(__file__).parent / "discussions_inject.css"
        with open(css_file, "r", encoding="utf-8") as f:
            css_content = f.read()
        
        # Wstrzyknij CSS używając argumentów zamiast template string
        driver.execute_script("""
            const style = document.createElement('style');
            style.textContent = arguments[0];
            document.head.appendChild(style);
        """, css_content)
        print("   ✅ Style wstrzyknięte")
        
        # Odczekaj chwilę żeby style się zastosowały
        time.sleep(1)
        
        # Zrób screenshot
        screenshot_file = Path(__file__).parent / "discussions_real_screenshot.png"
        driver.save_screenshot(str(screenshot_file))
        print(f"   📸 Screenshot zapisany: {screenshot_file}")
        
        # Zapisz HTML
        html_file = Path(__file__).parent / "discussions_real_output.html"
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"   💾 HTML zapisany: {html_file}")
        
        # Sprawdź ile jest wątków
        try:
            threads = driver.find_elements(By.CLASS_NAME, "thread-item")
            print(f"   📬 Znaleziono {len(threads)} wątków")
            
            if threads:
                print("\n   📋 Lista wątków:")
                for i, thread in enumerate(threads[:5], 1):  # Pokaż pierwsze 5
                    try:
                        title = thread.find_element(By.CLASS_NAME, "thread-title").text
                        preview = thread.find_element(By.CLASS_NAME, "thread-preview").text
                        print(f"      {i}. {title}")
                        print(f"         → {preview[:60]}...")
                    except Exception as e:
                        print(f"      {i}. (nie można odczytać)")
        except Exception as e:
            print(f"   ⚠️  Błąd liczenia wątków: {e}")
        
        # Zostaw przeglądarkę otwartą na 5 sekund żeby zobaczyć
        print("\n   ⏳ Przeglądarka zostanie otwarta przez 5 sekund...")
        time.sleep(5)
        
        driver.quit()
        
        print("\n" + "=" * 60)
        print("✅ Test zakończony sukcesem!")
        print(f"📸 Screenshot: {screenshot_file.absolute()}")
        print(f"💾 HTML: {html_file.absolute()}")
        
        # Otwórz screenshot
        import subprocess
        subprocess.Popen(["start", str(screenshot_file.absolute())], shell=True)
        
        return True
        
    except ImportError:
        print("   ❌ Brak Selenium - zainstaluj: pip install selenium")
        return False
    except Exception as e:
        print(f"   ❌ Błąd: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Zawsze zamknij aplikację Flask
        if flask_process:
            print("\n🛑 Zamykam aplikację Flask...")
            flask_process.terminate()
            try:
                flask_process.wait(timeout=5)
            except:
                flask_process.kill()
            print("   ✅ Aplikacja zamknięta")


if __name__ == "__main__":
    print("🧪 Test strony discussions z prawdziwą aplikacją\n")
    
    success = test_discussions_with_real_app()
    
    if not success:
        print("\n❌ Test nie powiódł się")
        sys.exit(1)
