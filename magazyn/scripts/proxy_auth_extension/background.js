// Proxy configuration
var config = {
    mode: "fixed_servers",
    rules: {
      singleProxy: {
        scheme: "http",
        host: "PROXY_HOST",
        port: parseInt("PROXY_PORT")
      },
      bypassList: ["localhost", "127.0.0.1"]
    }
  };

// Set proxy IMMEDIATELY on load
console.log("[PROXY EXT] Setting proxy to: PROXY_HOST:PROXY_PORT");
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
            username: "PROXY_USER",
            password: "PROXY_PASS"
        }
    };
}

chrome.webRequest.onAuthRequired.addListener(
    callbackFn,
    {urls: ["<all_urls>"]},
    ['blocking']
);
