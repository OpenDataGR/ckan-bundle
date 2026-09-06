# CARTO basemaps — Configuration

Παραμετροποίηση των υποβάθρων (basemaps) χάρτη στο data.gov.gr, με έμφαση στο
CARTO (raster & vector) και στα σχετικά API keys (OD-814).

Οι χάρτες υπάρχουν σε **τρία σημεία**:

1. **Αναζήτηση συνόλων δεδομένων** (dataset spatial-search map) — ελέγχεται από
   properties με prefix `ckanext.data_gov_gr.map_search.*` (plugin
   `data_gov_gr`).
2. **Χωρική κάλυψη dataset** (spatial coverage) και
3. **Προεπισκοπήσεις πόρων** (resource views: Leaflet + OpenLayers) — ελέγχονται
   και τα δύο από properties με prefix `ckanext.spatial.common_map.*` (plugins
   `spatial` / `geoview`).

Για να εμφανίζεται **το ίδιο υπόβαθρο και στα τρία σημεία**, πρέπει να οριστούν
συμβατά και οι δύο ομάδες properties.

---

## 1. Πού συμπληρώνονται

Κάθε property μπορεί να οριστεί στο `ckan.ini`. **Δύο** από αυτά (τα API keys)
μπορούν επιπλέον να συμπληρωθούν από το **admin UI**:

`/ckan-admin/config` → ενότητα **Γενικά** → **«Χάρτες (CARTO basemaps)»**

Όταν ένα property συμπληρωθεί από το UI, η τιμή αποθηκεύεται στον πίνακα
`system_info` της βάσης και **υπερισχύει** της αντίστοιχης τιμής στο `ckan.ini`.

> **Ασφάλεια:** Τα CARTO API keys είναι **browser-visible** (basemap/browser
> keys — μεταφέρονται στον client για τα tile/style/glyph/sprite requests).
> Χρησιμοποιήστε key με τους κατάλληλους περιορισμούς domain — **ποτέ**
> server-side secret. Η τιμή αποθηκεύεται plaintext στο `system_info`, κάτι
> αποδεκτό ακριβώς επειδή το key είναι ούτως ή άλλως δημόσιο στον browser.

---

## 2. Χάρτης αναζήτησης — `ckanext.data_gov_gr.map_search.*`

| Property | Default | UI | Περιγραφή |
| --- | --- | :---: | --- |
| `ckanext.data_gov_gr.map_search.basemap` | `carto_light_all` | — | Basemap key. Τιμές: `carto_light_all`, `carto_light_nolabels`, `carto_voyager_nolabels`, `carto_vector`, `osm`, `esri_light_gray`, `eox_osm`. |
| `ckanext.data_gov_gr.map_search.carto_api_key` | `` (κενό) | ✅ | Προαιρετικό CARTO API key για τα CARTO layers της αναζήτησης. Browser-visible. |
| `ckanext.data_gov_gr.map_search.vector_style_url` | `/basemaps/carto-positron-el-no-maritime.json` | — | MapLibre Style JSON όταν `basemap = carto_vector`. |
| `ckanext.data_gov_gr.map_search.vector_fallback_basemap` | `carto_light_all` | — | Raster basemap key όταν το vector/WebGL δεν είναι διαθέσιμο. |

```ini
# Παράδειγμα (αναζήτηση με CARTO vector)
ckanext.data_gov_gr.map_search.basemap = carto_vector
ckanext.data_gov_gr.map_search.carto_api_key = YOUR_CARTO_KEY
ckanext.data_gov_gr.map_search.vector_style_url = /basemaps/carto-positron-el-no-maritime.json
ckanext.data_gov_gr.map_search.vector_fallback_basemap = carto_light_all
```

Το `map_search.carto_api_key` προστίθεται αυτόματα και URL-encoded στο tile URL,
μόνο όταν το επιλεγμένο basemap είναι CARTO. Αν είναι κενό, δεν προστίθεται
`key` query parameter.

---

## 3. Χωρική κάλυψη & προεπισκοπήσεις πόρων — `ckanext.spatial.common_map.*`

| Property | Default | UI | Περιγραφή |
| --- | --- | :---: | --- |
| `ckanext.spatial.common_map.type` | (upstream) | — | `custom` για raster XYZ profiles ή `carto_vector` για το CARTO vector profile. |
| `ckanext.spatial.common_map.custom_url` | (upstream) | — | URL template των XYZ tiles (`{z}/{x}/{y}`, και στο CARTO `{s}`/`{r}`). |
| `ckanext.spatial.common_map.attribution` | (upstream) | — | Attribution πάνω στον χάρτη· πρέπει να συμφωνεί με τους όρους του provider. |
| `ckanext.spatial.common_map.subdomains` | (upstream) | — | Προαιρετικό, όταν το URL περιέχει `{s}` (π.χ. `abcd` για CARTO). |
| `ckanext.spatial.common_map.tms` | (upstream) | — | Προαιρετικό boolean για TMS providers με ανεστραμμένο άξονα Y. Δεν χρειάζεται στα CARTO profiles. |
| `ckanext.spatial.common_map.carto_vector.style_url` | `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json` | — | MapLibre Style JSON όταν `type = carto_vector`. |
| `ckanext.spatial.common_map.carto_vector.api_key` | `` (κενό) | ✅ | Προαιρετικό CARTO vector API key (style, vector tile, glyph, sprite requests). Browser-visible. |
| `ckanext.spatial.common_map.carto_vector.fallback_url` | `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png` | — | Raster XYZ URL που ενεργοποιείται αυτόματα αν αποτύχει το vector layer. |

```ini
# Παράδειγμα (κοινός χάρτης με CARTO vector)
ckanext.spatial.common_map.type = carto_vector
ckanext.spatial.common_map.carto_vector.style_url = https://basemaps.cartocdn.com/gl/positron-gl-style/style.json
ckanext.spatial.common_map.carto_vector.api_key = YOUR_CARTO_KEY
ckanext.spatial.common_map.carto_vector.fallback_url = https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png
ckanext.spatial.common_map.subdomains = abcd
ckanext.spatial.common_map.attribution = &copy; OpenStreetMap contributors &copy; CARTO
```

> Όταν ο provider δεν χρησιμοποιεί `{s}`, η γραμμή `subdomains` πρέπει να
> αφαιρείται ή να σχολιάζεται.

---

## 4. Παράδειγμα: ενεργοποίηση CARTO vector και στα τρία σημεία

Πλήρες profile για ενεργό CARTO vector σε **spatial coverage + resource views +
αναζήτηση**, με το API key να συμπληρώνεται από το **admin UI** (γι' αυτό μένει
κενό στο ini):

```ini
# --- Κοινός χάρτης: spatial coverage + resource views (Leaflet & OpenLayers) ---
ckanext.spatial.common_map.type = carto_vector
ckanext.spatial.common_map.carto_vector.style_url = /basemaps/carto-positron-el-no-maritime.json
ckanext.spatial.common_map.carto_vector.fallback_url = https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png
ckanext.spatial.common_map.carto_vector.api_key =
# Raster fallback + attribution (όταν αποτύχει το vector layer)
ckanext.spatial.common_map.custom_url = https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png
ckanext.spatial.common_map.subdomains = abcd
ckanext.spatial.common_map.attribution = &copy; OpenStreetMap contributors &copy; CARTO

# --- Χάρτης αναζήτησης datasets ---
ckanext.data_gov_gr.map_search.basemap = carto_vector
ckanext.data_gov_gr.map_search.vector_style_url = /basemaps/carto-positron-el-no-maritime.json
ckanext.data_gov_gr.map_search.vector_fallback_basemap = carto_light_all
ckanext.data_gov_gr.map_search.carto_api_key =
```

Μετά το ini:

1. **Restart/reload** CKAN για να διαβαστεί το νέο config.
2. `/ckan-admin/config` → Γενικά → «Χάρτες (CARTO basemaps)» → συμπλήρωσε **και
   τα δύο** keys → Update. Οι τιμές του UI αποθηκεύονται στο `system_info` και
   **υπερισχύουν** των κενών τιμών του ini.
3. Επαλήθευση: φορτώνονται `.mvt` tiles + style/glyph/sprite requests με `?key=`.
   Σε αποτυχία vector/WebGL, ενεργοποιείται αυτόματα το raster fallback.

> **Προσοχή:** χρειάζονται **και τα δύο** keys. Αν λείπει το ένα, το αντίστοιχο
> σημείο (π.χ. μόνο η αναζήτηση, ή μόνο τα resource views) θα δείχνει το CARTO
> watermark «API KEY REQUIRED».

---

## 5. Μη-CARTO επιλογές & ιδιαιτερότητα EOX

Το `ckanext.data_gov_gr.map_search.basemap` δέχεται και **μη-CARTO** τιμές:
`osm`, `esri_light_gray`, `eox_osm`. Το URL/attribution αυτών είναι hardcoded
στο `public/map_search.js` (δεν παραμετροποιούνται από config).

### EOX (`eox_osm`) — προσοχή στο URL

Το EOX είναι **WMTS endpoint** και το tile URL έχει **διαφορετική δομή** από το
τυπικό XYZ των CARTO layers:

```text
https://tiles.maps.eox.at/wmts/1.0.0/osm_3857/default/g/{z}/{y}/{x}.jpg
```

Ιδιαιτερότητες σε σχέση με το CARTO (`.../{z}/{x}/{y}{r}.png`):

- **Σειρά `{z}/{y}/{x}`** — το `{y}` έρχεται **πριν** το `{x}` (όχι `{z}/{x}/{y}`).
- **Χωρίς `{s}`** — άρα το `subdomains` πρέπει να αφαιρείται/σχολιάζεται.
- **Χωρίς `?key=`** — το EOX δεν χρειάζεται API key.
- **Χωρίς `{r}`** (retina suffix).

Στην αναζήτηση (`map_search.basemap = eox_osm`) όλα αυτά τα χειρίζεται ήδη το JS.
Αν όμως θελήσετε EOX στους κοινούς χάρτες (spatial coverage / resource views)
μέσω του γενικού `common_map.custom_url`, πρέπει να τα ρυθμίσετε χειροκίνητα:

```ini
# EOX profile στους κοινούς χάρτες (raster)
ckanext.spatial.common_map.type = custom
ckanext.spatial.common_map.custom_url = https://tiles.maps.eox.at/wmts/1.0.0/osm_3857/default/g/{z}/{y}/{x}.jpg
ckanext.spatial.common_map.attribution = <a href="https://maps.eox.at">EOX::Maps</a> | Data &copy; OpenStreetMap contributors, Rendering &copy; EOX and MapServer
# ΠΡΟΣΟΧΗ: αφαιρέστε/σχολιάστε τα subdomains και carto_vector.api_key για το EOX
```

> Η σειρά `{z}/{y}/{x}` δεν είναι το τυπικό XYZ που υποθέτει το
> `common_map.custom_url` — είναι μη δοκιμασμένο μονοπάτι για τους κοινούς
> χάρτες και μπορεί να χρειαστεί προσοχή (π.χ. `tms`).

---

## 6. Properties με δυνατότητα συμπλήρωσης από το UI

Από όλα τα παραπάνω, **μόνο τα δύο API keys** είναι editable από το admin config
UI (τα υπόλοιπα ορίζονται αποκλειστικά στο `ckan.ini`):

| Property | UI location |
| --- | --- |
| `ckanext.data_gov_gr.map_search.carto_api_key` | Γενικά → Χάρτες (CARTO basemaps) → «CARTO API key — χάρτης αναζήτησης» |
| `ckanext.spatial.common_map.carto_vector.api_key` | Γενικά → Χάρτες (CARTO basemaps) → «CARTO API key — προεπισκόπηση πόρων & χωρική κάλυψη» |

Τεχνική σημείωση: το whitelist των editable properties γίνεται στο
`update_config_schema` (IConfigurer) του plugin `data_gov_gr`. Αν χρειαστεί να
γίνει editable κι άλλο property στο μέλλον, προστίθεται εκεί (`[ignore_missing,
unicode_safe]`) και ένα αντίστοιχο πεδίο στο `templates/admin/config.html`.

---

## 7. Σειρά προτεραιότητας

1. Τιμή από **admin UI** (`system_info`, DB) — αν υπάρχει, υπερισχύει.
2. Τιμή από **`ckan.ini`** — fallback.
3. **Default** του property (όπως δηλώνεται στο `declare_config_options`).

Αν ένα key οριστεί **και** στο `.ini` **και** από το UI, ισχύει η τιμή του UI.
Για αποφυγή σύγχυσης, προτιμήστε να το διαχειρίζεστε από ένα μόνο σημείο.
