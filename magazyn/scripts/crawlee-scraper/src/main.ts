/**
 * Allegro Price Scraper oparty na Crawlee
 * 
 * Wykorzystuje:
 * - PlaywrightCrawler z automatycznym fingerprint spoofing
 * - Opcjonalna integracja z Camoufox dla trudniejszych stron
 * - handleCloudflareChallenge dla DataDome/Cloudflare
 * 
 * Uzycie:
 *   npx tsx src/main.ts <allegro_url>
 *   npx tsx src/main.ts --test
 */

import { PlaywrightCrawler, Dataset, log, ProxyConfiguration } from 'crawlee';
import { firefox, chromium } from 'playwright';

// Camoufox - opcjonalny import
let camoufoxLaunchOptions: any = null;
try {
  const camoufox = await import('camoufox-js');
  camoufoxLaunchOptions = camoufox.launchOptions;
  log.info('Camoufox dostepny');
} catch {
  log.debug('Camoufox niedostepny');
}

// Stale
const MY_SELLER = 'Retriever_Shop';
const MAX_DELIVERY_DAYS = 4;

// Polskie miesiace do parsowania dat
const POLISH_MONTHS: Record<string, number> = {
  sty: 1, lut: 2, mar: 3, kwi: 4, maj: 5, cze: 6,
  lip: 7, sie: 8, wrz: 9, paz: 10, lis: 11, gru: 12
};

interface CompetitorOffer {
  seller: string;
  price: number;
  currency: string;
  deliveryText: string;
  deliveryDays: number | null;
  isSuperSeller: boolean;
  offerId: string;
}

interface ScrapingResult {
  success: boolean;
  error?: string;
  myPrice?: number;
  competitors: CompetitorOffer[];
  cheapest?: CompetitorOffer;
  priceDiff?: number;
  totalOffers: number;
}

/**
 * Parsuje tekst dostawy na liczbe dni
 */
function parseDeliveryDays(text: string): number | null {
  if (!text) return null;
  
  const t = text.toLowerCase().trim();
  
  // Pomin "Dostawa od X zl" - to cena, nie czas
  if (/^dostawa\s+od\s+\d/.test(t)) return null;
  
  // "dostawa za 2-3 dni"
  const rangeMatch = t.match(/dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni/);
  if (rangeMatch) {
    return Math.floor((parseInt(rangeMatch[1]) + parseInt(rangeMatch[2])) / 2);
  }
  
  // "15 sty" - data
  const dateMatch = t.match(/(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)/);
  if (dateMatch) {
    const day = parseInt(dateMatch[1]);
    const month = POLISH_MONTHS[dateMatch[2]] || 1;
    const today = new Date();
    let target = new Date(today.getFullYear(), month - 1, day);
    if (target < today) {
      target = new Date(today.getFullYear() + 1, month - 1, day);
    }
    return Math.ceil((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  }
  
  if (t.includes('jutro')) return 1;
  if (t.includes('dzisiaj') || t.includes('dzis')) return 0;
  
  return null;
}

/**
 * Glowna funkcja scrapujaca
 */
async function scrapeAllegro(
  offerUrl: string,
  options: {
    maxDeliveryDays?: number;
    useCamoufox?: boolean;
    proxyUrl?: string;
  } = {}
): Promise<ScrapingResult> {
  const {
    maxDeliveryDays = MAX_DELIVERY_DAYS,
    useCamoufox = false,
    proxyUrl
  } = options;

  const result: ScrapingResult = {
    success: false,
    competitors: [],
    totalOffers: 0
  };

  let comparisonUrl: string | null = null;
  let offersData: CompetitorOffer[] = [];

  // Konfiguracja proxy (opcjonalna)
  const proxyConfiguration = proxyUrl
    ? new ProxyConfiguration({ proxyUrls: [proxyUrl] })
    : undefined;

  // Konfiguracja crawlera
  const crawlerOptions: any = {
    maxRequestsPerCrawl: 3, // Max 3 requesty (oferta + porownanie + retry)
    requestHandlerTimeoutSecs: 120,
    navigationTimeoutSecs: 60,
    
    // Fingerprint spoofing wlaczony domyslnie
    browserPoolOptions: {
      useFingerprints: !useCamoufox, // Wylacz jesli uzywamy Camoufox
      fingerprintOptions: {
        fingerprintGeneratorOptions: {
          browsers: [{ name: 'chrome', minVersion: 120 }],
          devices: ['desktop'],
          operatingSystems: ['windows'],
          locales: ['pl-PL'],
        },
      },
    },
    
    // Hooks po nawigacji
    postNavigationHooks: [
      async ({ page, handleCloudflareChallenge }: any) => {
        // Obsluga DataDome/Cloudflare challenge
        try {
          await handleCloudflareChallenge();
        } catch {
          // Ignoruj jesli nie ma challenge
        }
      },
    ],
    
    // Proxy
    proxyConfiguration,
  };

  // Camoufox integracja
  if (useCamoufox && camoufoxLaunchOptions) {
    try {
      // Headful mode dziala lepiej z DataDome
      const opts = await camoufoxLaunchOptions({ 
        headless: false,  // Headful dla lepszego stealth
        humanize: true,
      });
      crawlerOptions.launchContext = {
        launcher: firefox,
        launchOptions: opts,
      };
      crawlerOptions.browserPoolOptions.useFingerprints = false;
      log.info('Uzywam Camoufox (headful) dla lepszego stealth');
    } catch (e: any) {
      log.warning(`Camoufox init error: ${e.message}, uzywam standardowego Playwright`);
    }
  } else if (useCamoufox) {
    log.warning('Camoufox niedostepny, uzywam standardowego Playwright');
  }

  const crawler = new PlaywrightCrawler({
    ...crawlerOptions,
    
    async requestHandler({ request, page, enqueueLinks }) {
      const url = request.url;
      log.info(`Przetwarzam: ${url}`);

      // Czekaj na zaladowanie strony
      await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
      
      // Sprawdz czy strona jest zablokowana
      const content = await page.content();
      const title = await page.title();
      
      log.info(`Tytul strony: "${title}", Content length: ${content.length}`);
      
      // DataDome daje krotka strone z captcha
      const isBlocked = content.length < 10000 && 
        (title.toLowerCase() === 'allegro.pl' || content.includes('captcha-delivery.com'));
      
      if (isBlocked) {
        log.error('Strona zablokowana przez DataDome');
        log.debug(`Content preview: ${content.substring(0, 500)}`);
        result.error = 'Strona zablokowana przez DataDome';
        return;
      }

      // Krok 1: Strona oferty - znajdz link do porownania
      if (url.includes('/oferta/') && !comparisonUrl) {
        log.info('Szukam linku do porownania ofert...');
        
        // Szukaj linku do /oferty-produktu/
        const links = await page.$$('a[href*="/oferty-produktu/"]');
        for (const link of links) {
          const href = await link.getAttribute('href');
          if (href) {
            comparisonUrl = href.startsWith('/') ? `https://allegro.pl${href}` : href;
            break;
          }
        }
        
        if (comparisonUrl) {
          log.info(`Znaleziono URL porownania: ${comparisonUrl}`);
          await enqueueLinks({
            urls: [comparisonUrl],
            label: 'COMPARISON'
          });
        } else {
          log.warning('Nie znaleziono linku do porownania - moze byc jedyny sprzedawca');
          result.error = 'Brak linku do porownania ofert';
        }
        return;
      }

      // Krok 2: Strona porownania - parsuj oferty
      if (request.label === 'COMPARISON' || url.includes('/oferty-produktu/')) {
        log.info('Parsuje oferty konkurentow...');
        
        // Szukaj JSON z danymi w script tags
        const scripts = await page.$$('script');
        for (const script of scripts) {
          const text = await script.textContent();
          if (text && text.includes('__listing_StoreState')) {
            const match = text.match(/__listing_StoreState\s*=\s*({.+?});\s*<\/script>/s);
            if (match) {
              try {
                const data = JSON.parse(match[1]);
                const elements = data?.items?.elements || [];
                
                for (const el of elements) {
                  const seller = el.seller || {};
                  const priceInfo = el.price?.mainPrice || el.price || {};
                  const delivery = el.shipping?.delivery || {};
                  const deliveryLabel = delivery.label?.text || '';
                  
                  const price = parseFloat(priceInfo.amount || '0');
                  if (price <= 0) continue;
                  
                  offersData.push({
                    seller: seller.login || 'Nieznany',
                    price,
                    currency: priceInfo.currency || 'PLN',
                    deliveryText: deliveryLabel,
                    deliveryDays: parseDeliveryDays(deliveryLabel),
                    isSuperSeller: seller.superSeller || false,
                    offerId: el.id || '',
                  });
                }
                
                log.info(`Znaleziono ${offersData.length} ofert w JSON`);
              } catch (e) {
                log.warning(`Blad parsowania JSON: ${e}`);
              }
            }
          }
        }
        
        // Fallback: parsuj z DOM
        if (offersData.length === 0) {
          log.info('Probuje parsowac z DOM...');
          // Tu mozna dodac parsowanie z selektorow DOM
        }
      }
    },

    failedRequestHandler({ request }, error) {
      log.error(`Request ${request.url} failed: ${error.message}`);
      result.error = error.message;
    },
  });

  // Uruchom crawler
  try {
    await crawler.run([offerUrl]);
    
    // Filtruj po czasie dostawy
    const filtered = offersData.filter(
      o => o.deliveryDays === null || o.deliveryDays <= maxDeliveryDays
    );
    
    // Znajdz moja oferte
    const myOffer = filtered.find(
      o => o.seller.toLowerCase() === MY_SELLER.toLowerCase()
    );
    if (myOffer) {
      result.myPrice = myOffer.price;
    }
    
    // Konkurenci (bez mojej oferty)
    const competitors = filtered
      .filter(o => o.seller.toLowerCase() !== MY_SELLER.toLowerCase())
      .sort((a, b) => a.price - b.price);
    
    result.competitors = competitors;
    result.totalOffers = filtered.length;
    
    if (competitors.length > 0) {
      result.cheapest = competitors[0];
      if (result.myPrice) {
        result.priceDiff = Math.round((result.myPrice - competitors[0].price) * 100) / 100;
      }
    }
    
    result.success = offersData.length > 0;
    
  } catch (e: any) {
    result.error = e.message;
  }

  return result;
}

/**
 * Formatuje wynik do wyswietlenia
 */
function formatResult(result: ScrapingResult): string {
  const lines: string[] = [];
  
  if (!result.success) {
    return `BLAD: ${result.error}`;
  }
  
  lines.push(result.myPrice 
    ? `Moja cena: ${result.myPrice} PLN` 
    : 'Moja oferta nie znaleziona'
  );
  lines.push(`Konkurentow: ${result.competitors.length}`);
  lines.push(`Wszystkich ofert (po filtrze): ${result.totalOffers}`);
  
  if (result.cheapest) {
    lines.push(`\nNajtanszy: ${result.cheapest.seller} @ ${result.cheapest.price} PLN`);
    if (result.cheapest.deliveryText) {
      lines.push(`  Dostawa: ${result.cheapest.deliveryText}`);
    }
    if (result.priceDiff !== undefined) {
      const sign = result.priceDiff > 0 ? '+' : '';
      lines.push(`  Roznica: ${sign}${result.priceDiff} PLN`);
    }
  }
  
  if (result.competitors.length > 0) {
    lines.push('\n--- Wszyscy konkurenci ---');
    for (const c of result.competitors.slice(0, 15)) {
      const days = c.deliveryDays !== null ? `${c.deliveryDays}d` : '?';
      const superMark = c.isSuperSeller ? ' [SS]' : '';
      lines.push(`  ${c.seller.padEnd(25)} | ${c.price.toFixed(2).padStart(8)} PLN | ${days.padStart(4)}${superMark}`);
    }
    if (result.competitors.length > 15) {
      lines.push(`  ... i ${result.competitors.length - 15} wiecej`);
    }
  }
  
  return lines.join('\n');
}

/**
 * Test scrapera
 */
async function testScraper(): Promise<boolean> {
  const testUrl = 'https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323';
  
  console.log('='.repeat(60));
  console.log('CRAWLEE ALLEGRO SCRAPER TEST');
  console.log('='.repeat(60));
  console.log(`URL: ${testUrl}`);
  console.log();
  
  log.setLevel(log.LEVELS.INFO);
  
  // Test 1: Standard Playwright
  console.log('Test 1: Playwright z fingerprint spoofing...');
  let result = await scrapeAllegro(testUrl, { useCamoufox: false });
  
  if (!result.success) {
    console.log(`Blad: ${result.error}`);
    console.log('\nTest 2: Probuje z Camoufox...');
    result = await scrapeAllegro(testUrl, { useCamoufox: true });
  }
  
  console.log(formatResult(result));
  return result.success;
}

// CLI
async function main() {
  const args = process.argv.slice(2);
  
  if (args.length === 0) {
    console.log('Uzycie:');
    console.log('  npx tsx src/main.ts <allegro_url>');
    console.log('  npx tsx src/main.ts --test');
    console.log('  npx tsx src/main.ts <url> --camoufox');
    console.log('  npx tsx src/main.ts <url> --proxy=http://user:pass@host:port');
    return;
  }
  
  if (args[0] === '--test') {
    const success = await testScraper();
    process.exit(success ? 0 : 1);
  }
  
  const url = args[0];
  const useCamoufox = args.includes('--camoufox');
  const proxyArg = args.find(a => a.startsWith('--proxy='));
  const proxyUrl = proxyArg ? proxyArg.split('=')[1] : undefined;
  
  log.setLevel(log.LEVELS.INFO);
  
  const result = await scrapeAllegro(url, { useCamoufox, proxyUrl });
  
  if (result.success) {
    console.log(JSON.stringify({
      success: true,
      myPrice: result.myPrice,
      totalOffers: result.totalOffers,
      competitorCount: result.competitors.length,
      cheapest: result.cheapest,
      priceDiff: result.priceDiff,
      competitors: result.competitors,
    }, null, 2));
  } else {
    console.log(JSON.stringify({ success: false, error: result.error }, null, 2));
    process.exit(1);
  }
}

main().catch(console.error);
