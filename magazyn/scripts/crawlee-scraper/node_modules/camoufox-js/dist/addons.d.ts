export declare const DefaultAddons: {
    /**
     * Default addons to be downloaded
     */
    UBO: string;
};
export declare function confirmPaths(paths: string[]): void;
export declare function addDefaultAddons(addonsList: string[], excludeList?: (keyof typeof DefaultAddons)[]): void;
/**
 * Downloads and extracts an addon from a given URL to a specified path
 */
export declare function downloadAndExtract(url: string, extractPath: string, name: string): Promise<void>;
/**
 * Downloads and extracts addons from a given dictionary to a specified list
 * Skips downloading if the addon is already downloaded
 */
export declare function maybeDownloadAddons(addons: Record<string, string>, addonsList?: string[]): void;
