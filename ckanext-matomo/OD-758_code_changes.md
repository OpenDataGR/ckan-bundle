# OD-758 — Υλοποίηση Banner Αποδοχής Cookies

## Επισκόπηση

Το feature υλοποιήθηκε σε **δύο repositories** με ταυτόχρονα commits (2026-04-25):

| Repo | Commit | Ρόλος |
|---|---|---|
| `ckanext-matomo` | `174288b` | Matomo JS integration (backend + tracking script) |
| `ckanext-data-gov-gr` | `6bc00c7` | UI (banner, admin config, CSS, i18n, τεκμηρίωση) |

---

## 1. ckanext-matomo — Αλλαγές κώδικα

### 1.1 `ckanext/matomo/helpers.py`

**Τι άλλαξε:** Δύο προσθήκες.

**α) Νέο πεδίο στο `matomo_snippet()`:**

```python
def matomo_snippet():
    data = {
        "matomo_domain": ...,
        "matomo_script_domain": ...,
        "matomo_site_id": ...,
        "matomo_tracker_filename": ...,
        "matomo_script_filename": ...,
        "consent_mode": config.get('ckanext.matomo.consent_mode', 'disabled'),  # ΝΕΟ
    }
    return render_snippet("matomo/snippets/matomo.html", data)
```

- Διαβάζει το config setting `ckanext.matomo.consent_mode` (default: `'disabled'`)
- Το περνάει στο Jinja2 template ως μεταβλητή `consent_mode`
- Έτσι το template μπορεί να αποφασίσει αν θα ενεργοποιήσει consent στο Matomo JS

**β) Νέα helper function:**

```python
def matomo_consent_mode():
    return config.get('ckanext.matomo.consent_mode', 'disabled')
```

- Standalone helper που επιστρέφει μόνο την τιμή του consent mode
- Χρησιμοποιείται από το banner template στο ckanext-data-gov-gr μέσω `h.matomo_consent_mode()`

---

### 1.2 `ckanext/matomo/plugin/__init__.py`

**Τι άλλαξε:** Μία γραμμή στο `get_helpers()`.

```python
def get_helpers(self):
    return {
        'matomo_snippet': helpers.matomo_snippet,
        'get_years': helpers.get_years,
        'matomo_show_download_graph': helpers.show_download_graph,
        'get_current_date': helpers.get_current_date,
        'get_downloads_in_date_range_for_resource': helpers.get_downloads_in_date_range_for_resource,
        'matomo_consent_mode': helpers.matomo_consent_mode  # ΝΕΟ
    }
```

- Καταχωρεί τη `matomo_consent_mode` ως CKAN template helper
- Μετά από αυτό, οποιοδήποτε Jinja2 template μπορεί να καλέσει `h.matomo_consent_mode()`

---

### 1.3 `ckanext/matomo/templates/matomo/snippets/matomo.html`

**Τι άλλαξε:** Προστέθηκε conditional block **πριν** το `trackPageView`.

```html
<script type="text/javascript">
  var _paq = window._paq = window._paq || [];

  {% if consent_mode == 'tracking_consent' %}
  _paq.push(['requireConsent']);
  {% elif consent_mode == 'cookie_consent' %}
  _paq.push(['requireCookieConsent']);
  {% endif %}

  _paq.push(['trackPageView']);       <!-- αυτό υπήρχε ήδη -->
  _paq.push(['enableLinkTracking']);  <!-- αυτό υπήρχε ήδη -->
```

**Τι κάνει κάθε εντολή:**

| Εντολή Matomo | Συμπεριφορά |
|---|---|
| `requireConsent` | Μπλοκάρει **τα πάντα** (requests + cookies) μέχρι να κληθεί `rememberConsentGiven()` |
| `requireCookieConsent` | Επιτρέπει ανώνυμα tracking requests αλλά **μπλοκάρει cookies** μέχρι `rememberCookieConsentGiven()` |
| *(τίποτα, mode=disabled)* | Τρέχουσα συμπεριφορά — tracking χωρίς περιορισμούς |

> **Σημαντικό:** Αυτές οι εντολές πρέπει να εκτελούνται **πριν** το `trackPageView`, αλλιώς το πρώτο pageview θα καταγραφεί χωρίς consent. Η σειρά στο template είναι σωστή.

---

## 2. ckanext-data-gov-gr — Αλλαγές κώδικα

### 2.1 `ckanext/data_gov_gr/plugin.py`

**Τι άλλαξε:** Τρεις προσθήκες.

**α) Admin config form schema (validation):**

```python
schema.update({
    ...
    'ckanext.matomo.consent_mode': [ignore_missing, unicode_safe],  # ΝΕΟ
})
```

- Ορίζει validation rules: η τιμή είναι προαιρετική (`ignore_missing`) και αποθηκεύεται ως unicode string
- Χωρίς αυτό, το CKAN admin form θα αγνοούσε το πεδίο κατά το save

**β) Config declaration:**

```python
declaration.declare(key.ckanext.matomo.consent_mode, "disabled").set_description(
    "Matomo consent mode: 'disabled', 'tracking_consent', 'cookie_consent', or 'opt_out'."
)
```

- Δηλώνει το config key στο CKAN config declaration system
- Default value: `"disabled"`
- Αυτό επιτρέπει στο CKAN να γνωρίζει ότι αυτό το setting υπάρχει, τι τιμή έχει by default, και τι κάνει

---

### 2.2 `ckanext/data_gov_gr/templates/admin/config.html`

**Τι άλλαξε:** Νέο section στο admin config page.

```html
<hr>
<h4>{{ _('Matomo — Συγκατάθεση Cookies') }}</h4>

{% set consent_mode_options = [
  {'value': 'disabled',          'text': _('Απενεργοποιημένο (χωρίς banner)')},
  {'value': 'tracking_consent',  'text': _('Πλήρης συγκατάθεση (tracking consent)')},
  {'value': 'cookie_consent',    'text': _('Συγκατάθεση cookies μόνο (cookie consent)')},
  {'value': 'opt_out',           'text': _('Opt-out (ο χρήστης μπορεί να εξαιρεθεί)')}
] %}

{{ form.select(
  'ckanext.matomo.consent_mode',
  ...
  selected=data.get('ckanext.matomo.consent_mode', 'disabled'),
) }}
```

- Dropdown (`<select>`) με 4 επιλογές
- Η επιλεγμένη τιμή αποθηκεύεται στο CKAN config DB όταν ο admin κάνει save
- Κάθε label περνάει από `_()` για i18n

---

### 2.3 `ckanext/data_gov_gr/templates/footer.html`

**Τι άλλαξε:** Μία γραμμή include.

```html
{% include 'snippets/cookie_consent_banner.html' %}
```

- Εισάγει το banner snippet στο footer κάθε σελίδας
- Τοποθετείται μετά τα υπόλοιπα footer scripts (π.χ. Botaki webchat)

---

### 2.4 `ckanext/data_gov_gr/templates/snippets/cookie_consent_banner.html` (ΝΕΟ)

Αυτό είναι το κύριο αρχείο του feature — 160 γραμμές, HTML + JavaScript.

#### Δομή HTML

```html
{% set consent_mode = h.matomo_consent_mode() %}
{% if consent_mode and consent_mode != 'disabled' %}

  <div id="cookie-consent-banner" class="cookie-consent-banner"
       data-consent-mode="{{ consent_mode }}" style="display: none;">

    <!-- Κείμενο: διαφορετικό για opt_out vs consent modes -->
    {% if consent_mode == 'opt_out' %}
      <p>...μπορείτε να εξαιρεθείτε...</p>
    {% else %}
      <p>...επιλέξτε αν αποδέχεστε ή απορρίπτετε...</p>
    {% endif %}

    <!-- Κουμπιά: διαφορετικά ανά mode -->
    {% if consent_mode in ('tracking_consent', 'cookie_consent') %}
      <button id="cookie-consent-accept">Accept</button>
      <button id="cookie-consent-decline">Decline</button>
    {% elif consent_mode == 'opt_out' %}
      <button id="cookie-consent-optout">Opt Out of Tracking</button>
      <button id="cookie-consent-close">×</button>
    {% endif %}

  </div>
```

- Το banner αρχικά είναι `display: none` — εμφανίζεται μόνο μέσω JS αν χρειάζεται
- Η `data-consent-mode` attribute περνάει τη λειτουργία στο JavaScript
- Αν `consent_mode == 'disabled'`, δεν renderάρεται τίποτα

#### JavaScript — tracking_consent / cookie_consent

```javascript
var consentCookie = (mode === 'tracking_consent') ? 'mtm_consent' : 'mtm_cookie_consent';

// Αν υπάρχει ήδη consent ή decline cookie → μην δείξεις banner
if (hasCookie(consentCookie) || hasCookie('mtm_consent_removed')) {
  return;
}

banner.style.display = 'flex';  // Δείξε το banner

acceptBtn.addEventListener('click', function () {
  if (mode === 'tracking_consent') {
    _paq.push(['rememberConsentGiven']);   // → θέτει cookie mtm_consent
  } else {
    _paq.push(['rememberCookieConsentGiven']);  // → θέτει cookie mtm_cookie_consent
  }
  banner.style.display = 'none';
});

declineBtn.addEventListener('click', function () {
  if (mode === 'tracking_consent') {
    _paq.push(['forgetConsentGiven']);
  } else {
    _paq.push(['forgetCookieConsentGiven']);
  }
  setCookie('mtm_consent_removed', '1', 365);  // Custom cookie για να θυμάται το decline
  banner.style.display = 'none';
});
```

**Ροή αποφάσεων:**

```
Σελίδα φορτώνει
  → Υπάρχει cookie mtm_consent / mtm_cookie_consent; → ΝΑΙ → Δεν εμφανίζεται banner
  → Υπάρχει cookie mtm_consent_removed;              → ΝΑΙ → Δεν εμφανίζεται banner
  → Κανένα cookie                                     → Εμφανίζεται banner
    → Accept  → Matomo αποθηκεύει consent cookie, ξεκινάει tracking
    → Decline → Θέτει mtm_consent_removed, tracking παραμένει blocked
```

#### JavaScript — opt_out

```javascript
// Χρησιμοποιεί sessionStorage αντί cookie — banner ξαναεμφανίζεται σε νέο session
if (sessionStorage.getItem('cookieConsentBannerDismissed') === '1') {
  return;
}

banner.style.display = 'flex';

optoutBtn.addEventListener('click', function () {
  _paq.push([function () {
    if (this.isUserOptedOut()) {
      _paq.push(['forgetUserOptOut']);    // Επαναφορά tracking
    } else {
      _paq.push(['optUserOut']);          // Εξαίρεση από tracking
    }
  }]);
});

closeBtn.addEventListener('click', function () {
  banner.style.display = 'none';
  sessionStorage.setItem('cookieConsentBannerDismissed', '1');
});
```

**Διαφορά opt_out:** Εδώ ο χρήστης κάνει tracking by default — μπορεί ενεργά να εξαιρεθεί. Το banner κλείνει με × και δεν ξαναεμφανίζεται στο ίδιο session (sessionStorage).

---

### 2.5 `ckanext/data_gov_gr/public/data_gov_gr.css`

Νέα CSS class `.cookie-consent-banner`:

```css
.cookie-consent-banner {
  position: fixed;
  bottom: 0;
  left: 0; right: 0;
  z-index: 1040;
  background-color: #ffffff;
  border-top: 3px solid var(--color-primary, #003476);
  box-shadow: 0 -2px 10px rgba(0,0,0,0.15);
  display: none;           /* εμφανίζεται μόνο μέσω JS */
}
```

- Fixed-bottom banner πάνω από όλο το content (`z-index: 1040`)
- Responsive: σε mobile (`max-width: 576px`) τα στοιχεία γίνονται column layout
- Κουμπιά: primary color για Accept, ουδέτερο γκρι για Decline

---

### 2.6 `i18n/el/LC_MESSAGES/ckanext-data_gov_gr.po`

Νέα μεταφρασμένα strings:

| msgid (EN) | msgstr (EL) |
|---|---|
| `Cookie consent` | `Συγκατάθεση cookies` |
| `Accept` | `Αποδοχή` |
| `Decline` | `Απόρριψη` |
| `Opt Out of Tracking` | `Εξαίρεση από την παρακολούθηση` |
| `Resume Tracking` | `Επαναφορά παρακολούθησης` |

Τα admin-only strings (dropdown labels, help texts) δεν μεταφράστηκαν (`msgstr ""`) — εμφανίζονται στα Ελληνικά ως msgid γιατί ο admin UI είναι ήδη στα Ελληνικά.

---

### 2.7 `README.md`

Αντικατέστησε το placeholder:

```markdown
-**TODO:** Document any optional config settings here. For example:
-    ckanext.data_gov_gr.some_setting = some_default_value
```

Με πλήρη τεκμηρίωση:
- Config setting `ckanext.matomo.consent_mode` με τις 4 τιμές
- Πίνακας σύγκρισης GDPR compliance ανά mode
- Πίνακας analytics impact (τι χάνεις ανά mode)
- Πίνακας privacy gains (τι κερδίζεις ανά mode)
- Σύσταση: `cookie_consent` για δημόσια πύλη ΕΕ

> Το README **δεν επηρεάζει τη λειτουργία** — είναι τεκμηρίωση για developers/admins. Δεν εκτελείται, δεν διαβάζεται από τον κώδικα. Αλλά είναι κρίσιμο γιατί εξηγεί τις **συνέπειες** κάθε config τιμής σε business terms (GDPR, analytics loss).

---

## Αρχιτεκτονικό Διάγραμμα

```
┌─────────────────────────────────────────────────────────────┐
│  ckan.ini / Admin UI                                        │
│  ckanext.matomo.consent_mode = cookie_consent                │
└─────────┬───────────────────────────────────┬───────────────┘
          │                                   │
          ▼                                   ▼
┌─────────────────────┐         ┌─────────────────────────────┐
│  ckanext-matomo      │         │  ckanext-data-gov-gr         │
│                     │         │                             │
│  helpers.py         │         │  plugin.py                  │
│  ├ matomo_snippet() │         │  ├ config schema            │
│  │  → consent_mode  │         │  └ config declaration       │
│  └ matomo_consent   │         │                             │
│    _mode()          │◄────────│  cookie_consent_banner.html │
│                     │  calls  │  ├ h.matomo_consent_mode()  │
│  matomo.html        │         │  ├ banner HTML              │
│  ├ requireConsent   │         │  └ consent JS logic         │
│  └ requireCookie    │         │                             │
│    Consent          │         │  admin/config.html          │
└─────────────────────┘         │  └ dropdown selector        │
                                │                             │
                                │  footer.html                │
                                │  └ {% include banner %}     │
                                │                             │
                                │  data_gov_gr.css            │
                                │  └ banner styles            │
                                └─────────────────────────────┘
```

---

## Ροή Εκτέλεσης (Runtime)

1. Admin επιλέγει `cookie_consent` στο `/ckan-admin/config` → αποθηκεύεται στο CKAN config DB
2. Χρήστης ανοίγει σελίδα →
   - `matomo.html` εκτελείται: `_paq.push(['requireCookieConsent'])` → Matomo μπλοκάρει cookies
   - `_paq.push(['trackPageView'])` → Matomo στέλνει ανώνυμο request (χωρίς cookies)
   - `footer.html` φορτώνει → `cookie_consent_banner.html` renderάρεται
   - JS ελέγχει: υπάρχει `mtm_cookie_consent` cookie; Όχι → εμφάνιση banner
3. Χρήστης πατάει **Accept** →
   - `_paq.push(['rememberCookieConsentGiven'])` → Matomo θέτει cookie `mtm_cookie_consent`
   - Από εδώ και πέρα: πλήρες tracking με cookies (visitor identification)
   - Banner δεν ξαναεμφανίζεται (cookie υπάρχει)
4. Χρήστης πατάει **Decline** →
   - `_paq.push(['forgetCookieConsentGiven'])` → Matomo δεν θέτει cookies
   - Custom cookie `mtm_consent_removed` αποθηκεύεται (365 μέρες)
   - Banner δεν ξαναεμφανίζεται (decline cookie υπάρχει)
   - Tracking συνεχίζεται ανώνυμα (requests χωρίς cookies)

---

## 3. Επαλήθευση βάσει επίσημης τεκμηρίωσης Matomo

Πηγές:
- [Tracking Consent Guide](https://developer.matomo.org/guides/tracking-consent)
- [JavaScript Tracking Guide](https://developer.matomo.org/guides/tracking-javascript-guide)
- [JavaScript Tracker API Reference](https://developer.matomo.org/api-reference/tracking-javascript)

---

### 3.1 Mode: `disabled` — Χωρίς banner

**Τι κάνει ο κώδικας:** Δεν εισάγει καμία `requireConsent` / `requireCookieConsent` εντολή. Δεν renderάρει banner.

**Τι λέει η τεκμηρίωση Matomo:**
> "By default the Matomo tracker assumes consent to tracking."
> "By default the Matomo tracker assumes consent to using cookies."

**Επαλήθευση: ΣΩΣΤΟ.** Η default συμπεριφορά του Matomo είναι πλήρες tracking με cookies χωρίς καμία παρέμβαση. Η υλοποίηση δεν αλλάζει τίποτα — ακριβώς αυτό που πρέπει.

**Τι καταγράφεται:**

| Μετρική | Καταγράφεται; |
|---|---|
| Pageviews | Ναι — κάθε `trackPageView` στέλνει request |
| Cookies (visitor ID, session) | Ναι — first-party cookies ενεργά |
| Unique / Returning visitors | Ναι — μέσω cookies |
| Session duration, bounce rate | Ναι — μέσω cookies |
| Downloads, events, outlinks | Ναι — `enableLinkTracking` ενεργό |
| Referrers, campaigns | Ναι — στέλνονται στο request |

---

### 3.2 Mode: `tracking_consent` — Πλήρης συγκατάθεση

**Τι κάνει ο κώδικας:**

1. `matomo.html` → `_paq.push(['requireConsent'])` **πριν** το `trackPageView`
2. Banner εμφανίζεται αν δεν υπάρχει cookie `mtm_consent` ή `mtm_consent_removed`
3. Accept → `_paq.push(['rememberConsentGiven'])`
4. Decline → `_paq.push(['forgetConsentGiven'])` + custom cookie `mtm_consent_removed`

**Τι λέει η τεκμηρίωση Matomo:**

**`requireConsent()`:**
> "To change this behavior so nothing is tracked until a user consents, you must call `requireConsent`."
> "No tracking request will be sent to Matomo and no cookies will be set."

- Πρέπει να κληθεί **πριν** το `trackPageView` → **Ο κώδικας το κάνει σωστά** (γραμμές πριν το `trackPageView` στο template)
- Μπλοκάρει **τα πάντα**: requests + cookies → **Συμφωνεί με τον κώδικα**

**`rememberConsentGiven(hoursToExpire)`:**
> "Mark that the current user has consented, and remembers this consent through a browser cookie."
> "If you call this method, you do not need to call `setConsentGiven`."

- Θέτει first-party cookie **`mtm_consent`** → **Ο κώδικας ελέγχει σωστά αυτό το cookie**
- Δέχεται προαιρετικό `hoursToExpire` → **Ο κώδικας δεν περνάει παράμετρο**, που σημαίνει ότι η συγκατάθεση δεν λήγει (μόνο αν ο χρήστης καθαρίσει cookies). Αυτό είναι αποδεκτή συμπεριφορά.

**`forgetConsentGiven()`:**
> "Remove a user's consent, both if the consent was one-time only and if the consent was remembered."
> Deletes consent-related cookies.

- Σβήνει το `mtm_consent` cookie → **Σωστό**
- Ο κώδικας θέτει επιπλέον custom cookie `mtm_consent_removed` (365 ημέρες) για να θυμάται ότι ο χρήστης αρνήθηκε → **Αυτό δεν είναι Matomo API — είναι custom λογική** για να μην ξαναεμφανιστεί το banner. Η τεκμηρίωση Matomo δεν παρέχει τέτοιο μηχανισμό, οπότε η custom υλοποίηση είναι απαραίτητη και σωστή.

**Επαλήθευση: ΣΩΣΤΟ.** Η σειρά κλήσεων, τα API calls, και η λογική cookies ακολουθούν πιστά την τεκμηρίωση.

**Τι καταγράφεται ανά κατάσταση χρήστη:**

| Μετρική | Πριν consent (νέος χρήστης) | Μετά Accept | Μετά Decline |
|---|---|---|---|
| Pageviews | **Κανένα** — request δεν στέλνεται | Ναι | **Κανένα** |
| Cookies | **Κανένα** | Ναι (visitor ID κλπ) | **Κανένα** |
| Unique visitors | **Δεν υπάρχει** | Ναι | **Δεν υπάρχει** |
| Session duration | **Δεν υπάρχει** | Ναι | **Δεν υπάρχει** |
| Downloads / events | **Κανένα** | Ναι | **Κανένα** |
| Referrers | **Κανένα** | Ναι | **Κανένα** |

> **Σημείωση:** Αυτή είναι η πιο αυστηρή λειτουργία. Χρήστες που δεν αλληλεπιδρούν με το banner (ούτε Accept ούτε Decline) είναι **εντελώς αόρατοι** στο Matomo.

---

### 3.3 Mode: `cookie_consent` — Συγκατάθεση μόνο για cookies

**Τι κάνει ο κώδικας:**

1. `matomo.html` → `_paq.push(['requireCookieConsent'])` **πριν** το `trackPageView`
2. Banner εμφανίζεται αν δεν υπάρχει cookie `mtm_cookie_consent` ή `mtm_consent_removed`
3. Accept → `_paq.push(['rememberCookieConsentGiven'])`
4. Decline → `_paq.push(['forgetCookieConsentGiven'])` + custom cookie `mtm_consent_removed`

**Τι λέει η τεκμηρίωση Matomo:**

**`requireCookieConsent()`:**
> "To change this behavior so no cookies are used by default, you must call `requireCookieConsent`."
> "Tracking requests will be always sent. However, cookies will be only used if consent for storing and using cookies was given by the user."

- Τα requests **στέλνονται κανονικά** → pageviews, events, downloads καταγράφονται
- Τα cookies **μπλοκάρονται** → δεν γίνεται visitor identification
- Πρέπει να κληθεί **πριν** το `trackPageView` → **Ο κώδικας το κάνει σωστά**

**`rememberCookieConsentGiven(hoursToExpire)`:**
> "Mark that the current user has consented to using cookies, and remembers this consent through a browser cookie."
> "If you call this method, you do not need to call `setCookieConsentGiven`."

- Θέτει first-party cookie **`mtm_cookie_consent`** → **Ο κώδικας ελέγχει σωστά αυτό το cookie**
- Χωρίς `hoursToExpire` → consent δεν λήγει → **Αποδεκτό**

**`forgetCookieConsentGiven()`:**
> "Remove a user's cookie consent, both if the consent was one-time only and if the consent was remembered."
> Deletes persistent cookie consent records.

- Σβήνει το `mtm_cookie_consent` cookie → **Σωστό**
- Custom `mtm_consent_removed` cookie → ίδια λογική με tracking_consent → **Σωστό**

**Επαλήθευση: ΣΩΣΤΟ.** Η υλοποίηση ακολουθεί πιστά την τεκμηρίωση.

**Τι καταγράφεται ανά κατάσταση χρήστη:**

| Μετρική | Πριν consent (νέος χρήστης) | Μετά Accept | Μετά Decline |
|---|---|---|---|
| Pageviews | **Ναι** — requests στέλνονται | Ναι | **Ναι** |
| Cookies | **Όχι** | Ναι (visitor ID κλπ) | **Όχι** |
| Unique visitors | **Όχι** — κάθε request = νέος visitor | Ναι | **Όχι** |
| Session duration | **Ανακριβές** — χωρίς cookies κάθε pageview = νέα session | Ναι | **Ανακριβές** |
| Downloads / events | **Ναι** | Ναι | **Ναι** |
| Referrers | **Ναι** | Ναι | **Ναι** |

> **Σημείωση:** Αυτή η λειτουργία προσφέρει το καλύτερο balance. Ακόμα και χωρίς cookies, τα βασικά analytics (πόσα pageviews, ποια downloads, από πού ήρθαν) λειτουργούν. Χάνεται μόνο η **ταυτοποίηση επισκέπτη** (unique visitors, returning visitors, session tracking).

---

### 3.4 Mode: `opt_out` — Tracking by default, εξαίρεση κατ' επιλογή

**Τι κάνει ο κώδικας:**

1. `matomo.html` → **Δεν εισάγει καμία `requireConsent`/`requireCookieConsent` εντολή** (σωστά — δεν υπάρχει `{% elif consent_mode == 'opt_out' %}` block στο matomo.html)
2. Banner εμφανίζεται αν δεν υπάρχει `sessionStorage.cookieConsentBannerDismissed`
3. Opt Out → `_paq.push(['optUserOut'])` (toggle — αν ήδη opted-out, καλεί `forgetUserOptOut`)
4. Close (×) → `sessionStorage.cookieConsentBannerDismissed = '1'`

**Τι λέει η τεκμηρίωση Matomo:**

**`optUserOut()`:**
> "After calling this function, the user will be opted out and no longer be tracked."

- Θέτει opt-out indicator cookie → **Ο χρήστης δεν καταγράφεται πλέον**

**`forgetUserOptOut()`:**
> "After calling this method the user will be tracked again. Call this method if the user opted out before."

- Αφαιρεί το opt-out cookie → **Επαναφορά tracking**

**`isUserOptedOut()`:**
> "Returns true or false depending on whether the user is opted out or not."

- Ο κώδικας χρησιμοποιεί `this.isUserOptedOut()` μέσα σε `_paq.push([function() {...}])` → **Σωστή χρήση** — η anonymous function εκτελείται στο context του tracker, οπότε `this` είναι ο tracker instance

> **Σημείωση τεκμηρίωσης:** "This method might not return the correct value if you are using the opt out iframe." Η υλοποίηση **δεν** χρησιμοποιεί iframe — χρησιμοποιεί custom banner, οπότε αυτός ο περιορισμός **δεν ισχύει**.

**Επαλήθευση: ΣΩΣΤΟ.** Η υλοποίηση ακολουθεί πιστά την τεκμηρίωση.

**Ειδική σημείωση — Banner dismiss με sessionStorage:**
Η τεκμηρίωση Matomo δεν ορίζει μηχανισμό dismiss για opt-out banners. Η υλοποίηση χρησιμοποιεί `sessionStorage` (όχι cookie), που σημαίνει:
- Το banner εξαφανίζεται μόνο για το τρέχον browser session
- Σε νέο tab/session, ξαναεμφανίζεται
- Αυτό είναι **σκόπιμη σχεδιαστική απόφαση**: δίνει στον χρήστη συνεχή πρόσβαση στο opt-out toggle, χωρίς να τον ενοχλεί κατά τη διάρκεια μιας session

**Τι καταγράφεται ανά κατάσταση χρήστη:**

| Μετρική | Default (δεν πάτησε τίποτα) | Μετά Opt Out | Μετά Resume Tracking |
|---|---|---|---|
| Pageviews | **Ναι** | **Κανένα** | **Ναι** |
| Cookies | **Ναι** | **Κανένα** | **Ναι** |
| Unique visitors | **Ναι** | **Δεν υπάρχει** | **Ναι** |
| Session duration | **Ναι** | **Δεν υπάρχει** | **Ναι** |
| Downloads / events | **Ναι** | **Κανένα** | **Ναι** |
| Referrers | **Ναι** | **Κανένα** | **Ναι** |

> **Σημείωση:** Σε αντίθεση με τα consent modes, εδώ το tracking ξεκινάει **αμέσως** χωρίς να περιμένει αλληλεπίδραση. Αν ο χρήστης κλείσει απλά το banner (×), το tracking συνεχίζεται κανονικά.

---

### 3.5 Συνολική επαλήθευση — Matomo JS API calls

| Ενέργεια κώδικα | Matomo API call | Τεκμηρίωση επιβεβαιώνει; | Σημειώσεις |
|---|---|---|---|
| Block all tracking | `requireConsent()` | **Ναι** — "no tracking request will be sent and no cookies will be set" | Πρέπει πριν `trackPageView` — ο κώδικας το τηρεί |
| Block only cookies | `requireCookieConsent()` | **Ναι** — "tracking requests will be always sent, cookies will be only used if consent was given" | Πρέπει πριν `trackPageView` — ο κώδικας το τηρεί |
| Accept (tracking) | `rememberConsentGiven()` | **Ναι** — "remembers consent through a browser cookie" (`mtm_consent`) | Χωρίς `hoursToExpire` = δεν λήγει |
| Accept (cookie) | `rememberCookieConsentGiven()` | **Ναι** — "remembers consent through a browser cookie" (`mtm_cookie_consent`) | Χωρίς `hoursToExpire` = δεν λήγει |
| Decline (tracking) | `forgetConsentGiven()` | **Ναι** — "remove a user's consent" | Σβήνει `mtm_consent` |
| Decline (cookie) | `forgetCookieConsentGiven()` | **Ναι** — "remove a user's cookie consent" | Σβήνει `mtm_cookie_consent` |
| Opt out | `optUserOut()` | **Ναι** — "user will be opted out and no longer be tracked" | |
| Resume tracking | `forgetUserOptOut()` | **Ναι** — "user will be tracked again" | |
| Check opt-out status | `isUserOptedOut()` | **Ναι** — "returns true or false" | "might not return correct value if using opt out iframe" — δεν ισχύει εδώ |

---

### 3.6 Custom λογική εκτός Matomo API

Ο κώδικας χρησιμοποιεί κάποια **custom λογική** που δεν προέρχεται από το Matomo API:

| Custom στοιχείο | Λόγος | Αξιολόγηση |
|---|---|---|
| Cookie `mtm_consent_removed` (365 ημέρες) | Το Matomo API δεν παρέχει τρόπο να «θυμάται» ότι ο χρήστης αρνήθηκε. Χωρίς αυτό το cookie, το banner θα εμφανιζόταν ξανά σε κάθε reload. | **Σωστή σχεδιαστική απόφαση** — απαραίτητο για UX |
| `sessionStorage.cookieConsentBannerDismissed` | Στο opt_out mode, το banner δεν πρέπει να ξαναφαίνεται στην ίδια session μετά το dismiss, αλλά πρέπει να εμφανίζεται σε νέα session ώστε ο χρήστης να μπορεί πάντα να κάνει opt-out. | **Σωστή σχεδιαστική απόφαση** — balance μεταξύ UX και πρόσβασης στο opt-out |
| `hasCookie()` function | Client-side check μέσω `document.cookie` πριν εμφανιστεί το banner | **Σωστό** — αποφεύγει server-side dependency, ταχύτερο |
| `setCookie()` function | Θέτει cookies με `SameSite=Lax` και `path=/` | **Σωστό** — `SameSite=Lax` είναι η συνιστώμενη τιμή για first-party cookies |

---

### 3.7 Πιθανά σημεία προσοχής

**1. `rememberConsentGiven()` χωρίς `hoursToExpire`:**
Η τεκμηρίωση δέχεται προαιρετική παράμετρο `hoursToExpire`. Ο κώδικας δεν τη χρησιμοποιεί, που σημαίνει ότι η συγκατάθεση **δεν λήγει ποτέ** (μόνο αν ο χρήστης καθαρίσει cookies). Ανάλογα με τη νομική ερμηνεία, μπορεί να χρειαστεί ανανέωση consent μετά από X μήνες. Αν χρειαστεί, αρκεί να προστεθεί η παράμετρος:
```javascript
_paq.push(['rememberConsentGiven', 8760]); // 1 έτος σε ώρες
```

**2. Opt-out mode δεν αλλάζει τίποτα στο `matomo.html`:**
Στο `matomo.html` template, δεν υπάρχει `{% elif consent_mode == 'opt_out' %}` block. Αυτό είναι **σωστό** γιατί στο opt-out mode ο tracker πρέπει να λειτουργεί κανονικά (πλήρες tracking by default) — η εξαίρεση γίνεται μέσω `optUserOut()` στο banner JS, όχι μέσω αλλαγής στον tracker initialization.

**3. Σειρά εκτέλεσης `_paq` commands:**
Η τεκμηρίωση αναφέρει:
> "For asynchronous tracking, configuration and tracking calls are pushed onto the global `_paq` array for execution, independent of the asynchronous loading of `matomo.js`."

Τα commands εκτελούνται **με τη σειρά** που γίνονται push. Η σειρά στο template (`requireConsent` → `trackPageView` → `enableLinkTracking`) είναι σωστή. Αν γινόταν ανάποδα, το πρώτο pageview θα καταγραφόταν πριν ενεργοποιηθεί το consent requirement.

---

## 4. Ανάλυση εναλλαγής modes — Τι συμβαίνει με τα cookies κάθε χρήστη

### 4.1 Cookies που θέτει/ελέγχει κάθε mode

Πριν εξετάσουμε τις εναλλαγές, ας δούμε ποια cookies εμπλέκονται:

| Cookie / Storage | Ποιος το θέτει | Πού ελέγχεται | Διάρκεια |
|---|---|---|---|
| `mtm_consent` | Matomo API (`rememberConsentGiven`) | Banner JS σε mode `tracking_consent` | Δεν λήγει (μόνο clear browser) |
| `mtm_cookie_consent` | Matomo API (`rememberCookieConsentGiven`) | Banner JS σε mode `cookie_consent` | Δεν λήγει |
| `mtm_consent_removed` | Custom JS (`setCookie`) | Banner JS σε modes `tracking_consent` **και** `cookie_consent` | 365 ημέρες |
| `sessionStorage.cookieConsentBannerDismissed` | Custom JS | Banner JS σε mode `opt_out` | Μέχρι κλείσιμο tab/browser |
| Matomo opt-out cookie | Matomo API (`optUserOut`) | Matomo tracker εσωτερικά | Ορίζεται από Matomo |

**Κρίσιμη παρατήρηση:** Το `mtm_consent_removed` χρησιμοποιείται **κοινό** και για τα δύο consent modes. Αν ο χρήστης κάνει Decline σε ένα mode, το cookie υπάρχει και στο άλλο.

---

### 4.2 Πίνακας εναλλαγών — Όλα τα σενάρια

Ο admin αλλάζει mode στο `/ckan-admin/config`. Από την **επόμενη σελίδα** που φορτώνει ο χρήστης, ισχύει το νέο mode. Ας δούμε τι συμβαίνει ανά περίπτωση:

---

#### 4.2.1 `disabled` → οποιοδήποτε mode

| Προηγούμενο | Νέο | Cookies χρήστη | Εμφανίζεται banner; | Tracking; | Αξιολόγηση |
|---|---|---|---|---|---|
| disabled | tracking_consent | Κανένα consent cookie | **Ναι** | Blocked μέχρι Accept | **Σωστό** |
| disabled | cookie_consent | Κανένα consent cookie | **Ναι** | Ανώνυμο (χωρίς cookies) μέχρι Accept | **Σωστό** |
| disabled | opt_out | Κανένα σχετικό storage | **Ναι** | Πλήρες αμέσως | **Σωστό** |

**Συμπέρασμα:** Η μετάβαση από `disabled` σε οτιδήποτε λειτουργεί **τέλεια**. Δεν υπάρχουν παλιά cookies που να δημιουργούν σύγχυση.

---

#### 4.2.2 `tracking_consent` → `cookie_consent`

Σενάριο: Ο admin χαλαρώνει τη ρύθμιση (από αυστηρό σε λιγότερο αυστηρό).

**Χρήστης που είχε κάνει Accept:**
- Έχει cookie: `mtm_consent`
- Νέο mode ελέγχει: `mtm_cookie_consent` ή `mtm_consent_removed`
- `mtm_cookie_consent` **δεν υπάρχει**, `mtm_consent_removed` **δεν υπάρχει**
- **Banner εμφανίζεται ξανά** παρόλο που ο χρήστης είχε δώσει πλήρη συγκατάθεση
- `matomo.html`: `requireCookieConsent()` — cookies blocked μέχρι νέο Accept
- **Αποτέλεσμα:** Ο χρήστης πρέπει να ξανα-αποδεχτεί, αλλιώς τρέχει ανώνυμο tracking
- **Αξιολόγηση:** ⚠️ **Ενοχλητικό αλλά όχι λάθος** — ο χρήστης βλέπει ξανά banner, αλλά ακόμα και χωρίς αποδοχή τα βασικά analytics (pageviews, downloads) λειτουργούν

**Χρήστης που είχε κάνει Decline:**
- Έχει cookie: `mtm_consent_removed`
- Νέο mode ελέγχει: `mtm_cookie_consent` ή `mtm_consent_removed`
- `mtm_consent_removed` **υπάρχει**
- **Banner ΔΕΝ εμφανίζεται**
- `matomo.html`: `requireCookieConsent()` — cookies blocked
- **Αποτέλεσμα:** Ο χρήστης δεν βλέπει banner, **ΑΛΛΑ** τώρα γίνεται ανώνυμο tracking (pageviews, events) ενώ πριν δεν γινόταν τίποτα
- **Αξιολόγηση:** ⚠️ **Πρόβλημα privacy** — ο χρήστης αρνήθηκε **ΟΛΟ** το tracking στο tracking_consent, αλλά τώρα γίνεται ανώνυμο tracking χωρίς να ρωτηθεί. Δεν βλέπει καν banner για να ξέρει ότι άλλαξε κάτι.

---

#### 4.2.3 `cookie_consent` → `tracking_consent`

Σενάριο: Ο admin αυστηροποιεί τη ρύθμιση.

**Χρήστης που είχε κάνει Accept:**
- Έχει cookie: `mtm_cookie_consent`
- Νέο mode ελέγχει: `mtm_consent` ή `mtm_consent_removed`
- Κανένα δεν υπάρχει
- **Banner εμφανίζεται ξανά**
- `matomo.html`: `requireConsent()` — τα πάντα blocked
- **Αποτέλεσμα:** Ο χρήστης πρέπει να ξανα-αποδεχτεί. Μέχρι τότε: κανένα tracking
- **Αξιολόγηση:** **Σωστό** — ο admin θέλει αυστηρότερη συγκατάθεση, ο χρήστης ξαναρωτιέται

**Χρήστης που είχε κάνει Decline:**
- Έχει cookie: `mtm_consent_removed`
- Νέο mode ελέγχει: `mtm_consent` ή `mtm_consent_removed`
- `mtm_consent_removed` **υπάρχει**
- **Banner ΔΕΝ εμφανίζεται**
- `matomo.html`: `requireConsent()` — τα πάντα blocked
- **Αποτέλεσμα:** Κανένα tracking — η άρνηση μεταφέρεται σωστά
- **Αξιολόγηση:** **Σωστό** — ο χρήστης που αρνήθηκε cookies, αρνείται αυτόματα και πλήρες tracking

---

#### 4.2.4 `tracking_consent` ή `cookie_consent` → `opt_out`

**Χρήστης που είχε κάνει Accept (οποιοδήποτε consent mode):**
- Έχει cookie: `mtm_consent` ή `mtm_cookie_consent`
- Opt_out mode ελέγχει: `sessionStorage.cookieConsentBannerDismissed`
- Δεν υπάρχει στο sessionStorage
- **Banner εμφανίζεται** (opt-out version)
- `matomo.html`: **κανένα** requireConsent — πλήρες tracking αμέσως
- **Αποτέλεσμα:** Tracking ξεκινάει αμέσως (σωστό — opt_out σημαίνει tracking by default). Ο χρήστης μπορεί να κάνει opt-out αν θέλει.
- **Αξιολόγηση:** **Αποδεκτό** — αλλαγή πολιτικής, ο χρήστης ενημερώνεται μέσω banner

**Χρήστης που είχε κάνει Decline (οποιοδήποτε consent mode):**
- Έχει cookie: `mtm_consent_removed`
- Opt_out mode ελέγχει: `sessionStorage.cookieConsentBannerDismissed`
- Δεν υπάρχει στο sessionStorage
- **Banner εμφανίζεται** (opt-out version)
- `matomo.html`: **κανένα** requireConsent — πλήρες tracking αμέσως
- **Αποτέλεσμα:** Ο χρήστης που αρνήθηκε τώρα γίνεται tracked πλήρως!
- **Αξιολόγηση:** ⚠️ **Πρόβλημα privacy** — αλλά τουλάχιστον ο χρήστης βλέπει banner και μπορεί να κάνει opt-out

---

#### 4.2.5 `opt_out` → `tracking_consent` ή `cookie_consent`

**Χρήστης που δεν πάτησε τίποτα (ή dismiss):**
- Cookies: κανένα consent cookie, πιθανώς `sessionStorage.cookieConsentBannerDismissed`
- Νέο mode ελέγχει: `mtm_consent`/`mtm_cookie_consent` ή `mtm_consent_removed`
- Κανένα δεν υπάρχει
- **Banner εμφανίζεται**
- **Αξιολόγηση:** **Σωστό**

**Χρήστης που είχε κάνει Opt Out:**
- Cookies: Matomo opt-out cookie (internal)
- Νέο mode ελέγχει: `mtm_consent`/`mtm_cookie_consent` ή `mtm_consent_removed`
- Κανένα δεν υπάρχει
- **Banner εμφανίζεται**
- `matomo.html`: `requireConsent()` ή `requireCookieConsent()`
- Matomo: ο tracker ελέγχει **και** το requireConsent **και** το opt-out cookie
- **Αποτέλεσμα:** Tracking blocked λόγω requireConsent + opt-out cookie. Banner ζητάει consent.
- **Αξιολόγηση:** **Σωστό** — αν ο χρήστης κάνει Accept, χρειάζεται επίσης `forgetUserOptOut` για να ξεκινήσει tracking. **Πιθανό πρόβλημα:** ο κώδικας καλεί `rememberConsentGiven` αλλά **δεν** καλεί `forgetUserOptOut` — το παλιό opt-out cookie μπορεί να εξακολουθεί να μπλοκάρει το tracking ακόμα και μετά το Accept.

---

#### 4.2.6 Οποιοδήποτε mode → `disabled`

**Κάθε χρήστης:**
- `matomo.html`: **κανένα** requireConsent/requireCookieConsent
- Banner: **δεν renderάρεται** (`{% if consent_mode != 'disabled' %}` → false)
- **Αποτέλεσμα:** Πλήρες tracking αμέσως, ανεξάρτητα τι είχε επιλέξει ο χρήστης
- Τα παλιά cookies (`mtm_consent`, `mtm_cookie_consent`, `mtm_consent_removed`) παραμένουν αλλά **κανείς δεν τα ελέγχει**
- **Αξιολόγηση:** ⚠️ **Πρόβλημα privacy** — χρήστες που αρνήθηκαν τώρα γίνονται tracked χωρίς ειδοποίηση

---

### 4.3 Συγκεντρωτικός πίνακας εναλλαγών

| Από → Προς | Χρήστης: Accept | Χρήστης: Decline | Χρήστης: Νέος |
|---|---|---|---|
| **disabled → tracking** | Banner, blocked μέχρι Accept | — | Banner, blocked μέχρι Accept |
| **disabled → cookie** | Banner, ανώνυμο μέχρι Accept | — | Banner, ανώνυμο μέχρι Accept |
| **disabled → opt_out** | Banner, tracking αμέσως | — | Banner, tracking αμέσως |
| **tracking → cookie** | ⚠️ Banner ξανά (παλιό consent αγνοείται) | ⚠️ **Χωρίς banner, ανώνυμο tracking ξεκινά** | Banner, ανώνυμο μέχρι Accept |
| **cookie → tracking** | Banner ξανά (σωστό — αυστηρότερο) | Χωρίς banner, blocked (σωστό) | Banner, blocked μέχρι Accept |
| **tracking → opt_out** | Banner opt-out, tracking αμέσως | ⚠️ **Banner opt-out, πλήρες tracking αμέσως** | Banner opt-out, tracking αμέσως |
| **cookie → opt_out** | Banner opt-out, tracking αμέσως | ⚠️ **Banner opt-out, πλήρες tracking αμέσως** | Banner opt-out, tracking αμέσως |
| **opt_out → tracking** | — | ⚠️ Banner, blocked αλλά opt-out cookie μπορεί να μείνει | Banner, blocked μέχρι Accept |
| **opt_out → cookie** | — | ⚠️ Banner, ανώνυμο αλλά opt-out cookie μπορεί να μείνει | Banner, ανώνυμο μέχρι Accept |
| **tracking → disabled** | Tracking αμέσως (OK) | ⚠️ **Πλήρες tracking χωρίς ειδοποίηση** | Tracking αμέσως |
| **cookie → disabled** | Tracking αμέσως (OK) | ⚠️ **Πλήρες tracking χωρίς ειδοποίηση** | Tracking αμέσως |
| **opt_out → disabled** | Tracking αμέσως (OK) | ⚠️ **Πλήρες tracking χωρίς ειδοποίηση** | Tracking αμέσως |

---

### 4.4 Εντοπισμένα προβλήματα

#### Πρόβλημα 1: `tracking_consent` → `cookie_consent` (Decline χρήστης)

**Σοβαρότητα:** Μεσαία-Υψηλή (privacy concern)

**Τι συμβαίνει:** Ο χρήστης αρνήθηκε **ΟΛΟ** το tracking. Ο admin αλλάζει σε cookie_consent. Τώρα γίνεται ανώνυμο tracking χωρίς ο χρήστης να ρωτηθεί ξανά (δεν βλέπει καν banner γιατί το `mtm_consent_removed` cookie κρύβει το banner).

**Γιατί συμβαίνει:** Το `mtm_consent_removed` cookie μοιράζεται μεταξύ tracking_consent και cookie_consent. Ο banner JS ελέγχει αυτό το cookie και αποφασίζει "ο χρήστης ήδη αποφάσισε, δεν δείχνω banner". Αλλά η `requireCookieConsent()` στο matomo.html **επιτρέπει** ανώνυμα requests.

**Πιθανή λύση:** Χρήση ξεχωριστών decline cookies ανά mode, π.χ. `mtm_tracking_consent_removed` και `mtm_cookie_consent_removed`.

#### Πρόβλημα 2: Οτιδήποτε → `disabled` (Decline χρήστης)

**Σοβαρότητα:** Μεσαία (αλλά αναμενόμενη)

**Τι συμβαίνει:** Ο χρήστης που αρνήθηκε γίνεται πλήρως tracked χωρίς ειδοποίηση.

**Γιατί:** Το disabled mode δεν renderάρει banner ούτε ελέγχει cookies. Ο Matomo tracker φορτώνει χωρίς requireConsent.

**Σημείωση:** Αυτό είναι **αναμενόμενο** — ο admin αποφάσισε συνειδητά να απενεργοποιήσει τη συγκατάθεση. Αλλά νομικά μπορεί να είναι προβληματικό.

#### Πρόβλημα 3: `opt_out` → consent modes (Opted-out χρήστης)

**Σοβαρότητα:** Χαμηλή

**Τι συμβαίνει:** Ο χρήστης είχε κάνει opt-out. Τώρα βλέπει consent banner. Αν κάνει Accept, ο κώδικας καλεί `rememberConsentGiven()` αλλά **δεν** καλεί `forgetUserOptOut()`. Το Matomo opt-out cookie μπορεί να εξακολουθεί να μπλοκάρει το tracking.

**Πιθανή λύση:** Στο Accept handler, αν υπάρχει opt-out status, καλείται επιπλέον `forgetUserOptOut()`.

---

### 4.5 Ρόλος του καθαρισμού cookies στον browser

| Ενέργεια χρήστη | Αποτέλεσμα |
|---|---|
| Clear all cookies | Σβήνονται `mtm_consent`, `mtm_cookie_consent`, `mtm_consent_removed`, Matomo opt-out cookie. **Banner εμφανίζεται ξανά.** Ο χρήστης πρέπει να ξανααποφασίσει. |
| Clear only Matomo cookies | Ίδιο με παραπάνω — οι αποφάσεις consent χάνονται |
| Incognito / Private window | Κανένα cookie — **Banner εμφανίζεται πάντα** σε consent modes. Σε opt_out, banner εμφανίζεται αλλά tracking γίνεται αμέσως. |
| Αλλαγή browser | Κανένα cookie — ξεκινάει from scratch |
| sessionStorage clear | Μόνο σε opt_out: banner ξαναεμφανίζεται (αλλά tracking δεν αλλάζει) |

**Σημαντικό:** Αν ο χρήστης καθαρίσει cookies, η εναλλαγή mode δεν έχει κανένα πρόβλημα — ο χρήστης ξεκινάει "καθαρός" και βλέπει banner.

---

### 4.6 Σύσταση για ασφαλή εναλλαγή mode

Αν ο admin θέλει να αλλάξει mode χωρίς side effects:

1. **Από αυστηρό σε χαλαρό** (tracking_consent → cookie_consent/opt_out/disabled): Οι χρήστες που είχαν αρνηθεί μπορεί να αρχίσουν να γίνονται tracked. **Σύσταση:** Ενημέρωση χρηστών (π.χ. ανακοίνωση) ή/και νέα σελίδα πολιτικής cookies.

2. **Από χαλαρό σε αυστηρό** (cookie_consent/opt_out → tracking_consent): Ασφαλής μετάβαση — οι χρήστες ξαναρωτιούνται. Δεν υπάρχει privacy risk.

3. **Μεταξύ consent modes** (tracking ↔ cookie): ~~Λόγω του κοινού `mtm_consent_removed` cookie, η μετάβαση tracking_consent → cookie_consent μπορεί να ξεκινήσει ανώνυμο tracking σε χρήστες που αρνήθηκαν.~~ **Διορθώθηκε** — βλ. Section 5.

---

## 5. Διόρθωση: Διακριτά decline cookies ανά mode

### 5.1 Τι αλλάχτηκε

**Αρχείο:** `ckanext-data-gov-gr/ckanext/data_gov_gr/templates/snippets/cookie_consent_banner.html`

**Πριν (κοινό cookie):**
```javascript
var consentCookie = (mode === 'tracking_consent') ? 'mtm_consent' : 'mtm_cookie_consent';

if (hasCookie(consentCookie) || hasCookie('mtm_consent_removed')) {
  return;
}
// ...
setCookie('mtm_consent_removed', '1', 365);
```

**Μετά (διακριτά cookies):**
```javascript
var consentCookie = (mode === 'tracking_consent') ? 'mtm_consent' : 'mtm_cookie_consent';
var declineCookie = (mode === 'tracking_consent') ? 'mtm_tracking_declined' : 'mtm_cookie_declined';

if (hasCookie(consentCookie) || hasCookie(declineCookie)) {
  return;
}
// ...
setCookie(declineCookie, '1', 365);
```

### 5.2 Τι λύνει

| Σενάριο | Πριν | Μετά |
|---|---|---|
| `tracking_consent` → `cookie_consent` (Decline χρήστης) | ⚠️ Χωρίς banner, ανώνυμο tracking σιωπηλά | **Banner εμφανίζεται ξανά** — ο χρήστης ξαναρωτιέται |
| `cookie_consent` → `tracking_consent` (Decline χρήστης) | Χωρίς banner, blocked (σωστό τυχαία — λόγω κοινού cookie) | **Banner εμφανίζεται ξανά** — ο χρήστης ξαναρωτιέται |

Τώρα σε **κάθε** εναλλαγή μεταξύ consent modes, ο χρήστης που είχε αρνηθεί **βλέπει πάντα νέο banner** και αποφασίζει ξανά.

### 5.3 Cookies ανά mode μετά τη διόρθωση

| Cookie | Θέτεται από | Ελέγχεται σε mode | Σκοπός |
|---|---|---|---|
| `mtm_consent` | Matomo API | `tracking_consent` | Ο χρήστης αποδέχτηκε πλήρες tracking |
| `mtm_cookie_consent` | Matomo API | `cookie_consent` | Ο χρήστης αποδέχτηκε cookies |
| `mtm_tracking_declined` | Custom JS | `tracking_consent` | Ο χρήστης αρνήθηκε πλήρες tracking |
| `mtm_cookie_declined` | Custom JS | `cookie_consent` | Ο χρήστης αρνήθηκε cookies |

Κάθε mode ελέγχει **μόνο τα δικά του cookies** — καμία cross-contamination.

### 5.4 Αναθεωρημένος πίνακας εναλλαγών

| Από → Προς | Χρήστης: Accept | Χρήστης: Decline | Χρήστης: Νέος |
|---|---|---|---|
| **disabled → tracking** | Banner, blocked μέχρι Accept | — | Banner, blocked μέχρι Accept |
| **disabled → cookie** | Banner, ανώνυμο μέχρι Accept | — | Banner, ανώνυμο μέχρι Accept |
| **disabled → opt_out** | Banner, tracking αμέσως | — | Banner, tracking αμέσως |
| **tracking → cookie** | Banner ξανά, ανώνυμο μέχρι Accept | **Banner ξανά** — ο χρήστης αποφασίζει εκ νέου | Banner, ανώνυμο μέχρι Accept |
| **cookie → tracking** | Banner ξανά, blocked μέχρι Accept | **Banner ξανά** — ο χρήστης αποφασίζει εκ νέου | Banner, blocked μέχρι Accept |
| **tracking → opt_out** | Banner opt-out, tracking αμέσως | Banner opt-out, tracking αμέσως (*) | Banner opt-out, tracking αμέσως |
| **cookie → opt_out** | Banner opt-out, tracking αμέσως | Banner opt-out, tracking αμέσως (*) | Banner opt-out, tracking αμέσως |
| **opt_out → tracking** | — | Banner, blocked (**) | Banner, blocked μέχρι Accept |
| **opt_out → cookie** | — | Banner, ανώνυμο (**) | Banner, ανώνυμο μέχρι Accept |
| **tracking → disabled** | Tracking αμέσως | Tracking αμέσως (***) | Tracking αμέσως |
| **cookie → disabled** | Tracking αμέσως | Tracking αμέσως (***) | Tracking αμέσως |
| **opt_out → disabled** | Tracking αμέσως | Tracking αμέσως (***) | Tracking αμέσως |

### 5.5 Εναπομείναντα edge cases

Τα παρακάτω **δεν είναι bugs** αλλά εγγενείς συμπεριφορές της αρχιτεκτονικής:

**(*)** `consent → opt_out` (Decline χρήστης): Ο χρήστης που αρνήθηκε τώρα γίνεται tracked αμέσως (opt_out = tracking by default). **Αλλά** βλέπει banner και μπορεί ενεργά να κάνει opt-out. **Δεν είναι αθόρυβη αλλαγή** — ο χρήστης ειδοποιείται. Αυτό αντικατοπτρίζει τη συνειδητή αλλαγή πολιτικής του admin.

**(**)** `opt_out → consent` (Opted-out χρήστης): Ο χρήστης βλέπει consent banner. Αν κάνει Accept, ο κώδικας καλεί `rememberConsentGiven()` αλλά **δεν** καλεί `forgetUserOptOut()`. Πιθανό εσωτερικό conflict στο Matomo tracker. **Πρακτικός αντίκτυπος:** Ελάχιστος — λίγοι χρήστες θα έχουν ταυτόχρονα opt-out cookie + consent cookie. Αν παρατηρηθεί πρόβλημα, η λύση είναι να προστεθεί `_paq.push(['forgetUserOptOut'])` στο Accept handler.

**(***)**  `οτιδήποτε → disabled`: Ο admin απενεργοποιεί **συνειδητά** τη συγκατάθεση. Πλήρες tracking χωρίς banner. **Δεν είναι bug** — είναι η ορισμένη συμπεριφορά του `disabled`. Τα παλιά cookies παραμένουν αλλά κανείς δεν τα ελέγχει. Αν ο admin ξαναενεργοποιήσει consent αργότερα, θα εμφανιστεί banner κανονικά (τα παλιά cookies θα εξακολουθούν να ισχύουν αν δεν έχουν λήξει).

### 5.6 Τελικό συμπέρασμα

Μετά τη διόρθωση με τα διακριτά decline cookies:

- **Εναλλαγή μεταξύ `tracking_consent` ↔ `cookie_consent`:** Λειτουργεί **σωστά** — ο χρήστης ξαναρωτιέται πάντα
- **Εναλλαγή από/προς `opt_out`:** Λειτουργεί **αποδεκτά** — ο χρήστης ενημερώνεται μέσω banner
- **Εναλλαγή από/προς `disabled`:** Λειτουργεί **by design** — ο admin αποφασίζει συνειδητά
- **Clear cookies:** Λύνει **κάθε** edge case — ο χρήστης ξεκινάει καθαρός
