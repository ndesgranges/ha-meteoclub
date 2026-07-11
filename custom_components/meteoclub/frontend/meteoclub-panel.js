/**
 * MeteoClub Weather Dashboard Panel
 * Version: 5.0.0 - Native HA components (ha-top-app-bar-fixed, ha-date-range-picker)
 *
 * A custom Home Assistant panel that displays weather model accuracy comparison.
 * Uses Home Assistant's native ha-chart-base component with ECharts for proper
 * styling, interactions, and the built-in legend with checkboxes to toggle series.
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
      
      // Wait for HA components to be defined before rendering
      await this._ensureComponentsLoaded();
      this._render();

      // Load initial chart data
      if (this._selectedCity) {
        this._loadChartData();
      }
    } catch (err) {
      console.error("Failed to load MeteoClub config:", err);
      this._renderError("Failed to load configuration");
    }
  }

  async _ensureComponentsLoaded() {
    // Load the "history" fragment which includes ha-top-app-bar-fixed and ha-date-range-picker
    // This is the HA-native way to trigger lazy loading of components
    try {
      await this._hass.loadFragmentTranslation("history");
    } catch (e) {
      console.warn("MeteoClub: Could not load history fragment:", e);
    }
    
    // Now wait for the components to be defined (they should be loading now)
    const components = [
      "ha-top-app-bar-fixed",
      "ha-date-range-picker",
    ];
    
    await Promise.all(
      components.map(name => 
        customElements.whenDefined(name).catch(() => {
          console.warn(`MeteoClub: Component ${name} not available`);
        })
      )
    );
  }

  async _loadChartData() {
    if (!this._selectedCity || !this._hass || this._loading) return;

    this._loading = true;
    this._render();
    this._renderLoadingState();

    try {
      const result = await this._hass.callWS({
        type: "meteoclub/chart_data",
        city_id: this._selectedCity,
        metric: this._selectedMetric,
        horizon_days: this._selectedHorizon,
        models: this._allModels || ["gfs", "arome"],
        start_date: this._startDate.toISOString(),
        end_date: this._endDate.toISOString(),
      });

      console.log("MeteoClub: Chart data received", result);
      this._chartData = result;
      this._loading = false;
      this._render();
      this._renderChart();
    } catch (err) {
      console.error("Failed to load chart data:", err);
      this._loading = false;
      this._render();
    }
  }

  _renderLoadingState() {
    const chartEl = this.shadowRoot.getElementById("chart");
    if (chartEl) {
      chartEl.innerHTML = `
        <div class="loading-overlay">
          <ha-circular-progress indeterminate></ha-circular-progress>
          <span class="loading-text">Loading forecast data...</span>
          <span class="loading-subtext">This may take a moment for large datasets</span>
        </div>
      `;
    }
  }

  _render() {
    if (!this._config) {
      this.shadowRoot.innerHTML = `
        <style>${this._getStyles()}</style>
        <div class="loading"><ha-circular-progress indeterminate></ha-circular-progress></div>
      `;
      return;
    }

    // Content goes INSIDE ha-top-app-bar-fixed (in default slot)
    this.shadowRoot.innerHTML = `
      <style>${this._getStyles()}</style>
      <ha-top-app-bar-fixed>
        <span slot="title">MeteoClub</span>

        <div class="content">
          <ha-card>
            <div class="card-content controls">
              <div class="control-group date-range-group">
                <label>Date Range</label>
                <ha-date-range-picker
                  id="date-range-picker"
                  extended-presets
                ></ha-date-range-picker>
              </div>

              <div class="control-group">
                <label>City</label>
                <select id="city-select" class="native-select">
                  ${this._cities.map(c => `<option value="${c.id}" ${c.id === this._selectedCity ? "selected" : ""}>${c.name}</option>`).join("")}
                </select>
              </div>

              <div class="control-group">
                <label>Metric</label>
                <select id="metric-select" class="native-select">
                  ${this._config.metrics.map(m => `<option value="${m.id}" ${m.id === this._selectedMetric ? "selected" : ""}>${m.name}</option>`).join("")}
                </select>
              </div>

              <div class="control-group">
                <label>Forecast Horizon</label>
                <select id="horizon-select" class="native-select">
                  ${this._config.horizons.map(h => `<option value="${h}" ${h === this._selectedHorizon ? "selected" : ""}>${h} day${h > 1 ? "s" : ""}</option>`).join("")}
                </select>
              </div>

              ${this._loading ? '<ha-circular-progress indeterminate size="small"></ha-circular-progress>' : ''}
            </div>
          </ha-card>

          <ha-card>
            <div class="card-content">
              <div class="chart-container" id="chart">
                <div class="chart-placeholder">Select a city to display the chart</div>
              </div>
            </div>
          </ha-card>

          <ha-card class="info-card">
            <div class="card-content">
              <p>
                <ha-icon icon="mdi:information-outline"></ha-icon>
                Dashed lines show what each model predicted, based on forecasts made
                <strong>${this._selectedHorizon} day${this._selectedHorizon > 1 ? "s" : ""}</strong> in advance.
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

    // Setup date range picker - MUST pass hass for localization
    const dateRangePicker = this.shadowRoot.getElementById("date-range-picker");
    if (dateRangePicker) {
      // Pass hass first (required for localization)
      dateRangePicker.hass = this._hass;
      dateRangePicker.startDate = this._startDate;
      dateRangePicker.endDate = this._endDate;
      dateRangePicker.addEventListener("value-changed", (e) => {
        const { startDate, endDate } = e.detail.value;
        if (startDate && endDate) {
          this._startDate = startDate;
          this._endDate = endDate;
          this._savePreferences();
          this._loadChartData();
        }
      });
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
  }

  _renderChart() {
    const chartContainer = this.shadowRoot.getElementById("chart");
    if (!chartContainer || !this._chartData) {
      console.log("MeteoClub: No chart container or data", { chartContainer, chartData: this._chartData });
      return;
    }

    const { observations, forecasts, metric } = this._chartData;
    console.log("MeteoClub: Rendering chart", { observations: observations?.length, forecasts: Object.keys(forecasts || {}), metric });

    if (!observations || observations.length === 0) {
      chartContainer.innerHTML = `<div class="chart-placeholder">No observation data available for the selected period</div>`;
      return;
    }

    // Prepare series data for ha-chart-base (ECharts format)
    // ha-chart-base expects: data = array of series, options = chart config
    const seriesData = [];
    const legendData = [];

    // Observation series (solid line)
    const obsId = "observation";
    seriesData.push({
      id: obsId,
      name: "Observation",
      type: "line",
      data: observations.map((o) => [new Date(o.time).getTime(), o.value]),
      smooth: true,
      symbol: "circle",
      symbolSize: 4,
      lineStyle: {
        width: 2,
      },
      color: COLORS.observation,
      emphasis: {
        focus: "series",
      },
    });
    legendData.push({ id: obsId, name: "Observation" });

    // Forecast series (dashed lines) - add ALL configured models
    for (const modelConfig of this._config.models) {
      const model = modelConfig.id;
      const modelName = modelConfig.name;
      const data = forecasts[model] || [];
      const color = COLORS[model] || "#888";
      const seriesId = `forecast-${model}`;
      
      seriesData.push({
        id: seriesId,
        name: modelName,
        type: "line",
        data: data.map((f) => [new Date(f.time).getTime(), f.value]),
        smooth: true,
        symbol: "none",
        lineStyle: {
          width: 2,
          type: "dashed",
        },
        color: color,
        emphasis: {
          focus: "series",
        },
      });
      legendData.push({ id: seriesId, name: modelName });
    }

    // Chart options for ha-chart-base (without series - that goes in data prop)
    const chartOptions = {
      xAxis: {
        type: "time",
        min: new Date(observations[0].time),
        max: new Date(observations[observations.length - 1].time),
      },
      yAxis: {
        type: "value",
        name: `${metric.name} (${metric.unit})`,
        nameLocation: "middle",
        nameGap: 50,
      },
      legend: {
        show: true,
        type: "custom",
        data: legendData,
      },
      tooltip: {
        trigger: "axis",
      },
    };

    // Clear container and create ha-chart-base
    chartContainer.innerHTML = "";
    
    const chartEl = document.createElement("ha-chart-base");
    chartEl.hass = this._hass;
    chartEl.data = seriesData;
    chartEl.options = chartOptions;
    chartEl.style.height = "400px";
    chartContainer.appendChild(chartEl);
    
    console.log("MeteoClub: ha-chart-base created with", seriesData.length, "series");
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

      .control-group.date-range-group ha-date-range-picker {
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

      .chart-container {
        min-height: 400px;
        position: relative;
      }

      .chart-container ha-chart-base {
        display: block;
        width: 100%;
        height: 400px;
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
        min-height: 200px;
        font-size: 16px;
        color: var(--secondary-text-color, #666);
      }

      .error {
        color: var(--error-color, #f44336);
      }

      @media (max-width: 600px) {
        .controls {
          flex-direction: column;
          align-items: stretch;
        }

        .control-group {
          width: 100%;
        }

        .native-select {
          width: 100%;
        }
      }
    `;
  }
}

customElements.define(PANEL_NAME, MeteoClubPanel);
