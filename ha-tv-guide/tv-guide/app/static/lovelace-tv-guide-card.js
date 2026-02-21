class TvGuideCard extends HTMLElement {
  set hass(hass) { this._hass = hass; }

  setConfig(config) {
    this._config = config;
    this._addonUrl = config.addon_url || '/api/hassio_ingress/tv_guide';
    this._state = { sonos: {}, firetv: {}, shows: [], loading: true };
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
      this._render();
      this._poll();
    }
  }

  async _api(path, opts = {}) {
    const base = this._addonUrl.replace(/\/$/, '');
    const r = await fetch(base + path, opts);
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
  }
  async _post(path, body) {
    return this._api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }

  async _poll() {
    try {
      const [sonos, data, shows] = await Promise.all([
        this._api('/api/sonos/state'),
        this._api('/api/data'),
        this._api('/api/shows'),
      ]);
      this._state.sonos = sonos;
      this._state.data = data;
      // In-progress shows: have a watched episode but not all watched
      this._state.shows = shows.filter(s => {
        const w = (data.watched[String(s.id)] || []).length;
        return w > 0 && w < s.episodeCount;
      }).slice(0, 5);
      this._state.allShows = shows;
      this._state.status = await this._api('/api/status');
      this._state.loading = false;
    } catch (e) {
      this._state.error = e.message;
      this._state.loading = false;
    }
    this._render();
    setTimeout(() => this._poll(), 30000);
  }

  async _ftv(cmd) {
    try { await this._post('/api/firetv/command', { command: cmd }); }
    catch (e) { console.error('Fire TV error', e); }
  }

  async _sonos(cmd, extra = {}) {
    try {
      await this._post('/api/sonos/command', { command: cmd, ...extra });
      setTimeout(() => this._refreshSonos(), 800);
    } catch (e) { console.error('Sonos error', e); }
  }

  async _refreshSonos() {
    try {
      this._state.sonos = await this._api('/api/sonos/state');
      this._render();
    } catch (e) {}
  }

  async _launch(svc, profileIndex = 0) {
    try { await this._post('/api/firetv/launch', { service: svc, profileIndex }); }
    catch (e) { console.error('Launch error', e); }
  }

  _showProfilePicker(svc) {
    const profiles = (this._state.status?.profiles || {})[svc] || [];
    if (!profiles.length) { this._launch(svc, 0); return; }
    this._pickState = { svc, profiles };
    this._render();
  }

  _render() {
    const s = this._state;
    const { sonos = {}, shows = [], loading, error, pickState } = s;
    this._pickState = this._pickState || null;
    const vol = Math.round((sonos.volume || 0) * 100);

    const SVCS = {
      netflix:'Netflix',hulu:'Hulu',disney:'Disney+',max:'Max',
      peacock:'Peacock',discovery:'Discovery+',tubi:'Tubi',prime:'Prime',
      pluto:'Pluto TV',plex:'Plex',youtube:'YouTube',paramount:'Paramount+',
    };

    const styles = `
      :host { display: block; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
      .card { background: var(--card-background-color, #1a1a35); border-radius: 16px; overflow: hidden; color: var(--primary-text-color, #e8e8f0); }
      .section { padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,.08); }
      .section:last-child { border-bottom: none; }
      .label { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--secondary-text-color, #7070a0); margin-bottom: 10px; font-weight: 700; }
      /* Fire TV */
      .ftv-grid { display: grid; grid-template-columns: repeat(5,1fr); gap: 6px; margin-bottom: 8px; }
      .ftv-row { display: grid; grid-template-columns: repeat(3,1fr); gap: 6px; }
      .fb { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.1); border-radius: 10px; padding: 8px 4px; cursor: pointer; text-align: center; font-size: 16px; transition: background .15s; color: inherit; }
      .fb:hover { background: rgba(255,255,255,.15); }
      .fb.wide { grid-column: span 2; }
      .dpad { display: grid; grid-template-columns: repeat(3,1fr); gap: 4px; width: 110px; margin: 0 auto; }
      .dpad .fb { padding: 10px 4px; }
      /* Sonos */
      .sonos-row { display: flex; align-items: center; gap: 10px; }
      .vol-label { font-size: 20px; font-weight: 800; min-width: 42px; }
      .vol-bar { flex: 1; height: 6px; background: rgba(255,255,255,.1); border-radius: 3px; overflow: hidden; }
      .vol-fill { height: 100%; background: linear-gradient(90deg,#7b2fff,#e5173f); border-radius: 3px; transition: width .3s; }
      .sb { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.1); border-radius: 10px; padding: 7px 10px; cursor: pointer; font-size: 13px; font-weight: 600; color: inherit; white-space: nowrap; transition: all .15s; }
      .sb:hover { background: rgba(255,255,255,.15); }
      .sb.on { background: rgba(229,23,63,.25); border-color: rgba(229,23,63,.5); color: #ff6b85; }
      .toggle-row { display: flex; gap: 8px; margin-top: 10px; }
      /* Shows */
      .show-item { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,.05); }
      .show-item:last-child { border-bottom: none; }
      .show-poster { width: 32px; height: 48px; object-fit: cover; border-radius: 6px; background: rgba(255,255,255,.05); }
      .show-info { flex: 1; min-width: 0; }
      .show-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .show-sub { font-size: 11px; color: var(--secondary-text-color, #7070a0); margin-top: 2px; }
      .launch-btn { background: rgba(229,23,63,.15); border: 1px solid rgba(229,23,63,.3); border-radius: 8px; padding: 5px 10px; color: #ff6b85; font-size: 12px; cursor: pointer; font-weight: 700; white-space: nowrap; }
      .launch-btn:hover { background: rgba(229,23,63,.35); }
      /* Profile picker */
      .picker-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.75); z-index: 9999; display: flex; align-items: center; justify-content: center; }
      .picker-box { background: #1a1a35; border: 1px solid rgba(255,255,255,.1); border-radius: 20px; padding: 28px; min-width: 300px; text-align: center; }
      .picker-title { font-size: 11px; color: #7070a0; text-transform: uppercase; margin-bottom: 4px; }
      .picker-app { font-size: 20px; font-weight: 800; margin-bottom: 18px; }
      .picker-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px,1fr)); gap: 8px; margin-bottom: 14px; }
      .picker-btn { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12); border-radius: 12px; padding: 14px 8px; cursor: pointer; color: #e8e8f0; font-size: 14px; font-weight: 700; transition: all .15s; }
      .picker-btn:hover { background: rgba(229,23,63,.25); border-color: rgba(229,23,63,.5); }
      .picker-cancel { background: none; border: none; color: #7070a0; font-size: 13px; cursor: pointer; }
    `;

    const pickerHtml = this._pickState ? `
      <div class="picker-overlay">
        <div class="picker-box">
          <div class="picker-title">Who's watching?</div>
          <div class="picker-app">${SVCS[this._pickState.svc] || this._pickState.svc}</div>
          <div class="picker-grid">
            ${this._pickState.profiles.map((p, i) => `<button class="picker-btn" data-pick="${i}">${p}</button>`).join('')}
          </div>
          <button class="picker-cancel" data-cancel="1">Cancel</button>
        </div>
      </div>` : '';

    const showsHtml = shows.length ? shows.map(sh => {
      const svc = (s.data?.services || {})[String(sh.id)];
      const watched = (s.data?.watched?.[String(sh.id)] || []).length;
      const pct = sh.episodeCount ? Math.round(watched / sh.episodeCount * 100) : 0;
      return `<div class="show-item">
        <img class="show-poster" src="${sh.poster}" onerror="this.style.visibility='hidden'">
        <div class="show-info">
          <div class="show-title">${sh.title}</div>
          <div class="show-sub">${svc ? SVCS[svc] || svc : 'No service'} · ${pct}% watched</div>
        </div>
        ${svc ? `<button class="launch-btn" data-launch="${svc}" data-showid="${sh.id}">🔥</button>` : ''}
      </div>`;
    }).join('') : '<div style="color:#7070a0;font-size:13px;padding:8px 0">No in-progress shows</div>';

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="card">
        <!-- Fire TV -->
        <div class="section">
          <div class="label">🔥 Fire TV</div>
          <div style="display:flex;gap:10px;align-items:flex-start">
            <div>
              <div class="dpad">
                <div></div><button class="fb" data-ftv="up">▲</button><div></div>
                <button class="fb" data-ftv="left">◀</button>
                <button class="fb" data-ftv="select">⬤</button>
                <button class="fb" data-ftv="right">▶</button>
                <div></div><button class="fb" data-ftv="down">▼</button><div></div>
              </div>
            </div>
            <div style="flex:1">
              <div class="ftv-grid">
                <button class="fb" data-ftv="play_pause">⏯</button>
                <button class="fb" data-ftv="rewind">⏪</button>
                <button class="fb" data-ftv="forward">⏩</button>
                <button class="fb" data-ftv="back">↩</button>
                <button class="fb" data-ftv="home">⌂</button>
              </div>
              <div class="ftv-row">
                <button class="fb" data-ftv="vol_down">🔉</button>
                <button class="fb" data-ftv="vol_up">🔊</button>
                <button class="fb" data-ftv="mute">🔇</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Sonos -->
        <div class="section">
          <div class="label">🔊 Sonos — Living Room</div>
          <div class="sonos-row">
            <button class="sb" data-sonos="volume_down" data-vol="${sonos.volume || 0}">−</button>
            <div class="vol-bar"><div class="vol-fill" style="width:${vol}%"></div></div>
            <div class="vol-label">${vol}%</div>
            <button class="sb" data-sonos="volume_up" data-vol="${sonos.volume || 0}">+</button>
            <button class="sb${sonos.muted ? ' on' : ''}" data-sonos="mute" data-muted="${sonos.muted}">🔇</button>
          </div>
          <div class="toggle-row">
            <button class="sb${sonos.speech_enhancement ? ' on' : ''}" data-sonos="speech_enhancement" data-state="${sonos.speech_enhancement}">🗣 Speech</button>
            <button class="sb${sonos.night_mode ? ' on' : ''}" data-sonos="night_mode" data-state="${sonos.night_mode}">🌙 Night</button>
          </div>
        </div>

        <!-- In-progress shows -->
        <div class="section">
          <div class="label">▶ In Progress</div>
          ${showsHtml}
        </div>
      </div>
      ${pickerHtml}
    `;

    // Fire TV button events
    this.shadowRoot.querySelectorAll('[data-ftv]').forEach(btn => {
      btn.addEventListener('click', () => this._ftv(btn.dataset.ftv));
    });

    // Sonos button events
    this.shadowRoot.querySelectorAll('[data-sonos]').forEach(btn => {
      btn.addEventListener('click', () => {
        const cmd = btn.dataset.sonos;
        const vol = parseFloat(btn.dataset.vol || 0);
        const muted = btn.dataset.muted === 'true';
        const state = btn.dataset.state === 'true';
        this._sonos(cmd, { current: vol, muted, state });
      });
    });

    // Launch buttons
    this.shadowRoot.querySelectorAll('[data-launch]').forEach(btn => {
      btn.addEventListener('click', () => {
        const svc = btn.dataset.launch;
        const profiles = (this._state.status?.profiles || {})[svc] || [];
        if (profiles.length > 1) {
          this._pickState = { svc, profiles };
          this._render();
        } else {
          this._launch(svc, 0);
        }
      });
    });

    // Profile picker buttons
    this.shadowRoot.querySelectorAll('[data-pick]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.pick);
        const svc = this._pickState?.svc;
        this._pickState = null;
        this._render();
        if (svc) this._launch(svc, idx);
      });
    });
    const cancelBtn = this.shadowRoot.querySelector('[data-cancel]');
    if (cancelBtn) cancelBtn.addEventListener('click', () => {
      this._pickState = null; this._render();
    });
  }

  getCardSize() { return 5; }
  static getStubConfig() {
    return { addon_url: '/api/hassio_ingress/tv_guide' };
  }
}

customElements.define('tv-guide-card', TvGuideCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'tv-guide-card',
  name: 'TV Guide Card',
  description: 'Fire TV remote, Sonos controls, and in-progress shows'
});
