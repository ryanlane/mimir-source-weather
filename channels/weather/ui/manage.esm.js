// Weather Manager Web Component for Mimir Platform
const CHANNEL_ID = 'com.mimir.weather';

// Layout families and their canonical preview dimensions
const LAYOUTS = [
  { id: 'auto',      label: 'Auto',      icon: '⟳', hint: 'Picks best layout based on display aspect ratio' },
  { id: 'landscape', label: 'Landscape', icon: '▬', hint: '800×480 — wide displays, side-by-side panels' },
  { id: 'portrait',  label: 'Portrait',  icon: '▮', hint: '480×800 — tall displays, stacked layout' },
  { id: 'square',    label: 'Square',    icon: '■', hint: '600×600 — square displays, two-column grid' },
];
const PREVIEW_SIZES = {
  landscape: [640, 384], portrait: [320, 533], square: [400, 400], auto: [640, 384],
};
// For "Auto" we show all three orientations side-by-side
const AUTO_PREVIEWS = [
  { layout: 'landscape', w: 480, h: 288, label: 'Landscape' },
  { layout: 'portrait',  w: 200, h: 333, label: 'Portrait' },
  { layout: 'square',    w: 260, h: 260, label: 'Square' },
];

const CSS = `
  :host {
    display: block;
    font-family: "Lato", system-ui, sans-serif;
    font-size: 14px;
    color: var(--color-text, #e0e0e0);
    background: transparent;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .manager { display: flex; flex-direction: column; gap: 16px; padding: 16px 0; }

  /* Setup banner */
  .setup-banner {
    background: #0a1e2c; border: 1px solid #1e4060;
    border-radius: 10px; padding: 20px;
    display: flex; flex-direction: column; gap: 14px;
  }
  .setup-title { font-size: 15px; font-weight: 700; }
  .setup-steps { display: flex; flex-direction: column; gap: 10px; }
  .step { display: flex; gap: 10px; align-items: flex-start; font-size: 13px; color: var(--color-text-secondary, #888); line-height: 1.5; }
  .step-num { flex-shrink: 0; width: 22px; height: 22px; border-radius: 50%; background: #1e4060; color: #60b3f8; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
  .step a { color: var(--color-accent, #00C851); text-decoration: none; }
  .step a:hover { text-decoration: underline; }
  .step code { background: var(--color-surface, #162325); border: 1px solid var(--color-border, #2a3a3c); border-radius: 3px; padding: 1px 5px; font-size: 12px; }
  .key-row { display: flex; gap: 8px; }
  .key-row input { flex: 1; background: var(--color-background, #0B1314); border: 1px solid var(--color-border, #2a3a3c); border-radius: 6px; padding: 9px 12px; font-family: monospace; font-size: 13px; color: var(--color-text, #e0e0e0); }
  .key-row input:focus { outline: 2px solid var(--color-accent, #00C851); border-color: transparent; }

  /* Section */
  .section { display: flex; flex-direction: column; gap: 8px; }
  .section-header { display: flex; align-items: center; justify-content: space-between; }
  .section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-text-secondary, #888); }

  /* Display cards (gallery list) */
  .display-list { display: flex; flex-direction: column; gap: 8px; }
  .display-card {
    background: var(--color-surface, #162325);
    border: 1px solid var(--color-border, #2a3a3c);
    border-radius: 8px; padding: 12px 14px;
    display: flex; gap: 14px; align-items: flex-start;
  }
  .display-thumb {
    flex-shrink: 0; width: 120px; height: 72px; border-radius: 4px;
    background: var(--color-background, #0B1314);
    border: 1px solid var(--color-border, #2a3a3c);
    overflow: hidden; display: flex; align-items: center; justify-content: center;
    font-size: 10px; color: var(--color-text-secondary, #888);
  }
  .display-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .display-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .display-name { font-weight: 600; font-size: 14px; }
  .display-meta { font-size: 12px; color: var(--color-text-secondary, #888); }
  .display-actions { display: flex; gap: 6px; flex-shrink: 0; margin-top: 2px; }
  .badge {
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  }
  .badge-layout { background: #0a2035; color: #60b3f8; border: 1px solid #1e4060; }
  .badge-theme-dark  { background: #1a1a1a; color: #aaa; border: 1px solid #333; }
  .badge-theme-light { background: #f5f5f5; color: #333; border: 1px solid #ccc; }

  /* Edit / Add panel */
  .edit-panel {
    background: var(--color-surface, #162325);
    border: 1px solid var(--color-border, #2a3a3c);
    border-radius: 8px; padding: 0; overflow: hidden;
  }
  .edit-panel-header {
    background: var(--color-background, #0B1314);
    padding: 12px 16px; font-weight: 600; font-size: 13px;
    border-bottom: 1px solid var(--color-border, #2a3a3c);
    display: flex; justify-content: space-between; align-items: center;
  }
  .edit-body { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
  .edit-form { padding: 16px; display: flex; flex-direction: column; gap: 12px; border-right: 1px solid var(--color-border, #2a3a3c); }
  .edit-preview-panel { padding: 16px; display: flex; flex-direction: column; gap: 10px; background: var(--color-background, #0B1314); }
  .preview-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-text-secondary, #888); }

  /* Preview images */
  .preview-single { width: 100%; border-radius: 4px; border: 1px solid var(--color-border, #2a3a3c); display: block; }
  .preview-auto { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
  .preview-auto-item { display: flex; flex-direction: column; gap: 4px; align-items: center; }
  .preview-auto-item img { border-radius: 4px; border: 1px solid var(--color-border, #2a3a3c); display: block; max-width: 100%; }
  .preview-auto-item span { font-size: 10px; color: var(--color-text-secondary, #888); }
  .preview-placeholder { padding: 40px 20px; text-align: center; color: var(--color-text-secondary, #888); font-size: 13px; border: 1px dashed var(--color-border, #2a3a3c); border-radius: 4px; }

  /* Form fields */
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-text-secondary, #888); }
  .field input, .field select {
    background: var(--color-background, #0B1314); border: 1px solid var(--color-border, #2a3a3c);
    border-radius: 6px; padding: 8px 10px; font-size: 13px; font-family: inherit;
    color: var(--color-text, #e0e0e0); width: 100%;
  }
  .field input:focus, .field select:focus { outline: 2px solid var(--color-accent, #00C851); border-color: transparent; }
  .field-hint { font-size: 11px; color: var(--color-text-tertiary, #666); }
  .field-row { display: flex; gap: 8px; }
  .field-row .field { flex: 1; }

  /* City search */
  .city-search-wrap { position: relative; }
  .city-dropdown {
    position: absolute; top: 100%; left: 0; right: 0; z-index: 10;
    background: var(--color-surface, #162325); border: 1px solid var(--color-border, #2a3a3c);
    border-radius: 0 0 6px 6px; max-height: 200px; overflow-y: auto;
  }
  .city-option {
    padding: 8px 12px; cursor: pointer; font-size: 13px;
    border-bottom: 1px solid var(--color-border, #2a3a3c);
    transition: background 0.1s;
  }
  .city-option:last-child { border-bottom: none; }
  .city-option:hover { background: var(--color-surface-hover, #1e2f31); }

  /* Toggles row */
  .toggles { display: flex; flex-wrap: wrap; gap: 8px; }
  .toggle-check { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
  .toggle-check input { width: 14px; height: 14px; accent-color: var(--color-accent, #00C851); }

  /* Edit footer */
  .edit-footer {
    padding: 12px 16px; border-top: 1px solid var(--color-border, #2a3a3c);
    display: flex; gap: 8px; justify-content: flex-end;
    background: var(--color-background, #0B1314);
  }

  /* Layout selector */
  .layout-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .layout-opt {
    border: 1px solid var(--color-border, #2a3a3c); border-radius: 6px;
    padding: 8px 6px; cursor: pointer; text-align: center;
    font-size: 11px; background: var(--color-background, #0B1314);
    transition: border-color 0.12s, background 0.12s;
  }
  .layout-opt.selected { border-color: var(--color-accent, #00C851); background: #0a2518; }
  .layout-opt .icon { font-size: 18px; display: block; margin-bottom: 4px; }
  .layout-opt .lname { font-weight: 600; }

  /* Empty state */
  .empty-state { padding: 24px; text-align: center; font-size: 13px; color: var(--color-text-secondary, #888); background: var(--color-surface, #162325); border: 1px dashed var(--color-border, #2a3a3c); border-radius: 8px; }

  /* Buttons */
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 6px; border: none; font-size: 13px; font-family: inherit; cursor: pointer; font-weight: 600; transition: background 0.15s, opacity 0.15s; white-space: nowrap; }
  .btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .btn-primary { background: var(--color-accent, #00C851); color: #000; }
  .btn-primary:hover:not(:disabled) { background: var(--color-accent-hover, #00d858); }
  .btn-secondary { background: var(--color-surface, #162325); color: var(--color-text, #e0e0e0); border: 1px solid var(--color-border, #2a3a3c); }
  .btn-secondary:hover:not(:disabled) { background: var(--color-surface-hover, #1e2f31); }
  .btn-danger { background: #c62828; color: #fff; }
  .btn-danger:hover:not(:disabled) { background: #d32f2f; }
  .btn-ghost { background: transparent; color: var(--color-text-secondary, #888); padding: 4px 8px; font-size: 12px; font-weight: 400; }
  .btn-ghost:hover:not(:disabled) { color: var(--color-text, #e0e0e0); }
  .btn-sm { padding: 4px 10px; font-size: 12px; }
  .btn-icon { padding: 5px 8px; }

  /* Status messages */
  .msg { padding: 8px 12px; border-radius: 6px; font-size: 13px; display: flex; align-items: center; gap: 6px; }
  .msg.success { background: #0a2918; border: 1px solid #1a5c38; color: #4ade80; }
  .msg.error   { background: #2a0a0a; border: 1px solid #6b1111; color: #f87171; }
  .msg.info    { background: var(--color-surface, #162325); border: 1px solid var(--color-border, #2a3a3c); color: var(--color-text-secondary, #888); }

  /* Key panel */
  .key-panel { background: var(--color-surface, #162325); border: 1px solid var(--color-border, #2a3a3c); border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; gap: 10px; }
  .key-masked { font-family: monospace; font-size: 13px; color: var(--color-text-secondary, #888); flex: 1; }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--color-border, #2a3a3c); border-top-color: var(--color-accent, #00C851); animation: spin 0.7s linear infinite; flex-shrink: 0; }

  @media (max-width: 600px) {
    .edit-body { grid-template-columns: 1fr; }
    .edit-form { border-right: none; border-bottom: 1px solid var(--color-border, #2a3a3c); }
    .preview-auto { flex-direction: column; align-items: flex-start; }
  }
`;

// ─── Blank form state ───────────────────────────────────────────────────────
function blankForm() {
  return {
    id: '', name: '', city_name: '', country: '', lat: '', lon: '',
    units: 'imperial', layout: 'auto', theme: 'dark',
    show_forecast: true, forecast_days: 3,
    show_humidity: true, show_wind: true,
    show_feels_like: true, show_high_low: true,
  };
}

class WeatherManager extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.state = {
      loading: true,
      setupRequired: false,
      displays: [],
      settings: null,
      apiKeyInput: '',
      validating: false,
      showChangeKey: false,
      editingId: null,     // null = closed, '' = new, 'uuid' = editing existing
      form: blankForm(),
      cityQuery: '',
      cityResults: [],
      citySearching: false,
      saving: false,
      previewUrls: {},     // layout -> data URL (for auto: {landscape:.., portrait:.., square:..})
      previewLoading: false,
      message: null,
    };
    this._cityDebounce = null;
    this._previewDebounce = null;
  }

  get channelId() { return this.getAttribute('channel-id') || CHANNEL_ID; }
  get apiBase() { return `/api/channels/${this.channelId}`; }

  async connectedCallback() {
    this.render();
    await this.loadStatus();
  }

  async loadStatus() {
    this.setState({ loading: true });
    try {
      const r = await fetch(`${this.apiBase}/status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      // Load full display configs to get thumbnails
      this.setState({
        loading: false,
        setupRequired: d.setup_required,
        displays: d.displays || [],
        settings: d.settings || {},
      });
    } catch (e) {
      this.setState({ loading: false, message: { type: 'error', text: `Load failed: ${e.message}` } });
    }
  }

  setState(updates) {
    Object.assign(this.state, updates);
    this.render();
  }

  // ── API key ──────────────────────────────────────────────────────────────
  async validateKey() {
    const key = this.state.apiKeyInput.trim();
    if (!key) { this.setState({ message: { type: 'error', text: 'Enter your API key first' } }); return; }
    this.setState({ validating: true, message: null });
    try {
      const r = await fetch(`${this.apiBase}/validate-key`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
      });
      const d = await r.json();
      if (d.valid) {
        this.setState({ validating: false, setupRequired: false, showChangeKey: false, apiKeyInput: '',
          message: { type: 'success', text: 'API key verified and saved ✓' } });
        await this.loadStatus();
      } else {
        this.setState({ validating: false, message: { type: 'error', text: d.error || 'Invalid key' } });
      }
    } catch (e) {
      this.setState({ validating: false, message: { type: 'error', text: e.message } });
    }
  }

  // ── Display CRUD ─────────────────────────────────────────────────────────
  openAdd() {
    this.setState({ editingId: '', form: blankForm(), cityQuery: '', cityResults: [],
      previewUrls: {}, message: null });
  }

  async openEdit(id) {
    try {
      const r = await fetch(`${this.apiBase}/subchannels/${id}`);
      const d = await r.json();
      this.setState({ editingId: id, form: { ...blankForm(), ...d },
        cityQuery: `${d.city_name}, ${d.country}`, cityResults: [],
        previewUrls: {}, message: null });
      this.schedulePreview();
    } catch (e) {
      this.setState({ message: { type: 'error', text: `Load failed: ${e.message}` } });
    }
  }

  closeEdit() {
    this.setState({ editingId: null, form: blankForm(), cityQuery: '', cityResults: [], previewUrls: {} });
  }

  async saveDisplay() {
    const { form, editingId } = this.state;
    if (!form.name) { this.setState({ message: { type: 'error', text: 'Display name is required' } }); return; }
    if (!form.lat || !form.lon) { this.setState({ message: { type: 'error', text: 'Select a city from the search results' } }); return; }

    this.setState({ saving: true, message: null });
    try {
      const url = editingId ? `${this.apiBase}/subchannels/${editingId}` : `${this.apiBase}/subchannels`;
      const method = editingId ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      this.setState({ saving: false });
      this.closeEdit();
      await this.loadStatus();
    } catch (e) {
      this.setState({ saving: false, message: { type: 'error', text: `Save failed: ${e.message}` } });
    }
  }

  async deleteDisplay(id) {
    if (!confirm('Remove this weather display?')) return;
    try {
      await fetch(`${this.apiBase}/subchannels/${id}`, { method: 'DELETE' });
      await this.loadStatus();
    } catch (e) {
      this.setState({ message: { type: 'error', text: `Delete failed: ${e.message}` } });
    }
  }

  // ── City search ──────────────────────────────────────────────────────────
  onCityInput(value) {
    this.state.cityQuery = value;
    this.state.form.city_name = '';
    this.state.form.lat = '';
    this.state.form.lon = '';
    clearTimeout(this._cityDebounce);
    // Clear dropdown without a full re-render — just update the DOM directly
    this._updateCityDropdown([]);
    if (value.length < 3) return;
    this._cityDebounce = setTimeout(() => this.searchCity(value), 500);
  }

  async searchCity(q) {
    // Don't setState here — that would destroy the input mid-typing.
    // Update only the dropdown node directly.
    try {
      const r = await fetch(`${this.apiBase}/search-city?q=${encodeURIComponent(q)}`);
      const results = await r.json();
      this.state.cityResults = results || [];
      this._updateCityDropdown(results || []);
    } catch (_) {
      this.state.cityResults = [];
      this._updateCityDropdown([]);
    }
  }

  _updateCityDropdown(results) {
    const root = this.shadowRoot;
    const wrap = root?.querySelector('.city-search-wrap');
    if (!wrap) return;

    let dropdown = wrap.querySelector('.city-dropdown');
    if (!results.length) {
      if (dropdown) dropdown.remove();
      return;
    }
    if (!dropdown) {
      dropdown = document.createElement('div');
      dropdown.className = 'city-dropdown';
      wrap.appendChild(dropdown);
    }
    dropdown.innerHTML = results.map((r, i) =>
      `<div class="city-option" data-index="${i}">${this._esc(r.display_name)}</div>`
    ).join('');
    dropdown.querySelectorAll('.city-option').forEach(el => {
      el.addEventListener('click', () => {
        const r = this.state.cityResults[parseInt(el.dataset.index, 10)];
        if (r) this.selectCity(r);
      });
    });
  }

  selectCity(result) {
    this.state.cityResults = [];
    const cityInput = this.shadowRoot?.querySelector('[data-city-input]');
    if (cityInput) cityInput.value = result.display_name;
    this._updateCityDropdown([]);
    const form = { ...this.state.form, city_name: result.name, country: result.country, lat: result.lat, lon: result.lon };
    this.state.form = form;
    this.state.cityQuery = result.display_name;
    // Update the coords hint without a full re-render
    const hint = this.shadowRoot?.querySelector('.city-coords-hint');
    if (hint) hint.textContent = `📍 ${result.lat.toFixed(4)}, ${result.lon.toFixed(4)}`;
    this.schedulePreview();
  }

  // ── Live preview ─────────────────────────────────────────────────────────
  schedulePreview() {
    clearTimeout(this._previewDebounce);
    this._previewDebounce = setTimeout(() => this.loadPreview(), 600);
  }

  async loadPreview() {
    const { form } = this.state;
    if (!form.lat || !form.lon) return;
    this.setState({ previewLoading: true });

    try {
      const baseConfig = { ...form };

      if (form.layout === 'auto') {
        // Fetch all three orientations in parallel
        const results = await Promise.all(
          AUTO_PREVIEWS.map(async (p) => {
            const cfg = { ...baseConfig, layout: p.layout };
            const r = await fetch(`${this.apiBase}/preview`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ config: cfg, w: p.w, h: p.h }),
            });
            if (!r.ok) return [p.layout, null];
            const blob = await r.blob();
            return [p.layout, URL.createObjectURL(blob)];
          })
        );
        const urls = Object.fromEntries(results.filter(([, u]) => u));
        this.setState({ previewUrls: urls, previewLoading: false });
      } else {
        const [pw, ph] = PREVIEW_SIZES[form.layout] || PREVIEW_SIZES.landscape;
        const r = await fetch(`${this.apiBase}/preview`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ config: { ...baseConfig }, w: pw, h: ph }),
        });
        if (!r.ok) { this.setState({ previewLoading: false }); return; }
        const blob = await r.blob();
        this.setState({ previewUrls: { [form.layout]: URL.createObjectURL(blob) }, previewLoading: false });
      }
    } catch (_) {
      this.setState({ previewLoading: false });
    }
  }

  // ── Render helpers ───────────────────────────────────────────────────────
  _esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  buildSetupBanner() {
    const { validating, apiKeyInput } = this.state;
    return `
      <div class="setup-banner">
        <div class="setup-title">☁ OpenWeatherMap API Key Required</div>
        <div class="setup-steps">
          <div class="step"><span class="step-num">1</span>
            <span>Create a free account at <a href="https://openweathermap.org/api" target="_blank">openweathermap.org/api</a> — just email and password, no credit card.</span>
          </div>
          <div class="step"><span class="step-num">2</span>
            <span>After signing up, go to <a href="https://home.openweathermap.org/api_keys" target="_blank">home.openweathermap.org/api_keys</a> to find your default API key. It is active within a few minutes of account creation.</span>
          </div>
          <div class="step"><span class="step-num">3</span>
            <span>The free tier allows <strong>1,000 API calls/day</strong>, which is more than enough. Mimir caches weather data (default 30 min), so a single display uses only ~48 calls/day.</span>
          </div>
          <div class="step"><span class="step-num">4</span>
            <span>Copy your key and paste it below. It looks like: <code>a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4</code></span>
          </div>
        </div>
        <div class="key-row">
          <input type="password" placeholder="Paste your OWM API key here…"
            value="${this._esc(apiKeyInput)}" data-field="apiKeyInput" autocomplete="off" />
          <button class="btn btn-primary" data-action="validate-key" ${validating ? 'disabled' : ''}>
            ${validating ? '<span class="spinner"></span> Verifying…' : 'Verify & Save'}
          </button>
        </div>
      </div>`;
  }

  buildKeyPanel() {
    const { settings, showChangeKey, validating, apiKeyInput } = this.state;
    if (showChangeKey) return `
      <div class="key-panel" style="flex-direction:column;align-items:stretch;gap:8px">
        <span class="section-title">Change API Key</span>
        <div class="key-row">
          <input type="password" placeholder="Paste new OWM API key…"
            value="${this._esc(apiKeyInput)}" data-field="apiKeyInput" autocomplete="off" />
          <button class="btn btn-primary btn-sm" data-action="validate-key" ${validating ? 'disabled' : ''}>
            ${validating ? '<span class="spinner"></span>' : 'Verify & Save'}
          </button>
          <button class="btn btn-ghost btn-sm" data-action="cancel-change-key">Cancel</button>
        </div>
      </div>`;
    return `
      <div class="key-panel">
        <span class="section-title">API Key</span>
        <span class="key-masked">${this._esc(settings?.api_key || '')}</span>
        <button class="btn btn-ghost btn-sm" data-action="show-change-key">Change</button>
      </div>`;
  }

  buildDisplayList() {
    const { displays } = this.state;
    if (!displays.length) return `<div class="empty-state">No weather displays yet. Click <strong>+ Add Display</strong> to create one.</div>`;
    return `<div class="display-list">${displays.map(d => `
      <div class="display-card">
        <div class="display-thumb" data-display-id="${d.id}">
          <img src="${this.apiBase}/subchannels/${d.id}/preview?w=240&h=144" alt="preview"
            onerror="this.style.display='none'"
            onload="this.style.display='block'" />
        </div>
        <div class="display-info">
          <div class="display-name">${this._esc(d.name)}</div>
          <div class="display-meta">${this._esc(d.city)}, ${this._esc(d.country)} · ${d.units === 'imperial' ? '°F' : '°C'}</div>
          <div style="margin-top:4px;display:flex;gap:4px;flex-wrap:wrap">
            <span class="badge badge-layout">${d.layout || 'auto'}</span>
            <span class="badge badge-theme-${d.theme || 'dark'}">${d.theme || 'dark'}</span>
          </div>
        </div>
        <div class="display-actions">
          <button class="btn btn-secondary btn-sm" data-action="edit-display" data-id="${d.id}">Edit</button>
          <button class="btn btn-danger btn-sm btn-icon" data-action="delete-display" data-id="${d.id}" title="Remove">✕</button>
        </div>
      </div>`).join('')}</div>`;
  }

  buildSettingsPanel() {
    const { settings } = this.state;
    const cm = settings?.cache_minutes ?? 30;
    return `
      <div class="section">
        <div class="section-header"><span class="section-title">Settings</span></div>
        <div class="key-panel" style="flex-wrap:wrap;gap:12px">
          <div class="field" style="flex:1;min-width:140px">
            <label>Weather Cache (minutes)</label>
            <input type="number" min="5" max="1440" value="${this._esc(cm)}" data-settings-field="cache_minutes" style="width:100px" />
          </div>
          <div style="display:flex;align-items:flex-end">
            <button class="btn btn-secondary btn-sm" data-action="save-settings">Save</button>
          </div>
        </div>
      </div>`;
  }

  async saveSettings() {
    const root = this.shadowRoot;
    const el = root.querySelector('[data-settings-field="cache_minutes"]');
    if (!el) return;
    const val = parseInt(el.value, 10);
    if (isNaN(val) || val < 5) { this.setState({ message: { type: 'error', text: 'Cache must be at least 5 minutes' } }); return; }
    try {
      const r = await fetch(`${this.apiBase}/settings`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cache_minutes: val }),
      });
      const d = await r.json();
      this.setState({ settings: d.settings || { ...this.state.settings, cache_minutes: val },
        message: { type: 'success', text: 'Settings saved' } });
    } catch (e) {
      this.setState({ message: { type: 'error', text: `Save failed: ${e.message}` } });
    }
  }

  buildEditPanel() {
    const { form, editingId, cityQuery, saving, previewUrls, previewLoading } = this.state;
    const isNew = editingId === '';
    const title = isNew ? 'Add Weather Display' : 'Edit Weather Display';

    // Layout selector
    const layoutGrid = LAYOUTS.map(l => `
      <div class="layout-opt ${form.layout === l.id ? 'selected' : ''}" data-action="set-layout" data-layout="${l.id}" title="${l.hint}">
        <span class="icon">${l.icon}</span>
        <span class="lname">${l.label}</span>
      </div>`).join('');

    // Preview panel content
    let previewContent;
    if (previewLoading) {
      previewContent = `<div class="preview-placeholder"><span class="spinner" style="margin:auto"></span></div>`;
    } else if (!form.lat) {
      previewContent = `<div class="preview-placeholder">Search for a city to see a live preview of your weather display.</div>`;
    } else if (form.layout === 'auto') {
      const autoItems = AUTO_PREVIEWS.map(p => {
        const url = previewUrls[p.layout];
        return url
          ? `<div class="preview-auto-item"><img src="${url}" width="${p.w}" height="${p.h}" alt="${p.label}" /><span>${p.label}</span></div>`
          : '';
      }).join('');
      previewContent = autoItems
        ? `<div class="preview-auto">${autoItems}</div>`
        : `<div class="preview-placeholder">Loading previews…</div>`;
    } else {
      const url = previewUrls[form.layout];
      previewContent = url
        ? `<img class="preview-single" src="${url}" alt="preview" />`
        : `<div class="preview-placeholder">Loading preview…</div>`;
    }

    return `
      <div class="edit-panel">
        <div class="edit-panel-header">
          <span>${title}</span>
          <button class="btn btn-ghost btn-sm" data-action="close-edit">✕ Close</button>
        </div>
        <div class="edit-body">
          <div class="edit-form">
            <div class="field">
              <label>Display Name</label>
              <input type="text" placeholder="Living Room, Office…" value="${this._esc(form.name)}" data-field="name" />
            </div>
            <div class="field">
              <label>City</label>
              <div class="city-search-wrap">
                <input type="text" placeholder="Type at least 3 characters…" value="${this._esc(cityQuery)}" data-city-input autocomplete="off" />
              </div>
              <span class="field-hint city-coords-hint">${form.lat ? `📍 ${this._esc(form.lat?.toFixed?.(4) || form.lat)}, ${this._esc(form.lon?.toFixed?.(4) || form.lon)}` : ''}</span>
            </div>
            <div class="field-row">
              <div class="field">
                <label>Units</label>
                <select data-field="units">
                  <option value="imperial" ${form.units === 'imperial' ? 'selected' : ''}>Imperial (°F, mph)</option>
                  <option value="metric"   ${form.units === 'metric'   ? 'selected' : ''}>Metric (°C, m/s)</option>
                </select>
              </div>
              <div class="field">
                <label>Theme</label>
                <select data-field="theme">
                  <option value="dark"  ${form.theme === 'dark'  ? 'selected' : ''}>Dark</option>
                  <option value="light" ${form.theme === 'light' ? 'selected' : ''}>Light</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label>Layout</label>
              <div class="layout-grid">${layoutGrid}</div>
            </div>
            <div class="field-row">
              <div class="field">
                <label>Forecast Days</label>
                <select data-field="forecast_days">
                  ${[1,2,3,4,5].map(n => `<option value="${n}" ${form.forecast_days == n ? 'selected' : ''}>${n} day${n > 1 ? 's' : ''}</option>`).join('')}
                </select>
              </div>
            </div>
            <div class="field">
              <label>Show</label>
              <div class="toggles">
                ${[
                  ['show_forecast',  'Forecast'],
                  ['show_humidity',  'Humidity'],
                  ['show_wind',      'Wind'],
                  ['show_feels_like','Feels Like'],
                  ['show_high_low',  'High / Low'],
                ].map(([key, label]) => `
                  <label class="toggle-check">
                    <input type="checkbox" data-field="${key}" ${form[key] ? 'checked' : ''} />
                    ${label}
                  </label>`).join('')}
              </div>
            </div>
          </div>
          <div class="edit-preview-panel">
            <span class="preview-label">${form.layout === 'auto' ? 'Auto layout previews' : 'Preview'}</span>
            ${previewContent}
          </div>
        </div>
        <div class="edit-footer">
          <button class="btn btn-secondary btn-sm" data-action="close-edit">Cancel</button>
          <button class="btn btn-primary btn-sm" data-action="save-display" ${saving ? 'disabled' : ''}>
            ${saving ? '<span class="spinner"></span> Saving…' : (isNew ? 'Add Display' : 'Save Changes')}
          </button>
        </div>
      </div>`;
  }

  render() {
    const { loading, setupRequired, editingId, message, showChangeKey } = this.state;
    const msgHtml = message ? `<div class="msg ${message.type}"><span>${message.type === 'success' ? '✓' : message.type === 'error' ? '✕' : '⟳'}</span>${this._esc(message.text)}</div>` : '';

    if (loading) {
      this.shadowRoot.innerHTML = `<style>${CSS}</style><div class="manager"><div class="msg info"><span class="spinner"></span> Loading…</div></div>`;
      return;
    }

    this.shadowRoot.innerHTML = `
      <style>${CSS}</style>
      <div class="manager">
        ${setupRequired ? this.buildSetupBanner() : `
          ${this.buildKeyPanel()}
          <div class="section">
            <div class="section-header">
              <span class="section-title">Weather Displays</span>
              <button class="btn btn-primary btn-sm" data-action="add-display">+ Add Display</button>
            </div>
            ${editingId === null ? this.buildDisplayList() : ''}
          </div>
          ${editingId === null ? this.buildSettingsPanel() : ''}
          ${editingId !== null ? this.buildEditPanel() : ''}
        `}
        ${msgHtml}
      </div>`;

    this._attachListeners();
  }

  _attachListeners() {
    const root = this.shadowRoot;

    root.querySelectorAll('[data-action]').forEach(el => {
      el.addEventListener('click', e => {
        e.stopPropagation();
        const a = el.dataset.action;
        if (a === 'validate-key')   this.validateKey();
        else if (a === 'show-change-key')   this.setState({ showChangeKey: true, apiKeyInput: '', message: null });
        else if (a === 'cancel-change-key') this.setState({ showChangeKey: false, message: null });
        else if (a === 'add-display')   this.openAdd();
        else if (a === 'edit-display')  this.openEdit(el.dataset.id);
        else if (a === 'delete-display') this.deleteDisplay(el.dataset.id);
        else if (a === 'close-edit')    this.closeEdit();
        else if (a === 'save-display')  this.saveDisplay();
        else if (a === 'save-settings') this.saveSettings();
        else if (a === 'set-layout') {
          this.state.form.layout = el.dataset.layout;
          this.setState({ previewUrls: {} });
          this.schedulePreview();
        }
      });
    });

    // City search input
    const cityInput = root.querySelector('[data-city-input]');
    if (cityInput) {
      cityInput.addEventListener('input', e => this.onCityInput(e.target.value));
    }

    // Generic field bindings
    root.querySelectorAll('[data-field]').forEach(el => {
      const field = el.dataset.field;
      const handler = () => {
        let val = el.type === 'checkbox' ? el.checked : el.value;
        if (el.tagName === 'SELECT' && (field === 'forecast_days')) val = parseInt(val, 10);
        if (['name','units','layout','theme'].includes(field)) {
          this.state.form[field] = val;
          if (['units','theme'].includes(field)) this.schedulePreview();
        } else if (field === 'apiKeyInput') {
          this.state.apiKeyInput = val;
        } else if (field in this.state.form) {
          this.state.form[field] = val;
          this.schedulePreview();
        }
        // Re-render for layout changes to update the layout grid highlight
        if (field === 'layout') this.render();
      };
      el.addEventListener(el.type === 'checkbox' ? 'change' : 'input', handler);
      if (el.tagName === 'SELECT') el.addEventListener('change', handler);
    });
  }
}

customElements.define('x-weather-manager', WeatherManager);
export default WeatherManager;
