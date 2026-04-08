# ckanext-orgreport

CKAN extension - Αναφορά Κατάστασης Email Φορέων.

Χρησιμοποιεί το **ckanext-report** `IReport` interface για caching,
CSV/JSON export και ενιαία σελίδα αναφορών.

## Τι κάνει

- Πίνακας με όλους τους φορείς και αν έχουν email ή όχι
- Σύνοψη στατιστικών (σύνολο / με email / χωρίς email)
- Φιλτράρισμα (όλοι / χωρίς email / με email)
- Ταξινόμηση στηλών (κατάσταση, φορέας, email) με click στα headers
- Client-side pagination (20, 50, 100, όλα)
- Φίλτρο κατά organization (option filtering μέσω ckanext-report)
- CSV/JSON export αυτόματα
- Cache σε πίνακα `data_cache`: δεν τρέχει query σε κάθε page load
- Πρόσβαση μόνο για sysadmin

## Απαιτήσεις

- CKAN >= 2.11
- ckanext-report (`pip install -e git+https://github.com/ckan/ckanext-report.git#egg=ckanext-report`)

## Εγκατάσταση

```bash
# Ενεργοποίηση virtualenv
. /usr/lib/ckan/default/bin/activate

# Εγκατάσταση ckanext-report (αν δεν υπάρχει ήδη)
pip install -e git+https://github.com/ckan/ckanext-report.git#egg=ckanext-report

# Αρχικοποίηση DB tables του ckanext-report
ckan -c /etc/ckan/default/ckan.ini report initdb

# Εγκατάσταση orgreport
cd /usr/lib/ckan/default/src/ckanext-orgreport
pip install -e .

# Προσθήκη στο ckan.ini (μετά το report)
# ckan.plugins = ... report orgreport

# Restart
sudo supervisorctl restart all
```

## Δομή αρχείων

```
ckanext-orgreport/
├── setup.py
├── MANIFEST.in
├── README.md
└── ckanext/
    ├── __init__.py
    └── orgreport/
        ├── __init__.py
        ├── plugin.py          # IReport + IConfigurer
        ├── reports.py         # generate function + report_info
        └── templates/
            └── report/
                └── org_email_status.html   # template αναφοράς
```

## Χρήση

### Web

Η αναφορά εμφανίζεται στο:
```
https://your-ckan.gr/report/org-email-status
```

Και στη λίστα αναφορών (μόνο για sysadmin):
```
https://your-ckan.gr/report
```

### CLI - Generate cache

```bash
# Όλα τα reports
ckan -c /etc/ckan/default/ckan.ini report generate

# Μόνο αυτό το report
ckan -c /etc/ckan/default/ckan.ini report generate org-email-status
```

Σημείωση: Το generate δημιουργεί cache entry για κάθε οργανισμό (option combinations).
Με 229 φορείς, δημιουργούνται 230 entries (229 + 1 για "όλοι").

### Nightly cron

```bash
0 3 * * * /usr/lib/ckan/default/bin/ckan -c /etc/ckan/default/ckan.ini report generate org-email-status
```

## Σημειώσεις

- Η `organization_list` επιστρέφει μέχρι `ckan.group_and_organization_list_max` 
  οργανισμούς (default: 1000). Αν ξεπεράσεις αυτό το όριο, πρέπει να αυξήσεις 
  την τιμή στο ckan.ini ή να προσαρμοστεί ο κώδικας με pagination.