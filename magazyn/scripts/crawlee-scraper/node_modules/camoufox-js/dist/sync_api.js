import { firefox } from 'playwright';
import { launchOptions, syncAttachVD } from './utils.js';
import { VirtualDisplay } from './virtdisplay.js';
export async function Camoufox(launch_options) {
    return NewBrowser(firefox, false, {}, false, false, launch_options);
}
export async function NewBrowser(playwright, headless = false, fromOptions = {}, persistentContext = false, debug = false, launch_options = {}) {
    let virtualDisplay = null;
    if (headless === 'virtual') {
        virtualDisplay = new VirtualDisplay(debug);
        launch_options['virtualDisplay'] = virtualDisplay.get();
        headless = false;
    }
    if (!fromOptions || Object.keys(fromOptions).length === 0) {
        fromOptions = await launchOptions({ headless, debug, ...launch_options });
    }
    if (persistentContext) {
        const context = await playwright.launchPersistentContext('~/.crawlee/persistent-user-data-dir', fromOptions);
        return syncAttachVD(context, virtualDisplay);
    }
    const browser = await playwright.launch(fromOptions);
    return syncAttachVD(browser, virtualDisplay);
}
