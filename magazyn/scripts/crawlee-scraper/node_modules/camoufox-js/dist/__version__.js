/**
 * Camoufox version constants.
 */
export class CONSTRAINTS {
    /**
     * The minimum and maximum supported versions of the Camoufox browser.
     */
    static MIN_VERSION = 'beta.19';
    static MAX_VERSION = '1';
    static asRange() {
        /**
         * Returns the version range as a string.
         */
        return `>=${CONSTRAINTS.MIN_VERSION}, <${CONSTRAINTS.MAX_VERSION}`;
    }
}
