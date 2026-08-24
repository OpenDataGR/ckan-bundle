# MQA Visibility Configuration

Το data.gov.gr υποστηρίζει παραμετροποίηση της ορατότητας του MQA (Metadata Quality Assessment) μέσω της επιλογής:

```ini
ckanext.data_gov_gr.dataset.mqa_visibility = hidden
```

## Διαθέσιμες Τιμές

### `hidden`

Το MQA δεν εμφανίζεται στους χρήστες.

Με αυτή την επιλογή:

- δεν εμφανίζεται το MQA tab στη σελίδα dataset
- δεν είναι διαθέσιμη η απευθείας σελίδα `/dataset/mqa/<dataset-name>`
- δεν εμφανίζεται το φίλτρο αναζήτησης για ποιότητα μεταδεδομένων
- η αναφορά `Metadata Quality` δεν εμφανίζεται

Αυτή είναι η ασφαλής προεπιλογή όταν δεν έχει οριστεί κάποια σχετική ρύθμιση.

```ini
ckanext.data_gov_gr.dataset.mqa_visibility = hidden
```

### `public`

Το MQA εμφανίζεται κανονικά σε όσους μπορούν να δουν το dataset.

Με αυτή την επιλογή:

- το MQA tab εμφανίζεται στα δημόσια datasets
- η απευθείας σελίδα `/dataset/mqa/<dataset-name>` είναι διαθέσιμη σε όσους μπορούν να δουν το dataset
- το φίλτρο αναζήτησης για ποιότητα μεταδεδομένων εμφανίζεται στην αναζήτηση
- η αναφορά `Metadata Quality` εμφανίζεται κανονικά
- τα private datasets συνεχίζουν να ακολουθούν τα κανονικά δικαιώματα πρόσβασης του CKAN

```ini
ckanext.data_gov_gr.dataset.mqa_visibility = public
```

### `organization_members`

Το MQA εμφανίζεται μόνο σε εσωτερικούς χρήστες της πύλης.

Ως εσωτερικοί χρήστες θεωρούνται:

- sysadmins
- συνδεδεμένοι χρήστες που ανήκουν σε τουλάχιστον έναν οργανισμό, με οποιονδήποτε ρόλο

Με αυτή την επιλογή:

- anonymous χρήστες δεν βλέπουν το MQA tab
- logged-in χρήστες χωρίς συμμετοχή σε οργανισμό δεν βλέπουν το MQA tab
- μέλη οποιουδήποτε οργανισμού βλέπουν MQA σε datasets που μπορούν ήδη να δουν
- private datasets παραμένουν ορατά μόνο σε όσους έχουν κανονική πρόσβαση σε αυτά μέσω CKAN
- το φίλτρο αναζήτησης για ποιότητα μεταδεδομένων εμφανίζεται μόνο σε sysadmins και μέλη οργανισμών
- η αναφορά `Metadata Quality` εμφανίζεται μόνο σε sysadmin χρήστες

```ini
ckanext.data_gov_gr.dataset.mqa_visibility = organization_members
```

## Αναφορά Metadata Quality

Η συνολική αναφορά `Metadata Quality` ακολουθεί ξεχωριστή πολιτική από το dataset tab:

- με `hidden`, δεν εμφανίζεται
- με `public`, εμφανίζεται κανονικά
- με `organization_members`, εμφανίζεται μόνο σε sysadmin χρήστες

## Σελίδα Εργαλείων `/more`

Η κάρτα `Αναφορές ποιότητας Συνόλων Δεδομένων` στη σελίδα `/more` δεν ελέγχεται από αυτή τη ρύθμιση.

Η συμπεριφορά της παραμένει όπως έχει οριστεί από την υπάρχουσα παραμετροποίηση της πύλης.

## Εμφάνιση της Ρύθμισης στο Admin UI

Η επιλογή `ckanext.data_gov_gr.dataset.mqa_visibility` μπορεί να εμφανιστεί ως dropdown στο `/ckan-admin/config`, αλλά αυτό είναι απενεργοποιημένο από προεπιλογή.

Το dropdown εμφανίζεται μόνο αν ενεργοποιηθεί από το `ckan.ini`:

```ini
ckanext.data_gov_gr.dataset.mqa_visibility.admin_config_enabled = yes
```

Αν η παραπάνω επιλογή λείπει ή είναι `no`, το dropdown δεν εμφανίζεται στο admin UI.

Η επιλογή `admin_config_enabled` είναι ini-only και δεν εμφανίζεται ως πεδίο στο `/ckan-admin/config`.

## Περιορισμός Επιλογών στο Admin UI

Οι διαθέσιμες επιλογές του dropdown μπορούν να περιοριστούν από το `ckan.ini` με την ini-only επιλογή:

```ini
ckanext.data_gov_gr.dataset.mqa_visibility.allowed_values = hidden,organization_members
```

Οι τιμές γράφονται comma-separated και μπορούν να είναι:

- `hidden`
- `public`
- `organization_members`

Αν η επιλογή λείπει ή είναι κενή, το dropdown επιτρέπει από προεπιλογή μόνο:

```ini
hidden,organization_members
```

Για να επιτρέπεται και η επιλογή `public` στο admin UI, πρέπει να δηλωθεί ρητά:

```ini
ckanext.data_gov_gr.dataset.mqa_visibility.allowed_values = hidden,public,organization_members
```

Αν δηλωθεί μόνο μία τιμή, το dropdown περιορίζεται μόνο σε αυτή την επιλογή:

```ini
ckanext.data_gov_gr.dataset.mqa_visibility.allowed_values = hidden
```

ή:

```ini
ckanext.data_gov_gr.dataset.mqa_visibility.allowed_values = organization_members
```

Ο ίδιος περιορισμός εφαρμόζεται και στο backend validation του `/ckan-admin/config`, ώστε να μην μπορεί να αποθηκευτεί μη επιτρεπτή τιμή μέσω χειροκίνητου POST.

Για νέες εγκαταστάσεις, ορίστε πρώτα το `allowed_values` στο `ckan.ini` και μετά ενεργοποιήστε ή χρησιμοποιήστε το dropdown. Η ρύθμιση αυτή δεν μεταναστεύει ούτε διορθώνει αυτόματα παλιές τιμές που έχουν ήδη αποθηκευτεί πριν εφαρμοστεί ο περιορισμός.

## Συμβατότητα με Παλαιότερη Ρύθμιση

Η παλαιότερη επιλογή εξακολουθεί να υποστηρίζεται:

```ini
ckanext.data_gov_gr.dataset.hide_mqa_tab = yes
```

Αν δεν έχει οριστεί το νέο `ckanext.data_gov_gr.dataset.mqa_visibility`, τότε:

- `hide_mqa_tab = yes` αντιστοιχεί σε `mqa_visibility = hidden`
- `hide_mqa_tab = no` αντιστοιχεί σε `mqa_visibility = public`

Για νέες εγκαταστάσεις ή νέες αλλαγές προτείνεται να χρησιμοποιείται το `mqa_visibility`, επειδή εκφράζει καθαρά όλες τις διαθέσιμες επιλογές.
