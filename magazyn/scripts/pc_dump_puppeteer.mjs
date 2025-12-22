#!/usr/bin/env node
import puppeteer from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';
import fs from 'fs/promises';

// Add stealth plugin
puppeteer.use(StealthPlugin());

async function readCookies() {
    const cookiesPath = process.env.ALLEGRO_COOKIES_FILE || '/home/suchokrates1/allegro_cookies.json';
    try {
        const data = await fs.readFile(cookiesPath, 'utf-8');
        return JSON.parse(data);
    } catch (err) {
        console.log('cookies_read_error', err.message);
        return [];
    }
}

async function scrapeAllegro() {
    const offerUrl = 'https://allegro.pl/oferta/17892897249';
    
    console.log('puppeteer_stealth_starting');
    
    const browser = await puppeteer.launch({
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--window-size=1280,900',
            '--lang=pl-PL',
        ],
        executablePath: '/usr/bin/chromium',
    });
    
    try {
        const page = await browser.newPage();
        
        // Set viewport
        await page.setViewport({ width: 1280, height: 900 });
        
        // Set realistic user agent
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36');
        
        // Set extra headers
        await page.setExtraHTTPHeaders({
            'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        });
        
        // Step 1: Load homepage
        console.log('puppeteer_loading allegro.pl');
        await page.goto('https://allegro.pl/', { waitUntil: 'domcontentloaded', timeout: 60000 });
        console.log('puppeteer_loaded allegro.pl');
        await page.screenshot({ path: '/tmp/price_check_step1_home.png' });
        console.log('saved_screenshot /tmp/price_check_step1_home.png');
        
        // Step 2: Set cookies
        const cookiesData = await readCookies();
        if (cookiesData && cookiesData.length > 0) {
            const puppeteerCookies = cookiesData.map(c => ({
                name: c.name,
                value: c.value,
                domain: c.domain || '.allegro.pl',
                path: c.path || '/',
                secure: c.secure || false,
                httpOnly: c.httpOnly || false,
                sameSite: c.sameSite || 'Lax',
            })).filter(c => c.name && c.value);
            
            await page.setCookie(...puppeteerCookies);
            console.log(`puppeteer_added_cookies ${puppeteerCookies.length}`);
        }
        
        await new Promise(resolve => setTimeout(resolve, 1000));
        await page.screenshot({ path: '/tmp/price_check_step2_cookies.png' });
        console.log('saved_screenshot /tmp/price_check_step2_cookies.png');
        
        // Step 3: Load offer page
        console.log(`puppeteer_loading offer ${offerUrl}`);
        await page.goto(offerUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
        console.log('puppeteer_loaded offer');
        await new Promise(resolve => setTimeout(resolve, 3000));
        await page.screenshot({ path: '/tmp/price_check_step3_offer.png' });
        console.log('saved_screenshot /tmp/price_check_step3_offer.png');
        
        // Human-like scrolling
        console.log('puppeteer_scrolling');
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.5));
        await new Promise(resolve => setTimeout(resolve, 2000));
        await page.screenshot({ path: '/tmp/price_check_step4_scroll_mid.png' });
        console.log('saved_screenshot /tmp/price_check_step4_scroll_mid.png');
        
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.9));
        await new Promise(resolve => setTimeout(resolve, 2000));
        await page.screenshot({ path: '/tmp/price_check_step5_scroll_bottom.png' });
        console.log('saved_screenshot /tmp/price_check_step5_scroll_bottom.png');
        
        await page.evaluate(() => window.scrollTo(0, 0));
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Final screenshot and HTML
        await page.screenshot({ path: '/tmp/price_check_shot.png' });
        console.log('saved_screenshot /tmp/price_check_shot.png');
        
        const html = await page.content();
        await fs.writeFile('/tmp/price_check_offer.html', html, 'utf-8');
        console.log('saved_html /tmp/price_check_offer.html via puppeteer-stealth');
        
    } finally {
        await browser.close();
    }
}

// Run
scrapeAllegro().catch(err => {
    console.error('puppeteer_error', err.message);
    process.exit(1);
});
