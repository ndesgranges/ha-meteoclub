/**
 * MeteoClub Weather Dashboard Panel
 *
 * A custom Home Assistant panel that displays weather model accuracy comparison.
 */

const PANEL_NAME = "meteoclub-panel";

const COLORS = {
  observation: "#4CAF50",
  gfs: "#2196F3",
  wrf: "#FF9800",
  arome: "#9C27B0",
  arpege: "#F44336",
  icon_eu: "#00BCD4",
};

const STORAGE_KEY = "meteoclub_dashboard_prefs";

class MeteoClubPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._config = null;
    this._cities = [];
    this._chartData = null;
    this._loading = false;
    this._allModels = [];
    this._componentsLoaded = false;
    this._translations = {};  // Loaded via HTTP

    // Incremental loading state
    this._observations = null;
    this._forecasts = {};
    this._metric = null;
    this._modelLoadingState = {};  // { modelId: 'loading' | 'loaded' | 'error' }
    this._loadGeneration = 0;  // Increments on each load to ignore stale responses
    this._seriesVisibility = {};  // { seriesId: true/false } for toggling curves

    const saved = this._loadPreferences();
    this._selectedCity = saved.city || null;
    this._selectedMetric = saved.metric || "temperature";
    this._selectedHorizon = saved.horizon || 3;

    const now = new Date();
    this._endDate = saved.endDate ? new Date(saved.endDate) : now;
    this._startDate = saved.startDate ? new Date(saved.startDate) : new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  }

  _loadPreferences() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : {};
    } catch (e) {
      return {};
    }
  }

  _savePreferences() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        city: this._selectedCity,
        metric: this._selectedMetric,
        horizon: this._selectedHorizon,
        startDate: this._startDate.toISOString(),
        endDate: this._endDate.toISOString(),
      }));
    } catch (e) {
      // Ignore storage errors
    }
  }

  // Translation helper
  _t(key, replacements = {}) {
    let text = this._translations[key] || key;

    // Replace placeholders like {horizon}
    for (const [k, v] of Object.entries(replacements)) {
      text = text.replace(`{${k}}`, v);
    }
    return text;
  }

  // Translate metric name
  _translateMetric(metricId, fallback) {
    return this._translations.metrics?.[metricId] || fallback || metricId;
  }

  // Load translations from server
  async _loadTranslations() {
    const lang = this._hass?.language || "en";
    try {
      let response = await fetch(`/meteoclub/translations/${lang}.json`);
      if (!response.ok && lang !== "en") {
        response = await fetch("/meteoclub/translations/en.json");
      }
      if (response.ok) {
        const data = await response.json();
        this._translations = data.panel || {};
      }
    } catch (e) {
      console.warn("MeteoClub: Could not load translations", e);
    }
  }

  set hass(hass) {
    this._hass = hass;

    // Update hass on child HA components that need it
    const dateRangePicker = this.shadowRoot?.querySelector("ha-date-range-picker");
    if (dateRangePicker) {
      dateRangePicker.hass = hass;
    }

    if (!this._config) {
      this._loadConfig();
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    // Update ha-top-app-bar-fixed narrow property if rendered
    const topAppBar = this.shadowRoot?.querySelector("ha-top-app-bar-fixed");
    if (topAppBar) {
      topAppBar.narrow = narrow;
    }
  }

  async _loadConfig() {
    try {
      // Get dashboard configuration
      const configResult = await this._hass.callWS({ type: "meteoclub/config" });
      this._config = configResult;

      // Get cities
      const citiesResult = await this._hass.callWS({ type: "meteoclub/cities" });
      this._cities = citiesResult.cities || [];

      // Set default city if not set or invalid
      if (this._cities.length > 0) {
        const cityIds = this._cities.map(c => c.id);
        if (!this._selectedCity || !cityIds.includes(this._selectedCity)) {
          this._selectedCity = this._cities[0].id;
        }
      }

      // Validate metric
      if (this._config.metrics && this._config.metrics.length > 0) {
        const metricIds = this._config.metrics.map(m => m.id);
        if (!metricIds.includes(this._selectedMetric)) {
          this._selectedMetric = this._config.metrics[0].id;
        }
      }

      // Validate horizon
      if (this._config.horizons && this._config.horizons.length > 0) {
        if (!this._config.horizons.includes(this._selectedHorizon)) {
          this._selectedHorizon = this._config.horizons[0];
        }
      }

      // Get all model IDs (we'll fetch all and let the chart legend handle visibility)
      if (this._config.models && this._config.models.length > 0) {
        this._allModels = this._config.models.map(m => m.id);
      }

      this._savePreferences();

      // Wait for HA components and translations before rendering
      await this._ensureComponentsLoaded();
      await this._loadTranslations();
      this._render();

      // Load initial chart data
      if (this._selectedCity) {
        this._loadChartData();
      }
    } catch (err) {
      console.error("Failed to load MeteoClub config:", err);
      this._renderError(this._t('error_config'));
    }
  }

  async _ensureComponentsLoaded() {
    // Guard against multiple calls
    if (this._componentsLoaded) return;

    const componentsNeeded = ["ha-top-app-bar-fixed", "ha-date-range-picker"];

    // Check if already available
    if (componentsNeeded.every(name => customElements.get(name))) {
      this._componentsLoaded = true;
      return;
    }

    // Access partial-panel-resolver and trigger history panel import
    // This loads the components we need (ha-top-app-bar-fixed, ha-date-range-picker)
    try {
      const homeAssistant = document.querySelector("home-assistant");
      const haMain = homeAssistant?.shadowRoot?.querySelector("home-assistant-main");
      const partialResolver = haMain?.shadowRoot?.querySelector("partial-panel-resolver");

      if (partialResolver?.routerOptions?.routes?.history?.load) {
        await partialResolver.routerOptions.routes.history.load();
      }
    } catch (e) {
      console.warn("MeteoClub: Could not load history panel:", e);
    }

    // Wait for components to be defined (with timeout)
    const timeout = 5000;
    const startTime = Date.now();

    while (!componentsNeeded.every(name => customElements.get(name)) && Date.now() - startTime < timeout) {
      await new Promise(r => setTimeout(r, 100));
    }

    this._componentsLoaded = true;

    // Log only if components failed to load
    for (const name of componentsNeeded) {
      if (!customElements.get(name)) {
        console.error(`MeteoClub: Component ${name} not available`);
      }
    }
  }

  async _loadChartData() {
    if (!this._selectedCity || !this._hass) return;

    // Increment generation to invalidate any in-flight requests
    const currentGeneration = ++this._loadGeneration;

    // Reset state for new load
    this._loading = true;
    this._observations = null;
    this._forecasts = {};
    this._metric = null;
    this._modelLoadingState = {};

    // Initialize all models as 'loading'
    for (const model of this._allModels) {
      this._modelLoadingState[model] = 'loading';
    }

    this._renderLoadingState();
    this._updateModelStatusUI();

    // Step 1: Load observations first (with empty models array)
    try {
      const obsResult = await this._hass.callWS({
        type: "meteoclub/chart_data",
        city_id: this._selectedCity,
        metric: this._selectedMetric,
        horizon_days: this._selectedHorizon,
        models: [],  // No models - just observations
        start_date: this._startDate.toISOString(),
        end_date: this._endDate.toISOString(),
      });

      // Ignore if a newer load has started
      if (currentGeneration !== this._loadGeneration) return;

      this._observations = obsResult.observations || [];
      this._metric = obsResult.metric;

      // Render chart with just observations
      if (this._observations.length > 0) {
        this._renderChart();
        this._updateModelStatusUI();
      }
    } catch (err) {
      console.error("Failed to load observations:", err);
      if (currentGeneration !== this._loadGeneration) return;
      this._loading = false;
      this._render();
      return;
    }

    // Step 2: Load each model in parallel
    const modelPromises = this._allModels.map(async (modelId) => {
      try {
        const result = await this._hass.callWS({
          type: "meteoclub/chart_data",
          city_id: this._selectedCity,
          metric: this._selectedMetric,
          horizon_days: this._selectedHorizon,
          models: [modelId],  // Single model
          start_date: this._startDate.toISOString(),
          end_date: this._endDate.toISOString(),
        });

        // Ignore if a newer load has started
        if (currentGeneration !== this._loadGeneration) return;

        // Store forecast data for this model
        this._forecasts[modelId] = result.forecasts?.[modelId] || [];
        this._modelLoadingState[modelId] = 'loaded';

        // Update UI immediately when this model completes
        this._updateModelStatusUI();
        this._renderChart();
      } catch (err) {
        console.error(`Failed to load forecast for ${modelId}:`, err);
        if (currentGeneration !== this._loadGeneration) return;
        this._modelLoadingState[modelId] = 'error';
        this._updateModelStatusUI();
      }
    });

    // Wait for all models to complete
    await Promise.all(modelPromises);

    if (currentGeneration !== this._loadGeneration) return;
    this._loading = false;
    this._updateModelStatusUI();
  }

  _renderLoadingState() {
    const chartEl = this.shadowRoot.getElementById("chart");
    if (chartEl) {
      chartEl.innerHTML = `
        <div class="loading-overlay">
          <ha-circular-progress indeterminate></ha-circular-progress>
          <span class="loading-text">${this._t('loading_observations')}</span>
        </div>
      `;
    }
  }

  _updateModelStatusUI() {
    const statusContainer = this.shadowRoot.getElementById("model-status");
    if (!statusContainer || !this._config?.models) return;

    const html = this._config.models.map(model => {
      const state = this._modelLoadingState[model.id] || 'pending';
      const color = COLORS[model.id] || '#888';
      const seriesId = `forecast-${model.id}`;
      const isVisible = this._seriesVisibility[seriesId] !== false;
      const isLoading = state === 'loading' || state === 'pending';

      return `
        <div class="legend-item ${isVisible ? '' : 'disabled'} ${isLoading ? 'loading' : ''}" data-series="${seriesId}">
          <span class="legend-indicator" style="--color: ${color}">
            ${isLoading ? '' : ''}
          </span>
          <span class="legend-label">${model.name}</span>
        </div>
      `;
    }).join('');

    // Add observation at the start
    const obsLoading = !this._observations;
    const obsVisible = this._seriesVisibility['observation'] !== false;

    statusContainer.innerHTML = `
      <div class="legend-item ${obsVisible ? '' : 'disabled'} ${obsLoading ? 'loading' : ''}" data-series="observation">
        <span class="legend-indicator" style="--color: ${COLORS.observation}"></span>
        <span class="legend-label">${this._t('observations')}</span>
      </div>
      ${html}
    `;

    // Add click listeners for toggling
    statusContainer.querySelectorAll('.legend-item').forEach(item => {
      item.addEventListener('click', () => this._toggleSeries(item.dataset.series));
    });
  }

  _toggleSeries(seriesId) {
    // Toggle visibility
    this._seriesVisibility[seriesId] = this._seriesVisibility[seriesId] === false ? true : false;

    // Re-render chart and legend
    this._updateModelStatusUI();
    this._renderChart();
  }

  _render() {
    if (!this._config) {
      this.shadowRoot.innerHTML = `
        <style>${this._getStyles()}</style>
        <div class="loading"><ha-circular-progress indeterminate></ha-circular-progress></div>
      `;
      return;
    }

    // Note: ha-date-range-picker is added programmatically to ensure hass is set BEFORE
    // the element is added to DOM. This prevents "this.hass is undefined" errors in Lit's willUpdate.
    // Content goes INSIDE ha-top-app-bar-fixed (in default slot)
    const horizonText = this._selectedHorizon === 0 ? this._t('latest') : `${this._selectedHorizon} ${this._selectedHorizon > 1 ? this._t('days') : this._t('day')}`;

    this.shadowRoot.innerHTML = `
      <style>${this._getStyles()}</style>
      <ha-top-app-bar-fixed>
        <span slot="title">${this._t('title')}</span>

        <div class="content">
          <ha-card>
            <div class="card-content controls">
              <div class="control-group date-range-group">
                <label>${this._t('date_range')}</label>
                <div id="date-range-picker-container"></div>
              </div>

              <div class="control-group">
                <label>${this._t('city')}</label>
                <select id="city-select" class="native-select">
                  ${this._cities.map(c => `<option value="${c.id}" ${c.id === this._selectedCity ? "selected" : ""}>${c.name}</option>`).join("")}
                </select>
              </div>

              <div class="control-group">
                <label>${this._t('metric')}</label>
                <select id="metric-select" class="native-select">
                  ${this._config.metrics.map(m => `<option value="${m.id}" ${m.id === this._selectedMetric ? "selected" : ""}>${this._translateMetric(m.id, m.name)}</option>`).join("")}
                </select>
              </div>

              <div class="control-group">
                <label>${this._t('forecast_horizon')}</label>
                <select id="horizon-select" class="native-select">
                  ${this._config.horizons.map(h => `<option value="${h}" ${h === this._selectedHorizon ? "selected" : ""}>${h === 0 ? this._t('latest') : `${h} ${h > 1 ? this._t('days') : this._t('day')}`}</option>`).join("")}
                </select>
              </div>

              ${this._loading ? '<ha-circular-progress indeterminate size="small"></ha-circular-progress>' : ''}
            </div>
          </ha-card>

          <ha-card>
            <div class="card-content chart-card-content">
              <div class="chart-container" id="chart">
                <div class="chart-placeholder">${this._t('select_city')}</div>
              </div>
              <div class="legend-panel" id="model-status">
                <!-- Legend items will be injected here -->
              </div>
            </div>
          </ha-card>

          <ha-card class="info-card">
            <div class="card-content">
              <p>
                <ha-icon icon="mdi:information-outline"></ha-icon>
                ${this._selectedHorizon === 0 ? this._t('info_text_latest') : this._t('info_text', { horizon: `<strong>${horizonText}</strong>` })}
              </p>
            </div>
          </ha-card>
        </div>
      </ha-top-app-bar-fixed>
    `;

    this._setupEventListeners();
  }

  _setupEventListeners() {
    // Set narrow on ha-top-app-bar-fixed
    const topAppBar = this.shadowRoot.querySelector("ha-top-app-bar-fixed");
    if (topAppBar) {
      topAppBar.narrow = this._narrow;
    }

    // Create ha-date-range-picker PROGRAMMATICALLY to set hass BEFORE adding to DOM
    // This prevents "this.hass is undefined" errors in Lit's willUpdate lifecycle
    const container = this.shadowRoot.getElementById("date-range-picker-container");
    if (container && customElements.get("ha-date-range-picker")) {
      // Only create if not already present
      if (!container.querySelector("ha-date-range-picker")) {
        const dateRangePicker = document.createElement("ha-date-range-picker");
        dateRangePicker.hass = this._hass;  // Set hass FIRST - critical!
        dateRangePicker.id = "date-range-picker";
        dateRangePicker.startDate = this._startDate;
        dateRangePicker.endDate = this._endDate;
        dateRangePicker.setAttribute("extended-presets", "");

        dateRangePicker.addEventListener("value-changed", (e) => {
          const { startDate, endDate } = e.detail.value;
          if (startDate && endDate) {
            this._startDate = startDate;
            this._endDate = endDate;
            this._savePreferences();
            this._loadChartData();
          }
        });

        container.appendChild(dateRangePicker);
      }
    }

    // City select
    const citySelect = this.shadowRoot.getElementById("city-select");
    if (citySelect) {
      citySelect.addEventListener("change", (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val !== this._selectedCity) {
          this._selectedCity = val;
          this._savePreferences();
          this._loadChartData();
        }
      });
    }

    // Metric select
    const metricSelect = this.shadowRoot.getElementById("metric-select");
    if (metricSelect) {
      metricSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        if (val && val !== this._selectedMetric) {
          this._selectedMetric = val;
          this._savePreferences();
          this._loadChartData();
        }
      });
    }

    // Horizon select
    const horizonSelect = this.shadowRoot.getElementById("horizon-select");
    if (horizonSelect) {
      horizonSelect.addEventListener("change", (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val !== this._selectedHorizon) {
          this._selectedHorizon = val;
          this._savePreferences();
          this._loadChartData();
        }
      });
    }

    // Initialize model status panel with pending state
    this._initializeModelStatusUI();
  }

  _initializeModelStatusUI() {
    const statusContainer = this.shadowRoot.getElementById("model-status");
    if (!statusContainer || !this._config?.models) return;

    // Initialize visibility - all visible by default
    this._seriesVisibility['observation'] = true;
    this._config.models.forEach(model => {
      this._seriesVisibility[`forecast-${model.id}`] = true;
    });

    this._updateModelStatusUI();
  }

  _renderChart() {
    const chartContainer = this.shadowRoot.getElementById("chart");
    if (!chartContainer || !this._observations) return;

    if (this._observations.length === 0) {
      chartContainer.innerHTML = `<div class="chart-placeholder">${this._t('no_data')}</div>`;
      return;
    }

    // Prepare series data for ha-chart-base (ECharts format)
    const seriesData = [];
    const legendData = [];

    // Observation series (solid line) - only if visible
    const obsId = "observation";
    const obsVisible = this._seriesVisibility[obsId] !== false;
    if (obsVisible) {
      seriesData.push({
        id: obsId,
        name: this._t('observation'),
        type: "line",
        data: this._observations.map((o) => [new Date(o.time).getTime(), o.value]),
        smooth: true,
        symbol: "circle",
        symbolSize: 4,
        lineStyle: { width: 2 },
        color: COLORS.observation,
        emphasis: { focus: "series" },
      });
    }
    legendData.push({ id: obsId, name: this._t('observation') });

    // Forecast series (dashed lines) - only add if visible and loaded
    for (const modelConfig of this._config.models) {
      const model = modelConfig.id;
      const modelName = modelConfig.name;
      const data = this._forecasts[model];
      const color = COLORS[model] || "#888";
      const seriesId = `forecast-${model}`;
      const isVisible = this._seriesVisibility[seriesId] !== false;

      // Only add series if visible and data has been loaded
      if (isVisible && data && data.length > 0) {
        seriesData.push({
          id: seriesId,
          name: modelName,
          type: "line",
          data: data.map((f) => [new Date(f.time).getTime(), f.value]),
          smooth: true,
          symbol: "none",
          lineStyle: { width: 2, type: "dashed" },
          color: color,
          emphasis: { focus: "series" },
        });
      }
      legendData.push({ id: seriesId, name: modelName });
    }

    // Chart options
    const isMobile = window.innerWidth <= 600;
    const chartHeight = isMobile ? Math.max(350, Math.floor(window.innerHeight * 0.55)) : 400;

    const chartOptions = {
      animation: true,
      animationDuration: 1000,
      animationEasing: "cubicOut",
      animationDelay: (idx) => idx * 10,
      grid: {
        top: "5%",
        right: "3%",
        bottom: "12%",
        left: "12%",
        containLabel: false,
      },
      xAxis: {
        type: "time",
        min: new Date(this._observations[0].time),
        max: new Date(this._observations[this._observations.length - 1].time),
      },
      yAxis: {
        type: "value",
        name: this._metric ? `${this._translateMetric(this._metric.id, this._metric.name)} (${this._metric.unit})` : '',
        nameLocation: "middle",
        nameGap: isMobile ? 30 : 50,
        scale: true,  // Auto-scale based on data, don't force include 0
      },
      legend: {
        show: false,  // We use our own legend
      },
      tooltip: {
        trigger: "axis",
      },
    };

    // Clear container and set explicit height
    chartContainer.innerHTML = "";
    chartContainer.style.height = `${chartHeight}px`;

    const chartEl = document.createElement("ha-chart-base");
    chartEl.hass = this._hass;
    chartEl.data = seriesData;
    chartEl.options = chartOptions;

    // Set height as property and style - ha-chart-base needs explicit height
    chartEl.height = chartHeight;
    chartEl.chartHeight = chartHeight;
    chartEl.style.cssText = `display: block; width: 100%; height: ${chartHeight}px;`;
    chartEl.setAttribute("chart-height", chartHeight);

    chartContainer.appendChild(chartEl);

    // Resize after render - delay to allow animation to start
    setTimeout(() => {
      if (chartEl.chart) {
        chartEl.chart.resize({ height: chartHeight, animation: { duration: 0 } });
      }
    }, 50);
  }

  _renderError(message) {
    this.shadowRoot.innerHTML = `
      <style>${this._getStyles()}</style>
      <div class="error">
        <ha-icon icon="mdi:alert-circle"></ha-icon>
        ${message}
      </div>
    `;
  }

  _getStyles() {
    return `
      :host {
        display: block;
        --mdc-theme-primary: var(--primary-color);
      }

      ha-top-app-bar-fixed {
        --mdc-theme-primary: var(--app-header-background-color, var(--primary-color));
        --mdc-theme-on-primary: var(--app-header-text-color, #fff);
      }

      .content {
        padding: 16px;
        max-width: 1200px;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 16px;
        background: var(--primary-background-color, #fafafa);
      }

      ha-card {
        --ha-card-border-radius: 12px;
      }

      .card-content {
        padding: 16px;
      }

      .controls {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        align-items: flex-end;
      }

      .control-group {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 150px;
      }

      .control-group.date-range-group {
        min-width: 300px;
        flex-grow: 1;
      }

      #date-range-picker-container {
        width: 100%;
      }

      #date-range-picker-container ha-date-range-picker {
        width: 100%;
      }

      .control-group label {
        font-size: 12px;
        font-weight: 500;
        color: var(--secondary-text-color, #666);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .native-select {
        min-width: 150px;
        padding: 8px 12px;
        font-size: 14px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color, #212121);
        cursor: pointer;
        outline: none;
        -webkit-appearance: none;
        -moz-appearance: none;
        appearance: none;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23666' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 10px center;
        padding-right: 30px;
      }

      .native-select:hover {
        border-color: var(--primary-color);
      }

      .native-select:focus {
        border-color: var(--primary-color);
        box-shadow: 0 0 0 2px rgba(var(--rgb-primary-color, 33, 150, 243), 0.2);
      }

      .chart-card-content {
        padding: 16px;
      }

      .chart-container {
        position: relative;
      }

      .chart-container ha-chart-base {
        display: block;
        width: 100%;
      }

      .legend-panel {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        justify-content: center;
      }

      .legend-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        border-radius: 16px;
        background: var(--secondary-background-color, #f5f5f5);
        font-size: 13px;
        cursor: pointer;
        user-select: none;
        transition: opacity 0.2s, background 0.2s;
      }

      .legend-item:hover {
        background: var(--divider-color, #e0e0e0);
      }

      .legend-item.disabled {
        opacity: 0.4;
      }

      .legend-item.disabled .legend-indicator {
        background: var(--disabled-color, #bdbdbd) !important;
      }

      .legend-indicator {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--color);
        flex-shrink: 0;
        box-sizing: border-box;
      }

      /* Spinner animation when loading */
      .legend-item.loading .legend-indicator {
        background: transparent;
        border: 2px solid var(--divider-color, #e0e0e0);
        border-top-color: var(--color);
        animation: legend-spin 0.8s linear infinite;
      }

      @keyframes legend-spin {
        to {
          transform: rotate(360deg);
        }
      }

      .legend-label {
        color: var(--primary-text-color, #212121);
        white-space: nowrap;
      }

      .chart-placeholder {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 400px;
        color: var(--secondary-text-color, #666);
        font-style: italic;
      }

      .loading-overlay {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 400px;
        gap: 16px;
        background: var(--card-background-color, #fff);
      }

      .loading-overlay ha-circular-progress {
        --mdc-theme-primary: var(--primary-color);
      }

      .loading-text {
        font-size: 16px;
        font-weight: 500;
        color: var(--primary-text-color, #212121);
      }

      .loading-subtext {
        font-size: 13px;
        color: var(--secondary-text-color, #666);
      }

      .info-card p {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        margin: 0;
        color: var(--secondary-text-color, #666);
        font-size: 14px;
        line-height: 1.5;
      }

      .info-card ha-icon {
        flex-shrink: 0;
        --mdc-icon-size: 20px;
        color: var(--primary-color);
      }

      .loading, .error {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
      }

      .error {
        color: var(--error-color, #f44336);
      }

      @media (max-width: 600px) {
        .content {
          padding: 8px;
        }

        .card-content {
          padding: 12px;
        }

        .chart-card-content {
          padding: 12px;
        }

        .controls {
          flex-direction: column;
          align-items: stretch;
        }

        .control-group {
          width: 100%;
          min-width: unset;
        }

        .control-group.date-range-group {
          min-width: unset;
        }

        .native-select {
          width: 100%;
        }

        .legend-panel {
          justify-content: center;
        }

        .legend-item {
          padding: 4px 10px;
          font-size: 12px;
        }
      }
    `;
  }
}

customElements.define(PANEL_NAME, MeteoClubPanel);
