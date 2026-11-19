import { LitElement, css, html, nothing } from "lit";

const CREATE_TODO_ITEM = 1;
const UPDATE_TODO_ITEM = 4;

class HaTodoCard extends LitElement {
  static properties = {
    hass: {},
    config: {},
    _items: { state: true },
    _loading: { state: true },
    _error: { state: true },
    _newItem: { state: true },
    _adding: { state: true },
    _busyItems: { state: true },
  };

  static styles = css`
    :host {
      display: block;
      color: var(--primary-text-color);
    }

    ha-card {
      overflow: hidden;
    }

    .header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 16px 16px 8px;
      font-size: 1.1rem;
      font-weight: 500;
    }

    .count {
      color: var(--secondary-text-color);
      font-size: 0.85rem;
      font-weight: 400;
      margin-left: auto;
    }

    .content {
      padding: 8px 16px 16px;
    }

    .items {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .items.tiles {
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr));
    }

    .item {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      min-width: 0;
      padding: 0;
      border: 1px solid var(--divider-color);
      border-radius: 12px;
      background: var(--card-background-color);
    }

    .item.completed {
      opacity: 0.68;
    }

    .item-label {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      width: 100%;
      min-width: 0;
      min-height: 44px;
      padding: 10px 12px;
      box-sizing: border-box;
      cursor: pointer;
    }

    .item input[type="checkbox"] {
      flex: 0 0 auto;
      width: 22px;
      height: 22px;
      margin: 1px 0 0;
      accent-color: var(--primary-color);
      cursor: pointer;
    }

    .item input[type="checkbox"]:disabled {
      cursor: default;
    }

    .item-body {
      flex: 1;
      min-width: 0;
    }

    .summary {
      overflow-wrap: anywhere;
      line-height: 1.35;
    }

    .completed .summary {
      text-decoration: line-through;
      color: var(--secondary-text-color);
    }

    .details {
      display: flex;
      flex-wrap: wrap;
      gap: 4px 10px;
      margin-top: 4px;
      color: var(--secondary-text-color);
      font-size: 0.82rem;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }

    .empty,
    .loading,
    .error {
      padding: 12px 0;
      color: var(--secondary-text-color);
      text-align: center;
    }

    .error {
      color: var(--error-color, var(--error-state-color));
    }

    form {
      display: flex;
      gap: 8px;
      margin-top: 14px;
    }

    form input {
      flex: 1;
      min-width: 0;
      min-height: 44px;
      box-sizing: border-box;
      padding: 0 12px;
      border: 1px solid var(--divider-color);
      border-radius: 10px;
      background: var(--card-background-color);
      color: var(--primary-text-color);
      font: inherit;
    }

    form button {
      min-width: 44px;
      min-height: 44px;
      padding: 0 14px;
      border: 0;
      border-radius: 10px;
      background: var(--primary-color);
      color: var(--text-primary-color, white);
      font: inherit;
      font-weight: 500;
      cursor: pointer;
    }

    form button:disabled {
      opacity: 0.5;
      cursor: default;
    }

    @media (max-width: 420px) {
      .content {
        padding-right: 12px;
        padding-left: 12px;
      }

      .items.tiles {
        grid-template-columns: 1fr;
      }
    }
  `;

  constructor() {
    super();
    this._items = [];
    this._loading = true;
    this._error = "";
    this._newItem = "";
    this._adding = false;
    this._busyItems = new Set();
    this._unsubscribe = undefined;
    this._subscribedConnection = undefined;
    this._subscribedEntity = undefined;
    this._subscriptionToken = 0;
  }

  setConfig(config) {
    if (!config || typeof config.entity !== "string" || !/^todo\.[a-z0-9_]+$/i.test(config.entity)) {
      throw new Error("Please define a valid Todo entity, for example todo.shopping_list.");
    }

    const display = config.display ?? "list";
    if (!["list", "tiles"].includes(display)) {
      throw new Error("The display option must be either 'list' or 'tiles'.");
    }

    this.config = {
      entity: config.entity,
      display,
      show_completed: config.show_completed === true,
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this._ensureSubscription();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._clearSubscription();
  }

  updated(changedProperties) {
    if (changedProperties.has("hass") || changedProperties.has("config")) {
      this._ensureSubscription();
    }
  }

  _clearSubscription() {
    this._subscriptionToken += 1;
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = undefined;
    }
    this._subscribedConnection = undefined;
    this._subscribedEntity = undefined;
  }

  async _ensureSubscription() {
    if (!this.isConnected || !this.hass?.connection || !this.config?.entity) {
      return;
    }

    const connection = this.hass.connection;
    const entity = this.config.entity;
    if (
      this._subscribedConnection === connection &&
      this._subscribedEntity === entity
    ) {
      return;
    }

    this._clearSubscription();
    this._items = [];
    this._loading = true;
    this._error = "";
    this._subscribedConnection = connection;
    this._subscribedEntity = entity;
    const token = this._subscriptionToken;

    try {
      const unsubscribe = await connection.subscribeMessage(
        (event) => {
          if (token !== this._subscriptionToken) {
            return;
          }
          this._items = Array.isArray(event.items) ? event.items : [];
          this._loading = false;
          this._error = "";
        },
        {
          type: "todo/item/subscribe",
          entity_id: entity,
        },
      );

      if (token !== this._subscriptionToken) {
        unsubscribe();
      } else {
        this._unsubscribe = unsubscribe;
      }
    } catch (error) {
      if (token === this._subscriptionToken) {
        this._loading = false;
        this._subscribedConnection = undefined;
        this._subscribedEntity = undefined;
        this._error = error?.message || "The to-do list could not be loaded.";
      }
    }
  }

  get _entityState() {
    return this.hass?.states?.[this.config?.entity];
  }

  get _canAdd() {
    return Boolean(
      Number(this._entityState?.attributes?.supported_features ?? 0) &
        CREATE_TODO_ITEM,
    );
  }

  get _canUpdate() {
    return Boolean(
      Number(this._entityState?.attributes?.supported_features ?? 0) &
        UPDATE_TODO_ITEM,
    );
  }

  get _visibleItems() {
    return this.config?.show_completed
      ? this._items
      : this._items.filter((item) => item.status !== "completed");
  }

  _hasText(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  _formatDue(value) {
    if (!this._hasText(value)) {
      return "";
    }

    const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    const date = dateOnly
      ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
      : new Date(value);

    if (Number.isNaN(date.getTime())) {
      return value;
    }

    return date.toLocaleString(undefined, {
      dateStyle: "medium",
      ...(dateOnly ? {} : { timeStyle: "short" }),
    });
  }

  async _addItem(event) {
    event.preventDefault();
    const item = this._newItem.trim();
    if (!item || !this._canAdd) {
      return;
    }

    this._error = "";
    this._adding = true;
    try {
      await this.hass.callService("todo", "add_item", {
        entity_id: this.config.entity,
        item,
      });
      this._newItem = "";
    } catch (error) {
      this._error = error?.message || "The item could not be added.";
    } finally {
      this._adding = false;
    }
  }

  async _toggleItem(item, event) {
    event.stopPropagation();
    if (!this._canUpdate || !item.uid || this._busyItems.has(item.uid)) {
      return;
    }

    const nextStatus =
      item.status === "completed" ? "needs_action" : "completed";
    this._busyItems = new Set(this._busyItems).add(item.uid);
    this._error = "";

    try {
      await this.hass.callService("todo", "update_item", {
        entity_id: this.config.entity,
        item: item.uid,
        status: nextStatus,
      });
    } catch (error) {
      this._error = error?.message || "The item status could not be changed.";
    } finally {
      const busy = new Set(this._busyItems);
      busy.delete(item.uid);
      this._busyItems = busy;
    }
  }

  _renderItem(item) {
    const completed = item.status === "completed";
    const description = this._hasText(item.description)
      ? item.description.trim()
      : "";
    const due = this._formatDue(item.due);

    return html`
      <li class="item ${completed ? "completed" : ""}">
        <label class="item-label">
        <input
          type="checkbox"
          .checked=${completed}
          .disabled=${!this._canUpdate || !item.uid || this._busyItems.has(item.uid)}
          aria-label=${completed ? "Reopen item" : "Complete item"}
          @change=${(event) => this._toggleItem(item, event)}
        />
        <div class="item-body">
          <div class="summary">${item.summary || ""}</div>
          ${description || due
            ? html`
                <div class="details">
                  ${description ? html`<span>${description}</span>` : nothing}
                  ${due ? html`<span>${due}</span>` : nothing}
                </div>
              `
            : nothing}
        </div>
        </label>
      </li>
    `;
  }

  render() {
    if (!this.config) {
      return nothing;
    }

    const title =
      this._entityState?.attributes?.friendly_name || this.config.entity;
    const openCount = this._items.filter(
      (item) => item.status !== "completed",
    ).length;

    return html`
      <ha-card>
        <div class="header">
          <span>${title}</span>
          <span class="count">${openCount}</span>
        </div>
        <div class="content">
          ${this._loading
            ? html`<div class="loading">Loading…</div>`
            : this._error && this._items.length === 0
              ? html`<div class="error" role="alert">${this._error}</div>`
              : this._visibleItems.length === 0
                ? html`<div class="empty">No open items</div>`
                : html`
                    <ul class="items ${this.config.display}">
                      ${this._visibleItems.map((item) => this._renderItem(item))}
                    </ul>
                  `}
          ${this._canAdd
            ? html`
                <form @submit=${this._addItem}>
                  <input
                    type="text"
                    .value=${this._newItem}
                    placeholder="Add an item"
                    aria-label="New to-do item"
                    @input=${(event) => {
                      this._newItem = event.target.value;
                    }}
                  />
                  <button type="submit" ?disabled=${!this._newItem.trim() || this._adding}>
                    ${this._adding ? "Adding…" : "Add"}
                  </button>
                </form>
              `
            : nothing}
          ${this._error && this._items.length > 0
            ? html`<div class="error" role="alert">${this._error}</div>`
            : nothing}
        </div>
      </ha-card>
    `;
  }

  getCardSize() {
    return Math.max(2, Math.min(8, this._visibleItems.length + 1));
  }
}

customElements.define("ha-todo-card", HaTodoCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ha-todo-card",
  name: "To-do Sync Card",
  description: "Display and manage a Home Assistant to-do list.",
});
