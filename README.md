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
* 🛡️ **Empty-List Safety Brake:** Protects your lists against faulty cloud reads. If a list appears completely empty while the snapshot still contains open items, the sync holds back for `6 minutes` to verify the empty result isn't a temporary API glitch. Partial deletions are synchronized immediately.
* 📝 **Open-List Synchronization:** Only currently open items are read and synchronized. Completing an item or deleting it both remove it from the active list, so either action is mirrored on the other list. Duplicate cleanup is the deliberate exception: it completes only extra occurrences while retaining one open occurrence, so the logical item remains active. Provider completion history is outside the synchronization scope.
* 🧹 **Optional Duplicate Cleanup:** Can complete extra identical open entries on each list before syncing, while keeping one open occurrence. Disabled by default.
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

## 🧠 How Item Names & Details Are Bridged

Lists like **Bring!** store the item name and its details separately, whereas **Alexa** only supports a single item title. To make both sides comparable, **To-do Sync** applies one deterministic parsing rule to titles from providers without description support:

**The first word is always the item name; everything after the first space is the detail.** This rule is intentional and does not try to guess whether the remaining text is a quantity, a note, or part of a product name.

| Action | Bring! (`todo.zuhause`) | ⇄ | Alexa (`todo.alexa_shopping_list`) | How it's handled |
| :--- | :--- | :---: | :--- | :--- |
| **Add on Bring!** | **Item:** `Milch`<br>**Desc:** `3` | ➡️ | **Title:** `Milch 3` | Appends description to the title on lists without description support. |
| **Add on Alexa** | **Item:** `Käse`<br>**Desc:** `200 g` | ⬅️ | **Title:** `Käse 200 g` | Splits after the first word: `Käse` is the name and `200 g` the detail. |
| **Text Details** | **Item:** `gelbe`<br>**Desc:** `Tomaten` | 🔄 | **Title:** `gelbe Tomaten` | The first word remains the identity even when the detail is ordinary text rather than a quantity. |
| **Same Name, Different Details** | **Items:** `Pizza` + **Desc:** `4 Käse` and `4 Stagioni` | 🔄 | **Titles:** `Pizza 4 Käse` and `Pizza 4 Stagioni` | Both titles become the same name (`Pizza`) with different details, so neither entry overwrites the other. |
| **Numbers & Product Names** | **Item:** `Formel`<br>**Desc:** `1` | 🔄 | **Title:** `Formel 1` | Numbers are treated like any other detail; no special quantity or product-name detection is attempted. |

---

## 📦 Installation

> [!IMPORTANT]
> Tested with **Home Assistant 2026.11.0** and newer (probably working on older versions though). Requires at least two existing `todo` entities.

### Option 1: Marketplace / HACS (Recommended)

1. Go to **Settings** → **Marketplace** (or **HACS** on HA versions prior to 2026.11) → **⋮** (top right) → **Custom repositories**.
2. Add `https://github.com/qu4nd/ha-todo-sync` with category **Integration**.
3. Install **To-do Sync** and restart Home Assistant.

### Optional beta releases

Stable releases are installed by default. If you want to help test upcoming changes, enable pre-release versions for this repository in HACS. Beta releases are published deliberately for selected changes (for example, `0.1.31b1` and `0.1.31b2`); they are not generated automatically after every merge. Users who do not opt in continue receiving stable releases only. A stable release following a beta series uses the same target version without the beta suffix (for example, `0.1.31`).

### Option 2: Manual Installation

Copy the `custom_components/todo_sync` folder into your Home Assistant `<config>/custom_components/todo_sync` directory and restart Home Assistant.

---

## ⚙️ Setup & Configuration

[![Open your Home Assistant instance and start setting up a new integration of a specific brand.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=todo_sync)

1. Go to **Settings** → **Devices & services** → **Add integration** → search for **To-do Sync**.
2. Select **List A** and **List B** (must be two different `todo` entities).
3. *(Optional)* Click **Configure** on the integration entry to adjust the periodic sync interval (`1–1440 min`) and enable duplicate cleanup. This option is disabled by default. When enabled, To-do Sync checks the currently open items on both lists before each synchronization and marks additional open occurrences of the same logical item as completed, keeping one open occurrence per list. Matching uses the normalized item name and description (case-insensitive; surrounding whitespace is ignored). The cleanup is verified before the normal sync continues; if it cannot be completed or verified safely, that sync run is stopped. Previously completed provider history is not fetched or modified.

---

## 📊 Synchronization Status

To-do Sync creates a diagnostic sensor for each configured list pair. The sensor is available alongside the integration's other entities and shows the latest synchronization state:

| State | Meaning |
| :--- | :--- |
| `idle` | No synchronization is currently running and no safety hold is active. |
| `syncing` | A synchronization run is in progress. |
| `waiting` | One of the configured to-do entities is missing or currently `unknown`/`unavailable`; synchronization is paused until it becomes available. |
| `held_back` | A completely empty list is being verified against the last snapshot; no list changes are applied during this hold. |
| `success` | The latest run completed successfully. |
| `error` | The latest run encountered a read failure, write failure, invalid provider item data, or another unexpected error. |

Automations that evaluate the sensor state should account for the additional `waiting` and `held_back` states. The sensor also exposes these attributes:

- `last_success`: Timestamp of the last fully successful synchronization.
- `last_error`: Timestamp of the latest synchronization error.
- `synced_items`: Number of items successfully created, updated, or removed in the latest run.
- `last_error_type`: Technical error category (for example, `WriteError`, `TodoListReadError`, or `InvalidItemIdentityError`).
- `waiting_entity`: Entity ID of the to-do list that is preventing synchronization while the sensor is in `waiting`; `None` otherwise.
- `waiting_state`: Observed state of that entity (`missing`, `unknown`, or `unavailable`); `None` otherwise.

Status history is stored locally and restored after a Home Assistant restart. A run that was interrupted by a restart is restored as `idle`, not as actively syncing. An active `held_back` state is restored; because the confirmation timer is in memory, the verification window starts again when the lists are checked after restart. The safety brake applies only when a list is completely empty while open items remain in the snapshot; partial deletions are not delayed. A held-back run does not update `last_success`. The sensor exposes the affected entity ID and its observed state only while synchronization is in the `waiting` state, through `waiting_entity` and `waiting_state`. It does not expose item names, descriptions, or task contents.

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

## ⚠️ Synchronization Details & Limitations

### Provider write delays

Some providers update their Home Assistant entity state asynchronously after a service call. To avoid interpreting an old provider read as a new change, To-do Sync keeps a local pending-write expectation for the destination item for up to **10 minutes**. While the destination still shows the exact pre-write value and the source still matches the expected new value, that stale destination read is ignored. The expectation is cleared when the destination reflects the write, when a different value indicates a genuine edit/conflict, or when the time window expires. Failed writes never create an expectation. Pending expectations are stored locally alongside the synchronization snapshot and restored after a restart.

Snapshots are written only when their persisted data changes. Transient `syncing` sensor updates remain in memory; final status changes are persisted with a short delayed save to coalesce writes. A snapshot is flushed during unload after any in-flight sync has finished.

* **Open-List State:** Only open items returned by Home Assistant's `todo.get_items` service are part of the synchronization model. The last common snapshot lets the integration distinguish a newly added item from an item removed on one side. Completing and deleting an item have the same effect here: the item is no longer open and is removed from the other active list as well. Completed-item history is not synchronized.
* **Renaming Items:** Changing an item's name or description is processed as a deletion of the old name/details pair + creation of the new pair.
* **Exact Duplicates:** Two entries with exactly the same name and description are treated as one logical item; the Home Assistant sync model does not currently preserve duplicate multiplicity.
* **Ambiguous Text on Alexa:** Lists without description support always split a title at the first space: the first word becomes the item name and everything after it becomes the description. For example, `"Milch fettarm"` is interpreted as name `Milch` and description `fettarm`. The integration cannot distinguish a multi-word product name from a name followed by details; this rule applies to new items as well.
* **Parentheses:** Parentheses in item names are not treated specially.

---

## 🔍 Troubleshooting & Debug Logging

If either configured `todo` entity is missing, `unknown`, or `unavailable`, the sensor enters `waiting`, identifies the affected entity through its diagnostic attributes, and pauses synchronization. The integration retries every `30 seconds` and resumes automatically when both entities are available again. A warning is logged only when the unavailable condition or affected entity changes, avoiding repeated identical warnings. At startup, the integration uses the same waiting behavior until both `todo` entities are available. Debug logging provides privacy-safe operational context through stable `sync_event` and `category` fields, including run start counts, copy/delete direction, pending-write outcomes, and retry timing. Error categories distinguish `read_failure`, `write_failure`, `invalid_identity`, and unexpected failures; the empty-list safety brake is logged separately as `empty_list_guard`. Invalid provider records with missing, empty, or malformed identity data fail the run safely instead of being interpreted as deletions. Error logs include only generic reasons and exception class names, never exception messages or tracebacks, because providers may include item titles or service data in them. List item names, descriptions, and task contents are never included in log messages. While the sensor is in `waiting`, the affected entity ID is exposed through `waiting_entity` and `waiting_state`; warning logs identify the affected list as A or B without printing its entity ID. The synchronization snapshot is stored locally in Home Assistant. To inspect this diagnostic information, enable debug logging:

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

Check **Settings** → **System** → **Logs** and filter for `todo_sync`. Debug output is intended to explain synchronization flow and aggregate outcomes, not to expose individual list entries.

---

## 📄 License

Distributed under the **MIT License**.
