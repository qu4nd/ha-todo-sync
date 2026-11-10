<div align="center">

<img src="custom_components/todo_sync/brand/icon.png" width="110" alt="To-do Sync icon">

# To-do Sync for Home Assistant

**Bidirectional real-time & periodic sync between any two Home Assistant `todo` entities.**  
*Purpose-built for **Bring!** ⇄ **Alexa Shopping List**, compatible with any To-do integration.*

[![GitHub Release](https://img.shields.io/github/v/release/qu4nd/ha-todo-sync?style=for-the-badge&logo=github)](https://github.com/qu4nd/ha-todo-sync/releases)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.11.1%2B-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-Local%20Push-success?style=for-the-badge)](https://www.home-assistant.io/blog/2016/02/12/classifying-the-internet-of-things/)
[![License](https://img.shields.io/github/license/qu4nd/ha-todo-sync?style=for-the-badge)](LICENSE)

[**🇬🇧 English**](#-features) • [**🇩🇪 Deutsch**](#-deutsch) • [**🐛 Report Issue**](https://github.com/qu4nd/ha-todo-sync/issues)

</div>

---

## ✨ Features

* 🔄 **True Two-Way Sync:** Adding, removing, checking, and unchecking items are synced in both directions using a persistent 3-way state snapshot.
* ⚖️ **Smart Quantity & Details Bridging:** Automatically translates between lists *with* item descriptions (e.g., **Bring!**) and lists *without* them (e.g., **Alexa**).
* ⚡ **Event-Driven + Periodic:** Triggers automatically on list changes (with a `3 s` debounce) alongside a configurable fallback interval (`1–1440 min`, default `5 min`).
* 🔘 **Ad-Hoc Sync Button:** Exposes a `Sync now` button entity per list pair for dashboards or custom automations.
* 🛡️ **Mass-Delete Safety Brake:** Protects your lists against faulty cloud reads. If $\ge 5$ open items (and $> 50\%$ of the list) vanish at once, the sync holds back for `6 minutes` to verify the deletion isn't a temporary API glitch.
* 🕓 **Clean History Handling:** Completed items (such as Bring!'s *"recently used"* history) are never created or deleted on the opposing list—only status changes of mutually existing items are synced.
* 🌐 **100% UI Configured:** Full Config Flow & Options Flow support with English and German translations. Zero YAML required.

---

## 🧠 How Smart Quantity Bridging Works

Lists like **Bring!** store quantities and notes in a dedicated `description` field, whereas **Alexa** only supports a single item title. **To-do Sync** bridges this seamlessly:

| Action | Bring! (`todo.zuhause`) | ⇄ | Alexa (`todo.alexa_shopping_list`) | How it's handled |
| :--- | :--- | :---: | :--- | :--- |
| **Add on Bring!** | **Item:** `Milch`<br>**Desc:** `3` | ➡️ | **Title:** `Milch 3` | Appends description to the title on lists without description support. |
| **Add on Alexa** | **Item:** `Käse`<br>**Desc:** `200 g` | ⬅️ | **Title:** `Käse 200 g` | Splits trailing numbers + optional units (`2`, `200 g`, `0,5l`) into the description field. |
| **Known Custom Text** | **Item:** `Test`<br>**Desc:** `bringdetails` | 🔄 | **Title:** `Test bringdetails` | Remembers exact known `Name Details` pairs from Bring! or the last snapshot—even without numbers. |

---

## 📦 Installation

> [!IMPORTANT]
> Requires **Home Assistant 2026.11.1** or newer and at least two existing `todo` entities.

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

## 🤖 Pro-Tip: Fast Sync Automation

Source integrations only update as fast as their polling intervals allow (Core **Bring!** polls every `90 s`, **Alexa Devices** every `5 min`). You can use the provided `button` entity alongside `homeassistant.update_entity` to force an immediate refresh when opening your shopping dashboard or leaving work:

```yaml
alias: "Shopping List: Force Refresh & Sync"
triggers:
  - trigger: state
    entity_id: person.daniel
    from: "home"
actions:
  - action: homeassistant.update_entity
    target:
      entity_id:
        - todo.zuhause
        - todo.alexa_shopping_list
  - delay: "00:00:02"
  - action: button.press
    target:
      entity_id: button.todo_zuhause_todo_alexa_shopping_list_sync_now

⚠️ Conflict Resolution & Limitations
 * Conflict Priority: Items are matched case-insensitively by name. If both lists modify the exact same item between syncs, the list that triggered the sync wins (on periodic timer runs, List A wins).
 * Renaming Items: Renaming an item's base name is processed as a deletion of the old name + creation of the new name.
 * Text-Only Details on Alexa: Adding a brand-new item on Alexa with text-only details (e.g., "Milch fettarm" without numbers) is read as the full item name.
 * Parentheses: Parentheses in item names are not treated specially.
<details>
<summary><b>🔍 Troubleshooting & Debug Logging (Click to expand)</b></summary>
At startup, the integration automatically waits until both todo entities are available. To inspect the item-by-item sync decisions, enable debug logging:
Option A: Temporary via UI
Go to Developer tools → Actions → call logger.set_level:
action: logger.set_level
data:
  custom_components.todo_sync: debug

Option B: Permanent in configuration.yaml
logger:
  logs:
    custom_components.todo_sync: debug

Check Settings → System → Logs and filter for todo_sync.
</details>
<div align="center">
<a id="-deutsch"></a>
🇩🇪 Deutsch
Bidirektionaler Echtzeit- & Intervall-Sync zweier To-do-Listen in Home Assistant.
Entwickelt für Bring! ⇄ Alexa-Einkaufsliste, nutzbar mit beliebigen todo-Entitäten.
</div>
✨ Funktionen
 * 🔄 Echter Zwei-Wege-Sync: Anlegen, Löschen, Abhaken und Wieder-Öffnen werden über einen persistenten 3-Wege-Snapshot in beide Richtungen synchronisiert.
 * ⚖️ Intelligente Mengen- & Detail-Brücke: Übersetzt automatisch zwischen Listen mit Beschreibungsfeld (z. B. Bring!) und Listen ohne Beschreibungsfeld (z. B. Alexa).
 * ⚡ Event-gesteuert + Intervall: Reagiert automatisch auf jede Listenänderung (3 s Entprellung) plus einstellbarem Zeitintervall (1–1440 Min, Standard 5 Min).
 * 🔘 „Sync now“-Button: Eigene Button-Entität pro Listenpaar für den sofortigen Abgleich per Dashboard oder Automation.
 * 🛡️ Sicherheitsbremse bei Massenlöschung: Verschwinden mindestens 5 offene Einträge (und mehr als die Hälfte) auf einmal aus einer Liste, wartet der Sync 6 Minuten und übernimmt das Löschen nur, wenn das Ergebnis unverändert bleibt (Schutz vor fehlerhaften Cloud-Reads).
 * 🕓 Sauberer Verlauf: Erledigte Einträge (wie „Zuletzt verwendet“ in Bring!) werden auf der Gegenseite nie neu angelegt oder gelöscht – nur Statuswechsel von Einträgen, die auf beiden Seiten existieren, werden abgeglichen.
🧠 Wie die Mengen- & Detail-Übersetzung funktioniert
Listen mit Beschreibungsfeld (Bring!) nutzen dieses nativ; andere (Alexa) erhalten das Format Name Details. Beim Einlesen und Schreiben passiert Folgendes:
| Aktion | Bring! (todo.zuhause) | ⇄ | Alexa (todo.alexa_shopping_list) | Verhalten |
|---|---|---|---|---|
| In Bring! angelegt | Name: Milch
Details: 3 | ➡️ | Titel: Milch 3 | Hängt die Beschreibung bei Listen ohne Beschreibungsfeld an den Titel an. |
| Über Alexa angelegt | Name: Käse
Details: 200 g | ⬅️ | Titel: Käse 200 g | Trennt Zahlen am Ende inkl. optionaler Einheit (2, 200 g, 0,5l) sauber ins Detailfeld ab. |
| Bekannter Freitext | Name: Test
Details: bringdetails | 🔄 | Titel: Test bringdetails | Erkennt bekannte Kombinationen aus Bring! oder dem letzten Sync exakt wieder – auch ohne Zahl. |
📦 Installation & Einrichtung
> [!IMPORTANT]
> Setzt Home Assistant 2026.11.1 (oder neuer) sowie zwei eingerichtete todo-Entitäten voraus.
> 
 * Marketplace / HACS: Unter Einstellungen → Marketplace (bzw. HACS vor 2026.11) → ⋮ → Benutzerdefinierte Repositories die URL https://github.com/qu4nd/ha-todo-sync als Kategorie Integration hinzufügen, To-do Sync installieren und Home Assistant neu starten. (Alternativ manuell nach <config>/custom_components/todo_sync kopieren).
 * Einrichten: Unter Einstellungen → Geräte & Dienste → Integration hinzufügen nach To-do Sync suchen.
 * Liste A und Liste B auswählen (müssen verschieden sein). Über Konfigurieren lässt sich optional das Sync-Intervall anpassen.
> [!TIP]
> Vor der Ersteinrichtung: Einmal alte, erledigte Einträge in beiden Listen aufräumen – das sorgt für einen sauberen Start-Snapshot.
> 
⚠️ Konflikte & Einschränkungen
 * Konfliktlösung: Einträge werden über den Namen (ohne Groß-/Kleinschreibung) zugeordnet. Haben beide Seiten denselben Eintrag gleichzeitig geändert, gewinnt die auslösende Liste (beim periodischen Lauf gewinnt Liste A).
 * Umbenennen: Wird als Löschen + Neuanlegen synchronisiert.
 * Freitext-Details auf Alexa: Details ohne Zahl bei einem komplett neuen Alexa-Eintrag (z. B. „Milch fettarm“) gelten als Teil des Namens.
 * Polling-Intervalle der Quellen: Änderungen kommen so schnell an, wie die Quell-Integrationen aktualisieren (Bring! im Core fragt alle 90 s ab, Alexa Devices alle 5 Min).
<details>
<summary><b>🔍 Fehlersuche & Debug-Logging (Ausklappen)</b></summary>
Beim Start wartet der Sync automatisch, bis beide Listen verfügbar sind. Für detaillierte Infos (alle Einträge beider Listen + Entscheidung pro Eintrag) das Debug-Logging unter Entwicklerwerkzeuge → Aktionen → logger.set_level aktivieren:
action: logger.set_level
data:
  custom_components.todo_sync: debug

Oder dauerhaft in der configuration.yaml eintragen und anschließend unter Einstellungen → System → Protokolle nach todo_sync filtern.
</details>
📄 License
Distributed under the MIT License.