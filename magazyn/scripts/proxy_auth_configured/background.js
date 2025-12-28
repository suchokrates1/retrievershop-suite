// Proxy configuration
var config = {
    mode: "fixed_servers",
    rules: {
      singleProxy: {
        scheme: "http",
        host: "res.geonix.com",
        port: parseInt("10000")
      },
      bypassList: ["localhost", "127.0.0.1"]
    }
  };

// Set proxy IMMEDIATELY on load
console.log("[PROXY EXT] Setting proxy to: res.geonix.com:10000");
chrome.proxy.settings.set({value: config, scope: "regular"}, function() {
    if (chrome.runtime.lastError) {
        console.error("[PROXY EXT] Error setting proxy:", chrome.runtime.lastError);
    } else {
        console.log("[PROXY EXT] Proxy set successfully!");
    }
});

// Handle authentication
function callbackFn(details) {
    console.log("[PROXY EXT] Auth requested for:", details.challenger.host);
    return {
        authCredentials: {
            username: "0e7fda9b3495e89f",
            password: "ktZ7KLWr"
        }
    };
}

chrome.webRequest.onAuthRequired.addListener(
    callbackFn,
    {urls: ["<all_urls>"]},
    ['blocking']
);
