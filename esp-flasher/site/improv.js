// Improv Wi-Fi over USB serial (https://www.improv-wifi.com/serial/): sends the saved Wi-Fi to a freshly flashed ESP,
// so nobody has to type the password in the ESP Web Tools dialog (Claude AI, 2026-10-30).
//
// Packet: "IMPROV" + version 1 + type + length + data + checksum (sum of all previous bytes) + "\n".
const HEADER = [0x49, 0x4d, 0x50, 0x52, 0x4f, 0x56, 0x01];
const TYPE = {state: 0x01, error: 0x02, rpc: 0x03, result: 0x04};
const CMD = {wifi: 0x01, state: 0x02, info: 0x03};
export const STATE = {0x02: 'Enheden er klar', 0x03: 'Enheden forbinder til Wi-Fi …', 0x04: 'Enheden er på Wi-Fi'};
const ERRORS = {
    0x01: 'Ugyldig kommando', 0x02: 'Ukendt kommando',
    0x03: 'Kunne ikke komme på Wi-Fi – tjek navn og kode', 0x04: 'Ikke tilladt', 0xff: 'Ukendt fejl',
};

function packet(type, data) {
    const out = [...HEADER, type, data.length, ...data];
    out.push(out.reduce((a, b) => (a + b) & 0xff, 0), 0x0a);
    return new Uint8Array(out);
}

function rpc(command, payload = []) {
    return packet(TYPE.rpc, [command, payload.length, ...payload]);
}

function strings(bytes) {
    const out = [];
    for (let i = 0; i < bytes.length;) {
        const n = bytes[i++];
        out.push(new TextDecoder().decode(new Uint8Array(bytes.slice(i, i + n))));
        i += n;
    }
    return out;
}

/** Parses Improv packets out of a raw byte stream (the device also prints its normal log on the same port). */
export class ImprovParser {
    constructor() { this.buf = []; }
    push(chunk) {
        this.buf.push(...chunk);
        const packets = [];
        for (;;) {
            const start = this.findHeader();
            if (start < 0) { this.buf = this.buf.slice(-HEADER.length); break; }
            if (start > 0) this.buf = this.buf.slice(start);
            if (this.buf.length < 9) break;
            const len = this.buf[8];
            if (this.buf.length < 10 + len) break;
            const body = this.buf.slice(0, 9 + len);
            const sum = body.reduce((a, b) => (a + b) & 0xff, 0);
            if (sum === this.buf[9 + len]) packets.push({type: body[7], data: body.slice(9)});
            this.buf = this.buf.slice(10 + len);
        }
        return packets;
    }
    findHeader() {
        for (let i = 0; i + HEADER.length <= this.buf.length; i++) {
            if (HEADER.every((b, j) => this.buf[i + j] === b)) return i;
        }
        return -1;
    }
}

/**
 * Sends ssid/password to the ESP on `port` (a Web Serial port, closed). Calls onStatus(text) along the way and
 * resolves with {ok, urls, message}. The port is closed again afterwards.
 */
export async function provisionWifi(port, ssid, password, onStatus = () => {}, timeoutMs = 45000) {
    const enc = new TextEncoder();
    const s = enc.encode(ssid), p = enc.encode(password);
    if (s.length > 32 || p.length > 64) throw new Error('Wi-Fi-navn eller -kode er for lang');
    await port.open({baudRate: 115200});
    // Do not hold the chip in reset/download mode (ESP32-C3/C6/H2 USB-serial follows DTR/RTS)
    try { await port.setSignals({dataTerminalReady: false, requestToSend: false}); } catch { /* not every adapter */ }
    const writer = port.writable.getWriter();
    const reader = port.readable.getReader();
    const parser = new ImprovParser();
    let state = null;
    const deadline = Date.now() + timeoutMs;
    let sentWifi = false, lastAsk = 0, pending = null;
    const WAIT = Symbol('wait');
    try {
        onStatus('Venter på enheden …');
        while (Date.now() < deadline) {
            if (!sentWifi && Date.now() - lastAsk > 1500) {   // ask until it answers (it may still be booting)
                await writer.write(rpc(CMD.state));
                lastAsk = Date.now();
            }
            // One read at a time: a read that loses the race stays pending and is used next round (no lost bytes)
            if (!pending) pending = reader.read();
            const chunk = await Promise.race([pending, new Promise((r) => setTimeout(() => r(WAIT), 500))]);
            if (chunk === WAIT) continue;
            pending = null;
            if (chunk.done) break;
            if (!chunk.value) continue;
            for (const pk of parser.push(Array.from(chunk.value))) {
                if (pk.type === TYPE.state) {
                    state = pk.data[0];
                    onStatus(STATE[state] || 'Enheden svarer');
                    if (state === 0x02 && !sentWifi) {
                        onStatus(`Sender Wi-Fi "${ssid}" …`);
                        await writer.write(rpc(CMD.wifi, [s.length, ...s, p.length, ...p]));
                        sentWifi = true;
                    }
                } else if (pk.type === TYPE.error && pk.data[0] !== 0x00) {
                    return {ok: false, message: ERRORS[pk.data[0]] || 'Fejl fra enheden'};
                } else if (pk.type === TYPE.result) {
                    const cmd = pk.data[0];
                    const urls = strings(pk.data.slice(2));
                    if (cmd === CMD.wifi || (cmd === CMD.state && state === 0x04)) {
                        return {ok: true, urls, message: state === 0x04 && !sentWifi
                            ? 'Enheden var allerede på Wi-Fi' : 'Enheden er på Wi-Fi'};
                    }
                }
            }
        }
        return {ok: false, message: sentWifi ? 'Enheden svarede ikke – tjek Wi-Fi-koden' : 'Enheden svarede ikke på Improv'};
    } finally {
        try { await reader.cancel(); } catch { /* ignore */ }
        try { reader.releaseLock(); } catch { /* ignore */ }
        try { writer.releaseLock(); } catch { /* ignore */ }
        try { await port.close(); } catch { /* ignore */ }
    }
}

export const _test = {packet, rpc, strings};
