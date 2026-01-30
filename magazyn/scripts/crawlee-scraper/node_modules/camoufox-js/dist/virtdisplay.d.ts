export declare class VirtualDisplay {
    private debug;
    private proc;
    private _display;
    constructor(debug?: boolean);
    private get xvfb_args();
    private get xvfb_path();
    private get xvfb_cmd();
    private execute_xvfb;
    get(): string;
    kill(): void;
    static _get_lock_files(): string[];
    private static _free_display;
    private get display();
    private static assert_linux;
}
