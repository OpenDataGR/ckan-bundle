import hashlib
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import ckan.plugins as p
from ckan import model
from ckan.model import Session
from ckan.plugins.toolkit import config
from ckanext.harvest.harvesters.ckanharvester import CKANHarvester
from ckanext.harvest.model import HarvestObject

log = logging.getLogger(__name__)

class AtticaOpenDataHarvester(CKANHarvester):
    """
    Custom harvester for Attica Region Open Data portal
    Harvests from https://opendata.attica.gov.gr/content
    """

    def _create_or_update_package(self, package_dict, harvest_object, package_dict_form='package_show'):
        """
        Override της parent μεθόδου για να αποφύγουμε το deprecated REST API
        """

        try:
            user_name = self._get_user_name()
            context = {
                'model': model,
                'session': Session,
                'user': user_name,
                'ignore_auth': True,
            }

            # Check if package exists
            try:
                existing_package_dict = self._find_existing_package(package_dict)

                # In case name has been modified when first importing
                package_dict['name'] = existing_package_dict['name']

                # Check modified date
                if 'metadata_modified' not in package_dict or \
                        package_dict['metadata_modified'] > existing_package_dict.get('metadata_modified'):
                    log.info(f'Package with GUID {harvest_object.guid} exists and needs to be updated')

                    # Update package
                    context.update({'id': package_dict['id']})
                    package_dict.setdefault('name', existing_package_dict['name'])

                    # Always use package_update (modern API)
                    new_package = p.toolkit.get_action('package_update')(context, package_dict)
                else:
                    log.info(f'No changes to package with GUID {harvest_object.guid}, skipping...')
                    return 'unchanged'

                # Flag the other objects linking to this package as not current anymore
                Session.query(HarvestObject).filter(
                    HarvestObject.package_id == new_package["id"]).update(
                    {"current": False})

                # Flag this as the current harvest object
                harvest_object.package_id = new_package['id']
                harvest_object.current = True
                harvest_object.save()

            except p.toolkit.ObjectNotFound:
                # Package needs to be created

                # Get rid of auth audit on the context
                context.pop('__auth_audit', None)

                # Set name for new package to prevent name conflict
                if package_dict.get('name', None):
                    package_dict['name'] = self._gen_new_name(package_dict['name'])
                else:
                    package_dict['name'] = self._gen_new_name(package_dict['title'])

                log.info(f'Package with GUID {harvest_object.guid} does not exist, creating it')

                # ΜΗΝ ορίζουμε harvest_object.package_id εδώ!
                # harvest_object.current = True  # Θα το ορίσουμε μετά
                # harvest_object.package_id = package_dict['id']  # ΑΥΤΟ προκαλεί θέμα!

                # Create the package ΠΡΩΤΑ
                new_package = p.toolkit.get_action('package_create')(context, package_dict)

                # ΤΩΡα ορίζουμε το harvest object με το σωστό package ID
                harvest_object.package_id = new_package['id']
                harvest_object.current = True
                harvest_object.save()

            Session.commit()
            return True

        except p.toolkit.ValidationError as e:
            log.exception(e)
            self._save_object_error(f'Invalid package with GUID {harvest_object.guid}: {e.error_dict}',
                                    harvest_object, 'Import')
        except Exception as e:
            log.exception(e)
            self._save_object_error(f'{str(e)}', harvest_object, 'Import')

        return None

    # ##################################################################################################################

    def info(self):
        return {
            'name': 'attica_opendata',
            'title': 'Attica Open Data Harvester',
            'description': 'Harvester for Attica Region Open Data portal (opendata.attica.gov.gr)'
        }

    # ##################################################################################################################

    def gather_stage(self, harvest_job):
        """
        Gather all dataset URLs from the specified page range
        """
        log.debug('In AtticaOpenDataHarvester gather_stage')

        seen_urls = set()
        dataset_urls = []

        # Get configuration
        source_config = self._get_source_config(harvest_job.source.config)
        base_url = harvest_job.source.url.rstrip('/')

        # Get page range from config (default 1-30)
        start_page = source_config.get('start_page', 1)
        end_page = source_config.get('end_page', 30)

        empty_pages_in_a_row = 0

        # Iterate through pages
        for page_num in range(start_page, end_page + 1):
            page_url = f"{base_url}?page={page_num}"
            log.info(f"Gathering datasets from page {page_num}: {page_url}")

            try:
                response = requests.get(page_url, timeout=30)
                response.raise_for_status()

                # Parse HTML with BeautifulSoup
                soup = BeautifulSoup(response.content, 'html.parser')

                # Find dataset items
                dataset_items = soup.find_all('li', class_='dataset-item')

                if not dataset_items:
                    empty_pages_in_a_row += 1
                    log.warning(f"No dataset items found on page {page_num} (empty_pages_in_a_row={empty_pages_in_a_row})")

                    if empty_pages_in_a_row >= 3:
                        log.info(
                            f"No dataset items found for {empty_pages_in_a_row} consecutive pages. "
                            f"Stopping gather at page {page_num}."
                        )
                        break

                    continue

                # Αν βρήκες datasets, μηδένισε τον counter
                empty_pages_in_a_row = 0

                # Extract dataset URLs
                for item in dataset_items:
                    dataset_heading = item.find('h3', class_='dataset-heading')
                    if dataset_heading:
                        link = dataset_heading.find('a')
                        if link and link.get('href'):
                            dataset_url = link['href']
                            if not dataset_url.startswith('http'):
                                dataset_url = urljoin(base_url, dataset_url)
                            if dataset_url not in seen_urls:
                                # Μέριμνα για αποφυγή αποθήκευσης ως harvest object dataset που έχει ήδη καταχωρηθεί
                                seen_urls.add(dataset_url)
                                dataset_urls.append(dataset_url)
                            else:
                                log.debug(f"Duplicate dataset URL skipped: {dataset_url}")
                            log.debug(f"Found dataset: {dataset_url}")

                log.info(f"Found {len(dataset_items)} datasets on page {page_num}")

            except Exception as e:
                log.error(f"Error gathering from page {page_num}: {str(e)}")
                continue

        log.info(f"Total datasets found: {len(dataset_urls)}")

        # Create harvest objects
        object_ids = []
        for dataset_url in dataset_urls:
            obj = HarvestObject(
                guid=dataset_url,
                job=harvest_job,
                content=dataset_url
            )
            obj.save()
            object_ids.append(obj.id)

        return object_ids

    # ##################################################################################################################

    def fetch_stage(self, harvest_object):
        """
        Fetch the dataset page and extract metadata
        """
        log.debug('In AtticaOpenDataHarvester fetch_stage')

        dataset_url = harvest_object.content
        log.info(f"Fetching dataset: {dataset_url}")

        try:
            response = requests.get(dataset_url, timeout=30)
            response.raise_for_status()

            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract dataset metadata
            dataset_data = self._extract_dataset_metadata(soup, dataset_url)

            # Store as JSON in harvest object
            harvest_object.content = json.dumps(dataset_data)
            harvest_object.save()

            return True

        except Exception as e:
            log.error(f"Error fetching {dataset_url}: {str(e)}")
            self._save_object_error(f'Error fetching dataset: {str(e)}', harvest_object, 'Fetch')
            return False

    # ##################################################################################################################

    def import_stage(self, harvest_object):
        """
        Import the dataset into CKAN
        """
        log.debug('In AtticaOpenDataHarvester import_stage')

        try:
            dataset_data = json.loads(harvest_object.content)

            # Convert to CKAN package dict format
            package_dict = self._convert_to_ckan_package(dataset_data)
            # Ορίζουμε τον οργανισμό από το harvest source
            # Ορίζουμε τον οργανισμό από το harvest source package
            try:
                source_pkg = model.Package.get(harvest_object.job.source.id)
                if source_pkg and source_pkg.owner_org:
                    package_dict['owner_org'] = source_pkg.owner_org
                    log.info(f'Set owner_org from source package: {source_pkg.owner_org}')
                else:
                    log.warning("No organization set for harvest source")
            except Exception as e:
                log.warning(f'Could not get owner_org from harvest source: {str(e)}')

            # Import using parent class method
            return self._create_or_update_package(package_dict, harvest_object)

        except Exception as e:
            log.error(f"Error importing dataset: {str(e)}")
            self._save_object_error(f'Error importing dataset: {str(e)}', harvest_object, 'Import')
            return False

    # ##################################################################################################################

    def _extract_dataset_metadata(self, soup, dataset_url):
        """
        Extract dataset metadata from HTML soup (individual dataset page)
        """
        dataset_data = {
            'url': dataset_url,
            'resources': []
        }

        # Βασικά πεδία (τίτλος, περιγραφή, created/updated από main sections)
        self._extract_basic_metadata(dataset_data, soup)

        # Πόροι (resources) + εμπλουτισμός από resource pages
        self._extract_resources(dataset_data, soup, dataset_url)

        # Επιπλέον πληροφορίες από τον πίνακα "additional-info"
        self._extract_additional_info(dataset_data, soup)

        # Οργάνωση & κατηγορία από το URL
        self._extract_org_and_category(dataset_data, dataset_url)

        # Όνομα/slug (με βάση το URL)
        dataset_data['name'] = self._generate_dataset_name(dataset_url)

        # Default τιμές για πεδία που λείπουν
        self._apply_default_values(dataset_data)

        # Tags από το HTML (έχεις ήδη ξεχωριστή μέθοδο)
        tags = self._extract_tags(soup)
        if tags:
            dataset_data['tags'] = tags

        return dataset_data

    def _extract_basic_metadata(self, dataset_data, soup):
        """
        Εξαγωγή βασικών μεταδεδομένων από τα κύρια sections της σελίδας
        (τίτλος, περιγραφή, ημερομηνίες).
        """
        # Extract title from h1
        title_h1 = soup.find('h1')
        if title_h1:
            dataset_data['title'] = title_h1.get_text().strip()

        # Extract description from .description div
        description_div = soup.find('div', class_='description')
        if description_div:
            description_p = description_div.find('p')
            if description_p:
                dataset_data['notes'] = description_p.get_text().strip()
            else:
                dataset_data['notes'] = description_div.get_text().strip()

        # Extract datetime information (πχ ημερομηνία δημιουργίας)
        datetime_div = soup.find('div', class_='datetime')
        if datetime_div:
            dataset_data['metadata_created'] = datetime_div.get_text().strip()

        # Extract last updated info
        updated_span = soup.find('span', class_='updated')
        if updated_span:
            # Extract the date after "Τελευταία ανανέωση:"
            updated_text = updated_span.get_text().strip()
            if 'Τελευταία ανανέωση:' in updated_text:
                dataset_data['metadata_modified'] = updated_text.replace(
                    'Τελευταία ανανέωση:', ''
                ).strip()

    def _extract_resources(self, dataset_data, soup, dataset_url):
        """
        Εξαγωγή λίστας resources από το #dataset-resources section.
        Εμπλουτισμός κάθε resource από τη σελίδα του.
        """
        resources_section = soup.find('section', id='dataset-resources')
        if not resources_section:
            return

        resource_items = resources_section.find_all('li', class_='resource-item')
        for item in resource_items:
            resource_data = self._extract_single_resource(item, dataset_url)

            # Εμπλουτισμός από τη σελίδα του resource
            if resource_data.get('page_url'):
                self._enrich_resource_from_page(resource_data, resource_data['page_url'])

            dataset_data['resources'].append(resource_data)

    def _extract_single_resource(self, item, dataset_url):
        """
        Εξαγωγή δεδομένων για ένα resource item.
        """
        # Get resource name from p.heading a
        heading_p = item.find('p', class_='heading')
        resource_name = ''
        resource_page_url = ''
        if heading_p:
            heading_link = heading_p.find('a')
            if heading_link:
                resource_name = heading_link.get_text().strip()
                resource_page_url = heading_link.get('href', '')

        # Normalise σε πλήρες URL για τη σελίδα του resource
        if resource_page_url and not resource_page_url.startswith('http'):
            resource_page_url = urljoin(dataset_url, resource_page_url)

        # Get format from span.format-label
        format_span = item.find('span', class_='format-label')
        resource_format = ''
        if format_span:
            resource_format = format_span.get_text().strip()

        # --- Dropdown links: Download & Αναδρομολόγηση ---

        download_link = None
        redirect_link = None
        preview_link = None

        dropdown_menu = item.find('ul', class_='dropdown-menu')
        if dropdown_menu:
            for link in dropdown_menu.find_all('a', class_='dropdown-item'):
                link_text = link.get_text(strip=True)
                if 'Download' in link_text:
                    download_link = link
                elif 'Αναδρομολόγηση' in link_text:
                    redirect_link = link
                elif 'Προεπισκόπηση' in link_text:
                    preview_link = link

        # Default τιμή: αν δεν βρούμε κάτι άλλο, χρησιμοποιούμε τη σελίδα του resource
        actual_download_url = resource_page_url
        download_url = None
        redirect_url = None
        preview_url = None

        # Αν υπάρχει Download, παίρνουμε αυτό το href
        if download_link:
            download_url = download_link.get('href', '') or ''
            if download_url and not download_url.startswith('http'):
                download_url = urljoin(dataset_url, download_url)
            actual_download_url = download_url

        # Αν υπάρχει Αναδρομολόγηση, παίρνουμε αυτό το href
        if redirect_link:
            redirect_url = redirect_link.get('href', '') or ''
            if redirect_url and not redirect_url.startswith('http'):
                redirect_url = urljoin(dataset_url, redirect_url)

        # Αν υπάρχει Προεπισκόπηση, πάντα θα υπάρχει, παίρνουμε αυτό το href
        if preview_link:
            preview_url = preview_link.get('href', '') or ''
            if preview_url and not preview_url.startswith('http'):
                preview_url = urljoin(dataset_url, preview_url)

        # Get filename from a.description
        description_link = item.find('a', class_='description')
        filename = ''
        if description_link:
            filename_text = description_link.get_text().strip()
            # Remove format label from filename
            if format_span:
                filename = filename_text.replace(format_span.get_text().strip(), '').strip()
            else:
                filename = filename_text

        resource_data = {
            'url': actual_download_url,  # αυτό θα πάει στο CKAN resource.url
            'page_url': resource_page_url,  # σελίδα του resource (file_page)
            'name': resource_name or filename,
            'format': resource_format,
            'description': resource_name,
            'filename': filename,
            'download_url': download_url,  # μόνο αν υπάρχει Download
            'redirect_url': redirect_url,  # μόνο αν υπάρχει Αναδρομολόγηση
            'preview_url': preview_url,
        }

        return resource_data

    def _extract_additional_info(self, dataset_data, soup):
        """
        Εξαγωγή μεταδεδομένων από το section #additional-info (πίνακας).
        Τυχόν τιμές εδώ υπερισχύουν των προηγούμενων.
        """
        additional_info_section = soup.find('section', id='additional-info')
        if not additional_info_section:
            return

        table = additional_info_section.find('table')
        if not table:
            return

        rows = table.find_all('tr')
        # Skip header row
        for row in rows[1:]:
            cells = row.find_all('td')
            if len(cells) < 2:
                continue

            field = cells[0].get_text().strip()
            value = cells[1].get_text().strip()

            if field == 'Ημερομηνία δημιουργίας':
                dataset_data['metadata_created'] = value
            elif field == 'Τελευταία αλλαγή':
                dataset_data['metadata_modified'] = value
            elif field == 'Υπεύθυνος συντήρησης':
                dataset_data['maintainer'] = value
            elif field == 'Κατηγορία υψηλής αξίας':
                dataset_data['high_value_category'] = value
            elif field == 'Άδεια χρήσης' and value != '-':
                dataset_data['license_title'] = value

    def _extract_org_and_category(self, dataset_data, dataset_url):
        """
        Εξαγωγή organization/category από το path του URL.
        Πχ /content/<org>/<category>/...
        """
        parsed_url = urlparse(dataset_url)
        path_parts = [p for p in parsed_url.path.split('/') if p]

        if len(path_parts) >= 3:
            dataset_data['organization'] = path_parts[1]
            dataset_data['category'] = path_parts[2]

    def _apply_default_values(self, dataset_data):
        """
        Θέτει default τιμές για βασικά πεδία αν δεν έχουν ήδη συμπληρωθεί.
        """
        if 'maintainer' not in dataset_data:
            dataset_data['maintainer'] = 'Περιφέρεια Αττικής'

        dataset_data.setdefault('author', 'Περιφέρεια Αττικής')
        dataset_data.setdefault('author_email', 'opendata@attica.gov.gr')
        dataset_data.setdefault('maintainer_email', 'opendata@attica.gov.gr')

        # Αν θέλεις και default license_id:
        # dataset_data.setdefault('license_id', 'other-open')

    def _enrich_resource_from_page(self, resource_data, resource_page_url):
        """
        Κάνει HTTP GET στη σελίδα του resource (file_page) και
        εμπλουτίζει το resource_data με metadata από το #additional-info.
        """
        try:
            resp = requests.get(resource_page_url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"Could not fetch resource page {resource_page_url}: {e}")
            return

        try:
            soup = BeautifulSoup(resp.content, 'html.parser')
            additional_info_section = soup.find('section', id='additional-info')
            if not additional_info_section:
                return

            table = additional_info_section.find('table')
            if not table:
                return

            rows = table.find_all('tr')
            for row in rows[1:]:  # skip header
                cells = row.find_all('td')
                if len(cells) < 2:
                    continue
                field = cells[0].get_text().strip()
                value = cells[1].get_text().strip()

                # Map ελληνικά labels σε keys του resource_data
                if field == 'Ημερομηνία καταχώρησης':
                    # θα το κρατήσουμε και ως plain string, και σε extra
                    resource_data['created'] = value
                elif field == 'Έτος':
                    resource_data['year'] = value
                elif field == 'Τύπος αρχείου':
                    # π.χ. XLS, CSV κλπ. Μπορεί να "διορθώσει" το format
                    resource_data.setdefault('format', value)
                    resource_data['file_type'] = value
                elif field == 'Mime type':
                    resource_data['mimetype'] = value
                elif field == 'Μέγεθος':
                    resource_data['size'] = value  # αφήνουμε το "28 KB" ως string
                elif field == 'SHA1 HASH':
                    resource_data['hash'] = value

        except Exception as e:
            log.warning(f"Error parsing resource page {resource_page_url}: {e}")

    def _extract_tags(self, soup):
        """
        Extract tags from the #tags section of the dataset page
        Επιστρέφει λίστα από strings (τα ονόματα των tags)
        """
        tags = []

        tags_section = soup.find('section', id='tags')
        if not tags_section:
            return tags

        tag_list = tags_section.find('ul', class_='tag-list')
        if not tag_list:
            return tags

        for li in tag_list.find_all('li'):
            # Προτιμάμε το κείμενο από το <span>, αν υπάρχει
            span = li.find('span')
            if span:
                tag_text = span.get_text(strip=True)
            else:
                a_tag = li.find('a', class_='tag')
                tag_text = a_tag.get_text(strip=True) if a_tag else ''

            if tag_text:
                tags.append(tag_text)

        return tags

    # ##################################################################################################################

    def _generate_package_id(self, dataset_url):
        """
        Generate a unique package ID from the dataset URL
        """
        # Δημιουργία hash από το URL για unique ID
        return hashlib.md5(dataset_url.encode('utf-8')).hexdigest()

    # ######################################################################################

    def _convert_to_ckan_package(self, dataset_data):
        """
        Convert extracted data (dataset_data) to CKAN package dict format.
        Περιμένει dataset_data με δομή όπως:

        {
          "author": "...",
          "author_email": "...",
          "category": "...",
          "high_value_category": "...",
          "maintainer": "...",
          "maintainer_email": "...",
          "metadata_created": "2025-03-27 10:42",
          "metadata_modified": "2025-03-27 11:44",
          "name": "attica-402-...",
          "notes": "....",
          "organization": "genikh-dieythynsh-...",
          "resources": [ { ... } ],
          "tags": ["Δειγματοληψίες – Ψεκασμοί"],
          "title": "Πρόγραμμα Καταπολέμησης ...",
          "url": "https://opendata.attica.gov.gr/..."
        }
        """

        # Βασικά πεδία πακέτου
        package_dict = self._build_base_package(dataset_data)

        # Κρατάμε την άδεια του dataset για χρήση στα resources
        package_license_id = dataset_data.get('license_title')

        if package_license_id:
            package_dict['license_id'] = 'other-open'

        # Translated πεδία για fluent plugin
        self._apply_translated_fields(package_dict)

        # Extras για να μην χαθούν custom πεδία από το τρίτο σύστημα
        extras = self._build_extras(dataset_data)

        # DCAT / HVD / temporal / spatial / contact / publisher κτλ.
        self._apply_dcat_fields(package_dict, dataset_data)

        if extras:
            package_dict['extras'] = extras

        # Resources – αξιοποίηση των επιπλέον πεδίων (download_url, mimetype, size κτλ.)
        self._attach_resources(package_dict, dataset_data, package_license_id)

        # Tags – συνδυασμός tags, high_value_category, generic
        self._attach_tags(package_dict, dataset_data)

        return package_dict

    def _build_base_package(self, dataset_data):
        """
        Βασική δημιουργία του package_dict.
        """
        package_dict = {
            # Unique hash ID βασισμένο στο URL (ή στο name fallback)
            'id': self._generate_package_id(
                dataset_data.get('url') or dataset_data.get('name')
            ),

            'name': dataset_data.get('name'),
            'title': dataset_data.get('title'),
            'notes': dataset_data.get('notes', '') or '',
            'url': dataset_data.get('url'),

            # Αν δεν έχει έρθει license_id από το HTML/JSON, μπορείς να βάλεις default
            'license_id': dataset_data.get('license_id'),

            'author': dataset_data.get('author'),
            'author_email': dataset_data.get('author_email'),
            'maintainer': dataset_data.get('maintainer'),
            'maintainer_email': dataset_data.get('maintainer_email'),

            'resources': []
        }
        return package_dict

    def _apply_translated_fields(self, package_dict):
        """
        Ορισμός title_translated / notes_translated.
        """
        title_str = str(package_dict.get('title', '')) if package_dict.get('title') else 'No info'
        notes_str = str(package_dict.get('notes', '')) if package_dict.get('notes') else title_str

        package_dict['title_translated'] = {
            'el': title_str,
            'en': title_str
        }

        package_dict['notes_translated'] = {
            'el': notes_str,
            'en': notes_str
        }

    def _build_extras(self, dataset_data):
        """
        """
        extras = []

        # High value category (DCAT-AP σχετικό πεδίο που μπορείς να κάνεις map μετά)
        if dataset_data.get('high_value_category'):
            extras.append({
                'key': 'high_value_category',
                'value': dataset_data['high_value_category']
            })

        # Πληροφορίες χρόνου από το τρίτο σύστημα (όχι τα CKAN system fields)
        if dataset_data.get('metadata_created'):
            extras.append({
                'key': 'source_metadata_created',
                'value': dataset_data['metadata_created']
            })

        if dataset_data.get('metadata_modified'):
            extras.append({
                'key': 'source_metadata_modified',
                'value': dataset_data['metadata_modified']
            })

        # Κρατάμε και το raw organization/category σε extras για εύκολα mappings
        if dataset_data.get('organization'):
            extras.append({
                'key': 'source_organization',
                'value': dataset_data['organization']
            })

        if dataset_data.get('category'):
            extras.append({
                'key': 'source_category',
                'value': dataset_data['category']
            })

        return extras

    def _apply_dcat_fields(self, package_dict, dataset_data):
        """
        DCAT / access_rights / contact / publisher / temporal_coverage / spatial_coverage
        """
        package_dict['landing_page'] = dataset_data['url']
        package_dict['access_rights'] = 'http://publications.europa.eu/resource/authority/access-right/PUBLIC'
        package_dict['applicable_legislation'] = ['https://eur-lex.europa.eu/eli/dir/2019/1024/oj/eng']

        # Contact
        contact_info = [{
            "uri": "https://www.patt.gov.gr/",
            "name": "Περιφέρεια Αττικής",
            "email": "opendata@attica.gov.gr",
            "url": "https://www.patt.gov.gr/7_epikoinonia/epikoinonia/"
        }]
        package_dict['contact'] = contact_info

        # Publisher (από maintainer + σταθερές τιμές)
        publisher_info = [{
            "uri": "https://opendata.attica.gov.gr/content/" + dataset_data.get('organization'),
            "name": dataset_data.get('maintainer'),
            "email": dataset_data.get('maintainer_email'),
            "url": "https://www.patt.gov.gr",
            "type": "",
            "identifier": dataset_data.get('organization')
        }]
        package_dict['publisher'] = publisher_info

        # Temporal coverage από resources
        temporal = self._compute_temporal_coverage(dataset_data)
        if temporal:
            package_dict['temporal_coverage'] = [temporal]

        package_dict['spatial_coverage'] = [{
            "uri": "",
            "text": "Περιφέρεια Αττικής",
            "geom": "",
            "bbox": "{ \"type\": \"Polygon\", \"coordinates\": [[[22.90, 37.50], [22.90, 38.40], [24.40, 38.40], [24.40, 37.50], [22.90, 37.50]]] }",
            "centroid": "{\"type\": \"Point\", \"coordinates\": [23.65, 37.95]}"
        }]

        # HVD category ως URI(s) σύμφωνα με το λεξιλόγιο
        hvd_uris = self._get_hvd_category_uris(dataset_data)
        if hvd_uris:
            package_dict['hvd_category'] = hvd_uris

        package_dict['landing_page'] = dataset_data['url']

    def _attach_resources(self, package_dict, dataset_data, package_license_id):
        """
        Χτίζει τα resource dicts και τα βάζει στο package_dict['resources'].
        """
        for resource_data in dataset_data.get('resources', []):
            # Προτιμάμε download_url (πραγματικό αρχείο), ή url προεπισκόπησης αν είναι τέτοιος ο πόρος, ειδάλλως fallback σε url
            resource_url = (
                    resource_data.get('download_url')
                    or resource_data.get('redirect_url')
                    or resource_data.get('url')
            )

            if not resource_url:
                log.warning("Skipping resource without any URL")
                continue

            resource_name = (
                    resource_data.get('name')
                    or resource_data.get('filename')
                    or resource_data.get('url')
            )

            resource_format = (
                    resource_data.get('format')
                    or resource_data.get('file_type')
            )

            resource_description = (
                    resource_data.get('description')
                    or resource_data.get('name')
                    or ''
            )

            # Φροντίζουμε να είναι strings (και trimmed)
            name_str = str(resource_name or '').strip()
            desc_str = str(resource_description or '').strip()

            resource_dict = {
                'url': resource_url,
                'access_url': resource_data.get('preview_url'),
                'download_url': resource_data.get('download_url'),
                'name': resource_name,
                'format': resource_format,
                'description': resource_description,

                # Translated πεδία για fluent plugin στα resources
                'name_translated': {
                    'el': name_str,
                    'en': name_str
                },
                'description_translated': {
                    'el': desc_str,
                    'en': desc_str
                }
            }

            # Άδεια σε επίπεδο resource
            license_value = self._get_resource_license(resource_data, package_license_id)
            if license_value:
                resource_dict['license'] = license_value

            base_uri = "https://www.iana.org/assignments/media-types/"
            if resource_data.get('mimetype'):
                resource_dict['mimetype'] = base_uri + resource_data['mimetype']

            if resource_data.get('size'):
                try:
                    size_str = str(resource_data['size']).strip().lower()

                    # Αφαίρεση μονάδων και μετατροπή σε bytes
                    if 'kb' in size_str:
                        # Αφαίρεση "kb" και μετατροπή σε bytes
                        size_value = float(size_str.replace('kb', '').strip()) * 1024
                    elif 'mb' in size_str:
                        # Αφαίρεση "mb" και μετατροπή σε bytes
                        size_value = float(size_str.replace('mb', '').strip()) * 1024 * 1024
                    elif 'gb' in size_str:
                        # Αφαίρεση "gb" και μετατροπή σε bytes
                        size_value = float(size_str.replace('gb', '').strip()) * 1024 * 1024 * 1024
                    elif 'bytes' in size_str or 'byte' in size_str:
                        # Αφαίρεση "bytes"/"byte"
                        size_value = float(size_str.replace('bytes', '').replace('byte', '').strip())
                    else:
                        # Απλή μετατροπή χωρίς μονάδες
                        size_value = float(size_str)

                    # Στρογγυλοποίηση σε integer (bytes)
                    resource_dict['size'] = round(size_value)

                    # Έλεγχος για αρνητικές τιμές
                    if resource_dict['size'] < 0:
                        resource_dict.pop('size', None)

                except (ValueError, TypeError):
                    # Αν δεν μπορεί να μετατραπεί, αφαίρεσε το πεδίο
                    log.warning(f"Could not convert size '{resource_data['size']}' to integer, removing field")
                    # Δεν ορίζουμε το size αν δεν μπορεί να μετατραπεί
                    pass

            if resource_data.get('hash'):
                resource_dict['hash'] = resource_data['hash']

            if resource_data.get('created'):
                resource_dict['created'] = resource_data['created']

            resource_dict['availability'] = "http://publications.europa.eu/resource/authority/planned-availability/STABLE"

            # Αν θέλουμε να κρατήσουμε επιπλέον πληροφορίες σε extras ανά resource
            resource_extras = []

            # if resource_data.get('page_url'):
            #     resource_extras.append({
            #         'key': 'page_url',
            #         'value': resource_data['page_url']
            #     })
            #
            # if resource_data.get('redirect_url'):
            #     resource_extras.append({
            #         'key': 'redirect_url',
            #         'value': resource_data['redirect_url']
            #     })
            #
            # if resource_data.get('filename'):
            #     resource_extras.append({
            #         'key': 'filename',
            #         'value': resource_data['filename']
            #     })

            # if resource_data.get('year'):
            #     resource_extras.append({
            #         'key': 'year',
            #         'value': resource_data['year']
            #     })

            # if resource_extras:
            #     resource_dict['extras'] = resource_extras

            package_dict['resources'].append(resource_dict)

    def _attach_tags(self, package_dict, dataset_data):
        """
        Χτίζει τα tags και τα βάζει στο package_dict['tags'].
        """
        tags = []
        seen = set()

        def _add_tag(tag_value):
            """
            Helper για να μη διπλογράφουμε tags.
            Καθαρίζει επίσης μη έγκυρους χαρακτήρες από τα tags.
            Το CKAN επιτρέπει μόνο: alphanumeric, spaces, hyphens, underscores, dots.
            """
            if not tag_value:
                return

            original_name = str(tag_value).strip()

            # Βασικός έλεγχος για κενό
            if not original_name:
                return

            # Καθαρισμός μη έγκυρων χαρακτήρων
            cleaned_name = original_name

            # Αντικατάσταση προβληματικών χαρακτήρων
            cleaned_name = cleaned_name.replace('"', '')  # Αφαίρεση εισαγωγικών
            cleaned_name = cleaned_name.replace("'", '')  # Αφαίρεση μονών εισαγωγικών
            cleaned_name = cleaned_name.replace('«', '')  # Αφαίρεση ελληνικών εισαγωγικών
            cleaned_name = cleaned_name.replace('»', '')
            cleaned_name = cleaned_name.replace('(', '-')  # Παρενθέσεις -> παύλες
            cleaned_name = cleaned_name.replace(')', '-')
            cleaned_name = cleaned_name.replace('[', '-')
            cleaned_name = cleaned_name.replace(']', '-')
            cleaned_name = cleaned_name.replace('/', '-')  # Slash -> παύλα
            cleaned_name = cleaned_name.replace('\\', '-')  # Backslash -> παύλα
            cleaned_name = cleaned_name.replace('–', '-')  # Em dash -> παύλα
            cleaned_name = cleaned_name.replace('—', '-')  # En dash -> παύλα
            cleaned_name = cleaned_name.replace(',', '')  # Αφαίρεση κόμματος
            cleaned_name = cleaned_name.replace(';', '')  # Αφαίρεση ερωτηματικού
            cleaned_name = cleaned_name.replace(':', '')  # Αφαίρεση άνω κάτω τελείας

            # Διατήρηση μόνο έγκυρων χαρακτήρων: alphanumeric, spaces, hyphens, underscores, dots
            cleaned_name = ''.join(char for char in cleaned_name
                                   if char.isalnum() or char in ' -_.')

            # Καθαρισμός διπλών κενών και trim
            cleaned_name = ' '.join(cleaned_name.split())

            # Έλεγχος μήκους και έγκυρων τιμών
            if (not cleaned_name or
                    len(cleaned_name) < 2 or
                    cleaned_name in ['-', '--', '---', '.', '..', '...', '_', '__', '___']):
                log.debug(f"Removed invalid tag: '{original_name}' -> '{cleaned_name}'")
                return

            # normalized dedup (case-insensitive)
            normalized_key = cleaned_name.lower()
            normalized_key = ' '.join(normalized_key.split())  # collapse spaces

            # Έλεγχος για διπλότυπα
            if normalized_key in seen:
                return

            # Log αν έγινε αλλαγή
            if cleaned_name != original_name:
                log.debug(f"Cleaned tag: '{original_name}' -> '{cleaned_name}'")

            seen.add(cleaned_name)
            tags.append({'name': cleaned_name})

        # 1. Tags που έρχονται έτοιμα από το τρίτο σύστημα
        for t in dataset_data.get('tags', []):
            _add_tag(t)

        # 2. Οργάνωση / κατηγορία / high value category ως tags (πιο "ανθρώπινα")
        if dataset_data.get('organization'):
            org_tag = dataset_data['organization'].replace('-', ' ')
            # _add_tag(org_tag)

        if dataset_data.get('category'):
            cat_tag = dataset_data['category'].replace('-', ' ')
            # _add_tag(cat_tag)

        if dataset_data.get('high_value_category'):
            _add_tag(dataset_data['high_value_category'])

        # 3. Generic tags
        _add_tag('Περιφέρεια Αττικής')
        _add_tag('Ανοιχτά Δεδομένα')

        if tags:
            package_dict['tags'] = tags

    # ######################################################################################

    def _get_resource_license(self, resource_data, package_license_id=None):
        """
        Επιστρέφει την τιμή για το πεδίο 'license' του resource ως URI.

        Λογική:
        - Πρώτα κοιτάμε αν υπάρχει κάποιο λεκτικό άδειας στο resource (license / license_title / license_text)
        - Αν όχι, χρησιμοποιούμε το package_license_id (που είναι επίσης λεκτικό τύπου 'BY, SA', 'ΒΥ' κτλ.)
        - Αν βρούμε λεκτικό 'BY, SA' ή 'BY-SA' -> URI CC_BYSA_1_0
        - Αν βρούμε λεκτικό 'ΒΥ' -> URI CC_BY_1_0
        - Αν δεν ταιριάξει κανόνας -> επιστρέφουμε None (δεν γράφουμε καθόλου license στο resource_dict)
        """

        # Πιθανές πηγές λεκτικού άδειας σε επίπεδο resource
        license_text = (
            resource_data.get('license')
            or resource_data.get('license_title')
            or resource_data.get('license_text')
            or package_license_id
            or ''
        )

        if not license_text:
            return None

        # Κανονικοποίηση κειμένου για συγκρίσεις
        norm = str(license_text).upper().strip()
        # Βγάζουμε κενά για να πιάνουμε παραλλαγές τύπου "BY , SA"
        norm_no_space = ''.join(norm.split())

        # ------------------------------
        # Κανόνες mapping σε CC BY-SA 1.0 URI
        # ------------------------------
        # Παραλλαγές με κόμμα/παύλα κτλ.
        if (
            'BY,SA' in norm_no_space
            or 'BY-SA' in norm_no_space
            or 'BY,SA' in norm_no_space
            or 'BY-SA' in norm_no_space
        ):
            return "http://publications.europa.eu/resource/authority/licence/CC_BYSA_1_0"

        if (
            norm == 'BY'
        ):
            return "http://publications.europa.eu/resource/authority/licence/CC_BY_1_0"

        # Αν δεν βρέθηκε κάποιος γνωστός συνδυασμός, δεν βάζουμε άδεια στο resource
        return None

    def _get_hvd_category_uris(self, dataset_data):
        """
        Επιστρέφει λίστα με URIs high-value dataset categories (HVD)
        με βάση το λεκτικό που έχουμε στο dataset_data['high_value_category'].

        Αν δεν αναγνωρίσει την τιμή -> επιστρέφει [].
        Αν ήδη είναι URI -> το επιστρέφει όπως είναι.
        """

        label = dataset_data.get('high_value_category')
        if not label:
            return []

        value = str(label).strip()

        # Αν ήδη είναι URI του λεξιλογίου, το κρατάμε όπως είναι
        if value.startswith("http://data.europa.eu/bna/"):
            return [value]

        norm = value.lower()

        # Mapping λεκτικών -> URI (εύκολα επεκτάσιμο)
        hvd_map = {
            # Γεωχωρικά / Geospatial
            'γεωχωρικά': 'http://data.europa.eu/bna/c_ac64a52d',
            'γεωχωρικές πληροφορίες': 'http://data.europa.eu/bna/c_ac64a52d',
            'geospatial': 'http://data.europa.eu/bna/c_ac64a52d',

            # Στατιστικά / Statistics
            'στατιστικά': 'http://data.europa.eu/bna/c_e1da4e07',
            'στατιστικές': 'http://data.europa.eu/bna/c_e1da4e07',
            'statistics': 'http://data.europa.eu/bna/c_e1da4e07',

            # εδώ μπορούνε να προστεθούν κι άλλες τιμές από τον πίνακα:
            # 'μετεωρολογικά': 'http://data.europa.eu/bna/c_164e0bf5',
            # 'εταιρείες και ιδιοκτησία εταιρειών': 'http://data.europa.eu/bna/c_a9135398',
            # 'κινητικότητα': 'http://data.europa.eu/bna/c_b79e35eb',
            # κ.λπ.
        }

        uri = hvd_map.get(norm)
        if not uri:
            return []

        return [uri]

    def _compute_temporal_coverage(self, dataset_data):
        """
        Compute temporal coverage from resource 'year' fields.
        Επιστρέφει dict:
            { "start": "YYYY-01-01", "end": "YYYY-12-31" }
        ή None αν δεν υπάρχουν έτη.
        """
        years = []

        for res in dataset_data.get("resources", []):
            year = res.get("year")
            if not year:
                continue

            # Attempt to parse numbers safely
            try:
                y = int(str(year).strip())
                years.append(y)
            except:
                continue

        if not years:
            return None

        start_year = min(years)
        end_year = max(years)

        return {
            "start": f"{start_year}-01-01",
            "end": f"{end_year}-12-31"
        }

    # ##################################################################################################################

    def _generate_dataset_name(self, dataset_url):
        """
        Generate a unique dataset name from URL
        """
        parsed_url = urlparse(dataset_url)
        path_parts = [p for p in parsed_url.path.split('/') if p and p != 'content']

        # Use the last part of the path as base name
        if path_parts:
            base_name = path_parts[-1]
        else:
            base_name = 'attica-dataset'

        # Clean and ensure it's a valid CKAN name
        name = re.sub(r'[^a-z0-9-_]', '-', base_name.lower())
        name = re.sub(r'-+', '-', name)  # Replace multiple dashes with single
        name = name.strip('-')  # Remove leading/trailing dashes

        # Ensure it starts with letter or number
        if name and not name[0].isalnum():
            name = 'attica-' + name

        # Add prefix to avoid conflicts
        return f"attica-{name}"

    # ##################################################################################################################

    def _get_source_config(self, source_config):
        """
        Parse source configuration
        """
        import json

        if source_config:
            try:
                return json.loads(source_config)
            except (ValueError, TypeError):
                log.error(f"Invalid source config: {source_config}")
                return {}
        return {}