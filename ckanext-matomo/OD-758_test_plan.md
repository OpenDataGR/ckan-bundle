# OD-758 — Test Plan: Cookie Consent Banner

## Προαπαιτούμενα

- Πρόσβαση στο CKAN admin (`/ckan-admin/config`)
- Πρόσβαση στο Matomo dashboard
- Browser DevTools (F12) — tabs: Console, Application (Cookies), Network
- Ένα δεύτερο browser ή Incognito window για "καθαρό" χρήστη

---

## 0. Προετοιμασία

Πριν ξεκινήσεις, σε κάθε test:

1. **Clear cookies** για το domain του portal: DevTools → Application → Cookies → δεξί κλικ → Clear
2. **Clear sessionStorage**: DevTools → Application → Session Storage → Clear
3. **Matomo dashboard**: Άνοιξε σε ξεχωριστό tab, φίλτρο "Visitors → Real-time" ή "Visits Log" για να βλέπεις live αν καταγράφονται visits

---

## 1. Mode: `disabled`

### 1.1 Βασική λειτουργία

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Στο admin config, επέλεξε **Απενεργοποιημένο** → Save | Αποθηκεύεται | |
| 2 | Σε Incognito, άνοιξε τη σελίδα | **Κανένα banner** | |
| 3 | DevTools → Application → Cookies | Matomo cookies (π.χ. `_pk_id`, `_pk_ses`) **υπάρχουν** | |
| 4 | DevTools → Network → φίλτρο `matomo.php` | Request στάλθηκε με tracking data | |
| 5 | Matomo dashboard → Real-time | Visit **εμφανίζεται** | |

---

## 2. Mode: `tracking_consent`

### 2.1 Νέος χρήστης — Banner εμφάνιση

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Admin config → **Πλήρης συγκατάθεση** → Save | | |
| 2 | Clear cookies + Incognito, άνοιξε σελίδα | **Banner εμφανίζεται** με κουμπιά Accept / Decline | |
| 3 | DevTools → Network → `matomo.php` | **Κανένα request** δεν στάλθηκε | |
| 4 | DevTools → Cookies | **Κανένα** Matomo cookie (`_pk_id`, `_pk_ses`) | |
| 5 | Matomo dashboard | **Κανένα** visit | |

### 2.2 Accept

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Πάτα **Accept** | Banner εξαφανίζεται | |
| 2 | DevTools → Cookies | Cookie `mtm_consent` **δημιουργήθηκε** | |
| 3 | DevTools → Network → `matomo.php` | Request στάλθηκε **τώρα** | |
| 4 | Matomo dashboard | Visit **εμφανίζεται** | |
| 5 | Κάνε reload τη σελίδα | Banner **ΔΕΝ** εμφανίζεται ξανά | |
| 6 | Πλοηγήσου σε 2-3 σελίδες | Κάθε pageview **καταγράφεται** στο Matomo | |

### 2.3 Decline

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Clear cookies, reload | Banner εμφανίζεται | |
| 2 | Πάτα **Decline** | Banner εξαφανίζεται | |
| 3 | DevTools → Cookies | Cookie `mtm_tracking_declined` **δημιουργήθηκε** (365 ημέρες) | |
| 4 | DevTools → Cookies | **Κανένα** `mtm_consent`, `_pk_id`, `_pk_ses` | |
| 5 | DevTools → Network → `matomo.php` | **Κανένα** request | |
| 6 | Matomo dashboard | **Κανένα** visit | |
| 7 | Reload σελίδα | Banner **ΔΕΝ** εμφανίζεται | |
| 8 | Πλοηγήσου σε 2-3 σελίδες | **Κανένα** tracking — σιωπή στο Matomo | |

### 2.4 Χρήστης που αγνοεί το banner

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Clear cookies, reload | Banner εμφανίζεται | |
| 2 | **Μην πατήσεις τίποτα** — πλοηγήσου σε άλλη σελίδα | Banner **εμφανίζεται ξανά** | |
| 3 | DevTools → Network | **Κανένα** `matomo.php` request | |

---

## 3. Mode: `cookie_consent`

### 3.1 Νέος χρήστης — Ανώνυμο tracking

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Admin config → **Συγκατάθεση cookies μόνο** → Save | | |
| 2 | Clear cookies + Incognito, άνοιξε σελίδα | **Banner εμφανίζεται** | |
| 3 | DevTools → Network → `matomo.php` | Request **στάλθηκε** (ανώνυμο tracking) | |
| 4 | DevTools → Cookies | **Κανένα** `_pk_id`, `_pk_ses` (cookies blocked) | |
| 5 | Matomo dashboard | Visit **εμφανίζεται** αλλά χωρίς visitor ID | |

### 3.2 Accept

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Πάτα **Accept** | Banner εξαφανίζεται | |
| 2 | DevTools → Cookies | `mtm_cookie_consent` **δημιουργήθηκε** | |
| 3 | DevTools → Cookies | `_pk_id`, `_pk_ses` **δημιουργήθηκαν** (Matomo tracking cookies) | |
| 4 | Reload + πλοηγήσου | Banner δεν εμφανίζεται, πλήρες tracking | |
| 5 | Matomo dashboard | Visits με **visitor ID** — unique visitor αναγνωρίζεται | |

### 3.3 Decline

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Clear cookies, reload | Banner εμφανίζεται | |
| 2 | Πάτα **Decline** | Banner εξαφανίζεται | |
| 3 | DevTools → Cookies | `mtm_cookie_declined` **δημιουργήθηκε** | |
| 4 | DevTools → Cookies | **Κανένα** `_pk_id`, `_pk_ses` | |
| 5 | DevTools → Network → `matomo.php` | Requests **στέλνονται** (ανώνυμο tracking συνεχίζεται) | |
| 6 | Reload | Banner **ΔΕΝ** εμφανίζεται, ανώνυμο tracking συνεχίζεται | |
| 7 | Matomo dashboard | Pageviews **καταγράφονται** αλλά κάθε visit = νέος visitor | |

---

## 4. Mode: `opt_out`

### 4.1 Νέος χρήστης — Default tracking

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Admin config → **Opt-out** → Save | | |
| 2 | Clear cookies + sessionStorage, reload | **Banner εμφανίζεται** με κουμπί "Εξαίρεση από την παρακολούθηση" + × | |
| 3 | DevTools → Network → `matomo.php` | Request **στάλθηκε** (πλήρες tracking) | |
| 4 | DevTools → Cookies | `_pk_id`, `_pk_ses` **υπάρχουν** | |
| 5 | Matomo dashboard | Visit **εμφανίζεται** κανονικά | |

### 4.2 Dismiss (×)

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Πάτα **×** | Banner εξαφανίζεται | |
| 2 | DevTools → Session Storage | `cookieConsentBannerDismissed = '1'` | |
| 3 | Reload (ίδιο tab) | Banner **ΔΕΝ** εμφανίζεται | |
| 4 | Tracking | **Συνεχίζεται** κανονικά | |
| 5 | Άνοιξε **νέο tab** στο ίδιο site | Banner **εμφανίζεται ξανά** (νέο sessionStorage) | |

### 4.3 Opt Out

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Clear sessionStorage, reload | Banner εμφανίζεται | |
| 2 | Πάτα **Εξαίρεση από την παρακολούθηση** | Κουμπί αλλάζει σε **Επαναφορά παρακολούθησης** | |
| 3 | Πλοηγήσου σε νέα σελίδα | DevTools → Network: **κανένα** `matomo.php` request | |
| 4 | Matomo dashboard | **Κανένα** νέο visit | |

### 4.4 Resume Tracking

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Πάτα **Επαναφορά παρακολούθησης** | Κουμπί αλλάζει σε **Εξαίρεση...** | |
| 2 | Πλοηγήσου σε νέα σελίδα | `matomo.php` requests **ξανα-στέλνονται** | |
| 3 | Matomo dashboard | Visits **εμφανίζονται** ξανά | |

---

## 5. Εναλλαγές mode (cross-mode transitions)

**Σημαντικό:** Σε αυτά τα tests μη κάνεις clear cookies — θέλουμε να δούμε αν τα παλιά cookies δημιουργούν πρόβλημα.

### 5.1 `tracking_consent` → `cookie_consent` (Decline χρήστης)

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Mode = tracking_consent, clear cookies, reload | Banner εμφανίζεται | |
| 2 | Πάτα **Decline** | `mtm_tracking_declined` cookie δημιουργείται | |
| 3 | Admin config → **cookie_consent** → Save | | |
| 4 | Reload σελίδα (χωρίς clear cookies!) | **Banner εμφανίζεται ξανά** (νέο mode, νέο decline cookie) | |
| 5 | DevTools → Cookies | `mtm_tracking_declined` υπάρχει ακόμα, `mtm_cookie_declined` **δεν** υπάρχει | |

> Αυτό είναι το fix που εφαρμόστηκε — πριν, ο χρήστης δεν θα έβλεπε banner.

### 5.2 `tracking_consent` → `cookie_consent` (Accept χρήστης)

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Mode = tracking_consent, clear cookies, reload, **Accept** | `mtm_consent` cookie | |
| 2 | Admin config → **cookie_consent** → Save | | |
| 3 | Reload (χωρίς clear cookies) | **Banner εμφανίζεται ξανά** (δεν υπάρχει `mtm_cookie_consent`) | |

### 5.3 `cookie_consent` → `tracking_consent` (Decline χρήστης)

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Mode = cookie_consent, clear cookies, reload, **Decline** | `mtm_cookie_declined` cookie | |
| 2 | Admin config → **tracking_consent** → Save | | |
| 3 | Reload (χωρίς clear cookies) | **Banner εμφανίζεται ξανά** | |
| 4 | DevTools → Network | **Κανένα** `matomo.php` request (requireConsent active) | |

### 5.4 `tracking_consent` → `disabled`

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Mode = tracking_consent, clear cookies, reload, **Decline** | | |
| 2 | Admin config → **disabled** → Save | | |
| 3 | Reload | **Κανένα banner**, πλήρες tracking | |
| 4 | DevTools → Network | `matomo.php` request **στέλνεται** | |

> Αναμενόμενη συμπεριφορά — ο admin απενεργοποίησε consent.

### 5.5 `consent mode` → `opt_out` (Decline χρήστης)

| # | Βήμα | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Mode = tracking_consent, clear cookies, reload, **Decline** | | |
| 2 | Admin config → **opt_out** → Save | | |
| 3 | Reload | **Banner εμφανίζεται** (opt-out version) — tracking **ξεκινά αμέσως** | |
| 4 | Ο χρήστης μπορεί να πατήσει **Εξαίρεση** αν δεν θέλει | | |

---

## 6. UI / UX έλεγχοι

| # | Έλεγχος | Αναμενόμενο | Check |
|---|---|---|---|
| 1 | Banner εμφάνιση σε **mobile** (responsive < 576px) | Κουμπιά σε column layout, κεντραρισμένα | |
| 2 | Banner εμφάνιση σε **desktop** | Κουμπιά δίπλα στο κείμενο, μία γραμμή | |
| 3 | Banner **z-index** | Εμφανίζεται πάνω από footer, content, Botaki | |
| 4 | Banner κείμενο σε **Ελληνικά** | Μετάφραση σωστή (Αποδοχή/Απόρριψη/Εξαίρεση) | |
| 5 | Link **Πολιτική Cookies** | Εμφανίζεται μόνο αν υπάρχει CKAN page configured | |
| 6 | Banner δεν εμφανίζεται σε `/ckan-admin/` σελίδες | Ίδια συμπεριφορά — εμφανίζεται παντού (αν αυτό θέλουμε) | |

---

## 7. Matomo dashboard — Επαλήθευση δεδομένων

Αφού τρέξεις τα παραπάνω, τσέκαρε στο Matomo:

| # | Έλεγχος στο Matomo | Που βρίσκεται | Τι ψάχνεις |
|---|---|---|---|
| 1 | **Visits Log** | Visitors → Visits Log | Τα visits από Accept χρήστες εμφανίζονται με visitor ID |
| 2 | **Real-time** | Visitors → Real-time | Live tracking λειτουργεί μετά Accept |
| 3 | **Visitor profile** (cookie_consent Accept) | Κλικ σε visitor | Unique visitor αναγνωρίζεται, returning visits |
| 4 | **Visitor profile** (cookie_consent πριν Accept) | Visitors → Real-time | Visits χωρίς visitor ID — κάθε pageview = νέος |
| 5 | **Downloads** | Behaviour → Downloads | Downloads καταγράφονται σε cookie_consent (ακόμα χωρίς Accept) |
| 6 | **Referrers** | Acquisition → All Channels | Referrers καταγράφονται σε cookie_consent |
| 7 | **Consents** (αν υπάρχει plugin) | Privacy → Consents | Consent events recorded |

---

## 8. Edge cases

| # | Σενάριο | Βήματα | Αναμενόμενο | Check |
|---|---|---|---|---|
| 1 | **JavaScript disabled** | Disable JS στο browser, reload | Banner δεν εμφανίζεται, Matomo δεν λειτουργεί (JS tracker) | |
| 2 | **3rd party cookies blocked** | Browser settings: block 3rd party | Δεν αλλάζει τίποτα — Matomo χρησιμοποιεί 1st party cookies | |
| 3 | **Incognito mode** | Άνοιξε incognito | Banner εμφανίζεται πάντα (κανένα cookie) | |
| 4 | **Πολλαπλά tabs** | Tab 1: Accept. Tab 2: reload | Tab 2: Banner **δεν** εμφανίζεται (cookie υπάρχει ήδη) | |
| 5 | **Cookie expiry** | Θέσε ημερομηνία browser +366 ημέρες (ή περίμενε) | Decline cookie λήγει → banner ξαναεμφανίζεται | |
| 6 | **Admin config save χωρίς Matomo plugin** | Αφαίρεσε matomo plugin, τσέκαρε admin | `h.matomo_consent_mode()` θα κάνει error ή fallback | |

---

## Checklist ολοκλήρωσης

- [ ] `disabled` — κανένα banner, πλήρες tracking
- [ ] `tracking_consent` Accept — banner → accept → πλήρες tracking
- [ ] `tracking_consent` Decline — banner → decline → μηδέν tracking
- [ ] `tracking_consent` αγνόηση — banner παραμένει, μηδέν tracking
- [ ] `cookie_consent` Accept — banner → accept → πλήρες tracking με cookies
- [ ] `cookie_consent` Decline — banner → decline → ανώνυμο tracking χωρίς cookies
- [ ] `cookie_consent` αγνόηση — banner παραμένει, ανώνυμο tracking
- [ ] `opt_out` dismiss — banner κλείνει, tracking συνεχίζεται
- [ ] `opt_out` εξαίρεση — tracking σταματάει
- [ ] `opt_out` επαναφορά — tracking ξαναρχίζει
- [ ] Εναλλαγή tracking↔cookie (decline) — banner εμφανίζεται ξανά
- [ ] Εναλλαγή consent→disabled — tracking αμέσως, κανένα banner
- [ ] Εναλλαγή consent→opt_out (decline) — banner opt-out εμφανίζεται
- [ ] Mobile responsive
- [ ] Ελληνική μετάφραση
- [ ] Matomo dashboard δεδομένα σωστά
