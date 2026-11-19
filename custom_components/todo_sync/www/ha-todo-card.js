const CREATE_TODO_ITEM = 1;
const UPDATE_TODO_ITEM = 4;

const CARD_STYLES = [
  ":host { display: block; color: var(--primary-text-color); }",
  "ha-card { overflow: hidden; }",
  ".header { display: flex; align-items: center; gap: 8px; padding: 16px 16px 8px; font-size: 1.1rem; font-weight: 500; }",
  ".count { margin-left: auto; color: var(--secondary-text-color); font-size: 0.85rem; font-weight: 400; }",
  ".content { padding: 8px 16px 16px; }",
  ".items { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }",
  ".items.tiles { grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); }",
  ".item { min-width: 0; padding: 0; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--card-background-color); }",
  ".item.completed { opacity: 0.68; }",
  ".item-label { display: flex; align-items: flex-start; gap: 12px; width: 100%; min-width: 0; min-height: 44px; padding: 10px 12px; box-sizing: border-box; cursor: pointer; }",
  ".item input[type=checkbox] { flex: 0 0 auto; width: 22px; height: 22px; margin: 1px 0 0; accent-color: var(--primary-color); cursor: pointer; }",
  ".item input[type=checkbox]:disabled { cursor: default; }",
  ".item-body { flex: 1; min-width: 0; }",
  ".summary { overflow-wrap: anywhere; line-height: 1.35; }",
  ".completed .summary { color: var(--secondary-text-color); text-decoration: line-through; }",
  ".details { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 4px; color: var(--secondary-text-color); font-size: 0.82rem; line-height: 1.3; overflow-wrap: anywhere; }",
  ".empty, .loading, .error { padding: 12px 0; color: var(--secondary-text-color); text-align: center; }",
  ".error { color: var(--error-color, var(--error-state-color)); }",
  "form { display: flex; gap: 8px; margin-top: 14px; }",
  "form input { flex: 1; min-width: 0; min-height: 44px; box-sizing: border-box; padding: 0 12px; border: 1px solid var(--divider-color); border-radius: 10px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }",
  "form button { min-width: 44px; min-height: 44px; padding: 0 14px; border: 0; border-radius: 10px; background: var(--primary-color); color: var(--text-primary-color, white); font: inherit; font-weight: 500; cursor: pointer; }",
  "form button:disabled { opacity: 0.5; cursor: default; }",
  "@media (max-width: 420px) { .content { padding-right: 12px; padding-left: 12px; } .items.tiles { grid-template-columns: 1fr; } }",
].join("\n");

class HaTodoCard extends HTMLElement {
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
    if (
      !config ||
      typeof config.entity !== "string" ||
      !/^todo\.[a-z0-9_]+$/i.test(config.entity)
    ) {
      throw new Error(
        "Please define a valid Todo entity, for example todo.shopping_list.",
      );
    }

    const display = config.display || "list";
    if (!["list", "tiles"].includes(display)) {
      throw new Error("The display option must be either 'list' or 'tiles'.");
    }

    this._config = {
      entity: config.entity,
      display,
      show_completed: config.show_completed === true,
    };
    this._ensureSubscription();
    this._render();
  }

  set hass(value) {
    this._hass = value;
    this._ensureSubscription();
    this._render();
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._ensureSubscription();
    this._render();
  }

  disconnectedCallback() {
    this._clearSubscription();
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
    if (!this.isConnected || !this._hass?.connection || !this._config?.entity) {
      return;
    }

    const connection = this._hass.connection;
    const entity = this._config.entity;
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
    this._render();

    try {
      const unsubscribe = await connection.subscribeMessage(
        (event) => {
          if (token !== this._subscriptionToken) {
            return;
          }
          this._items = Array.isArray(event.items) ? event.items : [];
          this._loading = false;
          this._error = "";
          this._render();
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
        this._render();
      }
    }
  }

  get _entityState() {
    return this._hass?.states?.[this._config?.entity];
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
    return this._config?.show_completed
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
      ? new Date(
          Number(dateOnly[1]),
          Number(dateOnly[2]) - 1,
          Number(dateOnly[3]),
        )
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
    if (!item || !this._canAdd || this._adding) {
      return;
    }

    this._error = "";
    this._adding = true;
    this._render();
    try {
      await this._hass.callService("todo", "add_item", {
        entity_id: this._config.entity,
        item,
      });
      this._newItem = "";
    } catch (error) {
      this._error = error?.message || "The item could not be added.";
    } finally {
      this._adding = false;
      this._render();
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
    this._render();

    try {
      await this._hass.callService("todo", "update_item", {
        entity_id: this._config.entity,
        item: item.uid,
        status: nextStatus,
      });
    } catch (error) {
      this._error =
        error?.message || "The item status could not be changed.";
    } finally {
      const busy = new Set(this._busyItems);
      busy.delete(item.uid);
      this._busyItems = busy;
      this._render();
    }
  }

  _renderItem(item) {
    const completed = item.status === "completed";
    const description = this._hasText(item.description)
      ? item.description.trim()
      : "";
    const due = this._formatDue(item.due);

    const listItem = document.createElement("li");
    listItem.className = "item" + (completed ? " completed" : "");

    const label = document.createElement("label");
    label.className = "item-label";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = completed;
    checkbox.disabled =
      !this._canUpdate || !item.uid || this._busyItems.has(item.uid);
    checkbox.setAttribute(
      "aria-label",
      completed ? "Reopen item" : "Complete item",
    );
    checkbox.addEventListener("change", (event) => {
      this._toggleItem(item, event);
    });

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
        const descriptionElement = document.createElement("span");
        descriptionElement.textContent = description;
        details.append(descriptionElement);
      }
      if (due) {
        const dueElement = document.createElement("span");
        dueElement.textContent = due;
        details.append(dueElement);
      }
      body.append(details);
    }

    label.append(checkbox, body);
    listItem.append(label);
    return listItem;
  }

  _render() {
    if (!this.shadowRoot || !this._config) {
      return;
    }

    const style = document.createElement("style");
    style.textContent = CARD_STYLES;

    const card = document.createElement("ha-card");
    const header = document.createElement("div");
    header.className = "header";

    const title = document.createElement("span");
    title.textContent =
      this._entityState?.attributes?.friendly_name || this._config.entity;

    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(
      this._items.filter((item) => item.status !== "completed").length,
    );
    header.append(title, count);

    const content = document.createElement("div");
    content.className = "content";

    if (this._loading) {
      const loading = document.createElement("div");
      loading.className = "loading";
      loading.textContent = "Loading…";
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
      empty.textContent = this._config.show_completed
        ? "No items"
        : "No open items";
      content.append(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "items " + this._config.display;
      for (const item of this._visibleItems) {
        list.append(this._renderItem(item));
      }
      content.append(list);
    }

    if (this._canAdd) {
      const form = document.createElement("form");
      const input = document.createElement("input");
      input.type = "text";
      input.value = this._newItem;
      input.placeholder = "Add an item";
      input.setAttribute("aria-label", "New to-do item");

      const button = document.createElement("button");
      button.type = "submit";
      button.disabled = !this._newItem.trim() || this._adding;
      button.textContent = this._adding ? "Adding…" : "Add";

      input.addEventListener("input", (event) => {
        this._newItem = event.target.value;
        button.disabled = !this._newItem.trim() || this._adding;
      });
      form.addEventListener("submit", (event) => {
        this._addItem(event);
      });
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
