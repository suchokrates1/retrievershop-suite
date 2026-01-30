export declare class LeakWarning extends Error {
    constructor(message: string);
    static warn(warningKey: string, iKnowWhatImDoing?: boolean): void;
}
