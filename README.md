# To-do Sync for Home Assistant

<img src="custom_components/todo_sync/brand/icon.png" width="96" align="right" alt="To-do Sync icon">

Bidirectional sync of two Home Assistant to-do lists, built for **Bring!** ⇄ **Alexa Shopping List**, but usable with any two `todo` entities.

*(Deutsche Version: [unten](#deutsch))*

## Features

- Two-way sync of **adding, removing, checking and unchecking** items
- Item **details/quantity** are carried over: Bring! description `3` on "Milch" becomes "Milch 3" on lists without description support (e.g. Alexa), and back
- Triggered on every list change (3 s debounce) plus a **configurable periodic sync** (1–1440 min, default 5)
- **"Sync now" button** entity for ad hoc syncs
- Conflicts: if both sides changed the same item, the list that triggered the sync wins (list A on periodic runs)
- Completed items are treated as history: they are never created or deleted on the other side; only the status of items existing on both sides is synced
- Safety brake: if at least 5 open items (and more than half) vanish from a list at once, the sync waits 6 minutes and only applies it if the result is unchanged (protects against faulty reads)
- Fully UI-configured (config flow + options flow), English and German translations

## Requirements

- Home Assistant **2026.11.1** or newer
- Two `todo` entities, e.g. `todo.zuhause` (Bring!) and your Alexa list

## Installation

### Marketplace (recommended)
1. Settings → **Marketplace** → ⋮ → **Custom repositories** → add `https://github.com/qu4nd/ha-todo-sync` as category **Integration**.
2. Install **To-do Sync** and restart Home Assistant.

The same works with HACS on Home Assistant versions before 2026.11.

### Manual
Copy `custom_components/todo_sync` to `<config>/custom_components/todo_sync` and restart.

## Setup

1. Settings → Devices & services → **Add integration** → *To-do Sync*.
2. Pick **List A** and **List B** (they must differ).
3. Optional: **Configure** on the integration to set the sync interval.

Each list pair is its own entry; each gets a **Sync now** button.

## How it works

Items are matched by **name** (case-insensitive), since Bring! and Alexa use different IDs. The integration stores a snapshot of the last synced state and diffs both lists against it, so it can tell additions, deletions and changes apart. If both sides changed the same item, the list that triggered the sync wins; on periodic runs list A wins.

### Details / quantity
Lists that support item descriptions (Bring!) use them. Lists that don't (Alexa) get `Name Details`, e.g. `Käse 200 g`. When reading such a title:
1. If the whole title exactly matches a known title (a Bring! name, a `Name Details` combination, or one from the last sync), it is split accordingly (`Test bringdetails` → name `Test`, detail `bringdetails`).
2. Otherwise only a trailing number with optional unit is the detail (`Käse 200 g`, `Saure Sahne 2`, `Cola 0,5l`). Everything else is the name.

## Limitations

- Renaming an item is synced as delete + add.
- Details without a number on a *new* Alexa item (e.g. "Milch fettarm") are read as part of the name.
- Bring!'s "recently used" is exposed by its integration as completed items; behaviour depends on that integration.
- Parentheses in names are not specially handled.
- Changes only arrive as fast as the source integrations refresh: the core Bring! integration polls every 90 s, Alexa Devices every 5 min (per their source code).

## Troubleshooting

At startup the sync waits until both lists are available. For details enable debug logging, either permanently:
```yaml
logger:
  logs:
    custom_components.todo_sync: debug
```
or temporarily via Developer tools → Actions → `logger.set_level` with `custom_components.todo_sync: debug`. Then check Settings → System → Logs. The debug log lists all items of both lists and the decision per item. When first setting up, clean up old completed items in both lists.

## License
MIT

---

<a id="deutsch"></a>
# Deutsch

Bidirektionaler Sync zweier To-do-Listen in Home Assistant, gedacht für **Bring!** ⇄ **Alexa-Einkaufsliste**, nutzbar mit beliebigen `todo`-Entitäten.

## Funktionen

- Zwei-Wege-Sync von **Anlegen, Löschen, Abhaken, Wieder-Öffnen**
- **Details/Menge** werden übertragen: Bring!-Beschreibung `3` bei „Milch" wird auf Listen ohne Beschreibungsfeld (z. B. Alexa) zu „Milch 3" und zurück
- Auslösung bei jeder Listenänderung (3 s Verzögerung) plus **einstellbares Intervall** (1–1440 Min, Standard 5)
- **Button „Sync now"** für den sofortigen Abgleich
- Konflikte: Haben beide Seiten denselben Eintrag geändert, gewinnt die auslösende Liste (beim periodischen Lauf Liste A)
- Erledigte Einträge gelten als Verlauf: Sie werden auf der anderen Seite nie angelegt oder gelöscht; nur der Status von Einträgen, die auf beiden Seiten existieren, wird abgeglichen
- Sicherheitsbremse: Verschwinden mindestens 5 offene Einträge (und mehr als die Hälfte) auf einmal aus einer Liste, wartet der Sync 6 Minuten und übernimmt es nur bei unverändertem Ergebnis (Schutz vor fehlerhaften Reads)

## Voraussetzungen

- Home Assistant **2026.11.1** oder neuer
- Zwei `todo`-Entitäten, z. B. `todo.zuhause` (Bring!) und deine Alexa-Liste

## Installation

**Marketplace:** Einstellungen → **Marketplace** → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/qu4nd/ha-todo-sync` als Kategorie *Integration* hinzufügen, **To-do Sync** installieren, Home Assistant neu starten. Bei Home Assistant vor 2026.11 funktioniert das gleiche über HACS.

**Manuell:** `custom_components/todo_sync` nach `<config>/custom_components/todo_sync` kopieren und neu starten.

## Einrichtung

1. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → *To-do Sync*.
2. **Liste A** und **Liste B** wählen (müssen verschieden sein).
3. Optional: **Konfigurieren** für das Sync-Intervall.

## Funktionsweise

Einträge werden über den **Namen** zugeordnet (ohne Groß-/Kleinschreibung). Die Integration speichert den Stand des letzten Syncs und vergleicht beide Listen damit. Haben beide Seiten denselben Eintrag geändert, gewinnt die auslösende Liste; beim periodischen Lauf gewinnt Liste A.

Details: Listen mit Beschreibungsfeld (Bring!) nutzen es; andere (Alexa) bekommen `Name Details`, z. B. `Käse 200 g`. Beim Lesen gilt: Entspricht der ganze Titel genau einem bekannten Titel (Bring!-Name, Kombination `Name Details` oder Stand des letzten Syncs), wird er entsprechend getrennt (`Test bringdetails` → Name `Test`, Detail `bringdetails`). Sonst gilt nur eine Zahl am Ende (mit optionaler Einheit) als Detail (`Käse 200 g`, `Saure Sahne 2`); alles andere ist der Name.

## Einschränkungen

- Umbenennen wird als Löschen + Neuanlegen synchronisiert.
- Details ohne Zahl bei einem *neuen* Alexa-Eintrag („Milch fettarm") gelten als Teil des Namens.
- „Zuletzt verwendet" von Bring! erscheint je nach Bring!-Integration als erledigt.
- Klammern in Namen werden nicht gesondert behandelt.
- Änderungen kommen nur so schnell an, wie die Quell-Integrationen aktualisieren: Die Bring!-Integration im Core fragt alle 90 s ab, Alexa Devices alle 5 Min (laut Quellcode).

## Fehlersuche

Beim Start wartet der Sync, bis beide Listen verfügbar sind. Für Details Debug-Logging aktivieren, dauerhaft in der `configuration.yaml` (siehe oben) oder temporär unter Entwicklerwerkzeuge → Aktionen → `logger.set_level` mit `custom_components.todo_sync: debug`. Unter Einstellungen → System → Protokolle nach `todo_sync` suchen. Das Debug-Log zeigt alle Einträge beider Listen und die Entscheidung pro Eintrag. Vor der Ersteinrichtung alte erledigte Einträge in beiden Listen aufräumen.
