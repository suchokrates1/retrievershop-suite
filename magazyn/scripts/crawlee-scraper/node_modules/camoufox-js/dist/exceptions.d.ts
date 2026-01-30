export declare class UnsupportedVersion extends Error {
    constructor(message?: string);
}
export declare class MissingRelease extends Error {
    constructor(message?: string);
}
export declare class UnsupportedArchitecture extends Error {
    constructor(message?: string);
}
export declare class UnsupportedOS extends Error {
    constructor(message?: string);
}
export declare class UnknownProperty extends Error {
    constructor(message?: string);
}
export declare class InvalidPropertyType extends Error {
    constructor(message?: string);
}
export declare class InvalidAddonPath extends Error {
    constructor(message?: string);
}
export declare class InvalidDebugPort extends Error {
    constructor(message?: string);
}
export declare class MissingDebugPort extends Error {
    constructor(message?: string);
}
export declare class LocaleError extends Error {
    constructor(message: string);
}
export declare class InvalidIP extends Error {
    constructor(message?: string);
}
export declare class InvalidProxy extends Error {
    constructor(message?: string);
}
export declare class UnknownIPLocation extends LocaleError {
    constructor(message?: string);
}
export declare class InvalidLocale extends LocaleError {
    constructor(message?: string);
    static invalidInput(locale: string): InvalidLocale;
}
export declare class UnknownTerritory extends InvalidLocale {
    constructor(message?: string);
}
export declare class UnknownLanguage extends InvalidLocale {
    constructor(message?: string);
}
export declare class NotInstalledGeoIPExtra extends Error {
    constructor(message?: string);
}
export declare class NonFirefoxFingerprint extends Error {
    constructor(message?: string);
}
export declare class InvalidOS extends Error {
    constructor(message?: string);
}
export declare class VirtualDisplayError extends Error {
    constructor(message?: string);
}
export declare class CannotFindXvfb extends VirtualDisplayError {
    constructor(message?: string);
}
export declare class CannotExecuteXvfb extends VirtualDisplayError {
    constructor(message?: string);
}
export declare class VirtualDisplayNotSupported extends VirtualDisplayError {
    constructor(message?: string);
}
export declare class CamoufoxNotInstalled extends Error {
    constructor(message?: string);
}
export declare class FileNotFoundError extends Error {
    constructor(message?: string);
}
