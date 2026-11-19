const CREATE_TODO_ITEM = 1;
const UPDATE_TODO_ITEM = 4;

const CARD_STYLES = [
  ":host { display: block; color: var(--primary-text-color); }",
  "ha-card { overflow: hidden; }",
  ".header { display: flex; align-items: center; gap: 8px; padding: 16px 16px 8px; font-size: 1.1rem; font-weight: 500; }",
  ".count { margin-left: auto; color: var(--secondary-text-color); font-size: 0.85rem; font-weight: 400; }",
  ".content { padding: 8px 16px 16px; }",
  ".items { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }",
  ".items.tiles { grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); }",
  ".item { min-width: 0; padding: 0; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--ha-card-background, var(--card-background-color)); }",
  ".item.completed { background: var(--secondary-background-color); }",
  ".item-label { display: flex; align-items: flex-start; gap: 12px; width: 100%; min-width: 0; min-height: 52px; padding: 14px; box-sizing: border-box; cursor: pointer; }",
  ".item input[type=checkbox] { flex: 0 0 auto; width: 22px; height: 22px; margin: 1px 0 0; accent-color: var(--primary-color); cursor: pointer; }",
  ".item input[type=checkbox]:disabled { cursor: default; }",
  ".item-body { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex: 1; min-width: 0; }",
  ".summary { min-width: 0; overflow-wrap: anywhere; line-height: 1.4; }",
  ".completed .summary { color: var(--secondary-text-color); text-decoration: line-through; }",
  ".details { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 4px; color: var(--secondary-text-color); font-size: 0.82rem; line-height: 1.35; overflow-wrap: anywhere; }",
  ".items.list { display: block; }",
  ".items.list .item { border: 0; border-bottom: 1px solid var(--divider-color); border-radius: 0; background: transparent; }",
  ".items.list .item:last-child { border-bottom: 0; }",
  ".items.list .item-label { align-items: center; min-height: 52px; padding: 10px 4px; }",
  ".items.list .item-body { align-items: center; }",
  ".items.list .details { justify-content: flex-end; margin: 0 0 0 auto; text-align: right; }",
  ".empty, .loading, .error { padding: 12px 0; color: var(--secondary-text-color); text-align: center; }",
  ".error { color: var(--error-color, var(--error-state-color)); }",
  "form { display: flex; gap: 8px; margin-top: 14px; }",
  "form input { flex: 1; min-width: 0; min-height: 48px; box-sizing: border-box; padding: 0 14px; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--secondary-background-color); color: var(--primary-text-color); font: inherit; }",
  "form input:focus { outline: 2px solid var(--primary-color); outline-offset: 1px; }",
  "form button { min-width: 48px; min-height: 48px; padding: 0 16px; border: 0; border-radius: 12px; background: var(--primary-color); color: var(--text-primary-color, white); font-size: 1.4rem; cursor: pointer; }",
  "form button:disabled { opacity: 0.5; cursor: default; }",
  "@media (max-width: 520px) { .content { padding-right: 12px; padding-left: 12px; } .items.tiles { grid-template-columns: 1fr; } .items.list .item-body { align-items: flex-start; flex-direction: column; gap: 3px; } .items.list .details { justify-content: flex-start; margin: 0; text-align: left; } }",
].join("\n");

const EDITOR_SCHEMA = [
  { name: "entity", selector: { entity: { domain: "todo" } } },
  { name: "display", selector: { select: { mode: "dropdown", options: [
    { value: "tiles", label: "Kacheln" },
    { value: "list", label: "Liste" },
  ] } } },
  { name: "show_completed", selector: { boolean: {} } },
  { name: "show_details", selector: { boolean: {} } },
];

class HaTodoCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = {};
  }

  set hass(value) {
    this._hass = value;
    this._render();
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  _valueChanged(event) {
    const value = event.detail?.value;
    if (!value) return;
    this._config = { ...this._config, ...value };
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    const style = document.createElement("style");
    style.textContent = ".editor { display: grid; gap: 12px; } ha-form { display: block; }";
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.data = { display: "list", show_completed: false, show_details: true, ...this._config };
    form.schema = EDITOR_SCHEMA;
    form.computeLabel = (schema) => ({
      entity: "Todo-Liste",
      display: "Darstellung",
      show_completed: "Erledigte Einträge anzeigen",
      show_details: "Details anzeigen (falls vorhanden)",
    })[schema.name] || schema.name;
    form.addEventListener("value-changed", (event) => this._valueChanged(event));
    const wrapper = document.createElement("div");
    wrapper.className = "editor";
    wrapper.append(form);
    this.shadowRoot.replaceChildren(style, wrapper);
  }
}

if (!customElements.get("ha-todo-card-editor")) {
  customElements.define("ha-todo-card-editor", HaTodoCardEditor);
}

class HaTodoCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("ha-todo-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass?.states || {}).find((id) => id.startsWith("todo."));
    return { entity: entity || "", display: "list", show_completed: false, show_details: true };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = undefined;
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
      throw new Error("Bitte wähle eine gültige Todo-Entity aus.");
    }
    const display = config.display || "list";
    if (!["list", "tiles"].includes(display)) {
      throw new Error("Die Darstellung muss 'Liste' oder 'Kacheln' sein.");
    }
    this._config = {
      entity: config.entity,
      display,
      show_completed: config.show_completed === true,
      show_details: config.show_details !== false,
    };
    this._ensureSubscription();
    this._render();
  }

  set hass(value) {
    this._hass = value;
    this._ensureSubscription();
    this._render();
  }

  get hass() { return this._hass; }

  connectedCallback() {
    this._ensureSubscription();
    this._render();
  }

  disconnectedCallback() { this._clearSubscription(); }

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
    if (!this.isConnected || !this._hass?.connection || !this._config?.entity) return;
    const connection = this._hass.connection;
    const entity = this._config.entity;
    if (this._subscribedConnection === connection && this._subscribedEntity === entity) return;

    this._clearSubscription();
    this._items = [];
    this._loading = true;
    this._error = "";
    this._subscribedConnection = connection;
    this._subscribedEntity = entity;
    const token = this._subscriptionToken;
    this._render();

    try {
      const unsubscribe = await connection.subscribeMessage(
        (event) => {
          if (token !== this._subscriptionToken) return;
          this._items = Array.isArray(event.items) ? event.items : [];
          this._loading = false;
          this._error = "";
          this._render();
        },
        { type: "todo/item/subscribe", entity_id: entity },
      );
      if (token !== this._subscriptionToken) unsubscribe();
      else this._unsubscribe = unsubscribe;
    } catch (error) {
      if (token === this._subscriptionToken) {
        this._loading = false;
        this._subscribedConnection = undefined;
        this._subscribedEntity = undefined;
        this._error = error?.message || "Die Liste konnte nicht geladen werden.";
        this._render();
      }
    }
  }

  get _entityState() { return this._hass?.states?.[this._config?.entity]; }

  get _canAdd() {
    return Boolean(Number(this._entityState?.attributes?.supported_features ?? 0) & CREATE_TODO_ITEM);
  }

  get _canUpdate() {
    return Boolean(Number(this._entityState?.attributes?.supported_features ?? 0) & UPDATE_TODO_ITEM);
  }

  get _visibleItems() {
    return this._config?.show_completed
      ? this._items
      : this._items.filter((item) => item.status !== "completed");
  }

  _hasText(value) { return typeof value === "string" && value.trim().length > 0; }

  _formatDue(value) {
    if (!this._hasText(value)) return "";
    const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    const date = dateOnly
      ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
      : new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, {
      dateStyle: "medium",
      ...(dateOnly ? {} : { timeStyle: "short" }),
    });
  }

  async _addItem(event) {
    event.preventDefault();
    const item = this._newItem.trim();
    if (!item || !this._canAdd || this._adding) return;
    this._error = "";
    this._adding = true;
    this._render();
    try {
      await this._hass.callService("todo", "add_item", { entity_id: this._config.entity, item });
      this._newItem = "";
    } catch (error) {
      this._error = error?.message || "Der Eintrag konnte nicht hinzugefügt werden.";
    } finally {
      this._adding = false;
      this._render();
    }
  }

  async _toggleItem(item, event) {
    event.stopPropagation();
    if (!this._canUpdate || !item.uid || this._busyItems.has(item.uid)) return;
    const nextStatus = item.status === "completed" ? "needs_action" : "completed";
    this._busyItems = new Set(this._busyItems).add(item.uid);
    this._error = "";
    this._render();
    try {
      await this._hass.callService("todo", "update_item", {
        entity_id: this._config.entity, item: item.uid, status: nextStatus,
      });
    } catch (error) {
      this._error = error?.message || "Der Status des Eintrags konnte nicht geändert werden.";
    } finally {
      const busy = new Set(this._busyItems);
      busy.delete(item.uid);
      this._busyItems = busy;
      this._render();
    }
  }

  _renderItem(item) {
    const completed = item.status === "completed";
    const description = this._config.show_details && this._hasText(item.description)
      ? item.description.trim() : "";
    const due = this._config.show_details ? this._formatDue(item.due) : "";
    const listItem = document.createElement("li");
    listItem.className = "item" + (completed ? " completed" : "");
    const label = document.createElement("label");
    label.className = "item-label";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = completed;
    checkbox.disabled = !this._canUpdate || !item.uid || this._busyItems.has(item.uid);
    checkbox.setAttribute("aria-label", completed ? "Eintrag wieder öffnen" : "Eintrag erledigen");
    checkbox.addEventListener("change", (event) => this._toggleItem(item, event));
    const body = document.createElement("div");
    body.className = "item-body";
    const summary = document.createElement("div");
    summary.className = "summary";
    summary.textContent = item.summary || "";
    body.append(summary);

    if (description || due) {
      const details = document.createElement("div");
      details.className = "details";
      if (description) {
        const element = document.createElement("span");
        element.textContent = description;
        details.append(element);
      }
      if (due) {
        const element = document.createElement("span");
        element.textContent = due;
        details.append(element);
      }
      body.append(details);
    }
    label.append(checkbox, body);
    listItem.append(label);
    return listItem;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const previousInput = this.shadowRoot.activeElement;
    const restoreInputFocus = previousInput?.matches?.("form input");
    const selectionStart = restoreInputFocus ? previousInput.selectionStart : null;
    const selectionEnd = restoreInputFocus ? previousInput.selectionEnd : null;

    const style = document.createElement("style");
    style.textContent = CARD_STYLES;
    const card = document.createElement("ha-card");
    const header = document.createElement("div");
    header.className = "header";
    const title = document.createElement("span");
    title.textContent = this._entityState?.attributes?.friendly_name || this._config.entity;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(this._items.filter((item) => item.status !== "completed").length);
    header.append(title, count);

    const content = document.createElement("div");
    content.className = "content";
    if (this._loading) {
      const loading = document.createElement("div");
      loading.className = "loading";
      loading.textContent = "Wird geladen …";
      content.append(loading);
    } else if (this._error && this._items.length === 0) {
      const error = document.createElement("div");
      error.className = "error";
      error.setAttribute("role", "alert");
      error.textContent = this._error;
      content.append(error);
    } else if (this._visibleItems.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = this._config.show_completed ? "Keine Einträge" : "Keine offenen Einträge";
      content.append(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "items " + this._config.display;
      for (const item of this._visibleItems) list.append(this._renderItem(item));
      content.append(list);
    }

    if (this._canAdd) {
      const form = document.createElement("form");
      const input = document.createElement("input");
      input.type = "text";
      input.value = this._newItem;
      input.placeholder = "Neuer Eintrag";
      input.setAttribute("aria-label", "Neuer Eintrag");
      const button = document.createElement("button");
      button.type = "submit";
      button.disabled = !this._newItem.trim() || this._adding;
      button.textContent = this._adding ? "…" : "+";
      button.setAttribute("aria-label", "Eintrag hinzufügen");
      input.addEventListener("input", (event) => {
        this._newItem = event.target.value;
        button.disabled = !this._newItem.trim() || this._adding;
      });
      form.addEventListener("submit", (event) => this._addItem(event));
      form.append(input, button);
      content.append(form);
    }

    if (this._error && this._items.length > 0) {
      const error = document.createElement("div");
      error.className = "error";
      error.setAttribute("role", "alert");
      error.textContent = this._error;
      content.append(error);
    }
    card.append(header, content);
    this.shadowRoot.replaceChildren(style, card);

    if (restoreInputFocus) {
      const nextInput = this.shadowRoot.querySelector("form input");
      nextInput?.focus();
      if (selectionStart !== null && selectionEnd !== null) nextInput?.setSelectionRange(selectionStart, selectionEnd);
    }
  }

  getCardSize() { return Math.max(2, Math.min(8, this._visibleItems.length + 1)); }
}

if (!customElements.get("ha-todo-card")) {
  customElements.define("ha-todo-card", HaTodoCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ha-todo-card",
  name: "To-do Sync Card",
  description: "Todo-Listen als Kacheln oder Liste anzeigen und bearbeiten.",
  preview: true,
});