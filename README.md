<div align="center">

<img src="custom_components/todo_sync/brand/icon.png" width="110" alt="To-do Sync icon">

# To-do Sync for Home Assistant

**Event-driven and periodic bidirectional sync between two Home Assistant `todo` entities.**  
*Purpose-built for **Bring!** ⇄ **Alexa Shopping List**. Designed for Home Assistant To-do entities; compatibility depends on the capabilities and behavior of each provider.*

![Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fqu4nd%2Fha-todo-sync%2Fmain%2Fcustom_components%2Ftodo_sync%2Fmanifest.json&query=%24.version&label=version&color=blue&style=for-the-badge)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.11.0%2B-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-Local%20Push-success?style=for-the-badge)](https://www.home-assistant.io/blog/2016/02/12/classifying-the-internet-of-things/)
[![License](https://img.shields.io/github/license/qu4nd/ha-todo-sync?style=for-the-badge)](LICENSE)
[![Privacy](https://img.shields.io/badge/Privacy-Local%20Only-success?style=for-the-badge&logo=homeassistant&logoColor=white)](#-privacy--your-data-stays-yours)

[**🐛 Report Issue**](https://github.com/qu4nd/ha-todo-sync/issues)

</div>

---

## ✨ Features

* 🔄 **True Two-Way Sync:** Adding, removing, checking, and unchecking items are synced in both directions using a persistent 3-way state snapshot.
* ⚖️ **Smart Quantity & Details Bridging:** Automatically translates between lists *with* item descriptions (e.g., **Bring!**) and lists *without* them (e.g., **Alexa**). Items with the same name but different details remain separate.
* ⚡ **Event-Driven + Periodic:** Reacts to Home Assistant list-change events (with a `3 s` debounce) and runs a configurable periodic fallback (`1–1440 min`, default `5 min`). End-to-end sync speed also depends on how quickly each provider updates its Home Assistant entity.
* 🔘 **Ad-Hoc Sync Button:** Exposes a `Sync now` button entity per list pair for dashboards or custom automations.
* 📊 **Synchronization Status:** Exposes a diagnostic sensor per list pair with the current sync state, last successful sync, last error timestamp, and number of changed items.
* 🛡️ **Mass-Delete Safety Brake:** Protects your lists against faulty cloud reads. If 5 or more open items (and more than half of the list) vanish at once, the sync holds back for `6 minutes` to verify the deletion isn't a temporary API glitch.
* 🕓 **Clean History Handling:** Completed items (such as Bring!'s *"recently used"* history) are never created or deleted on the opposing list—only status changes of mutually existing items are synced.
* 🌐 **100% UI Configured:** Full Config Flow & Options Flow support with English and German translations. Zero YAML required.

---

## 🔒 Privacy – Your Data Stays Yours

**To-do Sync runs locally inside your Home Assistant instance.** It does not connect to Bring!, Amazon, or any other provider directly. It only accesses the two Home Assistant `todo` entities you select, using Home Assistant's built-in services.

- **No account access:** The integration never asks for or accesses your Bring! or Amazon credentials, account profiles, or login data.
- **No external data transfer:** It does not send your list contents, personal data, or usage information to the developer or to any external server.
- **Local storage only:** The synchronization snapshot is stored in Home Assistant's own local storage.

Your existing Home Assistant provider integrations may still communicate with their respective cloud services. To-do Sync itself does not see or handle their account credentials or communicate with those services.

**No cloud service. No tracking. No account access. Just local synchronization.**

---

## 🧠 How Smart Quantity Bridging Works

Lists like **Bring!** store quantities and notes in a dedicated `description` field, whereas **Alexa** only supports a single item title. **To-do Sync** bridges this seamlessly:

| Action | Bring! (`todo.zuhause`) | ⇄ | Alexa (`todo.alexa_shopping_list`) | How it's handled |
| :--- | :--- | :---: | :--- | :--- |
| **Add on Bring!** | **Item:** `Milch`<br>**Desc:** `3` | ➡️ | **Title:** `Milch 3` | Appends description to the title on lists without description support. |
| **Add on Alexa** | **Item:** `Käse`<br>**Desc:** `200 g` | ⬅️ | **Title:** `Käse 200 g` | Splits a trailing number and any following detail text (e.g. `2`, `200 g`, `0,5l`, `4 Käse`, `4 Stagioni`) into the description field. |
| **Known Custom Text** | **Item:** `Test`<br>**Desc:** `bringdetails` | 🔄 | **Title:** `Test bringdetails` | Remembers exact known `Name Details` pairs from Bring! or the last snapshot—even without numbers. |
| **Same Name, Different Details** | **Items:** `Pizza` + **Desc:** `4 Käse` and `4 Stagioni` | 🔄 | **Titles:** `Pizza 4 Käse` and `Pizza 4 Stagioni` | Uses the name + description pair as the identity, so neither entry overwrites the other. |

---

## 📦 Installation

> [!IMPORTANT]
> Requires **Home Assistant 2026.11.0** or newer (tested on **2026.11.1**) and at least two existing `todo` entities.

### Option 1: Marketplace / HACS (Recommended)

1. Go to **Settings** → **Marketplace** (or **HACS** on HA versions prior to 2026.11) → **⋮** (top right) → **Custom repositories**.
2. Add `https://github.com/qu4nd/ha-todo-sync` with category **Integration**.
3. Install **To-do Sync** and restart Home Assistant.

### Option 2: Manual Installation

Copy the `custom_components/todo_sync` folder into your Home Assistant `<config>/custom_components/todo_sync` directory and restart Home Assistant.

---

## ⚙️ Setup & Configuration

[![Open your Home Assistant instance and start setting up a new integration of a specific brand.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=todo_sync)

1. Go to **Settings** → **Devices & services** → **Add integration** → search for **To-do Sync**.
2. Select **List A** and **List B** (must be two different `todo` entities).
3. *(Optional)* Click **Configure** on the integration entry to adjust the periodic sync interval (`1–1440 min`).

> [!TIP]
> **First-Time Setup:** Clean up old completed items in both lists before setting up the integration for the cleanest initial snapshot.

---

## 📊 Synchronization Status

To-do Sync creates a diagnostic sensor for each configured list pair. The sensor is available alongside the integration's other entities and shows the latest synchronization state:

| State | Meaning |
| :--- | :--- |
| `idle` | No synchronization is currently running (for example, while a mass deletion is being verified). |
| `syncing` | A synchronization run is in progress. |
| `success` | The latest run completed successfully. |
| `error` | The latest run encountered a read or write error. |

The sensor also exposes these attributes:

- `last_success`: Timestamp of the last fully successful synchronization.
- `last_error`: Timestamp of the latest synchronization error.
- `synced_items`: Number of items successfully created, updated, or removed in the latest run.
- `last_error_type`: Technical error category (for example, `WriteError` or `TodoListReadError`).

Status history is stored locally and restored after a Home Assistant restart. A run that was interrupted by a restart is restored as `idle`, not as actively syncing. The sensor does not expose list entity IDs, item names, descriptions, or task contents.

---

## 🤖 Pro-Tip: Fast Sync Automation

Some source integrations refresh their Home Assistant entities periodically rather than immediately. To request a refresh before syncing, you can use the provided `button` entity alongside `homeassistant.update_entity` (where supported by the provider). The integration reacts to the resulting Home Assistant state changes; it cannot make a provider fetch external changes faster than that provider allows.

Replace the placeholder entity IDs below with the actual entity IDs from your Home Assistant instance:

```yaml
alias: 'Shopping List: Force Refresh & Sync'
triggers: []
actions:
  - action: homeassistant.update_entity
    data:
      entity_id:
        - todo.YOUR_FIRST_LIST
        - todo.YOUR_SECOND_LIST
  - delay: '00:00:02'
  - action: button.press
    target:
      entity_id: button.YOUR_SYNC_NOW_BUTTON
```

---

## ⚠️ Conflict Resolution & Limitations

* **Conflict Priority:** Items are matched case-insensitively by the combination of name and description. Items with the same name but different descriptions remain independent. If both lists modify the exact same item between syncs, the list that triggered the sync wins (on periodic timer runs, **List A** wins).
* **Renaming Items:** Changing an item's name or description is processed as a deletion of the old name/details pair + creation of the new pair.
* **Exact Duplicates:** Two entries with exactly the same name and description are treated as one logical item; the Home Assistant sync model does not currently preserve duplicate multiplicity.
* **Text-Only Details on Alexa:** Adding a *brand-new* item on Alexa with text-only details (e.g., `"Milch fettarm"` without numbers) is read as the full item name.
* **Parentheses:** Parentheses in item names are not treated specially.

---

## 🔍 Troubleshooting & Debug Logging

At startup, the integration automatically waits until both `todo` entities are available. To inspect the item-by-item sync decisions, enable debug logging:

**Option A: Temporary via UI**  
Go to **Developer tools** → **Actions** → call `logger.set_level`:

```yaml
action: logger.set_level
data:
  custom_components.todo_sync: debug
```

**Option B: Permanent in `configuration.yaml`**

```yaml
logger:
  logs:
    custom_components.todo_sync: debug
```

Check **Settings** → **System** → **Logs** and filter for `todo_sync`.

---

## 📄 License

Distributed under the **MIT License**.
