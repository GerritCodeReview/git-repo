// Run as:
// `node trace_processor.js .repo/TRACE_FILE > some_file.js`
// Note taht this may fail if TRACE_FILE contains traces from a run with parallel processes.
// E.g. if it fails, delete .repo/TRACE_FILE and run `repo sync -j1` before trying
// again with trace_processor.js


const fs = require('fs').promises;

if (process.argv.length < 3) {
    throw new Error('file to process required as the first argument');
}

(async () => {
    console.log(`export const data = [`);

    const contents = await fs.readFile(process.argv[2], 'utf-8');
    const matcher = /PID:\s(\d+)\s(START|END):\s(\d+)\s:(.*)/;
    const pids = {};

    function key(pid, command) {
        return `${pid}||${command}`;
    }

    for (const l of contents.split('\n')) {
        if (l.includes('PID:')) {
            const match = (matcher).exec(l);

            const PID = match[1];
            const PHASE = match[2];
            const ts = match[3];
            const command = match[4];
            const k = key(PID, command);

            if (PHASE === "START") {
                if (pids[k] != undefined) {
                    throw new Error('new start found but existing entry present ' + k)
                }

                pids[k] = [command, ts];
            }


            if (PHASE === "END") {
                if (pids[k] == undefined) {
                    throw new Error('new end found but existing entry NOT present ' + command);
                }

                console.log(`{
                    rowId:${PID},
                    start:${Math.floor(pids[k][1]/1000000)},
                    end:${Math.floor(ts/1000000)},
                    label:"${pids[k][0]}",
                },`)
                pids[k] = undefined;
            }
        }
    }
    console.log(`]`);
})()
