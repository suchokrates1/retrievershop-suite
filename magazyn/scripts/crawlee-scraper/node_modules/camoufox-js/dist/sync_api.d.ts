import { Browser, BrowserContext, BrowserType } from 'playwright';
import { LaunchOptions } from './utils.js';
export declare function Camoufox(launch_options: LaunchOptions): Promise<BrowserContext | Browser>;
export declare function NewBrowser(playwright: BrowserType<Browser>, headless?: boolean | 'virtual', fromOptions?: Record<string, any>, persistentContext?: boolean, debug?: boolean, launch_options?: LaunchOptions): Promise<Browser | BrowserContext>;
