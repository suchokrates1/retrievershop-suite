import { Impit } from 'impit';
export class InvalidIP extends Error {
}
export class InvalidProxy extends Error {
}
export class ProxyHelper {
    static parseServer(server) {
        const proxyMatch = server.match(/^(?:(\w+):\/\/)?(.*?)(?::(\d+))?$/);
        if (!proxyMatch) {
            throw new InvalidProxy(`Invalid proxy server: ${server}`);
        }
        return {
            schema: proxyMatch[1] || 'http',
            url: proxyMatch[2],
            port: proxyMatch[3]
        };
    }
    static asString(proxy) {
        const { schema, url, port } = this.parseServer(proxy.server);
        let result = `${schema}://`;
        if (proxy.username) {
            result += proxy.username;
            if (proxy.password) {
                result += `:${proxy.password}`;
            }
            result += '@';
        }
        result += url;
        if (port) {
            result += `:${port}`;
        }
        return result;
    }
    static asAxiosProxy(proxyString) {
        return {
            http: proxyString,
            https: proxyString,
        };
    }
}
export function validIPv4(ip) {
    if (!ip) {
        return false;
    }
    return /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/.test(ip);
}
export function validIPv6(ip) {
    if (!ip) {
        return false;
    }
    return /^(([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4})$/.test(ip);
}
export function validateIP(ip) {
    if (!validIPv4(ip) && !validIPv6(ip)) {
        throw new InvalidIP(`Invalid IP address: ${ip}`);
    }
}
export async function publicIP(proxy) {
    const URLS = [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://ipinfo.io/ip",
        "https://icanhazip.com",
        "https://ifconfig.co/ip",
        "https://ipecho.net/plain",
    ];
    for (const url of URLS) {
        try {
            const impit = new Impit({
                proxyUrl: proxy,
                timeout: 5000,
            });
            const response = await impit.fetch(url);
            if (!response.ok) {
                continue;
            }
            const ip = (await response.text()).trim();
            validateIP(ip);
            return ip;
        }
        catch (error) {
            console.warn(new InvalidProxy(`Failed to connect to proxy: ${proxy}`));
        }
    }
    throw new InvalidIP("Failed to get IP address");
}
