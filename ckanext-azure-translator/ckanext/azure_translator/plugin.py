from urllib.parse import urlsplit

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import requests


REQUEST_TIMEOUT = (5, 30)


def _validated_https_endpoint(endpoint):
    """Return a normalized Translator endpoint, rejecting insecure URLs."""
    if not endpoint or not isinstance(endpoint, str):
        raise ValueError("Azure Translator endpoint is not configured.")

    endpoint = endpoint.strip().rstrip("/")
    parsed = urlsplit(endpoint)

    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Azure Translator endpoint must be a valid HTTPS URL without "
            "credentials, query parameters, or a fragment."
        )

    return endpoint


class AzureTranslatorPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IActions)
    

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_public_directory(config_, "public")
        toolkit.add_resource("assets", "azure_translator")


    # # IActions
    def get_actions(self):
        return {
            'azure_translate': self.azure_translate_action
        }

    @staticmethod
    def azure_translate_action(context, data_dict):
        package_id = data_dict['id']

        toolkit.check_access('package_update', context, {'id':package_id})

        text = data_dict["text"]

        if not text:
            raise toolkit.ValidationError({'text': ['Text is required.']})

        try:
            result = AzureTranslatorPlugin.azure_translate(text)
            return result
        except Exception as e:
            raise toolkit.ValidationError({'error': str(e)})


    ''' Κλήση στο azure για μετάφραση του κειμένου '''
    @staticmethod
    def azure_translate(text, to_lang='en'):

        if not text:
            raise ValueError('Missing required parameter: text')

        try:
            # Get values from config
            subscription_key = toolkit.config.get('azure.translate.subscription_key')
            endpoint = _validated_https_endpoint(
                toolkit.config.get('azure.translate.endpoint')
            )
            region = toolkit.config.get('azure.translate.region')

            path = '/translate'
            constructed_url = f"{endpoint}{path}?api-version=3.0&to={to_lang}"

            headers = {
                'Ocp-Apim-Subscription-Key': subscription_key,
                'Ocp-Apim-Subscription-Region': region,
                'Content-type': 'application/json'
            }

            body = [{'Text': text}]
            response = requests.post(
                constructed_url,
                headers=headers,
                json=body,
                timeout=REQUEST_TIMEOUT,
                verify=True,
            )
            response.raise_for_status()

            result = response.json()
            return result

        except requests.exceptions.Timeout as e:
            raise RuntimeError(f'Microsoft Translator API request timed out: {str(e)}')
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f'Error communicating with Microsoft Translator API: {str(e)}')
        except Exception as e:
            raise RuntimeError(f'Unexpected error during translation: {str(e)}')



    
