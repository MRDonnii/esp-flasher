// ESP Flasher UI (Claude AI, 2026-10-30): firmware catalog with one ESP Web Tools button per firmware, first-run setup
// (standalone), settings, and "Send Wi-Fi" that hands the saved Wi-Fi to a freshly flashed device over USB (Improv).
// All URLs are relative, so the page works both on its own HTTPS port and inside Home Assistant (Ingress).
import {provisionWifi} from './improv.js';

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const KIND_LABEL = {any: 'Alle', zigbee: 'Zigbee', wifi: 'Wi-Fi'};
const state = {
    status: {}, list: [],
    chip: localStorage.getItem('ef-chip') || 'any',
    kind: localStorage.getItem('ef-kind') || 'any',
};

// ---------- small helpers ---------------------------------------------------------------------------------------
async function api(path, {method = 'GET', body} = {}) {
    const res = await fetch(path, {
        method, credentials: 'same-origin', cache: 'no-store',
        headers: body ? {'Content-Type': 'application/json'} : {},
        body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (!res.ok) throw Object.assign(new Error(data.error || `Fejl ${res.status}`), {status: res.status});
    return data;
}

let toastTimer;
function toast(msg, kind = 'ok') {
    const t = $('#toast');
    t.className = `toast ${kind}`;
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 4200);
}

let modalClose = null;
function openModal(html, {wide = false, onClose = null, locked = false} = {}) {
    const m = $('#modal');
    $('#modal-body').innerHTML = html;
    m.querySelector('.modal-card').classList.toggle('wide', wide);
    m.querySelector('.modal-x').hidden = locked;
    m.dataset.locked = locked ? '1' : '';
    m.hidden = false;
    modalClose = onClose;
    const first = m.querySelector('input:not([type=hidden]), button.primary');
    if (first) setTimeout(() => first.focus(), 30);
    return $('#modal-body');
}
function closeModal() {
    $('#modal').hidden = true;
    $('#modal-body').innerHTML = '';
    const cb = modalClose; modalClose = null;
    if (cb) cb();
}
document.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-close]') || (ev.target.id === 'modal' && !$('#modal').dataset.locked)) closeModal();
});
document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !$('#modal').hidden && !$('#modal').dataset.locked) closeModal();
});

function field(id, label, {type = 'text', value = '', placeholder = '', hint = '', attrs = ''} = {}) {
    const eye = type === 'password'
        ? `<button type="button" class="eye" data-eye="${id}" aria-label="Vis/skjul">👁</button>` : '';
    return `<label class="field"><span>${label}</span><div class="input-wrap"><input id="${id}" type="${type}"
        value="${esc(value)}" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false" ${attrs}>${eye}</div>
        ${hint ? `<small>${hint}</small>` : ''}</label>`;
}
document.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-eye]');
    if (!b) return;
    const inp = document.getElementById(b.dataset.eye);
    inp.type = inp.type === 'password' ? 'text' : 'password';
});

function formError(el, msg) {
    const box = $('.form-error', el);
    box.textContent = msg || '';
    box.hidden = !msg;
}

const isHa = () => state.status.mode === 'ha';
const unlocked = () => isHa() || state.status.logged_in;

// ---------- environment / header ---------------------------------------------------------------------------------
function topOrigin() {
    try { return window.top.location.origin; } catch { return location.origin; }
}
function topPath() {
    try { return window.top.location.pathname; } catch { return '/'; }
}

function renderEnvironment() {
    const env = $('#env');
    const s = state.status;
    const parts = [];
    let level = 'warn';
    // Chrome hides the USB API completely on a page without https, so check that first
    if (!window.isSecureContext) {
        level = 'bad';
        const origin = topOrigin();
        const https = (s.external_url || '').startsWith('https://') ? s.external_url : '';
        parts.push(`<b>USB er spærret, fordi siden er åbnet uden https</b> (${esc(origin)}).`);
        if (https) {
            parts.push(`<a class="btn small primary" href="${esc(https + topPath())}" target="_top">Åbn via ${esc(https)}</a>`);
        }
        parts.push(`${https ? 'Eller tillad' : 'Tillad'} adressen én gang i Chrome: åbn <code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code>,
            indsæt <code>${esc(origin)}</code> <button class="btn tiny" data-copy="${esc(origin)}">Kopiér</button>,
            vælg <b>Enabled</b> og genstart Chrome.`);
    } else if (!('serial' in navigator)) {
        level = 'bad';
        parts.push('<b>Denne browser kan ikke tale med USB.</b> Brug <b>Chrome</b> eller <b>Edge</b> på en computer.');
    }
    env.className = `banner ${level}`;
    env.innerHTML = parts.map((p) => `<div>${p}</div>`).join('');
    env.hidden = !parts.length;
}

function renderHeader() {
    const s = state.status;
    $('#subtitle').textContent = s.name ? `${s.name} · flash firmware med et USB-kabel` : 'Flash firmware direkte fra browseren med et USB-kabel';
    const badge = $('#mode-badge');
    badge.hidden = !s.setup_done;
    badge.className = `pill ${isHa() ? 'ha' : unlocked() ? 'open' : 'locked'}`;
    badge.textContent = isHa() ? 'Home Assistant' : unlocked() ? 'Låst op' : 'Låst';
    $('#btn-settings').hidden = !s.setup_done;
    $('#foot-version').textContent = `ESP Flasher ${s.version || ''}`.trim();
    $('#foot-cert').hidden = isHa();
    renderFirmware();
}

// Firmware comes from GitHub while the app runs (api: fwsync), so a new build shows up without updating the app
function renderFirmware() {
    const f = state.status.firmware;
    $('#foot-fw').hidden = !f;
    if (!f) return;
    const built = f.generated ? new Date(f.generated).toLocaleString('da-DK', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : '';
    const src = {github: 'hentet fra GitHub', app: 'fra appen', local: 'lokal build'}[f.source] || '';
    $('#fw-text').textContent = [built && `Firmware fra ${built}`, src, f.live && 'opdateres automatisk'].filter(Boolean).join(' · ');
    $('#fw-text').title = f.error ? `Sidste tjek fejlede: ${f.error}`
        : f.checked ? `Sidst tjekket ${new Date(f.checked * 1000).toLocaleTimeString('da-DK', {hour: '2-digit', minute: '2-digit'})}` : '';
    $('#fw-check').hidden = !f.live;
}

async function loadCatalog() {
    try {
        const res = await fetch('firmware/catalog.json', {cache: 'no-store'});
        state.list = (await res.json()).firmwares || [];
    } catch (err) {
        $('#list').innerHTML = `<p class="muted">Kunne ikke hente firmware-listen (${esc(err.message)}).</p>`;
    }
}

$('#fw-check').addEventListener('click', async (ev) => {
    const b = ev.currentTarget;
    b.disabled = true; b.textContent = 'Søger …';
    try {
        const r = await api('api/firmware/check', {method: 'POST'});
        state.status.firmware = r;
        if (r.updated) { await loadCatalog(); render(); toast('Ny firmware er hentet'); }
        else if (r.error) toast(`Kunne ikke tjekke GitHub: ${r.error}`, 'bad');
        else toast('Du har den nyeste firmware');
    } catch (err) { toast(err.message, 'bad'); }
    b.disabled = false; b.textContent = 'Søg efter ny';
    renderFirmware();
});

document.addEventListener('click', async (ev) => {
    const b = ev.target.closest('[data-copy]');
    if (!b) return;
    try { await navigator.clipboard.writeText(b.dataset.copy); toast('Kopieret'); } catch { toast('Kunne ikke kopiere', 'bad'); }
});

// ---------- catalog ---------------------------------------------------------------------------------------------
function renderFilters() {
    const count = (pred) => state.list.filter(pred).length;
    const chips = ['any', ...new Set(state.list.map((f) => f.chip))];
    if (!chips.includes(state.chip)) state.chip = 'any';
    $('#chip-filter').innerHTML = chips.map((c) => `<button class="${state.chip === c ? 'on' : ''}" data-chip="${esc(c)}">`
        + `${c === 'any' ? 'Alle' : esc(c)}<small>${count((f) => c === 'any' || f.chip === c)}</small></button>`).join('');
    const inChip = state.list.filter((f) => state.chip === 'any' || f.chip === state.chip);
    const kinds = ['any', ...new Set(inChip.map((f) => f.kind))];
    if (!kinds.includes(state.kind)) state.kind = 'any';
    $('#kind-filter').innerHTML = kinds.map((k) => `<button class="${state.kind === k ? 'on' : ''}" data-kind="${esc(k)}">`
        + `${esc(KIND_LABEL[k] || k)}<small>${k === 'any' ? inChip.length : inChip.filter((f) => f.kind === k).length}</small></button>`).join('');
}

function changelog(fw) {
    const log = fw.changelog || [];
    if (!log.length) return '';
    const list = (items) => `<ul class="features">${(items || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
    if (typeof log[0] === 'string') return `<details><summary>Nyheder i v${esc(fw.version)}</summary>${list(log)}</details>`;
    const [latest, ...older] = log;
    return `<details class="release"><summary>Nyt i v${esc(latest.version)}${latest.title ? ` – ${esc(latest.title)}` : ''}</summary>${list(latest.items)}</details>`
        + (older.length ? `<details><summary>Tidligere versioner</summary>${older.map((r) =>
            `<div class="old-rel"><b>v${esc(r.version)}</b>${list(r.items)}</div>`).join('')}</details>` : '');
}

function wifiBox(fw) {
    if (fw.kind !== 'wifi') return '';
    const s = state.status;
    if (!s.has_wifi) {
        return `<div class="wifi-box empty">📶 Gem dit Wi-Fi i <a href="#" data-open-settings>indstillingerne</a>,
            så kan den sendes til enheden efter flash med ét klik.</div>`;
    }
    return `<div class="wifi-box">
        <div>📶 Efter flash: send dit Wi-Fi${unlocked() && s.wifi_ssid ? ` <b>${esc(s.wifi_ssid)}</b>` : ''} til enheden</div>
        <div class="row">
          <button class="btn primary small" data-send-wifi="${esc(fw.id)}">Send Wi-Fi</button>
          <button class="btn small" data-copy-wifi>Kopiér kode</button>
        </div>
      </div>`;
}

function card(fw) {
    const status = fw.status === 'testet'
        ? '<span class="tag ok">Testet</span>' : `<span class="tag warn">${esc(fw.status || 'Ikke testet endnu')}</span>`;
    const wiring = (fw.wiring || []).length ? `<details><summary>Ledninger</summary><table class="wiring">${fw.wiring.map(([a, b]) =>
        `<tr><td>${esc(a)}</td><td class="arrow">→</td><td>${esc(b)}</td></tr>`).join('')}</table></details>` : '';
    const after = fw.after ? `<details><summary>Efter flash</summary><div class="note">${esc(fw.after)}</div></details>` : '';
    const ota = fw.ota ? `<div class="note">🔄 ${esc(fw.ota)}</div>` : '';
    return `<article class="card kind-${esc(fw.kind)}">
      <header>
        <div class="card-icon">${fw.kind === 'zigbee' ? '⬡' : '📶'}</div>
        <div class="card-head">
          <h3>${esc(fw.name)}</h3>
          <div class="sub">${esc(fw.chip)} · v${esc(fw.version)}${fw.date ? ` · ${esc(fw.date)}` : ''}</div>
        </div>
      </header>
      <div class="tags"><span class="tag kind">${esc(fw.kindLabel || KIND_LABEL[fw.kind] || fw.kind)}</span>${status}</div>
      ${fw.summary ? `<p class="summary">${esc(fw.summary)}</p>` : ''}
      ${(fw.features || []).length ? `<ul class="features">${fw.features.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      <div class="more">${changelog(fw)}${wiring}${after}</div>
      ${ota}
      <div class="actions">
        <esp-web-install-button manifest="firmware/${esc(fw.manifest)}">
          <button slot="activate" class="btn flash">⚡ Flash via USB</button>
          <span slot="unsupported" class="note">USB-flash kræver Chrome eller Edge på en computer.</span>
          <span slot="not-allowed" class="note">USB-flash kræver https – se øverst på siden.</span>
        </esp-web-install-button>
        ${wifiBox(fw)}
      </div>
    </article>`;
}

function renderList() {
    const items = state.list.filter((f) => (state.chip === 'any' || f.chip === state.chip)
        && (state.kind === 'any' || f.kind === state.kind));
    $('#list').innerHTML = items.map(card).join('');
    $('#empty').hidden = items.length > 0;
}

function render() {
    renderHeader();
    renderEnvironment();
    renderFilters();
    renderList();
}

document.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-chip],[data-kind]');
    if (!b) return;
    if (b.dataset.chip) { state.chip = b.dataset.chip; localStorage.setItem('ef-chip', state.chip); }
    if (b.dataset.kind) { state.kind = b.dataset.kind; localStorage.setItem('ef-kind', state.kind); }
    renderFilters();
    renderList();
});

// ---------- unlock (standalone) ----------------------------------------------------------------------------------
function unlock(reason = 'Skriv adminkoden for at fortsætte.') {
    if (unlocked()) return Promise.resolve(true);
    return new Promise((resolve) => {
        let done = false;
        const el = openModal(`<h2 id="modal-title">🔒 Lås op</h2><p class="muted">${esc(reason)}</p>
            <form id="f-unlock">${field('u-code', 'Adminkode', {type: 'password', attrs: 'autocomplete="current-password"'})}
            <p class="form-error" hidden></p>
            <div class="modal-actions"><button type="button" class="btn" data-close>Annullér</button>
            <button class="btn primary">Lås op</button></div></form>`, {onClose: () => { if (!done) resolve(false); }});
        $('#f-unlock', el).addEventListener('submit', async (ev) => {
            ev.preventDefault();
            try {
                await api('api/login', {method: 'POST', body: {admin_code: $('#u-code', el).value}});
                done = true;
                await loadStatus();
                closeModal();
                render();
                resolve(true);
            } catch (err) { formError(el, err.message); }
        });
    });
}

// ---------- Wi-Fi ----------------------------------------------------------------------------------------------
async function savedWifi() {
    if (!(await unlock('Adminkoden skal til, før Wi-Fi-koden kan bruges.'))) return null;
    return api('api/wifi');
}

document.addEventListener('click', async (ev) => {
    if (ev.target.closest('[data-copy-wifi]')) {
        const w = await savedWifi().catch((e) => { toast(e.message, 'bad'); return null; });
        if (!w) return;
        try {
            await navigator.clipboard.writeText(w.password || '');
            toast(`Koden til "${w.ssid}" er kopieret – sæt den ind i dialogen`);
        } catch { toast('Kunne ikke kopiere', 'bad'); }
    }
    if (ev.target.closest('[data-open-settings]')) { ev.preventDefault(); openSettings(); }
    const send = ev.target.closest('[data-send-wifi]');
    if (send) sendWifi(state.list.find((f) => f.id === send.dataset.sendWifi));
});

async function sendWifi(fw) {
    if (!('serial' in navigator) || !window.isSecureContext) { toast('USB er ikke tilgængelig her – se øverst på siden', 'bad'); return; }
    const w = await savedWifi().catch((e) => { toast(e.message, 'bad'); return null; });
    if (!w) return;
    if (!w.ssid) { toast('Der er ikke gemt noget Wi-Fi', 'bad'); return; }
    const el = openModal(`<h2 id="modal-title">📶 Send Wi-Fi til ${esc(fw?.name || 'enheden')}</h2>
        <ol class="steps-list"><li>Luk installationsdialogen, hvis den stadig er åben.</li>
        <li>Lad ESP'en sidde i USB efter flash.</li><li>Tryk <b>Vælg enhed</b> og vælg den samme port som før.</li></ol>
        <div class="progress" hidden><div class="spinner"></div><span id="pv-status"></span></div>
        <div id="pv-result"></div>
        <div class="modal-actions"><button class="btn" data-close>Luk</button>
        <button class="btn primary" id="pv-go">Vælg enhed</button></div>`);
    $('#pv-go', el).addEventListener('click', async () => {
        let port;
        try { port = await navigator.serial.requestPort(); } catch { return; }   // the user closed the port picker
        $('#pv-go', el).disabled = true;
        $('.progress', el).hidden = false;
        $('#pv-result', el).innerHTML = '';
        try {
            const res = await provisionWifi(port, w.ssid, w.password, (s) => { $('#pv-status', el).textContent = s; });
            $('.progress', el).hidden = true;
            const links = (res.urls || []).filter((u) => /^https?:\/\//.test(u))
                .map((u) => `<a class="btn small" href="${esc(u)}" target="_blank" rel="noopener">Åbn enheden</a>`).join('');
            $('#pv-result', el).innerHTML = res.ok
                ? `<div class="result ok">✅ ${esc(res.message)}. ${fw?.after_wifi ? esc(fw.after_wifi)
                    : 'Den dukker op i Home Assistant under Enheder → ESPHome som fundet enhed.'}<div class="row">${links}</div></div>`
                : `<div class="result bad">⚠️ ${esc(res.message)}</div>`;
        } catch (err) {
            $('.progress', el).hidden = true;
            $('#pv-result', el).innerHTML = `<div class="result bad">⚠️ ${esc(err.message.includes('open') || err.name === 'InvalidStateError'
                ? 'Porten er optaget – luk installationsdialogen og prøv igen' : err.message)}</div>`;
        } finally {
            $('#pv-go', el).disabled = false;
            $('#pv-go', el).textContent = 'Prøv igen';
        }
    });
}

// ---------- first-run setup (standalone) -------------------------------------------------------------------------
function openWizard() {
    const data = {name: '', admin_code: '', wifi_ssid: '', wifi_password: '', hosts: [location.hostname], ha_url: ''};
    const steps = [
        {title: 'Velkommen 👋', body: () => `<p>Her sætter du flasheren op til dit hjem. Intet af det gemmes i koden –
            kun her på serveren (i en secrets-fil, som kun den selv kan læse).</p>
            ${field('w-name', 'Navn på installationen', {value: data.name, placeholder: 'Fx Hjemme hos Jan', hint: 'Vises øverst på siden.'})}`,
         save: (el) => { data.name = $('#w-name', el).value.trim(); if (!data.name) throw new Error('Skriv et navn'); }},
        {title: 'Adminkode 🔒', body: () => `<p>Koden beskytter indstillingerne og din Wi-Fi-kode. Den gemmes kun som en hash.</p>
            ${field('w-code', 'Adminkode (mindst 6 tegn)', {type: 'password', attrs: 'autocomplete="new-password"'})}
            ${field('w-code2', 'Gentag koden', {type: 'password', attrs: 'autocomplete="new-password"'})}`,
         save: (el) => {
             const a = $('#w-code', el).value, b = $('#w-code2', el).value;
             if (a.length < 6) throw new Error('Koden skal være mindst 6 tegn');
             if (a !== b) throw new Error('De to koder er ikke ens');
             data.admin_code = a;
         }},
        {title: 'Wi-Fi til nye enheder 📶', body: () => `<p>Wi-Fi-enheder (fx Qlima Control) kan få dit Wi-Fi automatisk efter flash.
            Det er valgfrit – du kan også skrive det i dialogen hver gang.</p>
            ${field('w-ssid', 'Wi-Fi-navn (SSID)', {value: data.wifi_ssid, placeholder: 'Dit 2,4 GHz-netværk', hint: 'ESP-enheder kan kun 2,4 GHz.'})}
            ${field('w-pass', 'Wi-Fi-kode', {type: 'password', value: data.wifi_password})}`,
         save: (el) => { data.wifi_ssid = $('#w-ssid', el).value.trim(); data.wifi_password = $('#w-pass', el).value; }},
        {title: 'Adresse 🌐', body: () => `<p>Adressen du åbner flasheren på. Certifikatet laves til netop den, så browseren ikke
            advarer, når du har installeret det.</p>
            ${field('w-hosts', 'Adresse(r)', {value: data.hosts.join(', '), hint: 'IP eller navn, fx 192.168.1.10, nas.local – adskil med komma.'})}
            ${field('w-ha', 'Home Assistant (valgfri)', {value: data.ha_url, placeholder: 'https://homeassistant.local:8123', hint: 'Bruges til et link efter flash.'})}`,
         save: (el) => {
             data.hosts = $('#w-hosts', el).value.split(/[,\s]+/).map((h) => h.trim()).filter(Boolean);
             data.ha_url = $('#w-ha', el).value.trim();
         }},
    ];
    let i = 0;
    const show = () => {
        const st = steps[i];
        const el = openModal(`<div class="wizard">
            <div class="dots">${steps.map((_, n) => `<span class="${n < i ? 'done' : n === i ? 'on' : ''}"></span>`).join('')}<span class="${i >= steps.length ? 'on' : ''}"></span></div>
            <h2 id="modal-title">${st.title}</h2>
            <form id="f-wiz">${st.body()}<p class="form-error" hidden></p>
            <div class="modal-actions">${i ? '<button type="button" class="btn" id="w-back">Tilbage</button>' : '<span></span>'}
            <button class="btn primary">${i === steps.length - 1 ? 'Gem og afslut' : 'Næste'}</button></div></form></div>`,
        {locked: true, wide: true});
        $('#w-back', el)?.addEventListener('click', () => { try { st.save(el); } catch { /* keep going back */ } i--; show(); });
        $('#f-wiz', el).addEventListener('submit', async (ev) => {
            ev.preventDefault();
            try { st.save(el); } catch (err) { formError(el, err.message); return; }
            if (i < steps.length - 1) { i++; show(); return; }
            try {
                $('button.primary', el).disabled = true;
                await api('api/setup', {method: 'POST', body: data});
                await loadStatus();
                finished();
            } catch (err) { formError(el, err.message); $('button.primary', el).disabled = false; }
        });
    };
    const finished = () => {
        openModal(`<div class="wizard"><div class="dots">${steps.map(() => '<span class="done"></span>').join('')}<span class="on"></span></div>
            <h2 id="modal-title">Færdig ✅</h2>
            <p>Flasheren er sat op. Installér certifikatet én gang på hver computer, du flasher fra, så forsvinder
            browserens advarsel:</p>
            <div class="row"><a class="btn primary" href="ca.crt">⬇ Hent certifikat</a></div>
            <details><summary>Windows</summary><div class="note">Dobbeltklik på filen → <i>Installer certifikat</i> → <i>Lokal computer</i> →
              <i>Placer alle certifikater i nedenstående lager</i> → <i>Nøglecentre, der er tillid til, og som er rodnøglecentre</i>.
              Genstart Chrome.</div></details>
            <details><summary>macOS</summary><div class="note">Dobbeltklik på filen (Nøglering åbner) → find <i>ESP Flasher lokal CA</i> →
              dobbeltklik → <i>Tillid</i> → <i>Brug altid</i>. Genstart Chrome.</div></details>
            <details><summary>Linux</summary><div class="note">Chrome → Indstillinger → Privatliv og sikkerhed → Sikkerhed →
              Administrer certifikater → Autoriteter → Importér filen og sæt flueben ved websteder.</div></details>
            <div class="modal-actions"><span></span><button class="btn primary" id="w-done">Kom i gang</button></div></div>`,
        {locked: true, wide: true});
        $('#w-done').addEventListener('click', () => location.reload());
    };
    show();
}

// ---------- settings ---------------------------------------------------------------------------------------------
async function openSettings() {
    if (isHa()) {
        const s = state.status;
        openModal(`<h2 id="modal-title">⚙️ Indstillinger</h2>
            <p>Som Home Assistant-app laves indstillingerne i Home Assistant:<br>
            <b>Indstillinger → Apps → ESP Flasher → Konfiguration</b> (navn, Wi-Fi-navn og Wi-Fi-kode).</p>
            <dl class="kv"><dt>Navn</dt><dd>${esc(s.name || '–')}</dd><dt>Wi-Fi</dt><dd>${esc(s.wifi_ssid || 'ikke sat')}</dd>
            <dt>Version</dt><dd>${esc(s.version || '–')}</dd></dl>
            <p class="muted">Adgang styres af Home Assistants eget login. USB-flash kræver, at Home Assistant er åbnet via https.</p>
            <div class="modal-actions"><span></span><button class="btn primary" data-close>OK</button></div>`);
        return;
    }
    if (!(await unlock('Skriv adminkoden for at ændre indstillingerne.'))) return;
    let cfg;
    try { cfg = await api('api/settings'); } catch (err) { toast(err.message, 'bad'); return; }
    const el = openModal(`<h2 id="modal-title">⚙️ Indstillinger</h2>
        <form id="f-set">
          ${field('s-name', 'Navn på installationen', {value: cfg.name})}
          <div class="grid2">
            ${field('s-ssid', 'Wi-Fi-navn (SSID)', {value: cfg.wifi_ssid})}
            ${field('s-pass', 'Wi-Fi-kode', {type: 'password', placeholder: cfg.has_wifi_password ? '•••••• gemt – skriv ny for at ændre' : ''})}
          </div>
          ${field('s-hosts', 'Adresse(r) til certifikatet', {value: (cfg.hosts || []).join(', '), hint: 'Ændres de, laves et nyt servercertifikat (samme CA).'})}
          ${field('s-ha', 'Home Assistant (valgfri)', {value: cfg.ha_url})}
          <details><summary>Skift adminkode</summary>
            <div class="grid2">${field('s-old', 'Nuværende kode', {type: 'password'})}${field('s-new', 'Ny kode (mindst 6 tegn)', {type: 'password'})}</div>
          </details>
          <p class="form-error" hidden></p>
          <div class="modal-actions">
            <button type="button" class="btn danger" id="s-reset">Nulstil</button>
            <span class="spacer"></span>
            <button type="button" class="btn" id="s-lock">Lås</button>
            <button class="btn primary">Gem</button>
          </div>
        </form>`, {wide: true});
    $('#f-set', el).addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const body = {
            name: $('#s-name', el).value, wifi_ssid: $('#s-ssid', el).value, ha_url: $('#s-ha', el).value,
            hosts: $('#s-hosts', el).value.split(/[,\s]+/).filter(Boolean),
        };
        if ($('#s-pass', el).value) body.wifi_password = $('#s-pass', el).value;
        if ($('#s-new', el).value) { body.new_admin_code = $('#s-new', el).value; body.admin_code = $('#s-old', el).value; }
        try {
            await api('api/settings', {method: 'PUT', body});
            await loadStatus();
            closeModal();
            render();
            toast('Indstillingerne er gemt');
        } catch (err) { formError(el, err.message); }
    });
    $('#s-lock', el).addEventListener('click', async () => {
        await api('api/logout', {method: 'POST'}).catch(() => {});
        await loadStatus(); closeModal(); render(); toast('Låst');
    });
    $('#s-reset', el).addEventListener('click', () => {
        const r = openModal(`<h2 id="modal-title">Nulstil flasheren?</h2>
            <p>Navn, adminkode, Wi-Fi og adresser slettes, og opsætningen starter forfra. Firmware og certifikat bevares.</p>
            <form id="f-reset">${field('r-code', 'Adminkode', {type: 'password'})}<p class="form-error" hidden></p>
            <div class="modal-actions"><button type="button" class="btn" data-close>Annullér</button>
            <button class="btn danger">Nulstil</button></div></form>`);
        $('#f-reset', r).addEventListener('submit', async (ev) => {
            ev.preventDefault();
            try {
                await api('api/reset', {method: 'POST', body: {admin_code: $('#r-code', r).value}});
                location.reload();
            } catch (err) { formError(r, err.message); }
        });
    });
}
$('#btn-settings').addEventListener('click', openSettings);

// ---------- start ------------------------------------------------------------------------------------------------
async function loadStatus() {
    try { state.status = await api('api/status'); } catch { state.status = {setup_done: true, mode: 'static'}; }
}

await loadStatus();
await loadCatalog();
render();
// A page left open picks up firmware that arrived in the background
setInterval(async () => {
    if (!$('#modal').hidden || document.querySelector('ewt-install-dialog')) return;   // never in the middle of a flash
    const before = state.status.firmware?.generated;
    await loadStatus();
    if (state.status.firmware?.generated && state.status.firmware.generated !== before) {
        await loadCatalog(); render(); toast('Ny firmware er klar');
    } else renderFirmware();
}, 5 * 60 * 1000);
if (state.status.mode === 'docker' && !state.status.setup_done) openWizard();
