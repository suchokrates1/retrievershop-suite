import { CannotExecuteXvfb, CannotFindXvfb, VirtualDisplayNotSupported, } from './exceptions.js';
import { OS_NAME } from './pkgman.js';
import { execFileSync, spawn } from 'child_process';
import { existsSync } from 'fs';
import { tmpdir } from 'os';
// import { globSync } from 'glob';
import { randomInt } from 'crypto';
// import { Lock } from 'async-mutex';
export class VirtualDisplay {
    debug;
    proc = null;
    _display = null;
    // private _lock = new Lock();
    constructor(debug = false) {
        this.debug = debug;
    }
    get xvfb_args() {
        return [
            "-screen", "0", "1x1x24",
            "-ac",
            "-nolisten", "tcp",
            "-extension", "RENDER",
            "+extension", "GLX",
            "-extension", "COMPOSITE",
            "-extension", "XVideo",
            "-extension", "XVideo-MotionCompensation",
            "-extension", "XINERAMA",
            "-shmem",
            "-fp", "built-ins",
            "-nocursor",
            "-br",
        ];
    }
    get xvfb_path() {
        const path = execFileSync('which', ['Xvfb']).toString().trim();
        if (!path) {
            throw new CannotFindXvfb("Please install Xvfb to use headless mode.");
        }
        if (!existsSync(path) || !execFileSync('test', ['-x', path])) {
            throw new CannotExecuteXvfb(`I do not have permission to execute Xvfb: ${path}`);
        }
        return path;
    }
    get xvfb_cmd() {
        return [this.xvfb_path, `:${this.display}`, ...this.xvfb_args];
    }
    execute_xvfb() {
        if (this.debug) {
            console.log('Starting virtual display:', this.xvfb_cmd.join(' '));
        }
        this.proc = spawn(this.xvfb_cmd[0], this.xvfb_cmd.slice(1), {
            stdio: this.debug ? 'inherit' : 'ignore',
            detached: true,
        });
    }
    get() {
        VirtualDisplay.assert_linux();
        // this._lock.runExclusive(() => {
        if (!this.proc) {
            this.execute_xvfb();
        }
        else if (this.debug) {
            console.log(`Using virtual display: ${this.display}`);
        }
        // });
        return `:${this.display}`;
    }
    kill() {
        // this._lock.runExclusive(() => {
        if (this.proc && !this.proc.killed) {
            if (this.debug) {
                console.log('Terminating virtual display:', this.display);
            }
            this.proc.kill();
        }
        // });
    }
    static _get_lock_files() {
        const tmpd = process.env.TMPDIR || tmpdir();
        try {
            return [];
            // return globSync(join(tmpd, ".X*-lock")).filter(p => existsSync(p));
        }
        catch {
            return [];
        }
    }
    static _free_display() {
        const ls = VirtualDisplay._get_lock_files().map(x => parseInt(x.split("X")[1].split("-")[0]));
        return ls.length ? Math.max(99, Math.max(...ls) + randomInt(3, 20)) : 99;
    }
    get display() {
        if (this._display === null) {
            this._display = VirtualDisplay._free_display();
        }
        return this._display;
    }
    static assert_linux() {
        if (OS_NAME !== 'lin') {
            throw new VirtualDisplayNotSupported("Virtual display is only supported on Linux.");
        }
    }
}
